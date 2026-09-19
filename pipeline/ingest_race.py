#!/usr/bin/env python3
"""
Ingest scraped Giro d'Italia or Vuelta a España stage data into cycling.db.

Reads JSON files from pipeline/<race>_scrapes/YEAR/stage_N.json (or flat
<race>_scrapes/stage_N.json for Giro's legacy 2026 layout) and inserts into
the shared multi-race schema. Replaces the old ingest_giro.py / ingest_vuelta.py
— the two were ~85% identical; race-specific behavior (Giro's flat-2026
fallback, Giro's post-ingest name-fix pass) is now explicit branches below
instead of being duplicated wholesale.

Usage:
  python3 ingest_race.py --race giro                    # all years with stage files
  python3 ingest_race.py --race giro 1990 1991 1992      # specific years only
  python3 ingest_race.py --race giro 1990-2000           # year range
  python3 ingest_race.py --race vuelta --dry-run         # show what would be inserted
  python3 ingest_race.py --race vuelta --all             # re-ingest every year
"""

import json
import os
import re
import sqlite3
import sys
from glob import glob

import gc_source
from backfill_source_slugs import backfill_edition_slugs
from race_common import (
    RACES,
    STAGE_ROW_LEN,
    STAGE_ROW_LENGTHS,
    STAGE_ROW_LEN_V2,
    SOURCE_PCS,
    SOURCE_WIKIPEDIA,
    SOURCE_MANUAL,
    SOURCE_DERIVED,
    fix_mojibake,
    record_provenance,
    record_provenance_bulk,
    DB_PATH,
    StageRow,
    detect_route_type,
    load_route_type_overrides,
    load_rider_aliases,
    parse_bonus_seconds,
    parse_int,
    parse_time_to_seconds,
    implausible_speed,
    MIN_KMH,
    MAX_KMH,
    parse_year_args,
    to_iso_date,
    COUNTRY_NAMES,
    FLAT_FALLBACK_YEAR,
)
from race_set_ingest import capture_patches, report_patches, restore_patches

HERE = os.path.dirname(os.path.abspath(__file__))
DRY_RUN = "--dry-run" in sys.argv
# Re-ingest rebuilds an edition from its stage FILES, so a stage that lives
# only in the database is deleted and never comes back. See the orphan guard
# in ingest_year — three Vuelta stages were lost that way before it existed.
ALLOW_DROP = "--allow-drop" in sys.argv
# Escape hatch for the swap gate below. Deliberately verbose to type:
# a flagged swap is nearly always real (the first run of this check
# surfaced 7 genuine swap pairs), so bypassing should be a decision.
SKIP_SWAP_GATE = "--skip-swap-gate" in sys.argv


# Loaded once: a handful of stages where PCS's own metadata names the wrong
# kind of race. See race_common.load_route_type_overrides.
ROUTE_TYPE_OVERRIDES = load_route_type_overrides()
RIDER_ALIASES = load_rider_aliases()

# Above this many non-winners sharing the winner's exact second, an individual
# time trial's times are PCS filler rather than results. Matches validate_db's
# ITT-tie check and comes from the same measured distribution: across 607 ITT
# stages, genuine ties at second resolution run 1-20 a stage and the defect 21+,
# with nothing in between. See "Times that no race produced".
ITT_TIE_LIMIT = 20


def _stage_num(path: str) -> int:
    return int(re.search(r"stage_(\d+)\.json$", path).group(1))


# implausible_speed lives in race_common so every writer can reach it.
# It was defined here once, and derive_ttt_rider_times.py then wrote 130
# fabricated prologue times at 10 km/h because the guard was in the module
# that did not run. A guard is only where you put it.


def find_stage_files_for_year(scrapes_dir: str, year: int, flat_fallback: bool) -> list[str]:
    """Find stage files for a year, checking the year subdir first, then
    (for races with the legacy layout) the flat FLAT_FALLBACK_YEAR fallback.

    Numeric sort — plain sorted() is lexicographic (stage_1, stage_10, ...,
    stage_2), which scrambles any logic that walks stages in race order.
    """
    year_dir = os.path.join(scrapes_dir, str(year))
    files = sorted(glob(os.path.join(year_dir, "stage_*.json")), key=_stage_num)
    if files:
        return files
    if flat_fallback and year == FLAT_FALLBACK_YEAR:
        return sorted(glob(os.path.join(scrapes_dir, "stage_*.json")), key=_stage_num)
    return []


