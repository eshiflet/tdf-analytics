#!/usr/bin/env python3
"""
Scrape vertical_meters and profile_score for Giro d'Italia stages from PCS.

A thin wrapper: the implementation is shared with the other Grand Tour in
scrape_stage_info.py, which this and its sibling were 94% identical to. Kept as
its own entry point because ai-context.md's recipes name it.

Usage:
  python3 scrape_giro_stage_info.py 2021-2025
  python3 scrape_giro_stage_info.py 2021-2025 --dry-run
"""
import sys

from scrape_stage_info import main as _main


def main():
    return _main(["--race", "giro"] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
