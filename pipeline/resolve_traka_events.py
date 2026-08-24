#!/usr/bin/env python3
"""Decide, once and visibly, which event IS "The Traka 360" in each year.

Same job as resolve_gravel_courses.py does for the Life Time races, and it
exists for the same reason: the answer is a judgement call, and a judgement
call made silently inside a scrape loop is one nobody can check.

The judgement is harder here than on Athlinks, because two things move:

  * The course NAME drifts every single year — 360K (2021), THE TRAKA 360
    (2022, 2023, 2024), 360 K (2025), 360 PRO M (2026). Matching on a fixed
    string would silently return nothing, and "no results" looks exactly like
    "race not held".
  * The DISTANCE moved too. 2026's "360" is 325 km. A km band tight enough to
    exclude the 200 would have excluded the 2026 race itself.

So the rule is: among a year's events, take those whose name starts with a
360 token, then prefer an explicitly men's one (2026 splits into PRO M / PRO W
/ OPEN and only PRO M is wanted). Everything the rule saw is written to the map
beside what it chose, so a wrong pick is visible rather than inferred.

The Traka also runs 50/60/100/200/560 km events on the same weekend. Those are
DIFFERENT RACES, not other classes of this one, and none of them is here.

The 360 distance did not exist before 2021: 2019 was a two-stage race and 2020
ran 50/100/200 only. Those editions are recorded with a skip reason rather than
omitted, so the gap stays explained.

Usage:
  python3 resolve_traka_events.py            # resolve + write the map
  python3 resolve_traka_events.py --report   # re-read the saved map, offline
  python3 resolve_traka_events.py --force    # ignore the raw cache, refetch
"""
import argparse
import json
import os
import re
import sys

from race_common import (GRAVEL, SOURCE_PCS, SOURCE_SPORTMANIACS,
                         SOURCE_TRETZESPORTS, exit_on_help)
import scrape_pcs_gravel as pcs
import traka_api as api

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(HERE, "gravel_scrapes", "_traka_events.json")

# tretzesports has no searchable index, so its editions are addressed by the
# ids The Traka's own results page links. Listed with every distance that year
# ran, not just the 360, so the skip reasons below can be stated from evidence.
TRETZE_IDS = [827, 835, 901, 903, 904, 906, 996, 997, 998,
              1051, 1052, 1062, 1075, 1316, 1317, 1318]

# PCS files gravel under `national-race/`, a namespace its own search does not
# return — which is why an earlier pass concluded, wrongly and in writing, that
# PCS had nothing here. Probed by URL, it has 2023 onward, and it is the
# PREFERRED source for any year it covers: it publishes real rider/<slug> ids,
# so the crossover to a road career becomes an exact join instead of a name
# match, and it has 2025, which neither timer ever published.
PCS_SLUG = "the-traka-360"
PCS_YEARS = range(2023, 2027)

# A name is a 360 if it opens with that number, with the race name optionally
# in front. Anchored at the start so "THE TRAKA 100" cannot match on a stray
# 360 later in the string. Two details both cost a silent miss when wrong:
# "THE" is optional (2021 tretzesports calls it "TRAKA 360"), and there is no
# \b after the digits ("360K" has no word boundary between 0 and K).
IS_360 = re.compile(r"^(?:the\s+)?(?:traka\s+)?360(?!\d)", re.I)
# 2026 split the 360 by class. Only the men's pro race is wanted.
IS_MENS = re.compile(r"\b(PRO\s*M|M)\b")
IS_WOMENS = re.compile(r"\b(PRO\s*W|W|F)\b")


