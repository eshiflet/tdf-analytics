#!/usr/bin/env python3
"""
Tests for the two repair tools added during the September 2026 pass.

Run:  python3 -m unittest test_repair_tools -v

preview_reingest.py is what decides whether a re-ingest is safe to run, so a
wrong answer from it misleads at exactly the moment it matters — the 1982 Tour
lost 145 real placings to an --allow-drop that looked like a one-stage cleanup,
and the check that should have caught it first is this one. Its three
categories are not interchangeable: a NULL-fill is a gain, an overwrite wants
reading, and a clear is either a carried-forward value correctly dropped or
real data disappearing.

clear_impossible_stage_times.py keys on the RANK 1 rider rather than the
fastest stored time. That distinction spared Milan-San Remo 1915, where the
winner's time is fine and one other row holds 3:18 for 289 km: condemning the
stage would have thrown away good data to punish one bad row.
"""

import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import clear_impossible_stage_times as CIST
import preview_reingest as PR


class TestPreviewDiff(unittest.TestCase):
    """preview_reingest.diff — fills, overwrites and clears counted apart."""

    @staticmethod
    def results(**rows):
        """{(stage, rider): {col: value}} with every tracked column defaulted."""
        out = {}
        for key, changed in rows.items():
            stage, rider = key.split("_", 1)
            row = {c: None for c in PR.RESULT_COLS}
            row.update(changed)
            out[(int(stage), rider)] = row
        return out

    def diff(self, before, after):
        return PR.diff(({}, before), ({}, after))

    def test_a_value_arriving_is_a_fill_not_an_overwrite(self):
        d = self.diff(self.results(**{"1_rider/a": {}}),
                      self.results(**{"1_rider/a": {"finish_time_seconds": 3600}}))
        self.assertEqual(d["fill"], {"finish_time_seconds": 1})
        self.assertEqual(d["over"], {})
        self.assertEqual(d["clear"], {})

    def test_a_value_leaving_is_a_clear(self):
        """The category to read first. A clear is either a carried-forward GC
        rank correctly dropped or real data going missing, and the count alone
        cannot tell you which — which is why it is never folded into the rest."""
        d = self.diff(self.results(**{"1_rider/a": {"gc_rank": 4}}),
                      self.results(**{"1_rider/a": {}}))
        self.assertEqual(d["clear"], {"gc_rank": 1})
        self.assertEqual(d["fill"], {})

    def test_a_changed_value_is_an_overwrite(self):
        d = self.diff(self.results(**{"1_rider/a": {"gap_seconds": 10}}),
                      self.results(**{"1_rider/a": {"gap_seconds": 12}}))
        self.assertEqual(d["over"], {"gap_seconds": 1})

    def test_an_unchanged_value_is_counted_nowhere(self):
        same = {"gap_seconds": 10, "stage_rank": 3}
        d = self.diff(self.results(**{"1_rider/a": same}),
                      self.results(**{"1_rider/a": dict(same)}))
        self.assertEqual((d["fill"], d["over"], d["clear"]), ({}, {}, {}))

    def test_rows_gone_and_new_are_reported_separately_from_the_columns(self):
        """A rider who disappears is not an 'overwrite' of anything — the 1982
        Tour's stage 9 fell from 155 rows to 10, and no column count would have
        shown it."""
        d = self.diff(self.results(**{"1_rider/a": {"stage_rank": 1},
                                      "1_rider/b": {"stage_rank": 2}}),
                      self.results(**{"1_rider/a": {"stage_rank": 1},
                                      "1_rider/c": {"stage_rank": 2}}))
        self.assertEqual((d["gone"], d["new"]), (1, 1))
        self.assertEqual(d["rows_before"], 2)
        self.assertEqual(d["rows_after"], 2)
        self.assertEqual(d["over"], {}, "a departed rider is not a changed value")

    def test_a_stage_field_change_is_tracked_apart_from_the_results(self):
        d = PR.diff(({1: {c: None for c in PR.STAGE_COLS}}, {}),
                    ({1: {**{c: None for c in PR.STAGE_COLS}, "route_type": "M"}}, {}))
        self.assertEqual(d["stage_fields"], {"route_type": 1})


class TestImpossibleTimes(unittest.TestCase):
    """clear_impossible_stage_times — which stage is condemned, and on what."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
            self.conn.executescript(f.read())
        cur = self.conn.cursor()
        cur.execute("INSERT INTO races (race_id, name, country, race_type) "
                    "VALUES (1,'Tour de France','France','stage_race')")
        cur.execute("INSERT INTO race_editions (edition_id, race_id, year) VALUES (1,1,1962)")
        self.cur = cur

    def tearDown(self):
        self.conn.close()

    def stage(self, number, km, times, cancelled=0):
        """times: [(stage_rank, finish_time_seconds)]"""
        self.cur.execute("INSERT INTO stages (edition_id, stage_number, distance_km, "
                         "cancelled) VALUES (1,?,?,?)", (number, km, cancelled))
        sid = self.cur.lastrowid
        for i, (rank, secs) in enumerate(times):
            rid = f"rider/{number}-{i}"
            self.cur.execute("INSERT OR IGNORE INTO riders (rider_id, full_name) "
                             "VALUES (?,?)", (rid, rid))
            self.cur.execute("INSERT INTO stage_results (stage_id, rider_id, stage_rank, "
                             "finish_time_seconds) VALUES (?,?,?,?)", (sid, rid, rank, secs))
        return sid

    def test_a_gc_total_in_the_time_column_is_caught(self):
        """1962 stage-2b: 23 km in 10:45:17, which is 2.1 km/h."""
        self.stage(3, 23.0, [(1, 38717), (2, 38753)])
        hits = CIST.find(self.cur)
        self.assertEqual([(h["stage_number"], round(h["kmh"], 1)) for h in hits], [(3, 2.1)])

    def test_a_gap_in_the_winners_cell_is_caught(self):
        """2008 stage 6: 195.5 km in one second, because the rider who won it
        was stripped and the promoted rider's row carries his GAP."""
        self.stage(6, 195.5, [(1, 1), (2, 2)])
        self.assertEqual([h["stage_number"] for h in CIST.find(self.cur)], [6])

    def test_a_real_stage_is_left_alone(self):
        for n, km, secs in ((1, 240.0, 28800), (2, 23.0, 1800), (4, 468.0, 75600)):
            self.stage(n, km, [(1, secs), (2, secs + 30)])
        self.assertEqual(CIST.find(self.cur), [])

    def test_one_bad_row_does_not_condemn_the_stage(self):
        """Milan-San Remo 1915 in miniature: the winner's time is fine and a
        single other row is absurd. Keying on MIN() would clear the whole
        field; keying on rank 1 clears nothing, and the bad row is left for a
        repair that can tell a bad row from a bad stage."""
        self.stage(5, 289.0, [(1, 28000), (2, 198), (3, 28100)])
        self.assertEqual(CIST.find(self.cur), [])

    def test_the_fastest_time_stands_in_when_no_rank_1_has_one(self):
        sid = self.stage(7, 100.0, [(1, None), (2, 2)])
        secs, source = CIST.winner_time(self.cur, sid)
        self.assertEqual((secs, source), (2, "fastest stored"))

    def test_a_cancelled_stage_is_never_examined(self):
        """distance 0 and no race: there is no speed to be implausible."""
        self.stage(8, 0.0, [(1, 38717)], cancelled=1)
        self.assertEqual(CIST.find(self.cur), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
