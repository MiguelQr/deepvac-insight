"""Entry point — login flow, splash screen, and main() only."""
import sys

from PySide6.QtCore import Qt, QRectF, QSettings
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from app.common import LOGO_PATH, ICON_PATH
from app.main_window import DeepVacDesktop
from app.login_window import LoginWindow
from app.services import auth_service, backup_service, log_service


class LoadingSplash(QSplashScreen):
    def drawContents(self, painter):
        painter.setPen(QColor("#f8fafc"))
        painter.setFont(QFont("Segoe UI", 11, 600))
        painter.drawText(QRectF(0, 224, 520, 54),
                         Qt.AlignCenter | Qt.TextWordWrap, self.message())


def make_splash():
    pixmap = QPixmap(520, 300)
    pixmap.fill(QColor("#0b1020"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setPen(QColor("#60a5fa"))
    painter.setBrush(QColor("#111827"))
    painter.drawRoundedRect(18, 18, 484, 264, 14, 14)

    logo = QPixmap(LOGO_PATH)
    if not logo.isNull():
        scaled = logo.scaledToHeight(90, Qt.SmoothTransformation)
        x = (520 - scaled.width()) // 2
        painter.drawPixmap(x, 62, scaled)
    else:
        painter.setPen(QColor("#f8fafc"))
        painter.setFont(QFont("Segoe UI", 26, QFont.Black))
        painter.drawText(QRectF(0, 60, 520, 80), Qt.AlignCenter, "DeepVac")

    painter.setPen(QColor("#60a5fa"))
    painter.drawLine(60, 192, 460, 192)

    painter.end()
    return LoadingSplash(pixmap)


def _remembered_user():
    token = QSettings("DeepVac", "Insight").value("auth/remember_token", "")
    return auth_service.get_user_by_token(token) if token else None


def main():
    log_service.install_excepthook()

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(ICON_PATH))

    try:
        backup_service.backup_all()
    except Exception as exc:
        print(f"[backup] startup backup skipped: {exc}")

    user = _remembered_user()

    while True:
        if user is None:
            login = LoginWindow()
            login.show()
            app.exec()
            user = login.authenticated_user
            if user is None:
                sys.exit(0)

        splash = make_splash()
        splash.show()
        splash.showMessage("Starting DeepVac…", Qt.AlignCenter | Qt.AlignBottom, Qt.white)
        app.processEvents()

        window = DeepVacDesktop(splash=splash, current_user=user)
        window.restore_window_state()
        splash.finish(window)
        app.exec()

        if not window.logout_requested:
            break
        user = None

    sys.exit(0)


if __name__ == "__main__":
    main()
