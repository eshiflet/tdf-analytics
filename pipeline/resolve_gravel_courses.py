#!/usr/bin/env python3
"""Resolve, for every edition of the six Life Time off-road races, WHICH
Athlinks course and division hold the top-level men's field.

Why this is a separate, checked-in step rather than a heuristic run inline at
scrape time: Athlinks addresses everything by numeric id and renames courses
constantly ("DK 200" -> "UNBOUND 200" -> "Elite Men - 200 MILE"; "Chequamegon
40" -> "Pro/Elite Chequamegon 40"), and a single edition can carry a dozen
courses of the same length that differ only by tandem/single-speed/relay. A
heuristic that silently picks the wrong one does not fail — it produces a
plausible, entirely fictional race. This is the same lesson as source_slug for
PCS: resolve once, write the answer down, review it, then fetch by id.

Output: gravel_scrapes/_course_map.json, plus a review table on stdout.

  {"leadville": {"2015": {"event_id":..., "course_id":..., "division_id":...,
                          "rule": "open_field", "distance_km":..., ...}}}

Three selection rules come out of this, and they are not interchangeable:

  elite_course     the edition ran a separate top-level men's race, and that
                   course IS the field. Keep every finisher.
  elite_division   one mass-start course, with the pro/elite class scored as a
                   division inside it. Keep that division's members.
  open_field       no pro class existed at all — the pros started with
                   everyone (Leadville through 2015, Dirty Kanza through 2021).
                   There is no line in the data between "elite" and "everyone
                   else", so the scraper takes a documented top-N window of the
                   men's results rather than inventing one.

Usage:
  python3 resolve_gravel_courses.py                # resolve all six
  python3 resolve_gravel_courses.py --race leadville
  python3 resolve_gravel_courses.py --report       # print the saved map, no
                                                   # network — this is the
                                                   # table to review
  python3 resolve_gravel_courses.py --no-probe     # skip the per-course
                                                   # results probe (fast, but
                                                   # cannot detect an EMPTY
                                                   # elite course — see below)
"""
import argparse
import json
import os
import re
import sys

from athlinks_api import editions, event_metadata, get_json, REIGNITE
from race_common import GRAVEL

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES = os.path.join(HERE, "gravel_scrapes")
MAP_PATH = os.path.join(SCRAPES, "_course_map.json")

# Courses that are the same distance as the real race but are a different
# contest. Left in, "Chequamegon 40 Tandem" looks exactly like "Chequamegon 40".
EXCLUDE_COURSE = re.compile(
    r"tandem|relay|half.?pint|single.?speed|singlespeed|fat.?bike|e-?bike|"
    r"coaching|lottery|kids?|junior|jr\b|trail run|\brun\b|swim|triathlon|"
    r"post registration|purchases|clydesdale|early start",
    re.I,
)

# Men's top-level divisions, most specific first. "Pro/Elite" outranks "Grand
# Prix": the Grand Prix is a 25-rider invitational inside the pro race, and the
# pro race is the field this archive is about — Vermeulen and Stetina show up
# in the former only some years, in the latter always.
MENS_DIVISIONS = [
    "pro/elite men", "pro/elite male", "elite/a men",
    "pro men", "pro male", "prom", "m pro", "m pro/open", "m pro open",
    "pro open men", "men pro", "elite men", "men elite", "elite male",
    "m elite", "grand prix men", "grand prix male",
]

# Per-race candidate filter for the headline course: (regex, km_low, km_high).
# The km band is the real guard — Athlinks course names are far too unstable to
# trust alone, and every one of these races has a nominal distance that has
# held for its whole history.
HEADLINE = {
    "leadville":    (re.compile(r"leadville|lt100|mountain.?bike|mt\.? ?bike|100 ?mi", re.I), 150, 180),
    "chequamegon":  (re.compile(r"chequamegon|40 ?mi|mountain.?bike", re.I), 58, 70),
    "unbound":      (re.compile(r"200|unbound|dk", re.I), 310, 340),
    "little-sugar": (re.compile(r"100 ?k", re.I), 90, 105),
    "big-sugar":    (re.compile(r"big sugar", re.I), 80, 175),
}

