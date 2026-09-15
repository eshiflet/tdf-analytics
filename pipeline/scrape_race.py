#!/usr/bin/env python3
"""
Scrape Grand Tour stage results from procyclingstats.com.

Serves the Giro and the Vuelta from one implementation. They were two files,
scrape_giro.py and scrape_vuelta.py, measured 95% identical across 422 lines —
and everything that differed was the PCS URL slug, the output directory and the
words printed to the terminal. None of it was logic.

That mattered beyond tidiness. The parsing here is fixture-tested
(test_scrapers.py against test_fixtures/), but only ever through the Vuelta
copy: the Giro's identical 584 lines were untested, so a fix applied to one and
not the other would not have failed anything. One implementation means one set
of tests covers both.

Produces per-stage JSON in <race>_scrapes/YEAR/stage_N.json, compatible with
ingest_race.py and build_<race>_points.py.

Every scraped year is run through fix_name_swaps --replay before this exits.
PCS reproduces its adjacent-row name swaps on every request, so a re-scrape
transposes any previously-repaired pair again — and since the scrape file is
the source of truth, nothing downstream would know. Recorded repairs go
straight back; it prints only when it actually restores something. --no-replay
opts out.

Usage:
  python3 scrape_race.py --race vuelta 2025
  python3 scrape_race.py --race giro 1990-2000 --resume
  python3 scrape_race.py --race tour 1985 --no-replay   # leave PCS's rows as-is

scrape_giro.py and scrape_vuelta.py remain as thin wrappers, so every recipe in
ai-context.md keeps working.

Cloudflare (2026-08): PCS now challenges plain HTTP requests even for
historical years, not just the live race. Solve the challenge once in a real
browser, then set CF_CLEARANCE to that session's `cf_clearance` cookie value
(DevTools → Network → any procyclingstats.com request → Request Headers →
Cookie) so this script's requests ride on that browser's clearance:

  CF_CLEARANCE=xxxxx python3 scrape_vuelta.py 2020-2025

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

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

from race_common import (
    RACES,
    apply_stage_title,
    exit_on_help,
    assign_stage_numbers,
    page_says_cancelled,
    parse_ttt_rows,
)

HERE = os.path.dirname(os.path.abspath(__file__))

BASE = "https://www.procyclingstats.com"
CF_CLEARANCE = os.environ.get("CF_CLEARANCE", "")
HEADERS = {
    "User-Agent": os.environ.get(
        "CF_USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
if CF_CLEARANCE:
    HEADERS["Cookie"] = f"cf_clearance={CF_CLEARANCE}"
DELAY = float(os.environ.get("SCRAPE_DELAY", "2.0"))
MAX_WAIT = 12.0

ICON_TO_ROUTE = {"p1": "F", "p2": "H", "p3": "H", "p4": "M", "p5": "M"}


_NETWORK_ERROR = "__NETWORK_ERROR__"

class _Cancelled:
    """A stage PCS declares cancelled. Distinct from a failure: there is
    nothing to retry, and the hole it leaves in the stage numbering is correct.

    Deliberately FALSY, so the only contract every caller of scrape_stage
    already relies on — "anything falsy means write no file" — keeps holding
    for a value none of them has heard of. The scrape loop tests identity to
    say something more specific.
    """
    __slots__ = ()

    def __bool__(self):
        return False

    def __repr__(self):
        return "<cancelled>"


_CANCELLED = _Cancelled()


def fetch(url: str, retries: int = 2, soft_fail_429: bool = False,
          probe: bool = False) -> str | None:
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                html = r.read().decode("utf-8", errors="replace")
                if "Just a moment" in html and len(html) < 10000:
                    print(f"    Cloudflare challenge on {url}")
                    return None
                return html
        except urllib.error.HTTPError as e:
            if e.code in (404, 410, 500):
                return None
            if e.code == 403:
                body = e.read().decode("utf-8", errors="replace")
                if "Just a moment" in body or "cf-mitigated" in str(e.headers):
                    print(
                        f"\n  CLOUDFLARE BLOCKED (403) on {url}\n"
                        f"  CF_CLEARANCE is missing or has expired — retrying won't help.\n"
                        f"  Get a fresh cookie (see the module docstring) and re-run; "
                        f"pass --resume to skip years already fully scraped.\n"
                    )
                    sys.exit(1)
                # A real (non-Cloudflare) 403 — fall through to generic retry below.
            if e.code == 429:
                if soft_fail_429:
                    return None
                time.sleep(5.0)
                if attempt < retries:
                    continue
                return _NETWORK_ERROR if probe else None
            print(f"    HTTP {e.code} on {url} (attempt {attempt+1})")
            if attempt < retries:
                time.sleep(MAX_WAIT)
        except Exception as e:
            print(f"    Error {e} on {url} (attempt {attempt+1})")
            if attempt < retries:
                time.sleep(MAX_WAIT)
    return _NETWORK_ERROR if probe else None


def looks_like_a_stage(html) -> bool:
    return bool(html and html is not _NETWORK_ERROR
                and "rider/" in html and len(html) > 15000)


def discover_stages(race, year: int) -> list[str]:
    """Probe PCS for stage slugs: prologue, stage-1, ..., or stage-1a/1b for splits."""
    slugs = []
    consecutive_misses = 0

    # A prologue is slugged 'prologue', never 'stage-0' — and this loop only
    # ever asked for stage-N, so it found none of the 82 in the database (41 of
    # them the Tour's, 1967-2012). Nothing broke loudly, because
    # assign_stage_numbers handles a prologue perfectly well once it is given
    # one: the year would simply have been scraped one stage short, and
    # ingest_race's orphan guard would then refuse the whole edition rather
    # than renumber every stage behind the missing day.
    if looks_like_a_stage(fetch(f"{BASE}/race/{race.pcs_slug}/{year}/prologue", probe=True)):
        slugs.append("prologue")
        time.sleep(DELAY)

    for n in range(1, 30):
        found_any = False
        network_error = False
        slug = f"stage-{n}"
        url = f"{BASE}/race/{race.pcs_slug}/{year}/{slug}"
        html = fetch(url, probe=True)
        if looks_like_a_stage(html):
            slugs.append(slug)
            found_any = True
            consecutive_misses = 0
            time.sleep(DELAY)
        elif html is _NETWORK_ERROR:
            network_error = True
            print(f"    Network error on {url}, not counting as miss")
            time.sleep(DELAY * 2)
        else:
            for letter in "abcd":
                slug = f"stage-{n}{letter}"
                html = fetch(f"{BASE}/race/{race.pcs_slug}/{year}/{slug}", probe=True)
                if looks_like_a_stage(html):
                    slugs.append(slug)
                    found_any = True
                    consecutive_misses = 0
                    time.sleep(DELAY)
                elif html is _NETWORK_ERROR:
                    network_error = True
                    print(f"    Network error on sub-stage {slug}, not counting as miss")
                    time.sleep(DELAY * 2)
                    break
                else:
                    break
            if not found_any and not network_error:
                consecutive_misses += 1
                time.sleep(DELAY * 0.5)

        if consecutive_misses >= 3 and len(slugs) > 5:
            break

    return slugs


def td_text(html: str) -> str:
    t = re.sub(r"<[^>]+>", "", html)
    t = t.replace("&amp;", "&").replace("&#160;", " ").replace("&nbsp;", " ")
    return " ".join(t.split())


def dedup_time(t: str) -> str:
    if not t:
        return ""
    s = t.lstrip(",").strip()
    if len(s) >= 2 and len(s) % 2 == 0 and s[:len(s)//2] == s[len(s)//2:]:
        s = s[:len(s)//2]
    return s


# A time trial's Time cell, which looks nothing like a road stage's:
#
#   road stage:  <font>3:29:07</font><span class="hide">3:29:07</span>
#   time trial:  22.24<font class="fs10">,54</font><span class="hide"></span>
#
# PCS times a TT to the hundredth, prints MM.SS (or H.MM.SS) as bare text and
# puts only the hundredths in the fs10 font — and leaves the hidden span EMPTY,
# so the authoritative-value rule that road stages rely on has nothing to read.
# The old fallback then took the FIRST <font> in the cell, which here is the
# hundredths: Sobrero's 22:24 in the 2022 Giro's Verona TT became ",54", and
# dedup_time halved that to "5". Every value ended up unparseable, so ingest
# stored NULL — 19 time trials across the three races, 2021-2026, with no
# winner's time and no gaps at all.
_HUNDREDTHS_TIME_RE = re.compile(r'^\s*(\d{1,2}(?:\.\d{2}){1,2})\s*<font class="fs10">')


def parse_hundredths_time(time_td: str) -> str:
    """The MM.SS / H.MM.SS text of a time-trial Time cell, as H:MM:SS.

    Returns "" for any cell that is not in that shape, so a road stage falls
    through to the ordinary hidden-span/font handling untouched. The hundredths
    themselves are dropped: the database stores whole seconds, and PCS's own
    displayed seconds are the value to keep rather than one we re-round.
    """
    m = _HUNDREDTHS_TIME_RE.match(time_td)
    return m.group(1).replace(".", ":") if m else ""


def parse_profile_icon(html: str) -> str:
    m = re.search(r'class="[^"]*\bicon\b[^"]*\bprofile\b[^"]*\b(p[1-5])\b', html)
    if m:
        return m.group(1)
    m = re.search(r'class="icon\s+(p[1-5])\b', html)
    return m.group(1) if m else "p1"


def parse_info(html: str) -> dict:
    info = {}

    def extract(label):
        m = re.search(
            re.escape(label) + r'[^<]*</div><div[^>]*>\s*(?:<a[^>]*>)?([^<]+?)(?:</a>)?\s*</div>',
            html, re.IGNORECASE,
        )
        return m.group(1).strip() if m else None

    for key in ("Date", "Distance", "Departure", "Arrival",
                "Won how", "Avg. speed winner", "Vertical meters"):
        val = extract(f"{key}:")
        if val:
            if key == "Departure":
                info["Start"] = val
            elif key == "Arrival":
                info["Finish"] = val
            else:
                info[key] = val

    if info.get("Date"):
        raw = info["Date"]
        try:
            from datetime import datetime
            for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
                try:
                    info["Date"] = datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
        except Exception:
            pass

    apply_stage_title(info, html)

    return info


def find_results_table(html: str) -> str | None:
    tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.DOTALL)
    for table in tables:
        headers = re.findall(r"<th[^>]*>(.*?)</th>", table, re.DOTALL)
        header_texts = [td_text(h) for h in headers]
        if "Rnk" in header_texts and ("GC" in header_texts or "Rider" in " ".join(header_texts)):
            return table
        if "Rnk" in header_texts:
            tbody = re.search(r"<tbody>(.*?)</tbody>", table, re.DOTALL)
            if tbody and len(re.findall(r"<tr", tbody.group(1))) > 30:
                return table
    return None


def parse_header_indices(table_html: str) -> dict:
    headers = re.findall(r"<th[^>]*>(.*?)</th>", table_html, re.DOTALL)
    return {td_text(h): i for i, h in enumerate(headers)}


def parse_header_codes(table_html: str) -> dict:
    """{data-code: column index} — PCS's own name for each column.

    Preferred over the visible header text, which is not a reliable key: an old
    Tour table carries an empty <th> for the bonus column and prints "Pnt"
    twice, and a fixed positional map breaks the moment a table gains or loses
    a column. PCS tags every <th> with data-code ("rnk", "bonis", "pnt",
    "time"), so ask it rather than guess.
    """
    return {m.group(1): i for i, m in enumerate(
        re.finditer(r'<th[^>]*\bdata-code="([^"]*)"[^>]*>', table_html))}


def parse_rows(table_html: str) -> list[list]:
    ci = parse_header_indices(table_html)
    cc = parse_header_codes(table_html)
    tbody_m = re.search(r"<tbody>(.*?)</tbody>", table_html, re.DOTALL)
    if not tbody_m:
        return []

    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody_m.group(1), re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        if len(tds) < 5:
            continue

        try:
            rnk = td_text(tds[ci.get("Rnk", 0)])

            gc_pos = ""
            gc_lag = ""
            if "GC" in ci:
                gc_raw = td_text(tds[ci["GC"]])
                parts = gc_raw.split()
                gc_pos = parts[0] if parts else ""
                gc_lag = dedup_time(" ".join(parts[1:])) if len(parts) > 1 else ""
            if "Timelag" in ci and not gc_lag:
                gc_lag = dedup_time(td_text(tds[ci["Timelag"]]))

            bib = td_text(tds[ci["BIB"]]) if "BIB" in ci else ""
            age = td_text(tds[ci["Age"]]) if "Age" in ci else ""

            rider_name = rider_slug = nat = ""
            team_name = team_slug = ""
            rider_col = team_col = -1

            for i, td in enumerate(tds):
                if "rider/" in td and rider_col < 0:
                    rider_col = i
                elif "team/" in td and team_col < 0:
                    team_col = i

            if rider_col >= 0:
                rtd = tds[rider_col]
                slug_m = re.search(r'href="/?([^"]*rider/[a-z0-9.-]+)"', rtd)
                rider_slug = slug_m.group(1) if slug_m else ""
                if rider_slug.startswith("/"):
                    rider_slug = rider_slug[1:]

                anchor_m = re.search(r'<a[^>]*href="[^"]*rider/[^"]*"[^>]*>(.*?)</a>', rtd, re.DOTALL)
                rider_name = td_text(anchor_m.group(1)) if anchor_m else ""

                nat_m = re.search(r'class="flag ([a-z]{2})"', rtd)
                nat = nat_m.group(1) if nat_m else ""

            if not rider_slug:
                continue

            if team_col >= 0:
                ttd = tds[team_col]
                # The dot matters. A PCS slug carries one wherever the team's
                # name does — iBanesto.com, O.N.C.E., FDJ.fr, R.M.O., Vini
                # Caldirola - So.di — and without it in the class the pattern
                # cannot reach the closing quote, so it matches nothing at all
                # and the row lands with a team NAME and no team. 4,118 rows
                # across the Tour's scrape files, every one of them a real
                # rider on a real team. The rider pattern above has the same
                # shape and a worse failure: a row whose slug will not parse is
                # dropped entirely, a few lines below.
                ts_m = re.search(r'href="/?([^"]*team/[a-z0-9.-]+)"', ttd)
                team_slug = ts_m.group(1) if ts_m else ""
                if team_slug.startswith("/"):
                    team_slug = team_slug[1:]
                tn_m = re.search(r'>([^<]+)</a>', ttd)
                team_name = tn_m.group(1).strip() if tn_m else ""

            uci = td_text(tds[ci["UCI"]]) if "UCI" in ci else ""
            pnt = td_text(tds[ci["Pnt"]]) if "Pnt" in ci else ""

            time_idx = ci.get("Time", len(tds) - 1)
            time_td = tds[time_idx] if time_idx < len(tds) else ""
            # PCS renders a rider tied with the row above as a ditto mark
            # (",," in the visible <font> text) but embeds the real,
            # unambiguous value right next to it in a hidden
            # <span class="hide">...</span> — read that authoritative value
            # when present instead of reverse-engineering the ditto text.
            # Falls back to the old font-text heuristic when no hidden span
            # exists (older/atypical page layouts).
            hide_m = re.search(r'<span class="hide">([^<]*)</span>', time_td)
            if hide_m and hide_m.group(1).strip():
                time_txt = hide_m.group(1).strip()
            elif parse_hundredths_time(time_td):
                # A time trial: the span is empty by design, and the first
                # <font> holds hundredths rather than a time. See above.
                time_txt = parse_hundredths_time(time_td)
            else:
                font_m = re.search(r"<font[^>]*>([^<]*)</font>", time_td)
                time_txt = dedup_time(font_m.group(1).strip() if font_m else td_text(time_td))

            abs_time_txt = ""
            gap_txt = ""
            if rnk == "1":
                # The winner's gap is zero, not their own finishing time.
                # Setting both from the one cell is what produced the doubled
                # winner times fix_doubled_winner_times.py had to repair —
                # 3,377 rows across 3,354 stages, because ingest computes
                # `finish = winner_seconds + gap`. That script fixed the
                # database and left this line alone, so every re-scrape since
                # has written the defect back into the stage files.
                abs_time_txt = time_txt
                gap_txt = "+0:00"
            elif time_txt.startswith("+"):
                gap_txt = time_txt
            elif time_txt in ("s.t.", "s.t", "0:00", ""):
                gap_txt = "+0:00"
            elif re.match(r"^\d+:\d{2}(:\d{2})?$", time_txt):
                gap_txt = time_txt
            else:
                gap_txt = time_txt

            # The bonus column, asked for by name. This used to scan the two
            # columns before Time for anything shaped like a number, which
            # picks up the POINTS column whenever it sits there — 29,849 Giro
            # and 24,963 Vuelta rows held a points total as a time bonus, every
            # one equal to that row's own pcs_pts. It also caught a doubled time
            # on Tour 1954 stage 4. data-code makes the guess unnecessary.
            bonus_txt = ""
            if "bonis" in cc and cc["bonis"] < len(tds):
                bt = td_text(tds[cc["bonis"]]).strip()
                if re.match(r'^\d+[″"]?$', bt):
                    bonus_txt = bt

            rows.append([
                rnk, gc_pos, gc_lag, bib, age,
                rider_name, rider_slug, nat,
                team_name, team_slug,
                uci, pnt, bonus_txt,
                abs_time_txt, gap_txt,
            ])
        except Exception:
            continue

    return rows


def parse_points_page(html: str, point_type: str) -> dict:
    if not html:
        return {}
    pts = {}
    h4s = list(re.finditer(r"<h4[^>]*>(.*?)</h4>", html, re.DOTALL))
    tables = list(re.finditer(r"<table[^>]*>(.*?)</table>", html, re.DOTALL))

    for h4 in h4s:
        text = td_text(h4.group(1))
        match = False
        if point_type == "sprint":
            match = text.startswith("Sprint |") or text == "Points at finish"
        else:
            match = text.startswith("KOM Sprint") or text.startswith("GPM Sprint")
        if not match:
            continue

        h4_end = h4.end()
        tbl = None
        for t in tables:
            if t.start() > h4_end:
                tbl = t
                break
        if not tbl:
            continue

        # Read the `pnt` column by its data-code, the same rule parse_rows
        # follows. "The last numeric cell in the row" used to stand in for it
        # and was wrong on every modern page: these tables end with `delta_pnt`
        # ("Today"), so the winner of the 2026 Vuelta's stage 2 was credited
        # with 10 points instead of 30 — and on a row where Today is blank, the
        # fallback silently landed on `pnt` instead, so the error varied row by
        # row and the totals looked merely low rather than wrong. Van Aert
        # finished that Vuelta on 208 of his real 326 points.
        #
        # Positions cannot stand in either: a sprint with time bonuses carries
        # a `result_boni` column and one without it does not, so the same page
        # serves 9- and 10-column tables side by side.
        codes = parse_header_codes(tbl.group(1))
        if "pnt" not in codes:
            continue
        pnt_i = codes["pnt"]

        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl.group(1), re.DOTALL):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
            if pnt_i >= len(tds):
                continue
            slug = ""
            for td in tds:
                slug_m = re.search(r'href="/?([^"]*rider/[a-z0-9.-]+)"', td)
                if slug_m:
                    s = slug_m.group(1)
                    slug = s[1:] if s.startswith("/") else s
                    break
            txt = td_text(tds[pnt_i]).strip()
            points = int(txt) if re.match(r"^\d+$", txt) else 0
            if slug and points > 0:
                pts[slug] = pts.get(slug, 0) + points

    return pts


def scrape_stage(race, year: int, slug: str, stage_num: int) -> dict | None:
    url = f"{BASE}/race/{race.pcs_slug}/{year}/{slug}"
    html = fetch(url)
    if not html:
        return None

    # A cancelled stage, checked BEFORE the tables are read. The empty-results
    # guard further down catches the common shape, but not the one the Vuelta
    # 2026's stage 3 arrived in: PCS served a full 183-row table with every
    # rank "NR" and every GC column carried over from stage 2, under a banner
    # reading "Race/stage is cancelled". Parsed as results that is 183 people
    # finishing a stage the jury stopped on the Col de Mont-Louis for hail,
    # plus one day's general classification repeated as the next day's.
    # insert_cancelled_stages.py places the row instead, cancelled=1 with no
    # results, and stage_notes.json records the reason.
    if page_says_cancelled(html):
        return _CANCELLED

    # A TTT is grouped by team and needs its own parser, because on many of
    # these pages find_results_table picks up an unrelated table and parse_rows
    # returns a single stray row that looks like a valid result.
    #
    # But not on all of them. Where PCS also publishes an ordinary per-rider
    # results table for a team trial, that table is strictly better: it holds
    # the riders DROPPED by their team, who finish on their own time and are
    # absent from the per-team blocks entirely. Vuelta 2003 stage 1 has 22 team
    # blocks totalling 168 riders and a results table with all 197 — the 29
    # missing each rode between 6 and 20 later stages of that same Vuelta.
    #
    # So parse both and keep the fuller one, rather than trusting either shape
    # to be the right one everywhere. The comparison is what makes this safe:
    # on a page where the ordinary path really does return one stray row, 1 is
    # not greater than the team blocks' count and the TTT rows still win.
    # is_ttt stays true either way — it records what the PAGE was, and drives
    # route_type='TTT' downstream regardless of which table the rows came from.
    ttt_rows = parse_ttt_rows(html)
    is_ttt = bool(ttt_rows)
    table_html = find_results_table(html)
    normal_rows = parse_rows(table_html) if table_html else []

    if is_ttt:
        if len(normal_rows) > len(ttt_rows):
            rows = normal_rows
            print(f"TTT+{len(normal_rows) - len(ttt_rows)} ", end="")
        else:
            rows = ttt_rows
            print("TTT ", end="")
    else:
        if not table_html:
            print("NO TABLE", end=" ")
            return None
        rows = normal_rows
        if not rows:
            # An empty results table is not a stage this scraper can write.
            # PCS says "Race/stage is cancelled" on every one found so far —
            # the 1991 Vuelta's weather-cancelled stage 11 and the 1978 Tour's
            # stage-12a, abandoned to the Valence d'Agen riders' strike — and a
            # stage file would land such a day in the database as one that was
            # raced and that nobody finished. insert_cancelled_stages.py places
            # them instead, with cancelled=1 and no results at all.
            print("NO ROWS", end=" ")
            return None

    info = parse_info(html)
    icon = parse_profile_icon(html)

    time.sleep(DELAY * 0.5)
    pts_html = fetch(f"{BASE}/race/{race.pcs_slug}/{year}/{slug}-points", soft_fail_429=True)
    time.sleep(DELAY * 0.5)
    kom_html = fetch(f"{BASE}/race/{race.pcs_slug}/{year}/{slug}-kom", soft_fail_429=True)

    # PCS 500s `<slug>-points` and `<slug>-kom` for the FINAL stage of every
    # Grand Tour — verified 2026-09-14 on the Tour, Giro and Vuelta 2026, and on
    # the Vuelta 2025, so it is not a one-off. That silently left stage 21 with
    # no sprint or KOM points in every year scraped this way.
    #
    # The stage's own result page carries the same `Sprint | ...`, `Points at
    # finish` and `KOM Sprint` tables, and it is already in hand. Checked
    # against both dedicated pages on Vuelta 2026 stage 20: all three parse to
    # identical sprint and KOM dicts. Falling back to it costs no extra request.
    sprint_points = parse_points_page(pts_html or html, "sprint")
    kom_points = parse_points_page(kom_html or html, "kom")

    return {
        "n": stage_num,
        # The PCS slug this row set actually came from. "n" is a DB-side
        # sequential number that diverges from the slug on any split day, so
        # only the slug can be trusted to re-fetch the same page later.
        "slug": slug,
        # Whether PCS served this as a TEAM time trial. "Won how" says only
        # "Time trial" for some TTTs (Vuelta 1989 stage 3a among them), so
        # detect_route_type cannot tell them apart — but the page structure
        # can, and this records what the page actually was.
        "is_ttt": is_ttt,
        "info": info,
        "profile_icon": icon,
        "rows": rows,
        "sprint_points": sprint_points,
        "kom_points": kom_points,
    }


def scrape_year(race, year: int, out_dir: str) -> bool:
    print(f"\n{'='*60}")
    print(f"{year}: discovering stages...")
    slugs = discover_stages(race, year)
    if not slugs:
        print(f"  No stages found for {year}")
        return False

    print(f"  Found {len(slugs)} stages")
    os.makedirs(out_dir, exist_ok=True)

    # Map slugs -> DB stage numbers up front. assign_stage_numbers() refuses
    # to number an incomplete sequence, so a stage dropped by discover_stages()
    # (transient Cloudflare block, network hiccup) aborts the year instead of
    # silently shifting every later stage down one. It also gives split days
    # ("stage-3a"/"stage-3b") distinct numbers — deriving the number from the
    # slug's digits alone made both halves collide on one file, silently
    # discarding the first.
    numbered, err = assign_stage_numbers(slugs)
    if err:
        print(f"  ABORT {year}: {err}")
        return False

    saved_nums, cancelled_nums = [], []
    for stage_num, slug in numbered:
        out_path = os.path.join(out_dir, f"stage_{stage_num}.json")

        print(f"  {slug} → stage_{stage_num}.json ... ", end="", flush=True)
        result = scrape_stage(race, year, slug, stage_num)
        if result is _CANCELLED:
            print("CANCELLED — no results file written")
            cancelled_nums.append(stage_num)
        elif result:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
            sp = len(result["sprint_points"])
            kp = len(result["kom_points"])
            print(f"{len(result['rows'])}r {sp}sp {kp}km")
            saved_nums.append(stage_num)
        else:
            print("FAILED")

        time.sleep(DELAY)

    saved = len([f for f in os.listdir(out_dir) if f.startswith("stage_") and f.endswith(".json")])
    print(f"  {year}: {saved}/{len(slugs)} stages saved to {out_dir}")

    if cancelled_nums:
        print(f"  {year}: stage(s) {cancelled_nums} cancelled by PCS — run "
              f"insert_cancelled_stages.py after ingest to place the row(s), "
              f"and record the reason in stage_notes.json.")

    if saved_nums:
        expected = set(range(min(saved_nums), max(saved_nums) + 1))
        # A cancelled stage is a hole on purpose, not one to retry.
        missing = sorted(expected - set(saved_nums) - set(cancelled_nums))
        if missing:
            print(f"  WARNING: gap in stage numbering — missing stage(s) {missing} "
                  f"between {min(saved_nums)} and {max(saved_nums)}. Re-run to retry them.")

    return saved > 0


def parse_year_args(args: list[str]) -> list[int]:
    years = []
    for a in args:
        if a.startswith("-"):
            continue
        if "-" in a and not a.startswith("-"):
            parts = a.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                years.extend(range(int(parts[0]), int(parts[1]) + 1))
                continue
        if a.isdigit():
            years.append(int(a))
    return sorted(set(years))


def main(argv=None):
    exit_on_help(__doc__)
    args = list(argv if argv is not None else sys.argv[1:])
    race_key = None
    if "--race" in args:
        i = args.index("--race")
        race_key = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if race_key not in RACES:
        print("Usage: python3 scrape_race.py --race {giro|vuelta} YEAR [YEAR...] "
              "[YEAR_START-YEAR_END] [--resume]")
        print("Example: python3 scrape_race.py --race vuelta 2025")
        return 1
    race = RACES[race_key]

    resume = "--resume" in args
    no_replay = "--no-replay" in args
    years = parse_year_args(args)
    if not years:
        print(f"Usage: python3 scrape_race.py --race {race_key} YEAR [YEAR...] "
              "[YEAR_START-YEAR_END] [--resume]")
        return 1

    print(f"Scraping {race.name} for {len(years)} year(s): {years[0]}–{years[-1]}")

    scrapes_dir = os.path.join(HERE, race.scrapes_dirname)
    for year in years:
        out_dir = os.path.join(scrapes_dir, str(year))

        if resume and os.path.exists(out_dir):
            existing = [f for f in os.listdir(out_dir)
                        if f.startswith("stage_") and f.endswith(".json")]
            if len(existing) >= 10:
                print(f"\n{year}: skipping ({len(existing)} stages already scraped)")
                continue

        scrape_year(race, year, out_dir)

    # PCS reproduces its adjacent-row name swaps on every request, so the years
    # just written have any previously-repaired pair transposed again — and the
    # scrape file is the source of truth, so nothing downstream would know. The
    # repairs are recorded, so put them straight back; this is the same bargain
    # as re-applying DB patches across a re-ingest, and for the same reason.
    # Idempotent, and it refuses to touch a row showing neither recorded name.
    if not no_replay and years:
        from fix_name_swaps import replay
        for year in years:
            replay(race_key, year, apply=True, quiet=True)

    print(f"\n{'='*60}")
    print("Done. Next steps:")
    for cmd in (f"build_{race.cli}_points.py",
                f"ingest_race.py --race {race.cli}",
                f"export_gc.py --race {race.cli}",
                f"export_race_summary.py --race {race.cli}",
                f"export_riders_index.py --race {race.cli}"):
        print(f"  python3 {cmd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
