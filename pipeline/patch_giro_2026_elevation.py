#!/usr/bin/env python3
"""
Patch 2026 Giro d'Italia stages with per-stage elevation gain and corrected route types.
Source: giroitalialive.com stage table + official Giro website.

HISTORICAL. 16 of these 21 stages have since been superseded by scraped PCS
values (stage 8 reads 1,804 m against the 2,500 m estimate here), and the five
that still match are stages 1-5. Kept as the record of where those five came
from; run it only if you mean to put the estimates back.

Two things were wrong with it until 2026-09-19 and are worth not repeating:

  * It had no ``if __name__ == "__main__"`` guard, so it connected, UPDATEd 21
    stages and committed AT IMPORT TIME. It was the only script in the pipeline
    that did — an audit of every unguarded module found these three top-level
    writers and the other two only define SQL strings. Merely importing this
    module to read STAGE_DATA rewrote the database.
  * It wrote ``vertical_meters`` and ``route_type`` for 21 stages without a
    single ``record_provenance()`` call, against the rule that every writer
    records its source. It does now.
"""

import argparse
import sqlite3
import os
import sys

from race_common import record_provenance

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")

# giroitalialive.com is not one of VALID_SOURCES, and inventing a source name
# for a one-off patch would make the registry meaningless. "manual" is what
# this is — values a human read off a website and typed in — and source_ref
# below names the site.
SOURCE = "manual"

# Per-stage data from giroitalialive.com route table + official giro website.
# Route types: F=Flat, H=Hilly, M=Mountain, TT=Time Trial
# Elevation values with ~ are estimates from the source (still best available).
STAGE_DATA = {
    1:  {"vert": 872,  "route_type": "F"},   # Nessebar → Burgas, Flat
    2:  {"vert": 2348, "route_type": "H"},   # Burgas → Veliko Tarnovo, Hilly
    3:  {"vert": 1577, "route_type": "F"},   # Plovdiv → Sofia, Flat (capital sprint)
    4:  {"vert": 1600, "route_type": "H"},   # Catanzaro → Cosenza, Flat/hilly
    5:  {"vert": 3724, "route_type": "H"},   # Praia a Mare → Potenza, Hilly
    6:  {"vert": 500,  "route_type": "F"},   # Paestum → Naples, Flat
    7:  {"vert": 4500, "route_type": "M"},   # Formia → Blockhaus, Mountain
    8:  {"vert": 2500, "route_type": "H"},   # Chieti → Fermo, Hilly
    9:  {"vert": 2500, "route_type": "H"},   # Cervia → Corno alle Scale, Hilly
    10: {"vert": 100,  "route_type": "TT"},  # Viareggio → Massa, ITT
    11: {"vert": 2800, "route_type": "H"},   # Porcari → Chiavari, Hilly
    12: {"vert": 2200, "route_type": "H"},   # Imperia → Novi Ligure, Flat/hilly
    13: {"vert": 1800, "route_type": "F"},   # Alessandria → Verbania, Flat
    14: {"vert": 4200, "route_type": "M"},   # Aosta → Pila, Mountain
    15: {"vert": 500,  "route_type": "F"},   # Voghera → Milan, Flat
    16: {"vert": 3000, "route_type": "M"},   # Bellinzona → Carì, Mountain
    17: {"vert": 2500, "route_type": "H"},   # Cassano d'Adda → Andalo, Hilly
    18: {"vert": 1800, "route_type": "H"},   # Fai della Paganella → Pieve di Soligo, Flat/hilly
    19: {"vert": 4800, "route_type": "M"},   # Feltre → Piani di Pezzè, Mountain (queen stage)
    20: {"vert": 4000, "route_type": "M"},   # Gemona → Piancavallo, Mountain
    21: {"vert": 500,  "route_type": "F"},   # Rome → Rome, Flat
}

def main():
    # Dry run by default, like backfill_gc_gaps.py and the other writers here.
    # This one earns it twice over: 16 of its 21 values have since been
    # superseded by scraped PCS figures, so running it is not a no-op that
    # re-applies a patch — it REPLACES measured values with the source's own
    # approximations. Stage 8 goes from 1,804 m back to 2,500 m.
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="write (default: show what would change)")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    edition = cur.execute("""
        SELECT re.edition_id FROM race_editions re
        JOIN races r ON r.race_id = re.race_id
        WHERE r.name = 'Giro d''Italia' AND re.year = 2026
    """).fetchone()

    if not edition:
        print("ERROR: 2026 Giro edition not found in DB")
        conn.close()
        return 1

    edition_id = edition["edition_id"]
    updated = 0

    print(f"{'st':>3} {'stored':>8} {'this file':>10}  route")
    for stage_num, data in sorted(STAGE_DATA.items()):
        cur_row = cur.execute(
            "SELECT vertical_meters, route_type FROM stages "
            "WHERE edition_id = ? AND stage_number = ?",
            (edition_id, stage_num)).fetchone()
        if cur_row and cur_row["vertical_meters"] != data["vert"]:
            print(f"{stage_num:>3} {str(cur_row['vertical_meters']):>8} "
                  f"{data['vert']:>10}  {cur_row['route_type']} -> {data['route_type']}")
        if not args.apply:
            continue
        cur.execute("""
            UPDATE stages SET vertical_meters = ?, route_type = ?
            WHERE edition_id = ? AND stage_number = ?
        """, (data["vert"], data["route_type"], edition_id, stage_num))
        if cur.rowcount:
            updated += cur.rowcount
            # Both columns, because it writes both. The original recorded
            # neither, which is why the five surviving values had no source.
            stage_id = cur.execute(
                "SELECT stage_id FROM stages WHERE edition_id = ? AND stage_number = ?",
                (edition_id, stage_num)).fetchone()["stage_id"]
            for field in ("vertical_meters", "route_type"):
                record_provenance(
                    cur, "stages", stage_id, field, SOURCE,
                    source_ref="giroitalialive.com route table + the official "
                               "Giro site; several values are the source's own "
                               "approximations",
                    script=os.path.basename(__file__))

    if not args.apply:
        conn.close()
        print("\nDry run. Nothing written. Re-run with --apply if you really "
              "mean to replace the scraped values above with these.")
        return 0
    conn.commit()
    conn.close()

    total_vert = sum(d["vert"] for d in STAGE_DATA.values())
    print(f"Updated {updated} stages for 2026 Giro d'Italia")
    print(f"Total elevation: {total_vert:,}m across 21 stages")
    print(f"(Official total per giroitalialive.com: 49,150m — difference of {49150 - total_vert:+}m from approximate stage values)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
