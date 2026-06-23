#!/usr/bin/env python3
"""
Build a SQLite database of Tour de France results (multiple years) from the
raw per-stage JSON files scraped from procyclingstats.com
(tdf_{year}_stage_01.json ... tdf_{year}_stage_21.json) plus
tdf_{year}_classifications.json for each year.

Each raw row (per extractStage() in the browser scraper) has the shape:
[rnk, gcPos, gcTimeLag, bib, age, riderName, riderSlug, nationality,
 teamName, teamSlug, uciPoints, pcsPoints, bonusSeconds, stageAbsTime, stageGap]

Usage: python3 build_db.py
"""
import json
import re
import sqlite3
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = "/tmp/cycling.db"
SCHEMA_PATH = os.path.join(HERE, "schema.sql")


def ordinal(n):
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# Each Tour de France edition we have scraped raw JSON for. Edition number
# follows the real-world numbering (2024 = 111th), so year - 1913 = edition #.
EDITIONS = [(year, f"{ordinal(year - 1913)} Tour de France") for year in range(1995, 2026)]

COUNTRY_NAMES = {
    "fr": "France", "nl": "Netherlands", "be": "Belgium", "si": "Slovenia",
    "es": "Spain", "dk": "Denmark", "it": "Italy", "gb": "Great Britain",
    "co": "Colombia", "au": "Australia", "ca": "Canada", "us": "United States",
    "no": "Norway", "za": "South Africa", "pt": "Portugal", "lv": "Latvia",
    "ru": "Russia", "pl": "Poland", "ec": "Ecuador", "de": "Germany",
    "lu": "Luxembourg", "ch": "Switzerland", "kz": "Kazakhstan", "ie": "Ireland",
    "at": "Austria", "cz": "Czech Republic", "er": "Eritrea",
}


def parse_time_to_seconds(text):
    """Parse a clock-style time string like '5:07:22', '+0:00', '1:01:21'
    into total seconds. Returns None if not parseable (blank, ',,', etc.)."""
    if not text:
        return None
    t = text.strip().lstrip("+").lstrip("*")
    if t in ("", ",,", ",", "-"):
        return None
    if not re.match(r"^\d+:\d{2}(:\d{2})?$", t):
        return None
    parts = [int(p) for p in t.split(":")]
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    return None


def parse_bonus_seconds(text):
    """Parse a bonus/penalty marker like '10″', '-40″', '' into a signed int
    of seconds. Positive = bonus seconds awarded; negative = time penalty."""
    if not text:
        return 0
    t = text.strip()
    if not t:
        return 0
    m = re.match(r"^(-?\d+)", t)
    if not m:
        return 0
    return int(m.group(1))


def parse_int(text):
    if text is None:
        return None
    t = str(text).strip()
    if not t or not re.match(r"^-?\d+$", t):
        return None
    return int(t)


def clean_team_name(team_id, fallback_name):
    # team slugs look like 'team/uae-team-emirates-2024'
    return fallback_name.strip()


def season_year_from_team_id(team_id):
    m = re.search(r"-(\d{4})$", team_id or "")
    return int(m.group(1)) if m else None


