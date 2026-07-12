# DeepVac Inisght

A PySide6 desktop dashboard application.

## Project layout

```text
insight/
├── main.py              # entry point — run this
├── requirements.txt
├── app/                 # application package
│   ├── app.py           # QApplication bootstrap + splash screen
│   ├── main_window.py   # DeepVacDesktop main window
│   ├── common.py        # shared constants, path config, icon helpers
│   ├── title_bar.py, tab_system.py, chart_widget.py, run_tab.py
│   ├── services/
│   │   └── data_service.py   # run cache (sqlite), report generation
│   ├── views/            # one module per page (dashboard, runs, reports, simulator, monitoring, opc)
│   └── model/             # bundled GRU checkpoint + closed-loop simulator
│       ├── model.pt
│       └── simulation.py
├── resources/             # icons, logo, window icon
└── data/                  # local run cache + generated reports (gitignored)
    ├── deepvac_runs.sqlite3
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
