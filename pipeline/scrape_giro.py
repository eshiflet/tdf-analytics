#!/usr/bin/env python3
"""
Scrape Giro d'Italia stage results from procyclingstats.com.

A thin wrapper: the implementation is shared with the other Grand Tour in
scrape_race.py, which this and its sibling were 95% identical to. Kept as its
own entry point because every recipe in ai-context.md names it, and because the
Cloudflare history below is specific to what this script has been through.

Produces per-stage JSON in giro_scrapes/YEAR/stage_N.json, compatible with
ingest_race.py --race giro and build_giro_points.py.

Usage:
  python3 scrape_giro.py 1990-2000
  python3 scrape_giro.py 1990-2000 --resume    # skip years already scraped

Cloudflare (2026-08): PCS now challenges plain HTTP requests even for
historical years, not just the live race. Solve the challenge once in a real
browser, then set CF_CLEARANCE to that session's `cf_clearance` cookie value
(DevTools → Network → any procyclingstats.com request → Request Headers →
Cookie) so this script's requests ride on that browser's clearance:

  CF_CLEARANCE=xxxxx python3 scrape_giro.py 1990-2000

The cookie expires after a while (commonly 30min-2h) — once it does, every
request starts 403ing again and the script exits with a clear message
instead of silently retrying forever. Get a fresh cookie and re-run
(add --resume once a year has fully completed to skip it next time).

WARNING (verified 2026-08-13): the CF_CLEARANCE workflow described above NO
LONGER WORKS, for any year. PCS returns 403 with `cf-mitigated: challenge`
and `cType: 'managed'` even given a cookie minted seconds earlier plus that
browser's exact User-Agent, because clearance is bound to the client's
TLS fingerprint and urllib cannot present Chrome's. Defeating that needs a
TLS-impersonation library, which is out of bounds. Use the DevTools-snippet
route instead -- see ai-context.md's "Scraping a live/in-progress race from
PCS", and parse_classics_bundle.py for the bundle format.
"""
import sys

from scrape_race import main as _main


def main():
    return _main(["--race", "giro"] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
