#!/usr/bin/env python3
"""
Apply PCS GC winner time corrections to vuelta_races_summary_overrides.json.

Reads vuelta_gc_time_corrections.json (year -> pcs_winner_seconds from PCS),
computes corrected slowestFinisherTimeSeconds as winner + max_gap from DB,
and merges into vuelta_races_summary_overrides.json.

Run after check_vuelta_gc_times.py has produced vuelta_gc_time_corrections.json.
"""

import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
CORRECTIONS_PATH = os.path.join(HERE, "vuelta_gc_time_corrections.json")
OVERRIDES_PATH = os.path.join(HERE, "vuelta_races_summary_overrides.json")


def main():
    with open(CORRECTIONS_PATH) as f:
        corrections = {int(k): v for k, v in json.load(f).items()}

    overrides = {}
    if os.path.exists(OVERRIDES_PATH):
        with open(OVERRIDES_PATH) as f:
            overrides = {int(k): v for k, v in json.load(f).items()}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    race_row = cur.execute("SELECT race_id FROM races WHERE name=?", ("Vuelta a España",)).fetchone()
    race_id = race_row["race_id"]

    applied = 0
    for year, pcs_winner_secs in sorted(corrections.items()):
        edition = cur.execute(
            "SELECT edition_id FROM race_editions WHERE race_id=? AND year=?",
            (race_id, year),
        ).fetchone()
        if not edition:
            continue

        last_stage = cur.execute(
            "SELECT stage_id FROM stages WHERE edition_id=? ORDER BY stage_number DESC LIMIT 1",
            (edition["edition_id"],),
        ).fetchone()

        slowest = None
        if last_stage:
            max_gap = cur.execute(
                "SELECT MAX(gc_gap_seconds) FROM stage_results WHERE stage_id=? AND status='FINISHED'",
                (last_stage["stage_id"],),
            ).fetchone()[0]
            if max_gap is not None:
                slowest = pcs_winner_secs + int(max_gap)

        entry = overrides.get(year, {})
        entry["gcWinnerTimeSeconds"] = pcs_winner_secs
        if slowest is not None:
            entry["slowestFinisherTimeSeconds"] = slowest
        overrides[year] = entry
        applied += 1

    conn.close()

    with open(OVERRIDES_PATH, "w") as f:
        json.dump({str(k): v for k, v in sorted(overrides.items())}, f, indent=2)

    print(f"Applied corrections for {applied} years -> {OVERRIDES_PATH}")


if __name__ == "__main__":
    main()
