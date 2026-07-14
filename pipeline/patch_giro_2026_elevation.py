#!/usr/bin/env python3
"""
Patch 2026 Giro d'Italia stages with per-stage elevation gain and corrected route types.
Source: giroitalialive.com stage table + official Giro website.
"""

import sqlite3
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")

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
    exit(1)

edition_id = edition["edition_id"]
updated = 0

for stage_num, data in STAGE_DATA.items():
    cur.execute("""
        UPDATE stages SET vertical_meters = ?, route_type = ?
        WHERE edition_id = ? AND stage_number = ?
    """, (data["vert"], data["route_type"], edition_id, stage_num))
    if cur.rowcount:
        updated += cur.rowcount

conn.commit()
conn.close()

total_vert = sum(d["vert"] for d in STAGE_DATA.values())
print(f"Updated {updated} stages for 2026 Giro d'Italia")
print(f"Total elevation: {total_vert:,}m across 21 stages")
print(f"(Official total per giroitalialive.com: 49,150m — difference of {49150 - total_vert:+}m from approximate stage values)")