def load_gc_standings(scrapes_dir: str, year: int) -> dict | None:
    """Per-stage GC from build_vuelta_gc_standings.py (--race giro|vuelta), if present.

    Returns {stage_number(int): {rider_slug: [rank_or_None, gap_seconds]}}.
    """
    path = os.path.join(scrapes_dir, str(year), "gc_standings.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {int(n): entries for n, entries in data.get("stages", {}).items()}


def discover_years(scrapes_dir: str, flat_fallback: bool) -> list[int]:
    """Find all years that have scraped stage files."""
    years = set()
    for entry in os.listdir(scrapes_dir):
        if entry.isdigit() and os.path.isdir(os.path.join(scrapes_dir, entry)):
            files = glob(os.path.join(scrapes_dir, entry, "stage_*.json"))
            if files:
                years.add(int(entry))
    if flat_fallback and glob(os.path.join(scrapes_dir, "stage_*.json")):
        years.add(FLAT_FALLBACK_YEAR)
    return sorted(years)


def check_swaps(race: str, year: int, stage_files: list[str]) -> list[dict]:
    """Bib-identity consistency across the stage files about to be ingested.

    Within a race-year a bib must map to the same rider on every stage; a bib
    that shows a different name/slug/nat on even one stage is a PCS table
    artifact that silently attributes one rider's ride to another. This gate
    was previously wired only into add_stages.py for TDF 2026, leaving the
    Giro/Vuelta path — every year of it — completely unchecked.

    Note the gate's known limit: it catches a bib whose identity is
    inconsistent ACROSS stages. A bib appearing once with the wrong rider
    attached on a single stage is invisible to it.
    """
    from detect_name_swaps import _bib_check

    stages_by_n = {}
    for sf in stage_files:
        try:
            with open(sf, encoding="utf-8") as f:
                data = json.load(f)
            stages_by_n[data.get("n", _stage_num(sf))] = data.get("rows", [])
        except Exception:
            continue
    return _bib_check(race, year, stages_by_n)


def ingest_year(conn, race_id: int, race_name: str, scrapes_dir: str, year: int, stage_files: list[str]) -> int:
    """Ingest one year's stage files. Returns total results inserted."""
    cur = conn.cursor()
    # Empty unless this edition already exists; capture_patches() fills it in
    # the replace branch below, before anything is deleted.
    patched = {"stages": [], "results": []}

    existing = cur.execute(
        "SELECT edition_id FROM race_editions WHERE race_id=? AND year=?",
        (race_id, year),
    ).fetchone()

    # Preserve per-stage fields that come from scrape_{giro,vuelta}_stage_info.py,
    # not the stage scrape files — otherwise a re-ingest silently wipes them.
    #
    # Keyed by source_slug wherever the existing row has one, falling back to
    # stage_number only for rows predating that column. Keying on stage_number
    # alone is actively dangerous: the whole reason you re-ingest an edition is
    # usually that its numbering was wrong, and number-keyed preservation then
    # re-attaches each elevation to whichever *different* stage now holds that
    # number — silently re-corrupting the data during the repair. (This is what
    # happened while fixing the 2010 Vuelta's two missing stages.)
    # distance_km rides along: PCS's "Distance:" info row reads "0 km" for some
    # historical stages, and patch_missing_distances.py backfills the real
    # figure from the same page's header ("(85km)"); patch_bri_distances.py
    # fills others from bikeraceinfo.com. Either way the value lives only in
    # the DB, so a re-ingest that trusts the scrape file's 0 silently destroys
    # it (caught re-ingesting 2010 Vuelta stage 21, 85.0 km -> 0.0). Only ever
    # used when the incoming value is 0/absent. data_provenance records which
    # source each surviving figure came from.
    preserved_by_slug = {}
    preserved_by_number = {}
    if existing:
        for r in cur.execute(
            "SELECT stage_number, source_slug, vertical_meters, profile_score, distance_km, "
            "cancelled FROM stages WHERE edition_id=?",
            (existing[0],),
        ):
            if (r["vertical_meters"] is None and r["profile_score"] is None
                    and not r["distance_km"] and not r["cancelled"]
                    and not r["source_slug"]):
                continue
            vals = (r["vertical_meters"], r["profile_score"], r["distance_km"],
                    r["cancelled"], r["source_slug"])
            # Populate BOTH indexes, always. The incoming stage file may or may
            # not carry a slug independently of whether the existing row has
            # one, so keying only on whichever the old row had would miss
            # every stage when the two disagree (that wipes the whole
            # edition's elevation on re-ingest).
            preserved_by_number[r["stage_number"]] = vals
            if r["source_slug"]:
                preserved_by_slug[r["source_slug"]] = vals

    # Disqualification markers already in the DB, keyed (stage_number, rider).
    #
    # A scrape file written before 2026-09-11 has 15 fields and carries no
    # marker at all, and an ABSENT marker means UNKNOWN -- not "this rider was
    # not disqualified". Letting a legacy file's silence overwrite a known 1
    # would quietly undo every repair audit_disqualifications.py made, and the
    # normal patch-carry cannot help here: it only rescues PATCH_SOURCES, and
    # the honest source for a struck rank is 'pcs', which an ingest also
    # writes. So the value is carried across explicitly, and only a file that
    # actually carries the field is allowed to change it.
    preserved_dsq = {}
    if existing:
        for r in cur.execute(
            """SELECT s.stage_number, sr.rider_id, sr.disqualified
                 FROM stage_results sr JOIN stages s ON s.stage_id = sr.stage_id
                WHERE s.edition_id = ? AND sr.disqualified = 1""",
            (existing[0],),
        ):
            preserved_dsq[(r["stage_number"], r["rider_id"])] = 1

    if DRY_RUN:
        action = "replace existing" if existing else "insert"
        print(f"  [DRY RUN] Would {action} {year} {race_name} with {len(stage_files)} stages")
        return 0

    if existing:
        eid = existing[0]

        # A stage that exists in the DB but has no scrape file is about to be
        # deleted and never re-inserted. Those are not accidents: Vuelta 1941
        # st20 and st22 and 1968 st20 were placed here by deliberate repairs
        # from sources other than a scrape, and re-ingesting those editions
        # silently destroyed all three. Refuse rather than drop them.
        incoming = set()
        for p in stage_files:
            m = re.search(r"stage_(\d+)\.json$", p)
            if m:
                incoming.add(int(m.group(1)))
        orphans = [r[0] for r in cur.execute(
            "SELECT stage_number FROM stages WHERE edition_id=? ORDER BY stage_number",
            (eid,)) if r[0] not in incoming]
        if orphans and not ALLOW_DROP:
            print(f"  REFUSED {year}: stage(s) {orphans} are in the database with no "
                  f"scrape file; re-ingesting would delete them. Re-run with "
                  f"--allow-drop only if that is what you want.")
            return 0

        # Corrections that live only in the DB — the Wikipedia Paris-finale
        # distances, the two cyclingflash elevations relayed by hand, the
        # manual Vuelta values — are about to be destroyed with the edition.
        # Read them out now and hand them back at the end of this function.
        # 24 of the archive's 25 patched stage-fields are Grand Tour values, so
        # this path carries the most exposure of the three ingests.
        patched = capture_patches(cur, race_id, year)

        # A stage's incidents (1904's disqualifications, 1998's Festina walkout)
        # are keyed to a stage_id that is about to be deleted, and they exist in
        # no scrape file. Carry them by stage NUMBER, which is what survives.
        incidents = [(r["stage_number"], r["description"]) for r in cur.execute(
            "SELECT s.stage_number, si.description FROM stage_incidents si "
            "JOIN stages s USING(stage_id) WHERE s.edition_id=?", (eid,))]

        cur.execute("DELETE FROM stage_results WHERE stage_id IN (SELECT stage_id FROM stages WHERE edition_id=?)", (eid,))
        # Provenance is keyed by stage_id, and re-inserting an edition mints new
        # ones — without this the old rows are orphaned and accumulate as dead
        # weight that inflates every coverage count. There is no FK cascade
        # because entity_id is polymorphic across tables.
        cur.execute(
            "DELETE FROM data_provenance WHERE entity='stages' AND entity_id IN "
            "(SELECT stage_id FROM stages WHERE edition_id=?)", (eid,))
        cur.execute("DELETE FROM stage_incidents WHERE stage_id IN "
                    "(SELECT stage_id FROM stages WHERE edition_id=?)", (eid,))
        cur.execute("DELETE FROM stages WHERE edition_id=?", (eid,))

    # The edition ROW stays. It used to be deleted and re-inserted, which is
    # how this path came to refuse every year it most needed to serve:
    # classification_standings references edition_id and has no ON DELETE
    # CASCADE, so from the moment the September standings landed (86 Tour, 88
    # Giro and 80 Vuelta editions) the delete raised FOREIGN KEY constraint
    # failed and rolled the whole ingest back. The verification that this path
    # matched reingest_edition_results on 1949 predates those rows.
    #
    # Keeping the row also keeps what the scrape files do not carry: the
    # ordinal edition_name ("72nd Tour de France", on 1,170 editions) and
    # uci_classification, both of which the re-insert overwrote with a generic
    # "YEAR Race". ingest_classics.replace_edition has always done it this way.
    if existing:
        edition_id = eid
        cur.execute(
            "UPDATE race_editions SET edition_name = COALESCE(edition_name, ?) "
            "WHERE edition_id=?", (f"{year} {race_name}", edition_id))
    else:
        cur.execute(
            "INSERT INTO race_editions (race_id, year, edition_name) VALUES (?,?,?)",
            (race_id, year, f"{year} {race_name}"),
        )
        edition_id = cur.lastrowid
        incidents = []

    countries_seen = {r["code"] for r in cur.execute("SELECT code FROM countries")}
    riders_seen = {r["rider_id"] for r in cur.execute("SELECT rider_id FROM riders")}
    teams_seen = {r["team_id"] for r in cur.execute("SELECT team_id FROM teams")}

    gc_standings = load_gc_standings(scrapes_dir, year)
    total_results = 0
    malformed: list[tuple] = []   # (stage_n, field_count, first_fields)
    implausible: list[tuple] = []  # (stage_n, distance_km, refused_seconds)
    itt_filler: list[tuple] = []   # (stage_n, riders_whose_ITT_time_was_filler)
    carried_dsq: list[tuple] = []  # (stage_n, rider) markers a legacy file lacked

    for sf in stage_files:
        with open(sf, encoding="utf-8") as f:
            stage_data = json.load(f)

        n = stage_data["n"]
        slug = stage_data.get("slug")  # absent in files scraped before slugs were recorded
        info = stage_data.get("info", {})
        rows = stage_data.get("rows", [])
        profile_icon = stage_data.get("profile_icon", "p1")

        date_iso = None
        # to_iso_date, not a bare ISO strptime: an older PCS page writes
        # "30 June 1949", and storing that verbatim is how 68 stages across
        # three Tour editions ended up with a date that sorts as a string.
        if info.get("Date"):
            date_iso = to_iso_date(info["Date"])

        distance_km = None
        if info.get("Distance"):
            m = re.match(r"([\d.]+)", info["Distance"])
            if m:
                distance_km = float(m.group(1))

        won_how = info.get("Won how", "")
        # The scraper's is_ttt comes from the page structure and beats the
        # "Won how" heuristic, which reads plain "Time trial" for some team
        # trials and so classified them TT (Vuelta 1989 stage 3a).
        #
        # TitleTT is PCS's own "(ITT)"/"(TTT)" marker from the stage headline,
        # which is the only evidence available when "Won how" is empty — the
        # gap that left 44 time trials stored as flat road stages, including
        # the 1968 Tour's Melun > Paris finale.
        title_tt = info.get("TitleTT")
        if stage_data.get("is_ttt") or title_tt == "TTT":
            route_type = "TTT"
        elif title_tt == "ITT":
            route_type = "TT"
        else:
            route_type = detect_route_type(profile_icon, won_how)

        # Last word goes to route_type_overrides.json, because every branch
        # above reads PCS and this file exists for the stages PCS is wrong
        # about. Giro 1985 stage-8a is reported "Won how: Time trial" and was a
        # mass-start circuit race, so a re-scrape cannot fix it and a DB patch
        # would not survive the next re-ingest.
        route_override = ROUTE_TYPE_OVERRIDES.get((race_name, year, slug)) if slug else None
        if route_override:
            # Refuse an override that has stopped describing what it corrects.
            # If PCS changes its mind and starts reporting the right type, the
            # entry is stale and should be deleted rather than silently kept.
            if route_override.get("was") not in (None, route_type):
                print(f"    stage {n}: route_type override for {slug} expects "
                      f"{route_override['was']!r}, scrape now gives {route_type!r} — "
                      "not applied; check whether the entry is still needed")
                route_override = None
            else:
                route_type = route_override["route_type"]

        if slug and slug in preserved_by_slug:
            preserved_vm, preserved_ps, preserved_d, preserved_c, preserved_slug = \
                preserved_by_slug[slug]
        else:
            preserved_vm, preserved_ps, preserved_d, preserved_c, preserved_slug = \
                preserved_by_number.get(n, (None, None, None, 0, None))

        # source_slug is DB-only for any edition whose stage files predate slug
        # recording, and on a SPLIT edition it cannot be re-derived —
        # backfill_edition_slugs rightly refuses to guess there, because PCS
        # letters split days in some editions and numbers them sequentially in
        # others. So a re-ingest that does not carry it over silently discards
        # probe-verified slugs and nothing puts them back. (Caught re-ingesting
        # the TTT stages: 9 split Vuelta editions lost every slug.)
        if not slug:
            slug = preserved_slug

        is_cancelled = bool(stage_data.get("cancelled") or preserved_c)

        # Trust the freshly scraped distance whenever it's a real figure; fall
        # back to the stored one only when PCS gave us nothing usable. Never for
        # a cancelled stage: 0 km is its true distance, and the stored value is
        # liable to belong to whatever stage previously occupied this number.
        distance_from_scrape = bool(distance_km)
        if not distance_km and preserved_d and not is_cancelled:
            print(f"    stage {n}: scrape has no distance, keeping stored {preserved_d} km")
            distance_km = preserved_d
        cur.execute(
            """INSERT INTO stages
               (edition_id, stage_number, stage_label, stage_date,
                start_location, finish_location, distance_km, stage_type,
                vertical_meters, profile_score, route_type, won_how, source_slug,
                cancelled)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                edition_id, n, f"Stage {n}", date_iso,
                info.get("Start"), info.get("Finish"), distance_km,
                "itt" if route_type in ("TT", "TTT") else "road",
                preserved_vm, preserved_ps, route_type, won_how,
                # NULL, not a reconstructed f"stage-{n}", when the scrape file
                # predates slug recording: on a split edition that guess is
                # wrong for every stage after the split, and a wrong slug is
                # worse than a missing one because callers will trust it.
                # backfill_source_slugs.py fills these in date-aware.
                slug,
                # A cancelled stage has no results, so nothing in the scrape rows
                # can imply it — the flag lives only in the file or the DB.
                1 if is_cancelled else 0,
            ),
        )
        stage_id = cur.lastrowid

        # Whether this stage's GC has to be approximated from the finishing
        # order — see the fallback below, which is the only user.
        stage_rank_is_the_only_gc = (
            n == 1
            and not any(len(r) > 1 and r[1] for r in rows)
            and not (gc_standings or {}).get(n))

        # PCS marks a rider whose recorded time was AWARDED rather than raced.
        # Read it here so a rebuild recreates the flag rather than losing it —
        # backfill_time_adjusted.py put it on existing rows, and without this a
        # re-ingest would silently drop all 718 again. gc_source refuses a page
        # it cannot prove belongs to this stage, so an edition with misnamed
        # pages (the 1992 Giro) yields an empty set rather than another
        # stage's marks.
        # The stage table is read from the rows already in hand; the
        # classification needs the verified page beside them.
        time_adjusted_here = (
            gc_source.marked_in_stage_rows(rows)
            | gc_source.marked_riders(gc_source.gc_page(race_name, year, n, slug)))

        # Provenance. Route fields come from this stage file's PCS scrape; the
        # scrape file path plus the slug pins down exactly which page. Elevation
        # is deliberately NOT claimed here — it was carried over from whatever
        # previously populated it, whose own provenance row already stands.
        ref = f"{os.path.relpath(sf, HERE)} ({slug})" if slug else os.path.relpath(sf, HERE)
        scraped_fields = ["source_slug"] if route_override else ["route_type", "source_slug"]
        if distance_from_scrape:
            scraped_fields.append("distance_km")
        record_provenance_bulk(cur, "stages", stage_id, scraped_fields,
                               SOURCE_PCS, source_ref=ref)
        # One entry for the whole result set — see the granularity rule in
        # schema.sql. All of a stage's rows come from one page, so per-row
        # provenance would be millions of copies of a single fact.
        record_provenance(cur, "stages", stage_id, "results",
                          SOURCE_PCS, source_ref=ref)
        if route_override:
            # The override's OWN source, not PCS — claiming pcs here would say
            # the page reports what it does not, and hide the correction.
            src = (SOURCE_WIKIPEDIA if route_override.get("source") == "wikipedia"
                   else SOURCE_MANUAL)
            record_provenance(cur, "stages", stage_id, "route_type", src,
                              source_ref=route_override.get("source_ref")
                              or "route_type_overrides.json")

        winner_seconds = None

        for row in rows:
            if len(row) not in STAGE_ROW_LENGTHS:
                # Never silently drop a row. A malformed row is a scrape bug,
                # and swallowing it loses a real rider's result with no trace —
                # Marco Haller's 2026 stage 2 result went missing this way and
                # stayed missing until a schema tightening happened to surface
                # it. Record it and report loudly at the end of the run.
                malformed.append((n, len(row), row[:6]))
                continue
            sr = StageRow.from_list(row)
            rnk, gc_pos, gc_lag = sr.rnk, sr.gc_pos, sr.gc_lag
            # PCS struck this rank through: the result was annulled after the
            # fact. Empty on a legacy 15-field file, where it means UNKNOWN,
            # not "clean" — only a re-scrape can tell those apart.
            if len(row) == STAGE_ROW_LEN_V2:
                dsq = 1 if str(sr.dsq).strip() == "1" else 0   # the file knows
            else:
                # Legacy file: the marker is unknown, so keep what is stored.
                dsq = preserved_dsq.get((n, sr.slug), 0)
                if dsq:
                    carried_dsq.append((n, sr.slug))
            bib, age = sr.bib, sr.age
            rider_name, rider_slug, nat = sr.name, sr.slug, sr.nat
            # An id this repo has established is a variant of another person's.
            # Applied HERE because the scrape file still carries the old
            # spelling, so without it a rebuild mints the absorbed id again and
            # the merge silently comes undone. See race_common.load_rider_aliases.
            rider_slug = RIDER_ALIASES.get(rider_slug, rider_slug)
            team_name, team_slug = sr.team, sr.team_slug
            uci_pts, pcs_pts = sr.uci_pts, sr.pcs_pts
            bonus_txt, abs_time_txt, gap_txt = sr.bonus, sr.abs_time, sr.gap

            if not rider_slug:
                continue

            # Per-stage GC. Priority: (1) raw scraped gc_pos/gc_lag from this
            # stage's own result row — authoritative when present; (2)
            # gc_standings.json (real PCS GC merged with cumulative times
            # computed from actual stage results — see
            # build_vuelta_gc_standings.py --race giro|vuelta), which fills
            # gaps for historical PCS result pages that carried GC for only a
            # few riders per stage (sparse pre-1998). Never carry values
            # across stages (a rider's gap changes every stage — stale values
            # are fabricated data).
            #
            # NOTE: gc_standings.json must NEVER override a present raw value.
            # It used to be preferred outright whenever the file existed,
            # which silently discarded good raw gc_pos for any rider it
            # didn't happen to cover — confirmed to have dropped 26-48% of
            # finishers' GC rank on several recent Giro editions (found
            # 2026-08-01 investigating a "79 finishers instead of 151" report).
            # LAST RESORT ONLY, and never beside a real source. After stage 1
            # PCS publishes a GC position for very few riders -- three of 180
            # on Vuelta 1996 stage 1, the top three reordered by bonifications
            # -- so giving everyone else their STAGE placing invented a second
            # ladder and dropped it on top of the real one. 748 stage-1 GC
            # ranks in the archive ended up held by two riders that way, and
            # the invented rank is the wrong half: the gap of 0 beside it is
            # usually true, because a bunch rider really did finish on the
            # winner's time.
            #
            # So the fallback now runs only where the stage has NO other
            # source: no rider with a published gc_pos, and no gc_standings
            # entry. 217 of the 303 stage-1 files are the mixing case and
            # every one of them has gc_standings, which agrees with PCS's own
            # inline positions on 18,263 of 18,268 rows. 31 files have neither
            # and keep the approximation, where nothing can collide with it.
            if not gc_pos and stage_rank_is_the_only_gc:
                stage_rank_fallback = parse_int(rnk)
                if stage_rank_fallback is not None:
                    gc_pos = str(stage_rank_fallback)
                    gc_lag = gap_txt
            gc_rank_v = parse_int(gc_pos)
            gc_gap_v = parse_time_to_seconds(gc_lag)
            if gc_rank_v is None and gc_standings is not None:
                entry = gc_standings.get(n, {}).get(rider_slug)
                if entry:
                    gc_rank_v, gc_gap_v = entry[0], entry[1]

            if nat and nat not in countries_seen:
                countries_seen.add(nat)
                cur.execute(
                    "INSERT OR IGNORE INTO countries (code, name) VALUES (?,?)",
                    (nat, COUNTRY_NAMES.get(nat)),
                )

            if rider_slug not in riders_seen:
                riders_seen.add(rider_slug)
                cur.execute(
                    "INSERT OR IGNORE INTO riders (rider_id, full_name, nationality_code) VALUES (?,?,?)",
                    (rider_slug, fix_mojibake(rider_name), nat),
                )
                # Only claim provenance for a row this ingest actually wrote.
                # OR IGNORE means an existing rider keeps someone else's value,
                # and claiming it here would attribute their work to us.
                if cur.rowcount:
                    record_provenance_bulk(cur, "riders", rider_slug,
                                           ["full_name", "nationality_code"],
                                           SOURCE_PCS, source_ref=ref)

            if team_slug and team_slug not in teams_seen:
                teams_seen.add(team_slug)
                m = re.search(r"-(\d{4})$", team_slug)
                season_year = int(m.group(1)) if m else None
                cur.execute(
                    "INSERT OR IGNORE INTO teams (team_id, name, season_year) VALUES (?,?,?)",
                    (team_slug, fix_mojibake(team_name), season_year),
                )
                if cur.rowcount:
                    record_provenance(cur, "teams", team_slug, "name",
                                      SOURCE_PCS, source_ref=ref)
                    record_provenance(cur, "teams", team_slug, "season_year",
                                      SOURCE_DERIVED,
                                      source_ref="trailing year of the PCS team slug")

            # Status. NOTE: "DF" is deliberately NOT an exit status — on
            # historical PCS pages it marks riders who finished the stage
            # without a recorded position/time (often the whole peloton);
            # they stay in the race.
            status = "FINISHED"
            if rnk in ("DNF", "DNS", "OTL", "NP", "DSQ", "DEL"):
                status = rnk

            abs_secs = parse_time_to_seconds(abs_time_txt)
            gap_secs = parse_time_to_seconds(gap_txt)

            # Only the stage winner's row carries an absolute time. PCS renders
            # that cell as the displayed time immediately followed by a hidden
            # gap — "4:15:284:15:28" — so the parser reads BOTH fields as the
            # same value, and winner + gap doubled the winner's finish time on
            # 3,377 stages. Every later row shows a gap in that cell instead,
            # so its abs field is not an absolute time at all.
            #
            # winner_seconds is set once and never overwritten: a promoted
            # co-winner after a disqualification is also rank 1 (2008 TDF st4
            # lists both Schumacher and Kirchen) and would otherwise replace
            # the real winning time with an 18-second gap.
            is_winner_row = False
            # A struck rider STILL anchors the stage's times, and that is
            # deliberate. The disqualification took away the placing, not the
            # afternoon: his clock is the only absolute time the page carries,
            # and the man promoted into his place is shown tied with him.
            # 1904 stage 3 is the case — Cornet's own time cell is PCS's ditto
            # ("0:00", meaning "as above"), so refusing Aucouturier's 15:43:55
            # here makes winner_seconds ZERO and times the whole stage from
            # nothing. The marker records the fact; it does not rewrite the
            # clock. (Caught by TestDisqualifiedRanks writing the assertion
            # the other way round first.)
            if (status == "FINISHED" and abs_secs is not None and rnk == "1"
                    and winner_seconds is None):
                # ...and that duplicated value is not a gap either. Storing it
                # says the winner finished his own time behind himself, and a
                # re-ingest would put it straight back after the DB was
                # repaired. He is by definition zero behind the winner.
                gap_secs = 0
                if implausible_speed(distance_km, abs_secs):
                    # Not a stage time at all. On some split-day time trials
                    # PCS puts the GC TOTAL in the Time column — the 1962
                    # Tour's 23 km stage-2b reads 10:45:17, Darrigade's
                    # cumulative time, which would have the whole field riding
                    # at 2.1 km/h. Storing nothing beats storing a number that
                    # fails its own check, and the gaps on such a page are
                    # still real, so only the absolute time is refused.
                    implausible.append((n, distance_km, abs_secs))
                else:
                    winner_seconds = abs_secs
                    is_winner_row = True

            finish_secs = None
            if status == "FINISHED" and winner_seconds is not None:
                if is_winner_row:
                    finish_secs = winner_seconds
                elif gap_secs is not None:
                    finish_secs = winner_seconds + gap_secs

            bonus_secs = parse_bonus_seconds(bonus_txt)
            stage_rank = parse_int(rnk) if status == "FINISHED" else None
            gc_rank = gc_rank_v
            gc_gap_secs = gc_gap_v

            cur.execute(
                """INSERT OR IGNORE INTO stage_results
                   (stage_id, rider_id, team_id, bib_number, stage_rank, status,
                    finish_time_seconds, gap_seconds, bonus_seconds, penalty_seconds,
                    uci_points, pcs_points, gc_rank, gc_gap_seconds, age_at_race,
                    disqualified, time_adjusted)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    stage_id, rider_slug,
                    team_slug if team_slug else None,
                    parse_int(bib), stage_rank, status,
                    finish_secs, gap_secs, bonus_secs, 0,
                    parse_int(uci_pts), parse_int(pcs_pts),
                    gc_rank, gc_gap_secs,
                    parse_int(age), dsq,
                    1 if rider_slug in time_adjusted_here else 0,
                ),
            )
            total_results += 1

        # ── An individual time trial the clock never recorded ──────────────
        # A rider alone against the clock cannot finish on the winner's exact
        # second. PCS fills the gap cell of a rider it never timed with
        # "+0:00" on older pages and "-0:00" on current ones;
        # parse_time_to_seconds rejects the second spelling but reads the
        # first as a real zero gap, so winner + 0 credited the whole untimed
        # field with the winning time. That is where the 4,040 rows across 41
        # stages came from, and a re-ingest put them straight back until this
        # guard existed.
        #
        # Deliberately scoped to ITTs. On a mass-start stage a zero gap is the
        # ORDINARY case -- Giro 1979 stage 5 ("Sprint of large group") has 115
        # riders legitimately on the winner's time -- so an unscoped rule
        # would destroy far more than it fixed. route_type here is already
        # override-corrected, which is why Giro 1985 stage-8a, a circuit race
        # PCS labels "Time trial", is not caught by it.
        #
        # stage_rank and status are left alone: PCS publishes a finishing
        # order for these riders even where it has no time for them, and
        # dropping the placing would trade one defect for another.
        if route_type == "TT":
            winner_row = cur.execute(
                """SELECT MIN(finish_time_seconds) FROM stage_results
                    WHERE stage_id = ? AND stage_rank = 1
                      AND finish_time_seconds IS NOT NULL""", (stage_id,)).fetchone()
            wsecs = winner_row[0] if winner_row else None
            if wsecs is not None:
                tied = cur.execute(
                    """SELECT result_id FROM stage_results
                        WHERE stage_id = ? AND status = 'FINISHED'
                          AND finish_time_seconds = ?
                          AND (stage_rank IS NULL OR stage_rank <> 1)""",
                    (stage_id, wsecs)).fetchall()
                if len(tied) > ITT_TIE_LIMIT:
                    for (rid,) in tied:
                        cur.execute(
                            "UPDATE stage_results SET finish_time_seconds = NULL "
                            "WHERE result_id = ?", (rid,))
                        record_provenance(
                            cur, "stage_results", rid, "finish_time_seconds",
                            SOURCE_PCS, source_ref=f"{ref} — gap cell is filler "
                            "(no time published for this rider on an ITT)")
                    itt_filler.append((n, len(tied)))

        # Supplement with gc_standings entries for riders absent from result rows.
        # Old PCS stage pages often omit mid-pack riders entirely; gc_standings has
        # computed GC positions for them. INSERT OR IGNORE skips existing rows.
        if gc_standings is not None:
            for slug, entry in gc_standings.get(n, {}).items():
                gc_rank_s, gc_gap_s = entry[0], entry[1]
                if gc_rank_s is None:
                    continue
                try:
                    cur.execute(
                        "INSERT OR IGNORE INTO stage_results "
                        "(stage_id, rider_id, status, gc_rank, gc_gap_seconds) "
                        "VALUES (?,?,'FINISHED',?,?)",
                        (stage_id, slug, gc_rank_s, gc_gap_s),
                    )
                except Exception:
                    pass  # rider not in riders table; skip

        print(f"  Stage {n}: {len(rows)} rows inserted")

    # Stage files scraped before slugs were recorded leave source_slug NULL.
    # Derive them from the same-date split detection the standalone backfill
    # uses, so a re-ingest of an old year doesn't quietly undo the backfill and
    # leave scrape_*_stage_info.py with nothing to key off.
    if malformed:
        print(f"\n  WARNING: {len(malformed)} malformed row(s) skipped in {year} — "
              f"expected {STAGE_ROW_LEN} or {STAGE_ROW_LEN_V2} fields:")
        for stage_n, count, head in malformed[:10]:
            print(f"    stage {stage_n}: {count} fields, starts {head}")
        if len(malformed) > 10:
            print(f"    ... and {len(malformed) - 10} more")
        print("    These are dropped results. Re-scrape the stage(s) to recover them.")

    if implausible:
        print(f"\n  {len(implausible)} stage(s) had a winner's time that is not one: "
              f"stored NULL rather than a fabricated field.")
        for stage_n, km, secs in implausible[:10]:
            h, rem = divmod(secs, 3600)
            print(f"    stage {stage_n}: {km} km in {h}:{rem // 60:02d}:{rem % 60:02d} "
                  f"= {km / (secs / 3600):.1f} km/h. PCS is showing the GC total here. "
                  "The gaps on the page are still real and were kept.")
        if len(implausible) > 10:
            print(f"    ... and {len(implausible) - 10} more")

    if carried_dsq:
        print(f"\n  carried {len(carried_dsq)} disqualification marker(s) across the "
              "rebuild — the scrape file(s) predate the field and do not carry it. "
              "Re-scrape those stages to make the marker self-describing.")

    if itt_filler:
        n_rows = sum(c for _, c in itt_filler)
        print(f"\n  {len(itt_filler)} time trial(s) had no per-rider times: "
              f"{n_rows:,} finisher(s) stored NULL rather than the winner's second.")
        for stage_n, count in itt_filler[:10]:
            print(f"    stage {stage_n}: {count} rider(s) on the winner's exact time. "
                  "PCS publishes their placing but not their time.")
        if len(itt_filler) > 10:
            print(f"    ... and {len(itt_filler) - 10} more")

    filled = backfill_edition_slugs(cur, edition_id)
    if filled:
        print(f"  derived source_slug for {filled} stage(s) from stage dates")

    # Hand the incidents back to the stages that now hold their numbers. A
    # stage that the re-ingest did not re-create keeps its incident only if
    # some other stage took its number, which is why this reports the shortfall
    # rather than passing over it.
    if incidents:
        restored = 0
        for stage_number, description in incidents:
            row = cur.execute(
                "SELECT stage_id FROM stages WHERE edition_id=? AND stage_number=?",
                (edition_id, stage_number)).fetchone()
            if row:
                cur.execute(
                    "INSERT INTO stage_incidents (stage_id, description) VALUES (?,?)",
                    (row[0], description))
                restored += 1
        if restored != len(incidents):
            print(f"  WARNING: {len(incidents) - restored} stage incident(s) had no "
                  f"stage to return to and were dropped")
        else:
            print(f"  restored {restored} stage incident(s)")

    report_patches(f"{race_name} {year}",
                   *restore_patches(cur, edition_id, patched))

    conn.commit()
    return total_results


