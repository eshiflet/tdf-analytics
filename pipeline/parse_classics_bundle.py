#!/usr/bin/env python3
"""Split the browser-captured classics bundle into per-race scrape JSON.

The bundle is what the DevTools snippet downloads: one file holding every
race x year it fetched, in blocks of

    ##RACE <race-slug> <year>
    ##INFO Key=Value~Key=Value...
    ##H1 <page headline>
    ##TEAMS team/<slug>=<name>~...
    ##ROWS
    rnk|bib|age|name|slug|nat|teamIdx|uci|pnt|time     (one line per rider)

A cancelled/absent race has ##NORESULTS instead of ##TEAMS/##ROWS, and a
fetch failure has ##ERROR. Both are recorded rather than dropped — a race
that did not happen is a fact about the season, not missing data.

Output: classics_scrapes/<race>/<year>.json, shaped like the Giro/Vuelta
stage scrapes so ingest can consume it:
  {"info": {...}, "cancelled": bool, "rows": [[15 fields], ...]}
with rows in race_common.StageRow field order.

Time semantics follow ai-context.md rule 2: PCS puts the absolute time and
the gap in ONE cell, so only rank 1 carries abs_time and everyone else's
value is a gap. `winner + gap` applied to every row is what once doubled
3,377 winning times.

Usage:  python3 parse_classics_bundle.py ~/Downloads/classics_2020_2025.txt
"""
import datetime
import json
import os
import re
import sys

from race_common import CLASSICS

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.join(HERE, "classics_scrapes")
# Compared against each race's date to tell "not run yet" from "cancelled".
TODAY = datetime.date.today().isoformat()
STAGE_ROW_LEN = 15

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def norm_date(raw):
    """'03 October 2021' -> '2021-10-03'. Returns None if unparseable."""
    if not raw:
        return None
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", raw.strip())
    if not m:
        return None
    d, mon, y = m.groups()
    if mon not in MONTHS:
        return None
    return f"{y}-{MONTHS[mon]:02d}-{int(d):02d}"


def num(raw):
    """Leading number out of '257.7 km' / '1304'. None if absent or bogus.

    PCS leaves these blank on a cancelled race's page, where the innerText
    regex in the capture snippet can slurp the NEXT field's label instead
    (e.g. 'Vertical meters=Departure: Compiegne'). Anything that isn't a
    clean leading number is therefore treated as missing, not guessed at.
    """
    if not raw:
        return None
    m = re.match(r"\s*([\d.]+)", raw)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    # A blank PCS field renders as "0 km" / "0", and a stored 0 is worse than a
    # NULL: it reads as real data and skews any average built over it. No race
    # has zero distance or zero climbing (the 2004 Omloop's cancelled page
    # reports "Distance: 0 km"). Cf. the 2006 Paris finale that carried
    # vertical_meters=0 / profile_score=0 for exactly this reason.
    return v if v > 0 else None


def parse_blocks(text):
    blocks, cur = [], None
    for line in text.split("\n"):
        if line.startswith("##RACE "):
            if cur:
                blocks.append(cur)
            _, race, year = line.split(None, 2)
            cur = {"race": race, "year": int(year), "info": {}, "h1": "",
                   "teams": [], "team_names": {}, "rows": [],
                   "noresults": False, "error": None}
        elif cur is None:
            continue
        elif line.startswith("##INFO "):
            for pair in line[len("##INFO "):].split("~"):
                if "=" in pair:
                    k, _, v = pair.partition("=")
                    cur["info"][k.strip()] = v.strip()
        elif line.startswith("##H1 "):
            cur["h1"] = line[len("##H1 "):].strip()
        elif line.startswith("##TEAMS "):
            for pair in line[len("##TEAMS "):].split("~"):
                if "=" in pair:
                    slug, _, name = pair.partition("=")
                    cur["teams"].append(slug.strip())
                    cur["team_names"][slug.strip()] = name.strip()
        elif line.startswith("##NORESULTS"):
            cur["noresults"] = True
        elif line.startswith("##ERROR"):
            cur["error"] = line[len("##ERROR"):].strip()
        elif line.startswith("##ROWS"):
            cur["_in_rows"] = True
        elif cur.get("_in_rows"):
            # A row can span several physical lines: PCS renders a UCI-points
            # DEDUCTION inside the points cell (Paris-Roubaix 2023, Rex
            # Laurenz: "160 ... -25"), and innerText keeps the embedded
            # newlines/tabs. Keep appending until the accumulated line has all
            # 10 fields rather than dropping the rider.
            if not line.strip() and not cur.get("_pending"):
                continue
            pending = cur.pop("_pending", "")
            joined = (pending + " " + line) if pending else line
            if joined.count("|") < 9:
                cur["_pending"] = joined
            else:
                cur["rows"].append(re.sub(r"\s+", " ", joined).strip())
    if cur:
        cur.pop("_pending", None)
        blocks.append(cur)
    return blocks


