#!/usr/bin/env python3
"""
Scrape per-stage sprint points classifications from PCS for years 2000–2010
where the existing data only has intermediate sprint checkpoint bonuses.

For each stage, fetches:
  procyclingstats.com/race/tour-de-france/YEAR/stage-N-points

This gives CUMULATIVE sprint points after each stage. We compute the
per-stage INCREMENT and store it in tour_sprint_points.json (replacing old bad data).

Usage:
  python3 scrape_sprint_per_stage.py              # default target years (2000–2010)
  python3 scrape_sprint_per_stage.py 2010         # single year
  python3 scrape_sprint_per_stage.py 2008 2009    # specific years
"""

import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from race_common import exit_on_help

HERE        = os.path.dirname(os.path.abspath(__file__))
SPRINT_PATH = os.path.join(HERE, "tour_sprint_points.json")
DB_PATH     = os.path.join(HERE, "cycling.db")

TARGET_YEARS = [1997, 1999] + list(range(2000, 2011)) + [2012, 2013, 2019]

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
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 500):
                return None
            if e.code == 403:
                print(f"    HTTP 403 rate-limited, waiting 30s...")
                time.sleep(30)
            else:
                print(f"    HTTP {e.code} (attempt {attempt+1})")
                time.sleep(5)
        except Exception as ex:
            print(f"    Error: {ex} (attempt {attempt+1})")
            time.sleep(5)
    return None


def td_text(td):
    return " ".join(re.sub(r"<[^>]+>", "", td).split())


