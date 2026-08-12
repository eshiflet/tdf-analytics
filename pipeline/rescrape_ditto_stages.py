#!/usr/bin/env python3
"""
Re-scrape stages whose stored gaps never had PCS's ditto marks expanded.

PCS prints ",," in the time column for "same as the rider above". The parser
handles it correctly today, but the stage files on disk were written before
that fix, so they record "+0:00" for riders who were really 1:02 down — and the
database inherited it. On the worst stages 189 riders of 198 are recorded as
finishing level with the winner.

Detection is race_common.gap_violations: a finishing order's gaps never
decrease, so a zero gap behind a rider who lost time is impossible.

The stale FILES matter even where the database is currently right. Giro 1923
stage 1 has bad gaps on disk and correct ones in the DB, so the next re-ingest
of that edition would undo the good data. Fixing the files is what makes the
repair durable.

Guards, all required before a file is rewritten:

  * the fresh scrape must have at least as many result rows as the file
  * it must have strictly FEWER gap violations
  * it must parse to well-formed rows of the full schema width

Anything that fails is reported and left alone, so a truncated fetch or a
markup change cannot replace good data with worse. Files are written via a
temporary file and renamed, so an interrupted run cannot leave a half-written
stage behind.

Re-ingest is NOT run automatically — that is a destructive path and belongs in
a deliberate step. The editions touched are printed at the end.

Usage:
  python3 rescrape_ditto_stages.py --race giro --dry-run
  python3 rescrape_ditto_stages.py --race giro --apply
  python3 rescrape_ditto_stages.py --race vuelta --apply --limit 50
"""

import argparse
import json
import os
import re
import sys
import time

import sqlite3

import scrape_giro
import scrape_vuelta
from race_common import DB_PATH, STAGE_ROW_LEN, parse_ttt_rows, row_gap_violations

HERE = os.path.dirname(os.path.abspath(__file__))
RACES = {
    "giro": ("giro-d-italia", "giro_scrapes", scrape_giro, "Giro d'Italia"),
    "vuelta": ("vuelta-a-espana", "vuelta_scrapes", scrape_vuelta, "Vuelta a España"),
}
BASE = "https://www.procyclingstats.com"
DELAY = 1.5


def stale_files(scrapes_dir):
    """[(year, stage_number, path, data, violations)] worth re-scraping."""
    out = []
    root = os.path.join(HERE, scrapes_dir)
    for year in sorted(y for y in os.listdir(root) if y.isdigit()):
        ydir = os.path.join(root, year)
        for fn in sorted(os.listdir(ydir)):
            if not (fn.startswith("stage_") and fn.endswith(".json")):
                continue
            path = os.path.join(ydir, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            v = row_gap_violations(data.get("rows") or [])
            if v:
                out.append((int(year), int(fn[6:-5]), path, data, v))
    return out


def fetch_rows(module, race_path, year, slug):
    """Fresh rows for one stage, TTT-aware. None if the page cannot be read."""
    html = module.fetch(f"{BASE}/race/{race_path}/{year}/{slug}/result/result")
    if not html:
        return None, False
    if re.search(r'class="[^"]*ttt-results', html):
        return parse_ttt_rows(html), True
    table = module.find_results_table(html)
    return (module.parse_rows(table) if table else []), False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=sorted(RACES), required=True)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    race_path, scrapes_dir, module, race_name = RACES[args.race]

    # Slugs come from the DATABASE, never from "stage-{n}". A stage file that
    # predates slug recording has none, and on a split edition the DB's
    # contiguous numbering runs ahead of PCS's from the split onward — so the
    # guess fetches a different stage, or 500s forever. Every source_slug is
    # now confirmed against PCS's own stage list, so this is the reliable map.
    # Guessing cost 5 unreachable pages in the first 18 of this run.
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    slugs = {(y, n): sl for y, n, sl in db.execute(
        """SELECT re.year, s.stage_number, s.source_slug FROM stages s
             JOIN race_editions re USING(edition_id) JOIN races ra USING(race_id)
            WHERE ra.name=? AND s.source_slug IS NOT NULL""", (race_name,))}
    db.close()
    module.DELAY = DELAY

    targets = stale_files(scrapes_dir)
    if args.year:
        targets = [t for t in targets if t[0] == args.year]
    if args.limit:
        targets = targets[:args.limit]

    print(f"{len(targets)} stale stage file(s) in {scrapes_dir}\n")
    fixed, refused, failed = 0, 0, 0
    years = set()

    for year, n, path, data, before in targets:
        slug = slugs.get((year, n)) or data.get("slug")
        if not slug:
            failed += 1
            print(f"  ?   {args.race} {year} st{n:<3} no source_slug — skipped")
            continue
        rows, is_ttt = fetch_rows(module, race_path, year, slug)
        time.sleep(DELAY)
        tag = f"{args.race} {year} st{n:<3} ({slug})"

        if rows is None:
            failed += 1
            print(f"  ?   {tag}  page could not be read")
            continue
        malformed = sum(1 for r in rows if len(r) != STAGE_ROW_LEN)
        rows = [r for r in rows if len(r) == STAGE_ROW_LEN]
        after = row_gap_violations(rows)
        old_n = len([r for r in (data.get("rows") or []) if len(r) == STAGE_ROW_LEN])

        if len(rows) < old_n:
            refused += 1
            print(f"  !   {tag}  fresh scrape has {len(rows)} rows vs {old_n} — refused")
            continue
        if after >= before:
            refused += 1
            print(f"  !   {tag}  violations {before} -> {after}, no improvement — refused")
            continue

        fixed += 1
        years.add(year)
        extra = f", +{len(rows)-old_n} rows" if len(rows) != old_n else ""
        warn = f"  ({malformed} malformed dropped)" if malformed else ""
        print(f"  ->  {tag}  gap violations {before} -> {after}{extra}{warn}")

        if args.apply:
            data["rows"] = rows
            if is_ttt:
                data["is_ttt"] = True
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}{fixed} file(s) "
          f"{'would be ' if args.dry_run else ''}rewritten, {refused} refused, "
          f"{failed} unreachable")
    if years and args.apply:
        print("\nRe-ingest these editions:")
        for y in sorted(years):
            print(f"  python3 ingest_race.py --race {args.race} {y}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
