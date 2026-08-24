#!/usr/bin/env python3
"""Thin client for the two platforms that publish The Traka's results.

The Traka is not a Life Time race, so none of it is on Athlinks. Its editions
are split across the two timers Klassmark has used:

  sportmaniacs.com                          2023, 2024, 2026
      /es/api/races/{slug}                  race id, date, city
      /es/api/events?race={raceId}          each distance, with its own uuid
      /es/races/rankings/{eventId}          the field, in ONE response

  tretzesports.com (Klassmark's own)        2021, 2022
      /curses3/backend/code/api/getCursa.php?idCursa=N      name + date
      /curses3/backend/code/api/getResultats.php?idCursa=N  the field

Neither needs a key, a cookie or a browser — both are plain JSON over GET, and
both are gzipped, which urllib does NOT decompress on its own. Forgetting that
is the one way to get a UnicodeDecodeError out of a perfectly good response.

Neither paginates: a Traka field is at most a few thousand rows and both APIs
return the lot. That is why there is no page-size dance here of the kind
athlinks_api.results() has to do.
"""
import gzip
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# Same contract as athlinks_api's cache: raw responses, GITIGNORED, so a
# selection-rule change can be re-derived without refetching. Delete to refetch.
RAW_CACHE = os.path.join(HERE, "gravel_scrapes", "_raw")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

SPORTMANIACS = "https://sportmaniacs.com"
TRETZE = "https://tretzesports.com/curses3/backend/code/api"

DELAY = 0.35


def _get_json(url, referer, tries=4, timeout=90):
    """GET + gunzip + parse, with backoff. None on persistent failure.

    Returns None rather than raising for the same reason athlinks_api does: a
    sweep over every edition must not abort because one of them 500s.
    """
    headers = {"User-Agent": UA, "Referer": referer,
               "Accept": "application/json", "Accept-Encoding": "gzip"}
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("content-encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except Exception as exc:            # noqa: BLE001 - reported, not swallowed
            last = exc
            time.sleep(1.5 * (attempt + 1))
    print(f"    ! GET failed after {tries} tries: {url}\n      {last}")
    return None


def _cache_path(name):
    return os.path.join(RAW_CACHE, f"traka_{name}.json")


def _cached(name, fetch, force=False):
    """Read-through cache. `force` refetches and rewrites."""
    path = _cache_path(name)
    if not force and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    data = fetch()
    if data is not None:
        os.makedirs(RAW_CACHE, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        time.sleep(DELAY)
    return data


# ── sportmaniacs ────────────────────────────────────────────────────────────

def sm_race(slug, force=False):
    """The edition's own record: id, date, city. `slug` is e.g. the-traka-2025."""
    d = _cached(f"sm_race_{slug}",
                lambda: _get_json(f"{SPORTMANIACS}/es/api/races/{slug}",
                                  f"{SPORTMANIACS}/"), force)
    return (d or {}).get("data")


def sm_events(race_id, force=False):
    """Every distance in one edition: [{id, name, distance}, ...]."""
    d = _cached(f"sm_events_{race_id}",
                lambda: _get_json(f"{SPORTMANIACS}/es/api/events?race={race_id}",
                                  f"{SPORTMANIACS}/"), force)
    return (d or {}).get("data") or []


def sm_rankings(event_id, force=False):
    """One distance's whole field, plus Event/Race/Categories metadata.

    An event that exists but has no published results returns an empty
    Rankings list rather than an error — every 2025 Traka distance does this,
    which is a fact about the source, not a failure of the fetch.
    """
    d = _cached(f"sm_rankings_{event_id}",
                lambda: _get_json(f"{SPORTMANIACS}/es/races/rankings/{event_id}",
                                  f"{SPORTMANIACS}/"), force)
    return (d or {}).get("data") or {}


def sm_race_index(force=False):
    """Every race sportmaniacs knows, as [{key: slug, value: name}, ...].

    ~24k entries. Used only to DISCOVER which Traka editions exist, so that
    _traka_events.json is built from the source rather than a hardcoded list.
    """
    d = _cached("sm_index",
                lambda: _get_json(
                    "https://api-aws.sportmaniacs.com/api/races?prefetch=true&lang=es",
                    f"{SPORTMANIACS}/"), force)
    return (d or {}).get("data") or []


# ── tretzesports ────────────────────────────────────────────────────────────

def tz_race(cursa_id, force=False):
    """Race record for one `idCursa`: nom, data (ISO date), organitzador.

    The response also carries the event logo as a base64 JPEG data URI, which
    is most of its ~120 KB. It is cached as-is rather than stripped, because
    the cache's job is to be the raw response.
    """
    return _cached(f"tz_race_{cursa_id}",
                   lambda: _get_json(f"{TRETZE}/getCursa.php?idCursa={cursa_id}",
                                     "https://tretzesports.com/curses3/resultats/curses/"),
                   force)


def tz_results(cursa_id, force=False):
    """One race's field. Rows carry Sexe ('Home'/'Dona') and PosicioSexe."""
    d = _cached(f"tz_results_{cursa_id}",
                lambda: _get_json(f"{TRETZE}/getResultats.php?idCursa={cursa_id}",
                                  "https://tretzesports.com/curses3/resultats/curses/"),
                force)
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, list):
                return v
    return []
