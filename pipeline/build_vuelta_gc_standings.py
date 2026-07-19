#!/usr/bin/env python3
"""
Build per-stage GC standings for Vuelta years from scraped PCS data.

Problem: PCS stage-result pages before 1998 embed GC standings for only a
handful of riders per stage (often just the leader), and the old ingest
"carry-forward" invented per-stage GC by replicating stale values. This script
derives real per-stage GC for every rider from actual scraped data only.

Sources, in trust order:
  1. AUTHORITATIVE — PCS's own per-stage GC: the GC/Timelag columns of
     stage-result rows plus the GC-standings tables scraped by
     scrape_vuelta_gc_pages.py (vuelta_scrapes/YEAR/gc_pages/*.json).
     These are exact (bonus-inclusive official standings) but sparse pre-1998.
  2. COMPUTED — each rider's cumulative sum of per-stage gaps ("score").
     Working in gap-space makes the day winners' absolute times cancel out.
     score is tied to real GC gaps through a per-day offset C[d] estimated
     from riders present in both (median). Computed gaps omit time bonuses
     (not published on old PCS pages), so:
  3. VALIDATION — every rider with authoritative entries is cross-checked:
     if computed and authoritative gaps ever disagree beyond TOL, the rider's
     computed values are dropped (their authoritative entries remain). A
     rider-stage with no derivable value gets NO entry — never an estimate.

Output: vuelta_scrapes/YEAR/gc_standings.json
  { "year": 1985, "stages": { "1": { "rider/slug": [gc_rank, gap_seconds], ... } } }
gc_rank may be null when coverage is too sparse to rank reliably; gap_seconds
is always real. Consumed by ingest_race.py. A per-year validation report is
printed; use --report for per-day detail.

Usage:
  python3 build_vuelta_gc_standings.py 1979-1997
  python3 build_vuelta_gc_standings.py --race giro 1909-1997
  python3 build_vuelta_gc_standings.py --all
"""

import json
import os
import re
import statistics
import sys
from glob import glob

HERE = os.path.dirname(os.path.abspath(__file__))
RACE = "vuelta"
if "--race" in sys.argv:
    RACE = sys.argv[sys.argv.index("--race") + 1]
    if RACE not in ("vuelta", "giro"):
        sys.exit(f"error: unknown race '{RACE}' (use vuelta or giro)")
SCRAPES_DIR = os.path.join(HERE, f"{RACE}_scrapes")

from race_common import parse_time_to_seconds, parse_int, parse_year_args  # noqa: E402

TOL = 5               # max seconds computed may deviate from authoritative
MAX_GAP = 4 * 3600    # larger values in a gap cell are absolute-time leakage
RANK_COVERAGE = 0.85  # emit computed ranks only at this share of active riders

# Riders out of the race. NOTE: "DF" is NOT here — PCS uses DF for riders who
# finished a stage without a recorded position/time (whole peloton on many
# historical stages); they remain in the race.
EXIT_STATUSES = {"DNF", "DNS", "OTL", "NP", "DSQ", "DEL"}


def numeric_stage_files(year: int) -> list[str]:
    files = glob(os.path.join(SCRAPES_DIR, str(year), "stage_*.json"))
    return sorted(files, key=lambda p: int(re.search(r"stage_(\d+)\.json$", p).group(1)))


