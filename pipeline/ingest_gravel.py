#!/usr/bin/env python3
"""Ingest the Life Time off-road scrapes into cycling.db.

Each race is its own race row (races.race_type = 'gravel') with exactly one
stage per edition — the same shape the one-day classics use, and for the same
reason: these are independent races that the frontend later aggregates into a
single displayed "season" at export time. Nothing here knows about that.

Reads gravel_scrapes/<race-slug>/<year>.json (scrape_athlinks.py) and
gravel_scrapes/_rider_ids.json (link_gravel_riders.py). Re-ingesting a
race-year deletes and re-creates it atomically, so the script is safe to
re-run.

What is deliberately NOT stored:

  vertical_meters   STORED where PCS publishes it (The Traka 2026: 4198 m),
                    read by scrape_pcs_gravel.parse_parcours. Athlinks
                    publishes no elevation, so its six races stay NULL: every
                    published figure for, say, Leadville disagrees with every
                    other (11,586 ft and 14,517 ft for the same course, from
                    two RideWithGPS traces), so the column waits until a
                    source is chosen per race-year. A NULL is a gap; a guess
                    would be a claim.
  profile_score     PCS's metric, stored alongside the elevation. A 0 printed
                    against an unmeasured "-" elevation means unrated rather
                    than flat and is not stored. Athlinks has no equivalent.
  team_id           Athlinks records no team. lifetimegrandprix.com does, but
                    only ONE team per athlete — their current one — so
                    attaching it to a 2022 result would be fiction.

Usage:
  python3 ingest_gravel.py --dry-run
  python3 ingest_gravel.py
  python3 ingest_gravel.py --race leadville --year 2019
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import sys

from ingest_classics import upsert_team
from link_gravel_riders import fold
from race_set_ingest import (
    capture_patches,
    replace_edition,
    report_patches,
    restore_patches,
    upsert_country,
    upsert_race,
)
from race_common import (
    GRAVEL,
    SOURCE_ATHLINKS,
    SOURCE_DERIVED,
    fix_mojibake,
    gravel_route_type,
    record_provenance,
    load_rider_aliases,
    load_rider_splits,
    load_tandem_entries,
    fold_name,
    strip_series_flag,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
SCRAPES = os.path.join(HERE, "gravel_scrapes")
RIDER_IDS = os.path.join(SCRAPES, "_rider_ids.json")

# Above upsert_rider because that is what reads it. It used to sit 60 lines
# further down, inside the comment block explaining the Dorsal placeholder
# filter, which is a different subject.
RIDER_ALIASES = load_rider_aliases()
# One id that is really two people, keyed on (rider_id, race, year) — see
# race_common.load_rider_splits. Applied AFTER the alias map, because a split
# acts on the canonical id: the absorbed spelling never reaches this point.
RIDER_SPLITS = load_rider_splits()
# Two people on one bib. Not riders, and this schema cannot say what they
# are — see tandem_entries.json for why it is a list and not a rule.
TANDEMS = load_tandem_entries()


def upsert_rider(cur, ident, source=SOURCE_ATHLINKS, source_ref=None):
    """Insert a gravel-only rider; leave an already-known rider untouched.

    The no-overwrite rule is the same one ingest_classics.py follows, and it
    matters more here: when link_gravel_riders.py says this name IS
    `rider/peter-stetina`, the road career is the authority on his name,
    nationality and birth year. Athlinks knows only where he currently lives.
    """
    # Resolve the alias HERE, before the row is created, the way
    # ingest_classics.upsert_rider() does. The caller used to resolve it
    # afterwards, which is a different thing entirely: upsert_rider had already
    # INSERTed the absorbed id by then, and only the stage_result carried the
    # canonical one. So every gravel ingest minted a rider row that nothing
    # referenced, and re-minted it on the next run — 22 of the 23 ids in
    # rider_aliases.json were sitting in `riders` with zero results, including
    # 22 created by a run on 2026-09-12. It did not undo the merge (the results
    # were on the right rider) and so nothing that checks results ever saw it.
    rid = RIDER_ALIASES.get(ident["rider_id"], ident["rider_id"])
    cur.execute("SELECT rider_id FROM riders WHERE rider_id = ?", (rid,))
    if cur.fetchone():
        return rid
    name = fix_mojibake(ident["name"])
    first = fix_mojibake(ident.get("first_name"))
    last = fix_mojibake(ident.get("last_name"))
    cur.execute(
        """INSERT INTO riders (rider_id, full_name, nationality_code,
                               birth_year_approx, first_name, last_name)
           VALUES (?,?,?,?,?,?)""",
        (rid, name, upsert_country(cur, ident.get("country")),
         ident.get("birth_year_approx"), first, last),
    )
    # NOTE on nationality: Athlinks records where an athlete LIVES, not their
    # nationality, and the two differ for real riders in this data (Torbjorn
    # Andre Roed races as Norwegian out of Grand Junction, Colorado). It is
    # stored anyway because it is right for the overwhelming majority and a
    # missing flag helps nobody — but it is never allowed to overwrite a
    # nationality that came from PCS, which is why this function returns early
    # above. That caveat is what `nationality_code`'s provenance below means:
    # athlinks is the honest source, and it is a residence, not a passport.
    # The source is the race file this rider is first seen in — which is where
    # the stored values actually came from. A rider who later turns up in
    # another off-road race keeps this row, because upsert returns early above.
    for field in ("full_name", "first_name", "last_name", "nationality_code",
                  "birth_year_approx"):
        record_provenance(cur, "riders", rid, field, source,
                          source_ref=source_ref or "gravel_scrapes/_rider_ids.json")
    return rid


# tretzesports publishes a PLACEHOLDER in the name field itself where it timed
# an entrant it could not name: the raw 2021 Traka rows read
# {"Nom": "DORSAL 71 ", "Temps": "DNS", "PosicioSexe": "-1"}. "Dorsal" is
# Spanish for bib number, so this is the timer saying "bib 71, no name" -- not
# a person. Ingested literally it became nine riders called "Dorsal 71" through
# "Dorsal 79", each with its own rider_id and a row in the riders table.
#
# Matched on the name alone, which is what the placeholder actually is. The
# scrape files are NOT edited: they are the record of what the source said, and
# the filter belongs at the point the DB decides what a rider is.
PLACEHOLDER_NAME_RE = re.compile(r"^dorsal[\s_-]*\d+\b", re.I)


def upsert_split_rider(cur, rule, source=SOURCE_ATHLINKS, source_ref=None):
    """The second person behind a shared id, created on demand.

    Deliberately NOT upsert_rider(): that one takes an `ident` out of
    _rider_ids.json, and the whole point of a split is that the linker has no
    entry for this person — it folded them into somebody else. The row is built
    from the split rule, which is where the evidence for the claim lives.
    """
    rid = rule["rider_id"]
    cur.execute("SELECT rider_id FROM riders WHERE rider_id = ?", (rid,))
    if cur.fetchone():
        return rid
    name = rule["name"]
    parts = name.split()
    first, last = ((" ".join(parts[:-1]), parts[-1]) if len(parts) > 1
                   else (None, name))
    cur.execute(
        """INSERT INTO riders (rider_id, full_name, nationality_code,
                               birth_year_approx, first_name, last_name)
           VALUES (?,?,?,?,?,?)""",
        (rid, name, upsert_country(cur, rule.get("nationality_code")),
         rule.get("birth_year_approx"), first, last),
    )
    for field in ("full_name", "first_name", "last_name", "nationality_code",
                  "birth_year_approx"):
        record_provenance(cur, "riders", rid, field, source,
                          source_ref=source_ref,
                          script="ingest_gravel.py (rider_splits.json)")
    return rid


def is_placeholder_name(name: str) -> bool:
    return bool(PLACEHOLDER_NAME_RE.match((name or "").strip()))


def ingest_one(cur, path, rider_ids, dry_run=False):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    info = data["info"]
    slug, year = info["race_slug"], info["year"]
    if slug not in GRAVEL:
        raise ValueError(f"{path}: unknown gravel slug {slug!r}")
    meta = GRAVEL[slug]

    if dry_run:
        return (slug, year, len(data["rows"]), data["cancelled"], info.get("rule"))

    race_id = upsert_race(cur, meta.name, meta.country, "gravel")
    # Read the patches out BEFORE the rebuild destroys them; put them back after.
    patched = capture_patches(cur, race_id, year)
    # Atomic: clears this edition's stages, results and provenance first.
    edition_id = replace_edition(cur, race_id, year, info.get("event_name"))

    # The resolved Athlinks address, stored so nothing ever re-finds this race
    # by searching course names again — the same discipline as source_slug for
    # PCS, and for the same reason: the name is not stable, the id is.
    # Not every gravel race is on Athlinks: The Traka's editions are addressed
    # by sportmaniacs event uuid or tretzesports idCursa. The file says which,
    # and an older file that does not say predates any of that and is Athlinks.
    source = info.get("source", SOURCE_ATHLINKS)
    if source == SOURCE_ATHLINKS:
        source_slug = (f"event/{info['event_id']}/race/{info['course_id']}"
                       if info.get("course_id") else f"event/{info['event_id']}")
    else:
        source_slug = f"{source}/{info['event_id']}"
    route = gravel_route_type(info.get("discipline"))
    cur.execute(
        """INSERT INTO stages
             (edition_id, stage_number, stage_label, stage_date, distance_km,
              stage_type, route_type, cancelled, source_slug,
              vertical_meters, profile_score)
           VALUES (?,1,?,?,?,?,?,?,?,?,?)""",
        (edition_id, meta.name, info.get("date"), info.get("distance_km"),
         info.get("discipline"), route,
         1 if data["cancelled"] else 0, source_slug,
         info.get("vertical_meters"), info.get("profile_score")),
    )
    stage_id = cur.lastrowid

    api = info.get("api_url") or info.get("source_url")
    # 'results' covers every stage_results row below: they come out of this same
    # fetch, so they are recorded here rather than per rider (see schema.sql).
    tracked = ["stage_date", "distance_km", "source_slug", "cancelled",
               "stage_type", "results"]
    # PCS is the only gravel upstream that publishes a parcours, and only for
    # the editions it has actually measured (see parse_parcours). Claim an
    # origin for what the source addressed — an Athlinks file carries neither
    # key, and recording 'athlinks' against a NULL nobody looked for would
    # assert something the timer never said.
    tracked += [f for f in ("vertical_meters", "profile_score") if f in info]
    for field in tracked:
        record_provenance(cur, "stages", stage_id, field, source,
                          source_ref=api)
    record_provenance(cur, "stages", stage_id, "route_type", SOURCE_DERIVED,
                      source_ref="race_common.gravel_route_type(discipline)")

    inserted = 0
    # stage_results is keyed on (stage_id, rider_id), so two rows that resolve
    # to the same rider silently overwrite each other. That is almost always
    # the right thing — but not when two DIFFERENT people share a name in one
    # field, which really happens: Chequamegon 2007 has two Matthew Nelsons,
    # aged 36 and 32, from different Wisconsin towns, finishing 50th and 53rd.
    # Identity here is by name (see link_gravel_riders.py) and Athlinks gives
    # nothing better, so the row IS lost — but it is reported, not hidden.
    seen_riders = {}
    collisions = []
    placeholders = []          # bib-only rows with no result: skipped
    named_placeholders = []    # bib-only rows that DID place: kept, reported
    tandems = []               # two-person entries: dropped, reported
    maybe_tandems = []         # unlisted rows joined by "&"/"and": reported only
    tandem_names = TANDEMS.get((slug, year), set())
    for r in data["rows"]:
        # Same strip the linker applies before it takes an identity key, or
        # the lookup below misses: _rider_ids.json is keyed on the cleaned
        # name. See race_common.strip_series_flag.
        key = strip_series_flag(r["name"])
        # A bib with no name behind it is not a rider. Skipped only when the
        # row also carries NO result -- every one seen so far is a DNS with no
        # rank and no time, so nothing is lost. A placeholder that DID finish
        # would be a real result we simply cannot name, and dropping it would
        # shrink the field and move other riders' positions, so it is kept and
        # reported instead. Same rule as the malformed-row handling in
        # ingest_race: never silently drop a result.
        # A TANDEM is two people sharing one bib and one finish. Storing it
        # makes a rider who does not exist, and every check downstream then
        # treats that person as real — which is how "Elliot Cooper Sally
        # Finkbeiner" ended up being proposed for merging into Elliot Cooper.
        # Dropped rather than kept-and-flagged, unlike a named placeholder,
        # because a placeholder is one real rider we cannot name while this is
        # two riders we cannot separate.
        if fold_name(key) in tandem_names:
            tandems.append((key, r.get("rank")))
            continue
        if re.search(r"\s(?:&|and)\s", key, re.I):
            maybe_tandems.append((key, r.get("rank")))
        if is_placeholder_name(key):
            if r.get("finish_seconds") is None and r.get("rank") is None:
                placeholders.append(key)
                continue
            named_placeholders.append((key, r.get("rank"), r.get("finish_seconds")))
        ident = rider_ids.get(fold(key).strip())
        if ident is None:
            raise KeyError(
                f"{path}: {key!r} has no entry in _rider_ids.json — "
                "re-run link_gravel_riders.py after any new scrape")
        # Returns the CANONICAL id: upsert_rider resolves the alias before it
        # inserts, so the absorbed id is never written. The scrape file still
        # carries the old spelling, which is why the mapping has to be applied
        # somewhere on every run. See race_common.load_rider_aliases.
        rider_id = upsert_rider(cur, ident, source, api)
        split = RIDER_SPLITS.get((rider_id, slug, year))
        if split:
            rider_id = upsert_split_rider(cur, split, source, api)
        if rider_id in seen_riders:
            collisions.append((r["name"], seen_riders[rider_id], r.get("rank")))
        seen_riders[rider_id] = r.get("rank")
        bib = r.get("bib")
        # Athlinks records no team, which is why this column was NULL for every
        # gravel result. A PCS-sourced row DOES carry one, and it is a real
        # trade team for that season — the same kind of value the classics
        # store, from the same source. Coverage is sparse (PCS names a team for
        # 2 to 29 riders an edition), and sparse-but-real beats absent.
        team_id = upsert_team(cur, r.get("team_slug"), r.get("team_name"), api)
        cur.execute(
            """INSERT OR REPLACE INTO stage_results
                 (stage_id, rider_id, team_id, bib_number, stage_rank, status,
                  finish_time_seconds, gap_seconds, age_at_race)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (stage_id, rider_id, team_id,
             int(bib) if (bib or "").isdigit() else None,
             r.get("rank"), r.get("status") or "FINISHED",
             r.get("finish_seconds"), r.get("gap_seconds"), r.get("age")),
        )
        inserted += 1

    # ── A finisher cannot beat the winner and still rank behind him ──────
    #
    # Athlinks asserts both. Unbound 2026 has Paul Voss at status CONF, rank
    # 14, with a gun time of 6h32m over a 326 km course -- 49.9 km/h on
    # gravel. Eleven riders in that edition, 37 across the set. The DB matched
    # the scrape file exactly and every record carried a real gun time, so
    # this is the timer's own data disagreeing with itself, not a parse.
    #
    # The RELATIONAL test is what catches it. race_common.implausible_speed()
    # cannot: its ceiling is calibrated for road racing, where a short
    # prologue legitimately exceeds 55 km/h, so 52.6 sails through. "Slower
    # than the man you finished behind" needs no course knowledge at all.
    #
    # DIRECTION MATTERS, and this is the part worth reading twice. If MOST of
    # the field beats the winner, the wrong time is the WINNER'S, and nulling
    # everyone else would destroy a good field to protect one bad row. So a
    # majority is reported and left alone; only a minority is nulled.
    #
    # The rank and status stay: the rider finished and placed. What is removed
    # is a duration that cannot be true.
    # NOTE: this connection has no row_factory, so every read here is by INDEX.
    wrow = cur.execute(
        """SELECT MIN(finish_time_seconds) FROM stage_results
            WHERE stage_id = ? AND stage_rank = 1 AND status = 'FINISHED'
              AND finish_time_seconds > 0""", (stage_id,)).fetchone()
    wsecs = wrow[0] if wrow else None
    impossible = []
    if wsecs:
        impossible = cur.execute(
            """SELECT sr.result_id, sr.stage_rank, sr.finish_time_seconds, ri.full_name
                 FROM stage_results sr JOIN riders ri ON ri.rider_id = sr.rider_id
                WHERE sr.stage_id = ? AND sr.status = 'FINISHED'
                  AND sr.stage_rank > 1 AND sr.finish_time_seconds > 0
                  AND sr.finish_time_seconds < ?""", (stage_id, wsecs)).fetchall()
        n_fin = cur.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage_id=? AND status='FINISHED'",
            (stage_id,)).fetchone()[0]
        if impossible and len(impossible) * 2 >= n_fin:
            print(f"    ! {slug} {year}: {len(impossible)} of {n_fin} finishers beat the "
                  f"winner's {wsecs}s — that many cannot be wrong, so the WINNER's time "
                  "is the suspect one. Nothing changed; this needs a human.")
            impossible = []
        for r in impossible:
            rid, rank, secs, _name = r
            # gap_seconds goes too. It is derived from the same impossible time
            # and reads -9754 — "finished two and a half hours before the
            # winner" — which is the identical claim in another column. Nulling
            # one and leaving the other just moves the contradiction.
            cur.execute("UPDATE stage_results SET finish_time_seconds=NULL, "
                        "gap_seconds=NULL WHERE result_id=?", (rid,))
            ref = (f"{api} — {secs}s is faster than the winner's {wsecs}s on a "
                   f"rider ranked {rank}; the timer reports both. Rank and status "
                   "kept, the impossible duration removed.")
            for field in ("finish_time_seconds", "gap_seconds"):
                record_provenance(cur, "stage_results", rid, field, source,
                                  source_ref=ref)

    report_patches(f"{slug} {year}", *restore_patches(cur, edition_id, patched))
    if impossible:
        print(f"    {slug} {year}: {len(impossible)} finisher(s) timed faster than the "
              f"winner while ranked behind him — time set NULL, placing kept "
              f"({', '.join(r[3] for r in impossible[:4])}"
              f"{', ...' if len(impossible) > 4 else ''})")
    if tandems:
        print(f"    {slug} {year}: dropped {len(tandems)} tandem entr(y/ies) — "
              "two people on one bib, which this schema cannot store as a rider: "
              + ", ".join(n for n, _ in tandems[:4])
              + (" ..." if len(tandems) > 4 else ""), flush=True)
    if maybe_tandems:
        print(f"    {slug} {year}: {len(maybe_tandems)} row(s) joined by '&' or 'and' are NOT in "
              "tandem_entries.json — check whether they are two people: "
              + ", ".join(n for n, _ in maybe_tandems[:4]), flush=True)
    if placeholders:
        print(f"    {slug} {year}: skipped {len(placeholders)} bib-only entr"
              f"{'y' if len(placeholders) == 1 else 'ies'} with no result "
              f"({', '.join(placeholders[:5])}"
              f"{', ...' if len(placeholders) > 5 else ''}) — the timer "
              "published a bib number where it had no name")
    for name, rank, secs in named_placeholders:
        print(f"    ! {slug} {year}: {name!r} has no name but DID place "
              f"(rank {rank}, {secs}s) — kept, because dropping a real result "
              "would move everyone behind it. Needs a human.")
    if collisions:
        for name, first_rank, second_rank in collisions:
            print(f"    ! {slug} {year}: two riders named {name!r} "
                  f"(ranks {first_rank} and {second_rank}) share one identity; "
                  f"the second row is not stored")
    return (slug, year, inserted, data["cancelled"], info.get("rule"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", help="one gravel slug (default: all)")
    ap.add_argument("--year", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.exists(RIDER_IDS):
        print("gravel_scrapes/_rider_ids.json missing — run link_gravel_riders.py first")
        return 1
    with open(RIDER_IDS, encoding="utf-8") as f:
        rider_ids = json.load(f)

    pattern = os.path.join(SCRAPES, args.race or "*", f"{args.year or '*'}.json")
    paths = sorted(p for p in glob.glob(pattern)
                   if os.path.basename(os.path.dirname(p)) in GRAVEL)
    if not paths:
        print(f"no scrape files matched {pattern}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    results = []
    try:
        for p in paths:
            results.append(ingest_one(cur, p, rider_ids, dry_run=args.dry_run))
        conn.rollback() if args.dry_run else conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    total = sum(n for _, _, n, _, _ in results)
    canc = sum(1 for *_, c, _ in results if c)
    print(("DRY RUN — nothing written\n" if args.dry_run else "") +
          f"{len(results)} race-years, {total:,} results, {canc} cancelled")
    by_race = {}
    for slug, year, n, c, rule in results:
        by_race.setdefault(slug, []).append((year, n, c, rule))
    for slug in sorted(by_race):
        yrs = sorted(by_race[slug])
        n = sum(x[1] for x in yrs)
        print(f"  {GRAVEL[slug].name:<26} {yrs[0][0]}-{yrs[-1][0]}  "
              f"{len(yrs):>2} editions  {n:>6,} results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
