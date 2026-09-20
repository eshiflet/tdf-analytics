#!/usr/bin/env python3
"""Merge team display names that differ only in spelling, not in content.

PCS spells the same team more than one way across seasons: `Alcyon - Dunlop`
in 1909 and `Alcyon-Dunlop` in 1936, `AG2R Prevoyance` in 2000 and
`AG2R Prévoyance` in every year after. The team filter on the Riders page
lists display names, so each spelling arrives as its own entry and the same
team appears two or three times in the dropdown.

This rewrites `teams.name` so one spelling wins per team. It is a display
repair and nothing else:

* **`team_id` is never touched.** The id came out of a PCS href and is PCS's
  own key; renaming it would break the join to the source and to every scrape
  file on disk. Same rule the mojibake repair follows — fix the display value,
  never the upstream key. Nothing else in the schema changes either: no row is
  inserted, deleted, or re-pointed, so every result keeps the team it had.
* **Only spelling merges.** Two names merge when they are identical after
  folding away accents, case, and every run of punctuation/whitespace. That is
  the whole test: the words themselves must already match. `Bianchi` and
  `Bianchi - Campagnolo` are different sponsors and stay apart, as do
  `Hitachi - Marc` / `Hitachi - Marc - Splendor` and `Centre/Nord-est` /
  `Nord-est/Centre` (word order is content, not spelling).

**The slug is not a safe merge key**, which is why this groups by folded name
instead. 172 slug stems carry more than one display name, but many of those
are a team whose sponsors changed under a slug PCS minted once and kept:
`team/bianchi-1958` is named `Bianchi - Campagnolo`. Merging by stem would
collapse genuinely different teams.

Which spelling wins, in order:

1. **The one with accents.** Dropping an accent loses information; adding one
   does not. `AG2R Prévoyance` beats `AG2R Prevoyance`, `Isolés` beats
   `Isoles`, `St. Raphaël-Géminiani` beats `St. Raphael-Geminiani`.
2. **The one PCS actually uses most**, counted in rider results and then in
   team rows, so the winner is the spelling most of the data already carries.
3. **The spaced `A - B` form** on an exact tie, the majority house style
   (1,836 team rows to 832).

`STYLE_OVERRIDES` sits in front of all three. A handful of merges are
case-only, and there the count argues for a spelling that is simply wrong:
PCS's title-caser produces `Mss` for an acronym and `Van De Ven` for a Dutch
particle. Those are listed explicitly rather than folded into the ranking,
because the rule that decides them is knowledge about the name, not anything
present in the data.

Names carrying PCS's `?` uncertainty marker are left alone — `Ricci?` says
PCS is not sure this is Ricci, and merging it into `Ricci` would assert
something the source does not.

Provenance for a rewritten name becomes `derived`: the value is ours now, not
the string PCS served, and recording it as `pcs` would misattribute it.

Usage:
  python3 normalize_team_names.py --dry-run     # print the change table
  python3 normalize_team_names.py
"""
import argparse
import os
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict

from race_common import SOURCE_DERIVED, record_provenance

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")

