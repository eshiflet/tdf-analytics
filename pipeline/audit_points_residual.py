#!/usr/bin/env python3
"""
Measure and CATEGORISE the gap between our per-stage points and PCS's
published points/KOM classifications.

WHY. "The residual is upstream" was said twice in this repo and was wrong both
times — most of it turned out to be a missing finale, recoverable from PCS's
own cumulative standings (see derive_missing_stage_points.py). A number with no
breakdown invites that mistake, because anything unexplained can be filed under
it. This prints the breakdown instead.

Two modes:

  default     one fetch per edition. Compares our summed per-stage points to
              PCS's published final classification and reports the agreement
              rate. Cheap enough to run over the whole archive.

  --localize  one fetch per STAGE for the editions that disagree, which is what
              turns "7% disagree" into a cause. PCS publishes the cumulative
              classification on every stage page, so the per-stage delta can be
              compared against the award we scraped, and each disagreement
              lands in one of:

    PENALTY      the classification DROPS on some stage. A jury docked the
                 rider (relegation, irregular sprinting). PCS applies it to
                 the classification and shows nothing on the stage page, so we
                 are HIGH by the penalty. Giro 2016 lists two riders on -5,
                 i.e. a penalty exceeding everything they scored.
    SCALE        the classification's delta for a stage is a consistent
                 MULTIPLE of the award its own stage page lists — the Vuelta
                 2024's stage 19 gains 30/25/22/19 where the page says
                 20/17/15/13. PCS disagreeing with PCS; believing either page
                 is a choice, not a fix.
    JITTER       the award is credited to an adjacent stage. Cancels in the
                 total and is harmless; counted so it stops being mistaken for
                 a real gap.
    UNEXPLAINED  everything else, which is the number actually worth quoting.

Usage:
  python3 audit_points_residual.py --race giro
  python3 audit_points_residual.py --race vuelta 2024 --localize
"""

import argparse
import collections
import json
import os
import sys
import time

from race_common import exit_on_help, parse_year_args
import derive_missing_stage_points as D
import scrape_classifications as SC

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = ("POINTS", "KOM")


def our_totals(race, year, kind):
    f = os.path.join(HERE, f"{race}_{'sprint' if kind == 'POINTS' else 'kom'}_points.json")
    with open(f, encoding="utf-8") as fh:
        arr = json.load(fh).get(str(year), [])
    c = collections.Counter()
    for st in arr:
        for r, v in st.items():
            c[r] += v
    return c


def published(race, year):
    """PCS's final classifications, from the race's own /gc page."""
    url = f"https://www.procyclingstats.com/race/{D.PCS_SLUG[race]}/{year}/gc"
    try:
        html = SC.fetch(url)
    except Exception:
        return {}
    blocks = SC.tab_blocks(html) if html else {}
    return {k: {r[1]: r[4] for r in SC.parse_rows(blocks[k]) if r[4] is not None}
            for k in KINDS if k in blocks}


def localize(race, year, kind, offenders):
    """Classify each disagreeing rider by walking PCS's own stage-by-stage
    standings. Returns Counter of category -> riders."""
    files = D.stage_files(race, year)
    nums = sorted(files)
    lo = nums[0]
    f = os.path.join(HERE, f"{race}_{'sprint' if kind == 'POINTS' else 'kom'}_points.json")
    with open(f, encoding="utf-8") as fh:
        arr = json.load(fh).get(str(year), [])
    ours = {lo + i: d for i, d in enumerate(arr)}

    stand = {}
    for n in nums:
        stand[n] = D.standings(race, year, files[n][1])
        time.sleep(0.3)

    cats = collections.Counter()
    prev = None
    penalty, scale, jitter = set(), set(), set()
    for n in nums:
        a = stand[n].get(kind, {})
        if not a:
            continue
        if prev is None:
            prev = n
            continue
        b = stand[prev].get(kind, {})
        if b:
            aw = ours.get(n, {})
            for r in offenders:
                if r not in a or r not in b:
                    continue
                d, o = a[r] - b[r], aw.get(r, 0)
                if d == o:
                    continue
                if d < 0:
                    penalty.add(r)
                elif o and d and abs(d / o - 1.5) < 0.12:
                    scale.add(r)
                else:
                    jitter.add(r)
        prev = n
    for r in offenders:
        if r in penalty:
            cats["PENALTY"] += 1
        elif r in scale:
            cats["SCALE"] += 1
        elif r in jitter:
            cats["JITTER"] += 1
        else:
            cats["UNEXPLAINED"] += 1
    return cats


def main(argv=None):
    exit_on_help(__doc__)
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=("giro", "vuelta"), required=True)
    ap.add_argument("years", nargs="*")
    ap.add_argument("--localize", action="store_true")
    args = ap.parse_args(argv)

    race = args.race
    root = os.path.join(HERE, f"{race}_scrapes")
    wanted = parse_year_args(args.years) if args.years else None
    years = sorted(int(d) for d in os.listdir(root)
                   if d.isdigit() and os.path.isdir(os.path.join(root, d)))
    if wanted:
        years = [y for y in years if y in wanted]

    tot_match = tot_listed = 0
    cats = collections.Counter()
    print(f"{'year':<6}{'POINTS':<16}{'KOM':<16}{'disagreeing riders'}")
    for y in years:
        pub = published(race, y)
        if not pub:
            continue
        line, offenders = f"{y:<6}", {}
        for kind in KINDS:
            off = pub.get(kind, {})
            if not off:
                line += f"{'-':<16}"
                continue
            mine = our_totals(race, y, kind)
            bad = [r for r, v in off.items() if mine.get(r, 0) != v]
            offenders[kind] = bad
            tot_match += len(off) - len(bad)
            tot_listed += len(off)
            line += f"{f'{len(off)-len(bad)}/{len(off)}':<16}"
        n_bad = sum(len(v) for v in offenders.values())
        print(line + (str(n_bad) if n_bad else ""))
        sys.stdout.flush()
        if args.localize:
            for kind, bad in offenders.items():
                if bad:
                    c = localize(race, y, kind, bad)
                    cats.update(c)
                    print(f"        {kind}: " + "  ".join(f"{k}={v}" for k, v in c.most_common()))
        time.sleep(0.5)

    if tot_listed:
        print(f"\n{race}: {tot_match}/{tot_listed} exact ({100*tot_match/tot_listed:.1f}%), "
              f"{tot_listed-tot_match} disagree")
    if cats:
        tot = sum(cats.values())
        print("\nwhere the disagreements come from:")
        for k, v in cats.most_common():
            print(f"   {k:<14}{v:>5}  ({100*v/tot:.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
