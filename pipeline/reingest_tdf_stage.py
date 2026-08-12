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
  python3 reingest_tdf_stage.py --year 1989 --stage 2 --from-pcs --apply

--from-pcs scrapes the stage page instead of reading the file. tdf_YEAR_full.json
only exists for 1903-1959 and 2026, so it is the only route for a modern edition:
TDF 1989 st2 and 2008 st4 both held 196 and 178 rows carrying GC standings alone —
no finishing position, no finish time — because they were built from the GC page
and never from the stage result. PCS publishes both in full.
"""

import argparse
import json
import os
import re
import sqlite3
import sys

import scrape_vuelta as _sv          # generic PCS results-table parsing
from race_common import (
    COUNTRY_NAMES,
    gap_violations,
    DB_PATH,
    SOURCE_PCS,
    STAGE_ROW_LEN,
    StageRow,
    parse_bonus_seconds,
    parse_int,
    parse_time_to_seconds,
    parse_ttt_rows,
    record_provenance,
    row_gap_violations,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def scrape_from_pcs(year, stage_number):
    """Fetch one TDF stage's results by its stored source_slug.

    Keyed on source_slug, never on a rebuilt "stage-{n}": on a split edition the
    DB's contiguous numbering diverges from PCS's permanently, so deriving the
    URL fetches a different stage. A ttt-results list means the field rode it as
    teams and needs parse_ttt_rows — the ordinary parser finds essentially
    nothing there and returns a single stray row that looks like a valid result.
    """
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    row = conn.execute(
        """SELECT s.source_slug FROM stages s
             JOIN race_editions re ON s.edition_id=re.edition_id
             JOIN races r ON re.race_id=r.race_id
            WHERE r.name='Tour de France' AND re.year=? AND s.stage_number=?""",
        (year, stage_number)).fetchone()
    conn.close()
    if not row or not row[0]:
        sys.exit(f"error: TDF {year} stage {stage_number} has no source_slug to fetch")
    slug = row[0]
    url = f"https://www.procyclingstats.com/race/tour-de-france/{year}/{slug}/result/result"
    html = _sv.fetch(url)
    if not html:
        sys.exit(f"error: could not fetch {url}")

    is_ttt = bool(re.search(r'class="[^"]*ttt-results', html))
    if is_ttt:
        rows = parse_ttt_rows(html)
    else:
        table = _sv.find_results_table(html)
        rows = _sv.parse_rows(table) if table else []
    if not rows:
        sys.exit(f"error: no results parsed from {url}")
    return {"n": stage_number, "slug": slug, "rows": rows, "is_ttt": is_ttt,
            "origin": f"{url} ({'TTT team-grouped' if is_ttt else 'stage result'} table)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--stage", type=int, required=True)
    ap.add_argument("--from-pcs", action="store_true",
                    help="scrape the stage page instead of reading tdf_YEAR_full.json")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    if args.from_pcs:
        stage_data = scrape_from_pcs(args.year, args.stage)
        origin = stage_data["origin"]
    else:
        path = os.path.join(HERE, f"tdf_{args.year}_full.json")
        with open(path, encoding="utf-8") as f:
            full = json.load(f)
        stage_data = next((s for s in full["stages"] if s["n"] == args.stage), None)
        if stage_data is None:
            sys.exit(f"error: no stage {args.stage} in {os.path.basename(path)}")
        origin = (f"tdf_{args.year}_full.json "
                  f"({stage_data.get('slug', '?')}, TTT re-parse)")

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

    # Row count alone is the wrong test when the stored rows are GC standings
    # with no finishing position: PCS returns the same 196 riders for TDF 1989
    # st2, but ranked. Replace when the incoming data has more rows OR ranks
    # more of them; refuse when it would lose either.
    db_ranked = cur.execute(
        "SELECT COUNT(stage_rank) FROM stage_results WHERE stage_id=?",
        (st["stage_id"],)).fetchone()[0]
    new_ranked = sum(1 for r in rows if parse_int(StageRow.from_list(r).rnk) is not None)
    print(f"TDF {args.year} stage {args.stage}: DB has {st['res']} result(s) "
          f"({db_ranked} ranked), source has {len(rows)} ({new_ranked} ranked)")
    # A stale ditto repair adds no rows and no ranks — the gain is entirely in
    # the gaps, where PCS's ",," ("same as above") was read as no gap at all.
    # So compare violations too, or the guard rejects the very fix it is for.
    db_bad = gap_violations(cur.execute(
        "SELECT stage_rank, gap_seconds FROM stage_results WHERE stage_id=? "
        "ORDER BY stage_rank", (st["stage_id"],)).fetchall())
    new_bad = row_gap_violations(rows)
    print(f"  gap violations: DB {db_bad}, source {new_bad}")

    if new_ranked < db_ranked:
        sys.exit("refusing to replace: that would lose ranks")
    if len(rows) < st["res"] and not args.from_pcs:
        sys.exit("refusing to replace: that would lose rows")
    if new_bad > db_bad:
        sys.exit("refusing to replace: that would add gap violations")
    if len(rows) == st["res"] and new_ranked == db_ranked and new_bad == db_bad:
        sys.exit("nothing to gain: same rows, same ranks, same gaps")

    if args.dry_run:
        print("\n[DRY RUN] would replace the stage's results. Sample:")
        for r in rows[:3]:
            sr = StageRow.from_list(r)
            print(f"   rnk={sr.rnk:<3} {sr.name:<24} {sr.team:<22} time={sr.abs_time} gap={sr.gap}")
        conn.close()
        return

    stage_id = st["stage_id"]
    if args.from_pcs:
        # Replace only what the source covers. The DB's rows here were built
        # from the GC page, which can list a rider PCS's stage table omits —
        # John-Lee Augustyn sits in TDF 2008 st4's GC at 69th but is absent
        # from its result table. Deleting everything would silently drop him,
        # so rows for riders the scrape does not mention are left alone.
        incoming = {StageRow.from_list(r).slug for r in rows}
        preserved = cur.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage_id=? AND rider_id NOT IN "
            "(%s)" % ",".join("?" * len(incoming)),
            (stage_id, *incoming)).fetchone()[0]
        if preserved:
            print(f"  keeping {preserved} DB row(s) for riders absent from PCS's table")
        cur.executemany("DELETE FROM stage_results WHERE stage_id=? AND rider_id=?",
                        [(stage_id, slug) for slug in incoming])
    else:
        cur.execute("DELETE FROM stage_results WHERE stage_id=?", (stage_id,))

    # Same convention as ingest_race: the rank-1 absolute time anchors the
    # stage, and every other finisher is that plus their gap. On a TTT each
    # rider carries their team's time and gap, so this reproduces the team time.
    winner_seconds = None
    winner_index = None
    for i, r in enumerate(rows):
        sr = StageRow.from_list(r)
        if sr.rnk == "1" and parse_time_to_seconds(sr.abs_time) is not None:
            winner_seconds = parse_time_to_seconds(sr.abs_time)
            winner_index = i
            break

    inserted = 0
    for i, r in enumerate(rows):
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
        if i == winner_index:
            # PCS repeats the winner's own time in the gap field; storing it
            # says he finished his own time behind himself.
            gap_secs = 0
        finish_secs = None
        if status == "FINISHED" and winner_seconds is not None:
            # See ingest_race: only the winner's row carries an absolute time,
            # and PCS repeats it in the gap field, so winner + gap doubles it.
            if i == winner_index:
                finish_secs = winner_seconds
            elif gap_secs is not None:
                finish_secs = winner_seconds + gap_secs

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
                      source_ref=origin)
    conn.commit()
    print(f"  replaced {st['res']} result(s) with {inserted}")
    conn.close()


if __name__ == "__main__":
    main()
