#!/usr/bin/env python3
"""
Determine each edition's real PCS slug convention by probing, and fix source_slug.

backfill_source_slugs.py derives slugs from stage dates, assuming PCS always
letters the two halves of a split day ('stage-3a'/'stage-3b') so that the DB's
contiguous stage_number runs one ahead of the PCS number from the split on.

That assumption is wrong. PCS is inconsistent PER EDITION, not per race:

    Vuelta 1989   stage-3a + stage-3b exist        -> lettered, offset applies
    TDF 1974      stage-8a exists, stage-8 doesn't -> lettered
    TDF 1986      stage-1 + stage-2, no stage-1a   -> sequential, NO offset
    TDF 1970      stage-9, no stage-9a             -> sequential
    TDF 1991      stage-1, no stage-1a             -> sequential
    Giro 1953     stage-14, no stage-14a           -> sequential

So a derived slug is a guess, and for sequentially-numbered split editions it
is wrong for every stage after the split. This probes the actual convention at
each split day (one cheap request per split), recomputes the mapping, and then
VERIFIES it by fetching the affected stages and comparing PCS's departure and
arrival against the DB's. Only verified slugs are written, with provenance
recorded as 'pcs' rather than 'derived'.

Editions with no split day are untouched: stage_number maps to stage-{n} with
no ambiguity there (prologue is stage_number 0, slug 'prologue').

STATUS, 2026-08-10. A full --apply run over all 107 split editions wrote
nothing. 104 were already correct. The other three — Giro 1935, Giro 1939, TDF
1957 — produced 35 proposals, every one of which this script's own route
verification rejected, and the proposals were genuinely wrong: it wanted Giro
1935 n6 to be stage-6, but PCS's stage-6 is Portocivitanova > l'Aquila while n6
is Riccione > Portocivitanova. The stored stage-5b is right. Eric reviewed all
three editions by hand and confirmed they are correct as stored, so the
convention probe is what misfires there, not the data. Don't "fix" them.

This script is therefore NOT the way to improve source_slug provenance: it
records provenance only for slugs it REWRITES and says nothing about the ones
it leaves alone, which is exactly why correct slugs sat labelled 'derived'. Use
audit_stage_counts.py --confirm-slugs, which reads PCS's per-edition stage list
(slug and route in the same anchor) at one request per edition.

Usage:
  python3 resolve_source_slugs.py --race tdf --dry-run
  python3 resolve_source_slugs.py --race tdf --year 1986
  python3 resolve_source_slugs.py --apply
"""

import argparse
import re
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
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 1.6

_cache: dict[str, str | None] = {}


def fetch(url):
    if url in _cache:
        return _cache[url]
    req = urllib.request.Request(url, headers=HEADERS)
    out = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                html = r.read().decode("utf-8", errors="replace")
                out = None if ("Just a moment" in html and len(html) < 10000) else html
                break
        except urllib.error.HTTPError as e:
            if e.code in (404, 410, 500):
                break
            time.sleep(4)
        except Exception:
            time.sleep(4)
    _cache[url] = out
    time.sleep(DELAY)
    return out


def page_route(html):
    """(departure, arrival) as PCS states them, or (None, None)."""
    t = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    m = re.search(r"Departure:\s*(.+?)\s+Arrival:\s*(.+?)\s+(?:Race ranking|Distance|Date|Won how)", t)
    return (m.group(1).strip(), m.group(2).strip()) if m else (None, None)


