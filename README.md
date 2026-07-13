# DeepVac Inisght

A PySide6 desktop dashboard application.

## Project layout

```text
insight/
├── main.py              # entry point — run this
├── requirements.txt
├── app/                 # application package
│   ├── app.py           # QApplication bootstrap, login flow, splash screen
│   ├── main_window.py   # DeepVacDesktop main window
│   ├── login_window.py  # sign in / create account screen
│   ├── profile_dialog.py# change name, email, password
│   ├── common.py        # shared constants, path config, icon helpers
│   ├── title_bar.py, tab_system.py, chart_widget.py, run_tab.py
│   ├── services/
│   │   ├── data_service.py         # run cache (sqlite), report generation
│   │   ├── auth_service.py         # user accounts (sqlite), password hashing, sessions
│   │   ├── annotations_service.py  # chart annotations + variable rules (sqlite), per run/user
│   │   └── backup_service.py       # automated sqlite backups + restore
│   ├── views/            # one module per page (dashboard, runs, reports, simulator, monitoring, opc)
│   └── model/             # bundled GRU checkpoint + closed-loop simulator
│       ├── model.pt
│       └── simulation.py
├── resources/             # icons, logo, window icon
└── data/                  # local run cache + generated reports (gitignored)
    ├── deepvac_runs.sqlite3
    ├── deepvac_users.sqlite3
    ├── deepvac_annotations.sqlite3
    ├── backups/            # rotating daily backups of the databases above
    └── reports/
```

## Install

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

## Local run database

On startup, the app syncs the current run history into:

```text
data\deepvac_runs.sqlite3
```

Generated reports are written to `data\reports\`.

## Accounts

The app always opens to a sign-in screen, backed by `data\deepvac_users.sqlite3`
(passwords are salted + PBKDF2-hashed, never stored in plain text). A "Create
one" link on the login form switches to registration. "Remember me" persists
a session token via `QSettings` (`DeepVac`/`Insight`) so the app skips the
login screen on the next launch; logging out clears it. "Profile" (from the
account icon in the sidebar) lets the signed-in user change their name,
email, and password.

## Annotations & variable rules

Chart annotations (drag-to-label a time range) and variable rules (min/max
bands per channel), created from the Analysis tab, are persisted to
`data\deepvac_annotations.sqlite3` — keyed by the run and the user who
created them — instead of only living in memory. They survive closing the
tab, closing the app, and are visible to any user who opens that run, with
the creator's name shown alongside each one.

## Backups

Every `*.sqlite3` database under `data\` is backed up automatically — once
at startup, and rechecked every 6 hours for sessions left open across a day
boundary — into `data\backups\<name>\`, using SQLite's own online backup API
(safe even while the database is in use). Each database keeps its 14 most
recent backups. Use the gear icon → **Back Up Now** to force an extra backup,
or **Open Backups Folder** to browse them. To restore, call
`backup_service.restore_backup(db_name, backup_path)` — it safety-copies the
current (possibly damaged) database first, so a bad restore can be undone.
