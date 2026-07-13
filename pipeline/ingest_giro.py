#!/usr/bin/env python3
"""
Ingest scraped Giro d'Italia stage data into cycling.db.

Reads JSON files from pipeline/giro_scrapes/YEAR/stage_N.json (or flat
giro_scrapes/stage_N.json for legacy 2026 data) and inserts into the
existing multi-race schema.

Usage:
  python3 ingest_giro.py                    # all years with stage files
  python3 ingest_giro.py 1990 1991 1992     # specific years only
  python3 ingest_giro.py 1990-2000          # year range
  python3 ingest_giro.py --dry-run          # show what would be inserted
"""

import json
import os
import re
import sqlite3
import sys
from glob import glob

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
SCRAPES_DIR = os.path.join(HERE, "giro_scrapes")

DRY_RUN = "--dry-run" in sys.argv

ICON_TO_ROUTE = {"p1": "F", "p2": "H", "p3": "H", "p4": "M", "p5": "M"}

COUNTRY_NAMES = {
    "fr": "France", "nl": "Netherlands", "be": "Belgium", "si": "Slovenia",
    "es": "Spain", "dk": "Denmark", "it": "Italy", "gb": "Great Britain",
    "co": "Colombia", "au": "Australia", "ca": "Canada", "us": "United States",
    "no": "Norway", "za": "South Africa", "pt": "Portugal", "lv": "Latvia",
    "ru": "Russia", "pl": "Poland", "ec": "Ecuador", "de": "Germany",
    "lu": "Luxembourg", "ch": "Switzerland", "kz": "Kazakhstan", "ie": "Ireland",
    "at": "Austria", "cz": "Czech Republic", "er": "Eritrea", "mc": "Monaco",
    "ar": "Argentina", "br": "Brazil", "by": "Belarus", "cn": "China",
    "cr": "Costa Rica", "dz": "Algeria", "ee": "Estonia", "et": "Ethiopia",
    "fi": "Finland", "hr": "Croatia", "hu": "Hungary", "il": "Israel",
    "jp": "Japan", "li": "Liechtenstein", "lt": "Lithuania", "ma": "Morocco",
    "md": "Moldova", "mx": "Mexico", "nz": "New Zealand", "ro": "Romania",
    "se": "Sweden", "sk": "Slovakia", "tn": "Tunisia", "ua": "Ukraine",
    "uz": "Uzbekistan", "ve": "Venezuela", "cl": "Chile", "uy": "Uruguay",
    "bg": "Bulgaria", "mt": "Malta",
}