def main():
    args = sys.argv[1:]

    if "--race" not in args:
        sys.exit(
            "usage: python3 ingest_race.py --race {giro,vuelta} [YEARS...] "
            "[--dry-run|--all] [--skip-swap-gate]"
        )
    race = args[args.index("--race") + 1]
    if race not in RACES:
        sys.exit(f"error: unknown race '{race}' (use 'giro' or 'vuelta')")
    # The Tour was refused here until 2026-09-10, because its GC was carried
    # forward while this path refuses to carry values across stages. It now has
    # gc_standings.json sidecars like the other two, so the same code applies.
    # Its per-stage elevation/distance still live only in the DB, which is what
    # the preserved_by_slug block below exists to protect.
    info = RACES[race]
    scrapes_dir = os.path.join(HERE, info.scrapes_dirname)

    year_args = parse_year_args(args)
    if not year_args and "--all" not in args:
        sys.exit(
            f"Refusing to re-ingest every year in {info.scrapes_dirname}/ without an explicit --all.\n"
            "Re-ingesting a year wipes and rebuilds it; pass the year(s) you actually\n"
            f"changed (e.g. 'python3 ingest_race.py --race {race} 1985' or '1980-1989'), or --all\n"
            "if you really want to rebuild everything."
        )
    years = year_args if year_args else discover_years(scrapes_dir, info.flat_2026_fallback)

    if not years:
        print("No stage files found in", scrapes_dir)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    race_row = cur.execute("SELECT race_id FROM races WHERE name = ?", (info.name,)).fetchone()
    if not race_row:
        cur.execute(
            "INSERT INTO races (name, country, race_type) VALUES (?, ?, ?)",
            (info.name, info.country, "stage_race"),
        )
        conn.commit()
        race_id = cur.execute("SELECT race_id FROM races WHERE name = ?", (info.name,)).fetchone()[0]
        print(f"Created race '{info.name}' (race_id={race_id})")
    else:
        race_id = race_row["race_id"]
        print(f"Using existing {info.name} (race_id={race_id})")

    grand_total = 0
    for year in years:
        stage_files = find_stage_files_for_year(scrapes_dir, year, info.flat_2026_fallback)
        if not stage_files:
            print(f"{year}: no stage files found, skipping")
            continue
        print(f"\n{year}: {len(stage_files)} stage file(s)")

        # ── Gate: refuse to ingest a year with unresolved bib-identity swaps ──
        # Ingesting is destructive (the edition is deleted and rebuilt), so a
        # swap has to be caught before the write, not after.
        findings = check_swaps(race, year, stage_files)

        # Duplicate bibs are an upstream PCS defect we cannot fix and that
        # doesn't misattribute anyone's result — warn, but never block, or the
        # affected years could never be re-ingested again.
        dups = [f for f in findings if f.get("type") == "duplicate_bib"]
        findings = [f for f in findings if f.get("type") != "duplicate_bib"]
        for f in dups:
            print(f"  NOTE: bib {f['bib']} is shared by {', '.join(f['riders'])} "
                  "(PCS-side duplicate; results unaffected)")

        if findings and not SKIP_SWAP_GATE:
            print(f"\nERROR: {len(findings)} bib-identity anomaly(ies) in {race} {year} "
                  "— refusing to ingest:")
            for f in findings:
                maj = f["majority_identity"]
                print(f"  bib {f['bib']} -> majority: {maj[0]} ({maj[2]})")
                for stage_n, outlier in zip(f["outlier_stages"], f["outlier_names"]):
                    print(f"        stage {stage_n}: shows '{outlier}' instead")
            print(f"\nRun `python3 detect_name_swaps.py --race {race} --year {year}` for "
                  "detail, fix the scrape file(s), then re-run.")
            print("If these are genuinely correct, re-run with --skip-swap-gate.")
            sys.exit(1)

        total = ingest_year(conn, race_id, info.name, scrapes_dir, year, stage_files)
        grand_total += total
        if not DRY_RUN:
            print(f"  {year}: {total} results inserted")

    conn.close()
    print(f"\nDone: {grand_total} total stage results across {len(years)} year(s)")

    if not DRY_RUN and race == "giro":
        import importlib.util
        fix_path = os.path.join(HERE, "fix_giro_rider_names.py")
        spec = importlib.util.spec_from_file_location("fix_giro_rider_names", fix_path)
        fix_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fix_mod)
        print()
        fix_mod.main()


if __name__ == "__main__":
    main()
