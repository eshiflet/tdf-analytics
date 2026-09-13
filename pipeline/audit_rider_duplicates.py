#!/usr/bin/env python3
"""
Find riders already in the database whose ids are typo-variants of each other.

link_gravel_riders.py answers the other half of this question — does an
INCOMING name belong to an existing rider — and answers it strictly, because a
wrong merge fuses two careers and nothing downstream can tell. This script asks
about pairs that are already stored: `aaron-gammel` beside `aaron-gammell`,
`dennis-barret` beside `dennis-barrett`, `julius-thallmann` beside
`julius-thalmann`.

They arise two ways. PCS renames a rider and a partial re-ingest leaves the old
id holding the editions not yet rebuilt (see "PCS renames things, and the
database does not notice"). And Athlinks takes whatever an entrant typed at
registration, so the same person appears with and without a middle initial
across years.

IT NEVER MERGES ANYTHING. It classifies and prints, because the evidence that
settles one of these is usually outside the database — a Wikipedia article, a
rider's page on cyclingflash or PCS — and a script cannot read that. See
DATA_SOURCES.md for how to reach those.

TWO SUFFIXES THAT ARE MEANING, NOT NOISE, and are never treated as typos:
  * PCS's numeric disambiguator. `alessandro-fantini` and
    `alessandro-fantini-1` are two different people PCS is deliberately
    separating. Collapsing them would be the expensive error, in reverse.
  * PCS's roman numerals. `gilbert-desmet-i` and `gilbert-de-smet-ii` are two
    real riders of the same family.

Usage:
  python3 audit_rider_duplicates.py              # all groups, classified
  python3 audit_rider_duplicates.py --same       # only the confident ones
  python3 audit_rider_duplicates.py --json out.json
"""

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict

from race_common import DB_PATH, load_rider_separations, load_rider_splits

# PCS's own disambiguators. Stripped only so two ids can be COMPARED; a pair
# that differs by nothing else is two people and is dropped, never reported.
_PCS_NUM = re.compile(r"-?\d+$")
_PCS_ROMAN = re.compile(r"-(i{1,3}|iv|v)$")
# A middle initial as its own slug segment: ben-a-anderson vs ben-anderson.
_INITIAL = re.compile(r"-[a-z]-")
# Adjacent careers can still be two people; 40 years apart is not one career.
CAREER_SPAN = 25


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


def base(slug: str) -> str:
    """The id with PCS's deliberate disambiguators removed."""
    return _PCS_NUM.sub("", _PCS_ROMAN.sub("", slug))


def collapse(slug: str) -> str:
    """Fold to the shape a typo cannot change: no accents, no punctuation, no
    doubled letters. 'thallmann' and 'thalmann' both become 'thalman'."""
    return re.sub(r"(.)\1+", r"\1", re.sub(r"[^a-z]", "", fold(slug)))


SEPARATED = load_rider_separations()
# The halves of a deliberate split share a name EXACTLY, never share a stage,
# and so score as the most confident SAME this heuristic can produce. Without
# consulting rider_splits.json the next --apply fuses them back together and
# the split disappears silently — the same way an unrecorded separation gets
# re-merged, which is what SEPARATED above exists to stop.
SPLIT_HALVES = {
    frozenset((src.removeprefix("rider/"), rule["rider_id"].removeprefix("rider/"))): rule
    for (src, _race, _year), rule in load_rider_splits().items()
}