# Sea Otter is a week-long multi-discipline festival, not a race, and Athlinks
# models each discipline-day as its own EVENT with age groups as "courses".
# There is no single lineage to pattern-match, so the endurance race that is
# today's Grand Prix round is named outright, year by year, from the survey:
#
#   2022  Fuego XC 80k, "MEN OPEN"       (the 2022 Grand Prix opener)
#   2023  MTB Endurance - Fuego XL 67M   (not La Gravilla, the gravel race
#                                         held the same week)
#   2024  Fuego XL
#   2025  Sea Otter Gravel Men Elite/Pro (the round moved off-road-to-gravel)
#   2026  Sea Otter Gravel Men Elite
#
# Earlier Sea Otters are deliberately absent: before 2022 Athlinks holds only
# category-by-category XC results (Cat 1/2/3, no pro class) with no distances,
# and no endurance race of this lineage existed. Picking the Cat 1 XC race and
# calling it the same event would be a fabricated continuity.
SEA_OTTER = {
    2026: (1122437, 2675068),
    2025: (1090879, 2564948),
    2024: (1062752, 2407488),
    2023: (1023337, 2309089),
    2022: (1037852, 2313882),
}


# Editions where Athlinks' own labelling is wrong and no heuristic can save
# us. Each entry needs evidence written down, because an override is a claim
# made against the source.
#
# unbound 2016: the two course labels are SWAPPED. "200 Mile Cycling"
#   (321,869 m) holds 529 riders with a median finishing time of 9.5h and no
#   Ted King; "100 Mile Cycling" (161,900 m) holds 857 riders with a median of
#   15.8h and Ted King fastest. A 9.5h median over 200 miles of Flint Hills
#   gravel is not a fast year, it is a different race — and 15.8h is exactly
#   what the 200 looks like in every other edition. The distance is overridden
#   with the 321.87 km that every other Dirty Kanza edition carries.
OVERRIDES = {
    ("unbound", 2016): {"course_id": 840642, "distance_km": 321.87,
                        "note": "Athlinks has the 100/200 course labels swapped "
                                "for this edition; distance taken from every "
                                "other Dirty Kanza edition"},
}


def probe_count(event_id, course_id):
    """How many athletes that course actually holds.

    Needed because an edition can publish a correctly-named elite course that
    is EMPTY — Leadville 2025 has "Leadville 100 MTB - Elite Men" with zero
    athletes, while the real elite field sits in the mass-start course tagged
    with a division. Choosing on name alone yields an empty race there.
    """
    d = get_json(f"{REIGNITE}/event/{event_id}/race/{course_id}/results?from=0&limit=1")
    if not d:
        return None
    return (d.get("division") or {}).get("totalAthletes")


def mens_divisions(course):
    """EVERY top-level men's division on a course, in preference order.

    Plural because one race's pro field can be split across two of them:
    Leadville 2023 puts John Gaston in "Pro Male" and Keegan Swenson — who won
    it — in "Grand Prix Male", and neither division alone is the men's race.
    Taking only the first match published a 2023 Leadville with no winner.
    """
    divs = [d for d in (course.get("divisions") or []) if d.get("name")]
    out = []
    for want in MENS_DIVISIONS:
        for d in divs:
            if d["name"].strip().lower() == want:
                out.append({"id": d["id"], "name": d["name"]})
    return out


def is_mens_elite_course(name):
    low = (name or "").lower()
    if "women" in low or "female" in low:
        return False
    return bool(re.search(r"\belite\b|\bpro\b|pro/elite|men open", low))


