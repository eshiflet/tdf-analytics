#!/usr/bin/env python3
"""
Scrape official GC total times for all riders from Wikipedia.

Three strategies:
  1. Time-based GC years (1913+, 1903): parse final GC table — winner's
     absolute time + gap rows → convert all to absolute seconds.
  2. 1904: hardcoded from user-provided post-disqualification results.
  3. Points-system years (1905–1912): fetch per-stage Wikipedia pages,
     parse each stage result table, accumulate per-rider totals.

Output: gc_all_times.json  {year: {rider_id: total_seconds}}
Uses the same name-normalisation / DB lookup as patch_kom_wikipedia.py.

Usage:
  python3 scrape_gc_all_times.py            # all years
  python3 scrape_gc_all_times.py 1933 2025  # specific years
"""

import json, os, re, sqlite3, sys, time, unicodedata, urllib.request, urllib.error

HERE     = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(HERE, "cycling.db")
OUT_PATH = os.path.join(HERE, "gc_all_times.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; tdf-analytics/1.0)"}
DELAY   = 1.5

# Years where the GC was decided by points (no time-based classification).
# We fall back to per-stage time summation for these.
POINTS_SYSTEM_YEARS = set(range(1905, 1913))

# 1904 official results after all disqualifications (user-provided).
HARDCODED_1904 = [
    ("Henri Cornet",          "96h 05' 55\""),
    ("Jean-Baptiste Dortignacq", "+ 2h 16' 14\""),
    ("Aloïs Catteau",         "+ 9h 01' 25\""),
    ("Jean Dargassies",       "+ 13h 04' 30\""),
    ("Julien Maitron",        "+ 19h 06' 15\""),
    ("Auguste Daumain",       "+ 22h 44' 36\""),
    ("Louis Coolsaet",        "+ 23h 44' 20\""),
    ("Achille Colas",         "+ 25h 09' 50\""),
    ("René Saget",            "+ 25h 55' 16\""),
    ("Gustave Drioul",        "+ 30h 54' 49\""),
    ("Henri Paret",           "+ 32h 18' 39\""),
    ("Auguste Gauthier",      "+ 33h 14' 02\""),
    ("Auguste Rist",          "+ 35h 01' 20\""),
    ("Damelincourt Nicolas",   "+ 48h 39' 03\""),
    ("Antoine Deflotriere",   "+ 101h 28' 52\""),
]

ALL_RACE_YEARS = [y for y in range(1903, 2026)
                  if y not in range(1915, 1919) and y not in range(1940, 1947)]


# ── utilities ──────────────────────────────────────────────────────────────

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for _ in range(3):
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


def clean(html_frag):
    t = re.sub(r"<[^>]+>", "", html_frag)
    return t.replace("\xa0", " ").replace("&#160;", " ").replace("&#91;", "[").replace("&#93;", "]").strip()


