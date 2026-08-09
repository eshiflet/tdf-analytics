#!/usr/bin/env python3
"""
Insert the stages PCS lists but the DB never got, renumbering the edition.

audit_stage_counts.py finds them: 127 stages across 76 editions, mostly the
second half of a split day, sometimes an entire race finale (Giro 1937 is
missing 19a and 19b, so its "final" standings come from stage 18).

An edition's numbering is REBUILT from PCS's ordered stage list rather than
patched around the hole, because inserting stage 5b means every later stage
shifts up one. Existing stages are matched to PCS entries by route, walking
both lists in order so that a repeated route (Giro 1994's Bologna > Bologna 1a
and 1b) still pairs up correctly.

Giro/Vuelta are repaired at the SCRAPE FILE level and then re-ingested, not by
editing the database. Editing the DB directly would be undone by the next
re-ingest — the mistake that has cost data repeatedly in this pipeline. The
files are rewritten into a temporary directory and swapped in, so a
part-renumbered directory can never be left behind if the run dies.

Refuses to touch an edition when:
  * any existing stage's route is absent from PCS's list (the DB has something
    PCS does not, so the alignment is not understood), or
  * a missing stage cannot be scraped (no page, or no results and PCS does not
    say it was cancelled — inventing a raced stage is worse than the gap).

Usage:
  python3 insert_missing_stages.py --race giro --year 1994 --dry-run
  python3 insert_missing_stages.py --race giro --year 1994 --apply
  python3 insert_missing_stages.py --race vuelta --apply
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

import scrape_giro
import scrape_vuelta
from audit_stage_counts import norm, pcs_stages
from insert_cancelled_stages import parse_meta
from race_common import DB_PATH

HERE = os.path.dirname(os.path.abspath(__file__))

RACES = {
    "giro": ("Giro d'Italia", "giro-d-italia", scrape_giro, "giro_scrapes"),
    "vuelta": ("Vuelta a España", "vuelta-a-espana", scrape_vuelta, "vuelta_scrapes"),
}


def load_files(scrapes_dir, year):
    """{stage_number: (path, parsed)} for one year's scrape files."""
    d = os.path.join(HERE, scrapes_dir, str(year))
    out = {}
    if not os.path.isdir(d):
        return out
    for fn in os.listdir(d):
        if not (fn.startswith("stage_") and fn.endswith(".json")):
            continue
        p = os.path.join(d, fn)
        with open(p, encoding="utf-8") as f:
            out[int(fn[6:-5])] = (p, json.load(f))
    return out


def align(listed, files):
    """Pair PCS entries with existing stage files, in order, by route.

    Returns (plan, unmatched_files). plan is a list of
    (target_number, slug, route, existing_key_or_None) in PCS order.
    """
    used = set()
    keys = sorted(files)
    plan = []
    counter = 0
    for slug, route in listed:
        num = 0 if slug == "prologue" else (counter := counter + 1)
        hit = None
        for k in keys:
            if k in used:
                continue
            info = files[k][1].get("info", {})
            db_route = f"{info.get('Start')} - {info.get('Finish')}"
            if norm(db_route) == norm(route):
                hit = k
                used.add(k)
                break
        plan.append((num, slug, route, hit))

    # Second pass: PCS and the DB sometimes spell a route differently —
    # "Martos - Sierra Nevada" against PCS's "Martos - Sierra Nevada (Alto Hoya
    # de la Mora)". Those are the same stage, and treating one as missing would
    # insert a duplicate. Any stage files still unmatched are paired, in order,
    # with the still-unmatched PCS entries; only a PCS surplus beyond that is
    # genuinely absent.
    leftover_files = [k for k in keys if k not in used]
    if leftover_files:
        blanks = [i for i, (_, _, _, hit) in enumerate(plan) if hit is None]
        for i, k in zip(blanks, leftover_files):
            num, slug, route, _ = plan[i]
            plan[i] = (num, slug, route, k)
            used.add(k)
    return plan, [k for k in keys if k not in used]


