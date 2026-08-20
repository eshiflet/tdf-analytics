#!/usr/bin/env python3
"""
Correct the 2013 Milan-San Remo distance, which PCS publishes inconsistently.

PCS's own race page carries BOTH of these, and they cannot both be true:

    Distance: 121 km
    Avg. speed winner: 43.577 km/h

The winner's time on that same page is Ciolek's 5h37m20s. 121 km in 5h37m20s
is 21.5 km/h, so PCS's speed is computed from some other distance — 43.577 x
5.622h = 245.0 km — while its Distance field reports something else entirely,
most likely only the first sector ridden before the race was neutralised.

2013 is the snow edition: organisers stopped the race at Ovada, bussed the
field over the Passo del Turchino to Cogoleto, and restarted, cutting the
planned 298 km to 246. Wikipedia states that figure in both its infobox
(`| distance = 246`) and its prose, which is what this stores — a directly
published distance, rather than one back-computed from PCS's speed. The cost
is that our winning speed reads 43.76 km/h against PCS's 43.577, because PCS
internally used 245 km; that 0.4% is the price of a citable source.

Our 121 km was a faithful scrape (`ingest_classics.py`, provenance 'pcs'), so
nothing here was a parsing bug — the upstream field is simply wrong for this
edition. It rendered as a 21.5 km/h spike in the Race History chart, half the
speed of every neighbouring year.

Checked and NOT changed: no other PCS page carries a corrected distance
(/route, /info and the bare race page have no usable Distance), and an audit of
all 966 classics editions against their own race's 15-year median found no
other edition more than 25% off. The 1919 and 1945 Paris-Roubaix outliers are
war-damaged roads, not data errors.

Usage:
  python3 patch_msr_2013_distance.py          # report only
  python3 patch_msr_2013_distance.py --apply
"""

import argparse
import sqlite3
import sys

from race_common import DB_PATH, SOURCE_WIKIPEDIA, record_provenance

YEAR = 2013
RACE = "Milan-San Remo"
STORED_BAD = 121.0
CORRECT_KM = 246.0
CITATION = (
    "https://en.wikipedia.org/wiki/2013_Milan%E2%80%93San_Remo — infobox "
    "'distance = 246' and prose 'shortened ... from 298 km to 246 km'. "
    "Replaces PCS's own Distance field (121 km), which contradicts the avg "
    "speed winner (43.577 km/h) printed beside it on the same page. Must NOT "
    "be overwritten by a PCS re-scrape."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    row = cur.execute(
        """SELECT s.stage_id, s.distance_km,
                  (SELECT sr.finish_time_seconds FROM stage_results sr
                    WHERE sr.stage_id = s.stage_id AND sr.stage_rank = 1) AS t
           FROM stages s
           JOIN race_editions re ON re.edition_id = s.edition_id
           JOIN races r ON r.race_id = re.race_id
           WHERE r.name = ? AND re.year = ?""", (RACE, YEAR)).fetchone()
    if not row:
        sys.exit(f"{RACE} {YEAR} not found")

    # Refuse to run twice, or against a value someone has since revised: this
    # only ever replaces the specific broken figure it was written for.
    if row["distance_km"] != STORED_BAD:
        sys.exit(f"distance is {row['distance_km']} km, expected the broken "
                 f"{STORED_BAD} — already patched or changed; not touching it")

    hours = row["t"] / 3600
    print(f"{RACE} {YEAR}: {row['distance_km']} -> {CORRECT_KM} km")
    print(f"  winner time {row['t']}s = {hours:.4f} h")
    print(f"  speed {row['distance_km'] / hours:.3f} -> {CORRECT_KM / hours:.3f} km/h "
          f"(PCS prints 43.577, computed from 245 km)")

    if args.apply:
        cur.execute("UPDATE stages SET distance_km=? WHERE stage_id=?",
                    (CORRECT_KM, row["stage_id"]))
        record_provenance(cur, "stages", row["stage_id"], "distance_km",
                          SOURCE_WIKIPEDIA, source_ref=CITATION,
                          script="patch_msr_2013_distance.py")
        conn.commit()
        print("\napplied")
    else:
        print("\nDry run. Re-run with --apply to write this.")
    conn.close()


if __name__ == "__main__":
    main()
