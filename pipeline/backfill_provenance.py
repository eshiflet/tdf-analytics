#!/usr/bin/env python3
"""
Seed data_provenance for values that predate provenance tracking.

Going forward every writer records its own provenance (see record_provenance in
race_common.py). This fills in the history, but ONLY where the source can
actually be proven from artifacts still on disk:

  source_slug   'pcs' when the stage's scrape file carries a "slug" key (it was
                read off the page), otherwise 'derived' — backfill_source_slugs.py
                inferred it from stage-date split detection.
  results       'pcs' + the scrape file path when that file still exists.
                For the one-day races (11 classics, 7 gravel/MTB) the scrape
                file is per EDITION, not per stage, and the upstream is not
                always PCS — so the source is read back from what the ingest
                script recorded for that same stage's other fields. See
                ingested_origin().
  distance_km   'pcs' + file, but only when the scrape file's own "Distance"
                agrees with the DB. A disagreement means something later
                overwrote it (patch_missing_distances.py from the page header,
                patch_bri_distances.py from bikeraceinfo.com, or a manual fix)
                and we cannot tell which — that stays 'unknown'.

Everything else with a stored value and no provable origin is recorded as
'unknown' rather than guessed. That is deliberate: vertical_meters in
particular is a mix of PCS scrapes, Wikipedia backfills and hand-entered
values, and a confidently wrong provenance would invite exactly the bulk
re-scrape that destroys the good patched figures. 'unknown' is a to-do list;
a wrong 'pcs' is a trap.

Usage:
  python3 backfill_provenance.py --dry-run
  python3 backfill_provenance.py
"""

import argparse
import json
import os
import re
import sqlite3

from race_common import (
    CLASSICS,
    DB_PATH,
    GRAVEL,
    SOURCE_DERIVED,
    SOURCE_PCS,
    SOURCE_UNKNOWN,
    record_provenance,
)

HERE = os.path.dirname(os.path.abspath(__file__))

# race name -> scrapes dir (TDF's per-year files live in tdf_YEAR_full.json and
# aren't per-stage, so it has no per-stage file to point at)
SCRAPE_DIRS = {
    "Giro d'Italia": "giro_scrapes",
    "Vuelta a España": "vuelta_scrapes",
}

# The one-day races keep one file per EDITION under a slug directory, and the
# slug is PCS's / Life Time's rather than anything derivable from the race name
# (San Sebastian is `san-sebastian`, Flanders is `ronde-van-vlaanderen`). Both
# registries are already keyed by that slug, so invert them instead of
# restating a map that would silently rot the next time one is added.
ONE_DAY_DIRS = {
    **{info.name: ("classics_scrapes", slug) for slug, info in CLASSICS.items()},
    **{info.name: ("gravel_scrapes", slug) for slug, info in GRAVEL.items()},
}

# the scripts whose provenance rows describe the ingest itself, as opposed to a
# later patch of one field
INGEST_SCRIPTS = ("ingest_classics.py", "ingest_gravel.py")

# stages columns worth tracking — those with more than one possible source
TRACKED_FIELDS = ["vertical_meters", "profile_score", "distance_km",
                  "route_type", "source_slug"]


def load_stage_file(race_name, year, stage_number):
    """Return (parsed_json, relpath) for a stage's scrape file, or (None, None)."""
    d = SCRAPE_DIRS.get(race_name)
    if not d:
        return None, None
    path = os.path.join(HERE, d, str(year), f"stage_{stage_number}.json")
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), os.path.relpath(path, HERE)
    except Exception:
        return None, None


def load_edition_file(race_name, year):
    """(parsed_json, relpath) for a one-day race's edition file, or (None, None)."""
    entry = ONE_DAY_DIRS.get(race_name)
    if not entry:
        return None, None
    d, slug = entry
    path = os.path.join(HERE, d, slug, f"{year}.json")
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), os.path.relpath(path, HERE)
    except Exception:
        return None, None


