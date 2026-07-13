"""Persisted UI state (theme, window geometry, open tabs, per-run channel
selections), stored via QSettings (DeepVac/Insight) rather than reset to
hardcoded defaults every launch.

This state is shared across accounts (not per-user) -- consistent with the
rest of the app treating runs, annotations, and variable rules as a single
shared workspace rather than per-user private data."""
from PySide6.QtCore import QSettings

ORG  = "DeepVac"
APP  = "Insight"


def _settings():
    return QSettings(ORG, APP)


# ── Theme ────────────────────────────────────────────────────────────────

def load_theme(default=True):
    return _settings().value("ui/dark", default, type=bool)


def save_theme(dark):
    _settings().setValue("ui/dark", bool(dark))


# ── Language ─────────────────────────────────────────────────────────────

def load_language(default="en"):
    value = _settings().value("ui/language", default)
    return value or default


def save_language(code):
    _settings().setValue("ui/language", str(code))


# ── Window geometry ──────────────────────────────────────────────────────

def load_window_geometry():
    value = _settings().value("window/geometry")
    return value if value else None


def save_window_geometry(geometry):
    _settings().setValue("window/geometry", geometry)


def load_window_maximized(default=True):
    return _settings().value("window/maximized", default, type=bool)


def save_window_maximized(maximized):
    _settings().setValue("window/maximized", bool(maximized))


# ── Open tabs ────────────────────────────────────────────────────────────

def load_open_tabs():
    value = _settings().value("tabs/open_keys", [])
    if isinstance(value, str):
        return [value] if value else []
    return list(value or [])


def save_open_tabs(keys):
    _settings().setValue("tabs/open_keys", list(keys))


def load_active_tab():
    value = _settings().value("tabs/active_key", "")
    return value or None


def save_active_tab(key):
    _settings().setValue("tabs/active_key", key or "")


# ── Per-run channel (column) selection ───────────────────────────────────

def load_channels(run_key):
    value = _settings().value(f"channels/{run_key}", [])
    if isinstance(value, str):
        return [value] if value else []
    return list(value or [])


def save_channels(run_key, channels):
    _settings().setValue(f"channels/{run_key}", list(channels))
