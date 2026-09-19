#!/usr/bin/env python3
"""
Tests for the four validators — the checks that stand between a data defect
and the deployed site.

They had none until 2026-08-22, which is backwards: validate_db.py is the only
thing that can catch a silent revert of a patched value, and it CANNOT run in
CI at all (cycling.db is gitignored and not regenerable there). Its correctness
was established once, by hand, by replaying a damaged database through it. That
is not a thing that stays true on its own.

Every case here is either a failure the validator was written for, or a
distinction it draws deliberately and would be easy to "simplify" away:

  * a patch reverting to 'pcs' must ERROR; the same value RISING must not
  * orphaned provenance is an ERROR for entity='stages' and a WARN for
    entity='stage_results' — loss versus litter
  * the no-GC check is scoped by INCLUSION (race_type='stage_race'), because
    excluding 'one_day' stopped covering anything the day 'gravel' arrived
  * a cancelled stage sharing a date is a phantom split day UNLESS its slug
    ends in a letter, where it is a genuine cancelled second half

The DB fixtures are built from schema.sql rather than a copy of it, so the
tests cannot drift from the real schema the way an inlined copy did before.
"""
import audit_disqualifications
import audit_gc_ladders
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import validate_db
import validate_exports
import validate_gc
import validate_kom


def schema_conn():
    """An in-memory DB with the real schema, so a column rename breaks a test."""
    conn = sqlite3.connect(":memory:")
    with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


class DBCheckTest(unittest.TestCase):
    """Base for validate_db checks: real schema, isolated module-level lists."""

    def setUp(self):
        self.conn = schema_conn()
        self.cur = self.conn.cursor()
        # validate_db accumulates into module-level lists; give each test its own.
        validate_db.errors = []
        validate_db.warnings = []
        validate_db.notes = []

    def tearDown(self):
        self.conn.close()

    # ── fixture helpers ─────────────────────────────────────────────────────
    def race(self, race_id, name, race_type="stage_race", country="France"):
        self.cur.execute("INSERT INTO races (race_id,name,country,race_type) VALUES (?,?,?,?)",
                         (race_id, name, country, race_type))

    def edition(self, edition_id, race_id, year):
        self.cur.execute(
            "INSERT INTO race_editions (edition_id,race_id,year,edition_name) VALUES (?,?,?,?)",
            (edition_id, race_id, year, str(year)))

    def stage(self, stage_id, edition_id, number, **kw):
        cols = dict(stage_number=number, edition_id=edition_id, stage_id=stage_id)
        cols.update(kw)
        keys = ",".join(cols)
        self.cur.execute(f"INSERT INTO stages ({keys}) VALUES ({','.join('?' * len(cols))})",
                         tuple(cols.values()))

    def rider(self, rider_id, name="A Rider"):
        self.cur.execute("INSERT OR IGNORE INTO riders (rider_id,full_name) VALUES (?,?)",
                         (rider_id, name))

    def result(self, stage_id, rider_id, **kw):
        self.rider(rider_id)
        cols = dict(stage_id=stage_id, rider_id=rider_id)
        cols.update(kw)
        keys = ",".join(cols)
        self.cur.execute(f"INSERT INTO stage_results ({keys}) VALUES ({','.join('?' * len(cols))})",
                         tuple(cols.values()))

    def team(self, team_id, name="A Team", season=2013):
        self.cur.execute("INSERT OR IGNORE INTO teams (team_id,name,season_year) VALUES (?,?,?)",
                         (team_id, name, season))

    def prov(self, entity, entity_id, field, source, script="patch.py"):
        self.cur.execute(
            "INSERT INTO data_provenance (entity,entity_id,field,source,script,recorded_at)"
            " VALUES (?,?,?,?,?,'2026-01-01T00:00:00Z')",
            (entity, entity_id, field, source, script))

    # ── assertions ──────────────────────────────────────────────────────────
    def assertErrorMatching(self, fragment):
        joined = "\n".join(validate_db.errors)
        self.assertIn(fragment, joined,
                      f"no error containing {fragment!r}; errors were {validate_db.errors}")

    def assertNoErrors(self):
        self.assertEqual(validate_db.errors, [])


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_patched_values — the B1 machinery
# ══════════════════════════════════════════════════════════════════════════

class PatchedValuesTest(DBCheckTest):
    """
    The 2026-08-21 incident in miniature: a re-ingest rebuilt Milan-San Remo
    2013 from its scrape file, putting back PCS's wrong 121.0 km over a
    researched 246 km, and every count and every check stayed green.
    """

    def setUp(self):
        super().setUp()
        self.race(1, "Milan-San Remo", race_type="one_day", country="Italy")
        self.edition(1, 1, 2013)
        self.stage(10, 1, 1, distance_km=246.0, source_slug="result")
        self.result(10, "rider/gerald-ciolek", team_id=None, finish_time_seconds=20240)
        self.prov("stages", 10, "distance_km", "wikipedia")

        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                               encoding="utf-8")
        self.tmp.close()
        self._real_manifest = validate_db.PATCH_MANIFEST
        validate_db.PATCH_MANIFEST = self.tmp.name

    def tearDown(self):
        validate_db.PATCH_MANIFEST = self._real_manifest
        os.unlink(self.tmp.name)
        super().tearDown()

    def write_manifest(self, patched, value_counts=None):
        with open(self.tmp.name, "w", encoding="utf-8") as f:
            json.dump({"patched": patched, "value_counts": value_counts or {}}, f)

    def run_check(self):
        validate_db.check_patched_values(self.cur)

    # ── the manifest test ───────────────────────────────────────────────────
    def test_intact_patch_passes(self):
        self.write_manifest([["Milan-San Remo", 2013, 1, "distance_km", "wikipedia"]])
        self.run_check()
        self.assertNoErrors()

    def test_reverted_patch_is_an_error_naming_the_new_source(self):
        """The incident. Provenance flips to 'pcs' and the value is silently wrong."""
        self.write_manifest([["Milan-San Remo", 2013, 1, "distance_km", "wikipedia"]])
        self.cur.execute("UPDATE data_provenance SET source='pcs' WHERE entity='stages'")
        self.cur.execute("UPDATE stages SET distance_km=121.0 WHERE stage_id=10")
        self.run_check()
        self.assertErrorMatching("PATCH LOST")
        self.assertErrorMatching("Milan-San Remo 2013 stage 1 distance_km")
        # It must say what the value became, not merely that something changed:
        # 'pcs' is the tell that an ingest did it.
        self.assertErrorMatching("now 'pcs'")

    def test_patch_whose_provenance_vanished_entirely_reports_absent(self):
        """A re-ingest deletes the provenance row with the patch, so 'absent'
        is a distinct outcome from 'reverted to pcs' and must not crash."""
        self.write_manifest([["Milan-San Remo", 2013, 1, "distance_km", "wikipedia"]])
        self.cur.execute("DELETE FROM data_provenance")
        self.run_check()
        self.assertErrorMatching("now 'absent'")

    def test_a_missing_manifest_warns_rather_than_passing_silently(self):
        os.unlink(self.tmp.name)
        self.run_check()
        self.assertNoErrors()
        self.assertTrue(any("patched_values.json is missing" in w
                            for w in validate_db.warnings), validate_db.warnings)
        # Recreate so tearDown's unlink succeeds.
        open(self.tmp.name, "w").close()

    def test_an_unlisted_patch_is_a_note_not_an_error(self):
        """New patches are normal; they want the manifest refreshed, not a failure."""
        self.write_manifest([])
        self.run_check()
        self.assertNoErrors()
        self.assertTrue(any("not in patched_values.json" in n
                            for n in validate_db.notes), validate_db.notes)

    # ── the value-count test ────────────────────────────────────────────────
    def test_a_drop_in_patched_value_count_is_an_error(self):
        """The 84,800 -> 82,916 team attributions that nothing else noticed."""
        self.write_manifest([["Milan-San Remo", 2013, 1, "distance_km", "wikipedia"]],
                            {"one_day.finish_time_seconds": 5})
        self.run_check()
        self.assertErrorMatching("VALUES LOST")
        self.assertErrorMatching("fell from 5 to 1")

    def test_a_rise_in_value_count_is_a_note_not_an_error(self):
        """The deliberate asymmetry: a drop is loss, a rise is new data.
        Collapsing this to != would fail every run that adds a race-year."""
        self.write_manifest([["Milan-San Remo", 2013, 1, "distance_km", "wikipedia"]],
                            {"one_day.finish_time_seconds": 0})
        self.run_check()
        self.assertNoErrors()
        self.assertTrue(any("rose from 0 to 1" in n for n in validate_db.notes),
                        validate_db.notes)

    def test_a_matching_count_is_completely_silent(self):
        """The healthy case must produce nothing at all. A boundary slip to >=
        would emit "rose from 1 to 1" on every clean run and train the eye to
        skip the notes, which is where real drift gets reported."""
        self.write_manifest([["Milan-San Remo", 2013, 1, "distance_km", "wikipedia"]],
                            {"one_day.finish_time_seconds": 1})
        self.run_check()
        self.assertNoErrors()
        self.assertEqual(validate_db.notes, [])

    def test_counts_are_grouped_by_race_type(self):
        """A gravel loss must not be masked by a classics gain, and vice versa."""
        self.race(2, "Unbound Gravel", race_type="gravel", country="United States")
        self.edition(2, 2, 2024)
        self.stage(20, 2, 1, distance_km=320.0)
        self.result(20, "rider/keegan-swenson", finish_time_seconds=35000)
        self.write_manifest([["Milan-San Remo", 2013, 1, "distance_km", "wikipedia"]],
                            {"one_day.finish_time_seconds": 1,
                             "gravel.finish_time_seconds": 4})
        self.run_check()
        self.assertErrorMatching("gravel.finish_time_seconds")
        self.assertEqual(len(validate_db.errors), 1,
                         "the intact one_day count must not also fail")

    # ── the contradiction test ──────────────────────────────────────────────
    def test_live_provenance_for_a_null_value_is_an_error(self):
        """Needs no baseline: a patch claims a value that is not there."""
        self.write_manifest([["Milan-San Remo", 2013, 1, "distance_km", "wikipedia"]])
        self.prov("stage_results", 10, "team_id:rider/gerald-ciolek", "bikeraceinfo")
        self.run_check()   # team_id was inserted as NULL
        self.assertErrorMatching("carry patch provenance for a value that is now NULL")

    def test_contradiction_check_is_keyed_to_the_rider_in_the_field(self):
        """entity_id is the STAGE id, with the rider inside `field`. Joining on
        the stage alone would flag a teammate's intact value as lost."""
        self.write_manifest([["Milan-San Remo", 2013, 1, "distance_km", "wikipedia"]])
        self.team("team/cannondale-2013", "Cannondale")
        self.result(10, "rider/peter-sagan", team_id="team/cannondale-2013")
        self.prov("stage_results", 10, "team_id:rider/peter-sagan", "bikeraceinfo")
        self.run_check()
        self.assertNoErrors()

    def test_an_ingest_source_is_not_treated_as_a_patch(self):
        """'pcs' and 'derived' are what an ingest writes; only PATCH_SOURCES
        are values a re-ingest would throw away."""
        self.write_manifest([["Milan-San Remo", 2013, 1, "distance_km", "wikipedia"]])
        self.prov("stage_results", 10, "team_id:rider/gerald-ciolek", "pcs")
        self.run_check()
        self.assertNoErrors()

    # ── the writer ──────────────────────────────────────────────────────────
    def test_update_writes_the_manifest_it_later_reads(self):
        with contextlib.redirect_stdout(io.StringIO()):
            validate_db.check_patched_values(self.cur, update=True)
        with open(self.tmp.name, encoding="utf-8") as f:
            written = json.load(f)
        self.assertEqual(written["patched"],
                         [["Milan-San Remo", 2013, 1, "distance_km", "wikipedia"]])
        self.assertEqual(written["value_counts"]["one_day.finish_time_seconds"], 1)
        # And what it wrote must satisfy the check it wrote it for.
        validate_db.errors = []
        self.run_check()
        self.assertNoErrors()


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_provenance — loss versus litter
# ══════════════════════════════════════════════════════════════════════════

