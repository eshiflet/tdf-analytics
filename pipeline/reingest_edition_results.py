#!/usr/bin/env python3
"""
Rebuild one race-year's stage_results from its scrape files, in place.

WHY THIS EXISTS. Correcting a scrape file is only half a repair: the database
still holds what the file used to say. Nothing could push such a correction
back for a Tour edition — add_pre1960.py refuses any edition already in the DB
and only knows 1939/1947-1959, and reingest_tdf_stage.py replaces a single
stage without recomputing the general classification, which silently NULLed
102 gc_ranks on TDF 1924 stage 4 the one time it was tried.

GC IS NOT CARRIED FORWARD. It was, when this script was written on 2026-09-09,
because add_pre1960.py did and preserving behaviour seemed the conservative
choice during a name-swap repair. That was wrong, and build_vuelta_gc_standings.py
had already said so: "the old ingest carry-forward INVENTED per-stage GC by
replicating stale values". A rider's gap changes every stage, so repeating last
stage's figure asserts they neither gained nor lost time. 53,903 of the Tour's
66,673 stored gc_ranks were invented that way.

So the priority here is the same as ingest_race.py's: (1) the stage row's own
gc_pos, authoritative when present; (2) the year's gc_standings.json sidecar,
real PCS standings merged with gaps computed from actual stage results; (3)
nothing. A NULL is a gap; a repeated value is a claim.

WHAT IT DOES NOT TOUCH. The `stages` rows: distance, elevation, route type,
dates and their provenance live only in the database for the older editions —
144 distances and 40 elevation figures across those six Tours alone, all of
them 'unknown' provenance with no origin left to re-fetch from. A rebuild that
dropped those could not put them back, so this rebuilds `stage_results` and
nothing else.

Every stage race, every year, one code path: the layout difference between the
Tour's one-file-per-year and the Giro/Vuelta's one-file-per-stage lives in
race_common.load_stage_rows and nowhere else.

Usage:
  python3 reingest_edition_results.py --race tour --year 1924 --dry-run
  python3 reingest_edition_results.py --race tour --year 1924 --apply
  python3 reingest_edition_results.py --race tour 1924 1935 1937 --apply
"""

import argparse
import re
import sqlite3
import sys

from race_common import (
    COUNTRY_NAMES,
    DB_PATH,
    RACES,
    SOURCE_DERIVED,
    SOURCE_PCS,
    STAGE_RACES,
    StageRow,
    fix_mojibake,
    load_sidecar,
    load_stage_rows,
    parse_bonus_seconds,
    parse_int,
    parse_time_to_seconds,
    record_provenance,
    year_sources,
)

DB_RACE_NAME = {"tour": "Tour de France", **{k: v.name for k, v in RACES.items()}}

NON_FINISH = {"DNF": "DNF", "DNS": "DNS", "OTL": "OTL", "NP": "NP",
              "DSQ": "DSQ", "DEL": "DEL", "DF": "DNF"}


def build_results(stages, standings=None):
    """[(stage_n, [result dicts])] with GC carried forward, as the ingest does.

    `standings` is the year's gc_standings.json, or None. It fills only where
    the row itself is silent, and NEVER overrides a published gc_pos — doing so
    dropped 26-48% of finishers' GC rank on several Giro editions before
    ingest_race.py was corrected.
    """
    out = []
    for n in sorted(stages):
        winner_seconds, rows = None, []
        for row in stages[n].get("rows", []):
            if len(row) < 15:
                continue
            sr = StageRow.from_list(row)
            if not sr.slug:
                continue                     # an incident line, not a result

            gc_pos, gc_lag = sr.gc_pos, sr.gc_lag
            if not gc_pos and n == min(stages) and parse_int(sr.rnk) is not None:
                # On the opening stage the finishing order IS the classification.
                gc_pos, gc_lag = str(parse_int(sr.rnk)), sr.gap
            gc_rank_v = parse_int(gc_pos)
            gc_gap_v = parse_time_to_seconds(gc_lag)
            if gc_rank_v is None and standings:
                entry = standings.get(n, {}).get(sr.slug)
                if entry:
                    gc_rank_v, gc_gap_v = entry[0], entry[1]

            status = NON_FINISH.get(sr.rnk, "FINISHED")
            abs_secs = parse_time_to_seconds(sr.abs_time)
            gap_secs = parse_time_to_seconds(sr.gap)
            if status == "FINISHED" and abs_secs is not None and sr.rnk == "1":
                winner_seconds = abs_secs

            finish = None
            if status == "FINISHED" and winner_seconds is not None:
                if gap_secs is not None:
                    finish = winner_seconds + gap_secs
                elif parse_int(sr.rnk) == 1:
                    finish = winner_seconds

            rows.append({
                "slug": sr.slug, "name": sr.name, "nat": sr.nat,
                "team_slug": sr.team_slug or None, "team_name": sr.team,
                "bib": parse_int(sr.bib),
                "stage_rank": parse_int(sr.rnk) if status == "FINISHED" else None,
                "status": status, "finish": finish, "gap": gap_secs,
                "bonus": parse_bonus_seconds(sr.bonus),
                "pcs": parse_int(sr.pcs_pts),
                "gc_rank": gc_rank_v,
                "gc_gap": gc_gap_v,
                "age": parse_int(sr.age),
            })
        out.append((n, rows))
    return out


