#!/usr/bin/env python3
"""One-off: repair names that arrived as mojibake, and the ids minted from them.

Both upstreams shipped UTF-8 decoded through a single-byte codec, inside rows
that were otherwise clean: PCS served "Martens René" correctly and
"Banque d'Ã‰pargne" corrupted in the SAME row; Athlinks served "Emil √Öberg"
(Å) and "Lukas L√∂er" (ö) for Unbound 2025. race_common.fix_mojibake now
catches all of it at ingest, so this script exists only to clean what was
already stored before that landed.

Two id policies, and the difference is the whole point:

  * A gravel rider's `rider_id` was minted by OUR link_gravel_riders.slugify()
    from the corrupted string — PCS has no gravel coverage, so no upstream id
    exists and we own it outright. "√Öberg" slugified to "emil-oberg", which
    reads as Ø and is wrong twice over. Those ARE re-slugged.

  * A team's `team_id` came out of a PCS href. `team/sefb-banque-d-a-pargne-1987`
    is PCS's own identifier, generated from PCS's own corrupted name. Renaming
    it would silently break the join to the source and to every scrape file on
    disk. That id is left exactly as PCS spells it; only the display name is
    repaired. Same rule as the four upstream PCS bib collisions.

Usage:
  python3 repair_mojibake_names.py --dry-run     # change table only, no writes
  python3 repair_mojibake_names.py               # apply
"""
import argparse
import glob
import json
import os
import sqlite3
import sys

from race_common import (
    DB_PATH,
    GRAVEL,
    SOURCE_ATHLINKS,
    SOURCE_PCS,
    exit_on_help,
    fix_mojibake,
    record_provenance,
)
from link_gravel_riders import fold, slugify

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.basename(__file__)

# Every column that stores a human-readable name, by table and primary key.
NAME_COLUMNS = {
    "riders": ("rider_id", ["full_name", "first_name", "last_name"]),
    "teams": ("team_id", ["name"]),
    "races": ("race_id", ["name"]),
}

SOURCE_FOR = {"riders": None, "teams": SOURCE_PCS, "races": SOURCE_PCS}


def scrape_files():
    for pat in ("*_scrapes/**/*.json", "scrapes/**/*.json"):
        yield from sorted(glob.glob(os.path.join(HERE, pat), recursive=True))


def repair_json(obj):
    """Recursively repair every string. Returns (new_obj, n_changed)."""
    if isinstance(obj, dict):
        out, n = {}, 0
        for k, v in obj.items():
            nv, c = repair_json(v)
            out[k], n = nv, n + c
        return out, n
    if isinstance(obj, list):
        out, n = [], 0
        for v in obj:
            nv, c = repair_json(v)
            out.append(nv)
            n += c
        return out, n
    if isinstance(obj, str):
        fixed = fix_mojibake(obj)
        return fixed, int(fixed != obj)
    return obj, 0


def corrupted_strings(obj, out):
    """Collect every distinct string in `obj` that fix_mojibake would change."""
    if isinstance(obj, dict):
        for v in obj.values():
            corrupted_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            corrupted_strings(v, out)
    elif isinstance(obj, str):
        fixed = fix_mojibake(obj)
        if fixed != obj:
            out[obj] = fixed
    return out


