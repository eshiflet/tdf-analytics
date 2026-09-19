#!/usr/bin/env python3
"""
Apply the stage-1 GC rule to an edition a re-ingest cannot reach.

OFFLINE. Reads the stage files already on disk and fetches nothing.

WHY THIS EXISTS. ingest_race stopped giving a stage-1 rider his STAGE placing
as a GC position wherever the stage has a real source, and 212 editions were
re-ingested on 2026-09-19 to apply it. Five refused, each holding a stage that
is in the database with no scrape file, and the orphan guard is RIGHT to refuse
them:

  * Vuelta 1941, 1942 and 1968 number their stages by expanding PCS's split
    days -- stage-8a and stage-8b become our 8 and 9 -- while the scrape files
    are named for PCS's numbering. Vuelta 1942 has 20 stages and 17 files, and
    `stage_15.json` (14 July) is our stage 18. Re-ingesting would rebuild the
    edition as 17 stages and destroy both the split-day structure and 62 result
    rows.
  * Tour 1978 stage 13 is the Valence d'Agen strike stage, held as `stage-12a`
    with 99 rows and no file of its own.
  * Tour 1982 stage 5 is cancelled, holds no results and has no file to hold.

So `--allow-drop` is not an option here -- it is exactly the flag that cost the
1982 Tour 145 placings once. This writes the same outcome the ingest would, to
stage 1 only, and touches nothing else in the edition.

THE RULE, identical to ingest_race's:

  A stage-1 rider PCS left out of the classification gets a GC position from
  gc_standings if it has one for him, and otherwise NOTHING -- never his
  finishing place, which would collide with the positions PCS did publish.
  Where the stage has NO source at all the approximation stands, because
  nothing can contradict it.

Verified by round trip: restoring the 1996 Vuelta's stage 1 to its pre-fix
state and running this reproduces what the re-ingest produced, row for row.

Usage:
  python3 fix_stage1_gc.py --race vuelta --year 1942
  python3 fix_stage1_gc.py --refused            # the five, dry run
  python3 fix_stage1_gc.py --refused --apply
"""

import argparse
import json
import os
import sqlite3

import gc_source
from race_common import DB_PATH, exit_on_help, record_provenance, parse_time_to_seconds

RACE_ALIASES = {"tour": "Tour de France", "tdf": "Tour de France",
                "giro": "Giro d'Italia", "vuelta": "Vuelta a España"}

# The five a re-ingest cannot reach — see the module docstring.
REFUSED = [("Tour de France", 1978), ("Tour de France", 1982),
           ("Vuelta a España", 1941), ("Vuelta a España", 1942),
           ("Vuelta a España", 1968)]

GC_POS, GC_LAG, RIDER = 1, 2, 6


def published_gc(race, year):
    """{rider_id: (rank, gap)} PCS prints inline on this edition's stage 1."""
    directory = gc_source.SCRAPE_DIR.get(race)
    path = os.path.join(gc_source.HERE, directory, str(year), "stage_1.json")
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f).get("rows") or []
    except (ValueError, OSError):
        return None
    out = {}
    for r in rows:
        if len(r) > GC_LAG and str(r[GC_POS]).strip():
            out[r[RIDER]] = (int(r[GC_POS]), parse_time_to_seconds(r[GC_LAG]))
    return out


def standings_gc(race, year):
    """{rider_id: (rank, gap)} from gc_standings.json — EVERY entry it holds.

    Unranked entries are kept deliberately, and matching the ingest is the
    whole reason. It reads `if entry:` and takes both fields, so a rider PCS
    never placed but for whom the classification page has a gap keeps that gap
    with a NULL rank. Filtering those out here disagreed with a re-ingest on
    100 of the 1996 Vuelta's 180 stage-1 rows, which is how the difference was
    found: the gap is real data from the classification even where the position
    is not.
    """
    directory = gc_source.SCRAPE_DIR.get(race)
    path = os.path.join(gc_source.HERE, directory, str(year), "gc_standings.json")
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f).get("stages", {}).get("1") or {}
    except (ValueError, OSError):
        return {}
    return {k: (v[0], v[1]) for k, v in entries.items() if v}


def plan(conn, race, year):
    """[(result_id, rider, old, new, why)] for this edition's stage 1."""
    row = conn.execute(
        """SELECT s.stage_id FROM stages s
             JOIN race_editions re ON re.edition_id = s.edition_id
             JOIN races ra ON ra.race_id = re.race_id
            WHERE ra.name = ? AND re.year = ? AND s.stage_number = 1""",
        (race, year)).fetchone()
    if not row:
        return None, []
    stage_id = row[0]
    inline = published_gc(race, year)
    if inline is None:
        return stage_id, []
    standings = standings_gc(race, year)
    if not inline and not standings:
        # No source at all: the approximation stands, nothing can contradict it.
        return stage_id, []

    changes = []
    for result_id, rider, rank, gap in conn.execute(
            "SELECT result_id, rider_id, gc_rank, gc_gap_seconds FROM stage_results "
            "WHERE stage_id = ?", (stage_id,)):
        if rider in inline:
            new, why = inline[rider], "PCS publishes it"
        elif rider in standings:
            new, why = standings[rider], "gc_standings has it"
        else:
            new, why = (None, None), "no source — was the finishing place"
        if (rank, gap) != new:
            changes.append((result_id, rider, (rank, gap), new, why))
    return stage_id, changes


def main():
    exit_on_help(__doc__)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--race", help="tour | giro | vuelta")
    ap.add_argument("--year", type=int)
    ap.add_argument("--refused", action="store_true",
                    help="the five editions a re-ingest cannot reach")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args()

    if args.refused:
        targets = REFUSED
    elif args.race and args.year:
        targets = [(RACE_ALIASES.get(args.race.lower(), args.race), args.year)]
    else:
        ap.error("give --race and --year, or --refused")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total = 0
    for race, year in targets:
        stage_id, changes = plan(conn, race, year)
        if stage_id is None:
            print(f"{race} {year}: no stage 1 in the database")
            continue
        kinds = {}
        for _rid, _r, _old, _new, why in changes:
            kinds[why] = kinds.get(why, 0) + 1
        print(f"{race} {year} stage 1: {len(changes)} row(s) change  "
              + (", ".join(f"{v} {k}" for k, v in sorted(kinds.items())) or "nothing to do"))
        total += len(changes)
        if not args.apply:
            continue
        for result_id, _rider, _old, (rank, gap), _why in changes:
            cur.execute("UPDATE stage_results SET gc_rank = ?, gc_gap_seconds = ? "
                        "WHERE result_id = ?", (rank, gap, result_id))
        record_provenance(cur, "stages", stage_id, "results", "pcs",
                          source_ref="stage-1 GC re-derived without the "
                                     "finishing-order fallback",
                          script="fix_stage1_gc.py")
        conn.commit()

    print(f"\n{total} row(s) {'updated' if args.apply else 'would change'}.")
    if not args.apply:
        print("Dry run. Nothing written. Re-run with --apply.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
