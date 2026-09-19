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
