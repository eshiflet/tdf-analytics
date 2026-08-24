#!/usr/bin/env python3
"""
Regression tests for the gravel/off-road pipeline's pure logic.

Run:  python3 -m unittest test_gravel -v      (from pipeline/)

Same principle as test_pipeline.py: every case here is a way this data can go
wrong QUIETLY. A DNF that keeps its split time outranks the winner, a name
whose case differs between two events becomes two riders, and a top-100 window
that counts DNFs drops real finishers — none of which crash anything.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import os
import sqlite3

import ingest_classics
import ingest_gravel
import scrape_pcs_gravel
import scrape_traka
from resolve_traka_events import pick_360
from race_common import GRAVEL, gravel_route_type
from link_gravel_riders import decide, fold, slugify, tokens
from scrape_athlinks import (
    FIELD_CAP,
    MIN_FIELD_FOR_RELATIVE,
    dedupe,
    implausible,
    resolve_implausible,
    time_floor,
    clean_name,
    division_rank,
    normalize_case,
    row_status,
    select_field,
    split_name,
    to_row,
)


class TestGravelRaceTable(unittest.TestCase):
    def test_seven_races_with_unique_shorts(self):
        self.assertEqual(len(GRAVEL), 7)
        shorts = [i.short for i in GRAVEL.values()]
        self.assertEqual(len(shorts), len(set(shorts)), "x-axis labels must be unique")

    def test_a_race_addressed_by_athlinks_has_a_master_id(self):
        # master_id is optional now that not every gravel race is a Life Time
        # one, and the two must not drift: an athlinks-sourced race with no
        # master id cannot be scraped, and a non-athlinks race with one is
        # claiming an id that addresses nothing.
        for slug, info in GRAVEL.items():
            if info.source == "athlinks":
                self.assertIsNotNone(info.master_id, f"{slug} needs a masterEventId")
            else:
                self.assertIsNone(info.master_id, f"{slug} is not on Athlinks")

    def test_every_gravel_source_is_a_valid_provenance_source(self):
        from race_common import VALID_SOURCES
        for slug, info in GRAVEL.items():
            self.assertIn(info.source, VALID_SOURCES, slug)

    def test_route_type_is_surface_not_climbing(self):
        self.assertEqual(gravel_route_type("gravel"), "G")
        self.assertEqual(gravel_route_type("mtb"), "X")
        # An unknown discipline yields NULL rather than defaulting into the
        # road F/H/M scale, where it would be drawn as a flat road stage.
        self.assertIsNone(gravel_route_type("cyclocross"))


class TestNameNormalisation(unittest.TestCase):
    def test_mojibake_is_repaired(self):
        # Real row: Athlinks serves Andrew L'Esperance's apostrophe as UTF-8
        # bytes decoded through MacRoman.
        self.assertEqual(clean_name("Andrew L‚ÄôEsperance"),
                         "Andrew L’Esperance")

    def test_mojibake_of_accented_letters_is_repaired(self):
        # The E2-lead case above was the only one the first version caught.
        # Every accented LETTER mojibakes through C3, which MacRoman renders
        # as "√" — Unbound 2025 shipped two of them and both survived into
        # the DB, where "Emil √Öberg" was served to the app for weeks.
        self.assertEqual(clean_name("Emil √Öberg"), "Emil Åberg")
        self.assertEqual(clean_name("Lukas L√∂er"), "Lukas Löer")
        # cp1252 is the other renderer of the same bytes; C3 89 -> É.
        self.assertEqual(clean_name("Banque d'Ã‰pargne"), "Banque d'Épargne")

    def test_repair_is_idempotent(self):
        # A scrape partly repaired by an earlier run must not be "fixed" twice.
        for name in ("Emil Åberg", "Lukas Löer", "Andrew L’Esperance"):
            self.assertEqual(clean_name(name), name)

    def test_legitimate_accents_survive(self):
        for name in ("Torbjørn Andre Røed", "Petr Vakoč", "Cécile Lejeune",
                     "Emil Åberg", "Tadej Pogačar", "Jonas Vingegaard",
                     "Chloé Dygert", "Iván García Cortina", "Seán Kelly"):
            self.assertEqual(clean_name(name), name)

    def test_all_lower_and_all_upper_are_title_cased(self):
        # Sea Otter 2026 ships lowercase, Leadville 2026 title case; the same
        # rider must not become two people.
        self.assertEqual(normalize_case("bradyn lange"), "Bradyn Lange")
        self.assertEqual(normalize_case("KEEGAN SWENSON"), "Keegan Swenson")

    def test_mixed_case_is_left_alone(self):
        # "McElveen" only survives by not being touched.
        self.assertEqual(normalize_case("Payson McElveen"), "Payson McElveen")

    def test_lowercase_mc_is_capitalised_inside(self):
        self.assertEqual(normalize_case("payson mcelveen"), "Payson McElveen")

    def test_hyphens_and_apostrophes_capitalise_both_parts(self):
        self.assertEqual(normalize_case("oskar stack-michasiw"), "Oskar Stack-Michasiw")

    def test_split_name_is_particle_aware(self):
        self.assertEqual(split_name("Alexey Vermeulen"), ("Alexey", "Vermeulen"))
        self.assertEqual(split_name("Daniel Van Der Walt"), ("Daniel", "Van Der Walt"))
        self.assertEqual(split_name("Cher"), (None, "Cher"))


class TestFieldSelection(unittest.TestCase):
    @staticmethod
    def row(name, rank, status="CONF", gender="M", ms=3_600_000, div=None):
        r = {"displayName": name, "status": status, "gender": gender,
             "gunTimeInMillis": ms, "chipTimeInMillis": ms,
             "rankings": {"overall": rank}, "id": rank}
        if div:
            r["rankings"]["other"] = [{"id": div, "rank": rank}]
            r["divisions"] = {"primary": 0, "other": [div]}
        return r

    def test_dnf_loses_its_rank(self):
        rows = [self.row("Winner", 1), self.row("Quit", 2, status="DNF")]
        picked = select_field(rows, {"rule": "elite_course", "division_id": None})
        self.assertEqual(picked[0]["_rank"], 1)
        # Athlinks ranks some DNFs anyway; a non-finisher has no position.
        self.assertIsNone(picked[1]["_rank"])

    def test_dnf_time_is_not_stored_as_a_finish(self):
        # The Tsgabu Grmay case: Athlinks fills a DNF's time from the last
        # split, so Leadville 2025 shows him at 1h33 for a 100-miler. Kept, he
        # sorts ahead of the winner.
        r = self.row("Quit", 2, status="DNF", ms=5_580_000)
        r["_rank"] = None
        out = to_row(r, "gun")
        self.assertEqual(out["status"], "DNF")
        self.assertIsNone(out["finish_seconds"])

    def test_women_excluded_when_no_division_marks_the_men(self):
        rows = [self.row("Man", 2), self.row("Woman", 1, gender="F")]
        picked = select_field(rows, {"rule": "elite_course", "division_id": None})
        self.assertEqual([r["displayName"] for r in picked], ["Man"])
        # Re-ranked among men: the men's winner is 1st, not 2nd.
        self.assertEqual(picked[0]["_rank"], 1)

    def test_open_field_window_counts_only_finishers(self):
        rows = ([self.row(f"F{i}", i) for i in range(1, FIELD_CAP + 20)]
                + [self.row("Quit", 500, status="DNF")])
        picked = select_field(rows, {"rule": "open_field", "division_id": None})
        self.assertEqual(len(picked), FIELD_CAP)
        self.assertNotIn("Quit", [r["displayName"] for r in picked])

    def test_finisher_ranks_are_contiguous_despite_dnfs(self):
        # Athlinks numbers non-finishers in its overall ranking (Matej Mohoric
        # DNF'd Unbound 2024 and is overall 42). Numbering every row and
        # blanking the DNFs afterwards left holes: 117 finishers ranked to 130.
        rows = [self.row("A", 1), self.row("Quit", 2, status="DNF"),
                self.row("B", 3), self.row("C", 4)]
        picked = select_field(rows, {"rule": "elite_course", "division_id": None})
        ranks = [r["_rank"] for r in picked if r["_rank"] is not None]
        self.assertEqual(ranks, [1, 2, 3])
        self.assertEqual([r["displayName"] for r in picked][:3], ["A", "B", "C"])

    def test_elite_field_is_never_truncated(self):
        rows = [self.row(f"F{i}", i) for i in range(1, FIELD_CAP + 20)]
        picked = select_field(rows, {"rule": "elite_course", "division_id": None})
        self.assertEqual(len(picked), FIELD_CAP + 19)

    def test_division_rank_is_used_not_overall(self):
        # In a mass-start race the 20th pro is ~200th overall. Storing the
        # overall number would make the pro classification meaningless.
        r = self.row("Pro", 214, div=77)
        r["rankings"]["other"] = [{"id": 77, "rank": 20}]
        self.assertEqual(division_rank(r, 77), 20)
        picked = select_field([r], {"rule": "elite_division",
                                    "divisions_used": [{"id": 77}]})
        self.assertEqual(picked[0]["_rank"], 20)

    def test_primary_rank_is_the_division_rank_when_divisions_is_absent(self):
        # Rows from /division/{id}/results before ~2024 carry no `divisions`
        # object; `rankings.primary` is the rank in the division we asked for.
        r = {"displayName": "Swenson", "status": "CONF",
             "gunTimeInMillis": 14_621_000, "chipTimeInMillis": 14_621_000,
             "rankings": {"overall": 1, "primary": 1}}
        self.assertEqual(division_rank(r, 2069955), 1)

    def test_primary_is_ignored_when_it_names_a_different_division(self):
        r = {"displayName": "Swenson", "rankings": {"primary": 1},
             "divisions": {"primary": 2609315, "other": [2609313]}}
        self.assertIsNone(division_rank(r, 2609313 + 1))

    def test_two_divisions_are_reranked_from_the_clock(self):
        # Leadville 2023 splits its men's field: "Pro Male" ranks John Gaston
        # 1st, "Grand Prix Male" ranks Keegan Swenson 1st, and Swenson won the
        # race. Two independent rank sequences cannot be concatenated, so the
        # union is re-ranked on the clock the divisions were scored by.
        swenson = self.row("Swenson", 1, ms=20_600_000, div=88)
        swenson["rankings"]["other"] = [{"id": 88, "rank": 1}]
        gaston = self.row("Gaston", 3, ms=22_084_000, div=77)
        gaston["rankings"]["other"] = [{"id": 77, "rank": 1}]
        picked = select_field([gaston, swenson],
                              {"rule": "elite_division", "_rank_type": "gun",
                               "divisions_used": [{"id": 77}, {"id": 88}]})
        by_name = {r["displayName"]: r["_rank"] for r in picked}
        self.assertEqual(by_name, {"Swenson": 1, "Gaston": 2})

    def test_gun_or_chip_follows_the_divisions_own_ranktype(self):
        r = self.row("A", 1)
        r["gunTimeInMillis"], r["chipTimeInMillis"] = 7_200_000, 7_000_000
        r["_rank"] = 1
        self.assertEqual(to_row(r, "gun")["finish_seconds"], 7200)
        self.assertEqual(to_row(r, "chip")["finish_seconds"], 7000)


class TestUpstreamDefects(unittest.TestCase):
    """Two ways the source serves rows that are not results of this race."""

    def test_verbatim_duplicate_rows_are_dropped(self):
        # Big Sugar 2023 lists Connor Kamm three times, identical athlete id.
        r = {"id": 62872511, "displayName": "Connor Kamm",
             "chipTimeInMillis": None, "gunTimeInMillis": None}
        self.assertEqual(len(dedupe([dict(r), dict(r), dict(r)])), 1)

    def test_two_finishes_by_one_athlete_are_both_kept(self):
        # Not a duplicate: Chequamegon 2013 gives Brian Matter two DIFFERENT
        # times because two races were merged. dedupe() must not hide that —
        # the speed filter is what separates them.
        a = {"id": 4529691, "displayName": "Brian Matter",
             "chipTimeInMillis": 7_429_000, "gunTimeInMillis": 7_429_000}
        b = {**a, "chipTimeInMillis": 2_965_000, "gunTimeInMillis": 2_965_000}
        self.assertEqual(len(dedupe([a, b])), 2)

    @staticmethod
    def finisher(ms, rid=1, name="X"):
        return {"id": rid, "displayName": name, "status": "CONF",
                "gunTimeInMillis": ms, "chipTimeInMillis": ms,
                "rankings": {"overall": 1}}

    def test_a_16_mile_time_is_impossible_over_40_miles(self):
        short = self.finisher(2_965_000)   # 49:25
        real = self.finisher(7_429_000)    # 2:03:49
        self.assertTrue(implausible(short, "gun", 64.37))   # 78 km/h on a MTB
        self.assertFalse(implausible(real, "gun", 64.37))   # 31 km/h

    def test_a_foreign_result_is_dropped_when_the_athlete_also_finished(self):
        # Chequamegon 2013: one athlete id, a 40-mile time and a 16-mile time.
        real = self.finisher(7_429_000, rid=4529691, name="Brian Matter")
        short = self.finisher(2_965_000, rid=4529691, name="Brian Matter")
        kept, dropped, down = resolve_implausible([real, short], "gun", 64.37)
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["gunTimeInMillis"], 2_965_000)
        self.assertEqual(down, [])

    def test_a_merged_edition_treats_lone_odd_rows_as_foreign_too(self):
        # Chequamegon 2013 has eight riders whose ONLY row is a 16-mile time.
        # Once the edition is known to hold a second race, they are people who
        # rode that race, not abandons of this one.
        real = self.finisher(7_429_000, rid=1, name="Finisher")
        short_dup = self.finisher(2_965_000, rid=1, name="Finisher")
        short_only = self.finisher(2_900_000, rid=2, name="Short Only")
        kept, dropped, down = resolve_implausible(
            [real, short_dup, short_only], "gun", 64.37)
        self.assertEqual([r["displayName"] for r in kept], ["Finisher"])
        self.assertEqual(len(dropped), 2)
        self.assertEqual(down, [])

    def test_a_lone_impossible_time_becomes_a_dnf_not_a_deletion(self):
        # Unbound 2026 marks abandons CONF with their last split. The rider
        # started; erasing them would be a worse lie than the flag.
        abandon = self.finisher(1_800_000, rid=7, name="Justin Mcquerry")
        kept, dropped, down = resolve_implausible([abandon], "gun", 326.38)
        self.assertEqual(dropped, [])
        self.assertEqual(len(down), 1)
        self.assertEqual(kept[0]["status"], "DNF")

    def test_a_slow_finisher_is_never_called_implausible(self):
        # 12 hours for Leadville's 160 km is 13 km/h — a real finish.
        self.assertFalse(implausible({"gunTimeInMillis": 43_200_000}, "gun", 160.93))

    def test_a_dnfs_split_time_is_never_judged(self):
        # A DNF's time is the last split, so its implied speed is meaningless.
        # Judging it dropped ten of Sea Otter 2026's abandons as "impossible".
        dnf = {"status": "DNF", "gunTimeInMillis": 2_965_000,
               "rankings": {"overall": 40}}
        self.assertFalse(implausible(dnf, "gun", 142.91))

    def test_unknown_distance_cannot_judge_anything(self):
        self.assertFalse(implausible({"gunTimeInMillis": 1000}, "gun", None))

    def test_a_checkpoint_time_flagged_as_a_finish_is_caught_by_the_field(self):
        # Leadville 2017 ranked Floyd Landis first at 3:18:07 in a race whose
        # median finisher took 7:12. Nothing about 3:18 is absurd for a bike
        # race — only for this one, which is why the field has to judge it.
        field = [self.finisher(7 * 3600_000 + i * 60_000, rid=i)
                 for i in range(MIN_FIELD_FOR_RELATIVE + 4)]
        landis = self.finisher(3 * 3600_000 + 18 * 60_000, rid=999, name="Landis")
        rows = [landis] + field
        floor = time_floor(rows, "gun", 160.93)
        self.assertIsNotNone(floor)
        self.assertTrue(implausible(landis, "gun", 160.93, floor))
        self.assertFalse(implausible(field[0], "gun", 160.93, floor))

    def test_a_real_winner_survives_the_field_floor(self):
        # Every genuine winner measured sits at 0.70 of the median or slower;
        # the tightest margin in the archive is Lance Armstrong at 0.760.
        field = [self.finisher(8 * 3600_000 + i * 120_000, rid=i)
                 for i in range(MIN_FIELD_FOR_RELATIVE + 6)]
        winner = self.finisher(int(8 * 3600_000 * 0.76), rid=999, name="Armstrong")
        floor = time_floor([winner] + field, "gun", 160.93)
        self.assertFalse(implausible(winner, "gun", 160.93, floor))

    def test_a_tiny_field_cannot_judge_itself(self):
        rows = [self.finisher(7 * 3600_000, rid=i) for i in range(3)]
        self.assertIsNone(time_floor(rows, "gun", 160.93))


class TestStatusInference(unittest.TestCase):
    """Pre-2016 editions ship no `status` field. Defaulting those to DNF
    marked every finisher of every early edition as a non-finisher, nulled
    100 ranks per file and discarded every time — and the output still looked
    like valid data. Leadville 2012 and Dirty Kanza 2012 were both wrecked."""

    def test_missing_status_with_time_and_rank_is_a_finish(self):
        r = {"chipTimeInMillis": 25_000_000, "rankings": {"overall": 1}}
        self.assertEqual(row_status(r), "FINISHED")

    def test_missing_status_with_no_time_is_not_a_finish(self):
        self.assertEqual(row_status({"rankings": {"overall": 1}}), "DNF")

    def test_missing_status_with_no_rank_is_not_a_finish(self):
        self.assertEqual(row_status({"chipTimeInMillis": 25_000_000}), "DNF")

    def test_explicit_status_still_wins(self):
        r = {"status": "DNF", "chipTimeInMillis": 5_000_000,
             "rankings": {"overall": 66}}
        self.assertEqual(row_status(r), "DNF")

    def test_unknown_status_string_is_not_a_finish(self):
        self.assertEqual(row_status({"status": "WEIRD"}), "DNF")

    def test_zero_age_is_not_a_birth_year(self):
        # Every Dirty Kanza 2012 row carries age 0 for "not recorded".
        r = {"displayName": "A", "age": 0, "rankings": {"overall": 1},
             "chipTimeInMillis": 1000, "gunTimeInMillis": 1000, "_rank": 1,
             "status": "CONF"}
        self.assertIsNone(to_row(r, "gun")["age"])


class TestRiderLinking(unittest.TestCase):
    def test_fold_ignores_order_case_and_accents(self):
        # The DB stores PCS's "Vakoč Petr"; Athlinks ships "Petr Vakoc".
        self.assertEqual(tokens("Vakoč Petr"), tokens("Petr Vakoc"))
        self.assertEqual(fold("L’Esperance"), "l esperance")

    @staticmethod
    def person(name, years, births=()):
        return {"name": name, "years": set(years), "births": set(births)}

    @staticmethod
    def existing(rider_id, first, last, birth=None, nat="us", full=None):
        return {"rider_id": rider_id, "full_name": full or f"{last} {first}",
                "first_year": 2010, "last_year": 2019,
                "birth_year_approx": birth, "nationality_code": nat}

    def test_road_rider_is_matched(self):
        by_tokens = {tokens("Stetina Peter"): [self.existing("rider/peter-stetina", "Peter", "Stetina")]}
        rid, decision, _ = decide(self.person("Peter Stetina", [2021, 2024]), by_tokens)
        self.assertEqual(rid, "rider/peter-stetina")
        self.assertEqual(decision, "matched")

    def test_same_name_a_century_apart_is_not_matched(self):
        old = self.existing("rider/john-smith", "John", "Smith")
        old["first_year"], old["last_year"] = 1925, 1931
        rid, decision, _ = decide(self.person("John Smith", [2014]), {tokens("Smith John"): [old]})
        self.assertIsNone(rid)
        self.assertEqual(decision, "new_era_mismatch")

    def test_a_different_flag_after_a_long_silence_is_a_namesake(self):
        # Sean Yates last raced in 1996; a Spanish-registered rider of that
        # name rode the 2024 Traka. Neither Traka source publishes a birth
        # year, so the birth check below cannot fire and this is the only
        # disqualifier left.
        yates = self.existing("rider/sean-yates", "Sean", "Yates", nat="gb")
        yates["first_year"], yates["last_year"] = 1982, 1996
        person = dict(self.person("Sean Yates", [2024]), countries={"es"})
        rid, decision, why = decide(person, {tokens("Yates Sean"): [yates]})
        self.assertIsNone(rid)
        self.assertEqual(decision, "new_country_and_era_mismatch")
        self.assertIn("1996", why)

    def test_a_different_flag_while_still_racing_is_just_residence(self):
        # These sources record where someone entered FROM, not their passport:
        # Mohoric rides for Slovenia and enters from Monaco. 22 existing
        # matches look like this and every one of them is right.
        m = self.existing("rider/matej-mohoric", "Matej", "Mohoric", nat="si")
        m["first_year"], m["last_year"] = 2012, 2026
        person = dict(self.person("Matej Mohoric", [2024]), countries={"mc"})
        rid, decision, _ = decide(person, {tokens("Mohoric Matej"): [m]})
        self.assertEqual(rid, "rider/matej-mohoric")
        self.assertEqual(decision, "matched")

    def test_a_long_silence_with_the_same_flag_still_matches(self):
        # Chris Carmichael's road results stop in 1986 and he shows up in
        # 2006-2014 off-road, as himself. The gap alone proves nothing.
        c = self.existing("rider/chris-carmichael", "Chris", "Carmichael", nat="us")
        c["first_year"], c["last_year"] = 1985, 1986
        person = dict(self.person("Chris Carmichael", [2006, 2014]), countries={"us"})
        rid, decision, _ = decide(person, {tokens("Carmichael Chris"): [c]})
        self.assertEqual(rid, "rider/chris-carmichael")
        self.assertEqual(decision, "matched")

    def test_ambiguous_name_is_never_guessed(self):
        cands = [self.existing("rider/a-vermeulen", "Alexey", "Vermeulen"),
                 self.existing("rider/b-vermeulen", "Alexey", "Vermeulen")]
        rid, decision, _ = decide(self.person("Alexey Vermeulen", [2023]),
                                  {tokens("Vermeulen Alexey"): cands})
        self.assertIsNone(rid)
        self.assertEqual(decision, "new_ambiguous")

    def test_birth_year_disagreement_blocks_the_match(self):
        by_tokens = {tokens("Jones Cameron"): [self.existing("rider/cameron-jones", "Cameron", "Jones", birth=1975)]}
        rid, decision, _ = decide(self.person("Cameron Jones", [2025], births=[2001]), by_tokens)
        self.assertIsNone(rid)
        self.assertEqual(decision, "new_birth_mismatch")

    def test_single_token_name_is_never_matched(self):
        rid, decision, _ = decide(self.person("Cher", [2020]), {})
        self.assertIsNone(rid)
        self.assertEqual(decision, "new_single_token")

    def test_slugify_matches_the_pcs_shape(self):
        self.assertEqual(slugify("Peter Stetina"), "peter-stetina")
        self.assertEqual(slugify("Andrew L’Esperance"), "andrew-l-esperance")


if __name__ == "__main__":
    unittest.main()


def _schema_conn():
    """In-memory DB with the real schema, so a column rename breaks a test."""
    conn = sqlite3.connect(":memory:")
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


class TestIngestRepairsMojibake(unittest.TestCase):
    """The repair has to live at the INGEST choke point, not just the scraper.

    The scrape files on disk still hold whatever the upstream shipped the day
    they were fetched, so a rebuild reads the corruption again. These are the
    tests that "re-ingesting will not bring it back" actually rests on.
    """

    def setUp(self):
        self.conn = _schema_conn()
        self.cur = self.conn.cursor()

    def test_classics_team_is_repaired_on_insert(self):
        ingest_classics.upsert_team(self.cur, "team/sefb-1987",
                                    "S.E.F.B. Banque d'Ã‰pargne")
        self.cur.execute("SELECT name FROM teams WHERE team_id='team/sefb-1987'")
        self.assertEqual(self.cur.fetchone()[0], "S.E.F.B. Banque d'Épargne")

    def test_classics_team_already_stored_corrupted_is_healed(self):
        # A team inserted by an older run keeps sitting there: ingest_classics
        # returns early for a known team, so without the narrow un-corrupt
        # branch a re-ingest would leave the bad name in place forever.
        self.cur.execute("INSERT INTO teams (team_id, name) VALUES (?,?)",
                         ("team/sefb-1987", "S.E.F.B. Banque d'Ã‰pargne"))
        ingest_classics.upsert_team(self.cur, "team/sefb-1987",
                                    "S.E.F.B. Banque d'Ã‰pargne")
        self.cur.execute("SELECT name FROM teams WHERE team_id='team/sefb-1987'")
        self.assertEqual(self.cur.fetchone()[0], "S.E.F.B. Banque d'Épargne")

    def test_healing_cannot_rename_a_team(self):
        # The un-corrupt branch must never fire on two genuinely different
        # names, or a re-ingest silently rewrites team history.
        self.cur.execute("INSERT INTO teams (team_id, name) VALUES (?,?)",
                         ("team/x-1987", "Panasonic"))
        ingest_classics.upsert_team(self.cur, "team/x-1987", "Raleigh")
        self.cur.execute("SELECT name FROM teams WHERE team_id='team/x-1987'")
        self.assertEqual(self.cur.fetchone()[0], "Panasonic")

    def test_classics_rider_is_repaired_and_gets_provenance(self):
        ingest_classics.upsert_rider(self.cur, "rider/x", "Emil √Öberg", "no",
                                     "https://example.invalid/race")
        self.cur.execute("SELECT full_name FROM riders WHERE rider_id='rider/x'")
        self.assertEqual(self.cur.fetchone()[0], "Emil Åberg")
        self.cur.execute("""SELECT field, source FROM data_provenance
                             WHERE entity='riders' AND entity_id='rider/x'
                             ORDER BY field""")
        self.assertEqual(self.cur.fetchall(),
                         [("full_name", "pcs"), ("nationality_code", "pcs")])

    def test_gravel_rider_is_repaired_and_gets_provenance(self):
        ingest_gravel.upsert_rider(self.cur, {
            "rider_id": "rider/emil-aberg", "name": "Emil √Öberg",
            "first_name": "Emil", "last_name": "√Öberg",
            "country": "no", "birth_year_approx": 1999})
        self.cur.execute("""SELECT full_name, last_name FROM riders
                             WHERE rider_id='rider/emil-aberg'""")
        self.assertEqual(self.cur.fetchone(), ("Emil Åberg", "Åberg"))
        self.cur.execute("""SELECT COUNT(*) FROM data_provenance
                             WHERE entity='riders' AND entity_id='rider/emil-aberg'
                               AND source='athlinks'""")
        self.assertEqual(self.cur.fetchone()[0], 5)

    def test_provenance_takes_a_text_slug_as_entity_id(self):
        # ingest_gravel.py carried a comment claiming rider provenance was
        # impossible because entity_id is declared INTEGER. It is not: the
        # table is not STRICT, so affinity leaves a non-numeric string alone.
        ingest_classics.upsert_rider(self.cur, "rider/x", "A B", "be", None)
        self.cur.execute("""SELECT typeof(entity_id) FROM data_provenance
                             WHERE entity='riders' LIMIT 1""")
        self.assertEqual(self.cur.fetchone()[0], "text")


class TestTrakaEventSelection(unittest.TestCase):
    """Which event IS "The Traka 360" — the one judgement this race needs.

    The Traka runs 50/60/100/200/360/560 km on one weekend. Those are
    different races, not classes of one, and the name of the 360 changed in
    four of its five editions.
    """

    @staticmethod
    def ev(*names):
        return [{"id": i, "name": n} for i, n in enumerate(names)]

    def test_every_real_edition_name_is_recognised(self):
        # The five spellings the source has actually used, one per edition.
        for name in ("TRAKA 360", "THE TRAKA 360", "360K", "360 K", "360 PRO M"):
            chosen, _, _ = pick_360(self.ev(name, "THE TRAKA 200", "THE TRAKA 100"))
            self.assertIsNotNone(chosen, f"{name!r} should resolve")
            self.assertEqual(chosen["name"], name)

    def test_other_distances_are_never_the_360(self):
        # "360K" has no word boundary before the K, so a \b-anchored pattern
        # silently matched nothing — and no results looks exactly like no race.
        for name in ("THE TRAKA 200", "200 K", "THE TRAKA 100", "TRAKA 60",
                     "THE TRAKA ADVENTURE", "TRAKA GIRONA", "TRAKA GRAVEL - 200K"):
            chosen, cands, rule = pick_360(self.ev(name))
            self.assertIsNone(chosen, f"{name!r} must not resolve as the 360")
            self.assertEqual(cands, [])
            self.assertIsNone(rule)

    def test_2026_split_takes_the_mens_pro_race(self):
        chosen, cands, rule = pick_360(self.ev("360 PRO W", "360 PRO M", "360 OPEN"))
        self.assertEqual(chosen["name"], "360 PRO M")
        self.assertEqual(len(cands), 3, "all three must be recorded as candidates")
        # A split BY CLASS is the sport drawing the elite line itself, so the
        # whole field is kept rather than windowed.
        self.assertEqual(rule, "elite_course")

    def test_one_open_360_is_a_mass_start_and_gets_windowed(self):
        # 2021-2024: everyone rode the same race, so any elite cutoff is ours.
        chosen, _, rule = pick_360(self.ev("THE TRAKA 360", "THE TRAKA 200"))
        self.assertEqual(chosen["name"], "THE TRAKA 360")
        self.assertEqual(rule, "open_field")

    def test_an_unresolvable_split_picks_nothing(self):
        # Two men's-looking 360s is a question for a person, not a guess.
        chosen, cands, rule = pick_360(self.ev("360 M", "360 PRO M"))
        self.assertIsNone(chosen)
        self.assertEqual(len(cands), 2)
        self.assertIsNone(rule)


class TestTrakaRowParsing(unittest.TestCase):
    def test_a_dnf_zero_time_never_becomes_a_finish(self):
        # 180 of 2024's 737 men carry officialTime "00:00:00". Parsed naively
        # that is a finish in zero seconds, which sorts ahead of the winner.
        self.assertIsNone(scrape_traka.to_seconds("00:00:00"))
        self.assertIsNone(scrape_traka.to_seconds(""))
        self.assertIsNone(scrape_traka.to_seconds("DNF"))
        self.assertEqual(scrape_traka.to_seconds("11:42:23"), 42143)

    def test_country_covers_all_four_upstream_formats(self):
        for raw, want in (("ESP", "es"),          # ISO-3, 2026
                          ("ESPAÑA", "es"),       # Spanish, 2023
                          ("DE", "de"),           # ISO-2, 2024
                          ("Germany", "de"),      # English, 2024
                          ("Unites States (US)", "us"),  # upstream typo
                          ("UK", "gb")):          # not ISO, but unambiguous
            self.assertEqual(scrape_traka.country_of(raw), want, raw)

    def test_an_unmappable_country_is_null_not_a_guess(self):
        # A wrong flag is a claim; a missing one is a gap.
        for raw in ("", None, "UM", "ATLANTIS"):
            self.assertIsNone(scrape_traka.country_of(raw))

    def test_an_open_field_is_capped_like_every_other_mass_start(self):
        # 737 men finished the 2024 Traka 360 in one mass start. Keeping all of
        # them would make one race a third of the whole off-road archive, and
        # would apply a rule to it that no Life Time edition gets.
        rows = [{"rank": i, "name": f"R{i}", "finish_seconds": 40000 + i,
                 "status": "FINISHED", "country": "es", "gap_seconds": None}
                for i in range(1, 738)]
        kept = scrape_traka.apply_field_rule(list(rows), "open_field")
        self.assertEqual(len(kept), scrape_traka.FIELD_CAP)
        self.assertEqual(kept[0]["rank"], 1)
        self.assertEqual(kept[-1]["rank"], scrape_traka.FIELD_CAP)

    def test_an_elite_course_is_never_truncated(self):
        rows = [{"rank": i, "name": f"R{i}", "finish_seconds": 40000 + i,
                 "status": "FINISHED", "country": "es", "gap_seconds": None}
                for i in range(1, 136)]
        kept = scrape_traka.apply_field_rule(list(rows), "elite_course")
        self.assertEqual(len(kept), 135)

    def test_dnfs_do_not_fill_the_cap(self):
        # An unranked rider has no claim on a top-100 place. If DNFs counted,
        # a race with 90 finishers and 40 DNFs would drop real finishers.
        rows = [{"rank": i, "name": f"F{i}", "finish_seconds": 40000 + i,
                 "status": "FINISHED", "country": None, "gap_seconds": None}
                for i in range(1, 121)]
        rows += [{"rank": None, "name": f"D{i}", "finish_seconds": None,
                  "status": "DNF", "country": None, "gap_seconds": None}
                 for i in range(40)]
        kept = scrape_traka.apply_field_rule(rows, "open_field")
        self.assertEqual(len(kept), 100)
        self.assertTrue(all(r["status"] == "FINISHED" for r in kept))

    def test_a_named_exception_survives_the_cap_with_its_real_rank(self):
        # Leonardo Basso finished 103rd in the 2024 Traka 360 — three places
        # outside the window — and is kept by explicit decision. He must keep
        # rank 103, not be renumbered into the field: 103rd is what happened.
        rows = [{"rank": i, "name": f"R{i}", "finish_seconds": 40000 + i,
                 "status": "FINISHED", "country": "es", "gap_seconds": None}
                for i in range(1, 200)]
        rows[102]["name"] = "Leonardo Basso"          # rank 103
        kept = scrape_traka.apply_field_rule(rows, "open_field", 2024)
        self.assertEqual(len(kept), scrape_traka.FIELD_CAP + 1)
        self.assertEqual([r["rank"] for r in kept[:100]], list(range(1, 101)),
                         "the first 100 must still be exactly the window")
        self.assertEqual(kept[-1]["name"], "Leonardo Basso")
        self.assertEqual(kept[-1]["rank"], 103)

    def test_an_exception_is_scoped_to_its_own_year(self):
        # The list is keyed (name, year): a namesake in another edition must
        # not inherit the decision.
        rows = [{"rank": i, "name": f"R{i}", "finish_seconds": 40000 + i,
                 "status": "FINISHED", "country": "es", "gap_seconds": None}
                for i in range(1, 200)]
        rows[102]["name"] = "Leonardo Basso"
        self.assertEqual(len(scrape_traka.apply_field_rule(list(rows), "open_field", 2022)),
                         scrape_traka.FIELD_CAP)

    def test_a_dnf_exception_is_kept_without_a_rank(self):
        # Jeremy Hunt DNF'd the 2024 Traka, so he was never in the window at
        # all rather than just outside it. Stored like every other non-finisher
        # in this archive — Mohoric's Unbound 2024 DNF is the same shape.
        rows = [{"rank": i, "name": f"R{i}", "finish_seconds": 40000 + i,
                 "status": "FINISHED", "country": None, "gap_seconds": None}
                for i in range(1, 150)]
        rows.append({"rank": None, "name": "Jeremy Hunt", "finish_seconds": None,
                     "status": "DNF", "country": "gb", "gap_seconds": None})
        kept = scrape_traka.apply_field_rule(rows, "open_field", 2024)
        hunt = [r for r in kept if r["name"] == "Jeremy Hunt"]
        self.assertEqual(len(hunt), 1)
        self.assertIsNone(hunt[0]["rank"])
        self.assertEqual(hunt[0]["status"], "DNF")

    def test_gap_is_measured_from_the_mens_winner(self):
        rows = [{"rank": 1, "finish_seconds": 42143, "gap_seconds": None},
                {"rank": 2, "finish_seconds": 42160, "gap_seconds": None},
                {"rank": None, "finish_seconds": None, "gap_seconds": None}]
        scrape_traka.add_gaps(rows)
        self.assertEqual([r["gap_seconds"] for r in rows], [0, 17, None])


class TestPCSGravelParsing(unittest.TestCase):
    """PCS is the preferred gravel source where it exists. Two things about it
    corrupt data silently if read naively."""

    @staticmethod
    def row(rank, slug, time_raw):
        return {"rank_raw": rank, "pcs_slug": slug, "surname": "X", "given": "Y",
                "team_slug": None, "team_name": None, "country": "es",
                "time_raw": time_raw}

    def test_the_winners_cell_is_a_time_and_everyone_elses_is_a_gap(self):
        # One cell holds both. Reading the winner's as a gap and adding it to
        # itself is what doubled 3,377 winning times across this DB once.
        rows = scrape_pcs_gravel.to_rows([
            self.row("1", "rider/a", "12:55:42"),
            self.row("2", "rider/b", "13:00"),
            self.row("3", "rider/c", "1:49:13"),
        ])
        self.assertEqual([r["finish_seconds"] for r in rows],
                         [46542, 46542 + 780, 46542 + 6553])
        self.assertEqual([r["gap_seconds"] for r in rows], [0, 780, 6553])

    def test_a_national_rider_is_not_a_pro_slug(self):
        # national-rider/ is a separate namespace that does not exist in
        # `riders`; storing one as a rider_id would invent a join.
        rows = scrape_pcs_gravel.to_rows([
            self.row("1", "rider/a", "10:00:00"),
            self.row("2", "national-rider/b", "1:00"),
        ])
        self.assertEqual([r["pcs_is_pro"] for r in rows], [True, False])

    def test_a_non_finisher_keeps_no_rank_and_no_time(self):
        rows = scrape_pcs_gravel.to_rows([
            self.row("1", "rider/a", "10:00:00"),
            self.row("DNF", "rider/b", ""),
        ])
        self.assertIsNone(rows[1]["rank"])
        self.assertIsNone(rows[1]["finish_seconds"])
        self.assertEqual(rows[1]["status"], "DNF")

    def test_true_positions_are_preserved_not_renumbered(self):
        # PCS lists only riders it tracks, so 2024's 87 rows run to rank 147.
        # Renumbering would claim 87 people finished a race that 147 finished.
        rows = scrape_pcs_gravel.to_rows([
            self.row("1", "rider/a", "10:00:00"),
            self.row("147", "rider/b", "3:00:00"),
        ])
        self.assertEqual([r["rank"] for r in rows], [1, 147])

    def test_distance_comes_from_the_header_and_zero_means_unknown(self):
        html = '<b> &rsaquo; </b> (360km)<tbody></tbody>'
        self.assertEqual(scrape_pcs_gravel.parse_result(html)[1], 360.0)
        # Big Sugar's page says (0km) — PCS does not know it. A gap, not a zero.
        html0 = '<b> &rsaquo; </b> (0km)<tbody></tbody>'
        self.assertIsNone(scrape_pcs_gravel.parse_result(html0)[1])
