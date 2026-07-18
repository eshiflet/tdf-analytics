#!/usr/bin/env python3
"""
Build vuelta_sprint_points.json and vuelta_kom_points.json from scraped stage files.

Structure: { "2025": [ {rider_slug: points, ...}, ... ] }
where the outer array is indexed by stage (0-based).
"""

import json
import os
from glob import glob

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES_DIR = os.path.join(HERE, "vuelta_scrapes")


def stage_num(path: str) -> int:
    import re
    return int(re.search(r"stage_(\d+)\.json$", path).group(1))


def load_year(stage_files: list[str]) -> tuple[list[dict], list[dict]]:
    sprint_by_stage = []
    kom_by_stage = []
    # numeric sort: plain sorted() is lexicographic (stage_1, stage_10, ...,
    # stage_2), which misaligns the arrays with DB stage order for any year
    # with 10+ stages — export_gc.py indexes these arrays by stage position
    for sf in sorted(stage_files, key=stage_num):
        with open(sf, encoding="utf-8") as f:
            data = json.load(f)
        sprint_by_stage.append(data.get("sprint_points", {}))
        kom_by_stage.append(data.get("kom_points", {}))
    return sprint_by_stage, kom_by_stage


def main():
    all_sprint = {}
    all_kom = {}

    for entry in sorted(os.listdir(SCRAPES_DIR)):
        year_dir = os.path.join(SCRAPES_DIR, entry)
        if os.path.isdir(year_dir) and entry.isdigit():
            stage_files = glob(os.path.join(year_dir, "stage_*.json"))
            if stage_files:
                sprint, kom = load_year(stage_files)
                all_sprint[entry] = sprint
                all_kom[entry] = kom
                print(f"  {entry}: {len(stage_files)} stages")

    if not all_sprint:
        print("No stage files found in", SCRAPES_DIR)
        return

    sp_path = os.path.join(HERE, "vuelta_sprint_points.json")
    with open(sp_path, "w", encoding="utf-8") as f:
        json.dump(all_sprint, f)
    print(f"Wrote {sp_path} ({len(all_sprint)} years)")

    kp_path = os.path.join(HERE, "vuelta_kom_points.json")
    with open(kp_path, "w", encoding="utf-8") as f:
        json.dump(all_kom, f)
    print(f"Wrote {kp_path} ({len(all_kom)} years)")


if __name__ == "__main__":
    main()
