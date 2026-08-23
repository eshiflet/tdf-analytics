#!/usr/bin/env python3
"""
Validate KOM points in our JSON data against Wikipedia and bikeraceinfo.com.

Usage:
  python3 validate_kom.py              # all years that have JSON data
  python3 validate_kom.py 1982 1985    # specific years
  python3 validate_kom.py --summary    # one line per year, no detail
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
DATA_DIR = os.path.join(HERE, "..", "cycling-app", "src", "data")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; tdf-analytics-validator/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 0.8   # seconds between requests to same host


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {url}")
        return None
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def normalize(name: str) -> str:
    """Lowercase, strip accents, collapse whitespace, remove punctuation."""
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return " ".join(name.split())


def name_match(a: str, b: str) -> bool:
    """True if both names share enough tokens to be the same person."""
    ta = set(normalize(a).split())
    tb = set(normalize(b).split())
    if not ta or not tb:
        return False
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    # All tokens of shorter name must appear in longer name
    return smaller.issubset(larger)


# ── Wikipedia ────────────────────────────────────────────────────────────────

def fetch_wikipedia_kom(year: int) -> list[tuple[str, int]]:
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
    tbl = section_html[tbl_start : tbl_end + 8]

    results = []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.DOTALL)
    for row in rows:
        if "<th" in row and row.count("<th") > row.count("<td"):
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(tds) < 2:
            continue

        def td_text(td):
            t = re.sub(r"<[^>]+>", " ", td)
            t = t.replace("&amp;", "&").replace("&#160;", " ").replace("&nbsp;", " ").replace("\xa0", " ")
            return " ".join(t.split())

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

def fetch_bri_kom(year: int) -> list[tuple[str, int]]:
    url = f"https://bikeraceinfo.com/tdf/tdf{year}.html"
    html = fetch(url)
    if not html:
        return []

    # Find the Climbers' Competition ordered list
    m = re.search(r"[Cc]limbers['’]?\s*Competition", html)
    if not m:
        return []

    section = html[m.start():]
    # Extract the <ol> immediately following
    ol_m = re.search(r"<ol>(.*?)</ol>", section, re.DOTALL)
    if not ol_m:
        return []

    results = []
    items = re.findall(r"<li[^>]*>(.*?)</li>", ol_m.group(1), re.DOTALL)
    for item in items:
        # Strip all tags
        text = re.sub(r"<[^>]+>", " ", item)
        text = " ".join(text.split())

        # Pattern: "Name (Team): 278 points" or "Name (Team): 278"
        m2 = re.match(r"^(.+?)\s*\([^)]*\)\s*:\s*(\d+)", text)
        if m2:
            rider_name = m2.group(1).strip()
            points = int(m2.group(2))
            if rider_name and points > 0:
                results.append((rider_name, points))

    return sorted(results, key=lambda x: -x[1])


# ── Our data ─────────────────────────────────────────────────────────────────

def load_our_kom(year: int) -> list[tuple[str, int]]:
    path = os.path.join(DATA_DIR, f"gc_by_stage_{year}.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    totals = []
    for rider in d["riders"]:
        if rider["byStage"]:
            pts = rider["byStage"][-1]["cumulativeKomPoints"]
            if pts > 0:
                totals.append((rider["name"], pts))
    return sorted(totals, key=lambda x: -x[1])


# ── Comparison ───────────────────────────────────────────────────────────────

def compare(ref_name: str, ref_data: list[tuple[str, int]], our_data: list[tuple[str, int]]) -> dict:
    """Compare our data against one reference source."""
    matches, mismatches, missing = [], [], []
    for ref_rider, ref_pts in ref_data[:10]:
        best_match = next(
            ((name, pts) for name, pts in our_data[:20] if name_match(ref_rider, name)),
            None,
        )
        if best_match is None:
            missing.append({"name": ref_rider, "ref_pts": ref_pts})
        else:
            diff = best_match[1] - ref_pts
            pct = abs(diff) / ref_pts * 100 if ref_pts else 0
            entry = {
                "ref_name": ref_rider,
                "our_name": best_match[0],
                "ref_pts": ref_pts,
                "our_pts": best_match[1],
                "diff": diff,
                "pct_off": round(pct, 1),
            }
            (matches if pct < 5 else mismatches).append(entry)

    n_total = len(matches) + len(mismatches) + len(missing)
    return {
        "source": ref_name,
        "matches": matches,
        "mismatches": mismatches,
        "missing": missing,
        "match_rate": round(len(matches) / n_total * 100) if n_total else 0,
    }


def validate_year(year: int) -> dict:
    our = load_our_kom(year)

    time.sleep(DELAY)
    wiki = fetch_wikipedia_kom(year)
    time.sleep(DELAY)
    bri = fetch_bri_kom(year)

    result = {
        "year": year,
        "our_top": our[:10],
        "wiki_top": wiki[:10],
        "bri_top": bri[:10],
        "sources": {},
    }

    if wiki:
        result["sources"]["wikipedia"] = compare("wikipedia", wiki, our)
    if bri:
        result["sources"]["bikeraceinfo"] = compare("bikeraceinfo", bri, our)

    # Also cross-check the two reference sources against each other
    if wiki and bri:
        result["sources"]["wiki_vs_bri"] = compare("wiki_vs_bri", wiki, bri)

    # Overall status: pass if at least one source agrees ≥70%
    rates = [s["match_rate"] for s in result["sources"].values() if s["source"] != "wiki_vs_bri"]
    result["best_match_rate"] = max(rates) if rates else 0
    result["status"] = "ok" if result["best_match_rate"] >= 70 else ("no_data" if not our else "mismatch")
    return result


def print_result(r: dict, summary_only: bool = False):
    year = r["year"]
    status_sym = {"ok": "✓", "mismatch": "✗", "no_data": "○"}.get(r["status"], "?")

    sources_str = "  ".join(
        f"{s['source']}:{s['match_rate']}%"
        for s in r["sources"].values()
        if s["source"] != "wiki_vs_bri"
    ) or "no external data"

    print(f"{year}: {status_sym}  {sources_str}")

    if summary_only or r["status"] == "ok":
        return

    for src in r["sources"].values():
        if src["source"] == "wiki_vs_bri" or src["match_rate"] >= 70:
            continue
        print(f"  [{src['source']}]")
        for m in src["mismatches"]:
            sign = "+" if m["diff"] > 0 else ""
            print(f"    {m['ref_name']:30s}  ref={m['ref_pts']:4d}  ours={m['our_pts']:4d}  ({sign}{m['diff']}, {m['pct_off']}% off)")
        for m in src["missing"]:
            print(f"    {m['name']:30s}  ref={m['ref_pts']:4d}  MISSING from our data")

    # Note if the two reference sources disagree significantly
    wvb = r["sources"].get("wiki_vs_bri")
    if wvb and wvb["match_rate"] < 70:
        print(f"  ⚠  Wikipedia vs bikeraceinfo only {wvb['match_rate']}% agree — sources conflict")


def main():
    exit_on_help(__doc__)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    summary_only = "--summary" in sys.argv

    if args:
        years = [int(a) for a in args]
    else:
        files = sorted(f for f in os.listdir(DATA_DIR) if f.startswith("gc_by_stage_") and f.endswith(".json"))
        years = [int(re.search(r"(\d{4})", f).group(1)) for f in files]

    all_results = []
    for year in years:
        print(f"Checking {year}...", end=" ", flush=True)
        r = validate_year(year)
        all_results.append(r)
        print_result(r, summary_only)

    ok = sum(1 for r in all_results if r["status"] == "ok")
    mismatch = sum(1 for r in all_results if r["status"] == "mismatch")
    no_data = sum(1 for r in all_results if r["status"] == "no_data")
    print(f"\n{'='*60}")
    print(f"Summary: {ok} ok  {mismatch} mismatch  {no_data} no_data  ({len(all_results)} years total)")


if __name__ == "__main__":
    main()
