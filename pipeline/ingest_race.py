#!/usr/bin/env python3
"""
Ingest scraped Giro d'Italia or Vuelta a España stage data into cycling.db.

Reads JSON files from pipeline/<race>_scrapes/YEAR/stage_N.json (or flat
<race>_scrapes/stage_N.json for Giro's legacy 2026 layout) and inserts into
the shared multi-race schema. Replaces the old ingest_giro.py / ingest_vuelta.py
— the two were ~85% identical; race-specific behavior (Giro's flat-2026
fallback, Giro's post-ingest name-fix pass) is now explicit branches below
instead of being duplicated wholesale.

Usage:
  python3 ingest_race.py --race giro                    # all years with stage files
  python3 ingest_race.py --race giro 1990 1991 1992      # specific years only
  python3 ingest_race.py --race giro 1990-2000           # year range
  python3 ingest_race.py --race vuelta --dry-run         # show what would be inserted
  python3 ingest_race.py --race vuelta --all             # re-ingest every year
"""

import json
import os
import re
import sqlite3
import sys
from glob import glob

from backfill_source_slugs import backfill_edition_slugs
from race_common import (
    RACES,
    DB_PATH,
    StageRow,
    detect_route_type,
    parse_bonus_seconds,
    parse_int,
    parse_time_to_seconds,
    parse_year_args,
    COUNTRY_NAMES,
    FLAT_FALLBACK_YEAR,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DRY_RUN = "--dry-run" in sys.argv


def _stage_num(path: str) -> int:
    return int(re.search(r"stage_(\d+)\.json$", path).group(1))


def find_stage_files_for_year(scrapes_dir: str, year: int, flat_fallback: bool) -> list[str]:
    """Find stage files for a year, checking the year subdir first, then
    (for races with the legacy layout) the flat FLAT_FALLBACK_YEAR fallback.

    Numeric sort — plain sorted() is lexicographic (stage_1, stage_10, ...,
    stage_2), which scrambles any logic that walks stages in race order.
    """
    year_dir = os.path.join(scrapes_dir, str(year))
    files = sorted(glob(os.path.join(year_dir, "stage_*.json")), key=_stage_num)
    if files:
        return files
    if flat_fallback and year == FLAT_FALLBACK_YEAR:
        return sorted(glob(os.path.join(scrapes_dir, "stage_*.json")), key=_stage_num)
    return []


def load_gc_standings(scrapes_dir: str, year: int) -> dict | None:
    """Per-stage GC from build_vuelta_gc_standings.py (--race giro|vuelta), if present.

    Returns {stage_number(int): {rider_slug: [rank_or_None, gap_seconds]}}.
    """
    path = os.path.join(scrapes_dir, str(year), "gc_standings.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {int(n): entries for n, entries in data.get("stages", {}).items()}


def discover_years(scrapes_dir: str, flat_fallback: bool) -> list[int]:
    """Find all years that have scraped stage files."""
    years = set()
    for entry in os.listdir(scrapes_dir):
        if entry.isdigit() and os.path.isdir(os.path.join(scrapes_dir, entry)):
            files = glob(os.path.join(scrapes_dir, entry, "stage_*.json"))
            if files:
                years.add(int(entry))
    if flat_fallback and glob(os.path.join(scrapes_dir, "stage_*.json")):
        years.add(FLAT_FALLBACK_YEAR)
    return sorted(years)


def ingest_year(conn, race_id: int, race_name: str, scrapes_dir: str, year: int, stage_files: list[str]) -> int:
    """Ingest one year's stage files. Returns total results inserted."""
    cur = conn.cursor()

    existing = cur.execute(
        "SELECT edition_id FROM race_editions WHERE race_id=? AND year=?",
        (race_id, year),
    ).fetchone()

    # Preserve per-stage fields that come from scrape_{giro,vuelta}_stage_info.py,
    # not the stage scrape files — otherwise a re-ingest silently wipes them.
    #
    # Keyed by source_slug wherever the existing row has one, falling back to
    # stage_number only for rows predating that column. Keying on stage_number
    # alone is actively dangerous: the whole reason you re-ingest an edition is
    # usually that its numbering was wrong, and number-keyed preservation then
    # re-attaches each elevation to whichever *different* stage now holds that
    # number — silently re-corrupting the data during the repair. (This is what
    # happened while fixing the 2010 Vuelta's two missing stages.)
    # distance_km rides along: PCS reports "0 km" for some historical stages and
    # patch_missing_distances.py backfills the real figure from Wikipedia. That
    # patched value lives only in the DB, so a re-ingest that trusts the scrape
    # file's 0 silently destroys it (caught re-ingesting 2010 Vuelta stage 21,
    # 85.0 km -> 0.0). Only ever used when the incoming value is 0/absent.
    preserved_by_slug = {}
    preserved_by_number = {}
    if existing:
        for r in cur.execute(
            "SELECT stage_number, source_slug, vertical_meters, profile_score, distance_km, "
            "cancelled FROM stages WHERE edition_id=?",
            (existing[0],),
        ):
            if (r["vertical_meters"] is None and r["profile_score"] is None
                    and not r["distance_km"] and not r["cancelled"]):
                continue
            vals = (r["vertical_meters"], r["profile_score"], r["distance_km"],
                    r["cancelled"])
            # Populate BOTH indexes, always. The incoming stage file may or may
            # not carry a slug independently of whether the existing row has
            # one, so keying only on whichever the old row had would miss
            # every stage when the two disagree (that wipes the whole
            # edition's elevation on re-ingest).
            preserved_by_number[r["stage_number"]] = vals
            if r["source_slug"]:
                preserved_by_slug[r["source_slug"]] = vals

    if DRY_RUN:
        action = "replace existing" if existing else "insert"
        print(f"  [DRY RUN] Would {action} {year} {race_name} with {len(stage_files)} stages")
        return 0

    if existing:
        eid = existing[0]
        cur.execute("DELETE FROM stage_results WHERE stage_id IN (SELECT stage_id FROM stages WHERE edition_id=?)", (eid,))
        cur.execute("DELETE FROM stages WHERE edition_id=?", (eid,))
        cur.execute("DELETE FROM race_editions WHERE edition_id=?", (eid,))

    cur.execute(
        "INSERT INTO race_editions (race_id, year, edition_name) VALUES (?,?,?)",
        (race_id, year, f"{year} {race_name}"),
    )
    edition_id = cur.lastrowid

    countries_seen = {r["code"] for r in cur.execute("SELECT code FROM countries")}
    riders_seen = {r["rider_id"] for r in cur.execute("SELECT rider_id FROM riders")}
    teams_seen = {r["team_id"] for r in cur.execute("SELECT team_id FROM teams")}

    gc_standings = load_gc_standings(scrapes_dir, year)
    total_results = 0

    for sf in stage_files:
        with open(sf, encoding="utf-8") as f:
            stage_data = json.load(f)

        n = stage_data["n"]
        slug = stage_data.get("slug")  # absent in files scraped before slugs were recorded
        info = stage_data.get("info", {})
        rows = stage_data.get("rows", [])
        profile_icon = stage_data.get("profile_icon", "p1")

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

        if slug and slug in preserved_by_slug:
            preserved_vm, preserved_ps, preserved_d, preserved_c = preserved_by_slug[slug]
        else:
            preserved_vm, preserved_ps, preserved_d, preserved_c = preserved_by_number.get(
                n, (None, None, None, 0))

        is_cancelled = bool(stage_data.get("cancelled") or preserved_c)

        # Trust the freshly scraped distance whenever it's a real figure; fall
        # back to the stored one only when PCS gave us nothing usable. Never for
        # a cancelled stage: 0 km is its true distance, and the stored value is
        # liable to belong to whatever stage previously occupied this number.
        if not distance_km and preserved_d and not is_cancelled:
            print(f"    stage {n}: scrape has no distance, keeping stored {preserved_d} km")
            distance_km = preserved_d
        cur.execute(
            """INSERT INTO stages
               (edition_id, stage_number, stage_label, stage_date,
                start_location, finish_location, distance_km, stage_type,
                vertical_meters, profile_score, route_type, won_how, source_slug,
                cancelled)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                edition_id, n, f"Stage {n}", date_iso,
                info.get("Start"), info.get("Finish"), distance_km,
                "itt" if route_type in ("TT", "TTT") else "road",
                preserved_vm, preserved_ps, route_type, won_how,
                # NULL, not a reconstructed f"stage-{n}", when the scrape file
                # predates slug recording: on a split edition that guess is
                # wrong for every stage after the split, and a wrong slug is
                # worse than a missing one because callers will trust it.
                # backfill_source_slugs.py fills these in date-aware.
                slug,
                # A cancelled stage has no results, so nothing in the scrape rows
                # can imply it — the flag lives only in the file or the DB.
                1 if is_cancelled else 0,
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
                continue

            # Per-stage GC. Priority: (1) raw scraped gc_pos/gc_lag from this
            # stage's own result row — authoritative when present; (2)
            # gc_standings.json (real PCS GC merged with cumulative times
            # computed from actual stage results — see
            # build_vuelta_gc_standings.py --race giro|vuelta), which fills
            # gaps for historical PCS result pages that carried GC for only a
            # few riders per stage (sparse pre-1998). Never carry values
            # across stages (a rider's gap changes every stage — stale values
            # are fabricated data).
            #
            # NOTE: gc_standings.json must NEVER override a present raw value.
            # It used to be preferred outright whenever the file existed,
            # which silently discarded good raw gc_pos for any rider it
            # didn't happen to cover — confirmed to have dropped 26-48% of
            # finishers' GC rank on several recent Giro editions (found
            # 2026-08-01 investigating a "79 finishers instead of 151" report).
            if not gc_pos and n == 1:
                stage_rank_fallback = parse_int(rnk)
                if stage_rank_fallback is not None:
                    gc_pos = str(stage_rank_fallback)
                    gc_lag = gap_txt
            gc_rank_v = parse_int(gc_pos)
            gc_gap_v = parse_time_to_seconds(gc_lag)
            if gc_rank_v is None and gc_standings is not None:
                entry = gc_standings.get(n, {}).get(rider_slug)
                if entry:
                    gc_rank_v, gc_gap_v = entry[0], entry[1]

            if nat and nat not in countries_seen:
                countries_seen.add(nat)
                cur.execute(
                    "INSERT OR IGNORE INTO countries (code, name) VALUES (?,?)",
                    (nat, COUNTRY_NAMES.get(nat)),
                )

            if rider_slug not in riders_seen:
                riders_seen.add(rider_slug)
                cur.execute(
                    "INSERT OR IGNORE INTO riders (rider_id, full_name, nationality_code) VALUES (?,?,?)",
                    (rider_slug, rider_name, nat),
                )

            if team_slug and team_slug not in teams_seen:
                teams_seen.add(team_slug)
                m = re.search(r"-(\d{4})$", team_slug)
                season_year = int(m.group(1)) if m else None
                cur.execute(
                    "INSERT OR IGNORE INTO teams (team_id, name, season_year) VALUES (?,?,?)",
                    (team_slug, team_name, season_year),
                )

            # Status. NOTE: "DF" is deliberately NOT an exit status — on
            # historical PCS pages it marks riders who finished the stage
            # without a recorded position/time (often the whole peloton);
            # they stay in the race.
            status = "FINISHED"
            if rnk in ("DNF", "DNS", "OTL", "NP", "DSQ", "DEL"):
                status = rnk

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
            gc_rank = gc_rank_v
            gc_gap_secs = gc_gap_v

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

        # Supplement with gc_standings entries for riders absent from result rows.
        # Old PCS stage pages often omit mid-pack riders entirely; gc_standings has
        # computed GC positions for them. INSERT OR IGNORE skips existing rows.
        if gc_standings is not None:
            for slug, entry in gc_standings.get(n, {}).items():
                gc_rank_s, gc_gap_s = entry[0], entry[1]
                if gc_rank_s is None:
                    continue
                try:
                    cur.execute(
                        "INSERT OR IGNORE INTO stage_results "
                        "(stage_id, rider_id, status, gc_rank, gc_gap_seconds) "
                        "VALUES (?,?,'FINISHED',?,?)",
                        (stage_id, slug, gc_rank_s, gc_gap_s),
                    )
                except Exception:
                    pass  # rider not in riders table; skip

        print(f"  Stage {n}: {len(rows)} rows inserted")

    # Stage files scraped before slugs were recorded leave source_slug NULL.
    # Derive them from the same-date split detection the standalone backfill
    # uses, so a re-ingest of an old year doesn't quietly undo the backfill and
    # leave scrape_*_stage_info.py with nothing to key off.
    filled = backfill_edition_slugs(cur, edition_id)
    if filled:
        print(f"  derived source_slug for {filled} stage(s) from stage dates")

    conn.commit()
    return total_results


def main():
    args = sys.argv[1:]

    if "--race" not in args:
        sys.exit(
            "usage: python3 ingest_race.py --race {giro,vuelta} [YEARS...] [--dry-run|--all]"
        )
    race = args[args.index("--race") + 1]
    if race not in RACES:
        sys.exit(f"error: unknown race '{race}' (use 'giro' or 'vuelta')")
    info = RACES[race]
    scrapes_dir = os.path.join(HERE, info.scrapes_dirname)

    year_args = parse_year_args(args)
    if not year_args and "--all" not in args:
        sys.exit(
            f"Refusing to re-ingest every year in {info.scrapes_dirname}/ without an explicit --all.\n"
            "Re-ingesting a year wipes and rebuilds it; pass the year(s) you actually\n"
            f"changed (e.g. 'python3 ingest_race.py --race {race} 1985' or '1980-1989'), or --all\n"
            "if you really want to rebuild everything."
        )
    years = year_args if year_args else discover_years(scrapes_dir, info.flat_2026_fallback)

    if not years:
        print("No stage files found in", scrapes_dir)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    race_row = cur.execute("SELECT race_id FROM races WHERE name = ?", (info.name,)).fetchone()
    if not race_row:
        cur.execute(
            "INSERT INTO races (name, country, race_type) VALUES (?, ?, ?)",
            (info.name, info.country, "stage_race"),
        )
        conn.commit()
        race_id = cur.execute("SELECT race_id FROM races WHERE name = ?", (info.name,)).fetchone()[0]
        print(f"Created race '{info.name}' (race_id={race_id})")
    else:
        race_id = race_row["race_id"]
        print(f"Using existing {info.name} (race_id={race_id})")

    grand_total = 0
    for year in years:
        stage_files = find_stage_files_for_year(scrapes_dir, year, info.flat_2026_fallback)
        if not stage_files:
            print(f"{year}: no stage files found, skipping")
            continue
        print(f"\n{year}: {len(stage_files)} stage file(s)")
        total = ingest_year(conn, race_id, info.name, scrapes_dir, year, stage_files)
        grand_total += total
        if not DRY_RUN:
            print(f"  {year}: {total} results inserted")

    conn.close()
    print(f"\nDone: {grand_total} total stage results across {len(years)} year(s)")

    if not DRY_RUN and race == "giro":
        import importlib.util
        fix_path = os.path.join(HERE, "fix_giro_rider_names.py")
        spec = importlib.util.spec_from_file_location("fix_giro_rider_names", fix_path)
        fix_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fix_mod)
        print()
        fix_mod.main()


if __name__ == "__main__":
    main()
