#!/usr/bin/env python3
"""
Fill missing stages.vertical_meters from PCS's RACE ROUTE page.

Why a second elevation source when the per-stage scrapers already read PCS:
a handful of PCS stage pages are broken. `/race/tour-de-france/1990/stage-21`
serves "0 km" with no vertical meters and no ProfileScore, so every scraper
that walks stage pages recorded nothing for the Paris finale — and the 1990
Tour therefore charted 38,940 m instead of PCS's own 40,225 m, the lowest
total on record by a margin it had not earned.

The route page `/race/<slug>/<year>/route/stages` carries the same figures in
a table and does NOT have that hole. It is one request per edition instead of
one per stage, so it is also the cheap way to check a whole race.

By default this only FILLS NULLs. A stage that already has a figure is
compared and reported, never overwritten: PCS's current number is not
automatically better than a deliberate Wikipedia or manual patch, and telling
those apart needs a human (same rule as audit_elevation.py).

The one exception is --replace-derived, which also overwrites values this repo
COMPUTED itself (provenance source 'derived') rather than fetched. A scraped
figure always beats a reconstruction, so where PCS turns out to publish one
after all, the derived value is a liability — the ten Paris finales of
2001-2010 were reconstructed from BRouter/EU-DEM and ran anywhere from 48%
under to 2.9x over PCS's own number. It still never touches 'pcs',
'wikipedia', 'bikeraceinfo', 'manual' or 'unknown' provenance.

Rows are matched on the SOURCE_SLUG parsed out of each row's own href, never
on stage_number. The two diverge after any split day, and a scraper that
rebuilds "stage-{stage_number}" reads the neighbouring stage's figures — the
bug that put this project on notice in the first place.

Usage:
  python3 scrape_route_overview_elevation.py --race tdf --years 1990-2012
  python3 scrape_route_overview_elevation.py --race tdf --years 1990 --apply
  python3 scrape_route_overview_elevation.py --race giro --years 1992-1999
  python3 scrape_route_overview_elevation.py --race tdf --years 2001-2010 \
      --replace-derived --apply
Dry run unless --apply is given. SCRAPE_DELAY env var overrides the 2.5s delay.
"""

import argparse
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

from race_common import DB_PATH, SOURCE_DERIVED, SOURCE_PCS, record_provenance

