#!/usr/bin/env python3
"""Shared exporter for the AGGREGATE race sets — the one-day classics and the
Life Time off-road races.

Both invert the shape export_gc.py is built around. There, one edition is one
race with N stages. Here, an edition is a SEASON and each "stage" is a separate
race, ordered by the date it was actually run:

  edition  = a season (all 11 classics, or all six off-road races, of one year)
  "stage"  = one race, in real calendar order
  gcRank   = the rider's finishing position in that race (NOT cumulative)

Ordering by stage_date rather than a fixed calendar is what makes 2020 come out
right — COVID moved Il Lombardia to August, ahead of Fleche and Liege — and it
is also why a season can hold a different NUMBER of races each year without any
special-casing: the off-road set's 1994 holds only Leadville, and a classics
season before 1907 holds fewer than eleven.

`finalRank` is the rider's BEST finish of the season, not their last. It drives
legend ordering and the Top 10/20 quick-select, and "their placing at Lombardia"
would be meaningless for ranking a season. `totalTimeSeconds` is null: a season
of unrelated races has no total time.

WHY ONE MODULE RATHER THAN TWO SCRIPTS

export_gravel.py was written as a copy of export_classics.py and measured 71%
identical to it. The remaining 29% turned out not to be logic at all — only the
race_type filter, the output directory and the info table. Everything that
looked set-specific falls out of the data:

  * the season-standings block is a NO-OP for a set that awards no points.
    Every off-road result has pcs_points NULL, so the running total stays 0 and
    sprintRank stays None — which is exactly what that set needs to ship.
    No flag required.
  * teams likewise. tidx(None) is already -1, so a set with no team data emits
    an empty `teams` table without being told it has none.
  * start_location, finish_location and profile_score are NULL for the off-road
    races, so selecting them unconditionally yields the same null-filled output
    the bespoke query produced.

Verified by byte-identical output for both sets before and after the merge.
"""
import json
import os
import sqlite3
from dataclasses import dataclass

from link_rider_race_sets import stamp as stamp_cross_race
from race_common import CLASSICS, GRAVEL

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
DATA_ROOT = os.path.join(HERE, "..", "cycling-app", "src", "data")

DNF_SENTINEL = 9999


@dataclass(frozen=True)
class RaceSet:
    slug: str        # frontend race id, and the data directory under src/data/
    race_type: str   # races.race_type of its constituent races
    info: dict       # constituent slug -> an object with .name and .short


RACE_SETS = {
    "classics": RaceSet("classics", "one_day", CLASSICS),
    "gravel": RaceSet("gravel", "gravel", GRAVEL),
}


