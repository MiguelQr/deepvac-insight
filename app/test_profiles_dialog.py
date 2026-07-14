"""TestProfilesDialog — create/edit/delete multi-step test profiles
(app/services/test_profiles_service.py) from Live Monitoring's Test
Profiles picker."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.services import test_profiles_service as profiles

_STEP_COLUMNS = ["Temp (°C)", "Pressure", "Duration (s)", "Label"]


class TestProfilesDialog(QDialog):
    def __init__(self, current_user=None, parent=None):
        super().__init__(parent)
        self.current_user = current_user or {"name": "Unknown"}
        self.changed = False  # caller checks this to know whether to reload
        self._editing_id = None

        self.setWindowTitle(self.tr("Manage Test Profiles"))
        self.setMinimumSize(680, 480)
        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        root = QVBoxLayout(self)
        body = QHBoxLayout()

        left = QVBoxLayout()
        left_lbl = QLabel(self.tr("SAVED PROFILES"))
        left_lbl.setObjectName("sectionLabel")
        left.addWidget(left_lbl)
        self._list = QListWidget()
        self._list.setMinimumWidth(200)
        self._list.itemClicked.connect(self._load_selected)
        left.addWidget(self._list, 1)
        delete_btn = QPushButton(self.tr("Delete Selected"))
        delete_btn.clicked.connect(self._delete_selected)
        left.addWidget(delete_btn)
        body.addLayout(left)

        right = QVBoxLayout()
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(self.tr("Name")))
        self._name_ed = QLineEdit()
        self._name_ed.setPlaceholderText(self.tr("e.g. Thermal Soak Test A"))
        name_row.addWidget(self._name_ed, 1)
        right.addLayout(name_row)

        desc_row = QHBoxLayout()
        desc_row.addWidget(QLabel(self.tr("Description")))
        self._desc_ed = QLineEdit()
        self._desc_ed.setPlaceholderText(self.tr("Optional"))
        desc_row.addWidget(self._desc_ed, 1)
        right.addLayout(desc_row)

        steps_lbl = QLabel(self.tr("STEPS (in order)"))
        steps_lbl.setObjectName("sectionLabel")
        right.addWidget(steps_lbl)

        self._steps_table = QTableWidget()
        self._steps_table.setColumnCount(len(_STEP_COLUMNS))
        self._steps_table.setHorizontalHeaderLabels([self.tr(c) for c in _STEP_COLUMNS])
        self._steps_table.horizontalHeader().setStretchLastSection(True)
        self._steps_table.verticalHeader().setVisible(False)
        right.addWidget(self._steps_table, 1)

        step_btn_row = QHBoxLayout()
        add_step_btn = QPushButton(self.tr("+ Add Step"))
        add_step_btn.clicked.connect(self._add_step_row)
        remove_step_btn = QPushButton(self.tr("Remove Step"))
        remove_step_btn.clicked.connect(self._remove_selected_step)
        move_up_btn = QPushButton(self.tr("Move Up"))
        move_up_btn.clicked.connect(lambda: self._move_step(-1))
        move_down_btn = QPushButton(self.tr("Move Down"))
        move_down_btn.clicked.connect(lambda: self._move_step(1))
        for b in [add_step_btn, remove_step_btn, move_up_btn, move_down_btn]:
            step_btn_row.addWidget(b)
        step_btn_row.addStretch(1)
        right.addLayout(step_btn_row)

        body.addLayout(right, 1)
        root.addLayout(body, 1)

        button_row = QHBoxLayout()
        self._save_btn = QPushButton(self.tr("Save Profile"))
        self._save_btn.setObjectName("primaryButton")
        self._save_btn.clicked.connect(self._save)
        new_btn = QPushButton(self.tr("New Profile"))
        new_btn.clicked.connect(self._reset_form)
        close_btn = QPushButton(self.tr("Close"))
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(self._save_btn)
        button_row.addWidget(new_btn)
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        root.addLayout(button_row)

    # ── steps table helpers ─────────────────────────────────────────────────

    def _add_step_row(self, temp="", pressure="", duration="", label=""):
        row = self._steps_table.rowCount()
        self._steps_table.insertRow(row)
        for col, value in enumerate([temp, pressure, duration, label]):
            self._steps_table.setItem(row, col, QTableWidgetItem(str(value)))

    def _remove_selected_step(self):
        row = self._steps_table.currentRow()
        if row >= 0:
            self._steps_table.removeRow(row)

    def _move_step(self, delta):
        row = self._steps_table.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self._steps_table.rowCount():
            return
        for col in range(self._steps_table.columnCount()):
            a = self._steps_table.takeItem(row, col)
            b = self._steps_table.takeItem(target, col)
            self._steps_table.setItem(row, col, b)
            self._steps_table.setItem(target, col, a)
        self._steps_table.setCurrentCell(target, 0)

    def _read_steps(self):
        steps = []
        for row in range(self._steps_table.rowCount()):

            def cell(col, row=row):
                item = self._steps_table.item(row, col)
                return item.text().strip() if item else ""

            temp_text, pressure_text, duration_text, label = (
                cell(0),
                cell(1),
                cell(2),
                cell(3),
            )
            try:
                temp = float(temp_text) if temp_text else None
                pressure = float(pressure_text) if pressure_text else None
            except ValueError:
                raise profiles.TestProfileError(
                    f"Step {row + 1}: temperature/pressure must be numbers."
                ) from None
            try:
                duration = float(duration_text)
            except ValueError:
                raise profiles.TestProfileError(
                    f"Step {row + 1}: duration must be a number."
                ) from None
            steps.append(
                {
                    "setpoint_temp": temp,
                    "setpoint_pressure": pressure,
                    "duration_s": duration,
                    "label": label,
                }
            )
        return steps

    # ── profile list / form ──────────────────────────────────────────────────

    def _refresh_list(self):
        self._list.clear()
        for profile in profiles.list_profiles():
            n_steps = len(profile["steps"])
            item = QListWidgetItem(f"{profile['name']}  ({n_steps} step(s))")
            item.setData(Qt.UserRole, profile["id"])
            self._list.addItem(item)

    def _load_selected(self, item):
        profile_id = item.data(Qt.UserRole)
        profile = profiles.get_profile(profile_id)
        if not profile:
            return
        self._editing_id = profile["id"]
        self._name_ed.setText(profile["name"])
        self._desc_ed.setText(profile["description"])
        self._steps_table.setRowCount(0)
        for step in profile["steps"]:
            self._add_step_row(
                "" if step["setpoint_temp"] is None else step["setpoint_temp"],
                "" if step["setpoint_pressure"] is None else step["setpoint_pressure"],
                step["duration_s"],
                step["label"],
            )
        self._save_btn.setText(self.tr("Save Changes"))

    def _reset_form(self):
        self._editing_id = None
        self._name_ed.clear()
        self._desc_ed.clear()
        self._steps_table.setRowCount(0)
        self._save_btn.setText(self.tr("Save Profile"))

    def _save(self):
        name = self._name_ed.text().strip()
        description = self._desc_ed.text().strip()
        try:
            steps = self._read_steps()
            if self._editing_id is not None:
                profiles.update_profile(self._editing_id, name, description, steps)
            else:
                profiles.add_profile(
                    name, description, steps, created_by=self.current_user.get("name") or "Unknown"
                )
        except profiles.TestProfileError as exc:
            QMessageBox.critical(self, self.tr("Could not save test profile"), str(exc))
            return
        self.changed = True
        self._reset_form()
        self._refresh_list()

    def _delete_selected(self):
        item = self._list.currentItem()
        if not item:
            return
        profile_id = item.data(Qt.UserRole)
        profiles.delete_profile(profile_id)
        if self._editing_id == profile_id:
            self._reset_form()
        self.changed = True
        self._refresh_list()
