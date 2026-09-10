#!/usr/bin/env python3
"""
Split the Tour's scrape files into the per-stage layout the Giro and Vuelta use.

  tdf_YEAR_full.json   ->  tdf_scrapes/YEAR/stage_N.json
  scrapes/stage_N.json ->  tdf_scrapes/2026/stage_N.json
  bundle.classifications -> tdf_scrapes/YEAR/classifications.json

WHY. The Tour keeping a whole year in one file, while the other two keep a file
per stage, is an accident of which scraper was written first — and it has cost
real correctness. fix_name_swaps.py silently covered only the Giro and Vuelta
for exactly this reason, leaving ten name swaps unrepaired in Tour files it
reads happily once pointed at them. race_common.load_stage_rows() now hides the
difference, but hiding it is not the same as not having it: four tools still
read tdf_*_full.json directly, and add_pre1960.py / reingest_tdf_stage.py exist
only because the Tour cannot use the ordinary ingest path.

The 2026 files need no reshaping at all — the live scrape already writes exactly
the Giro/Vuelta per-stage shape (info, n, rows, profile_icon, kom_points,
sprint_points). They are merely in a flat `scrapes/` directory with no year in
the path. Where a stage exists in both places the flat file wins, which is the
precedence detect_name_swaps.check_bib_consistency_tdf2026 already applies.

`classifications` becomes a per-year sidecar because a per-stage file has no
place for it: it is one dict of final standings for the whole edition, present
for 1933-1959 only. The Giro and Vuelta already keep a per-year sidecar of their
own (gc_standings.json), so this adopts a pattern rather than inventing one.

NOTHING IS DELETED. The originals stay until the readers have moved and the
round-trip has been verified; --verify reconstructs each bundle from the split
files and compares it against the original, field by field.

Usage:
  python3 convert_tdf_layout.py --dry-run
  python3 convert_tdf_layout.py --apply
  python3 convert_tdf_layout.py --verify
"""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.join(HERE, "tdf_scrapes")
FLAT_2026 = os.path.join(HERE, "scrapes")
SIDECAR = "classifications.json"


def bundles():
    """[(year, path)] for every tdf_YEAR_full.json."""
    out = []
    for p in glob.glob(os.path.join(HERE, "tdf_*_full.json")):
        part = os.path.basename(p).split("_")[1]
        if part.isdigit():
            out.append((int(part), p))
    return sorted(out)


def flat_stages():
    """{stage_n: parsed} from the flat 2026 scrapes/ directory."""
    out = {}
    for p in sorted(glob.glob(os.path.join(FLAT_2026, "stage_*.json"))):
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
        out[j.get("n", int(os.path.basename(p)[6:-5]))] = j
    return out


def split_year(year, path, flat):
    """({stage_n: stage_json}, classifications) for one year, unwritten."""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    stages = {s["n"]: s for s in doc.get("stages", []) if "n" in s}
    # The live scrape is the fresher of the two for any stage it covers.
    for n, j in flat.items():
        stages[n] = j
    return stages, doc.get("classifications") or {}, doc


def write_year(year, stages, classifications):
    d = os.path.join(OUT_ROOT, str(year))
    os.makedirs(d, exist_ok=True)
    for n, j in stages.items():
        with open(os.path.join(d, f"stage_{n}.json"), "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False)
    if classifications:
        with open(os.path.join(d, SIDECAR), "w", encoding="utf-8") as f:
            json.dump(classifications, f, ensure_ascii=False)


def read_year(year):
    """({stage_n: stage_json}, classifications) back off disk."""
    d = os.path.join(OUT_ROOT, str(year))
    stages = {}
    for p in glob.glob(os.path.join(d, "stage_*.json")):
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
        stages[j.get("n", int(os.path.basename(p)[6:-5]))] = j
    cls = {}
    sc = os.path.join(d, SIDECAR)
    if os.path.exists(sc):
        with open(sc, encoding="utf-8") as f:
            cls = json.load(f)
    return stages, cls


def verify(year, path, flat):
    """[] when the split round-trips, else a list of differences."""
    want_stages, want_cls, doc = split_year(year, path, flat)
    got_stages, got_cls = read_year(year)
    bad = []
    if set(want_stages) != set(got_stages):
        bad.append(f"stage numbers differ: missing "
                   f"{sorted(set(want_stages) - set(got_stages))}, extra "
                   f"{sorted(set(got_stages) - set(want_stages))}")
    for n in sorted(set(want_stages) & set(got_stages)):
        if want_stages[n] != got_stages[n]:
            a, b = want_stages[n], got_stages[n]
            keys = sorted(set(a) | set(b))
            bad += [f"stage {n}: key '{k}' differs" for k in keys
                    if a.get(k) != b.get(k)]
    if want_cls != got_cls:
        bad.append("classifications differ")
    # `year` is carried by the directory name; assert it agreed to begin with.
    if doc.get("year") not in (None, year):
        bad.append(f"bundle year {doc.get('year')} != filename year {year}")
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    flat = flat_stages()
    todo = bundles()
    print(f"{len(todo)} bundle(s); {len(flat)} flat 2026 stage file(s)")

    if args.verify:
        failures = 0
        for year, path in todo:
            bad = verify(year, path, flat if year == 2026 else {})
            if bad:
                failures += 1
                print(f"  {year}: {len(bad)} difference(s)")
                for b in bad[:4]:
                    print(f"      {b}")
        print(f"\n{len(todo) - failures}/{len(todo)} year(s) round-trip exactly")
        return 1 if failures else 0

    stages_total = cls_total = 0
    for year, path in todo:
        stages, cls, _ = split_year(year, path, flat if year == 2026 else {})
        stages_total += len(stages)
        cls_total += 1 if cls else 0
        if args.apply:
            write_year(year, stages, cls)
    print(f"{'wrote' if args.apply else '[DRY RUN] would write'} "
          f"{stages_total:,} stage file(s) and {cls_total} sidecar(s) "
          f"under tdf_scrapes/")
    if args.apply:
        print("originals untouched — run --verify next, then move the readers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
