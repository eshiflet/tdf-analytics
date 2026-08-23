#!/usr/bin/env python3
"""
Stamp cross-race membership into every riders_index.json.

WHY. The rider detail page is cross-race by design — it shows every race a
rider has results in — and the only way it could know which those are was to
download and build all five `riders_index.json` files: 1,185 KB gzipped, plus
five synchronous index builds on the main thread, for every rider page opened.

Most of that is wasted. Of 17,736 riders across the five sets, 10,793 (61%)
appear in exactly ONE of them and 31 appear in all five. The page was paying
the all-five price to discover, most of the time, that four of the fetches had
nothing to say.

This script writes the answer into the file the page has to load anyway. Each
index gains:

    "xr": ["giro", "vuelta", ...]   # the OTHER sets this file's riders reach
    riders: { "<slug>": { ..., "x": 5 } }   # bitmask over xr; omitted when 0

so the frontend loads the current race's index, reads `x`, and fetches only
the sets the bitmask names. Measured over every (race, rider) pair:

    payload   1,185 KB gz  ->  705 KB mean / 737 KB median   (-41% / -38%)
    cost of the stamp itself:  +25 KB gzipped across all five files

A bitmask over a per-file `xr` table rather than a shared constant: the two
exporters (`export_riders_index.py` for the Grand Tours, `race_set_export.py`
for the aggregate sets) do not know about each other, and a fixed bit order
duplicated in Python and TypeScript is exactly the kind of pair that drifts.
Each file names its own bit order, and the frontend validates the slugs it
finds against the race registry rather than trusting them.

RUN IT AFTER any exporter that rewrites an index — it is a post-pass over
their output, not a step inside either. `validate_exports.py` fails when the
stamp disagrees with the files, so a forgotten run is loud rather than silent.

Idempotent: existing `x`/`xr` are discarded and recomputed from membership,
and a file is only rewritten when its bytes actually change.

Usage:
  python3 link_rider_race_sets.py            # stamp every index
  python3 link_rider_race_sets.py --check     # report drift, write nothing
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.join(HERE, "..", "cycling-app", "src", "data")


def load_indexes(data_root=None):
    """Every riders_index.json on disk, as {slug: parsed}, in slug order.

    Missing files are skipped rather than an error: a checkout that has not
    built the gravel set yet is a normal state, and the bitmask is defined
    over whatever sets exist.
    """
    root = data_root or DATA_ROOT
    out = {}
    if not os.path.isdir(root):
        return out
    for slug in sorted(os.listdir(root)):
        path = os.path.join(root, slug, "riders_index.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                out[slug] = json.load(f)
    return out


def compute_membership(indexes):
    """{slug: (xr, {rider_slug: mask})} from rider membership alone.

    Pure — takes parsed indexes, touches no files — so the encoding can be
    asserted directly against a handful of dicts.
    """
    members = {slug: set(idx.get("riders", {})) for slug, idx in indexes.items()}
    result = {}
    for slug in indexes:
        others = [o for o in sorted(members) if o != slug]
        masks = {}
        for rider in members[slug]:
            mask = 0
            for bit, other in enumerate(others):
                if rider in members[other]:
                    mask |= 1 << bit
            if mask:
                masks[rider] = mask
        result[slug] = (others, masks)
    return result


def apply_membership(idx, xr, masks):
    """Stamp one parsed index in place. Returns True if anything changed.

    Old stamps are cleared first, so a rider who has left a set loses the bit
    instead of keeping a stale one — the failure mode that would send the
    frontend after an index that no longer mentions them.
    """
    changed = idx.get("xr") != xr
    idx["xr"] = xr
    for rider_slug, rec in idx.get("riders", {}).items():
        want = masks.get(rider_slug)
        if rec.get("x") != want:
            changed = True
        if want is None:
            rec.pop("x", None)
        else:
            rec["x"] = want
    return changed


def stamp(data_root=None, check_only=False):
    """Returns (written, drifted) — paths rewritten, and paths that would be."""
    root = data_root or DATA_ROOT
    indexes = load_indexes(root)
    if len(indexes) < 2:
        print(f"Nothing to link: found {len(indexes)} riders_index.json under {root}")
        return [], []

    membership = compute_membership(indexes)
    written, drifted = [], []
    for slug, idx in indexes.items():
        xr, masks = membership[slug]
        path = os.path.join(root, slug, "riders_index.json")
        if not apply_membership(idx, xr, masks):
            print(f"  {slug:9s} unchanged ({len(masks):,}/{len(idx['riders']):,} cross-race)")
            continue
        drifted.append(path)
        if check_only:
            print(f"  {slug:9s} STALE ({len(masks):,}/{len(idx['riders']):,} cross-race)")
            continue
        # Same encoding the exporters use, or every stamp would show up as a
        # whole-file reformat in the diff.
        with open(path, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
        written.append(path)
        print(f"  {slug:9s} stamped {len(masks):,}/{len(idx['riders']):,} cross-race "
              f"-> {os.path.getsize(path) / 1024:.0f} KB")
    return written, drifted


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in argv
    print("Cross-race rider membership" + (" (check only)" if check_only else ""))
    _, drifted = stamp(check_only=check_only)
    if check_only and drifted:
        print(f"\n{len(drifted)} index(es) out of date. Run: python3 link_rider_race_sets.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
