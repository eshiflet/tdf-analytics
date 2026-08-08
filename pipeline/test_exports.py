#!/usr/bin/env python3
"""
Tests for the export scripts — the last step before data reaches the app.

Run:  python3 -m unittest test_exports -v

Two things are covered:

  * compute_stage_labels — the display labels the charts are drawn from. A
    wrong label here is directly visible and was what made Vuelta 1989 look
    broken (its "stage 21" is DB stage 22, because a split day shifts every
    later label). Pure, so tested directly.

  * export_all_races_summary.main — the per-year aggregate, exercised end to
    end against a scratch DB and scratch JSON inputs. Its arithmetic decides
    what the overview screen shows, and its Wikipedia reconciliation is the
    check that would have caught the 2010 Vuelta's two missing stages.

export_gc and export_riders_index are not covered here: both are large,
read many optional supplement files, and write via module-level paths that
would need extensive monkeypatching to isolate. compute_stage_labels was
extracted from export_gc precisely so the part that had a bug is testable.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import export_all_races_summary as EARS
from export_gc import compute_stage_labels

HERE = os.path.dirname(os.path.abspath(__file__))


def stage(n, date=None):
    return {"stage_number": n, "stage_date": date}


class TestStageLabels(unittest.TestCase):

    def test_plain_sequence(self):
        s = [stage(1, "2020-07-01"), stage(2, "2020-07-02"), stage(3, "2020-07-03")]
        self.assertEqual(compute_stage_labels(s), ["1", "2", "3"])

    def test_prologue_is_P_and_consumes_no_day(self):
        s = [stage(0, "2020-06-30"), stage(1, "2020-07-01"), stage(2, "2020-07-02")]
        self.assertEqual(compute_stage_labels(s), ["P", "1", "2"])

    def test_split_day_letters_and_shifts_later_labels(self):
        """Vuelta 1989: DB stages 3 and 4 are one racing day, so every later
        label sits one below its stage_number — DB 5 displays as '4'. This is
        correct, and is why the 1989 chart looked wrong at first glance."""
        s = [stage(1, "1989-04-24"), stage(2, "1989-04-25"),
             stage(3, "1989-04-26"), stage(4, "1989-04-26"),
             stage(5, "1989-04-27"), stage(6, "1989-04-28")]
        self.assertEqual(compute_stage_labels(s), ["1", "2", "3a", "3b", "4", "5"])

    def test_triple_split_day(self):
        s = [stage(1, "1950-05-01"), stage(2, "1950-05-02"),
             stage(3, "1950-05-02"), stage(4, "1950-05-02"),
             stage(5, "1950-05-03")]
        self.assertEqual(compute_stage_labels(s), ["1", "2a", "2b", "2c", "3"])

    def test_dateless_stage_keeps_its_position(self):
        """TDF 1998. Stage 17 (abandoned during the Festina affair) has no
        date. The old implementation grouped by date and walked the sorted
        keys, so '__nodate_17' sorted after every real date and the stage
        collected the LAST day number — it displayed as '21', pushing stages
        18-21 down to 17-20. Ordering must come from stage_number."""
        s = [stage(n, f"1998-07-{n:02d}") for n in range(1, 17)]
        s.append(stage(17, None))
        s += [stage(n, f"1998-07-{n:02d}") for n in range(18, 22)]
        labels = compute_stage_labels(s)
        self.assertEqual(labels[16], "17", "the dateless stage must keep its place")
        self.assertEqual(labels[-1], "21")
        self.assertEqual(labels, [str(i) for i in range(1, 22)])

    def test_all_dates_missing_still_orders_numerically(self):
        """With every date absent the old code ordered labels lexicographically
        (__nodate_10 before __nodate_2), scrambling them completely."""
        s = [stage(n, None) for n in range(1, 13)]
        self.assertEqual(compute_stage_labels(s), [str(i) for i in range(1, 13)])

    def test_repeated_date_that_is_not_consecutive_is_not_a_split(self):
        """A date repeated elsewhere in the edition is a data error, not a
        split day; grouping it would relabel unrelated stages."""
        s = [stage(1, "2020-07-01"), stage(2, "2020-07-02"),
             stage(3, "2020-07-03"), stage(4, "2020-07-01")]
        self.assertEqual(compute_stage_labels(s), ["1", "2", "3", "4"])

    def test_empty(self):
        self.assertEqual(compute_stage_labels([]), [])


class TestAllRacesSummary(unittest.TestCase):
    """export_all_races_summary end to end against scratch inputs."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        conn = sqlite3.connect(self.db)
        with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
            conn.executescript(f.read())
        cur = conn.cursor()
        cur.execute("INSERT INTO races (name, race_type) VALUES ('Tour de France','stage_race')")
        rid = cur.lastrowid
        cur.execute("INSERT INTO race_editions (race_id, year) VALUES (?, 1903)", (rid,))
        self.eid = cur.lastrowid
        cur.execute("INSERT INTO riders (rider_id, full_name) VALUES ('rider/a','A')")
        for n, km, vm in ((1, 100.0, 500), (2, 150.0, 1500)):
            cur.execute("""INSERT INTO stages (edition_id, stage_number, stage_date,
                           distance_km, vertical_meters) VALUES (?,?,?,?,?)""",
                        (self.eid, n, f"1903-07-0{n}", km, vm))
        self.last_stage_id = cur.lastrowid
        cur.execute("""INSERT INTO stage_results (stage_id, rider_id, status, gc_gap_seconds)
                       VALUES (?, 'rider/a', 'FINISHED', 600)""", (self.last_stage_id,))
        conn.commit()
        conn.close()

        self.out = os.path.join(self.tmp, "out.json")
        self._orig = (EARS.DB_PATH, EARS.OUT_PATH, EARS.WIKI_DISTANCES_PATH,
                      EARS.GC_WINNER_TIMES_PATH, EARS.OVERRIDES_PATH, EARS.STRICT)
        EARS.DB_PATH, EARS.OUT_PATH = self.db, self.out

    def tearDown(self):
        (EARS.DB_PATH, EARS.OUT_PATH, EARS.WIKI_DISTANCES_PATH,
         EARS.GC_WINNER_TIMES_PATH, EARS.OVERRIDES_PATH, EARS.STRICT) = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _json(self, name, obj):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return p

    def run_export(self, wiki=None, winners=None, overrides=None, strict=False):
        EARS.WIKI_DISTANCES_PATH = self._json("wiki.json", wiki or {})
        EARS.GC_WINNER_TIMES_PATH = self._json("win.json", winners or {})
        EARS.OVERRIDES_PATH = self._json("ovr.json", overrides or {})
        EARS.STRICT = strict
        import io
        buf, sys.stdout = sys.stdout, io.StringIO()
        try:
            EARS.main()
        finally:
            self.output = sys.stdout.getvalue()
            sys.stdout = buf
        with open(self.out, encoding="utf-8") as f:
            return {r["year"]: r for r in json.load(f)}

    def test_falls_back_to_db_sum_without_a_wikipedia_figure(self):
        rows = self.run_export()
        self.assertAlmostEqual(rows[1903]["totalDistanceKm"], 250.0)

    def test_prefers_the_wikipedia_figure_when_present(self):
        rows = self.run_export(wiki={"1903": 2428})
        self.assertEqual(rows[1903]["totalDistanceKm"], 2428)

    def test_elevation_sums_and_gap_years_are_null(self):
        rows = self.run_export()
        self.assertEqual(rows[1903]["totalElevationM"], 2000)

    def test_slowest_finisher_needs_a_winner_time(self):
        self.assertIsNone(self.run_export()[1903]["slowestFinisherTimeSeconds"])
        rows = self.run_export(winners={"1903": 1000})
        self.assertEqual(rows[1903]["slowestFinisherTimeSeconds"], 1600)  # 1000 + 600

    def test_overrides_win_over_computed_values(self):
        rows = self.run_export(overrides={"1903": {"totalElevationM": 99999}})
        self.assertEqual(rows[1903]["totalElevationM"], 99999)

    def test_close_wikipedia_figure_is_not_flagged(self):
        """Historical sources genuinely disagree by a percent or two."""
        self.run_export(wiki={"1903": 255})           # 250 vs 255 = 2%
        self.assertNotIn("WARNING", self.output)

    def test_divergent_wikipedia_figure_is_reported(self):
        """The check that would have caught the 2010 Vuelta's missing stages:
        the app shows Wikipedia's number, so a DB short by whole stages
        displays a correct-looking total unless the two are reconciled."""
        self.run_export(wiki={"1903": 500})           # 250 vs 500 = -50%
        self.assertIn("WARNING", self.output)
        self.assertIn("1903", self.output)

    def test_strict_mode_exits_nonzero_on_divergence(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_export(wiki={"1903": 500}, strict=True)
        self.assertEqual(cm.exception.code, 1)

    def test_strict_mode_passes_when_reconciled(self):
        self.run_export(wiki={"1903": 250}, strict=True)   # must not raise
        self.assertIn("reconciliation", self.output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
