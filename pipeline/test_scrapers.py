#!/usr/bin/env python3
"""
Scraper tests against recorded PCS pages — no network.

Run:  python3 -m unittest test_scrapers -v
      python3 record_fixtures.py        # to (re)record the pages

The scrapers were the pipeline's largest untested block, and the reason is that
each begins with a network fetch. But the fetch is not the interesting part —
the parsing is, and parsing is where the failures are silent: a regex that stops
matching returns None, which becomes a NULL column and a blank chart rather than
an error. Every fixture here is a real page recorded verbatim (see
record_fixtures.FIXTURES for why each was chosen).

These tests deliberately assert on values that can be checked against the real
world — Roglič won Vuelta 2021 stage 1, Sobrero won the 2022 Giro's closing
Verona time trial — so a passing test means the parser extracted the truth, not
merely something self-consistent.

When PCS changes its markup these will fail. That is the point: today the only
signal is a column quietly going NULL months later.
"""

import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import insert_cancelled_stages as ICS
import patch_missing_distances as PMD
import resolve_source_slugs as RSS
import scrape_vuelta as SV
import scrape_vuelta_stage_info as SVSI
from race_common import STAGE_ROW_LEN, StageRow
from record_fixtures import FIXTURES, load, path_for


def require(name):
    if not os.path.exists(path_for(name)):
        raise unittest.SkipTest(
            f"fixture {name!r} not recorded — run: python3 record_fixtures.py")
    return load(name)


class TestFixtures(unittest.TestCase):
    def test_all_fixtures_present(self):
        missing = [n for n in FIXTURES if not os.path.exists(path_for(n))]
        self.assertEqual(missing, [], "run: python3 record_fixtures.py")


class TestParseInfo(unittest.TestCase):
    """scrape_vuelta.parse_info — the stage metadata block."""

    def test_modern_stage(self):
        info = SV.parse_info(require("vuelta_2021_stage_1"))
        self.assertEqual(info["Date"], "2021-08-14")       # normalised to ISO
        self.assertEqual(info["Distance"], "7.1 km")
        self.assertEqual(info["Start"], "Burgos")          # PCS calls it Departure
        self.assertEqual(info["Finish"], "Burgos")         # ...and Arrival
        self.assertEqual(info["Vertical meters"], "87")

    def test_historical_stage_with_accented_place(self):
        info = SV.parse_info(require("tdf_1986_stage_8"))
        self.assertEqual(info["Date"], "1986-07-11")
        self.assertEqual(info["Start"], "Saint Hilaire du Harcouët")
        self.assertEqual(info["Finish"], "Nantes")

    def test_cancelled_stage_still_has_metadata(self):
        """A cancelled stage keeps date/route/elevation — only results are
        absent. That is what makes it recoverable as a placeholder row."""
        info = SV.parse_info(require("vuelta_1991_stage_11_cancelled"))
        self.assertEqual(info["Date"], "1991-05-09")
        self.assertEqual(info["Start"], "Andorra")
        self.assertEqual(info["Finish"], "Pla de Beret")
        self.assertEqual(info["Vertical meters"], "3015")

    def test_zero_distance_info_row_is_healed_from_the_headline(self):
        """PCS's 'Distance:' row says 0 km for this stage even though it was
        raced. parse_info now falls back to the headline, which carries the
        real 17.4 km — before that, such stages landed in the DB with no
        distance and dragged their edition's total down by a whole stage."""
        html = require("giro_2022_stage_21")
        self.assertRegex(html, r"Distance:.{0,200}?0\s*km",
                         "fixture must still be one where the info row reads 0 km")
        info = SV.parse_info(html)
        self.assertEqual(info["Distance"], "17.4 km")
        self.assertEqual(info["DistanceSource"], "pcs-title")

    def test_headline_marks_the_stage_a_time_trial(self):
        """"Won how" is empty here, so the (ITT) marker is the only evidence
        that this is a time trial rather than a flat road stage."""
        info = SV.parse_info(require("giro_2022_stage_21"))
        self.assertEqual(info.get("TitleTT"), "ITT")


class TestProfileIcon(unittest.TestCase):
    def test_icons_parse_to_known_codes(self):
        for name in ("vuelta_2021_stage_1", "tdf_1986_stage_8", "tdf_1986_prologue"):
            icon = SV.parse_profile_icon(require(name))
            self.assertRegex(icon, r"^p[1-5]$", name)

    def test_hilly_stage_detected(self):
        self.assertEqual(SV.parse_profile_icon(require("vuelta_2021_stage_1")), "p2")


