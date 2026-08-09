#!/usr/bin/env python3
"""
Re-scrape stages whose stored result set is far smaller than their edition's.

These are overwhelmingly TEAM time trials. PCS groups a TTT's results by team
in a <ul class="list ttt-results">, which the ordinary row parser could not
read — it returned a single stray row rather than none, so the stage looked
populated and nothing downstream complained. See race_common.parse_ttt_rows.

Targets are found by comparing each stage's result count against the median
for its edition, not by route_type: the type itself is unreliable here, since
PCS writes a plain "Time trial" in "Won how" for some team trials and those
were classified TT.

SAFETY: a stage file is rewritten only when the fresh scrape yields strictly
MORE rows than the file already holds. A re-scrape that comes back smaller
means something is wrong with the fetch, not with the stored data, and
overwriting on that basis would destroy real results.

Usage:
  python3 rescrape_ttt_stages.py --dry-run
  python3 rescrape_ttt_stages.py --apply
  python3 rescrape_ttt_stages.py --apply --race vuelta
"""

import argparse
import json
import os
import sqlite3
import sys
import time

import scrape_giro
import scrape_pcs_stages
import scrape_vuelta
from race_common import DB_PATH

HERE = os.path.dirname(os.path.abspath(__file__))

RACES = {
    "Vuelta a España": ("vuelta", scrape_vuelta, "vuelta_scrapes"),
    "Giro d'Italia": ("giro", scrape_giro, "giro_scrapes"),
    "Tour de France": ("tdf", scrape_pcs_stages, None),   # tdf_YEAR_full.json
}


def find_targets(race_filter=None):
    """Stages holding under a quarter of their edition's median field size."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    c, c2 = conn.cursor(), conn.cursor()
    out = []
    for e in c.execute("""SELECT re.edition_id, re.year, ra.name race
                          FROM race_editions re JOIN races ra ON re.race_id=ra.race_id
                          ORDER BY ra.name, re.year""").fetchall():
        if race_filter and RACES.get(e["race"], (None,))[0] != race_filter:
            continue
        st = c2.execute("""SELECT stage_number n, source_slug, cancelled,
              (SELECT COUNT(*) FROM stage_results WHERE stage_id=stages.stage_id) res
              FROM stages WHERE edition_id=? ORDER BY stage_number""",
                        (e["edition_id"],)).fetchall()
        live = [s["res"] for s in st if not s["cancelled"]]
        if not live:
            continue
        median = sorted(live)[len(live) // 2]
        if median < 20:
            continue
        for s in st:
            if not s["cancelled"] and s["res"] < median * 0.25:
                out.append({"race": e["race"], "year": e["year"], "n": s["n"],
                            "slug": s["source_slug"], "res": s["res"], "median": median})
    conn.close()
    return out


def rewrite_race_file(scrapes_dir, year, n, record):
    """Vuelta/Giro: one JSON per stage."""
    path = os.path.join(HERE, scrapes_dir, str(year), f"stage_{n}.json")
    with open(path, encoding="utf-8") as f:
        old = json.load(f)
    # keep the file's own stage number; the scrape only knows the slug
    record["n"] = old["n"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
    return path


def rewrite_tdf_file(year, n, record):
    """TDF: stages live inside one tdf_YEAR_full.json."""
    path = os.path.join(HERE, f"tdf_{year}_full.json")
    with open(path, encoding="utf-8") as f:
        full = json.load(f)
    for s in full["stages"]:
        if s["n"] == n:
            s["rows"] = record["rows"]
            s["info"] = record["info"]
            s["is_ttt"] = record.get("is_ttt", False)
            break
    else:
        return None
    with open(path, "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=["tdf", "giro", "vuelta"], default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    targets = find_targets(args.race)
    print(f"{len(targets)} stage(s) below a quarter of their edition's median\n")

    grew = unchanged = failed = 0
    touched_years = set()

    for t in targets:
        race_arg, module, scrapes_dir = RACES[t["race"]]
        tag = f"{t['race'][:6]} {t['year']} n{t['n']} {t['slug']}"
        module.DELAY = 1.5
        try:
            rec = module.scrape_stage(t["year"], t["slug"], t["n"])
        except Exception as exc:
            print(f"  {tag}: scrape error {exc}")
            failed += 1
            continue
        if not rec or not rec.get("rows"):
            print(f"  {tag}: no rows returned — leaving as is")
            failed += 1
            continue

        new_n, old_n = len(rec["rows"]), t["res"]
        if new_n <= old_n:
            print(f"  {tag}: {new_n} rows, not more than the stored {old_n} — SKIPPED")
            unchanged += 1
            continue

        flag = " [TTT]" if rec.get("is_ttt") else ""
        print(f"  {tag}: {old_n} -> {new_n} rows (median {t['median']}){flag}")
        grew += 1
        touched_years.add((race_arg, t["year"]))
        if args.apply:
            if scrapes_dir:
                rewrite_race_file(scrapes_dir, t["year"], t["n"], rec)
            else:
                rewrite_tdf_file(t["year"], t["n"], rec)
        time.sleep(0.5)

    print(f"\n{'[DRY RUN] ' if not args.apply else ''}"
          f"{grew} stage(s) recovered, {unchanged} unchanged, {failed} failed")
    if touched_years:
        print("\nRe-ingest:")
        for race_arg, year in sorted(touched_years):
            if race_arg == "tdf":
                print(f"  (TDF {year}: tdf_{year}_full.json updated — re-ingest via "
                      "add_pre1960.py / the TDF ingest path)")
            else:
                print(f"  python3 ingest_race.py --race {race_arg} {year}")


if __name__ == "__main__":
    main()
