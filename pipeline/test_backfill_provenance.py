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
