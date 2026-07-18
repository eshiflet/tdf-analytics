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
        "yw": [1984, 1989],                    # years rider won young-rider (white jersey)
                                                # classification; omitted if never
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

GC/sprint/KOM winning years are derived client-side from gcRank/sprintRank/
komRank === 1 per year, so only the young-rider (white jersey) win needs its
own field here — that classification isn't tracked anywhere else in the
exported per-year JSON, only in the DB's classification_standings table.

Run after export_gc.py (it reads that script's output for everything except
the youth-winner years, which come directly from cycling.db).

Usage:
  python3 export_riders_index.py
"""

import glob
import json
import os
import sqlite3
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "cycling-app", "src", "data", "tour")
OUT_PATH = os.path.join(DATA_DIR, "riders_index.json")
DB_PATH = os.path.join(HERE, "cycling.db")


def load_youth_winners():
    """Maps rider_id -> sorted list of years with a rank=1 finish in the
    youth (white jersey) classification, per cycling.db's
    classification_standings table."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT cs.rider_id, re.year FROM classification_standings cs "
        "JOIN race_editions re ON re.edition_id = cs.edition_id "
        "WHERE cs.classification = 'youth' AND cs.rank = 1"
    )
    winners = defaultdict(list)
    for rider_id, year in cur.fetchall():
        winners[rider_id].append(year)
    conn.close()
    return {rider_id: sorted(years) for rider_id, years in winners.items()}


def main():
    youth_winners = load_youth_winners()

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
            entry = riders.setdefault(slug, {"n": r["name"], "c": r.get("nationality"), "y": {}})
            if r.get("firstName") and "fn" not in entry:
                entry["fn"] = r["firstName"]
            if r.get("lastName") and "ln" not in entry:
                entry["ln"] = r["lastName"]
            if r["id"] in youth_winners:
                entry["yw"] = youth_winners[r["id"]]
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
