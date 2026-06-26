#!/usr/bin/env python3
"""
Scrape per-stage KOM points from procyclingstats.com for all TdF editions.
Produces kom_points.json with the same structure as sprint_points.json:
  { "YEAR": [ {rider_slug: points, ...}, ... ], ... }
Array index = DB stage ordering (stage_number order).

Usage: python3 scrape_kom_points.py [--year YEAR] [--resume]
  --year YEAR   Only scrape a single year
  --resume      Skip years already present in kom_points.json
"""
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
OUT_PATH = os.path.join(HERE, "kom_points.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.5",
}

# Delay between requests (seconds) to be polite to PCS
REQUEST_DELAY = 1.5


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # stage doesn't exist
            print(f"  HTTP {e.code} on {url}, attempt {attempt+1}")
            if attempt < retries - 1:
                time.sleep(5)
    return None


def parse_kom_points(html):
    """
    Parse KOM points earned per rider on this stage from a PCS stage-kom page.
    Returns dict: rider_slug -> total KOM points earned on this stage.

    Two formats exist on PCS:
    - Modern: <h4>KOM Sprint | Location</h4> sub-tables with class="pnt" column
    - Old: KOM standings table with data-code="delta_pnt" column (points earned today)
    """
    totals = {}

    # --- Modern format: KOM Sprint sub-tables ---
    sections = re.split(r"<h4>KOM Sprint[^<]*</h4>", html)
    if len(sections) > 1:
        for sec in sections[1:]:
            tbl_end = sec.find("</table>")
            if tbl_end == -1:
                continue
            tbl = sec[:tbl_end]
            rows = re.split(r"<tr>", tbl)
            for row in rows[1:]:
                rider_m = re.search(r'href="(rider/[^"]+)"', row)
                pnt_m = re.search(r'class="pnt[^"]*"\s*>(\d+)<', row)
                if rider_m and pnt_m:
                    slug = rider_m.group(1)
                    totals[slug] = totals.get(slug, 0) + int(pnt_m.group(1))
        return totals

    # --- Old format: tab-based layout with separate POINTS and KOM resTab divs ---
    # Find the data-id for the tab labeled "KOM" (not "POINTS")
    kom_tab_id = None
    for tab_m in re.finditer(r'<li[^>]*data-id="(\d+)"[^>]*>(.*?)</li>', html, re.DOTALL):
        label = re.sub(r"<[^>]+>", "", tab_m.group(2)).strip().upper()
        if label == "KOM":
            kom_tab_id = tab_m.group(1)
            break

    # Narrow HTML to just the KOM resTab div if we found it
    search_html = html
    if kom_tab_id:
        kom_div_m = re.search(
            rf'<div[^>]*resTab[^>]*data-id="{re.escape(kom_tab_id)}"[^>]*>(.*?)</div>\s*</div>',
            html, re.DOTALL
        )
        if kom_div_m:
            search_html = kom_div_m.group(1)

    # Parse the delta_pnt column from the KOM standings table.
    # Older years (pre-~1960) use "pnt2" instead of "prev"; require only delta_pnt.
    for thead_m, tbody_m in re.findall(
        r"<thead>(.*?)</thead>\s*<tbody>(.*?)</tbody>", search_html, re.DOTALL
    ):
        cols = re.findall(r'data-code="([^"]+)"', thead_m)
        if "delta_pnt" not in cols:
            continue
        delta_idx = cols.index("delta_pnt")
        rows = re.findall(r"<tr>(.*?)</tr>", tbody_m, re.DOTALL)
        for row in rows:
            rider_m = re.search(r'href="(rider/[^"]+)"', row)
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if not rider_m or delta_idx >= len(tds):
                continue
            delta_raw = re.sub(r"<[^>]+>", "", tds[delta_idx]).strip().lstrip("+")
            if not delta_raw:
                continue
            try:
                pts = float(delta_raw)
                if pts > 0:
                    slug = rider_m.group(1)
                    totals[slug] = totals.get(slug, 0) + int(round(pts))
            except ValueError:
                pass
        break  # only need first matching table in the KOM section

    return totals


def stage_url_suffixes(year):
    """
    Return list of PCS URL suffixes to try for each stage, in DB stage_number order.
    PCS uses stage-N, stage-Na, stage-Nb for split stages, prologue, etc.
    We derive the right suffix from the stage_label we already computed.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT edition_id FROM race_editions WHERE year = ?", (year,)
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return []
    edition_id = row["edition_id"]

    cur.execute(
        """SELECT stage_number, stage_date, start_location, finish_location
           FROM stages WHERE edition_id = ? ORDER BY stage_number""",
        (edition_id,),
    )
    stages = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Reproduce the label logic from export_gc.py
    from collections import defaultdict
    date_groups = defaultdict(list)
    for i, s in enumerate(stages):
        date_groups[s.get("stage_date") or f"__nodate_{i}"].append(i)
    stage_labels = [""] * len(stages)
    day_counter = 0
    for date in sorted(date_groups.keys()):
        indices = date_groups[date]
        if len(indices) == 1:
            i = indices[0]
            if stages[i]["stage_number"] == 0:
                stage_labels[i] = "P"
            else:
                day_counter += 1
                stage_labels[i] = str(day_counter)
        else:
            day_counter += 1
            for j, i in enumerate(indices):
                stage_labels[i] = f"{day_counter}{'abcde'[j]}"

    # Convert label → PCS URL suffix
    suffixes = []
    for lbl in stage_labels:
        if lbl == "P":
            suffixes.append("prologue")
        else:
            # "1" → "stage-1", "1a" → "stage-1a"
            suffixes.append(f"stage-{lbl}")
    return suffixes


def scrape_year(year):
    base = f"https://www.procyclingstats.com/race/tour-de-france/{year}"
    suffixes = stage_url_suffixes(year)
    if not suffixes:
        print(f"  No stages found in DB for {year}")
        return None

    year_data = []
    for i, suffix in enumerate(suffixes):
        url = f"{base}/{suffix}-kom"
        print(f"  Stage {i} ({suffix}): {url}")
        html = fetch(url)
        time.sleep(REQUEST_DELAY)

        if html is None:
            print(f"    -> 404/error, storing empty dict")
            year_data.append({})
            continue

        pts = parse_kom_points(html)
        if pts:
            print(f"    -> {len(pts)} riders with KOM points: {list(pts.items())[:3]}")
        else:
            print(f"    -> no KOM sprint tables found")
        year_data.append(pts)

    return year_data


def main():
    args = sys.argv[1:]
    single_year = None
    resume = False
    i = 0
    while i < len(args):
        if args[i] == "--year" and i + 1 < len(args):
            single_year = int(args[i + 1])
            i += 2
        elif args[i] == "--resume":
            resume = True
            i += 1
        else:
            i += 1

    # Load existing data
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            all_data = json.load(f)
    else:
        all_data = {}

    # Get years from DB
    conn = sqlite3.connect(DB_PATH)
    years = [r[0] for r in conn.execute("SELECT year FROM race_editions ORDER BY year")]
    conn.close()

    if single_year:
        years = [single_year]

    for year in years:
        yr_str = str(year)
        if resume and yr_str in all_data:
            print(f"{year}: already present, skipping")
            continue

        print(f"\n=== {year} ===")
        data = scrape_year(year)
        if data is not None:
            all_data[yr_str] = data
            # Save after each year in case of interruption
            with open(OUT_PATH, "w", encoding="utf-8") as f:
                json.dump(all_data, f)
            print(f"  Saved {year} ({len(data)} stages)")

    print(f"\nDone. Output: {OUT_PATH}")


if __name__ == "__main__":
    main()
