#!/usr/bin/env python3
"""
Tests for coverage.py — the "what is missing" report.

A coverage report is only useful if its denominators are honest. Every test
below is a case where a naive COUNT would have reported a gap that does not
exist, and buried the real ones underneath it.

Run:  python3 -m unittest test_coverage -v
"""

import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import coverage


class CoverageTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
            self.conn.executescript(f.read())
        self.cur = self.conn.cursor()
        for slug in ("r/a", "r/b"):
            self.cur.execute("INSERT INTO riders (rider_id, full_name) VALUES (?,?)",
                             (slug, slug))

    def tearDown(self):
        self.conn.close()

    def race(self, name, race_type="stage_race"):
        self.cur.execute("INSERT INTO races (name, race_type) VALUES (?,?)",
                         (name, race_type))
        return self.cur.lastrowid

    def edition(self, race_id, year):
        self.cur.execute("INSERT INTO race_editions (race_id, year) VALUES (?,?)",
                         (race_id, year))
        return self.cur.lastrowid

    def stage(self, edition_id, number, cancelled=0, **fields):
        cols = ["edition_id", "stage_number", "cancelled"] + list(fields)
        vals = [edition_id, number, cancelled] + list(fields.values())
        self.cur.execute(
            f"INSERT INTO stages ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))})", vals)
        return self.cur.lastrowid

    def sourced(self, stage_id, source):
        """Record which upstream supplied a stage, as every ingest does."""
        self.cur.execute(
            "INSERT INTO data_provenance (entity, entity_id, field, source, "
            "recorded_at) VALUES ('stages', ?, 'source_slug', ?, '2026-09-09')",
            (stage_id, source))

    def result(self, stage_id, status="FINISHED", rider="r/a", **fields):
        cols = ["stage_id", "rider_id", "status"] + list(fields)
        vals = [stage_id, rider, status] + list(fields.values())
        self.cur.execute(
            f"INSERT INTO stage_results ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))})", vals)

    def rows_for(self, race=None):
        return coverage.collect(self.cur, coverage.race_scope(self.cur, race))

    # ── denominators ─────────────────────────────────────────────────────────

    def test_a_cancelled_stage_is_not_a_gap(self):
        """It was never raced, so a NULL distance is the correct value. Counting
        it leaves an affected year permanently short of complete — the same rule
        the race totals use."""
        rid = self.race("Tour de France")
        eid = self.edition(rid, 1971)
        self.stage(eid, 1, distance_km=100.0)
        self.stage(eid, 2, cancelled=1)
        row = self.rows_for()[("Tour de France", 1971)]
        self.assertEqual((row["stages"], row["cancelled"]), (1, 1))
        self.assertEqual(coverage.denominator(row, "distance_km"), 1)
        self.assertEqual(coverage.gaps(self.rows_for(), "distance_km"), [])

    def test_a_DNF_has_no_finishing_time_to_be_missing(self):
        """The largest source of noise before it was split out: counting the
        whole startlist reported ~60% missing on years that are complete."""
        rid = self.race("Tour de France")
        eid = self.edition(rid, 1971)
        sid = self.stage(eid, 1, distance_km=100.0, route_type="F",
                         profile_score=1, source_slug="stage-1",
                         stage_date="1971-06-26", vertical_meters=10)
        self.result(sid, finish_time_seconds=3600, gc_rank=1, team_id=None)
        self.result(sid, status="DNF", rider="r/b")
        row = self.rows_for()[("Tour de France", 1971)]
        self.assertEqual((row["results"], row["finishers"]), (2, 1))
        self.assertEqual(coverage.denominator(row, "finish_time_seconds"), 1)
        self.assertEqual([g[3] for g in coverage.gaps(self.rows_for())], ["team_id"])

    def test_a_field_the_upstream_cannot_supply_is_not_reported(self):
        """Athlinks is a timing platform: it publishes a finish list, not a
        parcours, and records no trade team. For an edition it timed, those
        columns have nothing to scrape from and a NULL is the end state."""
        rid = self.race("Unbound Gravel", "gravel")
        eid = self.edition(rid, 2026)
        sid = self.stage(eid, 1, distance_km=320.0, stage_date="2026-05-30")
        self.sourced(sid, "athlinks")
        self.assertEqual(coverage.gaps(self.rows_for()), [])

    def test_the_same_gravel_fields_ARE_reported_when_PCS_covered_it(self):
        """The exclusion is per UPSTREAM, not per race type — this is the bug
        the whole per-stage denominator exists to prevent. PCS files gravel
        under national-race/ and publishes all three there: The Traka 2026
        carries "Vertical meters: 4198", "ProfileScore: 125", and a named team
        for 29 of its 141 riders. Excluding the whole gravel set on the theory
        that PCS has no gravel coverage hid ~325 fillable values."""
        rid = self.race("The Traka 360", "gravel")
        eid = self.edition(rid, 2026)
        sid = self.stage(eid, 1, distance_km=325.0, stage_date="2026-05-01")
        self.sourced(sid, "pcs")
        self.result(sid, finish_time_seconds=35000, team_id=None)
        found = {g[3] for g in coverage.gaps(self.rows_for())}
        self.assertEqual(found, {"vertical_meters", "profile_score", "team_id"})

    def test_one_year_of_a_set_can_mix_upstreams(self):
        """Why the denominator is counted per stage and not per race-year: 2025
        holds The Traka, which PCS covers, beside Big Sugar, which it does not.
        Only the Traka's riders could have had a team recorded, so a shared
        denominator would report Big Sugar's as missing forever."""
        traka = self.stage(self.edition(self.race("The Traka 360", "gravel"), 2025),
                           1, distance_km=360.0, stage_date="2025-05-02")
        self.sourced(traka, "pcs")
        self.cur.execute("INSERT INTO teams (team_id, name) VALUES ('t/x','X')")
        self.result(traka, team_id="t/x")
        big = self.stage(self.edition(self.race("Big Sugar Gravel", "gravel"), 2025),
                         1, distance_km=160.0, stage_date="2025-10-25")
        self.sourced(big, "athlinks")
        self.result(big, rider="r/b")
        row = self.rows_for()[("gravel", 2025)]
        self.assertEqual(row["results"], 2)
        self.assertEqual(coverage.denominator(row, "team_id"), 1)
        self.assertEqual(coverage.denominator(row, "vertical_meters"), 1)

    def test_a_classic_profile_score_is_a_real_gap(self):
        """The other half of the same mistake. PCS does classify a one-day race
        and ingest_classics.py has been storing it all along — 295 of 963
        classic stages carry one — but the field was excluded on the theory
        that a one-day race has no profile. That hid 668 fillable values."""
        rid = self.race("Paris-Roubaix", "one_day")
        sid = self.stage(self.edition(rid, 2026), 1, distance_km=259.0,
                         stage_date="2026-04-12")
        self.sourced(sid, "pcs")
        self.assertIn("profile_score", {g[3] for g in coverage.gaps(self.rows_for())})

    def test_a_computed_field_is_never_a_scrape_target(self):
        """route_type is derived from profile_score for a classic, so it fills
        exactly when profile_score does; listing it too would double-count the
        same afternoon's work."""
        rid = self.race("Paris-Roubaix", "one_day")
        sid = self.stage(self.edition(rid, 2026), 1, distance_km=259.0,
                         stage_date="2026-04-12")
        self.sourced(sid, "pcs")
        self.assertNotIn("route_type", {g[3] for g in coverage.gaps(self.rows_for())})

    def test_a_one_stage_race_has_no_classification_to_be_missing(self):
        """gc_rank is structural, not a sourcing question: there is no general
        classification in a race of one stage, whoever covered it."""
        rid = self.race("The Traka 360", "gravel")
        sid = self.stage(self.edition(rid, 2026), 1, distance_km=325.0,
                         stage_date="2026-05-01")
        self.sourced(sid, "pcs")
        self.result(sid, finish_time_seconds=35000, gc_rank=None)
        self.assertNotIn("gc_rank", {g[3] for g in coverage.gaps(self.rows_for())})

    def test_an_unrecognised_upstream_is_exempted_from_nothing(self):
        """The fail-safe direction. This report's failure mode must be showing
        work that turns out to be impossible, never hiding work that is
        possible — that is the bug being fixed here."""
        rid = self.race("Unbound Gravel", "gravel")
        sid = self.stage(self.edition(rid, 2026), 1, distance_km=320.0,
                         stage_date="2026-05-30")
        self.sourced(sid, "some-new-timer")
        found = {g[3] for g in coverage.gaps(self.rows_for())}
        self.assertIn("vertical_meters", found)

    def test_the_same_field_IS_reported_for_a_race_that_has_a_source(self):
        """The exclusion has to be per race type and per upstream, never
        global, or the report goes quiet about the gaps it exists to find."""
        rid = self.race("Tour de France")
        self.stage(self.edition(rid, 1971), 1, distance_km=100.0)
        found = {g[3] for g in coverage.gaps(self.rows_for())}
        self.assertIn("vertical_meters", found)
        self.assertNotIn("distance_km", found)

    # ── grouping and ranking ─────────────────────────────────────────────────

    def test_the_one_day_races_are_grouped_as_one_set(self):
        """A scrape session is 'the 1953 classics', not one race at a time, so
        that is the unit the report ranks."""
        for name in ("Paris-Roubaix", "Milan-San Remo"):
            rid = self.race(name, "one_day")
            self.stage(self.edition(rid, 1953), 1, distance_km=250.0)
        rows = self.rows_for()
        self.assertEqual(list(rows), [("one_day", 1953)])
        self.assertEqual(rows[("one_day", 1953)]["stages"], 2)

    def test_gaps_rank_by_values_missing_not_by_percentage(self):
        """A year at 40% of 180 values is a bigger afternoon's work than one at
        0% of 3, and the list exists to say what to do next."""
        rid = self.race("Tour de France")
        big = self.edition(rid, 1971)
        for n in range(1, 21):
            self.stage(big, n, distance_km=100.0)          # 20 missing elevation
        small = self.edition(rid, 1972)
        self.stage(small, 1, distance_km=100.0)            # 1 missing elevation
        ranked = [(g[1], g[2], g[3]) for g in coverage.gaps(self.rows_for(),
                                                            "vertical_meters")]
        self.assertEqual(ranked[0], ("Tour de France", 1971, "vertical_meters"))

    def test_a_race_year_with_no_stages_is_skipped_not_divided_by_zero(self):
        """An edition row can exist before anything is scraped into it."""
        rid = self.race("Tour de France")
        self.edition(rid, 2027)
        self.assertEqual(coverage.gaps(self.rows_for()), [])


if __name__ == "__main__":
    unittest.main()