def rewrite_strings_in_place(path):
    """Replace the corrupted substrings textually, leaving formatting alone.

    These twelve files are written by four different scripts in three different
    json.dump styles (compact, indent=1+sorted, and library default). Re-dumping
    would reformat every line of a file to fix one string, burying a two-name
    repair in a 40k-line diff. The corrupted strings are distinctive enough to
    replace literally; longest-first so "Emil √Öberg" is handled before the
    bare "√Öberg" it contains.
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()
    pairs = corrupted_strings(json.loads(text), {})
    for old in sorted(pairs, key=len, reverse=True):
        text = text.replace(old, pairs[old])
    json.loads(text)  # a formatting-preserving edit must still parse
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def gravel_only_riders(cur):
    """Riders whose every result is off-road, so their id is ours to change.

    PCS publishes nothing for these six races (verified), so a rider seen only
    here was never given an upstream id and cannot be re-joined to one.
    """
    names = tuple(i.name for i in GRAVEL.values())
    q = ",".join("?" * len(names))
    cur.execute(f"""
        SELECT sr.rider_id
          FROM stage_results sr
          JOIN stages s          ON s.stage_id  = sr.stage_id
          JOIN race_editions re  ON re.edition_id = s.edition_id
          JOIN races ra          ON ra.race_id  = re.race_id
         GROUP BY sr.rider_id
        HAVING SUM(CASE WHEN ra.name IN ({q}) THEN 0 ELSE 1 END) = 0""", names)
    return {r[0] for r in cur.fetchall()}


def plan(cur):
    """Every change this script would make, as a list of dicts."""
    changes = []
    for table, (pk, cols) in NAME_COLUMNS.items():
        for row in cur.execute(f"SELECT {pk},{','.join(cols)} FROM {table}"):
            for col, val in zip(cols, row[1:]):
                if not val:
                    continue
                fixed = fix_mojibake(val)
                if fixed != val:
                    changes.append({"kind": "name", "table": table, "pk": pk,
                                    "id": row[0], "col": col,
                                    "old": val, "new": fixed})
    gravel = gravel_only_riders(cur)
    for ch in [c for c in changes if c["table"] == "riders" and c["col"] == "full_name"]:
        if ch["id"] not in gravel:
            continue
        new_id = "rider/" + slugify(ch["new"])
        if new_id == ch["id"]:
            continue
        cur.execute("SELECT 1 FROM riders WHERE rider_id=?", (new_id,))
        if cur.fetchone():
            print(f"  SKIP re-slug {ch['id']} -> {new_id}: already taken", file=sys.stderr)
            continue
        changes.append({"kind": "reslug", "table": "riders", "pk": "rider_id",
                        "id": ch["id"], "col": "rider_id",
                        "old": ch["id"], "new": new_id})
    return changes


def print_table(changes, json_hits):
    print(f"\n{'KIND':<8} {'TABLE.COLUMN':<22} {'OLD':<50} -> NEW")
    print("-" * 118)
    for c in sorted(changes, key=lambda c: (c["kind"], c["table"], c["id"])):
        print(f"{c['kind']:<8} {c['table'] + '.' + c['col']:<22} {c['old']!r:<50} -> {c['new']!r}")
    print(f"\n{len(changes)} DB changes")
    total = sum(json_hits.values())
    print(f"{total} string(s) in {len(json_hits)} scrape file(s)")
    for p, n in sorted(json_hits.items()):
        print(f"   {n:>3}  {os.path.relpath(p, HERE)}")


def apply_db(cur, changes):
    for c in (c for c in changes if c["kind"] == "name"):
        cur.execute(f"UPDATE {c['table']} SET {c['col']}=? WHERE {c['pk']}=?",
                    (c["new"], c["id"]))
        src = SOURCE_FOR[c["table"]]
        if src is None:  # riders: gravel names come from Athlinks, road from PCS
            src = SOURCE_ATHLINKS if c["id"].startswith("rider/") and _is_gravel(cur, c["id"]) else SOURCE_PCS
        record_provenance(cur, c["table"], c["id"], c["col"], src,
                          source_ref="mojibake repair of the stored upstream value",
                          script=SCRIPT)
    for c in (c for c in changes if c["kind"] == "reslug"):
        old, new = c["old"], c["new"]
        cur.execute("UPDATE riders SET rider_id=? WHERE rider_id=?", (new, old))
        for tbl in ("stage_results", "classification_standings"):
            cur.execute(f"UPDATE {tbl} SET rider_id=? WHERE rider_id=?", (new, old))
        # Carry provenance to the new key, or the rows orphan.
        cur.execute("""UPDATE data_provenance SET entity_id=?
                        WHERE entity='riders' AND entity_id=?""", (new, old))
        record_provenance(cur, "riders", new, "rider_id", SOURCE_ATHLINKS,
                          source_ref=f"re-slugged from {old}, minted from a mojibake name",
                          script=SCRIPT)


_GRAVEL_CACHE = {}


def _is_gravel(cur, rid):
    if not _GRAVEL_CACHE:
        _GRAVEL_CACHE.update({r: True for r in gravel_only_riders(cur)})
    return _GRAVEL_CACHE.get(rid, False)


def apply_rider_ids_json(changes):
    """_rider_ids.json is keyed by folded name and stores the minted id."""
    path = os.path.join(HERE, "gravel_scrapes", "_rider_ids.json")
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    reslug = {c["old"]: c["new"] for c in changes if c["kind"] == "reslug"}
    out, n = {}, 0
    for key, ident in data.items():
        ident, _ = repair_json(ident)
        if ident.get("rider_id") in reslug:
            ident["rider_id"] = reslug[ident["rider_id"]]
            n += 1
        # Exactly fold(name).strip() — verified to reproduce all 3,569 existing
        # keys. Do NOT collapse internal runs of spaces: fold() maps each
        # stripped punctuation character to its own space, so "alex howes - gu"
        # legitimately keys as "alex howes   gu", and normalising that would
        # silently unlink 23 riders from their scrape rows.
        new_key = fold(ident.get("name") or key).strip()
        if new_key != key:
            n += 1
        out[new_key] = ident
    with open(path, "w", encoding="utf-8") as f:
        # Byte-identical to how link_gravel_riders.py writes this file, down to
        # the absent trailing newline — otherwise its next run reverts ours.
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    return n


def main(argv):
    exit_on_help(__doc__, argv)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    changes = plan(cur)

    json_hits = {}
    for p in scrape_files():
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        _, n = repair_json(data)
        if n:
            json_hits[p] = n

    print_table(changes, json_hits)

    if args.dry_run:
        print("\n--dry-run: nothing written")
        conn.close()
        return 0

    for p in json_hits:
        rewrite_strings_in_place(p)
    n_ids = apply_rider_ids_json(changes)
    apply_db(cur, changes)
    conn.commit()
    conn.close()
    print(f"\nwrote {len(changes)} DB changes, {len(json_hits)} scrape files, "
          f"{n_ids} _rider_ids.json edits")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
