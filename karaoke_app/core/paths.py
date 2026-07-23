"""
Application directory layout.

Everything the app writes lives under a single root so a user can wipe the
cache by deleting one folder. The root defaults to the package directory but
can be moved with ENCORE_HOME, which is what the packaged builds do.
"""
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent

_home = os.environ.get("ENCORE_HOME", "").strip()
DATA_ROOT = Path(_home).expanduser() if _home else APP_ROOT

DOWNLOADS_DIR = DATA_ROOT / "downloads"
STEMS_DIR = DATA_ROOT / "stems_cache"
LYRICS_DIR = DATA_ROOT / "lyrics_cache"
RECORDINGS_DIR = DATA_ROOT / "recordings"
DATA_DIR = DATA_ROOT / "data"
LOGS_DIR = DATA_ROOT / "logs"

LIBRARY_FILE = DATA_DIR / "library.json"
CONFIG_FILE = DATA_DIR / "config.json"

ALL_DIRS = (
    DOWNLOADS_DIR,
    STEMS_DIR,
    LYRICS_DIR,
    RECORDINGS_DIR,
    DATA_DIR,
    LOGS_DIR,
)


def ensure_dirs() -> None:
    """Create every directory the app writes to."""
    for directory in ALL_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
