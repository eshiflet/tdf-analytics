#!/usr/bin/env python3
"""
Find gravel riders stored under more than one id, using Athlinks' OWN racer id.

audit_rider_duplicates.py asks whether two stored ids LOOK like one person, and
has to be conservative because the only evidence it has is a name. This script
asks a different question with a better answer already in the data: every
Athlinks results row carries `racer_id`, the timer's persistent identifier for
a human being, and where two of our ids sit on rows sharing one racer_id, the
SOURCE is asserting they are one person. That is stronger than any name,
locality or age test we can run, and nothing read it for months —
link_gravel_riders.py dismisses it in a comment as "null on most rows", which
is true and beside the point. It is null on 78% of rows and decisive on the
rest.

Written 2026-09-18 after "Torbj R" turned out to be Torbjørn Andre Røed filed
as a third copy of himself. The first run of this sweep found 21 fractured
riders; six were already aliased, fifteen were merged that day.

IT NEVER MERGES ANYTHING, for the same reason its sibling does not: a merge is
a claim about a person, and a wrong one fuses two careers with nothing
downstream able to tell. It prints, and `--json` feeds
merge_rider_duplicates.py, which applies the claims a human has agreed to.

WHY THE TRUNCATED NAMES ARE THE CASE THAT MATTERS. Athlinks cuts `displayName`
at the first non-ASCII byte, and it does so per REGISTRATION, not per rider —
`Torbjørn Andre Røed` becomes `Torbj R` and `Andrew L'Esperance` becomes
`Andrew L` on some entries while the same season spells them correctly on
others. Our slugify then mints an id from the wreckage. No name-similarity
test can pair `torbj-r` with `torbjorn-andre-roed`; the racer id does it
without needing to.

THE TWO DIRECTIONS ARE NOT EQUALLY STRONG, which is why they print separately:

  * One racer_id across SEVERAL of our ids  -> the source says one person.
    Strong. This is the section that produces merges.
  * Several racer_ids on ONE of our ids     -> a LEAD about a possible
    conflation, and nothing more. A person can hold two Athlinks accounts, and
    some clearly do — rider/ryan-petry's two ids are 84638762 and 84638767,
    five apart, which is one person registering twice rather than two people.
    So these are printed as REVIEW and never given a verdict.

A NATIONALITY CLASH DOES NOT SEPARATE THESE, which is the opposite of what
audit_rider_duplicates.py does with the same signal, and the difference is
deliberate. Athlinks' `country` is where the entrant LIVES, not their passport:
Torbjørn Røed rode as `us` from Grand Junction and `no` from Asker, and Yuki
Ikeda reads `us` for years of Leadvilles before `jp` appears. Against a mere
name match a nationality clash is good evidence of two people; against the
source's own racer id it is good evidence of a rider who moved house. So it
downgrades the pair to REVIEW rather than ruling it DIFFERENT.

THE BLIND SPOT, stated because it cost a find. 78% of rows carry no racer_id at
all, and a pair whose rows all lack one is invisible here. Nathan/Nathaniel
Spratt is exactly that — the same person, split across two ids, and this sweep
cannot see him because his 2026 rows carry nothing to join on. A clean run does
NOT mean the corpus has no fractured riders; it means this signal has nothing
more to say. Keep running audit_rider_duplicates.py beside it.

Usage:
  python3 audit_rider_racer_ids.py               # both sections, classified
  python3 audit_rider_racer_ids.py --same        # only the confident merges
  python3 audit_rider_racer_ids.py --json out.json
  python3 merge_rider_duplicates.py --groups out.json        # then, after reading
"""

import argparse
import glob
import json
import os
import sqlite3
from collections import defaultdict

from race_common import (DB_PATH, load_rider_aliases, load_rider_separations,
                         load_rider_splits, strip_series_flag)
# The identity key has to be built EXACTLY as link_gravel_riders built the keys
# of _rider_ids.json — fold(strip_series_flag(name)) — or the lookup silently
# misses. Leadville's Leadman rows are the ones that would go: `(l)` in 2011
# and `LM` in 2013 are a series flag, not part of anybody's name.
from link_gravel_riders import fold

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES = os.path.join(HERE, "gravel_scrapes")

SEPARATED = load_rider_separations()
SPLIT_HALVES = {
    frozenset((src.removeprefix("rider/"), rule["rider_id"].removeprefix("rider/")))
    for (src, _race, _year), rule in load_rider_splits().items()
}


