#!/usr/bin/env python3
"""
Replace one TDF stage's results from tdf_YEAR_full.json, in place.

The TDF ingest path (add_pre1960.py / add_stages.py) is additive: it skips any
edition already in the DB, so there is no way to push a corrected stage back in
short of deleting and rebuilding the whole edition — which would discard the
elevation, patched distances and provenance that live only in the DB.

This does the narrow thing instead: swap out the results of a single stage,
leaving the stages row and every other stage untouched. Written for the TTT
recovery (TDF 1955 stage 2 held 3 results for a 127-rider team time trial,
because the ordinary row parser cannot read a TTT table — see
race_common.parse_ttt_rows), but it is not TTT-specific.

Refuses to shrink a stage: if the file has no more rows than the DB already
holds, something is wrong with the file, not the database.

Usage:
  python3 reingest_tdf_stage.py --year 1955 --stage 2 --dry-run
  python3 reingest_tdf_stage.py --year 1955 --stage 2 --apply
"""

import argparse
import json
import os
import re
import sqlite3
import sys

from race_common import (
    COUNTRY_NAMES,
    DB_PATH,
    SOURCE_PCS,
    STAGE_ROW_LEN,
    StageRow,
    parse_bonus_seconds,
    parse_int,
    parse_time_to_seconds,
    record_provenance,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--stage", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    path = os.path.join(HERE, f"tdf_{args.year}_full.json")
    with open(path, encoding="utf-8") as f:
        full = json.load(f)
    stage_data = next((s for s in full["stages"] if s["n"] == args.stage), None)
    if stage_data is None:
        sys.exit(f"error: no stage {args.stage} in {os.path.basename(path)}")

    rows = [r for r in stage_data.get("rows", []) if len(r) == STAGE_ROW_LEN]
    dropped = len(stage_data.get("rows", [])) - len(rows)
    if dropped:
        print(f"  WARNING: {dropped} malformed row(s) in the file will not be inserted")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    st = cur.execute("""SELECT s.stage_id, s.route_type,
            (SELECT COUNT(*) FROM stage_results WHERE stage_id=s.stage_id) res
          FROM stages s
          JOIN race_editions re ON s.edition_id=re.edition_id
          JOIN races r ON re.race_id=r.race_id
          WHERE r.name='Tour de France' AND re.year=? AND s.stage_number=?""",
                     (args.year, args.stage)).fetchone()
    if not st:
        sys.exit(f"error: TDF {args.year} stage {args.stage} not in the database")

    print(f"TDF {args.year} stage {args.stage}: DB has {st['res']} result(s), "
          f"file has {len(rows)}")
    if len(rows) <= st["res"]:
        sys.exit("refusing to replace: the file holds no more rows than the DB")

    if args.dry_run:
        print("\n[DRY RUN] would replace the stage's results. Sample:")
        for r in rows[:3]:
            sr = StageRow.from_list(r)
            print(f"   rnk={sr.rnk:<3} {sr.name:<24} {sr.team:<22} time={sr.abs_time} gap={sr.gap}")
        conn.close()
        return

    stage_id = st["stage_id"]
    cur.execute("DELETE FROM stage_results WHERE stage_id=?", (stage_id,))

    # Same convention as ingest_race: the rank-1 absolute time anchors the
    # stage, and every other finisher is that plus their gap. On a TTT each
    # rider carries their team's time and gap, so this reproduces the team time.
    winner_seconds = None
    for r in rows:
        sr = StageRow.from_list(r)
        if sr.rnk == "1" and parse_time_to_seconds(sr.abs_time) is not None:
            winner_seconds = parse_time_to_seconds(sr.abs_time)
            break

    inserted = 0
    for r in rows:
        sr = StageRow.from_list(r)
        if not sr.slug:
            continue
        if sr.nat:
            cur.execute("INSERT OR IGNORE INTO countries (code, name) VALUES (?,?)",
                        (sr.nat, COUNTRY_NAMES.get(sr.nat)))
        cur.execute("INSERT OR IGNORE INTO riders (rider_id, full_name, nationality_code) "
                    "VALUES (?,?,?)", (sr.slug, sr.name, sr.nat or None))
        if sr.team_slug:
            m = re.search(r"-(\d{4})$", sr.team_slug)
            cur.execute("INSERT OR IGNORE INTO teams (team_id, name, season_year) VALUES (?,?,?)",
                        (sr.team_slug, sr.team, int(m.group(1)) if m else None))

        status = sr.rnk if sr.rnk in ("DNF", "DNS", "OTL", "NP", "DSQ", "DEL") else "FINISHED"
        gap_secs = parse_time_to_seconds(sr.gap)
        finish_secs = None
        if status == "FINISHED" and winner_seconds is not None:
            if gap_secs is not None:
                finish_secs = winner_seconds + gap_secs
            elif parse_int(sr.rnk) == 1:
                finish_secs = winner_seconds

        cur.execute("""INSERT OR IGNORE INTO stage_results
              (stage_id, rider_id, team_id, bib_number, stage_rank, status,
               finish_time_seconds, gap_seconds, bonus_seconds, penalty_seconds,
               uci_points, pcs_points, gc_rank, gc_gap_seconds, age_at_race)
              VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,?,?)""",
                    (stage_id, sr.slug, sr.team_slug or None, parse_int(sr.bib),
                     parse_int(sr.rnk) if status == "FINISHED" else None, status,
                     finish_secs, gap_secs, parse_bonus_seconds(sr.bonus),
                     parse_int(sr.uci_pts), parse_int(sr.pcs_pts),
                     parse_int(sr.gc_pos), parse_time_to_seconds(sr.gc_lag),
                     parse_int(sr.age)))
        inserted += 1

    if stage_data.get("is_ttt"):
        cur.execute("UPDATE stages SET route_type='TTT' WHERE stage_id=?", (stage_id,))

    record_provenance(cur, "stages", stage_id, "results", SOURCE_PCS,
                      source_ref=f"tdf_{args.year}_full.json "
                                 f"({stage_data.get('slug', '?')}, TTT re-parse)")
    conn.commit()
    print(f"  replaced {st['res']} result(s) with {inserted}")
    conn.close()


if __name__ == "__main__":
    main()
