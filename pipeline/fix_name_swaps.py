#!/usr/bin/env python3
"""
Repair adjacent-row name-swap artifacts in stage-race scrape files.

The artifact: PCS renders two neighbouring result rows with their rider
identities transposed. Everything else on the row — bib, team, age, times, GC —
stays correctly bound to the row, so the fix is to swap name/slug/nat back
(race_common.swap_identity), and nothing else.

This is NOT fixable by re-scraping: the defect is durable on PCS's side and
reproduces on every request (confirmed 2026-07-25 re-scraping TDF stage 19).
The authority for the correct identity is the bib, which stays attached to the
right rider on every other stage of the race.

Only fully-corroborated swaps are applied. A pair must satisfy ALL of:
  * mutual        — A shows B's name AND B shows A's name, on the same stage
  * adjacent      — the two rows are neighbours in the results table
  * strong        — each bib's majority identity holds on >half its stages
                    and on more than one stage
  * team-bound    — each bib's team on the bad stage still matches the team it
                    carries on its other stages, proving only the name moved

Anything failing those is reported and left alone rather than guessed at.
Duplicate-bib findings are ignored here — those are an upstream PCS defect
where both riders and both results are correct (see detect_name_swaps._bib_check).

The Tour was added 2026-09-09 and had never been covered: SCRAPE_DIRS named
only the Giro and the Vuelta, so 10 pairs across 1924-1949 sat unrepaired in
files this script reads happily once pointed at them. Its years live one to a
file (tdf_YEAR_full.json, stages inside) rather than one per stage, which is
the only reason it was left out. Note only 1903-1959 have such a file; from
1960 there is none, so the 17 further pairs this finds in 1976-2014 cannot be
repaired here — see ai-context.md.

Usage:
  python3 fix_name_swaps.py --dry-run
  python3 fix_name_swaps.py --race giro --year 1973 --dry-run
  python3 fix_name_swaps.py --apply
"""

import argparse
import glob
import json
import os
from collections import Counter, defaultdict

from detect_name_swaps import _bib_check
from race_common import (STAGE_RACES, StageRow, load_stage_rows,
                         swap_identity, year_sources)

HERE = os.path.dirname(os.path.abspath(__file__))


def bib_profile(stages, bib):
    """Majority identity + support + team-by-stage for one bib."""
    idents, teams = Counter(), {}
    for n, j in stages.items():
        for row in j.get("rows", []):
            if len(row) != 15:
                continue
            sr = StageRow.from_list(row)
            if sr.bib != bib:
                continue
            idents[(sr.name, sr.slug, sr.nat)] += 1
            teams[n] = sr.team
    if not idents:
        return None, 0, 0, teams
    majority, support = idents.most_common(1)[0]
    return majority, support, sum(idents.values()), teams


def row_index(j, bib):
    for i, row in enumerate(j.get("rows", [])):
        if len(row) == 15 and row[3] == bib:
            return i
    return None


