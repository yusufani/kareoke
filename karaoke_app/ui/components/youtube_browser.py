"""
YouTube Browser Component
Embedded web browser for browsing and selecting YouTube videos.
"""
import logging
import re
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QLabel, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

logger = logging.getLogger(__name__)


class YouTubeBrowser(QWidget):
    """
    Embedded YouTube browser for searching and selecting songs.
    
    Signals:
        download_requested: Emitted when user wants to download current video (url, title)
        close_requested: Emitted when user wants to close the browser
    """
    
    download_requested = Signal(str, str)  # url, title
    close_requested = Signal()
    
    YOUTUBE_URL = "https://www.youtube.com"
    VIDEO_URL_PATTERN = re.compile(r'youtube\.com/watch\?v=([a-zA-Z0-9_-]+)')
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_video_id: Optional[str] = None
        self.current_title: Optional[str] = None
        self._setup_ui()
        
    def _setup_ui(self):
        """Set up the browser UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Navigation bar
        nav_bar = self._create_nav_bar()
        layout.addWidget(nav_bar)
        
        # Web browser
        self.browser = QWebEngineView()
        self.browser.setUrl(QUrl(self.YOUTUBE_URL))
        
        # Configure browser settings
        settings = self.browser.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, True)
        
        # Connect signals
        self.browser.urlChanged.connect(self._on_url_changed)
        self.browser.titleChanged.connect(self._on_title_changed)
        self.browser.loadFinished.connect(self._on_load_finished)
        
        layout.addWidget(self.browser)
        
    def _create_nav_bar(self) -> QFrame:
        """Create the navigation bar with controls."""
        nav_bar = QFrame()
        nav_bar.setStyleSheet("""
            QFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1a1a1a,
                    stop:1 #0f0f0f
                );
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                padding: 8px;
            }
        """)
        
        layout = QHBoxLayout(nav_bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        
        # Back button
        self.back_btn = QPushButton("◀")
        self.back_btn.setFixedSize(36, 36)
        self.back_btn.clicked.connect(lambda: self.browser.back())
        self.back_btn.setStyleSheet(self._nav_button_style())
        layout.addWidget(self.back_btn)
        
        # Forward button
        self.forward_btn = QPushButton("▶")
        self.forward_btn.setFixedSize(36, 36)
        self.forward_btn.clicked.connect(lambda: self.browser.forward())
        self.forward_btn.setStyleSheet(self._nav_button_style())
        layout.addWidget(self.forward_btn)
        
        # Refresh button
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setFixedSize(36, 36)
        self.refresh_btn.clicked.connect(lambda: self.browser.reload())
        self.refresh_btn.setStyleSheet(self._nav_button_style())
        layout.addWidget(self.refresh_btn)
        
        # Home button
        self.home_btn = QPushButton("🏠")
        self.home_btn.setFixedSize(36, 36)
        self.home_btn.clicked.connect(self.go_home)
        self.home_btn.setStyleSheet(self._nav_button_style())
        layout.addWidget(self.home_btn)
        
        # URL bar
        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("YouTube URL...")
        self.url_bar.returnPressed.connect(self._on_url_entered)
        self.url_bar.setStyleSheet("""
            QLineEdit {
                background: #0a0a0a;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 18px;
                padding: 8px 16px;
                color: #ffffff;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #1db954;
            }
        """)
        layout.addWidget(self.url_bar, stretch=1)
        
        # Download button (only visible on video pages)
        self.download_btn = QPushButton("⬇ Download This Song")
        self.download_btn.clicked.connect(self._on_download_clicked)
        self.download_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1db954,
                    stop:1 #1ed760
                );
                border: none;
                border-radius: 18px;
                padding: 10px 20px;
                color: #000000;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1ed760,
                    stop:1 #1fdf64
                );
            }
        """)
        self.download_btn.hide()  # Hidden until on video page
        layout.addWidget(self.download_btn)
        
        # Close/Back to Player button
        self.close_btn = QPushButton("✕ Close")
        self.close_btn.clicked.connect(self.close_requested.emit)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.1);
                border: none;
                border-radius: 18px;
                padding: 10px 16px;
                color: #ffffff;
                font-size: 12px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.2);
            }
        """)
        layout.addWidget(self.close_btn)
        
        return nav_bar
    
    def _nav_button_style(self) -> str:
        """Return style for navigation buttons."""
        return """
            QPushButton {
                background: rgba(255, 255, 255, 0.1);
                border: none;
                border-radius: 18px;
                color: #ffffff;
                font-size: 16px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.2);
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.05);
            }
        """
    
    def _on_url_changed(self, url: QUrl):
        """Handle URL changes in the browser."""
        url_str = url.toString()
        self.url_bar.setText(url_str)
        
        # Check if this is a video page
        match = self.VIDEO_URL_PATTERN.search(url_str)
        if match:
            self.current_video_id = match.group(1)
            self.download_btn.show()
            logger.debug(f"Video page detected: {self.current_video_id}")
        else:
            self.current_video_id = None
            self.download_btn.hide()
    
    def _on_title_changed(self, title: str):
        """Handle page title changes."""
        self.current_title = title
        # Remove " - YouTube" suffix if present
        if title.endswith(" - YouTube"):
            self.current_title = title[:-10]
    
    def _on_load_finished(self, ok: bool):
        """Handle page load completion."""
        if ok:
            logger.debug(f"Page loaded: {self.browser.url().toString()}")
            # Mute audio in the browser to avoid conflicts
            self.browser.page().setAudioMuted(True)
    
    def _on_url_entered(self):
        """Handle URL entry in the address bar."""
        url = self.url_bar.text().strip()
        if not url.startswith('http'):
            # Treat as search query
            url = f"https://www.youtube.com/results?search_query={url.replace(' ', '+')}"
        self.browser.setUrl(QUrl(url))
    
    def _on_download_clicked(self):
        """Handle download button click."""
        if self.current_video_id:
            url = f"https://www.youtube.com/watch?v={self.current_video_id}"
            title = self.current_title or "Unknown"
            logger.info(f"Download requested: {title} ({url})")
            self.download_requested.emit(url, title)
    
    def go_home(self):
        """Navigate to YouTube home page."""
        self.browser.setUrl(QUrl(self.YOUTUBE_URL))
    
    def search(self, query: str):
        """Search YouTube for the given query."""
        search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
        self.browser.setUrl(QUrl(search_url))
    
    def cleanup(self):
        """Clean up browser resources."""
        self.browser.setUrl(QUrl("about:blank"))
