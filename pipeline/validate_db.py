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
import json
import os
import sqlite3
import sys
from collections import defaultdict

from race_common import DB_PATH, VALID_SOURCES, load_stage_notes

# Provenance sources that ONLY a patch script ever writes. An ingest writes
# 'pcs', 'athlinks' and 'derived'; anything below arrived afterwards, by hand or
# from a second source, and a re-ingest will quietly throw it away.
PATCH_SOURCES = ("wikipedia", "bikeraceinfo", "cyclingflash", "manual")
PATCH_MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "patched_values.json")

RACES = ["Tour de France", "Giro d'Italia", "Vuelta a España"]

errors: list[str] = []
warnings: list[str] = []
notes: list[str] = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def note(msg):
    notes.append(msg)


def check_intentional_gaps(cur):
    """
    Reports stages that carry no results ON PURPOSE, and which of those still
    have no recorded reason.

    A cancelled stage with zero results is indistinguishable from a stage
    nobody has scraped yet — same row shape, same emptiness. Without this, each
    one gets rediscovered and re-investigated on every audit. Neither state is
    an error, so nothing here fails the run; the point is to say "this is
    finished, stop looking" for the documented ones and to name the rest so a
    reason can be added instead of invented.
    """
    stage_notes = load_stage_notes()
    rows = cur.execute(
        """SELECT r.name, e.year, s.stage_number, s.start_location, s.finish_location
           FROM stages s
           JOIN race_editions e USING(edition_id)
           JOIN races r USING(race_id)
           WHERE s.cancelled = 1
           ORDER BY r.name, e.year, s.stage_number"""
    ).fetchall()
    if not rows:
        return

    undocumented = [r for r in rows if (r[0], r[1], r[2]) not in stage_notes]
    note(f"{len(rows)} stage(s) carry no results by design (cancelled=1); "
         f"{len(rows) - len(undocumented)} documented in stage_notes.json")
    for race, year, num, start, finish in undocumented:
        note(f"  undocumented: {race} {year} stage {num} ({start} -> {finish})")

    # A note keyed to a stage that isn't there explains nothing and silences
    # nothing — it just sits in the file looking like the job is done. The
    # likeliest cause is keying by the PCS slug number instead of the DB's
    # stage_number, which differ on every edition with a split day.
    live = {(r[0], r[1], r[2]) for r in rows}
    for key in stage_notes:
        if key not in live:
            warn(f"stage_notes.json has a note for {key[0]} {key[1]} stage {key[2]}, "
                 f"which is not a cancelled stage in the DB (wrong stage_number?)")