class ProvenanceCheckTest(DBCheckTest):
    def setUp(self):
        super().setUp()
        self.race(1, "Tour de France")
        self.edition(1, 1, 2024)
        self.stage(10, 1, 1, source_slug="stage-1")

    def test_clean_provenance_says_nothing(self):
        self.prov("stages", 10, "distance_km", "pcs")
        validate_db.check_provenance(self.cur)
        self.assertNoErrors()
        self.assertEqual(validate_db.warnings, [])

    def test_orphaned_stages_provenance_is_an_error(self):
        self.prov("stages", 999, "distance_km", "pcs")
        validate_db.check_provenance(self.cur)
        self.assertErrorMatching("orphaned data_provenance row")

    def test_orphaned_stage_results_provenance_is_a_WARN_not_an_error(self):
        """The deliberate asymmetry. A stale stage_results row describes a stage
        that no longer exists, so it makes no claim about any live value — it is
        litter. Promoting it to an error would fail every DB carrying pre-2026-08-21
        residue; demoting the 'stages' one would restore the original blind spot."""
        self.prov("stage_results", 999, "team_id:rider/x", "bikeraceinfo")
        validate_db.check_provenance(self.cur)
        self.assertNoErrors()
        self.assertTrue(any("no longer exists" in w for w in validate_db.warnings),
                        validate_db.warnings)

    def test_orphaned_rider_provenance_is_an_error(self):
        """riders are keyed by TEXT rider_id, not an integer id, so this check
        has to compare as text — a CAST would silently match nothing."""
        self.rider("rider/alexey-vermeulen")
        self.prov("riders", "rider/alexey-vermeulen", "first_name", "pcs")
        self.prov("riders", "rider/ghost", "first_name", "pcs")
        validate_db.check_provenance(self.cur)
        self.assertErrorMatching("name a rider that does not exist")
        self.assertEqual(len(validate_db.errors), 1,
                         "the live rider's provenance must not be flagged")

    def test_rider_provenance_for_a_live_rider_is_silent(self):
        self.rider("rider/alexey-vermeulen")
        for f in ("first_name", "last_name", "birthday"):
            self.prov("riders", "rider/alexey-vermeulen", f, "pcs")
        validate_db.check_provenance(self.cur)
        self.assertNoErrors()

    def test_an_unknown_source_is_an_error(self):
        self.prov("stages", 10, "distance_km", "some-blog")
        validate_db.check_provenance(self.cur)
        self.assertErrorMatching("unknown source value 'some-blog'")

    def test_every_valid_source_is_accepted(self):
        """Driven off race_common.VALID_SOURCES; a second hardcoded list here
        once diverged when 'cyclingflash' was added and failed a value
        record_provenance() had already accepted."""
        from race_common import VALID_SOURCES
        for i, src in enumerate(sorted(VALID_SOURCES)):
            self.prov("stages", 10, f"field_{i}", src)
        validate_db.check_provenance(self.cur)
        self.assertNoErrors()

    def test_patch_sources_are_a_subset_of_valid_sources(self):
        """PATCH_SOURCES lists what only a patch writes; every one of them must
        still be a source record_provenance() will accept."""
        from race_common import VALID_SOURCES
        self.assertLessEqual(set(validate_db.PATCH_SOURCES), set(VALID_SOURCES))


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_phantom_split_days
# ══════════════════════════════════════════════════════════════════════════

class PhantomSplitDayTest(DBCheckTest):
    """
    Giro 1969's cancelled Trento-Marmolada carried stage 19's date, so
    compute_stage_labels() read the repeated date as a split day, rendered it
    '19b', and shifted every later label down one — the finale showed as 22
    instead of 23.
    """

    def setUp(self):
        super().setUp()
        self.race(1, "Giro d'Italia", country="Italy")
        self.edition(1, 1, 1969)

    def test_cancelled_stage_sharing_a_date_without_a_letter_slug_is_an_error(self):
        self.stage(10, 1, 19, stage_date="1969-06-01", source_slug="stage-19")
        self.stage(11, 1, 20, stage_date="1969-06-01", source_slug="stage-20", cancelled=1)
        validate_db.check_phantom_split_days(self.cur)
        self.assertErrorMatching("phantom split day")

    def test_a_genuine_cancelled_split_half_is_not_flagged(self):
        """Giro 1956 stage-9b and Vuelta 1978 stage-19b are real cancelled
        second halves. The trailing letter is the whole distinction."""
        self.stage(10, 1, 9, stage_date="1956-06-01", source_slug="stage-9a")
        self.stage(11, 1, 10, stage_date="1956-06-01", source_slug="stage-9b", cancelled=1)
        validate_db.check_phantom_split_days(self.cur)
        self.assertNoErrors()

    def test_a_cancelled_stage_on_its_own_date_is_fine(self):
        self.stage(10, 1, 19, stage_date="1969-06-01", source_slug="stage-19")
        self.stage(11, 1, 20, stage_date="1969-06-02", source_slug="stage-20", cancelled=1)
        validate_db.check_phantom_split_days(self.cur)
        self.assertNoErrors()

    def test_a_shared_date_between_two_LIVE_stages_is_not_flagged(self):
        """The check is scoped to cancelled stages, and that scope is the point:
        TDF 1986 stages 1 and 2 fall on one day and are a genuine split.
        Applying the rule to every stage produced 33 false errors on correct data."""
        self.stage(10, 1, 1, stage_date="1986-07-04", source_slug="stage-1")
        self.stage(11, 1, 2, stage_date="1986-07-04", source_slug="stage-2")
        validate_db.check_phantom_split_days(self.cur)
        self.assertNoErrors()

    def test_a_one_day_race_is_out_of_scope(self):
        """Every classics edition shares its date with itself across races;
        the check is scoped to race_type='stage_race'."""
        self.race(2, "Milan-San Remo", race_type="one_day", country="Italy")
        self.edition(2, 2, 2013)
        self.stage(20, 2, 1, stage_date="2013-03-17", source_slug="result")
        self.stage(21, 2, 2, stage_date="2013-03-17", source_slug="result-2", cancelled=1)
        validate_db.check_phantom_split_days(self.cur)
        self.assertNoErrors()


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_results
# ══════════════════════════════════════════════════════════════════════════

class ResultsCheckTest(DBCheckTest):
    def warnings_matching(self, fragment):
        return [w for w in validate_db.warnings if fragment in w]

    # ── multiple rank-1 finishers ───────────────────────────────────────────
    def test_a_TTT_may_give_every_rider_rank_1(self):
        self.race(1, "Tour de France")
        self.edition(1, 1, 2024)
        self.stage(10, 1, 1, route_type="TTT")
        self.result(10, "rider/a", stage_rank=1)
        self.result(10, "rider/b", stage_rank=1)
        validate_db.check_results(self.cur)
        self.assertEqual(self.warnings_matching("rank-1 finisher"), [])

    def test_two_rank_1_finishers_outside_a_TTT_warn(self):
        self.race(1, "Tour de France")
        self.edition(1, 1, 2008)
        self.stage(10, 1, 1, route_type="M")
        self.result(10, "rider/bernhard-kohl", stage_rank=1)
        self.result(10, "rider/carlos-sastre", stage_rank=1)
        validate_db.check_results(self.cur)
        self.assertTrue(self.warnings_matching("rank-1 finisher"), validate_db.warnings)

    # ── the no-GC check, and its scoping ────────────────────────────────────
    def test_a_stage_race_with_no_gc_rank_on_its_final_stage_warns(self):
        self.race(1, "Vuelta a España", country="Spain")
        self.edition(1, 1, 2020)
        self.stage(10, 1, 1, route_type="F")
        self.stage(11, 1, 2, route_type="F")
        self.result(10, "rider/a", stage_rank=1, gc_rank=1)
        self.result(11, "rider/a", stage_rank=1)          # no gc_rank on the finale
        validate_db.check_results(self.cur)
        self.assertTrue(self.warnings_matching("no gc_rank=1"), validate_db.warnings)

    def test_a_stage_race_with_gc_rank_on_its_final_stage_is_silent(self):
        self.race(1, "Vuelta a España", country="Spain")
        self.edition(1, 1, 2020)
        self.stage(10, 1, 1, route_type="F")
        self.stage(11, 1, 2, route_type="F")
        self.result(10, "rider/a", stage_rank=1, gc_rank=1)
        self.result(11, "rider/a", stage_rank=1, gc_rank=1)
        validate_db.check_results(self.cur)
        self.assertEqual(self.warnings_matching("no gc_rank=1"), [])

    def test_one_day_and_gravel_races_are_not_expected_to_have_a_GC(self):
        """Scoped by INCLUSION (race_type='stage_race'), not by excluding
        'one_day'. A one-day classic has no general classification at all, so
        every edition tripped this forever — it took the count from 17 to 83 the
        day the classics landed. And the exclusion list silently stopped
        covering anything the day a second non-stage-race type arrived: this
        test fails if 'gravel' is ever dropped back to an exclusion."""
        self.race(1, "Milan-San Remo", race_type="one_day", country="Italy")
        self.edition(1, 1, 2013)
        self.stage(10, 1, 1)
        self.result(10, "rider/gerald-ciolek", stage_rank=1)
        self.race(2, "Unbound Gravel", race_type="gravel", country="United States")
        self.edition(2, 2, 2024)
        self.stage(20, 2, 1)
        self.result(20, "rider/keegan-swenson", stage_rank=1)
        validate_db.check_results(self.cur)
        self.assertEqual(self.warnings_matching("no gc_rank=1"), [],
                         "a race with no GC must not be asked for one")

    # ── stages with results but no finishing positions ──────────────────────
    def test_a_stage_with_results_but_no_ranks_warns(self):
        self.race(1, "Tour de France")
        self.edition(1, 1, 1985)
        self.stage(10, 1, 1, route_type="TTT")
        self.result(10, "rider/a", stage_rank=None, finish_time_seconds=3600)
        validate_db.check_results(self.cur)
        self.assertTrue(self.warnings_matching("no finishing positions"),
                        validate_db.warnings)

    def test_a_cancelled_stage_with_no_ranks_does_not_warn(self):
        self.race(1, "Tour de France")
        self.edition(1, 1, 1985)
        self.stage(10, 1, 1, cancelled=1)
        self.result(10, "rider/a", stage_rank=None)
        validate_db.check_results(self.cur)
        self.assertEqual(self.warnings_matching("no finishing positions"), [])


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_editions
# ══════════════════════════════════════════════════════════════════════════

