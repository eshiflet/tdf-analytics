#!/usr/bin/env python3
"""Scrape a gravel race from PCS, into the standard gravel scrape-file shape.

PCS DOES cover some gravel — the earlier "it has nothing here" note was wrong,
and the way it was wrong is worth keeping: PCS files these under
`national-race/`, a namespace **its own search does not return**. Searching for
"traka" and "gravel" finds nothing, so one search looked like proof. Probe the
URL instead:

    procyclingstats.com/national-race/<slug>/<year>/result

Where PCS has a gravel race it is a better source than the event timer, for one
reason that outranks the rest: **it gives real `rider/<slug>` ids**. Rider
identity across this DB is otherwise matched by NAME under a strict rule with
its evidence written down (link_gravel_riders.py), because Athlinks has no id
to join on. A PCS slug turns that claim into a fact. It also publishes the
rider's TRUE finishing position in the full field, so no top-N window has to be
invented — see the `pcs_field` rule below.

Two things about PCS's rider column that shape everything downstream:

  rider/<slug>           a rider PCS tracks. Joins directly to `riders`, and is
                         the whole point of preferring this source.
  national-rider/<slug>  a rider PCS knows only from national/amateur racing.
                         A SEPARATE namespace — these do NOT join to `riders`
                         and must never be stored as if they did. They fall
                         back to the name-matching path like any other
                         gravel-only rider.

The time column is PCS's usual one-cell time-and-gap: rank 1 carries an
absolute finishing time and everyone below carries a GAP to it. Reading the
winner's cell as both is what doubled 3,377 winning times across this DB once
already (ai-context rule 2), so the winner's gap is forced to 0 here and every
other finisher's absolute time is winner + gap.

Usage:
  python3 scrape_pcs_gravel.py --race traka --year 2025
  python3 scrape_pcs_gravel.py --race traka          # every year in the map
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

from race_common import GRAVEL, exit_on_help, fix_mojibake, parse_time_to_seconds
from scrape_athlinks import clean_name, split_name

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES = os.path.join(HERE, "gravel_scrapes")
RAW_CACHE = os.path.join(SCRAPES, "_raw")
PCS = "https://www.procyclingstats.com"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")
DELAY = 1.0          # PCS is a small site; be a polite guest.

# Statuses PCS puts in the rank column instead of a number.
NON_FINISHER = {"DNF", "DNS", "DSQ", "OTL", "NP", "DF"}


def fetch(url, force=False):
    """GET with an on-disk cache, so re-deriving costs nothing."""
    key = re.sub(r"[^a-z0-9]+", "_", url.replace(PCS, "").lower()).strip("_")
    path = os.path.join(RAW_CACHE, f"pcs_{key}.html")
    if not force and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        html = resp.read().decode("utf-8", "replace")
    os.makedirs(RAW_CACHE, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    time.sleep(DELAY)
    return html


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def parse_result(html):
    """(rows, distance_km) from a PCS national-race result page.

    Returns rows in PCS's own order, each with its published rank — which is
    the position in the FULL field, not an index into this list. PCS lists only
    the riders it holds a page for, so 2024's 87 rows run to rank 147. Those
    holes are real and must be preserved: renumbering would claim 87 people
    finished a race 147 finished.
    """
    km = None
    # "<b> &rsaquo; </b> (360km)" in the header block. The tags between the
    # marker and the number move around, so match on the parenthesised figure
    # near the marker rather than on the exact markup. A 0 means PCS does not
    # know the distance (Big Sugar is like this) — that is a gap, not a zero.
    m = re.search(r"&rsaquo;.{0,40}?\((\d+(?:\.\d+)?)km\)", html, re.S)
    if m and float(m.group(1)) > 0:
        km = float(m.group(1))

    body = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    if not body:
        return [], km
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1), re.S):
        slug_m = re.search(r'href="((?:national-)?rider/[^"]+)"', tr)
        if not slug_m:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if not tds:
            continue
        rank_raw = _text(tds[0]).upper()
        # Capture the anchor's TEXT, not the href attribute: group(0) here is
        # the whole `href="team/..."` string and storing that as a team name is
        # exactly what it looks like.
        team_m = re.search(r'href="(team/[^"]+)"[^>]*>(.*?)</a>', tr, re.S)
        name_cell = next((td for td in tds if "rider/" in td), "")
        # PCS renders "SURNAME Firstname"; uppercase span marks the surname.
        surname = re.search(r'<span class="uppercase">(.*?)</span>', name_cell, re.S)
        anchor = re.search(r'href="(?:national-)?rider/[^"]*"[^>]*>(.*?)</a>',
                           name_cell, re.S)
        full = _text(anchor.group(1)) if anchor else ""
        if surname:
            sur = _text(surname.group(1))
            given = _text(full[len(sur):]) if full.startswith(sur) else ""
        else:
            sur, given = full, ""
        flag = re.search(r'<span class="flag ([a-z]{2})"', name_cell)
        time_cell = tds[-1]
        vis = re.search(r"<font[^>]*>(.*?)</font>", time_cell, re.S)
        rows.append({
            "rank_raw": rank_raw,
            "pcs_slug": slug_m.group(1),
            "surname": sur,
            "given": given,
            "team_slug": team_m.group(1) if team_m else None,
            "team_name": _text(team_m.group(2)) if team_m else None,
            "country": flag.group(1) if flag else None,
            "time_raw": _text(vis.group(1)) if vis else "",
        })
    return rows, km


def to_rows(parsed):
    """PCS rows -> the gravel scrape-file row shape, with times resolved."""
    out = []
    winner_seconds = None
    for p in parsed:
        rank = int(p["rank_raw"]) if p["rank_raw"].isdigit() else None
        status = "FINISHED" if rank else (
            p["rank_raw"] if p["rank_raw"] in NON_FINISHER else "DNF")
        secs = parse_time_to_seconds(p["time_raw"]) if p["time_raw"] else None
        if rank == 1:
            # One cell holds BOTH time and gap, so the winner parses with the
            # gap equal to his own finishing time. Take it as the time and zero
            # the gap; winner+gap on this row is the 3,377-row bug.
            finish, gap = secs, 0
            if winner_seconds is None:
                winner_seconds = secs
        elif rank:
            gap = secs
            finish = (winner_seconds + gap) if (winner_seconds and gap is not None) else None
        else:
            finish = gap = None
        # "SURNAME Given" -> "Given Surname", then the archive's own casing.
        name = clean_name(fix_mojibake(f"{p['given']} {p['surname']}".strip()))
        first, last = split_name(name)
        out.append({
            "rank": rank,
            "name": name,
            "first_name": first,
            "last_name": last,
            "bib": None,
            "age": None,
            "gender": "M",
            "country": p["country"],
            "club": None,
            "category": None,
            "finish_seconds": finish,
            "status": status,
            "rank_overall": rank,
            "gap_seconds": gap,
            # The reason this source is preferred. A `rider/` slug joins
            # straight to `riders`; a `national-rider/` one does not exist
            # there and must not be treated as if it did.
            "pcs_slug": p["pcs_slug"],
            "pcs_is_pro": p["pcs_slug"].startswith("rider/"),
            "team_slug": p["team_slug"],
            "team_name": p["team_name"],
        })
    return out


def scrape_year(race_slug, pcs_slug, year, force=False):
    url = f"{PCS}/national-race/{pcs_slug}/{year}/result"
    html = fetch(url, force=force)
    if "Page not found" in html[:4000]:
        return None
    parsed, km = parse_result(html)
    if not parsed:
        return None
    rows = to_rows(parsed)
    pro = sum(1 for r in rows if r["pcs_is_pro"])
    ranks = [r["rank"] for r in rows if r["rank"]]
    info = {
        "race_slug": race_slug,
        "year": year,
        "date": None,          # filled from the map; PCS's panel omits it here
        "source": "pcs",
        "event_id": f"{pcs_slug}/{year}",
        "event_name": f"{GRAVEL[race_slug].name} {year}",
        "course_id": None,
        # PCS lists who it tracks, at true positions. That IS the field: there
        # is no mass-start tail to window, so FIELD_CAP does not apply.
        "rule": "pcs_field",
        "distance_km": km,
        "discipline": GRAVEL[race_slug].discipline,
        "rank_type": "gun",
        "field_size_source": len(rows),
        "field_size_men": len(rows),
        "field_size_selected": len(rows),
        "truncated": False,
        "kept_beyond_cap": [],
        "pcs_pro_riders": pro,
        "pcs_national_only": len(rows) - pro,
        "last_rank": max(ranks) if ranks else None,
        "teams_named": sum(1 for r in rows if r["team_slug"]),
        "source_url": url,
        "api_url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return {"info": info, "cancelled": False, "rows": rows}


def main(argv=None):
    exit_on_help(__doc__, argv)
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", default="traka", help="gravel slug (default: traka)")
    ap.add_argument("--year", type=int)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    map_path = os.path.join(SCRAPES, "_traka_events.json")
    with open(map_path, encoding="utf-8") as f:
        events = json.load(f)
    out_dir = os.path.join(SCRAPES, args.race)
    os.makedirs(out_dir, exist_ok=True)

    written = 0
    for year in sorted(events, key=int):
        rec = events[year]
        if rec.get("source") != "pcs" or (args.year and int(year) != args.year):
            continue
        data = scrape_year(args.race, rec["pcs_slug"], int(year), force=args.force)
        if data is None:
            print(f"  {year}  no PCS result page")
            continue
        data["info"]["date"] = rec.get("date")
        if data["info"]["distance_km"] is None:
            data["info"]["distance_km"] = rec.get("distance_km")
        with open(os.path.join(out_dir, f"{year}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        i = data["info"]
        win = next((r["name"] for r in data["rows"] if r["rank"] == 1), "?")
        print(f"  {year}  pcs   rows={i['field_size_men']:<4} pro={i['pcs_pro_riders']:<4} "
              f"national={i['pcs_national_only']:<3} last_rank={i['last_rank'] or '-':<5} "
              f"teams={i['teams_named']:<3} km={i['distance_km']}  winner={win}")
        written += 1
    print(f"\nwrote {written} file(s) to {os.path.relpath(out_dir, HERE)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
