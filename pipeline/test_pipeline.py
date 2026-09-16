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
import shutil
import sqlite3
import tempfile
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import race_common as rc
from audit_stage_counts import norm
import backfill_bib_numbers
from backfill_source_slugs import slugs_for_edition
from detect_name_swaps import _bib_check
from race_common import (
    StageRow,
    to_iso_date,
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
    def test_rejects_any_length_but_15_or_16(self):
        """Real bug: ingest silently skipped short rows, losing Marco Haller's
        2026 stage-2 result. The schema must reject, not truncate.

        16 became legal on 2026-09-11, when a field was added for PCS's
        struck-through rank. 15 stays legal because every scrape file on disk
        has 15 — the protection this test exists for is against a row that is
        neither, which is a malformed extraction."""
        for n in (0, 13, 14, 17):
            with self.assertRaises(ValueError, msg=f"{n} fields must be refused"):
                StageRow.from_list(["1"] * n)
        self.assertEqual(StageRow.from_list(row("21", "A", "rider/a")).bib, "21")
        self.assertEqual(StageRow.from_list(["1"] * 16).dsq, "1")

    def test_a_legacy_row_reads_as_marker_unknown(self):
        """A 15-field row predates the field. Empty means UNKNOWN, not
        "this rider was not disqualified" — the whole reason ingest keeps a
        stored marker rather than letting a legacy file clear it."""
        self.assertEqual(StageRow.from_list(row("21", "A", "rider/a")).dsq, "")

    def test_roundtrip_normalises_a_legacy_row_to_the_current_length(self):
        r = row("21", "A", "rider/a")
        self.assertEqual(len(r), 15)
        out = StageRow.from_list(r).to_list()
        self.assertEqual(len(out), 16)
        self.assertEqual(out[:15], r, "the first 15 fields must be untouched")
        self.assertEqual(out[15], "", "and the added marker means unknown")

    def test_roundtrip_is_exact_for_a_current_row(self):
        r = row("21", "A", "rider/a") + ["1"]
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

class TestIsoDates(unittest.TestCase):
    """race_common.to_iso_date — one date format in the database, not three.

    PCS writes "30 June 1949" on older pages. Ingest tried an ISO strptime,
    failed, and stored the raw string, so 68 stages across the 1931, 1933 and
    1949 Tours held a date that sorts as text: "01 July" before "30 June".
    backfill_source_slugs derives split-day slugs from these dates, so the
    format is not cosmetic.
    """

    def test_the_format_pcs_uses_on_old_pages(self):
        self.assertEqual(to_iso_date("30 June 1949"), "1949-06-30")
        self.assertEqual(to_iso_date("27 Jun 1933"), "1933-06-27")

    def test_an_iso_date_passes_through(self):
        self.assertEqual(to_iso_date("1949-06-30"), "1949-06-30")

    def test_an_unparseable_date_is_None_not_the_raw_string(self):
        """None on purpose: a date nobody can parse is not a date, and storing
        it anyway is what produced a column that cannot be ordered."""
        for junk in ("nonsense", "", None, "June 1949", "30/06/1949"):
            self.assertIsNone(to_iso_date(junk), junk)

    def test_normalised_dates_sort_chronologically(self):
        """The property that was actually broken."""
        raw = ["30 June 1931", "01 July 1931", "02 July 1931"]
        iso = [to_iso_date(d) for d in raw]
        self.assertEqual(iso, sorted(iso))
        self.assertNotEqual(raw, sorted(raw), "the raw strings sort wrongly, which was the bug")


class TestSwapManifest(unittest.TestCase):
    """fix_name_swaps.record_swaps — the record that survives a re-scrape.

    The repair is written into the scrape file, and PCS reproduces the swap on
    every request, so re-fetching a repaired stage undoes it silently. The
    manifest is what makes that recoverable.
    """

    def setUp(self):
        import fix_name_swaps
        self.mod = fix_name_swaps
        self.tmp = tempfile.mkdtemp()
        self._orig = fix_name_swaps.MANIFEST
        fix_name_swaps.MANIFEST = os.path.join(self.tmp, "swaps.json")

    def tearDown(self):
        self.mod.MANIFEST = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    PAIR = ("tour", 2009, 19, "156", "192", "Pineau Jérôme", "Beppu Fumiyuki")

    def test_a_pair_is_recorded_with_the_names_it_should_end_up_with(self):
        self.assertEqual(self.mod.record_swaps([self.PAIR]), 1)
        swaps = self.mod.load_manifest()["swaps"]
        self.assertEqual(len(swaps), 1)
        self.assertEqual((swaps[0]["year"], swaps[0]["stage"], swaps[0]["bib_a"],
                          swaps[0]["name_a"]), (2009, 19, "156", "Pineau Jérôme"))

    def test_reapplying_does_not_duplicate(self):
        self.mod.record_swaps([self.PAIR])
        self.assertEqual(self.mod.record_swaps([self.PAIR]), 0)
        self.assertEqual(len(self.mod.load_manifest()["swaps"]), 1)

    def test_the_same_pair_named_from_the_other_side_is_the_same_pair(self):
        """Which bib the detector calls A depends on row order, and a re-scrape
        can reverse it. Recording both would replay the swap twice — back to
        where it started."""
        self.mod.record_swaps([self.PAIR])
        mirrored = ("tour", 2009, 19, "192", "156", "Beppu Fumiyuki", "Pineau Jérôme")
        self.assertEqual(self.mod.record_swaps([mirrored]), 0)
        self.assertEqual(len(self.mod.load_manifest()["swaps"]), 1)

    def test_a_different_stage_is_a_different_pair(self):
        self.mod.record_swaps([self.PAIR])
        other = ("tour", 2009, 20, "156", "192", "Pineau Jérôme", "Beppu Fumiyuki")
        self.assertEqual(self.mod.record_swaps([other]), 1)
        self.assertEqual(len(self.mod.load_manifest()["swaps"]), 2)


class TestBibBackfillScope(unittest.TestCase):
    """backfill_bib_numbers — the guard, and how far it reaches.

    A rider carrying two numbers in one edition makes "the rider's bib
    elsewhere" ambiguous THERE. The guard used to be global, so six such
    rider-editions in the 1931 and 1933 Tours blocked the tool for every race
    and every year — including the 7,647 TTT bibs a re-ingest of 1960-2025 has
    to put back.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        schema = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
        with open(schema, encoding="utf-8") as f:
            self.conn.executescript(f.read())
        cur = self.conn.cursor()
        cur.execute("INSERT INTO races (race_id, name, country, race_type) "
                    "VALUES (1,'Tour de France','France','stage_race')")
        for rider in ("rider/ambiguous", "rider/clean"):
            cur.execute("INSERT INTO riders (rider_id, full_name) VALUES (?,?)",
                        (rider, rider))
        # 1931: one rider wears two numbers. 1985: the ordinary case, with a
        # TTT row whose bib the parser could not read.
        for year, eid in ((1931, 1), (1985, 2)):
            cur.execute("INSERT INTO race_editions (edition_id, race_id, year) "
                        "VALUES (?,1,?)", (eid, year))
            for n in (1, 2):
                cur.execute("INSERT INTO stages (edition_id, stage_number, route_type) "
                            "VALUES (?,?,?)", (eid, n, "TTT" if n == 2 else "F"))
        def result(stage_number, edition_id, rider, bib):
            sid = cur.execute("SELECT stage_id FROM stages WHERE edition_id=? AND "
                              "stage_number=?", (edition_id, stage_number)).fetchone()[0]
            cur.execute("INSERT INTO stage_results (stage_id, rider_id, bib_number) "
                        "VALUES (?,?,?)", (sid, rider, bib))
        result(1, 1, "rider/ambiguous", 11)
        result(2, 1, "rider/ambiguous", 77)      # the same rider, a second number
        result(1, 2, "rider/clean", 55)
        result(2, 2, "rider/clean", None)        # the TTT row to fill
        self.conn.commit()
        self.cur = self.conn.cursor()

    def tearDown(self):
        self.conn.close()

    def test_the_ambiguous_edition_is_reported(self):
        bad = backfill_bib_numbers.violations(self.cur)
        self.assertEqual([(b["year"], b["rider_id"]) for b in bad],
                         [(1931, "rider/ambiguous")])

    def test_a_clean_edition_is_filled_even_so(self):
        skip = {b["edition_id"] for b in backfill_bib_numbers.violations(self.cur)}
        rows = backfill_bib_numbers.fillable(self.cur, "tour", sorted(skip))
        self.assertEqual([(r["year"], r["rider_id"], r["val"]) for r in rows],
                         [(1985, "rider/clean", 55)])

    def test_nothing_is_written_to_the_ambiguous_edition(self):
        """The invariant still holds where it is actually in doubt: 1931 gets
        no bib, however the rest of the run goes."""
        skip = sorted({b["edition_id"]
                       for b in backfill_bib_numbers.violations(self.cur)})
        rows = backfill_bib_numbers.fillable(self.cur, "tour", skip)
        self.assertNotIn(1931, [r["year"] for r in rows])

    def test_the_same_machinery_fills_a_team(self):
        """A rider carries one number and rides for one team for a whole
        edition, so both columns obey the same edition-scoped invariant. The
        gaps differ in origin — team_id's come from the GC sidecar supplying a
        rider for a stage PCS does not list him on, which inserts a position
        with no team — but the repair is the same one."""
        cur = self.cur
        sid = cur.execute("SELECT stage_id FROM stages WHERE edition_id=2 AND "
                          "stage_number=2").fetchone()[0]
        cur.execute("UPDATE stage_results SET team_id=NULL WHERE stage_id=?", (sid,))
        cur.execute("INSERT INTO teams (team_id, name) VALUES ('team/x-1985','X')")
        cur.execute("UPDATE stage_results SET team_id='team/x-1985' WHERE stage_id="
                    "(SELECT stage_id FROM stages WHERE edition_id=2 AND stage_number=1)")
        rows = backfill_bib_numbers.fillable(self.cur, "tour", (), "team_id")
        self.assertEqual([(r["year"], r["rider_id"], r["val"]) for r in rows],
                         [(1985, "rider/clean", "team/x-1985")])

    def test_a_rider_with_two_teams_in_one_edition_is_refused(self):
        """kelme-1980 and kelme-gios-1980 are PCS spelling the same team two
        ways inside one race. Nothing says which is canonical, so the edition is
        skipped rather than resolved by MIN()."""
        cur = self.cur
        cur.execute("INSERT INTO teams (team_id, name) VALUES ('team/kelme-1980','K')")
        cur.execute("INSERT INTO teams (team_id, name) VALUES ('team/kelme-gios-1980','K')")
        for n, team in ((1, "team/kelme-1980"), (2, "team/kelme-gios-1980")):
            cur.execute("UPDATE stage_results SET team_id=? WHERE stage_id="
                        "(SELECT stage_id FROM stages WHERE edition_id=1 AND stage_number=?)",
                        (team, n))
        bad = backfill_bib_numbers.violations(self.cur, "team_id")
        self.assertIn(1931, [b["year"] for b in bad])

    def test_without_the_skip_list_the_ambiguous_bib_would_be_guessed(self):
        """Why the skip list exists rather than nothing at all: MIN() would
        hand 1931 an arbitrary one of that rider's two numbers."""
        rows = backfill_bib_numbers.fillable(self.cur, "tour")
        self.assertEqual([r["year"] for r in rows], [1985],
                         "1931's rows are already bibbed, so only the shape of "
                         "the query is under test here")


if __name__ == "__main__":
    unittest.main(verbosity=2)

class TestDerivedFinalStagePoints(unittest.TestCase):
    """derive_final_stage_points.py — the guards, which is all that file is."""

    def _derive(self, after, before):
        """The write rule, exercised through the module's own logic."""
        import derive_final_stage_points as D
        both, out, neg, over = {}, {}, [], []
        for rider, total in after.items():
            if rider in before:
                d = total - before[rider]
                if d > 0:
                    both[rider] = d
                elif d < 0:
                    neg.append(rider)
        ceiling = max(both.values()) if both else 0
        out.update(both)
        for rider, total in after.items():
            if rider not in before:
                if 0 < total <= ceiling:
                    out[rider] = total
                elif total > ceiling:
                    over.append(rider)
                else:
                    neg.append(rider)
        return out, neg, over

    def test_a_negative_total_is_never_written(self):
        """PCS lists riders on a NEGATIVE classification total when a jury
        penalty exceeds their points — Giro 2016 has two on -5. Writing one as
        a stage award makes the cumulative curve decrease, which
        validate_exports reports as an error. It did, before this guard."""
        out, neg, _ = self._derive(
            {"a": 40, "b": 20, "penalised": -5}, {"a": 10, "b": 5})
        self.assertNotIn("penalised", out)
        self.assertIn("penalised", neg)
        self.assertTrue(all(v > 0 for v in out.values()))

    def test_a_rider_over_the_observed_ceiling_is_refused(self):
        """Absent from the previous standings means either a first score or a
        truncated table, and the two are indistinguishable per rider. The
        ceiling is the largest award among riders we CAN verify."""
        out, _, over = self._derive({"a": 40, "b": 20, "huge": 167}, {"a": 10, "b": 5})
        self.assertEqual(max(out.values()), 30)      # a: 40-10
        self.assertIn("huge", over)
        self.assertNotIn("huge", out)

    def test_no_baseline_yields_nothing(self):
        """With no previous standings every delta is the rider's whole-race
        total. The 1986 Giro publishes none, and this would have credited
        Bontempi with 167 points on the final day — his entire season in that
        race. The caller skips the kind entirely; nothing is derivable."""
        out, _, _ = self._derive({"a": 167, "b": 148}, {})
        self.assertEqual(out, {}, "a missing baseline must never mean zero")

