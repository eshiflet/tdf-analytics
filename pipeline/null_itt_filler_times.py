#!/usr/bin/env python3
"""
NULL the fabricated finish times on the 41 ITT stages PCS never timed.

An individual time trial is ridden alone against the clock, so the field does
not share a time. `validate_db` has long warned that 41 stages typed ITT hold
4,040 riders on the winner's exact second. Two faults were thought to look
identical from inside this database -- PCS's filler gap read as a real gap
(times fabricated), or a mass-start stage PCS mislabelled 'Time trial' (times
right, route_type wrong) -- and the note said there was no rule to tell them
apart. There is one, and PCS carries it (checked stage by stage 2026-09-11):

  A non-winner whose `Time` cell matches ^[-+]?0:00$ has NO published time.

That is the whole test. It holds regardless of rank: the filler appears both
on rows PCS marks 'DF' (39 stages) and on rows carrying a real integer rank
(Tour 1937 stage-17b, Vuelta 1995 prologue -- ranks 2-35 all at 0:00 over a
7 km prologue, which no prologue produces). A genuine bunch finish is not
confused with it, because a real shared time is an actual duplicated value
("2:06"), never the filler.

All 41 came back the same way. There is no mislabelled mass-start in this set;
Giro 1985 stage-8a was the genuine one and is already corrected through
route_type_overrides.json, which is why it does not appear here.

So the honest value for those 4,040 riders is NULL. That is what this writes.

TWO TRAPS, both hit while establishing the above:

  * The obvious gap column on a PCS results table is `Timelag`, and it is the
    GC gap, not the stage gap -- it is non-monotonic with rank. The stage gap
    is in `Time`. Reading the wrong one yields wrong-but-plausible values.
  * The filler has THREE spellings: '0:00', '+0:00' and '-0:00'. A filter that
    caught only the first reported 40 of 41 stages as recoverable from a
    re-scrape. They are not; PCS has no more than we store.

What this does NOT do:
  * It does not touch `stage_rank` or `status`. Where PCS publishes a
    finishing order without times those riders did finish, and dropping their
    placing would trade one defect for another.
  * It does not touch the winner, whose absolute time is real.
  * It does not touch a rider whose stored time differs from the winner's --
    those came from a real published gap.
  * It will not re-null a row already NULL, so it is idempotent and safe to
    re-run.

A re-ingest will reintroduce these values, because ingest still reads the same
filler. Re-run this after any re-ingest of the affected editions, the same way
backfill_bib_numbers is re-run. See "Times that no race produced".

Usage:
  python3 null_itt_filler_times.py                 # change table, writes nothing
  python3 null_itt_filler_times.py --apply
  python3 null_itt_filler_times.py --limit 5       # inspect a few stages
"""

import argparse
import sqlite3
import sys

from race_common import DB_PATH, SOURCE_PCS, record_provenance

# Stages where PCS publishes no per-rider times, established by fetching each
# stage's own page by source_slug on 2026-09-11. (race name, year, source_slug)
STAGES = [
    ("Tour de France", 1937, "stage-17b"),
    ("Giro d'Italia", 1953, "stage-8"),
    ("Giro d'Italia", 1956, "stage-5b"),
    ("Giro d'Italia", 1956, "stage-11"),
    ("Giro d'Italia", 1956, "stage-13"),
    ("Giro d'Italia", 1957, "stage-2"),
    ("Giro d'Italia", 1957, "stage-12"),
    ("Giro d'Italia", 1958, "stage-2"),
    ("Giro d'Italia", 1958, "stage-8"),
    ("Giro d'Italia", 1958, "stage-14"),
    ("Giro d'Italia", 1973, "prologue"),
    ("Giro d'Italia", 1973, "stage-16"),
    ("Giro d'Italia", 1979, "prologue"),
    ("Giro d'Italia", 1979, "stage-3"),
    ("Giro d'Italia", 1979, "stage-8"),
    ("Giro d'Italia", 1979, "stage-10"),
    ("Giro d'Italia", 1985, "prologue"),
    ("Giro d'Italia", 1985, "stage-12"),
    ("Giro d'Italia", 1986, "prologue"),
    ("Giro d'Italia", 1986, "stage-12"),
    ("Giro d'Italia", 1986, "stage-18"),
    ("Giro d'Italia", 1987, "prologue"),
    ("Giro d'Italia", 1987, "stage-1b"),
    ("Giro d'Italia", 1987, "stage-13"),
    ("Giro d'Italia", 1987, "stage-22"),
    ("Giro d'Italia", 1988, "stage-18"),
    ("Giro d'Italia", 1989, "stage-10"),
    ("Giro d'Italia", 1989, "stage-18"),
    ("Giro d'Italia", 1990, "stage-19"),
    ("Giro d'Italia", 1991, "stage-2b"),
    ("Vuelta a España", 1971, "stage-11b"),
    ("Vuelta a España", 1982, "prologue"),
    ("Vuelta a España", 1983, "stage-15b"),
    ("Vuelta a España", 1984, "stage-18b"),
    ("Vuelta a España", 1987, "prologue"),
    ("Vuelta a España", 1992, "stage-7"),
    ("Vuelta a España", 1992, "stage-19"),
    ("Vuelta a España", 1994, "stage-8"),
    ("Vuelta a España", 1994, "stage-20"),
    ("Vuelta a España", 1995, "prologue"),
    ("Vuelta a España", 1997, "stage-21"),
]

