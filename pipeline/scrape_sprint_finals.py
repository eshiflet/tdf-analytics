#!/usr/bin/env python3
"""
Scrape final sprint (points) classification totals from PCS for years
where per-stage data isn't available (1953–1963).

Source: procyclingstats.com/race/tour-de-france/YEAR/points  (POINTS tab, pnt2 col)

Writes final totals into the LAST stage slot of tour_sprint_points.json.

Actual pnt2 values from PCS are stored as-is for all years.

Golf scoring years (1953–1958): lower pnt2 = better rank.
Modern scoring years (1959+): higher pnt2 = better rank.

Usage:
  python3 scrape_sprint_finals.py              # default target years
  python3 scrape_sprint_finals.py 1958 1963   # specific years
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from race_common import exit_on_help

HERE = os.path.dirname(os.path.abspath(__file__))
SPRINT_PATH = os.path.join(HERE, "tour_sprint_points.json")

# Years where lower pnt2 = better (golf scoring)
GOLF_YEARS = set(range(1953, 1959))

TARGET_YEARS = list(range(1953, 1964)) + [1997, 1999] + list(range(2000, 2011)) + [2012, 2013, 2019]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}
DELAY = 1.5


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 500):
                return None
            time.sleep(5)
        except Exception:
            time.sleep(5)
    return None


def parse_points_final(html):
    """
    Parse POINTS tab from a /race/.../YEAR/points page.
    Returns list of {rider_slug, pnt2, rnk} sorted by rnk ascending.
    """
    pts_tab_id = None
    for m in re.finditer(r'<li[^>]*data-id="(\d+)"[^>]*>(.*?)</li>', html, re.DOTALL):
        label = re.sub(r'<[^>]+>', '', m.group(2)).strip().upper()
        if label == 'POINTS':
            pts_tab_id = m.group(1)
            break
    if not pts_tab_id:
        return []

    div_m = re.search(
        rf'<div[^>]*resTab[^>]*data-id="{re.escape(pts_tab_id)}"[^>]*>(.*?)</div>\s*</div>',
        html, re.DOTALL
    )
    if not div_m:
        return []
    frag = div_m.group(1)

    thead_m = re.search(r'<thead>(.*?)</thead>', frag, re.DOTALL)
    if not thead_m:
        return []
    cols = re.findall(r'data-code="([^"]+)"', thead_m.group(1))
    if 'pnt2' not in cols:
        return []

    pnt2_idx  = cols.index('pnt2')
    rnk_idx   = cols.index('rnk') if 'rnk' in cols else 0
    rider_idx = cols.index('ridername') if 'ridername' in cols else None

    tbody_m = re.search(r'<tbody>(.*?)</tbody>', frag, re.DOTALL)
    if not tbody_m:
        return []

    def td_text(td):
        return ' '.join(re.sub(r'<[^>]+>', '', td).split())

    results = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tbody_m.group(1), re.DOTALL):
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
        if pnt2_idx >= len(tds):
            continue
        try:
            pnt2 = int(td_text(tds[pnt2_idx]))
            rnk_raw = td_text(tds[rnk_idx]) if rnk_idx < len(tds) else ''
            rnk = int(rnk_raw) if rnk_raw.isdigit() else len(results) + 1
        except (ValueError, TypeError):
            continue

        rider_td = tds[rider_idx] if rider_idx is not None and rider_idx < len(tds) else ''
        slug_m = re.search(r'href="(rider/[a-z0-9-]+)"', rider_td)
        if not slug_m:
            continue
        rider_slug = slug_m.group(1)

        results.append({'rnk': rnk, 'rider_slug': rider_slug, 'pnt2': pnt2})

    results.sort(key=lambda r: r['rnk'])
    return results


def main():
    exit_on_help(__doc__)
    year_args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    years = year_args if year_args else TARGET_YEARS

    with open(SPRINT_PATH, encoding='utf-8') as f:
        sprint_pts: dict = json.load(f)

    for year in years:
        url = f"https://www.procyclingstats.com/race/tour-de-france/{year}/points"
        print(f"{year}: {url} ...", end=' ', flush=True)
        html = fetch(url)
        time.sleep(DELAY)

        if not html:
            print("fetch failed")
            continue

        riders = parse_points_final(html)
        if not riders:
            print("no POINTS tab or pnt2 column")
            continue

        golf = year in GOLF_YEARS
        leader = riders[0]
        print(f"{len(riders)} riders | {'golf' if golf else 'modern'} scoring | "
              f"leader rnk={leader['rnk']} pnt2={leader['pnt2']} {leader['rider_slug']}")

        # Store raw pnt2 values as-is (matching Wikipedia/PCS)
        stage_dict = {r['rider_slug']: r['pnt2'] for r in riders}

        yr_str = str(year)
        stages_list = sprint_pts.get(yr_str, [])
        if not stages_list:
            # Build from tdf_YEAR_full.json stage count
            full_path = os.path.join(HERE, f"tdf_{year}_full.json")
            if os.path.exists(full_path):
                with open(full_path) as f:
                    bundle = json.load(f)
                stages_list = [{} for _ in range(len(bundle.get('stages', [])))]
            else:
                print(f"  Warning: no stage count source for {year}")
                continue

        stages_list[-1] = stage_dict
        sprint_pts[yr_str] = stages_list

    sprint_pts = dict(sorted(sprint_pts.items(), key=lambda x: int(x[0])))
    with open(SPRINT_PATH, 'w', encoding='utf-8') as f:
        json.dump(sprint_pts, f, ensure_ascii=False)
    print(f"\nWrote {SPRINT_PATH}")


if __name__ == '__main__':
    main()
