#!/usr/bin/env python3
"""
Validate the exported gc_by_stage_*.json files in cycling-app/src/data.

Catches the class of data bugs that have actually shipped: cumulative point
totals that decrease (bad per-stage scrapes), duplicate ranks within a stage
(stale back-filled ranks), riders with stage entries beyond the final stage,
and final KOM totals drifting from the reference standings.

Hard errors (exit 1):
  - malformed structure (no stages / no riders / duplicate stage numbers)
  - byStage not sorted, or referencing a stage that doesn't exist
  - cumulativePoints or cumulativeKomPoints decreasing for a rider

Warnings (reported, exit 0):
  - duplicate sprintRank/komRank within a stage (the export back-fills a
    DNF rider's last entry with their final-standings rank, which can
    collide with the rank map at that earlier stage)
  - duplicate finalRank among finishers, excluding the 9999 DNF/DQ sentinel
    (genuine ties and post-doping-DQ standings produce real duplicates)

  Neither rank check runs for races in AGGREGATE_STANDINGS, where both fields
  hold standings rather than finishing positions and ties are expected.
  - final KOM totals off by >5% from reference (kom_totals.json) for years
    the reconcile report classifies as keep_pcs (other strategies are
    approximations by design)

gcRank duplicates within a stage are NOT checked: historical GC ties are
common (especially 1948-1959) and PCS represents DQ-adjusted standings with
shared ranks (e.g. Contador/Schleck both #1 in 2010).

Usage: python3 validate_exports.py [--year YEAR]
"""
import json
import os
import sys

from reconcile_kom import name_match, slug_to_display

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.join(HERE, "..", "cycling-app", "src", "data")
# (label, subdir, has_kom_reference) — KOM reference data exists only for TDF
RACE_DIRS = [
    ("tour", "tour", True),
    ("giro", "giro", False),
    ("vuelta", "vuelta", False),
    # The one-day classics: no all_races_summary.json (a season of unrelated
    # races has no meaningful cross-year total) and no sprint/KOM series, so
    # those checks pass trivially rather than needing to be skipped.
    ("classics", "classics", False),
    # The off-road set: same aggregate shape as the classics, and likewise no
    # all_races_summary.json and no sprint/KOM series.
    ("gravel", "gravel", False),
]

# Races whose ranks are STANDINGS rather than finishing positions, so ties are
# the normal case and not a defect:
#   - finalRank is the best result of the season (2021: nine riders share #1)
#   - sprintRank is the cumulative season-points standing, where hundreds of
#     riders legitimately sit on equal totals
# Checking either produced ~45,700 warnings on entirely clean data and buried
# every real one.
AGGREGATE_STANDINGS = {"classics", "gravel"}

# Which script rebuilds a race's riders_index.json, for the staleness error.
INDEX_REBUILD_CMD = {
    "tour": "python3 export_riders_index.py --race tdf",
    "giro": "python3 export_riders_index.py --race giro",
    "vuelta": "python3 export_riders_index.py --race vuelta",
    "classics": "python3 export_classics.py",
    "gravel": "python3 export_gravel.py",
}
TOTALS_PATH = os.path.join(HERE, "kom_totals.json")
REPORT_PATH = os.path.join(HERE, "kom_reconcile_report.json")

KOM_REF_TOLERANCE = 0.05  # warn if a keep_pcs year's top riders drift >5%


