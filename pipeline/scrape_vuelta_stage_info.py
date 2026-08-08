#!/usr/bin/env python3
"""
Scrape vertical_meters and profile_score for Vuelta a España stages from PCS.

Fetches /race/vuelta-a-espana/YEAR/stage-N/result/result and extracts:
  - Vertical meters:  <value>
  - ProfileScore:     <value>

Updates cycling.db stages table directly.

Usage:
  python3 scrape_vuelta_stage_info.py 2025          # single year
  python3 scrape_vuelta_stage_info.py 2021-2025     # year range
  python3 scrape_vuelta_stage_info.py 2025 --dry-run
"""

import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

from race_common import SOURCE_PCS, record_provenance_bulk

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
BASE = "https://www.procyclingstats.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = float(os.environ.get("SCRAPE_DELAY", "3.0"))


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                html = r.read().decode("utf-8", errors="replace")
                if "Just a moment" in html and len(html) < 10000:
                    print(f"    Cloudflare block on {url}")
                    return None
                return html
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            if e.code == 429:
                print(f"    429 rate limit, waiting 30s...")
                time.sleep(30)
                continue
            print(f"    HTTP {e.code} on {url} (attempt {attempt+1})")
            time.sleep(10)
        except Exception as e:
            print(f"    Error: {e} (attempt {attempt+1})")
            time.sleep(10)
    return None


def extract_info(html: str) -> dict:
    """Extract Vertical meters and ProfileScore from PCS stage result page."""
    vert = None
    score = None

    m = re.search(r'Vertical meters:\s*</div>\s*<div[^>]*>\s*(\d[\d,]*)', html)
    if m:
        vert = int(m.group(1).replace(",", ""))

    m = re.search(r'ProfileScore:\s*</div>\s*<div[^>]*>\s*(\d+)', html)
    if m:
        score = int(m.group(1))

    return {"vertical_meters": vert, "profile_score": score}


def parse_year_args(args: list[str]) -> list[int]:
    years = []
    for a in args:
        if a.startswith("-"):
            continue
        if "-" in a:
            parts = a.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                years.extend(range(int(parts[0]), int(parts[1]) + 1))
                continue
        if a.isdigit():
            years.append(int(a))
    return sorted(set(years))


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    years = parse_year_args(args)
    if not years:
        print("Usage: python3 scrape_vuelta_stage_info.py YEAR [YEAR...] [--dry-run]")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    race_row = cur.execute("SELECT race_id FROM races WHERE name=?", ("Vuelta a España",)).fetchone()
    if not race_row:
        print("Vuelta a España not in DB")
        conn.close()
        sys.exit(1)
    race_id = race_row["race_id"]

    total_updated = 0

    for year in years:
        edition = cur.execute(
            "SELECT edition_id FROM race_editions WHERE race_id=? AND year=?",
            (race_id, year),
        ).fetchone()
        if not edition:
            print(f"{year}: no edition in DB, skipping")
            continue

        edition_id = edition["edition_id"]
        stages = cur.execute(
            "SELECT stage_id, stage_number, stage_label, source_slug FROM stages "
            "WHERE edition_id=? ORDER BY stage_number",
            (edition_id,),
        ).fetchall()

        print(f"\n{year}: {len(stages)} stages")
        year_updated = 0

        for stage in stages:
            stage_id = stage["stage_id"]
            stage_num = stage["stage_number"]
            label = stage["stage_label"] or str(stage_num)

            # Fetch by the recorded PCS slug, never by stage_number. On any
            # edition with a split day the DB number runs ahead of the PCS
            # number from the split onward, so "stage-{stage_num}" pulls the
            # NEIGHBOURING stage's page — writing each stage's elevation onto
            # the wrong stage and 404ing on the tail. That silently corrupted
            # Vuelta 1989-1992 (and is why their last stages had no elevation).
            slug = stage["source_slug"]
            if not slug:
                print(f"  Stage {label}: no source_slug — run backfill_source_slugs.py; skipping")
                continue
            slugs = [slug]

            info = None
            for slug in slugs:
                url = f"{BASE}/race/vuelta-a-espana/{year}/{slug}/result/result"
                html = fetch(url)
                if html:
                    info = extract_info(html)
                    if info["vertical_meters"] is not None:
                        break
                time.sleep(DELAY)
            else:
                time.sleep(DELAY)

            if info is None:
                print(f"  Stage {label}: fetch failed")
                continue

            vert = info["vertical_meters"]
            score = info["profile_score"]
            print(f"  Stage {label}: {vert}m ascent, ProfileScore={score}")

            if not dry_run and vert is not None:
                cur.execute(
                    "UPDATE stages SET vertical_meters=?, profile_score=? WHERE stage_id=?",
                    (vert, score, stage_id),
                )
                # Record where these two numbers came from, down to the exact
                # page. Without this the DB can't distinguish a PCS-scraped
                # elevation from a Wikipedia backfill or a hand-entered value,
                # which is what makes the TDF split years unsafe to re-scrape.
                record_provenance_bulk(
                    cur, "stages", stage_id,
                    ["vertical_meters", "profile_score"],
                    SOURCE_PCS, source_ref=url,
                )
                year_updated += 1
            time.sleep(DELAY * 0.5)

        if not dry_run:
            conn.commit()
            print(f"  → Updated {year_updated} stages")
            total_updated += year_updated

    conn.close()
    if not dry_run:
        print(f"\nDone: {total_updated} stages updated across {len(years)} year(s)")
    else:
        print("\n[DRY RUN] No changes written")


if __name__ == "__main__":
    main()
