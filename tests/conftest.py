"""Shared pytest fixtures.

Deliberately minimal in Phase 1: just enough for `pytest` to collect and
run. Test-isolation fixtures for the runtime data directory (DEEPVAC_DATA_DIR
/ AppPaths) land in Phase 2; the Qt-specific fixtures (qapp/qtbot setup,
QSettings redirection, fake services) land in Phase 5.
"""
