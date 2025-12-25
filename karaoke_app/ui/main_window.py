"""
Main Window UI for Karaoke Separation App
"""
import logging
import json
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QFileDialog, QMessageBox, QProgressDialog,
    QGroupBox, QCheckBox, QSizePolicy, QFrame, QMenuBar, QMenu,
    QInputDialog, QLineEdit, QComboBox, QStackedWidget
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, Slot
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtGui import QAction

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from audio.separation import SeparationEngine
from audio.playback import StemPlayer
from audio.youtube_downloader import YouTubeDownloader
from audio.device_manager import AudioDeviceManager
from audio.video_converter import VideoConverter
from ui.components.notification_toast import NotificationToast
from ui.components.side_panel import SidePanel
from ui.components.youtube_browser import YouTubeBrowser


logger = logging.getLogger(__name__)


class ModelPreloadWorker(QThread):
    """Worker thread to preload AI model in background."""

    finished = Signal()
    error = Signal(str)

    def __init__(self, separation_engine: SeparationEngine):
        super().__init__()
        self.separation_engine = separation_engine

    def run(self):
        """Preload the model in background."""
        try:
            self.separation_engine.preload_model()
            self.finished.emit()
        except Exception as e:
            logger.error(f"Model preload failed: {str(e)}")
            self.error.emit(str(e))


class YouTubeDownloadWorker(QThread):
    """Worker thread for YouTube downloads."""

    progress = Signal(int, str)
    finished = Signal(Path, bool, str)  # file_path, was_cached, title
    error = Signal(str)

    def __init__(self, youtube_downloader: YouTubeDownloader, url: str):
        super().__init__()
        self.youtube_downloader = youtube_downloader
        self.url = url

    def run(self):
        """Download from YouTube in background."""
        try:
            file_path, was_cached, title = self.youtube_downloader.download(
                self.url,
                progress_callback=self._on_progress
            )
            self.finished.emit(file_path, was_cached, title)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, percentage: int, message: str):
        """Progress callback from downloader."""
        self.progress.emit(percentage, message)


class SeparationWorker(QThread):
    """Worker thread for audio separation to avoid blocking the UI."""

    progress = Signal(int, str)  # progress percentage, message
    finished = Signal(Path, Path)  # vocals_path, instrumental_path
    error = Signal(str)  # error message

    def __init__(self, separation_engine: SeparationEngine, file_path: Path):
        super().__init__()
        self.separation_engine = separation_engine
        self.file_path = file_path

    def run(self):
        """Run the separation in a background thread."""
        try:
            vocals_path, instrumental_path = self.separation_engine.separate(
                self.file_path,
                progress_callback=self._on_progress
            )
            self.finished.emit(vocals_path, instrumental_path)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, percentage: int, message: str):
        """Progress callback from separation engine."""
        self.progress.emit(percentage, message)


class VideoConversionWorker(QThread):
    """Worker thread for video conversion to avoid blocking the UI."""

    progress = Signal(int, str)  # progress percentage, message
    finished = Signal(Path)  # converted_path
    error = Signal(str)  # error message

    def __init__(self, video_converter, file_path: Path):
        super().__init__()
        self.video_converter = video_converter
        self.file_path = file_path

    def run(self):
        """Run the conversion in a background thread."""
        try:
            converted_path, was_converted = self.video_converter.convert(
                self.file_path,
                progress_callback=self._on_progress
            )
            self.finished.emit(converted_path)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, percentage: int, message: str):
        """Progress callback from converter."""
        self.progress.emit(percentage, message)