def normalize(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def parse_absolute(s):
    """Parse 'Xh YY' ZZ"' → seconds.  Returns None on failure."""
    s = s.replace("′", "'").replace("″", '"').strip()
    m = re.match(r"(\d+)\s*h\s*(\d+)['\s]+(\d+)", s)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    m = re.match(r"(\d+)\s*h\s*(\d+)", s)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60
    return None


def parse_gap(s):
    """Parse '+ Xh YY' ZZ"' or '+ YY' ZZ"' or '+ ZZ"' → seconds."""
    s = s.replace("′", "'").replace("″", '"').lstrip("+ ").strip()
    m = re.match(r"(\d+)\s*h\s*(\d+)['\s]+(\d+)", s)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    m = re.match(r"(\d+)['\s]+(\d+)", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r'(\d+)"', s)
    if m:
        return int(m.group(1))
    return None


def build_name_lookup(conn):
    """
    {normalized_name: rider_id}  — indexes both "Lastname Firstname" and
    "Firstname Lastname" forms to handle Wikipedia vs DB ordering.
    """
    lookup = {}
    for rider_id, full_name in conn.execute("SELECT rider_id, full_name FROM riders"):
        parts = full_name.strip().split()
        norm_db  = normalize(full_name)
        norm_rev = normalize(" ".join(reversed(parts))) if len(parts) >= 2 else norm_db
        lookup[norm_db]  = rider_id
        lookup[norm_rev] = rider_id
    return lookup


def match_name(raw, name_lookup):
    """Try several normalisations to match a Wikipedia name to a rider_id."""
    # Strip nationality "(FRA)" suffix
    name = re.sub(r"\s*\([A-Z]{2,3}\)\s*", "", raw).strip()
    # Also strip footnotes "[a]" etc.
    name = re.sub(r"\s*\[[^\]]+\]\s*", "", name).strip()
    for candidate in [name, " ".join(reversed(name.split()))]:
        rid = name_lookup.get(normalize(candidate))
        if rid:
            return rid
    return None


# ── strategy 1: time-based GC table ───────────────────────────────────────

def scrape_time_based_gc(html):
    """
    Return list of (name_raw, total_seconds) for all riders in the final
    GC classification table.  Gaps are converted to absolutes using
    the winner's time.
    """
    for anchor in [
        'id="General_classification"',
        'id="Final_general_classification"',
        'id="Overall_classification"',
    ]:
        idx = html.find(anchor)
        if idx >= 0:
            break
    else:
        return []

    snippet = html[idx: idx + 30000]

    for t in re.finditer(r"<table[^>]*>(.*?)</table>", snippet, re.DOTALL):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t.group(1), re.DOTALL)
        if not rows:
            continue
        hdr = [clean(h).lower() for h in re.findall(r"<th[^>]*>(.*?)</th>", rows[0], re.DOTALL)]
        if not any("time" in h for h in hdr):
            continue

        results = []
        winner_time = None
        for row in rows[1:]:
            tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
            if len(tds) < 3:
                continue
            rank_raw = clean(tds[0])
            name_raw = clean(tds[1])
            time_str = clean(tds[-1])

            if not name_raw:
                continue

            if winner_time is None:
                # First data row — expect an absolute time
                secs = parse_absolute(time_str)
                if secs and secs > 50000:
                    winner_time = secs
                    results.append((name_raw, secs))
            else:
                if time_str.startswith("+") or time_str.startswith("+ "):
                    gap = parse_gap(time_str)
                    if gap is not None:
                        results.append((name_raw, winner_time + gap))
                elif "s.t." in time_str.lower() or time_str.lower() in ("st", "s.t"):
                    # Same time as previous rider
                    if results:
                        results.append((name_raw, results[-1][1]))
                else:
                    secs = parse_absolute(time_str)
                    if secs and secs > 50000:
                        results.append((name_raw, secs))

        if results:
            return results

    return []


# ── strategy 2: points-system years — stage-page summation ────────────────

def find_stage_page_urls(html, base_year):
    """Extract Wikipedia stage-page links from the year article."""
    urls = set()
    for href in re.findall(r'href="(/wiki/[^"#]*[Ss]tage[^"#]*)"', html):
        if str(base_year) in href and "Tour_de_France" in href:
            urls.add("https://en.wikipedia.org" + href)
    return sorted(urls)


def parse_stage_page_times(html):
    """
    Parse all stage result tables (Rank, Rider, Time) from a stage page.
    Returns list of dicts: {stage_idx: {name: seconds}}.
    Handles 's.t.' (same time as rider directly above in that table).
    """
    stages_data = []
    for t in re.finditer(r"<table[^>]*>(.*?)</table>", html, re.DOTALL):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t.group(1), re.DOTALL)
        if not rows:
            continue
        hdr = [clean(h).lower() for h in re.findall(r"<th[^>]*>(.*?)</th>", rows[0], re.DOTALL)]
        if not (any("time" in h for h in hdr) and any("rider" in h for h in hdr)):
            continue

        rider_times = {}
        last_time = None
        for row in rows[1:]:
            tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
            if len(tds) < 3:
                continue
            name_raw = clean(tds[1])
            time_str = clean(tds[-1])
            if not name_raw:
                continue

            name = re.sub(r"\s*\([A-Z]{2,3}\)\s*", "", name_raw).strip()

            if time_str.startswith("+"):
                gap = parse_gap(time_str)
                if gap is not None and last_time is not None:
                    secs = last_time + gap
                    rider_times[name] = secs
                    last_time = secs
            elif "s.t." in time_str.lower() or time_str.lower() in ("st",):
                if last_time is not None:
                    rider_times[name] = last_time
            elif '"' in time_str or "h" in time_str:
                secs = parse_absolute(time_str)
                if secs:
                    rider_times[name] = secs
                    last_time = secs

        if rider_times:
            stages_data.append(rider_times)

    return stages_data


