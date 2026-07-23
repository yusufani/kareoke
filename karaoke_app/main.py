"""
Encore — Karaoke Studio. Entry point.
"""
import os
import sys

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .core.paths import DATA_ROOT, ensure_dirs
from .ui import theme
from .utils import setup_logging


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("Encore Karaoke Studio")
    app.setOrganizationName("Encore")
    app.setApplicationVersion("2.0.0")

    ensure_dirs()
    logger = setup_logging(DATA_ROOT)
    logger.info("Encore starting from %s", DATA_ROOT)

    theme.resolve_fonts()
    app.setFont(theme.ui_font(13))

    # Imported after the QApplication exists so font resolution has settled.
    from .ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