def pick_360(events):
    """(chosen, [candidates], rule) from one year's events. chosen may be None.

    `rule` is the same vocabulary resolve_gravel_courses.py uses, because
    scrape_traka.py applies the same FIELD_CAP window the Athlinks scraper
    does and the rule is what decides whether it applies at all:

      elite_course   the edition ran a separate top-level men's race, and that
                     race IS the field. Keep every finisher. The Traka 2026
                     splits into 360 PRO M / PRO W / OPEN, so PRO M is one.
      open_field     no pro class existed — the whole 360 started together,
                     which is every edition through 2024. There is no line in
                     the data between elite and everyone else, so the scraper
                     takes the documented top-N window rather than inventing
                     one, exactly as it does for Leadville through 2015.
    """
    cands = [e for e in events if IS_360.match((e.get("name") or "").strip())]
    if not cands:
        return None, [], None
    if len(cands) == 1:
        # One 360 on the programme: everybody who rode it rode the same race.
        return cands[0], cands, "open_field"
    # 2026: PRO M / PRO W / OPEN. Take the men's pro race; never a women's one.
    mens = [e for e in cands
            if IS_MENS.search(e["name"].upper()) and not IS_WOMENS.search(e["name"].upper())]
    if len(mens) == 1:
        return mens[0], cands, "elite_course"
    return None, cands, None


def resolve_pcs(force=False):
    """Every year PCS holds, which outranks whatever a timer has for it."""
    out = {}
    for year in PCS_YEARS:
        data = pcs.scrape_year("traka", PCS_SLUG, year, force=force)
        if data is None:
            continue
        i, rows = data["info"], data["rows"]
        out[str(year)] = {
            "source": SOURCE_PCS,
            "pcs_slug": PCS_SLUG,
            "event_id": i["event_id"],
            "event_name": f"The Traka 360 ({year})",
            "rule": "pcs_field",
            "distance_km": i["distance_km"],
            "date": None,
            "city": "Girona",
            "n_rows": len(rows),
            "n_men": len(rows),
            "pcs_pro_riders": i["pcs_pro_riders"],
            "pcs_national_only": i["pcs_national_only"],
            "last_rank": i["last_rank"],
        }
    return out


def resolve_sportmaniacs(force=False):
    """Every Traka edition sportmaniacs holds, keyed by year."""
    out = {}
    index = api.sm_race_index(force=force)
    slugs = sorted({r["key"] for r in index
                    if re.match(r"^the-traka(-|$)", r.get("key", ""))})
    for slug in slugs:
        race = api.sm_race(slug, force=force)
        if not race or not race.get("date"):
            continue
        year = int(race["date"][:4])
        events = api.sm_events(race["id"], force=force)
        chosen, cands, rule = pick_360(events)
        rec = {
            "source": SOURCE_SPORTMANIACS,
            "race_slug": slug,
            "race_id": race["id"],
            "date": race["date"],
            "city": race.get("city"),
            "candidates": [{"id": e["id"], "name": e["name"],
                            "distance": e.get("distance")} for e in events],
        }
        if not chosen:
            rec["skip"] = ("no 360 event in this edition" if not cands
                           else f"{len(cands)} 360 events and no single men's one")
        else:
            rank = api.sm_rankings(chosen["id"], force=force)
            rows = rank.get("Rankings") or []
            men = [r for r in rows if r.get("gender") == "gender_0"]
            rec.update({
                "event_id": chosen["id"],
                "event_name": chosen["name"],
                "rule": rule,
                "distance_km": _km(chosen.get("distance")),
                "n_rows": len(rows),
                "n_men": len(men),
            })
            if not rows:
                # The event exists and the race was held; the timer simply has
                # not published it. Recorded, never inferred away.
                rec["skip"] = "event exists but publishes no rankings"
        # 2021 is present in BOTH systems — sportmaniacs holds an empty "360K"
        # stub for it. The merge in main() is what decides; this just reports
        # what sportmaniacs has.
        out[str(year)] = rec
    return out


def resolve_tretzesports(force=False):
    """The 2021/2022 editions, from the ids The Traka's results page links."""
    by_year = {}
    for cid in TRETZE_IDS:
        race = api.tz_race(cid, force=force)
        if not race or not race.get("data"):
            continue
        year = int(str(race["data"])[:4])
        by_year.setdefault(year, []).append(
            {"id": cid, "name": (race.get("nom") or "").strip(),
             "date": race["data"]})
    out = {}
    for year, events in sorted(by_year.items()):
        chosen, cands, rule = pick_360(events)
        rec = {
            "source": SOURCE_TRETZESPORTS,
            "date": events[0]["date"],
            "city": "Girona",
            "candidates": [{"id": e["id"], "name": e["name"]} for e in events],
        }
        if not chosen:
            rec["skip"] = ("no 360 event in this edition" if not cands
                           else f"{len(cands)} 360 events and no single men's one")
        else:
            rows = api.tz_results(chosen["id"], force=force)
            men = [r for r in rows if r.get("Sexe") == "Home"]
            rec.update({
                "event_id": chosen["id"],
                "event_name": chosen["name"],
                "rule": rule,
                "distance_km": 360.0,
                "n_rows": len(rows),
                "n_men": len(men),
            })
        out[str(year)] = rec
    return out


