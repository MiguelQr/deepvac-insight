"""Application-wide logging and a global exception hook.

Anything that escapes the try/except blocks scattered through the UI code
(a bug in a signal handler, a background QThread's own connected slot, etc.)
would otherwise fall through to whatever Qt/Python does by default -- often
just a console traceback the user never sees, or a silent crash. Installing
this replaces that with: always logged to data/logs/app.log, and shown to
the user in a dialog when a Qt application is running.
"""

import contextlib
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler

from app.common import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"

_logging_configured = False
_hook_installed = False
_exception_listeners = []


def setup_logging():
    global _logging_configured
    if _logging_configured:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    _logging_configured = True


def install_excepthook(show_dialog=True):
    """Route uncaught exceptions to the log file and, if a QApplication is
    running and show_dialog is True, a crash dialog. show_dialog=False is
    for --smoke-test: a blocking QMessageBox.exec() with nothing to dismiss
    it would hang the process forever instead of exiting automatically.
    Safe to call more than once (later calls are a no-op, same as before --
    show_dialog only takes effect on the first, installing call)."""
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
        for listener in _exception_listeners:
            with contextlib.suppress(Exception):
                listener(exc_type, exc_value, exc_tb)
        if show_dialog:
            _show_crash_dialog(exc_type, exc_value, text)
        previous_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
    _hook_installed = True


def add_exception_listener(callback):
    """Register callback(exc_type, exc_value, exc_tb), invoked whenever the
    global excepthook fires (in addition to logging/the dialog). This is
    what lets --smoke-test detect an exception raised inside a Qt signal/
    slot callback during app.exec() -- those never propagate as a normal
    Python exception to the calling frame the way a synchronous one would."""
    _exception_listeners.append(callback)


def _show_crash_dialog(exc_type, exc_value, text):
    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()
        if app is None:
            return

        def tr(s):
            return QCoreApplication.translate("LogService", s)

        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle(tr("Unexpected error"))
        box.setText(
            tr("An unexpected error occurred and has been logged:")
            + "\n\n"
            + f"{exc_type.__name__}: {exc_value}\n\n"
            + tr("Log file: {0}").format(LOG_FILE)
        )
        box.setDetailedText(text)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()
    except Exception:
        # The crash dialog itself must never be able to crash the app.
        pass