def candidates(slug, meta):
    """Headline-course candidates for one edition, longest first."""
    pat, lo, hi = HEADLINE[slug]
    out = []
    for c in (meta or {}).get("races", []):
        name = c.get("name") or ""
        if EXCLUDE_COURSE.search(name):
            continue
        km = ((c.get("distance") or {}).get("meters") or 0) / 1000
        if not pat.search(name):
            continue
        # A 0 km course is unmeasured, not wrong — old editions have no
        # distance at all. Keep it if the name matches; the band can't judge it.
        if km and not (lo <= km <= hi):
            continue
        out.append({"course_id": c.get("id"), "name": name, "km": round(km, 2),
                    "divisions": c.get("divisions") or []})
    out.sort(key=lambda c: -c["km"])
    return out


def resolve_edition(slug, ev, probe=True):
    """One edition -> the chosen course/division, or a reason it was skipped."""
    meta = event_metadata(ev["event_id"])
    if not meta:
        return {"skip": "metadata unavailable"}

    by_id = {c.get("id"): c for c in meta.get("races", [])}

    if slug == "sea-otter":
        pick = SEA_OTTER.get(ev["year"])
        if not pick or pick[0] != ev["event_id"]:
            return {"skip": "not the endurance-race lineage (see SEA_OTTER)"}
        course = by_id.get(pick[1])
        if not course:
            return {"skip": f"mapped course {pick[1]} absent from event"}
        cands = [{"course_id": course.get("id"), "name": course.get("name") or "",
                  "km": round(((course.get("distance") or {}).get("meters") or 0) / 1000, 2),
                  "divisions": course.get("divisions") or []}]
    else:
        cands = candidates(slug, meta)
    if not cands:
        return {"skip": "no course matched the headline filter"}

    # An explicit men's elite course wins — but only if it has results.
    chosen, rule = None, None
    for c in cands:
        if is_mens_elite_course(c["name"]):
            n = probe_count(ev["event_id"], c["course_id"]) if probe else 1
            if n:
                chosen, rule = c, "elite_course"
                break
            c["empty"] = True     # kept in the map as evidence, not dropped

    if chosen is None:
        # Otherwise the mass-start course: the longest candidate that is not an
        # (empty) elite course and is not a women's race.
        main = [c for c in cands
                if not is_mens_elite_course(c["name"])
                and "women" not in c["name"].lower()]
        if not main:
            return {"skip": "only empty elite courses matched"}
        chosen = main[0]
        divs = mens_divisions(chosen)
        rule = "elite_division" if divs else "open_field"
        chosen["divisions_picked"] = divs

    # Even a dedicated elite course can be mixed-gender (Leadville 2022's
    # "LT100 Pro" holds Pro Male and Pro Female), so look for a men's division
    # inside it too. Found, it is a cleaner filter than the gender field.
    if rule == "elite_course" and "divisions_picked" not in chosen:
        chosen["divisions_picked"] = mens_divisions(chosen)

    n = probe_count(ev["event_id"], chosen["course_id"]) if probe else None
    picked_divs = chosen.get("divisions_picked") or []
    over = OVERRIDES.get((slug, ev["year"]))
    rec = {
        "event_id": ev["event_id"], "event_name": ev["name"], "date": ev["date"],
        "course_id": chosen["course_id"], "course_name": chosen["name"],
        "distance_km": chosen["km"] or None,
        "divisions": picked_divs,
        "division_id": picked_divs[0]["id"] if picked_divs else None,
        "division_name": ", ".join(d["name"] for d in picked_divs) or None,
        "rule": rule,
        "course_athletes": n,
        "candidates": [{"id": c["course_id"], "name": c["name"], "km": c["km"],
                        "empty": c.get("empty", False)} for c in cands],
    }
    if over:
        rec.update({k: v for k, v in over.items() if k != "note"})
        rec["override_note"] = over["note"]
        rec["divisions"], rec["division_id"], rec["division_name"] = [], None, None
        rec["rule"] = "open_field"
        rec["course_name"] = f"OVERRIDE -> course {over['course_id']}"
    return rec


