#!/usr/bin/env python3
"""
Compare each edition's stage list against PCS's, by route.

Nothing else catches this. validate_db finds GAPS in the stage_number sequence,
which only appear when a stage is dropped from the MIDDLE and later stages keep
their old numbers. An edition that simply ends early, or that never got the
second half of a split day, is numbered 1..N with no gap at all and looks
perfectly healthy.

Giro 1937 is the case that exposed it: PCS lists 23 stages, the DB holds 18. The
missing five are 5b, 8b, 11b and — worse — 19a and 19b, the last two stages of
the race. The DB's "final" standings are therefore taken from stage 18, and the
edition's total distance is short by five stages. Its stage_number sequence is a
clean 1..18.

It also flags slugs that cannot resolve: PCS serves 'stage-5a' and 'stage-5b'
for a split day and returns HTTP 500 for a plain 'stage-5', so any stored slug
of that shape is dead and every re-fetch of that stage silently fails.

Matching is by route (departure -> arrival), normalised for accents and
punctuation, because stage NUMBERS are exactly what is unreliable here.

Reads PCS's per-edition "results" page — one request per edition, so a full run
over ~300 editions takes a while.

Reporting is the default. --fix-slugs additionally repairs the unresolvable
slugs, since this is already the authoritative mapping: the anchor states the
slug and the route together, so a DB row matched by route can only have one
correct slug. Each change is still verified by fetching the target page and
comparing its departure/arrival, because writing a slug that does not resolve
is exactly the failure being repaired.

Missing STAGES are never inserted here — that renumbers an edition and belongs
in a deliberate repair, not a scan.

Usage:
  python3 audit_stage_counts.py --race giro --year 1937
  python3 audit_stage_counts.py                     # report everything (slow)
  python3 audit_stage_counts.py --fix-slugs         # repair slugs too
  python3 audit_stage_counts.py --confirm-slugs     # upgrade 'derived' provenance
"""

import argparse
import re
from collections import Counter
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.request

from race_common import DB_PATH, SOURCE_PCS, record_provenance