# Upstream typos: a name one letter from the right one. Folding cannot reach
# these — the letters themselves differ, and no rule can tell a typo from a
# real name, so each is listed only once the source page has been read and
# shown to spell the SAME team both ways. The target must already exist in the
# database; a name that does not is a typo in this map and stops the run.
#
# `Berrettini` appears 8 times across the saved bikeraceinfo pages and
# `Berretini` once, on Antonio Pancera's row of Milan-San Remo 1927 — the same
# page that spells Giuseppe Pancera's 1927 team correctly. The 1926 page does
# it again: four riders on `Berrettini-Russell Cycles`, Antonio Buelli on
# `Berettini-`.
MISSPELLINGS = {
    "Berretini-Hutchinson": "Berrettini-Hutchinson",
    "Berettini-Russell Cycles": "Berrettini-Russell Cycles",
    # Eric's rule, 2026-09-19: where one spelling carries the riders and the
    # other carries none (or a handful against 4x as many), the crowded one is
    # the team and the empty one is a typo. Every entry below was read off that
    # comparison; the ones the rule could NOT decide are deliberately absent —
    # see "What this map refuses to guess".
    "Benotto-Levrieri": "Benotto - Levriere",
    "Bertin-Porter 39-Miremo": "Bertin - Porter 39 - Milremo",
    "Botttecchia-Ursus": "Bottecchia - Ursus",
    "Carpenter-Zeep centrale-Splendor": "Carpenter - Zeepcentrale - Splendor",
    "Dielcta-Wolber": "Dilecta - Wolber",
    "Dilcta-Wolber": "Dilecta - Wolber",
    "Dreherforte": "Dreher Forte",
    "FLandria-De Clercq": "Flandria - De Clerck",
    "Flandria-De Clerk": "Flandria - De Clerck",
    "Frane Sport-Wolber": "France Sport-Wolber",
    "Gitane-Frigicreme": "Gitane - Frigécrème",
    "Golkdor-Gerka": "Goldor - Gerka",
    "Helyett-Fynsec-Hutchnson": "Helyett - Fynsec - Hutchinson",
    "Helyett-Hutchison": "Helyett - Hutchinson",
    "Ijsboercke-Colnago": "Ijsboerke - Colnago",
    "Il Littorale": "Il Littoriale",
    "AS-Kaskol": "Kas - Kaskol",
    "Locomotif-Vredestein": "Locomotief - Vredestein",
    "Lygie-Settebelo": "Lygie - Settebello",
    "Magnflex": "Magniflex",
    "Main-Bergougnan": "Maino - Bergougnan",
    "Man-Grundig": "Mann - Grundig",
    "Marc Zeep Centrale-Superia": "Marc Zeepcentrale - Superia",
    "Marc-Zeepcentale-Superia": "Marc Zeepcentrale - Superia",
    "Marc-Zeepsentrale-Superia": "Marc Zeepcentrale - Superia",
    "Margnat-Paloma-Inuris-Dunlop": "Margnat - Paloma - Inuri - Dunlop",
    "Molteani": "Molteni",
    "Métopole-Dunlop": "Métropole - Dunlop",
    "Nivea-Fuschs": "Nivea - Fuchs",
    "Pelfort-Sauvage-Lejeune": "Pelforth - Sauvage - Lejeune",
    "Pelforth-Saivage-Lejeune": "Pelforth - Sauvage - Lejeune",
    "Pelforth-Sauvag-Lejeune": "Pelforth - Sauvage - Lejeune",
    "Pelforth-Sauvage-Lejeun": "Pelforth - Sauvage - Lejeune",
    "Pelfoth-Sauvage-Lejeune": "Pelforth - Sauvage - Lejeune",
    "Peugeot-Wober": "Peugeot - Wolber",
    "Peugeot-Wolbert": "Peugeot - Wolber",
    "Plume Vainquer": "Plume-Vainqueur",
    "Plume-Vanqueur-Regina": "Plume-Vainqueur - Regina",
    "Salvaran": "Salvarani",
    "Savarani": "Salvarani",
    "Senio-Polack": "Senior - Polack",
    "Stella-Duinlop": "Stella - Dunlop",
    "Televizier-Betavis": "Televizier - Batavus",
    "Televizier-Betavus": "Televizier - Batavus",
    "Torpedo-Girardengo": "Torpado - Girardengo",
    "Touring-Pierelli": "Touring-Pirelli",
    "Tricolfilina-Coppi": "Tricofilina - Coppi",
    "Vitadello": "Vittadello",
    "Willem II-Gaxelle": "Willem II - Gazelle",
    # The six the rider count could NOT settle, resolved 2026-09-19 by reading
    # the source pages instead. Each line says what the evidence actually was.
    #
    # Same page, same team, both spellings — the Berrettini shape:
    "Aquiliano": "Aquilano",                  # 7 vs 1; MSR 1943 has both, and
                                              # Salvatore Crippa rides for each
    "JB Louvet-Puchois": "J.B. Louvet - Pouchois",   # 12 vs 4, and Hector
                                              # Martin appears under both
    "Helyett-Splendor-Hutchonson": "Helyett-Splendor-Hutchinson",
                                              # the tyre brand: 1,104 vs 1
    # Legnano: 5 `Torpedo` against 1 `Torpado` on the 1928/1929 pages. NOT a
    # contradiction of `Torpedo-Girardengo` -> `Torpado - Girardengo` above:
    # **both sponsors are real** and they are different companies — Torpado the
    # Italian frame builder (Torpado - Ursus, Magniflex - Torpado), Torpedo the
    # Fichtel & Sachs coaster hub (Torpedo - Fichtel & Sachs 1959, Opel -
    # Torpedo 1931). Two Italian frame builders would not co-sponsor one team,
    # which is the other reason Legnano's partner is the hub.
    "Legnano-Torpado": "Legnano-Torpedo",
    # The weakest of the six, and the only one without same-page or same-rider
    # proof: `Peina-Hutchinson` appears exactly once in the whole bikeraceinfo
    # corpus, against PCS's own `Prina - Hutchinson` for the same 1930 season
    # and the same co-sponsor. Prina was a real Italian marque; Peina is not.
    "Peina-Hutchinson": "Prina - Hutchinson",
    # Not a typo but the same thing twice: the not-on-a-team marker, `Individuals`
    # from PCS and `individual` from bikeraceinfo. `Isolés` is deliberately NOT
    # merged in — it is the Tour's own historical label for the category, and
    # collapsing it would throw away a real distinction rather than a spelling.
    "individual": "Individuals",
}

