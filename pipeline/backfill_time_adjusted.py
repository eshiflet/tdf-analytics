#!/usr/bin/env python3
"""
Record PCS's time marker on the GC rows that carry it.

OFFLINE. Reads the stage pages already stored under <race>_scrapes/<year>/
gc_pages/ and never fetches anything.

WHAT IT FIXES. PCS marks a rider whose recorded time was AWARDED rather than
raced -- credited with a group's time after a crash inside the final
kilometres, most often -- so the time no longer places him where he stands. We store the rank and the gap faithfully and throw the marker away, so
230 stages read downstream as self-contradictory — a later rank apparently
closer to the leader than an earlier one — when both stored values are right.
This puts the marker back. NO RANK AND NO GAP IS EVER WRITTEN.

WHY A BACKFILL RATHER THAN A RE-INGEST. A full ingest rebuilds a race-year from
its scrape files and has historically reverted corrections that lived only in
the database. This adds one column to existing rows and touches nothing else,
so there is no rebuild and nothing to revert. ingest_race.py sets the same flag
from the same helper, so a future rebuild recreates it rather than losing it.

THE PAGE IS VERIFIED BEFORE IT IS BELIEVED. gc_source.gc_page() refuses a page
whose own result table does not match the stage beside it — the 1992 Giro's
twenty gc_pages files are each the NEXT stage's page, and trusting the filename
there produced a confident, wrong bug report. A stage whose page cannot be
verified is skipped and counted, never guessed at.

Usage:
  python3 backfill_time_adjusted.py                # dry run, prints the table
  python3 backfill_time_adjusted.py --race tour
  python3 backfill_time_adjusted.py --apply
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter

import gc_source
from race_common import DB_PATH, exit_on_help, record_provenance

RACE_ALIASES = {"tour": "Tour de France", "tdf": "Tour de France",
                "giro": "Giro d'Italia", "vuelta": "Vuelta a España"}


def ensure_column(cur):
    """Add stage_results.time_adjusted if this database predates it.

    Additive and idempotent: an ALTER with a DEFAULT leaves every existing row
    untouched at 0, so running this on a current database does nothing.
    """
    cols = {r[1] for r in cur.execute("PRAGMA table_info(stage_results)")}
    if "time_adjusted" not in cols:
        cur.execute("ALTER TABLE stage_results ADD COLUMN "
                    "time_adjusted INTEGER NOT NULL DEFAULT 0")
        return True
    return False


def stage_file_rows(race, year, stage_number):
    """This stage's own scrape rows, or []. No verification needed: unlike the
    classification page, this file is named for the stage the ingest reads it
    as."""
    directory = gc_source.SCRAPE_DIR.get(race)
    if not directory:
        return []
    path = os.path.join(gc_source.HERE, directory, str(year),
                        f"stage_{stage_number}.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("rows") or []
    except (ValueError, OSError):
        return []


def find_adjusted(conn, race=None):
    """[(stage_id, race, year, stage_number, rider_id)] PCS marks, from disk."""
    sql = """SELECT s.stage_id, ra.name, re.year, s.stage_number, s.source_slug
               FROM stages s
               JOIN race_editions re ON re.edition_id = s.edition_id
               JOIN races ra ON ra.race_id = re.race_id
              WHERE ra.name IN ('Tour de France', "Giro d'Italia", 'Vuelta a España')"""
    params = []
    if race:
        sql += " AND ra.name = ?"
        params.append(race)
    found, stats = [], Counter()
    for stage_id, name, year, number, slug in conn.execute(sql, params):
        # THREE places carry the same mark and all are unioned. The stage's own
        # scrape file needs no verification — it is the file the ingest reads
        # for everything else about this stage — so it is read even where the
        # classification page cannot be placed. Reading only the verified page
        # found 67 marks on the 1990 Vuelta where a re-ingest finds 138, which
        # is how the gap was noticed: a backfill that disagrees with the ingest
        # is a backfill the next rebuild undoes.
        marked = gc_source.marked_in_stage_rows(
            stage_file_rows(name, year, number))
        page = gc_source.gc_page(name, year, number, slug)
        if page is None:
            stats["unverified"] += 1
        else:
            stats["verified"] += 1
            marked |= (gc_source.marked_riders(page)
                       | gc_source.marked_in_stage_rows(page.get("result_rows")))
        if not marked:
            continue
        # EVERY row we store for the stage, not only those holding a GC rank.
        # The mark is about the rider's TIME being awarded rather than raced,
        # which is true of his stage result as well, and ingest_race sets it on
        # every row — so restricting it here would make a rebuild disagree with
        # this script and quietly change 71 rows on the 1990 Vuelta alone.
        stored = {r[0] for r in conn.execute(
            "SELECT rider_id FROM stage_results WHERE stage_id = ?", (stage_id,))}
        for rider in sorted(marked & stored):
            found.append((stage_id, name, year, number, rider))
        stats["marked but not stored"] += len(marked - stored)
    return found, stats


def main():
    exit_on_help(__doc__)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--race", help="tour | giro | vuelta")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--limit", type=int, default=20, help="rows to print (0 for all)")
    args = ap.parse_args()

    race = RACE_ALIASES.get((args.race or "").lower(), args.race)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    found, stats = find_adjusted(conn, race)

    print(f"{stats['verified']} stage(s) had a page this could verify; "
          f"{stats['unverified']} could not be verified and were skipped.")
    print(f"{len(found)} row(s) carry PCS's time marker, in either table.\n")
    shown = found if args.limit == 0 else found[:args.limit]
    for _sid, name, year, number, rider in shown:
        print(f"  {name} {year} st{number:<3} {rider}")
    if args.limit and len(found) > args.limit:
        print(f"  ... and {len(found) - args.limit} more (--limit 0 for all)")
    if stats["marked but not stored"]:
        print(f"\n{stats['marked but not stored']} marked rider(s) hold no GC row here "
              "and were left alone.")

    if not args.apply:
        print("\nDry run. Nothing written. Re-run with --apply.")
        conn.close()
        return 0

    added = ensure_column(cur)
    if added:
        print("\nAdded stage_results.time_adjusted (existing rows default to 0).")
    for stage_id, _n, _y, _s, rider in found:
        cur.execute("UPDATE stage_results SET time_adjusted = 1 "
                    "WHERE stage_id = ? AND rider_id = ?", (stage_id, rider))
    # Provenance per stage, matching how the rest of stage_results is recorded:
    # one row covers the stage, because one page is the source for all of them.
    for stage_id in sorted({f[0] for f in found}):
        record_provenance(cur, "stages", stage_id, "time_adjusted", "pcs",
                          source_ref="gc_pages", script="backfill_time_adjusted.py")
    conn.commit()
    print(f"\nApplied: {len(found)} row(s) flagged across "
          f"{len({f[0] for f in found})} stage(s). No rank or gap was touched.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
