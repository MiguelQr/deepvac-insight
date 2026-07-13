"""Analysis tab page (RunTabPage) shown for each opened run, plus SimWorker."""
import csv

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget, QWidgetAction,
)

from app.common import COLORS, RULE_COLOR_OPTIONS, fmt, csv_escape, _svg_icon
from app.chart_widget import ChartWidget
import app.services.data_service as data
import app.services.annotations_service as annotations_service
import app.services.settings_service as settings_service


class SimWorker(QThread):
    finished_ok = Signal(dict)
    failed      = Signal(str)

    def __init__(self, payload):
        super().__init__()
        self.payload = payload

    def run(self):
        try:
            self.finished_ok.emit(data.simulate_gru_run(self.payload))
        except Exception as exc:
            self.failed.emit(str(exc))


class RunTabPage(QWidget):
    compare_changed = Signal(set)

    def __init__(self, run_key, all_runs, dark=True, current_user=None, parent=None):
        super().__init__(parent)
        self.run_key          = run_key
        self.all_runs         = all_runs
        self.active_run       = run_key
        self.detail           = None
        self.series           = None
        self.selected_columns = set()  # populated in load() from saved settings or defaults
        self._channel_colors  = {}
        self.compare_runs     = {run_key}
        self.dark             = dark
        self.current_user       = current_user or {"id": None, "name": "Unknown", "email": ""}
        self._user_annotations  = []   # [{id, x0, x1, label, color, user_name, ...}] — persisted
        self._ann_list_layout   = None
        self._var_rules         = []   # [{id, name, channel, lo, hi, color, user_name, ...}] — persisted
        self._rule_ch_combo     = None
        self._rules_list_layout = None
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("workspaceScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("workspaceBody")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(14, 14, 14, 14)
        self._body_layout.setSpacing(10)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # Chart card
        chart_card = QFrame()
        chart_card.setObjectName("card")
        chart_card_lay = QVBoxLayout(chart_card)
        chart_card_lay.setContentsMargins(10, 10, 10, 10)
        chart_card_lay.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)

        self.title_label = QLabel("Loading…")
        self.title_label.setObjectName("title")
        toolbar.addWidget(self.title_label)

        self.run_metric_labels = {}
        for lbl, key in [("Samples", "samples"), ("Duration", "duration")]:
            toolbar.addWidget(self._inline_stat(lbl, key))
        toolbar.addStretch(1)

        self._ch_btn = QPushButton("Channels ▾")
        self._ch_btn.setObjectName("secondaryButton")
        self._ch_btn.clicked.connect(self._open_channels_menu)

        self.chart_mode = QComboBox()
        self.chart_mode.addItems(["line", "scatter"])
        self.chart_mode.currentTextChanged.connect(self.refresh_chart)

        self.show_setpoint = QCheckBox("Setpoint")
        self.show_setpoint.setChecked(True)
        self.show_setpoint.stateChanged.connect(self.refresh_chart)

        self.setpoint_value = QLineEdit("0")
        self.setpoint_value.setFixedWidth(64)
        self.setpoint_value.textChanged.connect(self.refresh_chart)

        reset_btn = QPushButton("Reset View")
        reset_btn.setIcon(_svg_icon("arrow-counterclockwise", "#94a3b8", 14))
        reset_btn.setIconSize(QSize(14, 14))
        reset_btn.clicked.connect(self._reset_views)

        self._ann_btn = QPushButton("Annotate")
        self._ann_btn.setCheckable(True)
        self._ann_btn.setToolTip("Drag on the chart to mark a time range")
        self._ann_btn.toggled.connect(self._toggle_annotate_mode)

        download = QPushButton("Export")
        download.setIcon(_svg_icon("download", "#ffffff", 14))
        download.setIconSize(QSize(14, 14))
        download.setObjectName("primaryButton")
        dl_menu = QMenu(download)
        for label, slot in [
            ("Chart PNG",       self.export_chart_png),
            ("Run CSV",         self.export_run_csv),
            ("Comparison CSV",  self.export_comparison_csv),
        ]:
            act = QAction(label, dl_menu)
            act.triggered.connect(slot)
            dl_menu.addAction(act)
        download.setMenu(dl_menu)

        for w in [self._ch_btn, self.show_setpoint, self.setpoint_value, reset_btn,
                  self._ann_btn, self.chart_mode, download]:
            toolbar.addWidget(w)

        chart_card_lay.addLayout(toolbar)
        self.chart = ChartWidget()
        self.chart.annotation_committed.connect(self._on_annotation_committed)
        chart_card_lay.addWidget(self.chart)
        self._body_layout.addWidget(chart_card)

        # Controls card
        ctrl_card = QFrame()
        ctrl_card.setObjectName("card")
        ctrl_lay = QVBoxLayout(ctrl_card)
        ctrl_lay.setContentsMargins(10, 10, 10, 10)
        ctrl_lay.setSpacing(8)
        ctrl_lay.addWidget(self._sec_lbl("PLOT CONTROLS"))

        time_row = QHBoxLayout()
        time_row.setSpacing(6)
        self.time_start = QDoubleSpinBox()
        self.time_start.setRange(0, 1_000_000)
        self.time_start.setDecimals(1)
        self.time_start.setSuffix(" s")
        self.time_end = QDoubleSpinBox()
        self.time_end.setRange(0, 1_000_000)
        self.time_end.setDecimals(1)
        self.time_end.setSuffix(" s")
        apply_time = QPushButton("Apply Range")
        apply_time.clicked.connect(self._apply_time_range)
        reset_time = QPushButton("Full Range")
        reset_time.clicked.connect(self._reset_time_range)
        self.smoothing = QSpinBox()
        self.smoothing.setRange(1, 501)
        self.smoothing.setSingleStep(2)
        self.smoothing.setValue(1)
        self.smoothing.setSuffix(" pt")
        self.smoothing.valueChanged.connect(self._set_smoothing)
        for w in [QLabel("Start"), self.time_start, QLabel("End"), self.time_end,
                  apply_time, reset_time, QLabel("Smooth"), self.smoothing]:
            time_row.addWidget(w)
        time_row.addStretch(1)
        ctrl_lay.addLayout(time_row)

        ov_row = QHBoxLayout()
        ov_row.setSpacing(12)
        ov_row.addWidget(QLabel("Overlays"))
        self.overlay_min = QCheckBox("Min")
        self.overlay_max = QCheckBox("Max")
        self.overlay_avg = QCheckBox("Average")
        for cb in [self.overlay_min, self.overlay_max, self.overlay_avg]:
            cb.stateChanged.connect(self._update_overlays)
            ov_row.addWidget(cb)
        ov_row.addSpacing(20)
        ov_row.addWidget(QLabel("Markers"))
        self.mk_events = QCheckBox("Events")
        self.mk_alarms = QCheckBox("Alarms")
        self.mk_ctrl   = QCheckBox("Controller")
        self.mk_state  = QCheckBox("State")
        for cb in [self.mk_events, self.mk_alarms, self.mk_ctrl, self.mk_state]:
            cb.setChecked(True)
            cb.stateChanged.connect(self._update_markers)
            ov_row.addWidget(cb)
        ov_row.addStretch(1)
        ctrl_lay.addLayout(ov_row)
        self._body_layout.addWidget(ctrl_card)

        self._rules_card_widget = self._build_rules_card()
        self._body_layout.addWidget(self._rules_card_widget)

        self._ann_card_widget = self._build_annotations_card()
        self._body_layout.addWidget(self._ann_card_widget)

        self.chart.set_dark(self.dark)

    def _inline_stat(self, label, key):
        box = QFrame()
        box.setObjectName("inlineStat")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(0)
        cap = QLabel(label)
        cap.setObjectName("inlineStatLabel")
        val = QLabel("-")
        val.setObjectName("inlineStatValue")
        lay.addWidget(cap)
        lay.addWidget(val)
        self.run_metric_labels[key] = val
        return box

    def _sec_lbl(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("sectionLabel")
        return lbl

    # ── Data loading ─────────────────────────────────────────────────────────

    def load(self):
        try:
            self.detail = data.run_detail(self.run_key)
        except Exception as exc:
            QMessageBox.critical(self, "Load error", str(exc))
            return
        if not any(c in self.detail["numeric_columns"] for c in self.selected_columns):
            numeric_cols = self.detail["numeric_columns"]
            saved = [c for c in settings_service.load_channels(self.run_key) if c in numeric_cols]
            if saved:
                self.selected_columns = set(saved)
            else:
                preferred = [c for c in ["temp", "temp_ref"] if c in numeric_cols]
                self.selected_columns = set(preferred or numeric_cols[:3])
        run = self.detail.get("run", {})
        self.title_label.setText(run.get("id", self.run_key))
        self._user_annotations = annotations_service.list_annotations(self.run_key)
        self._var_rules        = annotations_service.list_rules(self.run_key)
        self._render_summary()
        self._render_channels()
        self._refresh_annotations_list()
        self._refresh_rules_list()
        self._load_series()

    def set_compare_run(self, key, checked):
        if checked:
            self.compare_runs.add(key)
        else:
            self.compare_runs.discard(key)
        if not self.compare_runs:
            self.compare_runs.add(self.run_key)
        self._load_series()
        self.compare_changed.emit(self.compare_runs)

    def update_theme(self, dark):
        self.dark = dark
        self.chart.set_dark(dark)

    def primary_chart(self):  return self.chart
    def _compare_mode(self):  return len(self.compare_runs) > 1
    def _first_col(self):     return next(iter(self.selected_columns), None)
    def _active_charts(self): return [self.chart]

    def _render_summary(self):
        run     = (self.detail or {}).get("run", {})
        summary = (self.detail or {}).get("summary", {})
        values  = {
            "samples":  run.get("samples"),
            "duration": f'{fmt(run.get("duration_s"), 1)} s' if run.get("duration_s") is not None else None,
            "tail_mae": summary.get("tail_mae"),
        }
        for key, lbl in self.run_metric_labels.items():
            lbl.setText(fmt(values.get(key)))

    def _render_channels(self):
        if not self.detail:
            return
        cols = self.detail.get("numeric_columns", [])
        for i, col in enumerate(cols):
            if col not in self._channel_colors:
                self._channel_colors[col] = COLORS[i % len(COLORS)]
        self.selected_columns = {c for c in self.selected_columns if c in cols}
        if not self.selected_columns:
            preferred = [c for c in ["temp", "temp_ref"] if c in cols]
            self.selected_columns = set(preferred or cols[:2])
        self._update_ch_btn_label()
        self._update_rule_channel_combo()

    def _update_ch_btn_label(self):
        cols = (self.detail or {}).get("numeric_columns", [])
        n = len(self.selected_columns)
        self._ch_btn.setText(f"Channels ({n}/{len(cols)}) ▾" if cols else "Channels ▾")

    def _open_channels_menu(self):
        if not self.detail:
            return
        menu = QMenu(self)
        for col in self.detail.get("numeric_columns", []):
            wa  = QWidgetAction(menu)
            row = QWidget()
            rl  = QHBoxLayout(row)
            rl.setContentsMargins(10, 4, 10, 4)
            rl.setSpacing(10)

            cb = QCheckBox(col)
            cb.setChecked(col in self.selected_columns)
            cb.stateChanged.connect(lambda state, c=col: self._set_channel_active(c, bool(state)))

            swatch = QPushButton()
            swatch.setFixedSize(16, 16)
            color  = self._channel_colors.get(col, COLORS[0])
            swatch.setStyleSheet(
                f"background:{color};border:1px solid rgba(255,255,255,0.25);border-radius:3px;")
            swatch.clicked.connect(lambda _, c=col, m=menu: self._pick_channel_color(c, m))

            rl.addWidget(cb, 1)
            rl.addWidget(swatch)
            wa.setDefaultWidget(row)
            menu.addAction(wa)

        menu.exec(self._ch_btn.mapToGlobal(
            self._ch_btn.rect().bottomLeft()))

    def _set_channel_active(self, col, active):
        if active:
            self.selected_columns.add(col)
        else:
            self.selected_columns.discard(col)
        self._update_ch_btn_label()
        self._load_series()
        settings_service.save_channels(self.run_key, sorted(self.selected_columns))

    def _pick_channel_color(self, col, menu):
        menu.close()
        current = QColor(self._channel_colors.get(col, COLORS[0]))
        picked  = QColorDialog.getColor(current, self, f"Color — {col}")
        if picked.isValid():
            self._channel_colors[col] = picked.name()
            self.refresh_chart()

    def _load_series(self):
        cols = list(self.selected_columns)
        if not cols:
            self.series = {"columns": [], "points": []}
            self.refresh_chart()
            return
        try:
            if self._compare_mode():
                ch     = self._first_col()
                series = []
                for key in self.compare_runs:
                    payload = data.run_series(key, [ch])
                    run = next((r for r in self.all_runs if r["key"] == key), None)
                    series.append({"label": run["id"] if run else key, "points": payload["points"]})
                self.series = {"series": series, "channel": ch}
            else:
                self.series = data.run_series(self.run_key, cols)
        except Exception as exc:
            QMessageBox.critical(self, "Series error", str(exc))
            return
        self.refresh_chart()

    def refresh_chart(self):
        setpoint = None
        if self._compare_mode() and self.show_setpoint.isChecked():
            try:
                setpoint = float(self.setpoint_value.text())
            except ValueError:
                pass
        annotations = [] if self._compare_mode() else (self.detail or {}).get("annotations", [])
        for ch in self._active_charts():
            ch.draw(self.series, self.chart_mode.currentText(), annotations, setpoint,
                    colors=self._channel_colors)
        self._draw_rules_on_chart()
        self._draw_user_annotations()
        self._update_time_controls()

    def _update_time_controls(self):
        start, end = self.chart.data_x_range()
        if end <= start:
            return
        for sb in [self.time_start, self.time_end]:
            sb.blockSignals(True)
            sb.setRange(start, end)
        self.time_start.setValue(start)
        self.time_end.setValue(end)
        for sb in [self.time_start, self.time_end]:
            sb.blockSignals(False)

    def _apply_time_range(self):
        for ch in self._active_charts():
            ch.set_time_range(self.time_start.value(), self.time_end.value())

    def _reset_time_range(self):
        for ch in self._active_charts():
            ch.set_time_range(None, None)
        self._update_time_controls()

    def _set_smoothing(self, value):
        if value > 1 and value % 2 == 0:
            value += 1
            self.smoothing.blockSignals(True)
            self.smoothing.setValue(value)
            self.smoothing.blockSignals(False)
        for ch in self._active_charts():
            ch.set_smoothing_window(value)

    def _update_overlays(self):
        for ch in self._active_charts():
            ch.set_overlay_flags(min=self.overlay_min.isChecked(),
                                 max=self.overlay_max.isChecked(),
                                 avg=self.overlay_avg.isChecked())

    def _update_markers(self):
        for ch in self._active_charts():
            ch.set_marker_flags(events=self.mk_events.isChecked(),
                                alarms=self.mk_alarms.isChecked(),
                                controller=self.mk_ctrl.isChecked(),
                                state=self.mk_state.isChecked())

    def _reset_views(self):
        for ch in self._active_charts():
            ch.reset_view()

    # ── Annotations ───────────────────────────────────────────────────────────

    def _toggle_annotate_mode(self, checked: bool):
        self.chart.set_annotate_mode(checked)
        self._ann_btn.setText("Done" if checked else "Annotate")

    def _on_annotation_committed(self, ann: dict):
        saved = annotations_service.add_annotation(
            run_key=self.run_key,
            user_id=self.current_user.get("id"),
            user_name=self.current_user.get("name", "Unknown"),
            x0=ann["x0"], x1=ann["x1"], label=ann["label"], color=ann["color"],
        )
        self._user_annotations.append(saved)
        self._ann_btn.setChecked(False)
        self._refresh_annotations_list()
        self.refresh_chart()

    def _delete_user_annotation(self, idx: int):
        if 0 <= idx < len(self._user_annotations):
            ann = self._user_annotations.pop(idx)
            annotations_service.delete_annotation(ann["id"])
        self._refresh_annotations_list()
        self.refresh_chart()

    def _refresh_annotations_list(self):
        if self._ann_list_layout is None:
            return
        while self._ann_list_layout.count():
            item = self._ann_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for idx, ann in enumerate(self._user_annotations):
            row = QFrame()
            row.setObjectName("ruleRow")
            rlay = QHBoxLayout(row)
            rlay.setContentsMargins(6, 3, 6, 3)
            rlay.setSpacing(10)
            swatch = QLabel("■")
            swatch.setStyleSheet(f"color: {ann['color']}; background: transparent; font-size: 14px;")
            desc = QLabel(
                f"<b>{ann['label']}</b>  ·  {ann['x0']:.1f} – {ann['x1']:.1f} s"
                f"  ·  {ann.get('user_name', 'Unknown')}"
            )
            desc.setStyleSheet("background: transparent;")
            del_btn = QPushButton("✕")
            del_btn.setObjectName("tabClose")
            del_btn.setFixedSize(22, 22)
            del_btn.clicked.connect(lambda _=False, i=idx: self._delete_user_annotation(i))
            rlay.addWidget(swatch)
            rlay.addWidget(desc, 1)
            rlay.addWidget(del_btn)
            self._ann_list_layout.addWidget(row)

    def _draw_user_annotations(self):
        for ann in self._user_annotations:
            self.chart.add_x_annotation(ann["x0"], ann["x1"], ann["label"], ann["color"])

    def _build_annotations_card(self):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        hdr = QHBoxLayout()
        hdr.addWidget(self._sec_lbl("ANNOTATIONS"))
        info = QLabel("Click 'Annotate', then drag on the chart to mark a time range and label it.")
        info.setObjectName("sectionLabel")
        info.setWordWrap(True)
        hdr.addWidget(info, 1)
        lay.addLayout(hdr)
        self._ann_list_widget = QWidget()
        self._ann_list_layout = QVBoxLayout(self._ann_list_widget)
        self._ann_list_layout.setContentsMargins(0, 2, 0, 0)
        self._ann_list_layout.setSpacing(3)
        lay.addWidget(self._ann_list_widget)
        return card

    # ── Variable rules ────────────────────────────────────────────────────────

    def _build_rules_card(self):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.addWidget(self._sec_lbl("VARIABLE RULES"))
        info = QLabel("Highlight acceptable ranges on the Y-axis when the channel is plotted.")
        info.setObjectName("sectionLabel")
        info.setWordWrap(True)
        hdr.addWidget(info, 1)
        lay.addLayout(hdr)

        form = QHBoxLayout()
        form.setSpacing(6)
        self._rule_ch_combo = QComboBox()
        self._rule_ch_combo.setFixedWidth(110)
        self._rule_lo_ed = QLineEdit()
        self._rule_lo_ed.setPlaceholderText("min")
        self._rule_lo_ed.setFixedWidth(72)
        self._rule_hi_ed = QLineEdit()
        self._rule_hi_ed.setPlaceholderText("max")
        self._rule_hi_ed.setFixedWidth(72)
        self._rule_name_ed = QLineEdit()
        self._rule_name_ed.setPlaceholderText("label")
        self._rule_name_ed.setFixedWidth(100)
        self._rule_color_combo = QComboBox()
        for name, _ in RULE_COLOR_OPTIONS:
            self._rule_color_combo.addItem(name)
        self._rule_color_combo.setFixedWidth(90)
        add_btn = QPushButton("Add Rule")
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(self._add_var_rule)

        for cap, w in [("Channel", self._rule_ch_combo), ("Min", self._rule_lo_ed),
                       ("Max", self._rule_hi_ed),         ("Label", self._rule_name_ed),
                       ("Color", self._rule_color_combo), ("", add_btn)]:
            if cap:
                lbl = QLabel(cap)
                lbl.setObjectName("sectionLabel")
                form.addWidget(lbl)
            form.addWidget(w)
        form.addStretch(1)
        lay.addLayout(form)

        self._rules_list_widget = QWidget()
        self._rules_list_layout = QVBoxLayout(self._rules_list_widget)
        self._rules_list_layout.setContentsMargins(0, 2, 0, 0)
        self._rules_list_layout.setSpacing(3)
        lay.addWidget(self._rules_list_widget)
        return card

    def _update_rule_channel_combo(self):
        if not self._rule_ch_combo:
            return
        current = self._rule_ch_combo.currentText()
        self._rule_ch_combo.blockSignals(True)
        self._rule_ch_combo.clear()
        for col in (self.detail or {}).get("numeric_columns", []):
            self._rule_ch_combo.addItem(col)
        idx = self._rule_ch_combo.findText(current)
        if idx >= 0:
            self._rule_ch_combo.setCurrentIndex(idx)
        self._rule_ch_combo.blockSignals(False)

    def _add_var_rule(self):
        ch = self._rule_ch_combo.currentText() if self._rule_ch_combo else ""
        if not ch:
            return
        lo_text = self._rule_lo_ed.text().strip()
        hi_text = self._rule_hi_ed.text().strip()
        try:
            lo = float(lo_text) if lo_text else None
            hi = float(hi_text) if hi_text else None
        except ValueError:
            return
        if lo is None and hi is None:
            return
        _, color = RULE_COLOR_OPTIONS[self._rule_color_combo.currentIndex()]
        saved = annotations_service.add_rule(
            run_key=self.run_key,
            user_id=self.current_user.get("id"),
            user_name=self.current_user.get("name", "Unknown"),
            name=self._rule_name_ed.text().strip() or ch,
            channel=ch, lo=lo, hi=hi, color=color,
        )
        self._var_rules.append(saved)
        self._rule_lo_ed.clear()
        self._rule_hi_ed.clear()
        self._rule_name_ed.clear()
        self._refresh_rules_list()
        self.refresh_chart()

    def _remove_var_rule(self, idx):
        if 0 <= idx < len(self._var_rules):
            rule = self._var_rules.pop(idx)
            annotations_service.delete_rule(rule["id"])
        self._refresh_rules_list()
        self.refresh_chart()

    def _refresh_rules_list(self):
        while self._rules_list_layout.count():
            item = self._rules_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for idx, rule in enumerate(self._var_rules):
            row = QFrame()
            row.setObjectName("ruleRow")
            rlay = QHBoxLayout(row)
            rlay.setContentsMargins(6, 3, 6, 3)
            rlay.setSpacing(10)
            swatch = QLabel("■")
            swatch.setStyleSheet(f"color: {rule['color']}; background: transparent; font-size: 14px;")
            lo_str = f"{rule['lo']:g}" if rule["lo"] is not None else "−∞"
            hi_str = f"{rule['hi']:g}" if rule["hi"] is not None else "+∞"
            desc = QLabel(
                f"<b>{rule['name']}</b>  ·  {rule['channel']}  [{lo_str} , {hi_str}]"
                f"  ·  {rule.get('user_name', 'Unknown')}"
            )
            desc.setStyleSheet("background: transparent;")
            del_btn = QPushButton("✕")
            del_btn.setObjectName("tabClose")
            del_btn.setFixedSize(22, 22)
            del_btn.clicked.connect(lambda _=False, i=idx: self._remove_var_rule(i))
            rlay.addWidget(swatch)
            rlay.addWidget(desc, 1)
            rlay.addWidget(del_btn)
            self._rules_list_layout.addWidget(row)

    def _draw_rules_on_chart(self):
        for rule in self._var_rules:
            if rule["channel"] not in self.selected_columns:
                continue
            lo    = rule.get("lo")
            hi    = rule.get("hi")
            color = rule.get("color", "#60a5fa")
            name  = rule.get("name", "")
            if lo is not None and hi is not None:
                self.chart.add_range_band(lo, hi, color, name)
            elif lo is not None:
                self.chart.add_horizontal_marker(lo, f"{name} min", color, overlay=True)
            elif hi is not None:
                self.chart.add_horizontal_marker(hi, f"{name} max", color, overlay=True)

    # ── Exports ──────────────────────────────────────────────────────────────

    def export_chart_png(self):
        if not self.detail:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save chart", f"{self.detail['run']['id']}.png", "PNG (*.png)")
        if path:
            self.chart.export_view(path)

    def export_run_csv(self):
        if not self.detail:
            return
        table = data.run_table(self.run_key)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save run CSV",
            f"{self.detail['run']['id']}-samples.csv", "CSV (*.csv)")
        if path:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=table["columns"])
                writer.writeheader()
                writer.writerows(table["rows"])

    def export_comparison_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save comparison CSV", "deepvac-comparison.csv", "CSV (*.csv)")
        if not path:
            return
        rows  = [r for r in self.all_runs if r["key"] in (self.compare_runs or {self.run_key})]
        lines = ["Run,Cost,MAE,Tail MAE,Overshoot"]
        for r in rows:
            lines.append(",".join(csv_escape(r[k]) for k in ["id", "cost", "mae", "tail_mae", "overshoot"]))
        from pathlib import Path as _Path
        _Path(path).write_text("\n".join(lines), encoding="utf-8")
