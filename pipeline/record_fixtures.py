#!/usr/bin/env python3
"""
Record real PCS pages as gzipped fixtures for the scraper tests.

The scrapers are 16 of the pipeline's untested modules, and they are untested
because every one of them starts with a network fetch. Recording a handful of
real pages lets the parsing be tested offline — which is the part that has
actually gone wrong (a regex that silently returns None yields a NULL column,
not a crash).

Fixtures are gzipped because PCS pages are 40-60 KB of mostly boilerplate and
the repo should not carry half a megabyte of HTML. They are recorded verbatim
otherwise: trimming them would mean testing against a page shape that PCS never
actually serves.

Each entry below is chosen for a specific parsing edge case, not at random —
see FIXTURES. Re-record when PCS changes its markup and the tests start failing
for that reason (which is exactly the signal these fixtures exist to give):

  python3 record_fixtures.py            # record any that are missing
  python3 record_fixtures.py --force    # re-record everything
"""

import argparse
import gzip
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DIR = os.path.join(HERE, "test_fixtures", "pcs")
BASE = "https://www.procyclingstats.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# name -> (url path, why this page)
FIXTURES = {
    "vuelta_2021_stage_1": (
        "/race/vuelta-a-espana/2021/stage-1",
        "Modern stage: full results table, complete info block, profile icon. "
        "The baseline every parser must handle.",
    ),
    "vuelta_2021_stage_1_points": (
        "/race/vuelta-a-espana/2021/stage-1-points",
        "Sprint points page — a different table shape from the results page.",
    ),
    "vuelta_1989_stage_3a": (
        "/race/vuelta-a-espana/1989/stage-3a",
        "Lettered split-day slug. Confirms 'stage-3a' resolves to a real page "
        "and carries its own elevation, which is how the 1989 repair was made.",
    ),
    "vuelta_1991_stage_11_cancelled": (
        "/race/vuelta-a-espana/1991/stage-11",
        "CANCELLED stage: has date/route/vertical metres but NO results table. "
        "The scrapers must skip it rather than emit an empty stage, and "
        "insert_cancelled_stages must detect the cancellation text.",
    ),
    "giro_2022_stage_21": (
        "/race/giro-d-italia/2022/stage-21",
        "Final-stage ITT whose 'Distance:' info row reads 0 km while the header "
        "carries the real 17.4 km — the discrepancy patch_missing_distances "
        "exists to resolve.",
    ),
    "tdf_1986_stage_8": (
        "/race/tour-de-france/1986/stage-8",
        "Historical page used to prove the slug convention: PCS numbers this "
        "edition's split day sequentially, so DB stage 8 is stage-8 here, not "
        "stage-7. Departure/Arrival parsing is what verified that.",
    ),
    "vuelta_2015_stage_1_ttt": (
        "/race/vuelta-a-espana/2015/stage-1",
        "Modern TEAM time trial. Results are grouped by team in a "
        "<ul class='list ttt-results'> — team rank/name/time in the <li>, that "
        "team's riders in a nested <table> with empty per-rider time cells. The "
        "ordinary row parser finds almost nothing here, which is how 47 stages "
        "ended up holding a handful of results instead of a full field.",
    ),
    "tdf_1986_prologue": (
        "/race/tour-de-france/1986/prologue",
        "Prologue: slug is 'prologue', never 'stage-0'.",
    ),
}


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                html = r.read().decode("utf-8", errors="replace")
            if "Just a moment" in html and len(html) < 10000:
                print("    Cloudflare challenge")
                return None
            return html
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            print(f"    HTTP {e.code} (attempt {attempt + 1})")
            time.sleep(5)
        except Exception as e:
            print(f"    {e} (attempt {attempt + 1})")
            time.sleep(5)
    return None


def path_for(name):
    return os.path.join(FIXTURE_DIR, f"{name}.html.gz")


def load(name):
    """Read a recorded fixture. Used by the tests."""
    with gzip.open(path_for(name), "rt", encoding="utf-8") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    os.makedirs(FIXTURE_DIR, exist_ok=True)

    total = 0
    for name, (path, why) in FIXTURES.items():
        dest = path_for(name)
        if os.path.exists(dest) and not args.force:
            print(f"  have  {name}")
            total += os.path.getsize(dest)
            continue
        print(f"  fetch {name}  <- {path}")
        html = fetch(BASE + path)
        if html is None:
            print(f"    FAILED — not recorded")
            continue
        with gzip.open(dest, "wt", encoding="utf-8") as f:
            f.write(html)
        size = os.path.getsize(dest)
        total += size
        print(f"    {len(html):,} bytes -> {size:,} gzipped")
        time.sleep(2)

    print(f"\n{len(FIXTURES)} fixture(s), {total / 1024:.0f} KB on disk in "
          f"{os.path.relpath(FIXTURE_DIR, HERE)}")


if __name__ == "__main__":
    main()
