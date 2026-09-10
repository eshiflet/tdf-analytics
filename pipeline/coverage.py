#!/usr/bin/env python3
"""
What is missing from cycling.db, and where — one table instead of eight audits.

WHY THIS EXISTS. The repo has audits for individual fields (audit_elevation.py,
audit_stage_counts.py, provenance_report.py, the validate_* scripts), and each
one answers "is this field wrong?". None of them answers the question that
actually decides what to scrape next: **for every race and year, which fields
are simply not there yet?**

This is a COVERAGE report, not a validator. It never fails a build and never
says a value is wrong — every number here is "how much of this exists". Use
validate_db.py / validate_exports.py for correctness; use this to pick the next
scrape target.

WHAT IT DOES NOT COUNT. A gap that cannot be filled is noise. But a gap wrongly
declared unfillable is worse than noise — it is work this report will never show
you again — so every exclusion below is checked against the database and against
what the upstream actually publishes:

  * CANCELLED stages are excluded outright. They were never raced, so a NULL
    distance is the correct value, not a gap — the same rule the race totals
    use (see ai-context.md, "Race totals: cancelled stages").
  * A one-stage race has no GC, so `gc_rank` is excluded for the classics and
    the gravel/MTB set. Structural, and confirmed: 0 of 72,911 and 0 of 7,891.
  * `route_type` is COMPUTED, never fetched — gravel_route_type(discipline) for
    gravel, classic_route_type(profile_score) for a classic — so it fills
    exactly when its input does, and listing it separately would double-count
    the same afternoon's work. A gravel `source_slug` is likewise minted from
    the timer's event id at ingest.
  * Elevation, profile score and teams are excluded only for the gravel
    editions whose upstream cannot supply them — see SOURCE_EXEMPT.

Anything else that is NULL is reported, because in principle a source exists.

WHAT THIS USED TO GET WRONG, because it is the failure mode to watch for. Every
one of those columns was once excluded for the whole gravel set, on the stated
grounds that "PCS has no gravel or MTB coverage at all — verified, not assumed".
It was not verified; it rested on one method, a search of PCS's own index, which
returns nothing because PCS files gravel under national-race/ and that namespace
is not indexed. PCS covers The Traka, publishes "Vertical meters: 4198" and
"ProfileScore: 125" for its 2026 edition, and names a trade team for 29 of that
edition's 141 riders. The classics exclusion was wrong the same way: PCS does
classify a one-day race, and ingest_classics.py has been storing it all along —
295 of 963 classic stages carry a profile score. Roughly a thousand fillable
values were invisible here. When an exclusion says a source does not exist, it
needs a page checked, not a plausible reason.

Usage:
  python3 coverage.py                      # every race set, worst gaps first
  python3 coverage.py --race tour          # one race (tour/giro/vuelta/classics/gravel)
  python3 coverage.py --field vertical_meters   # one field, every year that lacks it
  python3 coverage.py --years              # full per-year table, not just the gaps
  python3 coverage.py --worst 40           # how many gap rows to list (default 20)
  python3 coverage.py --csv                # machine-readable, for sorting elsewhere
"""

import argparse
import csv
import os
import sqlite3
import sys
from collections import defaultdict

from race_common import DB_PATH

HERE = os.path.dirname(os.path.abspath(__file__))

# Which races each name selects. `classics` and `gravel` are whole sets rather
# than single races, matching how the exporters and the frontend group them.
RACE_FILTERS = {
    "tour": ("name", "Tour de France"),
    "giro": ("name", "Giro d'Italia"),
    "vuelta": ("name", "Vuelta a España"),
    "classics": ("race_type", "one_day"),
    "gravel": ("race_type", "gravel"),
}

# Stage-level fields, in the order a scrape would fill them.
STAGE_FIELDS = ["distance_km", "vertical_meters", "route_type", "profile_score",
                "source_slug", "stage_date"]
# Result-level fields, counted per stage_result row.
RESULT_FIELDS = ["team_id", "finish_time_seconds", "gc_rank"]
# ...of which these two are only meaningful for a rider who FINISHED. A DNF has
# no finishing time and no GC standing by definition, so counting the whole
# startlist as the denominator reports a permanent 60%-missing on years that
# are in fact complete — the single biggest source of noise in this report
# before it was split out.
FINISHERS_ONLY = {"finish_time_seconds", "gc_rank"}

