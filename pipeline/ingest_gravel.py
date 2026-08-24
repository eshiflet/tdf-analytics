#!/usr/bin/env python3
"""Ingest the Life Time off-road scrapes into cycling.db.

Each race is its own race row (races.race_type = 'gravel') with exactly one
stage per edition — the same shape the one-day classics use, and for the same
reason: these are independent races that the frontend later aggregates into a
single displayed "season" at export time. Nothing here knows about that.

Reads gravel_scrapes/<race-slug>/<year>.json (scrape_athlinks.py) and
gravel_scrapes/_rider_ids.json (link_gravel_riders.py). Re-ingesting a
race-year deletes and re-creates it atomically, so the script is safe to
re-run.

What is deliberately NOT stored:

  vertical_meters   Athlinks publishes no elevation and PCS does not cover
                    these races. Every published figure for, say, Leadville
                    disagrees with every other (11,586 ft and 14,517 ft for
                    the same course, from two RideWithGPS traces), so the
                    column stays NULL until a source is chosen per race-year.
                    A NULL is a gap; a guess would be a claim.
  profile_score     PCS's metric, and PCS has nothing here.
  team_id           Athlinks records no team. lifetimegrandprix.com does, but
                    only ONE team per athlete — their current one — so
                    attaching it to a 2022 result would be fiction.

Usage:
  python3 ingest_gravel.py --dry-run
  python3 ingest_gravel.py
  python3 ingest_gravel.py --race leadville --year 2019
"""
import argparse
import glob
import json
import os
import sqlite3
import sys

