#!/usr/bin/env python3
"""Shared DB writes for the aggregate race sets (one-day classics, off-road).

Both ingests are structured the same way — upsert the race, replace the edition
atomically, insert one stage and its results — and both had their own copy of
each step. The copies are the problem, not the size: `replace_edition()` below
is the block that clears a re-ingested edition's provenance rows, and
validate_db.py has a dedicated error for what happens when that is missed
("an edition was re-ingested without clearing them"). A fix applied to one copy
and not the other is exactly how that error comes back.

Deliberately NOT shared: rider upserts. The classics identify a rider by a PCS
slug that arrives with the scrape; the off-road set has no such id and resolves
identity by name beforehand (link_gravel_riders.py), so the two functions take
different arguments and answer to different rules. Merging them would mean a
flag deciding which identity model applies, which is the kind of sharing that
makes both harder to read.
"""
from race_common import COUNTRY_NAMES, record_provenance

# Provenance sources that only a patch script writes. An ingest writes 'pcs',
# 'athlinks' and 'derived'; anything here arrived afterwards — by hand, or from
# a second source — and is precisely what a rebuild would throw away.
PATCH_SOURCES = ("wikipedia", "bikeraceinfo", "cyclingflash", "manual")


def _columns(cur, table):
    return {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}


def capture_patches(cur, race_id, year):
    """Everything a patch script put into this edition, before it is rebuilt.

    THE POINT. An ingest rebuilds a race-year from its scrape files, which are a
    faithful record of what the SOURCE said — not of what we later worked out to
    be true. Corrections live in a second layer that writes straight to the DB,
    so a rebuild reverts them: on 2026-08-21 one put Milan-San Remo 2013 back to
    PCS's wrong 121.0 km and dropped 1,884 team attributions, in silence.

    Rather than a registry of patch scripts to re-run afterwards — which would
    need maintaining, ordering, and would miss any patch nobody registered —
    this reads the patches out of `data_provenance` itself and hands them back
    after the rebuild. Anything that recorded provenance is carried across, and
    that is the same rule the repo already requires of every writer.

    Keyed on stage_number and rider_id, never on stage_id or result_id: both are
    re-issued by the rebuild.
    """
    stage_cols = _columns(cur, "stages")
    result_cols = _columns(cur, "stage_results")
    qmarks = ",".join("?" * len(PATCH_SOURCES))

    stages, results = [], []
    for num, field, source, ref, script in cur.execute(
            f"""SELECT s.stage_number, dp.field, dp.source, dp.source_ref, dp.script
                FROM data_provenance dp
                JOIN stages s ON s.stage_id = dp.entity_id
                JOIN race_editions e ON e.edition_id = s.edition_id
                WHERE dp.entity = 'stages' AND e.race_id = ? AND e.year = ?
                  AND dp.source IN ({qmarks})""",
            (race_id, year, *PATCH_SOURCES)).fetchall():
        value = None
        if field in stage_cols:
            row = cur.execute(
                f"SELECT {field} FROM stages s JOIN race_editions e USING(edition_id) "
                "WHERE e.race_id=? AND e.year=? AND s.stage_number=?",
                (race_id, year, num)).fetchone()
            value = row[0] if row else None
        # A field that is not a column ('results' on a hand-entered Vuelta
        # stage) still has provenance worth keeping, just no value to restore.
        stages.append((num, field, field in stage_cols, value, source, ref, script))

    for num, field, source, ref, script in cur.execute(
            f"""SELECT s.stage_number, dp.field, dp.source, dp.source_ref, dp.script
                FROM data_provenance dp
                JOIN stages s ON s.stage_id = dp.entity_id
                JOIN race_editions e ON e.edition_id = s.edition_id
                WHERE dp.entity = 'stage_results' AND e.race_id = ? AND e.year = ?
                  AND dp.source IN ({qmarks})""",
            (race_id, year, *PATCH_SOURCES)).fetchall():
        col, _, rider = field.partition(":")
        if not rider or col not in result_cols:
            continue
        row = cur.execute(
            f"""SELECT sr.{col} FROM stage_results sr
                JOIN stages s USING(stage_id) JOIN race_editions e USING(edition_id)
                WHERE e.race_id=? AND e.year=? AND s.stage_number=? AND sr.rider_id=?""",
            (race_id, year, num, rider)).fetchone()
        if row is not None and row[0] is not None:
            results.append((num, col, rider, row[0], field, source, ref, script))

    return {"stages": stages, "results": results}


