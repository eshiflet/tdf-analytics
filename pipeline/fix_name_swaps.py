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

THE REPAIR LIVES IN THE FILE, SO A RE-SCRAPE UNDOES IT. The defect reproduces
on every PCS request, so re-fetching a repaired stage writes the transposed
rows straight back — silently, since the file is the source of truth. Every
applied pair is therefore recorded in name_swaps_applied.json, and

  python3 fix_name_swaps.py --replay --apply

puts back any that a scrape has reverted. It is idempotent (a pair already
reading correctly is left alone) and refuses to act when a row shows neither
of the two recorded names, so run it after every scrape. The ingest swap gate
is the backstop: a reverted pair blocks its edition rather than reaching the
database.

Usage:
  python3 fix_name_swaps.py --dry-run
  python3 fix_name_swaps.py --race giro --year 1973 --dry-run
  python3 fix_name_swaps.py --apply
  python3 fix_name_swaps.py --replay                 # what a re-scrape undid
  python3 fix_name_swaps.py --replay --apply         # put it back
"""

import argparse
import glob
import sqlite3
import json
import os
from collections import Counter, defaultdict
from datetime import date

from detect_name_swaps import _bib_check
from race_common import (DB_PATH, SOURCE_DERIVED, STAGE_RACES, StageRow,
                         load_stage_rows, record_provenance,
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


MANIFEST = os.path.join(HERE, "name_swaps_applied.json")

MANIFEST_README = (
    "Name swaps repaired in the scrape files. The repair is written INTO the "
    "file, so re-scraping that stage fetches PCS's transposed rows again and "
    "silently undoes it. This records every pair so it can be replayed: "
    "python3 fix_name_swaps.py --replay --apply. Nothing here is a judgement "
    "call — each entry was a mutual, adjacent, team-corroborated transposition "
    "that the detector resolved on its own."
)


def load_manifest():
    if not os.path.exists(MANIFEST):
        return {"_README": MANIFEST_README, "swaps": []}
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def record_swaps(pairs):
    """Add applied pairs to the manifest, keyed so re-applying cannot duplicate."""
    man = load_manifest()
    man["_README"] = MANIFEST_README
    seen = {(s["race"], s["year"], s["stage"], s["bib_a"], s["bib_b"])
            for s in man["swaps"]}
    added = 0
    for race, year, st, bib_a, bib_b, name_a, name_b in pairs:
        key = (race, year, st, bib_a, bib_b)
        if key in seen or (race, year, st, bib_b, bib_a) in seen:
            continue
        man["swaps"].append({
            "race": race, "year": year, "stage": st,
            "bib_a": bib_a, "bib_b": bib_b,
            # The names as they should stand AFTER the repair: bib_a carries
            # name_a. That is what replay compares against.
            "name_a": name_a, "name_b": name_b,
            "recorded": date.today().isoformat(),
        })
        seen.add(key)
        added += 1
    man["swaps"].sort(key=lambda s: (s["race"], s["year"], s["stage"], s["bib_a"]))
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return added


def replay(race_filter, year_filter, apply, quiet=False):
    """Re-apply recorded swaps to any file that has reverted to PCS's order.

    Idempotent by construction: a pair whose rows already read correctly is
    left alone, so this is safe to run after every scrape — which is exactly
    where scrape_race.py calls it from. `quiet` suppresses the summary when
    there was nothing to do, so a clean scrape stays readable; anything
    actually restored, or skipped, still prints.
    """
    man = load_manifest()
    by_year = defaultdict(list)
    for s in man["swaps"]:
        if race_filter and s["race"] != race_filter:
            continue
        if year_filter and s["year"] != year_filter:
            continue
        by_year[(s["race"], s["year"])].append(s)
    if not by_year:
        if not quiet:
            print("no recorded swaps match")
        return 0

    reverted, intact, missing, files = [], 0, [], 0
    for (race, year), swaps in sorted(by_year.items()):
        keys = {y: ydir for y, ydir in year_sources(race)}
        if year not in keys:
            missing.append(f"{race} {year}: no scrape files")
            continue
        stages, save = load_stage_rows(race, keys[year])
        touched = set()
        for s in swaps:
            j = stages.get(s["stage"])
            if not j:
                missing.append(f"{race} {year} st{s['stage']}: stage file gone")
                continue
            ia, ib = row_index(j, s["bib_a"]), row_index(j, s["bib_b"])
            if ia is None or ib is None:
                missing.append(f"{race} {year} st{s['stage']}: bib "
                               f"{s['bib_a']}/{s['bib_b']} not on the stage")
                continue
            shown_a = StageRow.from_list(j["rows"][ia]).name
            if shown_a == s["name_a"]:
                intact += 1
                continue
            if shown_a != s["name_b"]:
                missing.append(f"{race} {year} st{s['stage']}: bib {s['bib_a']} "
                               f"shows '{shown_a}', expected '{s['name_a']}' or "
                               f"'{s['name_b']}' — not replaying blind")
                continue
            reverted.append((race, year, s["stage"], s["bib_a"], s["bib_b"],
                             s["name_a"], s["name_b"]))
            if apply:
                swap_identity(j["rows"][ia], j["rows"][ib])
                touched.add(s["stage"])
        if apply and touched:
            files += save(touched)

    if quiet and not reverted and not missing:
        return 0
    print(f"{len(man['swaps'])} recorded pair(s); {intact} already correct, "
          f"{len(reverted)} reverted by a re-scrape")
    for race, year, st, a, b, na, nb in reverted:
        print(f"    {race} {year} st{st}: bib {a} <-> bib {b}   restore '{na}' / '{nb}'")
    for m in missing:
        print(f"    SKIPPED {m}")
    if apply:
        print(f"\nRewrote {files} stage file(s).")
    elif reverted:
        print("\n[DRY RUN] re-run with --apply to restore these.")
    return len(reverted)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=list(STAGE_RACES), default=None)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-db", action="store_true",
                    help="repair in the database, for editions with no scrape file")
    ap.add_argument("--replay", action="store_true",
                    help="re-apply swaps recorded in name_swaps_applied.json, for "
                         "files a re-scrape has reverted. Run after every scrape.")
    args = ap.parse_args()

    if args.replay:
        replay(args.race, args.year, args.apply)
        return

    if args.from_db:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        plan = db_plan(cur)
        print(f"{'[DRY RUN] ' if not args.apply else ''}{len(plan)} corroborated "
              f"pair(s) in the database")
        for year, n, _, ra, rb in plan:
            print(f"  {year} st{n:<3} bib {rb['bib_number']} -> "
                  f"{ra['rider_id'].split('/')[-1]}, "
                  f"bib {ra['bib_number']} -> {rb['rider_id'].split('/')[-1]}"
                  f"   (ranks {ra['stage_rank']}/{rb['stage_rank']}, "
                  f"gc {ra['gc_rank']}<->{rb['gc_rank']})")
        if args.apply:
            db_apply(cur, plan)
            conn.commit()
            print(f"\nswapped {len(plan)} pair(s)")
        conn.close()
        return
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
    if args.apply and all_fix:
        recorded = record_swaps(all_fix)
        print(f"Recorded {recorded} pair(s) in {os.path.basename(MANIFEST)} — "
              "replay them after any re-scrape with --replay --apply.")
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




# ── the same repair, sourced from the database ──────────────────────────────
# Columns bound to the ROW rather than to the rider. rider_id stays put and
# everything else moves, which is the same swap the file mode performs from the
# other side: there the identity moves within a fixed row, here the row's facts
# move between two fixed identities. The end state is identical, and this
# direction needs no sentinel to get past UNIQUE(stage_id, rider_id).
ROW_COLUMNS = ["team_id", "bib_number", "stage_rank", "status",
               "finish_time_seconds", "gap_seconds", "bonus_seconds",
               "penalty_seconds", "uci_points", "pcs_points",
               "gc_rank", "gc_gap_seconds", "age_at_race"]


def db_plan(cur):
    """[(year, stage_n, stage_id, rowA, rowB)] for corroborated DB-only swaps.

    The same four criteria the file mode applies, read from the database:
    mutual, strong majority, adjacent, team-bound.
    """
    import collections
    out, seen = [], set()
    riders = cur.execute("""
        SELECT st.edition_id, e.year, sr.rider_id
          FROM stage_results sr
          JOIN stages st ON st.stage_id = sr.stage_id
          JOIN race_editions e ON e.edition_id = st.edition_id
          JOIN races r ON r.race_id = e.race_id
         WHERE sr.bib_number IS NOT NULL AND r.race_type = 'stage_race'
         GROUP BY st.edition_id, sr.rider_id
        HAVING COUNT(DISTINCT sr.bib_number) > 1""").fetchall()

    prof = {}
    for r in riders:
        rows = cur.execute("""
            SELECT st.stage_number n, st.stage_id, sr.* FROM stage_results sr
              JOIN stages st ON st.stage_id = sr.stage_id
             WHERE st.edition_id=? AND sr.rider_id=? ORDER BY st.stage_number""",
            (r["edition_id"], r["rider_id"])).fetchall()
        bibs = collections.Counter(x["bib_number"] for x in rows
                                   if x["bib_number"] is not None)
        major, support = bibs.most_common(1)[0]
        teams = collections.Counter(x["team_id"] for x in rows
                                    if x["bib_number"] == major and x["team_id"])
        prof[(r["edition_id"], r["rider_id"])] = {
            "year": r["year"], "major": major, "support": support,
            "total": sum(bibs.values()),
            "team": teams.most_common(1)[0][0] if teams else None,
            "rows": {x["n"]: x for x in rows},
            "odd": [x for x in rows if x["bib_number"] not in (None, major)]}

    by_major = {(k[0], v["major"]): k for k, v in prof.items()}
    for k, a in prof.items():
        if k in seen:
            continue
        for row_a in a["odd"]:
            partner = by_major.get((k[0], row_a["bib_number"]))
            if not partner or partner in seen:
                continue
            b = prof[partner]
            row_b = b["rows"].get(row_a["n"])
            if row_b is None or row_b["bib_number"] != a["major"]:
                continue                      # mutual
            if not (a["support"] > 1 and a["support"] * 2 > a["total"]
                    and b["support"] > 1 and b["support"] * 2 > b["total"]):
                continue                      # strong
            ra, rb = row_a["stage_rank"], row_b["stage_rank"]
            if ra is None or rb is None or abs(ra - rb) != 1:
                continue                      # adjacent
            if row_a["team_id"] != b["team"] or row_b["team_id"] != a["team"]:
                continue                      # team-bound
            seen |= {k, partner}
            out.append((a["year"], row_a["n"], row_a["stage_id"], row_a, row_b))
            break
    return out


def db_apply(cur, plan):
    sets = ", ".join(f"{c}=?" for c in ROW_COLUMNS)
    for _, _, stage_id, ra, rb in plan:
        for target, source in ((ra, rb), (rb, ra)):
            cur.execute(f"UPDATE stage_results SET {sets} WHERE result_id=?",
                        [source[c] for c in ROW_COLUMNS] + [target["result_id"]])
        for row in (ra, rb):
            record_provenance(
                cur, "stage_results", stage_id, f"rider_id:{row['rider_id']}",
                SOURCE_DERIVED,
                source_ref="adjacent-row name swap; the bib's settled identity "
                           "across the rest of the edition is the authority",
                script="fix_name_swaps.py")


if __name__ == "__main__":
    main()
