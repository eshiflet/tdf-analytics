#!/usr/bin/env python3
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
SPRINT_POINTS_PATH = os.path.join(HERE, "sprint_points.json")

# Load scraped real sprint points (finish line + intermediate sprints, no KOM).
# Structure: {year_str: [stage0_dict, stage1_dict, ...]}
# where each stage_dict maps rider_slug -> points earned that stage.
# Array index matches DB stage ordering (stage_number order) for that year.
_sprint_points_cache = None

def load_sprint_points():
    global _sprint_points_cache
    if _sprint_points_cache is None:
        if os.path.exists(SPRINT_POINTS_PATH):
            with open(SPRINT_POINTS_PATH, encoding="utf-8") as f:
                _sprint_points_cache = json.load(f)
        else:
            _sprint_points_cache = {}
    return _sprint_points_cache


def export_year(year, out_path):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        "SELECT edition_id FROM race_editions WHERE year = ?", (year,)
    )
    row = cur.fetchone()
    if not row:
        print(f"No edition found for {year}")
        sys.exit(1)
    edition_id = row["edition_id"]

    cur.execute(
        """SELECT stage_id, stage_number, start_location, finish_location,
                  distance_km, vertical_meters, route_type
           FROM stages WHERE edition_id = ? ORDER BY stage_number""",
        (edition_id,),
    )
    stages = [dict(r) for r in cur.fetchall()]
    stage_ids = [s["stage_id"] for s in stages]

    # Build stage_number → index lookup for sprint_points array alignment
    stage_num_to_idx = {s["stage_number"]: i for i, s in enumerate(stages)}

    # Load real sprint points for this year (array indexed by stage position)
    sprint_pts_by_year = load_sprint_points().get(str(year), [])

    # final GC rank per rider = gc_rank on the last stage they have a result for
    last_stage_id = stage_ids[-1]

    cur.execute(
        """
        SELECT sr.rider_id, r.full_name AS name, c.name AS nationality,
               t.name AS team, sr.gc_rank AS finalRank
        FROM stage_results sr
        JOIN riders r ON r.rider_id = sr.rider_id
        LEFT JOIN countries c ON c.code = r.nationality_code
        LEFT JOIN teams t ON t.team_id = sr.team_id
        WHERE sr.stage_id = ?
        """,
        (last_stage_id,),
    )
    final_rows = {r["rider_id"]: dict(r) for r in cur.fetchall()}

    # all riders who appear anywhere in this edition (in case some DNF'd before the last stage)
    cur.execute(
        """
        SELECT DISTINCT sr.rider_id, r.full_name AS name, c.name AS nationality, t.name AS team
        FROM stage_results sr
        JOIN stages st ON st.stage_id = sr.stage_id
        JOIN riders r ON r.rider_id = sr.rider_id
        LEFT JOIN countries c ON c.code = r.nationality_code
        LEFT JOIN teams t ON t.team_id = sr.team_id
        WHERE st.edition_id = ?
        """,
        (edition_id,),
    )
    all_riders = {r["rider_id"]: dict(r) for r in cur.fetchall()}

    riders_out = []
    for rider_id, info in all_riders.items():
        final = final_rows.get(rider_id)
        final_rank = final["finalRank"] if final and final["finalRank"] is not None else 9999
        team = (final or info).get("team") or info.get("team")

        cur.execute(
            """
            SELECT st.stage_number AS stage, sr.gc_rank AS gcRank,
                   sr.gc_gap_seconds AS gcGapSeconds, sr.status AS status
            FROM stage_results sr
            JOIN stages st ON st.stage_id = sr.stage_id
            WHERE st.edition_id = ? AND sr.rider_id = ?
            ORDER BY st.stage_number
            """,
            (edition_id, rider_id),
        )
        by_stage = [dict(r) for r in cur.fetchall()]

        # Compute cumulative sprint points from real scraped sprint data
        cum_pts = 0
        for sp in by_stage:
            stage_idx = stage_num_to_idx.get(sp["stage"])
            if stage_idx is not None and stage_idx < len(sprint_pts_by_year):
                cum_pts += sprint_pts_by_year[stage_idx].get(rider_id, 0)
            sp["cumulativePoints"] = cum_pts

        riders_out.append({
            "id": rider_id,
            "name": info["name"],
            "nationality": info["nationality"],
            "team": team,
            "finalRank": final_rank,
            "byStage": by_stage,
        })

    riders_out.sort(key=lambda r: r["finalRank"])

    dataset = {
        "stages": [
            {
                "stage_number": s["stage_number"],
                "start_location": s["start_location"],
                "finish_location": s["finish_location"],
                "distance_km": s["distance_km"],
                "vertical_meters": s["vertical_meters"],
                "route_type": s["route_type"],
            }
            for s in stages
        ],
        "riders": riders_out,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f)

    print(f"{year}: {len(riders_out)} riders, {len(stages)} stages -> {out_path}")
    conn.close()


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    years = [r[0] for r in conn.execute("SELECT year FROM race_editions ORDER BY year")]
    conn.close()
    out_dir = os.path.join(HERE, "..", "cycling-app", "src", "data")
    os.makedirs(out_dir, exist_ok=True)
    for year in years:
        export_year(year, os.path.join(out_dir, f"gc_by_stage_{year}.json"))