BASE = "https://www.procyclingstats.com"
RACE_PATH = {
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
DELAY = float(os.environ.get("SCRAPE_DELAY", "2.5"))

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_SLUG_RE = re.compile(r'href="race/[^/]+/\d{4}/([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")


def route_url(race, year):
    return f"{BASE}/race/{RACE_PATH[race][1]}/{year}/route/stages"


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_route_table(html):
    """
    {source_slug: vertical_meters_or_None} for every stage row on the page.

    Scoped to the "Stages" table on purpose. The page carries a second table,
    "Hardest stages", whose rows link to the same stage URLs but whose last
    cell is the ProfileScore — parsing the whole page reads 395 as Alpe
    d'Huez's vertical metres and every figure comes out wrong-but-plausible.

    The stages table's last row is a totals line with no stage link; requiring
    an href is what excludes it, so the race total never lands on a stage.
    """
    start = html.find("<h4>Stages</h4>")
    if start == -1:
        return {}
    end = html.find("</table>", start)
    table = html[start:end if end != -1 else None]

    out = {}
    for row in _ROW_RE.findall(table):
        slug = _SLUG_RE.search(row)
        if not slug:
            continue
        cells = [_TAG_RE.sub("", c).strip() for c in _CELL_RE.findall(row)]
        if len(cells) < 2:
            continue
        vertical = cells[-1].replace(",", "")
        out[slug.group(1)] = int(vertical) if vertical.isdigit() else None
    return out


def parse_years(spec):
    years = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            years.update(range(int(lo), int(hi) + 1))
        elif part:
            years.add(int(part))
    return sorted(years)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=sorted(RACE_PATH), default="tdf")
    ap.add_argument("--years", required=True,
                    help="1990, 1990-2012, or 1990,1993,1995")
    ap.add_argument("--apply", action="store_true",
                    help="write to the DB (default: report only)")
    ap.add_argument("--replace-derived", action="store_true",
                    help="also overwrite values this repo computed itself "
                         "(provenance 'derived'); scraped beats reconstructed")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    race_row = cur.execute("SELECT race_id FROM races WHERE name=?",
                           (RACE_PATH[args.race][0],)).fetchone()
    if not race_row:
        sys.exit(f"{RACE_PATH[args.race][0]} not in races table")
    race_id = race_row["race_id"]

    filled, replaced, mismatched, unavailable, no_slug, kept = [], [], [], [], [], []

    for year in parse_years(args.years):
        edition = cur.execute(
            "SELECT edition_id FROM race_editions WHERE race_id=? AND year=?",
            (race_id, year)).fetchone()
        if not edition:
            continue
        stages = list(cur.execute(
            """SELECT stage_id, stage_number, source_slug, vertical_meters,
                      start_location, finish_location
               FROM stages WHERE edition_id=? AND cancelled=0""",
            (edition["edition_id"],)))
        missing = [s for s in stages if s["vertical_meters"] is None]

        # Derived values are targets too under --replace-derived. Read the
        # provenance rather than guessing from the number: only a row this
        # repo computed is safe to overwrite, and nothing about the value
        # itself says which those are.
        derived_ids = set()
        if args.replace_derived and stages:
            derived_ids = {r["entity_id"] for r in cur.execute(
                """SELECT entity_id FROM data_provenance
                   WHERE entity='stages' AND field='vertical_meters'
                     AND source=? AND entity_id IN (%s)"""
                % ",".join("?" * len(stages)),
                (SOURCE_DERIVED, *[s["stage_id"] for s in stages]))}
        stale = [s for s in stages if s["stage_id"] in derived_ids]

        if not missing and not stale:
            continue

        url = route_url(args.race, year)
        try:
            table = parse_route_table(fetch(url))
        except urllib.error.HTTPError as e:
            print(f"{year}: HTTP {e.code} on {url}")
            time.sleep(DELAY)
            continue
        time.sleep(DELAY)

        for s in missing + stale:
            if not s["source_slug"]:
                no_slug.append((year, s["stage_number"]))
                continue
            vertical = table.get(s["source_slug"])
            route = f'{s["start_location"]}→{s["finish_location"]}'
            if vertical is None:
                # A derived row is not "missing" — it keeps the value it had,
                # and the route page simply has nothing better to offer.
                if s["stage_id"] not in derived_ids:
                    unavailable.append((year, s["stage_number"], route))
                else:
                    kept.append((year, s["stage_number"], route,
                                 s["vertical_meters"]))
                continue
            if s["stage_id"] in derived_ids:
                replaced.append((year, s["stage_number"], route,
                                 s["vertical_meters"], vertical))
            else:
                filled.append((year, s["stage_number"], route, vertical))
            if args.apply:
                cur.execute("UPDATE stages SET vertical_meters=? WHERE stage_id=?",
                            (vertical, s["stage_id"]))
                record_provenance(cur, "stages", s["stage_id"], "vertical_meters",
                                  SOURCE_PCS, source_ref=url,
                                  script="scrape_route_overview_elevation.py")

        # Not the job, but free: the route page also re-states every stage that
        # already has a figure, so disagreements surface at no extra request.
        for s in stages:
            if (s["vertical_meters"] is None or not s["source_slug"]
                    or s["stage_id"] in derived_ids):
                continue
            theirs = table.get(s["source_slug"])
            if theirs is not None and theirs != s["vertical_meters"]:
                mismatched.append((year, s["stage_number"], s["vertical_meters"], theirs))

    if args.apply:
        conn.commit()
    conn.close()

    print(f"\n{'FILLED' if args.apply else 'WOULD FILL'}: {len(filled)} stage(s)")
    for year, n, route, vertical in filled:
        print(f"  {year} stage {n:<3} {vertical:>6} m   {route}")
    if replaced:
        print(f"\n{'REPLACED' if args.apply else 'WOULD REPLACE'} (derived → "
              f"PCS): {len(replaced)} stage(s)")
        for year, n, route, ours, theirs in replaced:
            print(f"  {year} stage {n:<3} {ours:>6} → {theirs:<6} m   {route}")
    if kept:
        print(f"\nKEPT derived (route page has no figure): {len(kept)} stage(s)")
        for year, n, route, ours in kept:
            print(f"  {year} stage {n:<3} {ours:>6} m   {route}")
    if unavailable:
        print(f"\nSTILL MISSING: {len(unavailable)} stage(s) — the route page "
              f"has no figure either")
        for year, n, route in unavailable:
            print(f"  {year} stage {n:<3} {route}")
    if no_slug:
        print(f"\nNO source_slug (cannot match safely): {no_slug}")
    if mismatched:
        print(f"\nDISAGREEMENT with stored values: {len(mismatched)} "
              f"(NOT changed — investigate)")
        for year, n, ours, theirs in mismatched:
            print(f"  {year} stage {n:<3} stored {ours} vs route page {theirs}")
    if not args.apply and (filled or replaced):
        print("\nDry run. Re-run with --apply to write these.")


if __name__ == "__main__":
    main()
