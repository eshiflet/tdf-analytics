#!/usr/bin/env python3
"""
Build a compact cross-year rider index for the Riders page.

The web app's Riders view needs every rider's per-year result without
loading all the per-year data files into the browser. This script collapses
the already-exported gc_by_stage_*.json files into a single small index so
the per-year files can be lazy-loaded on demand. Replaces the old
export_riders_index.py (TDF-only) / export_giro_riders_index.py /
export_vuelta_riders_index.py — the latter two were ~97% identical.

Output: cycling-app/src/data/<slug>/riders_index.json
  {
    "teams": ["<team name>", ...],            # string table, sorted
    "riders": {
      "<rider slug>": {                       # rider id minus the "rider/" prefix
        "n": "<name>",
        "c": "<nationality or null>",
        "yw": [1984, 1989],                    # years rider won young-rider (white jersey)
                                                # classification; omitted if never. TDF only —
                                                # Giro/Vuelta don't track this classification.
        "y": { "<year>": [gcRank, teamIdx]                        # no points rankings
               | [gcRank, teamIdx, sprintRank, komRank], ... }    # 0 = that rank absent
      }
    }
  }

teamIdx indexes into the "teams" table; -1 = no team recorded. Team names
repeat across thousands of rider-years, so the table cuts the raw payload by
roughly a third versus inlining the strings. Most rider-years have no
sprint/KOM ranking, so the short 2-element form avoids shipping sentinel
values for ~65% of entries. gcRank 9999 = DNF/DNS.

GC/sprint/KOM winning years are derived client-side from gcRank/sprintRank/
komRank === 1 per year, so only the young-rider (white jersey) win needs its
own field here — that classification isn't tracked anywhere else in the
exported per-year JSON, only in the DB's classification_standings table
(and only for the TDF; see race_common.EXPORT_RACE_INFO).

sprintRank/komRank come from that same classification_standings table for
every year it covers, and fall back to the gc_by_stage cumulative-points
order elsewhere — see load_final_classification_ranks() for why the two are
not interchangeable.

Run after export_gc.py (it reads that script's output for everything except
the youth-winner years, which come directly from cycling.db).

Usage:
  python3 export_riders_index.py                 # TDF (default)
  python3 export_riders_index.py --race giro
  python3 export_riders_index.py --race vuelta
"""

import glob
import json
import os
import sqlite3
import sys
from collections import defaultdict

from link_rider_race_sets import stamp as stamp_cross_race
from race_common import DB_PATH, resolve_race_arg

HERE = os.path.dirname(os.path.abspath(__file__))


def load_youth_winners(db_path=None):
    """Maps rider_id -> sorted list of years with a rank=1 finish in the
    youth (white jersey) classification, per cycling.db's
    classification_standings table. TDF only."""
    conn = sqlite3.connect(db_path or DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT cs.rider_id, re.year FROM classification_standings cs "
        "JOIN race_editions re ON re.edition_id = cs.edition_id "
        "WHERE cs.classification = 'youth' AND cs.rank = 1"
    )
    winners = defaultdict(list)
    for rider_id, year in cur.fetchall():
        winners[rider_id].append(year)
    conn.close()
    return {rider_id: sorted(years) for rider_id, years in winners.items()}


def load_final_classification_ranks(race_name, db_path=None):
    """Final points/KOM classification ranks per year, from cycling.db's
    PCS-scraped classification_standings.

    These are the official end-of-race standings, and they are not the same
    thing as "who led on cumulative points after the last stage", which is what
    the gc_by_stage files carry. The two diverge whenever the per-stage points
    this project reconstructs don't reproduce the era's scoring exactly, and
    they diverge permanently where a title was re-awarded after a doping
    disqualification (Bernhard Kohl's 2008 KOM going to Carlos Sastre). Where
    the DB has the official standings they win; the derived ranking is the
    fallback for years it doesn't cover.

    Returns ({classification: {(year, rider_id): rank}},
             {classification: {years covered}}).
    """
    conn = sqlite3.connect(db_path or DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT cs.classification, re.year, cs.rider_id, cs.rank "
        "FROM classification_standings cs "
        "JOIN race_editions re ON re.edition_id = cs.edition_id "
        "JOIN races ra ON ra.race_id = re.race_id "
        "WHERE ra.name = ? AND cs.classification IN ('points', 'kom')",
        (race_name,),
    )
    ranks = {"points": {}, "kom": {}}
    years_covered = {"points": set(), "kom": set()}
    for classification, year, rider_id, rank in cur.fetchall():
        ranks[classification][(str(year), rider_id)] = rank
        years_covered[classification].add(str(year))
    conn.close()
    return ranks, years_covered