def load_days(year: int) -> list[dict]:
    """One dict per race day in stage_number order:
    {n, rows, auth: {slug: (rank_or_None, gap)}, info}
    auth merges the rows' GC columns with the gc_pages GC-standings table.
    """
    days = []
    for path in numeric_stage_files(year):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        days.append({"n": d["n"], "rows": d.get("rows", []), "info": d.get("info", {})})

    for day in days:
        auth = {}
        for r in day["rows"]:
            if len(r) < 3 or not r[6]:
                continue
            rank = parse_int(r[1])
            gap = parse_time_to_seconds(r[2]) if r[2] else None
            if gap is not None and gap >= MAX_GAP:
                gap = None  # absolute time leaked into the gap column
            if rank == 1 and gap is None:
                gap = 0
            if rank is not None and gap is not None:
                auth[r[6]] = (rank, gap)
        day["auth"] = auth

    # Merge gc_pages: authoritative GC-standings tables per day.
    gp_dir = os.path.join(SCRAPES_DIR, str(year), "gc_pages")
    gc_pages = {}
    if os.path.isdir(gp_dir):
        for p in glob(os.path.join(gp_dir, "*.json")):
            if os.path.basename(p).startswith("_"):
                continue
            with open(p, encoding="utf-8") as f:
                gp = json.load(f)
            gc_pages[gp["slug"]] = gp

    if gc_pages:
        slug_list_path = os.path.join(gp_dir, "_slugs.json")
        if os.path.exists(slug_list_path):
            with open(slug_list_path) as f:
                slugs = [s for s in json.load(f) if s in gc_pages]
        else:
            slugs = list(gc_pages)

        used = set()
        slug_for_n = {}
        for day in days:
            date = day["info"].get("Date")
            finish = (day["info"].get("Finish") or "").strip().lower()
            match = None
            for s in slugs:
                if s in used:
                    continue
                gi = gc_pages[s]["info"]
                if gi.get("Date") == date and (gi.get("Finish") or "").strip().lower() == finish:
                    match = s
                    break
            if match is None:
                cands = [s for s in slugs if s not in used
                         and gc_pages[s]["info"].get("Date") == date]
                if len(cands) == 1:
                    match = cands[0]
            if match:
                used.add(match)
                slug_for_n[day["n"]] = match
        rem_days = [d for d in days if d["n"] not in slug_for_n]
        rem_slugs = [s for s in slugs if s not in used]
        if rem_days and len(rem_days) == len(rem_slugs):
            for d, s in zip(rem_days, rem_slugs):
                slug_for_n[d["n"]] = s

        for day in days:
            s = slug_for_n.get(day["n"])
            if not s:
                continue
            day["slug"] = s
            for rnk, _prev, slug, _name, time_txt in gc_pages[s].get("gc_rows", []):
                rank = parse_int(rnk)
                if rank is None or not slug:
                    continue
                if rank == 1:
                    day["auth"][slug] = (1, 0)
                else:
                    gap = parse_time_to_seconds(time_txt)
                    if gap is not None and gap < MAX_GAP:
                        day["auth"][slug] = (rank, gap)
    return days


def day_gaps_statuses(day: dict) -> tuple[dict, dict]:
    """rider -> stage gap seconds (winner = 0); rider -> status."""
    gaps = {}
    statuses = {}
    for r in day["rows"]:
        if len(r) < 15 or not r[6]:
            continue
        slug = r[6]
        rnk = r[0]
        if rnk in EXIT_STATUSES:
            statuses[slug] = rnk
            continue
        statuses[slug] = "FINISHED"
        if parse_int(rnk) == 1:
            # the winner's gap cell duplicates their absolute time — gap is 0
            gaps[slug] = 0
            continue
        if isinstance(r[14], str) and r[14].lstrip("+").startswith("*"):
            continue  # starred cells are bonus markers, not time gaps
        gap = parse_time_to_seconds(r[14])
        if gap is not None and gap < MAX_GAP:
            gaps[slug] = gap
    return gaps, statuses


