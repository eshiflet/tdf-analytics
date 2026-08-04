#!/usr/bin/env python3
"""
Fix the 1968 Vuelta stage data.

Problems:
  - Stage 15 (Vitoria-Pamplona) was CANCELLED; the backfill audit wrote the
    wrong content to stage_17.json (PCS stage-17 ITT), displacing:
      stage_17.json → should be PCS stage-16 (Pamplona-San Sebastián)
      stage_18.json → should be PCS stage-17 (ITT San Sebastián-Tolosa)
      stage_19.json → duplicate ITT (wrong)
      stage_20.json → should be stage_19 (PCS stage-18 Final Tolosa-Bilbao)
  - The final stage only has 5 result rows; needs all 51 GC finishers.

Fix:
  1. Rotate scrape files: 18→17, 19→18, 20→19, delete 20.
  2. Build new stage_19.json with all 51 GC finishers from the final GC page.
  3. Update gc_standings.json stage keys accordingly.
  4. Re-ingest 1968 via ingest_race.py.
"""

import json
import os
import shutil
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES = os.path.join(HERE, "vuelta_scrapes", "1968")

# ---------------------------------------------------------------------------
# Scraped data (from PCS final GC page and startlist, 2026-08-03)
# ---------------------------------------------------------------------------

# GC final standings: (gc_rank, name_pcs "LAST First", team, gap_str)
# gap_str: '+0:00' for leader, 'mm:ss' or 'h:mm:ss' for others
GC_FINAL = [
    (1,  "GIMONDI Felice",              "Salvarani",                       "+0:00"),
    (2,  "PÉREZ FRANCÉS José",          "Kas - Kaskol",                    "2:15"),
    (3,  "VÉLEZ Eusebio",               "Fagor",                           "5:08"),
    (4,  "ERRANDONEA José María",       "Fagor",                           "5:19"),
    (5,  "ADORNI Vittorio",             "Faema",                           "5:26"),
    (6,  "JANSSEN Jan",                 "Pelforth - Sauvage - Lejeune",    "5:43"),
    (7,  "GÓMEZ Antonio",               "Kas - Kaskol",                    "5:55"),
    (8,  "ECHEVERRÍA Carlos",           "Kas - Kaskol",                    "6:00"),
    (9,  "AIMAR Lucien",                "Bic",                             "6:42"),
    (10, "SPRUYT Jos",                  "Faema",                           "7:50"),
    (11, "OTAÑO Luis",                  "Fagor",                           "10:39"),
    (12, "DUCASSE Jean-Pierre",         "Pelforth - Sauvage - Lejeune",    "12:42"),
    (13, "GABICA Francisco",            "Fagor",                           "13:23"),
    (14, "WRIGHT Michael",              "Bic",                             "14:57"),
    (15, "DÍAZ Ventura",                "Ferrys",                          "15:04"),
    (16, "LÓPEZ RODRÍGUEZ José Manuel", "Fagor",                           "17:16"),
    (17, "MOMEÑE José Antonio",         "Fagor",                           "17:23"),
    (18, "ALTIG Rudi",                  "Salvarani",                       "18:43"),
    (19, "GANDARIAS Andrés",            "Kas - Kaskol",                    "19:54"),
    (20, "HAAST Cees",                  "Bic",                             "20:09"),
    (21, "MANZANEQUE Fernando",         "Karpy",                           "21:54"),
    (22, "PEFFGEN Wilfried",            "Salvarani",                       "24:41"),
    (23, "VAN SCHIL Victor",            "Faema",                           "24:50"),
    (24, "PERURENA Domingo",            "Fagor",                           "27:51"),
    (25, "ELORZA Sebastián",            "Kas - Kaskol",                    "30:52"),
    (26, "SCHLECK Johny",               "Pelforth - Sauvage - Lejeune",    "31:47"),
    (27, "LASA José Manuel",            "Kas - Kaskol",                    "32:25"),
    (28, "SANTAMARINA Luis Pedro",      "Fagor",                           "33:55"),
    (29, "URIBEZUBIA Juan María",       "Karpy",                           "35:55"),
    (30, "FERRETTI Giancarlo",          "Salvarani",                       "36:36"),
    (31, "CANET Salvador",              "Ferrys",                          "36:42"),
    (32, "SAÉZ Ramón",                  "Ferrys",                          "38:21"),
    (33, "ARANZABAL Jesús",             "Fagor",                           "39:17"),
    (34, "LÓPEZ Vicente",               "Kas - Kaskol",                    "40:28"),
    (35, "POGGIALI Roberto",            "Salvarani",                       "45:01"),
    (36, "SAN MIGUEL Gregorio",         "Kas - Kaskol",                    "46:51"),
    (37, "GRAIN Michel",                "Bic",                             "47:55"),
    (38, "VAN DEN BOSSCHE Martin",      "Faema",                           "53:07"),
    (39, "SOAVE Luciano",               "Faema",                           "55:35"),
    (40, "MARTÍN Manuel",               "Karpy",                           "59:26"),
    (41, "SAGARDUY Juan José",          "Karpy",                           "1:01:39"),
    (42, "ETTER Fernand",               "Pelforth - Sauvage - Lejeune",    "1:04:45"),
    (43, "LEMÉTEYER Paul",              "Bic",                             "1:07:58"),
    (44, "MONTY Willy",                 "Pelforth - Sauvage - Lejeune",    "1:08:29"),
    (45, "FARISATO Lino",               "Faema",                           "1:10:55"),
    (46, "GUERRA Pietro",               "Salvarani",                       "1:12:20"),
    (47, "DELBERGHE Edouard",           "Pelforth - Sauvage - Lejeune",    "1:14:10"),
    (48, "GOYENECHE José Ramón",        "Karpy",                           "1:18:55"),
    (49, "NOVAK Anatole",               "Bic",                             "1:30:07"),
    (50, "MINIERI Mario",               "Salvarani",                       "1:35:00"),
    (51, "FERNÁNDEZ Domingo José",      "Karpy",                           "1:46:09"),
]

