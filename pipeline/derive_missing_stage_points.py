#!/usr/bin/env python3
"""
Recover a Grand Tour finale's sprint/KOM points from PCS's own classifications.

WHY. 41 Giro/Vuelta editions carry points for every stage except the last one.
PCS 500s `<slug>-points` for a final stage (see "The points refresh"), and for
most of these years the stage's own result page carries no points tables
either — so `refresh_stage_points.py`'s fallback finds nothing and the finale
stays empty. The effect is not small: Nizzolo finished the 2015 Giro on 164 of
his published 181 points, Bettini the 2005 Giro on 151 of 162.

The points are not lost, they are just not on a stage page. PCS publishes the
CUMULATIVE points and KOM classification on every stage page, so the finale's
award is (classification after the last stage) - (classification after the
one before it). That is PCS's own data, not a reconstruction of ours.

VALIDATED before being used, against the per-stage awards we already have:
across the 2015 Giro's stages 2-20 the delta equals our scraped award for
1,403 of 1,438 rider-stages (97.6%). The 35 that differ are attribution jitter
between adjacent stages (van Poppel: delta 0 / award 3 on stage 6, then 3 / 0
on stage 7), which cancels in the cumulative total. Filling only the finale
took the 2005 Giro from 55/89 riders matching PCS exactly to 71/89, and the
2015 Giro from 77/108 to 97/108.

WHAT IT REFUSES TO DO:
  - overwrite a finale that already has points. Scraped data always wins.
  - write a negative delta. A classification can go DOWN (the 2015 Giro docks
    Intxausti 5 points on the last day) and that is a jury penalty, not an
    award; modelling it as a negative stage score would be wrong.

Every edition it touches is recorded in derived_stage_points.json, which
`refresh_stage_points.py` reads so a later refresh cannot silently purge these
values back to empty. Re-run this after any refresh, the way fix_name_swaps
is replayed after a re-scrape.

Usage:
  python3 derive_missing_stage_points.py --race giro --dry-run
  python3 derive_missing_stage_points.py --race giro --apply
  python3 derive_missing_stage_points.py --race vuelta 2015 --apply
"""

import argparse
import glob
import json
import os
import re
import sys
import time

from race_common import exit_on_help, parse_year_args
import scrape_classifications as SC

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD = os.path.join(HERE, "derived_stage_points.json")
_after_cache = {}
PCS_SLUG = {"giro": "giro-d-italia", "vuelta": "vuelta-a-espana"}
KINDS = {"POINTS": "sprint_points", "KOM": "kom_points"}


def _points_array(race, year, kind):
    f = os.path.join(HERE, f"{race}_{'sprint' if kind == 'POINTS' else 'kom'}_points.json")
    with open(f, encoding="utf-8") as fh:
        return json.load(fh).get(str(year), [])


def stage_files(race, year):
    """{stage_number: (path, slug)} — the slug is PCS's, never rebuilt from n."""
    out = {}
    for f in glob.glob(os.path.join(HERE, f"{race}_scrapes", str(year), "stage_*.json")):
        n = int(re.search(r"stage_(\d+)\.json$", f).group(1))
        with open(f, encoding="utf-8") as fh:
            out[n] = (f, json.load(fh).get("slug") or f"stage-{n}")
    return out


def standings(race, year, slug):
    """{kind: {rider: total}} from one stage page's classification tabs."""
    try:
        html = SC.fetch(f"https://www.procyclingstats.com/race/{PCS_SLUG[race]}/{year}/{slug}")
    except Exception as e:
        # PCS 500s some stage pages outright. An unreachable page must mean
        # "no standings", which the baseline guard then turns into "skip" —
        # never a crash that abandons every remaining year, and never an
        # empty baseline treated as zero.
        print(f"    {year} {slug}: {type(e).__name__} {e} — treated as no standings")
        return {kind: {} for kind in KINDS}
    blocks = SC.tab_blocks(html) if html else {}
    out = {}
    for kind in KINDS:
        rows = SC.parse_rows(blocks[kind]) if kind in blocks else []
        out[kind] = {r[1]: r[4] for r in rows if r[4] is not None}
    return out


