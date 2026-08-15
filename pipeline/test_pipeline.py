#!/usr/bin/env python3
"""
Regression tests for the pipeline's pure logic.

Run:  python3 -m unittest test_pipeline -v      (from pipeline/)
      python3 test_pipeline.py

Stdlib unittest, no dependencies — the pipeline is pure-stdlib Python and
should stay runnable with nothing installed.

Almost every case here encodes a bug that actually reached the database. The
functions are small and pure, which is exactly why they were easy to get wrong
and never noticed: a wrong stage number or a dropped identity produces
plausible-looking data, not a crash. Where a test corresponds to a real
incident it says so, so the case isn't "simplified" away later.
"""

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import race_common as rc
from audit_stage_counts import norm
from backfill_source_slugs import slugs_for_edition
from detect_name_swaps import _bib_check
from race_common import (
    StageRow,
    assign_stage_numbers,
    detect_route_type,
    parse_bonus_seconds,
    parse_int,
    parse_time_to_seconds,
    parse_year_args,
    swap_identity,
)


def row(bib, name, slug, nat="it", rnk="1", team="Team A", team_slug="team/a"):
    """A 15-field scrape row in StageRow order."""
    return [rnk, "", "", bib, "28", name, slug, nat, team, team_slug,
            "", "", "", "", ""]


class TestAssignStageNumbers(unittest.TestCase):
    """race_common.assign_stage_numbers — the slug -> stage_number mapping."""

    def test_plain_sequence(self):
        pairs, err = assign_stage_numbers(["stage-1", "stage-2", "stage-3"])
        self.assertIsNone(err)
        self.assertEqual(pairs, [(1, "stage-1"), (2, "stage-2"), (3, "stage-3")])

    def test_split_day_gets_distinct_numbers(self):
        """Real bug: the old regex dropped the [a-d] suffix, so stage-3a and
        stage-3b both wrote stage_3.json and the second silently overwrote the
        first — one stage lost per split day, on 68 Vuelta and 111 TDF days."""
        pairs, err = assign_stage_numbers(
            ["stage-1", "stage-2", "stage-3a", "stage-3b", "stage-4"])
        self.assertIsNone(err)
        self.assertEqual(pairs, [(1, "stage-1"), (2, "stage-2"), (3, "stage-3a"),
                                 (4, "stage-3b"), (5, "stage-4")])
        self.assertEqual(len({n for n, _ in pairs}), 5, "numbers must be unique")

    def test_prologue_takes_zero_and_must_come_first(self):
        pairs, err = assign_stage_numbers(["prologue", "stage-1", "stage-2"])
        self.assertIsNone(err)
        self.assertEqual(pairs[0], (0, "prologue"))
        self.assertEqual(pairs[1], (1, "stage-1"))
        _, err = assign_stage_numbers(["stage-1", "prologue"])
        self.assertIsNotNone(err)

    def test_gap_aborts_rather_than_shifting(self):
        """Real bug: 2010 Vuelta. discover_stages dropped PCS stages 11 and 12,
        and positional numbering shifted 13-21 down to 11-19 — silently wrong
        rather than visibly missing. A gap must be a hard error."""
        pairs, err = assign_stage_numbers(["stage-1", "stage-2", "stage-4"])
        self.assertEqual(pairs, [])
        self.assertIn("gap", err)

    def test_orphan_and_misordered_substages_rejected(self):
        self.assertNotEqual(assign_stage_numbers(["stage-1", "stage-2b"])[1], None)
        self.assertNotEqual(assign_stage_numbers(["stage-1a", "stage-1c"])[1], None)

    def test_unparseable_slug_rejected(self):
        _, err = assign_stage_numbers(["stage-1", "final"])
        self.assertIn("unparseable", err)


class TestStageRow(unittest.TestCase):
    def test_requires_exactly_15_fields(self):
        """Real bug: ingest silently skipped short rows, losing Marco Haller's
        2026 stage-2 result. The schema must reject, not truncate."""
        with self.assertRaises(ValueError):
            StageRow.from_list(["1"] * 14)
        with self.assertRaises(ValueError):
            StageRow.from_list(["1"] * 16)
        self.assertEqual(StageRow.from_list(row("21", "A", "rider/a")).bib, "21")

    def test_roundtrip(self):
        r = row("21", "A", "rider/a")
        self.assertEqual(StageRow.from_list(r).to_list(), r)

    def test_field_order_matches_scrape_format(self):
        sr = StageRow.from_list(row("21", "Merckx Eddy", "rider/eddy-merckx", nat="be"))
        self.assertEqual((sr.bib, sr.name, sr.slug, sr.nat),
                         ("21", "Merckx Eddy", "rider/eddy-merckx", "be"))