class TestResultsTable(unittest.TestCase):
    """find_results_table + parse_rows — the core extraction."""

    def test_modern_results(self):
        html = require("vuelta_2021_stage_1")
        rows = SV.parse_rows(SV.find_results_table(html))
        self.assertEqual(len(rows), 184)
        first = StageRow.from_list(rows[0])
        self.assertEqual(first.rnk, "1")
        self.assertEqual(first.name, "Roglič Primož")
        self.assertEqual(first.slug, "rider/primoz-roglic")
        self.assertEqual(first.nat, "si")

    def test_every_row_has_exactly_the_schema_width(self):
        """StageRow rejects any other width, and ingest drops such rows — so a
        parser that emits a short row silently loses a rider's result."""
        for name in ("vuelta_2021_stage_1", "tdf_1986_stage_8",
                     "tdf_1986_prologue", "giro_2022_stage_21"):
            table = SV.find_results_table(require(name))
            for i, row in enumerate(SV.parse_rows(table)):
                self.assertEqual(len(row), STAGE_ROW_LEN, f"{name} row {i}")
                StageRow.from_list(row)          # must not raise

    def test_winner_of_the_2022_giro_closing_time_trial(self):
        rows = SV.parse_rows(SV.find_results_table(require("giro_2022_stage_21")))
        self.assertEqual(StageRow.from_list(rows[0]).slug, "rider/matteo-sobrero")

    def test_cancelled_stage_yields_no_rows(self):
        """scrape_stage must return None for these, not an empty stage — an
        empty stage would land in the DB as a raced stage with no finishers."""
        html = require("vuelta_1991_stage_11_cancelled")
        self.assertEqual(SV.parse_rows(SV.find_results_table(html) or ""), [])

    def test_sparse_historical_page(self):
        """The ordinary row parser finds exactly ONE row on this page — and
        that is the bug, not the truth. It is a team time trial: the results
        are grouped by team, and the single stray row makes the stage look
        populated. TestTeamTimeTrial covers what parse_ttt_rows recovers."""
        rows = SV.parse_rows(SV.find_results_table(require("vuelta_1989_stage_3a")))
        self.assertEqual(len(rows), 1)
        self.assertEqual(StageRow.from_list(rows[0]).slug, "rider/roland-leclerc")

    def test_bibs_are_unique_within_a_stage(self):
        """A bib appearing twice is the upstream collision the swap detector
        has to distinguish from a name swap."""
        rows = SV.parse_rows(SV.find_results_table(require("vuelta_2021_stage_1")))
        bibs = [StageRow.from_list(r).bib for r in rows if StageRow.from_list(r).bib]
        self.assertEqual(len(bibs), len(set(bibs)))


class TestTeamTimeTrial(unittest.TestCase):
    """parse_ttt_rows — results grouped by team, not one row per rider.

    A TTT page carries no per-rider time: each rider takes the team's time and
    the team's placing. find_results_table/parse_rows find essentially nothing
    in this shape, and the single stray row they DO return looks like a valid
    result, so the stage lands in the DB looking populated. 47 stages and
    roughly 3,568 results were lost that way.
    """

    def test_historical_ttt_full_field(self):
        rows = SV.parse_ttt_rows(require("vuelta_1989_stage_3a"))
        self.assertEqual(len(rows), 188)
        self.assertEqual(len({StageRow.from_list(r).team for r in rows}), 21)

    def test_modern_ttt_full_field(self):
        rows = SV.parse_ttt_rows(require("vuelta_2015_stage_1_ttt"))
        self.assertEqual(len(rows), 198)
        self.assertEqual(len({StageRow.from_list(r).team for r in rows}), 22)

    def test_ordinary_parser_finds_almost_nothing_here(self):
        """The regression that hid this: one stray row, not zero, so nothing
        downstream looked wrong."""
        html = require("vuelta_1989_stage_3a")
        self.assertEqual(len(SV.parse_rows(SV.find_results_table(html) or "")), 1)
        self.assertEqual(len(SV.parse_ttt_rows(html)), 188)

    def test_winning_team_matches_the_published_result(self):
        """Vuelta 1989 stage 3a: Caja Rural 42:49, Reynolds-Banesto +0:02."""
        rows = [StageRow.from_list(r) for r in SV.parse_ttt_rows(require("vuelta_1989_stage_3a"))]
        win = [r for r in rows if r.rnk == "1"]
        self.assertEqual({r.team for r in win}, {"Caja Rural"})
        self.assertEqual({r.abs_time for r in win}, {"42:49"})
        self.assertEqual({r.gap for r in win}, {"0:00"})
        self.assertIn("rider/marino-lejarreta", {r.slug for r in win})

    def test_every_rider_takes_the_team_time_and_placing(self):
        rows = [StageRow.from_list(r) for r in SV.parse_ttt_rows(require("vuelta_1989_stage_3a"))]
        banesto = [r for r in rows if r.team == "Reynolds - Banesto"]
        self.assertEqual(len(banesto), 9)
        self.assertEqual({r.rnk for r in banesto}, {"2"})
        self.assertEqual({r.abs_time for r in banesto}, {"42:51"})
        self.assertEqual({r.gap for r in banesto}, {"0:02"})
        self.assertIn("rider/pedro-delgado", {r.slug for r in banesto})
        self.assertIn("rider/miguel-indurain", {r.slug for r in banesto})

    def test_rows_match_the_stage_row_schema(self):
        for name in ("vuelta_1989_stage_3a", "vuelta_2015_stage_1_ttt"):
            for row in SV.parse_ttt_rows(require(name)):
                self.assertEqual(len(row), STAGE_ROW_LEN, name)
                StageRow.from_list(row)

    def test_returns_nothing_for_a_non_ttt_page(self):
        for name in ("vuelta_2021_stage_1", "tdf_1986_stage_8", "giro_2022_stage_21"):
            self.assertEqual(SV.parse_ttt_rows(require(name)), [], name)

    def test_scrape_stage_flags_a_ttt(self):
        """route_type must come from the page, not from 'Won how' — which reads
        a plain 'Time trial' here and had this stage classified TT."""
        orig, SV.DELAY = SV.fetch, 0
        SV.fetch = lambda url, **kw: (None if url.endswith(("-points", "-kom"))
                                      else load("vuelta_1989_stage_3a"))
        try:
            buf, sys.stdout = sys.stdout, io.StringIO()
            try:
                rec = SV.scrape_stage(1989, "stage-3a", 3)
            finally:
                sys.stdout = buf
        finally:
            SV.fetch = orig
        self.assertTrue(rec["is_ttt"])
        self.assertEqual(len(rec["rows"]), 188)
        self.assertEqual(SV.parse_info(require("vuelta_1989_stage_3a"))["Won how"],
                         "Time trial")   # why the heuristic alone is not enough


