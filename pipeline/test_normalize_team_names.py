#!/usr/bin/env python3
"""
Tests for normalize_team_names.py — merging a team's spellings into one.

The risk this script carries is not the merge it performs but the merge it
might perform by mistake: `Bianchi` and `Bianchi - Campagnolo` share a slug
stem and look alike, and collapsing them would silently destroy a sponsor
change. Most of what follows pins down what must NOT merge.

Run:  python3 -m unittest test_normalize_team_names -v
"""

import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import normalize_team_names as ntn


class FoldTest(unittest.TestCase):
    def test_folds_away_accents_case_and_separators(self):
        for a, b in [
            ("Alcyon - Dunlop", "Alcyon-Dunlop"),
            ("AG2R Prévoyance", "AG2R Prevoyance"),
            ("Française des Jeux", "Francaise des Jeux"),
            ("Landbouwkrediet  - Colnago", "Landbouwkrediet - Colnago"),
            ("Dr. Mann-Grundig", "Dr, Mann-Grundig"),
            ("Bestetti - D'Alessandro", "Bestetti-d'Alessandro"),
            ("Dossche Sport", "Dossche sport"),
        ]:
            self.assertEqual(ntn.fold(a), ntn.fold(b), f"{a!r} vs {b!r}")

    def test_keeps_different_words_apart(self):
        """The words are content. Only their spelling is negotiable."""
        for a, b in [
            ("Bianchi", "Bianchi - Campagnolo"),        # a sponsor was added
            ("Hitachi - Marc", "Hitachi - Marc - Splendor"),
            ("Astana", "Astana Pro Team"),
            ("Centre/Nord-est", "Nord-est/Centre"),      # order is content too
            ("Bertin - D'Alessandro", "Bertin - Milremo"),
            ("Caja Rural", "Caja Rural - Orbea"),
        ]:
            self.assertNotEqual(ntn.fold(a), ntn.fold(b), f"{a!r} vs {b!r}")


class PickCanonicalTest(unittest.TestCase):
    def pick(self, *variants):
        vs = [{"name": n, "teams": t, "riders": r} for n, t, r in variants]
        return ntn.pick_canonical(ntn.fold(vs[0]["name"]), vs)

    def test_accented_spelling_wins_even_when_rarer(self):
        """Dropping an accent loses information; adding one does not."""
        self.assertEqual(
            self.pick(("AG2R Prevoyance", 1, 234), ("AG2R Prévoyance", 7, 0)),
            "AG2R Prévoyance")

    def test_otherwise_the_most_used_spelling_wins(self):
        self.assertEqual(
            self.pick(("Gis Gelati", 2, 590), ("Gis - Gelati", 4, 686)),
            "Gis - Gelati")

    def test_exact_tie_falls_back_to_the_spaced_house_style(self):
        self.assertEqual(
            self.pick(("Daring-Alix", 1, 3), ("Daring - Alix", 1, 3)),
            "Daring - Alix")

    def test_style_override_beats_the_count(self):
        """PCS's title-caser writes an acronym as `Mss`; the count agrees with
        it and is still wrong. See STYLE_OVERRIDES."""
        self.assertEqual(
            self.pick(("Milaneza - Mss", 2, 362), ("Milaneza - MSS", 1, 179)),
            "Milaneza - MSS")
        self.assertEqual(self.pick(("Kas", 4, 1034), ("KAS", 10, 0)), "KAS")


