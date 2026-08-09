#!/usr/bin/env python3
"""
Correct six Tour finales whose distance was copied from the stage before it.

PCS publishes "Distance: 0 km" for these pages. Something filled the hole at
some point by carrying the neighbouring stage's value forward, so the last
stage into Paris ended up holding the previous day's figure exactly — a 51 km
Beaujolais time trial standing in for a 197 km run to the Champs-Elysees. All
six read `source: unknown` in data_provenance ("later patched by an unrecorded
source"), which is how they were found.

1989 is the worst of them: the Versailles - Paris finale was the 24.5 km
individual time trial LeMond won the Tour on by eight seconds, stored as a
130 km flat road stage.

The replacement figures come from each edition's Wikipedia stage-characteristics
table, recorded as SOURCE_WIKIPEDIA. Wikipedia's *headline* totals are not
trustworthy here — its 1968, 1954 and 1999 infoboxes each contradict that same
article's stage table — but the per-stage tables agree with PCS and
bikeraceinfo everywhere they can be compared, and 1983's 195 km is independently
confirmed by bri_stages.json.

Each correction is checked against the edition total before it is written: with
it applied the summed stages must move CLOSER to the published race distance,
and stay within DISTANCE_TOLERANCE_PCT of it. 1984, 1986 and 1989 land within
1 km of the published figure, which is about as strong a confirmation as this
data allows.

Safe against re-ingest: ingest_race.py preserves a stored distance when the
scrape reports none, and the TDF path (add_stages.py) skips editions already in
the DB. route_type is NOT preserved, but nothing re-ingests these editions.

Usage:
  python3 fix_paris_finale_distances.py --dry-run
  python3 fix_paris_finale_distances.py --apply
"""

import argparse
import json
import os
import sqlite3
import sys

from race_common import DB_PATH, SOURCE_WIKIPEDIA, record_provenance

HERE = os.path.dirname(os.path.abspath(__file__))
WIKI_DISTANCES_PATH = os.path.join(HERE, "wiki_race_distances.json")
TOLERANCE_PCT = 3.0

WIKI = "https://en.wikipedia.org/wiki/%d_Tour_de_France"

# year: (stage_number, correct km, expected stored km, route)
FIXES = {
    1983: (22, 195.0, 50.0, "Alfortville - Paris"),
    1984: (23, 197.0, 51.0, "Pantin - Paris"),
    1986: (23, 255.0, 196.0, "Cosne sur Loire - Paris"),
    1989: (21, 24.5, 130.0, "Versailles - Paris"),
    1991: (22, 178.0, 57.0, "Melun - Paris"),
    1998: (21, 147.5, 53.0, "Melun - Paris"),
}

# The 1989 finale was an ITT, not the usual processional road stage.
ROUTE_TYPE_FIXES = {1989: (21, "TT", "itt")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    with open(WIKI_DISTANCES_PATH, encoding="utf-8") as f:
        published = json.load(f)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro" if args.dry_run else DB_PATH,
                           uri=args.dry_run)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    changed = 0
    for year, (n, correct, expected_old, route) in sorted(FIXES.items()):
        row = cur.execute(
            """SELECT s.stage_id, s.distance_km, s.start_location, s.finish_location,
                      s.edition_id
                 FROM stages s
                 JOIN race_editions re USING(edition_id)
                 JOIN races r USING(race_id)
                WHERE r.name='Tour de France' AND re.year=? AND s.stage_number=?""",
            (year, n)).fetchone()
        if row is None:
            print(f"  {year} stage {n}: not in the DB — skipped")
            continue

        # Refuse to write over a value that is no longer the one that was
        # diagnosed. If someone has already corrected it, or the edition has
        # been renumbered, this script's premise no longer holds.
        if abs((row["distance_km"] or 0) - expected_old) > 0.05:
            print(f"  {year} stage {n}: stored {row['distance_km']} km, expected "
                  f"{expected_old} km — changed since diagnosis, skipped")
            continue

        total = cur.execute("SELECT SUM(distance_km) FROM stages WHERE edition_id=?",
                            (row["edition_id"],)).fetchone()[0]
        ref = published.get(str(year))
        new_total = total - row["distance_km"] + correct
        if ref:
            before = abs(total - ref) / ref * 100
            after = abs(new_total - ref) / ref * 100
            if after >= before or after > TOLERANCE_PCT:
                print(f"  {year} stage {n}: correction does not reconcile "
                      f"({before:.1f}% -> {after:.1f}% off {ref} km) — skipped")
                continue
            verdict = f"edition total {total:.1f} -> {new_total:.1f} vs {ref} ({after:.1f}% off)"
        else:
            verdict = f"edition total {total:.1f} -> {new_total:.1f} (no published figure)"

        print(f"  {year} stage {n} {route}: {row['distance_km']} -> {correct} km")
        print(f"      {verdict}")

        if args.apply:
            cur.execute("UPDATE stages SET distance_km=? WHERE stage_id=?",
                        (correct, row["stage_id"]))
            record_provenance(cur, "stages", row["stage_id"], "distance_km",
                              SOURCE_WIKIPEDIA, source_ref=WIKI % year +
                              " (stage characteristics table); PCS publishes 0 km")
        changed += 1

        if year in ROUTE_TYPE_FIXES:
            _, rt, st = ROUTE_TYPE_FIXES[year]
            print(f"      route_type -> {rt}, stage_type -> {st}")
            if args.apply:
                cur.execute("UPDATE stages SET route_type=?, stage_type=? WHERE stage_id=?",
                            (rt, st, row["stage_id"]))
                for field in ("route_type", "stage_type"):
                    record_provenance(cur, "stages", row["stage_id"], field,
                                      SOURCE_WIKIPEDIA, source_ref=WIKI % year +
                                      " (individual time trial, not a road stage)")

    if args.apply:
        conn.commit()
    conn.close()
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}{changed} stage(s) "
          f"{'would be ' if args.dry_run else ''}corrected")
    sys.exit(0 if changed == len(FIXES) else 1)


if __name__ == "__main__":
    main()