def ingested_origin(cur, stage_id):
    """The (source, source_ref) the INGEST recorded for this stage's other
    scraped fields, or (None, None) when that is not unambiguous.

    A one-day race's results and its stage metadata come out of one fetch in
    one transaction, so the origin ingest_classics/ingest_gravel recorded for
    distance_km *is* the origin of the results — not a guess, the same file.
    This is why the source cannot be hardcoded to 'pcs': the gravel races come
    from Athlinks, and The Traka is tretzesports for 2021-22 and PCS from 2023.

    Scoping to the ingest scripts is what makes it unambiguous. Milan-San Remo
    2013's distance_km was later re-sourced from Wikipedia (PCS prints 121 km
    against a 43.577 km/h winner); that patch says nothing about where the
    results came from, and without the filter it would make the stage look
    like it had two origins.
    """
    rows = cur.execute(
        f"""SELECT DISTINCT source, source_ref FROM data_provenance
              WHERE entity='stages' AND entity_id=? AND source != ?
                AND script IN ({','.join('?' * len(INGEST_SCRIPTS))})""",
        (stage_id, SOURCE_DERIVED, *INGEST_SCRIPTS),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]["source"], rows[0]["source_ref"]
    return None, None


def scrape_file_distance(data):
    """The distance the scrape file itself recorded, or None."""
    raw = (data.get("info") or {}).get("Distance")
    if not raw:
        return None
    m = re.match(r"([\d.]+)", raw)
    return float(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    read, write, aux = conn.cursor(), conn.cursor(), conn.cursor()

    existing = {
        (r["entity_id"], r["field"])
        for r in read.execute(
            "SELECT entity_id, field FROM data_provenance WHERE entity='stages'"
        )
    }

    counts = {}
    def note(entity_id, field, source, ref):
        if (entity_id, field) in existing:
            return                      # never overwrite a real recorded origin
        counts[source] = counts.get(source, 0) + 1
        if not args.dry_run:
            record_provenance(write, "stages", entity_id, field, source,
                              source_ref=ref, script="backfill_provenance.py")

    rows = read.execute("""
        SELECT s.stage_id, s.stage_number, s.vertical_meters, s.profile_score,
               s.distance_km, s.route_type, s.source_slug,
               re.year, r.name AS race
        FROM stages s
        JOIN race_editions re ON s.edition_id = re.edition_id
        JOIN races r ON re.race_id = r.race_id
        ORDER BY r.name, re.year, s.stage_number
    """).fetchall()

    for s in rows:
        sid = s["stage_id"]
        data, relpath = load_stage_file(s["race"], s["year"], s["stage_number"])

        # ── source_slug: read off the page, or inferred from dates? ──
        if s["source_slug"]:
            if data and data.get("slug"):
                note(sid, "source_slug", SOURCE_PCS, f"{relpath} (slug)")
            else:
                note(sid, "source_slug", SOURCE_DERIVED,
                     "inferred from stage_date split detection")

        # ── results: the scrape file is the artifact they came from ──
        one_day, od_relpath = load_edition_file(s["race"], s["year"])
        if data is not None:
            note(sid, "results", SOURCE_PCS, relpath)
        elif one_day is not None:
            src, ref = ingested_origin(aux, sid)
            if src:
                note(sid, "results", src, ref or od_relpath)
            else:
                note(sid, "results", SOURCE_UNKNOWN,
                     f"{od_relpath} on disk but its ingest recorded no single "
                     "origin; origin unproven")
        else:
            note(sid, "results", SOURCE_UNKNOWN,
                 "no scrape file on disk; origin unproven")

        # ── distance_km: only claim PCS if the file still agrees ──
        if s["distance_km"] is not None:
            file_km = scrape_file_distance(data) if data else None
            if file_km is not None and abs(file_km - s["distance_km"]) < 0.05:
                note(sid, "distance_km", SOURCE_PCS, relpath)
            else:
                note(sid, "distance_km", SOURCE_UNKNOWN,
                     "DB value differs from scrape file or no file; "
                     "later patched by an unrecorded source")

        # ── route_type: derived from the scraped profile icon + won_how ──
        if s["route_type"]:
            if data is not None:
                note(sid, "route_type", SOURCE_DERIVED,
                     f"detect_route_type() from {relpath}")
            else:
                note(sid, "route_type", SOURCE_UNKNOWN, "origin unproven")

        # ── elevation: genuinely unknowable retroactively ──
        for field in ("vertical_meters", "profile_score"):
            if s[field] is not None:
                note(sid, field, SOURCE_UNKNOWN,
                     "predates provenance tracking; mix of PCS scrapes, "
                     "Wikipedia backfills and manual entry — re-scrape by "
                     "source_slug to establish")

    if not args.dry_run:
        conn.commit()

    total = sum(counts.values())
    print(f"{'[DRY RUN] ' if args.dry_run else ''}{total} provenance rows "
          f"across {len(rows)} stages")
    for src, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {src:12} {n:6}")
    if existing:
        print(f"  ({len(existing)} already recorded, left untouched)")
    conn.close()


if __name__ == "__main__":
    main()
