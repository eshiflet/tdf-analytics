#!/usr/bin/env python3
"""
Create stage files for race days PCS has but vuelta_scrapes/YEAR/ lacks.

The original scrape_vuelta.py discovery only probed stage-N slugs, so it
missed prologues entirely (1979–1987 all have one) and could drop a split
stage. scrape_vuelta_gc_pages.py records the full race-day slug list
(gc_pages/_slugs.json) and a full result table per day; this script diffs the
two and materializes any missing day as a normal stage_N.json scrape file:

  - a missing prologue becomes stage_0.json with n=0 (the TDF convention;
    numeric ordering puts it first, export labels it "P")
  - a missing mid-race day shifts later stage files up by one (files are
    renamed, their internal "n" rewritten) and slots in at its position

Run AFTER scrape_vuelta_gc_pages.py and BEFORE build_vuelta_gc_standings.py /
build_vuelta_points.py / ingest_vuelta.py.

Usage:
  python3 make_missing_vuelta_days.py 1979-1997
  python3 make_missing_vuelta_days.py --race giro 1909-1997
  python3 make_missing_vuelta_days.py 1985 --dry-run
"""

import json
import os
import re
import sys
from glob import glob

HERE = os.path.dirname(os.path.abspath(__file__))
_dirname = "vuelta_scrapes"
if "--race" in sys.argv:
    _race = sys.argv[sys.argv.index("--race") + 1]
    _dirname = {"vuelta": "vuelta_scrapes", "giro": "giro_scrapes"}.get(_race)
    if not _dirname:
        sys.exit(f"error: unknown race '{_race}' (use vuelta or giro)")
SCRAPES_DIR = os.path.join(HERE, _dirname)

from scrape_vuelta import parse_year_args  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv


def numeric_stage_files(year: int) -> list[str]:
    files = glob(os.path.join(SCRAPES_DIR, str(year), "stage_*.json"))
    return sorted(files, key=lambda p: int(re.search(r"stage_(\d+)\.json$", p).group(1)))


def day_key(info: dict) -> tuple:
    return (info.get("Date"), (info.get("Finish") or "").strip().lower())


def build_stage_payload(gp: dict, n: int) -> dict:
    info = dict(gp.get("info", {}))
    if gp["slug"] == "prologue" and "time trial" not in (info.get("Won how") or "").lower():
        # prologues are individual time trials by definition; PCS often leaves
        # "Won how" empty on them, which would misclassify the route type
        info["Won how"] = "Individual time trial (prologue)"
    return {
        "n": n,
        "info": info,
        "profile_icon": gp.get("profile_icon", "p1"),
        "rows": gp.get("result_rows", []),
        "sprint_points": {},
        "kom_points": {},
    }


def process_year(year: int) -> None:
    gp_dir = os.path.join(SCRAPES_DIR, str(year), "gc_pages")
    slugs_path = os.path.join(gp_dir, "_slugs.json")
    if not os.path.exists(slugs_path):
        print(f"{year}: no gc_pages/_slugs.json — run scrape_vuelta_gc_pages.py first")
        return
    with open(slugs_path) as f:
        slugs = json.load(f)

    gc_pages = {}
    for s in slugs:
        p = os.path.join(gp_dir, f"{s}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                gc_pages[s] = json.load(f)

    files = numeric_stage_files(year)
    file_keys = {}
    for path in files:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        file_keys[path] = day_key(d.get("info", {}))

    matched_slugs = set()
    for path, key in file_keys.items():
        for s, gp in gc_pages.items():
            if s in matched_slugs:
                continue
            if day_key(gp.get("info", {})) == key:
                matched_slugs.add(s)
                break
    unmatched_files = [p for p, k in file_keys.items()
                       if not any(day_key(gc_pages[s]["info"]) == k for s in matched_slugs)]
    missing = [s for s in slugs if s not in matched_slugs and s in gc_pages]

    # second pass: date-only match to absorb spelling differences
    still_missing = []
    for s in missing:
        gdate = gc_pages[s]["info"].get("Date")
        cands = [p for p in unmatched_files if file_keys[p][0] == gdate]
        if len(cands) == 1:
            matched_slugs.add(s)
            unmatched_files.remove(cands[0])
        else:
            still_missing.append(s)
    missing = still_missing

    if not missing:
        print(f"{year}: complete ({len(files)} files cover {len(slugs)} PCS days)")
        return

    for s in missing:
        gp = gc_pages[s]
        if not gp.get("result_rows"):
            print(f"{year}: {s} missing but gc_pages has no result rows — SKIPPED")
            continue
        slug_pos = slugs.index(s)
        if slug_pos == 0 and s == "prologue":
            n = 0
            out = os.path.join(SCRAPES_DIR, str(year), "stage_0.json")
            if os.path.exists(out):
                print(f"{year}: stage_0.json already exists, skipping {s}")
                continue
            print(f"{year}: creating stage_0.json (n=0) from {s} "
                  f"({len(gp['result_rows'])} rows, {gp['info'].get('Date')})")
            if not DRY_RUN:
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(build_stage_payload(gp, 0), f, ensure_ascii=False)
        else:
            # mid-race missing day: it belongs at file number slug_pos+1 when a
            # prologue file exists (n=0) or slug list has no prologue; shift
            # everything at that number and above up by one
            has_prologue_slug = slugs and slugs[0] == "prologue"
            insert_n = slug_pos if has_prologue_slug else slug_pos + 1
            print(f"{year}: inserting {s} as stage_{insert_n}.json, shifting later files up")
            if not DRY_RUN:
                existing = [(int(re.search(r"stage_(\d+)\.json$", p).group(1)), p)
                            for p in numeric_stage_files(year)]
                for num, path in sorted(existing, reverse=True):
                    if num < insert_n:
                        continue
                    with open(path, encoding="utf-8") as f:
                        d = json.load(f)
                    d["n"] = num + 1
                    new_path = os.path.join(SCRAPES_DIR, str(year), f"stage_{num + 1}.json")
                    with open(new_path, "w", encoding="utf-8") as f:
                        json.dump(d, f, ensure_ascii=False)
                    os.remove(path)
                out = os.path.join(SCRAPES_DIR, str(year), f"stage_{insert_n}.json")
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(build_stage_payload(gp, insert_n), f, ensure_ascii=False)

    stale = os.path.join(SCRAPES_DIR, str(year), "gc_standings.json")
    if not DRY_RUN and os.path.exists(stale):
        os.remove(stale)   # rebuild with build_vuelta_gc_standings.py


def main():
    years = parse_year_args(sys.argv[1:])
    if not years:
        print("Usage: python3 make_missing_vuelta_days.py YEAR|RANGE... [--dry-run]")
        sys.exit(1)
    for year in years:
        process_year(year)


if __name__ == "__main__":
    main()
