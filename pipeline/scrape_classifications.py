#!/usr/bin/env python3
"""
Scrape final points / KOM / youth classifications for any Grand Tour.

WHY. `classification_standings` held Tour rows only — 1960-2025, and nothing at
all for the Giro or the Vuelta. That was never a decision: the two writers that
populate it, add_stages.py and scrape_pcs_kom_finals.py, are both hardcoded to
the Tour, and scrape_pcs_kom_finals builds `race/tour-de-france/{year}/kom`
literally. Nobody had written the other two. PCS serves the same page for every
race, so this replaces the Tour-only path with one that takes a race.

TWO TRAPS THIS AVOIDS, both of which cost real time on 2026-09-09.

`/race/<race>/<year>/gc` does NOT serve the general classification. It serves
the last stage's STAGE result — its title says "Stage 21 results" — and
`/race/<race>/<year>/result` returns HTTP 500. All six classifications live on
that one page as `<div class="resTab" data-id=N>` blocks. Reading "the first
tbody" makes the final stage's winner look like the race winner: van Aert won
the 2025 Tour's last stage, Pogačar won the Tour.

So the table is chosen by its TAB LABEL, never by position. The page carries
`<ul class="tabs tabnav resultTabs">` whose `<li data-id>` entries name each
block, and position is not stable — a stage with four categorised climbs adds
four more tables than one with none.

GC is deliberately not stored here: every rider's per-stage GC already lives in
stage_results.gc_rank, and a second copy would be a second thing to keep true.

Usage:
  python3 scrape_classifications.py --race giro --year 2025 --dry-run
  python3 scrape_classifications.py --race giro --apply
  python3 scrape_classifications.py --apply            # all three, all years
"""

import argparse
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

from race_common import (
    DB_PATH,
    RACES,
    SOURCE_PCS,
    STAGE_RACES,
    exit_on_help,
    fix_mojibake,
    parse_int,
    parse_time_to_seconds,
    record_provenance,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "classification_scrapes")
PCS = "https://www.procyclingstats.com"
# The full Chrome string matters: PCS answers 403 to a stub "Mozilla/5.0".
# It is not blocking scrapers, it is rejecting an obviously fake agent.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")
DELAY = 1.0

# Tab label -> classification_standings.classification. STAGE and GC are read
# from the page but never stored; TEAMS has no per-rider shape at all.
WANTED = {"POINTS": "points", "KOM": "kom", "YOUTH": "youth"}


def fetch(url, force=False):
    """GET with an on-disk cache, so re-parsing costs no requests."""
    key = re.sub(r"[^a-z0-9]+", "_", url.replace(PCS, "").lower()).strip("_")
    path = os.path.join(CACHE, f"{key}.html")
    if not force and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        html = resp.read().decode("utf-8", "replace")
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    time.sleep(DELAY)
    return html


def tab_blocks(html):
    """{TAB LABEL: inner html of its resTab}, keyed by the page's own nav."""
    nav = re.search(r'<ul class="tabs tabnav resultTabs[^"]*"[^>]*>(.*?)</ul>',
                    html, re.S)
    if not nav:
        return {}
    labels = {}
    for did, inner in re.findall(r'<li[^>]*data-id="([^"]+)"[^>]*>(.*?)</li>',
                                 nav.group(1), re.S):
        labels[did] = re.sub(r"<[^>]+>", "", inner).strip().upper()

    out = {}
    for m in re.finditer(r'<div class="resTab[^"]*" data-id="([^"]*)"', html):
        did = m.group(1)
        if did not in labels:
            continue
        # to the next resTab, or the end of the results container
        nxt = re.search(r'<div class="resTab', html[m.end():])
        out[labels[did]] = html[m.end():m.end() + (nxt.start() if nxt else 200000)]
    return out


