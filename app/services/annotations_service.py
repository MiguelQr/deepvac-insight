"""User-created chart annotations and variable rules for runs, in their own
local SQLite database. Each row is linked to the run it was made on (by
run key) and the user who made it (id + a denormalized name snapshot for
display, so authorship still reads correctly even if that user later
renames themselves)."""
import sqlite3
from datetime import datetime, timezone

from app.common import DATA_DIR

ANNOTATIONS_DB = DATA_DIR / "deepvac_annotations.sqlite3"


def connect_annotations():
    ANNOTATIONS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ANNOTATIONS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_key TEXT NOT NULL,
            user_id INTEGER,
            user_name TEXT NOT NULL DEFAULT 'Unknown',
            x0 REAL NOT NULL,
            x1 REAL NOT NULL,
            label TEXT NOT NULL,
            color TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_annotations_run ON annotations(run_key)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS variable_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_key TEXT NOT NULL,
            user_id INTEGER,
            user_name TEXT NOT NULL DEFAULT 'Unknown',
            name TEXT NOT NULL,
            channel TEXT NOT NULL,
            lo REAL,
            hi REAL,
            color TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rules_run ON variable_rules(run_key)")
    conn.commit()
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat()


def _annotation_row(row):
    return {
        "id": row["id"],
        "run_key": row["run_key"],
        "user_id": row["user_id"],
        "user_name": row["user_name"],
        "x0": row["x0"],
        "x1": row["x1"],
        "label": row["label"],
        "color": row["color"],
        "created_at": row["created_at"],
    }


def _rule_row(row):
    return {
        "id": row["id"],
        "run_key": row["run_key"],
        "user_id": row["user_id"],
        "user_name": row["user_name"],
        "name": row["name"],
        "channel": row["channel"],
        "lo": row["lo"],
        "hi": row["hi"],
        "color": row["color"],
        "created_at": row["created_at"],
    }


def list_annotations(run_key):
    conn = connect_annotations()
    try:
        rows = conn.execute(
            "SELECT * FROM annotations WHERE run_key = ? ORDER BY x0", (run_key,)
        ).fetchall()
        return [_annotation_row(r) for r in rows]
    finally:
        conn.close()


def add_annotation(run_key, user_id, user_name, x0, x1, label, color):
    conn = connect_annotations()
    try:
        cur = conn.execute(
            """
            INSERT INTO annotations (run_key, user_id, user_name, x0, x1, label, color, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_key, user_id, user_name or "Unknown", float(x0), float(x1),
             str(label), str(color), _now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM annotations WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _annotation_row(row)
    finally:
        conn.close()


def delete_annotation(annotation_id):
    conn = connect_annotations()
    try:
        conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
        conn.commit()
    finally:
        conn.close()


def list_rules(run_key):
    conn = connect_annotations()
    try:
        rows = conn.execute(
            "SELECT * FROM variable_rules WHERE run_key = ? ORDER BY id", (run_key,)
        ).fetchall()
        return [_rule_row(r) for r in rows]
    finally:
        conn.close()


def add_rule(run_key, user_id, user_name, name, channel, lo, hi, color):
    conn = connect_annotations()
    try:
        cur = conn.execute(
            """
            INSERT INTO variable_rules (run_key, user_id, user_name, name, channel, lo, hi, color, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_key, user_id, user_name or "Unknown", str(name), str(channel),
             float(lo) if lo is not None else None,
             float(hi) if hi is not None else None,
             str(color), _now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM variable_rules WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _rule_row(row)
    finally:
        conn.close()


def delete_rule(rule_id):
    conn = connect_annotations()
    try:
        conn.execute("DELETE FROM variable_rules WHERE id = ?", (rule_id,))
        conn.commit()
    finally:
        conn.close()
