#!/usr/bin/env python3
"""Scrape the top-level men's field of every Life Time off-road race-edition.

Reads gravel_scrapes/_course_map.json (written by resolve_gravel_courses.py —
run that first, and review its table) and fetches exactly the course and
division it names. Nothing here searches for a course by name: the resolution
is a reviewed artifact, and re-deriving it per run is how a renamed course
silently becomes a different race.

Output: gravel_scrapes/<race-slug>/<year>.json, one file per race-edition,
tracked in git the way classics_scrapes/ is.

Three things this deliberately does NOT do:

  * store a partial time as a finish. Athlinks fills gunTime/chipTime for DNFs
    from their last recorded split, so Leadville 2025 shows Tsgabu Grmay at
    1h33 for a 100-miler. Sorted by time, the DNFs win the race. Only a
    status of CONF keeps its time.
  * guess elevation. Athlinks publishes none and PCS does not cover these
    races at all, so vertical_meters stays NULL rather than derived.
  * take everyone. See FIELD_CAP.

Usage:
  python3 scrape_athlinks.py                       # every mapped race-year
  python3 scrape_athlinks.py --race leadville
  python3 scrape_athlinks.py --race unbound --year 2019
  python3 scrape_athlinks.py --force               # refetch existing files
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

from athlinks_api import event_metadata, results
from race_common import GRAVEL, fix_mojibake

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES = os.path.join(HERE, "gravel_scrapes")
MAP_PATH = os.path.join(SCRAPES, "_course_map.json")

# How many finishers to keep from an `open_field` edition.
#
# Before ~2016 these races had no pro class: Dave Wiens and the eventual
# winner started alongside 1,800 people riding for a buckle, in one mass
# start, scored as one result list. There is no line in the data between
# "elite" and "everyone else" because there was no line in the race, so any
# cutoff is ours, not the sport's. 100 is chosen to sit comfortably outside
# the competitive front of every one of these races (the pro fields that DO
# exist run 36-143 riders) while keeping the archive to a size the Riders page
# can carry. The true field size is recorded alongside, so the window is
# always visible as a window.
#
# Editions WITH a pro class are never truncated — that field is the sport's
# own definition of the top level, and all of it is kept.
FIELD_CAP = 100

# Implied average speed outside this band means the row is not a result of the
# race it is filed under. Deliberately far wider than any real off-road field
# (winners run 20-40 km/h, last finishers around 10) because it exists to catch
# a category error, not to judge a slow rider.
#
# Chequamegon 2013 is why. Athlinks labels that edition "(Merged DBF)" and its
# "Chequamegon 40 Mile" course holds the Short & Fat 16 results too, under the
# same athlete ids: Brian Matter appears at 2:03:49 AND at 49:25. Ranked
# together, half the top 20 of a 40-mile race is people who rode 16. At the
# course's own 64.37 km, 49:25 implies 78 km/h on a mountain bike — which is
# not a fast ride, it is a different race.
SPEED_BAND_KMH = (5.0, 55.0)

# The absolute band above only catches order-of-magnitude errors. The subtler
# and more common failure is a row flagged as a finish that carries a
# checkpoint time — Leadville 2017 ranked Floyd Landis first at 3:18:07 for a
# race whose median finisher took 7:12, and 3:18 is a perfectly ordinary
# number for a bike race, just not for this one.
#
# So the field judges itself: a "finish" faster than RELATIVE_FLOOR of the
# median finishing time is not one. Measured across all 89 editions, the gap
# is wide and empty — every real winner in the archive sits at 0.70 or above
# (Leipheimer 0.749, Armstrong 0.760, Stamstad 0.775, the tightest being
# Chequamegon at 0.95), while the three corrupt editions sit at 0.445, 0.458
# and 0.484. 0.60 splits them with room on both sides.
RELATIVE_FLOOR = 0.60
# Below this many finishers the median is too easily contaminated by the very
# rows it is meant to catch, so the relative rule stands down.
MIN_FIELD_FOR_RELATIVE = 8

STATUS_MAP = {
    "CONF": "FINISHED", "OK": "FINISHED", "FIN": "FINISHED",
    "DNF": "DNF", "DNS": "DNS", "DQ": "DSQ", "DSQ": "DSQ", "OTL": "OTL",
}


def row_status(r):
    """FINISHED / DNF / ... for one Athlinks row.

    Editions before roughly 2016 carry NO status field at all — Leadville 2012
    and Dirty Kanza 2012 ship rows with a time, a rank and nothing else.
    Defaulting those to DNF marked all 100 riders of every early edition as
    non-finishers, nulled their ranks and threw away their times, and the files
    still looked perfectly well-formed. A row that has both a time and a
    finishing position IS a finisher; that is what the timer recorded.
    """
    raw = (r.get("status") or "").upper()
    if raw:
        return STATUS_MAP.get(raw, "DNF")
    has_time = r.get("chipTimeInMillis") or r.get("gunTimeInMillis")
    has_rank = (r.get("rankings") or {}).get("overall")
    return "FINISHED" if (has_time and has_rank) else "DNF"

# Surname particles, so "Andrew Van Der Poel" splits as first "Andrew",
# last "Van Der Poel" rather than last "Poel". Only affects sort order in the
# Riders grid — display concatenates first + last either way.
PARTICLES = {
    "van", "von", "de", "del", "della", "di", "da", "dos", "du", "le", "la",
    "der", "den", "ter", "ten", "op", "uit", "st", "st.", "san", "santa",
    "saint", "el", "al", "bin", "ibn", "mac", "af", "av",
}


def normalize_case(name):
    """Title-case a name that arrived all-lower or all-upper; leave others alone.

    Athlinks' case is per-event, not per-name: Sea Otter 2026 ships
    "bradyn lange" while Leadville 2026 ships "Bradyn Lange", and the same
    rider must not become two. Mixed-case names are left untouched — they are
    already how the timer recorded them, and "McElveen" survives only by not
    being touched.
    """
    if not name:
        return name
    if not (name.islower() or name.isupper()):
        return name
    out = []
    for word in name.split():
        parts = re.split(r"([-'’])", word.lower())
        rebuilt = "".join(p if p in "-'’" else p.capitalize() for p in parts)
        # Mc/Mac are the common exception the naive rule gets wrong.
        m = re.match(r"^(Mc)([a-z])(.*)$", rebuilt)
        if m:
            rebuilt = m.group(1) + m.group(2).upper() + m.group(3)
        out.append(rebuilt)
    return " ".join(out)


def split_name(full):
    """('Alexey', 'Vermeulen') from 'Alexey Vermeulen'. Particle-aware."""
    toks = full.split()
    if len(toks) < 2:
        return None, full or None
    i = len(toks) - 1
    while i > 1 and toks[i - 1].lower().strip(".") in PARTICLES:
        i -= 1
    return " ".join(toks[:i]) or None, " ".join(toks[i:]) or None


def clean_name(raw):
    return normalize_case(fix_mojibake((raw or "").strip()))


def division_rank(row, division_id):
    """The rider's rank INSIDE the selected division.

    Their overall rank is a different number and a misleading one — in the
    mass-start years the pro winner is overall #1, but in 2025 Leadville the
    20th-placed pro is somewhere in the 200s overall.
    """
    rk = row.get("rankings") or {}
    for other in rk.get("other") or []:
        if other.get("id") == division_id:
            return other.get("rank")
    divs = row.get("divisions")
    if divs is not None:
        return rk.get("primary") if divs.get("primary") == division_id else None
    # No per-row `divisions` object at all — the common case before ~2024.
    # These rows came back from /division/{id}/results, so `primary` IS the
    # rank in the division we asked for. Ignoring it cost real accuracy: Sea
    # Otter 2023 fell back to ranking on the clock, and because a handful of
    # that edition's rows carry a checkpoint time rather than a finishing one,
    # the published podium (Swenson, Finsterwald, Blevins — all confirmed by
    # Life Time's own results) was replaced by two riders ranked 57th and
    # below. The ranks were right; the clock was the unreliable part.
    return rk.get("primary")


def dedupe(rows):
    """Drop rows that repeat an athlete verbatim.

    Big Sugar 2023 lists Connor Kamm and Finn Gullickson three times each,
    identical athlete id and all. Left in, they overwrite themselves at ingest
    (stage_results is keyed on stage+rider) and the file's own count lies.
    """
    seen, out = set(), []
    for r in rows:
        key = (r.get("id"), r.get("displayName"),
               r.get("chipTimeInMillis"), r.get("gunTimeInMillis"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def clock_ms(r, rank_type):
    primary = "chipTimeInMillis" if rank_type == "chip" else "gunTimeInMillis"
    return r.get(primary) or r.get("chipTimeInMillis") or r.get("gunTimeInMillis")


def time_floor(rows, rank_type, distance_km):
    """Finishing times below this are not finishes of this race.

    Derived from the field's own median, so it needs no per-race constant and
    works the same for a 40-mile MTB race and a 350-mile gravel one. Returns
    None when the field is too small to trust.
    """
    ts = sorted(t for r in rows
                if row_status(r) == "FINISHED"
                and not implausible(r, rank_type, distance_km)
                for t in [clock_ms(r, rank_type)] if t)
    if len(ts) < MIN_FIELD_FOR_RELATIVE:
        return None
    return ts[len(ts) // 2] * RELATIVE_FLOOR


def implausible(r, rank_type, distance_km, floor=None):
    """True if this row's FINISHING time cannot belong to this race.

    Only finishers are judged. A DNF's time is the last split Athlinks saw, so
    its implied speed is meaningless by construction — testing it drops real
    riders (ten of Sea Otter 2026's abandons, Russell Finsterwald among them).
    """
    if row_status(r) != "FINISHED":
        return False
    ms = clock_ms(r, rank_type)
    if not ms:
        return False
    if floor is not None and ms < floor:
        return True
    if not distance_km:
        return False
    kmh = distance_km / (ms / 3_600_000.0)
    lo, hi = SPEED_BAND_KMH
    return not (lo <= kmh <= hi)


def resolve_implausible(picked, rank_type, distance_km, floor=None):
    """Split rows whose time cannot be a finish of this race into two cases.

    They are not the same thing and must not be handled the same way:

    * The athlete ALSO has a plausible row on this course. Then the odd one is
      a foreign result the source merged in, and it is removed. Chequamegon
      2013 is the case: Brian Matter appears at 2:03:49 for the 40 and at
      49:25 for the Short & Fat 16, same athlete id.

    * It is their ONLY row. Then they started this race and did not finish it,
      whatever the status flag says — Unbound 2026 marks seventeen riders CONF
      with times from 0.5h to 5.9h over 200 miles, a smooth abandon tail rather
      than a second race. Removing them would erase riders who really did line
      up, so the row stays and becomes a DNF: no time, no rank.

    Returns (kept, dropped, downgraded).
    """
    bad = [r for r in picked if implausible(r, rank_type, distance_km, floor)]
    if not bad:
        return picked, [], []
    good_ids = {r.get("id") for r in picked
                if r.get("id") is not None
                and not implausible(r, rank_type, distance_km, floor)}
    dropped, downgraded = [], []
    for r in bad:
        if r.get("id") is not None and r.get("id") in good_ids:
            dropped.append(r)
        else:
            r["status"] = "DNF"      # row_status() then nulls time and rank
            downgraded.append(r)
    # If this edition demonstrably has ANOTHER race merged into it, a lone
    # implausible row is far more likely to be a rider who only did that other
    # race than an abandon. Chequamegon 2013 has eight such rows: people who
    # rode the Short & Fat 16 and nothing else. Recording them as DNFs of a
    # 40-mile race they never started would be a small fabrication in a file
    # whose whole point is not making any.
    if dropped and downgraded:
        for r in downgraded:
            r.pop("status", None) if r.get("status") == "DNF" else None
        dropped.extend(downgraded)
        downgraded = []

    kept = [r for r in picked if r not in dropped]
    return kept, dropped, downgraded


def fetch_field(entry):
    """(rows, total, divisions_actually_used) for one edition.

    A race's top-level men's field can be split across two divisions
    (Leadville 2023: "Pro Male" holds John Gaston, "Grand Prix Male" holds
    Keegan Swenson, who won), so every resolved division is fetched and the
    results unioned by athlete id.

    And a division can be published but hold nothing: Leadville 2022's
    "LT100 Pro" course carries a "Pro Male" division that returns zero rows,
    which silently produced a race with no results at all. When the union comes
    back empty, fall back to the course itself — for an elite course that IS
    the field.
    """
    divs = entry.get("divisions")
    if divs is None:                       # map written before divisions[] existed
        divs = ([{"id": entry["division_id"], "name": entry.get("division_name")}]
                if entry.get("division_id") else [])
    if not divs:
        rows, total = results(entry["event_id"], entry["course_id"])
        return rows, total, []

    merged, seen, total = [], set(), 0
    used = []
    for d in divs:
        rows, n = results(entry["event_id"], entry["course_id"], division_id=d["id"])
        if not rows:
            continue
        used.append(d)
        total += n or 0
        for r in rows:
            key = r.get("id") or (r.get("displayName"), r.get("gunTimeInMillis"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(r)
    if merged:
        return merged, total, used

    print("       ! every resolved division returned nothing; "
          "falling back to the whole course")
    rows, total = results(entry["event_id"], entry["course_id"])
    return rows, total, []


def select_field(rows, entry):
    """Rows of the top-level men's field, ranked, per the edition's rule.

    `rows` already IS the division when one was resolved — see
    athlinks_api.results(division_id=...). Filtering here would be wrong twice
    over: most editions omit the per-rider `divisions` object, and the ones
    that carry it agree with the endpoint anyway.
    """
    rule = entry["rule"]
    div_ids = [d["id"] for d in (entry.get("divisions_used") or [])]
    rows = dedupe(rows)

    if div_ids:
        picked = list(rows)
        # One division and every row carrying its own rank: that IS the
        # published classification, so use it verbatim.
        ranks = ([division_rank(r, div_ids[0]) for r in picked]
                 if len(div_ids) == 1 else [None] * len(picked))
        if len(div_ids) == 1 and all(r is not None for r in ranks):
            for r, rk in zip(picked, ranks):
                r["_rank"] = rk
        else:
            # A union of two divisions has two independent rank sequences, and
            # some editions publish no per-row division rank at all. Either way
            # the men's classification has to be rebuilt from the clock, which
            # is what it was in the first place.
            rank_type = entry.get("_rank_type")
            def clock(r):
                primary = ("chipTimeInMillis" if rank_type == "chip"
                           else "gunTimeInMillis")
                return (r.get(primary) or r.get("chipTimeInMillis")
                        or r.get("gunTimeInMillis") or 10**15)
            finishers = [r for r in picked if row_status(r) == "FINISHED"]
            finishers.sort(key=clock)
            for i, r in enumerate(finishers, start=1):
                r["_rank"] = i
            for r in picked:
                if row_status(r) != "FINISHED":
                    r["_rank"] = None
    else:
        # No division to filter on, so gender is the only men's marker. An
        # elite MEN'S course is already all men and this is a no-op; a
        # mixed elite course (Chequamegon's "Pro/Elite 40") needs it.
        picked = [r for r in rows if (r.get("gender") or "").upper() == "M"]
        # Rank among men, in the timer's own order, counting FINISHERS ONLY.
        #
        # Athlinks' `overall` numbers non-finishers too — Matej Mohoric DNF'd
        # Unbound 2024 and is overall 42 — so numbering every row and blanking
        # the DNFs afterwards left the classification with holes: 117 finishers
        # ranked up to 130. A race's result is 1st through 117th.
        picked.sort(key=lambda r: ((r.get("rankings") or {}).get("overall") or 10**9))
        rank = 0
        for r in picked:
            overall = (r.get("rankings") or {}).get("overall")
            if overall and row_status(r) == "FINISHED":
                rank += 1
                r["_rank"] = rank
            else:
                r["_rank"] = None

    # A rider who did not finish has no finishing position. Athlinks numbers
    # some of them anyway (Leadville 2025 ranks a DNF 21st in the Grand Prix
    # division), and storing that would put a non-finisher in the results.
    for r in picked:
        if row_status(r) != "FINISHED":
            r["_rank"] = None

    picked.sort(key=lambda r: (r["_rank"] is None, r["_rank"] or 0))
    if rule == "open_field":
        # The window is over the CLASSIFIED field: an unranked rider has no
        # claim on a top-100 place, so DNFs are not what fills the cap.
        picked = picked[:FIELD_CAP]
    return picked


def to_row(r, rank_type):
    status = row_status(r)
    # Which clock the division was scored on. Ignoring it would rank a
    # mass-start race by chip time, which is not how it was won.
    primary = "chipTimeInMillis" if rank_type == "chip" else "gunTimeInMillis"
    ms = r.get(primary) or r.get("chipTimeInMillis") or r.get("gunTimeInMillis")
    # A DNF's time is the last split Athlinks saw, not a finish. Dropping it is
    # the whole point — kept, it outranks the winner.
    secs = int(round(ms / 1000)) if (ms and status == "FINISHED") else None
    loc = r.get("location") or {}
    name = clean_name(r.get("displayName"))
    first, last = split_name(name)
    return {
        "rank": r.get("_rank"),
        "name": name, "first_name": first, "last_name": last,
        "bib": (r.get("bib") or "").strip() or None,
        # Athlinks writes 0 for "not recorded" in the older editions — every
        # Dirty Kanza 2012 and 2013 row carries age 0. Stored as-is it becomes
        # a rider born the year they raced.
        "age": r.get("age") or None,
        "gender": r.get("gender"),
        "country": (loc.get("country") or "").lower() or None,
        "locality": loc.get("locality") or None,
        "region": loc.get("region") or None,
        "finish_seconds": secs,
        "status": status,
        "athlinks_id": r.get("id"),
        "racer_id": r.get("racerId") or None,
        "rank_overall": (r.get("rankings") or {}).get("overall"),
    }


def scrape_one(slug, year, entry, force=False):
    out_dir = os.path.join(SCRAPES, slug)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{year}.json")
    if os.path.exists(path) and not force:
        return "exists", 0

    if entry.get("skip"):
        return f"skip ({entry['skip']})", 0
    if entry["rule"] == "not_yet_run":
        return "not yet run", 0

    info = GRAVEL[slug]

    def discipline_of(course_name):
        """Per-EDITION surface, not per-race.

        Sea Otter's Grand Prix round changed discipline under the same name:
        Fuego XL was a mountain-bike race through 2024, and from 2025 the round
        is Sea Otter Gravel over a different course. One `discipline` per race
        would paint 2025 as MTB. The course name is the source's own statement
        of what it was.
        """
        return "gravel" if "gravel" in (course_name or "").lower() else info.discipline

    if entry["rule"] == "cancelled":
        data = {
            "info": {"race_slug": slug, "year": year, "date": entry["date"],
                     "event_id": entry["event_id"], "event_name": entry.get("event_name"),
                     "discipline": info.discipline, "rule": "cancelled",
                     "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            "cancelled": True, "rows": [],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return "cancelled", 0

    meta = event_metadata(entry["event_id"]) or {}
    course = next((c for c in meta.get("races", [])
                   if c.get("id") == entry["course_id"]), None)
    rank_type = None
    if course:
        for d in course.get("divisions") or []:
            if d.get("id") == (entry.get("division_id") or -1) or d.get("type") == "overall":
                rank_type = d.get("rankType") or rank_type
    # An open_field edition fetches its WHOLE field — 3,900 rows for
    # Chequamegon 2013 — to keep 100. Stopping early would be much faster and
    # would give the same 100 riders (results come back in rank order), but
    # `field_size_men` would then be unknown, and the honesty of the top-100
    # window depends on being able to say what it is a window ON. The raw
    # cache means this cost is paid once.
    rows, total, div_used = fetch_field(entry)
    if not rows:
        return "NO RESULTS RETURNED", 0

    entry = {**entry, "divisions_used": div_used, "_rank_type": rank_type}
    picked = select_field(rows, entry)

    # Speed check AFTER selection but BEFORE ranking, so nothing that is not a
    # finish of THIS race can take a place in its classification.
    km = entry.get("distance_km")
    floor = time_floor(picked, rank_type, km)
    picked, dropped, downgraded = resolve_implausible(picked, rank_type, km, floor)
    if dropped or downgraded:
        # Ranks were assigned over a field that included these rows.
        rank = 0
        for r in picked:
            if r.get("_rank") is not None and row_status(r) == "FINISHED":
                rank += 1
                r["_rank"] = rank
            else:
                r["_rank"] = None
        if dropped:
            print(f"       ! dropped {len(dropped)} row(s) from another race "
                  f"(e.g. {dropped[0].get('displayName')})")
        if downgraded:
            print(f"       ! {len(downgraded)} row(s) flagged finished but timed "
                  f"impossibly over {km} km -> recorded as DNF "
                  f"(e.g. {downgraded[0].get('displayName')})")
        if entry["rule"] == "open_field":
            picked = [r for r in picked if r["_rank"] is not None][:FIELD_CAP]

    # Re-sort: the speed pass renumbers finishers, so a row downgraded to DNF
    # can be left sitting above the winner in the file.
    picked.sort(key=lambda r: (r.get("_rank") is None, r.get("_rank") or 0))
    out_rows = [to_row(r, rank_type) for r in picked]

    # Gaps are computed here, not stored by Athlinks. Winner's gap is 0 by
    # definition; a rider with no finish time has no gap rather than a zero.
    win = next((r["finish_seconds"] for r in out_rows
                if r["rank"] == 1 and r["finish_seconds"]), None)
    for r in out_rows:
        r["gap_seconds"] = (r["finish_seconds"] - win
                            if win and r["finish_seconds"] is not None else None)

    data = {
        "info": {
            "race_slug": slug, "year": year, "date": entry["date"],
            "event_id": entry["event_id"], "event_name": entry.get("event_name"),
            "course_id": entry["course_id"], "course_name": entry.get("course_name"),
            "division_id": entry.get("division_id"),
            "division_name": entry.get("division_name"),
            "divisions_used": [d.get("name") for d in div_used],
            "rule": entry["rule"], "rank_type": rank_type,
            "distance_km": entry.get("distance_km"),
            "discipline": discipline_of(entry.get("course_name")),
            # Both numbers matter: `field_size_course` is how many people the
            # timer scored on this course, `field_size_selected` how many are
            # in this file. When they differ under `open_field`, the archive
            # holds a window on the race, and that has to stay visible.
            # Reported by whichever endpoint was read: the whole course for
            # elite_course/open_field, the division alone for elite_division.
            # It can exceed the rows served — a division counts its DNFs here
            # but does not return them.
            "field_size_source": total,
            "field_size_men": sum(1 for r in rows
                                  if (r.get("gender") or "").upper() == "M"),
            "field_size_selected": len(out_rows),
            # Non-zero means the source served rows that are not finishes of
            # this race — see resolve_implausible().
            "dropped_foreign": len(dropped),
            "downgraded_to_dnf": len(downgraded),
            "truncated": entry["rule"] == "open_field" and len(out_rows) == FIELD_CAP,
            "source_url": (f"https://www.athlinks.com/event/{entry['event_id']}"
                           f"/results/Event/{entry['event_id']}"
                           f"/Course/{entry['course_id']}/Results"),
            "api_url": (f"https://reignite-api.athlinks.com/event/{entry['event_id']}"
                        f"/race/{entry['course_id']}/results"),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "cancelled": False,
        "rows": out_rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return "ok", len(out_rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--race")
    ap.add_argument("--year", type=int)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    with open(MAP_PATH, encoding="utf-8") as f:
        course_map = json.load(f)

    slugs = [args.race] if args.race else list(GRAVEL)
    grand = 0
    for slug in slugs:
        if slug not in course_map:
            print(f"{slug}: not in course map — run resolve_gravel_courses.py")
            continue
        print(f"\n=== {GRAVEL[slug].name}")
        years = sorted(course_map[slug], reverse=True)
        for y in years:
            if args.year and int(y) != args.year:
                continue
            status, n = scrape_one(slug, int(y), course_map[slug][y], force=args.force)
            grand += n
            print(f"  {y}  {status:<44} {n or ''}")
    print(f"\n{grand:,} results written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
