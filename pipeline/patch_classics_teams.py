#!/usr/bin/env python3
"""Fill missing rider->team attribution for the classics from bikeraceinfo.

PCS carries almost no team data for the older classics (2% of riders in the
1940s, ~32% in the 50s/60s, 72% in the 70s), which leaves the team-grouped
by-Stage Table with little to group. bikeraceinfo publishes the team, so this
fills the gap from a second source. Run scrape_bikeraceinfo_teams.py first.

What it will and will not do:

* **Fills only what is MISSING.** A rider who already has a team keeps it. PCS
  stays authoritative wherever it has an opinion; this only fills holes.
* **Matches on NAME, never on rank.** Rank looks like the obvious key — both
  sources list the same race — but it is wrong here: riders who finish together
  share a time, and the two sources order that bunch differently (PCS puts
  Sergio Pagliazzi 20th at Il Lombardia 1949, bikeraceinfo 24th; both honest).
  Aligning on rank mismatches across every tied group, and worse, would
  attribute one rider's team to another wherever it drifted. Names are compared
  accent-folded and order-insensitive ("Fausto Coppi" vs "Coppi Fausto"), and a
  DB rider matching two different source teams is skipped as ambiguous rather
  than resolved by guessing.
* **Never invents a team.** bikeraceinfo genuinely lists many riders with no
  team in this era; those stay NULL.
* Provenance is recorded as `bikeraceinfo` with the exact page URL.

Teams are created with a season-scoped id (`team/<slug>-<year>`), matching the
convention the rest of the DB uses — team identity resets every season because
sponsor names change constantly.

Usage:
  python3 patch_classics_teams.py --dry-run
  python3 patch_classics_teams.py --years 1946-1989
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import sys
import unicodedata

from race_common import CLASSICS, record_provenance

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
SRC_ROOT = os.path.join(HERE, "bikeraceinfo_teams")
SOURCE = "bikeraceinfo"


def norm_tokens(name):
    """Accent-folded, punctuation-free token SET, so word order doesn't matter.

    NFKD does not decompose every letter this data contains (o-slash, l-stroke,
    a-ring survive as distinct letters), so those are mapped explicitly first.
    """
    s = (name or "").lower()
    for a, b in (("ø", "o"), ("ł", "l"), ("ß", "ss"), ("æ", "ae"), ("å", "a"),
                 ("ñ", "n"), ("ć", "c"), ("č", "c"), ("š", "s"), ("ž", "z"),
                 ("đ", "d"), ("ı", "i")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z ]", " ", s)
    return frozenset(t for t in s.split() if t)


def names_agree(a, b):
    """Do two spellings of a name refer to the same rider?

    Exact token-set equality, OR one set being a strict SUBSET of the other.
    The subset rule absorbs the common harmless variants — a nickname
    ('Alberic "Briek" Schotte' vs 'Schotte Briek'), a dropped middle name, a
    Spanish second surname — while staying strict where it matters: every
    shared token must still match exactly.

    It does NOT loosen the check that matters. Two different riders are
    rejected because their tokens are disjoint (Tankink vs Trenti), and even
    two riders sharing a surname are rejected because neither name is a subset
    of the other ({van,dijk,mick} vs {van,dijk,tim}). A genuine spelling
    difference in the surname itself (Vlaeyen vs Vlayen) is also rejected and
    reported — filling those would mean guessing.
    """
    if not a or not b:
        return False
    return a == b or a < b or b < a


def is_placeholder_team(team):
    """bikeraceinfo writes '?' where it does not know the team.

    Filtered here rather than in the scraper so the scraped files stay faithful
    to the source. Deliberately exact: several REAL teams of this era have very
    short names — 'Z' (Greg LeMond's squad), 'RM', 'BP' — so any
    filter-by-length heuristic would silently discard genuine data.
    """
    return team.strip(" ?-–—.") == ""


def team_slug(name, year):
    slug = unicodedata.normalize("NFKD", name.lower())
    slug = "".join(c for c in slug if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return f"team/{slug}-{year}"


def patch_race_year(cur, path, dry_run, stats):
    with open(path, encoding="utf-8") as f:
        src = json.load(f)
    race, year, url = src["race"], src["year"], src["source_ref"]
    if race not in CLASSICS:
        stats["unknown_race"].append(race)
        return
    meta = CLASSICS[race]

    cur.execute("""SELECT s.stage_id FROM stages s
                   JOIN race_editions e USING(edition_id)
                   JOIN races r USING(race_id)
                   WHERE r.name = ? AND e.year = ?""", (meta.name, year))
    row = cur.fetchone()
    if not row:
        stats["no_edition"] += 1
        return
    stage_id = row[0]

    cur.execute("""SELECT sr.stage_rank, sr.rider_id, ri.full_name, sr.team_id
                   FROM stage_results sr JOIN riders ri ON ri.rider_id = sr.rider_id
                   WHERE sr.stage_id = ?""", (stage_id,))
    db_rows = cur.fetchall()

    # Matched by NAME, not by rank. The two sources disagree on the internal
    # order of riders who finished together ("s.t." groups): PCS puts Sergio
    # Pagliazzi 20th at Il Lombardia 1949, bikeraceinfo 24th, and both are
    # honest — the whole group shares a time. Aligning on rank would therefore
    # mismatch across every tied group. A name is an identity; a position
    # inside a bunch is not.
    src_by_name = {}
    for _, name, team in src["results"]:
        if not team or is_placeholder_team(team):
            stats["src_no_team"] += 1
            continue
        src_by_name.setdefault(norm_tokens(name), []).append((name, team))

    for _rank, rider_id, full_name, team_id in db_rows:
        if team_id:
            stats["already_had_team"] += 1
            continue
        want = norm_tokens(full_name)
        hits = [(n, t) for toks, entries in src_by_name.items()
                if names_agree(want, toks) for (n, t) in entries]
        if not hits:
            stats["no_source_row"] += 1
            continue
        # Two different source riders answering to one DB name is ambiguous;
        # refuse rather than pick one.
        distinct = {t for _, t in hits}
        if len(distinct) > 1:
            stats["ambiguous"].append(
                f"{race} {year}: {full_name!r} matches {sorted(distinct)}")
            continue
        src_name, team = hits[0]

        tid = team_slug(team, year)
        if not dry_run:
            cur.execute("INSERT OR IGNORE INTO teams (team_id, name, season_year) "
                        "VALUES (?,?,?)", (tid, team, year))
            cur.execute("UPDATE stage_results SET team_id = ? "
                        "WHERE stage_id = ? AND rider_id = ?", (tid, stage_id, rider_id))
            record_provenance(cur, "stage_results", stage_id,
                              f"team_id:{rider_id}", SOURCE, source_ref=url)
        stats["filled"] += 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", help="YYYY-YYYY (default: every file present)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    lo, hi = 0, 9999
    if args.years:
        m = re.match(r"(\d{4})-(\d{4})$", args.years)
        if not m:
            print("--years must look like 1946-1989")
            return 1
        lo, hi = int(m.group(1)), int(m.group(2))

    paths = sorted(glob.glob(os.path.join(SRC_ROOT, "*", "*.json")))
    paths = [p for p in paths
             if os.path.basename(p)[:4].isdigit()
             and lo <= int(os.path.basename(p)[:4]) <= hi]
    if not paths:
        print(f"no bikeraceinfo files in range — run scrape_bikeraceinfo_teams.py first")
        return 1

    stats = {"filled": 0, "already_had_team": 0, "src_no_team": 0,
             "no_source_row": 0, "no_edition": 0,
             "ambiguous": [], "unknown_race": []}

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        for p in paths:
            patch_race_year(cur, p, args.dry_run, stats)
        conn.rollback() if args.dry_run else conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(("DRY RUN — nothing written\n" if args.dry_run else "") +
          f"{len(paths)} race-year file(s) considered")
    print(f"  teams filled           : {stats['filled']:,}")
    print(f"  already had a team     : {stats['already_had_team']:,}  (left alone)")
    print(f"  no team in source      : {stats['src_no_team']:,}  (left NULL)")
    print(f"  DB rider not in source : {stats['no_source_row']:,}  (left NULL)")
    print(f"  no such edition in DB  : {stats['no_edition']:,}")
    print(f"  AMBIGUOUS              : {len(stats['ambiguous']):,}  (skipped, not guessed)")
    for line in stats["ambiguous"][:12]:
        print(f"      {line}")
    if len(stats["ambiguous"]) > 12:
        print(f"      ... and {len(stats['ambiguous']) - 12} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
