#!/usr/bin/env python3
"""
Reconcile KOM points from multiple sources into a single authoritative dataset.

Sources (in priority order for final totals):
  1. Wikipedia  — final totals, top ~10 riders
  2. bikeraceinfo — final totals, top ~6 riders
  3. PCS (kom_points.json) — per-stage per-climb points (incomplete for many years)

Strategy per year:
  - Compute each rider's PCS cumulative total
  - Compare against reference totals (Wikipedia preferred, BRI fallback)
  - Classify year coverage: good (≥80%), partial (20–80%), broken (<20%)
  - Good:    keep PCS per-stage data as-is
  - Partial: scale each stage's points proportionally to match reference total
  - Broken:  distribute reference total across mountain/hilly stages,
             weighted by each stage's vertical_meters (elevation gain)

Output: kom_points_reconciled.json  (same structure as kom_points.json)
        kom_reconcile_report.json   (year-by-year decisions and coverage stats)

Usage:
  python3 reconcile_kom.py
  python3 reconcile_kom.py --dry-run   # report only, no output files
"""

import json
import math
import os
import re
import sqlite3
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH        = os.path.join(HERE, "cycling.db")
PCS_PATH       = os.path.join(HERE, "kom_points.json")
TOTALS_PATH    = os.path.join(HERE, "kom_totals.json")
OUT_PATH       = os.path.join(HERE, "kom_points_reconciled.json")
REPORT_PATH    = os.path.join(HERE, "kom_reconcile_report.json")

GOOD_THRESHOLD    = 0.80   # PCS total ≥ 80% of reference → keep as-is
PARTIAL_THRESHOLD = 0.20   # PCS total ≥ 20% → scale; below → redistribute


def normalize(name: str) -> str:
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return " ".join(name.split())


def name_match(a: str, b: str) -> bool:
    ta = set(normalize(a).split())
    tb = set(normalize(b).split())
    if not ta or not tb:
        return False
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return smaller.issubset(larger)


def best_reference(wiki: list, bri: list) -> list[tuple[str, int]]:
    """Merge Wikipedia and BRI, preferring Wikipedia when they conflict."""
    merged: dict[str, int] = {}

    # Start with BRI (lower priority)
    for name, pts in bri:
        merged[name] = pts

    # Wikipedia overrides BRI for same rider
    for wiki_name, wiki_pts in wiki:
        matched = False
        for existing_name in list(merged.keys()):
            if name_match(wiki_name, existing_name):
                merged[existing_name] = wiki_pts  # Wikipedia wins
                matched = True
                break
        if not matched:
            merged[wiki_name] = wiki_pts

    return sorted(merged.items(), key=lambda x: -x[1])


def pcs_totals(pcs_stages: list[dict]) -> dict[str, int]:
    """Sum per-stage PCS dicts into cumulative totals per rider slug."""
    totals: dict[str, int] = {}
    for stage in pcs_stages:
        for slug, pts in stage.items():
            totals[slug] = totals.get(slug, 0) + pts
    return totals


def slug_to_display(slug: str) -> str:
    """Convert 'rider/eddy-merckx' → 'eddy merckx' for fuzzy matching."""
    return slug.replace("rider/", "").replace("-", " ")


def coverage_ratio(pcs_tot: dict[str, int], ref: list[tuple[str, int]]) -> float:
    """
    Average (our_total / ref_total) across the top-N reference riders.
    Returns 0.0 if no matches found.
    """
    ratios = []
    for ref_name, ref_pts in ref[:6]:
        if ref_pts == 0:
            continue
        our_pts = 0
        for slug, pts in pcs_tot.items():
            if name_match(ref_name, slug_to_display(slug)):
                our_pts = pts
                break
        ratios.append(min(our_pts / ref_pts, 1.5))  # cap at 150% to handle over-counts
    return sum(ratios) / len(ratios) if ratios else 0.0


def scale_stages(pcs_stages: list[dict], pcs_tot: dict[str, int],
                 ref: list[tuple[str, int]]) -> list[dict]:
    """
    Scale each stage's points so final totals match reference.
    Scale factor is per-rider (so riders with more data scale less).
    """
    # Build per-rider scale factor
    scale: dict[str, float] = {}
    for ref_name, ref_pts in ref:
        if ref_pts == 0:
            continue
        for slug, our_pts in pcs_tot.items():
            if name_match(ref_name, slug_to_display(slug)):
                if our_pts > 0:
                    scale[slug] = ref_pts / our_pts
                break

    if not scale:
        return pcs_stages

    # Apply per-stage, rounding to integers
    result = []
    for stage in pcs_stages:
        new_stage: dict[str, int] = {}
        for slug, pts in stage.items():
            factor = scale.get(slug, 1.0)
            new_pts = round(pts * factor)
            if new_pts > 0:
                new_stage[slug] = new_pts
        result.append(new_stage)
    return result


def distribute_totals(ref: list[tuple[str, int]], stage_info: list[dict],
                      rider_id_map: dict[str, str]) -> list[dict]:
    """
    For years with no PCS per-stage data: distribute reference totals across
    mountain and hilly stages, weighted by vertical_meters.

    rider_id_map: ref_name → rider_id slug (best match from DB)
    """
    # Compute stage weights from elevation gain (mountain/hilly stages only)
    weights = []
    for s in stage_info:
        rt = s.get("route_type", "F") or "F"
        vm = s.get("vertical_meters") or 0
        if rt in ("M", "H") and vm > 0:
            weights.append(vm)
        else:
            weights.append(0)

    total_weight = sum(weights)
    if total_weight == 0:
        # Fallback: distribute evenly across all stages
        weights = [1.0] * len(stage_info)
        total_weight = len(stage_info)

    fractions = [w / total_weight for w in weights]

    # Build per-stage dicts
    result: list[dict[str, int]] = [{} for _ in stage_info]
    for ref_name, ref_pts in ref:
        slug = rider_id_map.get(ref_name)
        if not slug or ref_pts == 0:
            continue
        # Distribute proportionally, accumulating rounding error
        remainder = ref_pts
        for i, frac in enumerate(fractions):
            if i == len(fractions) - 1:
                pts = remainder
            else:
                pts = round(ref_pts * frac)
                remainder -= pts
            if pts > 0:
                result[i][slug] = pts

    return result


