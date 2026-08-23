#!/usr/bin/env python3
"""
Additive script: inserts pre-1960 Tour de France editions (1939, 1947–1959)
into the existing cycling.db without rebuilding it from scratch.

Reads tdf_YEAR_full.json files (produced by scrape_pcs_stages.py) and
profile_icons.json for route_type classification.

Replicates the stage/result insertion logic from build_db.py, with additions:
  - Sets route_type from profile_icons.json (p1→F, p2→H, p3→H, p4→M, p5→M)
  - Overrides TT/TTT from Won how field
  - Uses the same carry-forward GC gap logic

Usage:
  python3 add_pre1960.py              # all target years
  python3 add_pre1960.py 1953 1959   # specific years
  python3 add_pre1960.py --dry-run   # show what would be inserted
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime

from race_common import (
    SOURCE_DERIVED,
    SOURCE_PCS,
    StageRow,
    fix_mojibake,
    record_provenance,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(HERE, "cycling.db")
ICONS_PATH  = os.path.join(HERE, "profile_icons.json")

TARGET_YEARS = [1939] + list(range(1947, 1960))

DRY_RUN = "--dry-run" in sys.argv
YEAR_ARGS = [int(a) for a in sys.argv[1:] if a.isdigit()]

ICON_TO_ROUTE = {"p1": "F", "p2": "H", "p3": "H", "p4": "M", "p5": "M"}

COUNTRY_NAMES = {
    "fr": "France", "nl": "Netherlands", "be": "Belgium", "si": "Slovenia",
    "es": "Spain", "dk": "Denmark", "it": "Italy", "gb": "Great Britain",
    "co": "Colombia", "au": "Australia", "ca": "Canada", "us": "United States",
    "no": "Norway", "za": "South Africa", "pt": "Portugal", "lv": "Latvia",
    "ru": "Russia", "pl": "Poland", "ec": "Ecuador", "de": "Germany",
    "lu": "Luxembourg", "ch": "Switzerland", "kz": "Kazakhstan", "ie": "Ireland",
    "at": "Austria", "cz": "Czech Republic", "er": "Eritrea",
    "mc": "Monaco",
    # Previously missing — silently dropped to null nationality for any rider
    # with one of these codes (e.g. "cn" -> Cheng Ji, 2014) until this fix.
    "ar": "Argentina", "br": "Brazil", "by": "Belarus", "cn": "China",
    "cr": "Costa Rica", "dz": "Algeria", "ee": "Estonia", "et": "Ethiopia",
    "fi": "Finland", "hr": "Croatia", "hu": "Hungary", "il": "Israel",
    "jp": "Japan", "li": "Liechtenstein", "lt": "Lithuania", "ma": "Morocco",
    "md": "Moldova", "mx": "Mexico", "nz": "New Zealand", "ro": "Romania",
    "se": "Sweden", "sk": "Slovakia", "su": "Soviet Union", "tn": "Tunisia",
    "ua": "Ukraine", "uz": "Uzbekistan", "ve": "Venezuela", "yu": "Yugoslavia",
}


def ordinal(n):
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


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
    m = re.match(r"^(-?\d+)", str(text).strip())
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


def load_edition_data(year: int):
    path = os.path.join(HERE, f"tdf_{year}_full.json")
    if not os.path.exists(path):
        return None, None
    with open(path, encoding="utf-8") as f:
        bundle = json.load(f)
    stages = [
        (s["n"], s.get("info", {}), s.get("rows", []))
        for s in bundle.get("stages", [])
        if not s.get("error")
    ]
    stages.sort(key=lambda t: t[0])
    return stages, bundle.get("classifications", {})


def insert_edition(conn, race_id, year, icons_for_year, countries_seen, riders_seen, teams_seen, dry_run=False):
    stages_data, classifications = load_edition_data(year)
    if not stages_data:
        print(f"  No data file for {year}, skipping")
        return 0, 0
    # The scrape file is the honest source_ref: these rows come from it, not
    # from a live fetch. scrape_pcs_stages.py wrote it from PCS.
    ref = f"tdf_{year}_full.json"

    cur = conn.cursor()

    # Check if edition already exists (filter by race_id to avoid matching Giro/Vuelta same year)
    existing = cur.execute("SELECT edition_id FROM race_editions WHERE race_id=? AND year=?", (race_id, year)).fetchone()
    if existing:
        print(f"  {year}: already in DB (edition_id={existing[0]}), skipping")
        return 0, 0

    edition_name = f"{ordinal(year - 1913)} Tour de France"
    print(f"  {year}: inserting {len(stages_data)} stages...")

    if dry_run:
        print(f"    [DRY RUN] would insert edition '{edition_name}'")
        return 0, 0

    cur.execute(
        "INSERT INTO race_editions (race_id, year, edition_name, uci_classification) VALUES (?,?,?,?)",
        (race_id, year, edition_name, None),
    )
    edition_id = cur.lastrowid

    last_known_gc = {}
    total_results = total_incidents = 0

    for stage_idx, (n, info, rows) in enumerate(stages_data):
        # Stage date
        date_iso = None
        if info.get("Date"):
            try:
                date_iso = datetime.strptime(info["Date"], "%d %B %Y").strftime("%Y-%m-%d")
            except ValueError:
                date_iso = info.get("Date")

        # Distance
        distance_km = None
        if info.get("Distance"):
            m = re.match(r"([\d.]+)", info["Distance"])
            if m:
                distance_km = float(m.group(1))

        # Vertical meters
        vertical_meters = parse_int(info.get("Vertical meters"))
        profile_score   = parse_int(info.get("ProfileScore"))
        won_how = info.get("Won how", "")

        # Route type from profile_icons.json
        icon = icons_for_year[stage_idx] if stage_idx < len(icons_for_year) else "p1"
        route_type = detect_route_type(icon, won_how)

        avg_speed = None
        if info.get("Avg. speed winner"):
            m = re.match(r"([\d.]+)", info["Avg. speed winner"])
            if m:
                avg_speed = float(m.group(1))

        cur.execute(
            """INSERT INTO stages
               (edition_id, stage_number, stage_label, stage_date, start_time,
                start_location, finish_location, distance_km, stage_type,
                profile_score, vertical_meters, avg_speed_winner_kmh,
                avg_temperature_c, won_how, race_ranking, startlist_quality_score,
                timelimit_text, route_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                edition_id, n, f"Stage {n}", date_iso, info.get("Start time"),
                info.get("Departure"), info.get("Arrival"), distance_km,
                "itt" if route_type in ("TT", "TTT") else "road",
                profile_score, vertical_meters, avg_speed,
                None, won_how, None, None, None, route_type,
            ),
        )
        stage_id = cur.lastrowid

        winner_seconds = None

        for row in rows:
            if len(row) < 15:
                continue
            sr = StageRow.from_list(row)
            rnk, gc_pos, gc_lag = sr.rnk, sr.gc_pos, sr.gc_lag
            bib, age = sr.bib, sr.age
            rider_name, rider_slug, nat = sr.name, sr.slug, sr.nat
            team_name, team_slug = sr.team, sr.team_slug
            uci_pts, pcs_pts = sr.uci_pts, sr.pcs_pts
            bonus_txt, abs_time_txt, gap_txt = sr.bonus, sr.abs_time, sr.gap

            if not rider_slug:
                desc = rider_name or rnk or ""
                if desc:
                    cur.execute(
                        "INSERT INTO stage_incidents (stage_id, description) VALUES (?,?)",
                        (stage_id, desc),
                    )
                    total_incidents += 1
                continue

            # Carry-forward GC position
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
                countries_seen[nat] = COUNTRY_NAMES.get(nat)
                cur.execute(
                    "INSERT OR IGNORE INTO countries (code, name) VALUES (?,?)",
                    (nat, COUNTRY_NAMES.get(nat)),
                )

            # Riders
            if rider_slug not in riders_seen:
                riders_seen[rider_slug] = rider_name
                cur.execute(
                    "INSERT OR IGNORE INTO riders (rider_id, full_name, nationality_code) VALUES (?,?,?)",
                    (rider_slug, fix_mojibake(rider_name), nat),
                )
                # OR IGNORE: only claim provenance for a row we actually wrote.
                if cur.rowcount:
                    record_provenance(cur, "riders", rider_slug, "full_name",
                                      SOURCE_PCS, source_ref=ref)
                    record_provenance(cur, "riders", rider_slug, "nationality_code",
                                      SOURCE_PCS, source_ref=ref)

            # Teams
            if team_slug and team_slug not in teams_seen:
                teams_seen[team_slug] = team_name
                m = re.search(r"-(\d{4})$", team_slug)
                season_year = int(m.group(1)) if m else None
                cur.execute(
                    "INSERT OR IGNORE INTO teams (team_id, name, season_year) VALUES (?,?,?)",
                    (team_slug, fix_mojibake(team_name), season_year),
                )
                if cur.rowcount:
                    record_provenance(cur, "teams", team_slug, "name",
                                      SOURCE_PCS, source_ref=ref)
                    record_provenance(cur, "teams", team_slug, "season_year",
                                      SOURCE_DERIVED,
                                      source_ref="trailing year of the PCS team slug")

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

            bonus_secs  = parse_bonus_seconds(bonus_txt)
            stage_rank  = parse_int(rnk) if status == "FINISHED" else None
            gc_rank     = parse_int(gc_pos)
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
                    None, parse_int(pcs_pts),
                    gc_rank, gc_gap_secs,
                    parse_int(age),
                ),
            )
            total_results += 1

    print(f"    {total_results} stage results, {total_incidents} incidents")
    return total_results, total_incidents


