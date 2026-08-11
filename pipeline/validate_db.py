#!/usr/bin/env python3
"""
Integrity checks against cycling.db itself.

validate_exports.py checks the JSON the app consumes; this checks the database
those exports are built from, so a defect is caught before it propagates. Every
check here corresponds to a failure mode that actually occurred:

  * stage-number gaps          2010 Vuelta silently lost PCS stages 11 and 12
  * duplicate stages           1991 Vuelta had a stage duplicated to stand in
                               for a cancelled one that was never scraped
  * orphaned provenance        re-ingest mints new stage_ids, stranding rows
  * missing/duplicate slugs    a wrong source_slug re-fetches the wrong page
  * unverified split slugs     PCS letters split days in some editions and
                               numbers them sequentially in others; a derived
                               slug is a guess (201 were wrong)

Severities:
  ERROR  a real defect — exits 1
  WARN   known upstream limitation or judgement call, reported not failed

Usage:
  python3 validate_db.py
  python3 validate_db.py --race vuelta
  python3 validate_db.py --strict     # treat warnings as failures too
"""

import argparse
import sqlite3
import sys
from collections import defaultdict

from race_common import DB_PATH

RACES = ["Tour de France", "Giro d'Italia", "Vuelta a España"]

errors: list[str] = []
warnings: list[str] = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def check_referential(c):
    for label, sql in [
        ("stage_results referencing a missing stage",
         "SELECT COUNT(*) FROM stage_results sr LEFT JOIN stages s USING(stage_id) WHERE s.stage_id IS NULL"),
        ("stage_results referencing a missing rider",
         "SELECT COUNT(*) FROM stage_results sr LEFT JOIN riders r USING(rider_id) WHERE r.rider_id IS NULL"),
        ("stage_results referencing a missing team",
         "SELECT COUNT(*) FROM stage_results sr LEFT JOIN teams t USING(team_id) "
         "WHERE sr.team_id IS NOT NULL AND t.team_id IS NULL"),
        ("stages referencing a missing edition",
         "SELECT COUNT(*) FROM stages s LEFT JOIN race_editions re USING(edition_id) WHERE re.edition_id IS NULL"),
        ("classification_standings referencing a missing rider",
         "SELECT COUNT(*) FROM classification_standings cs LEFT JOIN riders r USING(rider_id) WHERE r.rider_id IS NULL"),
    ]:
        n = c.execute(sql).fetchone()[0]
        if n:
            err(f"{n} {label}")


def check_provenance(c):
    n = c.execute(
        "SELECT COUNT(*) FROM data_provenance dp WHERE dp.entity='stages' "
        "AND NOT EXISTS (SELECT 1 FROM stages s WHERE s.stage_id=dp.entity_id)"
    ).fetchone()[0]
    if n:
        err(f"{n} orphaned data_provenance row(s) — an edition was re-ingested "
            "without clearing them; ingest_race.py should do this")

    bad = c.execute(
        "SELECT DISTINCT source FROM data_provenance WHERE source NOT IN "
        "('pcs','wikipedia','bikeraceinfo','manual','derived','unknown')"
    ).fetchall()
    for (s,) in bad:
        err(f"data_provenance has unknown source value {s!r}")


