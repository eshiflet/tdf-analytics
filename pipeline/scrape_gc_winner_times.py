#!/usr/bin/env python3
"""
Scrape the GC winner's total race time from Wikipedia for each Tour de France.

Stores results in tour_gc_winner_times.json as {year: seconds}.

Usage:
  python3 scrape_gc_winner_times.py          # all years with a race
  python3 scrape_gc_winner_times.py 1903 1960 2025   # specific years
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "tour_gc_winner_times.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; tdf-analytics/1.0)"}
DELAY = 1.5

# All Tour de France years (no race during WWI and WWII)
ALL_YEARS = [y for y in range(1903, 2026) if y not in range(1915, 1919) and y not in range(1940, 1947)]


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(5)
        except Exception:
            time.sleep(5)
    return None


def parse_time(s):
    """Convert 'Xh YY' ZZ"' (or variants) to total seconds. Returns None if parse fails."""
    s = s.replace("′", "'").replace("″", '"').replace(" ", " ").strip()
    # Formats seen on Wikipedia:
    #   "94h 33' 14"" or "94h33'14""  or "94 h 33 min 14 s"
    m = re.match(r"(\d+)\s*h\s*(\d+)['\s](\d+)", s)
    if m:
        h, mn, sec = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return h * 3600 + mn * 60 + sec
    # Try "Xh YY'" (no seconds)
    m = re.match(r"(\d+)\s*h\s*(\d+)", s)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        return h * 3600 + mn * 60
    return None


def scrape_winner_time(html):
    """
    Find the General Classification table and return the winner's time in seconds.
    Looks for rank '1' (skipping DSQ rows so we use the actual official winner).
    """
    # Find GC section anchor
    for anchor_pat in [
        r'id="General_classification"',
        r'id="Final_general_classification"',
        r'id="Overall_classification"',
    ]:
        m = re.search(anchor_pat, html)
        if m:
            break
    else:
        return None

    snippet = html[m.start(): m.start() + 20000]

    for t in re.finditer(r"<table[^>]*>(.*?)</table>", snippet, re.DOTALL):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t.group(1), re.DOTALL)
        if not rows:
            continue
        hdr_cells = re.findall(r"<th[^>]*>(.*?)</th>", rows[0], re.DOTALL)
        hdr = [re.sub(r"<[^>]+>", "", h).strip().lower() for h in hdr_cells]
        # Need a Rank/# column and a Time column
        has_rank = any(h in ("rank", "#", "") for h in hdr) or any("rank" in h for h in hdr)
        has_time = any("time" in h for h in hdr)
        if not (has_rank and has_time):
            continue

        def clean(td):
            t2 = re.sub(r"<[^>]+>", "", td)
            return t2.replace("\xa0", " ").replace("&#160;", " ").strip()

        for row in rows[1:]:
            tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
            if len(tds) < 3:
                continue
            rank_raw = clean(tds[0])
            # Skip DSQ / DNS rows; only take rank '1'
            if rank_raw != "1":
                continue
            # Time is usually the last column
            time_str = clean(tds[-1])
            secs = parse_time(time_str)
            if secs and secs > 50000:  # sanity: >~14 hours
                return secs
    return None


def main():
    year_args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    years = year_args if year_args else ALL_YEARS

    existing = {}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            existing = json.load(f)

    results = dict(existing)

    for year in years:
        if not year_args and str(year) in results:
            print(f"{year}: already have {results[str(year)]}s, skipping")
            continue

        url = f"https://en.wikipedia.org/wiki/{year}_Tour_de_France"
        print(f"{year}: fetching ... ", end="", flush=True)
        html = fetch(url)
        time.sleep(DELAY)

        if not html:
            print("FAILED")
            continue

        secs = scrape_winner_time(html)
        if secs:
            results[str(year)] = secs
            h, rem = divmod(secs, 3600)
            mn, s = divmod(rem, 60)
            print(f"{h}h {mn:02d}' {s:02d}\"  ({secs}s)")
        else:
            print("could not parse winner time")

    results = dict(sorted(results.items(), key=lambda x: int(x[0])))
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {len(results)} years to {OUT_PATH}")


if __name__ == "__main__":
    main()
