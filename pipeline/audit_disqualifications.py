#!/usr/bin/env python3
"""
Find riders PCS has STRUCK THROUGH — disqualified — that we store as finishers.

PCS marks an annulled result by wrapping the rank in <s>, keeping the number:

    <td><s>&nbsp;1&nbsp;</s></td>   Aucouturier, 1904 stage 3 — disqualified
    <td>1</td>                      Cornet, the rider actually awarded the win

Every scraper here strips HTML tags, so both became a plain rank "1" and the
database ended up with two rank-1 finishers on one stage. That is the whole
explanation for the duplicated ranks validate_db reports, and it is worse than
a cosmetic tie: ingest takes the FIRST rank-1 row carrying an absolute time as
the stage winner, so on 1904 stage 3 every rider's finish time is computed
against the time of a man who was stripped of the result.

This is a SECOND disqualification convention, not the one already handled.
Where PCS puts the literal text "DSQ" in the rank cell, ingest_race already
reads it as a status (344 rows). The struck-through rank is invisible to it.

The 1904 Tour is the clearest case and is well documented: the UVF heard
testimony for months and in December 1904 disqualified the first four finishers
and every stage winner — 29 riders punished, two for life — handing the race to
19-year-old Henri Cornet four months after it ended. All six of its stages carry
a duplicated rank 1 in this database.

TWO SHAPES, and only one of them is findable from inside the database:

  * the rank is VACATED and someone is promoted into it, giving two riders the
    same number — 1904, where Cornet was awarded Aucouturier's win. These show
    up as duplicated ranks, which is what --duplicated-rank1 finds.
  * the rank is vacated and NOBODY moves up. The 2005 Tour GC strikes
    Armstrong at 1, Ullrich at 3, Leipheimer at 6, Hincapie at 14 and Boogerd
    at 24, and Basso stays 2, Mancebo 4, Vinokurov 5. No duplicate rank exists,
    so nothing in our data hints at it. Only the page shows it, which is why
    --years exists and why the seven Armstrong Tours have to be asked for by
    name.

What --apply writes, per struck rider:
  * disqualified -> 1
Nothing else. The rank, the time and the row all stay: the ride happened and
the clock ran, what was taken away was the placing. The frontend renders these
struck through, the way PCS does, so the rider stays visible and the fact is
visible with him.

Usage:
  python3 audit_disqualifications.py --race tour --years 1904
  python3 audit_disqualifications.py --race tour --years 1904 --apply
  python3 audit_disqualifications.py --duplicated-rank1    # the 39 suspects
Dry run unless --apply. SCRAPE_DELAY overrides the 2.5s delay.
"""

import argparse
import html as html_mod
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

from race_common import DB_PATH, SOURCE_PCS, record_provenance

BASE = "https://www.procyclingstats.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
PCS_RACE = {"Tour de France": "tour-de-france", "Giro d'Italia": "giro-d-italia",
            "Vuelta a España": "vuelta-a-espana"}
CLI = {"tour": "Tour de France", "giro": "Giro d'Italia", "vuelta": "Vuelta a España"}
DELAY = float(os.environ.get("SCRAPE_DELAY", "2.5"))


def fetch(url):
    for _ in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS),
                                        timeout=25) as r:
                html = r.read().decode("utf-8", "replace")
                return None if ("Just a moment" in html and len(html) < 10000) else html
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            time.sleep(5)
        except Exception:
            time.sleep(5)
    return None


def struck_riders(html):
    """Rider slugs whose rank cell is wrapped in <s>, plus the rank shown.

    Returns None when the page has no parsable results table, so 'no table'
    is never mistaken for 'nobody was disqualified'.
    """
    t = re.search(r'<table[^>]*class="[^"]*results[^"]*"[^>]*>(.*?)</table>', html, re.S)
    if not t:
        return None
    tb = re.search(r"<tbody[^>]*>(.*?)</tbody>", t.group(1), re.S)
    if not tb:
        return None
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tb.group(1), re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if not tds:
            continue
        m = re.search(r"<s>(.*?)</s>", tds[0], re.S)
        if not m:
            continue
        rank = html_mod.unescape(re.sub(r"<[^>]+>", "", m.group(1))).replace("\xa0", " ").strip()
        slug = re.search(r'href="(rider/[^"]+)"', tr)
        if slug:
            out.append((slug.group(1), rank))
    return out