def main():
    years = YEAR_ARGS if YEAR_ARGS else TARGET_YEARS

    # Load profile_icons
    if os.path.exists(ICONS_PATH):
        with open(ICONS_PATH, encoding="utf-8") as f:
            all_icons = json.load(f)
    else:
        print("Warning: profile_icons.json not found, route_type will default to F")
        all_icons = {}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Get race_id for Tour de France
    race_row = conn.execute("SELECT race_id FROM races WHERE name = 'Tour de France'").fetchone()
    if not race_row:
        print("ERROR: 'Tour de France' not found in races table. Is cycling.db built?")
        conn.close()
        return
    race_id = race_row["race_id"]
    print(f"Tour de France race_id={race_id}")

    # Preload existing riders/teams/countries to avoid duplicate inserts
    countries_seen = {r["code"]: r["name"] for r in conn.execute("SELECT code, name FROM countries")}
    riders_seen    = {r["rider_id"]: r["full_name"] for r in conn.execute("SELECT rider_id, full_name FROM riders")}
    teams_seen     = {r["team_id"]: r["name"] for r in conn.execute("SELECT team_id, name FROM teams")}

    total_results = total_incidents = 0

    for year in years:
        icons_for_year = all_icons.get(str(year), [])
        r, i = insert_edition(
            conn, race_id, year, icons_for_year,
            countries_seen, riders_seen, teams_seen,
            dry_run=DRY_RUN,
        )
        total_results   += r
        total_incidents += i

    if not DRY_RUN:
        conn.commit()
        print(f"\nTotal: {total_results} stage results, {total_incidents} incidents")
        print(f"DB: {DB_PATH}")
    else:
        print(f"\n[DRY RUN] no changes written")

    conn.close()


if __name__ == "__main__":
    main()