def scrape_points_system_gc(year_html, year, name_lookup):
    """
    Sum per-stage times from Wikipedia stage pages to get cumulative totals.
    Returns {rider_id: total_seconds}.
    """
    stage_page_urls = find_stage_page_urls(year_html, year)
    if not stage_page_urls:
        return {}

    # name (raw string) → cumulative seconds
    cum_by_name: dict[str, int] = {}

    for url in stage_page_urls:
        print(f"    fetching stage page {url.split('/')[-1]} ...", end=" ", flush=True)
        html = fetch(url)
        time.sleep(DELAY)
        if not html:
            print("FAILED")
            continue
        stages = parse_stage_page_times(html)
        print(f"{len(stages)} stage tables")
        for stage_riders in stages:
            for name, secs in stage_riders.items():
                # Only accumulate for riders already seen or first appearance
                cum_by_name[name] = cum_by_name.get(name, 0) + secs

    # Match names to rider IDs
    result = {}
    for name, total in cum_by_name.items():
        rid = match_name(name + " (XXX)", name_lookup) or match_name(name, name_lookup)
        if rid:
            result[rid] = total
    return result


# ── main ───────────────────────────────────────────────────────────────────

def process_year(year, html, name_lookup, conn):
    """Return {rider_id: total_seconds} for this year, or {}."""
    if year == 1904:
        # Use hardcoded post-disqualification results
        winner_time = parse_absolute(HARDCODED_1904[0][1])
        result = {}
        for name, time_str in HARDCODED_1904:
            if time_str.startswith("+"):
                gap = parse_gap(time_str)
                secs = winner_time + gap if gap is not None else None
            else:
                secs = parse_absolute(time_str)
            if secs is None:
                continue
            rid = match_name(name, name_lookup)
            if rid:
                result[rid] = secs
            else:
                print(f"    WARNING: could not match 1904 rider '{name}'")
        return result

    if year in POINTS_SYSTEM_YEARS:
        # Wikipedia stage pages only list top ~10 riders per stage, so cumulative
        # sums are inconsistent across riders (riders with more stage appearances
        # accumulate more time regardless of GC placing). No reliable total-time
        # data is available online for these years; return empty.
        return {}

    # Time-based GC
    rows = scrape_time_based_gc(html)
    result = {}
    for name_raw, secs in rows:
        rid = match_name(name_raw, name_lookup)
        if rid:
            result[rid] = secs
        else:
            # Silently skip — Wikipedia sometimes lists DSQ riders, teams, etc.
            pass
    return result


def main():
    year_args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    years = year_args if year_args else ALL_RACE_YEARS

    conn = sqlite3.connect(DB_PATH)
    name_lookup = build_name_lookup(conn)
    conn.close()

    existing = {}
    if os.path.exists(OUT_PATH) and not year_args:
        with open(OUT_PATH, encoding="utf-8") as f:
            existing = json.load(f)

    results = dict(existing)

    for year in years:
        yr_str = str(year)

        print(f"\n{'='*50}")
        print(f"{year}: fetching Wikipedia ...", end=" ", flush=True)
        html = fetch(f"https://en.wikipedia.org/wiki/{year}_Tour_de_France")
        time.sleep(DELAY)

        if not html and year != 1904:
            print("FAILED")
            continue

        year_data = process_year(year, html or "", name_lookup, conn)
        print(f"→ {len(year_data)} riders matched")

        if year_data:
            results[yr_str] = {str(k): v for k, v in year_data.items()}

    results = dict(sorted(results.items(), key=lambda x: int(x[0])))
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f)

    total_riders = sum(len(v) for v in results.values())
    print(f"\nWrote {len(results)} years, {total_riders} total rider-times → {OUT_PATH}")


if __name__ == "__main__":
    main()