def parse_rows(block):
    """[(rank, rider_slug, name, team_slug, points, time_seconds)] from one tab."""
    body = re.search(r"<tbody>(.*?)</tbody>", block, re.S)
    if not body:
        return []
    # Column meaning comes from the table's own header codes, not a fixed index:
    # a points table has Pnt where a youth table has Time.
    head = re.search(r"<thead>(.*?)</thead>", block, re.S)
    codes = re.findall(r'data-code="([^"]*)"', head.group(1)) if head else []

    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1), re.S):
        slug = re.search(r'href="(rider/[^"]+)"', tr)
        if not slug:
            continue
        tds = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", td)).strip()
               for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if not tds:
            continue
        rank = parse_int(tds[0])
        if rank is None:
            continue
        cell = dict(zip(codes, tds))
        name = re.search(r'href="rider/[^"]+"[^>]*>(.*?)</a>', tr, re.S)
        team = re.search(r'href="(team/[^"]+)"', tr)
        # pnt2 is the CLASSIFICATION total. `pnt` beside it is PCS points and
        # `uci_pnt` is UCI points; both are the 80/20/10-style award for placing
        # in the classification, not the tally that decided it — Mads Pedersen
        # took the 2025 Giro points jersey on 295, with pnt=80 next to it.
        # scrape_pcs_kom_finals.py already read pnt2 for the Tour; same column,
        # now for every race.
        pts = parse_int(cell.get("pnt2") or "")
        # PCS prints the time and the gap in ONE cell, so the leader's reads
        # "82:34:57 82:34:57" and parses as neither. Same defect as the stage
        # tables (rule 2 of the five); take the first half.
        secs = parse_time_to_seconds((cell.get("time") or "").split(" ")[0])
        rows.append((rank, slug.group(1),
                     fix_mojibake(re.sub(r"<[^>]+>", "", name.group(1)).strip())
                     if name else None,
                     team.group(1) if team else None, pts, secs))
    return rows


def scrape_edition(race, year, force=False):
    """{classification: rows} for one race-year, or {} when the page has none."""
    url = f"{PCS}/race/{RACES[race].pcs_slug}/{year}/gc"
    try:
        html = fetch(url, force=force)
    except urllib.error.HTTPError as e:
        print(f"  {race} {year}: HTTP {e.code}")
        return {}, url
    blocks = tab_blocks(html)
    out = {}
    for label, kind in WANTED.items():
        if label in blocks:
            rows = parse_rows(blocks[label])
            if rows:
                out[kind] = rows
    return out, url


def editions(cur, race, only_year=None):
    """[(edition_id, year)] already in the database for this race."""
    q = """SELECT e.edition_id, e.year FROM race_editions e
             JOIN races r ON r.race_id = e.race_id
            WHERE r.name = ?"""
    args = [RACES[race].name]
    if only_year:
        q += " AND e.year = ?"
        args.append(only_year)
    return cur.execute(q + " ORDER BY e.year", args).fetchall()


def store(cur, edition_id, kind, rows, url):
    """Replace one classification for one edition. Returns rows written."""
    cur.execute("DELETE FROM classification_standings WHERE edition_id=? "
                "AND classification=?", (edition_id, kind))
    written = 0
    for rank, slug, name, team, pts, secs in rows:
        # A rider or team the results never mentioned would break the FK; the
        # classification page is not the place to mint either.
        if not cur.execute("SELECT 1 FROM riders WHERE rider_id=?", (slug,)).fetchone():
            continue
        if team and not cur.execute("SELECT 1 FROM teams WHERE team_id=?",
                                    (team,)).fetchone():
            team = None
        cur.execute(
            """INSERT OR IGNORE INTO classification_standings
                 (edition_id, classification, rank, rider_id, team_id,
                  points, time_seconds) VALUES (?,?,?,?,?,?,?)""",
            (edition_id, kind, rank, slug, team, pts, secs))
        written += cur.rowcount
    if written:
        record_provenance(cur, "race_editions", edition_id, f"classification:{kind}",
                          SOURCE_PCS, source_ref=url,
                          script="scrape_classifications.py")
    return written


def main(argv=None):
    exit_on_help(__doc__, argv)
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=list(STAGE_RACES))
    ap.add_argument("--year", type=int)
    ap.add_argument("--force", action="store_true", help="refetch, ignore the cache")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    races = [args.race] if args.race else list(STAGE_RACES)
    total = skipped = 0

    for race in races:
        for edition_id, year in editions(cur, race, args.year):
            found, url = scrape_edition(race, year, args.force)
            if not found:
                skipped += 1
                continue
            parts = []
            for kind, rows in sorted(found.items()):
                if args.apply:
                    n = store(cur, edition_id, kind, rows, url)
                else:
                    n = len(rows)
                parts.append(f"{kind}={n}")
                total += n
            print(f"  {race} {year}: " + ", ".join(parts))

    if args.apply:
        conn.commit()
    print(f"\n{'wrote' if args.apply else '[DRY RUN] would write'} {total:,} "
          f"standing(s); {skipped} edition(s) had none")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
