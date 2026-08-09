#!/usr/bin/env python3
"""
Reclassify closing time trials that are stored as flat road stages.

`detect_route_type` reads PCS's "Won how" field. For older stages PCS prints
"-" there, and the fallback is 'F' — flat. So a decisive final-day time trial
comes out looking like a processional run-in: the 1968 Tour's 55.2 km Melun >
Paris, where Janssen took the race off van Springel, was stored as route_type
'F', stage_type 'road'. Same for the 1989 Versailles ITT (fixed separately in
fix_paris_finale_distances.py), the Giro's Roma and Verona finales, and the
Vuelta's run of San Sebastian and Madrid closers.

Nothing is guessed. Each candidate is fetched from PCS by its source_slug and
reclassified only on positive evidence:

  * PCS renders a **Startorder** tab on time trials and only on time trials.
    Verified against controls — 1968 stage-22a (road) and 1998 stage-21 (road)
    have none, while 1968 22b, Giro 2009 st21 and Vuelta 2014 st21 all do. The
    profile icon does NOT discriminate: PCS serves p0 for the 1998 road finale
    too.
  * A `ttt-results` list means the field rode it as teams, so it is a TTT
    rather than an ITT.

A stage showing neither marker is left exactly as it is.

Candidates are stages already classified 'F' with no "Won how" evidence — i.e.
stages whose type was defaulted, never determined. --all-stages widens the scan
beyond final stages.

Usage:
  python3 fix_tt_route_types.py --dry-run
  python3 fix_tt_route_types.py --apply
  python3 fix_tt_route_types.py --all-stages --dry-run
"""

import argparse
import re
import sqlite3
import sys
import time
import urllib.request

from race_common import DB_PATH, SOURCE_PCS, record_provenance

BASE = "https://www.procyclingstats.com"
RACE_PATHS = {
    "Tour de France": "tour-de-france",
    "Giro d'Italia": "giro-d-italia",
    "Vuelta a España": "vuelta-a-espana",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0"}
DELAY = 1.5

# A time trial long enough to be mistaken for a road stage is rare; above this
# the 'F' classification is more likely correct than not, and each case wants a
# human. The longest closing TT in the candidate set is 55.2 km.
MAX_KM = 75


def classify(race_path, year, slug):
    """('TT'|'TTT'|None, note) from the PCS stage page."""
    url = f"{BASE}/race/{race_path}/{year}/{slug}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS),
                                    timeout=25) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return None, f"fetch failed ({exc})"
    if re.search(r'class="[^"]*ttt-results', html):
        return "TTT", url
    text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    if "Startorder" in text:
        return "TT", url
    return None, "no Startorder tab — PCS does not present this as a time trial"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all-stages", action="store_true",
                    help="scan every stage, not just each edition's last")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro" if args.dry_run else DB_PATH,
                           uri=args.dry_run)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    final_only = "" if args.all_stages else (
        " AND s.stage_number=(SELECT MAX(stage_number) FROM stages x "
        " WHERE x.edition_id=s.edition_id)")
    rows = cur.execute(f"""
        SELECT s.stage_id, ra.name race, re.year, s.stage_number n, s.source_slug,
               s.start_location a, s.finish_location b, s.distance_km d
          FROM stages s
          JOIN race_editions re USING(edition_id)
          JOIN races ra USING(race_id)
         WHERE s.route_type='F'
           AND (s.won_how IS NULL OR s.won_how IN ('', '-'))
           AND NOT s.cancelled
           AND s.distance_km > 0 AND s.distance_km < ?
           AND s.source_slug IS NOT NULL
           {final_only}
         ORDER BY ra.name, re.year, s.stage_number""", (MAX_KM,)).fetchall()

    print(f"{len(rows)} candidate(s) — stages defaulted to 'F' with no evidence\n")
    changed = left = failed = 0
    for r in rows:
        verdict, note = classify(RACE_PATHS[r["race"]], r["year"], r["source_slug"])
        time.sleep(DELAY)
        tag = (f"{r['race'][:6]} {r['year']} n={r['n']:<3} {r['source_slug']:<10} "
               f"{r['a']} -> {r['b']}  {r['d']} km")
        if verdict is None:
            if note.startswith("fetch failed"):
                failed += 1
                print(f"  ?  {tag}\n       {note}")
            else:
                left += 1
                print(f"  =  {tag}\n       {note}")
            continue
        stage_type = "itt"
        print(f"  ->  {tag}\n       F/road -> {verdict}/{stage_type}")
        changed += 1
        if args.apply:
            cur.execute("UPDATE stages SET route_type=?, stage_type=? WHERE stage_id=?",
                        (verdict, stage_type, r["stage_id"]))
            for field in ("route_type", "stage_type"):
                record_provenance(cur, "stages", r["stage_id"], field, SOURCE_PCS,
                                  source_ref=f"{note} (Startorder tab present; "
                                             "PCS leaves 'Won how' empty)")

    if args.apply:
        conn.commit()
    conn.close()
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}{changed} reclassified, "
          f"{left} left as 'F', {failed} unreachable")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
