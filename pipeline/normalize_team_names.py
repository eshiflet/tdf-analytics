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
        key=lambda v: (-diacritics(v["name"]), -v["riders"], -v["teams"],
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
                "the team.")
        merges.append((right, sorted((t, n) for t, n in rows if n == wrong)))

    groups = defaultdict(lambda: defaultdict(list))
    for team_id, name in rows:
        if name in MISSPELLINGS and name in present:
            continue          # handled above, and must not steer a fold group
        groups[fold(name)][name].append(team_id)

    for key, by_name in sorted(groups.items()):
        if len(by_name) < 2:
            continue
        # PCS's own uncertainty marker: not a spelling variant.
        if any("?" in n for n in by_name):
            continue
        variants = [{"name": n,
                     "teams": len(ids),
                     "riders": sum(usage.get(t, 0) for t in ids)}
                    for n, ids in by_name.items()]
        canonical = pick_canonical(key, variants)
        rows = [(t, n) for n, ids in by_name.items() if n != canonical
                for t in ids]
        if rows:
            merges.append((canonical, sorted(rows)))
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
