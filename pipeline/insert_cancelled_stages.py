#!/usr/bin/env python3
"""
Fill stage-number gaps with the cancelled stages that belong in them.

A gap in an edition's stage_number sequence means a stage is missing. In every
case found so far the missing stage is one PCS lists as CANCELLED: it has a
date, route and distance but no results, so the scrapers — which require a
results table — skipped it, while every later stage kept its PCS number. The
hole is therefore fillable by a plain INSERT, with no renumbering.

Confirmed instances (all verified on PCS):
    Giro 1912 stage 4   Pescara -> Roma
    Giro 1946 stage 12  Rovigo -> Trieste
    Giro 1969 stage 20  Trento -> Marmolada        cold and snow
    Giro 2001 stage 18  Imperia -> Sant'Anna di Vinadio   San Remo raids
    Giro 2011 stage 4   Genova -> Livorno          Weylandt tribute
    Giro 2013 stage 19  Ponte di Legno -> Val Martello    adverse weather

Precedent: Vuelta 1968 stage 15 and Vuelta 1991 stage 11 already sit in the DB
this way — cancelled=1, zero results.

Safety: a stage is only inserted when PCS's page for that slug actually says
the stage was cancelled AND the neighbouring DB stages confirm the slug
numbering is unshifted there. Anything else is reported and skipped, because a
gap could also mean a stage was simply never scraped, and inventing a row for
that would fabricate a stage that was really raced.

Usage:
  python3 insert_cancelled_stages.py --dry-run
  python3 insert_cancelled_stages.py --apply
"""

import argparse
import re
import sqlite3
import sys
import time
import unicodedata

from audit_elevation import fetch
from race_common import DB_PATH, SOURCE_PCS, record_provenance

BASE = "https://www.procyclingstats.com"
RACE_PATH = {
    "Tour de France": "tour-de-france",
    "Giro d'Italia": "giro-d-italia",
    "Vuelta a España": "vuelta-a-espana",
}
CANCEL_RE = re.compile(r"(race/stage is cancelled|stage was cancelled|stage is cancelled"
                       r"|stage cancelled)", re.I)


def page_text(html):
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def parse_meta(html):
    t = page_text(html)
    out = {}
    m = re.search(r"Date:\s*(\d{1,2} \w+ \d{4})", t)
    if m:
        from datetime import datetime
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                out["date"] = datetime.strptime(m.group(1), fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                pass
    m = re.search(r"Departure:\s*(.+?)\s+Arrival:\s*(.+?)\s+(?:Race ranking|Distance|Date|Won how)", t)
    if m:
        out["start"], out["finish"] = m.group(1).strip(), m.group(2).strip()
    # header "(294km)"
    m = re.search(r"\((\d+(?:\.\d+)?)\s*km\)", t, re.I)
    if m:
        out["km"] = float(m.group(1))
    out["cancelled"] = bool(CANCEL_RE.search(t))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c, w = conn.cursor(), conn.cursor()

    inserted = skipped = 0
    for e in c.execute("""SELECT re.edition_id, re.year, r.name race
                          FROM race_editions re JOIN races r ON re.race_id=r.race_id
                          ORDER BY r.name, re.year""").fetchall():
        stages = w.execute(
            "SELECT stage_number, source_slug FROM stages WHERE edition_id=? ORDER BY stage_number",
            (e["edition_id"],)).fetchall()
        if not stages:
            continue
        nums = [s["stage_number"] for s in stages]
        by_num = {s["stage_number"]: s["source_slug"] for s in stages}
        gaps = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
        if not gaps:
            continue

        for gap in gaps:
            tag = f"{e['race'][:6]} {e['year']} stage {gap}"
            # The neighbours must both carry their own number as their slug,
            # otherwise this edition's numbering is shifted and 'stage-{gap}'
            # would point somewhere else entirely.
            before, after = by_num.get(gap - 1), by_num.get(gap + 1)
            if before != f"stage-{gap-1}" or after != f"stage-{gap+1}":
                print(f"  SKIP {tag}: neighbours are {before}/{after}, numbering is "
                      "shifted here — cannot infer the missing slug")
                skipped += 1
                continue

            slug = f"stage-{gap}"
            html = fetch(f"{BASE}/race/{RACE_PATH[e['race']]}/{e['year']}/{slug}")
            time.sleep(1.5)
            if not html:
                print(f"  SKIP {tag}: no PCS page for {slug}")
                skipped += 1
                continue
            meta = parse_meta(html)
            if not meta.get("cancelled"):
                print(f"  SKIP {tag}: PCS does not mark {slug} cancelled — a stage that "
                      "was actually raced is missing; scrape it properly instead")
                skipped += 1
                continue
            if not (meta.get("date") and meta.get("start") and meta.get("finish")):
                print(f"  SKIP {tag}: PCS page incomplete {meta}")
                skipped += 1
                continue

            print(f"  {tag}: {meta['date']}  {meta['start']} -> {meta['finish']}  "
                  f"{meta.get('km','?')}km  [cancelled]")
            inserted += 1
            if args.apply:
                w.execute("""INSERT INTO stages
                      (edition_id, stage_number, stage_label, stage_date,
                       start_location, finish_location, distance_km, stage_type,
                       route_type, cancelled, source_slug)
                      VALUES (?,?,?,?,?,?,?,?,?,1,?)""",
                          (e["edition_id"], gap, f"Stage {gap}", meta["date"],
                           # 0.0, not PCS's PLANNED distance: the stage was
                           # never raced, so it contributed nothing to the
                           # edition's total. Recording the planned figure
                           # would inflate totalDistanceKm and trip the
                           # Wikipedia reconciliation check. Matches how
                           # Vuelta 1968 st15 and 1991 st12 are already stored.
                           meta["start"], meta["finish"], 0.0,
                           "road", "F", slug))
                sid = w.lastrowid
                url = f"{BASE}/race/{RACE_PATH[e['race']]}/{e['year']}/{slug}"
                record_provenance(w, "stages", sid, "source_slug", SOURCE_PCS,
                                  source_ref=f"{url} (cancelled stage)")
                record_provenance(
                    w, "stages", sid, "distance_km", SOURCE_PCS,
                    source_ref=f"{url} — 0 km: cancelled, never raced "
                               f"(PCS lists a planned {meta.get('km','?')}km)")
        if args.apply:
            conn.commit()

    conn.close()
    print(f"\n{'[DRY RUN] ' if not args.apply else ''}"
          f"{inserted} cancelled stage(s) {'would be ' if not args.apply else ''}inserted, "
          f"{skipped} skipped")
    if args.apply and inserted:
        print("Re-run validate_db.py and the affected exports.")


if __name__ == "__main__":
    main()
