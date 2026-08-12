#!/usr/bin/env python3
"""
Give each rider his team's placing and time on a TTT PCS lists teams-only.

Three Tour team time trials — 1981 stage-4, 1983 stage-2, 1984 stage-3 — carry
a ttt-results block with every team's rank, time and gap, but each team's
nested rider table is EMPTY. PCS never published who rode, so parse_ttt_rows
correctly returns nothing and reingest_tdf_stage --from-pcs cannot help. The DB
holds the riders (from the GC page) with no finishing position and no time.

Everything needed is already present:

  * the team's rank, time and gap come from PCS's TTT block
  * the rider -> team mapping is already in stage_results.team_id

No startlist scrape is needed. The team sets match PCS exactly on all three
stages — 15/15, 14/14, 17/17, identical slugs — which is itself the check that
the two sources describe the same race.

Assigning the team's time to every one of its riders is not an assumption; it
is what PCS itself publishes on every TTT where the rider tables ARE filled in.
Checked against three recovered stages (1985 st3, 1990 st2, 2013 st4): 62 teams,
not one with more than a single (rank, time) pair among its riders.

Recorded as SOURCE_DERIVED, not SOURCE_PCS: PCS published the team's time, not
this rider's. A rider dropped by his team on the road would really have finished
later, and nothing here can see that.

Usage:
  python3 derive_ttt_rider_times.py --dry-run
  python3 derive_ttt_rider_times.py --apply
"""

import argparse
import re
import sqlite3
import sys
import time
import urllib.request

from race_common import (
    DB_PATH,
    SOURCE_DERIVED,
    parse_time_to_seconds,
    record_provenance,
)

BASE = "https://www.procyclingstats.com"
DELAY = 1.5
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0"}

# (year, DB stage_number). The slug is read from the DB — on a split edition the
# DB's numbering and PCS's diverge permanently, so 1981's stage_number 5 is
# PCS's stage-4.
TARGETS = [(1981, 5), (1983, 2), (1984, 3)]

_LI = re.compile(r"<li>(.*?)</li>", re.S)
_RANK = re.compile(r'<div class="w10 fs14">\s*(\d+)\s*</div>')
_TEAM = re.compile(r'href="(team/[^"]+)"')
_TIME = re.compile(r'<div[^>]*\btime\b[^>]*>\s*([\d:]+)\s*</div>')
_GAP = re.compile(r'</div>\s*<div class="w25 fs14">\s*([+\d:]+)\s*</div>')


def team_blocks(html):
    """[(rank, team_slug, seconds, gap_seconds)] from the ttt-results list."""
    ul = re.search(r'<ul class="list ttt-results">(.*?)</ul>', html, re.S)
    if not ul:
        return []
    out = []
    for li in _LI.findall(ul.group(1)):
        rank, team, tm, gap = (_RANK.search(li), _TEAM.search(li),
                               _TIME.search(li), _GAP.search(li))
        if not (rank and team and tm):
            continue
        secs = parse_time_to_seconds(tm.group(1))
        if secs is None:
            continue
        out.append((int(rank.group(1)), team.group(1), secs,
                    parse_time_to_seconds(gap.group(1)) if gap else None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro" if args.dry_run else DB_PATH,
                           uri=args.dry_run)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    total = 0

    for year, n in TARGETS:
        st = cur.execute("""
            SELECT s.stage_id, s.source_slug, s.route_type FROM stages s
              JOIN race_editions re USING(edition_id) JOIN races ra USING(race_id)
             WHERE ra.name='Tour de France' AND re.year=? AND s.stage_number=?""",
                         (year, n)).fetchone()
        if not st:
            print(f"  TDF {year} st{n}: not in the database"); continue

        url = f"{BASE}/race/tour-de-france/{year}/{st['source_slug']}/result/result"
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=HEADERS), timeout=25) as r:
            html = r.read().decode("utf-8", errors="replace")
        time.sleep(DELAY)
        blocks = team_blocks(html)
        by_team = {b[1]: b for b in blocks}

        rows = cur.execute(
            "SELECT result_id, rider_id, team_id, stage_rank FROM stage_results "
            "WHERE stage_id=?", (st["stage_id"],)).fetchall()
        db_teams = {r["team_id"] for r in rows}

        print(f"\n  TDF {year} st{n} ({st['source_slug']}, {st['route_type']}): "
              f"PCS {len(blocks)} teams, DB {len(db_teams)} teams, {len(rows)} riders")
        if not blocks:
            print("     no team block on the page — skipped"); continue
        # The two sources must describe the same race before anything is joined.
        if db_teams != set(by_team):
            print(f"     REFUSED: team sets differ. only-PCS={sorted(set(by_team)-db_teams)} "
                  f"only-DB={sorted(db_teams-set(by_team))}")
            continue
        ranks = [b[0] for b in sorted(blocks, key=lambda b: b[2])]
        if ranks != sorted(ranks):
            print("     REFUSED: team ranks do not increase with team time")
            continue
        already = [r for r in rows if r["stage_rank"] is not None]
        if already:
            print(f"     REFUSED: {len(already)} rider(s) already have a position")
            continue

        win = min(b[2] for b in blocks)
        for b in sorted(blocks, key=lambda b: b[0])[:3]:
            print(f"       {b[0]:>2}. {b[1]:<40} {b[2]}s  +{b[3] if b[3] is not None else 0}s")
        print(f"       ... assigning to {len(rows)} riders across {len(blocks)} teams")
        total += len(rows)

        if args.apply:
            for r in rows:
                rank, _, secs, gap = by_team[r["team_id"]]
                cur.execute(
                    "UPDATE stage_results SET stage_rank=?, finish_time_seconds=?, "
                    "gap_seconds=? WHERE result_id=?",
                    (rank, secs, gap if gap is not None else secs - win, r["result_id"]))
            record_provenance(
                cur, "stages", st["stage_id"], "results", SOURCE_DERIVED,
                source_ref=f"{url} — PCS publishes team times only (rider tables "
                           "empty); each rider takes his team's rank and time, "
                           "team membership from stage_results.team_id")
            conn.commit()

    conn.close()
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}{total} rider result(s) "
          f"{'would be ' if args.dry_run else ''}given a position and a time")
    sys.exit(0)


if __name__ == "__main__":
    main()