# Bib numbers from PCS startlist
STARTLIST_BIBS = {
    "JANSSEN Jan": 1, "VAN DE KERCKHOVE Bernard": 2, "MONTY Willy": 3,
    "DUCASSE Jean-Pierre": 4, "DELBERGHE Edouard": 5, "ETTER Fernand": 6,
    "SCHLECK Johny": 7, "LEFEBVRE Jean-Claude": 8, "VIDAMENT Jean": 9,
    "CHTIEJ René": 10,
    "CASTELLO Eduardo": 11, "DÍAZ Ventura": 12, "PERERA Juan Daniel": 13,
    "SAÉZ Ramón": 14, "PONTÓN José Antonio": 15, "IBÁÑEZ Ángel": 16,
    "EREÑOZAGA Gabino": 17, "MARTÍN Esteban": 18, "CANET Salvador": 19,
    "FERNÁNDEZ Sebastián": 20,
    "DE VLAEMINCK Eric": 21, "PLANCKAERT André": 22, "KONINGS Paul": 23,
    "STEEGMANS Raymond": 24, "VEKEMANS Willy": 25, "SONCK Étienne": 26,
    "ERNST Edouard": 27, "WECKX Edward": 28, "COOLS Jan": 29,
    "VERLINDE Gilbert": 30,
    "ERRANDONEA José María": 31, "GABICA Francisco": 32, "VÉLEZ Eusebio": 33,
    "SANTAMARINA Luis Pedro": 34, "LÓPEZ RODRÍGUEZ José Manuel": 35,
    "PERURENA Domingo": 36, "MOMEÑE José Antonio": 37, "OCAÑA Luis": 38,
    "ARANZABAL Jesús": 39, "OTAÑO Luis": 40,
    "AIMAR Lucien": 41, "DEN HARTOG Arie": 42, "HAAST Cees": 43,
    "ADLER Siegfried": 44, "NOVAK Anatole": 45, "GRAIN Michel": 46,
    "LEMÉTEYER Paul": 47, "MILESI Jean": 48, "GRACZYK Jean": 49,
    "WRIGHT Michael": 50,
    "ECHEVERRÍA Carlos": 51, "PÉREZ FRANCÉS José": 52, "GÓMEZ Antonio": 53,
    "SAN MIGUEL Gregorio": 54, "LÓPEZ Vicente": 55, "ELORZA Sebastián": 56,
    "LASA José Manuel": 57, "GONZÁLEZ Aurelio": 58, "ERRANDONEA José Luis": 59,
    "GANDARIAS Andrés": 60,
    "ALTIG Rudi": 61, "DE PRA Tommaso": 62, "FERRETTI Giancarlo": 63,
    "GIMONDI Felice": 64, "GUERRA Pietro": 65, "MINIERI Mario": 66,
    "PARTESOTTI Pietro": 67, "PEFFGEN Wilfried": 68, "POGGIALI Roberto": 69,
    "ZANDEGÙ Dino": 70,
    "MANZANEQUE Fernando": 71, "MARTÍN Manuel": 72, "MESA José Manuel": 73,
    "URIBEZUBIA Juan María": 74, "SAGARDUY Juan José": 75,
    "GOYENECHE José Ramón": 76, "SIVILOTTI Bruno": 77, "INCERA Andrés": 78,
    "FERNÁNDEZ Domingo José": 79, "ISASI Jesús": 80,
    "BAILETTI Antonio": 81, "VAN SCHIL Victor": 82, "SPRUYT Jos": 83,
    "VAN DEN BOSSCHE Martin": 84, "DENTI Giacomino": 85, "SOAVE Luciano": 86,
    "ADORNI Vittorio": 87, "DELOCHT Julien": 88, "FARISATO Lino": 89,
    "SCANDELLI Pietro": 90,
}


