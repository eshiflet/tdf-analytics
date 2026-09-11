#!/usr/bin/env python3
"""
Clear stage finishing times that no bike race could have ridden.

The stored winner's time on some stages is not a finishing time at all. It is
either the GC TOTAL, which PCS prints in the Time column on certain split-day
trials (the 1953 Giro's 30 km stage 11 reads 52:40:45, or 0.6 km/h), or a GAP
(the 2008 Tour's stage 6 has Valverde winning 195.5 km in ONE SECOND).

Either way the damage is the whole stage, not one row: ingest computes every
other rider as winner + gap, so one bad cell fabricates a finishing time for
the entire field. 2008 stage 6 has Evans at two seconds and Schleck at five.

WHAT IT DOES NOT TOUCH. The gaps, which are real on every stage examined —
Evans +0, Klöden +99, Kashechkin +104 are the true finishing order of that
time trial. Only the absolute times go, and they go to NULL rather than to a
corrected value, because nothing on the page says what the real time was.
A NULL is a gap in the record; a number that fails its own arithmetic is a
claim. export_gc.py reads tier 1 (Wikipedia) and tier 2 (winner time + gc gap)
for totalTimeSeconds, so the charts do not rest on these.

ingest_race.implausible_speed is the same check, applied at write time since
2026-09-10; this is that rule applied to what was already stored. The band is
deliberately wide (12-70 km/h) — the slowest Tour ever averaged 24 and the
fastest prologues touch 58 — because it is a guard against a value that is not
a stage time, not a judgement about a hard day.

Usage:
  python3 clear_impossible_stage_times.py --dry-run
  python3 clear_impossible_stage_times.py --race tour --dry-run
  python3 clear_impossible_stage_times.py --apply
"""

import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ingest_race import implausible_speed, MIN_KMH, MAX_KMH   # noqa: E402
from race_common import DB_PATH, SOURCE_DERIVED, record_provenance  # noqa: E402


def winner_time(cur, stage_id):
    """The rank-1 finishing time, or the smallest stored one.

    Rank 1 first, because a stage can carry one stray small value without the
    winner's own time being wrong, and MIN() alone would condemn the stage for
    it. Where no rank-1 row has a time, the smallest is the best available
    stand-in for the winner's.
    """
    row = cur.execute(
        "SELECT finish_time_seconds FROM stage_results WHERE stage_id=? AND "
        "stage_rank=1 AND finish_time_seconds IS NOT NULL "
        "ORDER BY finish_time_seconds LIMIT 1", (stage_id,)).fetchone()
    if row:
        return row[0], "rank 1"
    row = cur.execute(
        "SELECT MIN(finish_time_seconds) FROM stage_results WHERE stage_id=?",
        (stage_id,)).fetchone()
    return (row[0], "fastest stored") if row and row[0] is not None else (None, None)


def find(cur, race=None):
    where = "AND r.name = ?" if race else ""
    args = (race,) if race else ()
    stages = cur.execute(f"""
        SELECT s.stage_id, r.name AS race, e.year, s.stage_number, s.stage_label,
               s.distance_km, s.route_type
          FROM stages s
          JOIN race_editions e ON e.edition_id = s.edition_id
          JOIN races r ON r.race_id = e.race_id
         WHERE s.distance_km > 0 AND s.cancelled = 0 {where}
      ORDER BY r.name, e.year, s.stage_number""", args).fetchall()

    hits = []
    for s in stages:
        secs, source = winner_time(cur, s["stage_id"])
        if secs is None or not implausible_speed(s["distance_km"], secs):
            continue
        timed = cur.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage_id=? AND "
            "finish_time_seconds IS NOT NULL", (s["stage_id"],)).fetchone()[0]
        gaps = cur.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage_id=? AND "
            "gap_seconds IS NOT NULL", (s["stage_id"],)).fetchone()[0]
        hits.append({**dict(s), "secs": secs, "source": source,
                     "kmh": s["distance_km"] / (secs / 3600),
                     "timed": timed, "gaps": gaps})
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", help="races.name, e.g. 'Tour de France'")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    hits = find(cur, args.race)
    if not hits:
        print(f"no stage stores a winner's time outside {MIN_KMH}-{MAX_KMH} km/h")
        conn.close()
        return 0

    print(f"{'[DRY RUN] ' if not args.apply else ''}{len(hits)} stage(s) store a "
          f"winner's time no bike race could ride ({MIN_KMH}-{MAX_KMH} km/h band)")
    print(f"\n{'race':18s} {'yr':>5s} {'st':>3s} {'rt':>4s} {'km':>7s} "
          f"{'stored':>10s} {'km/h':>10s} {'times':>6s} {'gaps kept':>10s}")
    for h in hits:
        m, sec = divmod(h["secs"], 60)
        hr, m = divmod(m, 60)
        print(f"{h['race'][:18]:18s} {h['year']:5d} {h['stage_number']:3d} "
              f"{h['route_type'] or '-':>4s} {h['distance_km']:7.1f} "
              f"{hr:>4d}:{m:02d}:{sec:02d} {h['kmh']:10,.0f} {h['timed']:6d} {h['gaps']:10d}")
    total = sum(h["timed"] for h in hits)
    print(f"\n{total:,} finishing time(s) would become NULL; "
          f"{sum(h['gaps'] for h in hits):,} gap(s) are kept untouched")

    if not args.apply:
        print("\nre-run with --apply")
        conn.close()
        return 0

    for h in hits:
        cur.execute("UPDATE stage_results SET finish_time_seconds=NULL WHERE stage_id=?",
                    (h["stage_id"],))
        record_provenance(
            cur, "stages", h["stage_id"], "finish_time_seconds", SOURCE_DERIVED,
            source_ref=(f"cleared: the stored winner's time of {h['secs']}s over "
                        f"{h['distance_km']} km implies {h['kmh']:,.0f} km/h, which is "
                        f"not a stage time — PCS shows a GC total or a gap in that "
                        f"cell. Gaps on the stage are unaffected."),
            script="clear_impossible_stage_times.py")
    conn.commit()
    print(f"\ncleared {total:,} finishing time(s) across {len(hits)} stage(s)")
    print("Re-run validate_db.py (the count guard will want "
          "--update-patch-manifest) and the affected exports.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