from link_gravel_riders import fold
from race_set_ingest import (
    capture_patches,
    replace_edition,
    report_patches,
    restore_patches,
    upsert_country,
    upsert_race,
)
from race_common import (
    GRAVEL,
    SOURCE_ATHLINKS,
    SOURCE_DERIVED,
    fix_mojibake,
    gravel_route_type,
    record_provenance,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
SCRAPES = os.path.join(HERE, "gravel_scrapes")
RIDER_IDS = os.path.join(SCRAPES, "_rider_ids.json")


def upsert_rider(cur, ident, source=SOURCE_ATHLINKS, source_ref=None):
    """Insert a gravel-only rider; leave an already-known rider untouched.

    The no-overwrite rule is the same one ingest_classics.py follows, and it
    matters more here: when link_gravel_riders.py says this name IS
    `rider/peter-stetina`, the road career is the authority on his name,
    nationality and birth year. Athlinks knows only where he currently lives.
    """
    rid = ident["rider_id"]
    cur.execute("SELECT rider_id FROM riders WHERE rider_id = ?", (rid,))
    if cur.fetchone():
        return rid
    name = fix_mojibake(ident["name"])
    first = fix_mojibake(ident.get("first_name"))
    last = fix_mojibake(ident.get("last_name"))
    cur.execute(
        """INSERT INTO riders (rider_id, full_name, nationality_code,
                               birth_year_approx, first_name, last_name)
           VALUES (?,?,?,?,?,?)""",
        (rid, name, upsert_country(cur, ident.get("country")),
         ident.get("birth_year_approx"), first, last),
    )
    # NOTE on nationality: Athlinks records where an athlete LIVES, not their
    # nationality, and the two differ for real riders in this data (Torbjorn
    # Andre Roed races as Norwegian out of Grand Junction, Colorado). It is
    # stored anyway because it is right for the overwhelming majority and a
    # missing flag helps nobody — but it is never allowed to overwrite a
    # nationality that came from PCS, which is why this function returns early
    # above. That caveat is what `nationality_code`'s provenance below means:
    # athlinks is the honest source, and it is a residence, not a passport.
    # The source is the race file this rider is first seen in — which is where
    # the stored values actually came from. A rider who later turns up in
    # another off-road race keeps this row, because upsert returns early above.
    for field in ("full_name", "first_name", "last_name", "nationality_code",
                  "birth_year_approx"):
        record_provenance(cur, "riders", rid, field, source,
                          source_ref=source_ref or "gravel_scrapes/_rider_ids.json")
    return rid


def ingest_one(cur, path, rider_ids, dry_run=False):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    info = data["info"]
    slug, year = info["race_slug"], info["year"]
    if slug not in GRAVEL:
        raise ValueError(f"{path}: unknown gravel slug {slug!r}")
    meta = GRAVEL[slug]

    if dry_run:
        return (slug, year, len(data["rows"]), data["cancelled"], info.get("rule"))

    race_id = upsert_race(cur, meta.name, meta.country, "gravel")
    # Read the patches out BEFORE the rebuild destroys them; put them back after.
    patched = capture_patches(cur, race_id, year)
    # Atomic: clears this edition's stages, results and provenance first.
    edition_id = replace_edition(cur, race_id, year, info.get("event_name"))

    # The resolved Athlinks address, stored so nothing ever re-finds this race
    # by searching course names again — the same discipline as source_slug for
    # PCS, and for the same reason: the name is not stable, the id is.
    # Not every gravel race is on Athlinks: The Traka's editions are addressed
    # by sportmaniacs event uuid or tretzesports idCursa. The file says which,
    # and an older file that does not say predates any of that and is Athlinks.
    source = info.get("source", SOURCE_ATHLINKS)
    if source == SOURCE_ATHLINKS:
        source_slug = (f"event/{info['event_id']}/race/{info['course_id']}"
                       if info.get("course_id") else f"event/{info['event_id']}")
    else:
        source_slug = f"{source}/{info['event_id']}"
    route = gravel_route_type(info.get("discipline"))
    cur.execute(
        """INSERT INTO stages
             (edition_id, stage_number, stage_label, stage_date, distance_km,
              stage_type, route_type, cancelled, source_slug)
           VALUES (?,1,?,?,?,?,?,?,?)""",
        (edition_id, meta.name, info.get("date"), info.get("distance_km"),
         info.get("discipline"), route,
         1 if data["cancelled"] else 0, source_slug),
    )
    stage_id = cur.lastrowid

    api = info.get("api_url") or info.get("source_url")
    for field in ("stage_date", "distance_km", "source_slug", "cancelled",
                  "stage_type"):
        record_provenance(cur, "stages", stage_id, field, source,
                          source_ref=api)
    record_provenance(cur, "stages", stage_id, "route_type", SOURCE_DERIVED,
                      source_ref="race_common.gravel_route_type(discipline)")

    inserted = 0
    # stage_results is keyed on (stage_id, rider_id), so two rows that resolve
    # to the same rider silently overwrite each other. That is almost always
    # the right thing — but not when two DIFFERENT people share a name in one
    # field, which really happens: Chequamegon 2007 has two Matthew Nelsons,
    # aged 36 and 32, from different Wisconsin towns, finishing 50th and 53rd.
    # Identity here is by name (see link_gravel_riders.py) and Athlinks gives
    # nothing better, so the row IS lost — but it is reported, not hidden.
    seen_riders = {}
    collisions = []
    for r in data["rows"]:
        key = r["name"].strip()
        ident = rider_ids.get(fold(key).strip())
        if ident is None:
            raise KeyError(
                f"{path}: {key!r} has no entry in _rider_ids.json — "
                "re-run link_gravel_riders.py after any new scrape")
        rider_id = upsert_rider(cur, ident, source, api)
        if rider_id in seen_riders:
            collisions.append((r["name"], seen_riders[rider_id], r.get("rank")))
        seen_riders[rider_id] = r.get("rank")
        bib = r.get("bib")
        cur.execute(
            """INSERT OR REPLACE INTO stage_results
                 (stage_id, rider_id, team_id, bib_number, stage_rank, status,
                  finish_time_seconds, gap_seconds, age_at_race)
               VALUES (?,?,NULL,?,?,?,?,?,?)""",
            (stage_id, rider_id,
             int(bib) if (bib or "").isdigit() else None,
             r.get("rank"), r.get("status") or "FINISHED",
             r.get("finish_seconds"), r.get("gap_seconds"), r.get("age")),
        )
        inserted += 1

    report_patches(f"{slug} {year}", *restore_patches(cur, edition_id, patched))
    if collisions:
        for name, first_rank, second_rank in collisions:
            print(f"    ! {slug} {year}: two riders named {name!r} "
                  f"(ranks {first_rank} and {second_rank}) share one identity; "
                  f"the second row is not stored")
    return (slug, year, inserted, data["cancelled"], info.get("rule"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", help="one gravel slug (default: all)")
    ap.add_argument("--year", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.exists(RIDER_IDS):
        print("gravel_scrapes/_rider_ids.json missing — run link_gravel_riders.py first")
        return 1
    with open(RIDER_IDS, encoding="utf-8") as f:
        rider_ids = json.load(f)

    pattern = os.path.join(SCRAPES, args.race or "*", f"{args.year or '*'}.json")
    paths = sorted(p for p in glob.glob(pattern)
                   if os.path.basename(os.path.dirname(p)) in GRAVEL)
    if not paths:
        print(f"no scrape files matched {pattern}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    results = []
    try:
        for p in paths:
            results.append(ingest_one(cur, p, rider_ids, dry_run=args.dry_run))
        conn.rollback() if args.dry_run else conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    total = sum(n for _, _, n, _, _ in results)
    canc = sum(1 for *_, c, _ in results if c)
    print(("DRY RUN — nothing written\n" if args.dry_run else "") +
          f"{len(results)} race-years, {total:,} results, {canc} cancelled")
    by_race = {}
    for slug, year, n, c, rule in results:
        by_race.setdefault(slug, []).append((year, n, c, rule))
    for slug in sorted(by_race):
        yrs = sorted(by_race[slug])
        n = sum(x[1] for x in yrs)
        print(f"  {GRAVEL[slug].name:<26} {yrs[0][0]}-{yrs[-1][0]}  "
              f"{len(yrs):>2} editions  {n:>6,} results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
