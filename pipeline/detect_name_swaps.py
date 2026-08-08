#!/usr/bin/env python3
"""
Detect adjacent-row name-swap scraping artifacts across all races/years.

Two complementary checks:
  1. BIB CONSISTENCY (raw scrape files): within a race-year, a bib number must
     map to the same rider identity (name/slug/nat) across all stages. Any bib
     that shows a different identity on even one stage is flagged.
     Covers: Giro 2020-2026, Vuelta all years, TDF 2026.

  2. GC TRAJECTORY (exported JSON): a rider whose GC rank makes an implausible
     jump (far-back → top-5 → far-back) across three consecutive stages is
     flagged. Catches swaps where raw scrape files no longer exist (TDF 2020-2025).

Usage:
  python3 detect_name_swaps.py            # all races, all years
  python3 detect_name_swaps.py --year 2026
  python3 detect_name_swaps.py --race giro
  python3 detect_name_swaps.py --recent-only  # 2020+ only (much faster)
"""

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

from race_common import StageRow

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "cycling-app", "src", "data")

# ── helpers ──────────────────────────────────────────────────────────────────

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_row(row):
    """Return (bib, name, slug, nat) from a scrape row."""
    if len(row) != 15:
        return None
    sr = StageRow.from_list(row)
    if not sr.bib or not sr.slug:
        return None
    return sr.bib, sr.name, sr.slug, sr.nat


# ── Check 1: bib consistency from raw scrape files ───────────────────────────

def check_bib_consistency_tdf2026():
    """Check TDF 2026: tdf_2026_full.json + scrapes/stage_N.json."""
    findings = []
    stages_by_n = {}

    full_path = os.path.join(HERE, "tdf_2026_full.json")
    if os.path.exists(full_path):
        data = load_json(full_path)
        for s in data.get("stages", []):
            stages_by_n[s["n"]] = s["rows"]

    scrapes_dir = os.path.join(HERE, "scrapes")
    for path in sorted(glob.glob(os.path.join(scrapes_dir, "stage_*.json"))):
        s = load_json(path)
        stages_by_n[s["n"]] = s["rows"]

    findings.extend(_bib_check("tour", 2026, stages_by_n))
    return findings


def check_bib_consistency_dir(race, scrapes_dir, min_year=0):
    """Check a scrapes directory laid out as YEAR/stage_N.json."""
    findings = []
    year_dirs = sorted(
        d for d in glob.glob(os.path.join(scrapes_dir, "*"))
        if os.path.isdir(d) and os.path.basename(d).isdigit()
        and int(os.path.basename(d)) >= min_year
    )
    for year_dir in year_dirs:
        year = int(os.path.basename(year_dir))
        stages_by_n = {}
        for path in sorted(glob.glob(os.path.join(year_dir, "stage_*.json"))):
            try:
                s = load_json(path)
                n = s.get("n")
                if n is None:
                    # derive from filename
                    n = int(os.path.basename(path).replace("stage_", "").replace(".json", ""))
                stages_by_n[n] = s.get("rows", [])
            except Exception:
                pass
        if stages_by_n:
            findings.extend(_bib_check(race, year, stages_by_n))
    return findings


# Bib collisions confirmed against PCS to be upstream data errors rather than
# name swaps — two genuinely different riders sharing one bib. Unlike the
# within-stage duplicates detected below, these never appear in the SAME stage,
# so nothing in the data itself distinguishes them from a swap; each was
# verified by hand and is listed here so the ingest gate stops blocking.
#
#   giro 1952 bib 104 — Pasquale Fornara (5 stages) and Elio Brasola (stage 3).
#     PCS's own rider page for Elio Brasola confirms he rode the 1952 Giro for
#     Bottecchia-Ursus and finished 19th on GC; he is Annibale Brasola's
#     brother. Bib 103 is unused by that team. Both names are correct; only
#     the bib is wrong, and PCS gives no basis for choosing the right one.
VERIFIED_BIB_COLLISIONS = {
    ("giro", 1952, "104"),
}


