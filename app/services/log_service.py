"""Application-wide logging and a global exception hook.

Anything that escapes the try/except blocks scattered through the UI code
(a bug in a signal handler, a background QThread's own connected slot, etc.)
would otherwise fall through to whatever Qt/Python does by default -- often
just a console traceback the user never sees, or a silent crash. Installing
this replaces that with: always logged to data/logs/app.log, and shown to
the user in a dialog when a Qt application is running.
"""
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler

from app.common import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"

_logging_configured = False
_hook_installed = False


def setup_logging():
    global _logging_configured
    if _logging_configured:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    _logging_configured = True


def install_excepthook():
    """Route uncaught exceptions to the log file and, if a QApplication is
    running, a crash dialog. Safe to call more than once."""
    global _hook_installed
    if _hook_installed:
        return
    setup_logging()

    logger = logging.getLogger("deepvac.crash")
    previous_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            previous_hook(exc_type, exc_value, exc_tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.error("Unhandled exception:\n%s", text)
        _show_crash_dialog(exc_type, exc_value, text)
        previous_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
    _hook_installed = True


def _show_crash_dialog(exc_type, exc_value, text):
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None:
            return
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("Unexpected error")
        box.setText(
            f"An unexpected error occurred and has been logged:\n\n"
            f"{exc_type.__name__}: {exc_value}\n\n"
            f"Log file: {LOG_FILE}")
        box.setDetailedText(text)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()
    except Exception:
        # The crash dialog itself must never be able to crash the app.
        pass
