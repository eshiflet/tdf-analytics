#!/usr/bin/env python3
"""
Patch KOM final standings from Wikipedia for years where PCS only has top 3.

Fetches the "Mountains classification" table (top 10) from Wikipedia and
merges into the last stage slot of kom_points_reconciled.json, only adding
riders not already present.

Usage:
  python3 patch_kom_wikipedia.py              # all years with < 10 riders
  python3 patch_kom_wikipedia.py 1933 1936    # specific years
"""

import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
KOM_PATH = os.path.join(HERE, "kom_points_reconciled.json")
DB_PATH = os.path.join(HERE, "cycling.db")

TARGET_YEARS = list(range(1933, 1939))
MIN_RIDERS = 10  # patch years with fewer than this many riders

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; tdf-analytics/1.0)"}
DELAY = 1.5


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


def normalize(s):
    """Lowercase, strip accents, collapse whitespace."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def build_name_lookup(conn):
    """
    Build {normalized_full_name: rider_id} where full_name is stored as
    'Lastname Firstname' in the DB, so we index both 'lastname firstname'
    and 'firstname lastname'.
    """
    lookup = {}
    for rider_id, full_name in conn.execute("SELECT rider_id, full_name FROM riders"):
        parts = full_name.strip().split()
        # DB format: Lastname Firstname → also try Firstname Lastname
        norm_db = normalize(full_name)
        norm_rev = normalize(" ".join(reversed(parts))) if len(parts) >= 2 else norm_db
        lookup[norm_db] = rider_id
        lookup[norm_rev] = rider_id
    return lookup


def parse_kom_standings(html):
    """
    Parse the final Mountains classification table from a Wikipedia TdF page.
    Returns list of (rank, name, points) for up to 10 riders.
    """
    idx = html.find('id="Mountains_classification"')
    if idx == -1:
        return []
    snippet = html[idx:idx + 15000]

    for t in re.finditer(r"<table[^>]*>(.*?)</table>", snippet, re.DOTALL):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t.group(1), re.DOTALL)
        if not rows:
            continue
        # Check header has Rank and Rider columns
        hdr_cells = re.findall(r"<th[^>]*>(.*?)</th>", rows[0], re.DOTALL)
        hdr = [re.sub(r"<[^>]+>", "", h).strip().lower() for h in hdr_cells]
        if not any("rank" in h for h in hdr) or not any("rider" in h for h in hdr):
            continue

        results = []
        for row in rows[1:]:
            tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
            if len(tds) < 3:
                continue

            def clean(td):
                return re.sub(r"<[^>]+>", "", td).replace("\xa0", " ").replace("&#160;", " ").strip()

            rank_raw = clean(tds[0])
            rider_raw = clean(tds[1])
            pts_raw = clean(tds[-1])

            pts_m = re.match(r"[\d.]+", pts_raw)
            if not pts_m:
                continue
            try:
                pts = int(pts_m.group())
            except ValueError:
                continue

            # Strip nationality "(ESP)" etc. from rider name
            name = re.sub(r"\s*\([A-Z]{2,3}\)\s*", "", rider_raw).strip()
            results.append((rank_raw, name, pts))

        if results:
            return results

    return []


def main():
    year_args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    years = year_args if year_args else TARGET_YEARS

    conn = sqlite3.connect(DB_PATH)
    name_lookup = build_name_lookup(conn)
    conn.close()

    with open(KOM_PATH, encoding="utf-8") as f:
        kom: dict = json.load(f)

    for year in years:
        yr_str = str(year)
        stages_list = kom.get(yr_str, [])
        if not stages_list:
            print(f"{year}: no KOM data in file, skipping")
            continue

        # Find last non-empty stage (has the final totals)
        last_idx = len(stages_list) - 1
        while last_idx > 0 and not stages_list[last_idx]:
            last_idx -= 1
        current = stages_list[last_idx]

        if len(current) >= MIN_RIDERS and not year_args:
            print(f"{year}: already has {len(current)} riders, skipping")
            continue

        url = f"https://en.wikipedia.org/wiki/{year}_Tour_de_France"
        print(f"{year}: fetching {url} ...", end=" ", flush=True)
        html = fetch(url)
        time.sleep(DELAY)

        if not html:
            print("fetch failed")
            continue

        wiki_rows = parse_kom_standings(html)
        if not wiki_rows:
            print("no mountains classification table found")
            continue

        print(f"{len(wiki_rows)} riders from Wikipedia")

        added = 0
        unmatched = []
        for rank, name, pts in wiki_rows:
            norm = normalize(name)
            rider_id = name_lookup.get(norm)
            if not rider_id:
                unmatched.append(name)
                continue
            if rider_id in current:
                print(f"  already present: {name} ({rider_id}) = {current[rider_id]}")
            else:
                current[rider_id] = pts
                print(f"  added rank {rank}: {name} ({rider_id}) = {pts}")
                added += 1

        if unmatched:
            print(f"  WARNING: could not match: {unmatched}")

        stages_list[last_idx] = current
        kom[yr_str] = stages_list
        print(f"  → {added} new riders added (total now {len(current)})")

    kom = dict(sorted(kom.items(), key=lambda x: int(x[0])))
    with open(KOM_PATH, "w", encoding="utf-8") as f:
        json.dump(kom, f, ensure_ascii=False)
    print(f"\nWrote {KOM_PATH}")


if __name__ == "__main__":
    main()
