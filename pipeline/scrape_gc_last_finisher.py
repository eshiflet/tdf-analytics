#!/usr/bin/env python3
"""Read the lanterne rouge's total time off PCS's own GC page.

17 editions hold no `gc_rank=1` on their final stage, which is a PROOF that
the stored classification is not the whole field — the overall leader is
necessarily in a complete final GC. Their `slowestFinisherTimeSeconds`, which
the All Races view charts as a red "Slowest Finisher" line, is therefore the
slowest of the handful of riders we happen to hold: around 10th place in these
Giro years. Giro 1966 stores ten riders and charts 411,115s; PCS's own page
has 83 finishers and the last of them at 415,331s.

The house fix is to RESEARCH the figure, not to suppress it, so this fetches
PCS's full GC and writes `{year: seconds}` for the last classified rider.
Nothing is computed from what the database already holds — that is the thing
being corrected.

**Two traps, both already solved in this repo, both re-used here rather than
re-discovered:**

* *The first `<table class="results">` on the page is NOT the GC.* It is
  whichever tab PCS renders first, and reading it gives a confident, wrong
  answer — a 10-row table of something else entirely. `tab_blocks()` keys each
  block by the page's own nav, and this reads the block labelled `GC`.
* *PCS prints the value twice in one cell*: `111:10:48 111:10:48` for the
  winner, `4:11:234:11:23` for a gap. `first_time()` un-doubles it.

**The parse is gated on a value we already trust.** Every page's winner time
must match `{race}_gc_winner_times.json` to the second, or that year is
refused and reported rather than written. A page that parsed the wrong table,
the wrong race or the wrong year cannot agree with a number sourced
independently, so the gate catches exactly the failure that would otherwise
look like data.

Usage:
  python3 scrape_gc_last_finisher.py --race giro --years 1928,1930
  python3 scrape_gc_last_finisher.py --race giro          # every gapped year
"""
import argparse
import html as H
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from race_common import exit_on_help
from scrape_classifications import tab_blocks

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; tdf-analytics/1.0)"}
DELAY = 2.0

RACES = {
    "giro": ("Giro d'Italia", "giro-d-italia", "giro_gc_winner_times.json"),
    "vuelta": ("Vuelta a España", "vuelta-a-espana", "vuelta_gc_winner_times.json"),
    "tour": ("Tour de France", "tour-de-france", "tour_gc_winner_times.json"),
}


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def cells(row):
    return [H.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def first_time(text):
    """`111:10:48 111:10:48` and `4:11:234:11:23` both hold ONE value."""
    t = text.strip()
    # PCS's own time-adjusted marker rides on the front of the cell:
    # `*2:36:402:36:40`. It annotates the time; it is not part of it.
    adjusted = t.startswith("*")
    t = t.lstrip("*").strip()
    if not t:
        return None, False
    parts = t.split()
    if len(parts) == 2 and parts[0] == parts[1]:
        t = parts[0]
    elif len(t) % 2 == 0 and t[:len(t) // 2] == t[len(t) // 2:]:
        t = t[:len(t) // 2]
    m = re.match(r"^(\d+):(\d{2}):(\d{2})$", t)
    if m:
        return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]), adjusted
    m = re.match(r"^(\d+):(\d{2})$", t)
    if m:
        return int(m[1]) * 60 + int(m[2]), adjusted
    return None, adjusted


def parse_gc(doc):
    """(winner_seconds, last_rank, last_gap_seconds) from the GC tab."""
    block = tab_blocks(doc).get("GC")
    if not block:
        return None, None, None
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S)
    ranked = []
    for r in rows:
        c = cells(r)
        if len(c) < 12 or not c[0].isdigit():
            continue
        ranked.append((int(c[0]), c[11]))
    if len(ranked) < 2:
        return None, None, None
    winner, _ = first_time(ranked[0][1])
    # The SLOWEST finisher, not the last-ranked one. Giro 1961 separates them:
    # rank 92 is 2:36:40 down while rank 91 is 3:22:20 down, because PCS has
    # adjusted the last man's time (the `*`). `slowestFinisherTimeSeconds` is
    # a TIME, so it has to be the largest one on the page.
    gaps = [(first_time(cell)[0], rank) for rank, cell in ranked[1:]]
    gaps = [(g, r) for g, r in gaps if g is not None]
    if not gaps:
        return winner, None, None
    gap, rank = max(gaps)
    return winner, rank, gap


def main(argv=None):
    exit_on_help(__doc__)
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=sorted(RACES), default="giro")
    ap.add_argument("--years", help="comma-separated; default: every gapped year")
    args = ap.parse_args(argv)

    db_name, slug, winners_file = RACES[args.race]
    winners = json.load(open(os.path.join(HERE, winners_file), encoding="utf-8"))

    if args.years:
        years = [int(y) for y in args.years.split(",")]
    else:
        conn = sqlite3.connect(DB_PATH)
        years = [y for (y,) in conn.execute("""
            SELECT re.year FROM race_editions re JOIN races r ON r.race_id=re.race_id
             WHERE r.name = ? AND NOT EXISTS (
               SELECT 1 FROM stage_results sr JOIN stages s ON sr.stage_id=s.stage_id
                WHERE s.edition_id=re.edition_id AND sr.gc_rank=1
                  AND s.stage_number=(SELECT MAX(stage_number) FROM stages
                                       WHERE edition_id=re.edition_id))
             ORDER BY re.year""", (db_name,))]
        conn.close()

    print(f"{args.race}: {len(years)} year(s) — {years}\n")
    print(f"{'year':<6}{'finishers':>10}{'winner':>10}{'slowest':>10}"
          f"{'gap':>10}  verdict")
    out, refused = {}, []
    for i, year in enumerate(years):
        if i:
            time.sleep(DELAY)
        url = f"https://www.procyclingstats.com/race/{slug}/{year}/gc/result/result"
        try:
            win, last_rank, gap = parse_gc(fetch(url))
        except Exception as e:
            refused.append((year, f"fetch/parse failed: {type(e).__name__}"))
            print(f"{year:<6}{'-':>10}{'-':>10}{'-':>10}{'-':>10}  REFUSED")
            continue
        known = winners.get(str(year))
        if win is None or gap is None:
            refused.append((year, "no winner time or no last-rider gap on the page"))
            verdict = "REFUSED (unparsed)"
        elif known is None:
            refused.append((year, "no independent winner time to gate on"))
            verdict = "REFUSED (no gate)"
        elif win != known:
            refused.append((year, f"winner {win}s != known {known}s"))
            verdict = f"REFUSED (winner {win} != {known})"
        else:
            out[str(year)] = win + gap
            verdict = f"ok, rank {last_rank}"
        print(f"{year:<6}{str(last_rank):>10}{str(win):>10}"
              f"{str(out.get(str(year),'-')):>10}{str(gap):>10}  {verdict}")

    print(f"\n{len(out)} year(s) parsed and gated, {len(refused)} refused")
    for year, why in refused:
        print(f"   {year}: {why}")
    if out:
        path = os.path.join(HERE, f"{args.race}_gc_last_finisher.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, sort_keys=True)
            f.write("\n")
        print(f"\nwrote {os.path.basename(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
