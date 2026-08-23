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
import unicodedata
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from race_common import SOURCE_PCS, exit_on_help, record_provenance_bulk

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


def _fold(word: str) -> str:
    """Case- and accent-insensitive form, for MATCHING only — never for output."""
    word = unicodedata.normalize("NFD", word)
    return "".join(c for c in word if unicodedata.category(c) != "Mn").lower()


def split_from_both_orderings(full_name: str | None,
                              display_name: str | None) -> tuple[str, str] | None:
    """Split a name EXACTLY, using the two orderings PCS already gives us.

    Start lists carry "Lastname Firstname" (stored as riders.full_name); the
    rider page's <h1> carries "Firstname Lastname". One is a rotation of the
    other, and the rotation point IS the boundary — no guessing required.

    This supersedes parse_first_last() wherever it applies, and the difference
    is not marginal. Checked against 8,791 riders where the rotation is
    unambiguous, the particle heuristic gets 99 of them wrong, and they are not
    fixable by adding particles: "Pérez Francés", "Sánchez Camero",
    "Rodríguez Magro", "Holm Sørensen", "Vanden Berghen", "Dalla Bona" are
    two-word surnames with no particle in them at all. A list of little words
    cannot express "this surname happens to have two words"; the rotation can.

    Matching folds case and accents (the sources disagree on "de Koning" vs
    "De Koning"), but the OUTPUT is taken from the h1, which carries the
    canonical spelling. Returns None rather than guessing when the two strings
    are not rotations of each other — a middle name in one and not the other,
    or a spelling variant ("Dmitry" vs "Dmitri") — which is 1.6% of riders,
    left to parse_first_last().
    """
    if not full_name or not display_name:
        return None
    fw, dw = full_name.split(), display_name.split()
    if len(fw) != len(dw) or len(fw) < 2:
        return None
    ff, df = [_fold(w) for w in fw], [_fold(w) for w in dw]
    hits = [k for k in range(1, len(fw)) if ff[-k:] + ff[:-k] == df]
    if len(hits) != 1:            # 0 = not a rotation, >1 = repeated words
        return None
    k = hits[0]
    return " ".join(dw[:k]), " ".join(dw[k:])


def parse_first_last(display_name: str) -> tuple[str | None, str | None]:
    """Split "Firstname Lastname" into (first_name, last_name).

    Handles compound first names ("Juan Carlos Domínguez" → "Juan Carlos",
    "Domínguez"), surname particles ("Wout van Aert" → "Wout", "van Aert"),
    and both together ("Pedro de la Rosa" → "Pedro", "de la Rosa").

    FALLBACK ONLY since 2026-08-22 — prefer split_from_both_orderings(), which
    is exact and covers 98.4%. The PARTICLES list is deliberately unchanged:
    every case it gets wrong is a multi-word surname with no particle in it,
    which no list can express, and widening it now would only add risk on the
    1.6% where rotation cannot answer and there is no ground truth to check
    against.
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
    # COALESCE on birthday: a page that carries no birth date must not erase one
    # already stored. PCS often has no birthday for pre-war riders, so a
    # re-scrape or a --refetch would otherwise quietly null them — a dry run
    # over the cache found exactly that waiting to happen for
    # rider/ignacio-garcia-camacho2. Names are different: those come from the
    # h1 and are the reason we fetched, so they do overwrite.
    conn.execute(
        "UPDATE riders SET first_name=?, last_name=?, "
        "birthday=COALESCE(?, birthday) WHERE rider_id=?",
        (first_name, last_name, birthday, rider_id),
    )
    # The repo's rule is that every writer records where its value came from,
    # and the riders table was the one place with no provenance at all — 0 rows
    # for entity='riders' against 41,000 for stages and stage_results. These
    # values come from the PCS rider page's h1, so they are as attributable as
    # anything else here.
    #
    # entity_id is declared INTEGER but rider_id is TEXT. SQLite's type affinity
    # keeps a non-numeric string as TEXT, so it round-trips; the alternative —
    # inventing a surrogate integer key for riders — would make these rows
    # unjoinable to the table they describe. The orphan check in validate_db.py
    # knows to compare them as text.
    cur = conn.cursor()
    fields = ["first_name", "last_name"]
    if birthday is not None:
        fields.append("birthday")     # COALESCEd above; only claim what we set
    record_provenance_bulk(cur, "riders", rider_id, fields, SOURCE_PCS,
                           source_ref=f"{BASE}/{rider_id}",
                           script="scrape_rider_details.py")


# PCS writes an unknown given name as "?", "??", "." or "-" rather than leaving
# it out, so those arrive looking like names. Storing one makes displayName()
# render "? Pujol", which is worse than the surname alone — the app already
# falls back to the surname when there is no first name, and that is the honest
# output for a rider whose given name nobody recorded. 14 riders had one.
#
# An INITIAL is different and is kept: "C. Terruzzi" is what is known about
# that rider, not a placeholder for it.
UNKNOWN_NAME_MARKERS = {"?", "??", "???", ".", "-", "--", "_"}


def _drop_placeholder(name: str | None) -> str | None:
    return None if name is None or name.strip() in UNKNOWN_NAME_MARKERS else name


def split_for(conn: sqlite3.Connection, rider_id: str,
              display_name: str | None) -> tuple[str | None, str | None]:
    """The one place a name gets split. Exact rotation against the stored
    full_name where possible, particle heuristic otherwise, and PCS's
    unknown-name markers dropped rather than stored as names."""
    if not display_name:
        return (None, None)
    row = conn.execute("SELECT full_name FROM riders WHERE rider_id=?",
                       (rider_id,)).fetchone()
    full = row["full_name"] if row else None
    exact = split_from_both_orderings(full, display_name)
    first, last = exact if exact else parse_first_last(display_name)
    return _drop_placeholder(first), _drop_placeholder(last)


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
    # Mirror update_rider's COALESCE, or the change table advertises a birthday
    # loss the write no longer performs.
    new_b = birthday if birthday is not None else old_b
    if (old_f, old_l, old_b) == (first_name, last_name, new_b):
        return None
    birthday = new_b
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
    """Read one cached rider, treating a damaged file as simply absent.

    The cache IS the resumability of a multi-hour run, and the thing most
    likely to interrupt one — a shutdown, a battery, a kill — is also the thing
    most likely to leave a half-written file behind. Raising here would let a
    single truncated byte abort the resume for all 5,000 riders, so a corrupt
    entry is deleted and re-fetched instead.
    """
    p = cache_path(rider_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        print(f"  discarding damaged cache entry {os.path.basename(p)}", flush=True)
        try:
            os.remove(p)
        except OSError:
            pass
        return None


def save_cache(rider_id: str, data: dict) -> None:
    """Write atomically: full file to a temp name, then rename over the target.

    os.replace() is atomic on POSIX and Windows, so an interrupted run leaves
    either the old entry or the new one, never half of either. Writing in place
    is what creates the truncated file load_cache() now has to defend against.
    """
    slug = rider_id.removeprefix("rider/")
    os.makedirs(CACHE_DIR, exist_ok=True)
    p = os.path.join(CACHE_DIR, f"{slug}.json")
    tmp = f"{p}.tmp{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


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
        first, last = split_for(conn, rider_id, cached["display_name"])
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
    exit_on_help(__doc__)
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

        first, last = split_for(conn, rider_id, parsed.get("display_name"))
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
