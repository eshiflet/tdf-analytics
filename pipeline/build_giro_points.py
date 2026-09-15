#!/usr/bin/env python3
"""
Build giro_sprint_points.json and giro_kom_points.json from scraped stage files.

These files have the same structure as tour_sprint_points.json / tour_kom_points.json:
  { "2026": [ {rider_slug: points, ...}, ... ] }
where the outer array is indexed by stage (0-based).

Supports two directory layouts:
  - giro_scrapes/stage_N.json          (legacy flat layout, assumed year 2026)
  - giro_scrapes/YEAR/stage_N.json     (multi-year layout)
"""

import json
import re
import os
from glob import glob

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES_DIR = os.path.join(HERE, "giro_scrapes")


def stage_num(path: str) -> int:
    import re
    return int(re.search(r"stage_(\d+)\.json$", path).group(1))


def load_year(stage_files: list[str]) -> tuple[list[dict], list[dict]]:
    """Points per stage, as arrays export_gc.py can index by DB stage position.

    Built over the contiguous range of stage numbers, NOT over the files
    present, and a number with no file gets an empty dict. A CANCELLED stage
    has no scrape file by design — the scraper refuses to write one — but it
    DOES have a row in `stages`, and export_gc.py reads
    `sprint_pts_by_year[stage_idx]` with stage_idx counted over every stage of
    the edition. Appending only the files that exist shifts every later stage
    up one: the Vuelta 2026, whose stage 3 was cancelled for hail, would have
    credited stage 4's sprint points to stage 3, and dropped stage 21's
    entirely off the end of the array.

    A prologue is stage 0, so the range starts at the lowest number present
    rather than at 1.
    """
    by_num = {}
    for sf in stage_files:
        with open(sf, encoding="utf-8") as f:
            by_num[stage_num(sf)] = json.load(f)
    if not by_num:
        return [], []
    order = range(min(by_num), max(by_num) + 1)
    return ([by_num.get(n, {}).get("sprint_points", {}) for n in order],
            [by_num.get(n, {}).get("kom_points", {}) for n in order])


def main():
    all_sprint = {}
    all_kom = {}

    # Check for year subdirectories
    for entry in sorted(os.listdir(SCRAPES_DIR)):
        year_dir = os.path.join(SCRAPES_DIR, entry)
        if os.path.isdir(year_dir) and entry.isdigit():
            stage_files = glob(os.path.join(year_dir, "stage_*.json"))
            if stage_files:
                sprint, kom = load_year(stage_files)
                all_sprint[entry] = sprint
                all_kom[entry] = kom
                print(f"  {entry}: {len(stage_files)} stages")

    # Also check for flat layout (legacy 2026 files)
    flat_files = glob(os.path.join(SCRAPES_DIR, "stage_*.json"))
    if flat_files and "2026" not in all_sprint:
        sprint, kom = load_year(flat_files)
        all_sprint["2026"] = sprint
        all_kom["2026"] = kom
        print(f"  2026 (flat): {len(flat_files)} stages")

    if not all_sprint:
        print("No stage files found")
        return

    sp_path = os.path.join(HERE, "giro_sprint_points.json")
    with open(sp_path, "w", encoding="utf-8") as f:
        json.dump(all_sprint, f)
    print(f"Wrote {sp_path} ({len(all_sprint)} years)")

    kp_path = os.path.join(HERE, "giro_kom_points.json")
    with open(kp_path, "w", encoding="utf-8") as f:
        json.dump(all_kom, f)
    print(f"Wrote {kp_path} ({len(all_kom)} years)")


if __name__ == "__main__":
    main()
