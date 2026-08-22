#!/usr/bin/env python3
"""Export the Life Time off-road races as the frontend's aggregate "gravel" race.

The DB holds six independent races (races.race_type='gravel'); the app shows
ONE race whose "stages" are those races, ordered by the date each was actually
run. Same shape as the classics, and the mechanics are shared with them in
race_set_export.py.

Two things about this set are worth knowing, and neither needs code:

  * it awards nothing cumulative. The classics accumulate PCS points, which is
    what makes their bump chart a line worth following. These races award no
    points that PCS or anyone else records across the set, and inventing a
    scoring system (the Life Time Grand Prix's own 30-1 scale) would put a
    number in the archive that is not a fact about the race. Every result has
    pcs_points NULL, so the shared standings pass is a no-op and
    cumulativePoints ships as 0 — the frontend hides the metric.
  * a season is not a fixed set. 1994 holds one race (Leadville alone), 2001
    holds two, 2026 holds six, because these races were founded decades apart
    and only became a series in 2022. The date ordering renders that for free.

Usage:
  python3 export_gravel.py             # every year found
  python3 export_gravel.py --year 2024
"""
import argparse
import sys

from race_set_export import RACE_SETS, run


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    args = ap.parse_args(argv)
    return run(RACE_SETS["gravel"], args.year)


if __name__ == "__main__":
    sys.exit(main())
