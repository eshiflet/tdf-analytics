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

THE EXPORTERS CALL THIS THEMSELVES. `export_riders_index.py` and
`race_set_export.py` (via export_classics.py / export_gravel.py) invoke stamp()
after writing an index, so it is restored the moment it is dropped and there is
no step to remember. `validate_exports.py` still checks it — that is now a
backstop for a hand-edited file or a new writer that forgets, not the mechanism.

Run it by hand after any OTHER writer that touches a riders_index.json.

Stamping one index can legitimately rewrite the others: membership is symmetric,
so a rider newly appearing in the Giro changes the classics file's bitmask for
that rider too. Only files whose bytes actually change are written.

Idempotent: existing `x`/`xr` are discarded and recomputed from membership,
and a file is only rewritten when its bytes actually change.

Usage:
  python3 link_rider_race_sets.py            # stamp every index
  python3 link_rider_race_sets.py --check     # report drift, write nothing
"""

import json
import os
import sys

from race_common import load_rider_aliases

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.join(HERE, "..", "cycling-app", "src", "data")
ALIAS_MAP_NAME = "rider_aliases.json"


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


def build_alias_map(indexes):
    """{absorbed slug: canonical slug}, for redirecting a link to a merged rider.

    WHY THE FRONTEND NEEDS THIS. Merging two rider ids deletes one of them, and
    every link anyone ever made to it — a bookmark, a shared URL, a search
    result — then lands on "No rider matches this link." There are 141 absorbed
    ids; the bug report that started the 2026-09-18 merge pass was itself sent
    as a link to `rider/torbj-r`, which that pass deleted. The alias file lives
    in the pipeline and the browser has never been able to see it.

    ONLY entries whose canonical is actually in an index are exported. An alias
    naming a rider no index holds would redirect one dead page to another, which
    is worse than the message: at least the message is honest. Two entries are
    exactly that today — `jorge-padrones` and `damia-palafoix`, whose canonicals
    are Traka finishers below FIELD_CAP and exist in no export.

    One hop is enough because an alias may never point at another alias; that is
    an invariant with its own test (test_no_alias_points_at_another_alias), not
    an assumption made here.
    """
    known = set()
    for idx in indexes.values():
        known.update(idx.get("riders") or {})
    out = {}
    for absorbed, canonical in load_rider_aliases().items():
        target = canonical.removeprefix("rider/")
        if target in known:
            out[absorbed.removeprefix("rider/")] = target
    return dict(sorted(out.items()))


def write_alias_map(root, indexes, check_only=False):
    """Write the redirect map beside the per-race directories. Returns
    (path, changed) — or (path, False) when the bytes already match.

    Written here rather than by an exporter because it is the only output that
    is GLOBAL: every export_*.py takes one race and the alias map spans all of
    them, the same reason the cross-race stamp lives in this script.
    """
    path = os.path.join(root, ALIAS_MAP_NAME)
    body = json.dumps(build_alias_map(indexes), ensure_ascii=False,
                      indent=1, sort_keys=True) + "\n"
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == body:
                return path, False
    except OSError:
        pass
    if not check_only:
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    return path, True


def stamp(data_root=None, check_only=False, quiet=False):
    """Returns (written, drifted) — paths rewritten, and paths that would be.

    `quiet` reports only the files that changed. The exporters call it that way:
    they re-stamp on every run, and five "unchanged" lines after every export
    would train the eye to skip the one line that matters.
    """
    root = data_root or DATA_ROOT
    indexes = load_indexes(root)
    if len(indexes) < 2:
        if not quiet:
            print(f"Nothing to link: found {len(indexes)} riders_index.json under {root}")
        return [], []

    membership = compute_membership(indexes)
    written, drifted = [], []
    for slug, idx in indexes.items():
        xr, masks = membership[slug]
        path = os.path.join(root, slug, "riders_index.json")
        if not apply_membership(idx, xr, masks):
            if not quiet:
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

    # Built from the indexes as they are ON DISK, so it names only riders the
    # browser can actually reach. Tracked in `written`/`drifted` like any index,
    # which is what makes validate_exports' staleness check cover it too.
    alias_path, alias_changed = write_alias_map(root, indexes, check_only=check_only)
    n_alias = len(build_alias_map(indexes))
    if alias_changed:
        drifted.append(alias_path)
        if check_only:
            print(f"  {ALIAS_MAP_NAME} STALE ({n_alias:,} redirects)")
        else:
            written.append(alias_path)
            print(f"  {ALIAS_MAP_NAME} wrote {n_alias:,} merged-rider redirect(s)")
    elif not quiet:
        print(f"  {ALIAS_MAP_NAME} unchanged ({n_alias:,} redirects)")
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
