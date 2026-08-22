#!/usr/bin/env python3
"""
Compare GC winner times in our DB against PCS's GC final standings pages.

Serves the Giro and the Vuelta from one implementation — they were two files
measured 85% identical across 139 lines. Third and last of the giro/vuelta
pairs; see scrape_race.py for the reasoning.

Outputs (paths derived from the race):
  <race>_gc_time_corrections.json  — only the mismatched years, input to the
                                     apply_*_gc_corrections.py scripts
  <race>_gc_winner_times.json      — {year: pcs_winner_seconds} for every
                                     successfully scraped year, used by
                                     export_gc.py for per-rider totals.
                                     ONLY written with --write-winner-times.

WHY THAT FLAG EXISTS, AND THE INCONSISTENCY IT PRESERVES

The two originals disagreed: the Vuelta's wrote its winner-times file, the
Giro's did not. Merging them had to pick one, and picking either would have
changed a behaviour silently — so the flag keeps both exactly as they were
(check_vuelta_gc_times.py passes it, check_giro_gc_times.py does not) and makes
the difference one visible line instead of a divergence buried in 139
duplicated ones.

It is almost certainly drift rather than design, and worth resolving: as of
2026-08-22 NOTHING in this repo writes giro_gc_winner_times.json. export_gc.py
reads it through an f-string, and the file exists on disk, but no script
produces it — so whatever made it is gone. Turning the flag on for the Giro
would give it a writer again, at the cost of overwriting a file of unknown
provenance. That is a judgement call, not a refactor.

Usage:
  python3 check_gc_times.py --race vuelta 2020-2025
  python3 check_gc_times.py --race giro 1990
"""

import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

from race_common import RACES

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
    parts = t.strip().split(":")
    if len(parts) == 3:
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            return None
    return None


def seconds_to_hms(s: int) -> str:
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def extract_winner_time(html: str) -> int | None:
    """First H+:MM:SS time not preceded by '+' (gaps carry a '+' prefix)
    within a plausible Vuelta total-time range."""
    matches = re.findall(r'(?<!\+)(?<!\d)(\d{1,3}:\d{2}:\d{2})(?!\d)', html)
    for m in matches:
        secs = parse_time_to_seconds(m)
        # Vuelta winner totals range from ~40h (early short editions were
        # still 2,000+ km, so realistically 50h+) to ~250h
        if secs and 40 * 3600 < secs < 250 * 3600:
            return secs
    return None


def parse_year_args(args: list[str]) -> list[int] | None:
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
    return sorted(set(years)) if years else None


def main(argv=None):
    args = list(argv if argv is not None else sys.argv[1:])
    write_winner_times = "--write-winner-times" in args
    if write_winner_times:
        args.remove("--write-winner-times")
    # -h/--help used to fall through to a full run over every year, each one a
    # live PCS fetch. Discovered by doing it: `check_giro_gc_times.py --help`
    # spent five minutes hammering the site before it was killed.
    if "-h" in args or "--help" in args:
        print(__doc__.strip())
        return 0
    race_key = None
    if "--race" in args:
        i = args.index("--race")
        race_key = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if race_key not in RACES:
        print("Usage: python3 check_gc_times.py --race {giro|vuelta} "
              "[YEAR...] [--write-winner-times]")
        return 1
    race = RACES[race_key]
    winner_times_path = os.path.join(HERE, f"{race.cli}_gc_winner_times.json")
    corrections_path = os.path.join(HERE, f"{race.cli}_gc_time_corrections.json")

    requested_years = parse_year_args(args)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    race_row = cur.execute("SELECT race_id FROM races WHERE name=?", (race.name,)).fetchone()
    if not race_row:
        print(f"{race.name} not in DB")
        conn.close()
        sys.exit(1)
    race_id = race_row["race_id"]

    editions = cur.execute(
        "SELECT year, edition_id FROM race_editions WHERE race_id=? ORDER BY year",
        (race_id,),
    ).fetchall()

    winner_times = {}
    if os.path.exists(winner_times_path):
        with open(winner_times_path) as f:
            # Skip "_"-prefixed keys: these files carry a _README block
            # documenting where their values came from, the same convention
            # stage_notes.json and patched_values.json use.
            winner_times = {int(k): v for k, v in json.load(f).items()
                            if not k.startswith("_")}

    discrepancies = {}
    missing = []

    for edition in editions:
        year = edition["year"]
        edition_id = edition["edition_id"]

        if requested_years and year not in requested_years:
            continue

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

        url = f"{BASE}/race/{race.pcs_slug}/{year}/gc/result/result"
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

        winner_times[year] = pcs_time

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
    print(f"Winner times recorded: {len(winner_times)} years")
    print(f"Mismatches: {len(discrepancies)} years")
    if missing:
        print(f"Could not check: {missing}")

    if write_winner_times:
        with open(winner_times_path, "w") as f:
            json.dump({str(k): v for k, v in sorted(winner_times.items())}, f, indent=2)
        print(f"Winner times written to {winner_times_path}")

    if discrepancies:
        with open(corrections_path, "w") as f:
            json.dump({str(k): v for k, v in sorted(discrepancies.items())}, f, indent=2)
        print(f"Corrections written to {corrections_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