def norm(s):
    """Loose place-name comparison — accents and punctuation vary by source."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def exists(race_path, year, slug):
    return fetch(f"{BASE}/race/{race_path}/{year}/{slug}") is not None


def resolve_edition(race_path, year, stages):
    """Return {stage_number: slug} probed against PCS, or None if undecidable."""
    mapping, offset, prev_date, letter_pos = {}, 0, None, 0
    for s in stages:
        n, date = s["stage_number"], s["stage_date"]
        if n == 0:
            mapping[n] = "prologue"
            prev_date = date
            continue
        if prev_date is not None and date == prev_date:
            # A split day. Does PCS letter it, or just number it sequentially?
            base = n - offset - 1          # the number the first half would carry
            lettered = exists(race_path, year, f"stage-{base}{'abcd'[letter_pos + 1]}")
            if lettered:
                letter_pos += 1
                offset += 1
                mapping[n] = f"stage-{base}{'abcd'[letter_pos]}"
                mapping[n - letter_pos] = f"stage-{base}a"
            else:
                letter_pos = 0
                mapping[n] = f"stage-{n - offset}"
        else:
            letter_pos = 0
            mapping[n] = f"stage-{n - offset}"
        prev_date = date
    return mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=sorted(RACES), default=None)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify-all", action="store_true",
                    help="verify every stage's route, not just changed ones")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c1, c2, w = conn.cursor(), conn.cursor(), conn.cursor()

    races = [args.race] if args.race else sorted(RACES)
    changed = verified = failed = 0
    unverified = []

    for race in races:
        race_name, race_path = RACES[race]
        rid = c1.execute("SELECT race_id FROM races WHERE name=?", (race_name,)).fetchone()
        if not rid:
            continue
        editions = c1.execute(
            "SELECT edition_id, year FROM race_editions WHERE race_id=? ORDER BY year",
            (rid[0],),
        ).fetchall()

        for e in editions:
            if args.year and e["year"] != args.year:
                continue
            stages = c2.execute(
                "SELECT stage_id, stage_number, stage_date, source_slug, "
                "start_location, finish_location FROM stages "
                "WHERE edition_id=? ORDER BY stage_number", (e["edition_id"],),
            ).fetchall()
            if not stages or any(not s["stage_date"] for s in stages):
                continue
            dates = [s["stage_date"] for s in stages]
            if len(set(dates)) == len(dates):
                continue                    # no split day: stage-{n} is unambiguous

            mapping = resolve_edition(race_path, e["year"], stages)
            diffs = [s for s in stages if mapping[s["stage_number"]] != s["source_slug"]]
            if not diffs and not args.verify_all:
                print(f"  {race} {e['year']}: convention already correct")
                continue

            print(f"\n  {race} {e['year']}: {len(diffs)} slug(s) need changing")
            to_check = stages if args.verify_all else diffs
            ok = []
            for s in to_check:
                slug = mapping[s["stage_number"]]
                html = fetch(f"{BASE}/race/{race_path}/{e['year']}/{slug}")
                if not html:
                    failed += 1
                    unverified.append((race, e["year"], s["stage_number"], slug, "no page"))
                    continue
                dep, arr = page_route(html)
                if norm(dep) == norm(s["start_location"]) and norm(arr) == norm(s["finish_location"]):
                    ok.append((s, slug))
                    verified += 1
                else:
                    failed += 1
                    unverified.append((race, e["year"], s["stage_number"], slug,
                                       f"PCS says {dep}->{arr}, DB has "
                                       f"{s['start_location']}->{s['finish_location']}"))

            for s, slug in ok:
                if slug == s["source_slug"]:
                    continue
                print(f"      n{s['stage_number']:<3} {s['source_slug']:<12} -> {slug:<12} "
                      f"({s['start_location']} -> {s['finish_location']})")
                changed += 1
                if args.apply:
                    w.execute("UPDATE stages SET source_slug=? WHERE stage_id=?",
                              (slug, s["stage_id"]))
                    record_provenance(
                        w, "stages", s["stage_id"], "source_slug", SOURCE_PCS,
                        source_ref=f"{BASE}/race/{race_path}/{e['year']}/{slug} "
                                   "(probed; route verified)")
            if args.apply:
                conn.commit()

    print(f"\n{'' if args.apply else '[DRY RUN] '}{changed} slug(s) corrected, "
          f"{verified} route-verified, {failed} unverified")
    if unverified:
        print(f"\nUnverified ({len(unverified)}) — left unchanged:")
        for race, year, n, slug, why in unverified[:25]:
            print(f"  {race} {year} n{n} -> {slug}: {why}")
        if len(unverified) > 25:
            print(f"  ... and {len(unverified)-25} more")
    conn.close()


if __name__ == "__main__":
    main()
