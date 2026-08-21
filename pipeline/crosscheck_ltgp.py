#!/usr/bin/env python3
"""Cross-check the gravel archive against lifetimegrandprix.com — a source
that is NOT Athlinks.

The riskiest decision in this pipeline is which Athlinks course holds each
edition's top-level men's field. Athlinks cannot check that: the wrong course
returns a perfectly well-formed race. But Life Time publishes, on each Grand
Prix athlete's own page, that athlete's finishing PLACE and TIME for every
round they rode. If our stored place and time for Keegan Swenson at Leadville
2025 match what his organiser says, the course pick was right — and if a
course pick were wrong, every rider on it would mismatch at once.

Covers 2022-2026 only (the series' lifetime) and only Grand Prix athletes, so
it verifies the modern editions and says nothing about Leadville 1994. That is
still the half where the course structure changes most.

Usage:
  python3 crosscheck_ltgp.py                 # every athlete on /athletes/
  python3 crosscheck_ltgp.py --athlete keegan-swenson
  python3 crosscheck_ltgp.py --verbose       # list agreements too
"""
import argparse
import os
import json
import re
import sqlite3
from collections import defaultdict
import sys
import time
import urllib.request

from link_gravel_riders import fold
from race_common import GRAVEL

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
RIDER_IDS = os.path.join(HERE, "gravel_scrapes", "_rider_ids.json")
BASE = "https://www.lifetimegrandprix.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

# The organiser renames its own rounds year to year ("Sea Otter MTB" became
# "Sea Otter Gravel" when the round moved off the Fuego XL course), so match on
# the distinctive word rather than the full title.
EVENT_TO_SLUG = [
    (re.compile(r"sea otter", re.I), "sea-otter"),
    (re.compile(r"unbound", re.I), "unbound"),
    (re.compile(r"leadville", re.I), "leadville"),
    (re.compile(r"chequamegon", re.I), "chequamegon"),
    (re.compile(r"little sugar", re.I), "little-sugar"),
    (re.compile(r"big sugar", re.I), "big-sugar"),
]
# Rounds this archive deliberately does not carry.
UNTRACKED = re.compile(r"crusher|the rad\b|rad dirt", re.I)

# Gun vs chip time differs by a second or two on a mass start, and Life Time
# rounds inconsistently (2026 rows carry hundredths, earlier ones do not).
TIME_TOLERANCE_S = 3