class TestSwapIdentity(unittest.TestCase):
    def test_swaps_identity_only(self):
        """The PCS artifact transposes name/slug/nat between adjacent rows and
        nothing else — bib, team, times stay correctly bound. Verified across
        all 71 instances found: bib->team binding was intact 71/71."""
        a = row("1", "Merckx Eddy", "rider/eddy-merckx", nat="be", team="Molteni")
        b = row("72", "Battaglin Giovanni", "rider/giovanni-battaglin",
                nat="it", team="Jolly Ceramica")
        swap_identity(a, b)
        sa, sb = StageRow.from_list(a), StageRow.from_list(b)
        self.assertEqual(sa.name, "Battaglin Giovanni")
        self.assertEqual(sb.name, "Merckx Eddy")
        self.assertEqual(sa.nat, "it")
        self.assertEqual(sb.nat, "be")
        # everything else must be untouched
        self.assertEqual((sa.bib, sa.team), ("1", "Molteni"))
        self.assertEqual((sb.bib, sb.team), ("72", "Jolly Ceramica"))

    def test_swap_is_its_own_inverse(self):
        a = row("1", "A", "rider/a", nat="be")
        b = row("2", "B", "rider/b", nat="fr")
        before = (list(a), list(b))
        swap_identity(a, b)
        swap_identity(a, b)
        self.assertEqual((a, b), before)


class TestParsers(unittest.TestCase):
    def test_parse_time_to_seconds(self):
        self.assertEqual(parse_time_to_seconds("1:00"), 60)
        self.assertEqual(parse_time_to_seconds("1:00:00"), 3600)
        self.assertEqual(parse_time_to_seconds("+0:37"), 37)
        for junk in ("", None, "-", ",,", ",", "abc", "0"):
            self.assertIsNone(parse_time_to_seconds(junk), junk)

    def test_parse_bonus_seconds(self):
        self.assertEqual(parse_bonus_seconds("10"), 10)
        self.assertEqual(parse_bonus_seconds("-6"), -6)
        self.assertEqual(parse_bonus_seconds(""), 0)
        self.assertEqual(parse_bonus_seconds(None), 0)

    def test_parse_int(self):
        self.assertEqual(parse_int("42"), 42)
        self.assertEqual(parse_int("-3"), -3)
        for junk in ("DNF", "", None, "1a", "3.5"):
            self.assertIsNone(parse_int(junk), junk)

    def test_detect_route_type_prefers_won_how(self):
        self.assertEqual(detect_route_type("p1", "Team time trial"), "TTT")
        self.assertEqual(detect_route_type("p4", "Time trial"), "TT")
        self.assertEqual(detect_route_type("p4", "Sprint of large group"), "M")
        self.assertEqual(detect_route_type("p1", ""), "F")
        self.assertEqual(detect_route_type(None, None), "F")

    def test_parse_year_args_handles_ranges_and_flags(self):
        self.assertEqual(parse_year_args(["1990"]), [1990])
        self.assertEqual(parse_year_args(["1990-1992"]), [1990, 1991, 1992])
        self.assertEqual(parse_year_args(["--dry-run", "2020"]), [2020])
        self.assertEqual(parse_year_args(["--race", "giro"]), [])


class TestRouteNorm(unittest.TestCase):
    """audit_stage_counts.norm — route comparison across two spellings.

    Every stage repair in this pipeline is keyed on matching a DB route against
    PCS's, because stage numbers are the unreliable part. A route that fails to
    match is not a harmless miss: it leaves a correct slug unconfirmable and
    pushes the stage into the leftover-pairing fallback.
    """

    def test_accents_and_punctuation_ignored(self):
        self.assertEqual(norm("Saint-Pol-de-Léon"), norm("Saint Pol de Leon"))
        self.assertEqual(norm("Córdoba"), norm("Cordoba"))

    def test_saint_abbreviations_match(self):
        """The DB writes "St Malo", PCS writes "Saint-Malo". Six TDF stages in
        1973-1976 stayed unconfirmable on this alone."""
        self.assertEqual(norm("St Malo - Caen"), norm("Saint-Malo - Caen"))
        self.assertEqual(norm("Ste Foy la Grande"), norm("Sainte-Foy-la-Grande"))
        self.assertEqual(norm("St. Etienne"), norm("Saint-Étienne"))

    def test_expansion_happens_before_punctuation_is_stripped(self):
        """Order matters: strip punctuation first and "St Malo" becomes
        "stmalo", where "st" is no longer a token to expand."""
        self.assertTrue(norm("St Malo").startswith("saint"))

    def test_does_not_expand_st_inside_a_word(self):
        self.assertEqual(norm("Stavelot"), "stavelot")
        self.assertEqual(norm("Sestriere"), "sestriere")

    def test_distinct_routes_stay_distinct(self):
        self.assertNotEqual(norm("Pau - Luchon"), norm("Luchon - Pau"))
        self.assertNotEqual(norm("St Malo - Caen"), norm("St Malo - Rouen"))


