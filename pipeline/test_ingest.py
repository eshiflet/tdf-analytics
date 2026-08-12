#!/usr/bin/env python3
"""
Tests for ingest_race.ingest_year — the destructive path.

Run:  python3 -m unittest test_ingest -v

Re-ingesting an edition DELETEs and re-INSERTs it, so anything living only in
the DB (elevation, patched distances, the cancelled flag, provenance) is
destroyed unless explicitly carried across. Three separate silent-wipe bugs
were found here in one day, each of which quietly discarded correct data and
left plausible-looking output behind. Every test below reproduces one.

Uses a real SQLite database built from schema.sql plus scrape files on disk,
because the bugs were in the interaction between the two, not in any single
function — a mock would have reproduced none of them.
"""

import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_race
from race_common import STAGE_ROW_LEN

HERE = os.path.dirname(os.path.abspath(__file__))


def result_row(bib, name, slug, rnk="1", gap=""):
    return [rnk, "", "", bib, "28", name, slug, "it",
            "Team A", "team/a-1990", "", "", "", "", gap]


class IngestHarness(unittest.TestCase):
    RACE = "Vuelta a España"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scrapes = os.path.join(self.tmp, "vuelta_scrapes")
        os.makedirs(os.path.join(self.scrapes, "1990"))

        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
            self.conn.executescript(f.read())
        cur = self.conn.cursor()
        cur.execute("INSERT INTO races (name, country, race_type) VALUES (?,?,?)",
                    (self.RACE, "Spain", "stage_race"))
        self.race_id = cur.lastrowid
        self.conn.commit()
        ingest_race.DRY_RUN = False

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_stage(self, n, *, slug=None, distance="100 km", rows=None,
                    cancelled=False, date=None):
        data = {
            "n": n,
            "info": {"Date": date or f"1990-05-{n:02d}", "Distance": distance,
                     "Start": f"Town{n}", "Finish": f"Town{n+1}", "Won how": ""},
            "profile_icon": "p1",
            "rows": rows if rows is not None else [result_row("1", "Rider A", "rider/a")],
            "sprint_points": {}, "kom_points": {},
        }
        if slug:
            data["slug"] = slug
        if cancelled:
            data["cancelled"] = True
        p = os.path.join(self.scrapes, "1990", f"stage_{n}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return p

    def ingest(self):
        """Run a real ingest, muting its progress output so test failures read
        cleanly. Anything the ingest reports is asserted on via the DB, not
        stdout."""
        files = ingest_race.find_stage_files_for_year(self.scrapes, 1990, False)
        buf, sys.stdout = sys.stdout, io.StringIO()
        try:
            return ingest_race.ingest_year(self.conn, self.race_id, self.RACE,
                                           self.scrapes, 1990, files)
        finally:
            self.last_output = sys.stdout.getvalue()
            sys.stdout = buf

    def stages(self):
        return {r["stage_number"]: r for r in self.conn.execute(
            "SELECT * FROM stages ORDER BY stage_number")}


class TestPreservationAcrossReingest(IngestHarness):

    def test_elevation_survives_reingest(self):
        """Elevation comes from a separate scraper and lives only in the DB."""
        self.write_stage(1)
        self.ingest()
        sid = self.stages()[1]["stage_id"]
        self.conn.execute(
            "UPDATE stages SET vertical_meters=1234, profile_score=56 WHERE stage_id=?", (sid,))
        self.conn.commit()

        self.ingest()
        s = self.stages()[1]
        self.assertEqual((s["vertical_meters"], s["profile_score"]), (1234, 56))

    def test_elevation_survives_when_only_the_db_row_has_a_slug(self):
        """The bug that wiped all of 2010 Vuelta's elevation. Preservation was
        keyed on slug alone; the stored row had one (from the backfill) but the
        incoming file did not, so neither index matched and every value was
        dropped. Both indexes must be populated."""
        self.write_stage(1)                      # file carries NO slug
        self.ingest()
        self.conn.execute("UPDATE stages SET source_slug='stage-1', "
                          "vertical_meters=999, profile_score=42")
        self.conn.commit()

        self.ingest()                            # file still carries no slug
        s = self.stages()[1]
        self.assertEqual(s["vertical_meters"], 999,
                         "elevation must survive when file and row disagree about slugs")
        self.assertEqual(s["profile_score"], 42)

    def test_elevation_follows_the_slug_not_the_number(self):
        """When an edition is renumbered, a number-keyed carry-over re-attaches
        each value to a DIFFERENT stage — corrupting data during the repair
        that motivated the re-ingest."""
        self.write_stage(1, slug="stage-1")
        self.write_stage(2, slug="stage-2")
        self.ingest()
        for n, vm in ((1, 100), (2, 200)):
            self.conn.execute("UPDATE stages SET vertical_meters=? WHERE stage_number=?", (vm, n))
        self.conn.commit()

        # stage-2's data now arrives as stage_number 1 (an edition renumbering)
        os.remove(os.path.join(self.scrapes, "1990", "stage_2.json"))
        self.write_stage(1, slug="stage-2")
        self.ingest()
        self.assertEqual(self.stages()[1]["vertical_meters"], 200,
                         "elevation must follow source_slug, not stage_number")

    def test_patched_distance_survives_a_zero_from_the_scrape(self):
        """PCS reports '0 km' for some historical stages; the real figure is
        patched in from the page header and lives only in the DB. 2010 Vuelta
        stage 21 went 85.0 -> 0.0 on re-ingest."""
        self.write_stage(1, distance="0 km")
        self.ingest()
        self.conn.execute("UPDATE stages SET distance_km=85.0")
        self.conn.commit()

        self.ingest()
        self.assertEqual(self.stages()[1]["distance_km"], 85.0)

    def test_a_real_scraped_distance_still_wins(self):
        """Preservation must not shadow a genuine update."""
        self.write_stage(1, distance="0 km")
        self.ingest()
        self.conn.execute("UPDATE stages SET distance_km=85.0")
        self.conn.commit()

        self.write_stage(1, distance="120.5 km")
        self.ingest()
        self.assertEqual(self.stages()[1]["distance_km"], 120.5)

    def test_cancelled_flag_read_from_the_stage_file(self):
        self.write_stage(1, rows=[], cancelled=True)
        self.ingest()
        self.assertEqual(self.stages()[1]["cancelled"], 1)

    def test_cancelled_flag_survives_a_file_that_lacks_it(self):
        """The case that matters. A cancelled stage has no result rows, so
        nothing in the scrape can re-imply the flag; older scrape files predate
        it entirely (Vuelta 1968 st15). If preservation doesn't carry it, a
        re-ingest silently un-cancels the stage.

        Written deliberately so the flag is absent from the file on the second
        pass — an earlier version of this test set it in the file every time,
        which meant the preservation path was never exercised and a mutation
        removing it went undetected."""
        self.write_stage(1, rows=[], cancelled=True)
        self.ingest()
        self.assertEqual(self.stages()[1]["cancelled"], 1)

        self.write_stage(1, rows=[], cancelled=False)   # flag NOT in the file
        self.ingest()
        self.assertEqual(self.stages()[1]["cancelled"], 1,
                         "cancelled must be preserved when the scrape file lacks it")

    def test_cancelled_stage_does_not_inherit_a_stale_distance(self):
        """0 km is a cancelled stage's true distance. Carrying over the value
        left by whatever previously held that number gave the 1991 Vuelta
        cancelled stage a bogus 111.0 km."""
        self.write_stage(1, distance="111 km")
        self.ingest()
        self.write_stage(1, distance="0 km", rows=[], cancelled=True)
        self.ingest()
        s = self.stages()[1]
        self.assertEqual(s["cancelled"], 1)
        self.assertEqual(s["distance_km"], 0.0)


class TestFinishTimes(IngestHarness):
    """The winner's finish time. Wrong on 3,377 stages before this was fixed.

    PCS renders the time cell as the displayed time followed immediately by a
    hidden gap, so the winner's row parses with abs_time AND gap set to the same
    value — "4:15:28" in both. Computing finish = winner + gap therefore stored
    double the real winning time, and nothing noticed because every other rider
    on the stage was correct and the number is only a fallback in export_gc.
    """

    def winner_row(self, time_txt):
        """The winner's row as the parser really produces it: gap repeats the
        absolute time, because PCS prints them in one cell."""
        return result_row("1", "Winner", "rider/winner", rnk="1", gap=time_txt)[:13] \
            + [time_txt, time_txt]

    def other_row(self, bib, name, rnk, gap):
        return result_row(bib, name, f"rider/{name.lower()}", rnk=rnk, gap=gap)[:13] + ["", gap]

    def times(self):
        return {r["rider_id"]: r["finish_time_seconds"] for r in self.conn.execute(
            "SELECT rider_id, finish_time_seconds FROM stage_results")}

    def test_winner_time_is_not_doubled(self):
        self.write_stage(1, rows=[self.winner_row("4:15:28"),
                                  self.other_row("2", "Second", "2", "0:19")])
        self.ingest()
        t = self.times()
        self.assertEqual(t["rider/winner"], 15328,
                         "the winner's own time must not have its own gap added to it")
        self.assertEqual(t["rider/second"], 15328 + 19)

    def test_promoted_co_winner_keeps_a_real_gap(self):
        """After a disqualification PCS lists two rank-1 riders — 2008 TDF st4
        has Schumacher and the promoted Kirchen, 18s back. The second must not
        overwrite the winning time, and must keep its own gap."""
        # Kirchen's row carries "0:18" in BOTH fields, exactly like the
        # winner's — PCS prints the gap in that cell for every row after the
        # first. So "rank 1 with an absolute time" describes him too, and
        # without the once-only guard he replaces a 35:44 winning time with 18
        # seconds and drags every later rider's time down with him.
        kirchen = self.other_row("41", "Kirchen", "1", "0:18")
        kirchen[13] = "0:18"
        self.write_stage(1, rows=[self.winner_row("35:44"), kirchen,
                                  self.other_row("198", "Millar", "2", "0:18")])
        self.ingest()
        t = self.times()
        self.assertEqual(t["rider/winner"], 2144)
        self.assertEqual(t["rider/kirchen"], 2144 + 18,
                         "a promoted co-winner must not reset the winning time")
        self.assertEqual(t["rider/millar"], 2144 + 18)


class TestSlugAndProvenance(IngestHarness):

    def test_slug_from_file_is_stored(self):
        self.write_stage(1, slug="stage-1a")
        self.ingest()
        self.assertEqual(self.stages()[1]["source_slug"], "stage-1a")

    def test_absent_slug_is_not_fabricated(self):
        """Writing a guessed 'stage-{n}' is worse than NULL: on a split edition
        it is wrong for every stage after the split, and callers trust it."""
        self.write_stage(1)
        self.write_stage(2, date="1990-05-02")
        self.write_stage(3, date="1990-05-02")     # split day -> undecidable
        self.ingest()
        self.assertIsNone(self.stages()[2]["source_slug"],
                          "must not guess a slug on a split edition")

    def test_source_slug_survives_reingest_of_a_split_edition(self):
        """On a split edition the slug CANNOT be re-derived — backfill rightly
        refuses to guess, because PCS letters split days in some editions and
        numbers them sequentially in others. So a probe-verified slug lives
        only in the DB, and a re-ingest that doesn't carry it over destroys it
        with nothing to put it back. Nine split Vuelta editions lost every slug
        that way during the TTT recovery."""
        self.write_stage(1, date="1990-05-01")
        self.write_stage(2, date="1990-05-02")
        self.write_stage(3, date="1990-05-02")          # split day
        self.ingest()
        for n, slug in ((1, "stage-1"), (2, "stage-2a"), (3, "stage-2b")):
            self.conn.execute("UPDATE stages SET source_slug=? WHERE stage_number=?", (slug, n))
        self.conn.commit()

        self.ingest()                                    # files still carry no slug
        got = {n: r["source_slug"] for n, r in self.stages().items()}
        self.assertEqual(got, {1: "stage-1", 2: "stage-2a", 3: "stage-2b"})

    def test_a_slug_in_the_file_still_wins(self):
        self.write_stage(1, slug="stage-1")
        self.ingest()
        self.conn.execute("UPDATE stages SET source_slug='stale'")
        self.conn.commit()
        self.ingest()
        self.assertEqual(self.stages()[1]["source_slug"], "stage-1")

    def test_provenance_recorded_and_not_orphaned_by_reingest(self):
        self.write_stage(1, slug="stage-1")
        self.ingest()
        n1 = self.conn.execute(
            "SELECT COUNT(*) FROM data_provenance WHERE entity='stages'").fetchone()[0]
        self.assertGreater(n1, 0)

        self.ingest()
        orphans = self.conn.execute(
            "SELECT COUNT(*) FROM data_provenance dp WHERE dp.entity='stages' AND NOT EXISTS "
            "(SELECT 1 FROM stages s WHERE s.stage_id=dp.entity_id)").fetchone()[0]
        self.assertEqual(orphans, 0, "re-ingest must clear the old edition's provenance")


class TestMalformedRows(IngestHarness):

    def test_short_rows_are_skipped_but_counted(self):
        """A bare `continue` here lost a real rider's result with no trace."""
        good = result_row("1", "Rider A", "rider/a")
        short = good[:-1]
        self.write_stage(1, rows=[good, short])
        self.ingest()
        n = self.conn.execute("SELECT COUNT(*) FROM stage_results").fetchone()[0]
        self.assertEqual(n, 1, "the malformed row must not be inserted")
        self.assertIn("malformed", self.last_output.lower(),
                      "a dropped row must be reported, not silently swallowed")

    def test_well_formed_rows_all_land(self):
        rows = [result_row(str(i), f"Rider {i}", f"rider/{i}", rnk=str(i))
                for i in range(1, 6)]
        self.write_stage(1, rows=rows)
        self.ingest()
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM stage_results").fetchone()[0], 5)
        self.assertEqual(len(rows[0]), STAGE_ROW_LEN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