def _bib_check(race, year, stages_by_n):
    """
    For each bib, collect all (name, slug, nat) observed across stages.
    Flag any bib whose identity isn't unanimous.

    Two distinct conditions come out of this, and conflating them produces
    false swap reports:

      'duplicate_bib' — the same bib appears MORE THAN ONCE within a single
        stage, on two different riders (invariably teammates). That is an
        upstream PCS defect, not a scraping artifact and not a name swap:
        PCS's own 2015 Giro startlist lists "92 GRMAY / 92 FERRARI", and
        1952's Elio Brasola (a real Bottecchia-Ursus rider, 19th on GC that
        year) shares bib 104 with Pasquale Fornara while 103 sits unused.
        Both riders and both results are correct; only the bib is wrong, and
        we have no source for the true one.

      'bib_inconsistency' — a bib maps to different riders on DIFFERENT
        stages. That is the real swap artifact worth blocking on.

    Bibs hitting the first condition are excluded from the second, since a
    duplicated bib makes "the identity of bib N on stage S" ill-defined.
    """
    findings = []
    bib_identities = defaultdict(dict)  # bib -> {stage_n: (name, slug, nat)}
    duplicated = set(
        bib for (r, y, bib) in VERIFIED_BIB_COLLISIONS if r == race and y == year
    )

    for stage_n, rows in stages_by_n.items():
        per_stage = defaultdict(set)
        for row in rows:
            parsed = parse_row(row)
            if parsed is None:
                continue
            bib, name, slug, nat = parsed
            per_stage[bib].add((name, slug, nat))
            bib_identities[bib][stage_n] = (name, slug, nat)
        for bib, idents in per_stage.items():
            if len(idents) > 1:
                duplicated.add(bib)

    for bib in sorted(duplicated):
        names = sorted({
            ident[0]
            for rows in stages_by_n.values()
            for parsed in (parse_row(r) for r in rows)
            if parsed and parsed[0] == bib
            for ident in [parsed[1:]]
        })
        findings.append({
            "type": "duplicate_bib",
            "race": race,
            "year": year,
            "bib": bib,
            "riders": names,
        })
        bib_identities.pop(bib, None)

    for bib, by_stage in bib_identities.items():
        identities = set(v for v in by_stage.values())
        if len(identities) <= 1:
            continue

        # Find which stages are the outliers
        # Majority identity = most common
        from collections import Counter
        counts = Counter(by_stage.values())
        majority = counts.most_common(1)[0][0]
        outlier_stages = sorted(
            n for n, ident in by_stage.items() if ident != majority
        )
        outlier_names = [by_stage[n][0] for n in outlier_stages]

        # Skip if every outlier has the same name as the majority (only slug/nat differs —
        # likely a minor data inconsistency, not a name swap between two riders)
        if all(name == majority[0] for name in outlier_names):
            continue

        findings.append({
            "type": "bib_inconsistency",
            "race": race,
            "year": year,
            "bib": bib,
            "majority_identity": majority,
            "outlier_stages": outlier_stages,
            "outlier_names": outlier_names,
        })
    return findings


# ── Check 2: GC trajectory anomaly from exported JSON ────────────────────────

# A swap produces: R_before (far back) → R_peak (top 5) → R_after (back near R_before).
# Genuine GC improvement produces: R_before → R_peak → R_after ≈ R_peak (stays improved).
# So the key distinguishing signal is that R_after returns close to R_before AND stays
# far from R_peak.
BEFORE_THRESHOLD  = 15   # rider was outside top 15 before the anomaly stage
PEAK_THRESHOLD    = 5    # appeared in top 5
MIN_JUMP          = 15   # rank improvement must be ≥ 15 positions
RETURN_TO_BEFORE  = 10   # R_after must be within 10 of R_before (returned to origin)
RETURN_MIN_RANK   = 8    # R_after must also be worse than 8 (didn't stay in contention)


def check_gc_trajectory(race, min_year=2020, specific_year=None):
    """
    Scan exported gc_by_stage_*.json files for GC rank anomalies.
    """
    if race == "tour":
        pattern = os.path.join(DATA_DIR, "tour", "gc_by_stage_*.json")
    else:
        pattern = os.path.join(DATA_DIR, race, "gc_by_stage_*.json")

    findings = []
    for path in sorted(glob.glob(pattern)):
        year = int(os.path.basename(path).replace("gc_by_stage_", "").replace(".json", ""))
        if specific_year and year != specific_year:
            continue
        if not specific_year and year < min_year:
            continue

        try:
            data = load_json(path)
        except Exception:
            continue

        riders = data.get("riders", [])
        for rider in riders:
            rid = rider.get("id", "")
            name = rider.get("name", "")
            by_stage = rider.get("byStage", [])
            ranks = [(s["stage"], s.get("gcRank")) for s in by_stage if s.get("gcRank")]

            for i in range(1, len(ranks) - 1):
                s_before, r_before = ranks[i - 1]
                s_peak,   r_peak   = ranks[i]
                s_after,  r_after  = ranks[i + 1]

                if (r_before > BEFORE_THRESHOLD
                        and r_peak < PEAK_THRESHOLD
                        and (r_before - r_peak) >= MIN_JUMP
                        and abs(r_after - r_before) <= RETURN_TO_BEFORE
                        and r_after > RETURN_MIN_RANK):
                    findings.append({
                        "type": "gc_trajectory",
                        "race": race,
                        "year": year,
                        "rider": f"{name} ({rid})",
                        "stage_before": s_before, "rank_before": r_before,
                        "stage_peak":   s_peak,   "rank_peak":   r_peak,
                        "stage_after":  s_after,  "rank_after":  r_after,
                    })
    return findings


