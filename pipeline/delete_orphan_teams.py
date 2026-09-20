#!/usr/bin/env python3
"""Delete team rows that nothing references, and their provenance with them.

The companion to the 826-orphan-rider deletion of 2026-09-14, for the same rot
one table over. `validate_db.check_orphan_teams()` reports these; this is what
removes them.

**Why they exist.** `teams` is append-only: every writer uses `INSERT OR
IGNORE` or `upsert_team()`, no code path anywhere deletes a team row, and
`replace_edition()` wipes an edition's `stage_results` wholesale on each
re-ingest. A team row therefore outlives whatever created it — when a re-scrape
spells the sponsor differently, or PCS switches between a short name and the
full sponsor string, the riders move to the new `team_id` and the old row is
stranded permanently.

**What counts as an orphan, and what does not.** A row qualifies only when it
has no `stage_results` AND no `classification_standings`. The second half is
the part worth stating: **"no riders" does not mean "useless"** — a team
classification placing is the team's own result and needs no rider row behind
it. Seven teams are in exactly that position and this script must never touch
them.

**What deleting does not do.** It removes nothing the app shows. 415 distinct
names sit on these rows, but 145 of them also sit on rows that DO hold riders,
so those names survive; the 270 that disappear entirely appear in **no exported
`teams` array**, because the dropdown is built from riders' attributions. That
is checked again at run time rather than trusted — see `check_safe()`.

**It is a cleanup, not a fix.** These regenerate: a re-ingest will re-create
any team whose id is still attested in a scrape file on disk. 544 of the 733
are marked `unknown` precisely because no such file survives, so those are gone
for good, but the rest can come back. The permanent fix is for the ingest to
stop minting a row it will never attribute a rider to; this only clears what
has already piled up.

Usage:
  python3 delete_orphan_teams.py --dry-run
  python3 delete_orphan_teams.py
"""
import argparse
import glob
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
EXPORT_GLOB = os.path.join(HERE, "..", "cycling-app", "src", "data",
                           "*", "riders_index.json")

ORPHANS = """
    SELECT t.team_id, t.name FROM teams t
     WHERE NOT EXISTS (SELECT 1 FROM stage_results sr WHERE sr.team_id = t.team_id)
       AND NOT EXISTS (SELECT 1 FROM classification_standings cs
                        WHERE cs.team_id = t.team_id)
     ORDER BY t.team_id"""


def exported_team_names():
    names = set()
    for path in glob.glob(EXPORT_GLOB):
        with open(path, encoding="utf-8") as f:
            names |= set(json.load(f).get("teams") or [])
    return names


def check_safe(cur, orphans):
    """Refuse to run if deleting would take a name out of the app.

    Re-derived from the live database and the live exports every run rather
    than trusted from the last time someone checked, because the thing that
    makes this safe — every disappearing name being absent from the exports —
    is a fact about today's data, not a property of the code.
    """
    doomed = {t for t, _ in orphans}
    by_name = {}
    for team_id, name in cur.execute("SELECT team_id, name FROM teams"):
        by_name.setdefault(name, []).append(team_id)
    vanishing = {n for n, ids in by_name.items() if all(i in doomed for i in ids)}

    exported = exported_team_names()
    if not exported:
        return ["no exported riders_index.json found — cannot prove the "
                "deletion is invisible, so refusing to guess"]
    lost = sorted(vanishing & exported)
    if lost:
        return [f"{len(lost)} name(s) would disappear from the DB while still "
                f"being listed in an exported dropdown: {', '.join(lost[:5])}"]
    return []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would go, write nothing")
    ap.add_argument("--list", metavar="PATH",
                    help="write the full list of deleted ids here")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    orphans = cur.execute(ORPHANS).fetchall()
    if not orphans:
        print("no orphan teams")
        conn.close()
        return 0

    kept = cur.execute("""
        SELECT COUNT(*) FROM teams t
         WHERE NOT EXISTS (SELECT 1 FROM stage_results sr WHERE sr.team_id=t.team_id)
           AND EXISTS (SELECT 1 FROM classification_standings cs
                        WHERE cs.team_id=t.team_id)""").fetchone()[0]

    problems = check_safe(cur, orphans)
    if problems:
        for p in problems:
            print(f"REFUSING: {p}")
        conn.close()
        return 1

    prov = cur.execute(
        f"SELECT COUNT(*) FROM data_provenance WHERE entity='teams' "
        f"AND entity_id IN (SELECT team_id FROM ({ORPHANS}))").fetchone()[0]

    print(f"{len(orphans)} team row(s) referenced by nothing, "
          f"{prov} provenance row(s) with them")
    print(f"{kept} team(s) with no riders but a team-classification placing "
          f"are NOT touched")
    print("\nfirst 15:")
    for team_id, name in orphans[:15]:
        print(f"   {team_id:<46} {name}")
    if len(orphans) > 15:
        print(f"   ... and {len(orphans) - 15} more")

    if args.list:
        with open(args.list, "w", encoding="utf-8") as f:
            for team_id, name in orphans:
                f.write(f"{team_id}\t{name}\n")
        print(f"\nfull list written to {args.list}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        conn.close()
        return 0

    ids = [t for t, _ in orphans]
    cur.executemany("DELETE FROM data_provenance WHERE entity='teams' "
                    "AND entity_id = ?", [(t,) for t in ids])
    cur.executemany("DELETE FROM teams WHERE team_id = ?", [(t,) for t in ids])
    conn.commit()

    left = cur.execute(f"SELECT COUNT(*) FROM ({ORPHANS})").fetchone()[0]
    total = cur.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    conn.close()
    print(f"\ndeleted — teams is now {total:,} rows, {left} orphan(s) left")
    return 0


if __name__ == "__main__":
    sys.exit(main())
