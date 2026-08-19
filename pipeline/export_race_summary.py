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
  totalDistanceKm          — SUM(stages.distance_km) over the edition's
                             stages, excluding cancelled ones
  totalElevationM          — SUM(stages.vertical_meters), but null unless at
                             least ELEVATION_MIN_COVERAGE of the edition's
                             stages carry a figure (see total_elevation())
  gcWinnerTimeSeconds      — sum of finish_time_seconds for the overall GC winner
  slowestFinisherTimeSeconds — gcWinnerTimeSeconds + MAX(gc_gap_seconds) at final stage

totalDistanceKm is RECONCILED against {race}_race_distances.json (Wikipedia's
published total, built by scrape_wiki_distances.py) and any disagreement above
DISTANCE_TOLERANCE_PCT is reported. A summed distance always looks plausible,
so an edition missing whole stages produces a total that is merely small rather
than obviously wrong — there is nothing in the number itself to notice.

Unlike the TDF exporter, the DB sum is what gets EXPORTED here; Wikipedia is
used only as the check. The TDF displays Wikipedia's figure because its PCS
stage sums had errors 100-200 km wide, which is not the case for these two:
across 189 editions the median disagreement is 0.13% (Giro) / 0.23% (Vuelta).
Displaying the DB also keeps a defect visible in the UI instead of masking it
behind a correct-looking total that only the console mentions.

Usage:
  python3 export_race_summary.py --race giro
  python3 export_race_summary.py --race vuelta
  python3 export_race_summary.py --race giro --strict   # exit 1 on divergence