def restore_patches(cur, edition_id, captured):
    """Put the captured patches back, and say what happened to each.

    Returns (restored, redundant, unplaceable) as lists of human-readable
    strings. A patch is REDUNDANT when the rebuilt value already matches it —
    the upstream source has caught up, and the patch script could be retired.
    UNPLACEABLE means the stage or rider no longer exists in the rebuilt
    edition, which is a real change worth seeing rather than swallowing.
    """
    restored, redundant, unplaceable = [], [], []
    nums = {n: sid for sid, n in cur.execute(
        "SELECT stage_id, stage_number FROM stages WHERE edition_id=?", (edition_id,))}

    for num, field, is_col, value, source, ref, script in captured["stages"]:
        sid = nums.get(num)
        if sid is None:
            unplaceable.append(f"stage {num} {field} ({source})")
            continue
        if is_col:
            now = cur.execute(f"SELECT {field} FROM stages WHERE stage_id=?",
                              (sid,)).fetchone()[0]
            if now == value:
                redundant.append(f"stage {num} {field}={value!r} ({source})")
            else:
                cur.execute(f"UPDATE stages SET {field}=? WHERE stage_id=?",
                            (value, sid))
                restored.append(f"stage {num} {field}: {now!r} -> {value!r} ({source})")
        # Provenance is rewritten either way. Skipping it for a redundant patch
        # left Giro 1919 stage 10 with NO provenance row at all — the ingest had
        # deleted the 'wikipedia' one and nothing replaced it, so the field went
        # from attributed to unattributed while its value never moved.
        record_provenance(cur, "stages", sid, field, source,
                          source_ref=ref, script=script)

    for num, col, rider, value, field, source, ref, script in captured["results"]:
        sid = nums.get(num)
        if sid is None:
            unplaceable.append(f"stage {num} {field} ({source})")
            continue
        row = cur.execute(
            f"SELECT {col} FROM stage_results WHERE stage_id=? AND rider_id=?",
            (sid, rider)).fetchone()
        if row is None:
            unplaceable.append(f"stage {num} {rider} not in the rebuilt field")
            continue
        if row[0] != value:
            cur.execute(
                f"UPDATE stage_results SET {col}=? WHERE stage_id=? AND rider_id=?",
                (value, sid, rider))
            restored.append(f"stage {num} {rider} {col}={value!r} ({source})")
        record_provenance(cur, "stage_results", sid, field, source,
                          source_ref=ref, script=script)

    return restored, redundant, unplaceable


def report_patches(label, restored, redundant, unplaceable):
    """One line per outcome — silence here is how the 2026-08-21 loss happened."""
    if restored:
        print(f"    patches carried across {label}: {len(restored)}")
        for line in restored[:6]:
            print(f"      restored {line}")
        if len(restored) > 6:
            print(f"      ...and {len(restored) - 6} more")
    if redundant:
        print(f"    {len(redundant)} patch(es) now match the source and could be "
              f"retired, e.g. {redundant[0]}")
    for line in unplaceable:
        print(f"    ! patch has nowhere to go after the rebuild: {line}")


def upsert_country(cur, code):
    """Normalise and insert a country code, returning it. None-safe.

    Rejects anything that is not a two-letter alphabetic code: Athlinks writes
    region strings like '--' into the same field, and those must not become
    countries.
    """
    if not code:
        return None
    code = code.lower()
    if not code.isalpha() or len(code) != 2:
        return None
    cur.execute("INSERT OR IGNORE INTO countries (code, name) VALUES (?,?)",
                (code, COUNTRY_NAMES.get(code, code.upper())))
    return code


def upsert_race(cur, name, country, race_type):
    """race_id for a constituent race, creating it on first sight."""
    cur.execute("SELECT race_id FROM races WHERE name = ?", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO races (name, country, race_type) VALUES (?,?,?)",
                (name, country, race_type))
    return cur.lastrowid


def replace_edition(cur, race_id, year, edition_name=None):
    """edition_id for a race-year, cleared of any stages it already had.

    This is what makes a re-ingest atomic and re-runnable. Three things have to
    go together and in this order, per stage: its results, its provenance rows,
    then the stage itself. Dropping the provenance is the step most easily
    forgotten — the rows key on entity_id and survive the stage they describe,
    so the next ingest silently inherits another stage's provenance.
    """
    cur.execute("SELECT edition_id FROM race_editions WHERE race_id=? AND year=?",
                (race_id, year))
    row = cur.fetchone()
    if row:
        edition_id = row[0]
        cur.execute("SELECT stage_id FROM stages WHERE edition_id=?", (edition_id,))
        for (sid,) in cur.fetchall():
            cur.execute("DELETE FROM stage_results WHERE stage_id=?", (sid,))
            # BOTH entities. patch_classics_teams.py and patch_classics_times.py
            # record provenance as entity='stage_results' keyed on the STAGE id,
            # and nothing cleared those until 2026-08-21 — so every
            # re-ingest-then-re-patch cycle left the previous cycle's rows
            # behind, 4,450 of them by the time anyone looked.
            cur.execute("DELETE FROM data_provenance WHERE entity IN "
                        "('stages','stage_results') AND entity_id=?", (sid,))
            cur.execute("DELETE FROM stages WHERE stage_id=?", (sid,))
        cur.execute("UPDATE race_editions SET edition_name=? WHERE edition_id=?",
                    (edition_name, edition_id))
        return edition_id
    cur.execute("INSERT INTO race_editions (race_id, year, edition_name) VALUES (?,?,?)",
                (race_id, year, edition_name))
    return cur.lastrowid