def build_year(year: int, report: bool = False) -> dict | None:
    days = load_days(year)
    if not days:
        return None
    ndays = len(days)

    gaps_by_day = []
    status_by_day = []
    for day in days:
        g, s = day_gaps_statuses(day)
        gaps_by_day.append(g)
        status_by_day.append(s)

    first_seen, last_seen, exit_from = {}, {}, {}
    all_riders = set()
    for i, statuses in enumerate(status_by_day):
        for slug, st in statuses.items():
            all_riders.add(slug)
            first_seen.setdefault(slug, i)
            last_seen[slug] = i
            if st != "FINISHED" and slug not in exit_from:
                exit_from[slug] = i

    # --- Pass 1: forward-only scores for riders with complete chains from day 0.
    score = {}          # rider -> [score at each day or None]
    for slug in all_riders:
        vals = [None] * ndays
        if slug in gaps_by_day[0]:
            vals[0] = gaps_by_day[0][slug]
            for i in range(1, ndays):
                g = gaps_by_day[i].get(slug)
                if vals[i - 1] is None or g is None:
                    break
                vals[i] = vals[i - 1] + g
        score[slug] = vals

    # --- Passes 2+3, iterated to a fixpoint: estimate the per-day offset C[d]
    # (score-space minus gap-space) from riders having both a chained score and
    # an authoritative gap (median — robust to a few bonus-earning anchors),
    # then re-anchor broken chains from authoritative entries where C is known
    # and propagate forward/backward through known day-gaps. Each round can
    # make more days offset-estimable, so repeat until nothing changes.
    C = [None] * ndays
    c_spread = [None] * ndays
    for _round in range(6):
        changed = False
        for i, day in enumerate(days):
            pairs = []
            for slug, (rank, gap) in day["auth"].items():
                v = score[slug][i] if slug in score else None
                if v is not None:
                    pairs.append(v - gap)
            if pairs:
                new_c = statistics.median(pairs)
                if C[i] is None:
                    changed = True
                C[i] = new_c
                c_spread[i] = max(pairs) - min(pairs) if len(pairs) > 1 else 0

        for slug in all_riders:
            vals = score[slug]
            for i, day in enumerate(days):
                if vals[i] is None and C[i] is not None and slug in day["auth"]:
                    vals[i] = day["auth"][slug][1] + C[i]
                    changed = True
            for i in range(1, ndays):
                g = gaps_by_day[i].get(slug)
                if vals[i] is None and vals[i - 1] is not None and g is not None:
                    vals[i] = vals[i - 1] + g
                    changed = True
            for i in range(ndays - 2, -1, -1):
                g = gaps_by_day[i + 1].get(slug)
                if vals[i] is None and vals[i + 1] is not None and g is not None:
                    vals[i] = vals[i + 1] - g
                    changed = True
        if not changed:
            break

    # --- Pass 4: validation. Wherever a rider has both computed score and an
    # authoritative gap (C known), they must agree within TOL. One conflict
    # drops ALL the rider's computed values (bonus seconds are not in the
    # scraped data, so bonus earners fail here by design — better absent than
    # wrong). Authoritative entries always survive.
    suspects = set()
    for slug in all_riders:
        vals = score[slug]
        for i, day in enumerate(days):
            if C[i] is None or slug not in day["auth"]:
                continue
            v = vals[i]
            if v is None:
                continue
            if abs((v - C[i]) - day["auth"][slug][1]) > TOL:
                suspects.add(slug)
                break

    # --- Assembly.
    out_stages = {}
    stats = {"days": ndays, "auth": 0, "computed": 0, "dropped": len(suspects),
             "no_C_days": sum(1 for c in C if c is None), "no_rank_days": 0}
    for i, day in enumerate(days):
        auth = day["auth"]
        active = {r for r in all_riders
                  if first_seen.get(r, 10**9) <= i
                  and last_seen.get(r, -1) >= i
                  and exit_from.get(r, 10**9) > i}

        entries = {slug: [rank, gap] for slug, (rank, gap) in auth.items()}
        stats["auth"] += len(entries)

        computed = {}
        if C[i] is not None:
            for slug in active:
                if slug in auth or slug in suspects:
                    continue
                v = score[slug][i]
                if v is None:
                    continue
                gap = v - C[i]
                if gap < -TOL:
                    continue   # ahead of the known leader: contradiction
                computed[slug] = max(0, int(round(gap)))

        coverage = (len(computed) + len([r for r in auth if r in active])) / max(1, len(active))
        emit_ranks = coverage >= RANK_COVERAGE
        if computed and not emit_ranks:
            stats["no_rank_days"] += 1

        if computed:
            max_auth_rank = max((rk for rk, _ in auth.values() if rk), default=0)
            max_auth_gap = max((g for _, g in auth.values()), default=None)
            prev_rank_key = {}
            if i > 0:
                prev = out_stages.get(str(days[i - 1]["n"]), {})
                prev_rank_key = {s: e[0] for s, e in prev.items() if e[0]}
            ordered = sorted(computed.items(),
                             key=lambda kv: (kv[1], prev_rank_key.get(kv[0], 10**9), kv[0]))
            next_rank = max_auth_rank + 1
            for slug, gap in ordered:
                rank = None
                if emit_ranks and (max_auth_gap is None or gap >= max_auth_gap - TOL):
                    rank = next_rank
                    next_rank += 1
                entries[slug] = [rank, gap]
            stats["computed"] += len(computed)

        out_stages[str(day["n"])] = entries

        if report:
            print(f"    day {day['n']:>2}: auth={len(auth):3d} computed={len(computed):3d} "
                  f"active={len(active):3d} C={'—' if C[i] is None else int(C[i])} "
                  f"spread={c_spread[i] if c_spread[i] is not None else '—'}")

    return {"year": year, "stages": out_stages, "stats": stats}


def main():
    args = sys.argv[1:]
    report = "--report" in args
    years = parse_year_args(args)
    if not years and "--all" in args:
        years = sorted(
            int(e) for e in os.listdir(SCRAPES_DIR)
            if e.isdigit() and glob(os.path.join(SCRAPES_DIR, e, "stage_*.json"))
        )
    if not years:
        print("Usage: python3 build_vuelta_gc_standings.py YEAR|RANGE... | --all [--report]")
        sys.exit(1)

    for year in years:
        result = build_year(year, report=report)
        if result is None:
            print(f"{year}: no stage files")
            continue
        st = result.pop("stats")
        out_path = os.path.join(SCRAPES_DIR, str(year), "gc_standings.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        print(f"{year}: {st['days']} days | auth {st['auth']} + computed {st['computed']} "
              f"entries | {st['dropped']} riders dropped by validation | "
              f"{st['no_C_days']} days without offset | {st['no_rank_days']} days unranked")


if __name__ == "__main__":
    main()
