#!/usr/bin/env python3
"""
Apply all detected adjacent-row name swaps for TDF 2026.

For each (stage, bib_a, bib_b) entry: swap the name/slug/nat fields
between the two rows in tdf_2026_full.json AND in scrapes/stage_N.json
(for stages 8+).  Then rebuilds cycling.db for 2026 and re-exports.

Run with --dry-run to preview without writing anything.

STALE — the SWAPS list below (stages 1-15) has already been applied for
real; verified 2026-07-25 via `python3 detect_name_swaps.py --year 2026`
(reports clean) and by checking bib 83/51 in cycling.db (consistently
Foss/Seixas across all 20 stages). Do NOT run this without --dry-run
first: since it's not idempotent, re-applying an already-fixed SWAPS
entry swaps the two riders back to *wrong*. Newly-found swaps since
stage 16+ were fixed directly in the scrape files instead (see
add_stages.py's swap-detection gate) rather than added here.
"""

import json
import os
import sqlite3
import subprocess
import sys

from race_common import StageRow, swap_identity

HERE = os.path.dirname(os.path.abspath(__file__))
FULL_JSON   = os.path.join(HERE, "tdf_2026_full.json")
SCRAPES_DIR = os.path.join(HERE, "scrapes")
DB_PATH     = os.path.join(HERE, "cycling.db")