PCS_RACE = {"Tour de France": "tour-de-france", "Giro d'Italia": "giro-d-italia",
            "Vuelta a España": "vuelta-a-espana"}


def resolve(cur, race, year, slug):
    row = cur.execute(
        """SELECT s.stage_id, s.stage_number, s.distance_km
             FROM stages s
             JOIN race_editions re ON re.edition_id = s.edition_id
             JOIN races ra ON ra.race_id = re.race_id
            WHERE ra.name = ? AND re.year = ? AND s.source_slug = ?""",
        (race, year, slug)).fetchone()
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write; without it this only prints the change table")
    ap.add_argument("--limit", type=int, help="only the first N stages")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    stages = STAGES[:args.limit] if args.limit else STAGES

    total = 0
    missing = []
    plan = []
    print(f"{'race':<7}{'year':<6}{'slug':<12}{'st':>4}{'winner s':>10}"
          f"{'to NULL':>9}{'keep':>6}")
    print("-" * 60)
    for race, year, slug in stages:
        row = resolve(cur, race, year, slug)
        if not row:
            missing.append((race, year, slug))
            continue
        stage_id, stage_number, km = row
        wtime = cur.execute(
            """SELECT MIN(finish_time_seconds) FROM stage_results
                WHERE stage_id = ? AND stage_rank = 1
                  AND finish_time_seconds IS NOT NULL""", (stage_id,)).fetchone()[0]
        if wtime is None:
            missing.append((race, year, slug + " (no winner time)"))
            continue
        # Every non-winner stored on the winner's exact second. The winner is
        # identified by rank, not by time: on a stage where PCS timed nobody
        # the winner's own row is the only real value there is.
        victims = cur.execute(
            """SELECT result_id FROM stage_results
                WHERE stage_id = ? AND finish_time_seconds = ?
                  AND (stage_rank IS NULL OR stage_rank <> 1)""",
            (stage_id, wtime)).fetchall()
        keep = cur.execute(
            """SELECT COUNT(*) FROM stage_results
                WHERE stage_id = ? AND finish_time_seconds IS NOT NULL
                  AND finish_time_seconds <> ?""", (stage_id, wtime)).fetchone()[0]
        print(f"{race[:6]:<7}{year:<6}{slug:<12}{stage_number:>4}{wtime:>10}"
              f"{len(victims):>9}{keep:>6}")
        plan.append((race, year, slug, stage_id, [v[0] for v in victims]))
        total += len(victims)

    print("-" * 60)
    print(f"{len(plan)} stage(s), {total:,} finish_time_seconds -> NULL "
          f"(stage_rank and status untouched)")
    for m in missing:
        print(f"  NOT FOUND, skipped: {m}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
        return 0

    written = 0
    try:
        for race, year, slug, stage_id, ids in plan:
            ref = (f"https://www.procyclingstats.com/race/{PCS_RACE[race]}/{year}/"
                   f"{slug}/result/result")
            for rid in ids:
                cur.execute(
                    "UPDATE stage_results SET finish_time_seconds = NULL "
                    "WHERE result_id = ? AND finish_time_seconds IS NOT NULL", (rid,))
                if cur.rowcount:
                    written += cur.rowcount
                    # Provenance for the column actually written. The source IS
                    # PCS: the page is what establishes that no time exists.
                    record_provenance(
                        cur, "stage_results", rid, "finish_time_seconds",
                        SOURCE_PCS, source_ref=f"{ref} — Time cell is filler "
                        "(^[-+]?0:00$); PCS publishes no time for this rider")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print(f"\nAPPLIED: {written:,} value(s) set to NULL, provenance recorded for each.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
