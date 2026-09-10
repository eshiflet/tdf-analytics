#!/usr/bin/env python3
"""
Show what re-ingesting a year would change, without changing anything.

`ingest_race.py --dry-run` answers "would this run?" — it prints that it would
replace the edition and stops. This answers the question you actually need
before a bulk re-ingest: WHICH VALUES MOVE, and in which direction. It copies
cycling.db to a scratch file, runs the real ingest against the copy, and diffs
the two. The real database is opened read-only, once, to be copied.

Three kinds of change, kept apart because they carry different risk:

  NULL-fill   the database had nothing, the scrape has a value.  A gain.
  overwrite   both have a value and they differ.                 Look at these.
  clear       the database had a value, the re-ingest has none.  Look harder —
              a clear is either a carried-forward value being correctly
              dropped, or real data that lives only in the DB being lost.

Usage:
  python3 preview_reingest.py --race tour                 # every year with files
  python3 preview_reingest.py --race tour 1960-1975
  python3 preview_reingest.py --race vuelta 2001 2016 --verbose
  python3 preview_reingest.py --race tour --csv > changes.csv

A year the ingest REFUSES (bib-identity swaps, an orphaned stage) is reported
as such rather than counted: nothing would move, because the whole edition
would roll back.
"""

import argparse
import collections
import csv
import io
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from race_common import RACES, DB_PATH, parse_year_args  # noqa: E402

# The columns worth diffing: everything an ingest writes per rider-stage, plus
# the per-stage fields it can overwrite from the scrape file.
RESULT_COLS = ("stage_rank", "status", "finish_time_seconds", "gap_seconds",
               "gc_rank", "gc_gap_seconds", "uci_points", "pcs_points",
               "bonus_seconds", "bib_number", "team_id")
STAGE_COLS = ("stage_date", "distance_km", "route_type", "vertical_meters",
              "profile_score", "source_slug", "cancelled")