def _km(distance):
    """'360km' -> 360.0. None when the source does not say."""
    if not distance:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", str(distance))
    return float(m.group(1)) if m else None


def _usable(rec):
    return bool(rec and rec.get("event_id") and not rec.get("skip"))


def report(data):
    print(f"\n=== {GRAVEL['traka'].name}   (Girona, Spain)")
    print(f"{'year':<6}{'source':<14}{'event':<22}{'rule':<14}"
          f"{'km':>5}{'rows':>7}{'men':>6}  note")
    for year in sorted(data):
        r = data[year]
        if "event_id" not in r or r.get("skip"):
            note = r.get("skip", "")
            print(f"{year:<6}{r['source']:<14}{r.get('event_name','—'):<22}"
                  f"{'':<14}{'':>5}{'':>7}{'':>6}  SKIP: {note}")
            continue
        extra = ""
        if r["source"] == "pcs":
            extra = (f"  pro={r['pcs_pro_riders']} national={r['pcs_national_only']}"
                     f" last_rank={r['last_rank']}")
        seen = r.get("also_seen") or []
        if seen:
            extra += "  (also: " + ", ".join(
                f"{x['source']} {x.get('n_men') or x.get('skip')}" for x in seen) + ")"
        print(f"{year:<6}{r['source']:<14}{r['event_name']:<22}{r['rule']:<14}"
              f"{r['distance_km'] or 0:>5.0f}{r['n_rows']:>7}{r['n_men']:>6}{extra}")
    usable = [y for y, r in data.items() if r.get("event_id") and not r.get("skip")]
    print(f"\n{len(usable)} usable race-year(s): {', '.join(sorted(usable))}")
    print(f"{sum(data[y]['n_men'] for y in usable)} men's results")


def main(argv=None):
    exit_on_help(__doc__, argv)
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true",
                    help="print the saved map without fetching anything")
    ap.add_argument("--force", action="store_true",
                    help="ignore the raw cache and refetch")
    args = ap.parse_args(argv)

    if args.report:
        if not os.path.exists(MAP_PATH):
            print(f"no map at {MAP_PATH} — run without --report first")
            return 1
        with open(MAP_PATH, encoding="utf-8") as f:
            report(json.load(f))
        return 0

    data = resolve_tretzesports(force=args.force)
    sm = resolve_sportmaniacs(force=args.force)
    # The timers are consulted first so their record is visible in the map, but
    # PCS wins every year it covers — see PCS_YEARS. The timer's own reading is
    # kept alongside as `also_seen`, which is what makes the two comparable at
    # a glance rather than one silently replacing the other.
    for year, rec in sm.items():
        # 2021 exists in BOTH systems: tretzesports has the real 72-man field
        # and sportmaniacs has an empty stub. A record that resolved to actual
        # results always wins, whichever platform it came from — otherwise
        # merge order silently decides which edition the archive keeps.
        old = data.get(year)
        if _usable(old) and not _usable(rec):
            old.setdefault("also_seen", []).append(
                {"source": rec["source"], "skip": rec.get("skip")})
            continue
        data[year] = rec
    for year, rec in resolve_pcs(force=args.force).items():
        prev = data.get(year)
        if prev:
            rec["date"] = rec["date"] or prev.get("date")
            rec["also_seen"] = (prev.get("also_seen") or []) + [{
                "source": prev["source"], "event_name": prev.get("event_name"),
                "n_men": prev.get("n_men"), "skip": prev.get("skip")}]
        data[year] = rec
    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    report(data)
    print(f"\nwrote {MAP_PATH} — READ IT before scraping")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