def load_stage_info(year: int) -> list[dict]:
    """Load stage metadata from DB for elevation-weighted distribution."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT edition_id FROM race_editions WHERE year=?", (year,)).fetchone()
    if not row:
        conn.close()
        return []
    stages = [dict(r) for r in conn.execute(
        "SELECT stage_number, vertical_meters, route_type FROM stages "
        "WHERE edition_id=? ORDER BY stage_number", (row["edition_id"],)
    )]
    conn.close()
    return stages


def build_rider_id_map(year: int, ref: list[tuple[str, int]]) -> dict[str, str]:
    """
    Map reference rider names → DB rider_id slugs using fuzzy name matching.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT edition_id FROM race_editions WHERE year=?", (year,)).fetchone()
    if not row:
        conn.close()
        return {}
    db_riders = [dict(r) for r in conn.execute(
        """SELECT DISTINCT r.rider_id, r.full_name
           FROM stage_results sr
           JOIN stages st ON st.stage_id = sr.stage_id
           JOIN riders r ON r.rider_id = sr.rider_id
           WHERE st.edition_id=?""", (row["edition_id"],)
    )]
    conn.close()

    mapping: dict[str, str] = {}
    for ref_name, _ in ref:
        for db_rider in db_riders:
            if name_match(ref_name, db_rider["full_name"]):
                mapping[ref_name] = db_rider["rider_id"]
                break
    return mapping


def reconcile_year(year: int, pcs_stages: list[dict],
                   ref: list[tuple[str, int]]) -> tuple[list[dict], dict]:
    """
    Returns (reconciled_stages, report_entry).
    """
    pcs_tot = pcs_totals(pcs_stages)
    cov = coverage_ratio(pcs_tot, ref) if ref else 0.0

    if not ref:
        strategy = "no_reference"
        reconciled = pcs_stages
    elif cov >= GOOD_THRESHOLD:
        strategy = "keep_pcs"
        reconciled = pcs_stages
    elif cov >= PARTIAL_THRESHOLD:
        strategy = "scale_pcs"
        reconciled = scale_stages(pcs_stages, pcs_tot, ref)
    else:
        strategy = "distribute_reference"
        stage_info = load_stage_info(year)
        rider_map = build_rider_id_map(year, ref)
        reconciled = distribute_totals(ref, stage_info, rider_map)

    # Verify reconciled totals
    rec_tot = pcs_totals(reconciled)
    verification = []
    for ref_name, ref_pts in ref[:8]:
        our_pts = 0
        for slug, pts in rec_tot.items():
            if name_match(ref_name, slug_to_display(slug)):
                our_pts = pts
                break
        pct = round(abs(our_pts - ref_pts) / ref_pts * 100, 1) if ref_pts else 0
        verification.append({
            "name": ref_name, "ref": ref_pts, "ours": our_pts, "pct_off": pct
        })

    match_rate = sum(1 for v in verification if v["pct_off"] < 5) / len(verification) * 100 if verification else 0

    report = {
        "year": year,
        "strategy": strategy,
        "pcs_coverage": round(cov, 3),
        "match_rate_pct": round(match_rate),
        "reference_riders": len(ref),
        "verification": verification,
    }
    return reconciled, report


def main():
    dry_run = "--dry-run" in sys.argv

    with open(PCS_PATH, encoding="utf-8") as f:
        pcs_data: dict[str, list[dict]] = json.load(f)

    with open(TOTALS_PATH, encoding="utf-8") as f:
        totals_data: dict[str, dict] = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    all_years = [r[0] for r in conn.execute("SELECT year FROM race_editions ORDER BY year")]
    conn.close()

    reconciled_all: dict[str, list[dict]] = {}
    reports: list[dict] = []

    strat_counts: dict[str, int] = {}

    for year in all_years:
        yr = str(year)
        pcs_stages = pcs_data.get(yr, [])
        entry = totals_data.get(yr, {})
        wiki = [(n, p) for n, p in entry.get("wikipedia", [])]
        bri  = [(n, p) for n, p in entry.get("bikeraceinfo", [])]
        ref  = best_reference(wiki, bri)

        reconciled, report = reconcile_year(year, pcs_stages, ref)
        reconciled_all[yr] = reconciled
        reports.append(report)
        strat_counts[report["strategy"]] = strat_counts.get(report["strategy"], 0) + 1

        sym = "✓" if report["match_rate_pct"] >= 70 else "✗"
        print(f"{year}: {sym}  {report['strategy']:22s}  coverage={report['pcs_coverage']:.0%}  "
              f"match={report['match_rate_pct']}%  ref_riders={report['reference_riders']}")

    print(f"\nStrategy breakdown: {strat_counts}")
    print(f"Match ≥70%: {sum(1 for r in reports if r['match_rate_pct'] >= 70)}/{len(reports)} years")

    if not dry_run:
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(reconciled_all, f, ensure_ascii=False)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(reports, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {OUT_PATH}")
        print(f"Wrote {REPORT_PATH}")
    else:
        print("\n[dry-run] No files written.")


if __name__ == "__main__":
    main()
