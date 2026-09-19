#!/usr/bin/env python3
"""
Tests for the aggregate-race exporter (race_set_export.py).

This module is shared by the one-day classics and the off-road set, and until
now was covered only transitively — by the two exporters producing byte-identical
output after being merged. That proves it did not CHANGE; it does not pin what
it does, and it says nothing about the riders_index encoding, which has since
been rewritten.

The cases below are the behaviours that are easy to break and hard to notice:
season ordering, a finalRank that is a best-of rather than a last, standings
carried across races a rider skipped, and an index whose finalRank is derived
rather than stored.
"""
import json
import os
import sqlite3
import sys
import unittest
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from race_set_export import DNF_SENTINEL, RaceSet, build_index, build_year

# The REAL schema, not a hand-written subset.
#
# This was a 7-table miniature, and it drifted the moment a column was added:
# race_set_export.py learned to SELECT stages.field_definition and fifteen tests
# died on "no such column" — a failure that says nothing about the change that
# caused it. schema.sql is the file the live database is built from, so building
# the fixture from it means an exporter can only query columns that really
# exist, which is the same lesson test_ingest.py records for route_type.
def _schema_sql():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "schema.sql"), encoding="utf-8") as f:
        return f.read()



@dataclass(frozen=True)
class FakeInfo:
    name: str
    short: str


