#!/usr/bin/env python3
"""
Generates cycling-app/src/data/giro/all_races_summary.json — the cross-year
aggregate consumed by the "All Races Overview" view for the Giro d'Italia.

Covers every calendar year from 1909 to the latest Giro edition in the DB,
including gap years (WWI 1915-1918, WWII 1941-1945, and other non-running years)
so the x-axis is continuous.

Fields:
  totalDistanceKm          — SUM(stages.distance_km) for the edition
  totalElevationM          — SUM(stages.vertical_meters); null if unavailable
  gcWinnerTimeSeconds      — sum of finish_time_seconds for the overall GC winner
  slowestFinisherTimeSeconds — gcWinnerTimeSeconds + MAX(gc_gap_seconds) at final stage

Usage:
  python3 export_giro_races_summary.py
"""

import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
OUT_PATH = os.path.join(HERE, "..", "cycling-app", "src", "data", "giro", "all_races_summary.json")
OVERRIDES_PATH = os.path.join(HERE, "giro_races_summary_overrides.json")

FIRST_YEAR = 1909


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    race_row = cur.execute("SELECT race_id FROM races WHERE name = ?", ("Giro d'Italia",)).fetchone()
    if not race_row:
        print("Giro d'Italia not found in races table")
        return
    race_id = race_row["race_id"]

    last_year = cur.execute(
        "SELECT MAX(year) FROM race_editions WHERE race_id=?", (race_id,)
    ).fetchone()[0]
    if not last_year:
        print("No Giro editions found")
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

        # GC winner = rider with gc_rank=1 at the final stage
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
                # Sum finish_time_seconds for winner across all stages
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
                    # Slowest = winner + max gap at final stage among finishers
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