# ── main ─────────────────────────────────────────────────────────────────────

# Known-good GC trajectory cases that the heuristic flags as suspicious but are
# confirmed correct via PCS or raw scrape files.  Listed here for reference so
# they aren't re-investigated when this script is run again.
#
# TDF 2021 stage 7  Mohorič  33→4→34  — 18 km solo break gained 3+ min on peloton
# TDF 2022 stage 10 Kämna    21→2→21  — long breakaway briefly put him 2nd in GC
# Giro 2025 stage 8 Ulissi   30→1→21  — scrape file confirms GC leader after break
# Giro 2025 stage 8 Fortunato 25→2→22 — same stage
# Vuelta 2022 stage 5 Craddock 69→4→65 — Molard stage; break reshuffled entire GC
# Vuelta 2022 stage 5 Arndt  56→3→60  — same stage
# Vuelta 2025 stage 6 Vervaeke 41→4→33 — scrape file confirms top-5 GC

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--race", choices=["tour", "giro", "vuelta"], default=None)
    parser.add_argument("--recent-only", action="store_true",
                        help="only 2020+; the default now covers every year, since "
                             "the historical reconstructions are where swaps hide")
    args = parser.parse_args()

    min_year = 2020 if args.recent_only else 0
    specific_year = args.year

    races_to_check = [args.race] if args.race else ["tour", "giro", "vuelta"]

    all_findings = []

    for race in races_to_check:
        # ── bib consistency ──
        if race == "tour":
            if not specific_year or specific_year == 2026:
                all_findings.extend(check_bib_consistency_tdf2026())
        elif race == "giro":
            d = os.path.join(HERE, "giro_scrapes")
            all_findings.extend(check_bib_consistency_dir(race, d, min_year=min_year))
        elif race == "vuelta":
            d = os.path.join(HERE, "vuelta_scrapes")
            all_findings.extend(check_bib_consistency_dir(race, d, min_year=min_year))

        # ── GC trajectory ──
        all_findings.extend(check_gc_trajectory(race, min_year=min_year, specific_year=specific_year))

    # ── deduplicate: if bib_inconsistency and gc_trajectory both fire for the
    #    same race/year/stage, show both but mark them as corroborating.

    if not all_findings:
        print("No anomalies found.")
        return

    # Group and print
    by_race_year = defaultdict(list)
    for f in all_findings:
        by_race_year[(f["race"], f["year"])].append(f)

    total = 0
    for (race, year), findings in sorted(by_race_year.items()):
        print(f"\n{'='*60}")
        print(f"  {race.upper()} {year}")
        print(f"{'='*60}")
        for f in findings:
            total += 1
            if f["type"] == "duplicate_bib":
                print(f"  [DUP] bib {f['bib']} used by {len(f['riders'])} riders "
                      f"in the same stage(s): {', '.join(f['riders'])}")
                print("        upstream PCS defect — results are correct, the bib isn't")
            elif f["type"] == "bib_inconsistency":
                maj = f["majority_identity"]
                print(f"  [BIB] bib {f['bib']} → majority: {maj[0]} ({maj[2]})")
                for stage_n, outlier_name in zip(f["outlier_stages"], f["outlier_names"]):
                    print(f"        stage {stage_n}: shows '{outlier_name}' instead")
            else:
                print(f"  [GC]  {f['rider']}")
                print(f"        stage {f['stage_before']}: rank {f['rank_before']}"
                      f" → stage {f['stage_peak']}: rank {f['rank_peak']}"
                      f" → stage {f['stage_after']}: rank {f['rank_after']}")

    print(f"\n{total} anomalies found across {len(by_race_year)} race-years.")


if __name__ == "__main__":
    main()