class EditionsCheckTest(DBCheckTest):
    RACES = ["Tour de France"]

    def setUp(self):
        super().setUp()
        self.race(1, "Tour de France")
        self.edition(1, 1, 1989)

    def run_check(self):
        validate_db.check_editions(self.cur, self.RACES)

    def test_a_complete_edition_passes(self):
        self.stage(10, 1, 1, source_slug="stage-1", distance_km=100.0,
                   start_location="A", finish_location="B", stage_date="1989-07-01")
        self.stage(11, 1, 2, source_slug="stage-2", distance_km=150.0,
                   start_location="B", finish_location="C", stage_date="1989-07-02")
        self.run_check()
        self.assertNoErrors()

    def test_a_gap_in_stage_numbering_is_an_error(self):
        """The 2010 Vuelta silently lost PCS stages 11 and 12."""
        self.stage(10, 1, 1, source_slug="stage-1")
        self.stage(12, 1, 3, source_slug="stage-3")
        self.run_check()
        self.assertErrorMatching("gap in stage numbering at [2]")

    def test_a_missing_source_slug_is_an_error(self):
        self.stage(10, 1, 1, source_slug=None)
        self.run_check()
        self.assertErrorMatching("1 stage(s) with no source_slug")

    def test_a_reused_source_slug_is_an_error(self):
        """A wrong source_slug re-fetches the wrong PCS page."""
        self.stage(10, 1, 1, source_slug="stage-1")
        self.stage(11, 1, 2, source_slug="stage-1")
        self.run_check()
        self.assertErrorMatching("source_slug reused within the edition")

    def test_two_identical_stages_sharing_a_slug_are_an_error(self):
        """1991 Vuelta had a stage duplicated to stand in for a cancelled one
        that was never scraped: same date, same route, same PCS page."""
        for sid, num in ((10, 1), (11, 2)):
            self.stage(sid, 1, num, source_slug="stage-1", stage_date="1991-05-01",
                       start_location="Mérida", finish_location="Mérida",
                       distance_km=20.0)
        self.run_check()
        self.assertErrorMatching("are identical")
        self.assertErrorMatching("same slug stage-1")

    def test_a_split_day_over_the_same_circuit_is_NOT_a_duplicate(self):
        """Giro 1972's 12a and 12b are both 20 km Forte dei Marmi > Forte dei
        Marmi on one date, won by Merckx and Swerts. Distinct slugs mean
        distinct PCS pages, so they are two stages, not one duplicated."""
        self.stage(10, 1, 12, source_slug="stage-12a", stage_date="1972-05-30",
                   start_location="Forte dei Marmi", finish_location="Forte dei Marmi",
                   distance_km=20.0)
        self.stage(11, 1, 13, source_slug="stage-12b", stage_date="1972-05-30",
                   start_location="Forte dei Marmi", finish_location="Forte dei Marmi",
                   distance_km=20.0)
        self.run_check()
        self.assertNoErrors()

    def test_a_negative_distance_is_an_error(self):
        self.stage(10, 1, 1, source_slug="stage-1", distance_km=-5.0)
        self.run_check()
        self.assertErrorMatching("negative distance")

    def test_zero_distance_on_a_live_stage_warns_but_not_on_a_cancelled_one(self):
        self.stage(10, 1, 1, source_slug="stage-1", distance_km=0.0)
        self.stage(11, 1, 2, source_slug="stage-2", distance_km=0.0, cancelled=1)
        self.run_check()
        self.assertNoErrors()
        self.assertEqual(len([w for w in validate_db.warnings if "zero distance" in w]), 1)


class CarriedFinalDistanceTest(DBCheckTest):
    """
    PCS publishes "0 km" for a number of finales, and six Tours ended up with
    the previous day's figure on the run into Paris — 1989's 24.5 km LeMond
    time trial was stored as a 130 km road stage.

    Equal distances alone are far too common to flag (38 editions match, nearly
    all coincidence). Three further filters make it actionable, and each one is
    load-bearing: unrecorded provenance, the FINAL stage, a different route.
    """

    def setUp(self):
        super().setUp()
        self.race(1, "Tour de France")
        self.edition(1, 1, 1989)

    def build(self, last_distance=130.0, last_route=("Versailles", "Paris"),
              last_source=None, extra_stage=False):
        self.stage(10, 1, 1, source_slug="stage-20", distance_km=130.0,
                   start_location="Aix-les-Bains", finish_location="L'Isle-d'Abeau",
                   stage_date="1989-07-22")
        self.stage(11, 1, 2, source_slug="stage-21", distance_km=last_distance,
                   start_location=last_route[0], finish_location=last_route[1],
                   stage_date="1989-07-23")
        if last_source:
            self.prov("stages", 11, "distance_km", last_source)
        if extra_stage:
            self.stage(12, 1, 3, source_slug="stage-22", distance_km=99.0,
                       start_location="Paris", finish_location="Paris",
                       stage_date="1989-07-24")
        validate_db.check_editions(self.cur, ["Tour de France"])
        return [w for w in validate_db.warnings if "identical to stage" in w]

    def test_the_real_case_warns(self):
        self.assertTrue(self.build(), validate_db.warnings)

    def test_a_recorded_source_clears_it(self):
        """The value was researched, not carried. 'wikipedia' means someone
        checked; only 'unknown' means nobody did."""
        self.assertEqual(self.build(last_source="wikipedia"), [])

    def test_the_same_route_clears_it(self):
        """A circuit legitimately repeats its own distance."""
        self.assertEqual(
            self.build(last_route=("Aix-les-Bains", "L'Isle-d'Abeau")), [])

    def test_a_different_distance_clears_it(self):
        self.assertEqual(self.build(last_distance=24.5), [])

    def test_only_the_FINAL_pair_is_checked(self):
        """PCS's missing distances cluster on the finale, and a wrong figure
        there also skews the edition total. Mid-race repeats are coincidence."""
        self.assertEqual(self.build(extra_stage=True), [])


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_referential and check_intentional_gaps
# ══════════════════════════════════════════════════════════════════════════

class ReferentialCheckTest(DBCheckTest):
    """Foreign keys are ON in schema.sql, so these rows cannot arrive through
    a normal insert — but they DID arrive, through re-ingests that minted new
    ids. The check has to survive a DB where the constraint was bypassed."""

    def setUp(self):
        super().setUp()
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.race(1, "Tour de France")
        self.edition(1, 1, 2024)
        self.stage(10, 1, 1, source_slug="stage-1")

    def test_a_clean_db_passes(self):
        self.result(10, "rider/a", stage_rank=1)
        validate_db.check_referential(self.cur)
        self.assertNoErrors()

    def test_a_result_pointing_at_a_missing_stage_is_an_error(self):
        self.rider("rider/a")
        self.cur.execute("INSERT INTO stage_results (stage_id,rider_id) VALUES (999,'rider/a')")
        validate_db.check_referential(self.cur)
        self.assertErrorMatching("stage_results referencing a missing stage")

    def test_a_result_pointing_at_a_missing_rider_is_an_error(self):
        self.cur.execute("INSERT INTO stage_results (stage_id,rider_id) VALUES (10,'rider/ghost')")
        validate_db.check_referential(self.cur)
        self.assertErrorMatching("stage_results referencing a missing rider")

    def test_a_result_pointing_at_a_missing_team_is_an_error(self):
        self.rider("rider/a")
        self.cur.execute("INSERT INTO stage_results (stage_id,rider_id,team_id)"
                         " VALUES (10,'rider/a','team/ghost')")
        validate_db.check_referential(self.cur)
        self.assertErrorMatching("stage_results referencing a missing team")

    def test_a_NULL_team_is_not_a_missing_team(self):
        """Team attribution is absent for most pre-1990 results and all
        off-road ones; NULL is a legitimate value, not a dangling reference."""
        self.rider("rider/a")
        self.cur.execute("INSERT INTO stage_results (stage_id,rider_id,team_id)"
                         " VALUES (10,'rider/a',NULL)")
        validate_db.check_referential(self.cur)
        self.assertNoErrors()

    def test_a_stage_pointing_at_a_missing_edition_is_an_error(self):
        self.cur.execute("INSERT INTO stages (stage_id,edition_id,stage_number)"
                         " VALUES (99,999,1)")
        validate_db.check_referential(self.cur)
        self.assertErrorMatching("stages referencing a missing edition")