def derive_year(race, year, verbose=True):
    """Every stage of `year` whose points are empty but whose award PCS's own
    consecutive classifications imply.

    Originally this filled only the finale, because that is where PCS 500s the
    `-points` page. It is not the only hole: the 2019 Vuelta is missing EIGHT
    stages, and deriving the seven with a usable baseline took it from 23 of
    103 riders matching PCS to 47. The method does not care which stage it is —
    only that the classification on both sides of it is readable.
    """
    files = stage_files(race, year)
    if len(files) < 2:
        return None
    nums = sorted(files)
    lo = nums[0]
    arrays = {kind: _points_array(race, year, kind) for kind in KINDS}

    # A year with NO points anywhere predates the classification, and every
    # stage of it is "empty" in the sense this tool looks for. Walking those
    # costs a standings fetch per stage and can never produce anything: the
    # improvement gate has no published table to measure against, so each one
    # is discarded after the fetching. Left unguarded this spent 81 minutes on
    # the pre-1960 Giro and emitted not one line.
    if not any(any(st for st in arrays[kind]) for kind in KINDS):
        return {"year": year, "skipped": "no points in this era"}

    # Which stages are missing which classification's points?
    todo = {}
    for kind, key in KINDS.items():
        arr = arrays[kind]
        for n in nums:
            i = n - lo
            if i < len(arr) and not arr[i]:
                todo.setdefault(n, []).append((kind, key))
    if not todo:
        return {"year": year, "skipped": "nothing empty"}

    # Standings are only fetched for stages that could matter: an empty stage
    # and the one before it.
    need = set()
    for n in todo:
        need.add(n)
        prior = [m for m in nums if m < n]
        if prior:
            need.add(prior[-1])
    stand = {}
    for n in sorted(need):
        stand[n] = standings(race, year, files[n][1])
        time.sleep(0.35)

    per_stage, negatives, implausible, no_baseline = {}, [], [], []
    for n in sorted(todo):
        prior = [m for m in nums if m < n]
        if not prior:
            no_baseline.append((n, "first stage"))
            continue
        b_all, a_all = stand.get(prior[-1], {}), stand.get(n, {})
        for kind, key in todo[n]:
            a, b = a_all.get(kind, {}), b_all.get(kind, {})
            if not a:
                continue
            if not b:
                no_baseline.append((n, kind))
                continue
            both = {}
            for rider, total in a.items():
                if rider in b:
                    delta = total - b[rider]
                    if delta > 0:
                        both[rider] = delta
                    elif delta < 0:
                        negatives.append((kind, rider, delta))
            ceiling = max(both.values()) if both else 0
            d = dict(both)
            for rider, total in a.items():
                if rider not in b:
                    if 0 < total <= ceiling:
                        d[rider] = total
                    elif total > ceiling:
                        implausible.append((kind, rider, total, ceiling))
                    else:
                        negatives.append((kind, rider, total))
            if d:
                per_stage.setdefault(n, {})[key] = d

    return {"year": year, "lo": lo, "files": files, "per_stage": per_stage,
            "negatives": negatives, "implausible": implausible,
            "no_baseline": no_baseline}


def agreement(race, year, key, kind, after_standings, extra=None):
    """(matching riders, listed riders) against PCS's published classification.

    The self-check every write is gated on: does adding the derived points move
    our cumulative totals CLOSER to PCS's own table? A derivation that cannot
    show that is not written. It has earned its keep — it refused the Vuelta
    2000's points, which this would otherwise have taken from 66 exact to 26.
    """
    off = after_standings.get(kind, {})
    if not off:
        return None
    cur = {}
    for st in _points_array(race, year, kind):
        for r, v in st.items():
            cur[r] = cur.get(r, 0) + v
    for r, v in (extra or {}).items():
        cur[r] = cur.get(r, 0) + v
    return sum(1 for r, v in off.items() if cur.get(r, 0) == v), len(off)