# (stage_number, bib_a, bib_b) — swap name/slug/nat between these two rows
# Each pair was confirmed by the bib-consistency check in detect_name_swaps.py
SWAPS = [
    # stage 1
    (1,  "83",  "51"),   # Foss ↔ Seixas
    # stage 2
    (2,  "83",  "61"),   # Foss ↔ Higuita
    (2,  "51",  "71"),   # Seixas ↔ Martinez
    # stage 3
    (3,  "21",   "2"),   # Evenepoel ↔ del Toro
    (3,  "18",  "82"),   # Piganzoli ↔ Arensman
    # stage 4
    (4, "161", "225"),   # Izagirre ↔ Nicolau
    # stage 5
    (5,  "85", "213"),   # Godon ↔ Bittner
    (5, "131",  "33"),   # Girmay ↔ Pedersen
    # stage 6
    (6,  "31",  "25"),   # Ayuso ↔ Lipowitz
    # stage 7
    (7, "178",  "63"),   # Wright ↔ Gate
    (7,  "85",  "33"),   # Godon ↔ Pedersen
    # stage 8
    (8,  "64", "188"),   # Kanter ↔ Russo
    (8, "187", "178"),   # Pacher ↔ Wright
    # stage 9
    (9,  "11",  "25"),   # Vingegaard ↔ Lipowitz
    (9, "201", "202"),   # Jegat ↔ Breuillard
    # stage 10
    (10,  "2", "171"),   # del Toro ↔ Pidcock
    # stage 11
    (11, "221", "112"),  # Gaviria ↔ Ackermann
    # stage 13
    (13, "133", "194"),  # Bennett ↔ Hirschi
    (13, "183",   "7"),  # Braz Afonso ↔ Wellens
    # stage 14
    (14,  "31",  "25"),  # Ayuso ↔ Lipowitz
    (14,   "8",  "32"),  # Yates ↔ Gee-West
    (14,  "28",  "52"),  # Van Gils ↔ Benoot
    # stage 15
    (15,  "31",  "25"),  # Ayuso ↔ Lipowitz
    (15,  "77", "148"),  # Tiberi ↔ Rubio
    (15,  "22",  "38"),  # Cattaneo ↔ Verona
]


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def swap_names_in_rows(rows, bib_a, bib_b, stage_n, source):
    """Swap name/slug/nat between the two rows identified by bib."""
    row_a = row_b = None
    for row in rows:
        if len(row) != 15:
            print(f"  WARN stage {stage_n} ({source}): skipping malformed row "
                  f"(expected 15 fields, got {len(row)}): {row!r}")
            continue
        sr = StageRow.from_list(row)
        if sr.bib == bib_a:
            row_a = row
        elif sr.bib == bib_b:
            row_b = row
    if row_a is None or row_b is None:
        missing = []
        if row_a is None: missing.append(bib_a)
        if row_b is None: missing.append(bib_b)
        print(f"  WARN stage {stage_n} ({source}): bib(s) {missing} not found — skipped")
        return False
    swap_identity(row_a, row_b)
    print(f"  swapped stage {stage_n} ({source}): "
          f"bib {bib_a} ({row_a[5]}) ↔ bib {bib_b} ({row_b[5]})")
    return True


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=== DRY RUN — no files will be written ===\n")

    # ── 1. Load tdf_2026_full.json ────────────────────────────────────────────
    full = load_json(FULL_JSON)
    # Build a stage_number → rows map
    full_by_n = {s["n"]: s["rows"] for s in full["stages"]}

    # ── 2. Load per-stage scrape files (stages 8+) ───────────────────────────
    scrape_files = {}  # stage_n -> (path, data)
    for stage_n in set(n for n, _, _ in SWAPS if n >= 8):
        path = os.path.join(SCRAPES_DIR, f"stage_{stage_n}.json")
        if os.path.exists(path):
            scrape_files[stage_n] = (path, load_json(path))
        else:
            print(f"WARN: scrapes/stage_{stage_n}.json not found")

    # ── 3. Apply swaps ────────────────────────────────────────────────────────
    print("Applying swaps to tdf_2026_full.json:")
    changed_full   = False
    changed_scrapes = set()

    for stage_n, bib_a, bib_b in SWAPS:
        if stage_n not in full_by_n:
            print(f"  WARN: stage {stage_n} not in tdf_2026_full.json — skipped")
            continue
        ok = swap_names_in_rows(full_by_n[stage_n], bib_a, bib_b, stage_n, "full.json")
        if ok:
            changed_full = True

        # Also apply to scrape file if it exists
        if stage_n in scrape_files:
            _, scrape_data = scrape_files[stage_n]
            ok2 = swap_names_in_rows(scrape_data["rows"], bib_a, bib_b, stage_n, f"stage_{stage_n}.json")
            if ok2:
                changed_scrapes.add(stage_n)

    # ── 4. Write files ────────────────────────────────────────────────────────
    if not dry_run:
        if changed_full:
            save_json(FULL_JSON, full)
            print(f"\nWrote {FULL_JSON}")
        for stage_n in sorted(changed_scrapes):
            path, data = scrape_files[stage_n]
            save_json(path, data)
            print(f"Wrote {path}")
    else:
        print("\n(dry run — files not written)")
        return

    # ── 5. Rebuild cycling.db for 2026 ───────────────────────────────────────
    print("\nRebuilding cycling.db for 2026...")
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT edition_id FROM race_editions WHERE race_id=1 AND year=2026"
    ).fetchone()
    if row:
        eid = row[0]
        conn.execute(
            "DELETE FROM stage_results WHERE stage_id IN "
            "(SELECT stage_id FROM stages WHERE edition_id=?)", (eid,)
        )
        conn.execute("DELETE FROM stages WHERE edition_id=?", (eid,))
        conn.execute("DELETE FROM race_editions WHERE edition_id=?", (eid,))
        conn.commit()
        print(f"  Deleted edition {eid} from DB")
    conn.close()

    result = subprocess.run(
        [sys.executable, os.path.join(HERE, "add_pre1960.py"), "2026"],
        capture_output=True, text=True, cwd=HERE,
    )
    if result.returncode != 0:
        print(f"ERROR: add_pre1960.py failed:\n{result.stderr}")
        sys.exit(1)
    print(f"  {result.stdout.strip()}")

    # ── 6. Export ─────────────────────────────────────────────────────────────
    print("\nExporting...")
    for cmd, label in [
        ([sys.executable, "export_gc.py", "--year", "2026"], "export_gc.py"),
        ([sys.executable, "export_riders_index.py"], "export_riders_index.py"),
        ([sys.executable, "export_all_races_summary.py"], "export_all_races_summary.py"),
    ]:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
        if result.returncode != 0:
            print(f"ERROR: {label} failed:\n{result.stderr}")
            sys.exit(1)
        print(f"  {label}: OK")

    # ── 7. Validate ───────────────────────────────────────────────────────────
    print("\nValidating...")
    result = subprocess.run(
        [sys.executable, "validate_exports.py", "--year", "2026"],
        capture_output=True, text=True, cwd=HERE,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(f"ERRORS found:\n{result.stderr}")
        sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
