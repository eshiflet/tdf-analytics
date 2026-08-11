#!/usr/bin/env python3
"""
Fill in stages that reached the DB with no route and no date.

14 stages have NULL start_location, finish_location AND stage_date — 13 Tour
prologues from 1995-2012 and the 1998 stage 17 that the riders' strike cut
short. PCS has all three fields for every one of them; these rows simply never
came through a path that read the stage page. A prologue with no locations also
breaks route matching, which is how PCS's `prologue` entry once got matched to
TDF 1996 stage 1 and corrupted 21 editions' slugs (see audit_stage_counts).

Only NULLs are filled — a stored value is never overwritten. Before writing,
the page's distance is compared against the stored one: these stages already
have a distance, so a mismatch means the slug points at the wrong page and the
locations would belong to a different stage.

Metadata is read with insert_cancelled_stages.parse_meta, the same parser the
cancellation tooling uses, rather than a second copy of the same regexes.

Usage:
  python3 backfill_stage_metadata.py --dry-run
  python3 backfill_stage_metadata.py --apply
"""

import argparse
import sqlite3
import sys
import time
import urllib.request

from insert_cancelled_stages import parse_meta
from race_common import DB_PATH, SOURCE_PCS, record_provenance

BASE = "https://www.procyclingstats.com"
RACE_PATHS = {
    "Tour de France": "tour-de-france",
    "Giro d'Italia": "giro-d-italia",
    "Vuelta a España": "vuelta-a-espana",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0"}
DELAY = 1.5
FIELDS = (("start_location", "start"), ("finish_location", "finish"),
          ("stage_date", "date"))


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS),
                                    timeout=25) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro" if args.dry_run else DB_PATH,
                           uri=args.dry_run)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT s.stage_id, ra.name race, re.year, s.stage_number n, s.source_slug,
               s.start_location, s.finish_location, s.stage_date, s.distance_km
          FROM stages s
          JOIN race_editions re USING(edition_id)
          JOIN races ra USING(race_id)
         WHERE s.source_slug IS NOT NULL
           AND (s.start_location IS NULL OR s.start_location = ''
                OR s.finish_location IS NULL OR s.finish_location = ''
                OR s.stage_date IS NULL OR s.stage_date = '')
         ORDER BY ra.name, re.year, s.stage_number""").fetchall()

    print(f"{len(rows)} stage(s) missing a route or a date\n")
    filled = skipped = 0

    for r in rows:
        url = f"{BASE}/race/{RACE_PATHS[r['race']]}/{r['year']}/{r['source_slug']}"
        meta = parse_meta(fetch(url) or "")
        time.sleep(DELAY)
        tag = f"{r['race'][:6]} {r['year']} n={r['n']:<3} {r['source_slug']}"

        if r["distance_km"] and meta.get("km") and abs(meta["km"] - r["distance_km"]) > 0.6:
            skipped += 1
            print(f"  !!  {tag}\n        page says {meta['km']} km, DB has "
                  f"{r['distance_km']} km — wrong page, refused")
            continue

        updates = {col: meta[key] for col, key in FIELDS
                   if not r[col] and meta.get(key)}
        if not updates:
            skipped += 1
            print(f"  --  {tag}\n        nothing on the page to fill it with")
            continue

        filled += 1
        pretty = ", ".join(f"{c}={v!r}" for c, v in sorted(updates.items()))
        print(f"  ->  {tag}\n        {pretty}")
        if args.apply:
            cur.execute(
                f"UPDATE stages SET {', '.join(f'{c}=?' for c in updates)} "
                "WHERE stage_id=?", (*updates.values(), r["stage_id"]))
            for col in updates:
                record_provenance(cur, "stages", r["stage_id"], col, SOURCE_PCS,
                                  source_ref=f"{url} (info panel)")

    if args.apply:
        conn.commit()
    conn.close()
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}{filled} stage(s) "
          f"{'would be ' if args.dry_run else ''}filled, {skipped} skipped")
    sys.exit(0)


if __name__ == "__main__":
    main()
