"""
Custom-painted controls.

Qt's stock sliders cannot be made to look like the Encore faders, so the fader,
the horizontal parameter slider and the seek bar are drawn by hand. They share
one interaction model: press anywhere to jump, drag to adjust, and emit while
dragging so the audio engine follows the finger.
"""
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QWidget

from . import theme
from .theme import qc


# --------------------------------------------------------------------------
# Buttons
# --------------------------------------------------------------------------

BUTTON_QSS = f"""
QPushButton {{
    border-radius: 8px;
    padding: 0 14px;
}}
QPushButton:disabled {{ color: {theme.TEXT_GHOST}; }}

QPushButton#BtnGhost {{
    border: 1px solid {theme.BORDER_STRONG};
    background: transparent;
    color: {theme.TEXT_DIM};
    font-size: 12.5px;
}}
QPushButton#BtnGhost:hover {{ background: rgba(255,255,255,0.06); color: {theme.TEXT}; }}

QPushButton#BtnSoft {{
    border: 1px solid {theme.BORDER_STRONG};
    background: rgba(255,255,255,0.05);
    color: {theme.TEXT};
    font-size: 12.5px;
    font-weight: 600;
}}
QPushButton#BtnSoft:hover {{
    background: rgba(255,61,127,0.15);
    border-color: rgba(255,61,127,0.5);
}}

QPushButton#BtnAccent {{
    border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 {theme.PINK}, stop:1 {theme.PURPLE});
    color: #ffffff;
    font-weight: 700;
    font-size: 12.5px;
}}
QPushButton#BtnAccent:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #FF5B93, stop:1 #C75BFF);
}}

QPushButton#BtnPill {{
    border-radius: 12px;
    border: 1px solid rgba(255,61,127,0.5);
    background: rgba(255,61,127,0.12);
    color: {theme.PINK_HOVER};
    font-size: 11px;
    font-weight: 700;
    padding: 0 12px;
}}
QPushButton#BtnPill:hover {{ background: rgba(255,61,127,0.28); }}

QPushButton#BtnPillGhost {{
    border-radius: 12px;
    border: 1px solid {theme.BORDER_STRONG};
    background: transparent;
    color: {theme.TEXT_DIM};
    font-size: 11px;
    font-weight: 600;
    padding: 0 10px;
}}
QPushButton#BtnPillGhost:hover {{ background: rgba(255,255,255,0.07); color: {theme.TEXT}; }}

QPushButton#BtnTab {{
    border: none;
    background: rgba(255,255,255,0.05);
    color: {theme.TEXT_DIM};
    font-size: 12px;
    font-weight: 700;
}}
QPushButton#BtnTab:checked {{
    background: rgba(255,61,127,0.18);
    color: {theme.PINK_LIGHT};
}}

QPushButton#BtnChip {{
    border-radius: 12px;
    border: 1px solid {theme.BORDER_STRONG};
    background: rgba(255,255,255,0.05);
    color: {theme.TEXT_DIM};
    font-size: 10.5px;
    font-weight: 600;
    padding: 0 10px;
}}
QPushButton#BtnChip:hover {{ background: rgba(255,255,255,0.1); color: {theme.TEXT}; }}
QPushButton#BtnChip:checked {{
    border-color: rgba(255,61,127,0.55);
    background: rgba(255,61,127,0.22);
    color: {theme.PINK_LIGHT};
}}

QPushButton#BtnIcon {{
    border: 1px solid {theme.BORDER_STRONG};
    background: transparent;
    color: {theme.TEXT_DIM};
    padding: 0;
}}
QPushButton#BtnIcon:hover {{ background: rgba(255,255,255,0.07); color: {theme.TEXT}; }}

QPushButton#BtnFlat {{
    border: none;
    background: transparent;
    color: {theme.TEXT_DIM};
    padding: 0;
    font-size: 13px;
}}
QPushButton#BtnFlat:hover {{ color: {theme.TEXT}; }}

QPushButton#BtnStep {{
    border: none;
    background: transparent;
    color: {theme.TEXT_DIM};
    padding: 0;
    font-size: 15px;
    font-weight: 600;
}}
QPushButton#BtnStep:hover {{ color: #ffffff; }}
"""


