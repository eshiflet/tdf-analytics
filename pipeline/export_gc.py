#!/usr/bin/env python3
"""
Main exporter: cycling.db + JSON supplements -> src/data/<slug>/gc_by_stage_YYYY.json

Usage:
  python3 export_gc.py                          # TDF (default), all years
  python3 export_gc.py --race {tdf,giro,vuelta}  # all years for that race
  python3 export_gc.py --race vuelta --year 2020 # single year only

--year MUST be passed as its own flag ("--year 2020"), not a bare
positional ("... vuelta 2020") — a bare positional is silently ignored
and the script falls back to exporting every year for that race, which
regenerates riders_index.json/all_races_summary.json downstream too
(they always do a full cross-year rebuild). Unrecognized arguments now
raise an error instead of being silently dropped, to prevent exactly
that mistake.
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")

# Sprint scoring changed from golf (low=best) to modern (high=best) in 1959
GOLF_SPRINT_YEARS = set(range(1953, 1959))

# Placeholder paths — always resolved per-race (including TDF) in __main__
# before any of these are read; see resolve_supplement_paths().
SPRINT_POINTS_PATH = "__nonexistent__"
KOM_POINTS_PATH = "__nonexistent__"
GC_ALL_TIMES_PATH = "__nonexistent__"
GC_WINNER_TIMES_PATH = "__nonexistent__"

_sprint_points_cache = None
_kom_points_cache = None
_gc_all_times_cache = None
_gc_winner_times_cache = None

def resolve_supplement_paths(race_subdir):
    """Compute the sprint/KOM/GC-time supplement paths for one race.

    All three races follow the same `{race_subdir}_*.json` naming
    convention. TDF (race_subdir == "tour") has two extras with no
    Giro/Vuelta equivalent: a reconciled-vs-raw KOM fallback, and
    `gc_all_times.json` (Wikipedia per-rider times), which only exists
    for TDF and is left unprefixed since it has no per-race sibling.
    """
    sprint_path = os.path.join(HERE, f"{race_subdir}_sprint_points.json")

    if race_subdir == "tour":
        reconciled = os.path.join(HERE, "tour_kom_points_reconciled.json")
        raw = os.path.join(HERE, "tour_kom_points.json")
        kom_path = reconciled if os.path.exists(reconciled) else raw
        gc_all_times_path = os.path.join(HERE, "gc_all_times.json")
    else:
        kom_path = os.path.join(HERE, f"{race_subdir}_kom_points.json")
        gc_all_times_path = "__nonexistent__"

    gc_winner_path = os.path.join(HERE, f"{race_subdir}_gc_winner_times.json")

    return sprint_path, kom_path, gc_all_times_path, gc_winner_path

def load_gc_all_times():
    global _gc_all_times_cache
    if _gc_all_times_cache is None:
        if os.path.exists(GC_ALL_TIMES_PATH):
            with open(GC_ALL_TIMES_PATH, encoding="utf-8") as f:
                _gc_all_times_cache = json.load(f)
        else:
            _gc_all_times_cache = {}
    return _gc_all_times_cache

def load_gc_winner_times():
    global _gc_winner_times_cache
    if _gc_winner_times_cache is None:
        if os.path.exists(GC_WINNER_TIMES_PATH):
            with open(GC_WINNER_TIMES_PATH, encoding="utf-8") as f:
                _gc_winner_times_cache = json.load(f)
        else:
            _gc_winner_times_cache = {}
    return _gc_winner_times_cache

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


def export_year(year, out_path, race_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # race_id is required: multiple races can share a year, and a year-only
    # lookup silently picks whichever edition it finds first.
    cur.execute(
        "SELECT edition_id FROM race_editions WHERE year = ? AND race_id = ?", (year, race_id)
    )
    row = cur.fetchone()
    if not row:
        print(f"No edition found for {year}")
        sys.exit(1)
    edition_id = row["edition_id"]

    cur.execute(
        """SELECT stage_id, stage_number, stage_date, start_location, finish_location,
                  distance_km, vertical_meters, route_type, profile_score
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
        SELECT sr.rider_id, r.full_name AS name, r.first_name, r.last_name,
               c.name AS nationality,
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
        SELECT DISTINCT sr.rider_id, r.full_name AS name, r.first_name, r.last_name,
               c.name AS nationality, t.name AS team
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

    # Official total race times from Wikipedia scrape (top ~10 riders per year)
    official_times = load_gc_all_times().get(str(year), {})
    # Winner's official total time — used to compute absolute times for riders
    # who have gc_gap_seconds but are not in official_times (e.g. non-top-10)
    winner_time = load_gc_winner_times().get(str(year))

    # gc_gap_seconds at the last stage for each rider (fallback for riders not
    # in official_times but where we have the gap to the winner)
    cur.execute(
        """
        SELECT sr.rider_id, sr.gc_gap_seconds
        FROM stage_results sr
        WHERE sr.stage_id = ? AND sr.gc_gap_seconds IS NOT NULL
        """,
        (last_stage_id,),
    )
    last_stage_gap = {r["rider_id"]: r["gc_gap_seconds"] for r in cur.fetchall()}

    # Fallback: sum of per-stage finish_time_seconds (least preferred)
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
    stage_sum_by_rider = {r["rider_id"]: r["total_seconds"] for r in cur.fetchall()}

    def resolve_total_time(rider_id):
        """
        Priority: Wikipedia official time > winner_time + last_stage_gap
                  > sum of stage finish_time_seconds > None
        """
        t = official_times.get(str(rider_id)) or official_times.get(rider_id)
        if t:
            return t
        if winner_time is not None:
            gap = last_stage_gap.get(rider_id)
            if gap is not None:
                return winner_time + gap
        return stage_sum_by_rider.get(rider_id)

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

        # For riders who DNF'd before the last stage, pick up any final-standings
        # data stored in stage slots beyond their last actual stage (common in early
        # years where only the race total is available, not per-stage breakdowns).
        if by_stage:
            last_sp = by_stage[-1]
            last_stage_idx = stage_num_to_idx.get(last_sp["stage"], -1)
            for catch_idx in range(last_stage_idx + 1, len(sprint_pts_by_year)):
                cum_pts += sprint_pts_by_year[catch_idx].get(rider_id, 0)
            for catch_idx in range(last_stage_idx + 1, len(kom_pts_by_year)):
                cum_kom += kom_pts_by_year[catch_idx].get(rider_id, 0)
            last_sp["cumulativePoints"]    = cum_pts
            last_sp["cumulativeKomPoints"] = cum_kom
            # Also back-fill ranks from the final-stage pre-computed tables
            final_stage_idx = len(stages) - 1
            if last_sp["sprintRank"] is None and final_stage_idx < len(sprint_ranks_by_stage):
                last_sp["sprintRank"] = sprint_ranks_by_stage[final_stage_idx].get(rider_id)
            if last_sp["komRank"] is None and final_stage_idx < len(kom_ranks_by_stage):
                last_sp["komRank"] = kom_ranks_by_stage[final_stage_idx].get(rider_id)

        # Fallback: if finalRank is still 9999 (rider not in final stage data),
        # use the last known gc_rank from byStage when it's within 2 stages of the
        # final stage and the rider's last status was FINISHED. This repairs old
        # races where PCS final-stage pages omit legitimate finishers (e.g. the
        # 1963 Giro winner Balmamion appears in gc_standings through stage 20 but
        # not in stage 21's result rows).
        if final_rank == 9999 and by_stage:
            final_stage_number = stages[-1]["stage_number"]
            last_gc = next(
                (sp for sp in reversed(by_stage) if sp.get("gcRank") is not None),
                None,
            )
            if (
                last_gc is not None
                and by_stage[-1].get("status") == "FINISHED"
                and (final_stage_number - last_gc["stage"]) <= 2
            ):
                final_rank = last_gc["gcRank"]

        entry: dict = {
            "id": rider_id,
            "name": info["name"],
        }
        if info.get("first_name"):
            entry["firstName"] = info["first_name"]
        if info.get("last_name"):
            entry["lastName"] = info["last_name"]
        entry.update({
            "nationality": info["nationality"],
            "team": team,
            "finalRank": final_rank,
            "totalTimeSeconds": resolve_total_time(rider_id),
            "byStage": by_stage,
        })
        riders_out.append(entry)

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
                "profile_score": s["profile_score"] or None,
            }
            for i, s in enumerate(stages)
        ],
        "riders": riders_out,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, separators=(",", ":"), ensure_ascii=False)

    print(f"{year}: {len(riders_out)} riders, {len(stages)} stages -> {out_path}")
    conn.close()


