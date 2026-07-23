"""
The transport bar: play, scrub, tempo, key, A/B loop, record, takes.
"""
from typing import List, Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from . import theme
from .theme import qc
from .widgets import SeekBar, button, label, vline


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class RoundButton(QWidget):
    """Circular transport button, hand-painted so the glow works."""

    clicked = Signal()

    def __init__(self, diameter: int, icon: str, accent: bool = False,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon = icon
        self.accent = accent
        self.glow = accent
        self._hover = False

    def set_icon(self, icon: str) -> None:
        if icon != self.icon:
            self.icon = icon
            self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = self.width()
        rect = QRectF(1, 1, size - 2, size - 2)

        if self.accent:
            gradient = QLinearGradient(0, 0, size, size)
            base = ("#FF5B93", "#C75BFF") if self._hover else (theme.PINK, theme.PURPLE)
            gradient.setColorAt(0.0, qc(base[0]))
            gradient.setColorAt(1.0, qc(base[1]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(gradient))
        else:
            painter.setPen(QPen(qc("rgba(255,255,255,0.15)"), 1))
            painter.setBrush(qc("rgba(255,255,255,0.08)") if self._hover
                             else Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qc("#ffffff" if self.accent else theme.TEXT_DIM))
        centre = size / 2
        if self.icon == "play":
            path = QPainterPath()
            unit = size * 0.26
            path.moveTo(centre - unit * 0.55, centre - unit)
            path.lineTo(centre + unit, centre)
            path.lineTo(centre - unit * 0.55, centre + unit)
            path.closeSubpath()
            painter.drawPath(path)
        elif self.icon == "pause":
            bar = size * 0.09
            height = size * 0.30
            painter.drawRoundedRect(
                QRectF(centre - bar * 2.1, centre - height, bar * 1.7, height * 2), 1, 1)
            painter.drawRoundedRect(
                QRectF(centre + bar * 0.4, centre - height, bar * 1.7, height * 2), 1, 1)
        elif self.icon == "stop":
            side = size * 0.32
            painter.drawRoundedRect(
                QRectF(centre - side / 2, centre - side / 2, side, side), 2, 2)


class Stepper(QWidget):
    """Bordered −/value/+ control used for tempo and key."""

    stepped = Signal(int)

    def __init__(self, text: str, width: int = 44,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "Stepper { border: 1px solid rgba(255,255,255,0.09);"
            " border-radius: 8px; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(4)

        down = button("−", "BtnStep", height=20, width=20)
        down.clicked.connect(lambda: self.stepped.emit(-1))
        layout.addWidget(down)

        self.value = label(text, 11, color="rgba(238,240,248,0.8)", mono=True)
        self.value.setFixedWidth(width)
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value)

        up = button("+", "BtnStep", height=20, width=20)
        up.clicked.connect(lambda: self.stepped.emit(1))
        layout.addWidget(up)

    def set_text(self, text: str) -> None:
        self.value.setText(text)


class TransportBar(QWidget):
    """The strip along the bottom of the window."""

    playToggled = Signal()
    stopped = Signal()
    seeked = Signal(float)
    scrubbing = Signal(bool)
    speedStepped = Signal(int)
    keyStepped = Signal(int)
    markIn = Signal()
    markOut = Signal()
    recordToggled = Signal()
    takesToggled = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(76)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"TransportBar {{ background: {theme.BG_BAR};"
            f" border-top: 1px solid {theme.BORDER}; }}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(14)

        self.play = RoundButton(44, "play", accent=True)
        self.play.clicked.connect(self.playToggled)
        self.stop = RoundButton(32, "stop")
        self.stop.clicked.connect(self.stopped)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.play)
        buttons.addWidget(self.stop)
        layout.addLayout(buttons)

        self.elapsed = label("0:00", 11.5, color="rgba(238,240,248,0.6)", mono=True)
        self.elapsed.setFixedWidth(42)
        self.elapsed.setAlignment(Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.elapsed)

        self.seek = SeekBar()
        self.seek.seeked.connect(self.seeked)
        self.seek.scrubbing.connect(self.scrubbing)
        layout.addWidget(self.seek, 1)

        self.total = label("0:00", 11.5, color=theme.TEXT_FAINT, mono=True)
        self.total.setFixedWidth(42)
        layout.addWidget(self.total)

        self.speed = Stepper("1.00x", 42)
        self.speed.stepped.connect(self.speedStepped)
        layout.addWidget(self.speed)

        self.key = Stepper("KEY +0", 52)
        self.key.stepped.connect(self.keyStepped)
        layout.addWidget(self.key)

        layout.addWidget(vline(32))

        self.mark_a = button("A", "BtnPillGhost", height=28, width=34,
                             tooltip="Mark the start of a section (loop A)")
        self.mark_a.setFont(theme.ui_font(11, QFont.Weight.Bold))
        self.mark_a.clicked.connect(self.markIn)
        layout.addWidget(self.mark_a)

        self.mark_b = button("B", "BtnPillGhost", height=28, width=34,
                             tooltip="Mark the end of a section (loop B)")
        self.mark_b.setFont(theme.ui_font(11, QFont.Weight.Bold))
        self.mark_b.clicked.connect(self.markOut)
        layout.addWidget(self.mark_b)

        self.record = _RecordButton()
        self.record.clicked.connect(self.recordToggled)
        layout.addWidget(self.record)

        self.takes = button("Takes · 0", "BtnPillGhost", height=28)
        self.takes.clicked.connect(self.takesToggled)
        layout.addWidget(self.takes)

    # -- state ------------------------------------------------------------
    def set_playing(self, playing: bool) -> None:
        self.play.set_icon("pause" if playing else "play")

    def set_time(self, position: float, duration: float) -> None:
        self.elapsed.setText(clock(position))
        self.total.setText(clock(duration))
        self.seek.setFraction(position / duration if duration else 0.0)

    def set_marks(self, mark_in: Optional[float], mark_out: Optional[float],
                  duration: float) -> None:
        span = duration or 1.0
        self.seek.setMarks(None if mark_in is None else mark_in / span,
                           None if mark_out is None else mark_out / span)
        for widget, value in ((self.mark_a, mark_in), (self.mark_b, mark_out)):
            widget.setStyleSheet(
                "border-radius: 12px; border: 1px solid rgba(61,220,151,0.6);"
                "background: rgba(61,220,151,0.14); color: #3DDC97;"
                if value is not None else "")

    def set_speed(self, speed: float) -> None:
        self.speed.set_text(f"{speed:.2f}x")

    def set_key(self, key: int) -> None:
        self.key.set_text(f"KEY {key:+d}")

    def set_recording(self, recording: bool) -> None:
        self.record.set_recording(recording)

    def set_takes(self, count: int) -> None:
        self.takes.setText(f"Takes · {count}")


class _RecordButton(QWidget):
    """Pill with a pulsing dot."""

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(112, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recording = False
        self._hover = False

    def set_recording(self, recording: bool) -> None:
        self.recording = recording
        self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        if self.recording:
            painter.setPen(QPen(qc("rgba(255,69,69,0.7)"), 1))
            painter.setBrush(qc("rgba(255,69,69,0.16)"))
        else:
            painter.setPen(QPen(qc(theme.BORDER_STRONG), 1))
            painter.setBrush(qc("rgba(255,255,255,0.06)") if self._hover
                             else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 17, 17)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qc(theme.RED))
        painter.drawEllipse(QRectF(15, self.height() / 2 - 4.5, 9, 9))

        painter.setFont(theme.ui_font(12, QFont.Weight.Bold))
        painter.setPen(QPen(qc(theme.RED_LIGHT if self.recording
                               else "rgba(238,240,248,0.8)")))
        painter.drawText(QRectF(31, 0, self.width() - 36, self.height()),
                         Qt.AlignmentFlag.AlignVCenter,
                         "Stop" if self.recording else "Record")


class TakesPopover(QWidget):
    """Floating list of recorded takes."""

    playTake = Signal(str)
    exportTake = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedWidth(300)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"TakesPopover {{ background: {theme.BG_RAISED};"
            f" border: 1px solid {theme.BORDER_STRONG}; border-radius: 12px; }}")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(label("MY TAKES", 11, QFont.Weight.Bold, theme.TEXT_DIM,
                               spacing=16))
        header.addStretch(1)
        close = button("✕", "BtnFlat", height=20, width=20)
        close.clicked.connect(self.hide)
        header.addWidget(close)
        self._layout.addLayout(header)

        self.empty = label("No takes yet — set A/B markers and hit REC",
                           11.5, color=theme.TEXT_GHOST)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self._layout.addWidget(self.empty)
        self._rows: List[QWidget] = []

    def set_takes(self, takes: List[dict]) -> None:
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        for index, take in enumerate(takes, start=1):
            row = QWidget()
            row.setStyleSheet("QWidget:hover { background: rgba(255,255,255,0.05); }")
            line = QHBoxLayout(row)
            line.setContentsMargins(8, 6, 8, 6)
            line.setSpacing(10)

            play = button("▶", "BtnIcon", height=26, width=26)
            play.setStyleSheet("background: rgba(255,61,127,0.16); color: #FF6B9E;"
                               "border: none; border-radius: 13px;")
            play.clicked.connect(lambda _, p=take["path"]: self.playTake.emit(p))
            line.addWidget(play)

            column = QVBoxLayout()
            column.setSpacing(1)
            column.addWidget(label(f"Take {index}", 12, QFont.Weight.DemiBold))
            column.addWidget(label(
                f"{clock(take['start'])} – {clock(take['end'])} · {clock(take['length'])}",
                10.5, color="rgba(238,240,248,0.45)", mono=True))
            line.addLayout(column, 1)

            export = button("Export", "BtnPillGhost", height=22)
            export.clicked.connect(lambda _, p=take["path"]: self.exportTake.emit(p))
            line.addWidget(export)

            self._layout.insertWidget(self._layout.count() - 1, row)
            self._rows.append(row)

        self.empty.setVisible(not takes)
        self.adjustSize()
