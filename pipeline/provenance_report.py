#!/usr/bin/env python3
"""
Report what the DB knows about where its data came from.

Reads the data_provenance table (see schema.sql) and summarises coverage by
field and source, so you can answer "is this number trustworthy, and can I
safely re-scrape it?" before touching anything.

The number that matters most is the 'unknown' count: those are stored values
whose origin was never recorded and can't be proven from artifacts on disk.
They are not necessarily wrong — they're unverified. Re-scraping a field by
source_slug is what converts 'unknown' into 'pcs'.

Usage:
  python3 provenance_report.py                     # summary by field/source
  python3 provenance_report.py --race vuelta       # one race
  python3 provenance_report.py --unknown           # editions with unknown values
  python3 provenance_report.py --stage 20742       # everything about one stage
"""

import argparse
import sqlite3
from collections import defaultdict

from race_common import DB_PATH, EXPORT_RACE_INFO


def summary(cur, race_name=None):
    where, params = "", []
    if race_name:
        where = """ AND dp.entity_id IN (
            SELECT s.stage_id FROM stages s
            JOIN race_editions re ON s.edition_id = re.edition_id
            JOIN races r ON re.race_id = r.race_id WHERE r.name = ?)"""
        params = [race_name]

    rows = cur.execute(f"""
        SELECT dp.field, dp.source, COUNT(*) n
        FROM data_provenance dp
        WHERE dp.entity = 'stages'{where}
        GROUP BY dp.field, dp.source
    """, params).fetchall()

    by_field = defaultdict(dict)
    for r in rows:
        by_field[r["field"]][r["source"]] = r["n"]

    sources = sorted({r["source"] for r in rows})
    if not sources:
        print("No provenance recorded yet — run backfill_provenance.py")
        return

    head = f"  {'field':<17}" + "".join(f"{s:>13}" for s in sources) + f"{'total':>9}"
    print(head)
    print("  " + "-" * (len(head) - 2))
    for field in sorted(by_field):
        counts = by_field[field]
        line = f"  {field:<17}" + "".join(f"{counts.get(s, 0):>13,}" for s in sources)
        print(line + f"{sum(counts.values()):>9,}")

    total = sum(sum(v.values()) for v in by_field.values())
    unknown = sum(v.get("unknown", 0) for v in by_field.values())
    print(f"\n  {total:,} recorded values; {unknown:,} ({unknown/total*100:.0f}%) "
          "of unproven origin")


def unknown_editions(cur, race_name=None):
    where, params = "", []
    if race_name:
        where = " AND r.name = ?"
        params = [race_name]
    rows = cur.execute(f"""
        SELECT r.name race, re.year, dp.field, COUNT(*) n
        FROM data_provenance dp
        JOIN stages s ON s.stage_id = dp.entity_id
        JOIN race_editions re ON s.edition_id = re.edition_id
        JOIN races r ON re.race_id = r.race_id
        WHERE dp.entity = 'stages' AND dp.source = 'unknown'{where}
        GROUP BY r.name, re.year, dp.field
        ORDER BY r.name, re.year, dp.field
    """, params).fetchall()
    if not rows:
        print("No values of unknown origin.")
        return
    per_year = defaultdict(dict)
    for r in rows:
        per_year[(r["race"], r["year"])][r["field"]] = r["n"]
    print(f"  {len(per_year)} edition(s) hold values of unproven origin:\n")
    for (race, year), fields in sorted(per_year.items()):
        detail = ", ".join(f"{f}={n}" for f, n in sorted(fields.items()))
        print(f"  {race[:6]:<7}{year}  {detail}")


def one_stage(cur, stage_id):
    s = cur.execute("""
        SELECT s.*, re.year, r.name race FROM stages s
        JOIN race_editions re ON s.edition_id = re.edition_id
        JOIN races r ON re.race_id = r.race_id WHERE s.stage_id = ?
    """, (stage_id,)).fetchone()
    if not s:
        print(f"No stage with stage_id={stage_id}")
        return
    print(f"  {s['race']} {s['year']} stage {s['stage_number']} "
          f"(slug {s['source_slug']})")
    print(f"  {s['start_location']} -> {s['finish_location']}\n")
    rows = cur.execute(
        "SELECT field, source, source_ref, script, recorded_at FROM data_provenance "
        "WHERE entity='stages' AND entity_id=? ORDER BY field", (stage_id,)
    ).fetchall()
    if not rows:
        print("  (no provenance recorded)")
        return
    for r in rows:
        value = s[r["field"]] if r["field"] in s.keys() else "-"
        print(f"  {r['field']:<16} = {str(value):<12} {r['source']:<12} "
              f"{r['recorded_at'][:10]}")
        print(f"  {'':<16}   {r['source_ref']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=sorted(EXPORT_RACE_INFO), default=None)
    ap.add_argument("--unknown", action="store_true")
    ap.add_argument("--stage", type=int, default=None)
    args = ap.parse_args()

    race_name = EXPORT_RACE_INFO[args.race][0] if args.race else None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if args.stage is not None:
        one_stage(cur, args.stage)
    elif args.unknown:
        unknown_editions(cur, race_name)
    else:
        label = race_name or "all races"
        print(f"\nProvenance coverage — {label}\n")
        summary(cur, race_name)
    conn.close()


if __name__ == "__main__":
    main()
