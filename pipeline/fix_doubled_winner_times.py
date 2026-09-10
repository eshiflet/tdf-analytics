#!/usr/bin/env python3
"""
Repair stage winners whose finish_time_seconds is double the real time, and
the scrape files that keep re-creating the problem.

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

--files repairs the STAGE FILES, which is what stops this coming back. The
database was fixed in 2026-08; the parser that wrote the defect was not, so
every re-scrape since has written it straight back in — 1,755 Giro and 1,623
Vuelta stage winners still carry gap == abs_time on disk today, and the next
re-ingest of any of those editions would undo the repair below. Two artifacts
are corrected, both by rules that admit no ambiguity:

  winner gap   gap == abs_time on a rank-1 row. A winner's gap to themselves is
               zero; it can never be their own finishing time. -> "+0:00"
  points-as-   a bare bonus equal to that row's own pcs_pts. The old parser
  bonus        looked for the bonus by scanning columns near Time and found the
               POINTS column instead: 29,849 Giro and 24,963 Vuelta rows, every
               one matching its own pcs_pts exactly. A GENUINE bonus carries
               PCS's seconds mark (1"), never equals pcs_pts, and is left
               alone — as are Vuelta 2020 stage 12's unmarked 10/6/4, which are
               real. A bonus holding a clock value ("0:350:35", Tour 1954
               stage 4) is a misaligned column and is cleared too.

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
import json
import os
import sqlite3
import sys

from race_common import DB_PATH, SOURCE_DERIVED, record_provenance

HERE = os.path.dirname(os.path.abspath(__file__))

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


def repair_files(apply_it):
    """Fix winner gaps and points-as-bonus in every stage race's scrape files."""
    import glob
    from race_common import RACES, StageRow

    fixed_gap = fixed_bonus = touched = 0
    for race in sorted(RACES):
        root = os.path.join(HERE, RACES[race].scrapes_dirname)
        for path in sorted(glob.glob(os.path.join(root, "*", "stage_*.json"))):
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            changed = False
            for row in doc.get("rows", []):
                if len(row) != 15:
                    continue
                sr = StageRow.from_list(row)
                if sr.rnk == "1" and sr.abs_time and sr.gap == sr.abs_time:
                    row[14] = "+0:00"
                    fixed_gap += 1
                    changed = True
                b = (row[12] or "").strip()
                if b and ":" in b:
                    row[12] = ""            # a clock value, not a bonus
                    fixed_bonus += 1
                    changed = True
                elif b and "\u2033" not in b and '"' not in b and b == (row[11] or "").strip():
                    row[12] = ""            # the points column, misread
                    fixed_bonus += 1
                    changed = True
            if changed:
                touched += 1
                if apply_it:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(doc, f, ensure_ascii=False)
    print(f"{'repaired' if apply_it else '[DRY RUN] would repair'} "
          f"{fixed_gap:,} winner gap(s) and {fixed_bonus:,} bonus value(s) "
          f"across {touched:,} file(s)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", action="store_true",
                    help="repair the scrape files instead of the database")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=10,
                    help="how many examples to print")
    args = ap.parse_args()
    if args.files:
        return repair_files(args.apply)
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
