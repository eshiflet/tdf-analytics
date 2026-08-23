#!/usr/bin/env python3
"""Backfill data_provenance for rider and team rows written before it existed.

Companion to backfill_provenance.py, which does the same for `stages` columns
(source_slug, results, distance_km) and follows the same rule: prove the source
from artifacts still on disk, or record `unknown`. This one covers `riders` and
`teams`, which that script never touched — `teams` had no provenance at all.

Every writer records provenance now, but rows inserted earlier never did:
3,489 riders and all 4,798 teams had no row at all. `teams` had no coverage
whatsoever — the table was never in the provenance story.

The source is DERIVED FROM EVIDENCE, never assumed. This script reads every
scrape file on disk and records which rider/team ids are actually attested in
one, then:

  * an id attested only in gravel_scrapes  -> athlinks
  * an id attested in a road scrape        -> pcs
  * an id attested nowhere                 -> unknown

That last bucket is the point of the exercise rather than a failure of it.
1,303 teams — including all 718 that no longer have a single result pointing
at them — appear in no scrape file that still exists. Their ids are
PCS-shaped, so `pcs` would look right and read plausibly forever, but the
trail that would prove it is gone. `unknown` is what the schema provides for
exactly this ("predates provenance tracking; origin unproven"), and a row that
says so is worth more than a confident guess nobody can check.

Never overwrites an existing provenance row, and never claims a NULL column.

Usage:
  python3 backfill_provenance.py --dry-run
  python3 backfill_provenance.py
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import sys
from collections import Counter

from race_common import (
    DB_PATH,
    SOURCE_ATHLINKS,
    SOURCE_DERIVED,
    SOURCE_PCS,
    SOURCE_UNKNOWN,
    exit_on_help,
    record_provenance,
)

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.basename(__file__)
ID_RE = re.compile(r"(?:rider|team)/[A-Za-z0-9._\-]+")

# What each piece of evidence actually proves, field by field. A results
# table carries a rider's NAME and NATIONALITY and nothing else, so
# attestation in one is evidence for those two columns only — a birth year
# sitting in the same row came from somewhere this script cannot see, and
# gets `unknown` rather than a plausible-looking `pcs`.
FROM_RESULTS_TABLE = ("full_name", "nationality_code")
RIDER_FIELDS = ("full_name", "nationality_code", "first_name", "last_name",
                "birth_year_approx")
# Verified, not assumed: all 3,475 gravel-only riders hold values byte-identical
# to _rider_ids.json, so Athlinks is provably the source of every one of these.
ATHLINKS_FIELDS = RIDER_FIELDS

REF = {
    SOURCE_PCS: "attested in a road scrape file on disk (PCS results table)",
    SOURCE_ATHLINKS: "value identical to gravel_scrapes/_rider_ids.json (Athlinks)",
    SOURCE_UNKNOWN: "in no scrape file on disk; written before provenance tracking",
    SOURCE_DERIVED: "trailing year of the PCS team slug",
}


def attested_ids():
    """(road, gravel) sets of every rider/team id appearing in a scrape file."""
    road, gravel = set(), set()
    files = (glob.glob(os.path.join(HERE, "*_scrapes/**/*.json"), recursive=True)
             + glob.glob(os.path.join(HERE, "scrapes/**/*.json"), recursive=True)
             + glob.glob(os.path.join(HERE, "tdf_*_full.json")))
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        found = set(ID_RE.findall(text))
        rel = os.path.relpath(path, HERE)
        (gravel if rel.startswith("gravel_scrapes") else road).update(found)
    # link_gravel_riders.py mints ids that appear only as JSON keys' values.
    ids_path = os.path.join(HERE, "gravel_scrapes", "_rider_ids.json")
    if os.path.exists(ids_path):
        with open(ids_path, encoding="utf-8") as f:
            gravel.update(v["rider_id"] for v in json.load(f).values())
    return road, gravel


def classify(entity_id, road, gravel):
    if entity_id in road:
        return SOURCE_PCS
    if entity_id in gravel:
        return SOURCE_ATHLINKS
    return SOURCE_UNKNOWN


def plan(cur, road, gravel):
    """[(entity, id, field, source)] for every unclaimed non-NULL column."""
    have = {(e, i, f) for e, i, f in
            cur.execute("SELECT entity, entity_id, field FROM data_provenance")}
    out = []

    for row in cur.execute(f"SELECT rider_id,{','.join(RIDER_FIELDS)} FROM riders"):
        rid, values = row[0], row[1:]
        attested = classify(rid, road, gravel)
        for field, val in zip(RIDER_FIELDS, values):
            if val is None or ("riders", rid, field) in have:
                continue  # never claim a NULL, never overwrite
            if attested == SOURCE_ATHLINKS and field in ATHLINKS_FIELDS:
                src = SOURCE_ATHLINKS
            elif attested == SOURCE_PCS and field in FROM_RESULTS_TABLE:
                src = SOURCE_PCS
            else:
                # Attested, but not in a column that attestation speaks to.
                src = SOURCE_UNKNOWN
            out.append(("riders", rid, field, src))

    for tid, name, season in cur.execute(
            "SELECT team_id, name, season_year FROM teams"):
        if name is not None and ("teams", tid, "name") not in have:
            src = SOURCE_PCS if tid in road else SOURCE_UNKNOWN
            out.append(("teams", tid, "name", src))
        # season_year is parsed out of the id itself, so the id is the evidence
        # and it holds even for a team no surviving scrape mentions.
        if season is not None and ("teams", tid, "season_year") not in have:
            out.append(("teams", tid, "season_year", SOURCE_DERIVED))
    return out


def main(argv):
    exit_on_help(__doc__, argv)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    print("scanning scrape files for attested ids ...")
    road, gravel = attested_ids()
    print(f"  {len(road)} road ids, {len(gravel)} gravel ids attested")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    rows = plan(cur, road, gravel)

    tally = Counter((e, s) for e, _i, _f, s in rows)
    # One entity can appear under two sources (a team's name is pcs while its
    # season_year is derived), so count distinct ids per (entity, source) pair
    # rather than mapping each id to a single source.
    ents = Counter(k for k in {(e, s, i) for e, i, _f, s in rows}
                   for k in [(k[0], k[1])])
    print(f"\n{'ENTITY':<8} {'SOURCE':<10} {'ROWS':>9} {'ENTITIES':>9}")
    print("-" * 40)
    for (e, s), n in sorted(tally.items()):
        print(f"{e:<8} {s:<10} {n:>9} {ents[(e, s)]:>9}")
    print(f"\n{len(rows)} provenance rows to write")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0
    for entity, eid, field, src in rows:
        record_provenance(cur, entity, eid, field, src,
                          source_ref=REF.get(src), script=SCRIPT)
    conn.commit()
    conn.close()
    print(f"\nwrote {len(rows)} provenance rows")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