class TestPointsPage(unittest.TestCase):
    def test_sprint_points(self):
        pts = SV.parse_points_page(require("vuelta_2021_stage_1_points"), "sprint")
        self.assertEqual(pts["rider/primoz-roglic"], 20)
        self.assertTrue(all(v > 0 for v in pts.values()), "zero-point riders are dropped")
        self.assertTrue(all(k.startswith("rider/") for k in pts))


class TestElevationExtraction(unittest.TestCase):
    """scrape_*_stage_info.extract_info — vertical metres + ProfileScore."""

    def test_reads_both_values(self):
        self.assertEqual(SVSI.extract_info(require("vuelta_2021_stage_1")),
                         {"vertical_meters": 87, "profile_score": 9})

    def test_lettered_split_slug_carries_its_own_elevation(self):
        """stage-3a resolves to a real page with its own figures — the basis of
        the Vuelta 1989 repair. Fetching 'stage-3' instead 500s."""
        self.assertEqual(SVSI.extract_info(require("vuelta_1989_stage_3a")),
                         {"vertical_meters": 564, "profile_score": 36})

    def test_absent_elevation_is_none_not_zero(self):
        """PCS has no figures for this stage. None means 'unknown'; 0 would be
        a claim that the stage was flat."""
        self.assertEqual(SVSI.extract_info(require("giro_2022_stage_21")),
                         {"vertical_meters": None, "profile_score": None})

    def test_thousands_separator_is_stripped(self):
        """Synthetic, not from a fixture: the regex accepts '3,015' but PCS has
        never been observed to render it that way — every recorded page uses
        bare digits, including four-digit values. Pinning the intent so the
        branch is not mistaken for dead code and deleted, while being explicit
        that no real page exercises it."""
        html = ('<div>Vertical meters: </div><div class="value">3,015</div>'
                '<div>ProfileScore: </div><div class="value">213</div>')
        self.assertEqual(SVSI.extract_info(html),
                         {"vertical_meters": 3015, "profile_score": 213})

    def test_cancelled_stage_still_reports_planned_elevation(self):
        self.assertEqual(
            SVSI.extract_info(require("vuelta_1991_stage_11_cancelled"))["vertical_meters"],
            3015)


class TestHeaderDistance(unittest.TestCase):
    """patch_missing_distances.parse_distance — the page header."""

    def test_header_carries_a_distance_the_info_row_reports_as_zero(self):
        """The whole reason the patcher exists: PCS's info row reads 0 km while
        the headline carries the real 17.4 km."""
        html = require("giro_2022_stage_21")
        self.assertRegex(html, r"Distance:.{0,200}?0\s*km")
        self.assertEqual(PMD.parse_distance(html), 17.4)

    def test_distance_is_read_from_the_headline_not_anywhere_on_the_page(self):
        """A bare '(NNkm)' search matches whatever parenthesised distance comes
        first in the markup, which need not be this stage's. Scoping to the
        headline block is what makes the value trustworthy."""
        html = require("giro_2022_stage_21")
        decoy = '<p>see also the previous stage (246.5km)</p>'
        self.assertEqual(PMD.parse_distance(decoy + html), 17.4)

    def test_header_matches_the_info_row_when_both_are_present(self):
        html = require("tdf_1986_stage_8")
        self.assertEqual(PMD.parse_distance(html), 204.0)
        self.assertEqual(SV.parse_info(html)["Distance"], "204 km")

    def test_decimal_distance(self):
        self.assertEqual(PMD.parse_distance(require("vuelta_2021_stage_1")), 7.1)


