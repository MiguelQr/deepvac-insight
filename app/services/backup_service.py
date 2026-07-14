"""Automated local backups for the app's SQLite databases.

Backs up every *.sqlite3 database directly under DATA_DIR (the run cache,
user accounts, and annotations databases) into data/backups/<name>/, using
sqlite3's own online backup API rather than a raw file copy -- safe even
while the source database has an open connection, unlike copying the file
bytes directly which can grab a half-written page.

Runs at most once per calendar day per database unless force=True, and
prunes old backups beyond a retention count so this can't grow unbounded.
"""

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.common import DATA_DIR

BACKUPS_DIR = DATA_DIR / "backups"
MAX_BACKUPS_PER_DB = 14


def _source_databases(data_dir):
    if not data_dir.exists():
        return []
    return sorted(data_dir.glob("*.sqlite3"))


def _today_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def backup_database(source_path, reason="startup", backups_dir=None):
    """Write one timestamped online backup of source_path. Returns the new path."""
    backups_dir = backups_dir or BACKUPS_DIR
    dest_dir = backups_dir / source_path.stem
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest_path = dest_dir / f"{source_path.stem}_{stamp}_{reason}.sqlite3"

    src_conn = sqlite3.connect(str(source_path))
    dest_conn = sqlite3.connect(str(dest_path))
    try:
        src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()
    return dest_path


def _prune(dest_dir, keep=MAX_BACKUPS_PER_DB):
    backups = sorted(dest_dir.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime)
    excess = len(backups) - keep
    for old in backups[: max(0, excess)]:
        old.unlink(missing_ok=True)


def backup_all(force=False, data_dir=None, backups_dir=None):
    """Back up every database in data_dir (default: DATA_DIR). Skips a
    database that already has a backup from today unless force=True. Never
    raises -- a backup failure is printed and skipped rather than blocking
    app startup."""
    data_dir = data_dir or DATA_DIR
    backups_dir = backups_dir or BACKUPS_DIR
    results = []
    stamp = _today_stamp()
    for source_path in _source_databases(data_dir):
        dest_dir = backups_dir / source_path.stem
        already_today = (
            not force
            and dest_dir.exists()
            and any(
                p.name.startswith(f"{source_path.stem}_{stamp}") for p in dest_dir.glob("*.sqlite3")
            )
        )
        if already_today:
            continue
        try:
            dest_path = backup_database(
                source_path, reason="manual" if force else "daily", backups_dir=backups_dir
            )
            _prune(dest_dir)
            results.append(dest_path)
        except Exception as exc:
            print(f"[backup] failed to back up {source_path.name}: {exc}")
    return results


def list_backups(backups_dir=None):
    """Return {db_stem: [backup Paths, oldest first]} for display/restore."""
    backups_dir = backups_dir or BACKUPS_DIR
    out: dict[str, list[Path]] = {}
    if not backups_dir.exists():
        return out
    for sub in sorted(backups_dir.iterdir()):
        if sub.is_dir():
            out[sub.name] = sorted(sub.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime)
    return out


def restore_backup(db_name, backup_path, data_dir=None, backups_dir=None):
    """Restore <data_dir>/<db_name> from a backup file. The live database is
    itself preserved first (reason 'pre-restore') so a bad restore can be
    undone. That safety copy is a raw file copy, not the sqlite online
    backup API used elsewhere in this module -- restore exists precisely
    for the case where the live database may already be damaged, and a
    raw copy preserves whatever bytes are on disk even then, whereas the
    backup API requires opening the source as a valid database first. Any
    -wal/-shm sidecar files for the live database are cleared so the
    restored file becomes the sole source of truth."""
    data_dir = data_dir or DATA_DIR
    backups_dir = backups_dir or BACKUPS_DIR
    target = data_dir / db_name
    if target.exists():
        dest_dir = backups_dir / target.stem
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        shutil.copyfile(target, dest_dir / f"{target.stem}_{stamp}_pre-restore.sqlite3")
    shutil.copyfile(backup_path, target)
    for suffix in ("-wal", "-shm"):
        sidecar = target.with_name(target.name + suffix)
        if sidecar.exists():
            sidecar.unlink()