def validate_year(year: int, ds: dict,
                  ranks_are_unique: bool = True) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    stages = ds.get("stages", [])
    riders = ds.get("riders", [])
    if not stages:
        errors.append("no stages")
    if not riders:
        # A season whose every race was cancelled has no riders and is still
        # correct. 2020 in the off-road set is exactly that: Unbound was the
        # only one of the six that existed yet, and COVID took it. Dropping the
        # year instead would erase the cancellation, which is the one fact that
        # season has to offer.
        if stages and all(s.get("cancelled") for s in stages):
            warnings.append(
                f"no riders — all {len(stages)} race(s) cancelled, which is why")
        else:
            errors.append("no riders")
    if errors:
        return errors, warnings

    stage_numbers = [s["stage_number"] for s in stages]
    if len(set(stage_numbers)) != len(stage_numbers):
        errors.append("duplicate stage_number in stages list")
    known_stages = set(stage_numbers)
    final_stage = max(stage_numbers)

    # rank -> rider id, per stage, per rank field (gcRank excluded: real ties)
    rank_seen: dict[str, dict[int, dict[int, str]]] = {
        "sprintRank": {}, "komRank": {}
    }
    final_rank_seen: dict[int, str] = {}

    for r in riders:
        rid = r["id"]
        by_stage = r.get("byStage", [])
        prev_stage = None
        prev_pts = 0
        prev_kom = 0
        for sp in by_stage:
            st = sp["stage"]
            if st not in known_stages:
                errors.append(f"{rid}: byStage references unknown stage {st}")
            if prev_stage is not None and st <= prev_stage:
                errors.append(f"{rid}: byStage not strictly ascending at stage {st}")
            prev_stage = st

            pts = sp.get("cumulativePoints") or 0
            kom = sp.get("cumulativeKomPoints") or 0
            if pts < prev_pts:
                errors.append(
                    f"{rid}: cumulativePoints decreases {prev_pts}->{pts} at stage {st}"
                )
            if kom < prev_kom:
                errors.append(
                    f"{rid}: cumulativeKomPoints decreases {prev_kom}->{kom} at stage {st}"
                )
            prev_pts, prev_kom = pts, kom

            for field in ("sprintRank", "komRank"):
                rank = sp.get(field)
                if rank is None or not ranks_are_unique:
                    continue
                per_stage = rank_seen[field].setdefault(st, {})
                if rank in per_stage:
                    warnings.append(
                        f"stage {st}: duplicate {field} #{rank} "
                        f"({per_stage[rank]} and {rid})"
                    )
                else:
                    per_stage[rank] = rid

        # finalRank uniqueness only makes sense for riders who reached the end;
        # 9999 is the DNF/DQ sentinel and duplicates freely.
        #
        # Skipped entirely where finalRank is an aggregate rather than a placing: for
        # the classics it is the rider's BEST finish of the season, so ties are
        # the normal case (2021 alone had nine riders share #1 — the nine
        # winners of its eleven races). Left on, it emitted 325 warnings for
        # entirely clean data and buried the real ones.
        fr = r.get("finalRank")
        if (ranks_are_unique and fr is not None and fr != 9999
                and by_stage and by_stage[-1]["stage"] == final_stage):
            if fr in final_rank_seen:
                warnings.append(
                    f"duplicate finalRank #{fr} ({final_rank_seen[fr]} and {rid})"
                )
            else:
                final_rank_seen[fr] = rid

    return errors, warnings


def check_kom_reference(year: int, ds: dict, ref: list, strategy: str) -> list[str]:
    """Warn when a keep_pcs year's exported final KOM totals drift from reference."""
    if strategy != "keep_pcs" or not ref:
        return []
    totals: dict[str, int] = {}
    for r in ds.get("riders", []):
        by_stage = r.get("byStage", [])
        if by_stage:
            totals[r["id"]] = by_stage[-1].get("cumulativeKomPoints") or 0

    warnings = []
    for ref_name, ref_pts in ref[:3]:
        if not ref_pts:
            continue
        ours = 0
        for rid, pts in totals.items():
            if name_match(ref_name, slug_to_display(rid)):
                ours = pts
                break
        if abs(ours - ref_pts) / ref_pts > KOM_REF_TOLERANCE:
            warnings.append(
                f"KOM total for {ref_name}: exported {ours} vs reference {ref_pts}"
            )
    return warnings


