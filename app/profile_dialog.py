"""ProfileDialog — change display name, email, and password for the signed-in user."""
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from app.services import auth_service


class ProfileDialog(QDialog):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = dict(user)
        self.updated_user = dict(user)
        self.setWindowTitle("Profile")
        self.setMinimumWidth(360)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(14)

        info_lbl = QLabel("ACCOUNT DETAILS")
        info_lbl.setObjectName("sectionLabel")
        root.addWidget(info_lbl)

        form = QFormLayout()
        self.name_ed = QLineEdit(self.user["name"])
        self.email_ed = QLineEdit(self.user["email"])
        form.addRow("Name", self.name_ed)
        form.addRow("Email", self.email_ed)
        root.addLayout(form)

        save_info_btn = QPushButton("Save Changes")
        save_info_btn.setObjectName("primaryButton")
        save_info_btn.clicked.connect(self._save_profile)
        root.addWidget(save_info_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        pw_lbl = QLabel("CHANGE PASSWORD")
        pw_lbl.setObjectName("sectionLabel")
        root.addWidget(pw_lbl)

        pw_form = QFormLayout()
        self.current_pw_ed = QLineEdit()
        self.current_pw_ed.setEchoMode(QLineEdit.Password)
        self.new_pw_ed = QLineEdit()
        self.new_pw_ed.setEchoMode(QLineEdit.Password)
        self.confirm_pw_ed = QLineEdit()
        self.confirm_pw_ed.setEchoMode(QLineEdit.Password)
        pw_form.addRow("Current password", self.current_pw_ed)
        pw_form.addRow("New password", self.new_pw_ed)
        pw_form.addRow("Confirm new password", self.confirm_pw_ed)
        root.addLayout(pw_form)

        save_pw_btn = QPushButton("Update Password")
        save_pw_btn.clicked.connect(self._save_password)
        root.addWidget(save_pw_btn)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    def _save_profile(self):
        try:
            updated = auth_service.update_profile(
                self.user["id"],
                name=self.name_ed.text().strip(),
                email=self.email_ed.text().strip(),
            )
        except auth_service.AuthError as exc:
            QMessageBox.warning(self, "Profile", str(exc))
            return
        self.updated_user = updated
        self.user = updated
        QMessageBox.information(self, "Profile", "Profile updated.")

    def _save_password(self):
        new_pw = self.new_pw_ed.text()
        if new_pw != self.confirm_pw_ed.text():
            QMessageBox.warning(self, "Profile", "New passwords do not match.")
            return
        try:
            auth_service.change_password(
                self.user["id"], self.current_pw_ed.text(), new_pw)
        except auth_service.AuthError as exc:
            QMessageBox.warning(self, "Profile", str(exc))
            return
        self.current_pw_ed.clear()
        self.new_pw_ed.clear()
        self.confirm_pw_ed.clear()
        QMessageBox.information(self, "Profile", "Password updated.")
