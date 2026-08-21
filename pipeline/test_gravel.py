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
    def test_six_races_with_unique_shorts(self):
        self.assertEqual(len(GRAVEL), 6)
        shorts = [i.short for i in GRAVEL.values()]
        self.assertEqual(len(shorts), len(set(shorts)), "x-axis labels must be unique")

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

    def test_legitimate_accents_survive(self):
        for name in ("Torbjørn Andre Røed", "Petr Vakoč", "Cécile Lejeune"):
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