def normalize(s):
    """Lowercase, strip diacritics where possible, collapse whitespace."""
    nfd = unicodedata.normalize("NFD", s)
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return " ".join(stripped.lower().split())


def build_rider_lookup():
    """Build slug→{bib,age,name,nat,team,team_slug} from stage_1.json."""
    path = os.path.join(SCRAPES, "stage_1.json")
    d = json.load(open(path, encoding="utf-8"))
    lookup = {}  # slug → dict
    for row in d["rows"]:
        if len(row) < 15:
            continue
        slug = row[6]
        if not slug:
            continue
        lookup[slug] = {
            "bib":       row[3],
            "age":       row[4],
            "name":      row[5],
            "nat":       row[7],
            "team":      row[8],
            "team_slug": row[9],
        }
    return lookup


def pcs_name_to_display(pcs_name):
    """'GIMONDI Felice' → 'Gimondi Felice'."""
    parts = pcs_name.split()
    # Titlecase all tokens except keep accent chars intact via title() on each
    result = []
    for p in parts:
        if p.isupper():
            result.append(p[0] + p[1:].lower() if len(p) > 1 else p)
        else:
            result.append(p)
    return " ".join(result)


def match_gc_to_slug(pcs_name, rider_lookup):
    """Match a GC name ('LAST First') to a rider slug.

    PCS GC names are 'LASTNAME Firstname' (last in caps).
    Stage-1 rows store 'Lastname Firstname'.
    We normalize both to lowercase ASCII for matching.
    """
    # Reverse "LAST First" → "First Last" for matching
    parts = pcs_name.split()
    # The last-name portion is the leading run of all-uppercase words
    last_parts = []
    first_parts = []
    for p in parts:
        if p.isupper() or (len(p) > 1 and p[0].isupper() and p[1:].isupper()):
            last_parts.append(p)
        else:
            first_parts.append(p)
    # "First Last" form
    first_last = " ".join(first_parts + last_parts)
    # Also try "Last First" as stored in stage data
    last_first = " ".join(last_parts + first_parts)

    norm_fl = normalize(first_last)
    norm_lf = normalize(last_first)
    norm_orig = normalize(pcs_name)

    for slug, meta in rider_lookup.items():
        n = normalize(meta["name"])
        if n in (norm_fl, norm_lf, norm_orig):
            return slug, meta
    return None, None


