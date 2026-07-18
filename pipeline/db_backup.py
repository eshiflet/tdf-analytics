#!/usr/bin/env python3
"""
Rotating backups of cycling.db.

cycling.db is NOT regenerable — most historical years' raw scrape files no
longer exist, so the DB is the only copy of that data. Any script that
deletes/re-inserts editions should call backup_db() first.

Usage:
  python3 db_backup.py            # take a backup now
  from db_backup import backup_db # programmatic use

Backups go to pipeline/db_backups/cycling.db.YYYYMMDD-HHMMSS; the newest
KEEP_COUNT are retained, older ones are pruned.
"""

import os
import sqlite3
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
BACKUP_DIR = os.path.join(HERE, "db_backups")
KEEP_COUNT = 5


def backup_db(label: str = "") -> str:
    """Snapshot cycling.db into db_backups/ and prune old backups.

    Uses the sqlite3 backup API so the copy is consistent even if another
    process holds the DB open. Returns the backup path.
    """
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"{DB_PATH} not found")

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f".{label}" if label else ""
    dest_path = os.path.join(BACKUP_DIR, f"cycling.db.{stamp}{suffix}")

    src = sqlite3.connect(DB_PATH)
    dest = sqlite3.connect(dest_path)
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()

    # Prune: keep the newest KEEP_COUNT backups
    backups = sorted(
        (f for f in os.listdir(BACKUP_DIR) if f.startswith("cycling.db.")),
        reverse=True,
    )
    for old in backups[KEEP_COUNT:]:
        os.remove(os.path.join(BACKUP_DIR, old))

    size_mb = os.path.getsize(dest_path) / 1024 / 1024
    print(f"  DB backed up to {os.path.relpath(dest_path, HERE)} ({size_mb:.0f} MB)")
    return dest_path


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else ""
    backup_db(label)
