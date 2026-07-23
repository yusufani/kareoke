# PyInstaller build spec for Encore — Karaoke Studio.
#
#   .venv/bin/pyinstaller encore.spec        (macOS / Linux)
#   .venv\Scripts\pyinstaller encore.spec    (Windows)
#
# Two things this app needs that PyInstaller cannot work out on its own:
#
#   * the bundled typefaces, which are read from disk at start-up rather than
#     imported, so they have to be listed as data;
#   * demucs and torch, which reach for submodules dynamically.
#
# ffmpeg stays an external dependency: it is a large GPL binary with its own
# licensing considerations, so the app expects to find it on PATH. See
# PACKAGING.md.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "karaoke_app" / "ui" / "fonts"), "karaoke_app/ui/fonts"),
]
datas += collect_data_files("demucs")
datas += collect_data_files("soundfile")
datas += collect_data_files("sounddevice")

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "scipy.signal",
    "soundfile",
    "sounddevice",
]
hiddenimports += collect_submodules("demucs")
hiddenimports += collect_submodules("karaoke_app")

analysis = Analysis(
    ["encore.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "tkinter", "PyQt5", "PyQt6", "IPython", "notebook"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Encore",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="Encore",
)

app = BUNDLE(
    collection,
    name="Encore.app",
    bundle_identifier="dev.encore.karaoke",
    info_plist={
        # macOS refuses microphone access without a stated reason.
        "NSMicrophoneUsageDescription":
            "Encore mixes your microphone into the karaoke track you are singing.",
        "NSHighResolutionCapable": True,
    },
)