class TestStageTitle(unittest.TestCase):
    """race_common.parse_stage_title / apply_stage_title.

    PCS's info panel reports "Distance: 0 km" for a long tail of older stages
    and leaves "Won how" empty, so the headline is the only place the distance
    and the (ITT)/(TTT) marker appear. Missing it left 44 time trials stored as
    flat road stages and 9 stages with no distance at all.
    """

    TT = ('<title>Tour de France 1970 Stage 23 (ITT) results</title>'
          '<div class="title-line2 hideIfMobile"><font class="blue">Stage 23 (ITT) '
          '(Final)</font> &nbsp; &raquo; &nbsp; <font class="red">Versailles '
          '&nbsp;&rsaquo;&nbsp; Paris</font> &nbsp; <font class="red">(54km)</font></div>')
    ROAD = ('<title>Tour de France 1968 Stage 22a results</title>'
            '<div class="title-line2 hideIfMobile"><font class="blue">Stage 22a</font>'
            ' &nbsp; &raquo; &nbsp; <font class="red">Auxerre &nbsp;&rsaquo;&nbsp; '
            'Melun</font> &nbsp; <font class="red">(136km)</font></div>')

    def test_reads_distance_and_tt_marker(self):
        t = rc.parse_stage_title(self.TT)
        self.assertEqual(t["distance_km"], 54.0)
        self.assertEqual(t["tt_kind"], "ITT")

    def test_road_stage_has_no_marker(self):
        t = rc.parse_stage_title(self.ROAD)
        self.assertEqual(t["distance_km"], 136.0)
        self.assertIsNone(t["tt_kind"],
                          "a road stage must not be read as a time trial")

    def test_decimal_distance(self):
        html = self.TT.replace("(54km)", "(29.3km)")
        self.assertEqual(rc.parse_stage_title(html)["distance_km"], 29.3)

    def test_marker_must_be_bracketed_and_in_the_headline(self):
        """Two ways to get this wrong, both of which mislabel a road stage.

        A real PCS road page mentions its siblings — the 1968 stage-22a page
        links "Stage 22b (ITT)" in its stage picker — so the search has to be
        scoped to the headline, not the document. And it has to require the
        brackets: 'ITT' as a bare substring appears in ordinary words and in
        markup attributes."""
        with_sibling = self.ROAD + '<div class="pick">Stage 22b (ITT)</div>'
        self.assertIsNone(rc.parse_stage_title(with_sibling)["tt_kind"],
                          "a sibling stage's marker must not leak in")
        stray = self.ROAD.replace("Melun</font>", "Melun SPLITTING</font>")
        self.assertIsNone(rc.parse_stage_title(stray)["tt_kind"],
                          "an unbracketed substring is not a marker")

    def test_distance_must_come_from_the_headline(self):
        """PCS pages carry other stages' distances in navigation and related
        links; a document-wide '(NNkm)' search can pick up the wrong one."""
        decoy = '<p>previous stage (246.5km)</p>'
        self.assertEqual(rc.parse_stage_title(decoy + self.TT)["distance_km"], 54.0)

    def test_missing_title_is_not_an_error(self):
        t = rc.parse_stage_title("<html><body>nothing here</body></html>")
        self.assertIsNone(t["distance_km"])
        self.assertIsNone(t["tt_kind"])

    def test_fills_a_zero_distance(self):
        info = {"Distance": "0 km"}
        rc.apply_stage_title(info, self.TT)
        self.assertEqual(info["Distance"], "54.0 km")
        self.assertEqual(info["DistanceSource"], "pcs-title")

    def test_a_real_scraped_distance_wins(self):
        """The headline is the fallback, never the override — PCS's 1986 Tour
        stage-23 headline repeats stage 16's distance."""
        info = {"Distance": "136 km"}
        rc.apply_stage_title(info, self.TT)
        self.assertEqual(info["Distance"], "136 km")
        self.assertNotIn("DistanceSource", info)

    def test_won_how_evidence_beats_the_marker(self):
        info = {"Distance": "54 km", "Won how": "Sprint of small group"}
        rc.apply_stage_title(info, self.TT)
        self.assertNotIn("TitleTT", info,
                         "must not retype a stage whose result already says how it was won")

    def test_marker_surfaces_when_won_how_is_a_dash(self):
        info = {"Distance": "54 km", "Won how": "-"}
        rc.apply_stage_title(info, self.TT)
        self.assertEqual(info["TitleTT"], "ITT")


