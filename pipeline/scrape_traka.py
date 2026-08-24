#!/usr/bin/env python3
"""Turn the resolved Traka events into gravel_scrapes/traka/<year>.json.

Writes the SAME file shape scrape_athlinks.py writes, so everything downstream
— link_gravel_riders.py, ingest_gravel.py, export_gravel.py — works on this
race without knowing it came from somewhere else. The two upstreams are
normalised here and nowhere else.

Men's fields only, matching the rest of the gravel archive: `riders` has no
gender column, so a mixed field would silently merge two competitions. The
rank stored is the rank WITHIN the men's field, which is what the source's own
men's view shows; the overall mixed-field position is kept beside it as
`rank_overall` rather than thrown away.

The same FIELD_CAP window the Athlinks scraper applies applies here, for the
same reason and by the same rule. Through 2024 The Traka 360 was one open
mass start — 737 men finished the 2024 edition — with no pro class to draw a
line at, so `open_field` takes the documented top 100 of the classified field.
2026 split into 360 PRO M / PRO W / OPEN, which IS the sport drawing that line
itself, so `elite_course` keeps all 135. `field_size_men` records the true
size beside the window, so the window stays visible as a window.

Three upstream traps, each of which would corrupt the archive silently:

1. **A sportmaniacs non-finisher carries `officialTime: "00:00:00"`** with an
   empty position. Parsed naively that is a finish time of zero seconds, which
   sorts ahead of the winner. 180 of 2024's 737 men are in this state.
2. **tretzesports puts "DNF"/"DNS" in the time field itself**, and gives those
   rows `PosicioSexe: "-1"`. Both must become a status, never a rank or a time.
3. **`nationality` arrives in four different formats** across five editions —
   Spanish names (2023), ISO-2 (2024), ISO-3 (2026), and a few English names
   and typos. They are mapped through an explicit reviewed table below;
   anything not in it stays NULL, because a wrong flag is a claim and a missing
   one is a gap.

Usage:
  python3 scrape_traka.py                 # every resolved year
  python3 scrape_traka.py --year 2024
  python3 scrape_traka.py --force         # refetch instead of using the cache
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

from race_common import (
    GRAVEL,
    SOURCE_SPORTMANIACS,
    SOURCE_TRETZESPORTS,
    exit_on_help,
)
from scrape_athlinks import FIELD_CAP, clean_name, split_name
import traka_api as api

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES = os.path.join(HERE, "gravel_scrapes")
MAP_PATH = os.path.join(SCRAPES, "_traka_events.json")
OUT_DIR = os.path.join(SCRAPES, "traka")

# Every nationality string these five editions actually contain, mapped to
# lowercase ISO-2. Written out rather than computed because the source mixes
# languages and formats, and a fuzzy matcher here would quietly invent flags.
# Anything absent from this table stays NULL and is reported by --report.
COUNTRY = {
    # ISO-3 (2026)
    "AUS": "au", "AUT": "at", "BEL": "be", "CAN": "ca", "COL": "co",
    "CZE": "cz", "DEU": "de", "DNK": "dk", "ESP": "es", "FRA": "fr",
    "GBR": "gb", "IRL": "ie", "ISL": "is", "ITA": "it", "LTU": "lt",
    "NLD": "nl", "NOR": "no", "NZL": "nz", "POL": "pl", "PRT": "pt",
    "SWE": "se", "USA": "us", "ZAF": "za",
    # Spanish names (2023)
    "ALEMANIA": "de", "AUSTRALIA": "au", "BRASIL": "br", "BÉLGICA": "be",
    "CANADÁ": "ca", "COLOMBIA": "co", "COSTA RICA": "cr", "DINAMARCA": "dk",
    "ESLOVAQUIA": "sk", "ESPAÑA": "es", "ESTADOS UNIDOS (EE.UU)": "us",
    "FRANCIA": "fr", "IRLANDA": "ie", "ITALIA": "it", "KENYA": "ke",
    "LITUANIA": "lt", "LUXEMBURGO": "lu", "MÉXICO": "mx", "NAMIBIA": "na",
    "NORUEGA": "no", "NUEVA ZELANDA": "nz", "PAÍSES BAJOS": "nl",
    "POLONIA": "pl", "PORTUGAL": "pt", "REINO UNIDO": "gb", "RUSIA": "ru",
    "SERBIA": "rs", "SUDÁFRICA, REPÚBLICA DE": "za", "SUIZA": "ch",
    # English names and one upstream typo (2024)
    "AUSTRIA": "at", "BELGIUM": "be", "CANADA": "ca", "FRANCE": "fr",
    "GERMANY": "de", "ITALY": "it", "MEXICO": "mx", "NETHERLANDS": "nl",
    "SPAIN": "es", "UNITED KINGDOM": "gb", "UNITES STATES (US)": "us",
    # ISO-2 that is not ISO: the UK's exceptionally-reserved alias.
    "UK": "gb",
}
# Deliberately NOT mapped: "UM" (US Minor Outlying Islands). It is a real ISO-2
# code, so it cannot be dismissed as junk, but on a Girona start list it is far
# more likely a picker mis-selection than a claim about the rider. One row.


def to_seconds(text):
    """'11:42:23' -> 42143. None for a non-time or a zero-length one.

    "00:00:00" is what a sportmaniacs DNF carries, and it must never come back
    as 0 — a zero finish time sorts ahead of the winner.
    """
    if not text or not re.fullmatch(r"\d+:\d\d:\d\d", str(text).strip()):
        return None
    h, m, s = (int(x) for x in str(text).strip().split(":"))
    total = h * 3600 + m * 60 + s
    return total or None


def country_of(raw):
    if not raw:
        return None
    key = str(raw).strip()
    if not key:
        return None
    hit = COUNTRY.get(key.upper())
    if hit:
        return hit
    # A bare two-letter code the table does not list is still ISO-2; the
    # countries table takes it and names it after itself.
    if len(key) == 2 and key.isalpha() and key.upper() != "UM":
        return key.lower()
    return None


def _row(name, bib, rank, rank_overall, seconds, status, country, club, category):
    clean = clean_name(name)
    first, last = split_name(clean)
    return {
        "rank": rank,
        "name": clean,
        "first_name": first,
        "last_name": last,
        "bib": str(bib or "").strip() or None,
        "age": None,              # neither source publishes age or birth year
        "gender": "M",
        "country": country,
        "club": club or None,     # real per-edition attribution; see ingest note
        "category": category or None,
        "finish_seconds": seconds,
        "status": status,
        "rank_overall": rank_overall,
        "gap_seconds": None,      # filled once the winner is known
    }


def rows_sportmaniacs(event_id, force=False):
    data = api.sm_rankings(event_id, force=force)
    out = []
    for r in data.get("Rankings") or []:
        if r.get("gender") != "gender_0":
            continue          # men's field only
        finished = bool(r.get("finishedRace"))
        seconds = to_seconds(r.get("officialTime")) if finished else None
        pos = str(r.get("genPos") or "")
        overall = str(r.get("pos") or "")
        out.append(_row(
            r.get("name"), r.get("dorsal"),
            int(pos) if pos.isdigit() else None,
            int(overall) if overall.isdigit() else None,
            seconds,
            "FINISHED" if (finished and seconds) else "DNF",
            country_of(r.get("nationality")),
            (r.get("club") or "").strip(),
            r.get("category"),
        ))
    return out, len(data.get("Rankings") or [])


def rows_tretzesports(cursa_id, force=False):
    raw = api.tz_results(cursa_id, force=force)
    out = []
    for r in raw:
        if r.get("Sexe") != "Home":
            continue          # men's field only
        temps = (r.get("Temps") or "").strip()
        seconds = to_seconds(temps)
        pos = str(r.get("PosicioSexe") or "")
        overall = str(r.get("Posicio") or "")
        status = "FINISHED" if seconds else (
            temps.upper() if temps.upper() in ("DNF", "DNS") else "DNF")
        out.append(_row(
            r.get("Nom"), r.get("Dorsal"),
            int(pos) if pos.isdigit() and int(pos) > 0 else None,
            int(overall) if overall.isdigit() and int(overall) > 0 else None,
            seconds, status,
            None,             # tretzesports publishes no nationality at all
            (r.get("Club") or "").strip(),
            r.get("Categoria"),
        ))
    return out, len(raw)


# Riders kept beyond the FIELD_CAP window by explicit decision (Eric, 2026-08-24),
# in the spirit of fix_tt_route_types.ADJUDICATED_NOT_TT: a named list of calls a
# person made, not a rule the scraper inferred.
#
# The window exists because a mass-start field has no line between elite and
# everyone else. That is true of the field as a whole and still leaves specific
# riders it is worth making an exception for — a road professional whose gravel
# ride is exactly the crossover this archive exists to show. Keeping them costs
# three rows and does not move anyone else's rank: an exception keeps its REAL
# finishing position, so Basso is stored 103rd in a field of 100 rather than
# renumbered into it. That is the honest way to say "he finished 103rd".
#
# Keep this short. Every addition makes "top 100" less true as a description,
# and the count is reported per edition so it stays visible.
KEEP_BEYOND_CAP = {
    ("Leonardo Basso", 2023): "Italian road pro (Strade Bianche, Roubaix, Flanders); 139th",
    ("Leonardo Basso", 2024): "same rider, 103rd — three places outside the cap",
    ("Jeremy Hunt", 2024): "British road pro (Tour, Giro, Vuelta, 11 Roubaix); DNF, "
                           "so never in the window at all rather than just outside it",
}


def apply_field_rule(rows, rule, year=None):
    """The edition's field, windowed per its rule. Mirrors select_field().

    Sorted finishers-first in classification order, then the unranked — which
    is the order FIELD_CAP windows over, so it has to be right before the cut.

      open_field    no pro class existed; the whole 360 started together, so
                    any line between "elite" and "everyone else" is ours and
                    not the sport's. Take the same documented top-N window the
                    Athlinks scraper takes for Leadville through 2015. 737 men
                    finished the 2024 Traka 360, and keeping all of them would
                    make one edition a third of the off-road archive under a
                    rule no Life Time edition gets.
      elite_course  2026 split into 360 PRO M / PRO W / OPEN. That IS the sport
                    drawing the line, so the whole field is kept.

    The window is over the CLASSIFIED field: an unranked rider has no claim on
    a top-100 place, and because DNFs sort last they are never what fills the
    cap.
    """
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["name"]))
    if rule != "open_field":
        return rows
    kept, cut = rows[:FIELD_CAP], rows[FIELD_CAP:]
    # Re-attach the named exceptions, in their own finishing order after the
    # window. They are appended rather than merged so the first FIELD_CAP rows
    # remain exactly the window, whatever else is in the file.
    kept += [r for r in cut if (r["name"], year) in KEEP_BEYOND_CAP]
    return kept


def add_gaps(rows):
    """Gap to the men's winner. Only finishers get one."""
    winner = next((r["finish_seconds"] for r in sorted(
        (x for x in rows if x["rank"] and x["finish_seconds"]),
        key=lambda x: x["rank"])), None)
    for r in rows:
        if winner and r["finish_seconds"]:
            r["gap_seconds"] = r["finish_seconds"] - winner
    return winner


