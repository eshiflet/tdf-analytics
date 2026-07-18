#!/usr/bin/env python3
"""
Patch stage route_type from Wikipedia for years where PCS profile icons
don't distinguish mountain/flat/TT correctly.

Wikipedia stage type → DB route_type mapping:
  "Plain stage"              → F
  "Stage with mountain(s)"   → M
  "Individual time trial"    → TT
  "Mountain time trial"      → TT
  "Hilly stage"              → H   (exists in some eras)
  "Team time trial"          → TTT

Usage:
  python3 patch_route_types_wikipedia.py              # all years in DB
  python3 patch_route_types_wikipedia.py 1910 1925   # specific years
  python3 patch_route_types_wikipedia.py --dry-run
"""

import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; tdf-analytics/1.0)"}
DELAY = 1.5

TYPE_MAP = {
    "plain stage":            "F",
    "stage with mountain(s)": "M",
    "mountain stage":         "M",
    "individual time trial":  "TT",
    "mountain time trial":    "TT",
    "hilly stage":            "H",
    "team time trial":        "TTT",
}


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


def parse_stages_wikipedia(html):
    """
    Returns ordered list of (stage_label, route_type) from Wikipedia stages table.
    stage_label is the text of the first <th> cell (e.g. "1", "2a", "P").
    """
    # Find the first wikitable that contains stage type data
    tables = re.findall(r'<table[^>]*wikitable[^>]*>(.*?)</table>', html, re.DOTALL)
    for tbl in tables:
        if not ('Plain stage' in tbl or 'Plainstage' in tbl or
                'mountain' in tbl.lower() or 'time trial' in tbl.lower()):
            continue

        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tbl, re.DOTALL)
        if not rows:
            continue

        # Identify the Type column index from the header
        hdr_row = rows[0]
        ths = re.findall(r'<th[^>]*>(.*?)</th>', hdr_row, re.DOTALL)
        type_col = None
        for i, th in enumerate(ths):
            txt = re.sub(r'<[^>]+>', '', th).strip().lower()
            if 'type' in txt:
                type_col = i
                break

        results = []
        for row in rows[1:]:
            # Stage label from first <th>
            th_m = re.search(r'<th[^>]*>(.*?)</th>', row, re.DOTALL)
            if not th_m:
                continue
            label_raw = re.sub(r'<[^>]+>', '', th_m.group(1)).strip()
            # Normalize: "1", "2a", "P", "21b" etc.
            label = label_raw.lower().replace('\xa0', '').replace(' ', '')
            if not label or label in ('stage', 'total', 'rest'):
                continue

            tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)

            # Find the type text. When type_col is known, try that td index;
            # otherwise scan all tds for a known type keyword.
            route_type = None

            # Try type_col - 1 because th takes slot 0 (th is NOT in tds list)
            if type_col is not None and (type_col - 1) < len(tds):
                td = tds[type_col - 1]
                txt = re.sub(r'<[^>]+>', '', td).strip().lower()
                route_type = TYPE_MAP.get(txt)

            # Fallback: scan all tds for a type keyword
            if not route_type:
                for td in tds:
                    txt = re.sub(r'<[^>]+>', '', td).strip().lower()
                    rt = TYPE_MAP.get(txt)
                    if rt:
                        route_type = rt
                        break

            # Also check image src filenames (e.g. Plainstage.svg, Mountainstage.svg)
            if not route_type:
                for td in tds:
                    src_m = re.search(r'src="([^"]*(?:stage|trial)[^"]*\.(?:svg|png))"', td, re.I)
                    if src_m:
                        fname = src_m.group(1).lower()
                        if 'plain' in fname:
                            route_type = 'F'
                        elif 'mountain' in fname and 'trial' in fname:
                            route_type = 'TT'
                        elif 'mountain' in fname:
                            route_type = 'M'
                        elif 'hilly' in fname:
                            route_type = 'H'
                        elif 'ttt' in fname or 'teamtime' in fname:
                            route_type = 'TTT'
                        elif 'time' in fname or 'itt' in fname:
                            route_type = 'TT'
                        if route_type:
                            break

            if route_type:
                results.append((label, route_type))

        if results:
            return results

    return []


