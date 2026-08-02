#!/usr/bin/env python3
"""
Write stage JSON produced by the browser-fetch re-scrape (see ai-context.md,
2026-08-01 ditto-mark incident) into giro_scrapes/YEAR or vuelta_scrapes/YEAR,
matching scrape_giro.py/scrape_vuelta.py's exact per-stage file schema.

Usage:
  python3 write_browser_scrape.py --race giro --year 1920 stages.json

Deletes any existing stage_N.json for that year first (full redo — old files
predate the hidden-span parsing fix and must not be left mixed with new ones).
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", required=True, choices=["giro", "vuelta"])
    ap.add_argument("--year", required=True, type=int)
    ap.add_argument("stages_json")
    args = ap.parse_args()

    scrapes_dir = os.path.join(HERE, f"{args.race}_scrapes", str(args.year))
    os.makedirs(scrapes_dir, exist_ok=True)

    for f in os.listdir(scrapes_dir):
        if f.startswith("stage_") and f.endswith(".json"):
            os.remove(os.path.join(scrapes_dir, f))

    with open(args.stages_json, encoding="utf-8") as f:
        stages = json.load(f)

    for stage in stages:
        out_path = os.path.join(scrapes_dir, f"stage_{stage['n']}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(stage, f, ensure_ascii=False)

    print(f"{args.race} {args.year}: wrote {len(stages)} stage files to {scrapes_dir}")


if __name__ == "__main__":
    main()