class TokenCaseTest(unittest.TestCase):
    def test_capitalises_wherever_it_appears(self):
        self.assertEqual(ntn.apply_token_case("Daf Trucks"), "DAF Trucks")
        self.assertEqual(ntn.apply_token_case("Daf Trucks - Lejeune - PZ"),
                         "DAF Trucks - Lejeune - PZ")
        self.assertEqual(ntn.apply_token_case("Daf-Trucks"), "DAF-Trucks")

    def test_leaves_a_correct_name_untouched(self):
        for n in ("DAF Trucks - Cote d'Or - Gazelle",
                  "DAF Trucks - Tévé Blad - Rossin"):
            self.assertEqual(ntn.apply_token_case(n), n)

    def test_cannot_reach_inside_a_longer_word(self):
        """Whole-token only, or a real word becomes an acronym."""
        for n in ("Daffodil", "Dafne - Wolber", "Bidaf", "Daffy Duck - Gios"):
            self.assertEqual(ntn.apply_token_case(n), n)

    def test_does_not_add_periods_to_initials(self):
        """Periods come from a merge with a spelling the source already dots,
        never from a token rule — that rule invented `R.M.O. - Mavic - Liberia`
        and `J.B. Louvet-Dunlop`, neither of which any source writes."""
        for n in ("RMO - Mavic - Liberia", "JB Louvet-Dunlop", "KTM", "FDJ",
                  "TVM - Farm Frites", "CSF - Bardiani"):
            self.assertEqual(ntn.apply_token_case(n), n)

    def test_lowercases_a_brand_that_only_looks_like_an_acronym(self):
        """Upstream gets it wrong in both directions — DELKO is a brand name,
        not initials, so the rule has to run downward too."""
        self.assertEqual(ntn.apply_token_case("DELKO"), "Delko")
        self.assertEqual(ntn.apply_token_case("DELKO Marseille Provence KTM"),
                         "Delko Marseille Provence KTM")

    def test_leaves_an_already_correct_brand_untouched(self):
        for n in ("Delko Marseille Provence KTM", "Delko Marseille Provence"):
            self.assertEqual(ntn.apply_token_case(n), n)

    def test_only_listed_tokens_are_touched(self):
        self.assertEqual(ntn.apply_token_case("Kas - Kaskol"), "Kas - Kaskol")


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
            self.conn.executescript(f.read())
        self.cur = self.conn.cursor()

    def tearDown(self):
        self.conn.close()

    def team(self, team_id, name):
        self.cur.execute(
            "INSERT INTO teams (team_id, name, season_year) VALUES (?,?,?)",
            (team_id, name, int(team_id[-4:])))

    def test_merges_the_spellings_of_one_team(self):
        self.team("team/alcyon-dunlop-1909", "Alcyon - Dunlop")
        self.team("team/alcyon-dunlop-1936", "Alcyon-Dunlop")
        merges = ntn.plan(self.cur)
        self.assertEqual(len(merges), 1)
        canonical, rows = merges[0]
        self.assertEqual(canonical, "Alcyon - Dunlop")
        self.assertEqual(rows, [("team/alcyon-dunlop-1936", "Alcyon-Dunlop")])

    def test_leaves_a_changed_sponsor_alone(self):
        """Both live under the slug PCS minted once — the stem is not a key."""
        self.team("team/bianchi-1950", "Bianchi")
        self.team("team/bianchi-1958", "Bianchi - Campagnolo")
        self.assertEqual(ntn.plan(self.cur), [])

    def test_leaves_the_pcs_uncertainty_marker_alone(self):
        """`Ricci?` says PCS is not sure; merging would assert that it is."""
        self.team("team/ricci-1947", "Ricci")
        self.team("team/ricci-1948", "Ricci?")
        self.assertEqual(ntn.plan(self.cur), [])

    def test_merges_across_different_slugs(self):
        """The dropdown lists names, so the same name under two slugs is still
        two entries. `Legnano - Pirelli` really does appear under both."""
        self.team("team/legnano-1958", "Legnano - Pirelli")
        self.team("team/legnano-pirelli-1959", "Legnano-Pirelli")
        merges = ntn.plan(self.cur)
        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0][0], "Legnano - Pirelli")

    def test_is_idempotent(self):
        self.team("team/alcyon-dunlop-1909", "Alcyon - Dunlop")
        self.team("team/alcyon-dunlop-1936", "Alcyon-Dunlop")
        for canonical, rows in ntn.plan(self.cur):
            for team_id, _old in rows:
                self.cur.execute("UPDATE teams SET name=? WHERE team_id=?",
                                 (canonical, team_id))
        self.assertEqual(ntn.plan(self.cur), [])

    def test_dotted_initials_win_the_merge(self):
        """Merging a bare spelling with a dotted one yields the dotted one —
        even though the bare row carries 6 riders to the dotted row's 1, which
        the rider-count rule would otherwise settle the other way."""
        self.team("team/j.b.-louvet-soly-1922", "J.B. Louvet - Soly")
        self.team("team/jb-louvet-soly-1922", "JB Louvet-Soly")
        merges = ntn.plan(self.cur)
        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0][0], "J.B. Louvet - Soly")

    def test_bare_initials_with_no_dotted_sibling_are_left_alone(self):
        """Nothing in the database spells these with periods, so adding them
        would invent a spelling no source published."""
        self.team("team/jb-louvet-dunlop-1911", "JB Louvet-Dunlop")
        self.team("team/rmo-mavic-liberia-1989", "RMO - Mavic - Liberia")
        self.assertEqual(ntn.plan(self.cur), [])

    def test_merges_a_listed_upstream_typo(self):
        """One letter apart, so folding cannot reach it — see MISSPELLINGS."""
        self.team("team/berretini-hutchinson-1927", "Berretini-Hutchinson")
        self.team("team/berrettini-hutchinson-1927", "Berrettini-Hutchinson")
        merges = ntn.plan(self.cur)
        self.assertIn(("Berrettini-Hutchinson",
                       [("team/berretini-hutchinson-1927",
                         "Berretini-Hutchinson")]), merges)

    def test_a_typo_alone_is_left_alone(self):
        """The map corrects onto a team that EXISTS. With no correct spelling
        in the database there is nothing to merge into, and inventing one
        would be fabricating a team."""
        self.team("team/berretini-hutchinson-1927", "Berretini-Hutchinson")
        with self.assertRaises(SystemExit):
            ntn.plan(self.cur)

    def test_renames_a_typo_that_has_no_correct_sibling(self):
        """RENAMES is the signed-off path: nothing in the DB spells it right,
        so no other row can justify the change."""
        self.team("team/berettini-monza-1923", "Berettini - Monza")
        merges = ntn.plan(self.cur)
        self.assertEqual(merges, [("Berrettini - Monza",
                                   [("team/berettini-monza-1923",
                                     "Berettini - Monza")])])

    def test_a_rename_onto_an_existing_team_is_refused(self):
        """That is a merge, and merges answer to MISSPELLINGS' evidence rule."""
        self.team("team/berettini-monza-1923", "Berettini - Monza")
        self.team("team/berrettini-monza-1924", "Berrettini - Monza")
        with self.assertRaises(SystemExit):
            ntn.plan(self.cur)

    def test_an_unlisted_typo_is_not_guessed(self):
        """One edit apart and obviously a typo, but only names listed in
        MISSPELLINGS merge — proximity alone never does.

        The pair is INVENTED on purpose. This test used `Molteani`/`Molteni`
        first and `Aquilano`/`Aquiliano` second, and both stopped being
        unlisted the moment their group was resolved, failing a test that was
        still describing the right behaviour. An example drawn from live data
        is a test with an expiry date.
        """
        self.team("team/zzz-fictional-1974", "Zzz Fictional")
        self.team("team/zzz-ficticnal-1974", "Zzz Ficticnal")
        self.assertEqual(ntn.plan(self.cur), [])

    def test_never_touches_a_team_id(self):
        self.team("team/alcyon-dunlop-1909", "Alcyon - Dunlop")
        self.team("team/alcyon-dunlop-1936", "Alcyon-Dunlop")
        before = self.cur.execute(
            "SELECT team_id FROM teams ORDER BY team_id").fetchall()
        for canonical, rows in ntn.plan(self.cur):
            for team_id, _old in rows:
                self.cur.execute("UPDATE teams SET name=? WHERE team_id=?",
                                 (canonical, team_id))
        self.assertEqual(
            self.cur.execute("SELECT team_id FROM teams ORDER BY team_id").fetchall(),
            before)


if __name__ == "__main__":
    unittest.main()
