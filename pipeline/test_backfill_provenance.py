#!/usr/bin/env python3
"""
Tests for the one-day-race branch of backfill_provenance.py.

The incident: the script was written when the DB held only the Tour, Giro and
Vuelta, and its SCRAPE_DIRS names only the two per-stage ones. Every one of the
18 one-day races added later therefore fell through to the 'unknown' branch, so
a run would have marked 1,063 stages "origin unproven" while the file proving
them sat in classics_scrapes/ or gravel_scrapes/. 'unknown' is a to-do list, so
that is ~1,000 phantom to-dos hiding the 1,861 real ones.

The source cannot be hardcoded to 'pcs' the way the Giro/Vuelta branch does:
the gravel races come from Athlinks, and The Traka changes upstream mid-history.
"""
import json
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backfill_provenance as B
from race_common import CLASSICS, GRAVEL

HERE = os.path.dirname(os.path.abspath(__file__))

SCHEMA = """
CREATE TABLE data_provenance (entity TEXT, entity_id INTEGER, field TEXT, source TEXT,
    source_ref TEXT, script TEXT, recorded_at TEXT, PRIMARY KEY (entity, entity_id, field));
"""


class IngestedOriginTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.cur = self.conn.cursor()
        self.cur.executescript(SCHEMA)

    def prov(self, sid, field, source, ref, script):
        self.cur.execute("INSERT INTO data_provenance VALUES (?,?,?,?,?,?,'t')",
                         ("stages", sid, field, source, ref, script))

    def test_reads_the_source_the_ingest_recorded(self):
        self.prov(1, "distance_km", "pcs", "pcs-url", "ingest_classics.py")
        self.prov(1, "stage_date", "pcs", "pcs-url", "ingest_classics.py")
        self.assertEqual(B.ingested_origin(self.cur, 1), ("pcs", "pcs-url"))

    def test_gravel_is_athlinks_not_pcs(self):
        """The whole reason the source is read back rather than hardcoded."""
        self.prov(2, "distance_km", "athlinks", "athlinks-url", "ingest_gravel.py")
        self.assertEqual(B.ingested_origin(self.cur, 2), ("athlinks", "athlinks-url"))

    def test_a_later_patch_does_not_make_the_origin_ambiguous(self):
        """Milan-San Remo 2013: distance_km was re-sourced from Wikipedia because
        PCS prints 121 km against a 43.577 km/h winner. That patch says nothing
        about where the RESULTS came from, and must not obscure the ingest."""
        self.prov(3, "distance_km", "wikipedia", "wiki-url", "patch_msr.py")
        self.prov(3, "stage_date", "pcs", "pcs-url", "ingest_classics.py")
        self.assertEqual(B.ingested_origin(self.cur, 3), ("pcs", "pcs-url"))

    def test_derived_rows_are_ignored(self):
        """route_type is computed, not fetched — it names no upstream."""
        self.prov(4, "route_type", "derived", "classic_route_type()", "ingest_classics.py")
        self.prov(4, "distance_km", "pcs", "pcs-url", "ingest_classics.py")
        self.assertEqual(B.ingested_origin(self.cur, 4), ("pcs", "pcs-url"))

    def test_genuinely_ambiguous_returns_nothing(self):
        """Two different ingest origins for one stage is not something to guess at."""
        self.prov(5, "distance_km", "pcs", "a", "ingest_classics.py")
        self.prov(5, "stage_date", "athlinks", "b", "ingest_gravel.py")
        self.assertEqual(B.ingested_origin(self.cur, 5), (None, None))

    def test_no_ingest_rows_returns_nothing(self):
        self.assertEqual(B.ingested_origin(self.cur, 99), (None, None))


class OneDayDirsTest(unittest.TestCase):
    def test_every_one_day_race_is_mapped(self):
        """A race added to CLASSICS/GRAVEL without a scrape dir would silently
        go back to being backfilled as 'unknown'."""
        names = {i.name for i in CLASSICS.values()} | {i.name for i in GRAVEL.values()}
        self.assertEqual(names, set(B.ONE_DAY_DIRS))

    def test_mapped_directories_exist(self):
        for name, (d, slug) in B.ONE_DAY_DIRS.items():
            with self.subTest(race=name):
                self.assertTrue(os.path.isdir(os.path.join(HERE, d, slug)),
                                f"{d}/{slug} missing for {name}")

    def test_load_edition_file_finds_a_real_edition(self):
        data, rel = B.load_edition_file("Paris-Roubaix", 1896)
        self.assertIsNotNone(data)
        self.assertEqual(rel, os.path.join("classics_scrapes", "paris-roubaix", "1896.json"))

    def test_load_edition_file_is_quiet_about_a_missing_year(self):
        self.assertEqual(B.load_edition_file("Paris-Roubaix", 1799), (None, None))

    def test_stage_race_is_not_a_one_day_race(self):
        self.assertEqual(B.load_edition_file("Tour de France", 1996), (None, None))


