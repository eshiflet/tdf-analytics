#!/usr/bin/env python3
"""
Compare Vuelta a España GC winner times in our DB against PCS.

A thin wrapper: the implementation is shared with the other Grand Tour in
check_gc_times.py, which this and its sibling were 85% identical to.

Passes --write-winner-times, matching what this script has always done: it
is the only writer of vuelta_gc_winner_times.json, which export_gc.py reads.

Usage:
  python3 check_vuelta_gc_times.py            # all years
  python3 check_vuelta_gc_times.py 1990 1991  # specific years
"""
import sys

from check_gc_times import main as _main


def main():
    return _main(["--write-winner-times", "--race", "vuelta"] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
