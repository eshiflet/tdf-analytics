#!/usr/bin/env python3
"""
Backfill stages.source_slug for editions ingested before the column existed.

source_slug is the PCS URL slug a stage's data came from ('stage-3',
'stage-3a', 'prologue').

Editions with no repeated stage_date get the trivial stage-{n} mapping, which
is unambiguous and is all this script now does.

DO NOT use this to derive slugs for an edition WITH a split day. It used to,
assuming PCS always letters the two halves ('stage-3a'/'stage-3b') so the DB
number runs one ahead from the split on. PCS is inconsistent per edition:

    Vuelta 1989  stage-3a + stage-3b            -> lettered, offset applies
    TDF 1974     stage-8a, no stage-8           -> lettered
    TDF 1986     stage-1 + stage-2, no stage-1a -> sequential, NO offset
    TDF 1970/91  sequential
    Giro 1953    sequential

Guessing produced wrong slugs for every stage after a split in the sequential
editions (632 TDF stages). resolve_source_slugs.py probes PCS for the real
convention per edition and verifies each slug by matching departure/arrival,
so split editions are left to it.

Only fills rows where source_slug IS NULL; never overwrites a slug recorded at
scrape time. Skips (and reports) any edition with missing dates, since the
split detection is unreliable there.

Usage:
  python3 backfill_source_slugs.py --dry-run
  python3 backfill_source_slugs.py
  python3 backfill_source_slugs.py --race "Vuelta a España"
"""

import argparse
import os
import sqlite3
import sys

from race_common import SOURCE_DERIVED, record_provenance

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")

RACES = ["Tour de France", "Giro d'Italia", "Vuelta a España"]


def slugs_for_edition(stages: list[sqlite3.Row]) -> tuple[dict[int, str], int]:
    """Map stage_number -> PCS slug for one edition. Returns (mapping, n_splits).

    stage_number 0 is a prologue, which PCS slugs 'prologue', not 'stage-0'.
    It doesn't consume a numbered slot, so stage 1 is still 'stage-1'.
    """
    mapping = {}
    offset = 0          # how far the DB number has run ahead of the PCS number
    prev_date = None
    letter_pos = 0      # 0 => 'a' for the stage currently opening a split day
    splits = 0

    for s in stages:
        n = s["stage_number"]
        date = s["stage_date"]

        if n == 0:
            mapping[n] = "prologue"
            prev_date = date
            continue

        if prev_date is not None and date == prev_date:
            # A split day. Whether PCS letters it ('stage-3a'/'stage-3b', so the
            # DB number runs ahead from here) or just numbers it sequentially
            # varies per edition and cannot be inferred from the data — see the
            # module docstring. Refuse to guess; resolve_source_slugs.py probes.
            splits += 1
        mapping[n] = f"stage-{n}"
        prev_date = date

    if splits:
        return {}, splits            # caller must skip: undecidable without probing
    return mapping, splits


def backfill_edition_slugs(cur, edition_id: int) -> int:
    """Fill NULL source_slug for one edition, in place. Returns rows filled.

    Called by ingest_race.py after inserting an edition, so re-ingesting a year
    whose stage files predate slug recording doesn't undo the backfill. Refuses
    to guess when any stage_date is missing — split days are undetectable then,
    and a wrong slug is worse than a missing one.
    """
    stages = cur.execute(
        "SELECT stage_number, stage_date, source_slug FROM stages "
        "WHERE edition_id=? ORDER BY stage_number",
        (edition_id,),
    ).fetchall()
    if not stages or any(not s["stage_date"] for s in stages):
        return 0

    mapping, splits = slugs_for_edition(stages)
    if splits:
        return 0                     # undecidable here; resolve_source_slugs.py owns it
    filled = 0
    for s in stages:
        if s["source_slug"]:
            continue
        cur.execute(
            "UPDATE stages SET source_slug=? WHERE edition_id=? AND stage_number=?",
            (mapping[s["stage_number"]], edition_id, s["stage_number"]),
        )
        # 'derived', not 'pcs': this slug was inferred from stage dates, not
        # read off a page. It's well-tested but it IS an inference, and an
        # audit should be able to tell the two apart.
        row = cur.execute(
            "SELECT stage_id FROM stages WHERE edition_id=? AND stage_number=?",
            (edition_id, s["stage_number"]),
        ).fetchone()
        if row:
            record_provenance(cur, "stages", row[0], "source_slug",
                              SOURCE_DERIVED,
                              source_ref="inferred from stage_date split detection")
        filled += 1
    return filled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--race", default=None, help="limit to one race name")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c1, c2 = conn.cursor(), conn.cursor()

    races = [args.race] if args.race else RACES
    total_set = total_skipped = 0
    split_editions = []

    for race in races:
        row = c1.execute("SELECT race_id FROM races WHERE name=?", (race,)).fetchone()
        if not row:
            print(f"{race}: not in DB, skipping")
            continue

        editions = c1.execute(
            "SELECT edition_id, year FROM race_editions WHERE race_id=? ORDER BY year",
            (row["race_id"],),
        ).fetchall()

        race_set = 0
        for e in editions:
            stages = c2.execute(
                "SELECT stage_number, stage_date, source_slug FROM stages "
                "WHERE edition_id=? ORDER BY stage_number",
                (e["edition_id"],),
            ).fetchall()
            if not stages:
                continue

            if any(not s["stage_date"] for s in stages):
                print(f"  SKIP {race} {e['year']}: missing stage_date, "
                      "split detection unreliable — set source_slug manually")
                total_skipped += len(stages)
                continue

            mapping, splits = slugs_for_edition(stages)
            if splits:
                split_editions.append((race, e["year"], splits))
                print(f"  SKIP {race} {e['year']}: {splits} split day(s) — slug "
                      "convention must be probed; run resolve_source_slugs.py")
                continue

            for s in stages:
                if s["source_slug"]:
                    continue
                slug = mapping[s["stage_number"]]
                if not args.dry_run:
                    c2.execute(
                        "UPDATE stages SET source_slug=? WHERE edition_id=? AND stage_number=?",
                        (slug, e["edition_id"], s["stage_number"]),
                    )
                race_set += 1

        print(f"{race}: {race_set} stages {'would be' if args.dry_run else ''} filled")
        total_set += race_set

    if not args.dry_run:
        conn.commit()

    print(f"\nSplit editions detected ({len(split_editions)}):")
    for race, year, n in split_editions:
        print(f"  {race[:6]} {year}: {n} split-day continuation(s)")

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}"
          f"{total_set} stages filled, {total_skipped} skipped")
    conn.close()


if __name__ == "__main__":
    main()
