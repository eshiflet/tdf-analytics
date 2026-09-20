#!/usr/bin/env python3
"""
Tests for delete_orphan_teams.py — removing team rows nothing references.

This script deletes, so the tests are mostly about what it must refuse to
delete. Two things protect the data: a team-classification placing keeps a
row alive even with no riders, and the run aborts outright if deleting would
take a name out of a dropdown the app is still serving.

Run:  python3 -m unittest test_delete_orphan_teams -v
"""

import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import delete_orphan_teams as dot


class OrphanTeamDeleteTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
            self.conn.executescript(f.read())
        self.cur = self.conn.cursor()
        self.cur.execute("INSERT INTO races (race_id,name,race_type) "
                         "VALUES (1,'Tour de France','stage_race')")
        self.cur.execute("INSERT INTO race_editions (edition_id,race_id,year) "
                         "VALUES (1,1,2020)")
        self.cur.execute("INSERT INTO stages (stage_id,edition_id,stage_number) "
                         "VALUES (1,1,1)")
        # Several tests stub this out; it is module state, so put it back or
        # the failure lands in whichever test happens to run next.
        self._real_exports = dot.exported_team_names

    def tearDown(self):
        dot.exported_team_names = self._real_exports
        self.conn.close()

    def team(self, team_id, name):
        self.cur.execute("INSERT INTO teams (team_id,name,season_year) "
                         "VALUES (?,?,2020)", (team_id, name))

    def rider_on(self, rider_id, team_id):
        self.cur.execute("INSERT OR IGNORE INTO riders (rider_id,full_name) "
                         "VALUES (?,?)", (rider_id, rider_id))
        self.cur.execute("INSERT INTO stage_results (stage_id,rider_id,team_id) "
                         "VALUES (1,?,?)", (rider_id, team_id))

    def standing_for(self, team_id):
        self.cur.execute("INSERT OR IGNORE INTO riders (rider_id,full_name) "
                         "VALUES ('rider/x','x')")
        self.cur.execute(
            "INSERT INTO classification_standings "
            "(edition_id,classification,rank,rider_id,team_id) "
            "VALUES (1,'teams',1,'rider/x',?)", (team_id,))

    def orphans(self):
        return self.cur.execute(dot.ORPHANS).fetchall()

    def test_finds_a_team_nothing_references(self):
        self.team("team/stranded", "Stranded")
        self.assertEqual(self.orphans(), [("team/stranded", "Stranded")])

    def test_a_team_with_riders_is_not_an_orphan(self):
        self.team("team/live", "Live")
        self.rider_on("rider/a", "team/live")
        self.assertEqual(self.orphans(), [])

    def test_a_team_classification_placing_protects_a_riderless_team(self):
        """The placing is the team's own result — no rider row required."""
        self.team("team/won-the-team-prize", "Won The Team Prize")
        self.standing_for("team/won-the-team-prize")
        self.assertEqual(self.orphans(), [])

    def test_refuses_when_a_vanishing_name_is_still_in_the_app(self):
        """The name would go out of the DB while a dropdown still lists it."""
        self.team("team/only-row", "Ghost Team")
        dot.exported_team_names = lambda: {"Ghost Team", "Something Else"}
        problems = dot.check_safe(self.cur, self.orphans())
        self.assertTrue(problems)
        self.assertIn("Ghost Team", problems[0])

    def test_allows_when_the_name_survives_on_another_row(self):
        """145 names are in exactly this position: an empty row and a full one.
        The name stays in the app because the full row carries it."""
        self.team("team/alcyon-1946", "Alcyon - Dunlop")   # no riders
        self.team("team/alcyon-1947", "Alcyon - Dunlop")   # has one
        self.rider_on("rider/a", "team/alcyon-1947")
        dot.exported_team_names = lambda: {"Alcyon - Dunlop"}
        self.assertEqual(dot.check_safe(self.cur, self.orphans()), [])

    def test_refuses_when_there_are_no_exports_to_check_against(self):
        """Absence of evidence is not proof the deletion is invisible."""
        self.team("team/stranded", "Stranded")
        dot.exported_team_names = lambda: set()
        self.assertTrue(dot.check_safe(self.cur, self.orphans()))


if __name__ == "__main__":
    unittest.main()
