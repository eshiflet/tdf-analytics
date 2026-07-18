#!/usr/bin/env python3
"""
Add newly-scraped stages to the 2026 (or any in-progress year) TDF dataset.

Reads per-stage scrape files from pipeline/scrapes/stage_N.json, updates all
supplemental JSON files, deletes and re-inserts the year in cycling.db, and
runs all exports + validation.

Usage:
  python3 add_stages.py 8 9          # add stages 8 and 9
  python3 add_stages.py 8 9 --year 2025  # non-default year
  python3 add_stages.py 8 9 --dry-run    # preview without writing
  python3 add_stages.py 8 9 --scrapes-only  # only update JSON files, skip DB+export

Each stage_N.json must exist in pipeline/scrapes/ and contain:
{
  "n": 8,
  "info": { "Date": "...", "Distance": "...", ... },
  "rows": [ [rnk, gc_pos, gc_lag, bib, age, name, slug, nat, team, team_slug, uci, pnt, bonus, abs_time, gap], ... ],
  "profile_icon": "p1",
  "sprint_points": { "rider/slug": 25, ... },
  "kom_points": { "rider/slug": 3, ... }
}

The scrape files are produced by navigating to PCS stage pages in a browser and
running the extraction JS from scrape_stage_template.js (see that file for
instructions).
"""

import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES_DIR = os.path.join(HERE, "scrapes")
DB_PATH = os.path.join(HERE, "cycling.db")

