"""
Audio settings: devices, mic count, ducking, noise gate, monitor level.
"""
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QVBoxLayout,
                               QWidget)

from ..audio.engine import MAX_MICS
from . import theme
from .widgets import Slider, Switch, button, hline, label


class SettingsDialog(QDialog):
    """Modal settings sheet. Applies live; nothing is deferred to OK."""

    outputChanged = Signal(object)          # device index or None
    micCountChanged = Signal(int)
    duckingChanged = Signal(bool)
    gateChanged = Signal(bool)
    monitorChanged = Signal(int)

    def __init__(self, outputs: List[Dict], inputs: List[Dict],
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Audio settings")
        self.setModal(True)
        self.setFixedWidth(500)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.BG_RAISED};"
            f" border: 1px solid {theme.BORDER_STRONG}; border-radius: 16px; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.addWidget(label("Audio settings", 15, QFont.Weight.Bold))
        header.addStretch(1)
        close = button("✕", "BtnIcon", height=26, width=26)
        close.clicked.connect(self.accept)
        header.addWidget(close)
        layout.addLayout(header)

        self.output_box = self._combo(
            layout, "OUTPUT DEVICE",
            [("System default", None)] + [(d["name"], d["id"]) for d in outputs])
        self.output_box.currentIndexChanged.connect(
            lambda i: self.outputChanged.emit(self.output_box.itemData(i)))

        self.mic_count = self._combo(
            layout, "NUMBER OF MICROPHONES",
            [(f"{n} mic{'s' if n > 1 else ''}", n) for n in range(1, MAX_MICS + 1)])
        self.mic_count.currentIndexChanged.connect(
            lambda i: self._on_mic_count(self.mic_count.itemData(i)))

        # Which device each microphone uses lives on its channel strip in the
        # mixer, not here — it is a per-performance decision, not a setting.
        hint = label("Pick each microphone from its channel strip in the mixer.",
                     11, color=theme.TEXT_FAINT)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(hline())

        self.ducking = self._toggle(
            layout, "Smart music ducking",
            "Lowers the track −6 dB automatically while you record")
        self.ducking.toggled.connect(self.duckingChanged)

        self.gate = self._toggle(
            layout, "Noise gate",
            "Cuts mic background noise between phrases")
        self.gate.toggled.connect(self.gateChanged)

        monitor_row = QHBoxLayout()
        monitor_row.setSpacing(12)
        monitor_row.addWidget(label("Mic monitor level", 12.5, QFont.Weight.DemiBold))
        self.monitor = Slider(60)
        self.monitor_value = label("60", 11, color=theme.TEXT_DIM, mono=True)
        self.monitor_value.setFixedWidth(30)
        self.monitor_value.setAlignment(Qt.AlignmentFlag.AlignRight
                                        | Qt.AlignmentFlag.AlignVCenter)
        self.monitor.valueChanged.connect(lambda v: self.monitor_value.setText(str(v)))
        self.monitor.valueChanged.connect(self.monitorChanged)
        monitor_row.addWidget(self.monitor, 1)
        monitor_row.addWidget(self.monitor_value)
        layout.addLayout(monitor_row)

        footer = QHBoxLayout()
        footer.addStretch(1)
        done = button("Done", "BtnAccent", height=34)
        done.clicked.connect(self.accept)
        footer.addWidget(done)
        layout.addLayout(footer)

    # -- construction helpers ---------------------------------------------
    def _make_combo(self, options) -> QComboBox:
        box = QComboBox()
        box.setFont(theme.ui_font(12))
        box.setCursor(Qt.CursorShape.PointingHandCursor)
        for name, value in options:
            box.addItem(name, value)
        return box

    def _combo(self, layout: QVBoxLayout, title: str, options) -> QComboBox:
        block = QVBoxLayout()
        block.setSpacing(7)
        block.addWidget(label(title, 11, QFont.Weight.Bold, theme.TEXT_DIM,
                              spacing=10))
        box = self._make_combo(options)
        block.addWidget(box)
        layout.addLayout(block)
        return box

    def _toggle(self, layout: QVBoxLayout, title: str, description: str) -> Switch:
        row = QHBoxLayout()
        column = QVBoxLayout()
        column.setSpacing(1)
        column.addWidget(label(title, 12.5, QFont.Weight.DemiBold))
        column.addWidget(label(description, 10.5, color="rgba(238,240,248,0.45)"))
        row.addLayout(column, 1)
        switch = Switch()
        row.addWidget(switch)
        layout.addLayout(row)
        return switch

    def _on_mic_count(self, count: int) -> None:
        self.micCountChanged.emit(count)

    # -- state ------------------------------------------------------------
    def load(self, config) -> None:
        self._select(self.output_box, config.get("output_device"))
        self._select(self.mic_count, config.get("mic_count", 2))
        self.ducking.setChecked(bool(config.get("ducking", True)))
        self.gate.setChecked(bool(config.get("gate", True)))
        self.monitor.setValue(int(config.get("monitor", 0.6) * 100))
        self.monitor_value.setText(str(self.monitor.value()))
        self._on_mic_count(int(config.get("mic_count", 2)))

    @staticmethod
    def _select(box: QComboBox, value) -> None:
        index = box.findData(value)
        box.blockSignals(True)
        box.setCurrentIndex(index if index >= 0 else 0)
        box.blockSignals(False)
