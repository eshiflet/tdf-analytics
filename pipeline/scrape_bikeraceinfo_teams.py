#!/usr/bin/env python3
"""Scrape rider->team membership for the one-day classics from bikeraceinfo.com.

Why this exists: PCS carries almost no team attribution for the older classics
(2% of riders in the 1940s, ~32% in the 50s/60s, 72% in the 70s), which leaves
the team-grouped by-Stage Table with little to group. bikeraceinfo publishes the
team in its results lists, so this fills the gap from a second source.

It is NOT a source of results. Only team membership is taken; ranks and times
already in the DB are left untouched, and this script never writes to the DB at
all — `patch_classics_teams.py` does that, with name verification.

bikeraceinfo serves plain HTTP with no bot challenge (unlike PCS), so this runs
as an ordinary script. Be polite: DELAY between requests, and it caches every
page to disk so a re-run costs nothing.

Page shape — results are an ordered list, one <li> per rank, team optional:

    <li>Jean Forestier (Follis-Dunlop) 6hr 6min 42sec.</li>
    <li><a href="...">Fausto Coppi</a> (Bianchi-Pirelli) @ 15sec</li>
    <li>Ernest Sterckx  s.t.</li>            <- no team, common in this era

Each race indexes its years differently (`pr1955.html`, `fleche1955.html`,
`1955-liege-bastogne-liege.html`), so year pages are DISCOVERED from each race's
index rather than assembled from a guessed pattern.

Usage:
  python3 scrape_bikeraceinfo_teams.py --discover          # build the URL map
  python3 scrape_bikeraceinfo_teams.py --years 1946-1989   # fetch + parse
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.join(HERE, "bikeraceinfo_teams")
CACHE = os.path.join(OUT_ROOT, "_pages")
URLMAP = os.path.join(OUT_ROOT, "_urlmap.json")
BASE = "https://www.bikeraceinfo.com/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/150.0.0.0 Safari/537.36"}
DELAY = float(os.environ.get("BRI_DELAY", "1.0"))

# Our race slug -> that race's index page on bikeraceinfo. Strade Bianche has no
# page there and needs none: it starts in 2007, where PCS team data is 100%.
INDEXES = {
    "omloop-het-nieuwsblad": "classics/het-nieuwsblad/het-nieuwsblad.html",
    "milano-sanremo":        "classics/Milan-San%20Remo/milan-san-remo-index.html",
    "gent-wevelgem":         "classics/Ghent-Wevelgem/ghentindex.html",
    "ronde-van-vlaanderen":  "classics/Tour%20of%20Flanders/flandndx.html",
    "paris-roubaix":         "classics/paris-roubaix/paris-roubaix-index.html",
    "amstel-gold-race":      "classics/Amstel%20Gold%20Race/amstelindex.html",
    "la-fleche-wallonne":    "classics/Fleche%20Wallonne/flecheindex.html",
    "liege-bastogne-liege":  "classics/Liege-Bastogne-Liege/liege-index.html",
    "san-sebastian":         "classics/San%20Sebastian/sebastianindex.html",
    "il-lombardia":          "classics/Tour%20of%20Lombardy/lombindx.html",
}


def fetch(url, cache_key=None):
    """GET with an on-disk cache, so re-runs cost bikeraceinfo nothing."""
    if cache_key:
        os.makedirs(CACHE, exist_ok=True)
        path = os.path.join(CACHE, cache_key)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read(), True
    req = urllib.request.Request(url, headers=HEADERS)
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    if cache_key:
        with open(os.path.join(CACHE, cache_key), "w", encoding="utf-8") as f:
            f.write(html)
    time.sleep(DELAY)
    return html, False


def discover():
    """year -> absolute URL, per race, read off each race's own index.

    Generic on purpose: the year appears as a suffix (`pr1955`), an infix
    (`Amstel-Gold-Race-1966`) or a prefix (`1955-liege-bastogne-liege`), so any
    local .html link carrying a plausible year is a candidate. Where a race
    links the same year twice, the SHORTEST path wins — the long ones are
    rider-history essays, not results pages.
    """
    urlmap = {}
    for race, idx in INDEXES.items():
        idx_url = urllib.parse.urljoin(BASE, idx)
        try:
            html, _ = fetch(idx_url, cache_key=f"index_{race}.html")
        except Exception as e:
            print(f"  {race:24} INDEX ERROR {e}")
            continue
        years = {}
        for href in set(re.findall(r'href="([^"]+\.html)"', html)):
            if href.startswith(("http", "mailto", "#")) or href.startswith("../"):
                continue
            m = re.search(r"(18|19|20)\d{2}", href)
            if not m:
                continue
            year = int(m.group(0))
            if not (1890 <= year <= 2030):
                continue
            if year not in years or len(href) < len(years[year]):
                years[year] = href
        urlmap[race] = {str(y): urllib.parse.urljoin(idx_url, h)
                        for y, h in sorted(years.items())}
        ys = sorted(years)
        print(f"  {race:24} {len(ys):>3} years  "
              f"{ys[0] if ys else '-'}-{ys[-1] if ys else '-'}")
    os.makedirs(OUT_ROOT, exist_ok=True)
    with open(URLMAP, "w", encoding="utf-8") as f:
        json.dump(urlmap, f, indent=1, sort_keys=True)
    total = sum(len(v) for v in urlmap.values())
    print(f"\nwrote {URLMAP} — {total} race-years discoverable")
    return urlmap


# A rider entry ends with its time or gap. These are the terminators seen:
#   "s.t."              same time as the rider above
#   "@ 15sec" / "@ 5min 43sec" / "@ 1hr 2min 3sec"
#   "6hr 6min 42sec"    the winner's absolute time
TERMINATOR = re.compile(
    r"(?:s\.\s*t\.?|@\s*(?:\d+\s*hr\s*)?(?:\d+\s*min\s*)?\d+\s*sec"
    r"|(?:\d+\s*hr\s*)(?:\d+\s*min\s*)?(?:\d+\s*sec)?)",
    re.I)


def split_entries(text):
    """One <li> can hold SEVERAL riders — split it into one entry each.

    bikeraceinfo frequently packs a whole group that finished together into a
    single list item:

        "Emilio Corci-Torti s.t. Renzo Soldani (Legnano) s.t. Gino Sciardis
         s.t. Serse Coppi (Bianchi-Ursus) s.t. Sergio Pagliazzi (Atala) s.t."

    That is five riders (five ranks) in one <li>. Treating list position as
    rank would therefore shift every rank after it — Il Lombardia 1949 drifts
    by four from rank 20 on — and quietly attribute the wrong team to the
    wrong rider. Splitting on the time terminator recovers the real sequence.
    """
    entries, pos = [], 0
    for m in TERMINATOR.finditer(text):
        chunk = text[pos:m.start()].strip(" .,;")
        if chunk:
            entries.append(chunk)
        pos = m.end()
    tail = text[pos:].strip(" .,;")
    if tail:
        entries.append(tail)
    return entries


def parse_results(html):
    """[(rank, name, team_or_None)] from the results <ol>.

    Takes the LONGEST <ol> on the page: these pages also carry short ordered
    lists (podium summaries, footnotes) that would otherwise be mistaken for
    the result. Rank comes from position in the flattened entry sequence, NOT
    from <li> index — see split_entries.
    """
    ols = re.findall(r"<ol[^>]*>(.*?)</ol>", html, re.S | re.I)
    if not ols:
        return []
    body = max(ols, key=len)
    out = []
    rank = 0
    for li in re.findall(r"<li[^>]*>(.*?)</li>", body, re.S | re.I):
        text = re.sub(r"<[^>]+>", "", li)
        text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                    .replace("&quot;", '"').replace("&#39;", "'"))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        for entry in split_entries(text):
            # "Name (Team)" — the time/gap has already been consumed as the
            # entry terminator by split_entries.
            m = re.match(r"^(.*?)\s*\(([^)]*)\)", entry)
            if m:
                name, team = m.group(1).strip(), m.group(2).strip()
            else:
                name, team = entry.strip(), None
            name = name.strip(" .,;")
            if not name or len(name) < 3:
                continue
            rank += 1
            out.append((rank, name, team or None))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true", help="rebuild the URL map only")
    ap.add_argument("--years", help="YYYY-YYYY range to fetch (default: all discovered)")
    ap.add_argument("--race", help="one race slug")
    args = ap.parse_args(argv)

    if args.discover or not os.path.exists(URLMAP):
        print("discovering year pages per race:")
        urlmap = discover()
        if args.discover:
            return 0
    else:
        with open(URLMAP, encoding="utf-8") as f:
            urlmap = json.load(f)

    lo, hi = 0, 9999
    if args.years:
        m = re.match(r"(\d{4})-(\d{4})$", args.years)
        if not m:
            print("--years must look like 1946-1989")
            return 1
        lo, hi = int(m.group(1)), int(m.group(2))

    fetched = cached = failed = 0
    totals = []
    for race, years in sorted(urlmap.items()):
        if args.race and race != args.race:
            continue
        for year, url in sorted(years.items()):
            y = int(year)
            if not (lo <= y <= hi):
                continue
            try:
                html, was_cached = fetch(url, cache_key=f"{race}_{year}.html")
            except Exception as e:
                print(f"  {race} {year}: FETCH ERROR {e}")
                failed += 1
                continue
            cached += was_cached
            fetched += not was_cached
            rows = parse_results(html)
            with_team = sum(1 for _, _, t in rows if t)
            out_dir = os.path.join(OUT_ROOT, race)
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, f"{year}.json"), "w", encoding="utf-8") as f:
                json.dump({"race": race, "year": y, "source_ref": url,
                           "results": rows}, f, ensure_ascii=False)
            totals.append((race, y, len(rows), with_team))

    print(f"\n{len(totals)} race-years parsed "
          f"({fetched} fetched, {cached} from cache, {failed} failed)")
    rows_all = sum(t[2] for t in totals)
    team_all = sum(t[3] for t in totals)
    if rows_all:
        print(f"  {rows_all:,} result lines, {team_all:,} with a team "
              f"({100*team_all/rows_all:.0f}%)")
    empty = [(r, y) for r, y, n, _ in totals if n == 0]
    if empty:
        print(f"  {len(empty)} page(s) yielded no results list: {empty[:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
