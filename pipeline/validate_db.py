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
import bisect
import json
import os
import re
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
    check_orphan_riders(c)
    check_orphan_teams(c)
    check_dangling_alias_canonicals(c)


def check_dangling_alias_canonicals(c):
    """An alias whose canonical has no `riders` row — a pointer to nothing.

    rider_aliases.json is consulted at INGEST, so it outlives the rows it talks
    about: a canonical can be deleted (the 826-orphan purge did exactly that) or
    never created at all, and the entry still sits there naming it. Nothing
    noticed until two were found by hand on 2026-09-18 while merging a different
    rider. It is harmless while neither id can be minted, and a live defect the
    moment one can — the absorbed rider would resolve to an id that does not
    exist.

    An entry may carry a `dormant` key explaining why its canonical is legitimately
    absent; those are expected and stay quiet. Everything else warns. The two
    dormant entries today are Traka 360 finishers at PCS ranks 128 and 143, below
    the FIELD_CAP=100 that scrape_traka.py writes, so no code path can mint them.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rider_aliases.json")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        entries = (json.load(f).get("aliases") or {})
    live = {r[0] for r in c.execute("SELECT rider_id FROM riders")}
    missing = sorted(alias for alias, e in entries.items()
                     if e["canonical"] not in live and "dormant" not in e)
    if not missing:
        return
    warn(f"{len(missing)} alias(es) in rider_aliases.json name a canonical with no "
         f"`riders` row, so an ingest that mints the absorbed id would resolve it to "
         f"nothing. Either the canonical was deleted or it was never created. Add a "
         f"`dormant` key explaining why if that is expected. "
         + ", ".join(f"{a} -> {entries[a]['canonical']}" for a in missing[:3]))


def check_gc_rank_beyond_field(c):
    """A "GC position" that is not a position in its own classification.

    PCS published "1000" for Nibali on Vuelta 2015 st2 — the stage he was
    thrown off the race — and the ingest stored it as a rank, putting one rider
    1000th in a 198-rider field and making that stage read as a backwards GC
    ladder. `ingest_race.py` drops it in a post-pass now; this says so if one
    ever arrives by another route.

    **The obvious test is wrong and was tried first.** `gc_rank > COUNT(*)`
    flags 663 rows, because the row count is what a stage's PAGE published and
    the classification behind it is often bigger: Vuelta 1988 st21 stores ten
    finishers and ranks one of them 113th, correctly. `> 2 * COUNT(*)` still
    catches eight good rows. What holds is the shape of the rank set — a
    substantial classification, then a top rank that more than doubles the one
    below it. Archive-wide that matches exactly one row, against a next-worst
    jump of 75 (Giro 1969 st2, on a 21-rider remnant that the size floor
    excludes anyway).
    """
    rows = c.execute(
        """SELECT ra.name, e.year, s.stage_number, sr.rider_id, sr.gc_rank,
                  x.top, x.next_down, x.n
             FROM (SELECT stage_id,
                          MAX(gc_rank) top,
                          COUNT(*) n,
                          (SELECT MAX(gc_rank) FROM stage_results i
                            WHERE i.stage_id = o.stage_id
                              AND i.gc_rank < MAX(o.gc_rank)) next_down
                     FROM stage_results o
                    WHERE gc_rank IS NOT NULL
                    GROUP BY stage_id) x
             JOIN stage_results sr
               ON sr.stage_id = x.stage_id AND sr.gc_rank = x.top
             JOIN stages s ON s.stage_id = x.stage_id
             JOIN race_editions e USING(edition_id)
             JOIN races ra USING(race_id)
            WHERE x.n >= 50 AND x.next_down IS NOT NULL
              AND x.top > 2 * x.next_down
            ORDER BY x.top DESC"""
    ).fetchall()
    if not rows:
        return
    warn(f"{len(rows)} stage(s) hold a top GC position more than twice the next "
         f"one below it in a classification of 50 or more, which is a "
         f"placeholder rather than a position. "
         + ", ".join(f"{r[0][:6]} {r[1]} st{r[2]} {r[3]} rank {r[4]} "
                     f"(next {r[6]} of {r[7]})" for r in rows[:3]))


def check_corrupt_rider_names(c):
    """A `?` INSIDE a word is mojibake — a letter that did not survive the trip.

    Not to be confused with PCS's placeholder for a first name nobody recorded,
    which is a `?`, `??`, `???` or `.` standing ALONE after a surname —
    "Pujol ?", "Van Muyten ." — and is an honest record of an unknown. 16
    riders carry one, the frontend stops rendering it (see displayName()), and
    they are deliberately NOT reported here.

    It found two: `S?ren Nissen` and `Vojt?ch Marvan`. Both are upstream — the
    raw Athlinks response already says `S?ren` — and both had their rider_id
    MINTED from the corrupt string, so this also names the ids.

    **Nissen was merged away on 2026-09-19** into `rider/soren-nissen`, the
    same man filed twice because Athlinks spelled him two ways. The ages
    decided it, not the names: 30 at Leadville 2015 and 33 at Unbound 2018.
    That removed the corrupt id and the corrupt name together; the evidence is
    in `rider_aliases.json`, which the ingest reads, so a rebuild cannot
    recreate either.

    **Marvan stays**, and is now the only row here. He has no clean twin to
    merge into, and renaming him would pick a letter no source states
    (`Vojtěch` is near-certain for a Czech name of that shape, which is not the
    same as published).

    A count ABOVE one means a new scrape brought in more; read the raw file
    before touching the name, because the corruption is usually already there.
    """
    rows = c.execute(
        """SELECT rider_id, full_name FROM riders
            WHERE full_name GLOB '*[A-Za-z]?[A-Za-z]*'
              AND full_name LIKE '%?%'
            ORDER BY rider_id"""
    ).fetchall()
    # GLOB's `?` is a single-character wildcard, so the pattern above only
    # narrows to "some character between two letters" — every name matches it.
    # The literal test is done in Python, where `?` is just a character.
    bad = [(rid, name) for rid, name in rows
           if re.search(r"[^\W\d_]\?|\?[^\W\d_]", name)]
    if not bad:
        return
    # PROVE the id came from the corrupt name rather than guessing from its
    # shape: link_gravel_riders.slugify() is what minted it, and "S?ren Nissen"
    # runs through it to exactly "s-ren-nissen" because `?` is not [a-z0-9] and
    # becomes a separator. A merely hyphenated id proves nothing — every
    # two-word name has one.
    from link_gravel_riders import slugify
    minted = [rid for rid, name in bad
              if slugify(name) == rid.removeprefix("rider/")]
    warn(f"{len(bad)} rider name(s) hold a '?' inside a word, which is mojibake "
         f"rather than PCS's placeholder for an unrecorded first name. "
         f"{len(minted)} had an id minted from the corrupt string. The raw "
         f"scrape usually holds the same corruption — check it before renaming, "
         f"and see ai-context.md for why these are not repaired offline. "
         + ", ".join(f"{rid} ({name!r})" for rid, name in bad[:4]))


def check_orphan_riders(c):
    """Rider rows nothing references — the opposite direction to the checks above.

    A WARNING, not an error: a rider with no results is not corrupt, it is a row
    whose reason for existing went away. But it goes away SILENTLY, which is why
    this exists. 826 of them accumulated between 2026-08-24 and 2026-09-14
    without a single check noticing: re-sourcing The Traka from PCS replaced each
    edition's results, and every rider the timers had listed and PCS did not was
    left behind. They were found by reading data_provenance by hand, not by any
    validator, and the exporters never mentioned them because an unreferenced
    rider is never exported.

    Deleted 2026-09-14, which is why the expected count is now zero. A number
    above zero here means some ingest stranded rows again; read
    data_provenance's `script` and `recorded_at` for that rider_id to find out
    which run, the way those 826 were traced.
    """
    n = c.execute("""SELECT COUNT(*) FROM riders
                      WHERE rider_id NOT IN (SELECT DISTINCT rider_id FROM stage_results)""").fetchone()[0]
    if not n:
        return
    sample = [r[0] for r in c.execute("""SELECT rider_id FROM riders
                 WHERE rider_id NOT IN (SELECT DISTINCT rider_id FROM stage_results)
                 ORDER BY rider_id LIMIT 3""")]
    who = c.execute("""SELECT script, MIN(recorded_at), MAX(recorded_at) FROM data_provenance
                        WHERE entity='riders' AND entity_id IN (
                          SELECT rider_id FROM riders
                           WHERE rider_id NOT IN (SELECT DISTINCT rider_id FROM stage_results))
                        GROUP BY script ORDER BY COUNT(*) DESC LIMIT 1""").fetchone()
    trail = (f" — mostly written by {who[0]} between {str(who[1])[:10]} and "
             f"{str(who[2])[:10]}") if who else ""
    warn(f"{n:,} rider row(s) have no stage_results and are referenced by nothing"
         f"{trail}. e.g. {', '.join(sample)}. An unreferenced rider is never "
         "exported, so nothing downstream will ever complain about these.")


def check_orphan_teams(c):
    """Team rows nothing references — the `riders` problem one table over.

    Same mechanism as the 826 orphan riders, and it went unnoticed far longer
    because no check looked: **`teams` is append-only.** Every writer uses
    `INSERT OR IGNORE` or `upsert_team()`, no code path anywhere deletes a team
    row, and `replace_edition()` wipes an edition's `stage_results` wholesale
    on each re-ingest. A team row therefore outlives whatever created it — when
    a re-scrape spells the sponsor differently, or PCS switches between a short
    name and the full sponsor string, the riders move to the new `team_id` and
    the old row is stranded permanently. `team/kelme-1989` (`Kelme`) sits
    beside `team/kelme-iberia-varta-1989`; both held riders through 1988, and
    from 1989 the short one holds none.

    **Two kinds, and only one of them is litter**, which is the whole reason
    this reports them separately:

    * no `stage_results` AND no `classification_standings` — referenced by
      nothing, the deletable kind (733 at 2026-09-19);
    * no `stage_results` but a team-classification placing — **not useless and
      not deletable**, because that standing is the team's own result and does
      not need a rider row to be real (7 teams, 16 rows).

    A WARNING, not an error, and unlike `check_orphan_riders` the expected
    count is NOT zero: nothing has ever deleted these, so the number is a
    baseline to watch rather than a failure. A jump means a fresh ingest
    stranded more; read `data_provenance`'s `script` and `recorded_at` for the
    new ids to find which run. None of them reach the app either way — the team
    dropdown is built from riders' attributions, so a team with no riders is
    never exported.
    """
    UNREFERENCED = """
        SELECT team_id FROM teams t
         WHERE NOT EXISTS (SELECT 1 FROM stage_results sr WHERE sr.team_id=t.team_id)
           AND NOT EXISTS (SELECT 1 FROM classification_standings cs
                            WHERE cs.team_id=t.team_id)"""
    n = c.execute(f"SELECT COUNT(*) FROM ({UNREFERENCED})").fetchone()[0]
    if n:
        sample = [r[0] for r in c.execute(
            f"SELECT team_id FROM ({UNREFERENCED}) ORDER BY team_id LIMIT 3")]
        who = c.execute(f"""SELECT script, MIN(recorded_at), MAX(recorded_at)
                              FROM data_provenance
                             WHERE entity='teams' AND entity_id IN ({UNREFERENCED})
                             GROUP BY script ORDER BY COUNT(*) DESC LIMIT 1""").fetchone()
        trail = (f" — mostly written by {who[0]} between {str(who[1])[:10]} and "
                 f"{str(who[2])[:10]}") if who else ""
        warn(f"{n:,} team row(s) have no stage_results and are referenced by "
             f"nothing{trail}. e.g. {', '.join(sample)}. `teams` is append-only "
             "and nothing deletes these, so a steady number is the baseline; a "
             "jump means an ingest stranded more. An unreferenced team is never "
             "exported, so nothing downstream will complain about them.")

    kept = c.execute("""
        SELECT COUNT(*) FROM teams t
         WHERE NOT EXISTS (SELECT 1 FROM stage_results sr WHERE sr.team_id=t.team_id)
           AND EXISTS (SELECT 1 FROM classification_standings cs
                        WHERE cs.team_id=t.team_id)""").fetchone()[0]
    if kept:
        note(f"{kept} team(s) have no rider results but DO hold a team "
             "classification placing — a team's own result needs no rider row "
             "behind it. Not litter, and not safe to delete with the rest.")


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

    # Riders are keyed by their TEXT rider_id, not an integer, so this orphan
    # check compares as text. entity_id is declared INTEGER; SQLite's type
    # affinity leaves a non-numeric string alone, which is what makes that
    # work — but it also means a careless CAST would silently match nothing.
    n = c.execute(
        "SELECT COUNT(*) FROM data_provenance dp WHERE dp.entity='riders' "
        "AND NOT EXISTS (SELECT 1 FROM riders r WHERE r.rider_id = dp.entity_id)"
    ).fetchone()[0]
    if n:
        err(f"{n} data_provenance row(s) for entity='riders' name a rider that "
            "does not exist — a rider was renamed or deleted without clearing them")

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


def check_gc_rank_gap_consistency(c):
    """Riders sharing a GC position must share the GC gap that produced it.

    A general-classification rank IS a position on aggregate time, so two riders
    at the same rank are on the same time and the same gap. Rows that share a
    rank while disagreeing about the gap are internally contradictory: one of
    the two numbers is wrong and nothing downstream can tell which.

    A shared rank on its own is ordinary — Tour 1948 stage 1 has ten riders
    sharing 3rd, all on one time, which is what a bunch finish looks like. It is
    the DISAGREEING gap that is the fault, so this groups on (stage, gc_rank)
    and only reports where the gaps differ.

    Two populations, reported apart because only one is a defect:

    * **At rank 1**, this is the doping-annulment signature. PCS lists the
      stripped rider and the promoted one at the same position, the promoted
      rider keeping the gap he had to the man ahead — Scarponi at Giro 2011
      stage 21 carries 370s while Contador's stripped row carries 0. Expected,
      and check_results() already reports the stage-rank version of it.
    * **Below rank 1** it is not explained that way: 241 groups today and only
      14 hold a disqualified rider. The median disagreement is 23 seconds, so
      most are small — but the largest is Tour 1904 stage 6, where rank 2 holds
      388s and 18,945s, five hours apart.

    Rows PCS marks with a TIME IT AWARDED rather than timed are excluded
    outright: a rider credited with his group's time after a crash keeps the
    place he finished in, so his gap genuinely does not match the rank beside
    it and there is nothing to decide. See gc_source.py.

    A WARNING: the values are PCS's own, the annulment cases are correct as
    stored, and deciding which of two gaps is right needs the source page rather
    than a rule.

    check_gc_gap_monotonicity() is the wider view of the same defect and catches
    293 stages this one cannot see. It does not replace this: a tie whose two
    gaps both sit inside the surrounding ranks' window leaves the ladder
    ascending, so 14 of the stages below are invisible there.
    """
    rows = c.execute("""
        SELECT ra.name, re.year, s.stage_number, sr.gc_rank,
               COUNT(*) AS n, SUM(sr.disqualified) AS dq,
               MAX(sr.gc_gap_seconds) - MIN(sr.gc_gap_seconds) AS spread
          FROM stage_results sr
          JOIN stages s ON s.stage_id = sr.stage_id
          JOIN race_editions re ON re.edition_id = s.edition_id
          JOIN races ra ON ra.race_id = re.race_id
         WHERE sr.gc_rank IS NOT NULL AND sr.gc_gap_seconds IS NOT NULL
           AND sr.time_adjusted = 0
         GROUP BY s.stage_id, sr.gc_rank
        HAVING COUNT(*) > 1 AND COUNT(DISTINCT sr.gc_gap_seconds) > 1
         ORDER BY spread DESC""").fetchall()
    if not rows:
        return
    # main()'s connection has no row_factory, so every read here is BY INDEX:
    # (name, year, stage_number, gc_rank, n, dq, spread).
    NAME, YEAR, STAGE, RANK, _N, DQ, SPREAD = range(7)
    leader = [r for r in rows if r[RANK] == 1]
    rest = [r for r in rows if r[RANK] != 1]
    if leader:
        note(f"{len(leader)} GC position(s) at rank 1 hold two riders on different "
             f"gaps — the doping-annulment shape, where PCS lists the stripped and "
             f"the promoted rider together. {sum(1 for r in leader if r[DQ])} of "
             "them contain a row already flagged disqualified.")
    if rest:
        worst = ", ".join(
            f"{r[NAME].split()[0]} {r[YEAR]} st{r[STAGE]} rank "
            f"{r[RANK]} ({r[SPREAD]}s apart)" for r in rest[:3])
        warn(f"{len(rest)} GC position(s) below rank 1 are held by riders whose "
             f"gaps disagree, so the rank and the gap cannot both be right. Only "
             f"{sum(1 for r in rest if r[DQ])} involve a disqualified rider, so "
             f"most are not annulment fallout. Worst: {worst}")


def check_gc_gap_monotonicity(c):
    """A GC gap can never shrink as the rank grows.

    The general classification IS the ranking of aggregate time, so rank 29 is
    by definition no closer to the leader than rank 28. A ladder that runs
    backwards is therefore not a judgement call or an upstream quirk the way a
    missing value is — it is arithmetically impossible, and one of the two rows
    is wrong however the race was run.

    THIS IS THE WIDER VIEW OF check_gc_rank_gap_consistency, NOT ITS REPLACEMENT.
    That check finds two riders stored on one rank with different gaps; this one
    finds a gap that is out of order whether or not anything collides with it.
    Most corruption never collides, so the tie check saw 49 stages where this saw
    342 — but 14 of its 49 are invisible here, because a tie whose two gaps both
    fall inside the surrounding ranks' window keeps the ladder ascending while
    still contradicting itself. Neither check contains the other.

    Both now exclude rows whose time PCS marks as awarded rather than raced,
    which took the 342 to 113. See gc_source.py.

    Exempt, for the same reason as there: at rank 1 PCS lists the stripped rider
    and the promoted one together, and the promoted rider keeps the gap he held
    to the man ahead of him, so the ladder legitimately steps backwards out of
    the annulment. Rows flagged `disqualified` are skipped on either side of a
    step for the same reason.

    A WARNING, not an error. The values are PCS's own and this says only that
    the pair cannot both be right, never which one to keep: rank is not
    recoverable from gap (riders on equal time take DIFFERENT ranks, split by a
    tiebreak we do not store — deriving rank from gap alone moves 71,806 rows),
    and gap is not recoverable from rank. Closing one of these needs the source
    page, so this is a worklist for a re-scrape rather than a gate.
    """
    rows = c.execute("""
        SELECT s.stage_id, ra.name, re.year, s.stage_number,
               sr.gc_rank, sr.gc_gap_seconds,
               sr.disqualified OR sr.time_adjusted
          FROM stage_results sr
          JOIN stages s ON s.stage_id = sr.stage_id
          JOIN race_editions re ON re.edition_id = s.edition_id
          JOIN races ra ON ra.race_id = re.race_id
         WHERE sr.gc_rank IS NOT NULL AND sr.gc_gap_seconds IS NOT NULL
         ORDER BY s.stage_id, sr.gc_rank, sr.gc_gap_seconds""").fetchall()
    # main()'s connection has no row_factory, so every read here is BY INDEX.
    # The last column is `disqualified OR time_adjusted`: a step into or out of
    # either says nothing about the rows around it. A time-adjusted rider was
    # AWARDED a time he did not race, so PCS's own ladder steps backwards there
    # and ours is right to follow it — see gc_source.py.
    SID, NAME, YEAR, STAGE, RANK, GAP, DQ = range(7)
    by_stage = defaultdict(list)
    for r in rows:
        by_stage[r[SID]].append(r)

    # Sorting each stage by (rank, gap) puts a tie's smaller gap first, so a tie
    # is only counted as a step backwards when it disagrees with its NEIGHBOURS
    # rather than with itself — that case belongs to the check above.
    worst_per_stage = []
    for stage_rows in by_stage.values():
        worst = None
        for a, b in zip(stage_rows, stage_rows[1:]):
            if b[GAP] >= a[GAP] or a[RANK] == 1 or a[DQ] or b[DQ]:
                continue
            drop = a[GAP] - b[GAP]
            if worst is None or drop > worst[0]:
                worst = (drop, a, b)
        if worst:
            worst_per_stage.append(worst)
    if not worst_per_stage:
        return
    worst_per_stage.sort(key=lambda w: -w[0])
    examples = ", ".join(
        f"{a[NAME].split()[0]} {a[YEAR]} st{a[STAGE]} (rank {a[RANK]} is {a[GAP]}s "
        f"down, rank {b[RANK]} only {b[GAP]}s)"
        for _, a, b in worst_per_stage[:3])
    warn(f"{len(worst_per_stage)} stage(s) hold a GC ladder that runs backwards — "
         f"a later rank stored CLOSER to the leader than an earlier one, which no "
         f"race can produce. Rows PCS marks as time_adjusted are already excluded. "
         f"audit_gc_ladders.py triages what is left into the stages where one row "
         f"can be named and bounded and the rest that need the whole "
         f"classification. Worst: {examples}")

def check_gc_gap_zero_filler(c):
    """A stored GC gap of 0 that sits below a positive one cannot be a real tie.

    WHAT THIS ACTUALLY FINDS, corrected 2026-09-19 after the first reading was
    wrong. It was written up as PCS's "+0:00" filler read as a real zero, the
    same defect null_itt_filler_times.py fixed in the stage TIME column. It is
    not: 1,093 of the 1,095 rows are on STAGE 1 and carry gc_rank == stage_rank,
    which is the signature of this repo's own ingest.

    `ingest_race` has a fallback -- `if not gc_pos and n == 1` -- that gives a
    stage-1 rider his STAGE placing as a GC position and his stage gap as a GC
    gap. PCS publishes a GC position for very few riders after stage 1 (three
    of 180 on Vuelta 1996 stage 1: the top three, reordered by bonifications),
    so the fallback invents one for everybody else. The invented positions then
    collide with the real ones, which is why 748 stage-1 GC ranks in the archive
    are held by more than one rider, and why the invented gap of 0 sits below
    the published gap of +0:10 at the same rank.

    So the zero is usually TRUE -- a bunch rider really did finish on the
    winner's time -- and the RANK beside it is the fabricated half. Nulling
    these gaps would remove the true value and leave the false one, which is
    why nothing has been nulled.

    The two exceptions are the real thing: `rider/andris-nauduzs` on Giro 2004
    stages 11 and 12, whose gc_lag cell is "+0:00" while his stage gap is 15:20.

    The test is still comparative and still correct as a DETECTOR, whatever the
    cause: 7,735 riders genuinely share the leader's time, so only a zero with a
    positive gap already seen at a BETTER rank is impossible. Exempt for the
    usual two reasons -- a disqualified rider and one whose time PCS marks as
    awarded rather than raced are legitimately out of step with their rank.

    A WARNING. The repair is an ingest question (stop fabricating a stage-1 GC
    position, or prefer gc_standings for it) and it would move 26,315 rows, so
    it is Eric's call rather than a cleanup.
    """
    rows = c.execute("""
        SELECT s.stage_id, ra.name, re.year, s.stage_number, sr.gc_rank,
               sr.gc_gap_seconds, sr.disqualified OR sr.time_adjusted
          FROM stage_results sr
          JOIN stages s ON s.stage_id = sr.stage_id
          JOIN race_editions re ON re.edition_id = s.edition_id
          JOIN races ra ON ra.race_id = re.race_id
         WHERE sr.gc_rank IS NOT NULL AND sr.gc_gap_seconds IS NOT NULL
         -- gc_gap_seconds in the sort, not just the rank: two riders can share
         -- a rank, and without it SQLite may hand back the positive gap first
         -- and make the zero beside it look like it sits BELOW one. That is
         -- worth exactly two rows here, which is two too many for a number
         -- this reports as a count of defects.
         ORDER BY s.stage_id, sr.gc_rank, sr.gc_gap_seconds""").fetchall()
    SID, NAME, YEAR, STAGE, RANK, GAP, FLAG = range(7)
    by_stage = defaultdict(list)
    for r in rows:
        by_stage[r[SID]].append(r)

    per_edition = defaultdict(int)
    stages = set()
    for stage_rows in by_stage.values():
        best = 0
        for r in stage_rows:
            if r[GAP] == 0 and r[RANK] > 1 and best > 0 and not r[FLAG]:
                per_edition[(r[NAME], r[YEAR])] += 1
                stages.add(r[SID])
            best = max(best, r[GAP])
    if not stages:
        return
    total = sum(per_edition.values())
    worst = ", ".join(f"{n.split()[0]} {y} ({k})" for (n, y), k in
                      sorted(per_edition.items(), key=lambda kv: -kv[1])[:4])
    warn(f"{total} GC gap(s) across {len(stages)} stage(s) are stored as 0 while a "
         f"better rank in the same stage is already behind. Nearly all are stage 1, "
         f"where ingest_race gives a rider PCS left out of the classification his "
         f"STAGE placing instead — the invented rank then collides with a published "
         f"one. The zero is usually true and the rank beside it is not, so do NOT "
         f"null these. Worst: {worst}")


def check_field_definition(c):
    """Every off-road edition must say what field its ranks are over.

    An off-road race is a mass start with categories inside it, and which slice
    the timer publishes changes year to year — every gravel race but Little
    Sugar changes at least once, Leadville four times. Without this recorded,
    rank 3 at Leadville 2015 (third man across the line) and rank 3 at Leadville
    2016 (third PRO, with other men finishing between them) are the same number
    meaning two different things.

    Two failures, and the first is the dangerous one because it is silent: a
    NULL on a raced edition means an ingest wrote a stage without the rule, and
    every consumer then has to guess. The second is a value nothing understands,
    which would reach the frontend as an unlabelled field.
    """
    known = {"open_field", "elite_course", "elite_division", "pcs_field"}
    missing = c.execute(
        """SELECT ra.name, re.year FROM stages s
             JOIN race_editions re ON re.edition_id = s.edition_id
             JOIN races ra ON ra.race_id = re.race_id
            WHERE ra.race_type = 'gravel' AND s.cancelled = 0
              AND (s.field_definition IS NULL OR s.field_definition = '')
            ORDER BY ra.name, re.year""").fetchall()
    if missing:
        err(f"{len(missing)} off-road edition(s) do not record which field their "
            f"ranks are over, so a rank cannot be interpreted: "
            + ", ".join(f"{n} {y}" for n, y in missing[:5]))
    unknown = c.execute(
        """SELECT DISTINCT s.field_definition FROM stages s
             JOIN race_editions re ON re.edition_id = s.edition_id
             JOIN races ra ON ra.race_id = re.race_id
            WHERE ra.race_type = 'gravel' AND s.field_definition IS NOT NULL
              -- An empty string is an ingest that wrote nothing, and the
              -- missing check above already owns it. Reporting it here too
              -- double-counts one fault and sends the reader looking for a
              -- rule called ''.
              AND s.field_definition != ''
              AND s.field_definition NOT IN (%s)""" % ",".join("?" * len(known)),
        sorted(known)).fetchall()
    if unknown:
        err(f"unrecognised field_definition value(s): "
            + ", ".join(repr(u[0]) for u in unknown)
            + f". Known: {', '.join(sorted(known))}")
    # A road stage has exactly one field, so a value there is a mis-write.
    stray = c.execute(
        """SELECT COUNT(*) FROM stages s
             JOIN race_editions re ON re.edition_id = s.edition_id
             JOIN races ra ON ra.race_id = re.race_id
            WHERE ra.race_type != 'gravel' AND s.field_definition IS NOT NULL""").fetchone()[0]
    if stray:
        err(f"{stray} non-off-road stage(s) carry a field_definition; a stage "
            "with one field has nothing to disambiguate")


def check_gravel_rank_integrity(c):
    """A gravel classification that disagrees with its own clock, or numbers
    itself past its own size.

    Both come from how the gravel scraper ranks a DIVISION field. Where an
    edition publishes a Pro/Elite division, scrape_athlinks takes the whole
    division and reads each rider's place from Athlinks' `primary` ranking,
    on the documented assumption that a row fetched from /division/{id}/results
    carries its rank IN that division. **That assumption is not always true.**
    Leadville 2016 returns 43 riders whose `primary` tracks the OVERALL field
    instead, so the stored classification runs 1, 2, 3, 4, 5, 6, 8 ... 804 in a
    43-rider race, and Richard La China is recorded as finishing 804th.

    Two symptoms, checked separately because they catch different things:

    * **Ranks that run past the size of the field.** Three different causes
      produce this and the check does NOT guess between them, because two are
      harmless: a PCS-sourced edition stores PCS's own place in a field wider
      than the rows we keep (The Traka, ~1.1-1.6x), and a FIELD_CAP edition can
      lose a row to de-duplication after the window is taken (Unbound 2016 at
      98 of 100). Leadville 2016 is the one that is not explained that way at
      **18.7x**, so the report sorts by that ratio and leaves the reading to a
      human rather than asserting a bug.
    * **Finishers out of clock order.** Rarer and more interesting: 7 rows in
      the whole gravel corpus, and each one is a row whose time disagrees with
      its own ranking. They are the same class as the impossible times cleared
      in September 2026 — a checkpoint split stored as a finish — which is why
      Enrique Saborio is ranked 15th at Leadville 2017 on a 6.54h clock that
      would have put him 3rd.

    WARN, not ERROR. The underlying values are what Athlinks served, and the
    repair is a scraper change plus a re-ingest, not something a validator
    should imply is a one-line fix.
    """
    editions = defaultdict(list)
    for nm, yr, rk, t in c.execute(
            """SELECT ra.name, re.year, sr.stage_rank, sr.finish_time_seconds
                 FROM stage_results sr
                 JOIN stages s ON s.stage_id=sr.stage_id
                 JOIN race_editions re ON re.edition_id=s.edition_id
                 JOIN races ra ON ra.race_id=re.race_id
                WHERE ra.race_type='gravel' AND sr.stage_rank IS NOT NULL
                ORDER BY ra.name, re.year, sr.stage_rank"""):
        editions[(nm, yr)].append((rk, t))

    oversized, disordered = [], []
    for (nm, yr), rows in editions.items():
        ranks = [rk for rk, _ in rows]
        if max(ranks) > len(ranks):
            oversized.append((nm, yr, len(ranks), max(ranks)))
        # Count the rows that would have to move, not the pairs that disagree:
        # one badly placed rider otherwise reports as dozens of violations.
        times = [t for _, t in rows if t is not None]
        tails = []
        for x in times:
            i = bisect.bisect_right(tails, x)
            if i == len(tails):
                tails.append(x)
            else:
                tails[i] = x
        if len(times) - len(tails):
            disordered.append((nm, yr, len(times) - len(tails)))

    if oversized:
        # Sorted by RATIO, not by absolute rank: that is what separates a field
        # we merely store a subset of from one whose ranks are not places at all.
        worst = sorted(oversized, key=lambda e: -(e[3] / e[2]))[:4]
        warn(f"{len(oversized)} gravel edition(s) number their finishers past the "
             f"size of the field. Expected where we keep a subset of a wider "
             f"published field (PCS editions, or a FIELD_CAP window that later "
             f"loses a duplicate); a LARGE ratio instead means the stored numbers "
             f"are not places in this field at all. "
             + "; ".join(f"{nm} {yr}: {n} finishers ranked up to {mx} ({mx / n:.1f}x)"
                         for nm, yr, n, mx in worst))
    if disordered:
        warn(f"{sum(e[2] for e in disordered)} gravel finisher(s) across "
             f"{len(disordered)} edition(s) are ranked out of clock order. Each is "
             f"a row whose stored time disagrees with its own rank, usually a "
             f"checkpoint split kept as a finish. "
             + "; ".join(f"{nm} {yr} ({n})" for nm, yr, n in sorted(disordered)))


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

    # Zero is a value, not an absence, and no rider finishes a bike race in
    # no time. These are the residue of an older ingest: PCS gives only the
    # winner's time on these pages and leaves every other time cell blank, and
    # the blank became 0 instead of NULL. Tour 1937's 37 km stage-25 ITT holds
    # 45 of them, ranks 1 through 46 alongside a winner with a real 1:06:27.
    #
    # Re-ingesting does NOT fix them: today's code reads the same page's
    # "+0:00" filler gaps and would credit all 46 with the winner's time
    # instead, trading this defect for the ITT tie flagged below. The honest
    # value is NULL either way.
    zero_time = c.execute("""
        SELECT ra.name, re.year, s.stage_number, COUNT(*) n
        FROM stage_results sr
        JOIN stages s ON s.stage_id = sr.stage_id
        JOIN race_editions re ON re.edition_id = s.edition_id
        JOIN races ra ON ra.race_id = re.race_id
        WHERE sr.status = 'FINISHED' AND sr.finish_time_seconds = 0
        GROUP BY sr.stage_id ORDER BY n DESC""").fetchall()
    if zero_time:
        warn(f"{sum(z[3] for z in zero_time)} finisher(s) across {len(zero_time)} stage(s) "
             "have a finish time of exactly 0 seconds. Nobody finishes in no time — these "
             "are blank PCS time cells stored as 0 rather than NULL, and a re-ingest turns "
             "them into the ITT tie below rather than fixing them. e.g. "
             + ", ".join(f"{z[0][:6]} {z[1]} st{z[2]} ({z[3]})" for z in zero_time[:4]))

    # An individual time trial is ridden alone against the clock: the field
    # does not share a time. Where PCS has no per-rider times for an old ITT it
    # publishes a filler gap of "+0:00" against every rider, and ingest's
    # winner_seconds + gap_secs turns that absence into "everyone tied with the
    # winner" — 172 riders credited with the same 53:52 over the Giro 1985
    # stage-8 45 km ITT. Same shape as the cumulative-team-time defect: a
    # number that looks like data because it arrived in a time column.
    #
    # Threshold 20, from the distribution rather than taste: across 607 ITT
    # stages the tie counts are bimodal — 497 with none, a tail of 1-20 that is
    # genuine ties at second resolution (66 stages, 226 rows), then 44 stages
    # with 21 or more (4,524 rows) and nothing in between. WARN because the fix
    # is a re-scrape, not an edit: where PCS has since published real gaps a
    # re-ingest recovers them (the 2002 and 2003 Vuelta openers both did), and
    # where it has not, the honest value is NULL.
    itt_tied = c.execute("""
        WITH itt AS (
          SELECT s.stage_id, s.stage_number, s.edition_id, s.distance_km,
                 (SELECT MIN(finish_time_seconds) FROM stage_results
                  WHERE stage_id = s.stage_id AND stage_rank = 1
                    AND finish_time_seconds IS NOT NULL) AS wtime
          FROM stages s
          WHERE (s.stage_type = 'itt' OR s.route_type = 'TT') AND s.cancelled = 0
            -- stage_type can be a stale 'itt' on a stage route_type has since
            -- corrected to TTT (Vuelta 2003 st1 was both at once). A team time
            -- trial SHOULD have riders sharing a time, so exclude it by the
            -- column the re-ingest actually maintains.
            AND COALESCE(s.route_type, '') <> 'TTT')
        SELECT ra.name, re.year, itt.stage_number, itt.distance_km,
               SUM(sr.finish_time_seconds = itt.wtime
                   AND (sr.stage_rank IS NULL OR sr.stage_rank <> 1)) AS n_tied
        FROM itt
        JOIN stage_results sr ON sr.stage_id = itt.stage_id AND sr.status = 'FINISHED'
        JOIN race_editions re ON re.edition_id = itt.edition_id
        JOIN races ra ON ra.race_id = re.race_id
        WHERE itt.wtime IS NOT NULL
        GROUP BY itt.stage_id HAVING n_tied > 20
        ORDER BY n_tied DESC""").fetchall()
    if itt_tied:
        rows = sum(t[4] for t in itt_tied)
        warn(f"{len(itt_tied)} stage(s) typed as an individual time trial have {rows:,} "
             "riders on the winner's exact time. TWO different faults look like this and "
             "our data cannot tell them apart: PCS's '+0:00' filler gap read as a real "
             "gap (the times are fabricated), or a mass-start stage PCS mislabelled "
             "'Time trial' in won_how (the times are RIGHT and route_type is wrong). "
             "Giro 1985 stage-8a is the second kind — a 9x5 km 'Giri-sprint' circuit "
             "race, Foggia to Foggia, won by Allocchio from the bunch. Check the stage "
             "before touching a value: 30+ km of these average 45.6 km/h, which no era "
             "rode an ITT at. e.g. "
             + ", ".join(f"{t[0][:6]} {t[1]} st{t[2]} ({t[4]} of them"
                         + (f", {t[3]:.0f} km)" if t[3] else ")")
                         for t in itt_tied[:3]))

    # A team time trial cannot have been ridden by fewer people than the stage
    # after it: nobody joins a race mid-way. So every stage listed here is
    # missing riders who were demonstrably in the race.
    #
    # WHY it is missing them was measured on 2026-09-11, by re-fetching all ten
    # by source_slug and comparing both parses, and the answer is NOT what it
    # looks like. Only Vuelta 2003 st1 is a parser gap: PCS publishes a full
    # 197-rider results table there alongside 22 team blocks holding 168, and
    # scrape_race.py now keeps whichever is fuller. The other nine gain
    # nothing — PCS itself has only the team blocks (Giro 1956 st2b, Giro 1988
    # st4b, Vuelta 1960/1961/1992) or only a handful of riders at all (Tour
    # 1954 st4a has 10, Tour 1957 st3a has 15, on PCS as in the DB).
    #
    # So treat this as a coverage report, not a queue of parser bugs. Check the
    # page before assuming there is anything to recover — and fetch it by
    # source_slug, since 6 of these 10 are split days whose PCS slug is not
    # "stage-<n>" (DB stage 3 of the 1992 Vuelta is stage-2b; fetching stage-3
    # returns a 205 km road stage with 188 finishers and looks like a fix).
    ttt_short = c.execute("""
        SELECT ra.name, re.year, s.stage_number, COUNT(*) AS riders,
               COUNT(DISTINCT sr.team_id) AS teams,
               (SELECT COUNT(*) FROM stage_results sr2
                JOIN stages s2 ON s2.stage_id = sr2.stage_id
                WHERE s2.edition_id = s.edition_id
                  AND s2.stage_number = s.stage_number + 1) AS next_stage
        FROM stages s
        JOIN stage_results sr ON sr.stage_id = s.stage_id
        JOIN race_editions re ON re.edition_id = s.edition_id
        JOIN races ra ON ra.race_id = re.race_id
        WHERE s.route_type = 'TTT' AND s.cancelled = 0
        GROUP BY s.stage_id HAVING next_stage > riders + 5
        ORDER BY next_stage - riders DESC""").fetchall()
    if ttt_short:
        missing = sum(t[5] - t[3] for t in ttt_short)
        warn(f"{len(ttt_short)} team time trial(s) hold {missing:,} fewer riders than the "
             "stage immediately after them, so each is missing riders who were in the race. "
             "Measured 2026-09-11: 1 of 10 is recoverable (Vuelta 2003 st1, a full results "
             "table beside the team blocks); on the rest PCS has no more than we do. Check "
             "the page by source_slug before treating one as a parser bug. e.g. "
             + ", ".join(f"{t[0][:6]} {t[1]} st{t[2]} ({t[3]} in {t[4]} teams, next has {t[5]})"
                         for t in ttt_short[:3]))

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
        SELECT r.name, re.year FROM race_editions re
        JOIN races r ON r.race_id = re.race_id
        WHERE r.race_type = 'stage_race' AND NOT EXISTS (
          SELECT 1 FROM stage_results sr JOIN stages s ON sr.stage_id=s.stage_id
          WHERE s.edition_id=re.edition_id AND sr.gc_rank=1
            AND s.stage_number=(SELECT MAX(stage_number) FROM stages WHERE edition_id=re.edition_id))
        ORDER BY r.name, re.year
        """).fetchall()
    if nogc:
        # NAMED, because this one has a worklist. The missing rank 1 is a PROOF
        # rather than a symptom: the overall leader is necessarily in a complete
        # final classification, so an edition without one demonstrably does not
        # have the whole field. That makes its slowestFinisherTimeSeconds the
        # largest gap among the handful of riders stored — around 10th place in
        # these Giro years — and the All Races view charts it as "Slowest
        # Finisher" regardless.
        #
        # The house fix is to RESEARCH the real figure, not to suppress it: four
        # Vuelta years already carry one in vuelta_races_summary_overrides.json.
        # So the list matters more than the count.
        # An edition whose figure has been RESEARCHED is no longer charting a
        # wrong number, even though its stored classification is still partial.
        # Counting those with the rest is how a real worklist turns into noise
        # nobody reads, so they are separated and only the unresearched ones
        # are named.
        import json as _json
        covered = set()
        # The research record counts too, not just the overrides. Giro 1964 and
        # 1967 were read off PCS's own GC page and the figure already stored
        # turned out to be right, so no override was written — a no-op override
        # would be stripped by audit_summary_overrides.py anyway. Judging those
        # two "unresearched" would send someone to redo work that is done.
        for race_key, fname in (("Giro", "giro_gc_last_finisher.json"),
                                ("Vuelta", "vuelta_gc_last_finisher.json"),
                                ("Giro", "giro_races_summary_overrides.json"),
                                ("Vuelta", "vuelta_races_summary_overrides.json"),
                                ("Tour", "tour_all_races_summary_overrides.json")):
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                data = _json.load(f)
            for year, entry in data.items():
                if year.startswith("_"):
                    continue
                # an overrides file holds {year: {field: value}}; the research
                # file holds {year: seconds}
                if isinstance(entry, dict):
                    if "slowestFinisherTimeSeconds" in entry:
                        covered.add((race_key, int(year)))
                elif isinstance(entry, int):
                    covered.add((race_key, int(year)))
        open_ = [(n, y) for n, y in nogc if (n.split()[0], y) not in covered]
        done = len(nogc) - len(open_)
        if open_:
            who = ", ".join(f"{n.split()[0]} {y}" for n, y in open_[:6])
            warn(f"{len(open_)} of {len(nogc)} edition(s) with no gc_rank=1 on their "
                 "final stage have no researched slowestFinisherTimeSeconds, so "
                 "whatever the All Races view charts as 'Slowest Finisher' comes from "
                 "the handful of riders stored rather than the lanterne rouge — or, "
                 "where the edition has no winner time either, nothing is charted at "
                 f"all. Research or override: {who}"
                 + (f" ... and {len(open_) - 6} more" if len(open_) > 6 else "")
                 + (f". ({done} already carry a researched override.)" if done else ""))
        else:
            note(f"all {len(nogc)} edition(s) with a partial final classification "
                 "carry a researched slowestFinisherTimeSeconds override, so none of "
                 "them charts a figure taken from the handful of riders stored. The "
                 "classifications themselves are still partial.")


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
    check_corrupt_rider_names(cur)
    check_gc_rank_beyond_field(cur)
    check_provenance(cur)
    check_patched_values(cur)
    check_editions(cur, races)
    check_split_slug_provenance(cur)
    check_results(cur)
    check_gravel_rank_integrity(cur)
    check_field_definition(cur)
    check_gc_rank_gap_consistency(cur)
    check_gc_gap_monotonicity(cur)
    check_gc_gap_zero_filler(cur)
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
