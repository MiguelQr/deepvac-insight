"""Shared constants, pure utilities, and SVG icon helpers used across all modules."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

if getattr(sys, "frozen", False):
    # Running from a PyInstaller bundle: bundled read-only resources (icons,
    # translations, the model checkpoint) live under the bundle directory
    # (sys._MEIPASS for --onefile, the exe's own folder for --onedir -- both
    # are exposed via _MEIPASS). That directory may be inside Program Files
    # and isn't guaranteed writable, so user-writable state (databases,
    # logs, backups, generated reports) goes to %LOCALAPPDATA% instead,
    # which is what a real Windows install is expected to do.
    # _MEIPASS is set by PyInstaller's bootloader at runtime; it's not part
    # of typeshed's sys stub, hence the ignore.
    RESOURCES_DIR = Path(sys._MEIPASS) / "resources"  # type: ignore[attr-defined]
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DeepVac" / "data"
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    RESOURCES_DIR = PROJECT_ROOT / "resources"
    DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"

LOGO_PATH = str(RESOURCES_DIR / "logo.png")
ICON_PATH = str(RESOURCES_DIR / "icon.png")

COLORS = [
    "#8bd66f",
    "#4f7cff",
    "#51d6c7",
    "#f2bd52",
    "#ff6f7d",
    "#b792ff",
    "#f48fb1",
    "#7ec8ff",
]

RULE_COLOR_OPTIONS = [
    ("Blue", "#60a5fa"),
    ("Green", "#8bd66f"),
    ("Amber", "#f2bd52"),
    ("Red", "#ff6f7d"),
    ("Purple", "#b792ff"),
    ("Teal", "#51d6c7"),
]

_TAB_MIME = "application/deepvac-tab"
_gid = 0


def _new_gid() -> int:
    global _gid
    _gid += 1
    return _gid


def fmt(value, digits: int = 3) -> str:
    if value in (None, ""):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 1000:
        return f"{number:,.1f}"
    return f"{number:,.{digits}f}".rstrip("0").rstrip(".")


def csv_escape(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if any(ch in text for ch in [",", '"', "\n", "\r"]):
        return '"' + text.replace('"', '""') + '"'
    return text


def _render_svg(name: str, color: str, size: int = 20) -> QPixmap:
    path = RESOURCES_DIR / "icons" / f"{name}.svg"
    try:
        svg_bytes = path.read_text(encoding="utf-8").replace("currentColor", color).encode()
        renderer = QSvgRenderer(QByteArray(svg_bytes))
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap
    except Exception:
        return QPixmap()


def _svg_icon(name: str, color: str = "#94a3b8", size: int = 20) -> QIcon:
    px = _render_svg(name, color, size)
    return QIcon(px) if not px.isNull() else QIcon()


def _nav_icon(name: str, muted: str, accent: str, size: int = 22) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_render_svg(name, muted, size), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(_render_svg(name, accent, size), QIcon.Mode.Normal, QIcon.State.On)
    return icon
