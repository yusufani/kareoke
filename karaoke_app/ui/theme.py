"""
Design tokens and the global stylesheet.

Values come straight from the Encore design file, kept in one place so a colour
is never typed twice. The two typefaces the design calls for ship with the app
(both SIL Open Font Licence) so it looks the same on a machine that has neither
installed.
"""
import logging
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).resolve().parent / "fonts"

# -- palette ---------------------------------------------------------------
BG = "#08090D"
BG_BAR = "#0B0D14"
BG_PANEL = "#0C0E15"
BG_RAISED = "#12141E"

TEXT = "#EEF0F8"
TEXT_DIM = "rgba(238,240,248,0.55)"
TEXT_FAINT = "rgba(238,240,248,0.35)"
TEXT_GHOST = "rgba(238,240,248,0.28)"

PINK = "#FF3D7F"
PINK_HOVER = "#FF6B9E"
PINK_LIGHT = "#FF9EC2"
PURPLE = "#B93DFF"
INDIGO = "#6E5BFF"
LILAC = "#B7A8FF"
BLUE = "#6EC6FF"
GREEN = "#3DDC97"
RED = "#FF4545"
RED_LIGHT = "#FF8A8A"

BORDER = "rgba(255,255,255,0.07)"
BORDER_STRONG = "rgba(255,255,255,0.12)"
SURFACE = "rgba(255,255,255,0.03)"
SURFACE_HOVER = "rgba(255,255,255,0.07)"

# Channel accent colours, in strip order.
COLOR_VOCALS = LILAC
COLOR_MUSIC = BLUE
COLOR_MIC = PINK_HOVER
COLOR_MASTER = TEXT


def qc(value: str, alpha: float = 1.0) -> QColor:
    """Hex or rgba() string to QColor, with an optional extra alpha multiplier."""
    if value.startswith("rgba"):
        parts = value[value.index("(") + 1:value.rindex(")")].split(",")
        r, g, b = (int(float(p)) for p in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return QColor(r, g, b, int(255 * a * alpha))
    color = QColor(value)
    if alpha < 1.0:
        color.setAlpha(int(255 * alpha))
    return color


# -- fonts -----------------------------------------------------------------
_UI_STACK = ["Space Grotesk", "Inter", "SF Pro Display", "Segoe UI Variable",
             "Segoe UI", "Helvetica Neue", "Noto Sans", "sans-serif"]
_MONO_STACK = ["JetBrains Mono", "SF Mono", "Menlo", "Cascadia Mono",
               "Consolas", "DejaVu Sans Mono", "monospace"]


def _first_available(candidates):
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return candidates[-1]


UI_FAMILY = ""
MONO_FAMILY = ""


def load_bundled_fonts() -> None:
    """Register the shipped typefaces with Qt. Safe to call more than once."""
    if not FONT_DIR.is_dir():
        return
    for path in sorted(FONT_DIR.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            logger.warning("Could not load bundled font %s", path.name)


def resolve_fonts() -> None:
    """Pick the best available family. Call once, after QApplication exists."""
    global UI_FAMILY, MONO_FAMILY
    load_bundled_fonts()
    UI_FAMILY = _first_available(_UI_STACK)
    MONO_FAMILY = _first_available(_MONO_STACK)
    logger.info("UI font: %s · mono font: %s", UI_FAMILY, MONO_FAMILY)


def ui_font(size: float = 13, weight: int = QFont.Weight.Normal,
            spacing: float = 0.0) -> QFont:
    font = QFont(UI_FAMILY or _UI_STACK[-1])
    font.setPointSizeF(size)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + spacing)
    return font


def mono_font(size: float = 11) -> QFont:
    font = QFont(MONO_FAMILY or _MONO_STACK[-1])
    font.setPointSizeF(size)
    return font


# -- global stylesheet -----------------------------------------------------
def stylesheet() -> str:
    return f"""
    QWidget {{
        color: {TEXT};
        background: transparent;
        font-family: "{UI_FAMILY}";
        font-size: 13px;
    }}
    QMainWindow, QDialog {{ background: {BG}; }}

    QToolTip {{
        background: {BG_RAISED};
        color: {TEXT};
        border: 1px solid {BORDER_STRONG};
        border-radius: 6px;
        padding: 5px 8px;
    }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{
        background: transparent; width: 8px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255,255,255,0.12); border-radius: 4px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.22); }}
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; }}
    QScrollBar::handle:horizontal {{
        background: rgba(255,255,255,0.12); border-radius: 4px; min-width: 28px;
    }}

    QLineEdit {{
        background: transparent;
        border: none;
        color: {TEXT};
        selection-background-color: {PINK};
        selection-color: #ffffff;
    }}

    QComboBox {{
        background: rgba(255,255,255,0.05);
        border: 1px solid {BORDER_STRONG};
        border-radius: 8px;
        padding: 4px 10px;
        min-height: 24px;
    }}
    QComboBox:hover {{ border-color: rgba(255,61,127,0.5); }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {BG_RAISED};
        border: 1px solid {BORDER_STRONG};
        selection-background-color: rgba(255,61,127,0.25);
        outline: none;
        padding: 4px;
    }}

    #Card {{
        background: {SURFACE};
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 11px;
    }}
    #Card:hover {{ background: {SURFACE_HOVER}; }}

    #SectionLabel {{
        color: {TEXT_DIM};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 2px;
    }}
    #Mono {{ font-family: "{MONO_FAMILY}"; color: {TEXT_DIM}; font-size: 11px; }}
    """
