#!/usr/bin/env python3
"""
Scrape final KOM classification totals from PCS for pre-1960 years.

Source: procyclingstats.com/race/tour-de-france/YEAR/kom  (KOM tab, pnt2 column)

Does two things:
  1. Writes the final totals into the LAST stage entry of tour_kom_points.json
     so the bump chart shows the correct KOM ranking at the end of the race.
  2. Injects KOM classification rows into tdf_YEAR_full.json so that
     add_pre1960.py will insert them into classification_standings.

Usage:
  python3 scrape_pcs_kom_finals.py              # all target years
  python3 scrape_pcs_kom_finals.py 1939 1952   # specific years
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
KOM_PTS_PATH = os.path.join(HERE, "tour_kom_points.json")

TARGET_YEARS = [1939] + list(range(1947, 1960))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}
DELAY = 1.5


def fetch(url: str) -> str | None:
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


def parse_kom_final(html: str) -> list[dict]:
    """
    Parse the KOM tab from a /race/.../YEAR/kom page.
    Returns list of {rider_slug, rider_name, nat, team_slug, team_name, rnk, pnt2}.
    """
    # Find KOM tab id
    kom_tab_id = None
    for tab_m in re.finditer(r'<li[^>]*data-id="(\d+)"[^>]*>(.*?)</li>', html, re.DOTALL):
        label = re.sub(r"<[^>]+>", "", tab_m.group(2)).strip().upper()
        if label == "KOM":
            kom_tab_id = tab_m.group(1)
            break
    if not kom_tab_id:
        return []

    kom_div_m = re.search(
        rf'<div[^>]*resTab[^>]*data-id="{re.escape(kom_tab_id)}"[^>]*>(.*?)</div>\s*</div>',
        html, re.DOTALL
    )
    if not kom_div_m:
        return []
    frag = kom_div_m.group(1)

    thead_m = re.search(r"<thead>(.*?)</thead>", frag, re.DOTALL)
    if not thead_m:
        return []
    cols = re.findall(r'data-code="([^"]+)"', thead_m.group(1))
    if "pnt2" not in cols or "delta_pnt" not in cols:
        return []

    pnt2_idx    = cols.index("pnt2")
    rider_idx   = cols.index("ridername") if "ridername" in cols else None
    team_idx    = cols.index("teamnamelink") if "teamnamelink" in cols else None
    rnk_idx     = cols.index("rnk") if "rnk" in cols else 0

    tbody_m = re.search(r"<tbody>(.*?)</tbody>", frag, re.DOTALL)
    if not tbody_m:
        return []

    results = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody_m.group(1), re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        if pnt2_idx >= len(tds):
            continue

        def td_text(td):
            t = re.sub(r"<[^>]+>", "", td)
            return " ".join(t.split())

        rnk_raw  = td_text(tds[rnk_idx]) if rnk_idx < len(tds) else ""
        pnt2_raw = td_text(tds[pnt2_idx])

        try:
            pnt2 = int(pnt2_raw)
            rnk  = int(rnk_raw) if rnk_raw.isdigit() else len(results) + 1
        except (ValueError, TypeError):
            continue

        # Rider info
        rider_td  = tds[rider_idx] if rider_idx is not None and rider_idx < len(tds) else ""
        slug_m    = re.search(r'href="(rider/[a-z0-9-]+)"', rider_td)
        rider_slug = slug_m.group(1) if slug_m else ""

        last_m  = re.search(r'class="uppercase"[^>]*>([^<]+)<', rider_td)
        first_m = re.search(r'</span>\s*([^<\s][^<]*?)\s*</a>', rider_td)
        if last_m and first_m:
            rider_name = f"{last_m.group(1).strip()} {first_m.group(1).strip()}"
        elif last_m:
            rider_name = last_m.group(1).strip()
        else:
            rider_name = td_text(rider_td).split()[0] if rider_td else ""

        nat_m = re.search(r'class="flag ([a-z]{2})"', rider_td)
        nat = nat_m.group(1) if nat_m else ""

        team_td   = tds[team_idx] if team_idx is not None and team_idx < len(tds) else ""
        team_slug_m = re.search(r'href="(team/[a-z0-9-]+)"', team_td)
        team_slug  = team_slug_m.group(1) if team_slug_m else ""
        team_name  = td_text(team_td)

        if rider_slug:
            results.append({
                "rnk": rnk,
                "rider_slug": rider_slug,
                "rider_name": rider_name,
                "nat": nat,
                "team_slug": team_slug,
                "team_name": team_name,
                "pnt2": pnt2,
            })

    return results


def main():
    exit_on_help(__doc__)
    year_args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    years = year_args if year_args else TARGET_YEARS

    with open(KOM_PTS_PATH, encoding="utf-8") as f:
        kom_pts: dict = json.load(f)

    for year in years:
        url = f"https://www.procyclingstats.com/race/tour-de-france/{year}/kom"
        print(f"{year}: fetching {url} ...", end=" ", flush=True)
        html = fetch(url)
        time.sleep(DELAY)

        if not html:
            print("no data")
            continue

        riders = parse_kom_final(html)
        if not riders:
            print("no KOM tab or pnt2 column")
            continue

        print(f"{len(riders)} riders  (leader: {riders[0]['rider_name']} {riders[0]['pnt2']}pts)")

        # ── 1. Put totals into last stage of tour_kom_points.json ──────────────────
        yr_str = str(year)
        stages_list = kom_pts.get(yr_str, [])
        if not stages_list:
            # Load stage count from tdf_YEAR_full.json
            full_path = os.path.join(HERE, f"tdf_{year}_full.json")
            if os.path.exists(full_path):
                with open(full_path) as f:
                    bundle = json.load(f)
                n_stages = len(bundle.get("stages", []))
                stages_list = [{} for _ in range(n_stages)]
            else:
                print(f"  Warning: no tdf_{year}_full.json, skipping kom_points update")
                continue

        # Write totals to last stage
        last_stage_dict = {}
        for r in riders:
            last_stage_dict[r["rider_slug"]] = r["pnt2"]
        stages_list[-1] = last_stage_dict
        kom_pts[yr_str] = stages_list

        # ── 2. Inject classification rows into tdf_YEAR_full.json ─────────────
        full_path = os.path.join(HERE, f"tdf_{year}_full.json")
        if os.path.exists(full_path):
            with open(full_path, encoding="utf-8") as f:
                bundle = json.load(f)

            # Format: [rnk, prev, rider_name, rider_slug, nat, team_name, team_slug,
            #          font_txt, span_txt, last_raw]
            # build_db.py reads: value_text = font_txt or span_txt or last_raw
            # For "kom" type: points_val = parse_int(value_text)
            kom_rows = [
                [str(r["rnk"]), "", r["rider_name"], r["rider_slug"],
                 r["nat"], r["team_name"], r["team_slug"],
                 str(r["pnt2"]), "", ""]
                for r in riders
            ]
            if "classifications" not in bundle:
                bundle["classifications"] = {}
            bundle["classifications"]["kom"] = kom_rows

            with open(full_path, "w", encoding="utf-8") as f:
                json.dump(bundle, f, ensure_ascii=False)
            print(f"  Updated tdf_{year}_full.json classifications.kom")

    # Save tour_kom_points.json
    kom_pts = dict(sorted(kom_pts.items(), key=lambda x: int(x[0])))
    with open(KOM_PTS_PATH, "w", encoding="utf-8") as f:
        json.dump(kom_pts, f, ensure_ascii=False)
    print(f"\nWrote {KOM_PTS_PATH}")


if __name__ == "__main__":
    main()
