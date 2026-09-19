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

# race name -> scrapes dir.
#
# The Tour was MISSING here until 2026-09-19, on a comment saying its scrapes
# "live in tdf_YEAR_full.json and aren't per-stage, so it has no per-stage file
# to point at". That stopped being true when convert_tdf_layout.py moved it:
# there are now 2,423 `tour_scrapes/<year>/stage_<n>.json` files across 113
# years and not one `tdf_*_full.json` left. The comment outlived the layout,
# and with it every Tour stage fell to the `if not d: return None, None` at the
# top of load_stage_file() — so all 1,570 of them were recorded `unknown` for
# results, distance_km, route_type, source_slug AND elevation, on the grounds
# that a file this could not find did not exist.
SCRAPE_DIRS = {
    "Tour de France": "tour_scrapes",
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


def scrape_file_number(data, key):
    """The first number under `info[key]` in the scrape file, or None."""
    raw = (data.get("info") or {}).get(key)
    if raw in (None, ""):
        return None
    m = re.search(r"[\d.]+", str(raw).replace(",", ""))
    return float(m.group()) if m else None


def file_is_this_stage(data, row):
    """Does this scrape file actually describe the stage we are looking at?

    Stage files are named `stage_<stage_number>.json`, and a stage number is
    not a stable key: a split day makes PCS's slug diverge from ours, which is
    the bug that put this repo on notice in the first place. So a value is
    never believed on the filename alone — the file's own Distance or Date has
    to agree with the row before its figures are treated as that stage's.

    Either is enough; requiring both would reject 128 stages whose distance was
    later re-sourced from Wikipedia or bikeraceinfo while the date still pins
    the file down. 2,751 of the 2,879 matches agree on both.
    """
    km = scrape_file_number(data, "Distance")
    if km is not None and row["distance_km"] is not None \
            and abs(km - row["distance_km"]) < 0.15:
        return True
    file_date = ((data.get("info") or {}).get("Date") or "")[:10]
    return bool(file_date) and file_date == (row["stage_date"] or "")[:10]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--upgrade-unknown", action="store_true",
                    help="also replace rows already recorded as 'unknown' when "
                         "the artifact on disk now proves the source")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    read, write, aux = conn.cursor(), conn.cursor(), conn.cursor()

    # (entity_id, field) -> source. The SOURCE is needed, not just the key:
    # note() has to tell a real recorded origin, which it must never touch,
    # from an `unknown` placeholder, which --upgrade-unknown may replace.
    existing = {
        (r["entity_id"], r["field"]): r["source"]
        for r in read.execute(
            "SELECT entity_id, field, source FROM data_provenance WHERE entity='stages'"
        )
    }

    counts = {}
    # Per FIELD as well as per source. One total cannot be checked against
    # anything: "3,013 pcs" is true of a run that proved every distance and no
    # elevation at all, and of the reverse. The breakdown is what makes a claim
    # about vertical_meters verifiable against an independent count.
    by_field = {}
    upgraded = {}
    def note(entity_id, field, source, ref):
        prior = existing.get((entity_id, field))
        if prior is not None:
            # Never overwrite a real recorded origin. `unknown` is not one:
            # this script's own docstring calls it a to-do list, and the 51
            # Tour rows it wrote on 2026-08-08 say "unknown" only because
            # SCRAPE_DIRS was missing the Tour and the file it needed was
            # therefore invisible. Replacing "we do not know" with the proof is
            # completing that list, not discarding evidence — but it is still a
            # write over something, so it is opt-in and it only ever goes
            # unknown -> proven, never the other way.
            if not (args.upgrade_unknown and prior == SOURCE_UNKNOWN
                    and source != SOURCE_UNKNOWN):
                return
            upgraded[field] = upgraded.get(field, 0) + 1
        counts[source] = counts.get(source, 0) + 1
        by_field.setdefault(field, {}) \
                .setdefault(source, 0)
        by_field[field][source] += 1
        if not args.dry_run:
            record_provenance(write, "stages", entity_id, field, source,
                              source_ref=ref, script="backfill_provenance.py")

    rows = read.execute("""
        SELECT s.stage_id, s.stage_number, s.vertical_meters, s.profile_score,
               s.distance_km, s.route_type, s.source_slug, s.stage_date,
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

        # ── elevation and profile score: provable from the file, or unknown ──
        #
        # These were called "genuinely unknowable retroactively" until
        # 2026-09-19, and for profile_score that is still true of most of them.
        # It is NOT true of vertical_meters: the stage scrape files carry
        # "Vertical meters" in their own `info` block, and it matches the
        # database exactly for 2,879 of the 2,964 unprovenanced values. That is
        # the same standard distance_km above already uses — claim PCS only
        # where the artifact on disk still says so — and it turns a 2,964-row
        # to-do list into an 85-row one.
        #
        # A stage whose file DISAGREES stays unknown, and the disagreement is
        # the point: something later overwrote the scraped figure and did not
        # say what. Eight do, all of them Tour 2005/2006/2016 and Vuelta 2019.
        for field, key in (("vertical_meters", "Vertical meters"),
                           ("profile_score", "ProfileScore")):
            if s[field] is None:
                continue
            value = scrape_file_number(data, key) if data else None
            if value is not None and int(value) == s[field] \
                    and file_is_this_stage(data, s):
                note(sid, field, SOURCE_PCS, relpath)
            elif value is not None and int(value) != s[field]:
                note(sid, field, SOURCE_UNKNOWN,
                     f"{relpath} says {int(value)} where the DB says "
                     f"{s[field]} — a later writer overwrote the scraped "
                     "figure without recording itself")
            else:
                note(sid, field, SOURCE_UNKNOWN,
                     "no figure in the stage scrape file; PCS serves some "
                     "stages (notably the final one) with an empty stage page "
                     "and publishes the figure on the ROUTE page instead — "
                     "see scrape_route_overview_elevation.py")

    if not args.dry_run:
        conn.commit()

    total = sum(counts.values())
    print(f"{'[DRY RUN] ' if args.dry_run else ''}{total} provenance rows "
          f"across {len(rows)} stages")
    for src, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {src:12} {n:6}")
    print("\n  by field:")
    for field in TRACKED_FIELDS + ["results"]:
        got = by_field.get(field)
        if not got:
            continue
        detail = "  ".join(f"{src} {n:,}" for src, n in
                           sorted(got.items(), key=lambda kv: -kv[1]))
        print(f"    {field:16} {detail}")
    if upgraded:
        detail = "  ".join(f"{f} {n:,}" for f, n in sorted(upgraded.items()))
        print(f"\n  upgraded from 'unknown' to a proven source: {detail}")
    if existing:
        kept = len(existing) - sum(upgraded.values())
        print(f"  ({kept:,} already recorded, left untouched)")
    conn.close()


if __name__ == "__main__":
    main()