def report(course_map, only=None):
    """Print the saved map as one reviewable table. No network.

    This is the artifact to actually read before trusting the archive: one line
    per race-edition saying which Athlinks course was chosen, by which rule,
    and how big the field was.
    """
    for slug in (([only] if only else list(GRAVEL))):
        entries = course_map.get(slug) or {}
        if not entries:
            continue
        info = GRAVEL[slug]
        rules = {}
        for e in entries.values():
            rules[e.get("rule", "skip")] = rules.get(e.get("rule", "skip"), 0) + 1
        print(f"\n=== {info.name}  ({info.discipline})   "
              + ", ".join(f"{k} x{v}" for k, v in sorted(rules.items())))
        for year in sorted(entries, reverse=True):
            e = entries[year]
            if e.get("skip"):
                print(f"  {year}  skipped — {e['skip']}")
                continue
            div = f" / div {e['division_name']!r}" if e.get("division_name") else ""
            print(f"  {year}  {e['rule']:<14} "
                  f"{str(e.get('distance_km') or '?'):>7} km  "
                  f"n={str(e.get('course_athletes') or '-'):>5}  "
                  f"{(e.get('course_name') or '')[:40]}{div}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", help="one gravel slug (default: all six)")
    ap.add_argument("--report", action="store_true",
                    help="print the saved course map and exit; no network")
    ap.add_argument("--no-probe", action="store_true",
                    help="skip the per-course results probe (cannot detect empty elite courses)")
    args = ap.parse_args(argv)

    os.makedirs(SCRAPES, exist_ok=True)
    existing = {}
    if os.path.exists(MAP_PATH):
        with open(MAP_PATH, encoding="utf-8") as f:
            existing = json.load(f)

    if args.report:
        return report(existing, args.race)

    slugs = [args.race] if args.race else list(GRAVEL)
    for slug in slugs:
        if slug not in GRAVEL:
            print(f"unknown gravel slug {slug!r}; expected one of {list(GRAVEL)}")
            return 1
        info = GRAVEL[slug]
        print(f"\n=== {info.name} (athlinks master {info.master_id})")
        evs = editions(info.master_id)
        # One year can hold several Athlinks events (Leadville 2018 published a
        # 1,264-result race and an empty "Coaching Package" on the same day).
        # The one with results is the race.
        best = {}
        for ev in evs:
            if slug == "sea-otter":
                # Sea Otter publishes a dozen events per year, one per
                # discipline-day, and the endurance race is NOT the biggest of
                # them (2022's Fuego XC 80k has 266 results against the 912 of
                # the Fuego XC 40k/Short/La Gravilla event). Only the named
                # event counts.
                if SEA_OTTER.get(ev["year"], (None,))[0] != ev["event_id"]:
                    continue
                best[ev["year"]] = ev
                continue
            cur = best.get(ev["year"])
            if cur is None or ev["result_count"] > cur["result_count"]:
                best[ev["year"]] = ev

        out = existing.setdefault(slug, {})
        for year in sorted(best, reverse=True):
            ev = best[year]
            if ev["result_count"] == 0:
                # Zero results is ambiguous on its own: a cancelled edition and
                # an edition that has not been run yet look identical. The date
                # settles it, exactly as the classics' 500-vs-past-vs-future
                # check does.
                from datetime import date
                past = ev["date"] < date.today().isoformat()
                out[str(year)] = {"event_id": ev["event_id"], "date": ev["date"],
                                  "event_name": ev["name"],
                                  "rule": "cancelled" if past else "not_yet_run",
                                  "course_id": None, "division_id": None}
                print(f"  {year}  {'CANCELLED' if past else 'NOT YET RUN'}  ({ev['date']})")
                continue
            rec = resolve_edition(slug, ev, probe=not args.no_probe)
            out[str(year)] = rec
            if "skip" in rec:
                print(f"  {year}  SKIP — {rec['skip']}")
                continue
            div = f"  div={rec['division_name']!r}" if rec["division_name"] else ""
            print(f"  {year}  {rec['rule']:<14} [{rec['course_id']}] "
                  f"{rec['distance_km'] or '?':>7} km  n={rec['course_athletes']}"
                  f"  {rec['course_name'][:44]}{div}")

    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=1, ensure_ascii=False)
    print(f"\nwrote {MAP_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