def gap_str_to_seconds(gap_str):
    """'2:15' → 135, '1:01:39' → 3699, '+0:00' → 0."""
    s = gap_str.lstrip("+")
    parts = [int(p) for p in s.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


# PCS GT GC points scale (rank 1..51+)
GC_PCS_POINTS = [
    400, 290, 240, 220, 200, 190, 180, 170, 160, 150,
    140, 130, 120, 110, 100,  90,  85,  80,  75,  70,
     65,  60,  55,  50,  45,  40,  35,  30,  25,  20,
     20,  20,  20,  20,  20,  20,  20,  20,  20,  20,
     20,  20,  20,  20,  20,  20,  20,  20,  20,  20,
     20,
]


def build_final_stage_rows(rider_lookup):
    """Build 51 stage rows for the final stage from GC_FINAL data."""
    rows = []
    unmatched = []

    for gc_rank, pcs_name, team_name, gap_str in GC_FINAL:
        slug, meta = match_gc_to_slug(pcs_name, rider_lookup)

        if slug is None:
            # Try the startlist bib as last resort
            unmatched.append((gc_rank, pcs_name))
            # Build minimal row with empty slug (will be skipped by ingest)
            display_name = pcs_name_to_display(pcs_name)
            bib = str(STARTLIST_BIBS.get(pcs_name, ""))
            row = [
                str(gc_rank), str(gc_rank), gap_str,
                bib, "", display_name, "", "",
                team_name, "", "", str(GC_PCS_POINTS[gc_rank - 1] if gc_rank <= len(GC_PCS_POINTS) else 0),
                "", "", gap_str,
            ]
            rows.append(row)
            continue

        bib = str(STARTLIST_BIBS.get(pcs_name, meta["bib"]))
        pcs_pts = str(GC_PCS_POINTS[gc_rank - 1] if gc_rank <= len(GC_PCS_POINTS) else 0)

        row = [
            str(gc_rank),          # rnk (stage rank = GC rank, proxy)
            str(gc_rank),          # gc_pos
            gap_str,               # gc_lag
            bib,                   # bib
            meta["age"],           # age
            meta["name"],          # name (First Last as in existing data)
            slug,                  # slug
            meta["nat"],           # nat
            meta["team"],          # team
            meta["team_slug"],     # team_slug
            "",                    # uci_pts
            pcs_pts,               # pcs_pts
            "",                    # bonus
            "",                    # abs_time (unknown stage-specific time)
            gap_str if gc_rank > 1 else "+0:00",  # gap (using GC gap as proxy)
        ]
        rows.append(row)

    if unmatched:
        print(f"  WARNING: could not match {len(unmatched)} riders to slugs:")
        for r, n in unmatched:
            print(f"    GC#{r}: {n}")
    return rows


def fix_gc_standings(old_path):
    """Shift stage keys 18→17, 19→18, 20→19 and populate stage 19 with
    full 51-rider GC final data."""
    with open(old_path, encoding="utf-8") as f:
        gs = json.load(f)

    stages = gs.get("stages", {})
    new_stages = {}

    for key, riders in stages.items():
        k = int(key)
        if k <= 16:
            new_stages[str(k)] = riders
        elif k == 18:
            new_stages["17"] = riders
        elif k == 19:
            new_stages["18"] = riders
        elif k == 20:
            pass  # will be replaced by full GC data below
        # key 17 (old, ITT in wrong position) is dropped

    # Build stage 19 GC from GC_FINAL (the authoritative full-field data)
    stage19_gc = {}
    for gc_rank, pcs_name, _, gap_str in GC_FINAL:
        # We need the slug — try to match against existing stage data
        stage1_path = os.path.join(SCRAPES, "stage_1.json")
        d = json.load(open(stage1_path, encoding="utf-8"))
        rl = {}
        for row in d["rows"]:
            if len(row) >= 7 and row[6]:
                rl[row[6]] = row[5]

        gap_secs = gap_str_to_seconds(gap_str)
        # We'll populate this from match results below
        stage19_gc[pcs_name] = [gc_rank, gap_secs]  # temp key

    # Now replace temp keys with actual slugs
    rider_lookup = build_rider_lookup()
    stage19_by_slug = {}
    for gc_rank, pcs_name, _, gap_str in GC_FINAL:
        slug, _ = match_gc_to_slug(pcs_name, rider_lookup)
        if slug:
            stage19_by_slug[slug] = [gc_rank, gap_str_to_seconds(gap_str)]
    new_stages["19"] = stage19_by_slug

    gs["stages"] = new_stages
    with open(old_path, "w", encoding="utf-8") as f:
        json.dump(gs, f, ensure_ascii=False)
    print(f"  Updated gc_standings.json: shifted keys, stage 19 now has {len(stage19_by_slug)} riders")


def main():
    print("=== Fix 1968 Vuelta stage ordering and final stage results ===")

    # -----------------------------------------------------------------------
    # Step 1: Backup
    # -----------------------------------------------------------------------
    backup_dir = os.path.join(SCRAPES, "_backup_fix_1968")
    os.makedirs(backup_dir, exist_ok=True)
    for n in [17, 18, 19, 20]:
        src = os.path.join(SCRAPES, f"stage_{n}.json")
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup_dir, f"stage_{n}.json"))
    gc_path = os.path.join(SCRAPES, "gc_standings.json")
    if os.path.exists(gc_path):
        shutil.copy2(gc_path, os.path.join(backup_dir, "gc_standings.json"))
    print(f"  Backed up to {backup_dir}")

    # -----------------------------------------------------------------------
    # Step 2: Build rider lookup (from stage_1.json which has all 90 riders)
    # -----------------------------------------------------------------------
    rider_lookup = build_rider_lookup()
    print(f"  Built rider lookup: {len(rider_lookup)} riders from stage_1.json")

    # -----------------------------------------------------------------------
    # Step 3: Build the new stage_19.json rows (51 GC finishers)
    # -----------------------------------------------------------------------
    final_rows = build_final_stage_rows(rider_lookup)
    print(f"  Built {len(final_rows)} rows for new stage_19.json (final stage)")

    # Load the base stage info from stage_20.json (Tolosa-Bilbao)
    stage20_path = os.path.join(SCRAPES, "stage_20.json")
    with open(stage20_path, encoding="utf-8") as f:
        stage20 = json.load(f)

    # -----------------------------------------------------------------------
    # Step 4: Rotate files
    #   stage_18.json → stage_17.json (Pamplona-San Sebastián, n=17)
    #   stage_19.json → stage_18.json (ITT, n=18)
    #   new content   → stage_19.json (Final Tolosa-Bilbao, n=19)
    #   stage_20.json → DELETE
    # -----------------------------------------------------------------------
    p17 = os.path.join(SCRAPES, "stage_17.json")
    p18 = os.path.join(SCRAPES, "stage_18.json")
    p19 = os.path.join(SCRAPES, "stage_19.json")
    p20 = os.path.join(SCRAPES, "stage_20.json")

    with open(p18, encoding="utf-8") as f:
        d18 = json.load(f)
    with open(p19, encoding="utf-8") as f:
        d19 = json.load(f)

    # New stage_17 = old stage_18 (Pamplona-San Sebastián), n=17
    d18["n"] = 17
    with open(p17, "w", encoding="utf-8") as f:
        json.dump(d18, f, ensure_ascii=False)
    print("  Wrote stage_17.json (Pamplona-San Sebastián, PCS stage-16)")

    # New stage_18 = old stage_19 (ITT), n=18
    d19["n"] = 18
    with open(p18, "w", encoding="utf-8") as f:
        json.dump(d19, f, ensure_ascii=False)
    print("  Wrote stage_18.json (ITT San Sebastián-Tolosa, PCS stage-17)")

    # New stage_19 = Final Tolosa-Bilbao with 51 GC finishers, n=19
    new_stage19 = {
        "n": 19,
        "info": stage20["info"],
        "profile_icon": stage20.get("profile_icon", "p1"),
        "rows": final_rows,
        "sprint_points": stage20.get("sprint_points", []),
        "kom_points": stage20.get("kom_points", []),
    }
    with open(p19, "w", encoding="utf-8") as f:
        json.dump(new_stage19, f, ensure_ascii=False)
    print(f"  Wrote stage_19.json (Final Tolosa-Bilbao, {len(final_rows)} riders)")

    # Delete stage_20.json
    if os.path.exists(p20):
        os.remove(p20)
        print("  Deleted stage_20.json")

    # -----------------------------------------------------------------------
    # Step 5: Update gc_standings.json
    # -----------------------------------------------------------------------
    if os.path.exists(gc_path):
        fix_gc_standings(gc_path)

    # -----------------------------------------------------------------------
    # Step 6: Re-ingest 1968
    # -----------------------------------------------------------------------
    print("\n  Re-ingesting 1968 Vuelta...")
    ingest = os.path.join(HERE, "ingest_race.py")
    result = subprocess.run(
        [sys.executable, ingest, "--race", "vuelta", "1968"],
        cwd=HERE, capture_output=True, text=True,
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:2000])
    if result.returncode != 0:
        print("ERROR: ingest failed")
        return 1

    # -----------------------------------------------------------------------
    # Step 7: Insert the cancelled Stage 15 (Vitoria→Pamplona, 1968-05-09).
    #
    # PCS has this stage (their "Stage 15") but it was never scraped because
    # it produced no results. Re-ingest creates stages 1–19 from the 19 scrape
    # files; we shift stages 17–19 up by one and insert the cancelled stage at
    # position 17 so the race's own stage numbering (1a, 1b, 2, 3a, 3b, 4–18)
    # is preserved correctly in the DB and in exported JSON labels.
    # -----------------------------------------------------------------------
    print("\n  Inserting cancelled stage 15 (Vitoria→Pamplona)...")
    import sqlite3 as _sqlite3
    db_path = os.path.join(HERE, "cycling.db")
    conn2 = _sqlite3.connect(db_path)
    conn2.row_factory = _sqlite3.Row
    cur2 = conn2.cursor()
    eid = cur2.execute(
        "SELECT edition_id FROM race_editions re"
        " JOIN races r ON r.race_id = re.race_id"
        " WHERE r.name LIKE '%Vuelta%' AND re.year = 1968"
    ).fetchone()["edition_id"]
    # Shift in descending order to avoid UNIQUE constraint conflicts
    cur2.execute("UPDATE stages SET stage_number=20 WHERE edition_id=? AND stage_number=19", (eid,))
    cur2.execute("UPDATE stages SET stage_number=19 WHERE edition_id=? AND stage_number=18", (eid,))
    cur2.execute("UPDATE stages SET stage_number=18 WHERE edition_id=? AND stage_number=17", (eid,))
    cur2.execute(
        """INSERT INTO stages
           (edition_id, stage_number, stage_date, start_location, finish_location,
            distance_km, stage_type, route_type, cancelled)
           VALUES (?, 17, '1968-05-09', 'Vitoria', 'Pamplona', 0, 'road', 'F', 1)""",
        (eid,),
    )
    conn2.commit()
    conn2.close()
    print("  Inserted cancelled stage at position 17 (stages 17–19 shifted to 18–20)")

    print("\n=== Done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
