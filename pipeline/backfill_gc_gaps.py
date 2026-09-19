#!/usr/bin/env python3
"""
Fill GC gaps that are missing from the database but present on the stored page.

OFFLINE. Reads pages already under <race>_scrapes/<year>/gc_pages/ and fetches
nothing.

A stage_results row holding a gc_rank with no gc_gap_seconds shows the rider's
overall position with no time behind the leader, which the GC-by-stage chart
cannot plot. The value is usually right there on the page the edition was
ingested from — it was dropped rather than never published.

NULL-FILLS ONLY. It refuses to overwrite a stored value, which is what makes it
safe to run: nothing hand-researched can be destroyed by it, because every
write lands where there was nothing. Rows whose stored value DISAGREES with the
page are counted and named, never changed — deciding between them is a
different job with a different risk, and there are only five of them in the
whole archive.

Every page is verified before it is believed (gc_source.gc_page), so a stage
whose stored page belongs to a different stage contributes nothing. That is not
hypothetical: the 1992 Giro's twenty pages are each the NEXT stage's, and
trusting the filename there produced a confident, wrong bug report.

Usage:
  python3 backfill_gc_gaps.py                 # dry run, prints the table
  python3 backfill_gc_gaps.py --race tour
  python3 backfill_gc_gaps.py --apply
"""

import argparse
import sqlite3
from collections import Counter, defaultdict

import gc_source
from race_common import DB_PATH, exit_on_help, record_provenance

RACE_ALIASES = {"tour": "Tour de France", "tdf": "Tour de France",
                "giro": "Giro d'Italia", "vuelta": "Vuelta a España"}


def collect(conn, race=None):
    """(fills, conflicts, stats) — fills are (stage_id, race, year, stage, rider, seconds)."""
    sql = """SELECT s.stage_id, ra.name, re.year, s.stage_number, s.source_slug
               FROM stages s
               JOIN race_editions re ON re.edition_id = s.edition_id
               JOIN races ra ON ra.race_id = re.race_id
              WHERE ra.name IN ('Tour de France', "Giro d'Italia", 'Vuelta a España')"""
    params = []
    if race:
        sql += " AND ra.name = ?"
        params.append(race)
    fills, conflicts, stats = [], [], Counter()
    for stage_id, name, year, number, slug in conn.execute(sql, params):
        page = gc_source.gc_page(name, year, number, slug)
        if page is None:
            stats["unverified"] += 1
            continue
        gaps, reason = gc_source.gc_gaps_with_reason(page)
        if gaps is None:
            stats[reason] += 1
            continue
        stats["verified"] += 1
        for rider, stored in conn.execute(
                "SELECT rider_id, gc_gap_seconds FROM stage_results "
                "WHERE stage_id = ? AND gc_rank IS NOT NULL", (stage_id,)):
            page_value = gaps.get(rider)
            if page_value is None:
                continue
            if stored is None:
                fills.append((stage_id, name, year, number, rider, page_value))
            elif stored != page_value:
                conflicts.append((name, year, number, rider, stored, page_value))
    return fills, conflicts, stats


def main():
    exit_on_help(__doc__)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--race", help="tour | giro | vuelta")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--limit", type=int, default=0,
                    help="editions to print in the table (0 = all)")
    args = ap.parse_args()

    race = RACE_ALIASES.get((args.race or "").lower(), args.race)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    fills, conflicts, stats = collect(conn, race)

    by_edition = defaultdict(list)
    for _sid, name, year, number, _rider, _sec in fills:
        by_edition[(name, year)].append(number)

    print(f"{stats['verified']} stage(s) read; skipped {stats['unverified']} whose "
          f"page could not be verified, {stats['too few rows']} holding fewer than "
          f"two GC rows, and {stats['absolute times']} whose time column is "
          "absolute times rather than gaps.\n")
    print(f"{len(fills)} row(s) would be FILLED — every one currently NULL, so "
          "nothing is overwritten and nothing can be reverted away:\n")
    print(f"  {'race':<16} {'year':>5} {'rows':>5}  stages")
    rows = sorted(by_edition.items(), key=lambda kv: -len(kv[1]))
    for (name, year), numbers in (rows if not args.limit else rows[:args.limit]):
        uniq = sorted(set(numbers))
        shown = ", ".join(str(n) for n in uniq[:10]) + (" ..." if len(uniq) > 10 else "")
        print(f"  {name:<16} {year:>5} {len(numbers):>5}  {shown}")

    print(f"\n{len(conflicts)} row(s) DISAGREE with the page and are left alone:")
    for name, year, number, rider, stored, page_value in conflicts:
        print(f"  {name} {year} st{number} {rider}: stored {stored}s, page {page_value}s")

    if not args.apply:
        print("\nDry run. Nothing written. Re-run with --apply.")
        conn.close()
        return 0

    for stage_id, _n, _y, _s, rider, seconds in fills:
        cur.execute("UPDATE stage_results SET gc_gap_seconds = ? "
                    "WHERE stage_id = ? AND rider_id = ? AND gc_gap_seconds IS NULL",
                    (seconds, stage_id, rider))
    for stage_id in sorted({f[0] for f in fills}):
        record_provenance(cur, "stages", stage_id, "gc_gap_seconds", "pcs",
                          source_ref="gc_pages", script="backfill_gc_gaps.py")
    conn.commit()
    print(f"\nApplied: {len(fills)} gap(s) filled across "
          f"{len({f[0] for f in fills})} stage(s). Nothing was overwritten.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
