#!/usr/bin/env python3
"""
Generates cycling-app/src/data/vuelta/all_races_summary.json — the cross-year
aggregate consumed by the "All Races Overview" view for the Vuelta a España.

Covers every calendar year from 1935 to the latest Vuelta edition in the DB.
Gap years (1936-1940 due to Spanish Civil War and WWII, and other non-running
years) get null values so the x-axis is continuous.

Usage:
  python3 export_vuelta_races_summary.py
"""

import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
OUT_PATH = os.path.join(HERE, "..", "cycling-app", "src", "data", "vuelta", "all_races_summary.json")
OVERRIDES_PATH = os.path.join(HERE, "vuelta_races_summary_overrides.json")

FIRST_YEAR = 1935


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    race_row = cur.execute("SELECT race_id FROM races WHERE name = ?", ("Vuelta a España",)).fetchone()
    if not race_row:
        print("Vuelta a España not found in races table")
        return
    race_id = race_row["race_id"]

    last_year = cur.execute(
        "SELECT MAX(year) FROM race_editions WHERE race_id=?", (race_id,)
    ).fetchone()[0]
    if not last_year:
        print("No Vuelta editions found")
        return

    editions = {
        r["year"]: r["edition_id"]
        for r in cur.execute(
            "SELECT year, edition_id FROM race_editions WHERE race_id=?", (race_id,)
        )
    }

    overrides = {}
    if os.path.exists(OVERRIDES_PATH):
        with open(OVERRIDES_PATH, encoding="utf-8") as f:
            overrides = {int(k): v for k, v in json.load(f).items()}

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

        total_distance = cur.execute(
            "SELECT SUM(distance_km) FROM stages WHERE edition_id=?", (edition_id,)
        ).fetchone()[0]

        total_elevation = cur.execute(
            "SELECT SUM(vertical_meters) FROM stages WHERE edition_id=?", (edition_id,)
        ).fetchone()[0]

        last_stage = cur.execute(
            "SELECT stage_id FROM stages WHERE edition_id=? ORDER BY stage_number DESC LIMIT 1",
            (edition_id,),
        ).fetchone()

        gc_winner_seconds = None
        slowest_finisher = None

        if last_stage:
            last_stage_id = last_stage["stage_id"]
            winner_row = cur.execute(
                "SELECT rider_id FROM stage_results WHERE stage_id=? AND gc_rank=1 LIMIT 1",
                (last_stage_id,),
            ).fetchone()

            if winner_row:
                winner_id = winner_row["rider_id"]
                total_time = cur.execute(
                    """SELECT SUM(sr.finish_time_seconds)
                       FROM stage_results sr
                       JOIN stages s ON sr.stage_id = s.stage_id
                       WHERE s.edition_id=? AND sr.rider_id=?
                         AND sr.finish_time_seconds IS NOT NULL""",
                    (edition_id, winner_id),
                ).fetchone()[0]

                if total_time:
                    gc_winner_seconds = int(total_time)
                    max_gap = cur.execute(
                        """SELECT MAX(gc_gap_seconds) FROM stage_results
                           WHERE stage_id=? AND status='FINISHED'""",
                        (last_stage_id,),
                    ).fetchone()[0]
                    if max_gap is not None:
                        slowest_finisher = gc_winner_seconds + int(max_gap)

        row = {
            "year": year,
            "totalDistanceKm": round(total_distance, 1) if total_distance else None,
            "totalElevationM": int(total_elevation) if total_elevation else None,
            "gcWinnerTimeSeconds": gc_winner_seconds,
            "slowestFinisherTimeSeconds": slowest_finisher,
        }
        row.update(overrides.get(year, {}))
        out.append(row)

    conn.close()

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f)

    years_with_data = sum(1 for r in out if r["totalDistanceKm"] is not None)
    print(f"Wrote {len(out)} years ({FIRST_YEAR}-{last_year}), {years_with_data} with data -> {OUT_PATH}")


if __name__ == "__main__":
    main()
