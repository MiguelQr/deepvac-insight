"""User accounts: creation, authentication, profile updates, and
remember-me session tokens. Stored in their own local SQLite database,
separate from the run-data cache."""
import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone

from PySide6.QtCore import QCoreApplication

from app.common import DATA_DIR

AUTH_DB = DATA_DIR / "deepvac_users.sqlite3"
PBKDF2_ITERATIONS = 200_000


def _tr(text):
    # Not a QObject here, so QCoreApplication.translate() rather than
    # self.tr() -- pyside6-lupdate recognizes this pattern too.
    return QCoreApplication.translate("AuthService", text)


class AuthError(Exception):
    pass


def connect_auth():
    AUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            remember_token TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_remember_token ON users(remember_token)")
    conn.commit()
    return conn


def _hash_password(password, salt_hex=None):
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def _verify_password(password, salt_hex, hash_hex):
    computed, _ = _hash_password(password, salt_hex)
    return hmac.compare_digest(computed, hash_hex)


def _row_to_user(row):
    return {"id": row["id"], "name": row["name"], "email": row["email"]}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _normalize_email(email):
    return str(email).strip().lower()


def _validate_email(email):
    if "@" not in email or "." not in email.split("@")[-1] or email.startswith("@"):
        raise AuthError(_tr("Enter a valid email address."))


def user_count():
    conn = connect_auth()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def create_user(name, email, password):
    name = str(name).strip()
    email = _normalize_email(email)
    if not name:
        raise AuthError(_tr("Name is required."))
    _validate_email(email)
    if len(password) < 8:
        raise AuthError(_tr("Password must be at least 8 characters."))

    password_hash, salt = _hash_password(password)
    now = _now()
    conn = connect_auth()
    try:
        try:
            cur = conn.execute(
                """
                INSERT INTO users (name, email, password_hash, password_salt, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, email, password_hash, salt, now, now),
            )
        except sqlite3.IntegrityError:
            raise AuthError(_tr("An account with this email already exists."))
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_user(row)
    finally:
        conn.close()


def authenticate(email, password):
    email = _normalize_email(email)
    conn = connect_auth()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row or not _verify_password(password, row["password_salt"], row["password_hash"]):
            return None
        return _row_to_user(row)
    finally:
        conn.close()


def get_user(user_id):
    conn = connect_auth()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None
    finally:
        conn.close()


def get_user_by_token(token):
    if not token:
        return None
    conn = connect_auth()
    try:
        row = conn.execute("SELECT * FROM users WHERE remember_token = ?", (token,)).fetchone()
        return _row_to_user(row) if row else None
    finally:
        conn.close()


def set_remember_token(user_id):
    token = secrets.token_hex(32)
    conn = connect_auth()
    try:
        conn.execute("UPDATE users SET remember_token = ? WHERE id = ?", (token, user_id))
        conn.commit()
    finally:
        conn.close()
    return token


def clear_remember_token(token):
    conn = connect_auth()
    try:
        conn.execute(
            "UPDATE users SET remember_token = NULL WHERE remember_token = ?", (token,)
        )
        conn.commit()
    finally:
        conn.close()


def update_profile(user_id, name=None, email=None):
    conn = connect_auth()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthError(_tr("User not found."))
        new_name = str(name).strip() if name is not None else row["name"]
        new_email = _normalize_email(email) if email is not None else row["email"]
        if not new_name:
            raise AuthError(_tr("Name is required."))
        _validate_email(new_email)
        try:
            conn.execute(
                "UPDATE users SET name = ?, email = ?, updated_at = ? WHERE id = ?",
                (new_name, new_email, _now(), user_id),
            )
        except sqlite3.IntegrityError:
            raise AuthError(_tr("An account with this email already exists."))
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row)
    finally:
        conn.close()


def change_password(user_id, current_password, new_password):
    conn = connect_auth()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthError(_tr("User not found."))
        if not _verify_password(current_password, row["password_salt"], row["password_hash"]):
            raise AuthError(_tr("Current password is incorrect."))
        if len(new_password) < 8:
            raise AuthError(_tr("New password must be at least 8 characters."))
        password_hash, salt = _hash_password(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ?, password_salt = ?, updated_at = ? WHERE id = ?",
            (password_hash, salt, _now(), user_id),
        )
        conn.commit()
    finally:
        conn.close()
