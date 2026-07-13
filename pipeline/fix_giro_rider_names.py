#!/usr/bin/env python3
"""
Fix riders in the Giro data that have only a single-word name (first name only).
Reconstructs full name as "LASTNAME Firstname" using the rider slug, preserving
the scraped first name (which may have accents that the slug lacks).

Usage:
  python3 fix_giro_rider_names.py [--dry-run]
"""

import re
import sqlite3
import sys
import unicodedata

HERE = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
DB_PATH = __import__("os").path.join(HERE, "cycling.db")


def normalize(s: str) -> str:
    """Lowercase and strip diacritics for fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def slug_to_name_parts(slug: str) -> list[str]:
    """rider/fausto-masnada -> ['fausto', 'masnada']"""
    return slug.replace("rider/", "").split("-")


def build_full_name(current_first: str, slug: str) -> str:
    """
    Build 'LASTNAME Firstname' using the slug for last name and the current
    (scraped) first name for the given name, preserving accents in the first name.
    """
    parts = slug_to_name_parts(slug)
    # Strip any disambiguation digits (e.g. 'pozzi2' -> 'pozzi', '1' -> removed)
    parts = [cleaned for p in parts if (cleaned := re.sub(r"\d+$", "", p))]

    norm_first = normalize(current_first)

    # Find how many leading slug parts match the first name.
    # Handles simple cases (fausto -> fausto) and compound first names.
    matched = 0
    for p in parts:
        if normalize(current_first) == normalize("-".join(parts[: matched + 1])):
            matched += 1
            break
        if normalize(p) == norm_first:
            matched = 1
            break

    if matched == 0:
        # No match — construct entirely from slug using Title Case
        return " ".join(p.capitalize() for p in parts)

    last_parts = parts[matched:]
    if not last_parts:
        # Slug only had a first name (no last name), can't improve
        return current_first

    last_name = " ".join(p.capitalize() for p in last_parts)
    return f"{last_name} {current_first}"


def main(dry_run: bool | None = None):
    if dry_run is None:
        dry_run = "--dry-run" in sys.argv

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Find Giro riders with single-word names
    rows = cur.execute("""
        SELECT DISTINCT r.rider_id, r.full_name
        FROM riders r
        JOIN stage_results sr ON sr.rider_id = r.rider_id
        JOIN stages st ON st.stage_id = sr.stage_id
        JOIN race_editions re2 ON re2.edition_id = st.edition_id
        JOIN races ra ON ra.race_id = re2.race_id
        WHERE ra.name = 'Giro d''Italia'
          AND r.full_name NOT LIKE '% %'
        ORDER BY r.rider_id
    """).fetchall()

    print(f"{'[DRY RUN] ' if dry_run else ''}Fixing {len(rows)} riders with single-word names...")

    updated = 0
    unchanged = 0
    for row in rows:
        rider_id = row["rider_id"]
        current = row["full_name"]
        new_name = build_full_name(current, rider_id)

        if new_name == current:
            unchanged += 1
            continue

        if dry_run:
            print(f"  {rider_id}: {current!r} -> {new_name!r}")
        else:
            cur.execute("UPDATE riders SET full_name=? WHERE rider_id=?", (new_name, rider_id))
        updated += 1

    if not dry_run:
        conn.commit()
        print(f"Updated {updated} riders ({unchanged} already correct or no change)")
    else:
        print(f"\nWould update {updated} riders ({unchanged} no change)")

    conn.close()


if __name__ == "__main__":
    main()
