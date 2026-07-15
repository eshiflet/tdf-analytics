#!/usr/bin/env python3
"""
Build a compact cross-year rider index for the Vuelta a España Riders page.

Reads from cycling-app/src/data/vuelta/gc_by_stage_*.json and writes
cycling-app/src/data/vuelta/riders_index.json in the same format as the
TDF/Giro riders_index.json.

Usage:
  python3 export_vuelta_riders_index.py
"""

import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VUELTA_DATA_DIR = os.path.join(HERE, "..", "cycling-app", "src", "data", "vuelta")
OUT_PATH = os.path.join(VUELTA_DATA_DIR, "riders_index.json")


def main():
    riders = {}
    team_names = set()
    files = sorted(glob.glob(os.path.join(VUELTA_DATA_DIR, "gc_by_stage_*.json")))
    if not files:
        print("No Vuelta gc_by_stage_*.json files found")
        return

    raw_years = []
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
