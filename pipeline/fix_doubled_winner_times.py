#!/usr/bin/env python3
"""
Repair stage winners whose finish_time_seconds is double the real time.

PCS renders the results table's time cell as the displayed time followed
immediately by a hidden gap — "4:15:284:15:28" for the winner. The parser reads
both fields from that one cell, so the winner's row arrives with abs_time AND
gap set to the same value, and ingest's `finish = winner_seconds + gap` doubled
it. 3,377 rows across 3,354 stages, more than half the database.

Nothing noticed because every OTHER rider on those stages is correct — their
gap is a real gap — and export_gc only uses finish_time_seconds as a last-
resort fallback for a rider's total. The stage winner is simply recorded as
having taken twice as long as the field.

No re-scraping is needed. The stored gap on those rows IS the winner's own
time, so the true finish is exactly that value and the true gap is zero:

    finish = winner + gap,  gap == winner   =>   finish == 2 * gap

Only rows matching that identity exactly are touched. That is the point of the
test rather than "rank 1 with a gap": a promoted co-winner after a
disqualification is also rank 1 with a genuine non-zero gap — 2008 TDF stage 4
lists Kirchen at 18 seconds behind Schumacher, finish 2162 against gap 18 — and
must be left alone. It is the single row in the database with a rank-1 gap that
is not this bug.

The code path is fixed in ingest_race.py and reingest_tdf_stage.py, so a
re-ingest will not reintroduce it.

Usage:
  python3 fix_doubled_winner_times.py --dry-run
  python3 fix_doubled_winner_times.py --apply
"""

import argparse
import sqlite3
import sys

from race_common import DB_PATH, SOURCE_DERIVED, record_provenance

SELECT = """
    SELECT sr.result_id, sr.stage_id, sr.rider_id, sr.finish_time_seconds f,
           sr.gap_seconds g, ra.name race, re.year, s.stage_number n
      FROM stage_results sr
      JOIN stages s USING(stage_id)
      JOIN race_editions re USING(edition_id)
      JOIN races ra USING(race_id)
     WHERE sr.stage_rank = 1
       AND sr.finish_time_seconds IS NOT NULL
       AND sr.gap_seconds > 0
       AND sr.finish_time_seconds = 2 * sr.gap_seconds
     ORDER BY ra.name, re.year, s.stage_number"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=10,
                    help="how many examples to print")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro" if args.dry_run else DB_PATH,
                           uri=args.dry_run)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(SELECT).fetchall()

    print(f"{len(rows)} winner row(s) with finish == 2 x gap\n")
    for r in rows[:args.limit]:
        print(f"  {r['race'][:6]} {r['year']} st{r['n']:<3} {r['rider_id'][:34]:<35} "
              f"{r['f']}s -> {r['g']}s")
    if len(rows) > args.limit:
        print(f"  ... and {len(rows) - args.limit} more")

    if args.apply and rows:
        cur.executemany(
            "UPDATE stage_results SET finish_time_seconds=gap_seconds, gap_seconds=0 "
            "WHERE result_id=?", [(r["result_id"],) for r in rows])
        # One provenance row per STAGE, not per result: the fact recorded is
        # "this stage's winning time was recomputed", and stage_results has no
        # provenance granularity of its own.
        for stage_id in sorted({r["stage_id"] for r in rows}):
            record_provenance(
                cur, "stages", stage_id, "results", SOURCE_DERIVED,
                source_ref="winner's finish_time_seconds had its own time added "
                           "as a gap (PCS prints time and gap in one cell); "
                           "recomputed as finish = gap, gap = 0. See "
                           "fix_doubled_winner_times.py")
        conn.commit()

    left = cur.execute(
        "SELECT COUNT(*) FROM stage_results WHERE stage_rank=1 "
        "AND finish_time_seconds IS NOT NULL AND gap_seconds>0 "
        "AND finish_time_seconds=2*gap_seconds").fetchone()[0]
    conn.close()
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}"
          f"{len(rows)} row(s) {'would be ' if args.dry_run else ''}corrected; "
          f"{left} still matching the pattern")
    sys.exit(0)


if __name__ == "__main__":
    main()
