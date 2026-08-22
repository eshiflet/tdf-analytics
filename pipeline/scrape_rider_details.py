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
  python3 scrape_rider_details.py                      # ALL uncached riders
  python3 scrape_rider_details.py --missing            # only riders whose
                                                       #   first/last is NULL
  python3 scrape_rider_details.py --missing --race gravel --dry-run
  python3 scrape_rider_details.py --db-only            # apply cache, no network
  python3 scrape_rider_details.py --refetch            # re-fetch cached slugs
  SCRAPE_DELAY=1.5 python3 scrape_rider_details.py --missing --limit 50

A bare run walks every rider in the DB. The cache predates the classics and
gravel expansions, so that is now thousands of live requests — scope it with
--missing/--race/--limit, and read the change table from --dry-run first.
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
# Scope + safety, added 2026-08-22. Without --missing this walks all ~17,700
# riders; the cache predates the classics and gravel expansions, so a bare run
# now means thousands of live PCS requests. --dry-run fetches and caches but
# writes nothing, so the change table can be read before the DB moves.
MISSING_ONLY = "--missing" in sys.argv
DRY_RUN = "--dry-run" in sys.argv


def _flag_value(name: str, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


LIMIT = int(_flag_value("--limit", 0) or 0)
RACE = _flag_value("--race")        # tour|giro|vuelta|classics|gravel


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

# PCS answers an unknown rider slug with HTTP **200** and a "Page not found"
# body, so fetch() cannot tell it apart from a real page. Its <h1> is the error
# text, which parse_page() used to hand back as the rider's name: a dry run over
# 28 gravel riders produced first_name='Page not', last_name='found' for
# rider/kvalsten. Over the ~5,300 riders still missing a name split, every dead
# slug would have written that. The word "born" appears in the error page too,
# so the birthday is no help either — the title/h1 is the only signal.
NOT_FOUND_TITLES = {"page not found", "404", "not found"}


def parse_page(html: str) -> dict:
    """Extract display_name and birthday from a PCS rider page.

    Returns display_name=None for the not-found page, which makes every
    downstream step skip the rider rather than store the error text as a name.
    """
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html)
    display_name = h1.group(1).strip() if h1 else None

    title = re.search(r"<title[^>]*>(.*?)</title>", html)
    looks_missing = (
        (display_name or "").strip().lower() in NOT_FOUND_TITLES
        or (title.group(1).strip().lower() if title else "") in NOT_FOUND_TITLES
    )
    if looks_missing:
        return {"display_name": None, "birthday": None, "not_found": True}

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

RACE_TYPE_FOR = {"classics": "one_day", "gravel": "gravel"}


def get_all_rider_ids(conn: sqlite3.Connection) -> list[str]:
    """Riders to consider, narrowed by --missing and --race.

    --missing is the useful default for a top-up run: it asks only for riders
    whose first_name or last_name is still NULL, which is exactly the set whose
    display falls back to PCS's "Lastname Firstname" ordering in the app.
    """
    where, params = [], []
    if MISSING_ONLY:
        where.append("(r.first_name IS NULL OR r.last_name IS NULL)")
    if RACE:
        rt = RACE_TYPE_FOR.get(RACE)
        if rt:
            where.append("""r.rider_id IN (
                SELECT sr.rider_id FROM stage_results sr
                JOIN stages s USING(stage_id)
                JOIN race_editions e USING(edition_id)
                JOIN races ra USING(race_id) WHERE ra.race_type = ?)""")
            params.append(rt)
        else:
            where.append("""r.rider_id IN (
                SELECT sr.rider_id FROM stage_results sr
                JOIN stages s USING(stage_id)
                JOIN race_editions e USING(edition_id)
                JOIN races ra USING(race_id) WHERE ra.name = ?)""")
            params.append(RACE)
    sql = "SELECT r.rider_id FROM riders r"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.rider_id"
    cur = conn.cursor()
    cur.execute(sql, params)
    ids = [r[0] for r in cur.fetchall()]
    return ids[:LIMIT] if LIMIT else ids


def update_rider(conn: sqlite3.Connection, rider_id: str,
                 first_name: str | None, last_name: str | None,
                 birthday: str | None) -> None:
    if DRY_RUN:
        return
    conn.execute(
        "UPDATE riders SET first_name=?, last_name=?, birthday=? WHERE rider_id=?",
        (first_name, last_name, birthday, rider_id),
    )


def describe_change(conn: sqlite3.Connection, rider_id: str,
                    first_name, last_name, birthday) -> tuple | None:
    """One row of the change table: what is stored now vs what PCS says.

    Returns None when nothing would move. Separates a NULL-fill from an
    overwrite, because they carry very different risk — an overwrite is
    replacing a value somebody may have checked.
    """
    row = conn.execute(
        "SELECT full_name, first_name, last_name, birthday FROM riders WHERE rider_id=?",
        (rider_id,)).fetchone()
    if row is None:
        return None
    full, old_f, old_l, old_b = row["full_name"], row["first_name"], row["last_name"], row["birthday"]
    if (old_f, old_l, old_b) == (first_name, last_name, birthday):
        return None
    kind = "fill" if (old_f is None or old_l is None) else "OVERWRITE"
    return (kind, rider_id, full, f"{old_f} / {old_l}", f"{first_name} / {last_name}",
            f"{old_b} -> {birthday}" if old_b != birthday else "")


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
    changes = []
    for rider_id in rider_ids:
        cached = load_cache(rider_id)
        if not cached or not cached.get("display_name"):
            continue
        first, last = parse_first_last(cached["display_name"])
        row = describe_change(conn, rider_id, first, last, cached.get("birthday"))
        if row:
            changes.append(row)
        update_rider(conn, rider_id, first, last, cached.get("birthday"))
        updated += 1
    if not DRY_RUN:
        conn.commit()
    print_changes(changes)
    return updated


def print_changes(changes: list[tuple]) -> None:
    """Every bulk edit here prints what it did, NULL-fills separated from
    overwrites. A silent 5,000-row update is how a bad parse gets noticed a
    month later."""
    if not changes:
        print("no changes")
        return
    fills = [c for c in changes if c[0] == "fill"]
    over = [c for c in changes if c[0] == "OVERWRITE"]
    for label, rows in (("NULL-fill", fills), ("OVERWRITE", over)):
        if not rows:
            continue
        print(f"\n{label}: {len(rows)}")
        print(f"  {'rider_id':38} {'full_name':30} {'stored':28} -> {'from PCS':28}")
        for _, rid, full, old, new, bday in rows[:60]:
            print(f"  {rid:38} {full[:30]:30} {old[:28]:28} -> {new[:28]:28} {bday}")
        if len(rows) > 60:
            print(f"  ... and {len(rows)-60} more")


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
        save_cache(rider_id, parsed)   # cached even on a dry run, so the
                                       # follow-up apply needs no re-fetch

        first, last = parse_first_last(parsed.get("display_name") or "")
        update_rider(conn, rider_id, first, last, parsed.get("birthday"))
        if not DRY_RUN:
            conn.commit()

        fetched += 1
        if fetched % 100 == 0 or i % 500 == 0:
            print(f"[{i}/{total}] fetched={fetched} skipped={skipped} failed={failed}",
                  flush=True)

    n_applied = apply_cache_to_db(conn, rider_ids)
    print(f"\nDone{' (DRY RUN — nothing written)' if DRY_RUN else ''}. "
          f"fetched={fetched} skipped={skipped} failed={failed} "
          f"db_updated={0 if DRY_RUN else n_applied}/{total}")
    conn.close()


if __name__ == "__main__":
    main()