def check_riders_index(data_dir, subdir):
    """riders_index.json must agree with the gc_by_stage files it was built from.

    It is a derived cross-year rollup, and nothing forced it to be regenerated
    when a per-year file changed — export_riders_index.py also defaults to the
    TDF, so a run without --race silently leaves giro/vuelta behind. The Giro
    index drifted to 912 inconsistent rider-years that way, and the app served
    them: wrong final ranks and wrong teams, with no error anywhere.
    """
    path = os.path.join(data_dir, "riders_index.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        idx = json.load(f)
    teams = idx.get("teams", [])
    riders = idx.get("riders", {})

    stale = []
    for fname in sorted(os.listdir(data_dir)):
        if not (fname.startswith("gc_by_stage_") and fname.endswith(".json")):
            continue
        year = fname.replace("gc_by_stage_", "").replace(".json", "")
        with open(os.path.join(data_dir, fname), encoding="utf-8") as f:
            ds = json.load(f)
        for r in ds.get("riders", []):
            slug = r["id"].removeprefix("rider/")
            rec = riders.get(slug, {})
            # Two encodings. The Grand Tours store `y` as [finalRank, teamIdx];
            # the aggregate sets store `ym` as [teamIdx, raceIdx, rank, ...]
            # with finalRank DERIVED as min() of those ranks. Re-deriving it
            # here is the stronger check: it repeats on the index exactly what
            # the browser does, so a bad derivation fails rather than a bad
            # stored copy of a right one.
            if "ym" in rec:
                flat = rec["ym"].get(year)
                if flat is None:
                    stale.append(f"{year}: {slug} missing from riders_index")
                    continue
                ranks = flat[2::2]
                final_rank = min(ranks) if ranks else 9999
                team_idx = flat[0]
            else:
                entry = rec.get("y", {}).get(year)
                if entry is None:
                    stale.append(f"{year}: {slug} missing from riders_index")
                    continue
                final_rank, team_idx = entry[0], entry[1]

            if final_rank != r["finalRank"]:
                stale.append(f"{year}: {slug} finalRank {final_rank} != {r['finalRank']}")
                continue
            name = teams[team_idx] if 0 <= team_idx < len(teams) else None
            if name != r.get("team"):
                stale.append(f"{year}: {slug} team {name!r} != {r.get('team')!r}")
    return stale


def main():
    single_year = None
    if "--year" in sys.argv:
        single_year = int(sys.argv[sys.argv.index("--year") + 1])

    with open(TOTALS_PATH, encoding="utf-8") as f:
        totals_data = json.load(f)
    strategies: dict[int, str] = {}
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH, encoding="utf-8") as f:
            strategies = {r["year"]: r["strategy"] for r in json.load(f)}

    total_errors = 0
    total_warnings = 0
    checked = 0

    for race_label, subdir, has_kom_ref in RACE_DIRS:
        data_dir = os.path.join(DATA_ROOT, subdir)
        if not os.path.isdir(data_dir):
            continue
        files = sorted(
            f for f in os.listdir(data_dir)
            if f.startswith("gc_by_stage_") and f.endswith(".json")
        )
        for fname in files:
            year = int(fname.replace("gc_by_stage_", "").replace(".json", ""))
            if single_year and year != single_year:
                continue
            checked += 1
            with open(os.path.join(data_dir, fname), encoding="utf-8") as f:
                ds = json.load(f)

            errors, warnings = validate_year(
                year, ds, ranks_are_unique=(subdir not in AGGREGATE_STANDINGS))

            if has_kom_ref:
                entry = totals_data.get(str(year), {})
                ref_wiki = entry.get("wikipedia", [])
                ref_bri = entry.get("bikeraceinfo", [])
                ref = ref_wiki if ref_wiki else ref_bri
                warnings += check_kom_reference(year, ds, ref, strategies.get(year, ""))

            for e in errors:
                print(f"ERROR {race_label} {year}: {e}")
            for w in warnings:
                print(f"warn  {race_label} {year}: {w}")
            total_errors += len(errors)
            total_warnings += len(warnings)

    # riders_index is derived from the per-year files; nothing regenerates it
    # automatically, so check it still matches rather than trusting it.
    if not single_year:
        for race_label, subdir, _ in RACE_DIRS:
            data_dir = os.path.join(DATA_ROOT, subdir)
            if not os.path.isdir(data_dir):
                continue
            stale = check_riders_index(data_dir, subdir)
            if stale:
                print(f"ERROR {race_label}: riders_index.json is stale — "
                      f"{len(stale)} inconsistent rider-year(s). "
                      f"Run: {INDEX_REBUILD_CMD[subdir]}")
                for line in stale[:5]:
                    print(f"        {line}")
                if len(stale) > 5:
                    print(f"        ... and {len(stale) - 5} more")
                total_errors += 1

    print(f"\n{checked} files checked: {total_errors} errors, {total_warnings} warnings")
    sys.exit(1 if total_errors else 0)


if __name__ == "__main__":
    main()