if __name__ == "__main__":
    # Reject stray/unrecognized arguments instead of silently ignoring them
    # (a bare positional year like "2020" used to be dropped, falling back
    # to a full all-years export — see module docstring).
    _consumed = {0}
    for _flag in ("--race", "--year"):
        if _flag in sys.argv:
            _i = sys.argv.index(_flag)
            _consumed.add(_i)
            if _i + 1 >= len(sys.argv):
                sys.exit(f"error: {_flag} requires a value")
            _consumed.add(_i + 1)
    _stray = [a for i, a in enumerate(sys.argv) if i not in _consumed]
    if _stray:
        sys.exit(
            f"error: unrecognized argument(s) {_stray} — "
            f"did you mean '--year {_stray[0]}'? "
            f"Usage: python3 export_gc.py [--race {{tdf,giro,vuelta}}] [--year YYYY]"
        )

    # Determine which race to export
    race_name = "Tour de France"
    race_subdir = "tour"
    if "--race" in sys.argv:
        race_arg = sys.argv[sys.argv.index("--race") + 1]
        if race_arg == "giro":
            race_name = "Giro d'Italia"
            race_subdir = "giro"
        elif race_arg == "vuelta":
            race_name = "Vuelta a España"
            race_subdir = "vuelta"
        elif race_arg == "tdf":
            race_name = "Tour de France"
            race_subdir = "tour"
        else:
            sys.exit(f"error: unknown race '{race_arg}' (use 'tdf', 'giro', or 'vuelta')")

    # Resolve sprint/KOM/GC-time supplement paths for the chosen race — same
    # lookup for TDF as for Giro/Vuelta (see resolve_supplement_paths). Per-race
    # PCS winner times ({race}_gc_winner_times.json, from check_*_gc_times.py)
    # give correct totals as winner_time + last-stage gap; without them,
    # totalTimeSeconds falls back to summing per-stage times, which is wildly
    # wrong for historical years with sparse stage times.
    (
        SPRINT_POINTS_PATH,
        KOM_POINTS_PATH,
        GC_ALL_TIMES_PATH,
        GC_WINNER_TIMES_PATH,
    ) = resolve_supplement_paths(race_subdir)
    _sprint_points_cache = None
    _kom_points_cache = None
    _gc_all_times_cache = None
    _gc_winner_times_cache = None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    race_row = conn.execute("SELECT race_id FROM races WHERE name = ?", (race_name,)).fetchone()
    if not race_row:
        sys.exit(f"error: race '{race_name}' not found in database")
    race_id = race_row["race_id"]

    years = [r[0] for r in conn.execute(
        "SELECT year FROM race_editions WHERE race_id = ? ORDER BY year", (race_id,)
    )]
    conn.close()

    if "--year" in sys.argv:
        wanted = int(sys.argv[sys.argv.index("--year") + 1])
        if wanted not in years:
            sys.exit(f"error: no edition for year {wanted} in the database")
        years = [wanted]

    out_dir = os.path.join(HERE, "..", "cycling-app", "src", "data", race_subdir)
    os.makedirs(out_dir, exist_ok=True)
    for year in years:
        export_year(year, os.path.join(out_dir, f"gc_by_stage_{year}.json"), race_id=race_id)
