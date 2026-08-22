#!/usr/bin/env python3
"""
Compare Giro d'Italia GC winner times in our DB against PCS.

A thin wrapper: the implementation is shared with the other Grand Tour in
check_gc_times.py, which this and its sibling were 85% identical to.

Does NOT pass --write-winner-times, matching what this script has always
done. See check_gc_times.py for why that differs from the Vuelta's, and for
the fact that nothing in this repo currently writes giro_gc_winner_times.json.

Usage:
  python3 check_giro_gc_times.py            # all years
  python3 check_giro_gc_times.py 1990 1991  # specific years
"""
import sys

from check_gc_times import main as _main


def main():
    return _main(["--race", "giro"] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