def scrape_files():
    """Every per-edition gravel scrape file.

    `_raw/` is deliberately excluded: it is scrape_athlinks.py's gitignored
    fetch cache, it holds Athlinks' own key names (`racerId`, `displayName`)
    rather than ours, and it contains editions and divisions that were
    considered and NOT selected. Reading it would credit riders to races they
    are not in.
    """
    return sorted(f for f in glob.glob(os.path.join(SCRAPES, "*", "[0-9]*.json"))
                  if os.sep + "_raw" + os.sep not in f)


def rider_id_by_name():
    """folded name -> rider_id, as link_gravel_riders minted them."""
    path = os.path.join(SCRAPES, "_rider_ids.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v["rider_id"] for k, v in raw.items()
            if isinstance(v, dict) and v.get("rider_id")}


def collect():
    """(racer_id -> {rider_id -> [(year, race, name)]}, rider_id -> {racer_id}, stats)

    Ids are resolved THROUGH rider_aliases.json before grouping, so a pair that
    has already been merged does not get proposed again on every run — the same
    reason audit_rider_duplicates.py reads the `separated` section.
    """
    aliases = load_rider_aliases()
    by_name = rider_id_by_name()
    fuse = defaultdict(lambda: defaultdict(list))
    fission = defaultdict(set)
    rows = nulls = unmatched = 0

    for path in scrape_files():
        race = os.path.basename(os.path.dirname(path))
        year = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as f:
            for row in (json.load(f).get("rows") or []):
                rows += 1
                racer = row.get("racer_id")
                if not racer:          # null, and Athlinks also writes 0
                    nulls += 1
                    continue
                key = fold(strip_series_flag(row.get("name") or "")).strip()
                rid = by_name.get(key)
                if not rid:
                    unmatched += 1
                    continue
                rid = aliases.get(rid, rid)
                fuse[racer][rid].append((year, race, row.get("name")))
                fission[rid].add(racer)

    return (fuse, fission,
            {"rows": rows, "nulls": nulls, "unmatched": unmatched})


