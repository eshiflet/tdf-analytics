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
from race_common import COUNTRY_NAMES


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
