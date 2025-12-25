"""
Side Panel Widget
Slide-out panel for queue and history management.
"""
import logging
from pathlib import Path
from typing import Optional, Callable, List, Dict
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QSplitter, QScrollArea,
    QMenu, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QIcon, QPixmap, QFont


logger = logging.getLogger(__name__)


class HistoryItem(QWidget):
    """Custom widget for history list items."""

    clicked = Signal(dict)
    remove_clicked = Signal(str)

    def __init__(self, download_entry: Dict, parent=None):
        super().__init__(parent)
        self.entry = download_entry
        self._setup_ui()

    def _setup_ui(self):
        """Setup the item UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # Info container
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        # Title
        title = self.entry.get("title", "Unknown")
        if len(title) > 40:
            title = title[:37] + "..."
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 13px;
                font-weight: 500;
            }
        """)
        info_layout.addWidget(self.title_label)

        # Meta info (duration + date)
        duration = self.entry.get("duration", 0)
        mins, secs = divmod(duration, 60)
        duration_str = f"{mins}:{secs:02d}"
        
        downloaded_at = self.entry.get("downloaded_at", "")
        if downloaded_at:
            try:
                dt = datetime.fromisoformat(downloaded_at.replace("Z", "+00:00"))
                date_str = dt.strftime("%b %d, %Y")
            except:
                date_str = ""
        else:
            date_str = ""

        meta_text = f"{duration_str} • {date_str}" if date_str else duration_str
        self.meta_label = QLabel(meta_text)
        self.meta_label.setStyleSheet("""
            QLabel {
                color: #b3b3b3;
                font-size: 11px;
            }
        """)
        info_layout.addWidget(self.meta_label)

        layout.addLayout(info_layout, 1)

        # Play button
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(32, 32)
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setStyleSheet("""
            QPushButton {
                background: rgba(29, 185, 84, 0.8);
                border: none;
                border-radius: 16px;
                color: #000000;
                font-size: 14px;
            }
            QPushButton:hover {
                background: rgba(29, 185, 84, 1.0);
            }
        """)
        self.play_btn.clicked.connect(lambda: self.clicked.emit(self.entry))
        layout.addWidget(self.play_btn)

        # Style the widget
        self.setStyleSheet("""
            HistoryItem {
                background: rgba(255, 255, 255, 0.05);
                border-radius: 8px;
            }
            HistoryItem:hover {
                background: rgba(255, 255, 255, 0.1);
            }
        """)
        self.setCursor(Qt.PointingHandCursor)

    def contextMenuEvent(self, event):
        """Show context menu on right-click."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #282828;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 8px;
            }
            QMenu::item {
                color: #ffffff;
                padding: 8px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: rgba(255, 255, 255, 0.1);
            }
        """)

        load_action = menu.addAction("Load")
        load_action.triggered.connect(lambda: self.clicked.emit(self.entry))

        remove_action = menu.addAction("Remove from History")
        remove_action.triggered.connect(
            lambda: self.remove_clicked.emit(self.entry.get("video_id", ""))
        )

        menu.exec_(event.globalPos())

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to load."""
        self.clicked.emit(self.entry)


class QueueItem(QWidget):
    """Custom widget for queue list items."""

    remove_clicked = Signal(int)
    play_clicked = Signal(int)

    def __init__(self, index: int, file_path: Path, title: str, parent=None):
        super().__init__(parent)
        self.index = index
        self.file_path = file_path
        self.title = title
        self._setup_ui()

    def _setup_ui(self):
        """Setup the item UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # Index label
        self.index_label = QLabel(f"{self.index + 1}")
        self.index_label.setFixedWidth(24)
        self.index_label.setStyleSheet("""
            QLabel {
                color: #b3b3b3;
                font-size: 14px;
                font-weight: 500;
            }
        """)
        layout.addWidget(self.index_label)

        # Title
        display_title = self.title if len(self.title) <= 35 else self.title[:32] + "..."
        self.title_label = QLabel(display_title)
        self.title_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 13px;
            }
        """)
        layout.addWidget(self.title_label, 1)

        # Remove button
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setFixedSize(24, 24)
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #666666;
                font-size: 14px;
            }
            QPushButton:hover {
                color: #e74c3c;
            }
        """)
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.index))
        layout.addWidget(self.remove_btn)

        # Style
        self.setStyleSheet("""
            QueueItem {
                background: rgba(255, 255, 255, 0.03);
                border-radius: 6px;
            }
            QueueItem:hover {
                background: rgba(255, 255, 255, 0.08);
            }
        """)
        self.setCursor(Qt.PointingHandCursor)

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to play."""
        self.play_clicked.emit(self.index)


class SidePanel(QWidget):
    """Slide-out side panel with queue and history sections."""

    # Signals
    history_item_selected = Signal(dict)  # Emits download entry when selected
    queue_item_selected = Signal(int)  # Emits queue index when selected
    queue_item_removed = Signal(int)  # Emits queue index when removed
    history_item_removed = Signal(str)  # Emits video_id when removed

    PANEL_WIDTH = 350
    HANDLE_WIDTH = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_open = False
        self._queue_items: List[tuple] = []  # [(file_path, title), ...]
        self._history_items: List[Dict] = []
        
        self.setFixedWidth(self.HANDLE_WIDTH)
        self._setup_ui()
        self._setup_animation()

    def _setup_ui(self):
        """Setup the panel UI."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Content container (initially hidden)
        self.content = QWidget()
        self.content.setFixedWidth(self.PANEL_WIDTH - self.HANDLE_WIDTH)
        self.content.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0f0f0f,
                    stop:1 #1a1a1a
                );
            }
        """)
        
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(16, 16, 0, 16)
        content_layout.setSpacing(16)

        # Splitter for queue and history
        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background: rgba(255, 255, 255, 0.1);
                height: 2px;
            }
        """)

        # Queue section (top 50%)
        queue_section = QWidget()
        queue_layout = QVBoxLayout(queue_section)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(12)

        queue_header = QLabel("QUEUE")
        queue_header.setStyleSheet("""
            QLabel {
                color: #b3b3b3;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
            }
        """)
        queue_layout.addWidget(queue_header)

        self.queue_list = QVBoxLayout()
        self.queue_list.setSpacing(4)
        
        queue_scroll = QScrollArea()
        queue_scroll.setWidgetResizable(True)
        queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        queue_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 0.05);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
        """)
        
        queue_container = QWidget()
        queue_container.setLayout(self.queue_list)
        queue_container.setStyleSheet("background: transparent;")
        queue_scroll.setWidget(queue_container)
        queue_layout.addWidget(queue_scroll)

        self.queue_empty_label = QLabel("Queue is empty")
        self.queue_empty_label.setAlignment(Qt.AlignCenter)
        self.queue_empty_label.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 12px;
                padding: 20px;
            }
        """)
        queue_layout.addWidget(self.queue_empty_label)

        splitter.addWidget(queue_section)

        # History section (bottom 50%)
        history_section = QWidget()
        history_layout = QVBoxLayout(history_section)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(12)

        history_header = QLabel("HISTORY")
        history_header.setStyleSheet("""
            QLabel {
                color: #b3b3b3;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
            }
        """)
        history_layout.addWidget(history_header)

        self.history_list = QVBoxLayout()
        self.history_list.setSpacing(4)
        
        history_scroll = QScrollArea()
        history_scroll.setWidgetResizable(True)
        history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        history_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 0.05);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
        """)
        
        history_container = QWidget()
        history_container.setLayout(self.history_list)
        history_container.setStyleSheet("background: transparent;")
        history_scroll.setWidget(history_container)
        history_layout.addWidget(history_scroll)

        self.history_empty_label = QLabel("No download history")
        self.history_empty_label.setAlignment(Qt.AlignCenter)
        self.history_empty_label.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 12px;
                padding: 20px;
            }
        """)
        history_layout.addWidget(self.history_empty_label)

        splitter.addWidget(history_section)

        # Set splitter sizes (50/50 split)
        splitter.setSizes([200, 200])

        content_layout.addWidget(splitter)
        main_layout.addWidget(self.content)

        # Handle (always visible)
        self.handle = QPushButton("☰")
        self.handle.setFixedWidth(self.HANDLE_WIDTH)
        self.handle.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.handle.setCursor(Qt.PointingHandCursor)
        self.handle.setStyleSheet("""
            QPushButton {
                background: rgba(29, 185, 84, 0.15);
                border: none;
                border-radius: 4px 0 0 4px;
                color: #1db954;
                font-size: 16px;
            }
            QPushButton:hover {
                background: rgba(29, 185, 84, 0.3);
            }
        """)
        self.handle.clicked.connect(self.toggle_panel)
        main_layout.addWidget(self.handle)

        # Initially hide content
        self.content.hide()

    def _setup_animation(self):
        """Setup slide animation."""
        self.slide_anim = QPropertyAnimation(self, b"minimumWidth")
        self.slide_anim.setDuration(200)
        self.slide_anim.setEasingCurve(QEasingCurve.OutCubic)

        self.slide_anim_max = QPropertyAnimation(self, b"maximumWidth")
        self.slide_anim_max.setDuration(200)
        self.slide_anim_max.setEasingCurve(QEasingCurve.OutCubic)

    def toggle_panel(self):
        """Toggle panel open/closed state."""
        if self.is_open:
            self._close_panel()
        else:
            self._open_panel()

    def _open_panel(self):
        """Open the panel with animation."""
        self.content.show()
        self.slide_anim.setStartValue(self.HANDLE_WIDTH)
        self.slide_anim.setEndValue(self.PANEL_WIDTH)
        self.slide_anim_max.setStartValue(self.HANDLE_WIDTH)
        self.slide_anim_max.setEndValue(self.PANEL_WIDTH)
        self.slide_anim.start()
        self.slide_anim_max.start()
        self.is_open = True
        self.handle.setText("✕")
        logger.debug("Side panel opened")

    def _close_panel(self):
        """Close the panel with animation."""
        self.slide_anim.setStartValue(self.PANEL_WIDTH)
        self.slide_anim.setEndValue(self.HANDLE_WIDTH)
        self.slide_anim_max.setStartValue(self.PANEL_WIDTH)
        self.slide_anim_max.setEndValue(self.HANDLE_WIDTH)
        self.slide_anim.start()
        self.slide_anim_max.start()
        self.slide_anim.finished.connect(lambda: self.content.hide())
        self.is_open = False
        self.handle.setText("☰")
        logger.debug("Side panel closed")

    def update_history(self, history_items: List[Dict]):
        """
        Update the history list.

        Args:
            history_items: List of download entries from DownloadHistory
        """
        self._history_items = history_items

        # Clear existing items
        while self.history_list.count():
            item = self.history_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Hide/show empty label
        self.history_empty_label.setVisible(len(history_items) == 0)

        # Add new items
        for entry in history_items:
            item_widget = HistoryItem(entry)
            item_widget.clicked.connect(self._on_history_item_clicked)
            item_widget.remove_clicked.connect(self._on_history_item_removed)
            self.history_list.addWidget(item_widget)

        # Add stretch at the end
        self.history_list.addStretch()

    def _on_history_item_clicked(self, entry: Dict):
        """Handle history item click."""
        self.history_item_selected.emit(entry)
        logger.info(f"History item selected: {entry.get('title', 'Unknown')}")

    def _on_history_item_removed(self, video_id: str):
        """Handle history item removal."""
        self.history_item_removed.emit(video_id)
        logger.info(f"History item removal requested: {video_id}")

    def add_to_queue(self, file_path: Path, title: str):
        """
        Add an item to the queue.

        Args:
            file_path: Path to the file
            title: Display title
        """
        self._queue_items.append((file_path, title))
        self._refresh_queue_ui()

    def remove_from_queue(self, index: int):
        """
        Remove an item from the queue.

        Args:
            index: Queue index
        """
        if 0 <= index < len(self._queue_items):
            self._queue_items.pop(index)
            self._refresh_queue_ui()

    def get_queue(self) -> List[tuple]:
        """Get the current queue."""
        return self._queue_items.copy()

    def clear_queue(self):
        """Clear the queue."""
        self._queue_items.clear()
        self._refresh_queue_ui()

    def _refresh_queue_ui(self):
        """Refresh the queue list UI."""
        # Clear existing items
        while self.queue_list.count():
            item = self.queue_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Hide/show empty label
        self.queue_empty_label.setVisible(len(self._queue_items) == 0)

        # Add new items
        for i, (file_path, title) in enumerate(self._queue_items):
            item_widget = QueueItem(i, file_path, title)
            item_widget.remove_clicked.connect(self._on_queue_item_removed)
            item_widget.play_clicked.connect(self._on_queue_item_clicked)
            self.queue_list.addWidget(item_widget)

        # Add stretch
        self.queue_list.addStretch()

    def _on_queue_item_clicked(self, index: int):
        """Handle queue item click."""
        self.queue_item_selected.emit(index)

    def _on_queue_item_removed(self, index: int):
        """Handle queue item removal."""
        self.remove_from_queue(index)
        self.queue_item_removed.emit(index)
