#!/usr/bin/env python3
"""
Build a compact cross-year rider index for the Riders page.

The web app's Riders view needs every rider's per-year Tour result without
loading all 113 per-year data files into the browser. This script collapses
the already-exported gc_by_stage_*.json files into a single small index
(~180 KB gzipped) so the per-year files can be lazy-loaded on demand.

Output: cycling-app/src/data/riders_index.json
  {
    "<rider_id>": {
      "n": "<name>",
      "c": "<nationality or null>",
      "y": { "<year>": [finalRank, "<team or null>"], ... }
    }
  }

Run after export_gc.py (it reads that script's output, not the DB).

Usage:
  python3 export_riders_index.py
"""

import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "cycling-app", "src", "data")
OUT_PATH = os.path.join(DATA_DIR, "riders_index.json")


def main():
    index = {}
    files = sorted(glob.glob(os.path.join(DATA_DIR, "gc_by_stage_*.json")))
    for path in files:
        year = os.path.basename(path).removeprefix("gc_by_stage_").removesuffix(".json")
        with open(path, encoding="utf-8") as f:
            ds = json.load(f)
        for r in ds["riders"]:
            entry = index.setdefault(
                r["id"], {"n": r["name"], "c": r.get("nationality"), "y": {}}
            )
            entry["y"][year] = [r["finalRank"], r.get("team")]

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"Wrote {len(index):,} riders across {len(files)} years -> {OUT_PATH} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