# A typo with NO correctly-spelled sibling to merge into. This renames rather
# than merges, so it cannot be justified by another row in the database and
# needs a person to say so — each entry records who and when.
#
# `Berettini - Monza` is the 1923 edition of the same Italian firm that appears
# as `Berrettini` in 1924, 1926 and 1927. It came from PCS (the others came via
# bikeraceinfo), which is why nothing else in the database spells this pairing
# correctly. Eric's call, 2026-09-19.
RENAMES = {
    "Berettini - Monza": "Berrettini - Monza",
}

# How a sponsor's name is cased, wherever it appears and however many
# co-sponsors follow. A token rule rather than a list of names, so `Daf Trucks`
# and `Daf Trucks - Lejeune - PZ` are one decision and whatever PCS adds next
# season is already covered.
#
# It runs in both directions, because upstream gets it wrong both ways: DAF is
# an acronym and is always capitalised, while DELKO is a brand name that merely
# looks like one and is written Delko. Nothing here can be derived — whether a
# name is an acronym is knowledge about the company, not about the string.
#
# Matching is whole-token (`\bdaf\b`), so it cannot reach inside a longer word,
# and the map is an explicit allowlist: a token not named here is never
# recased. Eric's calls, 2026-09-19.
TOKEN_CASE = {
    "daf": "DAF",       # the Dutch truck maker, an acronym
    "delko": "Delko",   # French car parts, NOT an acronym
}

# Case-only merges where the count points at a spelling that is wrong about
# the name itself. Keyed by folded name -> the spelling to keep.
STYLE_OVERRIDES = {
    "kas": "KAS",                              # the sponsor is styled KAS
    "milaneza mss": "Milaneza - MSS",           # MSS is an acronym
    "safir van de ven": "Safir - Van de Ven",   # Dutch particle stays lower
    "t belfort": "'t Belfort",                  # Dutch article, not an apostrophe
}


def fold(name):
    """Strip accents, case and punctuation — what's left is the words alone."""
    d = unicodedata.normalize("NFKD", name)
    d = "".join(c for c in d if not unicodedata.combining(c))
    return re.sub(r"[^0-9A-Za-z]+", " ", d).casefold().strip()


def apply_token_case(name):
    """Recase any TOKEN_CASE token, leaving the rest of the name alone."""
    for token, cased in sorted(TOKEN_CASE.items()):
        name = re.sub(rf"\b{re.escape(token)}\b", cased, name, flags=re.IGNORECASE)
    return name


def initials_key(name):
    """`fold()`, with runs of single letters joined: `j b` -> `jb`.

    This is what puts `JB Louvet` and `J.B. Louvet` in one group so the merge
    can see them as the same team. It is ONLY a grouping key — **periods are
    never added to a name that has none.** They arrive one way: the group also
    contains a spelling the source already writes with periods, and
    `dotted_initials()` makes that spelling win. A bare name with no dotted
    sibling groups alone and is left exactly as it is, which is why
    `JB Louvet-Dunlop` and `RMO - Mavic - Liberia` keep their bare initials —
    nothing in the database spells those two with periods.
    """
    out, buf = [], []
    for word in fold(name).split():
        if len(word) == 1:
            buf.append(word)
        else:
            if buf:
                out.append("".join(buf))
                buf = []
            out.append(word)
    if buf:
        out.append("".join(buf))
    return " ".join(out)


def dotted_initials(name):
    """How many initials in `name` carry a period — `J.B. Louvet` scores 2."""
    return len(re.findall(r"\b[A-Za-z]\.", name))


