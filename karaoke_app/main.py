"""
Karaoke Separation App - Main Entry Point
A professional karaoke application with AI-powered vocal separation.
"""
import sys
import os
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

# Add the app directory to the path for imports
APP_DIR = Path(__file__).parent
sys.path.insert(0, str(APP_DIR))

from ui.main_window import MainWindow
from utils import setup_logging


def setup_app_directories():
    """Ensure required application directories exist."""
    dirs = [
        APP_DIR / "stems_cache",
        APP_DIR / "logs",
        APP_DIR / "settings"
    ]
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)


def main():
    """Application entry point."""
    # Enable high DPI scaling (Qt 6 does this automatically, but set policy for consistency)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    # Note: AA_EnableHighDpiScaling and AA_UseHighDpiPixmaps are deprecated in Qt 6
    # High DPI is enabled by default in Qt 6

    # Create application
    app = QApplication(sys.argv)
    app.setApplicationName("Karaoke Separation Studio")
    app.setOrganizationName("KaraokePro")
    app.setApplicationVersion("1.0.0")

    # Setup directories
    setup_app_directories()

    # Setup logging
    setup_logging(APP_DIR)

    # Create and show main window
    window = MainWindow()
    window.show()

    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