def check_editions(c, races):
    c2 = c.connection.cursor()
    for race in races:
        rid = c.execute("SELECT race_id FROM races WHERE name=?", (race,)).fetchone()
        if not rid:
            continue
        for e in c.execute(
            "SELECT edition_id, year FROM race_editions WHERE race_id=? ORDER BY year",
            (rid[0],),
        ).fetchall():
            eid, year = e[0], e[1]
            tag = f"{race[:6]} {year}"
            stages = c2.execute(
                "SELECT stage_number, stage_date, source_slug, start_location, "
                "finish_location, distance_km, cancelled, "
                "(SELECT source FROM data_provenance WHERE entity='stages' "
                " AND entity_id=stages.stage_id AND field='distance_km') "
                "FROM stages WHERE edition_id=? ORDER BY stage_number", (eid,)
            ).fetchall()
            if not stages:
                continue
            nums = [s[0] for s in stages]

            gaps = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
            if gaps:
                err(f"{tag}: gap in stage numbering at {gaps} — a stage is missing")

            slugs = [s[2] for s in stages]
            if any(x is None for x in slugs):
                err(f"{tag}: {sum(x is None for x in slugs)} stage(s) with no source_slug")
            dupes = {x for x in slugs if x and slugs.count(x) > 1}
            if dupes:
                err(f"{tag}: source_slug reused within the edition: {sorted(dupes)}")

            # Duplicate detection keys on the PCS slug as well as date and
            # route. A split day can legitimately run two stages over the same
            # circuit on the same date at the same distance — Giro 1972's 12a
            # and 12b are both 20 km Forte dei Marmi > Forte dei Marmi, won by
            # Merckx and Swerts respectively. Distinct slugs mean distinct PCS
            # pages, so they are two stages, not one duplicated.
            seen = {}
            for s in stages:
                key = (s[1], s[3], s[4], s[5], s[2])
                if s[1] and key in seen:
                    err(f"{tag}: stages {seen[key]} and {s[0]} are identical "
                        f"({s[3]} -> {s[4]} on {s[1]}, same slug {s[2]})")
                seen[key] = s[0]

            for s in stages:
                if s[5] is not None and s[5] < 0:
                    err(f"{tag} stage {s[0]}: negative distance {s[5]}")
                if not s[6] and s[5] == 0:
                    warn(f"{tag} stage {s[0]}: zero distance on a non-cancelled stage")

            # A stage whose distance exactly equals the one before it, over a
            # different route, is the signature of a hole filled by carrying
            # the neighbouring value forward. PCS publishes "0 km" for a number
            # of finales, and six Tours ended up with the previous day's figure
            # on the run into Paris — 1989's 24.5 km LeMond time trial was
            # stored as a 130 km road stage. See fix_paris_finale_distances.py.
            #
            # Equal distances alone are far too common to flag — round numbers
            # repeat and 38 editions match, nearly all coincidence. Two filters
            # make it actionable. The value's provenance must be UNKNOWN
            # (patched by a source nobody recorded), and it must be the FINAL
            # stage, which is where PCS's missing distances cluster and where a
            # wrong figure also skews the edition total and the finish-line
            # view. Every one of the six real cases satisfies both.
            prev, last = (stages[-2], stages[-1]) if len(stages) > 1 else (None, None)
            if (prev and prev[5] and last[5] and abs(prev[5] - last[5]) < 0.05
                    and not prev[6] and not last[6]
                    and (last[7] or "unknown") == "unknown"
                    and (prev[3], prev[4]) != (last[3], last[4])):
                warn(f"{tag} final stage {last[0]}: distance {last[5]} km is identical "
                     f"to stage {prev[0]}'s over a different route, from an unrecorded "
                     "source — check it was not copied from the neighbour")


