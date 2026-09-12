#!/usr/bin/env python3
"""
Fetch PCS rider pages CONCURRENTLY into the scrape_rider_details.py cache.

Why this exists rather than a flag on scrape_rider_details.py: that script
fetches and writes the DB in one serial loop, which is the right shape when
you are topping up a few hundred riders. 6,304 riders at its 2s delay is
3.5 hours, and the delay is the point — it is politeness, not latency. The
work is IO-bound and embarrassingly parallel, so N workers each observing the
same per-request delay is N times the throughput at the same per-connection
courtesy.

This script ONLY warms the cache. It never touches the database. The apply is
scrape_rider_details.apply_cache_to_db(), imported and called with exactly the
slugs fetched here, so the DB write stays on the path that already records
provenance and prints the NULL-fill/overwrite change table.

Scoping it to the fetched slugs matters. apply_cache_to_db() OVERWRITES
first_name/last_name (deliberately — they come from the page h1), so pointing
it at every rider would re-stamp 14,000 names and their provenance rows for
the sake of 6,304 birthdays.

Usage:
  python3 warm_rider_cache.py --missing-birthday --skip-no-pcs --apply
  python3 warm_rider_cache.py --missing-birthday --apply
  python3 warm_rider_cache.py --missing-birthday --apply --workers 6
  WORKERS=4 SCRAPE_DELAY=1.5 python3 warm_rider_cache.py --missing-birthday
  python3 warm_rider_cache.py --apply-only                   # cache -> DB only
"""

import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _flag(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


WORKERS = int(_flag("--workers") or os.environ.get("WORKERS", "5"))
LIMIT = int(_flag("--limit") or 0)
# fetch() sleeps this AFTER each request, inside the worker thread, so the
# effective request rate is WORKERS/DELAY per second. Default 5/1.5 ~= 3.3/s.
os.environ.setdefault("SCRAPE_DELAY", "1.5")

import scrape_rider_details as srd      # noqa: E402  (env must be set first)
from race_common import exit_on_help    # noqa: E402

APPLY = "--apply" in sys.argv
APPLY_ONLY = "--apply-only" in sys.argv
DRY_RUN = "--dry-run" in sys.argv
MISSING_BIRTHDAY = "--missing-birthday" in sys.argv
REFETCH = "--refetch" in sys.argv
# Measured 2026-09-12 on a random sample of 40 birthday-null riders: 38 came
# back "Page not found". The reason is structural, not a scraping backlog —
# gravel rider_ids are slugified from Life Time result sheets, not taken from
# PCS, so there is no page at that slug and never will be. All 3,806
# gravel-only riders are birthday-null, as are all 936 riders that carry no
# results at all. Fetching those 4,742 is ~4,700 requests to PCS for a
# guaranteed zero. This flag is what keeps a bulk run pointed at the 1,562
# riders who at least appear in a race PCS covers.
SKIP_NO_PCS = "--skip-no-pcs" in sys.argv


def targets(conn) -> list[str]:
    """Riders to fetch: missing the field we are after, and not already cached.

    Skipping cached slugs is what makes this resumable — kill it and re-run and
    it picks up where it stopped, because the cache IS the progress record.
    """
    where = []
    if MISSING_BIRTHDAY:
        where.append("(birthday IS NULL OR birthday = '')")
    if SKIP_NO_PCS:
        where.append("""rider_id IN (
            SELECT sr.rider_id FROM stage_results sr
            JOIN stages s USING(stage_id)
            JOIN race_editions e USING(edition_id)
            JOIN races ra USING(race_id)
            WHERE ra.race_type <> 'gravel')""")
    sql = "SELECT rider_id FROM riders"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY rider_id"
    ids = [r[0] for r in conn.execute(sql)]
    if not REFETCH:
        ids = [i for i in ids if srd.load_cache(i) is None]
    return ids[:LIMIT] if LIMIT else ids


def main() -> None:
    exit_on_help(__doc__)
    conn = sqlite3.connect(srd.DB_PATH)
    conn.row_factory = sqlite3.Row

    if APPLY_ONLY:
        ids = [r[0] for r in conn.execute("SELECT rider_id FROM riders ORDER BY rider_id")]
        ids = [i for i in ids if srd.load_cache(i) is not None]
        srd.DRY_RUN = DRY_RUN
        n = srd.apply_cache_to_db(conn, ids)
        print(f"Applied {n} cached riders to DB{' (DRY RUN)' if DRY_RUN else ''}")
        conn.close()
        return

    ids = targets(conn)
    print(f"{len(ids)} rider(s) to fetch, {WORKERS} workers, "
          f"{srd.DELAY}s delay per request per worker "
          f"(~{WORKERS / srd.DELAY:.1f} req/s)", flush=True)
    if not ids:
        conn.close()
        return

    lock = threading.Lock()
    counts = {"ok": 0, "no_bday": 0, "not_found": 0, "failed": 0}
    started = time.time()

    def work(rider_id: str):
        html = srd.fetch(f"{srd.BASE}/{rider_id}")
        if not html:
            return rider_id, None
        parsed = srd.parse_page(html)
        parsed["rider_id"] = rider_id
        # Cache the not-found answer too. PCS returns HTTP 200 with a "Page not
        # found" body for a dead slug, so without this every re-run re-fetches
        # every dead slug forever.
        srd.save_cache(rider_id, parsed)
        return rider_id, parsed

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(work, i) for i in ids]
        for n, fut in enumerate(as_completed(futures), 1):
            try:
                _, parsed = fut.result()
            except Exception as exc:
                with lock:
                    counts["failed"] += 1
                print(f"  worker error: {exc}", flush=True)
                continue
            with lock:
                if parsed is None:
                    counts["failed"] += 1
                elif parsed.get("not_found"):
                    counts["not_found"] += 1
                elif parsed.get("birthday"):
                    counts["ok"] += 1
                else:
                    counts["no_bday"] += 1
                if n % 250 == 0 or n == len(ids):
                    el = time.time() - started
                    rate = n / el if el else 0
                    print(f"[{n}/{len(ids)}] {counts}  {rate:.1f}/s  "
                          f"eta {(len(ids) - n) / rate / 60:.1f}m" if rate else
                          f"[{n}/{len(ids)}] {counts}", flush=True)

    print(f"\nFetched {len(ids)}: {counts} in {(time.time() - started) / 60:.1f}m",
          flush=True)

    if APPLY or DRY_RUN:
        srd.DRY_RUN = DRY_RUN
        n = srd.apply_cache_to_db(conn, ids)
        print(f"Applied {n}/{len(ids)}{' (DRY RUN — nothing written)' if DRY_RUN else ''}")
    else:
        print("Cache warmed. Re-run with --apply to write the DB.")
    conn.close()


if __name__ == "__main__":
    main()
