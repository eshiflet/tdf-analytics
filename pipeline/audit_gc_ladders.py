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
    to the man ahead, and a row marked `disqualified` carries the classification
    it was removed from on either side of a step.
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


# ── The source page, which is already on disk ───────────────────────────────
# Read from the scrape artifacts rather than the network: 288 of the 342
# affected stages have their GC page stored under <race>_scrapes/<year>/
# gc_pages/<source_slug>.json, so the question "what does PCS say" is offline.
#
# ALWAYS BY source_slug, NEVER by stage_number. The 1978 Tour opens with a
# prologue, so its stage 8 is PCS's `stage-7`, and reading stage-8.json puts a
# different rider on every row — which is how this was nearly mis-reported.

SCRAPE_DIR = {"Tour de France": "tour_scrapes", "Giro d'Italia": "giro_scrapes",
              "Vuelta a España": "vuelta_scrapes"}

# The repeated unit must contain a colon. Without that, a bare "11" reads as
# "1" doubled and an 11-second gap silently becomes 1 — every real cell is
# h:mm:ss or m:ss, so requiring the colon costs nothing and closes that.
_DOUBLED = re.compile(r"\*?((?:\d+:)+\d{2})\1")


def source_seconds(cell):
    """(seconds, starred) for one PCS gap cell, or (None, starred) if unreadable.

    Three shapes appear in 43,088 stored cells and no others:

      "10:42"        plain
      "*0:040:04"    the visible text and PCS's hidden sort span, concatenated
                     by the scraper, with the asterisk PCS prints on the
                     visible one
      ""             no published gap

    The asterisk is the whole reason this function returns a second value. PCS
    prints it on a rider whose PLACE was changed by the jury while his TIME was
    not — "Tim Merlier relegated from 2nd to 89th" is the Giro 2024 stage 11
    case, and the page carries a Penalties & Fines tab saying so. His stored
    time is then smaller than that of riders now ranked above him, which is
    exactly the backwards ladder this script triages, and it is PCS's own data
    rather than a defect of ours.
    """
    cell = (cell or "").strip()
    starred = cell.startswith("*")
    m = _DOUBLED.fullmatch(cell)
    if m:
        cell = m.group(1)
    cell = cell.lstrip("*+")
    if not re.fullmatch(r"\d+(?::\d{2})*", cell):
        return None, starred
    total = 0
    for part in cell.split(":"):
        total = total * 60 + int(part)
    return total, starred


def source_ladder(race, year, slug):
    """{rider_id: (rank, seconds, starred)} from the stored GC page, or None.

    The leading row carries the leader's ABSOLUTE time, not a gap, so it is
    read as zero rather than parsed.
    """
    directory = SCRAPE_DIR.get(race)
    if not directory or not slug:
        return None
    path = os.path.join(directory, str(year), "gc_pages", f"{slug}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f).get("gc_rows") or []
    except (ValueError, OSError):
        return None
    if not rows:
        return None
    out = {}
    for i, r in enumerate(rows):
        seconds, starred = (0, False) if i == 0 else source_seconds(r[4])
        out[r[2]] = (int(r[0]), seconds, starred)
    return out


def source_verdict(ladder):
    """Whether the stored page explains this stage's backwards ladder.

    "EXPLAINED" means PCS itself marks a row here, so the contradiction is the
    jury's and the values are correct as stored — nothing to repair but the
    lost marker. It deliberately does NOT check that the marked row is the same
    one we implicated: a stage can hold several relegations, and a marker
    anywhere in the ladder is enough to say the shape is PCS's.
    """
    if ladder is None:
        return "NO SOURCE"
    return "EXPLAINED" if any(s for _, _, s in ladder.values()) else "UNEXPLAINED"

def load(conn, race=None, year=None):
    sql = """
        SELECT s.stage_id, ra.name, re.year, s.stage_number, sr.gc_rank,
               sr.gc_gap_seconds, sr.disqualified, sr.rider_id, sr.stage_rank,
               s.source_slug
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
        ladder = source_ladder(race_name, yr, slug)
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
                print(f"  {head:<28} PCS marks a relegated rider here — the values "
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
          f"relegation PCS marks itself, {src['UNEXPLAINED']} unexplained, "
          f"{src['NO SOURCE']} with no page on disk.")
    if src["EXPLAINED"]:
        print("An EXPLAINED stage needs no repair to its values — PCS moved a "
              "rider's PLACE and left his TIME, and we store both faithfully. What "
              "is lost is the marker that says so, which is why the ladder reads as "
              "a contradiction downstream.")
    if interleaved:
        print(f"{interleaved} of them hold TWO interleaved classifications, one with "
              "gc_rank copied from stage_rank. Those are a ladder to remove, not a "
              "value to correct — check the source before touching either.")
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