def scrape_year(year, rec, force=False):
    if rec.get("skip") or not rec.get("event_id"):
        return None
    rule = rec.get("rule")
    if rec["source"] == SOURCE_SPORTMANIACS:
        rows, n_source = rows_sportmaniacs(rec["event_id"], force=force)
        source_url = (f"https://sportmaniacs.com/es/races/{rec['race_slug']}/"
                      f"{rec['event_id']}/results")
        api_url = f"https://sportmaniacs.com/es/races/rankings/{rec['event_id']}"
    elif rec["source"] == SOURCE_TRETZESPORTS:
        rows, n_source = rows_tretzesports(rec["event_id"], force=force)
        source_url = ("https://tretzesports.com/curses3/resultats/curses/#/cursa/"
                      f"{rec['event_id']}")
        api_url = ("https://tretzesports.com/curses3/backend/code/api/"
                   f"getResultats.php?idCursa={rec['event_id']}")
    else:
        raise ValueError(f"{year}: unknown source {rec['source']!r}")

    # Finishers first in classification order, then the unranked. This is the
    # order FIELD_CAP windows over, so it has to be right before the cut.
    n_men = len(rows)
    rows = apply_field_rule(rows, rule, year)
    add_gaps(rows)
    finishers = sum(1 for r in rows if r["status"] == "FINISHED")
    no_country = sum(1 for r in rows if not r["country"])

    info = {
        "race_slug": "traka",
        "year": year,
        "date": rec["date"],
        "source": rec["source"],
        "event_id": rec["event_id"],
        "event_name": rec["event_name"],
        "course_id": None,
        "rule": rule,
        "distance_km": rec.get("distance_km"),
        "discipline": GRAVEL["traka"].discipline,
        "rank_type": "gun",
        "field_size_source": n_source,
        "field_size_men": n_men,
        "field_size_selected": len(rows),
        "truncated": rule == "open_field" and len(rows) >= FIELD_CAP,
        "kept_beyond_cap": sorted(r["name"] for r in rows
                                  if (r["name"], year) in KEEP_BEYOND_CAP),
        "finishers": finishers,
        "no_country": no_country,
        "source_url": source_url,
        "api_url": api_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return {"info": info, "cancelled": False, "rows": rows}


def main(argv=None):
    exit_on_help(__doc__, argv)
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    ap.add_argument("--force", action="store_true",
                    help="refetch instead of reading the raw cache")
    args = ap.parse_args(argv)

    if not os.path.exists(MAP_PATH):
        print("no _traka_events.json — run resolve_traka_events.py first")
        return 1
    with open(MAP_PATH, encoding="utf-8") as f:
        events = json.load(f)

    os.makedirs(OUT_DIR, exist_ok=True)
    written = 0
    for year in sorted(events, key=int):
        if args.year and int(year) != args.year:
            continue
        rec = events[year]
        data = scrape_year(int(year), rec, force=args.force)
        if data is None:
            print(f"  {year}  skipped — {rec.get('skip', 'no event resolved')}")
            continue
        path = os.path.join(OUT_DIR, f"{year}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        i = data["info"]
        winner = next((r for r in data["rows"] if r["rank"] == 1), None)
        print(f"  {year}  {i['source']:<14} {i['event_name']:<16} "
              f"{i['rule']:<13} men={i['field_size_men']:<4} "
              f"kept={i['field_size_selected']:<4} fin={i['finishers']:<4} "
              f"{'CAPPED' if i['truncated'] else '      '}"
              f"{'+' + str(len(i['kept_beyond_cap'])) if i['kept_beyond_cap'] else '  '} "
              f"winner={winner['name'] if winner else '?'}")
        written += 1
    print(f"\nwrote {written} file(s) to {os.path.relpath(OUT_DIR, HERE)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
