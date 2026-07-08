#!/usr/bin/env python3
"""
Regenerates cycling-app/src/data/all_races_summary.json — the cross-year
aggregate consumed by the "All Races Overview" view.

Covers every calendar year from 1903 to the latest year in race_editions,
including WWI/WWII gap years (null fields) so the frontend's year axis is
continuous. Run after add_pre1960.py (or any DB-inserting script) whenever
race_editions changes.

Field priority (must match export_gc.py's totalTimeSeconds logic where
applicable):
  totalDistanceKm  — wiki_race_distances.json[year], falls back to
                      SUM(stages.distance_km) if no Wikipedia figure exists.
  totalElevationM  — SUM(stages.vertical_meters); null if no stage in that
                      edition has a recorded value.
  gcWinnerTimeSeconds      — gc_winner_times.json[year]; null if absent
                              (points-system years 1905-1912, or a Tour
                              still in progress with no official winner yet).
  slowestFinisherTimeSeconds — gcWinnerTimeSeconds + MAX(gc_gap_seconds)
                              among FINISHED riders at the edition's last
                              stage; null whenever gcWinnerTimeSeconds is null.

For an in-progress year (only some stages inserted so far, e.g. 2026),
SUM(vertical_meters) only covers the stages raced to date, unlike
totalDistanceKm which already has an authoritative full-route figure from
Wikipedia. all_races_summary_overrides.json lets a field be pinned to the
full planned-route value (e.g. the PCS route page's total) until the real
per-stage data catches up — applied after the DB-computed default, so it's
safe to leave in place across repeated re-exports as more stages are added.

Usage:
  python3 export_all_races_summary.py
"""

import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
WIKI_DISTANCES_PATH = os.path.join(HERE, "wiki_race_distances.json")
GC_WINNER_TIMES_PATH = os.path.join(HERE, "gc_winner_times.json")
OVERRIDES_PATH = os.path.join(HERE, "all_races_summary_overrides.json")
OUT_PATH = os.path.join(HERE, "..", "cycling-app", "src", "data", "all_races_summary.json")

FIRST_YEAR = 1903


def main():
    with open(WIKI_DISTANCES_PATH, encoding="utf-8") as f:
        wiki_distances = json.load(f)
    with open(GC_WINNER_TIMES_PATH, encoding="utf-8") as f:
        gc_winner_times = json.load(f)
    overrides = {}
    if os.path.exists(OVERRIDES_PATH):
        with open(OVERRIDES_PATH, encoding="utf-8") as f:
            overrides = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    last_year = cur.execute("SELECT MAX(year) FROM race_editions").fetchone()[0]

    editions = {
        r["year"]: r["edition_id"]
        for r in cur.execute("SELECT year, edition_id FROM race_editions")
    }

    out = []
    for year in range(FIRST_YEAR, last_year + 1):
        edition_id = editions.get(year)
        if edition_id is None:
            out.append({
                "year": year,
                "totalDistanceKm": None,
                "totalElevationM": None,
                "gcWinnerTimeSeconds": None,
                "slowestFinisherTimeSeconds": None,
            })
            continue

        yr_str = str(year)

        total_distance = wiki_distances.get(yr_str)
        if total_distance is None:
            total_distance = cur.execute(
                "SELECT SUM(distance_km) FROM stages WHERE edition_id=?", (edition_id,)
            ).fetchone()[0]

        total_elevation = cur.execute(
            "SELECT SUM(vertical_meters) FROM stages WHERE edition_id=?", (edition_id,)
        ).fetchone()[0]

        gc_winner_seconds = gc_winner_times.get(yr_str)

        slowest_finisher = None
        if gc_winner_seconds is not None:
            last_stage = cur.execute(
                "SELECT stage_id FROM stages WHERE edition_id=? ORDER BY stage_number DESC LIMIT 1",
                (edition_id,),
            ).fetchone()
            if last_stage:
                max_gap = cur.execute(
                    "SELECT MAX(gc_gap_seconds) FROM stage_results WHERE stage_id=? AND status='FINISHED'",
                    (last_stage["stage_id"],),
                ).fetchone()[0]
                if max_gap is not None:
                    slowest_finisher = gc_winner_seconds + max_gap

        row = {
            "year": year,
            "totalDistanceKm": total_distance,
            "totalElevationM": total_elevation,
            "gcWinnerTimeSeconds": gc_winner_seconds,
            "slowestFinisherTimeSeconds": slowest_finisher,
        }
        row.update(overrides.get(yr_str, {}))
        out.append(row)

    conn.close()

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f)

    print(f"Wrote {len(out)} years ({FIRST_YEAR}-{last_year}) -> {OUT_PATH}")


if __name__ == "__main__":
    main()