class IntentionalGapsTest(DBCheckTest):
    def setUp(self):
        super().setUp()
        self.race(1, "Giro d'Italia", country="Italy")
        self.edition(1, 1, 1969)
        self.stage(10, 1, 19, source_slug="stage-19", cancelled=1,
                   start_location="Trento", finish_location="Marmolada")
        self._real_notes = validate_db.load_stage_notes

    def tearDown(self):
        validate_db.load_stage_notes = self._real_notes
        super().tearDown()

    def use_notes(self, notes):
        validate_db.load_stage_notes = lambda: notes

    def test_a_documented_cancellation_is_reported_as_finished(self):
        self.use_notes({("Giro d'Italia", 1969, 19): "protest"})
        validate_db.check_intentional_gaps(self.cur)
        self.assertNoErrors()
        self.assertEqual(validate_db.warnings, [])
        self.assertTrue(any("1 documented in stage_notes.json" in n
                            for n in validate_db.notes), validate_db.notes)

    def test_an_undocumented_cancellation_is_named_so_a_reason_can_be_added(self):
        self.use_notes({})
        validate_db.check_intentional_gaps(self.cur)
        self.assertNoErrors()
        self.assertTrue(any("undocumented: Giro d'Italia 1969 stage 19" in n
                            for n in validate_db.notes), validate_db.notes)

    def test_a_note_keyed_to_no_cancelled_stage_warns(self):
        """A note that matches nothing explains nothing and silences nothing —
        it just sits in the file looking like the job is done. The likeliest
        cause is keying by the PCS slug number instead of the DB stage_number,
        which differ on every edition with a split day."""
        self.use_notes({("Giro d'Italia", 1969, 20): "protest"})
        validate_db.check_intentional_gaps(self.cur)
        self.assertTrue(any("which is not a cancelled stage in the DB" in w
                            for w in validate_db.warnings), validate_db.warnings)


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_split_slug_provenance
# ══════════════════════════════════════════════════════════════════════════

class SplitSlugProvenanceTest(DBCheckTest):
    """
    PCS letters split days in some editions and numbers them SEQUENTIALLY in
    others, so a slug derived from the stage number is a guess — and 201 of
    them were wrong. The check flags derived slugs only where a split day makes
    the convention ambiguous.
    """

    def setUp(self):
        super().setUp()
        self.race(1, "Vuelta a España", country="Spain")
        self.edition(1, 1, 2022)

    def suspects(self):
        validate_db.check_split_slug_provenance(self.cur)
        return [w for w in validate_db.warnings if "DERIVED source_slug" in w]

    def test_a_derived_slug_on_a_split_edition_warns(self):
        self.stage(10, 1, 1, stage_date="2022-08-19", source_slug="stage-1a")
        self.stage(11, 1, 2, stage_date="2022-08-19", source_slug="stage-1b")
        self.prov("stages", 11, "source_slug", "derived")
        self.assertTrue(self.suspects(), validate_db.warnings)

    def test_a_derived_slug_with_no_split_day_is_not_flagged(self):
        """Without a repeated date the convention is unambiguous, so deriving
        the slug is safe — flagging it would bury the cases that matter."""
        self.stage(10, 1, 1, stage_date="2022-08-19", source_slug="stage-1")
        self.stage(11, 1, 2, stage_date="2022-08-20", source_slug="stage-2")
        self.prov("stages", 11, "source_slug", "derived")
        self.assertEqual(self.suspects(), [])

    def test_a_confirmed_slug_on_a_split_edition_is_not_flagged(self):
        """audit_stage_counts.py --confirm-slugs pairs each slug with its route
        off PCS's own stage list; that took this from 4,572 stages to 31."""
        self.stage(10, 1, 1, stage_date="2022-08-19", source_slug="stage-1a")
        self.stage(11, 1, 2, stage_date="2022-08-19", source_slug="stage-1b")
        self.prov("stages", 11, "source_slug", "pcs")
        self.assertEqual(self.suspects(), [])

    def test_stages_with_no_dates_cannot_be_screened(self):
        self.stage(10, 1, 1, source_slug="stage-1a")
        self.stage(11, 1, 2, source_slug="stage-1b")
        self.prov("stages", 11, "source_slug", "derived")
        self.assertEqual(self.suspects(), [])


# ══════════════════════════════════════════════════════════════════════════
# validate_exports.validate_year — the gate on the JSON the app consumes
# ══════════════════════════════════════════════════════════════════════════

def ds(stages, riders):
    return {"stages": stages, "riders": riders}


def sp(stage, **kw):
    point = {"stage": stage, "gcRank": None, "gcGapSeconds": None,
             "status": "FINISHED", "sprintRank": None, "komRank": None,
             "cumulativePoints": 0, "cumulativeKomPoints": 0}
    point.update(kw)
    return point


class ValidateYearTest(unittest.TestCase):
    def check(self, dataset, **kw):
        return validate_exports.validate_year(2024, dataset, **kw)

    def test_a_clean_year_passes(self):
        errors, warnings = self.check(ds(
            [{"stage_number": 1}, {"stage_number": 2}],
            [{"id": "rider/a", "finalRank": 1,
              "byStage": [sp(1, cumulativePoints=10), sp(2, cumulativePoints=25)]}]))
        self.assertEqual((errors, warnings), ([], []))

    def test_no_stages_is_an_error(self):
        errors, _ = self.check(ds([], []))
        self.assertIn("no stages", errors)

    def test_no_riders_is_an_error(self):
        errors, _ = self.check(ds([{"stage_number": 1}], []))
        self.assertIn("no riders", errors)

    def test_a_fully_cancelled_season_has_no_riders_and_is_correct(self):
        """2020 in the off-road set: Unbound was the only one of the six that
        existed yet, and COVID took it. Dropping the year would erase the
        cancellation, which is the one fact that season has to offer."""
        errors, warnings = self.check(ds(
            [{"stage_number": 1, "cancelled": True}], []))
        self.assertEqual(errors, [])
        self.assertTrue(any("all 1 race(s) cancelled" in w for w in warnings), warnings)

    def test_a_partially_cancelled_season_with_no_riders_is_still_an_error(self):
        errors, _ = self.check(ds(
            [{"stage_number": 1, "cancelled": True}, {"stage_number": 2}], []))
        self.assertIn("no riders", errors)

    def test_duplicate_stage_numbers_are_an_error(self):
        errors, _ = self.check(ds(
            [{"stage_number": 1}, {"stage_number": 1}],
            [{"id": "rider/a", "byStage": [sp(1)]}]))
        self.assertIn("duplicate stage_number in stages list", errors)

    def test_byStage_referencing_an_unknown_stage_is_an_error(self):
        errors, _ = self.check(ds(
            [{"stage_number": 1}],
            [{"id": "rider/a", "byStage": [sp(1), sp(7)]}]))
        self.assertTrue(any("references unknown stage 7" in e for e in errors), errors)

    def test_byStage_must_be_strictly_ascending(self):
        """The frontend walks byStage in order and reads the last element as
        'latest'; an out-of-order array silently mis-reports the finish."""
        errors, _ = self.check(ds(
            [{"stage_number": 1}, {"stage_number": 2}],
            [{"id": "rider/a", "byStage": [sp(2), sp(1)]}]))
        self.assertTrue(any("not strictly ascending" in e for e in errors), errors)

    def test_a_repeated_stage_is_not_ascending_either(self):
        errors, _ = self.check(ds(
            [{"stage_number": 1}],
            [{"id": "rider/a", "byStage": [sp(1), sp(1)]}]))
        self.assertTrue(any("not strictly ascending" in e for e in errors), errors)

    def test_cumulative_points_may_not_decrease(self):
        errors, _ = self.check(ds(
            [{"stage_number": 1}, {"stage_number": 2}],
            [{"id": "rider/a", "byStage": [sp(1, cumulativePoints=30),
                                           sp(2, cumulativePoints=10)]}]))
        self.assertTrue(any("cumulativePoints decreases 30->10" in e for e in errors), errors)

    def test_cumulative_kom_points_may_not_decrease(self):
        errors, _ = self.check(ds(
            [{"stage_number": 1}, {"stage_number": 2}],
            [{"id": "rider/a", "byStage": [sp(1, cumulativeKomPoints=30),
                                           sp(2, cumulativeKomPoints=10)]}]))
        self.assertTrue(any("cumulativeKomPoints decreases 30->10" in e for e in errors), errors)

    def test_a_null_cumulative_reads_as_zero_not_as_a_decrease(self):
        """Points are NULL before a rider scores; treating that as a drop from
        the running total would fail every clean year."""
        errors, _ = self.check(ds(
            [{"stage_number": 1}, {"stage_number": 2}],
            [{"id": "rider/a", "byStage": [sp(1, cumulativePoints=None),
                                           sp(2, cumulativePoints=5)]}]))
        self.assertEqual(errors, [])

    def test_a_duplicate_sprint_rank_within_a_stage_warns(self):
        _, warnings = self.check(ds(
            [{"stage_number": 1}],
            [{"id": "rider/a", "byStage": [sp(1, sprintRank=3)]},
             {"id": "rider/b", "byStage": [sp(1, sprintRank=3)]}]))
        self.assertTrue(any("duplicate sprintRank #3" in w for w in warnings), warnings)

    def test_ranks_are_unique_False_suppresses_the_rank_warnings(self):
        """Aggregate sets share ranks legitimately across their constituent
        races, so the check is switched off rather than filtered afterwards."""
        _, warnings = self.check(ds(
            [{"stage_number": 1}],
            [{"id": "rider/a", "byStage": [sp(1, sprintRank=3)]},
             {"id": "rider/b", "byStage": [sp(1, sprintRank=3)]}]),
            ranks_are_unique=False)
        self.assertEqual(warnings, [])

    def test_a_duplicate_finalRank_among_finishers_warns(self):
        _, warnings = self.check(ds(
            [{"stage_number": 1}],
            [{"id": "rider/a", "finalRank": 1, "byStage": [sp(1)]},
             {"id": "rider/b", "finalRank": 1, "byStage": [sp(1)]}]))
        self.assertTrue(any("duplicate finalRank #1" in w for w in warnings), warnings)

    def test_the_9999_DNF_sentinel_duplicates_freely(self):
        _, warnings = self.check(ds(
            [{"stage_number": 1}],
            [{"id": "rider/a", "finalRank": 9999, "byStage": [sp(1)]},
             {"id": "rider/b", "finalRank": 9999, "byStage": [sp(1)]}]))
        self.assertEqual(warnings, [])

    def test_finalRank_is_only_checked_for_riders_who_reached_the_end(self):
        """A rider who abandoned keeps whatever rank they held; comparing it
        against a finisher's is meaningless."""
        _, warnings = self.check(ds(
            [{"stage_number": 1}, {"stage_number": 2}],
            [{"id": "rider/a", "finalRank": 1, "byStage": [sp(1), sp(2)]},
             {"id": "rider/b", "finalRank": 1, "byStage": [sp(1)]}]))
        self.assertEqual(warnings, [])


