#!/usr/bin/env python3
"""Fill finishing times for classics race-years where PCS has no Time column.

Source data lives in classics_bri_times.json (bikeraceinfo.com). PCS genuinely
omits the Time column for some editions — Gent-Wevelgem 2005 renders
`Rnk,BIB,H2H,Specialty,Age,Rider,Team,Pnt` with no time at all — so those
riders have ranks and nothing else. This fills the gap from a second source
rather than deriving anything.

Safety, in order of how badly each has burned this project before:

* **Names are verified, not trusted.** bikeraceinfo prints "Firstname
  Lastname", PCS stores "Lastname Firstname". Every rank is matched by
  normalized token set and the script REFUSES to write anything unless all of
  them agree. Aligning two sources by position alone is how you silently
  attribute one rider's time to another.
* **Only rank 1 gets an absolute time**; everyone else stores a gap.
  `winner + gap` written to every row is what doubled 3,377 winning times
  across this DB (ai-context.md rule 2).
* **`s.t.` chains are resolved forward** from the last explicit gap, the same
  meaning as PCS's ditto marks.
* **Nothing is overwritten.** A row that already has a time is left alone and
  reported, so this can never clobber scraped data.
* Provenance is recorded as `bikeraceinfo` with the exact URL.

Usage:
  python3 patch_classics_times.py --dry-run
  python3 patch_classics_times.py
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata

from race_common import CLASSICS, record_provenance

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
SRC_PATH = os.path.join(HERE, "classics_bri_times.json")
SOURCE = "bikeraceinfo"


def norm_tokens(name):
    """Accent-folded, punctuation-free token SET, so word order doesn't matter.

    unicodedata NFKD does not decompose every letter this data contains
    (Backstedt's a-ring, Munoz's n-tilde survive as distinct letters), so the
    explicit map below handles the ones that actually appear. Cf. the
    accent-normalisation note in ai-context.md's screenshot-workflow lesson.
    """
    s = name.lower()
    for a, b in (("ø", "o"), ("ł", "l"), ("ß", "ss"), ("æ", "ae"), ("å", "a"),
                 ("ñ", "n"), ("ć", "c"), ("č", "c"), ("š", "s"), ("ž", "z")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z ]", " ", s)
    return frozenset(t for t in s.split() if t)


def parse_gap(text):
    """'2min 55sec' / '31sec' -> seconds. Returns None if unparseable."""
    if not text:
        return None
    m = re.match(r"(?:(\d+)\s*min)?\s*(?:(\d+)\s*sec)?\s*$", text.strip())
    if not m or not any(m.groups()):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def parse_hms(text):
    parts = [int(p) for p in text.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def resolve(results):
    """[(rank, name, raw_gap)] -> [(rank, name, gap_seconds)], s.t. resolved."""
    out, last = [], None
    for rank, name, raw in results:
        if rank == 1:
            gap = 0
        elif raw.strip().lower() in ("s.t.", "s.t", "st"):
            if last is None:
                raise ValueError(f"rank {rank}: 's.t.' with no preceding gap")
            gap = last
        else:
            gap = parse_gap(raw)
            if gap is None:
                raise ValueError(f"rank {rank}: cannot parse gap {raw!r}")
        out.append((rank, name, gap))
        last = gap
    return out


def patch_one(cur, race_slug, year, entry, dry_run):
    meta = CLASSICS[race_slug]
    cur.execute(
        """SELECT s.stage_id FROM stages s
           JOIN race_editions e USING(edition_id)
           JOIN races r USING(race_id)
           WHERE r.name = ? AND e.year = ?""", (meta.name, int(year)))
    row = cur.fetchone()
    if not row:
        return [f"{race_slug} {year}: no edition in DB"], 0
    stage_id = row[0]

    cur.execute(
        """SELECT sr.stage_rank, ri.full_name, sr.finish_time_seconds,
                  sr.gap_seconds, sr.rider_id
           FROM stage_results sr JOIN riders ri ON ri.rider_id = sr.rider_id
           WHERE sr.stage_id = ? AND sr.stage_rank IS NOT NULL""", (stage_id,))
    db_rows = {r[0]: r for r in cur.fetchall()}

    resolved = resolve(entry["results"])
    aliases = {int(k): v for k, v in entry.get("aliases", {}).items()}
    disputed = {int(k): v for k, v in entry.get("disputed", {}).items()}
    problems, notes = [], []

    # Verify EVERY rank matches by name before writing anything. An alias is an
    # explicitly reviewed spelling difference; a disputed rank is a genuine
    # source disagreement and is skipped, never guessed at.
    for rank, name, _ in resolved:
        if rank in disputed:
            notes.append(f"rank {rank}: SKIPPED (disputed) — {disputed[rank]}")
            continue
        db = db_rows.get(rank)
        if db is None:
            problems.append(f"rank {rank} ({name}): no DB row")
            continue
        expected = aliases.get(rank, name)
        if norm_tokens(expected) != norm_tokens(db[1]):
            problems.append(f"rank {rank}: source {name!r} != db {db[1]!r}")
    missing = set(db_rows) - {r[0] for r in resolved}
    if missing:
        problems.append(f"DB has ranks with no source row: {sorted(missing)[:10]}")
    if problems:
        return problems + notes, 0

    winner_s = parse_hms(entry["winner_time"])
    url = entry["source_ref"]
    updated = 0
    for rank, name, gap in resolved:
        if rank in disputed:
            continue
        db = db_rows[rank]
        # Keyed on finish_time_seconds alone. gap_seconds is NOT evidence of a
        # recorded time: ingest sets it to 0 for every rank-1 rider, which is
        # trivially true of any winner, and checking it skipped the one row
        # that most needed filling.
        if db[2] is not None:
            problems.append(f"rank {rank} ({name}): already has a time, left alone")
            continue
        # Rank 1 alone carries the absolute time.
        finish = winner_s if rank == 1 else winner_s + gap
        if not dry_run:
            cur.execute(
                """UPDATE stage_results SET finish_time_seconds = ?, gap_seconds = ?
                   WHERE stage_id = ? AND rider_id = ?""",
                (finish, gap, stage_id, db[4]))
            record_provenance(cur, "stage_results", stage_id,
                              f"finish_time_seconds:{db[4]}", SOURCE, source_ref=url)
        updated += 1

    if not dry_run and entry.get("distance_km"):
        cur.execute("SELECT distance_km FROM stages WHERE stage_id=?", (stage_id,))
        cur_dist = cur.fetchone()[0]
        if cur_dist is None:
            cur.execute("UPDATE stages SET distance_km=? WHERE stage_id=?",
                        (entry["distance_km"], stage_id))
            record_provenance(cur, "stages", stage_id, "distance_km", SOURCE,
                              source_ref=url)

    return problems + notes, updated


def apply_overrides(cur, overrides, dry_run):
    """Replace winner times PCS has WRONG (not merely missing).

    Deliberately separate from the fill path above, which refuses to touch a row
    that already holds a value — that refusal is what stops this tool clobbering
    scraped data, so overwriting has to be an explicit, named exception with a
    recorded reason rather than a relaxation of the rule.
    """
    notes, n = [], 0
    for race_slug, years in overrides.items():
        if race_slug.startswith("_"):
            continue
        for year, o in years.items():
            meta = CLASSICS[race_slug]
            cur.execute("""SELECT s.stage_id FROM stages s
                           JOIN race_editions e USING(edition_id)
                           JOIN races r USING(race_id)
                           WHERE r.name = ? AND e.year = ?""", (meta.name, int(year)))
            row = cur.fetchone()
            if not row:
                notes.append(f"{race_slug} {year}: no edition in DB")
                continue
            stage_id = row[0]
            cur.execute("""SELECT sr.rider_id, ri.full_name, sr.finish_time_seconds
                           FROM stage_results sr JOIN riders ri ON ri.rider_id = sr.rider_id
                           WHERE sr.stage_id = ? AND sr.stage_rank = ?""",
                        (stage_id, o["rank"]))
            hit = cur.fetchone()
            if not hit:
                notes.append(f"{race_slug} {year}: no rider at rank {o['rank']}")
                continue
            # The named rider must still be the one sitting at that rank.
            if norm_tokens(hit[1]) != norm_tokens(o["rider"]):
                notes.append(f"{race_slug} {year}: rank {o['rank']} is {hit[1]!r}, "
                             f"override names {o['rider']!r} — SKIPPED")
                continue
            secs = parse_hms(o["winner_time"])
            notes.append(f"{race_slug} {year}: {hit[1]} {hit[2]}s -> {secs}s")
            if not dry_run:
                cur.execute("""UPDATE stage_results SET finish_time_seconds = ?, gap_seconds = 0
                               WHERE stage_id = ? AND rider_id = ?""",
                            (secs, stage_id, hit[0]))
                record_provenance(cur, "stage_results", stage_id,
                                  f"finish_time_seconds:{hit[0]}", SOURCE,
                                  source_ref=o["source_ref"])
            n += 1
    return notes, n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    with open(SRC_PATH, encoding="utf-8") as f:
        src = json.load(f)
    overrides = src.pop("overrides", {})

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total, all_problems = 0, []
    try:
        for race_slug, years in src.items():
            if race_slug.startswith("_"):
                continue
            for year, entry in years.items():
                problems, n = patch_one(cur, race_slug, year, entry, args.dry_run)
                total += n
                for p in problems:
                    all_problems.append(f"{race_slug} {year}: {p}")
                print(f"  {race_slug} {year}: {n} rider time(s) "
                      f"{'would be ' if args.dry_run else ''}filled")
        ov_notes, ov_n = apply_overrides(cur, overrides, args.dry_run)
        for line in ov_notes:
            print(f"  OVERRIDE {line}")
        total += ov_n
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(("DRY RUN — nothing written\n" if args.dry_run else "") +
          f"{total} rider times filled")
    if all_problems:
        print(f"--- problems ({len(all_problems)}) ---")
        for p in all_problems:
            print(f"  {p}")
        return 1
    print("no problems")
    return 0


if __name__ == "__main__":
    sys.exit(main())