def fetch(url, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as exc:            # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    print(f"    ! fetch failed: {url} ({last})")
    return None


def strip_tags(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def athlete_slugs():
    """Every athlete the series has ever listed, not just this season's field.

    The index lives at /athletes/ and links to /athletes/<slug>/ — note the
    PLURAL. The singular /athlete/<slug>/ 301s to it, so both work, but
    matching the singular against this page finds nothing.
    """
    html = fetch(f"{BASE}/athletes/") or ""
    found = set(re.findall(r"/athletes/([a-z0-9][a-z0-9-]+)/", html))
    return sorted(found)


def parse_time(text):
    m = re.match(r"^(\d+):(\d{2}):(\d{2})(?:\.\d+)?$", (text or "").strip())
    if not m:
        return None
    h, mi, s = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s


def athlete_results(slug):
    """[(year, race_slug, place, seconds, event_text)] from one athlete page."""
    html = fetch(f"{BASE}/athletes/{slug}/")
    if not html:
        return None, []
    name = strip_tags((re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S) or
                       re.search(r"<title>(.*?)</title>", html, re.S)).group(1))
    name = re.sub(r"\s*-\s*Life Time Grand Prix\s*$", "", name)
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [strip_tags(c) for c in
                 re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 5 or cells[0] == "Event":
            continue
        event, place, _ltgp, _pts, when = cells[:5]
        ym = re.match(r"^(\d{4})\s+(.*)$", event)
        if not ym:
            continue
        year, title = int(ym.group(1)), ym.group(2)
        if UNTRACKED.search(title):
            continue
        race = next((s for pat, s in EVENT_TO_SLUG if pat.search(title)), None)
        if not race:
            out.append((year, None, None, None, title))
            continue
        # Life Time writes 999999 for a rider who did not finish.
        rank = int(place) if place.isdigit() else None
        if rank is not None and rank >= 999999:
            rank = None
        out.append((year, race, rank, parse_time(when), title))
    return name, out


def db_result(cur, race_slug, year, rider_id):
    """This rider's stored place and time in that race-edition.

    Looked up by rider_id from _rider_ids.json rather than by name string:
    the DB stores PCS's "Vermeulen Alexey" for anyone who crossed over from the
    road, so matching on the displayed "Alexey Vermeulen" reported every single
    crossover rider — the ones this archive exists to connect — as missing.
    """
    cur.execute(
        """SELECT sr.stage_rank, sr.finish_time_seconds
           FROM stage_results sr
           JOIN stages s ON s.stage_id = sr.stage_id
           JOIN race_editions e ON e.edition_id = s.edition_id
           JOIN races r ON r.race_id = e.race_id
           WHERE r.name = ? AND e.year = ? AND sr.rider_id = ?""",
        (GRAVEL[race_slug].name, year, rider_id))
    return cur.fetchone()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--athlete", help="one athlete slug (default: all listed)")
    ap.add_argument("--verbose", action="store_true", help="list agreements too")
    args = ap.parse_args(argv)

    slugs = [args.athlete] if args.athlete else athlete_slugs()
    if not slugs:
        print("no athletes found on /athletes/ — page structure may have changed")
        return 1
    print(f"cross-checking {len(slugs)} Grand Prix athletes against the DB\n")

    if not os.path.exists(RIDER_IDS):
        print("gravel_scrapes/_rider_ids.json missing — run link_gravel_riders.py")
        return 1
    with open(RIDER_IDS, encoding="utf-8") as f:
        rider_ids = json.load(f)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = conn.cursor()

    agree = place_bad = time_bad = missing_db = unmapped = unknown = 0
    problems, absent = [], []
    # Grouped per race-edition, because these two sources disagree
    # SYSTEMATICALLY or not at all: a whole edition offset by a minute is one
    # fact about two clocks, not sixty separate defects, and printing it sixty
    # times buries the one edition where something is actually wrong.
    by_edition = defaultdict(lambda: {"agree": 0, "place": [], "time": []})
    for slug in slugs:
        name, rows = athlete_results(slug)
        if name is None:
            continue
        for year, race, place, secs, title in rows:
            if race is None:
                unmapped += 1
                continue
            ident = rider_ids.get(fold(name).strip())
            if ident is None:
                unknown += 1
                absent.append(f"{name} — not in the gravel archive under any name "
                              f"(women's field, or a spelling Athlinks differs on)")
                continue
            found = db_result(cur, race, year, ident["rider_id"])
            if not found:
                missing_db += 1
                absent.append(f"{name} — {year} {title}: not in the DB")
                continue
            db_rank, db_secs = found
            key = (race, year)
            ok = True
            if place is not None and db_rank != place:
                place_bad += 1
                ok = False
                by_edition[key]["place"].append((db_rank or 0) - place)
                problems.append(f"{name:<26} {year} {title[:22]:<22} "
                                f"place: LTGP {place}, DB {db_rank}")
            if secs and db_secs and abs(secs - db_secs) > TIME_TOLERANCE_S:
                time_bad += 1
                ok = False
                by_edition[key]["time"].append(db_secs - secs)
                problems.append(f"{name:<26} {year} {title[:22]:<22} "
                                f"time:  LTGP {secs}s, DB {db_secs}s "
                                f"({db_secs - secs:+d}s)")
            if ok:
                agree += 1
                by_edition[key]["agree"] += 1
                if args.verbose:
                    print(f"  OK  {name:<26} {year} {title[:24]:<24} "
                          f"#{db_rank} {db_secs}s")
    conn.close()

    print(f"\n{agree} results agree with Life Time on BOTH place and time")
    if place_bad or time_bad:
        print(f"{place_bad} place and {time_bad} time mismatches, "
              f"by edition (a consistent offset is two clocks, not an error):\n")
        print(f"  {'edition':<26} {'agree':>5} {'place≠':>6} {'time≠':>6}  "
              f"{'median place Δ':>14}  {'median time Δ':>14}")
        for (race, year) in sorted(by_edition, key=lambda k: (k[0], -k[1])):
            v = by_edition[(race, year)]
            if not v["place"] and not v["time"]:
                continue
            def med(xs):
                return sorted(xs)[len(xs) // 2] if xs else None
            pm, tm = med(v["place"]), med(v["time"])
            print(f"  {race + ' ' + str(year):<26} {v['agree']:>5} "
                  f"{len(v['place']):>6} {len(v['time']):>6}  "
                  f"{(f'{pm:+d}' if pm is not None else '-'):>14}  "
                  f"{(f'{tm:+d}s' if tm is not None else '-'):>14}")
        print(f"\n  first {min(12, len(problems))} of {len(problems)} individually:")
        for p in problems[:12]:
            print(f"    {p}")
    if unknown:
        print(f"\n{unknown} results belong to athletes with no row in the gravel "
              f"archive at all — expected: the women's field is not carried yet.")
    if missing_db:
        # Expected in two cases and only two: an athlete whose name Athlinks
        # spells differently, and a round this archive does not carry.
        print(f"\n{missing_db} Grand Prix results are absent from the DB:")
        for a in absent[:25]:
            print(f"  {a}")
        if len(absent) > 25:
            print(f"  ... {len(absent)-25} more")
    return 0 if not (place_bad or time_bad) else 2


if __name__ == "__main__":
    sys.exit(main())
