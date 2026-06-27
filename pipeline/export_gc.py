#!/usr/bin/env python3
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")

# Sprint scoring changed from golf (low=best) to modern (high=best) in 1959
GOLF_SPRINT_YEARS = set(range(1953, 1959))
SPRINT_POINTS_PATH = os.path.join(HERE, "sprint_points.json")
# Use reconciled KOM data if available, fall back to raw PCS scrape
_KOM_RECONCILED = os.path.join(HERE, "kom_points_reconciled.json")
_KOM_RAW        = os.path.join(HERE, "kom_points.json")
KOM_POINTS_PATH = _KOM_RECONCILED if os.path.exists(_KOM_RECONCILED) else _KOM_RAW

_sprint_points_cache = None
_kom_points_cache = None

def load_sprint_points():
    global _sprint_points_cache
    if _sprint_points_cache is None:
        if os.path.exists(SPRINT_POINTS_PATH):
            with open(SPRINT_POINTS_PATH, encoding="utf-8") as f:
                _sprint_points_cache = json.load(f)
        else:
            _sprint_points_cache = {}
    return _sprint_points_cache

def load_kom_points():
    global _kom_points_cache
    if _kom_points_cache is None:
        if os.path.exists(KOM_POINTS_PATH):
            with open(KOM_POINTS_PATH, encoding="utf-8") as f:
                _kom_points_cache = json.load(f)
        else:
            _kom_points_cache = {}
    return _kom_points_cache


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
        """SELECT stage_id, stage_number, stage_date, start_location, finish_location,
                  distance_km, vertical_meters, route_type
           FROM stages WHERE edition_id = ? ORDER BY stage_number""",
        (edition_id,),
    )
    stages = [dict(r) for r in cur.fetchall()]
    stage_ids = [s["stage_id"] for s in stages]

    # Build stage_number → index lookup for sprint_points array alignment
    stage_num_to_idx = {s["stage_number"]: i for i, s in enumerate(stages)}

    # Compute display labels: same-date stages get "Na"/"Nb"; stage_number 0 = "P"; others "N"
    from collections import defaultdict
    date_groups = defaultdict(list)
    for i, s in enumerate(stages):
        date_groups[s.get("stage_date") or f"__nodate_{i}"].append(i)
    stage_labels = [""] * len(stages)
    day_counter = 0
    for date in sorted(date_groups.keys()):
        indices = date_groups[date]
        if len(indices) == 1:
            i = indices[0]
            if stages[i]["stage_number"] == 0:
                stage_labels[i] = "P"
            else:
                day_counter += 1
                stage_labels[i] = str(day_counter)
        else:
            day_counter += 1
            for j, i in enumerate(indices):
                stage_labels[i] = f"{day_counter}{'abcde'[j]}"

    # Load real sprint/KOM points for this year (array indexed by stage position)
    sprint_pts_by_year = load_sprint_points().get(str(year), [])
    kom_pts_by_year = load_kom_points().get(str(year), [])

    # Pre-compute cumulative sprint & KOM standings and ranks at each stage.
    # This lets us rank all riders relative to each other per stage.
    golf_sprint = year in GOLF_SPRINT_YEARS

    sprint_cum_running = {}   # rider_id -> cumulative points so far
    kom_cum_running    = {}
    sprint_ranks_by_stage = []   # [stage_idx] -> {rider_id: rank (1=best)}
    kom_ranks_by_stage    = []

    for stage_idx in range(len(stages)):
        # Accumulate this stage's points into running totals
        sp_stage = sprint_pts_by_year[stage_idx] if stage_idx < len(sprint_pts_by_year) else {}
        km_stage = kom_pts_by_year[stage_idx]    if stage_idx < len(kom_pts_by_year)    else {}
        for rid, pts in sp_stage.items():
            sprint_cum_running[rid] = sprint_cum_running.get(rid, 0) + pts
        for rid, pts in km_stage.items():
            kom_cum_running[rid] = kom_cum_running.get(rid, 0) + pts

        # Sprint rank: golf years → ascending (lower pts = better), else descending
        if sprint_cum_running:
            reverse = not golf_sprint
            ranked = sorted(sprint_cum_running.items(), key=lambda x: x[1], reverse=reverse)
            sprint_ranks_by_stage.append({rid: r + 1 for r, (rid, _) in enumerate(ranked)})
        else:
            sprint_ranks_by_stage.append({})

        # KOM rank: always descending (higher pts = better)
        if kom_cum_running:
            ranked = sorted(kom_cum_running.items(), key=lambda x: -x[1])
            kom_ranks_by_stage.append({rid: r + 1 for r, (rid, _) in enumerate(ranked)})
        else:
            kom_ranks_by_stage.append({})

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

    # Compute total race time per rider (sum of finish_time_seconds across all stages)
    cur.execute(
        """
        SELECT sr.rider_id, SUM(sr.finish_time_seconds) AS total_seconds
        FROM stage_results sr
        JOIN stages st ON st.stage_id = sr.stage_id
        WHERE st.edition_id = ? AND sr.finish_time_seconds IS NOT NULL
        GROUP BY sr.rider_id
        """,
        (edition_id,),
    )
    total_time_by_rider = {r["rider_id"]: r["total_seconds"] for r in cur.fetchall()}

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

        # Attach cumulative sprint/KOM points and ranks from pre-computed tables
        cum_pts = 0
        cum_kom = 0
        for sp in by_stage:
            stage_idx = stage_num_to_idx.get(sp["stage"])
            if stage_idx is not None:
                if stage_idx < len(sprint_pts_by_year):
                    cum_pts += sprint_pts_by_year[stage_idx].get(rider_id, 0)
                if stage_idx < len(kom_pts_by_year):
                    cum_kom += kom_pts_by_year[stage_idx].get(rider_id, 0)
                sp["sprintRank"] = sprint_ranks_by_stage[stage_idx].get(rider_id) if stage_idx < len(sprint_ranks_by_stage) else None
                sp["komRank"]    = kom_ranks_by_stage[stage_idx].get(rider_id)    if stage_idx < len(kom_ranks_by_stage)    else None
            else:
                sp["sprintRank"] = None
                sp["komRank"]    = None
            sp["cumulativePoints"]    = cum_pts
            sp["cumulativeKomPoints"] = cum_kom

        riders_out.append({
            "id": rider_id,
            "name": info["name"],
            "nationality": info["nationality"],
            "team": team,
            "finalRank": final_rank,
            "totalTimeSeconds": total_time_by_rider.get(rider_id),
            "byStage": by_stage,
        })

    riders_out.sort(key=lambda r: r["finalRank"])

    dataset = {
        "stages": [
            {
                "stage_number": s["stage_number"],
                "stage_label": stage_labels[i],
                "start_location": s["start_location"],
                "finish_location": s["finish_location"],
                "distance_km": s["distance_km"] or None,
                "vertical_meters": s["vertical_meters"] or None,
                "route_type": s["route_type"],
            }
            for i, s in enumerate(stages)
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
