#!/usr/bin/env python3
"""
Build a compact cross-year rider index for the Riders page.

The web app's Riders view needs every rider's per-year Tour result without
loading all 113 per-year data files into the browser. This script collapses
the already-exported gc_by_stage_*.json files into a single small index
so the per-year files can be lazy-loaded on demand.

Output: cycling-app/src/data/riders_index.json
  {
    "teams": ["<team name>", ...],            # string table, sorted
    "riders": {
      "<rider slug>": {                       # rider id minus the "rider/" prefix
        "n": "<name>",
        "c": "<nationality or null>",
        "y": { "<year>": [gcRank, teamIdx]                        # no points rankings
               | [gcRank, teamIdx, sprintRank, komRank], ... }    # 0 = that rank absent
      }
    }
  }

teamIdx indexes into the "teams" table; -1 = no team recorded. Team names
repeat across thousands of rider-years, so the table cuts the raw payload by
roughly a third versus inlining the strings. Most rider-years have no
sprint/KOM ranking, so the short 2-element form avoids shipping sentinel
values for ~65% of entries. gcRank 9999 = DNF/DNS.

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
    riders = {}
    team_names = set()
    files = sorted(glob.glob(os.path.join(DATA_DIR, "gc_by_stage_*.json")))
    raw_years = []  # (entry, year, rider_record) triples for the second pass
    for path in files:
        year = os.path.basename(path).removeprefix("gc_by_stage_").removesuffix(".json")
        with open(path, encoding="utf-8") as f:
            ds = json.load(f)
        for r in ds["riders"]:
            slug = r["id"].removeprefix("rider/")
            entry = riders.setdefault(
                slug, {"n": r["name"], "c": r.get("nationality"), "y": {}}
            )
            if r.get("team"):
                team_names.add(r["team"])
            raw_years.append((entry, year, r))

    teams = sorted(team_names)
    team_idx = {t: i for i, t in enumerate(teams)}

    for entry, year, r in raw_years:
        ti = team_idx.get(r.get("team"), -1)
        last_stage = r["byStage"][-1] if r.get("byStage") else None
        sprint_rank = (last_stage.get("sprintRank") or 9999) if last_stage else 9999
        kom_rank = (last_stage.get("komRank") or 9999) if last_stage else 9999
        if sprint_rank == 9999 and kom_rank == 9999:
            entry["y"][year] = [r["finalRank"], ti]
        else:
            entry["y"][year] = [
                r["finalRank"],
                ti,
                0 if sprint_rank == 9999 else sprint_rank,
                0 if kom_rank == 9999 else kom_rank,
            ]

    index = {"teams": teams, "riders": riders}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(
        f"Wrote {len(riders):,} riders / {len(teams)} teams across "
        f"{len(files)} years -> {OUT_PATH} ({size_kb:.0f} KB)"
    )


if __name__ == "__main__":
    main()
