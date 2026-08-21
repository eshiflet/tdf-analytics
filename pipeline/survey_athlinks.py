#!/usr/bin/env python3
"""One-off reconnaissance: dump every course + division of every edition of the
six Life Time off-road races, so the field-selection rules in
scrape_athlinks.py can be written from evidence instead of assumption.

Not part of the pipeline. Kept because re-deriving this by hand is an hour.
"""
import json
import sys

from athlinks_api import editions, event_metadata

MASTERS = {
    "sea-otter": 36141,
    "unbound": 174195,
    "leadville": 219291,
    "chequamegon": 32709,
    "little-sugar": 381583,
    "big-sugar": 359937,
}


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    out = {}
    for slug, mid in MASTERS.items():
        if only and slug != only:
            continue
        print(f"\n########## {slug} (master {mid})", flush=True)
        evs = editions(mid)
        out[slug] = []
        for ev in evs:
            meta = event_metadata(ev["event_id"])
            courses = []
            for r in (meta or {}).get("races", []):
                courses.append({
                    "course_id": r.get("id"),
                    "name": r.get("name"),
                    "km": round(((r.get("distance") or {}).get("meters") or 0) / 1000, 2),
                    "hidden": r.get("hidden"),
                    "divisions": [d.get("name") for d in (r.get("divisions") or [])],
                })
            rec = {**ev, "courses": courses}
            out[slug].append(rec)
            print(f"  {ev['date']}  ev={ev['event_id']:<8} n={ev['result_count']:<6} {ev['name'][:52]}",
                  flush=True)
            for c in courses:
                divs = [d for d in c["divisions"] if d]
                flag = ""
                low = (c["name"] or "").lower()
                if any(k in low for k in ("elite", "pro")):
                    flag = "  <-- ELITE COURSE"
                elite_div = [d for d in divs
                             if any(k in d.lower() for k in ("elite", "pro", "grand prix"))]
                if elite_div:
                    flag += f"  <-- DIV {elite_div}"
                print(f"       [{c['course_id']}] {c['km']:>8} km  {c['name']}"
                      f"   ({len(divs)} divs){flag}", flush=True)
    with open("gravel_scrapes/_survey.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("\nwrote gravel_scrapes/_survey.json")


if __name__ == "__main__":
    main()