# ══════════════════════════════════════════════════════════════════════════
# validate_gc — stage alignment against bikeraceinfo
# ══════════════════════════════════════════════════════════════════════════

def bri(*distances):
    return [{"distance_km": d} for d in distances]


class SequentialMapTest(unittest.TestCase):
    """
    Our stage list and bikeraceinfo's do not line up: they disagree about
    prologues, split days and cancelled stages. Mapping them wrong compares
    stage N against stage N+1 for the rest of the race and reports every one
    as a mismatch.
    """
    def test_equal_counts_map_straight_through(self):
        self.assertEqual(validate_gc.build_sequential_map(bri(100, 200, 300),
                                                          bri(100, 200, 300)),
                         {0: 0, 1: 1, 2: 2})

    def test_a_longer_reference_maps_only_what_we_have(self):
        self.assertEqual(validate_gc.build_sequential_map(bri(100, 200, 300),
                                                          bri(100, 200)),
                         {0: 0, 1: 1})

    def test_one_extra_db_stage_is_skipped_where_the_distances_say_it_is(self):
        """The skip position is chosen by distance alignment, not assumed to be
        the end — a prologue we hold and BRI does not sits at the FRONT."""
        self.assertEqual(validate_gc.build_sequential_map(bri(100, 200, 300),
                                                          bri(100, 999, 200, 300)),
                         {0: 0, 1: 2, 2: 3})

    def test_the_extra_stage_can_be_the_first_one(self):
        self.assertEqual(validate_gc.build_sequential_map(bri(100, 200, 300),
                                                          bri(999, 100, 200, 300)),
                         {0: 1, 1: 2, 2: 3})

    def test_several_missing_stages_fall_back_to_distance_matching(self):
        """Counts differing by more than one leaves the fast path entirely."""
        self.assertEqual(validate_gc.build_sequential_map(bri(100, 300),
                                                          bri(100, 150, 200, 250, 300)),
                         {0: 0, 1: 4})

    def test_a_stage_matching_nothing_falls_back_to_sequential(self):
        """The 10% tolerance is what stops a desperate match. With no DB stage
        close to 500 km, taking the nearest anyway would jump to the last stage
        and strand everything between; sequential is the honest guess."""
        self.assertEqual(
            validate_gc.build_sequential_map(bri(100, 500), bri(100, 200, 300, 400)),
            {0: 0, 1: 1})

    def test_distance_matching_never_maps_backwards(self):
        """Each search starts after the last match. Searching from the top
        instead would let a later BRI stage claim an EARLIER DB stage whenever
        the distances happen to line up better there — here BRI's 100 km second
        stage would snap back to DB index 0 and invert the whole comparison."""
        mapping = validate_gc.build_sequential_map(
            bri(200, 100), bri(100, 200, 300, 400))
        self.assertEqual(mapping, {0: 1, 1: 2})
        self.assertEqual(list(mapping.values()), sorted(mapping.values()))

    def test_repeated_distances_are_consumed_one_at_a_time(self):
        mapping = validate_gc.build_sequential_map(
            bri(100, 100, 100), bri(100, 100, 100, 100))
        self.assertEqual(sorted(mapping.values()), sorted(set(mapping.values())))
        self.assertEqual(list(mapping.values()), sorted(mapping.values()))

    def test_alignment_score_is_the_fraction_within_7_percent(self):
        self.assertEqual(validate_gc._alignment_score(bri(100, 200), bri(100, 200),
                                                      {0: 0, 1: 1}), 1.0)
        self.assertEqual(validate_gc._alignment_score(bri(100, 200), bri(999, 888),
                                                      {0: 0, 1: 1}), 0.0)
        self.assertEqual(validate_gc._alignment_score(bri(100, 200), bri(100, 888),
                                                      {0: 0, 1: 1}), 0.5)

    def test_alignment_score_ignores_pairs_it_cannot_compare(self):
        """A zero or missing distance is no evidence either way; counting it as
        a miss would make a sparse edition look mis-aligned."""
        self.assertEqual(validate_gc._alignment_score(
            [{"distance_km": 100}, {"distance_km": None}],
            [{"distance_km": 100}, {"distance_km": 0}], {0: 0, 1: 1}), 1.0)


class GcNameMatchTest(unittest.TestCase):
    def test_accents_and_case_are_ignored(self):
        self.assertTrue(validate_gc.name_match("Tadej Pogačar", "POGACAR Tadej"))

    def test_a_subset_of_tokens_matches(self):
        self.assertTrue(validate_gc.name_match("Bernard Hinault",
                                               "Bernard Hinault Jr"))

    def test_the_last_name_fallback_matches_on_a_long_shared_token(self):
        """validate_gc accepts a long shared token where validate_kom does not:
        the GC references print initials, so 'B. Hinault' has to reach
        'Bernard Hinault'."""
        self.assertTrue(validate_gc.name_match("B Hinault", "Bernard Hinault"))

    def test_a_short_shared_token_is_not_enough(self):
        """Guarding the fallback: 'Van' and 'De' are shared by half the peloton."""
        self.assertFalse(validate_gc.name_match("Van Aert", "Van Vleuten"))

    def test_an_empty_name_never_matches(self):
        self.assertFalse(validate_gc.name_match("", "Bernard Hinault"))


# ══════════════════════════════════════════════════════════════════════════
# validate_kom
# ══════════════════════════════════════════════════════════════════════════

class KomNormalizeTest(unittest.TestCase):
    def test_accents_punctuation_and_case_are_stripped(self):
        self.assertEqual(validate_kom.normalize("  Tadej  POGAČAR-Jr.  "),
                         "tadej pogacar jr")

    def test_kom_name_match_requires_a_full_token_subset(self):
        """Unlike validate_gc, no last-name fallback: the KOM references print
        full names, so a lone shared surname would pair up teammates."""
        self.assertTrue(validate_kom.name_match("Richard Virenque", "VIRENQUE Richard"))
        self.assertFalse(validate_kom.name_match("B Hinault", "Bernard Hinault"))


class KomCompareTest(unittest.TestCase):
    def test_an_exact_agreement_is_a_full_match_rate(self):
        r = validate_kom.compare("wikipedia", [("Richard Virenque", 279)],
                                 [("VIRENQUE Richard", 279)])
        self.assertEqual(r["match_rate"], 100)
        self.assertEqual(r["mismatches"], [])
        self.assertEqual(r["missing"], [])

    def test_a_small_disagreement_still_counts_as_a_match(self):
        """Under 5%: the references round and drop stages, and failing on that
        would bury the real disagreements."""
        r = validate_kom.compare("wikipedia", [("Richard Virenque", 100)],
                                 [("VIRENQUE Richard", 104)])
        self.assertEqual(r["match_rate"], 100)
        self.assertEqual(r["matches"][0]["pct_off"], 4.0)

    def test_a_large_disagreement_is_a_mismatch_carrying_both_figures(self):
        r = validate_kom.compare("wikipedia", [("Richard Virenque", 100)],
                                 [("VIRENQUE Richard", 150)])
        self.assertEqual(r["match_rate"], 0)
        self.assertEqual(r["mismatches"][0]["ref_pts"], 100)
        self.assertEqual(r["mismatches"][0]["our_pts"], 150)
        self.assertEqual(r["mismatches"][0]["diff"], 50)

    def test_a_rider_we_do_not_have_is_missing_not_mismatched(self):
        """The distinction matters: a mismatch is a points disagreement, a
        missing rider means the classification itself is incomplete."""
        r = validate_kom.compare("wikipedia", [("Richard Virenque", 279)],
                                 [("PANTANI Marco", 200)])
        self.assertEqual(r["missing"], [{"name": "Richard Virenque", "ref_pts": 279}])
        self.assertEqual(r["match_rate"], 0)

    def test_an_empty_reference_does_not_divide_by_zero(self):
        r = validate_kom.compare("wikipedia", [], [("VIRENQUE Richard", 279)])
        self.assertEqual(r["match_rate"], 0)

    def test_a_zero_point_reference_does_not_divide_by_zero(self):
        r = validate_kom.compare("wikipedia", [("Richard Virenque", 0)],
                                 [("VIRENQUE Richard", 0)])
        self.assertEqual(r["match_rate"], 100)


class TestStruckThroughRanks(unittest.TestCase):
    """PCS marks an annulled result by striking the rank, keeping the number.

    Every scraper here strips HTML tags, so <s>&nbsp;1&nbsp;</s> and a live
    "1" both became rank 1 and the DB grew two rank-1 finishers on one stage.
    audit_disqualifications.py reads the marker the tag-stripping threw away.
    """

    PAGE = """
    <table class="results">
      <thead><tr><th>Rnk</th><th>GC</th><th>Timelag</th><th>Rider</th></tr></thead>
      <tbody>
        <tr><td><s>&nbsp;1&nbsp;</s></td><td></td><td></td>
            <td><a href="rider/hippolyte-aucouturier">AUCOUTURIER</a></td></tr>
        <tr><td>1</td><td>1</td><td>+0:00</td>
            <td><a href="rider/henri-cornet">CORNET</a></td></tr>
        <tr><td>3</td><td>2</td><td>+5:08</td>
            <td><a href="rider/francois-beaugendre">BEAUGENDRE</a></td></tr>
        <tr><td><s>&nbsp;4&nbsp;</s></td><td></td><td></td>
            <td><a href="rider/lucien-pothier">POTHIER</a></td></tr>
      </tbody>
    </table>"""

    def test_finds_only_the_struck_riders(self):
        got = audit_disqualifications.struck_riders(self.PAGE)
        self.assertEqual(got, [("rider/hippolyte-aucouturier", "1"),
                               ("rider/lucien-pothier", "4")])

    def test_the_rider_awarded_the_win_is_not_flagged(self):
        # Cornet shares the displayed rank 1 with a disqualified man. Catching
        # him too would annul the result the UVF actually awarded him.
        slugs = [s for s, _ in audit_disqualifications.struck_riders(self.PAGE)]
        self.assertNotIn("rider/henri-cornet", slugs)

    def test_no_results_table_is_not_read_as_nobody_disqualified(self):
        # The distinction that keeps a fetch failure from looking like a clean
        # page: None means "could not tell", [] means "checked, none struck".
        self.assertIsNone(audit_disqualifications.struck_riders("<html></html>"))
        self.assertEqual(
            audit_disqualifications.struck_riders(
                '<table class="results"><thead><tr><th>Rnk</th></tr></thead>'
                '<tbody><tr><td>1</td><td><a href="rider/x">X</a></td></tr>'
                '</tbody></table>'), [])


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_orphan_riders — rows nothing references
# ══════════════════════════════════════════════════════════════════════════

