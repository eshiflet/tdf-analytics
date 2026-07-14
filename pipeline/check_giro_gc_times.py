#!/usr/bin/env python3
"""
Compare GC winner times in our DB against PCS GC final standings page.

Fetches /race/giro-d-italia/YEAR/gc/result/result and extracts the #1
ranked rider's total time, then compares to SUM(finish_time_seconds) in DB.

Usage:
  python3 check_giro_gc_times.py              # all years
  python3 check_giro_gc_times.py 1909-1950    # year range
  python3 check_giro_gc_times.py 1925         # single year
"""

import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
BASE = "https://www.procyclingstats.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = float(os.environ.get("SCRAPE_DELAY", "2.0"))


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


def parse_time_to_seconds(t: str) -> int | None:
    """Parse H:MM:SS or HH:MM:SS or HHH:MM:SS into seconds."""
    t = t.strip()
    parts = t.split(":")
    if len(parts) == 3:
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            return None
    return None


def seconds_to_hms(s: int) -> str:
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def extract_winner_time(html: str) -> int | None:
    """
    Extract the GC winner's total time from a PCS GC results page.

    PCS renders the winner's time in the results table. The rank-1 row
    has a time like "137:31:13". Subsequent riders show gaps like "+0:03:12".

    We look for the first time value that looks like H+:MM:SS in the results.
    """
    # PCS GC page: rank-1 rider time appears as a standalone H:MM:SS or HH:MM:SS
    # pattern in the results table. The winner's time has no "+" prefix.
    # Look for time pattern after rank "1" in the table.

    # Find the results list section
    # PCS uses a ul.resultlist or similar. The winner's time is the first
    # time-looking value that appears without a "+" sign.

    # Try to find winner time: a time string not preceded by +
    # Pattern: digits:two-digits:two-digits that isn't a gap (no preceding +)
    matches = re.findall(r'(?<!\+)(?<!\d)(\d{1,3}:\d{2}:\d{2})(?!\d)', html)
    for m in matches:
        secs = parse_time_to_seconds(m)
        # Sanity check: Giro winner times range from ~60h to ~250h
        if secs and 60 * 3600 < secs < 300 * 3600:
            return secs
    return None


def parse_year_args(args: list[str]) -> list[int] | None:
    """Return list of years, or None to mean 'all years in DB'."""
    years = []
    for a in args:
        if a.startswith("-"):
            continue
        if "-" in a and not a.startswith("-"):
            parts = a.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                years.extend(range(int(parts[0]), int(parts[1]) + 1))
                continue
        if a.isdigit():
            years.append(int(a))
    return sorted(set(years)) if years else None


def main():
    args = sys.argv[1:]
    requested_years = parse_year_args(args)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    race_row = cur.execute("SELECT race_id FROM races WHERE name=?", ("Giro d'Italia",)).fetchone()
    if not race_row:
        print("Giro d'Italia not in DB")
        conn.close()
        sys.exit(1)
    race_id = race_row["race_id"]

    editions = cur.execute(
        "SELECT year, edition_id FROM race_editions WHERE race_id=? ORDER BY year",
        (race_id,),
    ).fetchall()

    discrepancies = {}
    missing = []

    for edition in editions:
        year = edition["year"]
        edition_id = edition["edition_id"]

        if requested_years and year not in requested_years:
            continue

        # Get our DB total GC winner time
        last_stage = cur.execute(
            "SELECT stage_id FROM stages WHERE edition_id=? ORDER BY stage_number DESC LIMIT 1",
            (edition_id,),
        ).fetchone()
        if not last_stage:
            continue

        winner_row = cur.execute(
            "SELECT rider_id FROM stage_results WHERE stage_id=? AND gc_rank=1 LIMIT 1",
            (last_stage["stage_id"],),
        ).fetchone()
        if not winner_row:
            continue

        db_total = cur.execute(
            """SELECT SUM(sr.finish_time_seconds)
               FROM stage_results sr
               JOIN stages s ON sr.stage_id = s.stage_id
               WHERE s.edition_id=? AND sr.rider_id=?
                 AND sr.finish_time_seconds IS NOT NULL""",
            (edition_id, winner_row["rider_id"]),
        ).fetchone()[0]

        # Fetch PCS GC page
        url = f"{BASE}/race/giro-d-italia/{year}/gc/result/result"
        html = fetch(url)
        time.sleep(DELAY)

        if not html:
            print(f"{year}: fetch failed")
            missing.append(year)
            continue

        pcs_time = extract_winner_time(html)

        if pcs_time is None:
            print(f"{year}: could not parse winner time from PCS")
            missing.append(year)
            continue

        db_time_str = seconds_to_hms(int(db_total)) if db_total else "None"
        pcs_time_str = seconds_to_hms(pcs_time)

        if db_total is None or abs(int(db_total) - pcs_time) > 60:
            delta = f" (diff: {abs(int(db_total or 0) - pcs_time)}s)" if db_total else ""
            print(f"{year}: DB={db_time_str}  PCS={pcs_time_str}  MISMATCH{delta}")
            discrepancies[year] = pcs_time
        else:
            print(f"{year}: OK  {pcs_time_str}")

    conn.close()

    print(f"\n--- Summary ---")
    print(f"Mismatches: {len(discrepancies)} years")
    if missing:
        print(f"Could not check: {missing}")
    if discrepancies:
        out_path = os.path.join(HERE, "giro_gc_time_corrections.json")
        with open(out_path, "w") as f:
            json.dump({str(k): v for k, v in sorted(discrepancies.items())}, f, indent=2)
        print(f"Corrections written to {out_path}")


if __name__ == "__main__":
    main()