def diacritics(name):
    return sum(1 for c in unicodedata.normalize("NFD", name)
               if unicodedata.combining(c))


def pick_canonical(key, variants):
    """variants: [{name, teams, riders}] -> the spelling to keep."""
    override = STYLE_OVERRIDES.get(key)
    if override:
        return override
    return sorted(
        variants,
        key=lambda v: (-dotted_initials(v["name"]), -diacritics(v["name"]),
                       -v["riders"], -v["teams"],
                       0 if " - " in v["name"] else 1, v["name"]),
    )[0]["name"]


def plan(cur):
    """Return [(canonical, [(team_id, old_name), ...])] for every merge."""
    usage = dict(cur.execute(
        "SELECT team_id, COUNT(*) FROM stage_results "
        "WHERE team_id IS NOT NULL GROUP BY team_id").fetchall())

    rows = cur.execute("SELECT team_id, name FROM teams").fetchall()
    present = {n for _, n in rows}

    merges = []
    for wrong, right in sorted(MISSPELLINGS.items()):
        if wrong not in present:
            continue
        if right not in present:
            raise SystemExit(
                f"MISSPELLINGS maps {wrong!r} onto {right!r}, which is not a "
                "team in this database — correct the map rather than inventing "
                "the team. A typo with no correct sibling belongs in RENAMES, "
                "which a person has to sign off on.")
        merges.append((right, sorted((t, n) for t, n in rows if n == wrong)))

    for wrong, right in sorted(RENAMES.items()):
        if wrong not in present:
            continue
        if right in present:
            raise SystemExit(
                f"RENAMES maps {wrong!r} onto {right!r}, which already exists — "
                "that is a merge, so move it to MISSPELLINGS.")
        merges.append((right, sorted((t, n) for t, n in rows if n == wrong)))

    handled = set(MISSPELLINGS) | set(RENAMES)

    # Sponsor-name casing is a TRANSFORM, not a merge of its own: it runs first
    # and the fold pass then sees the corrected name. That order matters —
    # `JB Louvet-Wolber` becomes `J.B. Louvet-Wolber`, which folds together
    # with `J.B. Louvet - Wolber` and is settled by the rider counts like any
    # other spelling pair. Recasing after the fold would leave the two apart.
    groups = defaultdict(lambda: defaultdict(list))
    for team_id, name in rows:
        if name in handled:
            continue          # claimed above, and must not steer a fold group
        groups[initials_key(apply_token_case(name))][apply_token_case(name)].append(
            (team_id, name))

    for key, by_name in sorted(groups.items()):
        # PCS's own uncertainty marker: not a spelling variant.
        if any("?" in n for n in by_name):
            continue
        variants = [{"name": n,
                     "teams": len(ids),
                     "riders": sum(usage.get(t, 0) for t, _ in ids)}
                    for n, ids in by_name.items()]
        canonical = (pick_canonical(key, variants) if len(by_name) > 1
                     else next(iter(by_name)))
        # `orig != canonical` rather than `n != canonical`, so a row that only
        # needed recasing is caught even when its group has a single variant:
        # a lone `RMO` in a season with no `R.M.O.` beside it still has to move.
        targets = sorted((t, orig) for ids in by_name.values()
                         for t, orig in ids if orig != canonical)
        if targets:
            merges.append((canonical, targets))
    return merges


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print the change table, write nothing")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    merges = plan(cur)

    if not merges:
        print("no team names need merging")
        conn.close()
        return 0

    print(f"{'CANONICAL (kept)':<38} {'RETIRED SPELLING':<38} {'team_id'}")
    print("-" * 110)
    rows = 0
    for canonical, targets in merges:
        for team_id, old in targets:
            print(f"{canonical:<38} {old:<38} {team_id}")
            rows += 1
    spellings = sum(len({n for _, n in t}) for _, t in merges)
    print(f"\n{len(merges)} teams · {spellings} spellings retired · "
          f"{rows} team rows renamed")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        conn.close()
        return 0

    for canonical, targets in merges:
        for team_id, _old in targets:
            cur.execute("UPDATE teams SET name = ? WHERE team_id = ?",
                        (canonical, team_id))
            record_provenance(cur, "teams", team_id, "name", SOURCE_DERIVED,
                              source_ref="spelling merged with the same team's "
                                          "other seasons")
    conn.commit()
    conn.close()
    print(f"\napplied — re-run the exports so the app picks the names up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
