#!/usr/bin/env python3
"""
Scrape per-stage GC standings from bikeraceinfo.com for all TdF years.

Produces bri_stages.json:
  {
    "1986": [
      {
        "label": "Prologue",
        "distance_km": 4.6,
        "date": "Friday, July 4",
        "route": "Boulogne-Billancourt",
        "stage_top10": [
          {"rank": 1, "name": "Thierry Marie", "time_sec": 321, "gap_sec": 0},
          ...
        ],
        "gc_top10": [
          {"rank": 1, "name": "Thierry Marie", "cumulative_sec": 321, "gap_sec": 0},
          ...
        ]
      }, ...
    ], ...
  }

Note: BRI inline per-stage GC is only available for years up to ~2009.
Later years link to individual stage pages (not scraped here).

Usage:
  python3 scrape_bri_stages.py              # all years
  python3 scrape_bri_stages.py 1982 1986   # specific years
  python3 scrape_bri_stages.py --resume    # skip years already in output
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

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(HERE, "cycling.db")
OUT_PATH = os.path.join(HERE, "bri_stages.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; tdf-analytics-validator/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 1.2


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


def parse_time_sec(s: str) -> int | None:
    """
    Parse time strings like '6hr 3min 18sec', '41min 21sec', '5min 21sec',
    '20min 51.840sec', '1hr 10min 27sec' into total seconds.
    Returns None if unparseable.
    """
    s = s.strip().lower()
    total = 0
    m = re.search(r"(\d+)\s*hr", s)
    if m:
        total += int(m.group(1)) * 3600
    m = re.search(r"(\d+)\s*min", s)
    if m:
        total += int(m.group(1)) * 60
    m = re.search(r"([\d.]+)\s*sec", s)
    if m:
        total += int(float(m.group(1)))
    return total if total > 0 else None


def parse_gap_sec(s: str) -> int | None:
    """
    Parse gap strings like '@ 4min 37sec', '@ 1sec', '@ 2sec'.
    Returns 0 for 's.t.' (same time). Returns None if unparseable.
    """
    s = s.strip().lower()
    if s in ("s.t.", "st", "same time", ""):
        return 0
    if "@" not in s and "same" not in s:
        return None
    gap_part = s.split("@", 1)[-1].strip()
    return parse_time_sec(gap_part)


def clean_name(raw: str) -> str:
    """Strip team names in parens, rank numbers, leading/trailing junk."""
    # Remove content in parentheses (team names)
    s = re.sub(r"\([^)]*\)", "", raw)
    # Remove leading rank number if present
    s = re.sub(r"^\d+\.\s*", "", s)
    # Remove trailing punctuation / time data after the name
    s = re.sub(r"[:@].*$", "", s)
    return " ".join(s.split())


def parse_result_list(items: list[str], is_gc_leader_time: bool = False) -> list[dict]:
    """
    Parse a list of <dd> or <li> text strings into result dicts.
    is_gc_leader_time: if True, first entry has cumulative time; else stage winner time.
    """
    results = []
    leader_time = None

    for i, raw in enumerate(items):
        raw = raw.strip()
        if not raw:
            continue

        # Remove embedded HTML tags
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = re.sub(r"&[a-z]+;", " ", raw)
        raw = " ".join(raw.split())

        # Extract rank if present (e.g. "1. Name: time")
        rank_m = re.match(r"^(\d+)[.)]\s*", raw)
        rank = int(rank_m.group(1)) if rank_m else i + 1
        rest = raw[rank_m.end():] if rank_m else raw

        # Split name from time on ": " or "@ " or " s.t."
        if ":" in rest and not rest.strip().startswith("@"):
            parts = rest.split(":", 1)
            name = clean_name(parts[0])
            time_part = parts[1].strip()
            if rank == 1 or is_gc_leader_time:
                t = parse_time_sec(time_part)
                if t:
                    leader_time = t
                    results.append({"rank": rank, "name": name,
                                    "time_sec": t, "gap_sec": 0})
                else:
                    results.append({"rank": rank, "name": name,
                                    "time_sec": None, "gap_sec": 0})
            else:
                gap = parse_gap_sec(time_part)
                results.append({"rank": rank, "name": name, "gap_sec": gap})
        elif "@" in rest or "s.t." in rest.lower():
            # Gap from leader
            at_idx = rest.find("@")
            st_idx = rest.lower().find("s.t.")
            split_idx = at_idx if at_idx != -1 else st_idx
            name = clean_name(rest[:split_idx])
            gap_part = rest[split_idx:].strip()
            gap = parse_gap_sec(gap_part)
            results.append({"rank": rank, "name": name, "gap_sec": gap})
        else:
            # Name only, no time
            name = clean_name(rest)
            if name:
                results.append({"rank": rank, "name": name, "gap_sec": None})

    # Compute cumulative seconds for GC entries
    if is_gc_leader_time and leader_time is not None:
        for r in results:
            if "time_sec" not in r:
                if r.get("gap_sec") is not None:
                    r["cumulative_sec"] = leader_time + r["gap_sec"]
                else:
                    r["cumulative_sec"] = None
            else:
                r["cumulative_sec"] = r.get("time_sec")

    return results


def extract_list_items(html_block: str) -> list[str]:
    """Extract text items from <dl><dd> or <ol><li> blocks."""
    items = re.findall(r"<(?:dd|li)[^>]*>(.*?)</(?:dd|li)>", html_block, re.DOTALL | re.IGNORECASE)
    if not items:
        # Try without closing tags (self-contained <dd> lines)
        items = re.findall(r"<(?:dd|li)[^>]*>(.*?)(?=<(?:dd|li|/dl|/ol))", html_block, re.DOTALL | re.IGNORECASE)
    return items


def parse_stage_header(text: str) -> dict:
    """
    Parse stage header text like:
      'Stage 12: Tuesday, July 15, Bayonne - Pau, 217.5 km'
      'Prologue: Friday, July 4, Boulogne-Billancourt, 4.6 km'
      'Stage 1A: Sunday, June 26, Lille - Brussels, 108 km'
    Returns dict with label, date, route, distance_km.
    """
    result = {}
    # Stage label
    label_m = re.match(r"(Prologue|Stage\s*[\dA-Za-z]+)", text, re.IGNORECASE)
    result["label"] = label_m.group(1).strip() if label_m else ""
    result["label"] = re.sub(r"\s+", " ", result["label"])

    # Distance
    dist_m = re.search(r"([\d.]+)\s*km", text)
    result["distance_km"] = float(dist_m.group(1)) if dist_m else None

    # Date — look for day-of-week pattern
    date_m = re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*([^,]+)", text, re.IGNORECASE)
    result["date"] = f"{date_m.group(1)}, {date_m.group(2).strip()}" if date_m else None

    # Route — city names between date and distance
    # Remove label and distance, keep middle
    middle = text
    if label_m:
        middle = middle[label_m.end():].lstrip(":, ")
    if dist_m:
        middle = middle[:middle.rfind(dist_m.group(0))].rstrip(", ")
    if date_m:
        after_date = middle.find(date_m.group(0))
        if after_date != -1:
            middle = middle[after_date + len(date_m.group(0)):].lstrip(", ")
    route = re.sub(r"[,;]\s*$", "", middle).strip()
    result["route"] = route if route else None

    return result


def parse_year_html(html: str) -> list[dict]:
    """
    Parse all stages + GC from a BRI year page.
    Returns list of stage dicts.
    """
    # Find the stages section start
    section_m = re.search(r'id=["\']?(?:stages|results)["\']?', html, re.IGNORECASE)
    if not section_m:
        # Try finding the first stage header as fallback
        section_m = re.search(r"<(?:b|strong)>(?:Stage\s*1\b|Prologue)", html, re.IGNORECASE)
    if not section_m:
        return []

    section = html[section_m.start():]

    # Find all stage headers. Two patterns:
    #   A) Label + distance inside one <b>: <b>Stage 12: ... 217.5 km</b>
    #   B) Label inside <b>, distance after: <p><b>Prologue:</b> Friday..., 4.6 km.</p>
    # We match the enclosing <p> when pattern A fails.
    stage_header_pat = re.compile(
        r"<p[^>]*>\s*<(?:b|strong)>((?:Prologue|Stage\s*[\dA-Za-z]+)[^<]*?)"
        r"</(?:b|strong)>([^<]*?(?:[\d.]+\s*km)[^<]*?)</p>"
        r"|"
        r"<(?:b|strong)>((?:Prologue|Stage\s*[\dA-Za-z]+)[^<]*?(?:[\d.]+\s*km)[^<]*?)"
        r"</(?:b|strong)>",
        re.IGNORECASE
    )

    def extract_header(m):
        # Pattern B (split across tag boundary): groups 1+2
        if m.group(1) is not None:
            return (m.group(1).strip() + " " + m.group(2).strip()).strip()
        # Pattern A (all inside tag): group 3
        return m.group(3).strip()

    stage_positions = [(m.start(), extract_header(m)) for m in stage_header_pat.finditer(section)]
    if not stage_positions:
        return []

    stages = []
    for idx, (pos, header_text) in enumerate(stage_positions):
        # Chunk: from this stage header to the next (or end of section)
        end = stage_positions[idx + 1][0] if idx + 1 < len(stage_positions) else len(section)
        chunk = section[pos:end]

        stage = parse_stage_header(header_text)

        # Major ascents (optional)
        ascent_m = re.search(r"[Mm]ajor\s+[Aa]scents?:([^<\r\n]+)", chunk)
        stage["major_ascents"] = ascent_m.group(1).strip() if ascent_m else None

        # Find the stage result list (before any GC block)
        gc_split = re.search(r"GC\s+after\s+(?:stage|Stage)", chunk)
        result_chunk = chunk[:gc_split.start()] if gc_split else chunk

        # Find first <dl> or <ol> in result chunk
        list_m = re.search(r"(<(?:dl|ol)[^>]*>.*?</(?:dl|ol)>)", result_chunk, re.DOTALL | re.IGNORECASE)
        if list_m:
            items = extract_list_items(list_m.group(1))
            stage["stage_top10"] = parse_result_list(items, is_gc_leader_time=False)[:10]
        else:
            stage["stage_top10"] = []

        # Check if stage header says "GC and stage times are the same"
        header_same = bool(re.search(r"GC and stage times are the same", chunk[:400], re.IGNORECASE))

        # Find GC block after results
        if header_same and not gc_split:
            # GC = stage results
            stage["gc_top10"] = [
                {**r, "cumulative_sec": r.get("time_sec"), "gap_sec": 0 if i == 0 else r.get("gap_sec")}
                for i, r in enumerate(stage["stage_top10"])
            ]
        elif gc_split:
            gc_chunk = chunk[gc_split.start():]
            # Skip "GC after stage N: Same as..." shorthand
            same_m = re.search(r"GC[^<\r\n]*Same", gc_chunk, re.IGNORECASE)
            list_m2 = re.search(r"(<(?:dl|ol)[^>]*>.*?</(?:dl|ol)>)", gc_chunk, re.DOTALL | re.IGNORECASE)
            if same_m and (not list_m2 or same_m.start() < list_m2.start()):
                stage["gc_top10"] = [
                    {**r, "cumulative_sec": r.get("time_sec"), "gap_sec": 0 if i == 0 else r.get("gap_sec")}
                    for i, r in enumerate(stage["stage_top10"])
                ]
            elif list_m2:
                items2 = extract_list_items(list_m2.group(1))
                stage["gc_top10"] = parse_result_list(items2, is_gc_leader_time=True)[:12]
            else:
                stage["gc_top10"] = []
        else:
            stage["gc_top10"] = []

        if stage["label"]:
            stages.append(stage)

    return stages


def scrape_year(year: int) -> list[dict] | None:
    url = f"https://bikeraceinfo.com/tdf/tdf{year}.html"
    html = fetch(url)
    if not html:
        return None

    stages = parse_year_html(html)
    if not stages:
        return None

    # Filter: if no stage has GC data, the year page probably links out
    has_gc = any(s["gc_top10"] for s in stages)
    if not has_gc:
        print(f"    No inline GC data found (page may link to individual stage pages)")
        return None

    return stages


def main():
    exit_on_help(__doc__)
    args = sys.argv[1:]
    resume = "--resume" in args
    year_args = [int(a) for a in args if a.isdigit()]

    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            data: dict[str, list] = json.load(f)
    else:
        data = {}

    conn = sqlite3.connect(DB_PATH)
    all_years = [r[0] for r in conn.execute("SELECT year FROM race_editions ORDER BY year")]
    conn.close()

    years = year_args if year_args else all_years

    for year in years:
        yr = str(year)
        if resume and yr in data:
            print(f"{year}: skipping (already scraped, {len(data[yr])} stages)")
            continue

        print(f"{year}: scraping...", end=" ", flush=True)
        stages = scrape_year(year)
        time.sleep(DELAY)

        if stages is None:
            print("no data")
            data[yr] = []
        else:
            gc_stages = sum(1 for s in stages if s["gc_top10"])
            print(f"{len(stages)} stages, {gc_stages} with GC data")
            data[yr] = stages

        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nDone → {OUT_PATH}")


if __name__ == "__main__":
    main()
