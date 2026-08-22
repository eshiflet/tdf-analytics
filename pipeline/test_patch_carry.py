#!/usr/bin/env python3
"""
Tests for carrying patched values across a re-ingest (race_set_ingest.py).

Every case here is a real incident. On 2026-08-21 a full re-ingest reverted
Milan-San Remo 2013 to PCS's wrong 121.0 km and dropped 1,884 team
attributions in complete silence, because an ingest rebuilds from the scrape
files and corrections live only in the database. And the first version of the
fix lost provenance on any patch whose value the source had since caught up
with — Giro 1919 stage 10 went from 'wikipedia' to no attribution at all while
its value never moved.
"""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from race_set_ingest import capture_patches, replace_edition, restore_patches

SCHEMA = """
CREATE TABLE races (race_id INTEGER PRIMARY KEY, name TEXT, country TEXT, race_type TEXT);
CREATE TABLE race_editions (edition_id INTEGER PRIMARY KEY, race_id INTEGER, year INTEGER, edition_name TEXT);
CREATE TABLE stages (stage_id INTEGER PRIMARY KEY AUTOINCREMENT, edition_id INTEGER,
    stage_number INTEGER, distance_km REAL, vertical_meters INTEGER, cancelled INTEGER DEFAULT 0);
CREATE TABLE stage_results (result_id INTEGER PRIMARY KEY AUTOINCREMENT, stage_id INTEGER,
    rider_id TEXT, team_id TEXT, finish_time_seconds INTEGER);
CREATE TABLE data_provenance (entity TEXT, entity_id INTEGER, field TEXT, source TEXT,
    source_ref TEXT, script TEXT, recorded_at TEXT, PRIMARY KEY (entity, entity_id, field));
"""


class PatchCarryTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.cur = self.conn.cursor()
        self.cur.executescript(SCHEMA)
        self.cur.execute("INSERT INTO races VALUES (1,'Milan-San Remo','Italy','one_day')")
        self.cur.execute("INSERT INTO race_editions VALUES (1,1,2013,'2013')")
        self.cur.execute("INSERT INTO stages (stage_id,edition_id,stage_number,distance_km)"
                         " VALUES (10,1,1,246.0)")
        self.cur.execute("INSERT INTO stage_results (stage_id,rider_id,team_id,finish_time_seconds)"
                         " VALUES (10,'rider/gerald-ciolek','team/mtn-2013',20240)")
        # what the patch scripts recorded
        self.cur.execute("INSERT INTO data_provenance VALUES "
                         "('stages',10,'distance_km','wikipedia','wiki-url','patch.py','t')")
        self.cur.execute("INSERT INTO data_provenance VALUES "
                         "('stage_results',10,'team_id:rider/gerald-ciolek','bikeraceinfo',"
                         "'bri-url','patch_teams.py','t')")

    def rebuild(self, distance, team=None, rider="rider/gerald-ciolek"):
        """Simulate an ingest: capture, wipe the edition, re-insert from 'scrape'."""
        captured = capture_patches(self.cur, 1, 2013)
        eid = replace_edition(self.cur, 1, 2013, "2013")
        self.cur.execute("INSERT INTO stages (edition_id,stage_number,distance_km)"
                         " VALUES (?,1,?)", (eid, distance))
        sid = self.cur.lastrowid
        self.cur.execute("INSERT INTO stage_results (stage_id,rider_id,team_id) "
                         "VALUES (?,?,?)", (sid, rider, team))
        return captured, eid, sid

    def value(self, sid, col="distance_km"):
        return self.cur.execute(f"SELECT {col} FROM stages WHERE stage_id=?",
                                (sid,)).fetchone()[0]

    def source(self, entity, eid, field):
        row = self.cur.execute(
            "SELECT source FROM data_provenance WHERE entity=? AND entity_id=? AND field=?",
            (entity, eid, field)).fetchone()
        return row[0] if row else None

    # ── the incident ────────────────────────────────────────────────────────
    def test_a_rebuild_alone_reverts_the_patch(self):
        """Without carrying, the scrape's wrong value wins. This is the bug."""
        _, _, sid = self.rebuild(121.0)
        self.assertEqual(self.value(sid), 121.0)

    def test_the_patched_value_survives_a_rebuild(self):
        # Team supplied by the "scrape" so only the distance patch is in play.
        captured, eid, sid = self.rebuild(121.0, team="team/mtn-2013")
        restored, _, _ = restore_patches(self.cur, eid, captured)
        self.assertEqual(self.value(sid), 246.0)
        self.assertEqual(self.source("stages", sid, "distance_km"), "wikipedia")
        self.assertEqual(len(restored), 1, restored)

    def test_a_patched_team_survives_a_rebuild(self):
        captured, eid, sid = self.rebuild(121.0, team=None)
        restore_patches(self.cur, eid, captured)
        team = self.cur.execute(
            "SELECT team_id FROM stage_results WHERE stage_id=?", (sid,)).fetchone()[0]
        self.assertEqual(team, "team/mtn-2013")
        self.assertEqual(self.source("stage_results", sid,
                                     "team_id:rider/gerald-ciolek"), "bikeraceinfo")

    # ── the bug in the first version of the fix ─────────────────────────────
    def test_a_redundant_patch_keeps_its_provenance(self):
        """Giro 1919 stage 10: the source caught up, so no value changed — but
        skipping record_provenance left the field with no attribution at all."""
        captured, eid, sid = self.rebuild(246.0, team="team/mtn-2013")
        restored, redundant, _ = restore_patches(self.cur, eid, captured)
        self.assertEqual(restored, [], restored)
        self.assertEqual(len(redundant), 1)
        self.assertEqual(self.value(sid), 246.0)
        self.assertEqual(self.source("stages", sid, "distance_km"), "wikipedia")

    # ── things it must not do ───────────────────────────────────────────────
    def test_a_patch_with_nowhere_to_go_is_reported_not_silently_dropped(self):
        captured = capture_patches(self.cur, 1, 2013)
        eid = replace_edition(self.cur, 1, 2013, "2013")   # rebuild with NO stages
        restored, _, unplaceable = restore_patches(self.cur, eid, captured)
        self.assertEqual(restored, [])
        self.assertEqual(len(unplaceable), 2)

    def test_a_rider_missing_from_the_rebuilt_field_is_reported(self):
        captured, eid, _ = self.rebuild(121.0, rider="rider/someone-else")
        _, _, unplaceable = restore_patches(self.cur, eid, captured)
        self.assertTrue(any("not in the rebuilt field" in u for u in unplaceable))

    def test_ingest_sources_are_never_carried(self):
        """Only patch sources travel. A 'pcs' value must be free to change when
        the scrape changes, or a re-scrape could never correct anything."""
        self.cur.execute("UPDATE data_provenance SET source='pcs' WHERE entity='stages'")
        captured, eid, sid = self.rebuild(121.0)
        restore_patches(self.cur, eid, captured)
        self.assertEqual(self.value(sid), 121.0)

    def test_capture_is_empty_for_an_edition_that_does_not_exist(self):
        captured = capture_patches(self.cur, 1, 1899)
        self.assertEqual(captured, {"stages": [], "results": []})


if __name__ == "__main__":
    unittest.main()