class OrphanRiderTest(DBCheckTest):
    """826 rider rows accumulated over three weeks with no check noticing.

    Re-sourcing The Traka from PCS on 2026-08-24 replaced each edition's
    results, and every rider the timers had listed and PCS had not was left
    behind. Nothing downstream complains, because an unreferenced rider is
    never exported — which is exactly why the DB has to say so itself. They
    were found by reading data_provenance by hand; this check is what makes
    that unnecessary next time.
    """

    def assertWarningMatching(self, fragment):
        joined = "\n".join(validate_db.warnings)
        self.assertIn(fragment, joined,
                      f"no warning containing {fragment!r}; warnings were {validate_db.warnings}")

    def test_a_rider_with_no_results_warns(self):
        self.race(1, "Tour de France")
        self.edition(1, 1, 2020)
        self.stage(1, 1, 1)
        self.result(1, "rider/has-a-result")
        self.rider("rider/stranded")
        validate_db.check_orphan_riders(self.cur)
        self.assertWarningMatching("1 rider row(s) have no stage_results")
        self.assertWarningMatching("rider/stranded")

    def test_it_names_the_script_that_stranded_them(self):
        """The trail is the point: script + date range is what turns 'there are
        orphans' into 'this run made them'."""
        self.rider("rider/stranded")
        self.prov("riders", "rider/stranded", "full_name", "sportmaniacs",
                  script="ingest_gravel.py")
        validate_db.check_orphan_riders(self.cur)
        self.assertWarningMatching("ingest_gravel.py")

    def test_a_clean_database_says_nothing(self):
        self.race(1, "Tour de France")
        self.edition(1, 1, 2020)
        self.stage(1, 1, 1)
        self.result(1, "rider/has-a-result")
        validate_db.check_orphan_riders(self.cur)
        self.assertEqual(validate_db.warnings, [])

    def test_it_is_a_warning_and_never_an_error(self):
        """A rider with no results is not corrupt — it is a row whose reason for
        existing went away. Failing the build on it would block every legitimate
        re-source."""
        self.rider("rider/stranded")
        validate_db.check_orphan_riders(self.cur)
        self.assertNoErrors()


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_gravel_rank_integrity — a classification against its clock
# ══════════════════════════════════════════════════════════════════════════

class GravelRankIntegrityTest(DBCheckTest):
    """Leadville 2016 stores 43 finishers and calls one of them 804th.

    The gravel scraper reads a rider's place from Athlinks' `primary` ranking
    on the documented assumption that a row fetched from a division's results
    carries its rank IN that division. Leadville 2016 disproves it: `primary`
    there tracks the overall field, so the stored classification runs
    1, 2, 3, 4, 5, 6, 8 ... 804. Nothing noticed for as long as the data has
    existed, because no check ever compared a classification against either its
    own size or its own clock.
    """

    def assertWarningMatching(self, fragment):
        joined = "\n".join(validate_db.warnings)
        self.assertIn(fragment, joined,
                      f"no warning containing {fragment!r}; warnings were {validate_db.warnings}")

    def gravel_edition(self, year, rows, race_id=9, edition_id=9, stage_id=9):
        """rows = [(rank, finish_seconds), ...]"""
        self.race(race_id, "Leadville Trail 100 MTB", race_type="gravel", country="USA")
        self.edition(edition_id, race_id, year)
        self.stage(stage_id, edition_id, 1)
        for i, (rank, secs) in enumerate(rows):
            self.result(stage_id, f"rider/r{i}", stage_rank=rank,
                        finish_time_seconds=secs, status="FINISHED")

    def test_a_rank_past_the_size_of_the_field_warns(self):
        self.gravel_edition(2016, [(1, 100), (2, 200), (804, 300)])
        validate_db.check_gravel_rank_integrity(self.cur)
        self.assertWarningMatching("past the size of the field")
        self.assertWarningMatching("ranked up to 804")

    def test_the_report_leads_with_the_worst_RATIO_not_the_worst_rank(self):
        """A field we merely store a subset of overshoots slightly; a field whose
        numbers are not places at all overshoots hugely. Sorting by absolute rank
        would bury the second behind the first."""
        self.gravel_edition(2016, [(1, 100), (2, 200), (804, 300)])
        self.race(8, "The Traka 360", race_type="gravel", country="Spain")
        self.edition(8, 8, 2025)
        self.stage(8, 8, 1)
        for i, rank in enumerate([1, 2, 3, 4, 900]):     # bigger max, tiny ratio
            self.result(8, f"rider/t{i}", stage_rank=rank,
                        finish_time_seconds=100 * (i + 1), status="FINISHED")
        for i in range(600):
            self.result(8, f"rider/pad{i}", stage_rank=None,
                        finish_time_seconds=None, status="FINISHED")
        validate_db.check_gravel_rank_integrity(self.cur)
        joined = "\n".join(validate_db.warnings)
        self.assertLess(joined.index("804"), joined.index("900"),
                        "the 268x edition must be reported before the 180x one")

    def test_a_finisher_ranked_ahead_of_a_faster_one_warns(self):
        self.gravel_edition(2017, [(1, 100), (2, 200), (3, 150)])
        validate_db.check_gravel_rank_integrity(self.cur)
        self.assertWarningMatching("out of clock order")

    def test_one_misplaced_rider_counts_as_one_not_as_every_pair(self):
        """Enrique Saborio is a single bad row at Leadville 2017, but he is
        faster than twelve riders ranked above him. Counting pairs would report
        one defect as twelve and make the number meaningless."""
        rows = [(i + 1, 1000 + i * 10) for i in range(12)]   # clean 1..12
        rows.append((13, 1))                                 # one row, wildly fast
        self.gravel_edition(2017, rows)
        validate_db.check_gravel_rank_integrity(self.cur)
        self.assertWarningMatching("1 gravel finisher(s)")
        # The pair count for this fixture is 12. If the check ever reports that
        # instead, the number has stopped meaning "rows that are wrong".
        self.assertNotIn("12 gravel finisher(s)", "\n".join(validate_db.warnings))

    def test_a_clean_edition_says_nothing(self):
        self.gravel_edition(2015, [(i + 1, 100 * (i + 1)) for i in range(10)])
        validate_db.check_gravel_rank_integrity(self.cur)
        self.assertEqual(validate_db.warnings, [])

    def test_a_ranked_row_with_no_time_does_not_count_as_disorder(self):
        """The row that actually exercises the NULL guard is a RANKED one with
        no clock — 11 time trials and a scatter of gravel rows are exactly that.
        A DNF would not do: it has no rank either, so the query never sees it.
        Treating the NULL as 0 would sort that rider to the front and report the
        whole edition as out of order."""
        self.gravel_edition(2019, [(1, 100), (2, 200), (3, 300)])
        self.result(9, "rider/no-clock", stage_rank=4, finish_time_seconds=None,
                    status="FINISHED")
        validate_db.check_gravel_rank_integrity(self.cur)
        self.assertEqual(validate_db.warnings, [])

    def test_it_is_a_warning_and_never_an_error(self):
        """The values are what Athlinks served. The repair is a scraper change
        and a re-ingest, not something a validator should fail the build over."""
        self.gravel_edition(2016, [(1, 100), (804, 300)])
        validate_db.check_gravel_rank_integrity(self.cur)
        self.assertNoErrors()


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_field_definition — what a rank is a rank OVER
# ══════════════════════════════════════════════════════════════════════════

class FieldDefinitionTest(DBCheckTest):
    """Every off-road edition must say which slice of the field it ranks.

    Leadville's timer began publishing a pro category in 2016 and the scraper
    followed it, so rank 3 went from "third man across the line" to "third PRO,
    with other men finishing between them" with nothing recording the change.
    Four of the six gravel races switch rule at least once.
    """

    def gravel_stage(self, field_definition, cancelled=0, race_type="gravel"):
        self.race(1, "Leadville Trail 100 MTB", race_type=race_type, country="USA")
        self.edition(1, 1, 2016)
        self.stage(1, 1, 1, cancelled=cancelled, field_definition=field_definition)

    def test_a_raced_edition_with_no_field_definition_is_an_ERROR(self):
        """An ERROR and not a warning: a rank nobody can interpret is not a
        known upstream limit, it is a value the database cannot explain."""
        self.gravel_stage(None)
        validate_db.check_field_definition(self.cur)
        self.assertTrue(validate_db.errors)
        self.assertIn("which field their ranks are over",
                      "\n".join(validate_db.errors))

    def test_an_empty_string_counts_as_MISSING_not_as_unrecognised(self):
        """Asserting the specific message, because "" trips the unknown-value
        branch too and merely checking that SOMETHING errored passes whether or
        not the missing check handles it. An empty string is an ingest that
        wrote nothing, and saying "unrecognised field_definition ''" sends the
        reader looking for a rule that does not exist."""
        self.gravel_stage("")
        validate_db.check_field_definition(self.cur)
        joined = "\n".join(validate_db.errors)
        self.assertIn("which field their ranks are over", joined)
        self.assertNotIn("unrecognised", joined)

    def test_a_known_value_is_accepted(self):
        for rule in ("open_field", "elite_course", "elite_division", "pcs_field"):
            with self.subTest(rule=rule):
                validate_db.errors = []
                self.cur.execute("DELETE FROM stages")
                self.cur.execute("DELETE FROM race_editions")
                self.cur.execute("DELETE FROM races")
                self.gravel_stage(rule)
                validate_db.check_field_definition(self.cur)
                self.assertEqual(validate_db.errors, [])

    def test_an_unknown_value_is_an_ERROR(self):
        """A rule the frontend cannot label reaches a reader as an unexplained
        rank, and nothing else would notice."""
        self.gravel_stage("elite_division_v2")
        validate_db.check_field_definition(self.cur)
        self.assertIn("unrecognised", "\n".join(validate_db.errors))

    def test_a_cancelled_edition_needs_none(self):
        """A race that was not run has no field for a rank to be over."""
        self.gravel_stage(None, cancelled=1)
        validate_db.check_field_definition(self.cur)
        self.assertEqual(validate_db.errors, [])

    def test_a_ROAD_stage_carrying_one_is_an_ERROR(self):
        """A Grand Tour stage has exactly one field. A value there is a
        mis-write, and it would teach a reader the column means something it
        does not."""
        self.gravel_stage("open_field", race_type="stage_race")
        validate_db.check_field_definition(self.cur)
        self.assertIn("nothing to disambiguate", "\n".join(validate_db.errors))

    def test_the_live_database_records_one_for_every_raced_edition(self):
        """The invariant against real data, not a fixture."""
        import os, sqlite3
        if not os.path.exists(validate_db.DB_PATH):
            # cycling.db is gitignored and CI cannot regenerate it.
            self.skipTest("no database")
        conn = sqlite3.connect(f"file:{validate_db.DB_PATH}?mode=ro", uri=True)
        self.addCleanup(conn.close)
        missing = conn.execute(
            """SELECT COUNT(*) FROM stages s
                 JOIN race_editions re ON re.edition_id = s.edition_id
                 JOIN races ra ON ra.race_id = re.race_id
                WHERE ra.race_type='gravel' AND s.cancelled=0
                  AND (s.field_definition IS NULL OR s.field_definition='')""").fetchone()[0]
        self.assertEqual(missing, 0)


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_gc_rank_gap_consistency — one position, two gaps
# ══════════════════════════════════════════════════════════════════════════