def build_index(datasets, youth_winners=None, final_ranks=None, ranked_years=None):
    """Collapse per-year gc_by_stage datasets into the compact rider index.

    `datasets` is an iterable of (year_str, parsed_gc_by_stage_dict). Pure —
    no file or database access — so the shape of the output can be asserted
    directly. main() does the globbing, reading and writing.

    Two passes are required, not one: teamIdx points into a string table that
    can only be built once every team across every year is known.

    `final_ranks`/`ranked_years` come from load_final_classification_ranks():
    for a year the DB has official standings for, the sprint/KOM rank is that
    standing (absent from it = unclassified), not the cumulative-points order
    at the last stage.
    """
    youth_winners = youth_winners or {}
    final_ranks = final_ranks or {}
    ranked_years = ranked_years or {}
    riders, team_names, raw_years = {}, set(), []

    for year, ds in datasets:
        for r in ds["riders"]:
            slug = r["id"].removeprefix("rider/")
            entry = riders.setdefault(slug, {"n": r["name"], "c": r.get("nationality"), "y": {}})
            if r.get("firstName") and "fn" not in entry:
                entry["fn"] = r["firstName"]
            if r.get("lastName") and "ln" not in entry:
                entry["ln"] = r["lastName"]
            if r["id"] in youth_winners:
                entry["yw"] = youth_winners[r["id"]]
            if r.get("team"):
                team_names.add(r["team"])
            raw_years.append((entry, year, r))

    teams = sorted(team_names)
    team_idx = {t: i for i, t in enumerate(teams)}

    for entry, year, r in raw_years:
        ti = team_idx.get(r.get("team"), -1)
        last_stage = r["byStage"][-1] if r.get("byStage") else None
        sprint_rank = (last_stage.get("sprintRank") or 9999) if last_stage else 9999
        kom_rank = (last_stage.get("komRank") or 9999) if last_stage else 9999
        # Official standings override the derived ones for the years they cover.
        if year in ranked_years.get("points", ()):
            sprint_rank = final_ranks["points"].get((year, r["id"]), 9999)
        if year in ranked_years.get("kom", ()):
            kom_rank = final_ranks["kom"].get((year, r["id"]), 9999)
        # Most rider-years have neither ranking; the short 2-element form keeps
        # sentinels out of ~65% of entries.
        if sprint_rank == 9999 and kom_rank == 9999:
            entry["y"][year] = [r["finalRank"], ti]
        else:
            entry["y"][year] = [
                r["finalRank"],
                ti,
                0 if sprint_rank == 9999 else sprint_rank,
                0 if kom_rank == 9999 else kom_rank,
            ]

    return {"teams": teams, "riders": riders}


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    race_name, subdir = resolve_race_arg(argv)
    data_dir = os.path.join(HERE, "..", "cycling-app", "src", "data", subdir)
    out_path = os.path.join(data_dir, "riders_index.json")

    youth_winners = load_youth_winners() if subdir == "tour" else {}
    final_ranks, ranked_years = load_final_classification_ranks(race_name)

    files = sorted(glob.glob(os.path.join(data_dir, "gc_by_stage_*.json")))
    if not files:
        print(f"No {subdir} gc_by_stage_*.json files found")
        return

    datasets = []
    for path in files:
        year = os.path.basename(path).removeprefix("gc_by_stage_").removesuffix(".json")
        with open(path, encoding="utf-8") as f:
            datasets.append((year, json.load(f)))

    index = build_index(datasets, youth_winners, final_ranks, ranked_years)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index, f, separators=(",", ":"), ensure_ascii=False)

    covered = sorted(ranked_years["points"] | ranked_years["kom"])
    if covered:
        print(
            f"Sprint/KOM ranks from official standings for {len(covered)} years "
            f"({covered[0]}-{covered[-1]}); derived ranks used outside that range"
        )

    size_kb = os.path.getsize(out_path) / 1024
    print(
        f"Wrote {len(index['riders']):,} riders / {len(index['teams'])} teams across "
        f"{len(files)} years -> {out_path} ({size_kb:.0f} KB)"
    )

    # The cross-race bitmask the rider detail page uses to decide which OTHER
    # indexes it can skip. Rewriting this file drops it, so it is restored here
    # rather than left as a step to remember — validate_exports.py checking for
    # it is a backstop, not the mechanism. Membership is symmetric, so this can
    # also touch the other races' indexes; only changed bytes are written.
    stamp_cross_race(quiet=True)


if __name__ == "__main__":
    main()
