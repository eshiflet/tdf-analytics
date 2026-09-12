#!/usr/bin/env python3
"""
Merge the rider ids audit_rider_duplicates.py classifies as SAME.

A wrong merge fuses two people's careers and nothing downstream can tell, so
this is the one operation in the repo that gets a disconfirming test rather
than a confirming one:

  IF THE TWO IDS EVER APPEAR ON THE SAME STAGE, THEY ARE TWO PEOPLE.

Nobody rides a race twice. That test alone caught `gilbert-desmet-i` beside
`gilbert-de-smet-ii` — two riders of one family, sharing 93 stages — which the
name heuristic had called SAME because the hyphenation differs as well as the
roman numeral. A group that fails it is skipped and reported, never merged.

Canonical id, in order: most results wins; then the PLAIN form over one
carrying a middle initial, because `tim-swift` is the name and `tim-m-swift`
is what somebody typed into a race entry form; then alphabetical, so the choice
is deterministic and re-running cannot pick differently.

The absorbed id's results, standings and provenance move to the survivor, the
orphan row is deleted, and the survivor gets a provenance row naming what it
absorbed and why. Re-export every race set the merged riders appear in
afterwards — a stale export left pointing at a deleted id is a dead link on the
rider page, which is how the julius-thallmann rename was found.

Usage:
  python3 merge_rider_duplicates.py                # change table, writes nothing
  python3 merge_rider_duplicates.py --apply
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys

from race_common import (DB_PATH, SOURCE_DERIVED, load_rider_separations,
                         record_provenance)

HERE = os.path.dirname(os.path.abspath(__file__))
INITIAL = re.compile(r"-[a-z]-")
SEPARATIONS = load_rider_separations()


def load_groups(path=None):
    if path:
        return json.load(open(path, encoding="utf-8"))
    out = os.path.join(HERE, ".rider_dups.json")
    subprocess.run([sys.executable, os.path.join(HERE, "audit_rider_duplicates.py"),
                    "--json", out], check=True, capture_output=True)
    groups = json.load(open(out, encoding="utf-8"))
    os.unlink(out)
    return groups


def share_a_stage(cur, ids):
    qm = ",".join("?" * len(ids))
    return cur.execute(
        f"""SELECT COUNT(*) FROM (
              SELECT s.stage_id FROM stage_results sr
                JOIN stages s ON s.stage_id = sr.stage_id
               WHERE sr.rider_id IN ({qm})
               GROUP BY s.stage_id HAVING COUNT(DISTINCT sr.rider_id) > 1)""",
        ids).fetchone()[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--groups", help="a JSON file from audit_rider_duplicates --json")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=120000")
    cur = conn.cursor()

    plan, skipped, refused = [], [], []
    for g in load_groups(args.groups):
        if g["verdict"] != "SAME":
            continue
        ids = [m["id"] for m in g["members"]]
        # Belt and braces: the audit already downgrades these to SETTLED, but a
        # stale --groups file could still carry one as SAME, and re-merging a
        # pair a human separated is precisely the error this whole path exists
        # to avoid.
        pair = frozenset(i.removeprefix("rider/") for i in ids)
        if pair in SEPARATIONS:
            refused.append((g["key"], SEPARATIONS[pair]["decided"]))
            continue
        n = share_a_stage(cur, ids)
        if n:
            skipped.append((g["key"], n))
            continue
        ms = sorted(g["members"], key=lambda m: (-m["results"],
                                                 bool(INITIAL.search(m["id"])),
                                                 m["nat"] is None, m["id"]))
        plan.append((ms[0]["id"], [m["id"] for m in ms[1:]], g["why"]))

    print(f"{'KEEP':<34}{'ABSORB':<34}{'rows':>5}")
    print("-" * 75)
    total = 0
    for keep, absorb, _ in plan:
        for aid in absorb:
            n = cur.execute("SELECT COUNT(*) FROM stage_results WHERE rider_id=?",
                            (aid,)).fetchone()[0]
            total += n
            print(f"{keep.removeprefix('rider/'):<34}{aid.removeprefix('rider/'):<34}{n:>5}")
    print(f"\n{sum(len(a) for _, a, _ in plan)} merge(s), {total} result row(s) to re-point")
    for key, when in refused:
        print(f"  REFUSED {key}: ruled different people on {when} — see the "
              "`separated` section of rider_aliases.json")
    for key, n in skipped:
        print(f"  SKIPPED {key}: the two ids share {n} stage(s) — two people, not one")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
        return 0

    merged = moved = 0
    try:
        for keep, absorb, why in plan:
            for aid in absorb:
                moved += cur.execute("UPDATE stage_results SET rider_id=? WHERE rider_id=?",
                                     (keep, aid)).rowcount
                cur.execute("UPDATE OR IGNORE classification_standings SET rider_id=? "
                            "WHERE rider_id=?", (keep, aid))
                cur.execute("DELETE FROM data_provenance WHERE entity='riders' "
                            "AND entity_id=?", (aid,))
                cur.execute("DELETE FROM riders WHERE rider_id=?", (aid,))
                record_provenance(
                    cur, "riders", keep, "full_name", SOURCE_DERIVED,
                    source_ref=f"absorbed {aid}: same name after collapsing doubled "
                               f"letters, accents and a middle initial; {why}; and the "
                               "two never appear on the same stage, which is the test "
                               "that would have disproved it")
                merged += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print(f"\nAPPLIED: {merged} rider(s) absorbed, {moved} result row(s) re-pointed.")
    print("Now re-export every race set these riders appear in, or their pages keep "
          "a dead link.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
