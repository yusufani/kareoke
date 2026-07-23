"""
The right-hand panel: channel strips, the per-microphone FX rack, and the queue.
"""
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..audio.fx import FX_LABELS, FX_PARAMS, PRESETS
from ..core.library import SongEntry
from . import theme
from .widgets import (ElidedLabel, Fader, MicLevel, Slider, button, hline,
                      label)


class ChannelStrip(QWidget):
    """One fader with its name, readout, mute and (for mics) FX button."""

    volumeChanged = Signal(str, int, int)     # kind, index, 0..100
    muteToggled = Signal(str, int, bool)   # kind, index, muted
    fxRequested = Signal(int)
    deviceRequested = Signal(int, object)     # mic index, global position

    def __init__(self, kind: str, index: int, name: str, color: str,
                 value: int = 75, has_fx: bool = False,
                 gradient: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.kind = kind
        self.index = index
        self.has_fx = has_fx
        self._color = color
        self._muted = False
        self._fx_active = False

        self.setMinimumWidth(52)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 10, 4, 9)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # A microphone's name doubles as its device picker — the thing you reach
        # for most often should not be three clicks deep in a settings dialog.
        if has_fx:
            self.name = button(f"{name} ▾", "BtnFlat", height=16)
            self.name.setFont(theme.ui_font(10, QFont.Weight.Bold, spacing=5))
            self.name.setStyleSheet(
                f"border: none; background: transparent; color: {color};"
                "padding: 0;")
            self.name.setToolTip("Choose the microphone for this channel")
            self.name.clicked.connect(self._ask_device)
        else:
            self.name = label(name, 10, QFont.Weight.Bold, color, spacing=5)
            self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.name)

        self.fader = Fader(value, color)
        self.fader.setColor(color, gradient)
        self.fader.valueChanged.connect(self._on_fader)
        layout.addWidget(self.fader, 0, Qt.AlignmentFlag.AlignHCenter)

        self.readout = label(str(value), 10, color=theme.TEXT_DIM, mono=True)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.readout)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        buttons.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.mute = button("M", "BtnIcon", height=20, width=22,
                           checkable=True, tooltip="Mute")
        self.mute.setFont(theme.ui_font(9.5, QFont.Weight.Bold))
        self.mute.toggled.connect(self._on_mute)
        buttons.addWidget(self.mute)
        if has_fx:
            self.fx = button("FX", "BtnIcon", height=20, width=26,
                             tooltip="Voice effects for this mic")
            self.fx.setFont(theme.ui_font(9, QFont.Weight.Bold))
            self.fx.clicked.connect(lambda: self.fxRequested.emit(self.index))
            buttons.addWidget(self.fx)
        else:
            self.fx = None
        layout.addLayout(buttons)

        if has_fx:
            self.level = MicLevel()
            layout.addWidget(self.level)
            self.device = ElidedLabel("No mic", 8.5, color=theme.TEXT_FAINT)
            self.device.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.device.setCursor(Qt.CursorShape.PointingHandCursor)
            self.device.mousePressEvent = lambda _: self._ask_device()
            layout.addWidget(self.device)
        else:
            self.level = None
            self.device = None

        self._paint_background()

    def _ask_device(self) -> None:
        anchor = self.device or self.name
        self.deviceRequested.emit(
            self.index, anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def set_device(self, name: Optional[str], working: bool) -> None:
        if self.device is None:
            return
        self.device.setText(name or "No mic — tap to choose")
        self.device.setStyleSheet(
            f"color: {theme.GREEN if working else theme.TEXT_FAINT};"
            "background: transparent;")

    def set_level(self, peak: float) -> None:
        if self.level is not None:
            self.level.set_level(peak)

    def _paint_background(self) -> None:
        highlight = self._fx_active
        self.setStyleSheet(
            "ChannelStrip {"
            f"  background: {'rgba(255,61,127,0.07)' if highlight else theme.SURFACE};"
            f"  border: 1px solid {'rgba(255,61,127,0.35)' if highlight else 'rgba(255,255,255,0.06)'};"
            "  border-radius: 10px;"
            "}"
        )

    def set_fx_active(self, active: bool) -> None:
        if active != self._fx_active:
            self._fx_active = active
            self._paint_background()
            if self.fx is not None:
                self.fx.setStyleSheet(
                    "background: rgba(255,61,127,0.3); color: #FF9EC2;"
                    "border: 1px solid rgba(255,61,127,0.5); border-radius: 5px;"
                    if active else "")

    def _on_fader(self, value: int) -> None:
        self.readout.setText("–" if self._muted else str(value))
        self.volumeChanged.emit(self.kind, self.index, value)

    def _on_mute(self, muted: bool, notify: bool = True) -> None:
        self._muted = muted
        self.readout.setText("–" if muted else str(self.fader.value()))
        self.fader.setColor("rgba(255,255,255,0.2)" if muted else self._color)
        self.mute.setStyleSheet(
            "background: rgba(255,69,69,0.25); color: #FF8A8A;"
            "border: 1px solid rgba(255,69,69,0.4); border-radius: 5px;"
            if muted else "")
        if notify:
            self.muteToggled.emit(self.kind, self.index, muted)

    def set_value(self, value: int) -> None:
        self.fader.setValue(value)
        self.readout.setText("–" if self._muted else str(value))

    def set_muted(self, muted: bool) -> None:
        """Reflect the engine's state without reporting it back.

        Rebuilding the strips (adding a mic, changing the count) must not be
        mistaken for the user pressing M — an earlier version emitted here and
        every rebuild silently inverted which channels were muted.
        """
        if muted == self.mute.isChecked():
            return
        self.mute.blockSignals(True)
        self.mute.setChecked(muted)
        self.mute.blockSignals(False)
        self._on_mute(muted, notify=False)


class FXRack(QWidget):
    """Preset chips plus the five parameter sliders for one microphone."""

    presetPicked = Signal(int, str)
    paramChanged = Signal(int, str, int)
    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.mic_index = 0
        self._sliders: Dict[str, Slider] = {}
        self._readouts: Dict[str, QLabel] = {}
        self._chips = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(8)

        header = QHBoxLayout()
        self.title = label("FX · MIC 1", 11, QFont.Weight.Bold,
                           theme.TEXT_DIM, spacing=18)
        header.addWidget(self.title)
        header.addStretch(1)
        close = button("✕", "BtnIcon", height=20, width=20)
        close.clicked.connect(self.closed)
        header.addWidget(close)
        outer.addLayout(header)

        # Six presets will not fit across a 372 px column on one line, so they
        # sit in a 3x2 grid rather than being squeezed until the names clip.
        chips = QGridLayout()
        chips.setSpacing(5)
        chips.setContentsMargins(0, 0, 0, 16)
        for position, name in enumerate(PRESETS):
            chip = button(name, "BtnChip", height=24, checkable=True)
            chip.setFont(theme.ui_font(10.5, QFont.Weight.DemiBold))
            chip.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Fixed)
            chip.clicked.connect(lambda _, n=name: self._pick(n))
            self._chips[name] = chip
            chips.addWidget(chip, position // 3, position % 3)
        chip_host = QWidget()
        chip_host.setLayout(chips)
        # Sized from the number of presets, not a hard-coded two rows — adding
        # one more otherwise squashes them all until the labels clip.
        rows = -(-len(PRESETS) // 3)
        chip_host.setFixedHeight(24 * rows + 5 * (rows - 1) + 16)
        outer.addWidget(chip_host)

        for key in FX_PARAMS:
            name, description = FX_LABELS[key]
            row = QHBoxLayout()
            row.setSpacing(10)

            text = QVBoxLayout()
            text.setSpacing(1)
            text.setContentsMargins(0, 0, 0, 0)
            text.addWidget(label(name, 10.5, QFont.Weight.DemiBold,
                                 "rgba(238,240,248,0.78)"))
            hint = label(description, 8.5, color=theme.TEXT_FAINT)
            hint.setToolTip(description)
            text.addWidget(hint)
            holder = QWidget()
            holder.setFixedWidth(112)
            holder.setLayout(text)
            row.addWidget(holder)

            slider = Slider(0)
            slider.valueChanged.connect(
                lambda value, k=key: self.paramChanged.emit(self.mic_index, k, value))
            self._sliders[key] = slider
            row.addWidget(slider, 1)

            readout = label("0", 10, color=theme.TEXT_DIM, mono=True)
            readout.setFixedWidth(26)
            readout.setAlignment(Qt.AlignmentFlag.AlignRight
                                 | Qt.AlignmentFlag.AlignVCenter)
            self._readouts[key] = readout
            slider.valueChanged.connect(lambda v, r=readout: r.setText(str(v)))
            row.addWidget(readout)
            outer.addLayout(row)

    def _pick(self, name: str) -> None:
        self.presetPicked.emit(self.mic_index, name)

    def show_mic(self, index: int, name: str, params: Dict[str, float],
                 preset: str) -> None:
        self.mic_index = index
        self.title.setText(f"FX · {name.upper()}")
        for key, slider in self._sliders.items():
            slider.blockSignals(True)
            slider.setValue(int(params.get(key, 0)))
            slider.blockSignals(False)
            self._readouts[key].setText(str(int(params.get(key, 0))))
        for name_, chip in self._chips.items():
            chip.setChecked(name_ == preset)


class QueueRow(QWidget):
    """One "up next" entry."""

    playNow = Signal(str)
    removed = Signal(str)

    def __init__(self, number: int, entry: SongEntry,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.song_id = entry.id
        self.setObjectName("QueueRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#QueueRow { background: rgba(255,255,255,0.03); border-radius: 8px; }"
            "#QueueRow:hover { background: rgba(255,255,255,0.07); }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(10)

        index = label(str(number), 10.5, color=theme.TEXT_FAINT, mono=True)
        index.setFixedWidth(20)
        index.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(index)

        column = QVBoxLayout()
        column.setSpacing(1)
        column.addWidget(ElidedLabel(entry.title, 12, QFont.Weight.DemiBold))
        minutes = int(entry.duration) // 60
        seconds = int(entry.duration) % 60
        meta = f"{entry.display_artist} · {minutes}:{seconds:02d}" if entry.duration \
            else entry.display_artist
        column.addWidget(ElidedLabel(meta, 10.5, color="rgba(238,240,248,0.45)"))
        layout.addLayout(column, 1)

        play = button("▶", "BtnIcon", height=24, width=24, tooltip="Play now")
        play.setFont(theme.ui_font(9))
        play.setStyleSheet(
            "background: rgba(255,61,127,0.15); color: #FF6B9E;"
            "border: none; border-radius: 6px;")
        play.clicked.connect(lambda: self.playNow.emit(self.song_id))
        layout.addWidget(play)

        remove = button("✕", "BtnFlat", height=24, width=24, tooltip="Remove")
        remove.setFont(theme.ui_font(11))
        remove.clicked.connect(lambda: self.removed.emit(self.song_id))
        layout.addWidget(remove)


class MixerPanel(QWidget):
    """The whole right column."""

    volumeChanged = Signal(str, int, int)
    muteToggled = Signal(str, int, bool)
    presetPicked = Signal(int, str)
    paramChanged = Signal(int, str, int)
    queuePlay = Signal(str)
    queueRemove = Signal(str)
    addSongsRequested = Signal()
    deviceRequested = Signal(int, object)     # mic index, global position

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedWidth(372)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"MixerPanel {{ background: {theme.BG_PANEL};"
            f" border-left: 1px solid {theme.BORDER}; }}")
        self.strips: Dict[str, ChannelStrip] = {}
        self._mic_strips: List[ChannelStrip] = []
        self._queue_rows: List[QueueRow] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # The whole column scrolls as one, as in the design. Four mic strips
        # plus an open FX rack plus a long queue will not fit on a laptop
        # screen, and a nested scroller inside a nested scroller is worse than
        # simply letting the panel move.
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        outer.addWidget(scroller)
        scroller.setWidget(content)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(16, 14, 16, 10)
        header.addWidget(label("MIXER", 11, QFont.Weight.Bold, theme.TEXT_DIM,
                               spacing=18))
        header.addStretch(1)
        self.status = label("", 10.5, color=theme.TEXT_FAINT, mono=True)
        self.status.setMinimumWidth(140)
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight
                                 | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.status)
        outer.addLayout(header)

        self.strip_row = QHBoxLayout()
        self.strip_row.setContentsMargins(12, 0, 12, 12)
        self.strip_row.setSpacing(6)
        outer.addLayout(self.strip_row)

        outer.addWidget(hline())

        # No explicit minimum on the host: an explicit minimumSize replaces the
        # layout's own minimum, which would let the rack be squeezed until its
        # rows overlapped. The two children carry the floor instead.
        self.fx_host = QWidget()
        fx_layout = QVBoxLayout(self.fx_host)
        fx_layout.setContentsMargins(0, 0, 0, 0)
        self.fx_rack = FXRack()
        # Without a floor the surrounding layout squeezes the rack until the
        # preset grid collides with the sliders. The panel scrolls, so claiming
        # the space it actually needs costs nothing.
        self.fx_rack.setMinimumHeight(252 + 29 * (-(-len(PRESETS) // 3)))
        self.fx_rack.presetPicked.connect(self.presetPicked)
        self.fx_rack.paramChanged.connect(self.paramChanged)
        self.fx_rack.closed.connect(self.close_fx)
        self.fx_placeholder = label(
            "Tap <b>FX</b> on a mic channel<br>to shape its sound",
            12, color=theme.TEXT_GHOST)
        self.fx_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fx_placeholder.setTextFormat(Qt.TextFormat.RichText)
        self.fx_placeholder.setMinimumHeight(140)
        fx_layout.addWidget(self.fx_rack)
        fx_layout.addWidget(self.fx_placeholder)
        self.fx_rack.setVisible(False)
        outer.addWidget(self.fx_host)

        outer.addWidget(hline())

        queue_header = QHBoxLayout()
        queue_header.setContentsMargins(16, 12, 16, 8)
        queue_header.addWidget(label("UP NEXT", 11, QFont.Weight.Bold,
                                     theme.TEXT_DIM, spacing=18))
        queue_header.addStretch(1)
        self.queue_count = label("0 songs", 10.5, color=theme.TEXT_FAINT)
        queue_header.addWidget(self.queue_count)
        outer.addLayout(queue_header)

        self.queue_body = QWidget()
        self.queue_layout = QVBoxLayout(self.queue_body)
        self.queue_layout.setContentsMargins(10, 0, 10, 10)
        self.queue_layout.setSpacing(4)
        self.queue_layout.addStretch(1)
        outer.addWidget(self.queue_body, 1)

        self.queue_empty = QLabel(
            'Queue is empty — <a href="#add" style="color:#FF3D7F;'
            'text-decoration:none">add songs</a>')
        self.queue_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.queue_empty.setFont(theme.ui_font(11.5))
        self.queue_empty.setStyleSheet(f"color: {theme.TEXT_GHOST}; padding: 18px;")
        self.queue_empty.linkActivated.connect(lambda _: self.addSongsRequested.emit())
        self.queue_layout.insertWidget(0, self.queue_empty)

    # -- strips -----------------------------------------------------------
    def build_strips(self, mic_count: int, values: Dict) -> None:
        while self.strip_row.count():
            item = self.strip_row.takeAt(0)
            if item.widget():
                # Reparent first: a widget only removed from its layout keeps
                # painting until deleteLater() is serviced.
                item.widget().setParent(None)
                item.widget().deleteLater()
        self.strips.clear()
        self._mic_strips.clear()

        specs = [
            ("stem", 0, "Vocals", theme.COLOR_VOCALS,
             int(values["vocals"] * 100), False, False),
            ("stem", 1, "Music", theme.COLOR_MUSIC,
             int(values["instrumental"] * 100), False, False),
        ]
        for index in range(mic_count):
            specs.append(("mic", index, f"Mic {index + 1}", theme.COLOR_MIC,
                          int(values["mics"][index] * 100), True, False))
        specs.append(("master", 0, "Master", theme.COLOR_MASTER,
                      int(values["master"] * 100), False, True))

        for kind, index, name, color, value, has_fx, gradient in specs:
            strip = ChannelStrip(kind, index, name, color, value, has_fx, gradient)
            strip.volumeChanged.connect(self.volumeChanged)
            strip.muteToggled.connect(self.muteToggled)
            strip.fxRequested.connect(self.open_fx)
            strip.deviceRequested.connect(self.deviceRequested)
            self.strip_row.addWidget(strip)
            self.strips[f"{kind}:{index}"] = strip
            if kind == "mic":
                self._mic_strips.append(strip)
                strip.set_muted(bool(values["mic_muted"][index]))

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    @property
    def mic_strips(self) -> List[ChannelStrip]:
        return list(self._mic_strips)

    # -- FX ---------------------------------------------------------------
    def open_fx(self, mic_index: int) -> None:
        self.fx_rack.setVisible(True)
        self.fx_placeholder.setVisible(False)
        for strip in self._mic_strips:
            strip.set_fx_active(strip.index == mic_index)
        self.fx_rack.mic_index = mic_index

    def close_fx(self) -> None:
        self.fx_rack.setVisible(False)
        self.fx_placeholder.setVisible(True)
        for strip in self._mic_strips:
            strip.set_fx_active(False)

    def show_mic_fx(self, index: int, name: str, params: Dict[str, float],
                    preset: str) -> None:
        self.fx_rack.show_mic(index, name, params, preset)

    # -- queue ------------------------------------------------------------
    def set_queue(self, entries: List[SongEntry]) -> None:
        for row in self._queue_rows:
            row.setParent(None)
            row.deleteLater()
        self._queue_rows.clear()

        for position, entry in enumerate(entries, start=1):
            row = QueueRow(position, entry)
            row.playNow.connect(self.queuePlay)
            row.removed.connect(self.queueRemove)
            self.queue_layout.insertWidget(position - 1, row)
            self._queue_rows.append(row)

        self.queue_empty.setVisible(not entries)
        self.queue_count.setText(f"{len(entries)} song{'' if len(entries) == 1 else 's'}")