class TestSlugsForEdition(unittest.TestCase):
    """backfill_source_slugs.slugs_for_edition — date-based derivation."""

    @staticmethod
    def stages(*pairs):
        return [{"stage_number": n, "stage_date": d} for n, d in pairs]

    def test_no_split_maps_directly(self):
        m, splits = slugs_for_edition(self.stages((1, "2020-07-01"), (2, "2020-07-02")))
        self.assertEqual(splits, 0)
        self.assertEqual(m, {1: "stage-1", 2: "stage-2"})

    def test_prologue_is_not_stage_zero(self):
        """PCS slugs a prologue 'prologue'; 'stage-0' 404s. It also does not
        consume a numbered slot, so stage 1 stays stage-1."""
        m, _ = slugs_for_edition(self.stages((0, "2020-06-30"), (1, "2020-07-01")))
        self.assertEqual(m[0], "prologue")
        self.assertEqual(m[1], "stage-1")

    def test_refuses_to_guess_on_split_editions(self):
        """Real bug: this used to assume PCS always letters split days, which
        holds for Vuelta 1989 but not TDF 1986/1970/1983-91 or Giro 1953 —
        those number sequentially. Guessing shifted 201 slugs by one. The
        convention must be probed (resolve_source_slugs.py), never derived."""
        m, splits = slugs_for_edition(
            self.stages((1, "2020-07-01"), (2, "2020-07-02"), (3, "2020-07-02")))
        self.assertEqual(splits, 1)
        self.assertEqual(m, {}, "must return no mapping when a split is present")


class TestBibCheck(unittest.TestCase):
    """detect_name_swaps._bib_check — swap vs duplicate-bib classification."""

    def test_clean_year_reports_nothing(self):
        stages = {n: [row("1", "A", "rider/a"), row("2", "B", "rider/b")]
                  for n in (1, 2, 3)}
        self.assertEqual(_bib_check("giro", 2020, stages), [])

    def test_cross_stage_swap_is_flagged(self):
        stages = {
            1: [row("1", "A", "rider/a"), row("2", "B", "rider/b")],
            2: [row("1", "A", "rider/a"), row("2", "B", "rider/b")],
            3: [row("1", "B", "rider/b"), row("2", "A", "rider/a")],  # swapped
        }
        f = _bib_check("giro", 2020, stages)
        self.assertTrue(all(x["type"] == "bib_inconsistency" for x in f))
        self.assertEqual({x["bib"] for x in f}, {"1", "2"})
        self.assertEqual(f[0]["outlier_stages"], [3])

    def test_duplicate_bib_in_one_stage_is_not_a_swap(self):
        """Real bug: two riders sharing a bib (PCS's own 2015 Giro startlist
        reads '92 GRMAY / 92 FERRARI') was reported as a name swap, because the
        per-stage dict overwrote. Both riders and results are correct there —
        renaming either would be fabrication."""
        both = [row("92", "Grmay", "rider/grmay"), row("92", "Ferrari", "rider/ferrari")]
        f = _bib_check("giro", 2015, {n: list(both) for n in (1, 2, 3)})
        self.assertEqual([x["type"] for x in f], ["duplicate_bib"])
        self.assertEqual(sorted(f[0]["riders"]), ["Ferrari", "Grmay"])

    def test_duplicate_bib_excluded_from_swap_check(self):
        stages = {
            1: [row("92", "Grmay", "rider/grmay"), row("92", "Ferrari", "rider/ferrari")],
            2: [row("92", "Ferrari", "rider/ferrari"), row("92", "Grmay", "rider/grmay")],
        }
        f = _bib_check("giro", 2015, stages)
        self.assertNotIn("bib_inconsistency", [x["type"] for x in f])

    def test_verified_collision_is_downgraded(self):
        """giro 1952 bib 104: Fornara and Elio Brasola never appear in the same
        stage, so nothing in the data distinguishes it from a swap. PCS's rider
        page confirms both rode; it's listed as a verified collision."""
        stages = {
            1: [row("104", "Fornara Pasquale", "rider/pasquale-fornara")],
            3: [row("104", "Brasola Elio", "rider/elio-brasola")],
            5: [row("104", "Fornara Pasquale", "rider/pasquale-fornara")],
        }
        f = _bib_check("giro", 1952, stages)
        self.assertEqual([x["type"] for x in f], ["duplicate_bib"])


