#!/usr/bin/env python3
"""
Correct two Paris-finale elevations from cyclingflash.com.

Both stages were scraped from PCS's race route page on 2026-08-19 and both came
out as outliers against every other Paris finale on record:

  2006 s20   376 m over 154.5 km = 2.4 m/km — lower than any finale 2011+
  2001 s20  1873 m over 160.5 km = 11.7 m/km — higher than all but 2026

cyclingflash.com publishes an "Elevation gain" for both, and its figures sit
inside the plausible band. Eric supplied them (2026-08-19) with the URLs below,
along with distances — 154.5 km and 160.5 km — that match this DB exactly,
which is what confirms both sites mean the same stage.

These values are NOT independently verified here. cyclingflash.com sits behind
Cloudflare bot detection and refuses automated fetches (HTTP 403, then a JS
challenge in a real browser), so they are recorded as SOURCE_CYCLINGFLASH with
the citing URL and this caveat rather than re-scraped. That is the honest
provenance: the source is known, the relay is human, and the row says so.

Effect: no elevation value in this DB is derived any more, and the two
remaining PCS outliers now carry a second source. A re-scrape must not
overwrite these — scrape_route_overview_elevation.py only fills NULLs or
replaces 'derived', so neither path can reach them.

Usage:
  python3 patch_cyclingflash_elevation.py          # report only
  python3 patch_cyclingflash_elevation.py --apply
"""

import argparse
import sqlite3
import sys

from race_common import DB_PATH, SOURCE_CYCLINGFLASH, record_provenance

# (year, source_slug, expected distance_km, new vertical_meters, citing URL)
CORRECTIONS = [
    (2006, "stage-20", 154.5, 1012,
     "https://cyclingflash.com/race/tour-de-france-2006/result/stage-20/combative"),
    (2001, "stage-20", 160.5, 1791,
     "https://cyclingflash.com/race/tour-de-france-2001/result"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    for year, slug, distance, vertical, url in CORRECTIONS:
        row = cur.execute(
            """SELECT s.stage_id, s.distance_km, s.vertical_meters,
                      s.start_location, s.finish_location
               FROM stages s
               JOIN race_editions re ON re.edition_id = s.edition_id
               JOIN races r ON r.race_id = re.race_id
               WHERE r.name='Tour de France' AND re.year=? AND s.source_slug=?""",
            (year, slug)).fetchone()
        if not row:
            sys.exit(f"{year} {slug} not found")

        # Guard, not decoration: the distance is the only independent field
        # tying Eric's source to this row. If it ever stops matching, the two
        # sites are describing different stages and the elevation must not be
        # trusted onto this one.
        if abs(row["distance_km"] - distance) > 0.05:
            sys.exit(f"{year} {slug}: distance is {row['distance_km']} km, "
                     f"cyclingflash says {distance} km — refusing to patch")

        route = f'{row["start_location"]}→{row["finish_location"]}'
        print(f"{year} {slug}  {row['vertical_meters']} → {vertical} m  "
              f"({vertical / distance:.1f} m/km)  {route}")

        if args.apply:
            cur.execute("UPDATE stages SET vertical_meters=? WHERE stage_id=?",
                        (vertical, row["stage_id"]))
            record_provenance(
                cur, "stages", row["stage_id"], "vertical_meters",
                SOURCE_CYCLINGFLASH, source_ref=(
                    f"{url} — 'Elevation gain'. Supplied by the repo owner "
                    f"2026-08-19 to replace a PCS route-page outlier; distance "
                    f"{distance} km matches this DB, confirming the same stage. "
                    f"NOT re-fetched here (Cloudflare blocks automated access). "
                    f"Must NOT be overwritten by a re-scrape."),
                script="patch_cyclingflash_elevation.py")

    if args.apply:
        conn.commit()
        print("\napplied")
    else:
        print("\nDry run. Re-run with --apply to write these.")
    conn.close()


if __name__ == "__main__":
    main()
