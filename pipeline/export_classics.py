#!/usr/bin/env python3
"""Export the one-day classics as the frontend's aggregate "classics" race.

The DB holds 11 independent one-day races; the app shows ONE race whose
"stages" are those races, ordered by the date each was actually run — which is
what makes 2020 come out right, since COVID moved Il Lombardia to August, ahead
of Fleche and Liege.

The mechanics live in race_set_export.py, shared with the off-road set: the two
were 71% identical line-for-line, and the rest turned out to be configuration
rather than logic. See that module's header for what falls out of the data
instead of needing a flag.

This is deliberately separate from export_gc.py, which is built around one
edition = one race with N stages. The classics invert that (N editions of N
races = one displayed season), so sharing that code would mean contorting both.
See architecture.md.

Usage:
  python3 export_classics.py              # every year found
  python3 export_classics.py --year 2021
"""
import argparse
import sys

from race_set_export import RACE_SETS, run


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    args = ap.parse_args(argv)
    return run(RACE_SETS["classics"], args.year)


if __name__ == "__main__":
    sys.exit(main())
