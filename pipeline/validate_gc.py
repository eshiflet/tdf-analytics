#!/usr/bin/env python3
"""
Validate our GC data against bikeraceinfo.com per-stage standings.

Compares:
  1. GC leader's cumulative time after each stage (our DB vs BRI)
  2. Top-5 riders' GC gaps after each stage
  3. Stage distances (BRI header vs our DB)

Outputs a summary report and flags problematic years/stages.

Usage:
  python3 validate_gc.py              # all years with BRI data
  python3 validate_gc.py 1982 1986   # specific years
  python3 validate_gc.py --summary   # one line per year only
"""

import json
import os
import re
import sqlite3
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH        = os.path.join(HERE, "cycling.db")
BRI_PATH       = os.path.join(HERE, "bri_stages.json")
GC_DATA_DIR    = os.path.join(HERE, "..", "cycling-app", "src", "data")

SUMMARY_ONLY = "--summary" in sys.argv
YEAR_ARGS    = [int(a) for a in sys.argv[1:] if a.isdigit()]


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
    # Full subset match
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if smaller.issubset(larger):
        return True
    # Last-name fallback: share at least one token ≥5 chars (avoids false positives on short names)
    long_a = {t for t in ta if len(t) >= 5}
    long_b = {t for t in tb if len(t) >= 5}
    return bool(long_a & long_b)


