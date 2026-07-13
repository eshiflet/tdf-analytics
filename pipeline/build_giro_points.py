#!/usr/bin/env python3
"""
Build giro_sprint_points.json and giro_kom_points.json from scraped stage files.

These files have the same structure as sprint_points.json / kom_points.json:
  { "2026": [ {rider_slug: points, ...}, ... ] }
where the outer array is indexed by stage (0-based).

Supports two directory layouts:
  - giro_scrapes/stage_N.json          (legacy flat layout, assumed year 2026)
  - giro_scrapes/YEAR/stage_N.json     (multi-year layout)
"""

import json
import os
from glob import glob

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES_DIR = os.path.join(HERE, "giro_scrapes")


def load_year(stage_files: list[str]) -> tuple[list[dict], list[dict]]:
    sprint_by_stage = []
    kom_by_stage = []
    for sf in sorted(stage_files):
        with open(sf, encoding="utf-8") as f:
            data = json.load(f)
        sprint_by_stage.append(data.get("sprint_points", {}))
        kom_by_stage.append(data.get("kom_points", {}))
    return sprint_by_stage, kom_by_stage


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
