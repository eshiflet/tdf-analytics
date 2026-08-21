#!/usr/bin/env python3
"""Thin client for the (public, unauthenticated) Athlinks results API.

Life Time owns Athlinks, so every Life Time off-road event times through it and
this is first-party data rather than a third-party aggregation. Three endpoints
carry everything the gravel pipeline needs:

  alaska.athlinks.com/MasterEvents/Api/{masterId}
      every edition of a race: date, eventId, result count, course names.
  reignite-api.athlinks.com/event/{eventId}/metadata
      that edition's courses, distances in metres, DIVISION names, splits.
  reignite-api.athlinks.com/event/{e}/race/{course}/results?from=&limit=
      the field itself, paginated. 500/page is accepted.

`reignite-api` sits behind CloudFront and 403s a default urllib/curl
User-Agent. A browser UA plus a www.athlinks.com Referer gets 200 — that is
the only "trick" involved; no key, no cookie, no login.
"""
import json
import os
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# Raw API responses, keyed by what was asked for. GITIGNORED: this is a local
# fetch cache, not data. It exists because the field-selection logic has needed
# several corrections (a DNF's split time is not a finish; pre-2016 editions
# carry no status field at all), and re-deriving from a cached response takes
# seconds where re-fetching 90 editions takes half an hour. Delete the
# directory to force a true refetch.
RAW_CACHE = os.path.join(HERE, "gravel_scrapes", "_raw")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Referer": "https://www.athlinks.com/",
           "Accept": "application/json"}

ALASKA = "https://alaska.athlinks.com"
REIGNITE = "https://reignite-api.athlinks.com"

# Athlinks tolerates a steady trickle; this keeps a full six-race sweep at a
# few minutes rather than hammering it.
DELAY = 0.35


def get_json(url, tries=4, timeout=90):
    """GET + parse, with backoff. Returns None on a persistent failure.

    Returning None rather than raising is deliberate: a sweep across 100+
    editions must not abort because one 500s, and a missing edition is a fact
    the caller records, not an exception it hides.
    """
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:            # noqa: BLE001 - reported, not swallowed
            last = exc
            time.sleep(1.5 * (attempt + 1))
    print(f"    ! GET failed after {tries} tries: {url}\n      {last}")
    return None


def master(master_id):
    """All editions of one race. None if the master event is unreachable."""
    d = get_json(f"{ALASKA}/MasterEvents/Api/{master_id}")
    time.sleep(DELAY)
    return (d or {}).get("result")


def editions(master_id):
    """[(year, date, event_id, name, result_count)] newest first."""
    res = master(master_id)
    if not res:
        return []
    out = []
    for r in res.get("eventRaces", []):
        date = (r.get("raceDate") or "")[:10]
        if not date:
            continue
        out.append({
            "year": int(date[:4]), "date": date, "event_id": r["raceID"],
            "name": r.get("raceName") or "", "result_count": r.get("resultCount") or 0,
        })
    out.sort(key=lambda e: e["date"], reverse=True)
    return out


def event_metadata(event_id):
    """Courses ('races'), each with distance, divisions and split intervals."""
    d = get_json(f"{REIGNITE}/event/{event_id}/metadata")
    time.sleep(DELAY)
    return d


def _cache_path(event_id, course_id, division_id):
    name = f"{event_id}_{course_id}" + (f"_d{division_id}" if division_id else "")
    return os.path.join(RAW_CACHE, f"{name}.json")


def results(event_id, course_id, division_id=None, page=100, cap=20000,
            use_cache=True):
    """Every result row on one course — or on one DIVISION of it — to the end.

    Pass `division_id` whenever the field wanted is a class inside a mass-start
    race (Leadville's "Pro/Elite Men", Unbound 2022's "Pro Open Men"). It is
    not an optimisation, it is the only thing that works: for most editions the
    plain course response omits the per-rider `divisions` object entirely, so
    filtering client-side silently yields nothing. The division endpoint also
    returns only CLASSIFIED FINISHERS — a division's DNFs count towards its
    totalAthletes but are never served — so these editions carry no DNF rows.

    Page size is adaptive. The results index stores each rider's timing splits
    as inner hits, so a course with many splits blows Elasticsearch's inner
    result window and 400s ("Inner result window is too large") at a page size
    another course serves happily. Rather than pick a pessimistic size for
    every request, start at 100 and halve on a 400.

    `cap` is a guard, not a filter: a runaway loop on a malformed `from`
    cursor would otherwise page forever.
    """
    cache_file = _cache_path(event_id, course_id, division_id)
    if use_cache and os.path.exists(cache_file):
        with open(cache_file, encoding="utf-8") as f:
            cached = json.load(f)
        return cached["rows"], cached["total"]

    rows, frm, total = [], 0, None
    while frm < cap:
        d = None
        size = page
        while size >= 10:
            path = (f"/division/{division_id}/results" if division_id
                    else "/results")
            url = (f"{REIGNITE}/event/{event_id}/race/{course_id}{path}"
                   f"?from={frm}&limit={size}")
            d = get_json(url, tries=2)
            time.sleep(DELAY)
            if d is not None:
                break
            size //= 2
        if not d:
            break
        if total is None:
            total = (d.get("division") or {}).get("totalAthletes")
        intervals = d.get("intervals") or []
        if not intervals:
            break
        # interval[0] is the full course; the rest are timing splits.
        batch = intervals[0].get("results") or []
        rows.extend(batch)
        frm += len(batch)
        if not batch or (total is not None and frm >= total):
            break

    if use_cache and rows:
        os.makedirs(RAW_CACHE, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"total": total, "rows": rows}, f)
    return rows, total