def snapshot(db, race_name, year):
    """(stages, results) for one edition, or ({}, {}) if it is not there yet."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT e.edition_id FROM race_editions e JOIN races r USING(race_id) "
        "WHERE r.name=? AND e.year=?", (race_name, year)).fetchone()
    if not row:
        conn.close()
        return {}, {}
    eid = row[0]
    stages = {r["stage_number"]: dict(r) for r in conn.execute(
        f"SELECT stage_number, {','.join(STAGE_COLS)} FROM stages WHERE edition_id=?",
        (eid,))}
    results = {(r["stage_number"], r["rider_id"]): dict(r) for r in conn.execute(
        f"SELECT s.stage_number, sr.rider_id, {','.join('sr.' + c for c in RESULT_COLS)} "
        "FROM stage_results sr JOIN stages s USING(stage_id) WHERE s.edition_id=?",
        (eid,))}
    conn.close()
    return stages, results


def diff(before, after):
    b_stages, b_results = before
    a_stages, a_results = after
    fill, over, clear = (collections.Counter() for _ in range(3))
    samples = collections.defaultdict(list)
    for key in set(b_results) & set(a_results):
        for col in RESULT_COLS:
            old, new = b_results[key][col], a_results[key][col]
            if old == new:
                continue
            kind = "fill" if old is None else "clear" if new is None else "over"
            {"fill": fill, "clear": clear, "over": over}[kind][col] += 1
            if len(samples[(kind, col)]) < 3:
                samples[(kind, col)].append((key[0], key[1], old, new))
    stage_fields = collections.Counter()
    for n in set(b_stages) & set(a_stages):
        for col in STAGE_COLS:
            if b_stages[n][col] != a_stages[n][col]:
                stage_fields[col] += 1
                if len(samples[("stage", col)]) < 3:
                    samples[("stage", col)].append(
                        (n, "", b_stages[n][col], a_stages[n][col]))
    return {
        "rows_before": len(b_results), "rows_after": len(a_results),
        "gone": len(set(b_results) - set(a_results)),
        "new": len(set(a_results) - set(b_results)),
        "stages_before": len(b_stages), "stages_after": len(a_stages),
        "fill": dict(fill), "over": dict(over), "clear": dict(clear),
        "stage_fields": dict(stage_fields), "samples": samples,
    }


def run_one(scratch, race, race_name, year):
    """Ingest one year into the scratch DB. Returns (diff, refusal_or_None)."""
    import ingest_race
    before = snapshot(scratch, race_name, year)
    argv, out = sys.argv, sys.stdout
    sys.argv = ["ingest_race.py", "--race", race, str(year)]
    sys.stdout = io.StringIO()
    try:
        ingest_race.main()
        refusal = None
    except SystemExit:
        refusal = None
    except Exception as exc:                       # noqa: BLE001 — report, never raise
        refusal = f"{type(exc).__name__}: {exc}"
    finally:
        log = sys.stdout.getvalue()
        sys.stdout, sys.argv = out, argv
    for line in log.splitlines():
        if "REFUSED" in line or line.strip().startswith("ERROR"):
            refusal = line.strip()[:120]
            break
    notes = [l.strip() for l in log.splitlines()
             if any(k in l for k in ("WARNING", "NOTE:", "incident", "patch(es)",
                                     "not one:", "malformed"))]
    return diff(before, snapshot(scratch, race_name, year)), refusal, notes[:4]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=sorted(RACES), required=True)
    ap.add_argument("years", nargs="*", help="1985, or 1960-1975; default: all with files")
    ap.add_argument("--verbose", action="store_true", help="show example changed values")
    ap.add_argument("--csv", action="store_true", help="one row per year/column/kind")
    args = ap.parse_args()

    info = RACES[args.race]
    scrapes = os.path.join(HERE, info.scrapes_dirname)
    years = parse_year_args(args.years)
    if not years:
        years = sorted(int(d) for d in os.listdir(scrapes)
                       if d.isdigit()
                       and any(f.startswith("stage_") for f in os.listdir(os.path.join(scrapes, d))))
    if not years:
        sys.exit(f"no scraped years found in {scrapes}")

    scratch = os.path.join(tempfile.mkdtemp(prefix="preview-reingest-"), "cycling.db")
    print(f"copying the database to {scratch} — the real one is never written",
          file=sys.stderr)
    shutil.copyfile(DB_PATH, scratch)
    import race_common
    race_common.DB_PATH = scratch
    import ingest_race
    ingest_race.DB_PATH = scratch

    reports = []
    for year in years:
        print(f"  {year} ...", end=" ", flush=True, file=sys.stderr)
        d, refusal, notes = run_one(scratch, args.race, info.name, year)
        d.update(year=year, refusal=refusal, notes=notes)
        reports.append(d)
        print("REFUSED" if refusal else
              f"+{sum(d['fill'].values())} ~{sum(d['over'].values())} "
              f"-{sum(d['clear'].values())}", file=sys.stderr)

    if args.csv:
        w = csv.writer(sys.stdout)
        w.writerow(["year", "kind", "column", "count"])
        for d in reports:
            for kind in ("fill", "over", "clear", "stage_fields"):
                for col, n in sorted(d[kind].items()):
                    w.writerow([d["year"], kind, col, n])
        return

    ok = [d for d in reports if not d["refusal"]]
    agg = {k: collections.Counter() for k in ("fill", "over", "clear", "stage_fields")}
    for d in ok:
        for k in agg:
            agg[k].update(d[k])

    print(f"\n{info.name}: {len(reports)} year(s), {len(ok)} would ingest, "
          f"{len(reports) - len(ok)} refused")
    print(f"rider-stage rows {sum(d['rows_before'] for d in ok):,} -> "
          f"{sum(d['rows_after'] for d in ok):,}  "
          f"({sum(d['gone'] for d in ok):,} gone, {sum(d['new'] for d in ok):,} new)\n")
    print(f"{'column':24s} {'NULL-fill':>11s} {'overwrite':>11s} {'clear':>11s}")
    for col in sorted(set(agg["fill"]) | set(agg["over"]) | set(agg["clear"])):
        print(f"{col:24s} {agg['fill'][col]:11,d} {agg['over'][col]:11,d} "
              f"{agg['clear'][col]:11,d}")
    if agg["stage_fields"]:
        print("\nstage fields changed: " +
              ", ".join(f"{c} {n:,}" for c, n in agg["stage_fields"].most_common()))

    refused = [d for d in reports if d["refusal"]]
    if refused:
        print(f"\nREFUSED — nothing would move, the edition rolls back:")
        for d in refused:
            print(f"  {d['year']}  {d['refusal']}")

    print(f"\n{'year':>6s} {'fill':>8s} {'over':>8s} {'clear':>8s}   rows")
    for d in reports:
        if d["refusal"]:
            print(f"{d['year']:6d} {'—':>8s} {'—':>8s} {'—':>8s}   refused")
            continue
        print(f"{d['year']:6d} {sum(d['fill'].values()):8,d} "
              f"{sum(d['over'].values()):8,d} {sum(d['clear'].values()):8,d}   "
              f"{d['rows_before']:,}->{d['rows_after']:,}")
        for note in d["notes"]:
            print(f"         {note[:100]}")

    if args.verbose:
        print("\nEXAMPLES (stage, rider, old -> new)")
        for d in ok:
            if not d["samples"]:
                continue
            print(f"  {d['year']}")
            for (kind, col), rows in sorted(d["samples"].items()):
                for stage_n, rider, old, new in rows:
                    print(f"    {kind:6s} {col:20s} st{stage_n:<3} {rider[:30]:30s} "
                          f"{old} -> {new}")


if __name__ == "__main__":
    main()