def to_stage_rows(block):
    out = []
    for line in block["rows"]:
        f = line.split("|")
        if len(f) != 10:
            raise ValueError(
                f"{block['race']} {block['year']}: expected 10 capture "
                f"fields, got {len(f)}: {line!r}")
        rnk, bib, age, name, slug, nat, tidx, uci, pnt, time = f
        team_slug = team_name = ""
        if tidx not in ("", "-1"):
            team_slug = block["teams"][int(tidx)]
            team_name = block["team_names"][team_slug]
        abs_time = time if rnk == "1" else ""
        row = [rnk, "", "", bib, age, name, slug, nat,
               team_name, team_slug, uci, pnt, "", abs_time, time]
        if len(row) != STAGE_ROW_LEN:
            raise ValueError(f"row is not {STAGE_ROW_LEN} fields: {row!r}")
        out.append(row)
    return out


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 1
    with open(argv[1], encoding="utf-8") as f:
        blocks = parse_blocks(f.read())

    summary, problems = [], []
    for b in blocks:
        # An unrecognised slug is almost always a wrong guess at a PCS URL, and
        # a wrong URL 500s -> no results table -> looks exactly like a cancelled
        # race. Refusing to write it is what stops six invented San Sebastian
        # cancellations from reaching the DB a second time.
        if b["race"] not in CLASSICS:
            problems.append(
                f"{b['race']} {b['year']}: UNKNOWN SLUG — not in race_common.CLASSICS, "
                f"skipped. Check the real PCS URL before adding it.")
            continue
        info = b["info"]
        # A page with no results table means one of THREE different things, and
        # only the date and the HTTP status tell them apart:
        #   - HTTP 500        -> the edition never existed (handled above)
        #   - 200, past date  -> genuinely cancelled (Omloop 1986, Roubaix 2020)
        #   - 200, future date-> simply not run yet (Il Lombardia in an in-progress
        #                        season), which must NOT be stored as a cancellation
        # Skipping the last one also keeps it out of the season's race list until
        # it actually happens, instead of showing an empty column all year.
        parsed_date = norm_date(info.get("Date"))
        if b["noresults"] and parsed_date and parsed_date > TODAY:
            problems.append(
                f"{b['race']} {b['year']}: not run yet (scheduled {parsed_date}) — "
                f"skipped, NOT recorded as cancelled")
            continue

        payload = {
            "info": {
                "race_slug": b["race"],
                "year": b["year"],
                "date": norm_date(info.get("Date")),
                "distance_km": num(info.get("Distance")),
                "vertical_meters": num(info.get("Vertical meters")),
                "profile_score": num(info.get("ProfileScore")),
                "start_location": info.get("Departure") or None,
                "finish_location": info.get("Arrival") or None,
                "won_how": info.get("Won how") if info.get("Won how") not in ("-", "") else None,
                "edition_name": b["h1"] or None,
                "source_slug": f"race/{b['race']}/{b['year']}/result",
            },
            "cancelled": bool(b["noresults"]),
            "rows": [] if b["noresults"] else to_stage_rows(b),
        }
        if b["error"]:
            problems.append(f"{b['race']} {b['year']}: ERROR {b['error']}")
            continue

        out_dir = os.path.join(OUT_ROOT, b["race"])
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, f"{b['year']}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

        rows = payload["rows"]
        fin = [r for r in rows if r[0].isdigit()]
        # Looking for the PCS adjacent-row name-swap artifact (see
        # detect_name_swaps.py). The signature is a bib mapping to two riders
        # ON THE SAME TEAM — bib uniqueness across the whole race is NOT an
        # invariant here: several editions number riders per-team, so two
        # squads legitimately share 11-17 (Flanders 2010: AG2R and Liquigas,
        # every rider correctly attached to their own team). Checking global
        # uniqueness flagged 8 whole-team blocks of pure noise, which is
        # exactly how a real swap would go unnoticed.
        seen, conflicts = {}, []
        for r in rows:
            bib, rider, team = r[3], r[6], r[9]
            if not bib:
                continue
            key = (team, bib)
            if key in seen and seen[key] != rider:
                conflicts.append(f"{bib}@{team or '?'}")
            seen[key] = rider
        ranks = [int(r[0]) for r in fin]
        dupes = sorted({x for x in ranks if ranks.count(x) > 1})

        if payload["cancelled"]:
            summary.append(f"  {b['race']:<24} {b['year']}  CANCELLED  "
                           f"date={payload['info']['date']}")
        else:
            summary.append(
                f"  {b['race']:<24} {b['year']}  {len(rows):>3} rows "
                f"({len(fin):>3} fin)  {payload['info']['date']}  "
                f"{payload['info']['distance_km']}km "
                f"{payload['info']['vertical_meters']}m")
        if conflicts:
            problems.append(f"{b['race']} {b['year']}: BIB CONFLICTS {conflicts}")
        if dupes:
            problems.append(f"{b['race']} {b['year']}: duplicate ranks {dupes}")
        if not payload["cancelled"] and not payload["info"]["date"]:
            problems.append(f"{b['race']} {b['year']}: NO DATE")

    print(f"parsed {len(blocks)} race-years\n")
    print("\n".join(summary))
    print(f"\n--- flags ({len(problems)}) ---")
    print("\n".join(problems) if problems else "  none")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
