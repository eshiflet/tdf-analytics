#!/usr/bin/env python3
"""
Scrape PCS rider detail pages to get full name (Firstname Lastname) and birthday.

Fetches https://www.procyclingstats.com/{rider_id} for every rider in the DB,
parses the h1 element (gives "Firstname Lastname") and the meta description
(gives "born YYYY-MM-DD"), then updates the riders table with first_name,
last_name, and birthday.

Caches raw parsed data in pipeline/rider_scrapes/{slug}.json for resumability.
Re-running is safe: already-cached slugs are skipped unless --refetch is passed.
Use --db-only to apply the cache to the DB without making any network requests.

Usage:
  python3 scrape_rider_details.py            # scrape all uncached riders
  python3 scrape_rider_details.py --db-only  # apply cache → DB, no network
  python3 scrape_rider_details.py --refetch  # re-fetch even cached slugs
  SCRAPE_DELAY=1.5 python3 scrape_rider_details.py
"""

import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
CACHE_DIR = os.path.join(HERE, "rider_scrapes")
BASE = "https://www.procyclingstats.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

DELAY = float(os.environ.get("SCRAPE_DELAY", "2.0"))

# Lowercase surname particles — used by parse_first_last() to group
# particles with the following capitalized word into the last name.
PARTICLES = {
    "van", "de", "di", "del", "den", "der", "von", "le", "la",
    "du", "dos", "das", "da", "lo", "el", "al", "bin", "bint",
    "y", "i", "af", "av", "ap", "mac", "mc", "o",
}

DB_ONLY = "--db-only" in sys.argv
REFETCH = "--refetch" in sys.argv


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

def fetch(url: str, max_tries: int = 8) -> str | None:
    for attempt in range(max_tries):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                html = r.read().decode("utf-8", errors="replace")
            if "Just a moment" in html and len(html) < 10000:
                print(f"  Cloudflare challenge, waiting 60s ({url})", flush=True)
                time.sleep(60)
                continue
            time.sleep(DELAY)
            return html
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 30 + attempt * 15
                print(f"  429, backing off {wait}s ({url})", flush=True)
                time.sleep(wait)
                continue
            if e.code in (404, 410):
                time.sleep(DELAY)
                return None
            print(f"  HTTP {e.code}: {url}", flush=True)
            time.sleep(DELAY)
            return None
        except Exception as exc:
            print(f"  error ({exc}): {url}", flush=True)
            time.sleep(DELAY)
            return None
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_page(html: str) -> dict:
    """Extract display_name and birthday from a PCS rider page."""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html)
    display_name = h1.group(1).strip() if h1 else None

    bday = re.search(r"born (\d{4}-\d{2}-\d{2})", html)
    birthday = bday.group(1) if bday else None

    return {"display_name": display_name, "birthday": birthday}


def parse_first_last(display_name: str) -> tuple[str | None, str | None]:
    """Split "Firstname Lastname" into (first_name, last_name).

    Handles compound first names ("Juan Carlos Domínguez" → "Juan Carlos",
    "Domínguez"), surname particles ("Wout van Aert" → "Wout", "van Aert"),
    and both together ("Pedro de la Rosa" → "Pedro", "de la Rosa").
    """
    words = display_name.strip().split() if display_name else []
    if not words:
        return (None, None)
    if len(words) == 1:
        return (None, words[0])

    # Scan right-to-left: pull in any PARTICLES immediately before the
    # last capitalized word, so they become part of the last name.
    i = len(words) - 1
    while i > 0 and words[i - 1].lower() in PARTICLES:
        i -= 1

    last_name = " ".join(words[i:])
    first_name = " ".join(words[:i]) if i > 0 else None
    return (first_name, last_name)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_all_rider_ids(conn: sqlite3.Connection) -> list[str]:
    cur = conn.cursor()
    cur.execute("SELECT rider_id FROM riders ORDER BY rider_id")
    return [r[0] for r in cur.fetchall()]


def update_rider(conn: sqlite3.Connection, rider_id: str,
                 first_name: str | None, last_name: str | None,
                 birthday: str | None) -> None:
    conn.execute(
        "UPDATE riders SET first_name=?, last_name=?, birthday=? WHERE rider_id=?",
        (first_name, last_name, birthday, rider_id),
    )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def cache_path(rider_id: str) -> str:
    slug = rider_id.removeprefix("rider/")
    return os.path.join(CACHE_DIR, f"{slug}.json")


def load_cache(rider_id: str) -> dict | None:
    p = cache_path(rider_id)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_cache(rider_id: str, data: dict) -> None:
    slug = rider_id.removeprefix("rider/")
    os.makedirs(CACHE_DIR, exist_ok=True)
    p = os.path.join(CACHE_DIR, f"{slug}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def apply_cache_to_db(conn: sqlite3.Connection, rider_ids: list[str]) -> int:
    updated = 0
    for rider_id in rider_ids:
        cached = load_cache(rider_id)
        if not cached or not cached.get("display_name"):
            continue
        first, last = parse_first_last(cached["display_name"])
        update_rider(conn, rider_id, first, last, cached.get("birthday"))
        updated += 1
    conn.commit()
    return updated


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rider_ids = get_all_rider_ids(conn)
    total = len(rider_ids)

    if DB_ONLY:
        n = apply_cache_to_db(conn, rider_ids)
        print(f"Applied {n}/{total} cached riders to DB")
        conn.close()
        return

    os.makedirs(CACHE_DIR, exist_ok=True)

    fetched = skipped = failed = 0
    for i, rider_id in enumerate(rider_ids, 1):
        cached = load_cache(rider_id)
        if cached and not REFETCH:
            skipped += 1
            continue

        url = f"{BASE}/{rider_id}"
        html = fetch(url)
        if not html:
            print(f"[{i}/{total}] FAILED: {rider_id}", flush=True)
            failed += 1
            continue

        parsed = parse_page(html)
        parsed["rider_id"] = rider_id
        save_cache(rider_id, parsed)

        first, last = parse_first_last(parsed.get("display_name") or "")
        update_rider(conn, rider_id, first, last, parsed.get("birthday"))
        conn.commit()

        fetched += 1
        if fetched % 100 == 0 or i % 500 == 0:
            print(f"[{i}/{total}] fetched={fetched} skipped={skipped} failed={failed}",
                  flush=True)

    n_applied = apply_cache_to_db(conn, rider_ids)
    print(f"Done. fetched={fetched} skipped={skipped} failed={failed} "
          f"db_updated={n_applied}/{total}")
    conn.close()


if __name__ == "__main__":
    main()
