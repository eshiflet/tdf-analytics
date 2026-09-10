#!/usr/bin/env python3
"""
Give the 1905 Tour's stage-1 finishers the placing PCS does not record.

PCS lists 29 riders in Tour 1905 stage 1 with rank "999" and a time of "-".
That is not an abandonment: 25 of the 29 ride stage 2 and are classified
normally there. It means PCS holds no individual time for them on stage 1.

The consequence is out of proportion to the gap. The cumulative-score chain in
build_vuelta_gc_standings.py is strictly forward and seeds from the first day,
so a rider with no stage-1 gap gets no score for the ENTIRE race and cannot be
re-anchored without an authoritative entry to tie the origin to. 1905 has
almost none. The edition computes 146 GC entries and leaves 8 of its 11 days
unranked, not because its data is thin but because 29 riders fall out of the
arithmetic on day one.

THE SOURCE IS NOT PCS. letour.fr, the race's own site, lists all 29 as
finishing stage 1 in 16th place with a gap of 5h20'00" — the same time as
Jean-Baptiste Fischer, who PCS records at 15th with exactly that gap. Our data
already agrees with letour.fr on the riders above them (13th Ventresque
5:00'00", 14th Pautrat 5:08'00", 15th Fischer 5:20'00"), which is what makes
the join safe. The page has no stable URL to cite, so the values were relayed
by the repo owner and are recorded as `manual`, never as `pcs`.

This is the only stage in the database with rank-999 rows — all 29 of them —
so nothing here is generalised from it. If another appears, check its own
source before assuming this shape.

Usage:
  python3 patch_1905_unranked_finishers.py --dry-run
  python3 patch_1905_unranked_finishers.py --apply
"""

import argparse
import json
import os
import sqlite3
import sys

from race_common import DB_PATH, SOURCE_MANUAL, StageRow, record_provenance

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE_FILE = os.path.join(HERE, "tour_scrapes", "1905", "stage_1.json")
PLACING = "16"
GAP = "5:20:00"
SOURCE_REF = ("letour.fr, the Tour's own results archive, relayed by the repo "
              "owner: all 29 listed 16th at +5h20'00\", the same time as "
              "Fischer in 15th. PCS records them as rank 999 with no time.")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    with open(STAGE_FILE, encoding="utf-8") as f:
        doc = json.load(f)

    targets = [r for r in doc.get("rows", [])
               if len(r) == 15 and StageRow.from_list(r).rnk == "999"]
    print(f"1905 stage 1: {len(targets)} rider(s) with rank 999")
    for r in targets[:4]:
        sr = StageRow.from_list(r)
        print(f"    {sr.name:<26} rank 999 -> {PLACING}, gap {sr.gap!r} -> {GAP!r}")
    if len(targets) > 4:
        print(f"    ... and {len(targets) - 4} more")

    if not args.apply:
        print("\n[DRY RUN] nothing written")
        return 0

    for r in targets:
        r[0] = PLACING
        r[14] = GAP
    with open(STAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)

    # The stage's results no longer come wholly from PCS, and the provenance
    # has to say so — a later re-ingest records 'pcs' for the stage as a whole,
    # which is why this runs after it and overwrites that claim.
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    row = cur.execute(
        """SELECT s.stage_id FROM stages s
             JOIN race_editions e ON e.edition_id = s.edition_id
             JOIN races r ON r.race_id = e.race_id
            WHERE r.name = 'Tour de France' AND e.year = 1905
              AND s.stage_number = 1""").fetchone()
    if row:
        record_provenance(cur, "stages", row[0], "results", SOURCE_MANUAL,
                          source_ref=SOURCE_REF,
                          script="patch_1905_unranked_finishers.py")
        conn.commit()
        print(f"  provenance recorded on stage_id {row[0]} as '{SOURCE_MANUAL}'")
    else:
        print("  NOTE: 1905 stage 1 not in the database; provenance not recorded")
    conn.close()
    print(f"\nrewrote {len(targets)} row(s) in {os.path.basename(STAGE_FILE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
