#!/usr/bin/env python3
"""Export the one-day classics as the frontend's aggregate "classics" race.

The DB holds 11 independent one-day races; the app shows ONE race whose
"stages" are those races. This script does that aggregation:

  edition  = a season (all 11 classics of one year)
  "stage"  = one classic, ordered by the date it was actually run
  gcRank   = the rider's finishing position in that race (NOT cumulative)

Ordering by stage_date rather than a fixed calendar is what makes 2020 come
out right — COVID moved Il Lombardia to August, ahead of Fleche and Liege.

`finalRank` is the rider's BEST finish of the season, not their last. It
drives legend ordering and the Top 10/20 quick-select, and "their placing at
Lombardia" would be meaningless for ranking a season. `totalTimeSeconds` is
null: a season of unrelated races has no total time.

This is deliberately separate from export_gc.py, which is built around one
edition = one race with N stages. The classics invert that (N editions of N
races = one displayed season), so sharing that code would mean contorting
both. See architecture.md.

Usage:
  python3 export_classics.py              # every year found
  python3 export_classics.py --year 2021
"""
import argparse
import json
import os
import sqlite3
import sys

from race_common import CLASSICS

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
OUT_DIR = os.path.join(HERE, "..", "cycling-app", "src", "data", "classics")

DNF_SENTINEL = 9999


def name_to_slug():
    return {info.name: slug for slug, info in CLASSICS.items()}


def fetch_year(cur, year):
    """(stages, results) for one season, stages in real calendar order."""
    cur.execute(
        """SELECT s.stage_id, r.name AS race_name, s.stage_date, s.start_location,
                  s.finish_location, s.distance_km, s.vertical_meters,
                  s.profile_score, s.route_type, s.cancelled
           FROM stages s
           JOIN race_editions e USING(edition_id)
           JOIN races r USING(race_id)
           WHERE r.race_type = 'one_day' AND e.year = ?
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
                   sr.gap_seconds, sr.team_id, sr.bib_number,
                   ri.full_name, ri.first_name, ri.last_name,
                   c.name AS nationality, t.name AS team_name
            FROM stage_results sr
            JOIN riders ri ON ri.rider_id = sr.rider_id
            LEFT JOIN countries c ON c.code = ri.nationality_code
            LEFT JOIN teams t ON t.team_id = sr.team_id
            WHERE sr.stage_id IN ({qmarks})""",
        list(by_id),
    )
    results = [dict(r) for r in cur.fetchall()]
    return stages, {"num": by_id, "rows": results}


def build_year(cur, year, slug_of):
    stages, res = fetch_year(cur, year)
    if not stages:
        return None

    out_stages = []
    for i, s in enumerate(stages, start=1):
        entry = {
            "stage_number": i,
            "stage_label": s["race_name"],
            "stage_short_label": CLASSICS[slug_of[s["race_name"]]].short,
            # ISO. The frontend shows it in the column tooltip; it is also what
            # the season is ordered by, so a missing one is worth seeing.
            "stage_date": s["stage_date"],
            "start_location": s["start_location"],
            "finish_location": s["finish_location"],
            "distance_km": s["distance_km"],
            "vertical_meters": s["vertical_meters"],
            "route_type": s["route_type"],
            "profile_score": s["profile_score"],
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
            "nationality": r["nationality"], "team": r["team_name"],
            "bibNumber": r["bib_number"], "byStage": [],
        })
        # A rider's team is per-race here; keep the first non-null seen.
        if rec["team"] is None and r["team_name"]:
            rec["team"] = r["team_name"]
        rec["byStage"].append({
            "stage": n,
            "gcRank": r["stage_rank"],
            "gcGapSeconds": r["gap_seconds"],
            "status": r["status"],
            # Sprint/KOM are not contested in the classics; the frontend hides
            # both metrics for this race, but the shape stays uniform.
            "cumulativePoints": 0,
            "cumulativeKomPoints": 0,
            "sprintRank": None,
            "komRank": None,
        })

    riders = []
    for rec in by_rider.values():
        rec["byStage"].sort(key=lambda p: p["stage"])
        finishes = [p["gcRank"] for p in rec["byStage"] if p["gcRank"] is not None]
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
    """Compact riders_index.json, including the classics-only `races`/`m`
    constituent tables the career chart's "C" toggle reads."""
    teams, races = [], []
    def tidx(name):
        if name is None:
            return -1
        if name not in teams:
            teams.append(name)
        return teams.index(name)
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
            ti = tidx(r["team"])
            rec["y"][str(year)] = [r["finalRank"], ti]
            # [raceIdx, rank] only — the team is already stored once per year
            # in `y`, and every constituent of a season carried the identical
            # index, so repeating it cost ~150 KB gzipped for nothing.
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
    slug_of = name_to_slug()

    if args.year:
        years = [args.year]
    else:
        cur.execute(
            """SELECT DISTINCT e.year FROM race_editions e
               JOIN races r USING(race_id)
               WHERE r.race_type='one_day' ORDER BY e.year""")
        years = [r[0] for r in cur.fetchall()]

    os.makedirs(OUT_DIR, exist_ok=True)
    built = {}
    for year in years:
        data = build_year(cur, year, slug_of)
        if not data:
            print(f"  {year}: no editions, skipped")
            continue
        built[year] = data
        path = os.path.join(OUT_DIR, f"gc_by_stage_{year}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        canc = sum(1 for s in data["stages"] if s.get("cancelled"))
        print(f"  {year}: {len(data['stages'])} races "
              f"({canc} cancelled), {len(data['riders'])} riders")

    # The index is a single cross-year file, so it is only correct when every
    # year was rebuilt — skip it on a --year run rather than write a partial.
    if not args.year:
        idx = build_index(built)
        with open(os.path.join(OUT_DIR, "riders_index.json"), "w",
                  encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  riders_index: {len(idx['riders'])} riders, "
              f"{len(idx['teams'])} teams, {len(idx['races'])} races")
    else:
        print("  riders_index: SKIPPED (--year run; rerun without --year)")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