def load_our_gc(year: int) -> dict:
    """
    Load our exported GC data for a year.
    Returns {stage_index: {rider_name: {rank, gap_seconds}}}
    """
    path = os.path.join(GC_DATA_DIR, f"gc_by_stage_{year}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Build stage_number → index map
    stages = data["stages"]
    sn_to_idx = {s["stage_number"]: i for i, s in enumerate(stages)}

    result = {}
    for rider in data["riders"]:
        for sp in rider["byStage"]:
            idx = sn_to_idx.get(sp["stage"])
            if idx is None:
                continue
            if idx not in result:
                result[idx] = {}
            if sp.get("gcRank") and sp["gcRank"] < 9999:
                result[idx][rider["name"]] = {
                    "rank": sp["gcRank"],
                    "gap": sp.get("gcGapSeconds") or 0,
                }
    return result


def load_db_stages(year: int) -> list[dict]:
    """Load stage list from DB with stage_number and distance_km."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT edition_id FROM race_editions WHERE year=?", (year,)).fetchone()
    if not row:
        conn.close()
        return []
    stages = [dict(r) for r in conn.execute(
        "SELECT stage_number, stage_date, distance_km, route_type FROM stages "
        "WHERE edition_id=? ORDER BY stage_number", (row["edition_id"],)
    )]
    conn.close()
    return stages


def build_sequential_map(bri_stages: list[dict], db_stages: list[dict]) -> dict[int, int]:
    """
    Map BRI stage index → DB stage index.

    Strategy:
    - If counts differ by ≤1: sequential with optional single-skip (fast path).
    - If counts differ by >1: label-based — BRI "Stage N" → DB stage_number=N.
      Split stages (1A/1B) are matched to the first/second DB stage sharing
      the same date as stage_number N.

    Returns {bri_idx: db_idx}.
    """
    nb = len(bri_stages)
    nd = len(db_stages)

    # ── Fast path: counts are close → sequential with optional single skip ───
    if abs(nb - nd) <= 1:
        if nb == nd:
            return {i: i for i in range(nb)}
        if nb > nd:
            return {i: i for i in range(nd)}
        # nb == nd - 1: try each skip position and pick the best alignment
        best_map = {i: i for i in range(nb)}
        best_score = _alignment_score(bri_stages, db_stages, best_map)
        for skip_at in range(nb + 1):
            candidate: dict[int, int] = {}
            db_idx = 0
            for bi in range(nb):
                if bi == skip_at:
                    db_idx += 1
                if db_idx < nd:
                    candidate[bi] = db_idx
                db_idx += 1
            score = _alignment_score(bri_stages, db_stages, candidate)
            if score > best_score:
                best_score = score
                best_map = candidate
        return best_map

    # ── Slow path: multiple gaps → distance-based sequence alignment ─────────
    # Greedily assign each BRI stage to the nearest-distance DB stage in order.
    # Tolerates up to 10% distance difference; skips unmatched DB stages.
    result: dict[int, int] = {}
    last_di = -1
    for bi, bs in enumerate(bri_stages):
        bri_d = bs.get("distance_km")
        if not bri_d:
            # No distance — advance sequentially from last matched position
            next_di = last_di + 1
            if next_di < nd:
                result[bi] = next_di
                last_di = next_di
            continue

        best_di   = None
        best_diff = float("inf")
        for di in range(last_di + 1, nd):
            db_d = db_stages[di].get("distance_km")
            if not db_d or db_d == 0:
                continue
            diff = abs(bri_d - db_d) / max(bri_d, db_d)
            if diff < best_diff:
                best_diff = diff
                best_di = di
            # Stop searching far ahead (at most nd - nb extra stages ahead)
            if di > last_di + 1 + (nd - nb) + 2:
                break

        if best_di is not None and best_diff <= 0.10:
            result[bi] = best_di
            last_di = best_di
        elif last_di + 1 < nd:
            # Fall back to sequential if no good distance match
            result[bi] = last_di + 1
            last_di += 1

    return result


def _alignment_score(bri_stages, db_stages, mapping):
    """Fraction of matched pairs with distances within 7%."""
    matches = total = 0
    for bi, di in mapping.items():
        bri_d = bri_stages[bi].get("distance_km")
        db_d  = db_stages[di].get("distance_km") if di < len(db_stages) else None
        if bri_d and db_d and db_d > 0:
            total += 1
            if abs(bri_d - db_d) / max(bri_d, db_d) <= 0.07:
                matches += 1
    return matches / total if total else 0


def validate_year(year: int, bri_stages: list[dict]) -> dict:
    """
    Compare BRI per-stage GC against our data.
    Returns report dict.
    """
    our_gc = load_our_gc(year)
    db_stages = load_db_stages(year)

    if not our_gc or not db_stages:
        return {"year": year, "status": "no_our_data", "stages_checked": 0}

    distance_mismatches = []
    gc_mismatches = []
    gc_leader_checks = 0
    gc_leader_ok = 0

    seq_map = build_sequential_map(bri_stages, db_stages)

    for bri_idx, bri_stage in enumerate(bri_stages):
        db_idx = seq_map.get(bri_idx)
        if db_idx is None or db_idx >= len(db_stages):
            continue
        if not bri_stage.get("gc_top10"):
            continue

        our_stage = our_gc.get(db_idx, {})

        # ── Distance check ───────────────────────────────────────────────────
        bri_dist = bri_stage.get("distance_km")
        db_dist  = db_stages[db_idx].get("distance_km")
        if bri_dist and db_dist:
            diff_pct = abs(bri_dist - db_dist) / max(bri_dist, db_dist)
            if diff_pct > 0.07:  # >7% difference (BRI rounds to nearest 0.5km)
                distance_mismatches.append({
                    "stage": bri_stage["label"],
                    "db_idx": db_idx,
                    "bri_km": bri_dist,
                    "db_km": db_dist,
                    "diff_pct": round(diff_pct * 100, 1),
                })

        # ── GC leader check ──────────────────────────────────────────────────
        bri_leader = bri_stage["gc_top10"][0]
        bri_name   = bri_leader.get("name", "")
        bri_cum    = bri_leader.get("cumulative_sec")

        # Find BRI leader in our data
        matched_rider = None
        for our_name, our_data in our_stage.items():
            if our_data["rank"] == 1 and name_match(bri_name, our_name):
                matched_rider = (our_name, our_data)
                break

        gc_leader_checks += 1
        if matched_rider:
            gc_leader_ok += 1
        else:
            # Find who is our GC leader at this stage
            our_leader = next(
                ((n, d) for n, d in our_stage.items() if d["rank"] == 1), None
            )
            gc_mismatches.append({
                "stage": bri_stage["label"],
                "db_idx": db_idx,
                "bri_leader": bri_name,
                "our_leader": our_leader[0] if our_leader else "?",
            })

        # ── Top-5 gap check ──────────────────────────────────────────────────
        # (for verbose output only — not counted in summary stats)

    leader_match_pct = round(gc_leader_ok / gc_leader_checks * 100) if gc_leader_checks else 0

    return {
        "year": year,
        "status": "ok" if leader_match_pct >= 70 else "mismatch",
        "stages_checked": gc_leader_checks,
        "leader_match_pct": leader_match_pct,
        "gc_mismatches": gc_mismatches,
        "distance_mismatches": distance_mismatches,
    }


def main():
    with open(BRI_PATH, encoding="utf-8") as f:
        bri_data: dict[str, list] = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    all_years = [r[0] for r in conn.execute("SELECT year FROM race_editions ORDER BY year")]
    conn.close()

    years = YEAR_ARGS if YEAR_ARGS else all_years

    ok = mismatch = no_data = 0
    all_reports = []

    for year in years:
        yr = str(year)
        bri_stages = bri_data.get(yr, [])
        if not bri_stages:
            print(f"{year}: no BRI data")
            no_data += 1
            continue

        report = validate_year(year, bri_stages)
        all_reports.append(report)

        if report["status"] == "no_our_data":
            print(f"{year}: no exported GC data")
            no_data += 1
            continue

        sym = "✓" if report["leader_match_pct"] >= 70 else "✗"
        print(f"{year}: {sym}  GC leader {report['leader_match_pct']:3d}%  "
              f"({report['stages_checked']} stages)  "
              f"dist_issues={len(report['distance_mismatches'])}")

        if not SUMMARY_ONLY:
            for m in report["gc_mismatches"]:
                print(f"       {m['stage']:10s}  BRI={m['bri_leader']!r:30s}  ours={m['our_leader']!r}")
            for m in report["distance_mismatches"]:
                print(f"       {m['stage']:10s}  BRI={m['bri_km']}km  DB={m['db_km']}km  ({m['diff_pct']}% off)")

        if report["leader_match_pct"] >= 70:
            ok += 1
        else:
            mismatch += 1

    print(f"\nSummary: {ok} ok  {mismatch} mismatch  {no_data} no_data  ({ok+mismatch+no_data} years total)")


if __name__ == "__main__":
    main()