def check_split_slug_provenance(c):
    """Split editions whose slugs were derived rather than probed."""
    c2 = c.connection.cursor()
    suspect = []
    for (eid, year, race) in c.execute(
        "SELECT re.edition_id, re.year, r.name FROM race_editions re "
        "JOIN races r ON re.race_id=r.race_id"
    ).fetchall():
        dates = [x[0] for x in c2.execute(
            "SELECT stage_date FROM stages WHERE edition_id=? AND stage_date IS NOT NULL", (eid,))]
        if not dates or len(set(dates)) == len(dates):
            continue                                   # no split day
        derived = c2.execute(
            "SELECT COUNT(*) FROM data_provenance dp JOIN stages s ON s.stage_id=dp.entity_id "
            "WHERE s.edition_id=? AND dp.field='source_slug' AND dp.source='derived'", (eid,)
        ).fetchone()[0]
        if derived:
            suspect.append(f"{race[:6]} {year} ({derived})")
    if suspect:
        # Do NOT send anyone to resolve_source_slugs.py for these, which is what
        # this warning used to say. That tool probes the split-day convention and
        # records provenance only for slugs it REWRITES; run against the 107 split
        # editions it found 104 already correct, rejected its own proposals for the
        # other 3 on route verification, and wrote nothing — it cannot clear this.
        # audit_stage_counts.py --confirm-slugs is what carries the evidence: PCS's
        # stage list pairs each slug with its route, one request per edition. That
        # took this from 4,572 stages to 31.
        #
        # The remainder are the cases route matching cannot settle: a route that
        # repeats inside one edition (a prologue and a stage 1a both Nice > Nice)
        # or one PCS spells differently ("Martos - Sierra Nevada (Alto Hoya de la
        # Mora)"). Nothing in the route tells the two apart, so they stay derived
        # rather than being confirmed on a guess.
        warn(f"{len(suspect)} split edition(s) still carry DERIVED source_slug on "
             "stages whose route is not unique within the edition, so PCS's stage "
             "list cannot confirm which is which. Run audit_stage_counts.py "
             f"--confirm-slugs first; what remains needs a human. "
             f"{', '.join(suspect[:8])}" + (" ..." if len(suspect) > 8 else ""))


def check_results(c):
    multi = c.execute("""
        SELECT ra.name, re.year, s.stage_number, s.route_type, COUNT(*) n
        FROM stage_results sr
        JOIN stages s ON sr.stage_id=s.stage_id
        JOIN race_editions re ON s.edition_id=re.edition_id
        JOIN races ra ON re.race_id=ra.race_id
        WHERE sr.stage_rank=1 GROUP BY sr.stage_id HAVING n>1""").fetchall()
    # A team time trial legitimately gives every rider on the team rank 1.
    non_ttt = [m for m in multi if m[3] != "TTT"]
    if non_ttt:
        warn(f"{len(non_ttt)} stage(s) have more than one rank-1 finisher outside a TTT. "
             "These are overwhelmingly doping disqualifications where PCS lists both the "
             "stripped and the promoted rider, both stored as status='FINISHED'. "
             f"e.g. {', '.join(f'{m[0][:6]} {m[1]} st{m[2]}' for m in non_ttt[:4])}")

    rankless = c.execute("""
        SELECT COUNT(*) FROM stages s WHERE s.cancelled=0
          AND EXISTS(SELECT 1 FROM stage_results WHERE stage_id=s.stage_id)
          AND NOT EXISTS(SELECT 1 FROM stage_results WHERE stage_id=s.stage_id
                         AND stage_rank IS NOT NULL)""").fetchone()[0]
    if rankless:
        warn(f"{rankless} stage(s) have results but no finishing positions at all "
             "(PCS marks the whole field 'DF'; mostly team time trials). Upstream limitation.")

    nogc = c.execute("""
        SELECT COUNT(*) FROM race_editions re WHERE NOT EXISTS (
          SELECT 1 FROM stage_results sr JOIN stages s ON sr.stage_id=s.stage_id
          WHERE s.edition_id=re.edition_id AND sr.gc_rank=1
            AND s.stage_number=(SELECT MAX(stage_number) FROM stages WHERE edition_id=re.edition_id))
        """).fetchone()[0]
    if nogc:
        warn(f"{nogc} edition(s) have no gc_rank=1 on their final stage — the final "
             "stage's result set is sparse, which also makes slowestFinisherTimeSeconds "
             "unreliable for those years")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=["tdf", "giro", "vuelta"], default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    races = RACES
    if args.race:
        races = [{"tdf": "Tour de France", "giro": "Giro d'Italia",
                  "vuelta": "Vuelta a España"}[args.race]]

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = conn.cursor()

    check_referential(cur)
    check_provenance(cur)
    check_editions(cur, races)
    check_split_slug_provenance(cur)
    check_results(cur)
    conn.close()

    for e in errors:
        print(f"ERROR  {e}")
    for w in warnings:
        print(f"warn   {w}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors or (args.strict and warnings) else 0)


if __name__ == "__main__":
    main()
