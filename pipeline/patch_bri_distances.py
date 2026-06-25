#!/usr/bin/env python3
"""
Patch missing or suspicious stage distances in cycling.db using bikeraceinfo.com data.

Uses the same distance-based sequential alignment from validate_gc.py to map
BRI stages to DB stages, then:
  1. Fills in DB stages where distance_km IS NULL or 0
  2. Reports stages where BRI and DB distances differ by >10% (for manual review)

Does NOT overwrite existing non-zero DB distances automatically.

Usage:
  python3 patch_bri_distances.py            # dry run: show what would change
  python3 patch_bri_distances.py --apply    # write changes to DB
  python3 patch_bri_distances.py 1979       # specific year (dry run)
  python3 patch_bri_distances.py 1979 --apply
"""

import json
import os
import sqlite3
import sys

HERE    = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
BRI_PATH = os.path.join(HERE, "bri_stages.json")

APPLY = "--apply" in sys.argv
YEAR_ARGS = [int(a) for a in sys.argv[1:] if a.isdigit()]


# ── Stage alignment (same logic as validate_gc.py) ────────────────────────────

def _alignment_score(bri_stages, db_stages, mapping):
    matches = total = 0
    for bi, di in mapping.items():
        bri_d = bri_stages[bi].get("distance_km")
        db_d  = db_stages[di]["distance_km"] if di < len(db_stages) else None
        if bri_d and db_d and db_d > 0:
            total += 1
            if abs(bri_d - db_d) / max(bri_d, db_d) <= 0.07:
                matches += 1
    return matches / total if total else 0


def build_stage_map(bri_stages: list[dict], db_stages: list[dict]) -> dict[int, int]:
    nb, nd = len(bri_stages), len(db_stages)

    if abs(nb - nd) <= 1:
        if nb == nd:
            return {i: i for i in range(nb)}
        if nb > nd:
            return {i: i for i in range(nd)}
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

    # Distance-based greedy alignment for years with many gaps
    result: dict[int, int] = {}
    last_di = -1
    for bi, bs in enumerate(bri_stages):
        bri_d = bs.get("distance_km")
        if not bri_d:
            next_di = last_di + 1
            if next_di < nd:
                result[bi] = next_di
                last_di = next_di
            continue
        best_di   = None
        best_diff = float("inf")
        for di in range(last_di + 1, min(nd, last_di + 2 + (nd - nb) + 2)):
            db_d = db_stages[di]["distance_km"]
            if not db_d or db_d == 0:
                continue
            diff = abs(bri_d - db_d) / max(bri_d, db_d)
            if diff < best_diff:
                best_diff = diff
                best_di = di
        if best_di is not None and best_diff <= 0.10:
            result[bi] = best_di
            last_di = best_di
        elif last_di + 1 < nd:
            result[bi] = last_di + 1
            last_di += 1
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    with open(BRI_PATH, encoding="utf-8") as f:
        bri_data: dict[str, list] = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    all_years = [r[0] for r in conn.execute("SELECT year FROM race_editions ORDER BY year")]

    years = YEAR_ARGS if YEAR_ARGS else all_years

    patches   = []  # (stage_id, new_km, reason)
    conflicts = []  # (year, label, bri_km, db_km, pct_off) — existing but differs

    for year in years:
        bri_stages = bri_data.get(str(year), [])
        if not bri_stages:
            continue

        row = conn.execute("SELECT edition_id FROM race_editions WHERE year=?", (year,)).fetchone()
        if not row:
            continue
        edition_id = row["edition_id"]

        db_rows = list(conn.execute(
            "SELECT stage_id, stage_number, distance_km FROM stages "
            "WHERE edition_id=? ORDER BY stage_number", (edition_id,)
        ))
        db_stages = [{"stage_id": r["stage_id"], "stage_number": r["stage_number"],
                      "distance_km": r["distance_km"] or 0} for r in db_rows]

        stage_map = build_stage_map(bri_stages, db_stages)

        for bi, di in stage_map.items():
            if di >= len(db_stages):
                continue
            bri_d = bri_stages[bi].get("distance_km")
            db_s  = db_stages[di]
            if not bri_d:
                continue

            db_km = db_s["distance_km"]
            label = bri_stages[bi].get("label", f"idx{bi}")

            if not db_km or db_km == 0:
                # Missing in DB — patch it
                patches.append((db_s["stage_id"], bri_d, f"{year} {label}"))
            else:
                pct = abs(bri_d - db_km) / max(bri_d, db_km) * 100
                if pct > 10:
                    conflicts.append({
                        "year": year, "label": label,
                        "bri_km": bri_d, "db_km": db_km,
                        "pct_off": round(pct, 1),
                    })

    # ── Report ────────────────────────────────────────────────────────────────
    print(f"{'DRY RUN — ' if not APPLY else ''}Distance patches: {len(patches)}")
    for stage_id, km, reason in patches:
        print(f"  PATCH  {reason}: → {km} km  (stage_id={stage_id})")

    print(f"\nDistance conflicts (existing DB value differs >10% from BRI): {len(conflicts)}")
    for c in conflicts:
        print(f"  CONFLICT  {c['year']} {c['label']:10s}  BRI={c['bri_km']}km  DB={c['db_km']}km  ({c['pct_off']}% off)")

    if APPLY and patches:
        cur = conn.cursor()
        for stage_id, km, reason in patches:
            cur.execute("UPDATE stages SET distance_km=? WHERE stage_id=?", (km, stage_id))
        conn.commit()
        print(f"\nApplied {len(patches)} patches to {DB_PATH}")
    elif not APPLY:
        print(f"\nRun with --apply to write changes.")

    conn.close()


if __name__ == "__main__":
    main()