def plan_year(race, year, key):
    """Return (fixable_pairs, unfixable) for one race-year."""
    stages, _ = load_stage_rows(race, key)
    # _bib_check rather than ingest_race.check_swaps: that wrapper reads stage
    # files off disk by path, which the Tour's one-file-per-year layout has
    # none of. It builds exactly this mapping and calls _bib_check anyway.
    findings = [f for f in _bib_check(race, year,
                                      {n: j.get("rows", []) for n, j in stages.items()})
                if f.get("type") == "bib_inconsistency"]
    if not findings:
        return [], []

    by_stage = defaultdict(list)
    for f in findings:
        for st in f["outlier_stages"]:
            by_stage[st].append(f)

    fixable, unfixable = [], []
    for st, group in sorted(by_stage.items()):
        maj_names = {f["majority_identity"][0]: f for f in group}
        handled = set()
        for f in group:
            bib = f["bib"]
            if bib in handled:
                continue
            path_j = stages[st]
            shown_name = None
            i = row_index(path_j, bib)
            if i is not None:
                shown_name = StageRow.from_list(path_j["rows"][i]).name

            partner = maj_names.get(shown_name)
            reason = None
            if partner is None or partner["bib"] == bib:
                reason = "no mutual partner on this stage"
            else:
                pj = row_index(path_j, partner["bib"])
                a_maj, a_sup, a_tot, a_teams = bib_profile(stages, bib)
                b_maj, b_sup, b_tot, b_teams = bib_profile(stages, partner["bib"])
                if StageRow.from_list(path_j["rows"][pj]).name != f["majority_identity"][0]:
                    reason = "partner does not show this bib's name (not a clean transposition)"
                elif i is None or pj is None or abs(i - pj) != 1:
                    reason = f"rows not adjacent ({i} vs {pj})"
                elif not (a_sup > 1 and a_sup * 2 > a_tot and b_sup > 1 and b_sup * 2 > b_tot):
                    reason = f"weak majority ({a_sup}/{a_tot}, {b_sup}/{b_tot})"
                else:
                    # team must still match what each bib carries elsewhere
                    def team_ok(teams, stage):
                        others = Counter(t for n, t in teams.items() if n != stage)
                        return not others or others.most_common(1)[0][0] == teams.get(stage)
                    if not (team_ok(a_teams, st) and team_ok(b_teams, st)):
                        reason = "team moved with the name — more than the identity is wrong"

            if reason:
                unfixable.append((race, year, st, bib, shown_name,
                                  f["majority_identity"][0], reason))
                handled.add(bib)
            else:
                fixable.append((race, year, st, bib, partner["bib"],
                                f["majority_identity"][0],
                                partner["majority_identity"][0]))
                handled |= {bib, partner["bib"]}
    return fixable, unfixable


def apply_year(race, key, pairs):
    """Apply swaps for one year; returns number of files rewritten."""
    stages, save = load_stage_rows(race, key)
    touched = set()
    for _, _, st, bib_a, bib_b, _, _ in pairs:
        j = stages[st]
        ia, ib = row_index(j, bib_a), row_index(j, bib_b)
        swap_identity(j["rows"][ia], j["rows"][ib])
        touched.add(st)
    return save(touched)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=list(STAGE_RACES), default=None)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    races = [args.race] if args.race else list(STAGE_RACES)
    all_fix, all_bad, files, years = [], [], 0, []

    for race in races:
        for year, ydir in year_sources(race):
            if args.year and year != args.year:
                continue
            fixable, unfixable = plan_year(race, year, ydir)
            if not fixable and not unfixable:
                continue
            all_fix += fixable
            all_bad += unfixable
            if fixable:
                years.append((race, year))
                print(f"\n{race} {year}: {len(fixable)} swap pair(s)")
                for _, _, st, a, b, na, nb in fixable:
                    print(f"    stage {st:>2}: bib {a} <-> bib {b}   "
                          f"restore '{na}' / '{nb}'")
                if args.apply:
                    files += apply_year(race, ydir, fixable)

    if all_bad:
        print(f"\nNOT fixed ({len(all_bad)}) — left alone rather than guessed:")
        for race, year, st, bib, shown, expect, why in all_bad:
            print(f"    {race} {year} st{st} bib {bib}: shows '{shown}', "
                  f"expected '{expect}' — {why}")

    print(f"\n{'[DRY RUN] ' if not args.apply else ''}"
          f"{len(all_fix)} pair(s) across {len(years)} race-year(s); "
          f"{len(all_bad)} left unresolved")
    if args.apply:
        print(f"Rewrote {files} stage file(s). Push the fix into the database:")
        for race, year in years:
            if race == "tour":
                # ingest_race.py covers the Giro and Vuelta only, and the TDF
                # ingest is additive — it skips an edition already in the DB.
                # reingest_tdf_stage.py is the one route that replaces a stage
                # in place, per affected stage rather than per year.
                for st in sorted({p[2] for p in all_fix
                                  if p[0] == race and p[1] == year}):
                    print(f"  python3 reingest_tdf_stage.py --year {year} "
                          f"--stage {st} --apply")
            else:
                print(f"  python3 ingest_race.py --race {race} {year}")


if __name__ == "__main__":
    main()
