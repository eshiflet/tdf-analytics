#!/usr/bin/env python3
"""
Scrape PCS per-stage GC pages for the Vuelta a España (or, with --race giro,
the Giro d'Italia — same page structure, different URL path and scrape dir).

For each race day of each requested year, fetches
/race/{race-path}/YEAR/{slug}-gc and saves a JSON file with:
  - info block (Date, Distance, Start, Finish, Won how, ...)
  - profile_icon
  - result_rows: the full stage-result table (same 15-column row format
    as vuelta_scrapes/YEAR/stage_N.json "rows")
  - gc_rows: the GC-standings table PCS shows after that stage
    ([gc_rank, prev_rank, rider_slug, rider_name, time_txt]; time_txt is
    the leader's absolute cumulative time on rank 1, a gap otherwise)

Output: vuelta_scrapes/YEAR/gc_pages/{slug}.json, plus _slugs.json with the
race-day slug list from the PCS stage dropdown (prologue, stage-1, stage-8a...).

Historical PCS stage-result pages (pre-1998) embed GC standings for only a
handful of riders; these pages are the authoritative source for whatever
per-stage GC PCS actually has. Used by build_vuelta_gc_standings.py.

Usage:
  python3 scrape_vuelta_gc_pages.py 1979-1997        # resumable; skips saved slugs
  python3 scrape_vuelta_gc_pages.py --race giro 1909-1997
  SCRAPE_DELAY=5 python3 scrape_vuelta_gc_pages.py 1990
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://www.procyclingstats.com"

# --race selects the PCS URL path segment and the scrape directory
RACES = {
    "vuelta": ("vuelta-a-espana", "vuelta_scrapes"),
    "giro": ("giro-d-italia", "giro_scrapes"),
}
RACE = "vuelta"
if "--race" in sys.argv:
    RACE = sys.argv[sys.argv.index("--race") + 1]
    if RACE not in RACES:
        sys.exit(f"error: unknown race '{RACE}' (use {'/'.join(RACES)})")
RACE_PATH, _scrapes_dirname = RACES[RACE]
SCRAPES_DIR = os.path.join(HERE, _scrapes_dirname)

# From scrape_race, not scrape_vuelta. The Giro/Vuelta scrapers were merged on
# 2026-08-22 and scrape_vuelta.py became a thin wrapper exporting only main(),
# which left this import raising ImportError on every run. Nothing caught it:
# this script has no tests and CI never invokes it. The --help audit that added
# the guard below is what surfaced it.
from scrape_race import (  # noqa: E402
    HEADERS, td_text, dedup_time, parse_profile_icon, parse_info,
    parse_rows, parse_year_args,
)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from race_common import exit_on_help

DELAY = float(os.environ.get("SCRAPE_DELAY", "3.5"))


def fetch(url: str, max_tries: int = 8) -> str | None:
    for attempt in range(max_tries):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                html = r.read().decode("utf-8", errors="replace")
            if "Just a moment" in html and len(html) < 10000:
                print(f"    Cloudflare challenge, waiting 30s ({url})", flush=True)
                time.sleep(30)
                continue
            time.sleep(DELAY)
            return html
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 30 + attempt * 15
                print(f"    429, backing off {wait}s ({url})", flush=True)
                time.sleep(wait)
                continue
            if e.code in (404, 410):
                time.sleep(DELAY)
                return None
            print(f"    HTTP {e.code} ({url})", flush=True)
            time.sleep(10)
        except Exception as e:
            print(f"    Error {e} ({url})", flush=True)
            time.sleep(10)
    return None


def get_slugs(year: int) -> list[str] | None:
    html = fetch(f"{BASE}/race/{RACE_PATH}/{year}/gc")
    if not html:
        return None
    opts = re.findall(
        rf'<option value="(race/{RACE_PATH}/{year}/(?:prologue|stage-\d+[a-z]?)/result/result)"',
        html,
    )
    slugs = []
    for v in opts:
        slug = v.split("/")[3]
        if slug not in slugs:
            slugs.append(slug)
    return slugs or None


def split_tables(html: str) -> list[tuple[list[str], str]]:
    out = []
    for t in re.findall(r"<table[^>]*>(.*?)</table>", html, re.DOTALL):
        headers = [td_text(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", t, re.DOTALL)]
        out.append((headers, t))
    return out


def parse_gc_rows(html: str) -> list[list]:
    """Rows of the GC-standings table (the one with a 'Prev' column)."""
    for headers, t in split_tables(html):
        if "Prev" not in headers:
            continue
        tbody_m = re.search(r"<tbody>(.*?)</tbody>", t, re.DOTALL)
        if not tbody_m:
            continue
        time_idx = headers.index("Time") if "Time" in headers else None
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody_m.group(1), re.DOTALL):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
            if len(tds) < 5:
                continue
            texts = [td_text(x) for x in tds]
            rnk, prev = texts[0], texts[1]
            slug_m = re.search(r'href="/?([^"]*rider/[a-z0-9-]+)"', tr)
            slug = slug_m.group(1).lstrip("/") if slug_m else ""
            name = ""
            anchor_m = re.search(r'<a[^>]*href="[^"]*rider/[^"]*"[^>]*>(.*?)</a>', tr, re.DOTALL)
            if anchor_m:
                name = td_text(anchor_m.group(1))
            time_txt = ""
            if time_idx is not None and time_idx < len(texts):
                time_txt = dedup_time(texts[time_idx].replace(" ", ""))
            if slug and rnk:
                rows.append([rnk, prev, slug, name, time_txt])
        if rows:
            return rows
    return []


def parse_result_rows(html: str) -> list[list]:
    """Full stage-result table (Rnk header, no Prev column), 15-col row format."""
    for headers, t in split_tables(html):
        if "Rnk" not in headers or "Prev" in headers:
            continue
        rows = parse_rows(t)
        if rows:
            return rows
    return []


def scrape_slug(year: int, slug: str) -> dict | None:
    html = fetch(f"{BASE}/race/{RACE_PATH}/{year}/{slug}-gc")
    result_rows = parse_result_rows(html) if html else []
    gc_rows = parse_gc_rows(html) if html else []
    if not result_rows and not gc_rows:
        # prologue-gc does not exist on PCS; fall back to the plain page
        html = fetch(f"{BASE}/race/{RACE_PATH}/{year}/{slug}")
        if not html:
            return None
        result_rows = parse_result_rows(html)
        gc_rows = parse_gc_rows(html)
        if not result_rows and not gc_rows:
            return None
    return {
        "year": year,
        "slug": slug,
        "info": parse_info(html),
        "profile_icon": parse_profile_icon(html),
        "result_rows": result_rows,
        "gc_rows": gc_rows,
    }


def main():
    exit_on_help(__doc__)
    years = parse_year_args(sys.argv[1:])
    if not years:
        print("Usage: python3 scrape_vuelta_gc_pages.py YEAR [YEAR_START-YEAR_END ...]")
        sys.exit(1)

    for year in years:
        out_dir = os.path.join(SCRAPES_DIR, str(year), "gc_pages")
        os.makedirs(out_dir, exist_ok=True)
        slugs_path = os.path.join(out_dir, "_slugs.json")
        if os.path.exists(slugs_path):
            with open(slugs_path) as f:
                slugs = json.load(f)
        else:
            slugs = get_slugs(year)
            if not slugs:
                print(f"{year}: FAILED to get stage list", flush=True)
                continue
            with open(slugs_path, "w") as f:
                json.dump(slugs, f)
        print(f"{year}: {len(slugs)} race days: {' '.join(slugs)}", flush=True)

        for slug in slugs:
            out_path = os.path.join(out_dir, f"{slug}.json")
            if os.path.exists(out_path):
                continue
            data = scrape_slug(year, slug)
            if data is None:
                print(f"  {year}/{slug}: FAILED", flush=True)
                continue
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"  {year}/{slug}: {len(data['result_rows'])}res {len(data['gc_rows'])}gc "
                  f"date={data['info'].get('Date')}", flush=True)

    print("DONE", flush=True)


if __name__ == "__main__":
    main()
