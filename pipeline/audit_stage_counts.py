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
over ~300 editions takes a while. Read-only; reports, changes nothing.

Usage:
  python3 audit_stage_counts.py --race giro --year 1937
  python3 audit_stage_counts.py --race vuelta
  python3 audit_stage_counts.py                     # everything (slow)
"""

import argparse
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.request

from race_common import DB_PATH

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
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


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
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    c, c2 = conn.cursor(), conn.cursor()

    races = [args.race] if args.race else sorted(RACES)
    short = dead_slugs = checked = 0

    for race in races:
        race_name, race_path = RACES[race]
        rid = c.execute("SELECT race_id FROM races WHERE name=?", (race_name,)).fetchone()
        if not rid:
            continue
        for e in c.execute("SELECT edition_id, year FROM race_editions WHERE race_id=? "
                           "ORDER BY year", (rid[0],)).fetchall():
            if args.year and e["year"] != args.year:
                continue
            db = c2.execute("""SELECT stage_number n, source_slug, start_location a,
                    finish_location b FROM stages WHERE edition_id=? ORDER BY stage_number""",
                            (e["edition_id"],)).fetchall()
            if not db:
                continue
            listed = pcs_stages(race_path, e["year"])
            time.sleep(DELAY)
            checked += 1
            if listed is None:
                print(f"  {race} {e['year']}: could not read PCS stage list")
                continue

            db_routes = {norm(f"{r['a']} - {r['b']}") for r in db}
            missing = [(slug, route) for slug, route in listed
                       if norm(route) not in db_routes]
            by_route = {norm(f"{r['a']} - {r['b']}"): r for r in db}
            wrong = []
            for slug, route in listed:
                r = by_route.get(norm(route))
                if r is not None and r["source_slug"] != slug:
                    wrong.append((r["n"], r["source_slug"], slug))

            if missing or wrong:
                print(f"\n  {race} {e['year']}: PCS lists {len(listed)}, DB has {len(db)}")
                for slug, route in missing:
                    print(f"      MISSING  {slug:<11} {route[:60]}")
                for dbn, have, want in wrong:
                    print(f"      SLUG     DB n={dbn:<3} {have} -> {want}")
                short += len(missing)
                dead_slugs += len(wrong)

    print(f"\n{checked} edition(s) checked: {short} stage(s) absent from the DB, "
          f"{dead_slugs} unresolvable slug(s)")
    conn.close()
    sys.exit(1 if short or dead_slugs else 0)


if __name__ == "__main__":
    main()
