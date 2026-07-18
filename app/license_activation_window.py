"""LicenseActivationWindow — browser-based device-code activation gate.

Shown once per installation (and again whenever the cached license stops
verifying, e.g. after it expires) before LoginWindow. Never asks for a
username or password itself: the user signs in through the hub's browser
portal instead (see ../../hub/docs/sequences.md in the sibling `hub` repo),
and this window only polls for approval and then submits the device's own
public key.
"""

import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.common import ICON_PATH, LOGO_PATH
from app.services import licensing_client


class LicenseActivationWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.activated_license = None
        self._activation = None
        self.setWindowTitle(self.tr("Activate — DeepVac Insight"))
        self.setWindowIcon(QIcon(ICON_PATH))
        self.setFixedSize(440, 440)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._build_ui()
        self._apply_style()
        self._center_on_screen()
        self._start()

    # ── UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 32, 36, 28)
        root.setSpacing(12)

        logo_lbl = QLabel()
        pix = QPixmap(LOGO_PATH)
        if not pix.isNull():
            logo_lbl.setPixmap(pix.scaledToHeight(48, Qt.SmoothTransformation))
        else:
            logo_lbl.setText(self.tr("DEEPVAC"))
            logo_lbl.setObjectName("brand")
        logo_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(logo_lbl)

        title = QLabel(self.tr("Activate this installation"))
        title.setObjectName("formTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        self.status_lbl = QLabel(self.tr("Starting activation…"))
        self.status_lbl.setObjectName("mutedLabel")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self.status_lbl)

        self.code_lbl = QLabel("")
        self.code_lbl.setObjectName("userCode")
        self.code_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self.code_lbl)

        self.error_lbl = QLabel("")
        self.error_lbl.setObjectName("errorLabel")
        self.error_lbl.setWordWrap(True)
        self.error_lbl.setVisible(False)
        root.addWidget(self.error_lbl)

        self.open_btn = QPushButton(self.tr("Open Activation Page in Browser"))
        self.open_btn.setObjectName("primaryButton")
        self.open_btn.setMinimumHeight(36)
        self.open_btn.clicked.connect(self._open_browser)
        self.open_btn.setEnabled(False)
        root.addWidget(self.open_btn)

        self.copy_btn = QPushButton(self.tr("Copy Code"))
        self.copy_btn.setMinimumHeight(32)
        self.copy_btn.clicked.connect(self._copy_code)
        self.copy_btn.setEnabled(False)
        root.addWidget(self.copy_btn)

        bottom_row = QHBoxLayout()
        self.retry_btn = QPushButton(self.tr("Retry"))
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(self._start)
        quit_btn = QPushButton(self.tr("Quit"))
        quit_btn.clicked.connect(self.close)
        bottom_row.addWidget(self.retry_btn)
        bottom_row.addStretch(1)
        bottom_row.addWidget(quit_btn)
        root.addLayout(bottom_row)
        root.addStretch(1)

    def _center_on_screen(self):
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.x() + (geo.width() - self.width()) // 2,
            geo.y() + (geo.height() - self.height()) // 2,
        )

    # ── Activation flow ──────────────────────────────────────────────────

    def _start(self):
        self._clear_error()
        self.retry_btn.setVisible(False)
        self.status_lbl.setText(self.tr("Starting activation…"))
        self.code_lbl.setText("")
        self.open_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)
        self._timer.stop()

        try:
            self._activation = licensing_client.start_activation()
        except licensing_client.LicensingError as exc:
            self._show_error(str(exc))
            return

        self.code_lbl.setText(self._activation.user_code)
        self.status_lbl.setText(
            self.tr("Open the activation page and sign in to approve this device.")
        )
        self.open_btn.setEnabled(True)
        self.copy_btn.setEnabled(True)
        self._open_browser()

        interval_ms = max(self._activation.polling_interval_seconds, 2) * 1000
        self._timer.start(interval_ms)

    def _open_browser(self):
        if self._activation:
            webbrowser.open(self._activation.verification_url)

    def _copy_code(self):
        if self._activation:
            QApplication.clipboard().setText(self._activation.user_code)

    def _poll(self):
        if not self._activation:
            return
        try:
            status = licensing_client.poll_activation_status(self._activation.activation_id)
        except licensing_client.LicensingError as exc:
            self._timer.stop()
            self._show_error(str(exc))
            return

        if status == "pending":
            return
        if status == "approved":
            self._timer.stop()
            self.status_lbl.setText(self.tr("Approved — finishing activation…"))
            self._complete()
            return

        self._timer.stop()
        messages = {
            "denied": self.tr("Activation was denied."),
            "expired": self.tr("Activation code expired. Click Retry to get a new one."),
            "consumed": self.tr("This activation code was already used."),
        }
        self._show_error(messages.get(status, self.tr("Activation failed ({0}).").format(status)))

    def _complete(self):
        try:
            license_payload = licensing_client.complete_activation(self._activation.activation_id)
        except licensing_client.LicensingError as exc:
            self._show_error(str(exc))
            return
        self.activated_license = license_payload
        self.close()

    def _show_error(self, msg):
        self.error_lbl.setText(msg)
        self.error_lbl.setVisible(True)
        self.retry_btn.setVisible(True)

    def _clear_error(self):
        self.error_lbl.setVisible(False)
        self.error_lbl.setText("")

    def closeEvent(self, event):
        self._timer.stop()
        QApplication.instance().quit()
        super().closeEvent(event)

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget { background: #0b1020; color: #f8fafc; font-family: "Segoe UI"; font-size: 10.5pt; }
            QLabel#brand { font-size: 20px; font-weight: 900; color: #60a5fa; }
            QLabel#formTitle { font-size: 16px; font-weight: 800; color: #f8fafc; margin-top: 4px; }
            QLabel#mutedLabel { color: #94a3b8; background: transparent; }
            QLabel#userCode {
                font-size: 22px; font-weight: 800; letter-spacing: 2px;
                background: #111827; border: 1px dashed #253247; border-radius: 8px;
                padding: 10px; min-height: 20px;
            }
            QLabel#errorLabel {
                color: #ff6f7d; background: rgba(255,111,125,0.08);
                border: 1px solid #ff6f7d; border-radius: 6px; padding: 6px 10px;
            }
            QPushButton {
                background: #1e293b; color: #f8fafc; border: 1px solid #253247;
                border-radius: 8px; padding: 6px 12px; font-weight: 650;
            }
            QPushButton:hover { background: #172033; border-color: #60a5fa; }
            QPushButton:disabled { color: #475569; border-color: #1e293b; }
            QPushButton#primaryButton { background: #2563eb; border-color: #2563eb; color: #ffffff; }
            QPushButton#primaryButton:hover { background: #60a5fa; border-color: #60a5fa; }
            QPushButton#primaryButton:disabled { background: #1e293b; border-color: #253247; color: #475569; }
        """)
