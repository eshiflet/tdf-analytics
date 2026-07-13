#!/usr/bin/env python3
"""
Build giro_sprint_points.json and giro_kom_points.json from scraped stage files.

These files have the same structure as sprint_points.json / kom_points.json:
  { "2026": [ {rider_slug: points, ...}, ... ] }
where the outer array is indexed by stage (0-based).
"""

import json
import os
from glob import glob

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES_DIR = os.path.join(HERE, "giro_scrapes")


def main():
    stage_files = sorted(glob(os.path.join(SCRAPES_DIR, "stage_*.json")))
    if not stage_files:
        print("No stage files found")
        return

    sprint_by_stage = []
    kom_by_stage = []

    for sf in stage_files:
        with open(sf, encoding="utf-8") as f:
            data = json.load(f)
        sprint_by_stage.append(data.get("sprint_points", {}))
        kom_by_stage.append(data.get("kom_points", {}))

    sprint_out = {"2026": sprint_by_stage}
    kom_out = {"2026": kom_by_stage}

    sp_path = os.path.join(HERE, "giro_sprint_points.json")
    with open(sp_path, "w", encoding="utf-8") as f:
        json.dump(sprint_out, f)
    print(f"Wrote {sp_path} ({len(sprint_by_stage)} stages)")

    kp_path = os.path.join(HERE, "giro_kom_points.json")
    with open(kp_path, "w", encoding="utf-8") as f:
        json.dump(kom_out, f)
    print(f"Wrote {kp_path} ({len(kom_by_stage)} stages)")


if __name__ == "__main__":
    main()
