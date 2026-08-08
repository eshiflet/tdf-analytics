#!/usr/bin/env python3
"""
Backfill stages.source_slug for editions ingested before the column existed.

source_slug is the PCS URL slug a stage's data came from ('stage-3',
'stage-3a'). It can't be reconstructed as f"stage-{stage_number}": on a split
day PCS races two stages under one number ('stage-3a'/'stage-3b') while the DB
spends two contiguous integers on them, so from the first split onward the DB
number runs *ahead* of the PCS number for the rest of that edition.

Split days are recoverable from the data itself — two stages sharing a
stage_date is exactly what a split day is. This walks each edition in stage
order, tracks the running offset, and emits:

    DB 1,2 (distinct dates)        -> stage-1, stage-2
    DB 3,4 (same date)             -> stage-3a, stage-3b
    DB 5   (next date)             -> stage-4        <- offset now 1

Editions with no repeated date get the trivial stage-{n} mapping.

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
            # Continuation of a split day: same PCS number, next letter.
            splits += 1
            offset += 1
            letter_pos += 1
            pcs_num = n - offset
            mapping[n] = f"stage-{pcs_num}{'abcd'[letter_pos]}"
            # Retroactively letter the day's first stage, which we emitted bare.
            first_n = n - letter_pos
            mapping[first_n] = f"stage-{pcs_num}a"
        else:
            letter_pos = 0
            mapping[n] = f"stage-{n - offset}"

        prev_date = date

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

    mapping, _ = slugs_for_edition(stages)
    filled = 0
    for s in stages:
        if s["source_slug"]:
            continue
        cur.execute(
            "UPDATE stages SET source_slug=? WHERE edition_id=? AND stage_number=?",
            (mapping[s["stage_number"]], edition_id, s["stage_number"]),
        )
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