def classify(a: dict, b: dict) -> tuple[str, str]:
    """(verdict, why). Deliberately conservative: SAME only where two
    independent signals agree, DIFFERENT where one positively separates
    them, REVIEW for everything else."""
    # A pair somebody already examined and ruled apart. Without this the
    # heuristic proposes it again on every run, and the next --apply re-merges
    # a decision that was already made — recording only the merges remembers
    # half the work.
    pair = frozenset((a["id"].removeprefix("rider/"), b["id"].removeprefix("rider/")))
    if pair in SEPARATED:
        return "SETTLED", "ruled different people on " + SEPARATED[pair]["decided"]
    if pair in SPLIT_HALVES:
        return "SETTLED", ("one id split into two people — see rider_splits.json; "
                           "merging these would undo that split")

    na, nb = a["nat"], b["nat"]
    if na and nb and na != nb:
        return "DIFFERENT", f"nationalities differ ({na} vs {nb})"

    spans = [x for x in (a["span"], b["span"]) if x]
    if len(spans) == 2:
        gap = max(spans[0][0], spans[1][0]) - min(spans[0][1], spans[1][1])
        if gap > CAREER_SPAN:
            return "DIFFERENT", f"careers {gap} years apart, longer than one"

    only_initial = _INITIAL.sub("-", a["base"]) == _INITIAL.sub("-", b["base"])
    if only_initial and na and nb and na == nb:
        return "SAME", "same nationality; differs only by a middle initial"
    if na and nb and na == nb and len(spans) == 2:
        return "SAME", "same nationality, careers within one lifetime"
    if not na or not nb:
        return "REVIEW", "one side has no nationality — needs an outside source"
    return "REVIEW", "no signal separates or joins them"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--same", action="store_true", help="only confident matches")
    ap.add_argument("--json", help="write the groups to this file")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    riders = {}
    for r in cur.execute("SELECT rider_id, full_name, nationality_code FROM riders"):
        slug = r["rider_id"].removeprefix("rider/")
        riders[r["rider_id"]] = {
            "id": r["rider_id"], "slug": slug, "base": base(slug),
            "name": r["full_name"], "nat": r["nationality_code"],
        }
    for rid, d in riders.items():
        row = cur.execute(
            """SELECT COUNT(*) n, MIN(e.year) lo, MAX(e.year) hi
                 FROM stage_results sr JOIN stages s ON s.stage_id = sr.stage_id
                 JOIN race_editions e ON e.edition_id = s.edition_id
                WHERE sr.rider_id = ?""", (rid,)).fetchone()
        d["results"] = row["n"]
        d["span"] = (row["lo"], row["hi"]) if row["lo"] else None

    buckets = defaultdict(list)
    for d in riders.values():
        buckets[collapse(d["base"])].append(d)

    groups = []
    for key, members in sorted(buckets.items()):
        if len({m["base"] for m in members}) < 2:
            continue          # differ only by a PCS disambiguator: two people
        members.sort(key=lambda m: -m["results"])
        verdict, why = classify(members[0], members[1])
        groups.append({"key": key, "verdict": verdict, "why": why,
                       "members": [{k: m[k] for k in ("id", "name", "nat", "results", "span")}
                                   for m in members]})

    order = {"SAME": 0, "REVIEW": 1, "DIFFERENT": 2, "SETTLED": 3}
    groups.sort(key=lambda g: (order[g["verdict"]], g["key"]))
    shown = [g for g in groups if not args.same or g["verdict"] == "SAME"]

    for g in shown:
        print(f"[{g['verdict']:<9}] {g['key']}  — {g['why']}")
        for m in g["members"]:
            span = f"{m['span'][0]}-{m['span'][1]}" if m["span"] else "no results"
            print(f"             {m['id']:<36} {str(m['name'])[:24]:<26} "
                  f"{m['results']:>4} res  {span:<11} nat={m['nat']}")
    counts = {v: sum(1 for g in groups if g["verdict"] == v) for v in order}
    print(f"\n{len(groups)} group(s): " + ", ".join(f"{v} {n}" for v, n in counts.items()))
    print("\nNothing was merged. A SAME verdict is a lead, not a decision — confirm "
          "against an outside source (Wikipedia, cyclingflash, the rider's PCS page; "
          "see DATA_SOURCES.md) before fusing two careers, because nothing "
          "downstream can tell a wrong merge from a right one.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(groups, f, indent=1, ensure_ascii=False)
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
