#!/usr/bin/env python3
"""Export the Life Time off-road races as the frontend's aggregate "gravel" race.

The DB holds six independent races (races.race_type='gravel'); the app shows
ONE race whose "stages" are those races, ordered by the date each was actually
run. Identical in shape to export_classics.py — and, like that script,
deliberately separate from export_gc.py, which is built around "one edition =
one race with N stages".

Two things differ from the classics, both because these races award nothing
cumulative:

  * there is no season standing. The classics accumulate PCS points, which is
    what makes their bump chart a line worth following. These races award no
    points that PCS or anyone else records across the set, and inventing a
    scoring system (the Life Time Grand Prix's own 30-1 scale) would put a
    number in the archive that is not a fact about the race. cumulativePoints
    ships as 0 and the frontend hides the metric.
  * a season is not a fixed set. 1994 holds one race (Leadville alone), 2001
    holds two, 2026 holds six — because these races were founded decades
    apart and only became a series in 2022. That falls out of the date
    ordering for free, exactly as it does for a classics season before 1907.

Usage:
  python3 export_gravel.py             # every year found
  python3 export_gravel.py --year 2024
"""
import argparse
import json
import os
import sqlite3
import sys

from race_common import GRAVEL

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
OUT_DIR = os.path.join(HERE, "..", "cycling-app", "src", "data", "gravel")

DNF_SENTINEL = 9999


def fetch_year(cur, year):
    cur.execute(
        """SELECT s.stage_id, r.name AS race_name, s.stage_date, s.distance_km,
                  s.vertical_meters, s.route_type, s.stage_type, s.cancelled
           FROM stages s
           JOIN race_editions e USING(edition_id)
           JOIN races r USING(race_id)
           WHERE r.race_type = 'gravel' AND e.year = ?
           -- NULL dates sort last rather than silently leading the season.
           ORDER BY (s.stage_date IS NULL), s.stage_date, r.name""",
        (year,),
    )
    stages = [dict(r) for r in cur.fetchall()]
    if not stages:
        return [], {}

    by_id = {s["stage_id"]: i + 1 for i, s in enumerate(stages)}
    qmarks = ",".join("?" * len(by_id))
    cur.execute(
        f"""SELECT sr.stage_id, sr.rider_id, sr.stage_rank, sr.status,
                   sr.gap_seconds, sr.bib_number,
                   ri.full_name, ri.first_name, ri.last_name,
                   c.name AS nationality
            FROM stage_results sr
            JOIN riders ri ON ri.rider_id = sr.rider_id
            LEFT JOIN countries c ON c.code = ri.nationality_code
            WHERE sr.stage_id IN ({qmarks})""",
        list(by_id),
    )
    return stages, {"num": by_id, "rows": [dict(r) for r in cur.fetchall()]}


def build_year(cur, year, short_of):
    stages, res = fetch_year(cur, year)
    if not stages:
        return None

    out_stages = []
    for i, s in enumerate(stages, start=1):
        entry = {
            "stage_number": i,
            "stage_label": s["race_name"],
            "stage_short_label": short_of[s["race_name"]],
            "stage_date": s["stage_date"],
            "start_location": None,
            "finish_location": None,
            "distance_km": s["distance_km"],
            # Always NULL today — see ingest_gravel.py. Shipped so the shape
            # matches every other race and the field can start carrying data
            # without a frontend change.
            "vertical_meters": s["vertical_meters"],
            "route_type": s["route_type"],
            "profile_score": None,
        }
        if s["cancelled"]:
            entry["cancelled"] = True
        out_stages.append(entry)

    by_rider = {}
    for r in res["rows"]:
        n = res["num"][r["stage_id"]]
        rec = by_rider.setdefault(r["rider_id"], {
            "id": r["rider_id"], "name": r["full_name"],
            "firstName": r["first_name"], "lastName": r["last_name"],
            "nationality": r["nationality"], "team": None,
            "bibNumber": r["bib_number"], "byStage": [],
        })
        rec["byStage"].append({
            "stage": n,
            "gcRank": r["stage_rank"],
            "gcGapSeconds": r["gap_seconds"],
            "status": r["status"],
            # Uniform shape for the frontend; none of these races contests a
            # points, sprint or KOM classification.
            "cumulativePoints": 0,
            "cumulativeKomPoints": 0,
            "sprintRank": None,
            "komRank": None,
        })

    riders = []
    for rec in by_rider.values():
        rec["byStage"].sort(key=lambda p: p["stage"])
        finishes = [p["gcRank"] for p in rec["byStage"] if p["gcRank"] is not None]
        # Best finish of the season, as for the classics: a rider's placing in
        # one of these races says nothing about the next, and "their placing at
        # Big Sugar" would be a meaningless way to rank a season.
        rec["finalRank"] = min(finishes) if finishes else DNF_SENTINEL
        rec["totalTimeSeconds"] = None
        if rec["firstName"] is None:
            rec.pop("firstName")
        if rec["lastName"] is None:
            rec.pop("lastName")
        riders.append(rec)
    riders.sort(key=lambda r: (r["finalRank"], r["name"]))
    return {"stages": out_stages, "riders": riders}


def build_index(years_data):
    """Compact riders_index.json, with the per-race `m` constituent table the
    career chart's aggregate toggle reads. Mirrors export_classics.py."""
    teams, races = [], []
    def ridx(name):
        if name not in races:
            races.append(name)
        return races.index(name)

    riders = {}
    for year, data in sorted(years_data.items()):
        labels = {s["stage_number"]: s["stage_label"] for s in data["stages"]}
        for r in data["riders"]:
            key = r["id"].replace("rider/", "")
            rec = riders.setdefault(key, {"n": r["name"], "c": r["nationality"],
                                          "y": {}, "m": {}})
            if r.get("firstName"):
                rec["fn"] = r["firstName"]
            if r.get("lastName"):
                rec["ln"] = r["lastName"]
            # -1 = no team. Athlinks records none for anyone, ever; the table
            # stays empty rather than being dropped, so the loader's shared
            # shape holds.
            rec["y"][str(year)] = [r["finalRank"], -1]
            rec["m"][str(year)] = [
                [ridx(labels[p["stage"]]), p["gcRank"] or DNF_SENTINEL]
                for p in r["byStage"]
            ]
    return {"teams": teams, "races": races, "riders": riders}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    args = ap.parse_args(argv)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    short_of = {info.name: info.short for info in GRAVEL.values()}

    if args.year:
        years = [args.year]
    else:
        cur.execute("""SELECT DISTINCT e.year FROM race_editions e
                       JOIN races r USING(race_id)
                       WHERE r.race_type='gravel' ORDER BY e.year""")
        years = [r[0] for r in cur.fetchall()]

    os.makedirs(OUT_DIR, exist_ok=True)
    built = {}
    for year in years:
        data = build_year(cur, year, short_of)
        if not data:
            print(f"  {year}: no editions, skipped")
            continue
        built[year] = data
        with open(os.path.join(OUT_DIR, f"gc_by_stage_{year}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        canc = sum(1 for s in data["stages"] if s.get("cancelled"))
        print(f"  {year}: {len(data['stages'])} races "
              f"({canc} cancelled), {len(data['riders'])} riders")

    # Single cross-year file: only correct when every year was rebuilt.
    if not args.year:
        idx = build_index(built)
        with open(os.path.join(OUT_DIR, "riders_index.json"), "w",
                  encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  riders_index: {len(idx['riders'])} riders, "
              f"{len(idx['races'])} races")
    else:
        print("  riders_index: SKIPPED (--year run; rerun without --year)")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