class TestCancellationDetection(unittest.TestCase):
    """insert_cancelled_stages.parse_meta — never invent a raced stage."""

    def test_cancelled_page_detected_with_full_metadata(self):
        meta = ICS.parse_meta(require("vuelta_1991_stage_11_cancelled"))
        self.assertTrue(meta["cancelled"])
        self.assertEqual(meta["date"], "1991-05-09")
        self.assertEqual(meta["start"], "Andorra")
        self.assertEqual(meta["finish"], "Pla de Beret")

    def test_raced_stages_are_not_flagged(self):
        for name in ("vuelta_2021_stage_1", "tdf_1986_stage_8",
                     "giro_2022_stage_21", "vuelta_1989_stage_3a"):
            self.assertFalse(ICS.parse_meta(require(name))["cancelled"], name)


class TestRouteParsing(unittest.TestCase):
    """resolve_source_slugs.page_route — how every corrected slug was verified."""

    def test_route_matches_the_info_block(self):
        for name in ("vuelta_2021_stage_1", "tdf_1986_stage_8",
                     "vuelta_1991_stage_11_cancelled"):
            html = require(name)
            info = SV.parse_info(html)
            self.assertEqual(RSS.page_route(html), (info["Start"], info["Finish"]), name)

    def test_the_route_that_disproved_the_slug_convention(self):
        """PCS stage-8 of the 1986 Tour is Saint Hilaire -> Nantes, which the DB
        holds as stage_number 8. The derived slug said stage-7. That mismatch is
        what showed PCS numbers this edition's split day sequentially."""
        self.assertEqual(RSS.page_route(require("tdf_1986_stage_8")),
                         ("Saint Hilaire du Harcouët", "Nantes"))

    def test_accent_insensitive_comparison(self):
        """Place names differ in accents between sources, so the verifier
        normalises before comparing — otherwise every accented route 'fails'."""
        self.assertEqual(RSS.norm("Saint Hilaire du Harcouët"),
                         RSS.norm("saint-hilaire du harcouet"))
        self.assertNotEqual(RSS.norm("Nantes"), RSS.norm("Nancy"))


class TestScrapeStageEndToEnd(unittest.TestCase):
    """scrape_vuelta.scrape_stage with fetch served from fixtures."""

    def setUp(self):
        self._fetch = SV.fetch
        self._delay = SV.DELAY
        SV.DELAY = 0

        def fake_fetch(url, **kw):
            if url.endswith("-points"):
                return load("vuelta_2021_stage_1_points")
            if url.endswith("-kom"):
                return None                      # no KOM page for this stage
            return load("vuelta_2021_stage_1")

        SV.fetch = fake_fetch

    def tearDown(self):
        SV.fetch, SV.DELAY = self._fetch, self._delay

    def test_builds_a_complete_stage_record(self):
        rec = SV.scrape_stage(2021, "stage-1", 1)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["n"], 1)
        self.assertEqual(rec["slug"], "stage-1")     # provenance, not derivable from n
        self.assertEqual(len(rec["rows"]), 184)
        self.assertEqual(rec["info"]["Start"], "Burgos")
        self.assertEqual(rec["profile_icon"], "p2")
        self.assertGreater(len(rec["sprint_points"]), 0)
        self.assertEqual(rec["kom_points"], {})      # missing page -> empty, not an error

    def test_returns_none_when_the_page_has_no_results(self):
        SV.fetch = lambda url, **kw: load("vuelta_1991_stage_11_cancelled")
        self.assertIsNone(self._quiet(SV.scrape_stage, 1991, "stage-11", 12))

    def test_returns_none_when_the_fetch_fails(self):
        SV.fetch = lambda url, **kw: None
        self.assertIsNone(self._quiet(SV.scrape_stage, 2021, "stage-1", 1))

    @staticmethod
    def _quiet(fn, *a):
        """scrape_stage prints its progress; keep it out of the test report."""
        buf, sys.stdout = sys.stdout, io.StringIO()
        try:
            return fn(*a)
        finally:
            sys.stdout = buf


if __name__ == "__main__":
    unittest.main(verbosity=2)