# Fields a race type cannot have whatever covered it: facts about the shape of
# the race, not about its source. A single-stage race has no classification to
# rank anyone in.
STRUCTURAL_EXEMPT = {
    "gravel": {"gc_rank"},
    "one_day": {"gc_rank"},
    "stage_race": set(),
}

# Fields this pipeline computes or assigns rather than fetching, so no scrape
# will ever fill them and a gap here is not a scrape target. See the docstring.
COMPUTED_EXEMPT = {
    "gravel": {"route_type", "source_slug"},
    "one_day": {"route_type"},
    "stage_race": set(),
}

# Availability that depends on WHICH upstream covered the edition rather than
# on the kind of race. Only the gravel set draws on more than one.
#
# Athlinks and tretzesports are timing platforms: they publish a finish list,
# not a parcours, and they record no trade team — which is the real reason
# gravel teams were once excluded, and it holds for those two. It does not hold
# for PCS, which publishes all three (see the docstring). An edition whose
# source is not recognised is exempted from NOTHING: this report's failure mode
# must be showing work that turns out to be impossible, never hiding work that
# is possible.
SOURCE_EXEMPT = {
    "athlinks": {"vertical_meters", "profile_score", "team_id"},
    "tretzesports": {"vertical_meters", "profile_score", "team_id"},
    "pcs": set(),
}


def exempt_fields(race_type, source):
    """Fields that are not a gap for one stage, given its type and upstream."""
    return (STRUCTURAL_EXEMPT.get(race_type, set())
            | COMPUTED_EXEMPT.get(race_type, set())
            | SOURCE_EXEMPT.get(source, set()))


def race_scope(cur, race=None):
    """[(race_id, name, race_type)] for the selected race(s), or all of them."""
    if race is None:
        cur.execute("SELECT race_id, name, race_type FROM races ORDER BY race_id")
        return cur.fetchall()
    if race not in RACE_FILTERS:
        raise SystemExit(f"Unknown race '{race}' (use {', '.join(RACE_FILTERS)})")
    column, value = RACE_FILTERS[race]
    cur.execute(f"SELECT race_id, name, race_type FROM races WHERE {column} = ? "
                "ORDER BY race_id", (value,))
    rows = cur.fetchall()
    if not rows:
        raise SystemExit(f"No races matched '{race}'")
    return rows


POSSIBLE = "__possible"          # row key suffix: how many a field COULD have


def stage_sources(cur, race_ids):
    """stage_id -> the upstream that supplied it.

    Read out of data_provenance rather than parsed back out of source_slug:
    recording where a value came from is that table's whole job, and since the
    2026-09-09 stages backfill every stage carries a row. `source_slug` is the
    field to read because every ingest writes it and no patch script rewrites
    it, so it names the ingest's own upstream rather than some later
    correction's — the same reason ingested_origin() reads it in
    backfill_provenance.py.
    """
    placeholders = ",".join("?" * len(race_ids))
    cur.execute(
        f"""SELECT s.stage_id, dp.source
            FROM stages s
            JOIN race_editions e ON e.edition_id = s.edition_id
            LEFT JOIN data_provenance dp
                   ON dp.entity = 'stages' AND dp.entity_id = s.stage_id
                  AND dp.field = 'source_slug'
            WHERE e.race_id IN ({placeholders})""", tuple(race_ids))
    return dict(cur.fetchall())


