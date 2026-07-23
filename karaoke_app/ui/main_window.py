"""
The main window — where every part of Encore is wired together.

The layout mirrors the design: a slim top bar, the stage on the left, the mixer
column on the right, and the transport along the bottom. The drawer and the
takes popover float on top of all of it.

Two rules shape the code here:

* **Nothing slow happens on this thread.** Loading stems, searching, downloading
  and separating are all handed to :class:`JobManager`. The window only ever
  reacts to signals.
* **The audio engine is polled, never listened to.** A 30 fps timer reads the
  playhead and repaints; the audio callback never calls into Qt.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QVBoxLayout, QWidget)

from ..audio import lyrics as lyrics_api
from ..audio.device_manager import AudioDeviceManager
from ..audio.engine import MAX_MICS, KaraokeEngine
from ..audio.fx import FX_PARAMS
from ..audio.youtube import SearchResult
from ..core.config import Config
from ..core import migrate
from ..core.jobs import (STAGE_LYRICS, STAGE_READY, STAGE_SEPARATE, JobManager)
from ..core.library import LYRICS_UNKNOWN, Library, SongEntry
from ..core.paths import RECORDINGS_DIR
from . import theme
from .drawer import STAGE_COLORS, SongDrawer
from .mixer import MixerPanel
from .settings_dialog import SettingsDialog
from .stage import Stage
from .transport import TakesPopover, TransportBar
from .widgets import BUTTON_QSS, Badge, button, label

logger = logging.getLogger(__name__)


class _LoadSignals(QObject):
    done = Signal(str, float)
    failed = Signal(str, str)


class _LoadTask(QRunnable):
    """Reads a song's stems off the GUI thread."""

    def __init__(self, engine: KaraokeEngine, entry: SongEntry,
                 signals: _LoadSignals):
        super().__init__()
        self.engine = engine
        self.entry = entry
        self.signals = signals
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            duration = self.engine.load(Path(self.entry.vocals_path),
                                        Path(self.entry.instrumental_path))
        except Exception as exc:
            logger.error("Could not load %s: %s", self.entry.title, exc)
            self.signals.failed.emit(self.entry.id, str(exc))
            return
        self.signals.done.emit(self.entry.id, duration)


