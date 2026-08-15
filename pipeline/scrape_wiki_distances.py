#!/usr/bin/env python3
"""
Builds {giro,vuelta}_race_distances.json — official published race distance per
year, scraped from the Wikipedia infobox of each edition's article.

This is the Giro/Vuelta counterpart to the TDF's wiki_race_distances.json, and
exists for the same reason: an INDEPENDENT check on the DB. Summing
stages.distance_km always produces a plausible-looking number, so an edition
missing whole stages displays a total that is merely small, not obviously
wrong. The 2010 Vuelta sat two stages short and the only thing that ever caught
it was a human noticing in the UI.

Uses the MediaWiki API rather than fetching rendered pages: it returns raw
wikitext (so the infobox is a literal `| distance = 3467.0` instead of prose to
regex out of HTML) and accepts up to 50 titles per request, making the whole
Giro+Vuelta history ~4 requests instead of 189. Wikipedia has no bot challenge,
unlike PCS — see "Scraping PCS" in ai-context.md.

Only years present in race_editions are requested, so war-gap years are never
fetched.

Usage:
  python3 scrape_wiki_distances.py --race giro
  python3 scrape_wiki_distances.py --race vuelta
"""

import json
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request

from race_common import DB_PATH

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://en.wikipedia.org/w/api.php"

# Identifies the script per Wikipedia's API etiquette; they ask for a real
# contact so they can get in touch instead of silently blocking.
UA = "tdf-analytics/1.0 (race distance reconciliation; https://ericshiflet.com/tdf-analytics/)"

RACES = {
    "giro": {"db_name": "Giro d'Italia", "title": "{year} Giro d'Italia"},
    "vuelta": {"db_name": "Vuelta a España", "title": "{year} Vuelta a España"},
}

BATCH = 50

DISTANCE_RE = re.compile(r"^\s*\|\s*distance\s*=\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
UNIT_RE = re.compile(r"^\s*\|\s*unit\s*=\s*(\S+)", re.MULTILINE | re.IGNORECASE)

MI_TO_KM = 1.609344


def fetch(titles):
    """Wikitext for each title, keyed by the title we asked for."""
    q = {
        "action": "query", "prop": "revisions", "rvprop": "content",
        "rvslots": "main", "format": "json", "formatversion": "2",
        "redirects": "1", "titles": "|".join(titles),
    }
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)

    # Wikipedia may normalize ("Vuelta a Espana" -> "Vuelta a España") or
    # redirect. Both are reported as from/to pairs; chain them back so the
    # result is keyed by what the caller asked for, not what Wikipedia served.
    back = {}
    for kind in ("normalized", "redirects"):
        for m in data.get("query", {}).get(kind, []):
            back[m["to"]] = back.get(m["from"], m["from"])

    out = {}
    for page in data.get("query", {}).get("pages", []):
        asked = back.get(page["title"], page["title"])
        if page.get("missing"):
            out[asked] = None
            continue
        out[asked] = page["revisions"][0]["slots"]["main"]["content"]
    return out


def parse_distance(text):
    """(km, None) or (None, reason). Never guesses."""
    if text is None:
        return None, "no article"
    m = DISTANCE_RE.search(text)
    if not m:
        return None, "no distance in infobox"

    raw = m.group(1)
    # Strip wiki noise: refs, comments, templates, thousands separators.
    raw = re.sub(r"<ref.*?(/>|</ref>)", "", raw, flags=re.DOTALL)
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
    raw = raw.replace("{{", " ").replace("}}", " ").replace(",", "")
    num = re.search(r"\d+(?:\.\d+)?", raw)
    if not num:
        return None, f"unparseable distance {m.group(1)!r}"
    value = float(num.group(0))

    unit_m = UNIT_RE.search(text)
    unit = (unit_m.group(1) if unit_m else "km").lower()
    if unit.startswith("mi"):
        value *= MI_TO_KM
    elif not unit.startswith("km"):
        return None, f"unrecognized unit {unit!r}"

    # A Grand Tour is never 200 km or 20,000 km. A parse that lands outside
    # this is a mis-parse (a stage distance, a prize purse), not a short race —
    # store nothing rather than a number that would fail reconciliation
    # against correct DB data and send someone hunting a phantom defect.
    if not 500 <= value <= 8000:
        return None, f"implausible {value:.0f} km"
    return round(value, 1), None


def main():
    if "--race" not in sys.argv:
        sys.exit("usage: python3 scrape_wiki_distances.py --race {giro,vuelta}")
    race = sys.argv[sys.argv.index("--race") + 1]
    if race not in RACES:
        sys.exit(f"error: unknown race '{race}' (use {' or '.join(RACES)})")
    spec = RACES[race]

    conn = sqlite3.connect(DB_PATH)
    race_id = conn.execute("SELECT race_id FROM races WHERE name=?", (spec["db_name"],)).fetchone()[0]
    years = [r[0] for r in conn.execute(
        "SELECT year FROM race_editions WHERE race_id=? ORDER BY year", (race_id,))]
    conn.close()

    title_for = {y: spec["title"].format(year=y) for y in years}
    wikitext = {}
    for i in range(0, len(years), BATCH):
        chunk = [title_for[y] for y in years[i:i + BATCH]]
        wikitext.update(fetch(chunk))
        print(f"  fetched {min(i + BATCH, len(years))}/{len(years)}")

    distances, skipped = {}, []
    for y in years:
        km, reason = parse_distance(wikitext.get(title_for[y]))
        if km is None:
            skipped.append((y, reason))
        else:
            distances[str(y)] = km

    out_path = os.path.join(HERE, f"{race}_race_distances.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(distances, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")

    print(f"\nWrote {len(distances)} of {len(years)} {race} years -> {os.path.basename(out_path)}")
    if skipped:
        print(f"{len(skipped)} year(s) with no usable figure (left absent, never guessed):")
        for y, reason in skipped:
            print(f"  {y}: {reason}")


if __name__ == "__main__":
    main()