def collect(cur, races):
    """One row per (race_set, year): totals and per-field non-NULL counts.

    Keyed on the SET rather than the individual race, because that is the unit
    a scrape is run in — "the 1953 classics" is a session, "Paris-Roubaix 1953"
    is a page within it. The Grand Tours are their own sets, so they are
    unaffected by the grouping.
    """
    ids = {r[0] for r in races}
    set_of, type_of = {}, {}
    for race_id, name, race_type in races:
        set_of[race_id] = name if race_type == "stage_race" else race_type
        type_of[race_id] = race_type

    sources = stage_sources(cur, ids)
    all_fields = STAGE_FIELDS + RESULT_FIELDS

    rows = defaultdict(lambda: {"stages": 0, "cancelled": 0, "results": 0,
                                "finishers": 0, "race_type": None,
                                **{f: 0 for f in all_fields},
                                **{f + POSSIBLE: 0 for f in all_fields}})

    placeholders = ",".join("?" * len(ids))
    # Cancelled stages are filtered in SQL rather than counted and subtracted:
    # they must not reach the denominator either, or a year that cancelled two
    # of its stages reads as permanently short of complete.
    cur.execute(
        f"""SELECT s.stage_id, r.race_id, e.year, s.cancelled,
                   {', '.join('s.' + f for f in STAGE_FIELDS)}
            FROM stages s
            JOIN race_editions e ON e.edition_id = s.edition_id
            JOIN races r ON r.race_id = e.race_id
            WHERE r.race_id IN ({placeholders})""", tuple(ids))
    # Which race-year each stage feeds, and what may fairly be asked of it.
    stage_key, stage_exempt = {}, {}
    for stage_id, race_id, year, cancelled, *values in cur.fetchall():
        key = (set_of[race_id], year)
        row = rows[key]
        row["race_type"] = type_of[race_id]
        if cancelled:
            row["cancelled"] += 1
            continue
        exempt = exempt_fields(type_of[race_id], sources.get(stage_id))
        stage_key[stage_id], stage_exempt[stage_id] = key, exempt
        row["stages"] += 1
        for field, value in zip(STAGE_FIELDS, values):
            if field in exempt:
                continue
            row[field + POSSIBLE] += 1
            if value is not None:
                row[field] += 1

    # The finisher-only fields are counted inside a CASE rather than in a second
    # query: one pass over 786,687 result rows instead of two.
    counted = [f"COUNT(CASE WHEN sr.status = 'FINISHED' THEN sr.{f} END)"
               if f in FINISHERS_ONLY else f"COUNT(sr.{f})"
               for f in RESULT_FIELDS]
    # Grouped per STAGE rather than per race-year, which is what lets a
    # per-stage exemption reach the result fields at all: one gravel year holds
    # races with different upstreams, so team_id is gettable for some of its
    # stages and not others. ~7,300 groups instead of ~470 costs nothing.
    cur.execute(
        f"""SELECT sr.stage_id, COUNT(*),
                   SUM(CASE WHEN sr.status = 'FINISHED' THEN 1 ELSE 0 END),
                   {', '.join(counted)}
            FROM stage_results sr
            JOIN stages s ON s.stage_id = sr.stage_id
            JOIN race_editions e ON e.edition_id = s.edition_id
            WHERE e.race_id IN ({placeholders}) AND s.cancelled = 0
            GROUP BY sr.stage_id""", tuple(ids))
    for stage_id, total, finishers, *counts in cur.fetchall():
        key = stage_key.get(stage_id)
        if key is None:                 # a cancelled stage that still has rows
            continue
        row, exempt = rows[key], stage_exempt[stage_id]
        finishers = finishers or 0
        row["results"] += total
        row["finishers"] += finishers
        for field, count in zip(RESULT_FIELDS, counts):
            if field in exempt:
                continue
            row[field + POSSIBLE] += finishers if field in FINISHERS_ONLY else total
            row[field] += count

    return rows


def denominator(row, field):
    """How many values this field COULD have for one race-year.

    Accumulated per stage while collecting rather than read off the race-year
    total, because a race SET can mix upstreams inside one year: 2025 holds The
    Traka, whose PCS page publishes elevation and names teams, alongside Big
    Sugar, whose Athlinks feed does neither. A single per-year denominator
    cannot say "70 of these 172 riders could have had a team recorded".
    """
    return row[field + POSSIBLE]


def gaps(rows, only_field=None):
    """[(pct, race_set, year, field, have, total)] for every incomplete field.

    Sorted by how much is missing in absolute terms, not by percentage: a year
    at 40% of 180 stage-results is a bigger afternoon's work than one at 0% of 3,
    and the point of this list is to rank what to do next.
    """
    out = []
    for (race_set, year), row in rows.items():
        for field in STAGE_FIELDS + RESULT_FIELDS:
            if only_field and field != only_field:
                continue
            # An exempt field never reached its denominator, so it falls out
            # here as total == 0 rather than needing a second exemption check.
            total = denominator(row, field)
            if total == 0:
                continue
            have = row[field]
            if have < total:
                out.append((have / total, race_set, year, field, have, total))
    out.sort(key=lambda g: (-(g[5] - g[4]), g[1], g[2]))
    return out