def parse_points_table(html):
    """
    Parse a PCS points classification page (per-stage or year-level).

    Returns list of {rider_slug, pnt2, rnk} sorted by rnk ascending.

    Handles two page structures:
    1. Tabbed page (year-level /points): looks for tab labeled POINTS,
       then finds the matching resTab div.
    2. Direct table (per-stage /stage-N/points): finds a <table> with
       pnt2 column in thead.
    """
    # ── Strategy 1: tabbed page (year-level) ──────────────────────────────────
    pts_tab_id = None
    for m in re.finditer(r'<li[^>]*data-id="(\d+)"[^>]*>(.*?)</li>', html, re.DOTALL):
        label = re.sub(r"<[^>]+>", "", m.group(2)).strip().upper()
        if label == "POINTS":
            pts_tab_id = m.group(1)
            break

    if pts_tab_id:
        div_m = re.search(
            rf'<div[^>]*resTab[^>]*data-id="{re.escape(pts_tab_id)}"[^>]*>(.*?)</div>\s*</div>',
            html, re.DOTALL,
        )
        if div_m:
            frag = div_m.group(1)
            result = _parse_table_fragment(frag)
            if result:
                return result

    # ── Strategy 2: direct table ───────────────────────────────────────────────
    # On per-stage pages the points standings are usually the main/only table.
    # Find all <table> blocks and try each one for a pnt2 column.
    for table_m in re.finditer(r"<table[^>]*>(.*?)</table>", html, re.DOTALL):
        result = _parse_table_fragment(table_m.group(1))
        if result:
            return result

    # ── Strategy 3: look for any resTab div ───────────────────────────────────
    for div_m in re.finditer(r'<div[^>]*resTab[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL):
        result = _parse_table_fragment(div_m.group(1))
        if result:
            return result

    return []


def _parse_table_fragment(frag):
    """Parse a table fragment (thead + tbody) for pnt2 column data."""
    thead_m = re.search(r"<thead>(.*?)</thead>", frag, re.DOTALL)
    if not thead_m:
        return []

    # Try data-code attributes first (PCS standard)
    cols = re.findall(r'data-code="([^"]+)"', thead_m.group(1))
    if "pnt2" not in cols:
        # Fallback: look for th text containing "pnt2"
        ths = re.findall(r"<th[^>]*>(.*?)</th>", thead_m.group(1), re.DOTALL)
        col_texts = [td_text(th).lower() for th in ths]
        if "pnt2" in col_texts:
            cols = col_texts
        else:
            return []

    pnt2_idx  = cols.index("pnt2")
    rnk_idx   = cols.index("rnk") if "rnk" in cols else 0
    rider_idx = cols.index("ridername") if "ridername" in cols else None

    tbody_m = re.search(r"<tbody>(.*?)</tbody>", frag, re.DOTALL)
    if not tbody_m:
        return []

    results = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody_m.group(1), re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        if pnt2_idx >= len(tds):
            continue
        try:
            pnt2 = int(td_text(tds[pnt2_idx]))
            rnk_raw = td_text(tds[rnk_idx]) if rnk_idx < len(tds) else ""
            rnk = int(rnk_raw) if rnk_raw.isdigit() else len(results) + 1
        except (ValueError, TypeError):
            continue

        rider_td = tds[rider_idx] if rider_idx is not None and rider_idx < len(tds) else ""
        slug_m = re.search(r'href="(rider/[a-z0-9-]+)"', rider_td)
        if not slug_m:
            continue
        rider_slug = slug_m.group(1)

        results.append({"rnk": rnk, "rider_slug": rider_slug, "pnt2": pnt2})

    results.sort(key=lambda r: r["rnk"])
    return results


def get_stages(year):
    """
    Return ordered list of (stage_number, pcs_slug) from the DB.
    stage_number=0 → 'prologue', else 'stage-N'.
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        """
        SELECT s.stage_number, s.stage_date
        FROM stages s
        JOIN race_editions re ON s.edition_id = re.edition_id
        WHERE re.year = ?
        ORDER BY s.stage_date, s.stage_number
        """,
        (year,),
    )
    rows = cur.fetchall()
    con.close()

    result = []
    for row in rows:
        n = row["stage_number"]
        slug = "prologue" if n == 0 else f"stage-{n}"
        result.append((n, slug))
    return result


def scrape_year(year):
    """
    Scrape per-stage cumulative sprint points for a year.
    Returns list of per-stage increment dicts (indexed by stage position).
    """
    stages = get_stages(year)
    if not stages:
        print(f"  No stages found in DB for {year}")
        return None

    print(f"  {len(stages)} stages")

    # cumulative points from previous stage (rider_slug → int)
    prev_cum = {}
    increments = []

    for stage_num, slug in stages:
        url = f"https://www.procyclingstats.com/race/tour-de-france/{year}/{slug}-points"
        print(f"  {slug}: {url} ...", end=" ", flush=True)

        html = fetch(url)
        time.sleep(DELAY)

        if not html:
            print("FAILED (fetch)")
            increments.append({})
            continue

        riders = parse_points_table(html)
        if not riders:
            print("no data parsed")
            increments.append({})
            continue  # keep prev_cum — cumulative carries forward

        # Build cumulative dict for this stage
        cum = {r["rider_slug"]: r["pnt2"] for r in riders}

        # Compute increments: this stage's points = cum_now - cum_before
        stage_inc = {}
        for slug_r, total in cum.items():
            prev = prev_cum.get(slug_r, 0)
            delta = total - prev
            if delta > 0:
                stage_inc[slug_r] = delta
            elif delta < 0:
                # Shouldn't happen; data inconsistency — skip
                print(f"\n    Warning: negative delta for {slug_r}: {prev}→{total}")

        leader = riders[0]
        print(f"{len(riders)} riders | leader {leader['rider_slug']} pnt2={leader['pnt2']} | +{sum(stage_inc.values())} pts this stage")

        increments.append(stage_inc)
        prev_cum = cum

    return increments


def main():
    exit_on_help(__doc__)
    year_args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    years = year_args if year_args else TARGET_YEARS

    with open(SPRINT_PATH, encoding="utf-8") as f:
        sprint_pts = json.load(f)

    for year in years:
        print(f"\n{year}:", flush=True)
        increments = scrape_year(year)
        if increments is None:
            continue

        yr_str = str(year)
        old_len = len(sprint_pts.get(yr_str, []))
        print(f"  Replacing {old_len}-stage array with {len(increments)}-stage array")
        sprint_pts[yr_str] = increments

        # Save after each year so interruptions don't lose progress
        sprint_pts_sorted = dict(sorted(sprint_pts.items(), key=lambda x: int(x[0])))
        with open(SPRINT_PATH, "w", encoding="utf-8") as f:
            json.dump(sprint_pts_sorted, f, ensure_ascii=False)
        print(f"  Saved {SPRINT_PATH}")

    print("\nDone.")


if __name__ == "__main__":
    main()
