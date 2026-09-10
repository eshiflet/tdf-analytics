#!/usr/bin/env python3
"""
Fill NULL stage_results.bib_number from the rider's own bib elsewhere in the
same edition.

WHY THERE ARE GAPS. Overwhelmingly the team time trial. PCS renders a TTT as
team blocks with the per-rider cells empty — the same shape that makes
race_common.parse_ttt_rows necessary — so no bib reaches the parser at all:
12,758 TTT result rows carry none, every Giro and Vuelta TTT row among them.
Re-scraping cannot help; the cells are empty at the source.

WHY THIS IS NOT A GUESS. In a stage race a rider carries one number for the
whole race, so their bib on any other stage of that edition IS their bib on the
TTT. That invariant is now exact: the 27 adjacent-row name swaps that used to
break it were repaired on 2026-09-09, and the database holds zero riders with
two bibs in one edition. The guard below re-checks it and refuses to write
anything if it has stopped being true, because a wrong bib is worse than a
missing one — bib is what detect_name_swaps keys its identity check on, so a
fabricated one would blind the very check that protects this invariant.

WHAT IT WILL NOT DO. Overwrite a stored bib, or invent one for a rider who
appears on no bibbed stage in that edition. Those stay NULL: pre-war Tours
record bibs for 4-20% of riders, and there is nothing to read across from.
Roughly 13,300 of 40,000 gaps are fillable; the rest are an honest absence.

Usage:
  python3 backfill_bib_numbers.py --dry-run
  python3 backfill_bib_numbers.py --race tour --dry-run
  python3 backfill_bib_numbers.py --apply
"""

import argparse
import sqlite3
import sys
from collections import Counter

from race_common import (
    DB_PATH,
    SOURCE_DERIVED,
    STAGE_RACES,
    record_provenance,
)

RACE_NAME = {"tour": "Tour de France", "giro": "Giro d'Italia",
             "vuelta": "Vuelta a España"}


def violations(cur):
    """Riders holding more than one bib inside one edition — the invariant."""
    return cur.execute("""
        SELECT e.year, r.name AS race, sr.rider_id, COUNT(DISTINCT sr.bib_number) n
          FROM stage_results sr
          JOIN stages st ON st.stage_id = sr.stage_id
          JOIN race_editions e ON e.edition_id = st.edition_id
          JOIN races r ON r.race_id = e.race_id
         WHERE sr.bib_number IS NOT NULL AND r.race_type = 'stage_race'
         GROUP BY st.edition_id, sr.rider_id
        HAVING n > 1""").fetchall()


def fillable(cur, race=None):
    """[(result_id, stage_id, rider_id, bib, race, year, route_type)] to write.

    `known` collapses each (edition, rider) to their single bib. MIN() is not
    picking a winner among several — the guard has already established there is
    only ever one — it is just how SQLite returns the value of a group.
    """
    where = "AND r.name = ?" if race else ""
    args = (RACE_NAME[race],) if race else ()
    return cur.execute(f"""
        WITH known AS (
            SELECT st.edition_id, sr.rider_id, MIN(sr.bib_number) AS bib
              FROM stage_results sr
              JOIN stages st ON st.stage_id = sr.stage_id
             WHERE sr.bib_number IS NOT NULL
             GROUP BY st.edition_id, sr.rider_id)
        SELECT sr.result_id, sr.stage_id, sr.rider_id, k.bib,
               r.name AS race, e.year, s.route_type
          FROM stage_results sr
          JOIN stages s ON s.stage_id = sr.stage_id
          JOIN race_editions e ON e.edition_id = s.edition_id
          JOIN races r ON r.race_id = e.race_id
          JOIN known k ON k.edition_id = e.edition_id AND k.rider_id = sr.rider_id
         WHERE sr.bib_number IS NULL AND r.race_type = 'stage_race' {where}
    """, args).fetchall()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=list(STAGE_RACES))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    bad = violations(cur)
    if bad:
        print(f"REFUSING: {len(bad)} rider-edition(s) hold more than one bib, so "
              "'the rider's bib elsewhere' is not a single value:")
        for b in bad[:10]:
            print(f"    {b['race']} {b['year']} {b['rider_id']} ({b['n']} bibs)")
        print("  Run fix_name_swaps.py --from-db --dry-run; these are usually "
              "adjacent-row name swaps.")
        conn.close()
        return 1

    rows = fillable(cur, args.race)
    by_race = Counter(r["race"] for r in rows)
    ttt = sum(1 for r in rows if r["route_type"] == "TTT")
    print(f"{'[DRY RUN] ' if not args.apply else ''}{len(rows):,} bib(s) fillable "
          f"({ttt:,} on TTT stages)")
    for name, n in sorted(by_race.items()):
        t = sum(1 for r in rows if r["race"] == name and r["route_type"] == "TTT")
        print(f"  {name:<18} {n:>6,}  ({t:,} TTT)")

    still = cur.execute("""
        SELECT COUNT(*) FROM stage_results sr
          JOIN stages s ON s.stage_id = sr.stage_id
          JOIN race_editions e ON e.edition_id = s.edition_id
          JOIN races r ON r.race_id = e.race_id
         WHERE sr.bib_number IS NULL AND r.race_type = 'stage_race'""").fetchone()[0]
    print(f"  ({still - len(rows):,} will stay NULL — the rider appears on no "
          "bibbed stage in that edition)")

    if not args.apply:
        conn.close()
        return 0

    # One provenance row per STAGE, not per rider: the whole fill for a stage
    # shares one origin, and per-rider rows would add ~13,000 copies of one fact.
    stages = set()
    for r in rows:
        cur.execute("UPDATE stage_results SET bib_number=? WHERE result_id=?",
                    (r["bib"], r["result_id"]))
        stages.add(r["stage_id"])
    for stage_id in stages:
        record_provenance(cur, "stages", stage_id, "bib_number", SOURCE_DERIVED,
                          source_ref="the rider's own bib on another stage of "
                                     "the same edition; a stage race issues one "
                                     "number per rider for the whole race",
                          script="backfill_bib_numbers.py")
    conn.commit()
    print(f"\nfilled {len(rows):,} bib(s) across {len(stages):,} stage(s)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
