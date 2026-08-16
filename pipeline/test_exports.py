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

  * export_gc.Supplements and export_gc.main — the supplement loading and
    argument handling, both of which were module-level state until they were
    refactored to be injectable.

  * export_riders_index.build_index — the compact cross-year index, now pure.
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
import export_gc
import export_race_summary as ERS
import export_riders_index as ERI
from export_gc import Supplements, compute_stage_labels

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


class TestSupplements(unittest.TestCase):
    """export_gc.Supplements — replaced four path globals and four caches."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, obj):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return p

    def test_absent_paths_yield_empty_dicts(self):
        """Every supplement is optional; a race may simply not have one."""
        s = Supplements()
        self.assertEqual(s.sprint_points, {})
        self.assertEqual(s.kom_points, {})
        self.assertEqual(s.gc_all_times, {})
        self.assertEqual(s.gc_winner_times, {})

    def test_nonexistent_file_is_not_an_error(self):
        s = Supplements(sprint_path=os.path.join(self.tmp, "nope.json"))
        self.assertEqual(s.sprint_points, {})

    def test_reads_each_file(self):
        s = Supplements(
            sprint_path=self._write("sp.json", {"2020": [1, 2]}),
            kom_path=self._write("kom.json", {"2020": [3]}),
            gc_winner_path=self._write("win.json", {"2020": 100}),
        )
        self.assertEqual(s.sprint_points["2020"], [1, 2])
        self.assertEqual(s.kom_points["2020"], [3])
        self.assertEqual(s.gc_winner_times["2020"], 100)

    def test_file_is_read_once_and_cached(self):
        p = self._write("sp.json", {"2020": [1]})
        s = Supplements(sprint_path=p)
        self.assertEqual(s.sprint_points["2020"], [1])
        os.remove(p)
        self.assertEqual(s.sprint_points["2020"], [1], "must be cached, not re-read")

    def test_instances_do_not_share_state(self):
        """The old module-level caches let one race's supplements leak into
        another's export unless __main__ remembered to reset all four."""
        a = Supplements(sprint_path=self._write("a.json", {"1999": ["A"]}))
        b = Supplements(sprint_path=self._write("b.json", {"1999": ["B"]}))
        self.assertEqual(a.sprint_points["1999"], ["A"])
        self.assertEqual(b.sprint_points["1999"], ["B"])

    def test_for_race_resolves_per_race_names(self):
        for subdir in ("tour", "giro", "vuelta"):
            s = Supplements.for_race(subdir)
            self.assertIn(f"{subdir}_sprint_points.json", s._paths["sprint_points"])
        # gc_all_times.json is TDF-only and unprefixed
        self.assertTrue(Supplements.for_race("tour")._paths["gc_all_times"].endswith(
            "gc_all_times.json"))
        self.assertEqual(Supplements.for_race("giro")._paths["gc_all_times"], "__nonexistent__")


class TestExportGcArgs(unittest.TestCase):
    """export_gc.main argument handling — was unreachable inside __main__."""

    def test_bare_positional_year_is_rejected(self):
        """A bare '2020' used to be silently dropped, quietly turning a
        single-year export into a full rebuild of every year."""
        with self.assertRaises(SystemExit) as cm:
            export_gc.main(["export_gc.py", "--race", "vuelta", "2020"])
        self.assertIn("unrecognized", str(cm.exception))

    def test_unknown_race_is_rejected(self):
        with self.assertRaises(SystemExit) as cm:
            export_gc.main(["export_gc.py", "--race", "bogus"])
        self.assertIn("unknown race", str(cm.exception))

    def test_flag_without_value_is_rejected(self):
        with self.assertRaises(SystemExit) as cm:
            export_gc.main(["export_gc.py", "--year"])
        self.assertIn("requires a value", str(cm.exception))


