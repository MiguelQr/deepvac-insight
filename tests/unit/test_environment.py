"""Phase 1 placeholder: proves the test environment itself is wired up
correctly (right Python version, app package importable) before any real
test suites exist. Superseded in relevance once Phase 3/4/5 land, but kept
as a fast sanity check."""

import sys


def test_python_version_matches_requires_python():
    assert sys.version_info >= (3, 10)


def test_app_package_importable():
    import app  # noqa: F401
