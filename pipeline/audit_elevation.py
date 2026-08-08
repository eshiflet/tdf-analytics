#!/usr/bin/env python3
"""
Audit stored elevation against PCS, fetching each stage by its source_slug.

Answers the question provenance can't: for stages whose vertical_meters and
profile_score were recorded before provenance tracking (source 'unknown'), do
they actually match what PCS serves for that stage's own page?

This matters most where source_slug diverges from stage_number — every stage
after a split day — because that is exactly where a tool that reconstructed
"stage-{stage_number}" would have read the neighbouring stage's figures. The
Vuelta/Giro elevation scrapers did precisely that. The TDF path did not: its
elevation comes from tdf_YEAR_full.json, parsed from the same page fetch as
the results, so it should be immune. "Should be" is why this script exists.

A stage that matches is upgraded from 'unknown' to 'pcs' provenance with the
URL it was verified against, so the audit permanently reduces the unknown
count instead of just producing a report. Mismatches are reported and NOT
auto-corrected — PCS's current figures aren't automatically better than a
deliberate Wikipedia or manual patch, and telling those apart needs a human.

Usage:
  python3 audit_elevation.py --race tdf --limit 40        # sample
  python3 audit_elevation.py --race tdf --split-only      # only post-split stages
  python3 audit_elevation.py --race tdf                   # everything (slow)
  python3 audit_elevation.py --race tdf --apply-provenance
"""

import argparse
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

from race_common import DB_PATH, SOURCE_PCS, record_provenance

BASE = "https://www.procyclingstats.com"
RACE_PATH = {
    "tdf": ("Tour de France", "tour-de-france"),
    "giro": ("Giro d'Italia", "giro-d-italia"),
    "vuelta": ("Vuelta a España", "vuelta-a-espana"),
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 2.0


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                html = r.read().decode("utf-8", errors="replace")
                return None if ("Just a moment" in html and len(html) < 10000) else html
        except urllib.error.HTTPError as e:
            if e.code in (404, 410, 500):
                return None
            time.sleep(5)
        except Exception:
            time.sleep(5)
    return None


def extract(html):
    vm = ps = None
    m = re.search(r'Vertical meters:\s*</div>\s*<div[^>]*>\s*(\d[\d,]*)', html)
    if m:
        vm = int(m.group(1).replace(",", ""))
    m = re.search(r'ProfileScore:\s*</div>\s*<div[^>]*>\s*(\d+)', html)
    if m:
        ps = int(m.group(1))
    return vm, ps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=sorted(RACE_PATH), default="tdf")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--split-only", action="store_true",
                    help="only stages whose source_slug differs from stage_number")
    ap.add_argument("--seed", type=int, default=1, help="sampling seed")
    ap.add_argument("--apply-provenance", action="store_true",
                    help="upgrade verified matches from 'unknown' to 'pcs'")
    args = ap.parse_args()

    race_name, url_slug = RACE_PATH[args.race]
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur, wcur = conn.cursor(), conn.cursor()

    q = """SELECT s.stage_id, s.stage_number, s.source_slug, s.vertical_meters vm,
                  s.profile_score ps, re.year,
                  s.start_location a, s.finish_location b
           FROM stages s
           JOIN race_editions re ON s.edition_id = re.edition_id
           JOIN races r ON re.race_id = r.race_id
           WHERE r.name = ? AND s.vertical_meters IS NOT NULL
             AND s.source_slug IS NOT NULL"""
    if args.split_only:
        q += " AND s.source_slug != 'stage-' || s.stage_number"
    rows = cur.execute(q + " ORDER BY re.year, s.stage_number", (race_name,)).fetchall()

    if args.limit and len(rows) > args.limit:
        random.seed(args.seed)
        rows = sorted(random.sample(list(rows), args.limit),
                      key=lambda r: (r["year"], r["stage_number"]))

    print(f"Auditing {len(rows)} {race_name} stage(s) against PCS by source_slug\n")
    match = mismatch = missing = failed = 0
    bad = []

    for i, s in enumerate(rows, 1):
        url = f"{BASE}/race/{url_slug}/{s['year']}/{s['source_slug']}/result/result"
        html = fetch(url)
        if html is None:
            failed += 1
            print(f"  [{i}/{len(rows)}] {s['year']} n{s['stage_number']} "
                  f"{s['source_slug']}: FETCH FAILED")
            time.sleep(DELAY)
            continue

        pvm, pps = extract(html)
        if pvm is None:
            missing += 1
        elif pvm == s["vm"] and (pps is None or pps == s["ps"]):
            match += 1
            if args.apply_provenance:
                record_provenance(wcur, "stages", s["stage_id"], "vertical_meters",
                                  SOURCE_PCS, source_ref=f"{url} (audited)")
                record_provenance(wcur, "stages", s["stage_id"], "profile_score",
                                  SOURCE_PCS, source_ref=f"{url} (audited)")
        else:
            mismatch += 1
            bad.append((s, pvm, pps))
            print(f"  [{i}/{len(rows)}] {s['year']} n{s['stage_number']} "
                  f"{s['source_slug']} {s['a']}->{s['b']}: "
                  f"DB {s['vm']}m/{s['ps']} vs PCS {pvm}m/{pps}")
        time.sleep(DELAY)

    if args.apply_provenance:
        conn.commit()

    total = len(rows)
    print(f"\n  matched PCS exactly : {match}/{total}")
    print(f"  mismatched          : {mismatch}")
    print(f"  PCS has no figure   : {missing}")
    print(f"  fetch failed        : {failed}")
    if args.apply_provenance and match:
        print(f"\n  upgraded {match} stage(s) to 'pcs' provenance")
    if mismatch:
        print("\n  Mismatches are NOT auto-corrected — a stored value may be a "
              "deliberate\n  Wikipedia or manual patch that PCS disagrees with. "
              "Review individually.")
    conn.close()
    sys.exit(1 if mismatch else 0)


if __name__ == "__main__":
    main()