class GcRankGapConsistencyTest(DBCheckTest):
    """A GC rank IS a position on aggregate time, so riders sharing one share
    the gap that produced it. Rows that share a rank while disagreeing about the
    gap are self-contradictory: one number is wrong and nothing downstream can
    tell which.

    A shared rank alone is ordinary — Tour 1948 stage 1 has ten riders sharing
    3rd on one time, which is what a bunch finish looks like. Only the
    disagreeing gap is a fault, which is why this groups first and compares
    second. Checking for duplicate ranks instead would report 1,025 groups,
    almost all of them correct.
    """

    def assertWarningMatching(self, fragment):
        joined = "\n".join(validate_db.warnings)
        self.assertIn(fragment, joined, f"warnings were {validate_db.warnings}")

    def setup_stage(self):
        self.race(1, "Tour de France")
        self.edition(1, 1, 1983)
        self.stage(1, 1, 1)

    def test_a_genuine_tie_is_not_reported(self):
        """Ten riders on one time sharing third place is a bunch finish."""
        self.setup_stage()
        for i in range(10):
            self.result(1, f"rider/t{i}", gc_rank=3, gc_gap_seconds=90)
        validate_db.check_gc_rank_gap_consistency(self.cur)
        self.assertEqual(validate_db.warnings, [])
        self.assertEqual(validate_db.notes, [])

    def test_one_position_with_two_gaps_warns(self):
        self.setup_stage()
        self.result(1, "rider/a", gc_rank=7, gc_gap_seconds=36)
        self.result(1, "rider/b", gc_rank=7, gc_gap_seconds=0)
        validate_db.check_gc_rank_gap_consistency(self.cur)
        self.assertWarningMatching("below rank 1")
        self.assertWarningMatching("36s apart")

    def test_rank_1_is_a_NOTE_not_a_warning(self):
        """At rank 1 this is the annulment shape: PCS lists the stripped rider
        and the promoted one together, the promoted one keeping the gap he had
        to the man ahead. Correct as stored, so it must not read as a fault."""
        self.setup_stage()
        self.result(1, "rider/stripped", gc_rank=1, gc_gap_seconds=0, disqualified=1)
        self.result(1, "rider/promoted", gc_rank=1, gc_gap_seconds=370)
        validate_db.check_gc_rank_gap_consistency(self.cur)
        self.assertEqual(validate_db.warnings, [])
        self.assertIn("annulment", "\n".join(validate_db.notes))

    def test_a_null_gap_is_not_a_disagreement(self):
        """An unknown gap is not a second opinion about the same rank.

        SQL's COUNT(DISTINCT) already skips NULLs, so this passes with or
        without the explicit IS NOT NULL in the query — it pins the BEHAVIOUR
        (an unknown gap raises nothing) rather than the clause that states it."""
        self.setup_stage()
        self.result(1, "rider/a", gc_rank=5, gc_gap_seconds=90)
        self.result(1, "rider/b", gc_rank=5, gc_gap_seconds=None)
        validate_db.check_gc_rank_gap_consistency(self.cur)
        self.assertEqual(validate_db.warnings, [])

    def test_the_same_rank_in_two_STAGES_is_not_a_disagreement(self):
        """Gaps are only comparable within one stage. Rank 5 on stage 1 and rank
        5 on stage 2 are different positions in different classifications, and
        grouping without the stage would report every race in the archive."""
        self.setup_stage()
        self.stage(2, 1, 2)
        self.result(1, "rider/a", gc_rank=5, gc_gap_seconds=90)
        self.result(2, "rider/b", gc_rank=5, gc_gap_seconds=400)
        validate_db.check_gc_rank_gap_consistency(self.cur)
        self.assertEqual(validate_db.warnings, [])

    def test_different_ranks_are_never_compared(self):
        self.setup_stage()
        self.result(1, "rider/a", gc_rank=5, gc_gap_seconds=90)
        self.result(1, "rider/b", gc_rank=6, gc_gap_seconds=20)
        validate_db.check_gc_rank_gap_consistency(self.cur)
        self.assertEqual(validate_db.warnings, [])

    def test_it_is_a_warning_and_never_an_error(self):
        """The values are PCS's own and deciding which of two gaps is right
        needs the source page, not a rule."""
        self.setup_stage()
        self.result(1, "rider/a", gc_rank=7, gc_gap_seconds=36)
        self.result(1, "rider/b", gc_rank=7, gc_gap_seconds=0)
        validate_db.check_gc_rank_gap_consistency(self.cur)
        self.assertNoErrors()


# ══════════════════════════════════════════════════════════════════════════
# validate_db.check_gc_gap_monotonicity — a ladder that runs backwards
# ══════════════════════════════════════════════════════════════════════════

class GcGapMonotonicityTest(DBCheckTest):
    """The GC is the ranking of aggregate time, so the gap can only grow as the
    rank grows. A later rank stored closer to the leader is arithmetically
    impossible, whatever happened in the race.

    This is the wider view of GcRankGapConsistencyTest above, not a replacement
    for it: that one needs two riders to collide on one rank, which most
    corruption never does (49 stages against 342), while a tie whose two gaps
    both sit inside the surrounding window keeps this ladder ascending (14
    stages it cannot see). test_a_self_contradicting_tie_can_still_ascend pins
    that the two checks really are independent.
    """

    def assertWarningMatching(self, fragment):
        joined = "\n".join(validate_db.warnings)
        self.assertIn(fragment, joined, f"warnings were {validate_db.warnings}")

    def setup_stage(self, stage_id=1, number=1):
        if stage_id == 1:
            self.race(1, "Tour de France")
            self.edition(1, 1, 1983)
        self.stage(stage_id, 1, number)

    def ladder(self, stage_id, gaps, start=1, **kw):
        """Ranks start..start+n-1 carrying `gaps` in order."""
        for i, gap in enumerate(gaps):
            self.result(stage_id, f"rider/s{stage_id}r{start + i}",
                        gc_rank=start + i, gc_gap_seconds=gap, **kw)

    def test_an_ascending_ladder_is_silent(self):
        self.setup_stage()
        self.ladder(1, [0, 12, 12, 40, 300])
        validate_db.check_gc_gap_monotonicity(self.cur)
        self.assertEqual(validate_db.warnings, [])

    def test_a_backwards_step_warns(self):
        """Rank 4 is 300s down and rank 5 only 40s: one of them is wrong."""
        self.setup_stage()
        self.ladder(1, [0, 12, 12, 300, 40])
        validate_db.check_gc_gap_monotonicity(self.cur)
        self.assertWarningMatching("runs backwards")
        self.assertWarningMatching("rank 4 is 300s down, rank 5 only 40s")

    def test_the_count_is_STAGES_not_steps(self):
        """A stage whose ladder is scrambled holds many backwards steps, and
        reporting each would make one broken stage look like twenty. The unit of
        repair is the stage — its whole ladder gets re-fetched — so the unit of
        the report is the stage, and only its worst step is quoted."""
        self.setup_stage()
        self.ladder(1, [0, 900, 10, 800, 20, 700])
        validate_db.check_gc_gap_monotonicity(self.cur)
        self.assertEqual(len(validate_db.warnings), 1)
        self.assertWarningMatching("1 stage(s)")
        # 900 -> 10 is the deepest drop, so it is the one quoted.
        self.assertWarningMatching("rank 2 is 900s down, rank 3 only 10s")

    def test_rank_1_may_step_backwards(self):
        """The annulment shape: PCS lists the stripped rider and the promoted
        one both at rank 1, the promoted rider keeping the gap he had to the man
        ahead. The step out of that pair is expected, not a fault.

        Run twice, and the UNFLAGGED case is the one that matters: only 4 of the
        5 rank-1 pairs in the archive hold a row marked `disqualified`, so on the
        fifth the disqualified exemption does not apply and the rank-1 clause is
        the only thing standing between it and a false report."""
        for flagged in (True, False):
            with self.subTest(flagged=flagged):
                self.setUp()
                self.setup_stage()
                self.result(1, "rider/stripped", gc_rank=1, gc_gap_seconds=0,
                            disqualified=1 if flagged else 0)
                # The promoted rider's 370s is his gap to the STRIPPED rider,
                # while rank 2's 100s is measured from the promoted rider who
                # now leads. Two baselines in one ladder, so it steps backwards.
                self.result(1, "rider/promoted", gc_rank=1, gc_gap_seconds=370)
                self.result(1, "rider/third", gc_rank=2, gc_gap_seconds=100)
                validate_db.check_gc_gap_monotonicity(self.cur)
                self.assertEqual(validate_db.warnings, [])

    def test_a_disqualified_row_is_exempt_on_either_side(self):
        """A stripped rider keeps the classification he was removed from, so a
        step into or out of his row says nothing about the rows around it."""
        for dq_rank in (5, 6):
            with self.subTest(dq_rank=dq_rank):
                self.setUp()
                self.setup_stage()
                self.ladder(1, [0, 10, 20, 30], start=1)
                self.result(1, "rider/x", gc_rank=5, gc_gap_seconds=900,
                            disqualified=1 if dq_rank == 5 else 0)
                self.result(1, "rider/y", gc_rank=6, gc_gap_seconds=40,
                            disqualified=1 if dq_rank == 6 else 0)
                validate_db.check_gc_gap_monotonicity(self.cur)
                self.assertEqual(validate_db.warnings, [])

    def test_a_self_contradicting_tie_can_still_ascend(self):
        """Why the tie check is not redundant. Rank 3 holds 20s and 25s — one of
        them is wrong — but both fall between rank 2's 12s and rank 4's 30s, so
        the ladder never steps backwards and this check is blind to it."""
        self.setup_stage()
        self.result(1, "rider/a", gc_rank=1, gc_gap_seconds=0)
        self.result(1, "rider/b", gc_rank=2, gc_gap_seconds=12)
        self.result(1, "rider/c", gc_rank=3, gc_gap_seconds=20)
        self.result(1, "rider/d", gc_rank=3, gc_gap_seconds=25)
        self.result(1, "rider/e", gc_rank=4, gc_gap_seconds=30)
        validate_db.check_gc_gap_monotonicity(self.cur)
        self.assertEqual(validate_db.warnings, [])
        validate_db.check_gc_rank_gap_consistency(self.cur)
        self.assertWarningMatching("below rank 1")

    def test_a_tie_is_ordered_by_gap_before_comparing(self):
        """Two gaps on one rank are not themselves a backwards step: sorting the
        stage by (rank, gap) puts the smaller first, so a tie is only counted
        here when it disagrees with its NEIGHBOURS. Without that ordering every
        self-contradicting tie would be double-reported by both checks."""
        self.setup_stage()
        self.result(1, "rider/a", gc_rank=1, gc_gap_seconds=0)
        self.result(1, "rider/b", gc_rank=2, gc_gap_seconds=25)
        self.result(1, "rider/c", gc_rank=2, gc_gap_seconds=20)
        self.result(1, "rider/d", gc_rank=3, gc_gap_seconds=30)
        validate_db.check_gc_gap_monotonicity(self.cur)
        self.assertEqual(validate_db.warnings, [])

    def test_stages_are_compared_separately(self):
        """Gaps are only comparable inside one classification. Without the
        per-stage split, every stage that opened tighter than the last one
        closed would read as a fault."""
        self.setup_stage(1, 1)
        self.setup_stage(2, 2)
        self.ladder(1, [0, 600])
        self.ladder(2, [0, 30])
        validate_db.check_gc_gap_monotonicity(self.cur)
        self.assertEqual(validate_db.warnings, [])

    def test_a_null_gap_breaks_nothing(self):
        """An unrecorded gap is not a claim about order, and treating NULL as 0
        would make every stage holding one look like it ran backwards."""
        self.setup_stage()
        self.result(1, "rider/a", gc_rank=1, gc_gap_seconds=0)
        self.result(1, "rider/b", gc_rank=2, gc_gap_seconds=None)
        self.result(1, "rider/c", gc_rank=3, gc_gap_seconds=30)
        validate_db.check_gc_gap_monotonicity(self.cur)
        self.assertEqual(validate_db.warnings, [])

    def test_it_is_a_warning_and_never_an_error(self):
        """It says the pair cannot both be right, never which one to keep --
        rank is not recoverable from gap (equal times take different ranks on a
        tiebreak we do not store) and gap is not recoverable from rank. That
        needs the source page, so this is a worklist, not a gate."""
        self.setup_stage()
        self.ladder(1, [0, 300, 40])
        validate_db.check_gc_gap_monotonicity(self.cur)
        self.assertNoErrors()