def adjudicated_ids():
    """rider_id -> why a conflation candidate was decided, from rider_splits.json.

    Both of that file's sections answer the question the mirror section below
    asks. `splits` is an id somebody DID fission; `rejected` is a candidate
    examined and left alone, which is the harder thing to remember and the whole
    reason that section exists. Either way the id is not an open lead.
    """
    path = os.path.join(HERE, "rider_splits.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {rid: str(why) for rid, why in (raw.get("rejected") or {}).items()}
    for rid in (raw.get("splits") or {}):
        out.setdefault(rid, "SPLIT into two riders — see rider_splits.json")
    return out


def share_a_stage(cur, ids):
    """The disconfirming test, and the only thing that can OVERRULE the source.

    Nobody rides one race twice. If two ids appear in the same edition they are
    two people whatever Athlinks' racer id says — a shared household account, or
    the timer's own error. It has never fired on this corpus; it is here so that
    the day it does, the answer is a printed DIFFERENT rather than a merge.
    """
    qm = ",".join("?" * len(ids))
    return cur.execute(
        f"""SELECT COUNT(*) FROM (
              SELECT s.stage_id FROM stage_results sr
                JOIN stages s ON s.stage_id = sr.stage_id
               WHERE sr.rider_id IN ({qm})
               GROUP BY s.stage_id HAVING COUNT(DISTINCT sr.rider_id) > 1)""",
        list(ids)).fetchone()[0]


def classify(cur, ids):
    """(verdict, why) for one racer_id's set of rider ids."""
    bare = [i.removeprefix("rider/") for i in ids]
    if len(ids) == 2:
        pair = frozenset(bare)
        if pair in SEPARATED:
            return "SETTLED", ("ruled different people on " + SEPARATED[pair]["decided"]
                               + " — see the `separated` section of rider_aliases.json")
        if pair in SPLIT_HALVES:
            return "SETTLED", ("the two halves of a deliberate split — see "
                               "rider_splits.json; merging them would undo it")
    n = share_a_stage(cur, ids)
    if n:
        return "DIFFERENT", (f"the ids share {n} stage(s), so they are two people "
                             "however they came to share a racer id")
    nats = {r[0] for r in cur.execute(
        f"SELECT nationality_code FROM riders WHERE rider_id IN "
        f"({','.join('?' * len(ids))})", list(ids)) if r[0]}
    if len(nats) > 1:
        return "REVIEW", (f"one racer id, but nationalities differ ({', '.join(sorted(nats))}) — "
                          "usually a rider who moved house, since Athlinks stores "
                          "where an entrant lives; confirm before merging")
    return "SAME", "Athlinks files these rows under one persistent racer id"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--same", action="store_true",
                    help="only the SAME groups, the ones ready to merge")
    ap.add_argument("--json", help="write the SAME/REVIEW groups here for "
                                   "merge_rider_duplicates.py --groups")
    args = ap.parse_args()

    fuse, fission, stats = collect()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    groups = []
    for racer, ids in fuse.items():
        if len(ids) < 2:
            continue
        verdict, why = classify(cur, list(ids))
        members = []
        for rid in sorted(ids):
            row = cur.execute("SELECT full_name, nationality_code FROM riders "
                              "WHERE rider_id=?", (rid,)).fetchone()
            n = cur.execute("SELECT COUNT(*) FROM stage_results WHERE rider_id=?",
                            (rid,)).fetchone()[0]
            members.append({"id": rid,
                            "name": row["full_name"] if row else "(no riders row)",
                            "nat": row["nationality_code"] if row else None,
                            "results": n,
                            "seen": sorted(f"{y} {r}" for y, r, _ in ids[rid])})
        members.sort(key=lambda m: -m["results"])
        groups.append({"key": f"racer:{racer}", "verdict": verdict, "why": why,
                       "racer_id": racer, "members": members})

    order = {"SAME": 0, "REVIEW": 1, "DIFFERENT": 2, "SETTLED": 3}
    groups.sort(key=lambda g: (order[g["verdict"]], -max(m["results"] for m in g["members"])))

    shown = [g for g in groups if not args.same or g["verdict"] == "SAME"]
    for g in shown:
        print(f"\n[{g['verdict']:<9}] {g['key']}  — {g['why']}")
        for m in g["members"]:
            names = sorted({n for _, _, n in fuse[g["racer_id"]][m["id"]] if n})
            print(f"    {m['id'].removeprefix('rider/'):<30}{m['results']:>3} result(s)  "
                  f"{m['nat'] or '--'}  as {' / '.join(names)}")
            print(f"        {', '.join(m['seen'])}")

    counts = {v: sum(1 for g in groups if g["verdict"] == v) for v in order}
    print(f"\n{len(groups)} racer id(s) span more than one rider id: "
          + ", ".join(f"{counts[v]} {v}" for v in order if counts[v]))

    # The mirror direction. A LEAD only — see the module docstring.
    multi = {rid: rs for rid, rs in fission.items() if len(rs) > 1}
    if multi and not args.same:
        # A lead somebody already ran down is not an open question, and printing
        # it as one invites the next reader to re-derive an answer that is
        # written down. rider_splits.json records both directions: `splits` for
        # an id that really was two people, `rejected` for a candidate that did
        # not meet the bar. jake-pantone is the second kind — three racer ids,
        # one man, checked 2026-09-18.
        adjudicated = adjudicated_ids()
        settled = {k: v for k, v in multi.items() if k in adjudicated}
        open_leads = {k: v for k, v in multi.items() if k not in adjudicated}
        print(f"\n{len(multi)} rider id(s) carry more than one racer id. This is NOT "
              "evidence of two people — a rider can hold two Athlinks accounts — but "
              "it is where a conflation would show.")
        if open_leads:
            print(f"\n  {len(open_leads)} not yet looked at:")
            for rid, rs in sorted(open_leads.items()):
                print(f"    {rid.removeprefix('rider/'):<30}{sorted(rs)}")
        for rid, rs in sorted(settled.items()):
            print(f"\n  SETTLED  {rid.removeprefix('rider/')} {sorted(rs)}"
                  f"\n    {adjudicated[rid]}")

    pct = stats["nulls"] / stats["rows"] * 100 if stats["rows"] else 0
    print(f"\nRead {stats['rows']:,} gravel rows; {stats['nulls']:,} ({pct:.0f}%) carry no "
          f"racer id and are INVISIBLE to this sweep, {stats['unmatched']:,} matched no "
          "known rider. A clean run does not mean there are no fractured riders — "
          "Nathan/Nathaniel Spratt is one this signal cannot see. Run "
          "audit_rider_duplicates.py too.")
    print("Nothing was merged. A SAME verdict is a lead, not a decision — read the "
          "rows above, then merge_rider_duplicates.py --groups.")

    if args.json:
        keep = [g for g in groups if g["verdict"] in ("SAME", "REVIEW")]
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(keep, f, indent=1, ensure_ascii=False)
        print(f"\nwrote {len(keep)} group(s) to {args.json} "
              "(SAME and REVIEW; SETTLED and DIFFERENT are deliberately omitted)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
