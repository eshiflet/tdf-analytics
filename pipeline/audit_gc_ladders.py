#!/usr/bin/env python3
"""
Triage the stages whose GC ladder runs backwards, into a worklist for a re-scrape.

OFFLINE AND READ-ONLY. It opens cycling.db, fetches nothing and writes nothing.

WHY THIS EXISTS RATHER THAN A REPAIR SCRIPT

`validate_db.check_gc_gap_monotonicity` reports 342 stages holding a gap that
shrinks as the rank grows, which no race can produce. The obvious next step —
correct them from the surrounding ranks — was tried on 2026-09-19 and does not
work, and the reason is worth keeping:

  * RANK IS NOT RECOVERABLE FROM GAP. Riders on equal aggregate time hold
    DIFFERENT ranks, separated by a tiebreak (sum of placings) we do not store.
    Deriving rank from gap alone moves 71,806 rows — 18% of the archive.
  * GAP IS NOT RECOVERABLE FROM RANK, for the same reason in reverse.
  * SO THE LADDER PROVES A ROW IS WRONG WITHOUT SAYING WHICH VALUE IS RIGHT.
    Tour 1978 st8 stores rank 28 at 289s and rank 29 at 4s. One is wrong. The
    ladder cannot say whether 4 should read 289+, or 289 should read <4.

What the ladder CAN do is name the row, and bound it. That turns a re-scrape of
342 whole classifications into 144 single-value lookups plus a smaller set that
genuinely needs the page. That is this script's whole job.

THE THREE VERDICTS

  ONE ROW  one backwards step, and removing exactly one of its two rows makes
           the ladder monotone again. That row is the suspect, and its true
           value is bounded by its neighbours — the tightest result available
           offline. 144 stages.
  PAIR     one backwards step, but removing EITHER row would fix it, so the
           evidence does not choose between them. 75 stages.
  LADDER   several steps, or removing neither row is enough. The corruption is
           not one cell and the classification needs re-fetching whole. 123.

A separate signature is called out where it appears: some stages hold TWO
interleaved classifications, one of them with gc_rank copied from stage_rank.
Tour 1987 stage 1 stores ranks 13-18 twice, once at a flat 23s with
rank==stage_rank and once at the real prologue gaps. That is not a wrong value
to correct but a contaminating ladder to remove, so it is flagged rather than
folded into the counts above.

THE BLIND SPOT, STATED UP FRONT: a ladder can be self-contradictory and still
ascend. Where two riders share a rank with different gaps that both fall inside
the surrounding window, nothing here sees it — 14 stages, reported instead by
validate_db.check_gc_rank_gap_consistency. Run both.

Usage:
  python3 audit_gc_ladders.py
  python3 audit_gc_ladders.py --race tour --year 1978
  python3 audit_gc_ladders.py --verdict ONE_ROW --limit 20
  python3 audit_gc_ladders.py --json gc_ladder_worklist.json
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

import gc_source

from race_common import DB_PATH, exit_on_help

RACE_ALIASES = {
    "tour": "Tour de France", "tdf": "Tour de France",
    "giro": "Giro d'Italia", "vuelta": "Vuelta a España",
}


def backwards_steps(ladder):
    """Indices i where ladder[i+1] is stored CLOSER to the leader than ladder[i].

    `ladder` is a list of (rank, gap, disqualified, rider_id) sorted by
    (rank, gap) — the same ordering validate_db uses, so a tie's smaller gap
    comes first and a tie is only counted when it disagrees with its NEIGHBOURS.

    Exempt for the same reason as there: out of rank 1 PCS lists the stripped
    and the promoted rider together and the promoted one keeps the gap he held
    to the man ahead, and a row marked `disqualified` OR `time_adjusted` carries
    a classification the row beside it is not on. The third element of each
    tuple is that combined flag, not `disqualified` alone — a time-adjusted
    rider was AWARDED a time he did not race, so PCS's own ladder steps
    backwards there and ours is right to follow it.
    """
    return [i for i, (a, b) in enumerate(zip(ladder, ladder[1:]))
            if b[1] < a[1] and a[0] != 1 and not a[2] and not b[2]]


def classify(ladder):
    """(verdict, suspects, window) for one stage's ladder.

    `suspects` holds the rows the evidence implicates — one for ONE ROW, two for
    PAIR, empty for LADDER. `window` is the (low, high) the suspect's true gap
    must fall between, or None where the ladder cannot bound it.
    """
    steps = backwards_steps(ladder)
    if not steps:
        return None, [], None
    # A ladder with SEVERAL backwards steps needs no separate branch, and the
    # early return that used to be here was unreachable in effect: removing one
    # row of the first step cannot clear a step further up, because that step's
    # own two rows are untouched — and where the two steps are adjacent the
    # three gaps descend, so whichever of the first pair goes, the survivors
    # still descend. Either way both removals fail and the evidence test below
    # returns LADDER on its own. Deleting the branch keeps the verdict decided
    # in one place, and the test suite can then reach the code that decides it.
    i = steps[0]
    a, b = ladder[i], ladder[i + 1]
    # Drop one row at a time: if the ladder comes good without it, that row is
    # the one carrying the contradiction.
    a_alone = not backwards_steps(ladder[:i] + ladder[i + 1:])
    b_alone = not backwards_steps(ladder[:i + 1] + ladder[i + 2:])
    if a_alone and b_alone:
        return "PAIR", [a, b], None
    if not a_alone and not b_alone:
        return "LADDER", [], None
    suspect = a if a_alone else b
    # The suspect sits between the rows that survive it, so its real gap does
    # too. Either side may be missing at the ends of a stored classification.
    before = ladder[i - 1][1] if (a_alone and i > 0) else (
        ladder[i][1] if not a_alone else None)
    after = ladder[i + 1][1] if a_alone else (
        ladder[i + 2][1] if i + 2 < len(ladder) else None)
    return "ONE ROW", [suspect], (before, after)


def mirror_ranks(rows_by_rank):
    """Ranks holding both a `gc_rank == stage_rank` row and a row that is not.

    The two-interleaved-classifications signature: one ladder is the real GC and
    the other has had its rank copied from the stage result. Three or more such
    ranks in one stage is past coincidence — a bunch finish legitimately puts
    many riders at rank == stage_rank, but not while another ladder occupies the
    same numbers.
    """
    # No explicit "more than one row" test: a single row cannot be both a
    # mirror and not one, so the two clauses already exclude it. Stating it
    # again would be a condition no input can ever fail.
    return [rk for rk, rows in rows_by_rank.items()
            if any(s == rk for _, s in rows) and any(s != rk for _, s in rows)]



# ── The source page ─────────────────────────────────────────────────────────
# gc_source does the reading, the parsing and — the part that matters — the
# check that the stored page really is this stage's page. It was three copies
# of that logic before, and the copy in this file had no verification at all,
# which is how the 1992 Giro was reported broken when it is fine.


def source_verdict(ladder):
    """Whether the stored page explains this stage's backwards ladder.

    "EXPLAINED" means PCS itself marks a row here — a time it awarded rather
    than timed — so the contradiction is the source's and the values are
    correct as stored. It deliberately does NOT check that the marked row is
    the one we implicated: a stage can hold several marks, and one anywhere is
    enough to say the shape is PCS's.

    "NO SOURCE" covers a missing page AND a page that failed verification,
    because both mean the same thing to a reader: nothing here has been
    checked. Folding either into UNEXPLAINED would put stages on a worklist
    that nothing has looked at, beside stages that something has.
    """
    if ladder is None:
        return "NO SOURCE"
    return "EXPLAINED" if any(s for _, _, s in ladder.values()) else "UNEXPLAINED"


def load(conn, race=None, year=None):
    sql = """
        SELECT s.stage_id, ra.name, re.year, s.stage_number, sr.gc_rank,
               sr.gc_gap_seconds, sr.disqualified OR sr.time_adjusted,
               sr.rider_id, sr.stage_rank, s.source_slug
          FROM stage_results sr
          JOIN stages s ON s.stage_id = sr.stage_id
          JOIN race_editions re ON re.edition_id = s.edition_id
          JOIN races ra ON ra.race_id = re.race_id
         WHERE sr.gc_rank IS NOT NULL AND sr.gc_gap_seconds IS NOT NULL"""
    params = []
    if race:
        sql += " AND ra.name = ?"
        params.append(race)
    if year:
        sql += " AND re.year = ?"
        params.append(year)
    stages, meta, ranks = defaultdict(list), {}, defaultdict(lambda: defaultdict(list))
    for sid, name, yr, num, rk, gap, dq, rid, srk, slug in conn.execute(sql, params):
        stages[sid].append((rk, gap, dq, rid))
        ranks[sid][rk].append((gap, srk))
        meta[sid] = (name, yr, num, slug)
    return stages, meta, ranks


def group_one_row_runs(one_row):
    """Collapse ONE ROW stages into (race, year, rider) -> [(stage, gap, window)].

    A stage count overstates how much is WRONG. Tour 1966 contributes seven
    stages to the worklist and one defect: Herman Van Springel holds a gap
    exactly one second short of his rank on stages 4 through 10, entering at a
    split day and carried forward untouched. Read as seven, it invites seven
    investigations of the same number.

    Returns both maps — every rider-edition, and the subset spanning more than
    one stage — because the first is the honest count of distinct causes and
    the second is the part worth printing.
    """
    by_rider = defaultdict(list)
    for d in one_row:
        s0 = d["suspects"][0]
        by_rider[(d["race"], d["year"], s0["rider_id"])].append(
            (d["stage"], s0["gc_gap_seconds"], d["window"]))
    runs = {k: sorted(v) for k, v in by_rider.items() if len(v) > 1}
    return by_rider, runs


def main():
    exit_on_help(__doc__)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--race", help="tour | giro | vuelta")
    ap.add_argument("--year", type=int)
    ap.add_argument("--verdict", choices=["ONE_ROW", "PAIR", "LADDER"],
                    help="show only this verdict")
    ap.add_argument("--limit", type=int, default=25,
                    help="stages to print per verdict (default 25; 0 for all)")
    ap.add_argument("--json", metavar="PATH", help="write the full worklist")
    args = ap.parse_args()

    race = RACE_ALIASES.get((args.race or "").lower(), args.race)
    conn = sqlite3.connect(DB_PATH)
    stages, meta, ranks = load(conn, race, args.year)

    found = defaultdict(list)
    for sid, rows in stages.items():
        verdict, suspects, window = classify(sorted(rows))
        if not verdict:
            continue
        race_name, yr, num, slug = meta[sid]
        page = gc_source.gc_page(race_name, yr, num, slug)
        ladder = gc_source.gc_ladder(page) if page else None
        found[verdict].append({
            "race": race_name, "year": yr, "stage": num,
            "verdict": verdict, "source": source_verdict(ladder),
            "suspects": [{"rider_id": s[3], "gc_rank": s[0], "gc_gap_seconds": s[1]}
                         for s in suspects],
            "window": list(window) if window else None,
            "interleaved_ranks": len(mirror_ranks(ranks[sid])),
        })

    order = ["ONE ROW", "PAIR", "LADDER"]
    total = sum(len(found[v]) for v in order)
    if not total:
        print(f"No GC ladder runs backwards{' here' if race or args.year else ''}.")
        conn.close()
        return 0

    for verdict in order:
        items = sorted(found[verdict], key=lambda d: (d["race"], d["year"], d["stage"]))
        if args.verdict and args.verdict.replace("_", " ") != verdict:
            continue
        if not items:
            continue
        print(f"\n{'─' * 78}\n{verdict}  ({len(items)} stage(s))\n{'─' * 78}")
        shown = items if args.limit == 0 else items[:args.limit]
        for d in shown:
            head = f"{d['race']} {d['year']} st{d['stage']}"
            if d["source"] == "EXPLAINED":
                print(f"  {head:<28} PCS marks a time_adjusted rider here — the values "
                      "are correct as stored")
                continue
            if d["verdict"] == "ONE ROW":
                s = d["suspects"][0]
                lo, hi = d["window"]
                bound = ("between {}s and {}s".format(lo, hi) if lo is not None and hi is not None
                         else f"at least {lo}s" if lo is not None
                         else f"at most {hi}s" if hi is not None else "unbounded")
                print(f"  {head:<28} {s['rider_id']} at rank {s['gc_rank']} stores "
                      f"{s['gc_gap_seconds']}s; the ladder needs {bound}")
            elif d["verdict"] == "PAIR":
                x, y = d["suspects"]
                print(f"  {head:<28} rank {x['gc_rank']}={x['gc_gap_seconds']}s "
                      f"({x['rider_id']}) or rank {y['gc_rank']}={y['gc_gap_seconds']}s "
                      f"({y['rider_id']}) — the ladder does not choose")
            else:
                extra = (f"; {d['interleaved_ranks']} rank(s) hold two ladders"
                         if d["interleaved_ranks"] >= 3 else "")
                print(f"  {head:<28} needs the whole classification{extra}")
        if args.limit and len(items) > args.limit:
            print(f"  ... and {len(items) - args.limit} more (--limit 0 for all)")

    interleaved = sum(1 for v in order for d in found[v] if d["interleaved_ranks"] >= 3)
    src = Counter(d["source"] for v in order for d in found[v])
    print(f"\n{total} stage(s) with a backwards GC ladder: "
          + ", ".join(f"{len(found[v])} {v}" for v in order) + ".")
    print(f"Against the STORED source pages: {src['EXPLAINED']} explained by a "
          f"time PCS marks as awarded, {src['UNEXPLAINED']} unexplained, "
          f"{src['NO SOURCE']} with no page on disk.")
    if src["EXPLAINED"]:
        print("An EXPLAINED stage needs no repair to its values — PCS awarded a "
              "rider a time he did not race, and we store the time and the place "
              "faithfully. What is lost is the marker that says so, which is why "
              "the ladder reads as a contradiction downstream.")
    if interleaved:
        print(f"{interleaved} of them hold TWO interleaved classifications, one with "
              "gc_rank copied from stage_rank. Those are a ladder to remove, not a "
              "value to correct — check the source before touching either.")
    # A stage count overstates how much is WRONG. One rider carrying a bad gap
    # for a week of racing is one defect, reported seven times, and a worklist
    # that says "18 stages" invites eighteen separate investigations of it.
    by_rider, runs = group_one_row_runs(found["ONE ROW"])
    if by_rider:
        print(f"\nThose {len(found['ONE ROW'])} ONE ROW stages are "
              f"{len(by_rider)} distinct rider-edition(s); "
              f"{len(runs)} of them {'spans' if len(runs)==1 else 'span'} more than one stage.")
        for (race_name, yr, rid), v in sorted(runs.items(), key=lambda x: -len(x[1])):
            stages_in = [st for st, _, _ in v]
            stored = sorted({g for _, g, _ in v})
            short = sorted({w[0] - g for _, g, w in v if w and w[0] is not None})
            # A single shortfall across every stage of a run is the tell: the
            # rider is carrying one wrong number forward, not failing anew each
            # day. Tour 1966's Van Springel is 1s short on all seven.
            tail = (f", every one short by exactly {short[0]}s"
                    if len(short) == 1 else f", short by {short}s")
            print(f"  {race_name} {yr} {rid}: stages {stages_in}, "
                  f"stored {stored}{tail}")
        print("  Check the earliest stage of a run first — a gap that is wrong "
              "on day one and carried forward is one repair, not several.")

    print("Nothing was fetched and nothing was written. A ONE ROW verdict names the "
          "row to check, never the value to store: confirm it against the source "
          "page, and see feedback_no_fabricated_data before filling one in.")
    print("This cannot see a self-contradicting ladder that still ascends — run "
          "validate_db.py for those.")

    if args.json:
        payload = [d for v in order for d in found[v]]
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, ensure_ascii=False)
        print(f"\nwrote {len(payload)} stage(s) to {args.json}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
