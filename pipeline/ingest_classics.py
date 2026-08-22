#!/usr/bin/env python3
"""Ingest the one-day classics scrapes into cycling.db.

Each classic is its own race (races.race_type = 'one_day') with exactly one
stage per edition — the shape ai-context.md's "Planned direction" note called
for. The frontend's combined "One-day Classics" race is assembled later by
export_classics.py; nothing here knows about that aggregation.

Reads classics_scrapes/<race-slug>/<year>.json (written by
parse_classics_bundle.py). Re-ingesting a race-year deletes and re-creates it
atomically, so the script is safe to re-run.

Cancelled races ARE ingested: a stage row with cancelled=1, its planned date
and distance, and no results. A race that did not happen is a fact about the
season — dropping it would silently shorten the year.

Usage:
  python3 ingest_classics.py --dry-run          # report only, no writes
  python3 ingest_classics.py                    # all races/years found
  python3 ingest_classics.py --race paris-roubaix --year 2021
"""
import argparse
import glob
import json
import os
import sqlite3
import sys

from race_common import (
    CLASSICS,
    classic_route_type,
    parse_time_to_seconds,
    record_provenance,
)
from race_set_ingest import replace_edition, upsert_country, upsert_race

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
SCRAPES = os.path.join(HERE, "classics_scrapes")
PCS = "https://www.procyclingstats.com"

SOURCE_PCS = "pcs"
SOURCE_DERIVED = "derived"

# Non-numeric values PCS puts in the Rnk column.
STATUS_MAP = {"DNF": "DNF", "DNS": "DNS", "DSQ": "DSQ", "OTL": "OTL", "DF": "DNF"}


def upsert_rider(cur, slug, name, nat):
    cur.execute("SELECT rider_id FROM riders WHERE rider_id = ?", (slug,))
    if cur.fetchone():
        # Never overwrite an existing identity — a rider already known from a
        # Grand Tour is the same person, and the name-swap repair work assumes
        # rider_id -> name stays stable.
        return slug
    cur.execute(
        "INSERT INTO riders (rider_id, full_name, nationality_code) VALUES (?,?,?)",
        (slug, name, upsert_country(cur, nat)),
    )
    return slug


def upsert_team(cur, slug, name):
    if not slug:
        return None
    cur.execute("SELECT team_id FROM teams WHERE team_id = ?", (slug,))
    if cur.fetchone():
        return slug
    season = None
    tail = slug.rsplit("-", 1)[-1]
    if tail.isdigit() and len(tail) == 4:
        season = int(tail)
    cur.execute("INSERT INTO teams (team_id, name, season_year) VALUES (?,?,?)",
                (slug, name, season))
    return slug


def ingest_one(cur, path, dry_run=False):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    info = data["info"]
    slug, year = info["race_slug"], info["year"]
    if slug not in CLASSICS:
        raise ValueError(f"{path}: unknown classic slug {slug!r}")
    meta = CLASSICS[slug]
    url = f"{PCS}/{info['source_slug']}"

    if dry_run:
        return (slug, year, len(data["rows"]), data["cancelled"])

    race_id = upsert_race(cur, meta.name, meta.country, "one_day")
    # Atomic: clears this edition's stages, results and provenance first.
    edition_id = replace_edition(cur, race_id, year, info.get("edition_name"))

    vm = info.get("vertical_meters")
    ps = info.get("profile_score")
    route = classic_route_type(ps)
    cur.execute(
        """INSERT INTO stages
             (edition_id, stage_number, stage_label, stage_date, start_location,
              finish_location, distance_km, stage_type, profile_score,
              vertical_meters, won_how, route_type, cancelled, source_slug)
           VALUES (?,1,?,?,?,?,?,'road',?,?,?,?,?,?)""",
        (edition_id, meta.name, info.get("date"), info.get("start_location"),
         info.get("finish_location"), info.get("distance_km"),
         int(ps) if ps is not None else None,
         int(vm) if vm is not None else None,
         info.get("won_how"), route, 1 if data["cancelled"] else 0,
         info["source_slug"]),
    )
    stage_id = cur.lastrowid

    for field in ("stage_date", "start_location", "finish_location", "distance_km",
                  "profile_score", "vertical_meters", "won_how", "source_slug",
                  "cancelled"):
        record_provenance(cur, "stages", stage_id, field, SOURCE_PCS, source_ref=url)
    # route_type is computed from ProfileScore, not published by PCS.
    record_provenance(cur, "stages", stage_id, "route_type", SOURCE_DERIVED,
                      source_ref="race_common.classic_route_type(profile_score)")

    winner_seconds = None
    inserted = 0
    for r in data["rows"]:
        (rnk, _gcpos, _gclag, bib, age, name, rslug, nat,
         team_name, team_slug, uci, pcs_pts, _bonus, abs_time, gap) = r
        if not rslug:
            continue
        upsert_rider(cur, rslug, name, nat)
        upsert_team(cur, team_slug, team_name)

        stage_rank = int(rnk) if rnk.isdigit() else None
        status = "FINISHED" if stage_rank is not None else STATUS_MAP.get(rnk.upper(), "DNF")

        finish_s = gap_s = None
        if stage_rank == 1:
            # PCS prints time and gap in ONE cell, so the winner's row parses
            # with both set to his finishing time. Take it directly and zero
            # the gap; `winner + gap` on this row is what doubled 3,377
            # winning times across the DB (ai-context.md rule 2).
            finish_s = parse_time_to_seconds(abs_time)
            if winner_seconds is None:
                winner_seconds = finish_s
            gap_s = 0
        elif stage_rank is not None:
            gap_s = parse_time_to_seconds(gap)
            if gap_s is not None and winner_seconds is not None:
                finish_s = winner_seconds + gap_s

        def as_int(v):
            v = (v or "").strip()
            # A UCI cell can carry a deduction ("160 -25"); keep the awarded
            # figure and ignore the annotation rather than guess the net.
            v = v.split()[0] if v.split() else ""
            return int(v) if v.lstrip("-").isdigit() else None

        cur.execute(
            """INSERT OR REPLACE INTO stage_results
                 (stage_id, rider_id, team_id, bib_number, stage_rank, status,
                  finish_time_seconds, gap_seconds, uci_points, pcs_points,
                  age_at_race)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (stage_id, rslug, team_slug or None,
             int(bib) if bib.isdigit() else None,
             stage_rank, status, finish_s, gap_s,
             as_int(uci), as_int(pcs_pts),
             int(age) if age.isdigit() else None),
        )
        inserted += 1

    return (slug, year, inserted, data["cancelled"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", help="one classic slug (default: all)")
    ap.add_argument("--year", type=int, help="one year (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    pattern = os.path.join(SCRAPES, args.race or "*", f"{args.year or '*'}.json")
    paths = sorted(glob.glob(pattern))
    if not paths:
        print(f"no scrape files matched {pattern}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    results = []
    try:
        for p in paths:
            results.append(ingest_one(cur, p, dry_run=args.dry_run))
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    total = sum(n for _, _, n, _ in results)
    canc = sum(1 for *_, c in results if c)
    print(("DRY RUN — nothing written\n" if args.dry_run else "") +
          f"{len(results)} race-years, {total:,} results, {canc} cancelled")
    for slug, year, n, c in results:
        print(f"  {slug:<24} {year}  {'CANCELLED' if c else f'{n:>4} results'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