def rider_coverage(cur):
    """Rider-level fields, which are global rather than per-year."""
    cur.execute("SELECT COUNT(*), COUNT(first_name), COUNT(birthday), "
                "COUNT(nationality_code) FROM riders")
    total, names, birthdays, nats = cur.fetchone()
    return total, {"first_name": names, "birthday": birthdays,
                   "nationality_code": nats}


def pct(have, total):
    return "—" if total == 0 else f"{100 * have / total:5.1f}%"


def print_year_table(rows, race_set):
    years = sorted(y for s, y in rows if s == race_set)
    if not years:
        return
    # A column is shown when any year of this set could hold it — a set whose
    # upstream changed partway (gravel moved to PCS in 2023) has years that can
    # and years that cannot, and the ones that cannot print "—" via pct().
    fields = [f for f in STAGE_FIELDS + RESULT_FIELDS
              if any(rows[(race_set, y)][f + POSSIBLE] for y in years)]
    print(f"\n{race_set}")
    header = f"  {'year':>5} {'stages':>7} {'results':>8}  " + \
             "  ".join(f"{f[:9]:>9}" for f in fields)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for year in years:
        row = rows[(race_set, year)]
        cells = []
        for field in fields:
            cells.append(f"{pct(row[field], denominator(row, field)):>9}")
        canc = f" ({row['cancelled']}c)" if row["cancelled"] else ""
        print(f"  {year:>5} {str(row['stages']) + canc:>7} {row['results']:>8}  "
              + "  ".join(cells))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--race", choices=sorted(RACE_FILTERS))
    ap.add_argument("--field", choices=STAGE_FIELDS + RESULT_FIELDS)
    ap.add_argument("--years", action="store_true",
                    help="full per-year table, not only the gaps")
    ap.add_argument("--worst", type=int, default=20,
                    help="how many gap rows to list (default 20)")
    ap.add_argument("--csv", action="store_true", help="machine-readable output")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        raise SystemExit(f"No database at {args.db}")
    conn = sqlite3.connect(args.db)
    cur = conn.cursor()
    races = race_scope(cur, args.race)
    rows = collect(cur, races)
    found = gaps(rows, args.field)

    if args.csv:
        w = csv.writer(sys.stdout)
        w.writerow(["race_set", "year", "field", "have", "total", "pct"])
        for ratio, race_set, year, field, have, total in found:
            w.writerow([race_set, year, field, have, total, f"{100 * ratio:.1f}"])
        conn.close()
        return 0

    race_sets = sorted({s for s, _ in rows})
    total_stages = sum(r["stages"] for r in rows.values())
    total_results = sum(r["results"] for r in rows.values())
    print(f"Coverage across {len(rows):,} race-years "
          f"({total_stages:,} stages, {total_results:,} results)")
    print("Cancelled stages and fields with no upstream source are excluded — "
          "see the module docstring.")

    if args.years:
        for race_set in race_sets:
            print_year_table(rows, race_set)

    print(f"\nBiggest gaps ({len(found)} race-year/field combinations incomplete):")
    if not found:
        print("  none — every field this report tracks is fully populated")
    for ratio, race_set, year, field, have, total in found[:args.worst]:
        print(f"  {race_set:<11} {year}  {field:<20} "
              f"{have:>7,}/{total:<7,} {pct(have, total)}  "
              f"({total - have:,} missing)")
    if len(found) > args.worst:
        remaining = sum(t - h for _, _, _, _, h, t in found[args.worst:])
        print(f"  ... and {len(found) - args.worst} more, {remaining:,} values "
              f"(--worst {len(found)} for all)")

    # Rider fields are global, so they sit outside the per-year table rather
    # than being repeated identically on every row of it.
    if not args.race and not args.field:
        total, counts = rider_coverage(cur)
        print(f"\nRiders ({total:,}):")
        for field, have in counts.items():
            print(f"  {field:<20} {have:>7,}/{total:<7,} {pct(have, total)}"
                  f"  ({total - have:,} missing)")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