def load_raw_data(year):
    """Load this year's raw scraped data, regardless of which of the two
    on-disk formats it's in:
      - combined: tdf_{year}_full.json -> {year, stages: [{n, info, rows}], classifications}
      - per-stage: tdf_{year}_stage_{NN}.json (x21) + tdf_{year}_classifications.json
    Returns (stages, classifications) where stages is a list of (n, info, rows)
    tuples sorted by stage number, and classifications is a dict of
    classification -> list of rows (possibly empty)."""
    combined_path = os.path.join(HERE, f"tdf_{year}_full.json")
    if os.path.exists(combined_path):
        with open(combined_path, encoding="utf-8") as f:
            bundle = json.load(f)
        stages = [
            (s["n"], s.get("info", {}), s.get("rows", []))
            for s in bundle.get("stages", [])
            if not s.get("error")
        ]
        stages.sort(key=lambda t: t[0])
        classifications = bundle.get("classifications", {})
        return stages, classifications

    stages = []
    for n in range(1, 30):
        path = os.path.join(HERE, f"tdf_{year}_stage_{n:02d}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        stages.append((n, data.get("info", {}), data.get("rows", [])))

    classifications = {}
    classifications_path = os.path.join(HERE, f"tdf_{year}_classifications.json")
    if os.path.exists(classifications_path):
        with open(classifications_path, encoding="utf-8") as f:
            classifications = json.load(f)

    return stages, classifications


def load_edition(cur, race_id, year, edition_name, countries_seen, riders_seen, teams_seen):
    """Load one year's worth of stage + classification data into the db.
    Returns (total_results, total_incidents, total_standings) for this edition."""
    total_results = 0
    total_incidents = 0
    total_standings = 0

    stages, classifications = load_raw_data(year)
    if not stages:
        return 0, 0, 0

    cur.execute(
        "INSERT INTO race_editions (race_id, year, edition_name, uci_classification) "
        "VALUES (?, ?, ?, ?)",
        (race_id, year, edition_name, None),
    )
    edition_id = cur.lastrowid

    # Some stages only publish "gc" (current GC rank) and "gc_timelag" for
    # riders whose rank changed that day (or, for genuinely neutralized/
    # protest stages, for nobody at all) -- leaving it blank for everyone
    # else. Since an unpublished value almost always means "unchanged from
    # the previous stage", carry the last known gc_pos/gc_lag forward per
    # rider across stages (in stage order) whenever a stage leaves it blank,
    # rather than leaving a gap in the GC-by-stage chart.
    last_known_gc = {}

    for n, info, rows in stages:
        if n == 1 and info.get("Classification"):
            cur.execute(
                "UPDATE race_editions SET uci_classification = ? WHERE edition_id = ?",
                (info.get("Classification"), edition_id),
            )

        # stage date: "29 June 2024" -> "2024-06-29"
        date_iso = None
        if info.get("Date"):
            try:
                date_iso = datetime.strptime(info["Date"], "%d %B %Y").strftime("%Y-%m-%d")
            except ValueError:
                date_iso = info.get("Date")

        distance_km = None
        if info.get("Distance"):
            m = re.match(r"([\d.]+)", info["Distance"])
            if m:
                distance_km = float(m.group(1))

        won_how = info.get("Won how", "")
        stage_type = "road"
        if won_how == "Time trial" or (distance_km and distance_km < 60):
            stage_type = "itt"

        avg_speed = None
        if info.get("Avg. speed winner"):
            m = re.match(r"([\d.]+)", info["Avg. speed winner"])
            if m:
                avg_speed = float(m.group(1))

        avg_temp = None
        if info.get("Avg. temperature"):
            m = re.match(r"(-?[\d.]+)", info["Avg. temperature"])
            if m:
                avg_temp = float(m.group(1))

        vertical_meters = parse_int(info.get("Vertical meters"))
        profile_score = parse_int(info.get("ProfileScore"))
        race_ranking = parse_int(info.get("Race ranking"))
        sq_score = None
        if info.get("Startlist quality score"):
            m = re.match(r"(\d+)", info["Startlist quality score"])
            if m:
                sq_score = int(m.group(1))

        cur.execute(
            """INSERT INTO stages
               (edition_id, stage_number, stage_label, stage_date, start_time,
                start_location, finish_location, distance_km, stage_type,
                profile_score, vertical_meters, avg_speed_winner_kmh,
                avg_temperature_c, won_how, race_ranking, startlist_quality_score,
                timelimit_text)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                edition_id, n, f"Stage {n}", date_iso, info.get("Start time"),
                info.get("Departure"), info.get("Arrival"), distance_km, stage_type,
                profile_score, vertical_meters, avg_speed,
                avg_temp, won_how, race_ranking, sq_score,
                info.get("Timelimit"),
            ),
        )
        stage_id = cur.lastrowid

        # winner's absolute stage time, to back-compute finish times for everyone else
        winner_seconds = None

        for row in rows:
            if len(row) < 15:
                continue
            (rnk, gc_pos, gc_lag, bib, age, rider_name, rider_slug, nat,
             team_name, team_slug, uci_pts, pcs_pts, bonus_txt, abs_time_txt, gap_txt) = row

            # Free-text incident rows (relegations/penalties) have no rider_slug
            if not rider_slug:
                desc = rider_name or rnk or ""
                if desc:
                    cur.execute(
                        "INSERT INTO stage_incidents (stage_id, description) VALUES (?, ?)",
                        (stage_id, desc),
                    )
                    total_incidents += 1
                continue

            if not gc_pos:
                carried = last_known_gc.get(rider_slug)
                if carried:
                    gc_pos, gc_lag = carried
                elif n == 1:
                    # No prior stage to carry forward from. On day 1, GC
                    # position closely tracks the stage finishing order
                    # (no accumulated time gaps yet), so fall back to the
                    # rider's stage rank when PCS didn't publish a GC rank.
                    stage_rank_fallback = parse_int(rnk)
                    if stage_rank_fallback is not None:
                        gc_pos = str(stage_rank_fallback)
                        gc_lag = gap_txt
            if gc_pos:
                last_known_gc[rider_slug] = (gc_pos, gc_lag)

            # countries
            if nat and nat not in countries_seen:
                countries_seen[nat] = COUNTRY_NAMES.get(nat)
                cur.execute(
                    "INSERT OR IGNORE INTO countries (code, name) VALUES (?, ?)",
                    (nat, COUNTRY_NAMES.get(nat)),
                )

            # riders
            if rider_slug not in riders_seen:
                riders_seen[rider_slug] = rider_name
                cur.execute(
                    "INSERT OR IGNORE INTO riders (rider_id, full_name, nationality_code) "
                    "VALUES (?, ?, ?)",
                    (rider_slug, rider_name, nat),
                )

            # teams
            if team_slug and team_slug not in teams_seen:
                teams_seen[team_slug] = team_name
                cur.execute(
                    "INSERT OR IGNORE INTO teams (team_id, name, season_year) VALUES (?, ?, ?)",
                    (team_slug, clean_team_name(team_slug, team_name), season_year_from_team_id(team_slug)),
                )

            status = "FINISHED"
            stage_rank = parse_int(rnk)
            if rnk == "DNF":
                status, stage_rank = "DNF", None
            elif rnk == "DNS":
                status, stage_rank = "DNS", None
            elif rnk == "OTL":
                status, stage_rank = "OTL", None

            bonus_seconds = parse_bonus_seconds(bonus_txt)
            penalty_seconds = -bonus_seconds if bonus_seconds < 0 else 0
            if bonus_seconds < 0:
                bonus_seconds = 0

            gap_seconds = parse_time_to_seconds(gap_txt)

            if stage_rank == 1 and status == "FINISHED":
                winner_seconds = parse_time_to_seconds(abs_time_txt)

            finish_time_seconds = None
            if status == "FINISHED" and winner_seconds is not None:
                if gap_seconds is not None:
                    finish_time_seconds = winner_seconds + gap_seconds
                elif stage_rank == 1:
                    finish_time_seconds = winner_seconds

            cur.execute(
                """INSERT OR IGNORE INTO stage_results
                   (stage_id, rider_id, team_id, bib_number, stage_rank, status,
                    finish_time_seconds, gap_seconds, bonus_seconds, penalty_seconds,
                    uci_points, pcs_points, gc_rank, gc_gap_seconds, age_at_race)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    stage_id, rider_slug, team_slug, parse_int(bib), stage_rank, status,
                    finish_time_seconds, gap_seconds, bonus_seconds, penalty_seconds,
                    parse_int(uci_pts), parse_int(pcs_pts), parse_int(gc_pos),
                    parse_time_to_seconds(gc_lag), parse_int(age),
                ),
            )
            total_results += 1

    # Close internal gaps: a handful of riders are simply absent from a
    # single stage's published results on the source site itself (verified
    # against the live page -- not a scraping bug), while clearly still in
    # the race since they have results on the stages right before and
    # after. Carry their last-known GC standing across the gap so the
    # chart doesn't show a break for a day they were actually still riding.
    cur.execute(
        """SELECT sr.rider_id, st.stage_number
           FROM stage_results sr JOIN stages st ON st.stage_id = sr.stage_id
           WHERE st.edition_id = ? ORDER BY sr.rider_id, st.stage_number""",
        (edition_id,),
    )
    by_rider = {}
    for rider_id, stage_number in cur.fetchall():
        by_rider.setdefault(rider_id, []).append(stage_number)

    stage_id_by_number = {}
    cur.execute("SELECT stage_id, stage_number FROM stages WHERE edition_id = ?", (edition_id,))
    for stage_id_row, stage_number_row in cur.fetchall():
        stage_id_by_number[stage_number_row] = stage_id_row

    gaps_closed = 0
    for rider_id, present in by_rider.items():
        present_set = set(present)
        lo, hi = min(present), max(present)
        for n in range(lo + 1, hi):
            if n in present_set:
                continue
            prev_n = max(p for p in present if p < n)
            cur.execute(
                """SELECT team_id, bib_number, gc_rank, gc_gap_seconds, age_at_race
                   FROM stage_results WHERE rider_id = ? AND stage_id = ?""",
                (rider_id, stage_id_by_number[prev_n]),
            )
            prev_row = cur.fetchone()
            if not prev_row:
                continue
            cur.execute(
                """INSERT OR IGNORE INTO stage_results
                   (stage_id, rider_id, team_id, bib_number, stage_rank, status,
                    finish_time_seconds, gap_seconds, bonus_seconds, penalty_seconds,
                    uci_points, pcs_points, gc_rank, gc_gap_seconds, age_at_race)
                   VALUES (?,?,?,?,NULL,'FINISHED',NULL,NULL,0,0,NULL,NULL,?,?,?)""",
                (stage_id_by_number[n], rider_id, prev_row[0], prev_row[1], prev_row[2], prev_row[3], prev_row[4]),
            )
            gaps_closed += 1
    if gaps_closed:
        print(f"  (closed {gaps_closed} single-stage result gaps via carry-forward)")

    # --- Final classification standings: points (green), KOM (polka dot), youth (white) ---
    if classifications:
        for ctype, cls_rows in classifications.items():
            for row in cls_rows:
                (rnk, prev, rider_name, rider_slug, nat, team_name, team_slug,
                 font_txt, span_txt, last_raw) = row

                if not rider_slug:
                    continue

                if nat and nat not in countries_seen:
                    countries_seen[nat] = COUNTRY_NAMES.get(nat)
                    cur.execute(
                        "INSERT OR IGNORE INTO countries (code, name) VALUES (?, ?)",
                        (nat, COUNTRY_NAMES.get(nat)),
                    )
                if rider_slug not in riders_seen:
                    riders_seen[rider_slug] = rider_name
                    cur.execute(
                        "INSERT OR IGNORE INTO riders (rider_id, full_name, nationality_code) "
                        "VALUES (?, ?, ?)",
                        (rider_slug, rider_name, nat),
                    )
                if team_slug and team_slug not in teams_seen:
                    teams_seen[team_slug] = team_name
                    cur.execute(
                        "INSERT OR IGNORE INTO teams (team_id, name, season_year) VALUES (?, ?, ?)",
                        (team_slug, clean_team_name(team_slug, team_name), season_year_from_team_id(team_slug)),
                    )

                # value = first non-empty of font / span / raw text
                value_text = font_txt or span_txt or last_raw or ""
                points_val = None
                seconds_val = None
                if ctype in ("points", "kom"):
                    points_val = parse_int(value_text)
                else:  # youth: clock-style time or gap
                    seconds_val = parse_time_to_seconds(value_text)

                cur.execute(
                    """INSERT OR IGNORE INTO classification_standings
                       (edition_id, classification, rank, rider_id, team_id, points, time_seconds)
                       VALUES (?,?,?,?,?,?,?)""",
                    (edition_id, ctype, parse_int(rnk), rider_slug, team_slug, points_val, seconds_val),
                )
                total_standings += 1

    return total_results, total_incidents, total_standings


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(open(SCHEMA_PATH).read())
    cur = conn.cursor()

    # --- Race (shared across all editions/years) ---
    cur.execute(
        "INSERT INTO races (name, country, race_type) VALUES (?, ?, ?)",
        ("Tour de France", "France", "stage_race"),
    )
    race_id = cur.lastrowid

    countries_seen = {}
    riders_seen = {}
    teams_seen = {}

    grand_total_results = 0
    grand_total_incidents = 0
    grand_total_standings = 0

    for year, edition_name in EDITIONS:
        results, incidents, standings = load_edition(
            cur, race_id, year, edition_name, countries_seen, riders_seen, teams_seen
        )
        grand_total_results += results
        grand_total_incidents += incidents
        grand_total_standings += standings
        print(f"  {year}: {results} stage results, {incidents} incidents, {standings} standings")

    conn.commit()

    print(f"Riders:      {len(riders_seen)}")
    print(f"Teams:       {len(teams_seen)}")
    print(f"Countries:   {len(countries_seen)}")
    print(f"Stage rows:  {grand_total_results}")
    print(f"Incidents:   {grand_total_incidents}")
    print(f"Standings:   {grand_total_standings}")
    print(f"DB written:  {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    main()