def check_phantom_split_days(cur):
    """
    A cancelled stage sharing a date with another stage, without the split-day
    slug that would justify it.

    compute_stage_labels() reads a repeated consecutive date as a split day and
    labels the pair '19a'/'19b' — correct when the day really was split, and
    wrong otherwise. Wrong is expensive: it renames the stage AND shifts every
    later label down one, because the pair consumes a single day number. Giro
    1969's cancelled Trento-Marmolada carried stage 19's date until 2026-08-15,
    so it rendered as '19b' and the finale showed as 22 instead of 23.

    SCOPED TO CANCELLED STAGES, and that scope is the whole check. A cancelled
    stage is where a bad date hides: it has no results, so nobody reads its
    row, and its date was parsed from a page that had nothing else on it.
    Ordinary stages cannot be screened this way at all — PCS letters split days
    in some editions and numbers them SEQUENTIALLY in others (TDF 1986
    stage-1/stage-2 fall on one day and are a genuine split), so the same rule
    applied to every stage produced 33 false errors on correct data.

    The slug still separates the two cancelled cases: a real split half ends in
    a letter, and Giro 1956 stage-9b and Vuelta 1978 stage-19b are both genuine
    cancelled second halves that must NOT be flagged.
    """
    rows = cur.execute(
        """SELECT r.name, e.year, s.stage_number, s.stage_date, s.source_slug, s.edition_id
           FROM stages s
           JOIN race_editions e USING(edition_id)
           JOIN races r USING(race_id)
           WHERE r.race_type = 'stage_race' AND s.stage_date IS NOT NULL
           ORDER BY r.name, e.year, s.stage_number"""
    ).fetchall()

    dates_seen = defaultdict(int)
    for row in rows:
        dates_seen[(row[5], row[3])] += 1

    cancelled = cur.execute(
        """SELECT r.name, e.year, s.stage_number, s.stage_date, s.source_slug, s.edition_id
           FROM stages s
           JOIN race_editions e USING(edition_id)
           JOIN races r USING(race_id)
           WHERE r.race_type = 'stage_race' AND s.cancelled = 1
             AND s.stage_date IS NOT NULL
           ORDER BY r.name, e.year, s.stage_number"""
    ).fetchall()

    for race, year, num, date, slug, edition_id in cancelled:
        if dates_seen[(edition_id, date)] < 2:
            continue
        if slug and slug[-1].isalpha():
            continue        # 'stage-19b' — a genuine cancelled split half
        err(f"{race} {year} stage {num} ({slug}) is cancelled and shares date "
            f"{date} with another stage, but its slug is not a split half — it "
            f"renders as a phantom split day and shifts every later label")


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
    # Orphan check, across EVERY entity rather than just 'stages'.
    #
    # It used to look at entity='stages' alone, and that blind spot is exactly
    # how a re-ingest destroyed 1,884 bikeraceinfo team attributions in silence
    # on 2026-08-21: those rows are entity='stage_results', keyed by stage_id,
    # so replace_edition() (which clears only entity='stages') left all 6,254
    # of them pointing at stage_ids it had just deleted. Counts were unchanged,
    # every check passed, and the data was gone.
    # entity_id is a STAGE id for both entities: patch_classics_teams.py and
    # patch_classics_times.py call record_provenance(cur, "stage_results",
    # stage_id, "team_id:rider/x", ...), putting the rider in `field` rather
    # than keying on result_id.
    n = c.execute(
        "SELECT COUNT(*) FROM data_provenance dp WHERE dp.entity='stages' "
        "AND NOT EXISTS (SELECT 1 FROM stages s WHERE s.stage_id=dp.entity_id)"
    ).fetchone()[0]
    if n:
        err(f"{n} orphaned data_provenance row(s) — an edition was re-ingested "
            "without clearing them; ingest_race.py should do this")

    # The same check for entity='stage_results', which nothing cleared until
    # 2026-08-21: replace_edition() and ingest_race.py both delete only
    # entity='stages' rows, so every re-ingest-then-re-patch cycle left the
    # previous cycle's rows behind pointing at a deleted stage_id.
    #
    # WARN, not ERROR: a stale row is litter, not loss. It describes a stage
    # that no longer exists, so it makes no claim about any live value. What
    # WOULD be loss is caught below, by checking live provenance against the
    # values it claims.
    stale = c.execute(
        "SELECT COUNT(*) FROM data_provenance dp WHERE dp.entity='stage_results' "
        "AND NOT EXISTS (SELECT 1 FROM stages s WHERE s.stage_id=dp.entity_id)"
    ).fetchone()[0]
    if stale:
        warn(f"{stale} data_provenance row(s) for entity='stage_results' point at "
             "a stage that no longer exists — litter from re-ingest cycles before "
             "replace_edition() started clearing them. Purge with "
             "python3 validate_db.py --purge-stale-provenance")

    # Driven off race_common.VALID_SOURCES rather than a second hardcoded
    # list: the two silently diverged when 'cyclingflash' was added, and the
    # validator failed a value record_provenance() had already accepted.
    bad = c.execute(
        "SELECT DISTINCT source FROM data_provenance WHERE source NOT IN "
        "(%s)" % ",".join("?" * len(VALID_SOURCES)),
        tuple(sorted(VALID_SOURCES))
    ).fetchall()
    for (s,) in bad:
        err(f"data_provenance has unknown source value {s!r}")