def button(text: str = "", kind: str = "BtnGhost", height: int = 32,
           width: Optional[int] = None, checkable: bool = False,
           tooltip: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.setObjectName(kind)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setFixedHeight(height)
    if width is not None:
        widget.setFixedWidth(width)
    widget.setCheckable(checkable)
    if tooltip:
        widget.setToolTip(tooltip)
    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return widget


def label(text: str = "", size: float = 13, weight: int = QFont.Weight.Normal,
          color: str = theme.TEXT, spacing: float = 0.0,
          mono: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setFont(theme.mono_font(size) if mono
                   else theme.ui_font(size, weight, spacing))
    widget.setStyleSheet(f"color: {color}; background: transparent;")
    return widget


class ElidedLabel(QLabel):
    """A label that ends in "…" instead of being cut off mid-letter.

    Qt only elides inside item views, so rows that have to give way to buttons
    need this. Set the text once; it re-elides itself on every resize.
    """

    def __init__(self, text: str = "", size: float = 12,
                 weight: int = QFont.Weight.Normal, color: str = theme.TEXT,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._full = text
        self.setFont(theme.ui_font(size, weight))
        self.setStyleSheet(f"color: {color}; background: transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(24)
        self._apply()

    def setText(self, text: str) -> None:
        self._full = text
        self._apply()

    def fullText(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        metrics = QFontMetrics(self.font())
        width = max(self.width() - 2, 24)
        super().setText(metrics.elidedText(self._full, Qt.TextElideMode.ElideRight,
                                           width))
        self.setToolTip(self._full if metrics.horizontalAdvance(self._full) > width
                        else "")


def hline() -> QWidget:
    line = QWidget()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.BORDER};")
    return line


def vline(height: int = 32) -> QWidget:
    line = QWidget()
    line.setFixedSize(1, height)
    line.setStyleSheet("background: rgba(255,255,255,0.08);")
    return line


# --------------------------------------------------------------------------
# Faders and sliders
# --------------------------------------------------------------------------


class Fader(QWidget):
    """Vertical channel fader, 0..100."""

    valueChanged = Signal(int)

    def __init__(self, value: int = 75, color: str = theme.PINK,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._value = value
        self._color = color
        self._gradient = False
        self._dragging = False
        self.setFixedSize(26, 124)
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int, notify: bool = False) -> None:
        value = max(0, min(100, int(value)))
        if value != self._value:
            self._value = value
            self.update()
            if notify:
                self.valueChanged.emit(value)

    def setColor(self, color: str, gradient: bool = False) -> None:
        self._color = color
        self._gradient = gradient
        self.update()

    def _apply(self, y: float) -> None:
        track = self.height()
        self.setValue(round((1.0 - max(0.0, min(1.0, y / track))) * 100), notify=True)

    def mousePressEvent(self, event) -> None:
        self._dragging = True
        self._apply(event.position().y())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._apply(event.position().y())

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False

    def wheelEvent(self, event) -> None:
        self.setValue(self._value + (1 if event.angleDelta().y() > 0 else -1) * 3,
                      notify=True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        centre = width / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qc("rgba(255,255,255,0.10)"))
        painter.drawRoundedRect(QRectF(centre - 2, 0, 4, height), 2, 2)

        fill = height * self._value / 100.0
        if fill > 0:
            if self._gradient:
                gradient = QLinearGradient(0, height, 0, height - fill)
                gradient.setColorAt(0.0, qc(theme.PINK))
                gradient.setColorAt(1.0, qc(theme.PURPLE))
                painter.setBrush(QBrush(gradient))
            else:
                painter.setBrush(qc(self._color))
            painter.drawRoundedRect(QRectF(centre - 2, height - fill, 4, fill), 2, 2)

        knob_y = height - fill
        painter.setBrush(qc("#E8EAF2"))
        painter.drawRoundedRect(QRectF(centre - 11, knob_y - 5.5, 22, 11), 4, 4)


class Slider(QWidget):
    """Horizontal parameter slider, 0..100."""

    valueChanged = Signal(int)

    def __init__(self, value: int = 50, color: str = theme.PINK,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._value = value
        self._color = color
        self._dragging = False
        self.setFixedHeight(18)
        self.setMinimumWidth(60)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int, notify: bool = False) -> None:
        value = max(0, min(100, int(value)))
        if value != self._value:
            self._value = value
            self.update()
            if notify:
                self.valueChanged.emit(value)

    def _apply(self, x: float) -> None:
        self.setValue(round(max(0.0, min(1.0, x / max(self.width(), 1))) * 100),
                      notify=True)

    def mousePressEvent(self, event) -> None:
        self._dragging = True
        self._apply(event.position().x())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._apply(event.position().x())

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False

    def wheelEvent(self, event) -> None:
        self.setValue(self._value + (1 if event.angleDelta().y() > 0 else -1) * 3,
                      notify=True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        middle = height / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qc("rgba(255,255,255,0.10)"))
        painter.drawRoundedRect(QRectF(0, middle - 1.5, width, 3), 2, 2)

        fill = width * self._value / 100.0
        painter.setBrush(qc(self._color))
        painter.drawRoundedRect(QRectF(0, middle - 1.5, fill, 3), 2, 2)
        painter.setBrush(qc("#E8EAF2"))
        painter.drawEllipse(QPointF(fill, middle), 5.5, 5.5)


class SeekBar(QWidget):
    """Transport scrubber with A/B markers and a live drag preview."""

    seeked = Signal(float)          # 0..1, on release
    scrubbing = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._fraction = 0.0
        self._drag_fraction: Optional[float] = None
        self.mark_in: Optional[float] = None
        self.mark_out: Optional[float] = None
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def fraction(self) -> float:
        return self._drag_fraction if self._drag_fraction is not None else self._fraction

    def setFraction(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._fraction) > 1e-4:
            self._fraction = value
            if self._drag_fraction is None:
                self.update()

    def setMarks(self, mark_in: Optional[float], mark_out: Optional[float]) -> None:
        self.mark_in, self.mark_out = mark_in, mark_out
        self.update()

    def _fraction_at(self, x: float) -> float:
        return max(0.0, min(1.0, x / max(self.width(), 1)))

    def mousePressEvent(self, event) -> None:
        self._drag_fraction = self._fraction_at(event.position().x())
        self.scrubbing.emit(True)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_fraction is not None:
            self._drag_fraction = self._fraction_at(event.position().x())
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_fraction is not None:
            value = self._drag_fraction
            self._drag_fraction = None
            self._fraction = value
            self.scrubbing.emit(False)
            self.seeked.emit(value)
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        middle = height / 2
        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(qc("rgba(255,255,255,0.09)"))
        painter.drawRoundedRect(QRectF(0, middle - 2.5, width, 5), 3, 3)

        if self.mark_in is not None and self.mark_out is not None:
            left = width * self.mark_in
            painter.setBrush(qc(theme.GREEN, 0.25))
            painter.drawRect(QRectF(left, middle - 2.5,
                                    width * (self.mark_out - self.mark_in), 5))

        fill = width * self.fraction()
        gradient = QLinearGradient(0, 0, width, 0)
        gradient.setColorAt(0.0, qc(theme.PINK))
        gradient.setColorAt(1.0, qc(theme.PURPLE))
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(QRectF(0, middle - 2.5, fill, 5), 3, 3)

        painter.setBrush(qc(theme.GREEN))
        for mark in (self.mark_in, self.mark_out):
            if mark is not None:
                painter.drawRoundedRect(QRectF(width * mark - 1, 2, 2, height - 4), 1, 1)

        painter.setBrush(qc("#ffffff"))
        painter.drawEllipse(QPointF(fill, middle), 6.5, 6.5)


class Switch(QWidget):
    """Settings toggle."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._checked = checked
        self._knob = 21.0 if checked else 3.0
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._animate)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, notify: bool = False) -> None:
        if checked == self._checked:
            return
        self._checked = checked
        self._timer.start()
        if notify:
            self.toggled.emit(checked)

    def _animate(self) -> None:
        target = 21.0 if self._checked else 3.0
        self._knob += (target - self._knob) * 0.35
        if abs(target - self._knob) < 0.4:
            self._knob = target
            self._timer.stop()
        self.update()

    def mousePressEvent(self, event) -> None:
        self.setChecked(not self._checked, notify=True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qc(theme.PINK) if self._checked else qc("rgba(255,255,255,0.14)"))
        painter.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        painter.setBrush(qc("#ffffff"))
        painter.drawEllipse(QRectF(self._knob, 3, 16, 16))


class ProgressStrip(QWidget):
    """Thin two-tone progress bar used by download cards and the toast."""

    def __init__(self, color: str = theme.BLUE, height: int = 4,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._fraction = 0.0
        self._color = color
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def setProgress(self, fraction: float, color: Optional[str] = None) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        if color:
            self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = self.height() / 2
        painter.setBrush(qc("rgba(255,255,255,0.10)"))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
        painter.setBrush(qc(self._color))
        painter.drawRoundedRect(
            QRectF(0, 0, self.width() * self._fraction, self.height()), radius, radius)


class MicLevel(QWidget):
    """Live input meter for one microphone.

    Answers the only question that matters after picking a device — "is it
    hearing me?" — without the user having to start a song to find out.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._level = 0.0
        self._peak = 0.0
        self.setFixedHeight(4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_level(self, peak: float) -> None:
        # Fast rise, slow fall — the way every meter behaves, so a short
        # syllable is still visible.
        peak = max(0.0, min(1.0, peak))
        self._level = peak if peak > self._level else self._level * 0.82
        self._peak = max(peak, self._peak * 0.96)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        width, height = self.width(), self.height()
        painter.setBrush(qc("rgba(255,255,255,0.08)"))
        painter.drawRoundedRect(QRectF(0, 0, width, height), 2, 2)

        # A logarithmic scale, because a voice spends most of its life quiet.
        import math
        shown = 0.0 if self._level < 1e-4 else \
            max(0.0, min(1.0, (20 * math.log10(self._level) + 54) / 54))
        if shown > 0:
            # Colour comes from the true peak, not from where the bar happens to
            # sit: on a log scale a perfectly healthy voice already fills most
            # of the bar, and painting that red would teach the singer to back
            # off when nothing is wrong.
            if self._level < 0.70:
                colour = theme.GREEN
            elif self._level < 0.90:
                colour = "#FFB020"
            else:
                colour = theme.RED
            painter.setBrush(qc(colour))
            painter.drawRoundedRect(QRectF(0, 0, width * shown, height), 2, 2)


class Badge(QLabel):
    """Small rounded status pill."""

    def __init__(self, text: str = "", color: str = theme.GREEN,
                 parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setFont(theme.ui_font(10.5, QFont.Weight.DemiBold))
        self.set_color(color)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_color(self, color: str) -> None:
        base = qc(color)
        self.setStyleSheet(
            f"color: {color};"
            f"background: rgba({base.red()},{base.green()},{base.blue()},0.12);"
            f"border: 1px solid rgba({base.red()},{base.green()},{base.blue()},0.32);"
            "border-radius: 9px; padding: 3px 9px;"
        )


class Thumbnail(QLabel):
    """Rounded artwork holder that falls back to a deterministic gradient."""

    GRADIENTS = (
        ("#3D1F5C", "#1F2E5C"), ("#5C1F3A", "#2E1F5C"), ("#1F4A5C", "#3A1F5C"),
        ("#5C3A1F", "#5C1F4A"), ("#1F5C46", "#1F3A5C"), ("#46205C", "#20465C"),
    )

    def __init__(self, width: int = 104, height: int = 58, seed: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._radius = 7
        self._pixmap: Optional[QPixmap] = None
        self._colors = self.GRADIENTS[(sum(map(ord, seed or "x"))) % len(self.GRADIENTS)]
        self._overlay = ""

    def set_overlay(self, text: str) -> None:
        self._overlay = text
        self.update()

    def set_image(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)

        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(
                int((self.width() - scaled.width()) / 2),
                int((self.height() - scaled.height()) / 2), scaled)
        else:
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0.0, QColor(self._colors[0]))
            gradient.setColorAt(1.0, QColor(self._colors[1]))
            painter.fillPath(path, QBrush(gradient))

        if self._overlay:
            painter.setFont(theme.mono_font(8.5))
            metrics = QFontMetrics(painter.font())
            text_width = metrics.horizontalAdvance(self._overlay) + 8
            box = QRectF(self.width() - text_width - 4, self.height() - 16,
                         text_width, 13)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(qc("rgba(0,0,0,0.75)"))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(QPen(qc("#ffffff")))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._overlay)


class EqualizerBackdrop(QWidget):
    """The slow bar animation behind the stage.

    Runs at 20 fps and stops entirely when hidden — it is decoration, and
    decoration does not get to compete with the audio thread for CPU.
    """

    BARS = (
        (180, theme.PINK, 1.10, 0.00),
        (260, theme.INDIGO, 1.40, 0.20),
        (320, theme.PINK, 0.90, 0.10),
        (240, theme.INDIGO, 1.30, 0.35),
        (190, theme.PINK, 1.05, 0.50),
    )

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._phase = 0.0
        self._level = 0.35
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    def set_level(self, level: float) -> None:
        """0..1 — how energetic the bars look. Driven by playback state."""
        self._level = max(0.15, min(1.0, level))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self) -> None:
        self._phase += 0.05
        self.update()

    def paintEvent(self, event) -> None:
        import math
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(0.14)
        painter.setPen(Qt.PenStyle.NoPen)

        total = len(self.BARS)
        spacing = 10
        bar_width = 26
        span = total * bar_width + (total - 1) * spacing
        left = (self.width() - span) / 2
        bottom = self.height()

        for index, (base_height, color, speed, offset) in enumerate(self.BARS):
            wave = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(self._phase * speed
                                                       + offset * 6.28))
            height = base_height * wave * self._level
            x = left + index * (bar_width + spacing)
            gradient = QLinearGradient(0, bottom, 0, bottom - height)
            gradient.setColorAt(0.0, qc(color))
            gradient.setColorAt(1.0, qc(color, 0.0))
            painter.setBrush(QBrush(gradient))
            painter.drawRect(QRectF(x, bottom - height, bar_width, height))
