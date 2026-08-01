#!/usr/bin/env python3
"""
Scrape Giro d'Italia stage results from procyclingstats.com.

Produces per-stage JSON files in giro_scrapes/YEAR/stage_N.json, compatible
with ingest_race.py --race giro and build_giro_points.py.

Usage:
  python3 scrape_giro.py 1990 1991 1992    # specific years
  python3 scrape_giro.py 1990-2000          # year range
  python3 scrape_giro.py 1990-2000 --resume # skip years already scraped

Cloudflare (2026-08): PCS now challenges plain HTTP requests even for
historical years, not just the live race. Solve the challenge once in a real
browser, then set CF_CLEARANCE to that session's `cf_clearance` cookie value
(DevTools → Network → any procyclingstats.com request → Request Headers →
Cookie) so this script's requests ride on that browser's clearance:

  CF_CLEARANCE=xxxxx python3 scrape_giro.py 1990-2000

The cookie expires after a while (commonly 30min-2h) — once it does, every
request starts 403ing again and the script exits with a clear message
instead of silently retrying forever. Get a fresh cookie and re-run
(add --resume once a year has fully completed to skip it next time).
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPES_DIR = os.path.join(HERE, "giro_scrapes")

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


# ── HTTP ─────────────────────────────────────────────────────────────────────

_NETWORK_ERROR = "__NETWORK_ERROR__"


def fetch(url: str, retries: int = 2, soft_fail_429: bool = False,
          probe: bool = False) -> str | None:
    """
    Returns HTML on success, None on definitive 404/410/500, or (if probe=True)
    _NETWORK_ERROR sentinel on transient errors so discovery doesn't count them as misses.
    """
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


# ── Stage discovery ──────────────────────────────────────────────────────────

def discover_stages(year: int) -> list[str]:
    """Probe PCS for stage slugs: stage-1, stage-2, ..., or stage-1a/1b for splits."""
    slugs = []
    consecutive_misses = 0
    for n in range(1, 30):
        found_any = False
        network_error = False
        slug = f"stage-{n}"
        url = f"{BASE}/race/giro-d-italia/{year}/{slug}"
        html = fetch(url, probe=True)
        if html and html is not _NETWORK_ERROR and "rider/" in html and len(html) > 15000:
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
                html = fetch(f"{BASE}/race/giro-d-italia/{year}/{slug}", probe=True)
                if html and html is not _NETWORK_ERROR and "rider/" in html and len(html) > 15000:
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


# ── HTML parsing helpers ─────────────────────────────────────────────────────

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

    return info


# ── Results table parsing ────────────────────────────────────────────────────

def find_results_table(html: str) -> str | None:
    """Find the main results table by looking for Rnk header."""
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
    """Map header names to column indices."""
    headers = re.findall(r"<th[^>]*>(.*?)</th>", table_html, re.DOTALL)
    return {td_text(h): i for i, h in enumerate(headers)}


def parse_rows(table_html: str) -> list[list]:
    """Parse results table into row arrays matching the stage_N.json format."""
    ci = parse_header_indices(table_html)
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

            # Find rider column (has rider/ link)
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
                slug_m = re.search(r'href="/?([^"]*rider/[a-z0-9-]+)"', rtd)
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
                ts_m = re.search(r'href="/?([^"]*team/[a-z0-9-]+)"', ttd)
                team_slug = ts_m.group(1) if ts_m else ""
                if team_slug.startswith("/"):
                    team_slug = team_slug[1:]
                tn_m = re.search(r'>([^<]+)</a>', ttd)
                team_name = tn_m.group(1).strip() if tn_m else ""

            uci = td_text(tds[ci["UCI"]]) if "UCI" in ci else ""
            pnt = td_text(tds[ci["Pnt"]]) if "Pnt" in ci else ""

            # Time column — last known column or explicit
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
            else:
                font_m = re.search(r"<font[^>]*>([^<]*)</font>", time_td)
                time_txt = dedup_time(font_m.group(1).strip() if font_m else td_text(time_td))

            abs_time_txt = ""
            gap_txt = ""
            if rnk == "1":
                abs_time_txt = time_txt
                gap_txt = time_txt
            elif time_txt.startswith("+"):
                gap_txt = time_txt
            elif time_txt in ("s.t.", "s.t", "0:00", ""):
                gap_txt = "+0:00"
            elif re.match(r"^\d+:\d{2}(:\d{2})?$", time_txt):
                gap_txt = time_txt
            else:
                gap_txt = time_txt

            # Bonus
            bonus_txt = ""
            for bi in range(max(0, time_idx - 2), time_idx):
                if bi < len(tds):
                    bt = td_text(tds[bi]).strip()
                    if re.match(r'^\d+[″"]?$', bt):
                        bonus_txt = bt
                        break

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


# ── Points parsing ───────────────────────────────────────────────────────────

def parse_points_page(html: str, point_type: str) -> dict:
    """Parse sprint or KOM points from a -points or -kom page."""
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

        # Find the next table after this h4
        h4_end = h4.end()
        tbl = None
        for t in tables:
            if t.start() > h4_end:
                tbl = t
                break
        if not tbl:
            continue

        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl.group(1), re.DOTALL):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
            slug = ""
            points = 0
            for td in tds:
                slug_m = re.search(r'href="/?([^"]*rider/[a-z0-9-]+)"', td)
                if slug_m:
                    s = slug_m.group(1)
                    slug = s[1:] if s.startswith("/") else s
                txt = td_text(td).strip()
                if re.match(r"^\d+$", txt) and int(txt) > 0:
                    points = int(txt)
            if slug and points > 0:
                pts[slug] = pts.get(slug, 0) + points

    return pts


# ── Per-stage scrape ─────────────────────────────────────────────────────────

def scrape_stage(year: int, slug: str, stage_num: int) -> dict | None:
    url = f"{BASE}/race/giro-d-italia/{year}/{slug}"
    html = fetch(url)
    if not html:
        return None

    table_html = find_results_table(html)
    if not table_html:
        print("NO TABLE", end=" ")
        return None

    rows = parse_rows(table_html)
    if not rows:
        print("NO ROWS", end=" ")
        return None

    info = parse_info(html)
    icon = parse_profile_icon(html)

    # Fetch points and KOM pages (soft-fail on 429 — missing points data is not fatal)
    time.sleep(DELAY * 0.5)
    pts_html = fetch(f"{BASE}/race/giro-d-italia/{year}/{slug}-points", soft_fail_429=True)
    time.sleep(DELAY * 0.5)
    kom_html = fetch(f"{BASE}/race/giro-d-italia/{year}/{slug}-kom", soft_fail_429=True)

    sprint_points = parse_points_page(pts_html, "sprint") if pts_html else {}
    kom_points = parse_points_page(kom_html, "kom") if kom_html else {}

    return {
        "n": stage_num,
        "info": info,
        "profile_icon": icon,
        "rows": rows,
        "sprint_points": sprint_points,
        "kom_points": kom_points,
    }


# ── Year scrape ──────────────────────────────────────────────────────────────

def scrape_year(year: int, out_dir: str) -> bool:
    print(f"\n{'='*60}")
    print(f"{year}: discovering stages...")
    slugs = discover_stages(year)
    if not slugs:
        print(f"  No stages found for {year}")
        return False

    print(f"  Found {len(slugs)} stages")
    os.makedirs(out_dir, exist_ok=True)

    saved_nums = []
    for slug in slugs:
        # Stage number comes from the slug itself, NOT from position in the
        # discovered list. discover_stages() silently drops any stage whose
        # probe fails (transient Cloudflare block, network hiccup, etc.) —
        # numbering by position would then quietly shift every later stage
        # down by one, mislabeling it as the wrong stage entirely. A gap in
        # the numbering is a much safer failure mode: it's visible (missing
        # file) and re-scrapable, instead of silently wrong data.
        m = re.match(r"^stage-(\d+)[a-d]?$", slug)
        if not m:
            print(f"  WARN: could not parse stage number from slug '{slug}', skipping")
            continue
        stage_num = int(m.group(1))
        out_path = os.path.join(out_dir, f"stage_{stage_num}.json")

        print(f"  {slug} → stage_{stage_num}.json ... ", end="", flush=True)
        result = scrape_stage(year, slug, stage_num)
        if result:
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

    if saved_nums:
        expected = set(range(min(saved_nums), max(saved_nums) + 1))
        missing = sorted(expected - set(saved_nums))
        if missing:
            print(f"  WARNING: gap in stage numbering — missing stage(s) {missing} "
                  f"between {min(saved_nums)} and {max(saved_nums)}. Re-run to retry them.")

    return saved > 0


# ── Main ─────────────────────────────────────────────────────────────────────

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


def main():
    args = sys.argv[1:]
    resume = "--resume" in args
    years = parse_year_args(args)

    if not years:
        print("Usage: python3 scrape_giro.py YEAR [YEAR...] [YEAR_START-YEAR_END] [--resume]")
        print("Example: python3 scrape_giro.py 1990-2000")
        sys.exit(1)

    print(f"Scraping Giro d'Italia for {len(years)} year(s): {years[0]}–{years[-1]}")

    for year in years:
        out_dir = os.path.join(SCRAPES_DIR, str(year))

        if resume and os.path.exists(out_dir):
            existing = [f for f in os.listdir(out_dir) if f.startswith("stage_") and f.endswith(".json")]
            if len(existing) >= 10:
                print(f"\n{year}: skipping ({len(existing)} stages already scraped)")
                continue

        scrape_year(year, out_dir)

    print(f"\n{'='*60}")
    print("Done. Next steps:")
    print("  python3 build_giro_points.py")
    print("  # delete existing editions, then:")
    print("  python3 ingest_race.py --race giro")
    print("  python3 export_gc.py --race giro")


if __name__ == "__main__":
    main()