"""

import json
import os
import sqlite3
import sys

from race_common import DB_PATH

HERE = os.path.dirname(os.path.abspath(__file__))

FIRST_YEAR = {"giro": 1909, "vuelta": 1935}
DB_RACE_NAME = {"giro": "Giro d'Italia", "vuelta": "Vuelta a España"}

# How far the DB's summed stage distances may drift from Wikipedia's published
# route total before it's treated as a defect rather than noise. Same 3% the
# TDF exporter uses. Historical sources genuinely disagree by a percent or two
# on neutralized sections and split stages; a whole missing stage lands well
# outside it. 186 of 189 editions sit under 1%.
DISTANCE_TOLERANCE_PCT = 3.0


def _flag(name, default):
    """Value of an optional `--name VALUE` argument, or default."""
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def load_distance_baseline(race):
    """
    Already-investigated divergences: {"1926": "why it's accepted", ...}.

    Without this the reconciliation is unusable. 19 of 189 editions disagree
    with Wikipedia by >3% for reasons that are NOT defects (prologue and split
    stage accounting, neutralized sections, stages stored as 0.0 km because
    they produced no classification). A warning that prints the same 19 rows
    forever is one nobody reads, and --strict could never pass, so nothing
    would ever gate on it. Listing them here means a 20th arrival is the only
    thing that shows up as new.

    Shared by export_all_races_summary.py so all three races behave alike.
    """
    path = os.path.join(HERE, "distance_divergence_baseline.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get(race, {})


def report_distance_divergences(divergences, accepted, tolerance, have_source, race, strict):
    """Prints the reconciliation outcome. Returns True if anything is NEW."""
    if not have_source:
        print(f"No {race}_race_distances.json — distance NOT reconciled. "
              f"Build it with: python3 scrape_wiki_distances.py --race {race}")
        return False

    new = [d for d in divergences if str(d["year"]) not in accepted]
    known = len(divergences) - len(new)

    if new:
        print(f"\nWARNING: {len(new)} NEW edition(s) where the DB's summed stage "
              f"distances disagree with Wikipedia by >{tolerance}%.")
        print("A large NEGATIVE gap is the missing-stages signature; a positive one is")
        print("usually a split stage counted twice or a differing neutralized section.")
        print(f"  {'year':<6}{'wiki km':>9}{'db km':>10}{'diff':>8}{'stages':>8}")
        for d in sorted(new, key=lambda d: d["pct"]):
            print(f"  {d['year']:<6}{d['wiki_km']:>9}{d['db_km']:>10}"
                  f"{d['pct']:>7}%{d['stages']:>8}")
        print("Investigate, then add each to distance_divergence_baseline.json with a reason.")
    else:
        print(f"Distance reconciliation: no new divergence beyond {tolerance}%.")

    if known:
        print(f"  ({known} already-investigated divergence(s) in the baseline)")
    if new and strict:
        print("\n--strict: failing on new distance divergence.")
        sys.exit(1)
    return bool(new)


# A cancelled stage counts toward NOTHING in the year's totals — not distance,
# not ascent. `cancelled=1` means the stage produced no classification: no GC
# time, no points. A stage whose racing was thrown away did not contribute the
# race's kilometres or its climbing either, and counting one but not the other
# is how distance and elevation end up describing two different races. Four
# figures move under this rule (2026-08-18): TDF 1982 stage 5 (556 m, ridden
# then annulled after the Orchies blockade), Vuelta 1991 stage 12 (3,015 m),
# and the distances of Vuelta 1957 stage 4 (136 km) and Vuelta 1968 stage 17
# (204 km). The other nine cancelled Grand Tour stages are already stored as
# 0.0 km with no elevation, so the rule only makes their convention explicit.
#
# Elevation additionally needs a COVERAGE floor, because SQL's SUM ignores
# NULLs: an edition where 1 stage of 23 has a figure reported that one stage as
# the whole race — Giro 1998 summed to 11 m (the Nice prologue) and Giro 1994 to
# 212 m, both plotted as real totals on the All Races Overview. Five such Giro
# years were suppressed by hand in giro_races_summary_overrides.json and two
# were missed, which is why this is a rule here and not a curated list.
#
# Coverage across all 302 editions splits cleanly: every edition with sparse
# elevation sits at or below 18% of its stages, and the least-covered plausible
# one (TDF 1998) at 86%. 50% is the wide middle of that gap, not a tuned edge.
ELEVATION_MIN_COVERAGE = 0.5


def total_distance(cur, edition_id):
    """Summed distance of the stages that counted, in km (None if no stages)."""
    return cur.execute(
        "SELECT SUM(distance_km) FROM stages WHERE edition_id=? AND cancelled=0",
        (edition_id,),
    ).fetchone()[0]


def total_elevation(cur, edition_id):
    """
    (elevation_or_None, coverage_note_or_None) for one edition.

    Returns None rather than a sum whenever too few stages carry a figure, so a
    near-empty edition reads as "no data" (like the 39 Giro years with none at
    all) instead of as a real, absurdly small total.
    """
    row = cur.execute(
        """SELECT COUNT(*) AS n,
                  COUNT(vertical_meters) AS have,
                  SUM(vertical_meters) AS total
           FROM stages WHERE edition_id=? AND cancelled=0""",
        (edition_id,),
    ).fetchone()
    n, have, total = row["n"], row["have"], row["total"]
    if not have:
        return None, None
    if n and have / n < ELEVATION_MIN_COVERAGE:
        return None, {"have": have, "n": n, "suppressed": total}
    return total, None


def report_elevation_coverage(notes):
    """Prints the editions whose elevation was suppressed as too sparse."""
    if not notes:
        return
    print(f"\nElevation: {len(notes)} edition(s) exported as null — under "
          f"{ELEVATION_MIN_COVERAGE:.0%} stage coverage:")
    for year, note in sorted(notes.items()):
        print(f"  {year}: {note['have']}/{note['n']} stages "
              f"(would have summed to {note['suppressed']} m)")


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
    strict = "--strict" in sys.argv

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

    # Wikipedia's published route total — an independent check on the DB, not a
    # value that gets exported. Built by scrape_wiki_distances.py --race <race>.
    wiki_distances = {}
    distances_path = os.path.join(HERE, f"{race}_race_distances.json")
    if os.path.exists(distances_path):
        with open(distances_path, encoding="utf-8") as f:
            wiki_distances = json.load(f)

    accepted = load_distance_baseline(race)

    out = []
    divergences = []
    elevation_notes = {}
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

        edition_distance = total_distance(cur, edition_id)

        wiki_distance = wiki_distances.get(str(year))
        if wiki_distance and edition_distance:
            pct = (edition_distance - wiki_distance) / wiki_distance * 100
            if abs(pct) > DISTANCE_TOLERANCE_PCT:
                n_stages = cur.execute(
                    "SELECT COUNT(*) FROM stages WHERE edition_id=?", (edition_id,)
                ).fetchone()[0]
                divergences.append({
                    "year": year, "wiki_km": wiki_distance,
                    "db_km": round(edition_distance, 1), "pct": round(pct, 1),
                    "stages": n_stages,
                })

        edition_elevation, elevation_note = total_elevation(cur, edition_id)
        if elevation_note:
            elevation_notes[year] = elevation_note

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
            "totalDistanceKm": round(edition_distance, 1) if edition_distance else None,
            "totalElevationM": int(edition_elevation) if edition_elevation else None,
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

    report_distance_divergences(divergences, accepted, DISTANCE_TOLERANCE_PCT,
                                bool(wiki_distances), race, strict)
    report_elevation_coverage(elevation_notes)


if __name__ == "__main__":
    main()
