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

# Both columns obey the same edition-scoped invariant, so they share this whole
# implementation: a rider carries one number and rides for one team from the
# grand départ to Paris. team_id's gaps have a different origin from bib's —
# the GC sidecar supplies riders for stages PCS does not list them on, and
# inserts a classification position with no team (Indurain is absent from the
# 1994 stage 3 file entirely) — but the repair is identical.
FIELDS = {"bib_number": "bib", "team_id": "team"}


def violations(cur, col="bib_number"):
    """Riders holding more than one value inside one edition — the invariant."""
    return cur.execute(f"""
        SELECT st.edition_id, e.year, r.name AS race, sr.rider_id,
               COUNT(DISTINCT sr.{col}) n
          FROM stage_results sr
          JOIN stages st ON st.stage_id = sr.stage_id
          JOIN race_editions e ON e.edition_id = st.edition_id
          JOIN races r ON r.race_id = e.race_id
         WHERE sr.{col} IS NOT NULL AND r.race_type = 'stage_race'
         GROUP BY st.edition_id, sr.rider_id
        HAVING n > 1""").fetchall()


def fillable(cur, race=None, skip_editions=(), col="bib_number"):
    """[(result_id, stage_id, rider_id, bib, race, year, route_type)] to write.

    `known` collapses each (edition, rider) to their single bib. MIN() is not
    picking a winner among several — the guard has already established there is
    only ever one for every edition this writes to — it is just how SQLite
    returns the value of a group.

    `skip_editions` are the editions where that is not true. They are excluded
    here rather than aborting the run: a rider carrying two numbers in the 1931
    Tour makes 1931 unfillable and says nothing whatever about 1985. The guard
    used to be global, so those six rider-editions blocked the tool for every
    race and every year — including the 7,647 TTT bibs that a re-ingest of
    1960-2025 has to put back.
    """
    where = "AND r.name = ?" if race else ""
    args = (RACE_NAME[race],) if race else ()
    if skip_editions:
        where += " AND e.edition_id NOT IN (%s)" % ",".join("?" * len(skip_editions))
        args = args + tuple(skip_editions)
    return cur.execute(f"""
        WITH known AS (
            SELECT st.edition_id, sr.rider_id, MIN(sr.{col}) AS val
              FROM stage_results sr
              JOIN stages st ON st.stage_id = sr.stage_id
             WHERE sr.{col} IS NOT NULL
             GROUP BY st.edition_id, sr.rider_id)
        SELECT sr.result_id, sr.stage_id, sr.rider_id, k.val,
               r.name AS race, e.year, s.route_type
          FROM stage_results sr
          JOIN stages s ON s.stage_id = sr.stage_id
          JOIN race_editions e ON e.edition_id = s.edition_id
          JOIN races r ON r.race_id = e.race_id
          JOIN known k ON k.edition_id = e.edition_id AND k.rider_id = sr.rider_id
         WHERE sr.{col} IS NULL AND r.race_type = 'stage_race' {where}
    """, args).fetchall()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=list(STAGE_RACES))
    ap.add_argument("--field", choices=list(FIELDS), default="bib_number",
                    help="bib_number (default) or team_id — the same invariant, "
                         "a rider carries one of each for a whole edition")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    col = args.field
    noun = FIELDS[col]
    bad = violations(cur, col)
    skip = sorted({b["edition_id"] for b in bad})
    if bad:
        print(f"SKIPPING {len(skip)} edition(s): {len(bad)} rider-edition(s) hold "
              f"more than one {noun}, so 'the rider's {noun} elsewhere' is not a single "
              "value there. Nothing is written to these; every other edition is "
              "unaffected.")
        for b in bad[:10]:
            print(f"    {b['race']} {b['year']} {b['rider_id']} ({b['n']} {noun}s)")
        if len(bad) > 10:
            print(f"    ... and {len(bad) - 10} more")
        print("  Run fix_name_swaps.py --from-db --dry-run; these are usually "
              "adjacent-row name swaps. Some are upstream PCS collisions that "
              "must NOT be renamed — see ai-context.md.")

    rows = fillable(cur, args.race, skip, col)
    by_race = Counter(r["race"] for r in rows)
    ttt = sum(1 for r in rows if r["route_type"] == "TTT")
    print(f"{'[DRY RUN] ' if not args.apply else ''}{len(rows):,} {noun}(s) fillable "
          f"({ttt:,} on TTT stages)")
    for name, n in sorted(by_race.items()):
        t = sum(1 for r in rows if r["race"] == name and r["route_type"] == "TTT")
        print(f"  {name:<18} {n:>6,}  ({t:,} TTT)")

    still = cur.execute("""
        SELECT COUNT(*) FROM stage_results sr
          JOIN stages s ON s.stage_id = sr.stage_id
          JOIN race_editions e ON e.edition_id = s.edition_id
          JOIN races r ON r.race_id = e.race_id
         WHERE sr.{col} IS NULL AND r.race_type = 'stage_race'""".format(col=col)).fetchone()[0]
    print(f"  ({still - len(rows):,} will stay NULL — the rider appears on no "
          f"stage of that edition carrying a {noun})")

    if not args.apply:
        conn.close()
        return 0

    # One provenance row per STAGE, not per rider: the whole fill for a stage
    # shares one origin, and per-rider rows would add ~13,000 copies of one fact.
    stages = set()
    for r in rows:
        cur.execute(f"UPDATE stage_results SET {col}=? WHERE result_id=?",
                    (r["val"], r["result_id"]))
        stages.add(r["stage_id"])
    for stage_id in stages:
        record_provenance(cur, "stages", stage_id, col, SOURCE_DERIVED,
                          source_ref=f"the rider's own {noun} on another stage of "
                                     "the same edition; a rider carries one number "
                                     "and rides for one team for the whole race",
                          script="backfill_bib_numbers.py")
    conn.commit()
    print(f"\nfilled {len(rows):,} {noun}(s) across {len(stages):,} stage(s)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