def scrape_missing(module, race_path, year, slug, num):
    """Scrape one stage. Returns a record, or None if it should not be written."""
    module.DELAY = 1.5
    rec = module.scrape_stage(year, slug, num)
    if rec and rec.get("rows"):
        return rec
    # No results: legitimate only if PCS says the stage was cancelled.
    html = module.fetch(f"{module.BASE}/race/{race_path}/{year}/{slug}")
    if not html:
        return None
    meta = parse_meta(html)
    if not meta.get("cancelled"):
        return None
    return {
        "n": num, "slug": slug, "cancelled": True,
        "info": {"Date": meta.get("date"), "Distance": "0 km",
                 "Start": meta.get("start"), "Finish": meta.get("finish"),
                 "Won how": ""},
        "profile_icon": "p1", "rows": [], "sprint_points": {}, "kom_points": {},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=sorted(RACES), required=True)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    race_name, race_path, module, scrapes_dir = RACES[args.race]
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    years = [r[0] for r in conn.execute(
        "SELECT year FROM race_editions re JOIN races r ON re.race_id=r.race_id "
        "WHERE r.name=? ORDER BY year", (race_name,))]
    conn.close()
    if args.year:
        years = [y for y in years if y == args.year]

    repaired_years, total_new, skipped = [], 0, 0

    for year in years:
        files = load_files(scrapes_dir, year)
        if not files:
            continue
        listed = pcs_stages(race_path, year)
        time.sleep(1.0)
        if not listed:
            continue
        plan, orphans = align(listed, files)
        gaps = [(num, slug, route) for num, slug, route, hit in plan if hit is None]
        if not gaps:
            continue

        print(f"\n{args.race} {year}: PCS {len(listed)}, files {len(files)}, "
              f"{len(gaps)} to insert")
        if orphans:
            print(f"   SKIP: {len(orphans)} existing stage(s) match no PCS entry "
                  f"(files {orphans}) — alignment not understood")
            skipped += len(gaps)
            continue

        renumbers = [(hit, num) for num, _, _, hit in plan if hit is not None and hit != num]
        for num, slug, route, hit in plan:
            if hit is None:
                print(f"   INSERT n={num:<3} {slug:<11} {route[:44]}")
        if renumbers:
            print(f"   renumber {len(renumbers)} existing stage(s), "
                  f"e.g. {renumbers[:4]}")

        if args.dry_run:
            total_new += len(gaps)
            repaired_years.append(year)
            continue

        # Scrape everything first: a partial write is worse than no write.
        fetched = {}
        failed = False
        for num, slug, route, hit in plan:
            if hit is not None:
                continue
            rec = scrape_missing(module, race_path, year, slug, num)
            if rec is None:
                print(f"   ABORT {year}: could not scrape {slug} and PCS does not "
                      "mark it cancelled")
                failed = True
                break
            rec["n"] = num
            fetched[num] = rec
            print(f"      scraped {slug}: {len(rec['rows'])} rows"
                  + ("  [cancelled]" if rec.get("cancelled") else ""))
        if failed:
            skipped += len(gaps)
            continue

        # Rebuild the directory in a temp dir, then swap. Renaming in place
        # collides (stage_6 -> stage_7 while stage_7 still exists).
        target = os.path.join(HERE, scrapes_dir, str(year))
        with tempfile.TemporaryDirectory() as tmp:
            for num, slug, route, hit in plan:
                rec = fetched[num] if hit is None else files[hit][1]
                rec["n"] = num
                rec.setdefault("slug", slug)
                rec["slug"] = slug
                with open(os.path.join(tmp, f"stage_{num}.json"), "w",
                          encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False)
            for fn in os.listdir(target):
                if fn.startswith("stage_") and fn.endswith(".json"):
                    os.remove(os.path.join(target, fn))
            for fn in os.listdir(tmp):
                shutil.copy2(os.path.join(tmp, fn), os.path.join(target, fn))

        total_new += len(gaps)
        repaired_years.append(year)
        print(f"   wrote {len(plan)} stage file(s)")

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}{total_new} stage(s) "
          f"{'would be ' if args.dry_run else ''}inserted across "
          f"{len(repaired_years)} edition(s); {skipped} skipped")
    if repaired_years and not args.dry_run:
        print("\nRe-ingest:")
        for y in repaired_years:
            print(f"  python3 ingest_race.py --race {args.race} {y}")


if __name__ == "__main__":
    main()