class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # Initialize components
        self.app_dir = Path(__file__).parent.parent
        self.settings_file = self.app_dir / "settings" / "app_settings.json"
        self.current_file: Optional[Path] = None
        self.current_settings = {}

        # Initialize separation engine
        self.separation_engine = SeparationEngine(self.app_dir / "stems_cache")

        # Initialize YouTube downloader
        self.youtube_downloader = YouTubeDownloader(self.app_dir / "downloads")

        # Initialize stem player with recordings directory
        self.stem_player = StemPlayer(recordings_dir=self.app_dir / "recordings")
        self.stem_player.position_callback = self._on_playback_position_changed

        # Initialize video converter for AV1/VP9 compatibility
        self.video_converter = VideoConverter(self.app_dir / "converted")

        # Initialize video player (for video files)
        # Note: Video may not work if QtMultimedia backends are not available
        self.video_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        try:
            self.video_player.setAudioOutput(self.audio_output)
            # Connect error signal to handle playback errors
            self.video_player.errorOccurred.connect(self._on_video_error)
        except Exception as e:
            logger.warning(f"Video player initialization warning: {e}")
            logger.info("Video playback may not be available, but audio-only mode will work")

        # Worker thread for separation
        self.separation_worker: Optional[SeparationWorker] = None

        # UI components (initialized in setup_ui)
        self.video_widget: Optional[QVideoWidget] = None
        self.placeholder_label: Optional[QLabel] = None
        self.status_label: Optional[QLabel] = None
        self.play_button: Optional[QPushButton] = None
        self.pause_button: Optional[QPushButton] = None
        self.stop_button: Optional[QPushButton] = None
        self.seek_slider: Optional[QSlider] = None
        self.time_label: Optional[QLabel] = None
        self.vocals_slider: Optional[QSlider] = None
        self.instrumental_slider: Optional[QSlider] = None
        self.vocals_mute_checkbox: Optional[QCheckBox] = None
        self.instrumental_mute_checkbox: Optional[QCheckBox] = None
        self.side_panel: Optional[SidePanel] = None
        self.notification_toast: Optional[NotificationToast] = None
        
        # Microphone UI components
        self.mic_device_combo: Optional[QComboBox] = None
        self.mic_slider: Optional[QSlider] = None
        self.mic_mute_checkbox: Optional[QCheckBox] = None
        self.mic_enable_checkbox: Optional[QCheckBox] = None
        self.reverb_slider: Optional[QSlider] = None
        self.echo_slider: Optional[QSlider] = None
        self.effects_checkbox: Optional[QCheckBox] = None
        self.record_button: Optional[QPushButton] = None
        self.recording_label: Optional[QLabel] = None
        self.recording_timer: Optional[QTimer] = None

        # Position update timer
        self.position_timer = QTimer()
        self.position_timer.timeout.connect(self._update_video_position)
        self.position_timer.setInterval(100)  # Update every 100ms

        # Setup UI
        self.setup_ui()
        self.setup_menu()
        self.load_settings()
        self._refresh_history()

        # Preload AI model in background
        self.model_preload_worker = ModelPreloadWorker(self.separation_engine)
        self.model_preload_worker.finished.connect(self._on_model_preloaded)
        self.model_preload_worker.error.connect(self._on_model_preload_error)
        self.model_preload_worker.start()

        logger.info("MainWindow initialized - AI model loading in background...")

    def setup_ui(self):
        """Setup the user interface."""
        self.setWindowTitle("Karaoke Separation Studio")
        self.setMinimumSize(1200, 800)

        # Load stylesheet
        self._load_stylesheet()

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main horizontal layout (content + side panel)
        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Main content container
        content_container = QWidget()
        main_layout = QVBoxLayout(content_container)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Status bar at top
        self.status_label = QLabel("Loading AI model...")
        self.status_label.setObjectName("statusLabel")
        main_layout.addWidget(self.status_label)

        # Content area (video + controls)
        content_layout = QHBoxLayout()

        # Left side: Video/visualization area
        video_container = QVBoxLayout()

        # Video widget (for video files)
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(640, 480)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setStyleSheet("background-color: black;")
        self.video_player.setVideoOutput(self.video_widget)

        # Placeholder (for audio-only files)
        self.placeholder_label = QLabel("🎵\n\nKARAOKE STUDIO\n\nSelect a song to begin")
        self.placeholder_label.setObjectName("placeholderLabel")
        self.placeholder_label.setAlignment(Qt.AlignCenter)
        self.placeholder_label.setMinimumSize(640, 480)

        # Stack video and placeholder (show one at a time)
        video_container.addWidget(self.placeholder_label)
        video_container.addWidget(self.video_widget)
        self.video_widget.hide()

        content_layout.addLayout(video_container, stretch=3)

        # Right side: Mixer controls
        mixer_layout = self._create_mixer_panel()
        content_layout.addLayout(mixer_layout, stretch=1)

        main_layout.addLayout(content_layout)

        # Bottom: Transport controls
        transport_layout = self._create_transport_controls()
        main_layout.addLayout(transport_layout)

        root_layout.addWidget(content_container, stretch=1)

        # Side panel (right side)
        self.side_panel = SidePanel(self)
        self.side_panel.history_item_selected.connect(self._on_history_item_selected)
        self.side_panel.history_item_removed.connect(self._on_history_item_removed)
        self.side_panel.queue_item_selected.connect(self._on_queue_item_selected)
        root_layout.addWidget(self.side_panel)

        # Notification toast (overlay)
        self.notification_toast = NotificationToast(self)

        # Create stacked widget for switching between player and browser
        self.main_stack = QStackedWidget()
        
        # Player view (index 0)
        self.player_container = QWidget()
        player_layout = QVBoxLayout(self.player_container)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.addWidget(central_widget)
        self.main_stack.addWidget(self.player_container)
        
        # YouTube browser view (index 1)
        self.youtube_browser = YouTubeBrowser()
        self.youtube_browser.download_requested.connect(self._on_browser_download_requested)
        self.youtube_browser.close_requested.connect(self._show_player_view)
        self.main_stack.addWidget(self.youtube_browser)
        
        # Set stacked widget as central widget
        self.setCentralWidget(self.main_stack)
        self.main_stack.setCurrentIndex(0)  # Start with player view

        # Set initial state
        self._set_controls_enabled(False)

    def _load_stylesheet(self):
        """Load the application stylesheet."""
        try:
            style_path = Path(__file__).parent / "styles" / "dark_gradient_theme.qss"
            if style_path.exists():
                with open(style_path, 'r', encoding='utf-8') as f:
                    stylesheet = f.read()
                self.setStyleSheet(stylesheet)
                logger.info("Dark gradient theme loaded")
            else:
                logger.warning(f"Stylesheet not found: {style_path}")
        except Exception as e:
            logger.error(f"Failed to load stylesheet: {e}")

    def setup_menu(self):
        """Setup menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        open_action = QAction("&Open Song...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")

        regenerate_action = QAction("&Re-generate Stems", self)
        regenerate_action.triggered.connect(self.regenerate_stems)
        tools_menu.addAction(regenerate_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _create_mixer_panel(self) -> QVBoxLayout:
        """Create the mixer control panel."""
        layout = QVBoxLayout()

        # Mixer group box
        mixer_group = QGroupBox("Mixer Controls")
        mixer_group.setStyleSheet("""
            QGroupBox {
                font-size: 11pt;
                font-weight: bold;
                border: 2px solid #3498db;
                border-radius: 5px;
                margin-top: 10px;
                padding: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)

        mixer_layout = QVBoxLayout()

        # Vocals control
        vocals_layout = QVBoxLayout()
        vocals_label = QLabel("🎤 VOCALS")
        vocals_label.setAlignment(Qt.AlignCenter)
        vocals_label.setStyleSheet("font-size: 10pt; font-weight: bold; color: #e74c3c;")
        vocals_layout.addWidget(vocals_label)

        self.vocals_slider = QSlider(Qt.Vertical)
        self.vocals_slider.setMinimum(0)
        self.vocals_slider.setMaximum(100)
        self.vocals_slider.setValue(100)
        self.vocals_slider.setTickPosition(QSlider.TicksLeft)
        self.vocals_slider.setTickInterval(10)
        self.vocals_slider.setMinimumHeight(200)
        self.vocals_slider.valueChanged.connect(self._on_vocals_volume_changed)
        vocals_layout.addWidget(self.vocals_slider, alignment=Qt.AlignCenter)

        self.vocals_value_label = QLabel("100%")
        self.vocals_value_label.setAlignment(Qt.AlignCenter)
        vocals_layout.addWidget(self.vocals_value_label)

        self.vocals_mute_checkbox = QCheckBox("Mute")
        self.vocals_mute_checkbox.stateChanged.connect(self._on_vocals_mute_changed)
        vocals_layout.addWidget(self.vocals_mute_checkbox)

        vocals_solo_button = QPushButton("Solo")
        vocals_solo_button.clicked.connect(self._on_vocals_solo)
        vocals_layout.addWidget(vocals_solo_button)

        # Instrumental control
        instrumental_layout = QVBoxLayout()
        instrumental_label = QLabel("🎸 INSTRUMENTAL")
        instrumental_label.setAlignment(Qt.AlignCenter)
        instrumental_label.setStyleSheet("font-size: 10pt; font-weight: bold; color: #27ae60;")
        instrumental_layout.addWidget(instrumental_label)

        self.instrumental_slider = QSlider(Qt.Vertical)
        self.instrumental_slider.setMinimum(0)
        self.instrumental_slider.setMaximum(100)
        self.instrumental_slider.setValue(100)
        self.instrumental_slider.setTickPosition(QSlider.TicksRight)
        self.instrumental_slider.setTickInterval(10)
        self.instrumental_slider.setMinimumHeight(200)
        self.instrumental_slider.valueChanged.connect(self._on_instrumental_volume_changed)
        instrumental_layout.addWidget(self.instrumental_slider, alignment=Qt.AlignCenter)

        self.instrumental_value_label = QLabel("100%")
        self.instrumental_value_label.setAlignment(Qt.AlignCenter)
        instrumental_layout.addWidget(self.instrumental_value_label)

        self.instrumental_mute_checkbox = QCheckBox("Mute")
        self.instrumental_mute_checkbox.stateChanged.connect(self._on_instrumental_mute_changed)
        instrumental_layout.addWidget(self.instrumental_mute_checkbox)

        instrumental_solo_button = QPushButton("Solo")
        instrumental_solo_button.clicked.connect(self._on_instrumental_solo)
        instrumental_layout.addWidget(instrumental_solo_button)

        # Microphone control
        mic_layout = QVBoxLayout()
        mic_label = QLabel("🎙️ MICROPHONE")
        mic_label.setAlignment(Qt.AlignCenter)
        mic_label.setStyleSheet("font-size: 10pt; font-weight: bold; color: #9b59b6;")
        mic_layout.addWidget(mic_label)

        self.mic_slider = QSlider(Qt.Vertical)
        self.mic_slider.setMinimum(0)
        self.mic_slider.setMaximum(100)
        self.mic_slider.setValue(70)
        self.mic_slider.setTickPosition(QSlider.TicksRight)
        self.mic_slider.setTickInterval(10)
        self.mic_slider.setMinimumHeight(200)
        self.mic_slider.valueChanged.connect(self._on_mic_volume_changed)
        mic_layout.addWidget(self.mic_slider, alignment=Qt.AlignCenter)

        self.mic_value_label = QLabel("70%")
        self.mic_value_label.setAlignment(Qt.AlignCenter)
        mic_layout.addWidget(self.mic_value_label)

        self.mic_mute_checkbox = QCheckBox("Mute")
        self.mic_mute_checkbox.stateChanged.connect(self._on_mic_mute_changed)
        mic_layout.addWidget(self.mic_mute_checkbox)

        self.mic_enable_checkbox = QCheckBox("Enable")
        self.mic_enable_checkbox.stateChanged.connect(self._on_mic_enable_changed)
        mic_layout.addWidget(self.mic_enable_checkbox)

        # Combine vocals, instrumental, and microphone side by side
        sliders_layout = QHBoxLayout()
        sliders_layout.addLayout(vocals_layout)
        sliders_layout.addLayout(instrumental_layout)
        sliders_layout.addLayout(mic_layout)
        mixer_layout.addLayout(sliders_layout)

        # Microphone device selector
        mic_device_layout = QHBoxLayout()
        mic_device_layout.addWidget(QLabel("Mic:"))
        self.mic_device_combo = QComboBox()
        self.mic_device_combo.setMinimumWidth(200)
        self.mic_device_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._refresh_mic_devices()
        self.mic_device_combo.currentIndexChanged.connect(self._on_mic_device_changed)
        mic_device_layout.addWidget(self.mic_device_combo, stretch=1)
        mixer_layout.addLayout(mic_device_layout)

        # Voice effects controls
        effects_group = QGroupBox("Voice Effects")
        effects_group.setStyleSheet("""
            QGroupBox {
                font-size: 9pt;
                font-weight: bold;
                border: 1px solid #9b59b6;
                border-radius: 3px;
                margin-top: 8px;
                padding: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 5px;
            }
        """)
        effects_layout = QVBoxLayout()

        self.effects_checkbox = QCheckBox("Enable Effects")
        self.effects_checkbox.setChecked(True)
        self.effects_checkbox.stateChanged.connect(self._on_effects_enable_changed)
        effects_layout.addWidget(self.effects_checkbox)

        # Reverb slider
        reverb_layout = QHBoxLayout()
        reverb_layout.addWidget(QLabel("Reverb:"))
        self.reverb_slider = QSlider(Qt.Horizontal)
        self.reverb_slider.setMinimum(0)
        self.reverb_slider.setMaximum(100)
        self.reverb_slider.setValue(30)
        self.reverb_slider.valueChanged.connect(self._on_reverb_changed)
        reverb_layout.addWidget(self.reverb_slider)
        self.reverb_value_label = QLabel("30%")
        self.reverb_value_label.setMinimumWidth(35)
        reverb_layout.addWidget(self.reverb_value_label)
        effects_layout.addLayout(reverb_layout)

        # Echo slider
        echo_layout = QHBoxLayout()
        echo_layout.addWidget(QLabel("Echo:"))
        self.echo_slider = QSlider(Qt.Horizontal)
        self.echo_slider.setMinimum(0)
        self.echo_slider.setMaximum(100)
        self.echo_slider.setValue(30)
        self.echo_slider.valueChanged.connect(self._on_echo_changed)
        echo_layout.addWidget(self.echo_slider)
        self.echo_value_label = QLabel("30%")
        self.echo_value_label.setMinimumWidth(35)
        echo_layout.addWidget(self.echo_value_label)
        effects_layout.addLayout(echo_layout)

        effects_group.setLayout(effects_layout)
        mixer_layout.addWidget(effects_group)

        # Reset button
        reset_button = QPushButton("Reset Mix")
        reset_button.clicked.connect(self._on_reset_mix)
        reset_button.setStyleSheet("""
            QPushButton {
                background-color: #95a5a6;
                color: white;
                font-weight: bold;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #7f8c8d;
            }
        """)
        mixer_layout.addWidget(reset_button)

        mixer_group.setLayout(mixer_layout)
        layout.addWidget(mixer_group)
        layout.addStretch()

        return layout

    def _create_transport_controls(self) -> QVBoxLayout:
        """Create transport control panel."""
        layout = QVBoxLayout()

        # Seek slider
        seek_layout = QHBoxLayout()
        seek_layout.addWidget(QLabel("Position:"))

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setMinimum(0)
        self.seek_slider.setMaximum(1000)
        self.seek_slider.sliderMoved.connect(self._on_seek_slider_moved)
        seek_layout.addWidget(self.seek_slider)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(120)
        seek_layout.addWidget(self.time_label)

        layout.addLayout(seek_layout)

        # Transport buttons
        buttons_layout = QHBoxLayout()

        # Open button (big, prominent)
        open_button = QPushButton("📁 SELECT SONG")
        open_button.setObjectName("selectSongButton")
        open_button.clicked.connect(self.open_file)
        buttons_layout.addWidget(open_button)

        # YouTube link button
        youtube_button = QPushButton("🎬 PASTE LINK")
        youtube_button.setObjectName("youtubeButton")
        youtube_button.clicked.connect(self.open_youtube_link)
        buttons_layout.addWidget(youtube_button)

        # Browse YouTube button
        browse_youtube_btn = QPushButton("🌐 BROWSE YOUTUBE")
        browse_youtube_btn.setObjectName("selectSongButton")  # Green style
        browse_youtube_btn.clicked.connect(self._show_browser_view)
        buttons_layout.addWidget(browse_youtube_btn)

        buttons_layout.addStretch()

        # Play button
        self.play_button = QPushButton("▶ Play")
        self.play_button.setObjectName("playButton")
        self.play_button.clicked.connect(self._on_play)
        buttons_layout.addWidget(self.play_button)

        # Pause button
        self.pause_button = QPushButton("⏸ Pause")
        self.pause_button.setObjectName("pauseButton")
        self.pause_button.clicked.connect(self._on_pause)
        buttons_layout.addWidget(self.pause_button)

        # Stop button
        self.stop_button = QPushButton("⏹ Stop")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.clicked.connect(self._on_stop)
        buttons_layout.addWidget(self.stop_button)

        buttons_layout.addStretch()

        # Recording controls
        self.record_button = QPushButton("● REC")
        self.record_button.setCheckable(True)
        self.record_button.clicked.connect(self._on_record_toggle)
        self.record_button.setStyleSheet("""
            QPushButton {
                background-color: #7f8c8d;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                font-size: 11pt;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #6c7a7d;
            }
            QPushButton:checked {
                background-color: #e74c3c;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """)
        buttons_layout.addWidget(self.record_button)

        self.recording_label = QLabel("00:00")
        self.recording_label.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 11pt;")
        self.recording_label.setVisible(False)
        buttons_layout.addWidget(self.recording_label)

        # Recording timer for updating display
        self.recording_timer = QTimer()
        self.recording_timer.timeout.connect(self._update_recording_time)
        self.recording_timer.setInterval(1000)

        layout.addLayout(buttons_layout)

        return layout

    def _set_controls_enabled(self, enabled: bool):
        """Enable or disable playback controls."""
        self.play_button.setEnabled(enabled)
        self.pause_button.setEnabled(enabled)
        self.stop_button.setEnabled(enabled)
        self.seek_slider.setEnabled(enabled)
        self.vocals_slider.setEnabled(enabled)
        self.instrumental_slider.setEnabled(enabled)
        self.vocals_mute_checkbox.setEnabled(enabled)
        self.instrumental_mute_checkbox.setEnabled(enabled)

    @Slot()
    def open_file(self):
        """Open file dialog to select a song."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Song",
            "",
            "Audio/Video Files (*.mp3 *.wav *.flac *.mp4 *.mkv *.avi);;All Files (*.*)"
        )

        if file_path:
            self.load_file(Path(file_path))

    @Slot()
    def open_youtube_link(self):
        """Open dialog to enter YouTube link."""
        url, ok = QInputDialog.getText(
            self,
            "YouTube Download",
            "Enter YouTube URL:\n(e.g., https://www.youtube.com/watch?v=...)",
            QLineEdit.Normal,
            ""
        )

        if ok and url:
            url = url.strip()
            if not self.youtube_downloader.is_youtube_url(url):
                QMessageBox.warning(
                    self,
                    "Invalid URL",
                    "Please enter a valid YouTube URL."
                )
                return

            self._start_youtube_download(url)

    def _start_youtube_download(self, url: str):
        """Start YouTube download in background."""
        # Create progress dialog
        progress_dialog = QProgressDialog(
            "Downloading from YouTube...",
            "Cancel",
            0,
            100,
            self
        )
        progress_dialog.setWindowTitle("YouTube Download")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setValue(0)

        # Create worker thread
        self.youtube_worker = YouTubeDownloadWorker(self.youtube_downloader, url)

        # Connect signals
        self.youtube_worker.progress.connect(
            lambda percentage, message: self._on_youtube_progress(progress_dialog, percentage, message)
        )
        self.youtube_worker.finished.connect(
            lambda file_path, was_cached, title: self._on_youtube_finished(progress_dialog, file_path, was_cached, title)
        )
        self.youtube_worker.error.connect(
            lambda error: self._on_youtube_error(progress_dialog, error)
        )

        # Allow cancellation
        progress_dialog.canceled.connect(self.youtube_worker.terminate)

        # Start download
        self.youtube_worker.start()

    @Slot(QProgressDialog, int, str)
    def _on_youtube_progress(self, dialog: QProgressDialog, percentage: int, message: str):
        """Handle YouTube download progress."""
        dialog.setValue(percentage)
        dialog.setLabelText(f"{message}")
        self.status_label.setText(f"Downloading: {message}")

    @Slot(QProgressDialog, Path, bool, str)
    def _on_youtube_finished(self, dialog: QProgressDialog, file_path: Path, was_cached: bool, title: str):
        """Handle YouTube download completion."""
        dialog.close()
        
        if was_cached:
            # Show notification for cached file
            self.notification_toast.show_message(
                f"Using cached: {title}",
                duration=3000,
                style="info"
            )
            self.status_label.setText(f"Loaded from cache: {title}")
            logger.info(f"Using cached YouTube download: {file_path}")
        else:
            self.status_label.setText("Download complete! Loading file...")
            logger.info(f"YouTube download finished: {file_path}")
        
        # Refresh history in side panel
        self._refresh_history()
        
        # Load the downloaded file
        self.load_file(file_path)

    @Slot(QProgressDialog, str)
    def _on_youtube_error(self, dialog: QProgressDialog, error: str):
        """Handle YouTube download error."""
        dialog.close()
        QMessageBox.critical(
            self,
            "Download Failed",
            f"Failed to download from YouTube:\n{error}"
        )
        self.status_label.setText("Download failed")

    # ===== Browser View Switching =====

    def _show_browser_view(self):
        """Switch to YouTube browser view."""
        self.main_stack.setCurrentIndex(1)
        logger.info("Switched to YouTube browser view")

    def _show_player_view(self):
        """Switch back to player view."""
        self.main_stack.setCurrentIndex(0)
        logger.info("Switched to player view")

    @Slot(str, str)
    def _on_browser_download_requested(self, url: str, title: str):
        """Handle download request from embedded browser."""
        logger.info(f"Browser download requested: {title} ({url})")
        
        # Switch back to player view
        self._show_player_view()
        
        # Start the download using existing flow
        self._start_youtube_download(url)

    def load_file(self, file_path: Path):
        """
        Load a song file and start separation if needed.

        Args:
            file_path: Path to the audio/video file
        """
        try:
            self.current_file = file_path
            self.status_label.setText(f"Loading: {file_path.name}")

            # Check if stems exist
            exists, vocals_path, instrumental_path = self.separation_engine.check_stems_exist(file_path)

            if exists:
                # Stems already exist, load them directly
                logger.info("Stems found in cache, loading...")
                self.status_label.setText(f"Loading stems from cache: {file_path.name}")
                self._load_stems(vocals_path, instrumental_path)
            else:
                # Need to separate
                logger.info("Stems not found, starting separation...")
                self._start_separation(file_path)

        except Exception as e:
            logger.error(f"Error loading file: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to load file:\n{str(e)}")
            self.status_label.setText("Error loading file")

    def _start_separation(self, file_path: Path):
        """Start the separation process in a background thread."""
        # Create progress dialog
        progress_dialog = QProgressDialog(
            "Separating audio into vocals and instrumental...",
            "Cancel",
            0,
            100,
            self
        )
        progress_dialog.setWindowTitle("AI Stem Separation")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setValue(0)

        # Create worker thread
        self.separation_worker = SeparationWorker(self.separation_engine, file_path)

        # Connect signals
        self.separation_worker.progress.connect(
            lambda percentage, message: self._on_separation_progress(progress_dialog, percentage, message)
        )
        self.separation_worker.finished.connect(
            lambda vocals_path, instrumental_path: self._on_separation_finished(
                progress_dialog, vocals_path, instrumental_path
            )
        )
        self.separation_worker.error.connect(
            lambda error: self._on_separation_error(progress_dialog, error)
        )

        # Allow cancellation
        progress_dialog.canceled.connect(self.separation_worker.terminate)

        # Start separation
        self.separation_worker.start()

    @Slot(QProgressDialog, int, str)
    def _on_separation_progress(self, dialog: QProgressDialog, percentage: int, message: str):
        """Handle separation progress updates."""
        dialog.setValue(percentage)
        dialog.setLabelText(f"{message}\n{percentage}% complete")
        self.status_label.setText(f"Separating: {percentage}% - {message}")

    @Slot(QProgressDialog, Path, Path)
    def _on_separation_finished(self, dialog: QProgressDialog, vocals_path: Path, instrumental_path: Path):
        """Handle separation completion."""
        try:
            logger.info("Separation finished callback called")
            logger.info(f"Vocals path: {vocals_path}")
            logger.info(f"Instrumental path: {instrumental_path}")

            dialog.close()
            self.status_label.setText("Separation complete!")
            logger.info("About to load stems...")
            self._load_stems(vocals_path, instrumental_path)
            logger.info("Stems loaded successfully from callback")
        except Exception as e:
            logger.error(f"Error in _on_separation_finished: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed after separation:\n{str(e)}")
            self.status_label.setText("Error after separation")

    @Slot(QProgressDialog, str)
    def _on_separation_error(self, dialog: QProgressDialog, error: str):
        """Handle separation error."""
        dialog.close()
        QMessageBox.critical(self, "Separation Error", f"Failed to separate audio:\n{error}")
        self.status_label.setText("Separation failed")

    def _load_stems(self, vocals_path: Path, instrumental_path: Path):
        """Load the separated stems for playback."""
        try:
            logger.info("_load_stems called")
            logger.info(f"Loading stems - Vocals: {vocals_path}, Instrumental: {instrumental_path}")

            # Load into stem player
            logger.info("Loading stems into player...")
            self.stem_player.load_stems(vocals_path, instrumental_path)
            logger.info("Stems loaded into player successfully")

            # Load video if applicable
            # Note: Video playback is optional - if it fails, audio still works
            if self.current_file and self._is_video_file(self.current_file):
                logger.info(f"File is video: {self.current_file}")
                
                # Check if video needs codec conversion (AV1/VP9 -> H.264)
                if self.video_converter.needs_conversion(self.current_file):
                    # Check for cached conversion first
                    cached = self.video_converter.is_already_converted(self.current_file)
                    if cached:
                        logger.info(f"Using cached converted video: {cached}")
                        self._setup_video_playback(cached)
                    else:
                        # Start async conversion
                        self._start_video_conversion(self.current_file)
                        # Video will be set up after conversion finishes
                        self.placeholder_label.setText(
                            f"🎵\n\n{self.current_file.name}\n\nConverting video..."
                        )
                        self.placeholder_label.show()
                        self.video_widget.hide()
                else:
                    # No conversion needed
                    self._setup_video_playback(self.current_file)
            else:
                # Audio only
                logger.info("File is audio-only")
                self.video_widget.hide()
                self.placeholder_label.show()
                self.placeholder_label.setText(
                    f"🎵\n\n{self.current_file.name}\n\nAudio Only"
                )

            # Update seek slider range
            logger.info("Updating seek slider range...")
            duration = self.stem_player.get_duration()
            self.seek_slider.setMaximum(int(duration * 1000))
            logger.info(f"Seek slider updated, duration: {duration}s")

            # Load saved settings for this song
            logger.info("Loading saved song settings...")
            self._load_song_settings()

            # Enable controls
            logger.info("Enabling playback controls...")
            self._set_controls_enabled(True)
            self.status_label.setText(f"Ready to play: {self.current_file.name}")

            logger.info("Stems loaded successfully - ready to play!")

        except Exception as e:
            logger.error(f"Error loading stems: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to load stems:\n{str(e)}")
            self.status_label.setText("Error loading stems")

    def _is_video_file(self, file_path: Path) -> bool:
        """Check if the file is a video file."""
        video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm']
        return file_path.suffix.lower() in video_extensions

    def _setup_video_playback(self, video_path: Path):
        """Set up video playback with the given video file."""
        try:
            logger.info(f"Setting up video playback: {video_path}")
            # Mute video player (we use stem player for audio)
            self.audio_output.setVolume(0)

            # Set video source
            self.video_player.setSource(QUrl.fromLocalFile(str(video_path)))
            logger.info("Video source set successfully")

            self.video_widget.show()
            self.placeholder_label.hide()
            logger.info("Video widget visible")
        except Exception as e:
            logger.warning(f"Could not set up video player: {e}")
            self.video_widget.hide()
            self.placeholder_label.show()
            self.placeholder_label.setText(
                f"🎵\n\n{self.current_file.name}\n\n(Video error - Audio only)"
            )

    def _start_video_conversion(self, file_path: Path):
        """Start video conversion in a background thread with progress dialog."""
        # Create progress dialog
        self.conversion_dialog = QProgressDialog(
            "Converting video to compatible format...\nThis may take a few minutes.",
            "Cancel",
            0, 100, self
        )
        self.conversion_dialog.setWindowTitle("Video Conversion")
        self.conversion_dialog.setWindowModality(Qt.WindowModal)
        self.conversion_dialog.setMinimumDuration(0)
        self.conversion_dialog.setAutoClose(False)
        self.conversion_dialog.setAutoReset(False)
        self.conversion_dialog.setValue(0)

        # Create worker
        self.conversion_worker = VideoConversionWorker(self.video_converter, file_path)

        # Connect signals
        self.conversion_worker.progress.connect(
            lambda p, m: self._on_conversion_progress(p, m)
        )
        self.conversion_worker.finished.connect(self._on_conversion_finished)
        self.conversion_worker.error.connect(self._on_conversion_error)

        # Handle cancel
        self.conversion_dialog.canceled.connect(self.conversion_worker.terminate)

        # Start conversion
        self.conversion_worker.start()

    @Slot(int, str)
    def _on_conversion_progress(self, percentage: int, message: str):
        """Handle conversion progress updates."""
        if hasattr(self, 'conversion_dialog') and self.conversion_dialog:
            self.conversion_dialog.setValue(percentage)
            self.conversion_dialog.setLabelText(f"{message}")
        self.status_label.setText(f"Converting: {percentage}%")

    @Slot(Path)
    def _on_conversion_finished(self, converted_path: Path):
        """Handle conversion completion."""
        if hasattr(self, 'conversion_dialog') and self.conversion_dialog:
            self.conversion_dialog.close()
        
        self.notification_toast.show_message(
            "Video converted successfully!",
            duration=3000,
            style="success"
        )
        self.status_label.setText(f"Ready to play: {self.current_file.name}")
        
        # Now set up video playback with the converted file
        self._setup_video_playback(converted_path)
        logger.info(f"Video conversion complete: {converted_path}")

    @Slot(str)
    def _on_conversion_error(self, error: str):
        """Handle conversion error."""
        if hasattr(self, 'conversion_dialog') and self.conversion_dialog:
            self.conversion_dialog.close()
        
        logger.error(f"Video conversion failed: {error}")
        self.notification_toast.show_message(
            "Video conversion failed - Audio only mode",
            duration=4000,
            style="warning"
        )
        self.status_label.setText(f"Ready to play: {self.current_file.name} (Audio only)")
        
        # Show placeholder
        self.video_widget.hide()
        self.placeholder_label.show()
        self.placeholder_label.setText(
            f"🎵\n\n{self.current_file.name}\n\n(Video conversion failed - Audio only)"
        )

    @Slot()
    def _on_video_error(self, error, error_string):
        """Handle video player errors gracefully."""
        logger.warning(f"Video playback error: {error_string}")
        logger.info("Continuing with audio-only mode")
        # Don't show error to user - just continue with audio
        # The video widget will show black/nothing, but audio works fine

    @Slot()
    def _on_play(self):
        """Handle play button click."""
        self.stem_player.play()

        if self.current_file and self._is_video_file(self.current_file):
            try:
                self.video_player.play()
                self.position_timer.start()
            except Exception as e:
                logger.warning(f"Video play failed: {e} - continuing with audio only")

        self.status_label.setText("Playing...")

    @Slot()
    def _on_pause(self):
        """Handle pause button click."""
        self.stem_player.pause()

        if self.current_file and self._is_video_file(self.current_file):
            try:
                self.video_player.pause()
                self.position_timer.stop()
            except Exception as e:
                logger.warning(f"Video pause failed: {e}")

        self.status_label.setText("Paused")

    @Slot()
    def _on_stop(self):
        """Handle stop button click."""
        self.stem_player.stop()

        if self.current_file and self._is_video_file(self.current_file):
            try:
                self.video_player.stop()
                self.position_timer.stop()
            except Exception as e:
                logger.warning(f"Video stop failed: {e}")

        self.status_label.setText("Stopped")

    @Slot(int)
    def _on_seek_slider_moved(self, value: int):
        """Handle seek slider movement."""
        position = value / 1000.0  # Convert from milliseconds
        self.stem_player.seek(position)

        if self.current_file and self._is_video_file(self.current_file):
            try:
                self.video_player.setPosition(int(position * 1000))
            except Exception as e:
                logger.warning(f"Video seek failed: {e}")

    def _on_playback_position_changed(self, position: float):
        """Handle playback position updates from stem player."""
        # Update seek slider
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(int(position * 1000))
        self.seek_slider.blockSignals(False)

        # Update time label
        duration = self.stem_player.get_duration()
        self.time_label.setText(
            f"{self._format_time(position)} / {self._format_time(duration)}"
        )

    def _update_video_position(self):
        """Update video player position to match audio (called by timer)."""
        if self.stem_player.is_playing:
            try:
                audio_position = self.stem_player.get_position()
                video_position = self.video_player.position() / 1000.0

                # Sync video to audio if drift is more than 100ms
                if abs(audio_position - video_position) > 0.1:
                    self.video_player.setPosition(int(audio_position * 1000))
            except Exception as e:
                logger.debug(f"Video sync failed: {e}")

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format time in seconds to MM:SS."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    @Slot(int)
    def _on_vocals_volume_changed(self, value: int):
        """Handle vocals volume slider change."""
        volume = value / 100.0
        self.stem_player.set_vocals_volume(volume)
        self.vocals_value_label.setText(f"{value}%")
        self._save_song_settings()

    @Slot(int)
    def _on_instrumental_volume_changed(self, value: int):
        """Handle instrumental volume slider change."""
        volume = value / 100.0
        self.stem_player.set_instrumental_volume(volume)
        self.instrumental_value_label.setText(f"{value}%")
        self._save_song_settings()

    @Slot(int)
    def _on_vocals_mute_changed(self, state: int):
        """Handle vocals mute checkbox."""
        muted = state == Qt.CheckState.Checked.value
        self.stem_player.set_vocals_muted(muted)
        self._save_song_settings()

    @Slot(int)
    def _on_instrumental_mute_changed(self, state: int):
        """Handle instrumental mute checkbox."""
        muted = state == Qt.CheckState.Checked.value
        self.stem_player.set_instrumental_muted(muted)
        self._save_song_settings()

    @Slot()
    def _on_vocals_solo(self):
        """Solo vocals (mute instrumental)."""
        self.vocals_mute_checkbox.setChecked(False)
        self.instrumental_mute_checkbox.setChecked(True)

    @Slot()
    def _on_instrumental_solo(self):
        """Solo instrumental (mute vocals)."""
        self.instrumental_mute_checkbox.setChecked(False)
        self.vocals_mute_checkbox.setChecked(True)

    @Slot()
    def _on_reset_mix(self):
        """Reset mix to default (both at 100%)."""
        self.vocals_slider.setValue(100)
        self.instrumental_slider.setValue(100)
        self.vocals_mute_checkbox.setChecked(False)
        self.instrumental_mute_checkbox.setChecked(False)
        self.mic_slider.setValue(70)
        self.mic_mute_checkbox.setChecked(False)
        self.reverb_slider.setValue(30)
        self.echo_slider.setValue(30)

    # ===== Microphone Handlers =====

    def _refresh_mic_devices(self):
        """Refresh the list of available microphone devices."""
        if not self.mic_device_combo:
            return
        
        self.mic_device_combo.blockSignals(True)
        self.mic_device_combo.clear()
        
        devices = AudioDeviceManager.get_input_devices()
        for device in devices:
            self.mic_device_combo.addItem(device["name"], device["id"])
        
        self.mic_device_combo.blockSignals(False)

    @Slot(int)
    def _on_mic_device_changed(self, index: int):
        """Handle microphone device selection change."""
        if index >= 0:
            device_id = self.mic_device_combo.itemData(index)
            self.stem_player.set_microphone_device(device_id)
            logger.info(f"Microphone device changed to: {self.mic_device_combo.currentText()}")

    @Slot(int)
    def _on_mic_volume_changed(self, value: int):
        """Handle microphone volume slider change."""
        volume = value / 100.0
        self.stem_player.set_microphone_volume(volume)
        self.mic_value_label.setText(f"{value}%")

    @Slot(int)
    def _on_mic_mute_changed(self, state: int):
        """Handle microphone mute checkbox."""
        muted = state == Qt.CheckState.Checked.value
        self.stem_player.set_microphone_muted(muted)

    @Slot(int)
    def _on_mic_enable_changed(self, state: int):
        """Handle microphone enable checkbox."""
        enabled = state == Qt.CheckState.Checked.value
        self.stem_player.set_microphone_enabled(enabled)
        
        if enabled:
            self.notification_toast.show_message(
                "Microphone enabled - Use headphones to avoid feedback!",
                duration=3000,
                style="warning"
            )

    # ===== Voice Effects Handlers =====

    @Slot(int)
    def _on_effects_enable_changed(self, state: int):
        """Handle effects enable checkbox."""
        enabled = state == Qt.CheckState.Checked.value
        self.stem_player.set_effects_enabled(enabled)

    @Slot(int)
    def _on_reverb_changed(self, value: int):
        """Handle reverb slider change."""
        intensity = value / 100.0
        self.stem_player.set_reverb_intensity(intensity)
        self.reverb_value_label.setText(f"{value}%")

    @Slot(int)
    def _on_echo_changed(self, value: int):
        """Handle echo slider change."""
        # Map 0-100 to 50-500ms delay and 0-0.8 feedback
        delay_ms = 50 + (value * 4.5)  # 50-500ms
        feedback = value / 125.0  # 0-0.8
        self.stem_player.set_echo_delay(delay_ms)
        self.stem_player.set_echo_feedback(feedback)
        self.echo_value_label.setText(f"{value}%")

    # ===== Recording Handlers =====

    @Slot()
    def _on_record_toggle(self):
        """Handle record button toggle."""
        if self.record_button.isChecked():
            # Start recording
            song_name = self.current_file.stem if self.current_file else "Unknown"
            self.stem_player.start_recording(song_name)
            self.recording_label.setVisible(True)
            self.recording_timer.start()
            self.notification_toast.show_message(
                "Recording started",
                duration=2000,
                style="success"
            )
            logger.info("Recording started")
        else:
            # Stop recording
            self.recording_timer.stop()
            self.recording_label.setVisible(False)
            saved_path = self.stem_player.stop_recording()
            
            if saved_path:
                self.notification_toast.show_message(
                    f"Recording saved: {saved_path.name}",
                    duration=4000,
                    style="success"
                )
                logger.info(f"Recording saved: {saved_path}")
            else:
                self.notification_toast.show_message(
                    "Recording stopped (no audio captured)",
                    duration=2000,
                    style="warning"
                )

    def _update_recording_time(self):
        """Update recording time display."""
        if self.stem_player.is_recording():
            duration = self.stem_player.get_recording_duration()
            self.recording_label.setText(self._format_time(duration))

    @Slot()
    def _on_model_preloaded(self):
        """Handle AI model preload completion."""
        logger.info("AI model preloaded and ready!")
        self.status_label.setText("Ready - AI model loaded - Select a song to begin")

    @Slot(str)
    def _on_model_preload_error(self, error: str):
        """Handle AI model preload error."""
        logger.warning(f"AI model preload failed: {error}")
        logger.info("Model will be loaded on first use instead")
        # Don't show error to user - model will load on first separation anyway

    def _save_song_settings(self):
        """Save current mix settings for the current song."""
        if not self.current_file:
            return

        settings = {
            "vocals_volume": self.vocals_slider.value(),
            "instrumental_volume": self.instrumental_slider.value(),
            "vocals_muted": self.vocals_mute_checkbox.isChecked(),
            "instrumental_muted": self.instrumental_mute_checkbox.isChecked()
        }

        self.current_settings[str(self.current_file)] = settings
        self.save_settings()

    def _load_song_settings(self):
        """Load saved mix settings for the current song."""
        if not self.current_file:
            return

        settings = self.current_settings.get(str(self.current_file), {})

        if settings:
            self.vocals_slider.setValue(settings.get("vocals_volume", 100))
            self.instrumental_slider.setValue(settings.get("instrumental_volume", 100))
            self.vocals_mute_checkbox.setChecked(settings.get("vocals_muted", False))
            self.instrumental_mute_checkbox.setChecked(settings.get("instrumental_muted", False))

    def load_settings(self):
        """Load application settings from file."""
        try:
            if self.settings_file.exists():
                with open(self.settings_file, 'r') as f:
                    self.current_settings = json.load(f)
                logger.info("Settings loaded")
        except Exception as e:
            logger.warning(f"Could not load settings: {str(e)}")
            self.current_settings = {}

    def save_settings(self):
        """Save application settings to file."""
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, 'w') as f:
                json.dump(self.current_settings, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save settings: {str(e)}")

    @Slot()
    def regenerate_stems(self):
        """Regenerate stems for the current song."""
        if not self.current_file:
            QMessageBox.information(self, "No Song", "Please load a song first.")
            return

        reply = QMessageBox.question(
            self,
            "Regenerate Stems",
            f"This will delete and regenerate stems for:\n{self.current_file.name}\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # Stop playback
            self._on_stop()

            # Delete existing stems
            self.separation_engine.delete_stems(self.current_file)

            # Reload file (will trigger separation)
            self.load_file(self.current_file)

    @Slot()
    def show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Karaoke Separation Studio",
            """<h2>Karaoke Separation Studio v1.0</h2>
            <p>Professional karaoke application with AI-powered vocal separation.</p>
            <p><b>Features:</b></p>
            <ul>
            <li>AI-powered stem separation using Demucs v4</li>
            <li>Real-time vocal and instrumental mixing</li>
            <li>Video playback support</li>
            <li>Smart caching for fast loading</li>
            <li>GPU acceleration support</li>
            </ul>
            <p>Built with PySide6, PyTorch, and Demucs.</p>
            """
        )

    def _refresh_history(self):
        """Refresh the history list in the side panel."""
        if self.side_panel:
            history = self.youtube_downloader.get_history()
            self.side_panel.update_history(history)

    @Slot(dict)
    def _on_history_item_selected(self, entry: dict):
        """Handle selecting an item from history."""
        file_path = Path(entry.get("file_path", ""))
        title = entry.get("title", "Unknown")
        
        if file_path.exists():
            # Show notification
            self.notification_toast.show_message(
                f"Loading: {title}",
                duration=2000,
                style="success"
            )
            # Load the file
            self.load_file(file_path)
        else:
            # File was deleted
            QMessageBox.warning(
                self,
                "File Not Found",
                f"The cached file was not found:\n{file_path}\n\nIt may have been deleted."
            )
            # Remove from history
            video_id = entry.get("video_id", "")
            if video_id:
                self.youtube_downloader.history.remove_download(video_id)
                self._refresh_history()

    @Slot(str)
    def _on_history_item_removed(self, video_id: str):
        """Handle removing an item from history."""
        self.youtube_downloader.history.remove_download(video_id)
        self._refresh_history()
        self.notification_toast.show_message(
            "Removed from history",
            duration=2000,
            style="info"
        )

    @Slot(int)
    def _on_queue_item_selected(self, index: int):
        """Handle selecting an item from queue."""
        queue = self.side_panel.get_queue()
        if 0 <= index < len(queue):
            file_path, title = queue[index]
            if file_path.exists():
                self.load_file(file_path)
            else:
                QMessageBox.warning(
                    self,
                    "File Not Found",
                    f"The file was not found:\n{file_path}"
                )
                self.side_panel.remove_from_queue(index)

    def closeEvent(self, event):
        """Handle window close event."""
        try:
            # Stop playback
            self.stem_player.cleanup()
            try:
                self.video_player.stop()
            except Exception as e:
                logger.warning(f"Error stopping video player on close: {e}")

            # Save settings
            self.save_settings()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        finally:
            event.accept()