class MainWindow(QMainWindow):
    """Top-level window: builds the UI, owns the engine, routes every signal."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Encore — Karaoke Studio")
        self.resize(1440, 860)
        self.setMinimumSize(1120, 700)

        self.config = Config()
        self.library = Library()
        migrate.run(self.library)
        self.jobs = JobManager(self.library, self)
        self.engine = KaraokeEngine(int(self.config.get("block_size", 512)))

        self.current: Optional[SongEntry] = None
        self.current_lyrics = None
        self.queue: List[str] = []
        self.takes: List[dict] = []
        self._duration = 0.0
        self._scrubbing = False
        self._active_jobs: Dict[str, dict] = {}
        self._loading_id: Optional[str] = None

        self._build_ui()
        self._apply_config()
        self._wire()
        self._start_audio()

        self.load_signals = _LoadSignals()
        self.load_signals.done.connect(self._on_song_loaded)
        self.load_signals.failed.connect(self._on_song_load_failed)

        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(33)          # 30 fps is plenty for lyrics
        self._frame_timer.timeout.connect(self._tick)
        self._frame_timer.start()

        self._slow_timer = QTimer(self)
        self._slow_timer.setInterval(1000)
        self._slow_timer.timeout.connect(self._tick_slow)
        self._slow_timer.start()

        self.refresh_library()
        self.jobs.preload_separator()
        QTimer.singleShot(50, self._restore_last_song)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setStyleSheet(theme.stylesheet() + BUTTON_QSS)

        root = QWidget()
        root.setStyleSheet(f"background: {theme.BG};")
        self.setCentralWidget(root)
        column = QVBoxLayout(root)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        column.addWidget(self._build_top_bar())

        middle = QWidget()
        middle_layout = QHBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(0)
        self.stage = Stage()
        self.mixer = MixerPanel()
        middle_layout.addWidget(self.stage, 1)
        middle_layout.addWidget(self.mixer)
        column.addWidget(middle, 1)

        self.transport = TransportBar()
        column.addWidget(self.transport)

        # Floating layers, parented to the central widget so they cover it.
        self.drawer = SongDrawer(root)
        self.drawer.setVisible(False)
        self.takes_popover = TakesPopover(root)
        self.takes_popover.setVisible(False)

        self.statusBar().setStyleSheet(
            f"color: {theme.TEXT_DIM}; background: {theme.BG_BAR};"
            f"border-top: 1px solid {theme.BORDER};")
        self.statusBar().setSizeGripEnabled(False)

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(52)
        bar.setObjectName("TopBar")
        bar.setStyleSheet(
            f"#TopBar {{ background: {theme.BG_BAR};"
            f" border-bottom: 1px solid {theme.BORDER}; }}")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(16)

        mark = QLabel("E")
        mark.setFixedSize(22, 22)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {theme.PINK}, stop:1 {theme.INDIGO});"
            "border-radius: 6px; color: white; font-weight: 700; font-size: 12px;")
        brand = QHBoxLayout()
        brand.setSpacing(9)
        brand.addWidget(mark)
        brand.addWidget(label("ENCORE", 13, QFont.Weight.Bold, spacing=14))
        layout.addLayout(brand)

        layout.addStretch(1)
        centre = QHBoxLayout()
        centre.setSpacing(10)
        self.now_title = label("No song loaded", 13, QFont.Weight.DemiBold)
        self.now_artist = label("", 13, color=theme.TEXT_DIM)
        self.now_badge = Badge("", theme.GREEN)
        self.now_badge.setVisible(False)
        centre.addWidget(self.now_title)
        centre.addWidget(self.now_artist)
        centre.addWidget(self.now_badge)
        layout.addLayout(centre)
        layout.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.add_button = button("⌕   Add songs", "BtnSoft")
        self.add_button.clicked.connect(lambda: self.open_drawer("search"))
        self.library_button = button("Library", "BtnGhost")
        self.library_button.clicked.connect(lambda: self.open_drawer("library"))
        self.settings_button = button("⚙", "BtnIcon", height=32, width=32,
                                      tooltip="Audio settings")
        self.settings_button.clicked.connect(self.open_settings)
        actions.addWidget(self.add_button)
        actions.addWidget(self.library_button)
        actions.addWidget(self.settings_button)
        layout.addLayout(actions)
        return bar

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def _wire(self) -> None:
        self.transport.playToggled.connect(self.toggle_play)
        self.transport.stopped.connect(self.stop_playback)
        self.transport.seeked.connect(self._on_seek)
        self.transport.scrubbing.connect(self._on_scrubbing)
        self.transport.speedStepped.connect(self._on_speed)
        self.transport.keyStepped.connect(self._on_key)
        self.transport.markIn.connect(self._mark_in)
        self.transport.markOut.connect(self._mark_out)
        self.transport.recordToggled.connect(self.toggle_recording)
        self.transport.takesToggled.connect(self.toggle_takes)

        self.mixer.presetPicked.connect(self._on_preset)
        self.mixer.paramChanged.connect(self._on_fx_param)
        self.mixer.queuePlay.connect(self.play_song)
        self.mixer.queueRemove.connect(self.remove_from_queue)
        self.mixer.addSongsRequested.connect(lambda: self.open_drawer("search"))

        self.drawer.searchRequested.connect(self.jobs.search)
        self.drawer.prepareRequested.connect(self.prepare_song)
        self.drawer.playNow.connect(self.play_song)
        self.drawer.queueSong.connect(self.add_to_queue)
        self.drawer.removeSong.connect(self.remove_from_library)
        self.drawer.importRequested.connect(self.import_file)
        self.drawer.thumbRequested.connect(self.jobs.load_thumbnail)
        self.drawer.closed.connect(self.close_drawer)

        self.jobs.search_done.connect(self._on_search_done)
        self.jobs.search_failed.connect(self._on_search_failed)
        self.jobs.thumb_loaded.connect(self.drawer.apply_thumbnail)
        self.jobs.signals.progress.connect(self._on_job_progress)
        self.jobs.signals.finished.connect(self._on_job_finished)
        self.jobs.signals.failed.connect(self._on_job_failed)
        self.jobs.signals.lyricsReady.connect(self._on_lyrics_ready)

        self.takes_popover.exportTake.connect(self._export_take)
        self.takes_popover.playTake.connect(self._reveal_take)

        shortcuts = {
            "Space": self.toggle_play,
            "Ctrl+F": lambda: self.open_drawer("search"),
            "Ctrl+L": lambda: self.open_drawer("library"),
            "Ctrl+R": self.toggle_recording,
            "Left": lambda: self._nudge(-5),
            "Right": lambda: self._nudge(5),
            "Ctrl+Right": self.play_next,
            "Escape": self.close_drawer,
        }
        for keys, handler in shortcuts.items():
            QShortcut(QKeySequence(keys), self, activated=handler)

    def _apply_config(self) -> None:
        config = self.config
        self.engine.set_mic_count(int(config.get("mic_count", 2)))
        self.engine.set_vocals(float(config.get("vocals_volume", 0.18)))
        self.engine.set_instrumental(float(config.get("instrumental_volume", 0.85)))
        self.engine.set_master(float(config.get("master_volume", 0.80)))
        self.engine.ducking = bool(config.get("ducking", True))
        self.engine.gate_enabled = bool(config.get("gate", True))
        self.engine.monitor = float(config.get("monitor", 0.6)) * 2.0

        volumes = config.get("mic_volumes") or [0.7] * MAX_MICS
        muted = config.get("mic_muted") or [False, True, True, True]
        presets = config.get("mic_presets") or ["Studio", "Dry", "Dry", "Dry"]
        stored_fx = config.get("mic_fx")
        for index, strip in enumerate(self.engine.mics):
            strip.volume = float(volumes[index]) if index < len(volumes) else 0.7
            strip.muted = bool(muted[index]) if index < len(muted) else index > 0
            strip.set_preset(presets[index] if index < len(presets) else "Dry")
            if stored_fx and index < len(stored_fx) and stored_fx[index]:
                for key, value in stored_fx[index].items():
                    if key in FX_PARAMS:
                        strip.params[key] = value
                strip.apply_params()
                # Keep the label honest: saved knob positions win over the saved
                # preset name, so the name has to be re-derived from them.
                strip.preset = strip._match_preset()

        self._rebuild_strips()

    def _rebuild_strips(self) -> None:
        self.mixer.build_strips(self.engine.mic_count, {
            "vocals": self.engine.vocals.target,
            "instrumental": self.engine.instrumental.target,
            "master": self.engine.master.target,
            "mics": [strip.volume for strip in self.engine.mics],
            "mic_muted": [strip.muted for strip in self.engine.mics],
        })
        for strip in self.mixer.strips.values():
            strip.volumeChanged.connect(self._on_volume)
            strip.muteToggled.connect(self._on_mute)
            strip.fxRequested.connect(self._open_fx)
            strip.deviceRequested.connect(self._show_mic_menu)
        self._refresh_mic_labels()

    def _refresh_mic_labels(self) -> None:
        """Put the chosen device — and whether it opened — on each mic strip."""
        stored = self.config.get("mic_devices") or []
        for strip in self.mixer.mic_strips:
            name = stored[strip.index] if strip.index < len(stored) else None
            strip.set_device(name, self.engine.inputs[strip.index].active)

    def _show_mic_menu(self, index: int, position) -> None:
        """Device picker for one microphone, opened from its channel strip."""
        from PySide6.QtWidgets import QMenu

        current = (self.config.get("mic_devices") or [None] * MAX_MICS)
        current_name = current[index] if index < len(current) else None
        taken = {name for slot, name in enumerate(current[:self.engine.mic_count])
                 if name and slot != index}

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {theme.BG_RAISED}; padding: 6px;"
            f" border: 1px solid {theme.BORDER_STRONG}; border-radius: 10px; }}"
            f"QMenu::item {{ padding: 6px 26px 6px 14px; border-radius: 6px; }}"
            f"QMenu::item:selected {{ background: rgba(255,61,127,0.22);"
            f" color: {theme.PINK_LIGHT}; }}"
            f"QMenu::item:disabled {{ color: {theme.TEXT_GHOST}; }}")

        off = menu.addAction("Off")
        off.setCheckable(True)
        off.setChecked(current_name is None)
        off.triggered.connect(lambda: self._pick_mic(index, None))
        menu.addSeparator()

        devices = AudioDeviceManager.get_input_devices()
        if not devices:
            menu.addAction("No microphones found").setEnabled(False)
        for device in devices:
            action = menu.addAction(device["name"])
            action.setCheckable(True)
            action.setChecked(device["name"] == current_name)
            if device["name"] in taken:
                # Two channels on one capsule just doubles the same voice.
                action.setEnabled(False)
                action.setText(f"{device['name']}  (in use)")
            action.triggered.connect(
                lambda _=False, d=device["id"]: self._pick_mic(index, d))
        menu.exec(position)

    def _pick_mic(self, index: int, device_id) -> None:
        self._change_mic(index, device_id)
        self._refresh_mic_labels()

    def _start_audio(self) -> None:
        device = self._device_id(self.config.get("output_device"), output=True)
        if not self.engine.start_audio(device):
            self.engine.start_audio(None)
        self.engine.open_mics([
            self._device_id(name, output=False)
            for name in (self.config.get("mic_devices") or [None] * MAX_MICS)
        ])

    @staticmethod
    def _device_id(stored, output: bool):
        """Config stores device *names*; resolve to the current index."""
        if stored is None:
            return None
        if isinstance(stored, int):
            return stored
        devices = (AudioDeviceManager.get_output_devices() if output
                   else AudioDeviceManager.get_input_devices())
        for device in devices:
            if device["name"] == stored:
                return device["id"]
        return None

    # ------------------------------------------------------------------
    # Layout of the floating layers
    # ------------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        if event is not None:
            super().resizeEvent(event)
        root = self.centralWidget()
        if root is None:
            return
        self.drawer.setGeometry(0, 52, root.width(), max(0, root.height() - 52 - 76))
        self.takes_popover.adjustSize()
        self.takes_popover.move(
            max(0, root.width() - self.takes_popover.width() - 16),
            max(0, root.height() - 76 - self.takes_popover.height() - 10))

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def play_song(self, song_id: str) -> None:
        entry = self.library.get(song_id)
        if entry is None or not entry.has_stems:
            self._flash("That song is not ready yet.")
            return
        if song_id in self.queue:
            self.queue.remove(song_id)
            self._refresh_queue()

        self._loading_id = song_id
        self.now_title.setText(entry.title)
        self.now_artist.setText(entry.display_artist)
        self._set_source_badge(entry)
        self._flash(f"Loading “{entry.title}”…")
        self.jobs.pool.start(_LoadTask(self.engine, entry, self.load_signals))

    @Slot(str, float)
    def _on_song_loaded(self, song_id: str, duration: float) -> None:
        if self._loading_id != song_id:
            return
        self._loading_id = None
        entry = self.library.get(song_id)
        if entry is None:
            return
        self.current = entry
        self.current_lyrics = lyrics_api.load_cached(song_id)
        if self.current_lyrics is None and entry.media_path:
            self.current_lyrics = lyrics_api.load_sidecar(Path(entry.media_path))

        self.stage.set_song(entry, self.current_lyrics, duration)
        self._duration = duration
        # Songs migrated from the old app — and songs whose first lookup came
        # back empty — get another try now, in the background. The stage swaps
        # over if it finds something.
        if self.current_lyrics is None or entry.lyrics_state == LYRICS_UNKNOWN:
            self.jobs.resolve_lyrics(entry)

        self.engine.loop_in = self.engine.loop_out = None
        self.transport.set_marks(None, None, duration)
        self.engine.play()
        self.transport.set_playing(True)
        self.takes = []
        self.transport.set_takes(0)
        self.takes_popover.set_takes([])
        entry.play_count += 1
        self.library.put(entry)
        self.config.set("last_song", song_id)
        self.config.save()
        self.statusBar().clearMessage()

    @Slot(str, object)
    def _on_lyrics_ready(self, song_id: str, result) -> None:
        """A late lookup came back — swap the stage over if it is still the
        song on screen."""
        self.refresh_library()
        if self.current is None or self.current.id != song_id:
            return
        entry = self.library.get(song_id) or self.current
        self.current = entry
        self.current_lyrics = result
        self._set_source_badge(entry)
        if result is not None and result.found:
            self.stage.set_song(entry, result, self._duration)
            self._flash("Found lyrics for this song.")
        else:
            self.stage.set_song(entry, None, self._duration)

    @Slot(str, str)
    def _on_song_load_failed(self, song_id: str, message: str) -> None:
        self._flash(f"Could not load that song: {message}")
        self._loading_id = None

    def toggle_play(self) -> None:
        if not self.engine.loaded:
            self.open_drawer("search")
            return
        self.engine.toggle()
        self.transport.set_playing(self.engine.playing)

    def stop_playback(self) -> None:
        self.engine.stop()
        self.transport.set_playing(False)
        self.stage._index = -1

    def play_next(self) -> None:
        if self.queue:
            self.play_song(self.queue[0])

    def _on_seek(self, fraction: float) -> None:
        self.engine.seek(fraction * self.engine.duration)
        self.stage._index = -1          # force a lyric repaint at the new spot

    def _on_scrubbing(self, active: bool) -> None:
        self._scrubbing = active

    def _nudge(self, seconds: float) -> None:
        if self.engine.loaded:
            self.engine.seek(self.engine.position + seconds)
            self.stage._index = -1

    def _on_speed(self, direction: int) -> None:
        self.engine.set_speed(round(self.engine.speed + direction * 0.05, 2))
        self.transport.set_speed(self.engine.speed)

    def _on_key(self, direction: int) -> None:
        self.engine.set_key(self.engine.key + direction)
        self.transport.set_key(self.engine.key)

    def _mark_in(self) -> None:
        if self.engine.loop_in is not None:
            self.engine.loop_in = None
            self.engine.loop_out = None
        else:
            self.engine.loop_in = self.engine.position
        self.transport.set_marks(self.engine.loop_in, self.engine.loop_out,
                                 self.engine.duration)

    def _mark_out(self) -> None:
        if self.engine.loop_out is not None:
            self.engine.loop_out = None
        elif self.engine.loop_in is not None:
            self.engine.loop_out = max(self.engine.position, self.engine.loop_in + 1.0)
            self._flash("Looping between A and B.")
        else:
            self._flash("Set A first, then B.")
        self.transport.set_marks(self.engine.loop_in, self.engine.loop_out,
                                 self.engine.duration)

    # ------------------------------------------------------------------
    # Mixer
    # ------------------------------------------------------------------
    def _on_volume(self, kind: str, index: int, value: int) -> None:
        level = value / 100.0
        if kind == "stem" and index == 0:
            self.engine.set_vocals(level)
            self.config.set("vocals_volume", level)
        elif kind == "stem":
            self.engine.set_instrumental(level)
            self.config.set("instrumental_volume", level)
        elif kind == "master":
            self.engine.set_master(level)
            self.config.set("master_volume", level)
        elif kind == "mic":
            self.engine.mics[index].volume = level
            volumes = list(self.config.get("mic_volumes") or [0.7] * MAX_MICS)
            volumes[index] = level
            self.config.set("mic_volumes", volumes)

    def _on_mute(self, kind: str, index: int, muted: bool) -> None:
        if kind == "stem" and index == 0:
            self.engine.vocals_muted = muted
        elif kind == "stem":
            self.engine.instrumental_muted = muted
        elif kind == "mic":
            self.engine.mics[index].muted = muted
            stored = list(self.config.get("mic_muted") or [False] * MAX_MICS)
            stored[index] = muted
            self.config.set("mic_muted", stored)

    def _open_fx(self, index: int) -> None:
        strip = self.engine.mics[index]
        self.mixer.open_fx(index)
        self.mixer.show_mic_fx(index, f"Mic {index + 1}", strip.params, strip.preset)

    def _on_preset(self, index: int, name: str) -> None:
        strip = self.engine.mics[index]
        strip.set_preset(name)
        self.mixer.show_mic_fx(index, f"Mic {index + 1}", strip.params, strip.preset)
        self._save_fx()

    def _on_fx_param(self, index: int, key: str, value: int) -> None:
        self.engine.mics[index].set_param(key, value)
        self._save_fx()

    def _save_fx(self) -> None:
        self.config.set("mic_fx", [dict(strip.params) for strip in self.engine.mics])
        self.config.set("mic_presets", [strip.preset for strip in self.engine.mics])

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def toggle_recording(self) -> None:
        if not self.engine.loaded:
            self._flash("Load a song before recording.")
            return
        if self.engine.recording:
            name = (self.current.title if self.current else "take")
            name = "".join(c for c in name if c not in '<>:"/\\|?*')[:40] or "take"
            path = RECORDINGS_DIR / f"{name} - Take {len(self.takes) + 1}.wav"
            take = self.engine.stop_recording(path)
            self.stage.rec_pill.setVisible(False)
            self.transport.set_recording(False)
            if take:
                self.takes.append(take)
                self.transport.set_takes(len(self.takes))
                self.takes_popover.set_takes(self.takes)
                self._flash(f"Take saved: {path.name}")
            else:
                self._flash("Nothing was captured for that take.")
        else:
            self.engine.start_recording()
            self.stage.rec_pill.setVisible(True)
            self.stage.rec_pill.raise_()
            self.transport.set_recording(True)

    def toggle_takes(self) -> None:
        self.takes_popover.setVisible(not self.takes_popover.isVisible())
        if self.takes_popover.isVisible():
            self.takes_popover.raise_()
            self.resizeEvent(None)

    def _export_take(self, path: str) -> None:
        import shutil
        from PySide6.QtWidgets import QFileDialog
        target, _ = QFileDialog.getSaveFileName(
            self, "Export take", str(Path.home() / Path(path).name), "WAV (*.wav)")
        if target:
            shutil.copyfile(path, target)
            self._flash(f"Exported to {Path(target).name}")

    def _reveal_take(self, path: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------
    # Drawer, search and jobs
    # ------------------------------------------------------------------
    def open_drawer(self, tab: str = "search") -> None:
        self.refresh_library()
        self.drawer.setVisible(True)
        self.drawer.raise_()
        self.drawer.show_tab(tab)
        self.resizeEvent(None)

    def close_drawer(self) -> None:
        self.drawer.setVisible(False)

    def refresh_library(self) -> None:
        self.drawer.set_library([e for e in self.library.all() if e.has_stems])

    @Slot(str, list)
    def _on_search_done(self, query: str, results: List[SearchResult]) -> None:
        index = {entry.id: entry for entry in self.library.all()}
        self.drawer.set_results(results, index)
        # Re-apply the state of anything already being prepared.
        for info in self._active_jobs.values():
            card = self.drawer.card_for(info["video_id"])
            if card is not None:
                card.set_busy(info["stage"], info["fraction"], info["label"])

    @Slot(str, str)
    def _on_search_failed(self, query: str, message: str) -> None:
        self.drawer.results_hint.setText(f"Search failed: {message[:60]}")
        self.drawer.results_hint.setVisible(True)

    def prepare_song(self, item: SearchResult) -> None:
        if self.jobs.job_for(item.video_id):
            return
        job_id = self.jobs.prepare(item)
        self._active_jobs[job_id] = {
            "video_id": item.video_id, "title": item.title,
            "stage": STAGE_LYRICS, "fraction": 0.0, "label": "Finding lyrics",
        }

    def import_file(self, path: str) -> None:
        job_id = self.jobs.import_file(Path(path))
        self._active_jobs[job_id] = {
            "video_id": "", "title": Path(path).name,
            "stage": STAGE_SEPARATE, "fraction": 0.0, "label": "Preparing",
        }
        self._flash(f"Importing {Path(path).name} in the background…")

    @Slot(str, str, float, str)
    def _on_job_progress(self, job_id: str, stage: str, fraction: float,
                         text: str) -> None:
        info = self._active_jobs.get(job_id)
        if info is None:
            return
        info.update(stage=stage, fraction=fraction, label=text)
        card = self.drawer.card_for(info["video_id"]) if info["video_id"] else None
        if card is not None:
            if stage == STAGE_READY:
                card.set_ready(self.library.get(info["video_id"]))
            else:
                card.set_busy(stage, fraction, text)

    @Slot(str, object)
    def _on_job_finished(self, job_id: str, entry: SongEntry) -> None:
        self._active_jobs.pop(job_id, None)
        self.refresh_library()
        card = self.drawer.card_for(entry.id)
        if card is not None:
            card.set_ready(entry)
        note = {"synced": "with synced lyrics",
                "plain": "with lyrics (timing estimated)"}.get(
                    entry.lyrics_state, "— no lyrics found, the video will play")
        self._flash(f"“{entry.title}” is ready {note}")
        if not self.engine.loaded and self._loading_id is None:
            self.play_song(entry.id)

    @Slot(str, str)
    def _on_job_failed(self, job_id: str, message: str) -> None:
        info = self._active_jobs.pop(job_id, None)
        if info is None or message == "Cancelled":
            return
        card = self.drawer.card_for(info["video_id"]) if info["video_id"] else None
        if card is not None:
            card.set_failed(message)
        self._flash(f"Could not prepare “{info['title'][:40]}”: {message[:70]}")

    # ------------------------------------------------------------------
    # Queue and library
    # ------------------------------------------------------------------
    def add_to_queue(self, song_id: str) -> None:
        entry = self.library.get(song_id)
        if entry is None or not entry.has_stems:
            self._flash("Still preparing that one — it can be queued once ready.")
            return
        if song_id not in self.queue:
            self.queue.append(song_id)
            self._refresh_queue()
            self._flash(f"Queued “{entry.title}”")

    def remove_from_queue(self, song_id: str) -> None:
        if song_id in self.queue:
            self.queue.remove(song_id)
            self._refresh_queue()

    def remove_from_library(self, song_id: str) -> None:
        entry = self.library.get(song_id)
        if entry is None:
            return
        answer = QMessageBox.question(
            self, "Remove song",
            f"Remove “{entry.title}” from the library?\n"
            "The downloaded file and its stems stay on disk.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.library.remove(song_id)
        self.remove_from_queue(song_id)
        self.refresh_library()

    def _refresh_queue(self) -> None:
        entries = [self.library.get(song_id) for song_id in self.queue]
        self.mixer.set_queue([e for e in entries if e is not None])

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def open_settings(self) -> None:
        dialog = SettingsDialog(AudioDeviceManager.get_output_devices(),
                                AudioDeviceManager.get_input_devices(), self)
        dialog.load(self.config)
        dialog.outputChanged.connect(self._change_output)
        dialog.micCountChanged.connect(self._change_mic_count)
        dialog.duckingChanged.connect(self._change_ducking)
        dialog.gateChanged.connect(self._change_gate)
        dialog.monitorChanged.connect(self._change_monitor)
        dialog.exec()
        self.config.save()
        self._refresh_mic_labels()

    def _device_name(self, device_id, output: bool) -> Optional[str]:
        if device_id is None:
            return None
        devices = (AudioDeviceManager.get_output_devices() if output
                   else AudioDeviceManager.get_input_devices())
        for device in devices:
            if device["id"] == device_id:
                return device["name"]
        return None

    def _mic_device_ids(self) -> List[Optional[int]]:
        stored = self.config.get("mic_devices") or [None] * MAX_MICS
        return [self._device_id(name, output=False) for name in stored]

    def _change_output(self, device_id) -> None:
        self.config.set("output_device", self._device_name(device_id, True))
        was_playing = self.engine.playing
        position = self.engine.position
        self.engine.pause()
        if not self.engine.start_audio(device_id):
            self._flash("That output device could not be opened.")
            self.engine.start_audio(None)
        self.engine.open_mics(self._mic_device_ids())
        if self.engine.loaded:
            self.engine.seek(position)
            if was_playing:
                self.engine.play()

    def _change_mic(self, slot: int, device_id) -> None:
        devices = list(self.config.get("mic_devices") or [])
        while len(devices) < MAX_MICS:
            devices.append(None)
        devices[slot] = self._device_name(device_id, False)
        self.config.set("mic_devices", devices)
        if not self.engine.inputs[slot].open(device_id) and device_id is not None:
            self._flash(f"Mic {slot + 1} could not be opened: "
                        f"{self.engine.inputs[slot].error[:60]}")

    def _change_mic_count(self, count: int) -> None:
        if count == self.engine.mic_count:
            return
        self.engine.set_mic_count(count)
        self.config.set("mic_count", count)
        self.engine.open_mics(self._mic_device_ids())
        self._rebuild_strips()

    def _change_ducking(self, enabled: bool) -> None:
        self.engine.ducking = enabled
        self.config.set("ducking", enabled)

    def _change_gate(self, enabled: bool) -> None:
        self.engine.gate_enabled = enabled
        self.config.set("gate", enabled)

    def _change_monitor(self, value: int) -> None:
        self.engine.monitor = value / 100.0 * 2.0
        self.config.set("monitor", value / 100.0)

    # ------------------------------------------------------------------
    # Frame loop
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        engine = self.engine
        position = engine.position
        if not self._scrubbing:
            self.transport.set_time(position, engine.duration)
        self.stage.tick(position, engine.playing, engine.speed)

        for strip in self.mixer.mic_strips:
            strip.set_level(engine.mic_peak(strip.index))

        if engine.recording:
            self.stage.rec_pill.set_state(engine.recording_duration, engine.ducking)

        if engine.finished and engine.loaded:
            engine._finished = False
            if self.queue:
                self.play_next()
            else:
                self.transport.set_playing(False)

        self._update_toast()

    def _tick_slow(self) -> None:
        latency = self.engine._output_latency * 1000
        self.mixer.set_status(
            f"{self.engine.sample_rate / 1000:.1f} kHz · {latency:.1f} ms")

    def _update_toast(self) -> None:
        """The stage's corner toast mirrors what the drawer is not showing."""
        if self.drawer.isVisible() or not self._active_jobs:
            if self.stage.toast.isVisible():
                self.stage.toast.setVisible(False)
            return
        job = next(iter(self._active_jobs.values()))
        self.stage.toast.show_job(job["title"], job["fraction"], job["label"],
                                  STAGE_COLORS.get(job["stage"], theme.BLUE))
        if not self.stage.toast.isVisible():
            self.stage.toast.setVisible(True)
            self.stage.toast.raise_()

    def _set_source_badge(self, entry: SongEntry) -> None:
        text, color = {
            "synced": ("● Synced lyrics", theme.GREEN),
            "plain": ("● Lyrics", theme.BLUE),
        }.get(entry.lyrics_state, ("● YouTube video", theme.RED_LIGHT))
        self.now_badge.setText(text)
        self.now_badge.set_color(color)
        self.now_badge.setVisible(True)
        self.now_badge.adjustSize()

    def _flash(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)

    def _restore_last_song(self) -> None:
        last = self.config.get("last_song")
        entry = self.library.get(last) if last else None
        if entry is None or not entry.has_stems:
            self.open_drawer("search")
            return
        self.play_song(entry.id)

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        self._frame_timer.stop()
        self._slow_timer.stop()
        self._save_fx()
        self.config.save()
        self.jobs.shutdown()
        self.engine.cleanup()
        super().closeEvent(event)