if __name__ == "__main__":
    unittest.main()

class ScrapeDirsTest(unittest.TestCase):
    """The Tour was missing from SCRAPE_DIRS until 2026-09-19.

    A comment said its scrapes "live in tdf_YEAR_full.json and aren't
    per-stage". That stopped being true when convert_tdf_layout.py moved them,
    and the comment outlived the layout: load_stage_file() returned (None, None)
    for every Tour stage, so all 1,570 of them were recorded `unknown` for
    results, distance_km, route_type, source_slug and elevation — on the
    grounds that a file it could not find did not exist.
    """

    def test_every_stage_race_is_mapped(self):
        for name in ("Tour de France", "Giro d'Italia", "Vuelta a España"):
            self.assertIn(name, B.SCRAPE_DIRS)

    def test_the_mapped_directories_hold_per_stage_files(self):
        """The claim the stale comment got wrong, asserted against the disk."""
        for name, d in B.SCRAPE_DIRS.items():
            path = os.path.join(B.HERE, d)
            self.assertTrue(os.path.isdir(path), f"{d} is missing")
            found = any(f.startswith("stage_") and f.endswith(".json")
                        for _root, _dirs, files in os.walk(path) for f in files)
            self.assertTrue(found, f"{name}: {d} holds no stage_*.json files")

    def test_no_tdf_full_year_files_remain(self):
        """If these ever come back the mapping above needs rethinking, so fail
        loudly rather than let both layouts half-exist."""
        import glob
        self.assertEqual(glob.glob(os.path.join(B.HERE, "tdf_*_full.json")), [])


class ScrapeFileNumberTest(unittest.TestCase):
    def test_reads_a_plain_figure(self):
        self.assertEqual(B.scrape_file_number(
            {"info": {"Vertical meters": "1971"}}, "Vertical meters"), 1971)

    def test_reads_a_figure_with_units_and_separators(self):
        self.assertEqual(B.scrape_file_number(
            {"info": {"Distance": "224.5 km"}}, "Distance"), 224.5)
        self.assertEqual(B.scrape_file_number(
            {"info": {"Vertical meters": "1,971"}}, "Vertical meters"), 1971)

    def test_missing_and_empty_are_None(self):
        self.assertIsNone(B.scrape_file_number({"info": {}}, "Vertical meters"))
        self.assertIsNone(B.scrape_file_number(
            {"info": {"Vertical meters": ""}}, "Vertical meters"))
        self.assertIsNone(B.scrape_file_number({}, "Vertical meters"))

    def test_zero_is_a_figure_not_a_missing_value(self):
        """Vuelta 2019 st21's file says 0, which is wrong but is not absent —
        it has to reach the DISAGREES branch, not the no-figure one."""
        self.assertEqual(B.scrape_file_number(
            {"info": {"Vertical meters": "0"}}, "Vertical meters"), 0)


class FileIsThisStageTest(unittest.TestCase):
    """Stage files are named stage_<n>.json, and a stage number is not a stable
    key — a split day makes PCS's slug diverge from ours. A figure is never
    believed on the filename alone."""

    ROW = {"distance_km": 224.5, "stage_date": "1970-06-27"}

    def file(self, **info):
        return {"info": info}

    def test_distance_alone_is_enough(self):
        self.assertTrue(B.file_is_this_stage(
            self.file(Distance="224.5 km"), self.ROW))

    def test_date_alone_is_enough(self):
        """128 stages had their distance re-sourced from Wikipedia or
        bikeraceinfo while the date still pins the file down."""
        self.assertTrue(B.file_is_this_stage(
            self.file(Distance="201 km", Date="1970-06-27"), self.ROW))

    def test_neither_matching_is_rejected(self):
        self.assertFalse(B.file_is_this_stage(
            self.file(Distance="201 km", Date="1970-07-04"), self.ROW))

    def test_an_empty_file_is_rejected(self):
        self.assertFalse(B.file_is_this_stage(self.file(), self.ROW))

    def test_a_row_with_neither_field_cannot_be_gated(self):
        self.assertFalse(B.file_is_this_stage(
            self.file(Distance="224.5 km", Date="1970-06-27"),
            {"distance_km": None, "stage_date": None}))

