#!/usr/bin/env python3
"""
Fill in stages whose distance_km is missing or zero, from the PCS page header.

PCS's "Distance:" info row reads "0 km" for a lot of historical stages, but the
page header still carries the real figure as "(102.5km)". The scrapers read the
info row, so those stages land in the DB as 0 and the edition's total distance
is understated.

This is overwhelmingly the FINAL stage of an edition: 117 of the 118 affected
stages are the last one of their race. Until 2026-08-08 this script hardcoded
tour-de-france, so only the Tour was ever repaired — 70 Giro and 47 Vuelta
editions still had a zero-length last stage silently dragging their
totalDistanceKm down by a full stage.

Stages are fetched by stages.source_slug. The previous version re-derived the
PCS URL suffix by reimplementing the a/b split-day labelling, which is exactly
the inference that turned out to be wrong (PCS letters split days in some
editions and numbers them sequentially in others). source_slug is probed and
route-verified, so it is the only thing worth keying off.

Usage:
  python3 patch_missing_distances.py --dry-run
  python3 patch_missing_distances.py --race vuelta --dry-run
  python3 patch_missing_distances.py --apply
"""

import argparse
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

from race_common import DB_PATH, SOURCE_PCS, record_provenance

BASE = "https://www.procyclingstats.com"
RACES = {
    "tdf": ("Tour de France", "tour-de-france"),
    "giro": ("Giro d'Italia", "giro-d-italia"),
    "vuelta": ("Vuelta a España", "vuelta-a-espana"),
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.5",
}
REQUEST_DELAY = 1.5


def fetch(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}")
        return None
    except Exception as e:
        print(f"    error: {e}")
        return None


def parse_distance(html):
    """Distance from the page header, e.g. '(102.5km)'."""
    m = re.search(r"\((\d+(?:\.\d+)?)\s*km\)", html, re.IGNORECASE)
    return float(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=sorted(RACES), default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    races = [args.race] if args.race else sorted(RACES)
    patched = failed = 0

    for race in races:
        race_name, race_path = RACES[race]
        rows = cur.execute("""
            SELECT s.stage_id, s.stage_number, s.source_slug, re.year,
                   s.start_location, s.finish_location,
                   (SELECT MAX(stage_number) FROM stages WHERE edition_id=s.edition_id) last
            FROM stages s
            JOIN race_editions re ON s.edition_id = re.edition_id
            JOIN races r ON re.race_id = r.race_id
            WHERE r.name = ? AND s.cancelled = 0
              AND (s.distance_km IS NULL OR s.distance_km = 0)
              AND s.source_slug IS NOT NULL
            ORDER BY re.year, s.stage_number
        """, (race_name,)).fetchall()

        print(f"\n{race_name}: {len(rows)} stage(s) with missing distance")
        for s in rows:
            url = f"{BASE}/race/{race_path}/{s['year']}/{s['source_slug']}/result/result"
            html = fetch(url)
            time.sleep(REQUEST_DELAY)
            if html is None:
                failed += 1
                continue
            dist = parse_distance(html)
            tail = " (final stage)" if s["stage_number"] == s["last"] else ""
            if dist is None:
                print(f"  {s['year']} n{s['stage_number']} {s['source_slug']}: "
                      f"no distance on page{tail}")
                failed += 1
                continue
            print(f"  {s['year']} n{s['stage_number']} {s['source_slug']}: "
                  f"{dist} km  ({s['start_location']} -> {s['finish_location']}){tail}")
            patched += 1
            if args.apply:
                cur.execute("UPDATE stages SET distance_km=? WHERE stage_id=?",
                            (dist, s["stage_id"]))
                # PCS, but the header rather than the "Distance:" info row the
                # scrapers read — worth distinguishing, since a plain re-scrape
                # would put the 0 back.
                record_provenance(cur, "stages", s["stage_id"], "distance_km",
                                  SOURCE_PCS, source_ref=f"{url} (header)")
        if args.apply:
            conn.commit()

    conn.close()
    print(f"\n{'[DRY RUN] ' if not args.apply else ''}"
          f"{patched} stage(s) {'would be ' if not args.apply else ''}patched, "
          f"{failed} failed/unavailable")
    if args.apply and patched:
        print("Re-run export_race_summary.py / export_all_races_summary.py "
              "so the corrected totals reach the app.")


if __name__ == "__main__":
    main()