def fetch_year(cur, race_set, year):
    """(stages, results) for one season, stages in real calendar order."""
    cur.execute(
        """SELECT s.stage_id, r.name AS race_name, s.stage_date, s.start_location,
                  s.finish_location, s.distance_km, s.vertical_meters,
                  s.profile_score, s.route_type, s.cancelled
           FROM stages s
           JOIN race_editions e USING(edition_id)
           JOIN races r USING(race_id)
           WHERE r.race_type = ? AND e.year = ?
           -- NULL dates sort last rather than silently leading the season.
           ORDER BY (s.stage_date IS NULL), s.stage_date, r.name""",
        (race_set.race_type, year),
    )
    stages = [dict(r) for r in cur.fetchall()]
    if not stages:
        return [], {}

    by_id = {s["stage_id"]: i + 1 for i, s in enumerate(stages)}
    qmarks = ",".join("?" * len(by_id))
    cur.execute(
        f"""SELECT sr.stage_id, sr.rider_id, sr.stage_rank, sr.status,
                   sr.gap_seconds, sr.team_id, sr.bib_number, sr.pcs_points,
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


def build_year(cur, race_set, year, short_of):
    stages, res = fetch_year(cur, race_set, year)
    if not stages:
        return None

    out_stages = []
    for i, s in enumerate(stages, start=1):
        entry = {
            "stage_number": i,
            "stage_label": s["race_name"],
            "stage_short_label": short_of[s["race_name"]],
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
            # cumulativePoints/sprintRank carry the SEASON STANDING, not a
            # sprint classification — neither set contests one. Filled in below
            # once every rider's races are known. KOM is genuinely unused, but
            # the shape stays uniform for the frontend.
            "points": r["pcs_points"] or 0,
            "cumulativePoints": 0,
            "cumulativeKomPoints": 0,
            "sprintRank": None,
            "komRank": None,
        })

    # ── Season standings ────────────────────────────────────────────────────
    # A rider's placing in one race says nothing about the next, so the bump
    # chart's line is meaningless until the y-axis accumulates something. PCS
    # points do accumulate, and PCS assigns them across the whole archive (the
    # 1890s included), so this works for every classics season.
    #
    # For a set that awards no points this loop is a no-op by construction —
    # every total stays 0 and every sprintRank stays None — which is exactly
    # what such a set should ship. That is why there is no flag here.
    #
    # Carried forward across races the rider did NOT contest: a standing is a
    # running total, and resetting or gapping it would make a rider appear to
    # lose points by missing a race.
    for rec in by_rider.values():
        rec["byStage"].sort(key=lambda p: p["stage"])
    n_races = len(out_stages)
    running = {rid: 0 for rid in by_rider}
    for n in range(1, n_races + 1):
        for rid, rec in by_rider.items():
            pt = next((p for p in rec["byStage"] if p["stage"] == n), None)
            if pt:
                running[rid] += pt["points"]
        standing = sorted(running.items(), key=lambda kv: -kv[1])
        rank_of, prev_pts, prev_rank = {}, None, 0
        for i, (rid, pts) in enumerate(standing, start=1):
            # Ties share a rank, as a standings table would show them.
            rank_of[rid] = prev_rank if pts == prev_pts else i
            prev_rank, prev_pts = rank_of[rid], pts
        for rid, rec in by_rider.items():
            pt = next((p for p in rec["byStage"] if p["stage"] == n), None)
            if pt:
                pt["cumulativePoints"] = running[rid]
                # Only rank riders who have actually scored; a rider on zero is
                # not "500th in the standings", they are simply unplaced.
                pt["sprintRank"] = rank_of[rid] if running[rid] > 0 else None

    riders = []
    for rec in by_rider.values():
        finishes = [p["gcRank"] for p in rec["byStage"] if p["gcRank"] is not None]
        rec["finalRank"] = min(finishes) if finishes else DNF_SENTINEL
        rec["totalTimeSeconds"] = None
        for p in rec["byStage"]:
            p.pop("points", None)   # transient: only cumulativePoints ships
        if rec["firstName"] is None:
            rec.pop("firstName")
        if rec["lastName"] is None:
            rec.pop("lastName")
        riders.append(rec)
    riders.sort(key=lambda r: (r["finalRank"], r["name"]))
    return {"stages": out_stages, "riders": riders}


def build_index(years_data):
    """Compact riders_index.json for an aggregate race set.

    ENCODING. One map per rider-year rather than two:

        ym: { "2021": [teamIdx, raceIdx, rank, raceIdx, rank, ...] }

    The Grand Tour indexes (export_riders_index.py) keep their own `y` shape —
    they have no constituent races to carry — so the loader branches on which
    key is present.

    This replaced a `y` of [finalRank, teamIdx] plus a parallel `m` of
    [[raceIdx, rank], ...]. Those stored every year key TWICE, and finalRank is
    min() of the ranks already in `m`, so it was derivable rather than data.
    Measured in the browser over the 11,934-rider classics index:

        raw     2,865 KB -> 2,078 KB   (-27%)
        gzipped   703 KB ->   547 KB   (-22%)
        parse      16.9ms ->    9.1ms
        build      19.4ms ->   20.9ms

    Deriving finalRank costs 1.5ms; parsing 156 KB less JSON saves 7.8ms. Net
    6.3ms faster AND smaller, which is the opposite of what was expected — the
    worry was that touching `m`-shaped data eagerly would reinstate the ~380ms
    that defineLazyConstituents() exists to avoid. It does not: that cost was
    materialising 11,934 objects, not running a numeric min() over a flat array.
    The constituents getter is still lazy, and now reads the same `ym` array.
    """
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
                                          "ym": {}})
            if r.get("firstName"):
                rec["fn"] = r["firstName"]
            if r.get("lastName"):
                rec["ln"] = r["lastName"]
            # [teamIdx, then raceIdx/rank pairs]. finalRank is NOT stored: it
            # is min() of these ranks, derived on load.
            flat = [tidx(r["team"])]
            for p in r["byStage"]:
                flat.append(ridx(labels[p["stage"]]))
                flat.append(p["gcRank"] or DNF_SENTINEL)
            rec["ym"][str(year)] = flat
    return {"teams": teams, "races": races, "riders": riders}


def run(race_set, year=None):
    """Export one race set. `year=None` rebuilds every year AND the index."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    short_of = {info.name: info.short for info in race_set.info.values()}
    out_dir = os.path.join(DATA_ROOT, race_set.slug)

    if year:
        years = [year]
    else:
        cur.execute(
            """SELECT DISTINCT e.year FROM race_editions e
               JOIN races r USING(race_id)
               WHERE r.race_type = ? ORDER BY e.year""", (race_set.race_type,))
        years = [r[0] for r in cur.fetchall()]

    os.makedirs(out_dir, exist_ok=True)
    built = {}
    for y in years:
        data = build_year(cur, race_set, y, short_of)
        if not data:
            print(f"  {y}: no editions, skipped")
            continue
        built[y] = data
        with open(os.path.join(out_dir, f"gc_by_stage_{y}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        canc = sum(1 for s in data["stages"] if s.get("cancelled"))
        print(f"  {y}: {len(data['stages'])} races "
              f"({canc} cancelled), {len(data['riders'])} riders")

    # The index is a single cross-year file, so it is only correct when every
    # year was rebuilt — skip it on a --year run rather than write a partial.
    if not year:
        idx = build_index(built)
        with open(os.path.join(out_dir, "riders_index.json"), "w",
                  encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  riders_index: {len(idx['riders'])} riders, "
              f"{len(idx['teams'])} teams, {len(idx['races'])} races")
        # See export_riders_index.py's call for why this is here and not a
        # step to remember. Skipped on a --year run for the same reason the
        # index itself is: nothing rewrote it, so nothing dropped the stamp.
        stamp_cross_race(quiet=True)
    else:
        print("  riders_index: SKIPPED (--year run; rerun without --year)")

    conn.close()
    return 0
