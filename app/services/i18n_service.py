"""Language selection and Qt translator loading.

Source strings in the code are English, wrapped in self.tr(...) throughout
the UI modules. Translations are compiled .qm files (built from .ts files
via pyside6-lupdate/pyside6-lrelease) under resources/i18n/.

Widgets read their text once, at construction time, via tr() -- there is no
live retranslation machinery here (no LanguageChange event handling / UI
rebuild). Switching languages therefore takes effect on the next restart;
the Settings menu makes that explicit rather than silently doing nothing.
"""

from PySide6.QtCore import QTranslator

from app.common import RESOURCES_DIR

I18N_DIR = RESOURCES_DIR / "i18n"

AVAILABLE_LANGUAGES = {
    "en": "English",
    "es": "Español",
    "de": "Deutsch",
}

_installed_translator = None


def install_language(app, code):
    """Install the translator for `code` on `app`, replacing any previously
    installed one. code="en" (the source language) just removes any active
    translator. Returns True if a .qm file was loaded, False otherwise
    (including for "en", where none is needed)."""
    global _installed_translator

    if _installed_translator is not None:
        app.removeTranslator(_installed_translator)
        _installed_translator = None

    if code == "en":
        return False

    qm_path = I18N_DIR / f"deepvac_{code}.qm"
    if not qm_path.exists():
        return False

    translator = QTranslator(app)
    if not translator.load(str(qm_path)):
        return False

    app.installTranslator(translator)
    _installed_translator = translator
    return True