def main(argv=None):
    exit_on_help(__doc__)
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=("giro", "vuelta"), required=True)
    ap.add_argument("years", nargs="*")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not args.apply:
        args.dry_run = True

    race = args.race
    root = os.path.join(HERE, f"{race}_scrapes")
    wanted = parse_year_args(args.years) if args.years else None
    years = sorted(int(d) for d in os.listdir(root)
                   if d.isdigit() and os.path.isdir(os.path.join(root, d)))
    if wanted:
        years = [y for y in years if y in wanted]

    record = {}
    unproven = []
    if os.path.exists(RECORD):
        with open(RECORD, encoding="utf-8") as f:
            record = json.load(f)

    print(f"{'year':<6}{'stages':<9}{'sprint riders/pts':<21}{'kom riders/pts':<19}notes")
    touched = 0
    for y in years:
        r = derive_year(race, y)
        if not r or r.get("skipped") or not r.get("per_stage"):
            continue

        # Gate per CLASSIFICATION, on measured agreement with PCS's published
        # final table. A stage-level gate is not possible — one stage's award
        # only moves a rider's total, and the total is what can be checked.
        after_st = standings(race, y, r["files"][max(r["files"])][1])
        time.sleep(0.3)
        kept = {}
        for kind, key in KINDS.items():
            add = {}
            for n, bykey in r["per_stage"].items():
                for rider, v in bykey.get(key, {}).items():
                    add[rider] = add.get(rider, 0) + v
            if not add:
                continue
            b = agreement(race, y, key, kind, after_st)
            a = agreement(race, y, key, kind, after_st, add)
            if b and a and a[0] > b[0]:
                kept[key] = (b[0], a[0], a[1])
            else:
                unproven.append((y, kind, b[0] if b else 0, a[0] if a else 0))
        if not kept:
            continue

        sp = {k: v for n, d in r["per_stage"].items() for k, v in d.get("sprint_points", {}).items()} \
            if "sprint_points" in kept else {}
        km = {k: v for n, d in r["per_stage"].items() for k, v in d.get("kom_points", {}).items()} \
            if "kom_points" in kept else {}
        stages = sorted(n for n, d in r["per_stage"].items() if any(k in kept for k in d))
        note = ""
        if r["negatives"]:
            note = f"{len(r['negatives'])} negative skipped"
        if r["implausible"]:
            note += f"  {len(r['implausible'])} over-ceiling skipped"
        if r["no_baseline"]:
            note += f"  {len(r['no_baseline'])} no baseline"
        print(f"{y:<6}{str(stages)[:8]:<9}"
              f"{f'{len(sp)} / {sum(sp.values())}':<21}"
              f"{f'{len(km)} / {sum(km.values())}':<19}{note}")
        touched += 1
        if args.apply:
            for n, bykey in r["per_stage"].items():
                path = r["files"][n][0]
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                wrote = []
                for key, d in bykey.items():
                    if key in kept and not data.get(key):
                        data[key] = d
                        wrote.append(key)
                if wrote:
                    tmp = path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False)
                    os.replace(tmp, path)
                    rec = record.setdefault(race, {}).setdefault(str(y), {})
                    rec[str(n)] = {
                        "slug": r["files"][n][1], "keys": wrote,
                        "method": "PCS classification delta across consecutive stages",
                        "derived_on": time.strftime("%Y-%m-%d"),
                    }
        sys.stdout.flush()

    if args.apply and touched:
        with open(RECORD, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print(f"\nrecorded {touched} edition(s) in {os.path.basename(RECORD)}")
    if unproven:
        print(f"\n{len(unproven)} classification(s) NOT written — the fill did not "
              f"improve agreement with PCS, so there is no evidence for the values:")
        for y, kind, b, a in unproven:
            print(f"    {race} {y} {kind}: {b} -> {a} exact")
    print(f"\n{race}: {touched} edition(s)"
          f"{'' if args.apply else '  [DRY RUN - nothing written]'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