class TestProvenance(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "schema.sql"), encoding="utf-8") as f:
            self.conn.executescript(f.read())
        self.cur = self.conn.cursor()

    def tearDown(self):
        self.conn.close()

    def test_rejects_unknown_source(self):
        """Sources are a closed vocabulary — a typo must fail loudly rather
        than silently create an unqueryable category."""
        with self.assertRaises(ValueError):
            rc.record_provenance(self.cur, "stages", 1, "vertical_meters", "guessed")

    def test_accepts_every_declared_source(self):
        for i, src in enumerate(sorted(rc.VALID_SOURCES)):
            rc.record_provenance(self.cur, "stages", i, "distance_km", src)
        self.assertEqual(
            self.cur.execute("SELECT COUNT(*) FROM data_provenance").fetchone()[0],
            len(rc.VALID_SOURCES))

    def test_upsert_replaces_not_duplicates(self):
        rc.record_provenance(self.cur, "stages", 1, "vertical_meters",
                             rc.SOURCE_UNKNOWN, source_ref="old")
        rc.record_provenance(self.cur, "stages", 1, "vertical_meters",
                             rc.SOURCE_PCS, source_ref="new")
        rows = self.cur.execute(
            "SELECT source, source_ref FROM data_provenance").fetchall()
        self.assertEqual(rows, [(rc.SOURCE_PCS, "new")])

    def test_bulk_records_each_field(self):
        rc.record_provenance_bulk(self.cur, "stages", 7,
                                  ["vertical_meters", "profile_score"],
                                  rc.SOURCE_PCS, source_ref="stage-3a")
        self.assertEqual(
            {r[0] for r in self.cur.execute(
                "SELECT field FROM data_provenance WHERE entity_id=7")},
            {"vertical_meters", "profile_score"})

    def test_schema_has_no_stage_zero_slug_assumption(self):
        """schema.sql must stay loadable standalone — several tools build a
        scratch DB from it."""
        cols = {r[1] for r in self.cur.execute("PRAGMA table_info(stages)")}
        self.assertIn("source_slug", cols)
        self.assertIn("cancelled", cols)



class TestStageNotes(unittest.TestCase):
    """
    race_common.load_stage_notes — why a stage legitimately has no results.

    A cancelled stage with zero results is byte-identical to a stage nobody has
    scraped yet, so without a record the same handful get re-investigated on
    every audit. Giro 2011 stage 4 is the case that prompted it: ridden as a
    processional tribute to Wouter Weylandt with no classification taken, so no
    result exists to find and none ever will.
    """

    def write(self, obj):
        import json
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "notes.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return p

    def test_flattens_to_race_year_stage_keys(self):
        p = self.write({"Giro d'Italia": {"2011": {"4": {"note": "n"}}}})
        self.assertEqual(rc.load_stage_notes(p), {("Giro d'Italia", 2011, 4): {"note": "n"}})

    def test_year_and_stage_are_ints_not_strings(self):
        """JSON keys are strings; DB rows are ints. Leaving them as strings
        means every lookup misses and the file silently does nothing."""
        (race, year, stage), = rc.load_stage_notes(
            self.write({"R": {"1969": {"21": {}}}}))
        self.assertIsInstance(year, int)
        self.assertIsInstance(stage, int)

    def test_underscore_keys_are_metadata_not_races(self):
        notes = rc.load_stage_notes(self.write({"_README": ["docs"], "R": {"2000": {"1": {}}}}))
        self.assertEqual(list(notes), [("R", 2000, 1)])

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(rc.load_stage_notes("/nonexistent/notes.json"), {})

    def test_shipped_file_documents_the_weylandt_stage(self):
        notes = rc.load_stage_notes()
        entry = notes.get(("Giro d'Italia", 2011, 4))
        self.assertIsNotNone(entry, "the stage this file was created for")
        self.assertIn("Weylandt", entry["note"])

    def test_every_shipped_entry_carries_a_note_and_a_source(self):
        """An entry without a source is a claim nobody can check, and this file
        exists to stop people re-deriving the same answers."""
        for key, entry in rc.load_stage_notes().items():
            self.assertGreater(len(entry.get("note", "")), 20, key)
            self.assertTrue(entry.get("source"), key)

if __name__ == "__main__":
    unittest.main(verbosity=2)