DEFAULT_YEAR = 2026


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    scrapes_only = "--scrapes-only" in args
    year = DEFAULT_YEAR

    if "--year" in args:
        idx = args.index("--year")
        year = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    stage_nums = sorted(int(a) for a in args if a.isdigit())
    if not stage_nums:
        print("Usage: python3 add_stages.py <stage_num> [stage_num ...] [--year N] [--dry-run] [--scrapes-only]")
        sys.exit(1)

    print(f"Adding stages {stage_nums} for year {year}")

    # ── Load scrape files ──
    scrapes = {}
    for n in stage_nums:
        path = os.path.join(SCRAPES_DIR, f"stage_{n}.json")
        if not os.path.exists(path):
            print(f"ERROR: {path} not found. Scrape stage {n} first.")
            sys.exit(1)
        scrapes[n] = load_json(path)
        rows = len(scrapes[n].get("rows", []))
        print(f"  Stage {n}: {rows} rows, profile={scrapes[n].get('profile_icon')}")

    year_str = str(year)

    # ── 1. Update tdf_YEAR_full.json ──
    tdf_path = os.path.join(HERE, f"tdf_{year}_full.json")
    tdf = load_json(tdf_path)
    existing_nums = {s["n"] for s in tdf["stages"]}
    added = []
    for n in stage_nums:
        if n in existing_nums:
            print(f"  Stage {n} already in tdf_{year}_full.json, replacing")
            tdf["stages"] = [s for s in tdf["stages"] if s["n"] != n]
        tdf["stages"].append({
            "n": n,
            "info": scrapes[n]["info"],
            "rows": scrapes[n]["rows"],
        })
        added.append(n)
    tdf["stages"].sort(key=lambda s: s["n"])
    total_stages = len(tdf["stages"])

    if not dry_run:
        save_json(tdf_path, tdf)
    print(f"  tdf_{year}_full.json: {total_stages} stages total")

    # ── 2. Update sprint_points.json ──
    sp_path = os.path.join(HERE, "sprint_points.json")
    sp = load_json(sp_path)
    sp_list = sp.get(year_str, [])
    # Extend list to cover all stages
    while len(sp_list) < total_stages:
        sp_list.append({})
    # Place each stage's sprint points at the correct index
    stage_nums_in_tdf = [s["n"] for s in tdf["stages"]]
    for n in stage_nums:
        idx = stage_nums_in_tdf.index(n)
        sp_list[idx] = scrapes[n].get("sprint_points", {})
    sp[year_str] = sp_list
    if not dry_run:
        save_json(sp_path, sp)
    print(f"  sprint_points.json: {len(sp_list)} entries for {year}")

    # ── 3. Update kom_points_reconciled.json ──
    kp_path = os.path.join(HERE, "kom_points_reconciled.json")
    kp = load_json(kp_path)
    kp_list = kp.get(year_str, [])
    while len(kp_list) < total_stages:
        kp_list.append({})
    for n in stage_nums:
        idx = stage_nums_in_tdf.index(n)
        kp_list[idx] = scrapes[n].get("kom_points", {})
    kp[year_str] = kp_list
    if not dry_run:
        save_json(kp_path, kp)
    print(f"  kom_points_reconciled.json: {len(kp_list)} entries for {year}")

    # ── 4. Update profile_icons.json ──
    pi_path = os.path.join(HERE, "profile_icons.json")
    pi = load_json(pi_path)
    pi_list = pi.get(year_str, [])
    while len(pi_list) < total_stages:
        pi_list.append("p1")
    for n in stage_nums:
        idx = stage_nums_in_tdf.index(n)
        pi_list[idx] = scrapes[n].get("profile_icon", "p1")
    pi[year_str] = pi_list
    if not dry_run:
        save_json(pi_path, pi)
    print(f"  profile_icons.json: {len(pi_list)} entries for {year}")

    if dry_run:
        print("\n[DRY RUN] No files written, no DB changes, no exports.")
        return

    if scrapes_only:
        print("\n[SCRAPES ONLY] Supplemental files updated. Skipping DB + exports.")
        return

    # ── 5. Delete edition from DB and re-insert ──
    print(f"\nRe-inserting {year} in cycling.db...")
    from db_backup import backup_db
    backup_db(f"pre-stages-{'-'.join(map(str, stage_nums))}")
    conn = sqlite3.connect(DB_PATH)
    tdf_row = conn.execute("SELECT race_id FROM races WHERE name='Tour de France'").fetchone()
    tdf_race_id = tdf_row[0] if tdf_row else 1
    ed = conn.execute("SELECT edition_id FROM race_editions WHERE race_id=? AND year=?", (tdf_race_id, year)).fetchone()
    if ed:
        edition_id = ed[0]
        conn.execute("DELETE FROM stage_results WHERE stage_id IN (SELECT stage_id FROM stages WHERE edition_id=?)", (edition_id,))
        conn.execute("DELETE FROM stage_incidents WHERE stage_id IN (SELECT stage_id FROM stages WHERE edition_id=?)", (edition_id,))
        conn.execute("DELETE FROM classification_standings WHERE edition_id=?", (edition_id,))
        conn.execute("DELETE FROM stages WHERE edition_id=?", (edition_id,))
        conn.execute("DELETE FROM race_editions WHERE edition_id=?", (edition_id,))
        conn.commit()
        print(f"  Deleted existing edition_id={edition_id}")
    conn.close()

    result = subprocess.run(
        [sys.executable, os.path.join(HERE, "add_pre1960.py"), str(year)],
        cwd=HERE, capture_output=True, text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(f"ERROR: add_pre1960.py failed:\n{result.stderr}")
        sys.exit(1)

    # ── 6. Run exports ──
    print(f"\nExporting...")
    for cmd, label in [
        ([sys.executable, "export_gc.py", "--year", str(year)], "export_gc.py"),
        ([sys.executable, "export_riders_index.py"], "export_riders_index.py"),
        ([sys.executable, "export_all_races_summary.py"], "export_all_races_summary.py"),
    ]:
        result = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
        print(f"  {label}: {result.stdout.strip()}")
        if result.returncode != 0:
            print(f"  ERROR: {result.stderr}")
            sys.exit(1)

    # ── 7. Validate ──
    print(f"\nValidating...")
    result = subprocess.run(
        [sys.executable, "validate_exports.py", "--year", str(year)],
        cwd=HERE, capture_output=True, text=True,
    )
    print(f"  {result.stdout.strip()}")
    if result.returncode != 0:
        print(f"  VALIDATION FAILED:\n{result.stderr}")
        sys.exit(1)

    print(f"\nDone! {len(stage_nums)} stage(s) added to {year}. Verify in the dev server.")


if __name__ == "__main__":
    main()