def stage_url(st):
    """A one-day race already stores its whole path in source_slug
    ('race/paris-roubaix/1949/result'); a stage race stores just the stage
    segment and needs the race and year putting back around it."""
    slug = st["source_slug"]
    if slug.startswith("race/"):
        return f"{BASE}/{slug}"
    return (f"{BASE}/race/{PCS_RACE[st['name']]}/{st['year']}/"
            f"{slug}/result/result")


def stages_for(cur, race_name, years, dup_only):
    q = """SELECT s.stage_id, s.stage_number, s.source_slug, e.year, ra.name
             FROM stages s
             JOIN race_editions e ON e.edition_id = s.edition_id
             JOIN races ra ON ra.race_id = e.race_id
            WHERE s.source_slug IS NOT NULL AND COALESCE(s.cancelled,0)=0"""
    args = []
    if race_name:
        q += " AND ra.name = ?"
        args.append(race_name)
    if years:
        q += f" AND e.year IN ({','.join('?' * len(years))})"
        args += years
    if dup_only:
        q += """ AND s.stage_id IN (
                   SELECT stage_id FROM stage_results
                    WHERE status='FINISHED' AND stage_rank = 1
                    GROUP BY stage_id HAVING COUNT(*) > 1)
                 AND COALESCE(s.route_type,'') <> 'TTT'"""
    return cur.execute(q + " ORDER BY e.year, s.stage_number", args).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=sorted(CLI))
    ap.add_argument("--years", help="e.g. 1904 or 1903-1910")
    ap.add_argument("--duplicated-rank1", action="store_true",
                    help="only stages that already show two rank-1 finishers")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    years = []
    if args.years:
        for part in args.years.split(","):
            if "-" in part:
                a, b = part.split("-")
                years += list(range(int(a), int(b) + 1))
            else:
                years.append(int(part))
    if not (args.race or years or args.duplicated_rank1):
        ap.error("give --race, --years or --duplicated-rank1; "
                 "auditing every stage is thousands of requests")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    stages = stages_for(cur, CLI.get(args.race), years, args.duplicated_rank1)
    print(f"Auditing {len(stages)} stage(s) for struck-through ranks\n")

    found = unparsable = written = 0
    for st in stages:
        url = stage_url(st)
        html = fetch(url)
        if html is None:
            print(f"  {st['year']} {st['source_slug']:<12} FETCH FAILED")
            time.sleep(DELAY)
            continue
        struck = struck_riders(html)
        if struck is None:
            unparsable += 1
            print(f"  {st['year']} {st['source_slug']:<12} no parsable results table")
            time.sleep(DELAY)
            continue
        hits = []
        for slug, shown in struck:
            row = cur.execute(
                """SELECT sr.result_id, sr.stage_rank, sr.status, sr.disqualified,
                          ri.full_name
                     FROM stage_results sr JOIN riders ri ON ri.rider_id = sr.rider_id
                    WHERE sr.stage_id = ? AND sr.rider_id = ?""",
                (st["stage_id"], slug)).fetchone()
            if row and not row["disqualified"]:
                hits.append((row, shown))
        if hits:
            found += len(hits)
            print(f"  {st['year']} {st['source_slug']:<12} "
                  f"{len(hits)} disqualified rider(s) stored as finishers:")
            for row, shown in hits:
                print(f"      #{str(row['stage_rank']):<5} {row['full_name'][:28]:<30} "
                      f"status={row['status']}  (PCS shows rank {shown}, struck)")
                if args.apply:
                    cur.execute("UPDATE stage_results SET disqualified=1 "
                                "WHERE result_id=?", (row["result_id"],))
                    record_provenance(cur, "stage_results", row["result_id"],
                                      "disqualified", SOURCE_PCS,
                                      source_ref=f"{url} — rank struck through "
                                                 "(<s>), result annulled")
                    written += 1
        time.sleep(DELAY)

    print(f"\n{found} disqualified rider(s) found across {len(stages)} stage(s)"
          + (f"; {unparsable} page(s) unparsable" if unparsable else ""))
    if args.apply:
        conn.commit()
        print(f"APPLIED: {written} row(s) marked disqualified=1 (rank and time kept).")
    else:
        print("Dry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