def stage_label_to_db_number(label, year_stages):
    """
    Map a Wikipedia stage label (e.g. "1", "2a", "p") to the DB stage_number.
    year_stages: list of (stage_number, stage_label) from DB.
    """
    label = label.lower().strip()

    # Direct match on DB stage_label (strip "Stage " prefix)
    for sn, sl in year_stages:
        sl_norm = (sl or "").lower().replace("stage ", "").replace("prologue", "p").strip()
        if sl_norm == label:
            return sn

    # Try matching just the numeric part for simple cases
    if label.isdigit():
        n = int(label)
        # Count non-split stages up to this number
        count = 0
        for sn, sl in year_stages:
            sl_n = (sl or "").lower().replace("stage ", "").strip()
            if sl_n.isdigit():
                count += 1
                if count == n:
                    return sn

    return None


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    year_args = [int(a) for a in args if a.isdigit()]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    all_years = [r[0] for r in conn.execute(
        "SELECT year FROM race_editions ORDER BY year"
    )]
    years = year_args if year_args else all_years

    total_updated = 0

    for year in years:
        url = f"https://en.wikipedia.org/wiki/{year}_Tour_de_France"
        print(f"{year}: {url} ...", end=" ", flush=True)

        html = fetch(url)
        time.sleep(DELAY)

        if not html:
            print("fetch failed")
            continue

        wiki_stages = parse_stages_wikipedia(html)
        if not wiki_stages:
            print("no stage type data found")
            continue

        print(f"{len(wiki_stages)} stages")

        # Load DB stages for this year
        edition_row = conn.execute(
            "SELECT edition_id FROM race_editions WHERE race_id=(SELECT race_id FROM races WHERE name='Tour de France') AND year=?", (year,)
        ).fetchone()
        if not edition_row:
            print(f"  not in DB")
            continue
        edition_id = edition_row["edition_id"]

        db_stages = [(r["stage_number"], r["stage_label"]) for r in conn.execute(
            "SELECT stage_number, stage_label FROM stages WHERE edition_id=? ORDER BY stage_number",
            (edition_id,)
        )]

        year_updated = 0

        # If Wikipedia stage count == DB stage count, use positional matching
        use_positional = (len(wiki_stages) == len(db_stages))
        if use_positional:
            print(f"  Using positional matching ({len(db_stages)} stages)")

        for pos, (label, wiki_rt) in enumerate(wiki_stages):
            if use_positional:
                sn = db_stages[pos][0]
            else:
                sn = stage_label_to_db_number(label, db_stages)
            if sn is None:
                print(f"  Warning: can't match label '{label}' to a DB stage")
                continue

            # Get current route_type
            cur_row = conn.execute(
                "SELECT route_type FROM stages WHERE edition_id=? AND stage_number=?",
                (edition_id, sn)
            ).fetchone()
            if not cur_row:
                continue
            cur_rt = cur_row["route_type"]

            # Only update if it changes something meaningful
            if cur_rt == wiki_rt:
                continue

            # Don't overwrite TT/TTT with a non-TT Wikipedia value
            # (won_how detection is more reliable for TT)
            if cur_rt in ("TT", "TTT") and wiki_rt not in ("TT", "TTT"):
                continue

            if not dry_run:
                conn.execute(
                    "UPDATE stages SET route_type=? WHERE edition_id=? AND stage_number=?",
                    (wiki_rt, edition_id, sn)
                )
            print(f"  Stage {sn} ('{label}'): {cur_rt} → {wiki_rt}")
            year_updated += 1

        if year_updated and not dry_run:
            conn.commit()
        total_updated += year_updated
        if year_updated == 0:
            print(f"  (no changes)")

    print(f"\nTotal stages updated: {total_updated}")
    conn.close()


if __name__ == "__main__":
    main()