# ══════════════════════════════════════════════════════════════════════════
# audit_gc_ladders — which ROW of a backwards ladder is the wrong one
# ══════════════════════════════════════════════════════════════════════════

class GcLadderTriageTest(unittest.TestCase):
    """validate_db says a ladder runs backwards; this says which row to check.

    It never says what the row should hold. Rank is not recoverable from gap
    (riders on equal time take different ranks on a tiebreak we do not store)
    and gap is not recoverable from rank, so the most the ladder can do is
    implicate a row and bound it. These tests pin that limit as hard as they
    pin the detection: a verdict that named a VALUE would be fabricating one.
    """

    def ladder(self, *pairs):
        """(rank, gap) pairs -> the (rank, gap, disqualified, rider_id) rows
        classify() takes, already in its (rank, gap) order."""
        return [(rk, gap, 0, f"rider/r{i}") for i, (rk, gap) in enumerate(pairs)]

    def test_an_ascending_ladder_has_no_verdict(self):
        v, suspects, window = audit_gc_ladders.classify(
            self.ladder((1, 0), (2, 10), (3, 10), (4, 90)))
        self.assertIsNone(v)
        self.assertEqual(suspects, [])

    def test_the_later_row_is_named_when_only_it_explains_the_step(self):
        """Tour 1978 st8 in miniature: rank 3 is 289s down and rank 4 stores 4s,
        with rank 5 at 304s. Dropping rank 4 leaves a clean ladder and dropping
        rank 3 does not, so rank 4 is the row carrying the contradiction."""
        v, suspects, window = audit_gc_ladders.classify(
            self.ladder((1, 0), (2, 10), (3, 289), (4, 4), (5, 304)))
        self.assertEqual(v, "ONE ROW")
        self.assertEqual([(s[0], s[1]) for s in suspects], [(4, 4)])
        self.assertEqual(window, (289, 304))

    def test_the_earlier_row_is_named_when_only_it_explains_the_step(self):
        """The mirror image, and not a case the obvious implementation gets
        right: reading the step left-to-right and always blaming the second row
        would convict rank 3 here, which is the one good value in the pair."""
        v, suspects, window = audit_gc_ladders.classify(
            self.ladder((1, 0), (2, 500), (3, 10), (4, 20)))
        self.assertEqual(v, "ONE ROW")
        self.assertEqual([(s[0], s[1]) for s in suspects], [(2, 500)])
        self.assertEqual(window, (0, 10))

    def test_a_window_stays_open_at_the_end_of_the_ladder(self):
        """A stored classification usually stops short of the full field, so a
        suspect in the last row has nothing above it. The bound is then one
        sided, and claiming a closed range would invent the upper end."""
        v, suspects, window = audit_gc_ladders.classify(
            self.ladder((1, 0), (2, 10), (3, 300), (4, 5)))
        self.assertEqual(v, "ONE ROW")
        self.assertEqual(window, (300, None))

    def test_PAIR_when_either_row_would_explain_it(self):
        """Both removals leave a clean ladder, so the evidence does not choose.
        Calling this ONE ROW would send someone to check an innocent row."""
        v, suspects, window = audit_gc_ladders.classify(
            self.ladder((1, 0), (2, 50), (3, 20), (4, 100)))
        self.assertEqual(v, "PAIR")
        self.assertEqual([(s[0], s[1]) for s in suspects], [(2, 50), (3, 20)])
        self.assertIsNone(window)

    def test_LADDER_when_several_steps_run_backwards(self):
        v, suspects, _ = audit_gc_ladders.classify(
            self.ladder((1, 0), (2, 90), (3, 10), (4, 80), (5, 20)))
        self.assertEqual(v, "LADDER")
        self.assertEqual(suspects, [])

    def test_LADDER_when_one_step_but_neither_row_explains_it(self):
        """One backwards step does not mean one bad row. Here the corruption
        spans the pair — removing either leaves the ladder still descending —
        so the classification has to be re-fetched rather than one cell fixed."""
        v, suspects, _ = audit_gc_ladders.classify(
            self.ladder((1, 0), (2, 10), (3, 50), (4, 5), (5, 7)))
        self.assertEqual(v, "LADDER")
        self.assertEqual(suspects, [])

    def test_the_annulment_step_out_of_rank_1_is_not_triaged(self):
        """PCS lists the stripped and the promoted rider together at rank 1 and
        the promoted one keeps his old gap, so the ladder legitimately steps
        backwards leaving that pair. Triaging it would send someone to check a
        row that is correct as stored."""
        v, _, _ = audit_gc_ladders.classify(
            self.ladder((1, 0), (1, 370), (2, 100)))
        self.assertIsNone(v)

    def test_a_disqualified_row_is_exempt_on_either_side(self):
        for dq_at in (0, 1):
            with self.subTest(dq_at=dq_at):
                rows = self.ladder((1, 0), (2, 500), (3, 10))
                rows[1 + dq_at] = rows[1 + dq_at][:2] + (1,) + rows[1 + dq_at][3:]
                self.assertIsNone(audit_gc_ladders.classify(rows)[0])

    # ── the two-interleaved-classifications signature ───────────────────────

    def test_a_rank_holding_two_ladders_is_flagged(self):
        """Tour 1987 st1 stores rank 15 twice: once at 23s with gc_rank copied
        from stage_rank, once at the real 30s. That is a ladder to remove, not
        a value to correct, so it is counted apart."""
        self.assertEqual(
            audit_gc_ladders.mirror_ranks({15: [(23, 15), (30, 73)]}), [15])

    def test_a_bunch_finish_is_not_two_ladders(self):
        """On a flat opening stage every rider legitimately holds
        gc_rank == stage_rank on one time. Matching that alone would flag the
        cleanest stages in the archive."""
        self.assertEqual(audit_gc_ladders.mirror_ranks({7: [(0, 7), (0, 7)]}), [])

    def test_two_real_rows_on_one_rank_are_not_two_ladders(self):
        """Two riders stored on one rank with different gaps is the tie
        contradiction validate_db.check_gc_rank_gap_consistency reports, and it
        is a different repair. The interleaving signature needs one of the two
        to have had its rank copied from the stage result — without that, this
        is one ladder with a bad cell in it."""
        self.assertEqual(
            audit_gc_ladders.mirror_ranks({15: [(30, 73), (31, 80)]}), [])

    def test_one_row_on_a_rank_is_never_two_ladders(self):
        self.assertEqual(audit_gc_ladders.mirror_ranks({7: [(0, 7)]}), [])
        self.assertEqual(audit_gc_ladders.mirror_ranks({7: [(25, 73)]}), [])
