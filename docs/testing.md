# Testing

## Layout

```text
tests/
  conftest.py           shared fixtures (see "Isolation" below)
  unit/
    model/               ChamberPID, CodesysDiff, GRUModel, simulate_candidate()
    services/            CSV parsing, bounded_float/make_sim_args, environment sanity
  integration/           sqlite cache, report generation, the golden simulation fixture
  ui/                    PySide6 widget/navigation/startup smoke tests
  fixtures/
    runs/valid_run/       a realistic run_samples.csv/run_summary.csv/band_metrics.csv
    simulation/            golden_case_1.json (see below)
```

`unit` tests touch no filesystem beyond what pytest's own `tmp_path`
fixture provides them directly. `integration` tests use real sqlite files
and real CSV parsing, but always through the isolation fixtures below.
`ui` tests construct real PySide6 widgets under `QT_QPA_PLATFORM=offscreen`.

Markers (`pyproject.toml`'s `[tool.pytest.ini_options]`): `unit`,
`integration`, `ui`, `slow`, `packaging`. `integration` in particular
marks anything that loads the real `app/model/model.pt` checkpoint --
those are slower (real GRU inference) and are what
`pytest tests/integration -m integration` selects.

## Isolation: no test may touch real user data

This is the one rule everything else here supports: no test process may
ever read or write `%LOCALAPPDATA%\DeepVac\data` or the source-tree
`data/` directory (the real 52 MB run cache, real accounts, real
backups). Two mechanisms:

1. **`app/common.py`'s `resolve_app_paths()`** resolves the writable data
   directory from (in priority order) an explicit override parameter, the
   `DEEPVAC_DATA_DIR` environment variable, or the unchanged production
   default. With neither set, nothing about this changes production
   behavior.
2. **`tests/conftest.py`'s `deepvac_data_dir` fixture** sets
   `DEEPVAC_DATA_DIR` to a fresh `tmp_path` *and* directly monkeypatches
   the already-resolved module-level constants (`app.common.DATA_DIR`,
   `auth_service.AUTH_DB`, `data_service.CACHE_DB`,
   `annotations_service.ANNOTATIONS_DB`, `backup_service.DATA_DIR`/
   `BACKUPS_DIR`). The second part is necessary because `app.common` is
   almost certainly already imported by the time any test runs -- module
   import is a process-wide singleton, so setting the environment variable
   alone can't retroactively change a constant that was already computed
   from it.

Integration tests that also need to control *source* discovery (where
`sync_cache()`/`upload_runs()` look for run folders) additionally set
`DEEPVAC_DATA_ROOT` to an empty `tmp_path` directory (see the
`fake_workspace` fixture in `tests/integration/test_data_service_cache.py`
and the `deepvac_ui` fixture in `tests/conftest.py`) -- otherwise
`workspace_root()`'s directory-walking fallback could wander off and find
a real deepvac workspace folder that happens to exist on whatever machine
runs the suite.

If you add a new module-level path constant to a service (another
`SOMETHING_DB = DATA_DIR / "..."`), add it to `deepvac_data_dir` too.

## UI test fixtures (`tests/conftest.py`)

- **`QT_QPA_PLATFORM=offscreen`** is set at module import time (before
  pytest-qt can import PySide6), via `os.environ.setdefault` so an
  explicit override is respected.
- **`no_modal_dialogs`** (autouse): `QMessageBox` statics are recorded
  instead of shown. A real `.exec()` here would hang the test forever
  with nothing to dismiss it.
- **`no_blocking_menus`** (autouse): Settings/Account are `QMenu.exec()`
  calls -- also a real blocking event loop. **Monkeypatching `QMenu.exec`
  on the class does not work** -- confirmed by direct reproduction, it's a
  Shiboken/C++-backed instance method, not a plain Python one, and the
  real `exec()` still ran and hung the process. The fix used instead is
  the standard one for this: a `QTimer` polling
  `QApplication.activePopupWidget()` and closing whatever it finds. If you
  add a test that opens some other blocking Qt dialog/menu and it hangs,
  this is probably why -- check whether it's a `QMessageBox` (patch it),
  a `QMenu` (already handled by this fixture), or something else that
  needs the same `activePopupWidget()`-polling treatment.
- **`qsettings_isolated`**: redirects `QSettings("DeepVac", "Insight")` to
  an INI file under `tmp_path` instead of the real registry key.
- **`deepvac_ui`**: composes `deepvac_data_dir` + `qsettings_isolated` +
  an empty `DEEPVAC_DATA_ROOT` + the shared `qapp`. Tears down by closing
  every top-level window and asserting no `QThread` is still running.
- **`fake_user`**: a throwaway in-memory user dict, same approach
  `app.app._run_smoke_test()` uses for `--smoke-test` -- bypasses real
  login for tests that only need *a* `current_user` to construct widgets.

A UI test that hangs should fail within a couple seconds via pytest's own
collection/teardown, not spin forever -- if you see a genuine hang, it's
almost always an unpatched blocking Qt call, not a fixture problem.

## The golden simulation fixture

`tests/fixtures/simulation/golden_case_1.json` is a frozen snapshot of
`simulate_candidate()`'s output against the *real* production checkpoint
(`app/model/model.pt`) for one fixed scenario (candidate gains, start/
target temp, duration). `tests/integration/test_simulation_golden.py`
re-runs that exact scenario and compares the resulting trajectory and
metrics against the stored values within a small tolerance.

**What it protects against:** a regression in `ChamberPID`, `CodesysDiff`,
`GRUModel`, or `simulate_candidate()`'s wiring that changes real numerical
behavior without anyone noticing -- the domain-specific control-loop code
that would otherwise have nothing catching a silent regression.

**It is never regenerated automatically.** `scripts/update_simulation_golden.py`
does that, and only when run explicitly with `--confirm`:

```powershell
uv run python scripts/update_simulation_golden.py --confirm
```

**Why this requires engineering review, not just running the script:** if
the fixture is stale because of a genuine bug, blindly regenerating it
just makes the "golden" file agree with the wrong behavior -- the test
would go back to green while quietly protecting nothing. Only regenerate
it when you can explain *why* the trajectory changed (a deliberately
retrained checkpoint, an intentional change to the PID/Diff/GRU math) and
have reviewed the diff between the old and new fixture values, not just
re-run the generator and committed whatever came out.

## Coverage thresholds

`scripts/check_coverage.py` reads `coverage.json` and enforces:

| Path | Floor | Actual (last measured) |
|---|---|---|
| `app/model/simulation.py` | 85% | 100% |
| `app/services/data_service.py` | 65% | 81% |
| whole project | 30% | 47% |

These are floors, not targets -- there's no requirement to chase 100%
project-wide, and "don't exclude a hard branch just to hit the number" is
the operating rule when a coverage gap does need closing (see e.g. the
cooling-vs-heating overshoot branch and the empty-tail-mask fallback in
`tests/unit/model/test_simulate_candidate.py`, both added specifically
because they showed up as uncovered, not because they were high-risk).