def db_stages(cur, race, year):
    """{stage_number: stage_id} for an edition already in the database."""
    return {r["stage_number"]: r["stage_id"] for r in cur.execute(
        """SELECT s.stage_number, s.stage_id FROM stages s
             JOIN race_editions e ON e.edition_id = s.edition_id
             JOIN races r ON r.race_id = e.race_id
            WHERE r.name = ? AND e.year = ?""", (DB_RACE_NAME[race], year))}


def reingest(cur, race, year, key, apply_it, allow_gc_drop=False):
    stages, _ = load_stage_rows(race, key)
    raw = load_sidecar(race, year, "gc_standings.json")
    standings = ({int(n): e for n, e in raw.get("stages", {}).items()}
                 if raw else None)
    known = db_stages(cur, race, year)
    if not known:
        print(f"  {race} {year}: not in the database, skipping")
        return 0, 0

    built = [(n, rows) for n, rows in build_results(stages, standings) if n in known]
    if not built:
        print(f"  {race} {year}: no stage in the file matches the database")
        return 0, 0

    before = {n: cur.execute(
        "SELECT COUNT(*), COUNT(stage_rank), COUNT(gc_rank) FROM stage_results "
        "WHERE stage_id=?", (known[n],)).fetchone() for n, _ in built}

    tot_rows = sum(len(r) for _, r in built)
    tot_ranked = sum(1 for _, r in built for x in r if x["stage_rank"] is not None)
    tot_gc = sum(1 for _, r in built for x in r if x["gc_rank"] is not None)
    old_rows = sum(b[0] for b in before.values())
    old_ranked = sum(b[1] for b in before.values())
    old_gc = sum(b[2] for b in before.values())
    print(f"  {race} {year}: rows {old_rows} -> {tot_rows}, "
          f"ranked {old_ranked} -> {tot_ranked}, gc {old_gc} -> {tot_gc}")

    # The guards reingest_tdf_stage.py has, plus the one it was missing. Losing
    # GC standings is what made the narrow tool unusable for this repair.
    for label, old, new in (("rows", old_rows, tot_rows),
                            ("ranks", old_ranked, tot_ranked),
                            ("gc standings", old_gc, tot_gc)):
        if new < old:
            # --replace-invented-gc is the one case where losing GC is the
            # point: the stored values were carried forward from a previous
            # stage rather than published, and the incoming ones are computed
            # from real stage times and validated against the authoritative
            # standings. Never a default — every other caller wants the refusal.
            if label == "gc standings" and allow_gc_drop:
                print(f"    replacing {old} carried GC value(s) with {new} computed")
                continue
            print(f"    REFUSING: that would lose {old - new} {label}")
            return 0, 0

    if not apply_it:
        return tot_rows, 0

    written = 0
    for n, rows in built:
        sid = known[n]
        cur.execute("DELETE FROM stage_results WHERE stage_id=?", (sid,))
        cur.execute("DELETE FROM data_provenance WHERE entity='stage_results' "
                    "AND entity_id=?", (sid,))
        for x in rows:
            if x["nat"]:
                cur.execute("INSERT OR IGNORE INTO countries (code, name) VALUES (?,?)",
                            (x["nat"], COUNTRY_NAMES.get(x["nat"])))
            cur.execute("INSERT OR IGNORE INTO riders (rider_id, full_name, "
                        "nationality_code) VALUES (?,?,?)",
                        (x["slug"], fix_mojibake(x["name"]), x["nat"] or None))
            if x["team_slug"]:
                m = re.search(r"-(\d{4})$", x["team_slug"])
                cur.execute("INSERT OR IGNORE INTO teams (team_id, name, season_year) "
                            "VALUES (?,?,?)", (x["team_slug"], fix_mojibake(x["team_name"]),
                                               int(m.group(1)) if m else None))
            cur.execute(
                """INSERT OR IGNORE INTO stage_results
                     (stage_id, rider_id, team_id, bib_number, stage_rank, status,
                      finish_time_seconds, gap_seconds, bonus_seconds, penalty_seconds,
                      uci_points, pcs_points, gc_rank, gc_gap_seconds, age_at_race)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, x["slug"], x["team_slug"], x["bib"], x["stage_rank"], x["status"],
                 x["finish"], x["gap"], x["bonus"], 0, None, x["pcs"],
                 x["gc_rank"], x["gc_gap"], x["age"]))
        # One 'results' row per stage covers every stage_results row it wrote.
        record_provenance(cur, "stages", sid, "results", SOURCE_PCS,
                          source_ref=f"{race} {year} scrape files, rebuilt with "
                                     "carried-forward GC",
                          script="reingest_edition_results.py")
        written += 1
    return tot_rows, written


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=list(STAGE_RACES), required=True)
    ap.add_argument("--year", type=int)
    ap.add_argument("years", nargs="*", type=int)
    ap.add_argument("--replace-invented-gc", action="store_true",
                    help="allow carried-forward GC to be replaced by fewer, real values")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    wanted = set(args.years) | ({args.year} if args.year else set())
    sources = [(y, k) for y, k in year_sources(args.race) if not wanted or y in wanted]
    if not sources:
        sys.exit(f"no scrape files for {args.race} {sorted(wanted) or ''}".strip())

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    print(f"{'[DRY RUN] ' if not args.apply else ''}{args.race}: "
          f"{len(sources)} race-year(s)")
    rows = stages_written = 0
    for year, key in sources:
        r, w = reingest(cur, args.race, year, key, args.apply,
                        args.replace_invented_gc)
        rows += r
        stages_written += w
    if args.apply:
        conn.commit()
        print(f"\nrebuilt {rows} result(s) across {stages_written} stage(s)")
    else:
        print(f"\nwould rebuild {rows} result(s)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