class ExportTestBase(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.cur = self.conn.cursor()
        self.cur.executescript(_schema_sql())
        self.cur.execute("INSERT INTO countries (code, name) VALUES ('be','Belgium')")
        # Columns named explicitly: schema.sql's teams also has season_year,
        # and a positional insert is what ties a fixture to a column COUNT.
        self.cur.execute("INSERT INTO teams (team_id, name) VALUES ('team/x','Team X')")
        self._sid = 0

    def add_race(self, race_id, name, short):
        self.cur.execute("INSERT INTO races (race_id, name, country, race_type) "
                         "VALUES (?,?,'Belgium','one_day')", (race_id, name))
        return FakeInfo(name, short)

    def add_edition(self, edition_id, race_id, year):
        self.cur.execute("INSERT INTO race_editions "
                         "(edition_id, race_id, year, edition_name) "
                         "VALUES (?,?,?,NULL)",
                         (edition_id, race_id, year))

    def add_stage(self, edition_id, label, date, cancelled=0):
        self._sid += 1
        self.cur.execute(
            "INSERT INTO stages (stage_id, edition_id, stage_number, stage_label, "
            "stage_date, cancelled) VALUES (?,?,1,?,?,?)",
            (self._sid, edition_id, label, date, cancelled))
        return self._sid

    def add_result(self, stage_id, rider, rank, points=0, team=None, bib=None):
        self.cur.execute("INSERT OR IGNORE INTO riders (rider_id, full_name, first_name, last_name, nationality_code) VALUES (?,?,NULL,NULL,'be')",
                         (rider, rider))
        self.cur.execute(
            "INSERT INTO stage_results (stage_id, rider_id, team_id, stage_rank, "
            "status, pcs_points, bib_number) VALUES (?,?,?,?,'FINISHED',?,?)",
            (stage_id, rider, team, rank, points, bib))

    def build(self, year, infos):
        rs = RaceSet("classics", "one_day", {i.short: i for i in infos})
        return build_year(self.cur, rs, year, {i.name: i.short for i in infos})


class TestSeasonShape(ExportTestBase):
    def test_races_are_ordered_by_the_date_they_ran(self):
        """2020 is the case: COVID moved Il Lombardia to August, ahead of
        Fleche and Liege. A fixed calendar order would render it wrong.

        The names deliberately sort OPPOSITE to the dates. An earlier version of
        this test used the real race names, whose alphabetical order happens to
        match their 2020 order — so it passed even with the ORDER BY replaced by
        `ORDER BY r.name`. Mutation testing found that; the names are synthetic
        now precisely so they cannot agree by accident."""
        a = self.add_race(1, "Alpha (ran last)", "AL")
        b = self.add_race(2, "Zulu (ran first)", "ZU")
        self.add_edition(1, 1, 2020); self.add_edition(2, 2, 2020)
        s1 = self.add_stage(1, "Alpha (ran last)", "2020-09-30")
        s2 = self.add_stage(2, "Zulu (ran first)", "2020-08-15")
        self.add_result(s1, "rider/x", 1); self.add_result(s2, "rider/x", 2)
        data = self.build(2020, [a, b])
        self.assertEqual([s["stage_label"] for s in data["stages"]],
                         ["Zulu (ran first)", "Alpha (ran last)"])

    def test_a_null_date_sorts_last_not_first(self):
        # Name order puts the undated race FIRST, so only the date rule can
        # produce the expected result.
        a = self.add_race(1, "Aaa undated", "UD")
        b = self.add_race(2, "Zzz dated", "DT")
        self.add_edition(1, 1, 2020); self.add_edition(2, 2, 2020)
        s1 = self.add_stage(1, "Aaa undated", None)
        s2 = self.add_stage(2, "Zzz dated", "2020-03-01")
        self.add_result(s1, "rider/x", 1); self.add_result(s2, "rider/x", 1)
        data = self.build(2020, [a, b])
        self.assertEqual([s["stage_label"] for s in data["stages"]],
                         ["Zzz dated", "Aaa undated"])

    def test_a_season_may_hold_a_single_race(self):
        """The off-road set's 1994 is Leadville alone; a classics season before
        1907 is likewise short. Nothing should special-case it."""
        a = self.add_race(1, "Leadville", "LV")
        self.add_edition(1, 1, 1994)
        s = self.add_stage(1, "Leadville", "1994-08-13")
        self.add_result(s, "rider/stamstad", 1)
        data = self.build(1994, [a])
        self.assertEqual(len(data["stages"]), 1)
        self.assertEqual(data["riders"][0]["finalRank"], 1)

    def test_a_cancelled_race_keeps_its_slot(self):
        a = self.add_race(1, "Cancelled", "CX")
        self.add_edition(1, 1, 2020)
        self.add_stage(1, "Cancelled", "2020-04-01", cancelled=1)
        data = self.build(2020, [a])
        self.assertTrue(data["stages"][0]["cancelled"])
        self.assertEqual(data["riders"], [])


class TestFinalRank(ExportTestBase):
    def setUp(self):
        super().setUp()
        self.a = self.add_race(1, "First", "F1")
        self.b = self.add_race(2, "Second", "S2")
        self.add_edition(1, 1, 2021); self.add_edition(2, 2, 2021)
        self.s1 = self.add_stage(1, "First", "2021-03-01")
        self.s2 = self.add_stage(2, "Second", "2021-04-01")

    def test_final_rank_is_the_best_of_the_season_not_the_last(self):
        self.add_result(self.s1, "rider/x", 3)
        self.add_result(self.s2, "rider/x", 47)
        data = self.build(2021, [self.a, self.b])
        self.assertEqual(data["riders"][0]["finalRank"], 3)

    def test_a_rider_who_never_finished_gets_the_sentinel(self):
        self.add_result(self.s1, "rider/x", None)
        data = self.build(2021, [self.a, self.b])
        self.assertEqual(data["riders"][0]["finalRank"], DNF_SENTINEL)

    def test_a_season_has_no_total_time(self):
        self.add_result(self.s1, "rider/x", 1)
        data = self.build(2021, [self.a, self.b])
        self.assertIsNone(data["riders"][0]["totalTimeSeconds"])


class TestSeasonStandings(ExportTestBase):
    def setUp(self):
        super().setUp()
        self.a = self.add_race(1, "First", "F1")
        self.b = self.add_race(2, "Second", "S2")
        self.add_edition(1, 1, 2021); self.add_edition(2, 2, 2021)
        self.s1 = self.add_stage(1, "First", "2021-03-01")
        self.s2 = self.add_stage(2, "Second", "2021-04-01")

    def points_at(self, data, rider, stage):
        rec = next(r for r in data["riders"] if r["id"] == rider)
        return next(p for p in rec["byStage"] if p["stage"] == stage)

    def test_points_accumulate_across_the_season(self):
        self.add_result(self.s1, "rider/x", 1, points=100)
        self.add_result(self.s2, "rider/x", 1, points=50)
        data = self.build(2021, [self.a, self.b])
        self.assertEqual(self.points_at(data, "rider/x", 1)["cumulativePoints"], 100)
        self.assertEqual(self.points_at(data, "rider/x", 2)["cumulativePoints"], 150)

    def test_a_rider_on_zero_is_unplaced_not_ranked_last(self):
        self.add_result(self.s1, "rider/x", 1, points=100)
        self.add_result(self.s1, "rider/zero", 90, points=0)
        data = self.build(2021, [self.a, self.b])
        self.assertEqual(self.points_at(data, "rider/x", 1)["sprintRank"], 1)
        self.assertIsNone(self.points_at(data, "rider/zero", 1)["sprintRank"])

    def test_tied_riders_share_a_rank(self):
        self.add_result(self.s1, "rider/a", 1, points=50)
        self.add_result(self.s1, "rider/b", 2, points=50)
        data = self.build(2021, [self.a, self.b])
        self.assertEqual(self.points_at(data, "rider/a", 1)["sprintRank"],
                         self.points_at(data, "rider/b", 1)["sprintRank"])

    def test_a_set_awarding_no_points_is_a_no_op(self):
        """The off-road races award nothing PCS records, so every pcs_points is
        NULL. The standings pass must then produce exactly what that set ships —
        zero totals and no ranks — which is why it needs no flag."""
        self.add_result(self.s1, "rider/x", 1, points=None)
        data = self.build(2021, [self.a, self.b])
        pt = self.points_at(data, "rider/x", 1)
        self.assertEqual(pt["cumulativePoints"], 0)
        self.assertIsNone(pt["sprintRank"])


class TestRidersIndexEncoding(ExportTestBase):
    """The `ym` encoding: [teamIdx, raceIdx, rank, raceIdx, rank, ...].
    finalRank is NOT stored — it is min() of those ranks, derived on load."""

    def build_index_for(self, results):
        a = self.add_race(1, "First", "F1")
        b = self.add_race(2, "Second", "S2")
        self.add_edition(1, 1, 2021); self.add_edition(2, 2, 2021)
        s1 = self.add_stage(1, "First", "2021-03-01")
        s2 = self.add_stage(2, "Second", "2021-04-01")
        for stage, rider, rank, team in results:
            self.add_result(s1 if stage == 1 else s2, rider, rank, team=team)
        return build_index({2021: self.build(2021, [a, b])})

    def test_flat_array_is_team_then_race_rank_pairs(self):
        idx = self.build_index_for([(1, "rider/x", 3, "team/x"), (2, "rider/x", 7, "team/x")])
        flat = idx["riders"]["x"]["ym"]["2021"]
        self.assertEqual(flat[0], idx["teams"].index("Team X"))
        self.assertEqual([idx["races"][flat[1]], flat[2]], ["First", 3])
        self.assertEqual([idx["races"][flat[3]], flat[4]], ["Second", 7])

    def test_final_rank_is_not_stored_and_derives_correctly(self):
        idx = self.build_index_for([(1, "rider/x", 9, None), (2, "rider/x", 4, None)])
        flat = idx["riders"]["x"]["ym"]["2021"]
        self.assertEqual(min(flat[2::2]), 4)          # what the loader computes
        self.assertNotIn("y", idx["riders"]["x"])
        self.assertNotIn("m", idx["riders"]["x"])

    def test_no_team_is_minus_one_and_leaves_the_table_empty(self):
        idx = self.build_index_for([(1, "rider/x", 1, None)])
        self.assertEqual(idx["riders"]["x"]["ym"]["2021"][0], -1)
        self.assertEqual(idx["teams"], [])

    def test_a_dnf_carries_the_sentinel_so_min_ignores_it(self):
        idx = self.build_index_for([(1, "rider/x", None, None), (2, "rider/x", 12, None)])
        flat = idx["riders"]["x"]["ym"]["2021"]
        self.assertIn(DNF_SENTINEL, flat[2::2])
        self.assertEqual(min(flat[2::2]), 12)


if __name__ == "__main__":
    unittest.main()


class TestFieldDefinitionIsExported(unittest.TestCase):
    """The off-road field slice reaches the browser, and only where it means
    something.

    A classic has one field and a rank is unambiguously a place in it, so a
    null key on all 21 of its editions would be payload for no reader. An
    off-road race is a mass start with categories inside it, and the key is
    what makes its rank interpretable.
    """

    def test_gravel_editions_carry_it(self):
        import glob
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.join(here, "..", "cycling-app", "src", "data", "gravel")
        files = sorted(glob.glob(os.path.join(root, "gc_by_stage_*.json")))
        if not files:
            self.skipTest("gravel not exported")
        seen, missing = set(), []
        for path in files:
            with open(path, encoding="utf-8") as f:
                for s in json.load(f)["stages"]:
                    if s.get("cancelled"):
                        continue
                    if not s.get("field_definition"):
                        missing.append(f"{os.path.basename(path)}:{s['stage_label']}")
                    else:
                        seen.add(s["field_definition"])
        self.assertEqual(missing, [], "raced off-road editions with no field_definition")
        self.assertTrue(seen <= {"open_field", "elite_course", "elite_division",
                                 "pcs_field"}, f"unexpected values: {seen}")

    def test_the_classics_do_not_carry_it(self):
        import glob
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.join(here, "..", "cycling-app", "src", "data", "classics")
        files = sorted(glob.glob(os.path.join(root, "gc_by_stage_*.json")))
        if not files:
            self.skipTest("classics not exported")
        for path in files:
            with open(path, encoding="utf-8") as f:
                for s in json.load(f)["stages"]:
                    self.assertNotIn("field_definition", s,
                                     f"{os.path.basename(path)} carries a key with "
                                     "nothing to disambiguate")

    def test_leadville_shows_the_2016_change(self):
        """The case this exists for: the same race, the same rank column, two
        different meanings either side of one year."""
        import glob
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.join(here, "..", "cycling-app", "src", "data", "gravel")
        got = {}
        for year in (2015, 2016, 2026):
            path = os.path.join(root, f"gc_by_stage_{year}.json")
            if not os.path.exists(path):
                self.skipTest(f"gravel {year} not exported")
            with open(path, encoding="utf-8") as f:
                for s in json.load(f)["stages"]:
                    if s["stage_label"].startswith("Leadville"):
                        got[year] = s.get("field_definition")
        self.assertEqual(got, {2015: "open_field",
                               2016: "elite_division",
                               2026: "elite_course"})


class TestSeasonLevelBibIsDeterministic(ExportTestBase):
    """A season-level bib must not depend on SQLite's row order.

    A stage race has one bib per rider per edition, so this never arises there.
    An aggregate season is a dozen SEPARATE races and a rider has a different
    number in each: Mattia De Marchi rode 2022 as bib 110 at The Traka and 2399
    at Unbound, and both are correct. The exporter takes whichever row it sees
    FIRST, and its query has no ORDER BY — so re-ingesting any race in the
    season shuffled the rowids and changed the answer, churning every
    gc_by_stage_*.json in the set with no data change behind it.

    The rows are inserted here in REVERSE calendar order on purpose: that is
    what makes "first row returned" and "first race of the season" different
    answers, and without it the test passes whether or not the sort exists.
    """

    def setUp(self):
        super().setUp()
        self.infos = [self.add_race(1, "Late Race", "LR"),
                      self.add_race(2, "Early Race", "ER")]
        self.add_edition(1, 1, 2022)
        self.add_edition(2, 2, 2022)
        # Inserted late-first, so rowid order is the OPPOSITE of calendar order.
        self.late = self.add_stage(1, "Late Race", "2022-09-01")
        self.early = self.add_stage(2, "Early Race", "2022-04-01")
        self.add_result(self.late, "rider/a", 5, bib=2399, team="team/x")
        self.add_result(self.early, "rider/a", 3, bib=110)

    def test_the_bib_comes_from_the_seasons_FIRST_race(self):
        year = self.build(2022, self.infos)
        rec = next(r for r in year["riders"] if r["id"] == "rider/a")
        self.assertEqual(rec["bibNumber"], 110,
                         "the bib should be the one from the April race, not "
                         "whichever row SQLite happened to return first")

    def test_the_race_order_it_depends_on_is_by_DATE(self):
        """Guards the assumption underneath: stage 1 of the season is the
        earliest race, not the lowest stage_id."""
        year = self.build(2022, self.infos)
        self.assertEqual([s["stage_label"] for s in year["stages"]],
                         ["Early Race", "Late Race"])

    def test_the_team_is_taken_the_same_way(self):
        """The team had the identical bug — 'keep the first non-null seen' over
        an unordered result set — and moved on 181 riders when this was fixed.
        Here only the LATE race records a team, so a correct implementation
        still finds it while walking in calendar order."""
        year = self.build(2022, self.infos)
        rec = next(r for r in year["riders"] if r["id"] == "rider/a")
        self.assertEqual(rec["team"], "Team X")

    def test_a_rider_with_one_race_is_unaffected(self):
        self.add_result(self.late, "rider/b", 9, bib=77)
        year = self.build(2022, self.infos)
        rec = next(r for r in year["riders"] if r["id"] == "rider/b")
        self.assertEqual(rec["bibNumber"], 77)
