"""Shared pytest fixtures.

Qt-specific fixtures (qapp/qtbot setup, QSettings redirection, fake
services) land in Phase 5.
"""

import pytest


@pytest.fixture
def deepvac_data_dir(tmp_path, monkeypatch):
    """Redirect every database/log/backup/report path this app writes to
    into an isolated tmp_path, so tests never touch the real
    %LOCALAPPDATA%\\DeepVac\\data (or the source-tree data/ dir in a dev
    checkout). Never point a test at the real 52 MB run database.

    Two mechanisms, both pointed at the same directory:

    1. The DEEPVAC_DATA_DIR environment variable (app/common.py's
       resolve_app_paths() reads this) -- correct for anything imported
       for the first time *after* this fixture runs, and for subprocess
       cases like the frozen --smoke-test.
    2. Directly monkeypatching the small, fixed set of already-resolved
       module-level path constants (app.common.DATA_DIR/REPORTS_DIR and
       each service's own DB_PATH-style constant) -- needed because
       app.common is almost certainly already imported by the time any
       test runs (module import is a process-wide singleton), so the env
       var alone can't retroactively change constants that were computed
       from it at import time.

    Not reset here: log_service's setup_logging()/install_excepthook() are
    explicitly idempotent (guarded by a module-level flag, safe to call
    more than once) and don't reopen their file handler for a new
    directory on a second call. No current test suite depends on
    per-test log isolation; if one starts to, that guard is the thing
    to revisit.
    """
    data_dir = tmp_path / "deepvac_data"
    monkeypatch.setenv("DEEPVAC_DATA_DIR", str(data_dir))

    import app.common as common

    monkeypatch.setattr(common, "DATA_DIR", data_dir)
    monkeypatch.setattr(common, "REPORTS_DIR", data_dir / "reports")

    import app.services.annotations_service as annotations_service
    import app.services.auth_service as auth_service
    import app.services.backup_service as backup_service
    import app.services.data_service as data_service

    monkeypatch.setattr(auth_service, "AUTH_DB", data_dir / "deepvac_users.sqlite3")
    monkeypatch.setattr(data_service, "CACHE_DB", data_dir / "deepvac_runs.sqlite3")
    monkeypatch.setattr(
        annotations_service, "ANNOTATIONS_DB", data_dir / "deepvac_annotations.sqlite3"
    )
    monkeypatch.setattr(backup_service, "DATA_DIR", data_dir)
    monkeypatch.setattr(backup_service, "BACKUPS_DIR", data_dir / "backups")

    return data_dir
