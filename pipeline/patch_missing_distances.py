#!/usr/bin/env python3
"""
Patch stages with missing/zero distance_km by scraping the PCS stage result page.
The distance appears in the page header as "(102.5km)".

Usage: python3 patch_missing_distances.py [--dry-run]
"""
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict

from race_common import SOURCE_PCS, record_provenance

HERE = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
DB_PATH = __import__("os").path.join(HERE, "cycling.db")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.5",
}

REQUEST_DELAY = 1.2


def fetch(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {url}")
        return None
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def parse_distance(html):
    """Extract distance in km from page header like '(102.5km)'."""
    m = re.search(r'\((\d+(?:\.\d+)?)\s*km\)', html, re.IGNORECASE)
    return float(m.group(1)) if m else None


def stage_label(year, stage_number, stage_date, all_stages_for_year):
    """Reproduce the label logic to get the PCS URL suffix."""
    date_groups = defaultdict(list)
    for i, s in enumerate(all_stages_for_year):
        key = s["stage_date"] or f"__nodate_{i}"
        date_groups[key].append(i)

    labels = [""] * len(all_stages_for_year)
    day_counter = 0
    for date in sorted(date_groups.keys()):
        indices = date_groups[date]
        if len(indices) == 1:
            i = indices[0]
            if all_stages_for_year[i]["stage_number"] == 0:
                labels[i] = "P"
            else:
                day_counter += 1
                labels[i] = str(day_counter)
        else:
            day_counter += 1
            for j, i in enumerate(indices):
                labels[i] = f"{day_counter}{'abcde'[j]}"

    # Find label for our stage
    for i, s in enumerate(all_stages_for_year):
        if s["stage_number"] == stage_number:
            return labels[i]
    return None


def pcs_url_suffix(label):
    if label == "P":
        return "prologue"
    return f"stage-{label}"


def main():
    dry_run = "--dry-run" in sys.argv

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Get all stages with missing/zero distance that have a finish location (skip bare prologues)
    missing = conn.execute("""
        SELECT re.year, s.stage_id, s.stage_number, s.stage_date, s.finish_location
        FROM stages s
        JOIN race_editions re ON re.edition_id = s.edition_id
        WHERE (s.distance_km IS NULL OR s.distance_km = 0)
          AND s.finish_location IS NOT NULL
          AND s.stage_date IS NOT NULL
        ORDER BY re.year, s.stage_number
    """).fetchall()

    print(f"Found {len(missing)} stages with missing distance")
    if dry_run:
        print("DRY RUN — no DB writes")

    # Cache all stages per year for label computation
    stages_by_year = {}

    patched = 0
    failed = 0

    for row in missing:
        year = row["year"]
        stage_id = row["stage_id"]
        stage_number = row["stage_number"]
        finish = row["finish_location"]

        if year not in stages_by_year:
            edition_id = conn.execute(
                "SELECT edition_id FROM race_editions WHERE race_id=(SELECT race_id FROM races WHERE name='Tour de France') AND year=?", (year,)
            ).fetchone()["edition_id"]
            stages_by_year[year] = [
                dict(r) for r in conn.execute(
                    "SELECT stage_number, stage_date FROM stages WHERE edition_id=? ORDER BY stage_number",
                    (edition_id,),
                )
            ]

        lbl = stage_label(year, stage_number, row["stage_date"], stages_by_year[year])
        if not lbl:
            print(f"  {year} stage {stage_number}: could not compute label, skipping")
            failed += 1
            continue

        suffix = pcs_url_suffix(lbl)
        url = f"https://www.procyclingstats.com/race/tour-de-france/{year}/{suffix}/result/result"
        print(f"{year} stage {lbl} ({finish}): {url}")

        html = fetch(url)
        time.sleep(REQUEST_DELAY)

        if html is None:
            print("  -> fetch failed")
            failed += 1
            continue

        dist = parse_distance(html)
        if dist is None:
            print("  -> distance not found in page")
            failed += 1
            continue

        print(f"  -> {dist} km")
        if not dry_run:
            conn.execute(
                "UPDATE stages SET distance_km=? WHERE stage_id=?",
                (dist, stage_id),
            )
            # Also PCS, but a different part of the page than the scrapers
            # use: the header "(102.5km)" rather than the "Distance:" info row,
            # which is blank/0 for these stages. Worth distinguishing, since
            # re-running a stage scrape would put the 0 back.
            record_provenance(conn, "stages", stage_id, "distance_km",
                              SOURCE_PCS, source_ref=f"{url} (header)")
            conn.commit()
        patched += 1

    conn.close()
    print(f"\nDone. Patched: {patched}, Failed/skipped: {failed}")


if __name__ == "__main__":
    main()
