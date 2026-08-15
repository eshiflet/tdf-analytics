#!/usr/bin/env python3
"""
Finds NO-OP entries in {giro,vuelta}_races_summary_overrides.json — override
fields that pin exactly the value export_race_summary.py already computes from
the DB.

Why this exists: an override is a hardcoded value that silently outranks real
data. That is the whole point when it's correcting something (Giro 1992's
elevation sums to an absurd 70 m, so it's pinned to null), but a pin that
merely restates the computed value is dead weight that will quietly mask the
DB the day the DB changes underneath it — and nothing warns about it. Most of
these were left behind when the curated {race}_gc_winner_times.json lookup
moved ahead of the `winner_row` gate in export_race_summary.py: from that point
on the exporter produced the right winner time by itself, and the override rows
that had been compensating became redundant without becoming visible.

Method: re-run the real exporter twice, once with the real overrides file and
once with an empty one, both redirected to temp files via --out, then diff
field by field. It deliberately does NOT reimplement the exporter's priority
logic — a checker that duplicates the logic it checks agrees with the bug.

Per FIELD, not per year: a year can pin three fields where only one does work
(Giro 1992 pins two winner/slowest times that match the computation, plus the
elevation null that doesn't).

Usage:
  python3 audit_summary_overrides.py                  # report only
  python3 audit_summary_overrides.py --strip          # also delete the no-ops
  python3 audit_summary_overrides.py --race giro
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RACES = ("giro", "vuelta")


def fmt(field, v):
    if v is None:
        return "—"
    if "Seconds" in field:
        v = int(v)
        return f"{v // 3600}:{v % 3600 // 60:02d}:{v % 60:02d}"
    return str(v)


def render(race, overrides_path, out_path):
    subprocess.run(
        [sys.executable, os.path.join(HERE, "export_race_summary.py"),
         "--race", race, "--overrides", overrides_path, "--out", out_path],
        capture_output=True, check=True,
    )
    with open(out_path, encoding="utf-8") as f:
        return {r["year"]: r for r in json.load(f)}


def audit(race, tmpdir):
    overrides_path = os.path.join(HERE, f"{race}_races_summary_overrides.json")
    with open(overrides_path, encoding="utf-8") as f:
        overrides = json.load(f)

    empty_path = os.path.join(tmpdir, f"{race}_empty.json")
    with open(empty_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    pinned = render(race, overrides_path, os.path.join(tmpdir, f"{race}_pinned.json"))
    bare = render(race, empty_path, os.path.join(tmpdir, f"{race}_bare.json"))

    working, noop = [], []
    for year, fields in overrides.items():
        for field, value in fields.items():
            computed = bare[int(year)].get(field)
            # Compare against the BARE render, not the raw override value: the
            # exporter rounds and int()s, so a pin can differ from the file's
            # literal and still be a no-op in the shipped output.
            if computed == pinned[int(year)].get(field):
                noop.append((int(year), field, value))
            else:
                working.append((int(year), field, computed, value))
    return overrides, working, noop


def main():
    races = [sys.argv[sys.argv.index("--race") + 1]] if "--race" in sys.argv else list(RACES)
    strip = "--strip" in sys.argv
    total_noop = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        for race in races:
            overrides, working, noop = audit(race, tmpdir)
            n_fields = sum(len(v) for v in overrides.values())
            total_noop += len(noop)
            print(f"\n=== {race}: {len(overrides)} years / {n_fields} pinned fields — "
                  f"{len(working)} do work, {len(noop)} are no-ops ===")
            for year, field, computed, value in sorted(working):
                print(f"  WORKS  {year} {field}: computed {fmt(field, computed)} "
                      f"-> pinned {fmt(field, value)}")
            if noop:
                years = sorted({y for y, _, _ in noop})
                print(f"  NO-OP  {len(noop)} fields across {len(years)} years: "
                      f"{years[0]}–{years[-1]}")

            if strip and noop:
                drop = {(y, f) for y, f, _ in noop}
                cleaned = {}
                for year, fields in overrides.items():
                    kept = {f: v for f, v in fields.items() if (int(year), f) not in drop}
                    if kept:
                        cleaned[year] = kept
                path = os.path.join(HERE, f"{race}_races_summary_overrides.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(cleaned, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                print(f"  stripped -> {len(cleaned)} years remain in {os.path.basename(path)}")

                # Prove the strip changed nothing the app can see.
                after = render(race, path, os.path.join(tmpdir, f"{race}_after.json"))
                before_path = os.path.join(HERE, "..", "cycling-app", "src", "data",
                                           race, "all_races_summary.json")
                with open(before_path, encoding="utf-8") as f:
                    before = {r["year"]: r for r in json.load(f)}
                diffs = [y for y in before if before[y] != after.get(y)]
                if diffs:
                    sys.exit(f"  ERROR: stripping changed {len(diffs)} year(s): {diffs[:10]}")
                print("  verified: shipped output is byte-identical after stripping")

    if not strip and total_noop:
        print(f"\n{total_noop} no-op field(s) total. Re-run with --strip to remove them.")


if __name__ == "__main__":
    main()
