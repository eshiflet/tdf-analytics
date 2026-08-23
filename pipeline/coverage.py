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

WHAT IT DOES NOT COUNT. A gap that cannot be filled is noise, and noise is what
made the per-field audits hard to read together:

  * CANCELLED stages are excluded outright. They were never raced, so a NULL
    distance is the correct value, not a gap — the same rule the race totals
    use (see ai-context.md, "Race totals: cancelled stages").
  * The gravel/MTB set is EXEMPT from elevation, profile score, route type,
    teams and source slugs. PCS has no gravel or MTB coverage at all — verified,
    not assumed — so those columns have no upstream to scrape from.
  * The one-day classics are exempt from profile_score and route_type for the
    same reason: a one-day race is not classified as flat/hilly/mountain.

Anything else that is NULL is reported, because in principle a source exists.

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

# race_type -> fields with no upstream to scrape, so a NULL is the end state
# rather than a gap. See the module docstring for why each one is here.
EXEMPT = {
    "gravel": {"vertical_meters", "profile_score", "route_type", "source_slug",
               "team_id", "gc_rank"},
    "one_day": {"profile_score", "route_type", "gc_rank"},
    "stage_race": set(),
}


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


def collect(cur, races):
    """One row per (race_set, year): totals and per-field non-NULL counts.

    Keyed on the SET rather than the individual race, because that is the unit
    a scrape is run in — "the 1953 classics" is a session, "Paris-Roubaix 1953"
    is a page within it. The Grand Tours are their own sets, so they are
    unaffected by the grouping.
    """
    ids = {r[0] for r in races}
    set_of = {}
    for race_id, name, race_type in races:
        set_of[race_id] = name if race_type == "stage_race" else race_type

    rows = defaultdict(lambda: {"stages": 0, "cancelled": 0, "results": 0,
                                "finishers": 0, "race_type": None,
                                **{f: 0 for f in STAGE_FIELDS + RESULT_FIELDS}})

    placeholders = ",".join("?" * len(ids))
    # Cancelled stages are filtered in SQL rather than counted and subtracted:
    # they must not reach the denominator either, or a year that cancelled two
    # of its stages reads as permanently short of complete.
    cur.execute(
        f"""SELECT r.race_id, e.year, s.cancelled,
                   {', '.join('s.' + f for f in STAGE_FIELDS)}
            FROM stages s
            JOIN race_editions e ON e.edition_id = s.edition_id
            JOIN races r ON r.race_id = e.race_id
            WHERE r.race_id IN ({placeholders})""", tuple(ids))
    for race_id, year, cancelled, *values in cur.fetchall():
        key = (set_of[race_id], year)
        row = rows[key]
        row["race_type"] = next(t for i, _, t in races if i == race_id)
        if cancelled:
            row["cancelled"] += 1
            continue
        row["stages"] += 1
        for field, value in zip(STAGE_FIELDS, values):
            if value is not None:
                row[field] += 1

    # The finisher-only fields are counted inside a CASE rather than in a second
    # query: one pass over 786,687 result rows instead of two.
    counted = [f"COUNT(CASE WHEN sr.status = 'FINISHED' THEN sr.{f} END)"
               if f in FINISHERS_ONLY else f"COUNT(sr.{f})"
               for f in RESULT_FIELDS]
    cur.execute(
        f"""SELECT r.race_id, e.year, COUNT(*),
                   SUM(CASE WHEN sr.status = 'FINISHED' THEN 1 ELSE 0 END),
                   {', '.join(counted)}
            FROM stage_results sr
            JOIN stages s ON s.stage_id = sr.stage_id
            JOIN race_editions e ON e.edition_id = s.edition_id
            JOIN races r ON r.race_id = e.race_id
            WHERE r.race_id IN ({placeholders}) AND s.cancelled = 0
            GROUP BY r.race_id, e.year""", tuple(ids))
    for race_id, year, total, finishers, *counts in cur.fetchall():
        row = rows[(set_of[race_id], year)]
        row["results"] += total
        row["finishers"] += finishers or 0
        for field, count in zip(RESULT_FIELDS, counts):
            row[field] += count

    return rows


def denominator(row, field):
    """How many values this field COULD have for one race-year."""
    if field in FINISHERS_ONLY:
        return row["finishers"]
    if field in RESULT_FIELDS:
        return row["results"]
    return row["stages"]


def gaps(rows, only_field=None):
    """[(pct, race_set, year, field, have, total)] for every incomplete field.

    Sorted by how much is missing in absolute terms, not by percentage: a year
    at 40% of 180 stage-results is a bigger afternoon's work than one at 0% of 3,
    and the point of this list is to rank what to do next.
    """
    out = []
    for (race_set, year), row in rows.items():
        exempt = EXEMPT.get(row["race_type"], set())
        for field in STAGE_FIELDS + RESULT_FIELDS:
            if only_field and field != only_field:
                continue
            if field in exempt:
                continue
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
    race_type = rows[(race_set, years[0])]["race_type"]
    exempt = EXEMPT.get(race_type, set())
    fields = [f for f in STAGE_FIELDS + RESULT_FIELDS if f not in exempt]
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