class TestAbandonedRidersLeaveTheClassifications(unittest.TestCase):
    """export_gc.export_year — a rider who abandons keeps the points they
    scored but stops being ranked against the riders still racing.

    Without this, whoever led a classification when they climbed off held that
    lead to the finish: Roger De Vlaeminck abandoned stage 12 of the 1969 Tour
    on 61 sprint points and so outranked Merckx's eventual 59 on stage 25,
    taking the year's green jersey in the riders index.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        conn = sqlite3.connect(self.db)
        with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
            conn.executescript(f.read())
        cur = conn.cursor()
        cur.execute("INSERT INTO races (name, race_type) VALUES ('Tour de France','stage_race')")
        self.race_id = cur.lastrowid
        cur.execute("INSERT INTO race_editions (race_id, year) VALUES (?, 1969)", (self.race_id,))
        eid = cur.lastrowid
        for name in ("quitter", "stayer"):
            cur.execute("INSERT INTO riders (rider_id, full_name) VALUES (?,?)",
                        (f"rider/{name}", name))
        stage_ids = []
        for n in (1, 2, 3):
            cur.execute("""INSERT INTO stages (edition_id, stage_number, stage_date, distance_km)
                           VALUES (?,?,?,100.0)""", (eid, n, f"1969-07-0{n}"))
            stage_ids.append(cur.lastrowid)
        # The quitter abandons on stage 2; the stayer goes to Paris.
        for idx, sid in enumerate(stage_ids):
            cur.execute("""INSERT INTO stage_results (stage_id, rider_id, status, gc_rank)
                           VALUES (?, 'rider/stayer', 'FINISHED', ?)""", (sid, idx + 1))
        cur.execute("""INSERT INTO stage_results (stage_id, rider_id, status, gc_rank)
                       VALUES (?, 'rider/quitter', 'FINISHED', 2)""", (stage_ids[0],))
        cur.execute("""INSERT INTO stage_results (stage_id, rider_id, status, gc_rank)
                       VALUES (?, 'rider/quitter', 'DNF', NULL)""", (stage_ids[1],))
        conn.commit()
        conn.close()

        # The quitter builds a bigger points total before abandoning.
        sprint = os.path.join(self.tmp, "sprint.json")
        with open(sprint, "w", encoding="utf-8") as f:
            json.dump({"1969": [{"rider/quitter": 50, "rider/stayer": 10},
                                {"rider/stayer": 10},
                                {"rider/stayer": 10}]}, f)
        self.supp = Supplements(sprint_path=sprint)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def export(self):
        import io
        out = os.path.join(self.tmp, "out.json")
        buf, sys.stdout = sys.stdout, io.StringIO()   # export_year narrates
        try:
            export_gc.export_year(1969, out, race_id=self.race_id,
                                  db_path=self.db, supplements=self.supp)
        finally:
            sys.stdout = buf
        with open(out, encoding="utf-8") as f:
            return {r["id"]: r for r in json.load(f)["riders"]}

    def ranks(self, rider):
        return {s["stage"]: s.get("sprintRank") for s in rider["byStage"]}

    def test_the_finisher_leads_the_final_standings(self):
        riders = self.export()
        self.assertEqual(self.ranks(riders["rider/stayer"])[3], 1,
                         "30 points still racing beats 50 points gone home")

    def test_the_leader_is_ranked_until_the_stage_they_abandon(self):
        riders = self.export()
        quitter = self.ranks(riders["rider/quitter"])
        self.assertEqual(quitter[1], 1, "led the classification while racing")
        self.assertIsNone(quitter[2], "unranked from the stage they abandon on")

    def test_a_rider_whose_results_merely_stop_is_left_in(self):
        # A gap in old PCS pages is not an abandonment: the stayer's stage-3
        # row disappears, but their FINISHED stage-2 row keeps them ranked.
        conn = sqlite3.connect(self.db)
        conn.execute("""DELETE FROM stage_results WHERE rider_id = 'rider/stayer'
                        AND stage_id = (SELECT MAX(stage_id) FROM stages)""")
        conn.commit()
        conn.close()
        riders = self.export()
        self.assertEqual(self.ranks(riders["rider/stayer"])[2], 1)


class TestRidersIndex(unittest.TestCase):
    """export_riders_index.build_index — now pure, no file or DB access."""

    @staticmethod
    def rider(rid, name, team=None, final=1, by_stage=None, **kw):
        r = {"id": rid, "name": name, "finalRank": final,
             "byStage": by_stage if by_stage is not None else [{"stage": 1}]}
        if team:
            r["team"] = team
        r.update(kw)
        return r

    def test_team_string_table_is_sorted_and_indexed(self):
        ds = [("2020", {"riders": [self.rider("rider/a", "A", team="Zeta"),
                                   self.rider("rider/b", "B", team="Alpha")]})]
        idx = ERI.build_index(ds)
        self.assertEqual(idx["teams"], ["Alpha", "Zeta"])
        self.assertEqual(idx["riders"]["a"]["y"]["2020"][1], 1)   # Zeta
        self.assertEqual(idx["riders"]["b"]["y"]["2020"][1], 0)   # Alpha

    def test_missing_team_is_minus_one(self):
        idx = ERI.build_index([("2020", {"riders": [self.rider("rider/a", "A")]})])
        self.assertEqual(idx["riders"]["a"]["y"]["2020"], [1, -1])

    def test_short_form_when_no_sprint_or_kom_rank(self):
        idx = ERI.build_index([("2020", {"riders": [self.rider("rider/a", "A")]})])
        self.assertEqual(len(idx["riders"]["a"]["y"]["2020"]), 2)

    def test_long_form_when_a_ranking_exists(self):
        r = self.rider("rider/a", "A", by_stage=[{"stage": 1, "sprintRank": 4}])
        idx = ERI.build_index([("2020", {"riders": [r]})])
        self.assertEqual(idx["riders"]["a"]["y"]["2020"], [1, -1, 4, 0])

    def test_only_the_last_stage_supplies_the_rankings(self):
        r = self.rider("rider/a", "A", by_stage=[{"stage": 1, "sprintRank": 9},
                                                 {"stage": 2, "komRank": 3}])
        idx = ERI.build_index([("2020", {"riders": [r]})])
        self.assertEqual(idx["riders"]["a"]["y"]["2020"], [1, -1, 0, 3])

    def test_rider_spans_multiple_years(self):
        ds = [("2019", {"riders": [self.rider("rider/a", "A", final=5)]}),
              ("2020", {"riders": [self.rider("rider/a", "A", final=2)]})]
        idx = ERI.build_index(ds)
        self.assertEqual(sorted(idx["riders"]["a"]["y"]), ["2019", "2020"])
        self.assertEqual(idx["riders"]["a"]["y"]["2020"][0], 2)

    def test_youth_winner_years_attached(self):
        ds = [("2020", {"riders": [self.rider("rider/a", "A")]})]
        idx = ERI.build_index(ds, {"rider/a": [1984, 1989]})
        self.assertEqual(idx["riders"]["a"]["yw"], [1984, 1989])
        idx2 = ERI.build_index(ds)
        self.assertNotIn("yw", idx2["riders"]["a"], "omitted when never won")

    def test_first_and_last_name_recorded_once(self):
        ds = [("2019", {"riders": [self.rider("rider/a", "A", firstName="Ada", lastName="Zed")]}),
              ("2020", {"riders": [self.rider("rider/a", "A", firstName="CHANGED")]})]
        idx = ERI.build_index(ds)
        self.assertEqual(idx["riders"]["a"]["fn"], "Ada")
        self.assertEqual(idx["riders"]["a"]["ln"], "Zed")

    def test_rider_prefix_stripped(self):
        idx = ERI.build_index([("2020", {"riders": [self.rider("rider/eddy-merckx", "M")]})])
        self.assertIn("eddy-merckx", idx["riders"])

    def test_empty_input(self):
        self.assertEqual(ERI.build_index([]), {"teams": [], "riders": {}})

    # Official standings beat the derived cumulative-points order — the 1969
    # green jersey was Merckx's, not the rider who led on points when he
    # abandoned, and the 2008 KOM title is Sastre's after Kohl's DQ.
    def test_official_standings_override_derived_ranks(self):
        r = self.rider("rider/a", "A", by_stage=[{"stage": 1, "sprintRank": 2, "komRank": 5}])
        idx = ERI.build_index(
            [("2020", {"riders": [r]})],
            final_ranks={"points": {("2020", "rider/a"): 1}, "kom": {("2020", "rider/a"): 3}},
            ranked_years={"points": {"2020"}, "kom": {"2020"}},
        )
        self.assertEqual(idx["riders"]["a"]["y"]["2020"], [1, -1, 1, 3])

    def test_rider_absent_from_official_standings_is_unranked(self):
        r = self.rider("rider/a", "A", by_stage=[{"stage": 1, "sprintRank": 1}])
        idx = ERI.build_index(
            [("2020", {"riders": [r]})],
            final_ranks={"points": {}, "kom": {}},
            ranked_years={"points": {"2020"}, "kom": {"2020"}},
        )
        self.assertEqual(idx["riders"]["a"]["y"]["2020"], [1, -1],
                         "an unclassified rider keeps no derived rank")

    def test_derived_ranks_kept_for_years_the_db_does_not_cover(self):
        r = self.rider("rider/a", "A", by_stage=[{"stage": 1, "sprintRank": 2}])
        idx = ERI.build_index(
            [("1930", {"riders": [r]})],
            final_ranks={"points": {("2020", "rider/a"): 1}, "kom": {}},
            ranked_years={"points": {"2020"}, "kom": {"2020"}},
        )
        self.assertEqual(idx["riders"]["a"]["y"]["1930"], [1, -1, 2, 0])


class TestDistanceBaseline(unittest.TestCase):
    """
    export_race_summary.report_distance_divergences — the Giro/Vuelta distance
    reconciliation, shared with the TDF exporter.

    19 of 189 Giro+Vuelta editions disagree with Wikipedia by >3% for reasons
    that are not defects. Reporting all 19 on every run makes the warning
    unreadable and means --strict can never pass, so the baseline is what makes
    the check usable at all: only a NEW divergence is allowed to surface.
    """

    DIV = {"year": 1926, "wiki_km": 3249.7, "db_km": 3425.0, "pct": 5.4, "stages": 12}

    def report(self, divergences, accepted, strict=False, have_source=True):
        import io
        buf, sys.stdout = sys.stdout, io.StringIO()
        try:
            new = ERS.report_distance_divergences(
                divergences, accepted, 3.0, have_source, "giro", strict)
        finally:
            self.output = sys.stdout.getvalue()
            sys.stdout = buf
        return new

    def test_unlisted_divergence_is_reported_as_new(self):
        self.assertTrue(self.report([self.DIV], {}))
        self.assertIn("WARNING", self.output)
        self.assertIn("1926", self.output)

    def test_baselined_divergence_is_not_new(self):
        self.assertFalse(self.report([self.DIV], {"1926": "investigated"}))
        self.assertNotIn("WARNING", self.output)
        self.assertIn("already-investigated", self.output)

    def test_baseline_hides_only_the_listed_year(self):
        other = dict(self.DIV, year=1949)
        self.assertTrue(self.report([self.DIV, other], {"1926": "investigated"}))
        self.assertIn("1949", self.output)
        # The baselined year must not reappear in the NEW table.
        table = self.output[self.output.index("WARNING"):]
        self.assertNotIn("1926", table)

    def test_strict_exits_on_a_new_divergence(self):
        with self.assertRaises(SystemExit) as cm:
            self.report([self.DIV], {}, strict=True)
        self.assertEqual(cm.exception.code, 1)

    def test_strict_passes_when_every_divergence_is_baselined(self):
        self.report([self.DIV], {"1926": "investigated"}, strict=True)  # must not raise

    def test_missing_distance_file_says_how_to_build_it(self):
        self.assertFalse(self.report([], {}, have_source=False))
        self.assertIn("scrape_wiki_distances.py", self.output)

    def test_shipped_baseline_is_well_formed(self):
        """Every entry needs a real reason — an empty note silences a year
        without recording why, which is the failure this file exists to fix."""
        path = os.path.join(HERE, "distance_divergence_baseline.json")
        with open(path, encoding="utf-8") as f:
            baseline = json.load(f)
        self.assertEqual(set(baseline), {"tour", "giro", "vuelta"})
        for race, years in baseline.items():
            for year, reason in years.items():
                self.assertRegex(year, r"^(19|20)\d\d$", f"{race} {year}")
                self.assertGreater(len(reason), 20, f"{race} {year} needs a real reason")

    def test_every_race_loads_its_own_slice(self):
        self.assertNotEqual(ERS.load_distance_baseline("giro"),
                            ERS.load_distance_baseline("vuelta"))
        self.assertEqual(ERS.load_distance_baseline("nonexistent-race"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
