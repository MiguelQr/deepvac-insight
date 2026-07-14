"""Checks coverage.json (produced by `pytest --cov=app --cov-report=json`)
against a small set of per-file and whole-project line-coverage floors.

Deliberately not a single global threshold: app/model/simulation.py and
(from Phase 4 on) app/services/data_service.py are the two modules where a
silent regression would be hardest to notice by eye, so they get a much
higher bar than the project as a whole -- most of the codebase is PySide6
UI code covered by Phase 5's smoke tests, not exhaustively unit tested.

Usage:
    uv run pytest --cov=app --cov-branch --cov-report=json
    uv run python scripts/check_coverage.py
"""

import json
import sys
from pathlib import Path

COVERAGE_JSON = Path(__file__).resolve().parent.parent / "coverage.json"

# path (relative to repo root, forward slashes) -> minimum % line coverage.
PER_FILE_THRESHOLDS = {
    "app/model/simulation.py": 85.0,
    "app/services/data_service.py": 65.0,
}
PROJECT_THRESHOLD = 30.0


def _percent_covered(file_summary):
    return file_summary["summary"]["percent_covered"]


def main():
    if not COVERAGE_JSON.exists():
        print(f"ERROR: {COVERAGE_JSON} not found -- run pytest with --cov-report=json first.")
        return 1

    data = json.loads(COVERAGE_JSON.read_text(encoding="utf-8"))
    failures = []

    for rel_path, threshold in PER_FILE_THRESHOLDS.items():
        # coverage.py's JSON report keys files by the path it discovered
        # them at, which may use OS-native separators -- normalize both
        # sides to forward slashes before matching.
        match = next(
            (f for p, f in data["files"].items() if p.replace("\\", "/") == rel_path), None
        )
        if match is None:
            failures.append(
                f"{rel_path}: not found in coverage.json (was it imported by any test?)"
            )
            continue
        actual = _percent_covered(match)
        if actual < threshold:
            failures.append(f"{rel_path}: {actual:.1f}% < required {threshold:.1f}%")
        else:
            print(f"OK   {rel_path}: {actual:.1f}% >= {threshold:.1f}%")

    project_actual = data["totals"]["percent_covered"]
    if project_actual < PROJECT_THRESHOLD:
        failures.append(f"whole project: {project_actual:.1f}% < required {PROJECT_THRESHOLD:.1f}%")
    else:
        print(f"OK   whole project: {project_actual:.1f}% >= {PROJECT_THRESHOLD:.1f}%")

    if failures:
        print("\nCoverage check FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nAll coverage thresholds met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
