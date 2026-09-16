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

Every edition it touches is recorded in derived_final_stage_points.json, which
`refresh_stage_points.py` reads so a later refresh cannot silently purge these
values back to empty. Re-run this after any refresh, the way fix_name_swaps
is replayed after a re-scrape.

Usage:
  python3 derive_final_stage_points.py --race giro --dry-run
  python3 derive_final_stage_points.py --race giro --apply
  python3 derive_final_stage_points.py --race vuelta 2015 --apply
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
RECORD = os.path.join(HERE, "derived_final_stage_points.json")
_after_cache = {}
PCS_SLUG = {"giro": "giro-d-italia", "vuelta": "vuelta-a-espana"}
KINDS = {"POINTS": "sprint_points", "KOM": "kom_points"}


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
    files = stage_files(race, year)
    if len(files) < 2:
        return None
    nums = sorted(files)
    fin, pen = nums[-1], nums[-2]
    fin_path, fin_slug = files[fin]
    with open(fin_path, encoding="utf-8") as f:
        data = json.load(f)

    want = [k for kind, k in KINDS.items() if not data.get(k)]
    if not want:
        return {"year": year, "skipped": "final stage already has points"}

    after = standings(race, year, fin_slug)
    time.sleep(SC.DELAY if hasattr(SC, "DELAY") else 1.0)
    before = standings(race, year, files[pen][1])
    _after_cache[(race, year)] = after

    filled, negatives = {}, []
    skipped_no_baseline, implausible = [], []
    for kind, key in KINDS.items():
        if key not in want:
            continue
        a, b = after.get(kind, {}), before.get(kind, {})
        if not a:
            continue
        # A BASELINE IS MANDATORY. With no penultimate standings every delta
        # becomes the rider's whole-race total, which is not a stage award and
        # is wildly wrong: the 1986 Giro's penultimate page lists nobody, so
        # this would have credited Bontempi with 167 points on the last day —
        # his entire classification. PCS simply does not publish per-stage
        # classifications for that era, and "no baseline" must mean "skip",
        # never "assume zero".
        if not b:
            skipped_no_baseline.append(kind)
            continue

        d, both = {}, {}
        for rider, total in a.items():
            if rider in b:
                delta = total - b[rider]
                if delta > 0:
                    both[rider] = delta
                elif delta < 0:
                    negatives.append((kind, rider, delta))
        # A rider present in the final standings but absent from the previous
        # one either scored their first points on the finale, or the earlier
        # table was truncated. Only the first is real, and the two are
        # indistinguishable per rider — so accept one only if it is no larger
        # than the biggest award actually observed among riders we can verify.
        # That ceiling is read from this stage's own data rather than being a
        # magic number.
        ceiling = max(both.values()) if both else 0
        d.update(both)
        for rider, total in a.items():
            if rider not in b:
                # `> 0` is not redundant: PCS lists riders on a NEGATIVE
                # classification total when a jury penalty exceeds the points
                # they scored (Giro 2016 has two on -5). Without this the
                # ceiling test passes them straight through, and a negative
                # "award" makes the cumulative curve decrease — which
                # validate_exports catches as an error, correctly.
                if 0 < total <= ceiling:
                    d[rider] = total
                elif total > ceiling:
                    implausible.append((kind, rider, total, ceiling))
                else:
                    negatives.append((kind, rider, total))
        if d:
            filled[key] = d
    return {"year": year, "stage": fin, "slug": fin_slug, "path": fin_path,
            "data": data, "filled": filled, "negatives": negatives,
            "no_baseline": skipped_no_baseline, "implausible": implausible}


def agreement(race, year, key, kind, after_standings, extra=None):
    """(matching riders, listed riders) for one classification.

    The self-check this tool is gated on: does adding the derived finale move
    our cumulative totals CLOSER to PCS's own published classification? A
    derivation that cannot demonstrate that is not written.
    """
    off = after_standings.get(kind, {})
    if not off:
        return None
    src_file = os.path.join(HERE, f"{race}_{'sprint' if kind == 'POINTS' else 'kom'}_points.json")
    with open(src_file, encoding="utf-8") as f:
        arr = json.load(f).get(str(year), [])
    cur = {}
    for st in arr:
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

    print(f"{'year':<6}{'stage':<7}{'sprint riders/pts':<22}{'kom riders/pts':<20}notes")
    touched = 0
    for y in years:
        r = derive_year(race, y)
        if not r or r.get("skipped") or not r.get("filled"):
            continue
        # Drop any classification the fill cannot be shown to improve. Flat is
        # not proof the values are wrong — an edition can be short for other
        # reasons — but it is not proof they are right either, and this is
        # DERIVED data going into a file that has no per-value provenance.
        after_st = _after_cache.get((race, y), {})
        gains = {}
        for kind, key in KINDS.items():
            if key not in r["filled"]:
                continue
            b = agreement(race, y, key, kind, after_st)
            a = agreement(race, y, key, kind, after_st, r["filled"][key])
            if b and a and a[0] > b[0]:
                gains[key] = (b[0], a[0], a[1])
            else:
                r["filled"].pop(key)
                unproven.append((y, kind, b[0] if b else 0, a[0] if a else 0))
        if not r["filled"]:
            continue
        sp = r["filled"].get("sprint_points", {})
        km = r["filled"].get("kom_points", {})
        note = ""
        if r["negatives"]:
            note = f"{len(r['negatives'])} negative NOT written (penalty)"
        if r["implausible"]:
            note += f"  {len(r['implausible'])} over-ceiling NOT written"
        if r["no_baseline"]:
            note += f"  no baseline for {'/'.join(r['no_baseline'])}"
        print(f"{y:<6}{r['stage']:<7}"
              f"{f'{len(sp)} / {sum(sp.values())}':<22}"
              f"{f'{len(km)} / {sum(km.values())}':<20}{note}")
        touched += 1
        if args.apply:
            data = r["data"]
            for key, d in r["filled"].items():
                data[key] = d
            tmp = r["path"] + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, r["path"])
            record.setdefault(race, {})[str(y)] = {
                "stage": r["stage"], "slug": r["slug"],
                "sprint_riders": len(sp), "sprint_points": sum(sp.values()),
                "kom_riders": len(km), "kom_points": sum(km.values()),
                "method": "PCS classification after the final stage minus after the one before it",
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
