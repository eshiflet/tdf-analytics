#!/usr/bin/env python3
"""
Scrape final KOM season totals from Wikipedia and bikeraceinfo for all TdF years.
Produces kom_totals.json:
  {
    "1982": {
      "wikipedia":    [["Bernard Vallet", 278], ["Jean-René Bernaudeau", 237], ...],
      "bikeraceinfo": [["Bernard Vallet", 278], ...]
    }, ...
  }

Usage:
  python3 scrape_kom_totals.py              # all years
  python3 scrape_kom_totals.py 1982 1985   # specific years
  python3 scrape_kom_totals.py --resume    # skip years already in output file
"""

import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
import urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from race_common import exit_on_help

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "kom_totals.json")
DB_PATH = os.path.join(HERE, "cycling.db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; tdf-analytics-validator/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 1.0


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {url}")
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


# ── Wikipedia ────────────────────────────────────────────────────────────────

def scrape_wikipedia(year: int) -> list[tuple[str, int]]:
    url = f"https://en.wikipedia.org/wiki/{year}_Tour_de_France"
    html = fetch(url)
    if not html:
        return []

    section_m = re.search(r'id="Mountains_classification"', html, re.IGNORECASE)
    if not section_m:
        section_m = re.search(
            r'(?:Mountains classification|Polka dot jersey)[^<]{0,60}(?:</h[23]>|</span>\s*</div>)',
            html, re.IGNORECASE,
        )
    if not section_m:
        return []

    section_html = html[section_m.start():]
    tbl_start = section_html.find("<table")
    if tbl_start == -1:
        return []
    tbl_end = section_html.find("</table>", tbl_start)
    if tbl_end == -1:
        return []
    tbl = section_html[tbl_start:tbl_end + 8]

    results = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.DOTALL):
        if "<th" in row and row.count("<th") > row.count("<td"):
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(tds) < 2:
            continue

        def td_text(td):
            t = re.sub(r"<[^>]+>", " ", td)
            for ent, ch in [("&amp;", "&"), ("&#160;", " "), ("&nbsp;", " ")]:
                t = t.replace(ent, ch)
            return " ".join(t.replace("\xa0", " ").split())

        texts = [td_text(td) for td in tds]

        rider_name = None
        for td in tds:
            links = re.findall(r'<a[^>]+href="/wiki/[^"#]+"[^>]*>([^<]+)</a>', td)
            if links:
                candidate = links[-1].strip()
                if len(candidate) > 3 and not re.match(r"^[A-Z]{2,3}$", candidate):
                    rider_name = candidate
                    break

        if not rider_name:
            continue

        points = None
        for text in reversed(texts):
            m = re.match(r"^(\d+)$", text.strip())
            if m:
                points = int(m.group(1))
                break

        if rider_name and points is not None:
            results.append((rider_name, points))

    seen: dict[str, int] = {}
    for name, pts in results:
        if name not in seen or pts > seen[name]:
            seen[name] = pts
    return sorted(seen.items(), key=lambda x: -x[1])


# ── bikeraceinfo.com ─────────────────────────────────────────────────────────

def scrape_bri(year: int) -> list[tuple[str, int]]:
    url = f"https://bikeraceinfo.com/tdf/tdf{year}.html"
    html = fetch(url)
    if not html:
        return []

    m = re.search(r"[Cc]limbers['']?\s*Competition", html)
    if not m:
        return []

    section = html[m.start():]
    ol_m = re.search(r"<ol>(.*?)</ol>", section, re.DOTALL)
    if not ol_m:
        return []

    results = []
    for item in re.findall(r"<li[^>]*>(.*?)</li>", ol_m.group(1), re.DOTALL):
        text = re.sub(r"<[^>]+>", " ", item)
        text = " ".join(text.split())
        m2 = re.match(r"^(.+?)\s*\([^)]*\)\s*:\s*(\d+)", text)
        if m2:
            name = m2.group(1).strip()
            pts = int(m2.group(2))
            if name and pts > 0:
                results.append((name, pts))

    return sorted(results, key=lambda x: -x[1])


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    exit_on_help(__doc__)
    import sqlite3
    args = sys.argv[1:]
    resume = "--resume" in args
    year_args = [int(a) for a in args if a.isdigit()]

    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    conn = sqlite3.connect(DB_PATH)
    all_years = [r[0] for r in conn.execute("SELECT year FROM race_editions ORDER BY year")]
    conn.close()

    years = year_args if year_args else all_years

    for year in years:
        yr = str(year)
        if resume and yr in data and data[yr].get("wikipedia") and data[yr].get("bikeraceinfo"):
            print(f"{year}: skipping (already have both sources)")
            continue

        print(f"{year}:")
        entry = data.get(yr, {})

        if not entry.get("wikipedia"):
            wiki = scrape_wikipedia(year)
            print(f"  wikipedia: {len(wiki)} riders — {wiki[:3]}")
            entry["wikipedia"] = [[n, p] for n, p in wiki]
            time.sleep(DELAY)

        if not entry.get("bikeraceinfo"):
            bri = scrape_bri(year)
            print(f"  bikeraceinfo: {len(bri)} riders — {bri[:3]}")
            entry["bikeraceinfo"] = [[n, p] for n, p in bri]
            time.sleep(DELAY)

        data[yr] = entry
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nDone → {OUT_PATH}")


if __name__ == "__main__":
    main()
