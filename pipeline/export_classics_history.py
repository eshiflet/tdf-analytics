#!/usr/bin/env python3
"""Export per-race trends across the whole archive, for the classics history view.

The Grand Tours' All Years Summary totals a single race's stages per year. That
is meaningless for the classics — a season is eleven unrelated races, so its
"total distance" is an arbitrary sum. What IS meaningful is the opposite pivot:
one series per RACE, tracked across its own history.

Output: cycling-app/src/data/classics/race_history.json

  {"races": [{"name": ..., "short": ..., "first": 1896, "last": 2026,
              "years": [{"y": 1896, "km": 280.0, "kmh": 30.2, "n": 28}, ...]}]}

  km   distance
  kmh  winner's average speed, distance / winning time
  n    classified finishers (a proxy for field size and attrition)

Speed is DERIVED here rather than taken from PCS's "Avg. speed winner" field,
which is absent for most historical editions; distance and winning time are
present for 965 of 971 editions. A cancelled race contributes no point at all —
its planned distance is not a fact about a race that happened.
"""
import json
import os
import sqlite3
import sys

from race_common import CLASSICS

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
OUT = os.path.join(HERE, "..", "cycling-app", "src", "data", "classics",
                   "race_history.json")


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT r.name AS race_name, e.year, s.cancelled,
               s.distance_km, s.vertical_meters,
               (SELECT sr.finish_time_seconds FROM stage_results sr
                 WHERE sr.stage_id = s.stage_id AND sr.stage_rank = 1
                 ORDER BY sr.finish_time_seconds LIMIT 1) AS win_secs,
               (SELECT COUNT(*) FROM stage_results sr
                 WHERE sr.stage_id = s.stage_id AND sr.stage_rank IS NOT NULL) AS finishers
        FROM stages s
        JOIN race_editions e USING(edition_id)
        JOIN races r USING(race_id)
        WHERE r.race_type = 'one_day'
        ORDER BY r.name, e.year""")

    name_to_slug = {info.name: slug for slug, info in CLASSICS.items()}
    by_race = {}
    rejected = []
    for row in cur.fetchall():
        if row["cancelled"]:
            continue
        pt = {"y": row["year"]}
        if row["distance_km"]:
            pt["km"] = round(row["distance_km"], 1)
        if row["distance_km"] and row["win_secs"]:
            kmh = row["distance_km"] / (row["win_secs"] / 3600.0)
            # A road-race winner averages roughly 20-50 km/h; the archive spans
            # 22.9 (1896 Roubaix) to 48.9 (2026 Roubaix). Anything outside these
            # generous bounds is a corrupt time, not a discovery, and publishing
            # it would wreck the y-axis for every other race. Milan-San Remo
            # 1915 was the case that proved it: PCS serves '3:18', which parses
            # to 198 seconds and charts at 5254 km/h. REPORTED, never silently
            # dropped — a rejection here means the DB needs fixing.
            if 15 <= kmh <= 60:
                pt["kmh"] = round(kmh, 1)
            else:
                rejected.append(f"{row['race_name']} {row['year']}: "
                                f"{kmh:.0f} km/h from {row['win_secs']}s "
                                f"over {row['distance_km']}km")
        if row["finishers"]:
            pt["n"] = row["finishers"]
        # A year with nothing but its own number tells the reader nothing.
        if len(pt) > 1:
            by_race.setdefault(row["race_name"], []).append(pt)

    races = []
    # Ordered by first edition, so the legend reads as a history.
    for name, years in sorted(by_race.items(), key=lambda kv: kv[1][0]["y"]):
        races.append({
            "name": name,
            "short": CLASSICS[name_to_slug[name]].short,
            "first": years[0]["y"],
            "last": years[-1]["y"],
            "years": years,
        })

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"races": races}, f, ensure_ascii=False, separators=(",", ":"))

    print(f"wrote {os.path.relpath(OUT, HERE)}")
    for r in races:
        pts = r["years"]
        spd = [p["kmh"] for p in pts if "kmh" in p]
        print(f"  {r['short']:<4} {r['name']:<26} {r['first']}-{r['last']}  "
              f"{len(pts):>3} editions, {len(spd):>3} with speed"
              + (f"  {min(spd)}-{max(spd)} km/h" if spd else ""))
    if rejected:
        print(f"\n  IMPLAUSIBLE SPEEDS REJECTED ({len(rejected)}) — fix the DB:")
        for line in rejected:
            print(f"    {line}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
