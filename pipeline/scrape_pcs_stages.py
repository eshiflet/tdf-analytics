#!/usr/bin/env python3
"""
Scrape Tour de France stage results from procyclingstats.com for years
1939 and 1947–1959, producing tdf_YEAR_full.json files compatible with
build_db.py. Also updates profile_icons.json for those years.

The Tour did not run 1940–1946 (WWII).

Usage:
  python3 scrape_pcs_stages.py              # all target years
  python3 scrape_pcs_stages.py 1953 1959   # specific years
  python3 scrape_pcs_stages.py --resume    # skip years already scraped
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

HERE    = os.path.dirname(os.path.abspath(__file__))
ICONS_PATH = os.path.join(HERE, "profile_icons.json")

BASE = "https://www.procyclingstats.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY    = 1.0   # seconds between requests
MAX_WAIT = 8.0   # max time to wait on a retried request

TARGET_YEARS = [1939] + list(range(1947, 1960))

# Profile icon → route type.  TT/TTT are detected from "Won how" field.
ICON_TO_ROUTE = {
    "p1": "F",
    "p2": "H",
    "p3": "H",
    "p4": "M",
    "p5": "M",
}


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def fetch(url: str, retries: int = 2) -> str | None:
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            if e.code == 500:
                return None  # Stage doesn't exist
            print(f"    HTTP {e.code} on {url} (attempt {attempt+1})")
            if attempt < retries:
                time.sleep(MAX_WAIT)
        except Exception as e:
            print(f"    Error {e} on {url}")
            if attempt < retries:
                time.sleep(MAX_WAIT)
    return None


# ── Stage discovery ───────────────────────────────────────────────────────────

def discover_stages(year: int) -> list[str]:
    """
    Return ordered list of stage slugs like ['stage-1', 'stage-2a', 'stage-2b', ...].
    Probes sequentially: for each number N, try N, Na, Nb, Nc.
    Stops when a full number N yields nothing (no sub-stages found either).
    """
    slugs = []
    for n in range(1, 30):
        found_any = False
        # Try plain number first
        slug = f"stage-{n}"
        html = fetch(f"{BASE}/race/tour-de-france/{year}/{slug}")
        if html and "rider/" in html and len(html) > 20000:
            slugs.append(slug)
            found_any = True
            time.sleep(DELAY)
        else:
            # Try sub-stages (a, b, c, d)
            for letter in "abcd":
                slug = f"stage-{n}{letter}"
                html = fetch(f"{BASE}/race/tour-de-france/{year}/{slug}")
                if html and "rider/" in html and len(html) > 20000:
                    slugs.append(slug)
                    found_any = True
                    time.sleep(DELAY)
                else:
                    if found_any:
                        break  # no more sub-stages for this number
                    elif letter == "a":
                        time.sleep(DELAY * 0.5)
                    break  # tried plain and 'a', neither worked

        if not found_any and n > 5:
            # Allow a couple of gaps (cancelled stages) but stop after 3 consecutive misses
            if not any(f"stage-{n+k}" in " ".join(slugs) or
                       f"stage-{n+k}a" in " ".join(slugs) for k in range(1, 3)):
                # peek ahead
                peek = fetch(f"{BASE}/race/tour-de-france/{year}/stage-{n+1}")
                if not peek or "rider/" not in peek or len(peek) < 20000:
                    break

    return slugs


# ── Info section parsing ──────────────────────────────────────────────────────

def parse_info(html: str) -> dict:
    """Extract stage metadata from the PCS info list."""
    info = {}

    def extract(label: str) -> str | None:
        # Pattern: "Label: </div><div class=" value" >VALUE</div></li>"
        # or with link: ">VALUE</a></div></li>"
        m = re.search(
            re.escape(label) + r'[^<]*</div><div[^>]*>\s*(?:<a[^>]*>)?([^<]+?)(?:</a>)?\s*</div>',
            html, re.IGNORECASE
        )
        return m.group(1).strip() if m else None

    info["Date"]               = extract("Date:")
    info["Distance"]           = extract("Distance:")
    info["Departure"]          = extract("Departure:")
    info["Arrival"]            = extract("Arrival:")
    info["Vertical meters"]    = extract("Vertical meters:")
    info["Won how"]            = extract("Won how:")
    info["Avg. speed winner"]  = extract("Avg. speed winner:")
    info["Avg. temperature"]   = extract("Avg. temperature:")
    info["ProfileScore"]       = extract("ProfileScore:")
    info["Race ranking"]       = extract("Race ranking:")

    # Remove None values
    return {k: v for k, v in info.items() if v is not None}


def parse_profile_icon(html: str) -> str | None:
    """Extract the p1–p5 profile icon class from the stage page."""
    m = re.search(r'class="icon\s+(p[1-5])\b', html)
    if m:
        return m.group(1)
    # Alternative: background image in a div with p1-p5
    m = re.search(r'<div[^>]*\bclass="[^"]*\b(p[1-5])\b[^"]*"', html)
    return m.group(1) if m else None


# ── Results table parsing ─────────────────────────────────────────────────────

def td_text(html: str) -> str:
    """Strip tags and decode entities from a single <td> inner HTML."""
    t = re.sub(r"<[^>]+>", "", html)
    t = t.replace("&amp;", "&").replace("&#160;", " ").replace("&nbsp;", " ")
    return " ".join(t.split())


def parse_rows(html: str) -> list[list]:
    """
    Parse the stage results tbody into rows matching build_db.py format:
    [rnk, gc_pos, gc_lag, bib, age, rider_name, rider_slug, nat,
     team_name, team_slug, uci_pts, pcs_pts, bonus_txt, abs_time_txt, gap_txt]

    PCS column layout (fixed):
      0: rnk  1: gc  2: gc_timelag  3: bib  4: h2h(skip)  5: specialty(skip)
      6: age  7: ridername  8: team  9: pnt  10: bonus  11: time

    Time column: <font>5:33:45</font><span class="hide">…</span> for winner;
                 <font>,,</font><span class="hide">…</span> for others (no stage gap shown).
    """
    tbody_m = re.search(r"<tbody>(.*?)</tbody>", html, re.DOTALL)
    if not tbody_m:
        return []

    rows = []

    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody_m.group(1), re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        if len(tds) < 8:
            continue

        try:
            rnk    = td_text(tds[0])
            gc_pos = td_text(tds[1]) if len(tds) > 1 else ""
            gc_lag = td_text(tds[2]) if len(tds) > 2 else ""
            bib    = td_text(tds[3]) if len(tds) > 3 else ""
            # tds[4] = h2h (skip), tds[5] = specialty (skip)
            age    = td_text(tds[6]) if len(tds) > 6 else ""

            rider_td = tds[7] if len(tds) > 7 else ""

            # Rider slug + name
            slug_m = re.search(r'href="(rider/[a-z0-9-]+)"', rider_td)
            rider_slug = slug_m.group(1) if slug_m else ""

            last_m  = re.search(r'class="uppercase"[^>]*>([^<]+)<', rider_td)
            first_m = re.search(r'</span>\s*([^<\s][^<]*?)\s*</a>', rider_td)
            if last_m and first_m:
                rider_name = f"{last_m.group(1).strip()} {first_m.group(1).strip()}"
            elif last_m:
                rider_name = last_m.group(1).strip()
            elif rider_slug:
                rider_name = rider_slug.replace("rider/", "").replace("-", " ").title()
            else:
                # Incident / note row
                rows.append([rnk, "", "", "", "", td_text(rider_td), "", "", "", "", "", "", "", "", ""])
                continue

            nat_m = re.search(r'class="flag ([a-z]{2})"', rider_td)
            nat = nat_m.group(1) if nat_m else ""

            team_td = tds[8] if len(tds) > 8 else ""
            team_slug_m = re.search(r'href="(team/[a-z0-9-]+)"', team_td)
            team_slug = team_slug_m.group(1) if team_slug_m else ""
            team_name = td_text(team_td)

            pcs_pts  = td_text(tds[9])  if len(tds) > 9  else ""
            bonus_txt = td_text(tds[10]) if len(tds) > 10 else ""

            # Time column: extract only the <font> content (skip hidden span)
            time_td = tds[11] if len(tds) > 11 else ""
            font_m  = re.search(r"<font[^>]*>([^<]*)</font>", time_td)
            time_txt = font_m.group(1).strip() if font_m else td_text(time_td)

            # PCS shows absolute time only for rank-1; others show ",," (no stage gap)
            abs_time_txt = ""
            gap_txt = ""
            if rnk == "1":
                abs_time_txt = time_txt
                gap_txt = "+0:00"
            elif time_txt.startswith("+"):
                gap_txt = time_txt
            elif time_txt in ("s.t.", "s.t", "0:00", ""):
                gap_txt = "+0:00"
            elif time_txt == ",,":
                gap_txt = ""  # stage gap not available for this rider
            elif re.match(r"^\d+:\d{2}(:\d{2})?$", time_txt):
                abs_time_txt = time_txt  # some stages show absolute for all
            else:
                gap_txt = time_txt

            rows.append([
                rnk, gc_pos, gc_lag, bib, age,
                rider_name, rider_slug, nat,
                team_name, team_slug,
                "", pcs_pts, bonus_txt,
                abs_time_txt, gap_txt,
            ])

        except Exception:
            continue

    return rows


# ── Route type detection ──────────────────────────────────────────────────────

def detect_route_type(icon: str | None, won_how: str, distance_km: float | None) -> str:
    """Map profile icon + won_how to route type."""
    wh = (won_how or "").lower()
    if "team time trial" in wh or "ttt" in wh:
        return "TTT"
    if "time trial" in wh:
        return "TT"
    if distance_km and distance_km < 15:
        return "TT"  # Very short stages are almost certainly time trials

    return ICON_TO_ROUTE.get(icon or "p1", "F")


# ── Per-stage scrape ──────────────────────────────────────────────────────────

def scrape_stage(year: int, slug: str, stage_n: int) -> dict | None:
    """Scrape one stage page and return {n, info, rows, icon}."""
    url = f"{BASE}/race/tour-de-france/{year}/{slug}"
    html = fetch(url)
    if not html:
        return None

    info = parse_info(html)
    rows = parse_rows(html)
    icon = parse_profile_icon(html)

    if not rows:
        print(f"    Warning: no rows parsed for {year}/{slug}")

    return {"n": stage_n, "slug": slug, "info": info, "rows": rows, "icon": icon}


# ── Year scrape ───────────────────────────────────────────────────────────────

def scrape_year(year: int) -> dict | None:
    """Scrape all stages for a year. Returns the full.json structure."""
    print(f"{year}: discovering stages...", flush=True)
    slugs = discover_stages(year)
    if not slugs:
        print(f"  No stages found for {year}")
        return None

    print(f"  Found {len(slugs)} stages: {slugs}")

    stages = []
    icons  = []

    for stage_n, slug in enumerate(slugs, start=1):
        print(f"  Scraping {slug}...", end=" ", flush=True)
        result = scrape_stage(year, slug, stage_n)
        if result:
            stages.append({
                "n": stage_n,
                "slug": slug,
                "info": result["info"],
                "rows": result["rows"],
            })
            icons.append(result["icon"] or "p1")
            nrows = len(result["rows"])
            print(f"{nrows} riders")
        else:
            print("FAILED")
        time.sleep(DELAY)

    if not stages:
        return None

    return {
        "year": year,
        "stages": stages,
        "classifications": {},
        "_icons": icons,  # route type icons, stripped before saving
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    resume = "--resume" in args
    year_args = [int(a) for a in args if a.isdigit()]
    years = year_args if year_args else TARGET_YEARS

    # Load existing profile_icons
    if os.path.exists(ICONS_PATH):
        with open(ICONS_PATH, encoding="utf-8") as f:
            all_icons: dict = json.load(f)
    else:
        all_icons = {}

    for year in years:
        out_path = os.path.join(HERE, f"tdf_{year}_full.json")

        if resume and os.path.exists(out_path):
            print(f"{year}: skipping (already scraped)")
            continue

        data = scrape_year(year)
        if not data:
            continue

        icons = data.pop("_icons", [])

        # Save stage data
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"  Wrote {out_path}")

        # Update profile_icons
        all_icons[str(year)] = icons
        # Keep icons sorted by year
        all_icons = dict(sorted(all_icons.items(), key=lambda x: int(x[0])))
        with open(ICONS_PATH, "w", encoding="utf-8") as f:
            json.dump(all_icons, f, ensure_ascii=False, indent=2)
        print(f"  Updated profile_icons.json for {year}")

    print("\nDone.")


if __name__ == "__main__":
    main()
