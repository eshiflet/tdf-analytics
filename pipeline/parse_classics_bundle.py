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
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.join(HERE, "classics_scrapes")
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
    return v


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
        info = b["info"]
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
        # A bib mapping to two different riders is the signature of the PCS
        # adjacent-row name-swap artifact (see detect_name_swaps.py).
        bibs, conflicts = {}, []
        for r in rows:
            if r[3] and r[3] in bibs and bibs[r[3]] != r[6]:
                conflicts.append(r[3])
            bibs[r[3]] = r[6]
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