def parse_time_to_seconds(text):
    if not text:
        return None
    t = text.strip().lstrip("+").lstrip("*")
    if t in ("", ",,", ",", "-"):
        return None
    if not re.match(r"^\d+:\d{2}(:\d{2})?$", t):
        return None
    parts = [int(p) for p in t.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def parse_bonus_seconds(text):
    if not text:
        return 0
    m = re.match(r"^(-?\d+)", str(text).strip().replace("″", "").replace("″", ""))
    return int(m.group(1)) if m else 0


def parse_int(text):
    if text is None:
        return None
    t = str(text).strip()
    return int(t) if re.match(r"^-?\d+$", t) else None


def detect_route_type(icon: str, won_how: str) -> str:
    wh = (won_how or "").lower()
    if "team time trial" in wh or "ttt" in wh:
        return "TTT"
    if "time trial" in wh:
        return "TT"
    return ICON_TO_ROUTE.get(icon or "p1", "F")


def parse_year_args(args: list[str]) -> list[int]:
    years = []
    for a in args:
        if a.startswith("-"):
            continue
        if "-" in a and not a.startswith("-"):
            parts = a.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                years.extend(range(int(parts[0]), int(parts[1]) + 1))
                continue
        if a.isdigit():
            years.append(int(a))
    return sorted(set(years))


def find_stage_files_for_year(year: int) -> list[str]:
    """Find stage files for a year, checking year subdir first, then flat layout for 2026."""
    year_dir = os.path.join(SCRAPES_DIR, str(year))
    files = sorted(glob(os.path.join(year_dir, "stage_*.json")))
    if files:
        return files
    if year == 2026:
        return sorted(glob(os.path.join(SCRAPES_DIR, "stage_*.json")))
    return []


def discover_years() -> list[int]:
    """Find all years that have scraped stage files."""
    years = set()
    for entry in os.listdir(SCRAPES_DIR):
        if entry.isdigit() and os.path.isdir(os.path.join(SCRAPES_DIR, entry)):
            files = glob(os.path.join(SCRAPES_DIR, entry, "stage_*.json"))
            if files:
                years.add(int(entry))
    if glob(os.path.join(SCRAPES_DIR, "stage_*.json")):
        years.add(2026)
    return sorted(years)


def ingest_year(conn, race_id: int, year: int, stage_files: list[str]) -> int:
    """Ingest one year's stage files. Returns total results inserted."""
    cur = conn.cursor()

    # Check if edition already exists
    existing = cur.execute(
        "SELECT edition_id FROM race_editions WHERE race_id=? AND year=?",
        (race_id, year),
    ).fetchone()
    if existing:
        eid = existing[0]
        cur.execute("DELETE FROM stage_results WHERE stage_id IN (SELECT stage_id FROM stages WHERE edition_id=?)", (eid,))
        cur.execute("DELETE FROM stages WHERE edition_id=?", (eid,))
        cur.execute("DELETE FROM race_editions WHERE edition_id=?", (eid,))
        conn.commit()

    if DRY_RUN:
        print(f"  [DRY RUN] Would insert {year} Giro d'Italia with {len(stage_files)} stages")
        return 0

    cur.execute(
        "INSERT INTO race_editions (race_id, year, edition_name) VALUES (?,?,?)",
        (race_id, year, f"{year} Giro d'Italia"),
    )
    edition_id = cur.lastrowid

    # Preload existing entities
    countries_seen = {r["code"] for r in cur.execute("SELECT code FROM countries")}
    riders_seen = {r["rider_id"] for r in cur.execute("SELECT rider_id FROM riders")}
    teams_seen = {r["team_id"] for r in cur.execute("SELECT team_id FROM teams")}

    last_known_gc = {}
    total_results = 0

    for sf in stage_files:
        with open(sf, encoding="utf-8") as f:
            stage_data = json.load(f)

        n = stage_data["n"]
        info = stage_data.get("info", {})
        rows = stage_data.get("rows", [])
        profile_icon = stage_data.get("profile_icon", "p1")

        # Parse stage metadata
        date_iso = None
        if info.get("Date"):
            try:
                from datetime import datetime
                date_iso = datetime.strptime(info["Date"], "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                date_iso = info.get("Date")

        distance_km = None
        if info.get("Distance"):
            m = re.match(r"([\d.]+)", info["Distance"])
            if m:
                distance_km = float(m.group(1))

        won_how = info.get("Won how", "")
        route_type = detect_route_type(profile_icon, won_how)

        cur.execute(
            """INSERT INTO stages
               (edition_id, stage_number, stage_label, stage_date,
                start_location, finish_location, distance_km, stage_type,
                profile_score, route_type, won_how)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                edition_id, n, f"Stage {n}", date_iso,
                info.get("Start"), info.get("Finish"), distance_km,
                "itt" if route_type in ("TT", "TTT") else "road",
                None, route_type, won_how,
            ),
        )
        stage_id = cur.lastrowid

        winner_seconds = None

        for row in rows:
            if len(row) < 15:
                continue
            (rnk, gc_pos, gc_lag, bib, age, rider_name, rider_slug, nat,
             team_name, team_slug, uci_pts, pcs_pts, bonus_txt, abs_time_txt, gap_txt) = row

            if not rider_slug:
                continue

            # Carry-forward GC position for riders not shown on this stage's GC
            if not gc_pos:
                carried = last_known_gc.get(rider_slug)
                if carried:
                    gc_pos, gc_lag = carried
                elif n == 1:
                    stage_rank_fallback = parse_int(rnk)
                    if stage_rank_fallback is not None:
                        gc_pos = str(stage_rank_fallback)
                        gc_lag = gap_txt
            if gc_pos:
                last_known_gc[rider_slug] = (gc_pos, gc_lag)

            # Countries
            if nat and nat not in countries_seen:
                countries_seen.add(nat)
                cur.execute(
                    "INSERT OR IGNORE INTO countries (code, name) VALUES (?,?)",
                    (nat, COUNTRY_NAMES.get(nat)),
                )

            # Riders
            if rider_slug not in riders_seen:
                riders_seen.add(rider_slug)
                cur.execute(
                    "INSERT OR IGNORE INTO riders (rider_id, full_name, nationality_code) VALUES (?,?,?)",
                    (rider_slug, rider_name, nat),
                )

            # Teams
            if team_slug and team_slug not in teams_seen:
                teams_seen.add(team_slug)
                m = re.search(r"-(\d{4})$", team_slug)
                season_year = int(m.group(1)) if m else None
                cur.execute(
                    "INSERT OR IGNORE INTO teams (team_id, name, season_year) VALUES (?,?,?)",
                    (team_slug, team_name, season_year),
                )

            # Status
            status = "FINISHED"
            if rnk in ("DNF", "DNS", "OTL", "NP", "DSQ", "DEL", "DF"):
                status = {"DNF": "DNF", "DNS": "DNS", "OTL": "OTL",
                          "NP": "NP", "DSQ": "DSQ", "DEL": "DEL", "DF": "DNF"}.get(rnk, "DNF")

            # Times
            abs_secs = parse_time_to_seconds(abs_time_txt)
            gap_secs = parse_time_to_seconds(gap_txt)

            if status == "FINISHED" and abs_secs is not None and rnk == "1":
                winner_seconds = abs_secs

            finish_secs = None
            if status == "FINISHED" and winner_seconds is not None:
                if gap_secs is not None:
                    finish_secs = winner_seconds + gap_secs
                elif parse_int(rnk) == 1:
                    finish_secs = winner_seconds

            bonus_secs = parse_bonus_seconds(bonus_txt)
            stage_rank = parse_int(rnk) if status == "FINISHED" else None
            gc_rank = parse_int(gc_pos)
            gc_gap_secs = parse_time_to_seconds(gc_lag)

            cur.execute(
                """INSERT OR IGNORE INTO stage_results
                   (stage_id, rider_id, team_id, bib_number, stage_rank, status,
                    finish_time_seconds, gap_seconds, bonus_seconds, penalty_seconds,
                    uci_points, pcs_points, gc_rank, gc_gap_seconds, age_at_race)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    stage_id, rider_slug,
                    team_slug if team_slug else None,
                    parse_int(bib), stage_rank, status,
                    finish_secs, gap_secs, bonus_secs, 0,
                    parse_int(uci_pts), parse_int(pcs_pts),
                    gc_rank, gc_gap_secs,
                    parse_int(age),
                ),
            )
            total_results += 1

        print(f"  Stage {n}: {len(rows)} rows inserted")

    conn.commit()
    return total_results


def main():
    args = sys.argv[1:]
    year_args = parse_year_args(args)
    years = year_args if year_args else discover_years()

    if not years:
        print("No stage files found in", SCRAPES_DIR)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    race_row = cur.execute("SELECT race_id FROM races WHERE name = ?", ("Giro d'Italia",)).fetchone()
    if not race_row:
        cur.execute(
            "INSERT INTO races (name, country, race_type) VALUES (?, ?, ?)",
            ("Giro d'Italia", "Italy", "stage_race"),
        )
        conn.commit()
        race_id = cur.execute("SELECT race_id FROM races WHERE name = ?", ("Giro d'Italia",)).fetchone()[0]
        print(f"Created race 'Giro d'Italia' (race_id={race_id})")
    else:
        race_id = race_row["race_id"]
        print(f"Using existing Giro d'Italia (race_id={race_id})")

    grand_total = 0
    for year in years:
        stage_files = find_stage_files_for_year(year)
        if not stage_files:
            print(f"{year}: no stage files found, skipping")
            continue
        print(f"\n{year}: {len(stage_files)} stage file(s)")
        total = ingest_year(conn, race_id, year, stage_files)
        grand_total += total
        if not DRY_RUN:
            print(f"  {year}: {total} results inserted")

    conn.close()
    print(f"\nDone: {grand_total} total stage results across {len(years)} year(s)")

    if not DRY_RUN:
        import importlib.util
        fix_path = os.path.join(HERE, "fix_giro_rider_names.py")
        spec = importlib.util.spec_from_file_location("fix_giro_rider_names", fix_path)
        fix_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fix_mod)
        print()
        fix_mod.main()


if __name__ == "__main__":
    main()
