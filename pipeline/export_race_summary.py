#!/usr/bin/env python3
"""
Generates cycling-app/src/data/<slug>/all_races_summary.json — the cross-year
aggregate consumed by the "All Races Overview" view, for the Giro d'Italia or
Vuelta a España. Replaces export_giro_races_summary.py / export_vuelta_races_summary.py,
which were ~92% identical.

TDF is NOT covered here: its summary predates these two scripts, lives at
the top-level cycling-app/src/data/all_races_summary.json (not
data/tour/all_races_summary.json), and is built by export_all_races_summary.py
instead — see ai-context.md's "Planned direction" for the plan to eventually
fold it in.

Covers every calendar year from each race's first edition to the latest one
in the DB, including gap years (wars, cancellations) so the x-axis is
continuous.

Fields:
  totalDistanceKm          — SUM(stages.distance_km) for the edition
  totalElevationM          — SUM(stages.vertical_meters); null if unavailable
  gcWinnerTimeSeconds      — sum of finish_time_seconds for the overall GC winner
  slowestFinisherTimeSeconds — gcWinnerTimeSeconds + MAX(gc_gap_seconds) at final stage

Usage:
  python3 export_race_summary.py --race giro
  python3 export_race_summary.py --race vuelta
"""

import json
import os
import sqlite3
import sys

from race_common import DB_PATH

HERE = os.path.dirname(os.path.abspath(__file__))

FIRST_YEAR = {"giro": 1909, "vuelta": 1935}
DB_RACE_NAME = {"giro": "Giro d'Italia", "vuelta": "Vuelta a España"}


def _flag(name, default):
    """Value of an optional `--name VALUE` argument, or default."""
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    if "--race" not in sys.argv:
        sys.exit("usage: python3 export_race_summary.py --race {giro,vuelta}")
    race = sys.argv[sys.argv.index("--race") + 1]
    if race not in FIRST_YEAR:
        sys.exit(
            f"error: unknown race '{race}' (use 'giro' or 'vuelta' — "
            "TDF uses export_all_races_summary.py instead)"
        )
    race_name = DB_RACE_NAME[race]
    first_year = FIRST_YEAR[race]
    # --out / --overrides both default to the real paths, so a bare run is
    # unchanged. They exist so audit_summary_overrides.py can render this same
    # export with an empty overrides file WITHOUT touching the shipped JSON —
    # the alternative (move the overrides file aside, re-export, move it back)
    # leaves the app's real data file overrides-free if it dies in between.
    out_path = _flag("--out", os.path.join(
        HERE, "..", "cycling-app", "src", "data", race, "all_races_summary.json"))
    overrides_path = _flag("--overrides", os.path.join(
        HERE, f"{race}_races_summary_overrides.json"))

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    race_row = cur.execute("SELECT race_id FROM races WHERE name = ?", (race_name,)).fetchone()
    if not race_row:
        print(f"{race_name} not found in races table")
        return
    race_id = race_row["race_id"]

    last_year = cur.execute(
        "SELECT MAX(year) FROM race_editions WHERE race_id=?", (race_id,)
    ).fetchone()[0]
    if not last_year:
        print(f"No {race_name} editions found")
        return

    editions = {
        r["year"]: r["edition_id"]
        for r in cur.execute(
            "SELECT year, edition_id FROM race_editions WHERE race_id=?", (race_id,)
        )
    }

    overrides = {}
    if os.path.exists(overrides_path):
        with open(overrides_path, encoding="utf-8") as f:
            overrides = {int(k): v for k, v in json.load(f).items()}

    # Authoritative GC winner times, keyed by year as a string. Same file
    # export_gc.py reads; loaded here so both exporters agree on the figure.
    curated_winner_times = {}
    winner_times_path = os.path.join(HERE, f"{race}_gc_winner_times.json")
    if os.path.exists(winner_times_path):
        with open(winner_times_path, encoding="utf-8") as f:
            curated_winner_times = json.load(f)

    out = []
    for year in range(first_year, last_year + 1):
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

            # The curated {race}_gc_winner_times.json wins when it has the year,
            # and is consulted BEFORE the winner lookup — it identifies the time
            # without needing to identify the rider. That matters: 19 Giro
            # editions have no gc_rank=1 row on their final stage (the sparse
            # final stage validate_db warns about), so gating the curated value
            # behind `if winner_row` left every one of them empty even after the
            # figure was added to the file.
            #
            # Summing per-stage times is only a FALLBACK: it silently
            # understates any edition where some stages lack a winner time, and
            # there is no way to tell a short sum from a short race. Vuelta 1968
            # had times for 12 of its 20 stages and reported 18:33:54 against a
            # real 78:29:00. export_gc.py has always preferred this file; this
            # exporter did not.
            gc_winner_seconds = curated_winner_times.get(str(year))

            if gc_winner_seconds is None and winner_row:
                total_time = cur.execute(
                    """SELECT SUM(sr.finish_time_seconds)
                       FROM stage_results sr
                       JOIN stages s ON sr.stage_id = s.stage_id
                       WHERE s.edition_id=? AND sr.rider_id=?
                         AND sr.finish_time_seconds IS NOT NULL""",
                    (edition_id, winner_row["rider_id"]),
                ).fetchone()[0]
                if total_time:
                    gc_winner_seconds = int(total_time)

            if gc_winner_seconds:
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

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)

    years_with_data = sum(1 for r in out if r["totalDistanceKm"] is not None)
    print(f"Wrote {len(out)} years ({first_year}-{last_year}), {years_with_data} with data -> {out_path}")


if __name__ == "__main__":
    main()