def check_patched_values(c, update=False):
    """Assert that every value a patch script produced is still patched.

    THE PROBLEM THIS EXISTS FOR. An ingest rebuilds a race-year from its scrape
    files, which are a faithful record of what the SOURCE said — not of what we
    later worked out to be true. Corrections live in a second layer (the
    patch_*.py scripts) that writes straight to the DB, so a full re-ingest
    reverts them and nothing notices: on 2026-08-21 a re-ingest put Milan-San
    Remo 2013 back to PCS's wrong 121.0 km, discarding a researched Wikipedia
    value, while every count stayed identical and every check stayed green.

    Two complementary tests, because the two failure shapes differ:

      1. The manifest. When a stage is re-ingested its provenance rows are
         deleted and rewritten as 'pcs', so the evidence of the patch vanishes
         with the patch. Absence cannot be detected from the DB alone, so the
         expected set is recorded in patched_values.json — keyed on race, year,
         stage number and field, never on stage_id, which changes on re-ingest.

      2. Contradiction. A row like 'team_id:rider/x' on entity='stage_results'
         survives a re-ingest (see check_provenance) but the value it describes
         does not. Provenance claiming a value that is now NULL is proof of
         loss, and needs no baseline at all.

    Run with --update-patch-manifest after deliberately adding or removing a
    patch; that is the only thing that should ever change this file.
    """
    rows = c.execute(
        """SELECT dp.source, dp.field, r.name, e.year, s.stage_number
           FROM data_provenance dp
           JOIN stages s ON s.stage_id = dp.entity_id
           JOIN race_editions e USING(edition_id)
           JOIN races r USING(race_id)
           WHERE dp.entity = 'stages' AND dp.source IN (%s)
           ORDER BY r.name, e.year, s.stage_number, dp.field"""
        % ",".join("?" * len(PATCH_SOURCES)), PATCH_SOURCES).fetchall()
    current = sorted([r[2], r[3], r[4], r[1], r[0]] for r in rows)

    # Stage-field patches are only half the exposure. patch_classics_teams.py
    # and patch_classics_times.py fill values on stage_results, and those keep
    # their provenance keyed to a stage_id that a re-ingest replaces — so after
    # a revert the provenance is merely stale, not contradicted, and nothing
    # above notices. What DOES move, unmistakably, is how many of those values
    # exist: the 2026-08-21 incident took the classics from 84,800 team
    # attributions to 82,916 while every other number held still.
    counts = {}
    for label, col in (("team_id", "team_id"),
                       ("finish_time_seconds", "finish_time_seconds")):
        for (rt, n) in c.execute(
                f"""SELECT r.race_type, COUNT(*) FROM stage_results sr
                    JOIN stages s USING(stage_id)
                    JOIN race_editions e USING(edition_id)
                    JOIN races r USING(race_id)
                    WHERE sr.{col} IS NOT NULL GROUP BY r.race_type"""):
            counts[f"{rt}.{label}"] = n

    if update:
        with open(PATCH_MANIFEST, "w", encoding="utf-8") as f:
            json.dump({"_README": (
                "Values written by a patch script rather than by an ingest. "
                "validate_db.py fails if any of them reverts to an ingest "
                "source, which is what a full re-ingest silently does. "
                "Regenerate ONLY when deliberately changing a patch: "
                "python3 validate_db.py --update-patch-manifest"),
                "patched": current, "value_counts": counts},
                f, indent=1, ensure_ascii=False)
            f.write("\n")
        print(f"wrote {os.path.basename(PATCH_MANIFEST)}: {len(current)} patched value(s)")
        return

    if not os.path.exists(PATCH_MANIFEST):
        warn("patched_values.json is missing, so a re-ingest that reverted a "
             "patched value could not be detected. Create it with "
             "python3 validate_db.py --update-patch-manifest")
        return
    with open(PATCH_MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    expected = [list(x) for x in manifest["patched"]]

    # A DROP is the alarm. A rise is new data and merely wants the manifest
    # refreshed, so it is a note rather than a failure.
    for key, want in (manifest.get("value_counts") or {}).items():
        have = counts.get(key, 0)
        if have < want:
            err(f"VALUES LOST: {key} fell from {want:,} to {have:,} "
                f"({want - have:,} gone) — a re-ingest reverted a patch that "
                "fills this column. Restore from a backup and re-run the patch "
                "scripts (patch_classics_teams.py, patch_classics_times.py).")
        elif have > want:
            note(f"{key} rose from {want:,} to {have:,}; refresh the manifest "
                 "with --update-patch-manifest if that was deliberate")

    missing = [e for e in expected if e not in current]
    for race, year, stage, field, source in missing[:12]:
        now = c.execute(
            """SELECT dp.source FROM data_provenance dp
               JOIN stages s ON s.stage_id = dp.entity_id
               JOIN race_editions e USING(edition_id) JOIN races r USING(race_id)
               WHERE dp.entity='stages' AND dp.field=? AND r.name=? AND e.year=?
                 AND s.stage_number=?""", (field, race, year, stage)).fetchone()
        err(f"PATCH LOST: {race} {year} stage {stage} {field} was {source!r}, "
            f"now {(now[0] if now else 'absent')!r} — a re-ingest reverted it. "
            "Restore from a backup and re-run that patch script.")
    if len(missing) > 12:
        err(f"...and {len(missing)-12} more reverted patched value(s)")

    added = [c for c in current if c not in expected]
    if added:
        note(f"{len(added)} patched value(s) not in patched_values.json — if "
             "deliberate, refresh it with --update-patch-manifest")

    # Contradiction test. These rows record both the result_id and, inside
    # `field`, the rider the value belongs to — so they can be checked against
    # reality with no baseline at all. Two ways they can be wrong after a
    # re-ingest: the row they name now holds a DIFFERENT rider (result_id is
    # not AUTOINCREMENT, so ids get reused), or it holds the right rider with
    # the patched value gone.
    # These rows name both the stage and, inside `field`, the rider — so they
    # can be checked against reality with no baseline at all. A LIVE row whose
    # value is NULL means the patch was applied and then thrown away.
    qmarks = ",".join("?" * len(PATCH_SOURCES))
    gone = c.execute(
        f"""SELECT COUNT(*) FROM data_provenance dp
            JOIN stage_results sr ON sr.stage_id = dp.entity_id
              AND sr.rider_id = substr(dp.field, instr(dp.field, ':') + 1)
            WHERE dp.entity='stage_results' AND dp.source IN ({qmarks})
              AND ((dp.field LIKE 'team_id:%' AND sr.team_id IS NULL)
                OR (dp.field LIKE 'finish_time_seconds:%'
                    AND sr.finish_time_seconds IS NULL))""",
        PATCH_SOURCES).fetchone()[0]
    if gone:
        err(f"{gone} result(s) carry patch provenance for a value that is now "
            "NULL — the patch was reverted, most likely by a re-ingest. "
            "Restore from a backup and re-run that patch script.")


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
        # or one PCS spells differently. Nothing in the route tells the two
        # apart, so they stay derived rather than confirmed on a guess. A
        # spelling case CAN be closed by adopting PCS's name where it is the
        # official one — Vuelta 2022 st15 became "Sierra Nevada (Alto Hoya de la
        # Mora)" and confirmed immediately.
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
        # "Mostly team time trials, upstream limitation" was wrong, and the
        # label discouraged looking: 25 of the 28 TDF TTTs listed here DID have
        # per-rider results on PCS, grouped by team, and were recovered with
        # reingest_tdf_stage.py --from-pcs (43 stages -> 18). What is left is a
        # real limitation — three TTTs where PCS's team blocks carry an empty
        # rider table, and stages that were neutralised, stopped or protested
        # so no individual result was ever declared. Before adding to this
        # list, check the page for a ttt-results block with riders in it.
        warn(f"{rankless} stage(s) have results but no finishing positions at all: "
             "stages neutralised or abandoned mid-race, plus three 1980s TTTs "
             "where PCS publishes team times against an empty rider table.")

    # Scoped to stage races BY INCLUSION, not by excluding 'one_day'. A one-day
    # classic has no general classification at all, so every one of its
    # editions would trip this check forever (it took the count from 17 to 83
    # the day the classics landed) — and the exclusion list silently stopped
    # covering that the day a second non-stage-race type ('gravel') arrived.
    # Naming what DOES have a GC cannot rot the same way.
    nogc = c.execute("""
        SELECT COUNT(*) FROM race_editions re
        JOIN races r ON r.race_id = re.race_id
        WHERE r.race_type = 'stage_race' AND NOT EXISTS (
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
    ap.add_argument("--purge-stale-provenance", action="store_true",
                    help="delete data_provenance rows describing a stage that "
                         "no longer exists; they make no claim about live data")
    ap.add_argument("--update-patch-manifest", action="store_true",
                    help="rewrite patched_values.json from the DB's current "
                         "state; only after deliberately changing a patch")
    args = ap.parse_args()

    races = RACES
    if args.race:
        races = [{"tdf": "Tour de France", "giro": "Giro d'Italia",
                  "vuelta": "Vuelta a España"}[args.race]]

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = conn.cursor()

    if args.purge_stale_provenance:
        # Needs write access, so it opens its own connection rather than using
        # the read-only one every check shares.
        conn.close()
        w = sqlite3.connect(DB_PATH)
        n = w.execute(
            "DELETE FROM data_provenance WHERE entity IN ('stages','stage_results') "
            "AND NOT EXISTS (SELECT 1 FROM stages s WHERE s.stage_id=entity_id)"
        ).rowcount
        w.commit()
        w.close()
        print(f"purged {n} stale data_provenance row(s)")
        return 0

    if args.update_patch_manifest:
        check_patched_values(cur, update=True)
        conn.close()
        return 0

    check_referential(cur)
    check_provenance(cur)
    check_patched_values(cur)
    check_editions(cur, races)
    check_split_slug_provenance(cur)
    check_results(cur)
    check_phantom_split_days(cur)
    check_intentional_gaps(cur)
    conn.close()

    for e in errors:
        print(f"ERROR  {e}")
    for w in warnings:
        print(f"warn   {w}")
    # Informational only — never affects the exit code, including under
    # --strict. These describe data that is correct and finished.
    for n in notes:
        print(f"note   {n}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors or (args.strict and warnings) else 0)


if __name__ == "__main__":
    main()