BASE = "https://www.procyclingstats.com"
RACES = {
    "tdf": ("Tour de France", "tour-de-france"),
    "giro": ("Giro d'Italia", "giro-d-italia"),
    "vuelta": ("Vuelta a España", "vuelta-a-espana"),
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0"}
DELAY = 1.5


def norm(s):
    """Route text reduced to something comparable across two spellings.

    Accents go first, then the saint abbreviations, then everything that is not
    a letter or digit. The abbreviation step has to happen while word boundaries
    still exist: stripping punctuation first turns "St Malo" into "stmalo",
    where "st" is no longer a separate token.

    That step is not cosmetic. The DB writes "St Malo" and "Ste Foy la Grande"
    where PCS writes "Saint-Malo" and "Sainte-Foy-la-Grande", and every one of
    those routes failed to match — leaving correct slugs unconfirmable and
    forcing the leftover-pairing fallback to carry stages it should never have
    needed to.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"\bste\b\.?", "sainte", s)
    s = re.sub(r"\bst\b\.?", "saint", s)
    return re.sub(r"[^a-z0-9]", "", s)


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS),
                                    timeout=25) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def pcs_stages(race_path, year):
    """[(slug, 'Departure - Arrival')] for one edition, from its results page.

    Read from the stage ANCHORS, not from the flattened page text. Each link
    carries both the exact slug — including the letter on a split day — and the
    route in its label:

        <a href="race/giro-d-italia/1937/stage-5a">Stage 5a (TTT) | Viareggio - Marina di Massa</a>

    Flattening the page and pattern-matching "Stage N | route" instead needs the
    list to be bounded by hand, and every way of doing that was wrong for some
    edition: older pages repeat the list with winner names appended, modern ones
    do not repeat it at all, and a fixed character cap silently dropped the last
    stage of 14 editions — reporting complete editions as short. The anchors
    have no such ambiguity.
    """
    html = fetch(f"{BASE}/race/{race_path}/{year}/results")
    if not html:
        return None
    out, seen = [], set()
    for href, label in re.findall(
            r'href="race/' + re.escape(race_path) +
            r'/\d+/((?:stage-[0-9a-e]+|prologue))"[^>]*>([^<]*)</a>', html):
        if href in seen:
            continue
        seen.add(href)
        route = label.split("|", 1)[1].strip() if "|" in label else ""
        out.append((href, route))
    return out or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=sorted(RACES), default=None)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--fix-slugs", action="store_true",
                    help="rewrite unresolvable source_slug values (route-verified)")
    ap.add_argument("--confirm-slugs", action="store_true",
                    help="record provenance for slugs PCS's stage list confirms")
    args = ap.parse_args()

    writing = args.fix_slugs or args.confirm_slugs
    conn = sqlite3.connect(DB_PATH if writing
                           else f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    c, c2, w = conn.cursor(), conn.cursor(), conn.cursor()

    races = [args.race] if args.race else sorted(RACES)
    short = dead_slugs = checked = confirmed_n = 0
    fixed_n = [0]

    for race in races:
        race_name, race_path = RACES[race]
        rid = c.execute("SELECT race_id FROM races WHERE name=?", (race_name,)).fetchone()
        if not rid:
            continue
        for e in c.execute("SELECT edition_id, year FROM race_editions WHERE race_id=? "
                           "ORDER BY year", (rid[0],)).fetchall():
            if args.year and e["year"] != args.year:
                continue
            db = c2.execute("""SELECT stage_id, stage_number n, source_slug,
                    start_location a, finish_location b
                    FROM stages WHERE edition_id=? ORDER BY stage_number""",
                            (e["edition_id"],)).fetchall()
            if not db:
                continue
            listed = pcs_stages(race_path, e["year"])
            time.sleep(DELAY)
            checked += 1
            if listed is None:
                print(f"  {race} {e['year']}: could not read PCS stage list")
                continue

            # Count-based, not membership-based. When PCS lists a route TWICE
            # (a split day whose halves share a town, e.g. Giro 1994's Bologna
            # > Bologna 1a and 1b) and the DB holds it once, set membership
            # says "present" and the absent half is invisible. Compare how many
            # times each route appears on each side and report the surplus.
            db_route_counts = Counter(norm(f"{r['a']} - {r['b']}") for r in db)
            pcs_route_counts = Counter(norm(route) for _, route in listed)
            seen_route = Counter()
            missing = []
            for slug, route in listed:
                key = norm(route)
                seen_route[key] += 1
                if seen_route[key] > db_route_counts.get(key, 0):
                    missing.append((slug, route))
            # Absorb spelling differences: a DB stage whose route matched
            # nothing pairs with an unmatched PCS entry rather than counting as
            # absent, where PCS qualifies a finish the DB names plainly.
            # (Vuelta 2022's "Martos - Sierra Nevada" vs PCS's "... (Alto Hoya
            # de la Mora)" was the example; that one is now spelled PCS's way
            # in the DB, but others remain.) Only a genuine surplus survives.
            matched_db = sum(min(v, db_route_counts.get(k, 0))
                             for k, v in pcs_route_counts.items())
            unmatched_db = len(db) - matched_db
            if unmatched_db > 0 and missing:
                missing = missing[unmatched_db:]

            # Route is NOT a unique key. Circuit stages and same-town split
            # halves repeat a departure/arrival pair within one edition —
            # "Arco - Arco", "Portoferraio - Portoferraio", "Seraing -
            # Seraing". Matching on a duplicated route picks whichever entry
            # happens to be last, so two stages trade slugs and each pass
            # "fixes" the previous one's work. Only unambiguous routes — those
            # appearing exactly once on each side — may be repaired; the rest
            # are reported for a human, because nothing in the route tells you
            # which of the two stages is which.
            by_route = {norm(f"{r['a']} - {r['b']}"): r for r in db
                        if db_route_counts[norm(f"{r['a']} - {r['b']}")] == 1}
            wrong, ambiguous, confirmed, swapped = [], [], [], []

            # Duplicated routes can still be CONFIRMED, just never reassigned.
            # Both lists are chronological — PCS publishes its stage list in
            # race order, and stage_number is race order — so when a route
            # appears the same number of times on each side, the two sequences
            # can be compared position by position. If the slugs the DB already
            # holds read the same as PCS's in that order, the existing
            # assignment is right; nothing is written but the label.
            #
            # This is safe precisely because it never reassigns. The
            # oscillation bug came from PICKING a row for a duplicated route
            # and rewriting it, which two stages then undid for each other on
            # alternate passes. Here a disagreement is reported, not acted on —
            # and it is a real signal: two split halves stored the wrong way
            # round produce reversed sequences and show up here.
            pcs_groups, db_groups, order_confirmed = {}, {}, set()
            for slug, route in listed:
                pcs_groups.setdefault(norm(route), []).append(slug)
            for r in db:                       # already ordered by stage_number
                db_groups.setdefault(norm(f"{r['a']} - {r['b']}"), []).append(r)
            for key, pslugs in pcs_groups.items():
                drows = db_groups.get(key, [])
                if len(pslugs) < 2 or len(drows) != len(pslugs):
                    continue                   # unique, or a count mismatch
                have = [r["source_slug"] for r in drows]
                if have == pslugs:
                    order_confirmed.add(key)
                    for r, slug in zip(drows, pslugs):
                        confirmed.append((r["stage_id"], slug,
                                          f"{pslugs} in race order"))
                else:
                    swapped.append((key, have, pslugs,
                                    [r["n"] for r in drows]))

            for slug, route in listed:
                key = norm(route)
                if pcs_route_counts[key] > 1 or db_route_counts.get(key, 0) > 1:
                    # Settled above by race order — not something for a human.
                    if db_route_counts.get(key) and key not in order_confirmed:
                        ambiguous.append((slug, route))
                    continue
                r = by_route.get(key)
                if r is not None and r["source_slug"] == slug:
                    # PCS's own stage list pairs this slug with this route, and
                    # the route is unique on both sides, so the stored slug is
                    # confirmed rather than merely derived. This is the only
                    # place that evidence exists per stage at one request per
                    # EDITION: resolve_source_slugs probes the split-day
                    # convention and rewrites what disagrees, but it records
                    # nothing for the slugs it leaves alone, so 59 split
                    # editions kept a 'derived' label on slugs that are right.
                    confirmed.append((r["stage_id"], slug, route))
                if r is not None and r["source_slug"] != slug:
                    # Never hand a slug to one row while another still holds
                    # it — that produces two stages claiming the same PCS page,
                    # and whichever is re-fetched second overwrites the first.
                    # It happens when the DB row this slug belongs to has NULL
                    # locations (so its route can't match) while a DIFFERENT
                    # stage shares the town: PCS's 'prologue' entry for TDF
                    # 1996 matched stage 1, because both start and finish in
                    # 's-Hertogenbosch and the prologue row has no locations.
                    taken = next((x for x in db
                                  if x["source_slug"] == slug and x["stage_id"] != r["stage_id"]),
                                 None)
                    if taken is not None:
                        ambiguous.append(
                            (slug, f"{route} — already held by DB n={taken['n']}"))
                        continue
                    wrong.append((r["stage_id"], r["n"], r["source_slug"], slug, route))

            if args.confirm_slugs and confirmed:
                for sid, slug, route in confirmed:
                    record_provenance(
                        w, "stages", sid, "source_slug", SOURCE_PCS,
                        source_ref=f"{BASE}/race/{race_path}/{e['year']}/results"
                                   f" — PCS's stage list pairs {slug} with"
                                   f" \"{route}\"; route unique on both sides")
                confirmed_n += len(confirmed)
                conn.commit()

            if swapped:
                print(f"\n  {race} {e['year']}: duplicated route(s) whose order "
                      "disagrees with PCS — possible swap, NOT rewritten")
                for key, have, want, nums in swapped:
                    print(f"      ORDER    DB n={nums} hold {have}, "
                          f"PCS lists {want} in that order")
                dead_slugs += len(swapped)

            if missing or wrong or ambiguous:
                print(f"\n  {race} {e['year']}: PCS lists {len(listed)}, DB has {len(db)}")
                for slug, route in missing:
                    print(f"      MISSING  {slug:<11} {route[:60]}")
                for sid, dbn, have, want, route in wrong:
                    verdict = ""
                    if args.fix_slugs:
                        # Confirm the replacement actually resolves and is the
                        # right stage before writing it. A slug that 500s is
                        # the defect; swapping in another bad one is no fix.
                        page = fetch(f"{BASE}/race/{race_path}/{e['year']}/{want}")
                        time.sleep(DELAY)
                        ok = False
                        if page:
                            t2 = " ".join(re.sub(r"<[^>]+>", " ", page).split())
                            m2 = re.search(r"Departure:\s*(.+?)\s+Arrival:\s*(.+?)\s+"
                                           r"(?:Race ranking|Distance|Date|Won how)", t2)
                            ok = bool(m2) and norm(f"{m2.group(1)} - {m2.group(2)}") == norm(route)
                        if ok:
                            w.execute("UPDATE stages SET source_slug=? WHERE stage_id=?",
                                      (want, sid))
                            record_provenance(
                                w, "stages", sid, "source_slug", SOURCE_PCS,
                                source_ref=f"{BASE}/race/{race_path}/{e['year']}/{want}"
                                           " (from the edition stage list; route verified)")
                            fixed_n[0] += 1
                            verdict = "  FIXED"
                        else:
                            verdict = "  NOT VERIFIED - left alone"
                    print(f"      SLUG     DB n={dbn:<3} {have} -> {want}{verdict}")
                for slug, route in ambiguous:
                    print(f"      AMBIG    {slug:<11} {route[:50]} — route repeats; "
                          "cannot tell the stages apart, resolve by hand")
                short += len(missing)
                dead_slugs += len(wrong)
                if args.fix_slugs:
                    conn.commit()

    print(f"\n{checked} edition(s) checked: {short} stage(s) absent from the DB, "
          f"{dead_slugs} unresolvable slug(s)")
    if args.confirm_slugs:
        print(f"{confirmed_n} slug(s) confirmed against PCS's stage list")
    if args.fix_slugs:
        print(f"{fixed_n[0]} slug(s) repaired and route-verified")
    conn.close()
    sys.exit(1 if short or dead_slugs else 0)


if __name__ == "__main__":
    main()
