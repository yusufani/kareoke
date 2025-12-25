"""
Notification Toast Widget
Displays temporary notifications with fade animation.
"""
import logging
from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor


logger = logging.getLogger(__name__)


class NotificationToast(QWidget):
    """A toast notification that appears and fades away."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        self._setup_ui()
        self._setup_animation()
        
        # Hide timer
        self.hide_timer = QTimer(self)
        self.hide_timer.timeout.connect(self._start_fade_out)
        self.hide_timer.setSingleShot(True)

    def _setup_ui(self):
        """Setup the toast UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("""
            QLabel {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(29, 185, 84, 0.95),
                    stop:1 rgba(30, 215, 96, 0.95)
                );
                color: #000000;
                font-size: 14px;
                font-weight: 600;
                padding: 16px 32px;
                border-radius: 8px;
            }
        """)
        layout.addWidget(self.label)

    def _setup_animation(self):
        """Setup fade animations."""
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(1.0)
        
        # Fade in animation
        self.fade_in_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_in_anim.setDuration(200)
        self.fade_in_anim.setStartValue(0.0)
        self.fade_in_anim.setEndValue(1.0)
        self.fade_in_anim.setEasingCurve(QEasingCurve.OutCubic)
        
        # Fade out animation
        self.fade_out_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out_anim.setDuration(300)
        self.fade_out_anim.setStartValue(1.0)
        self.fade_out_anim.setEndValue(0.0)
        self.fade_out_anim.setEasingCurve(QEasingCurve.InCubic)
        self.fade_out_anim.finished.connect(self.hide)

    def show_message(self, message: str, duration: int = 3000, style: str = "success"):
        """
        Show a toast notification.
        
        Args:
            message: Message to display
            duration: Duration in milliseconds (default 3000)
            style: 'success', 'info', 'warning', or 'error'
        """
        self.label.setText(message)
        
        # Apply style
        styles = {
            "success": """
                QLabel {
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba(29, 185, 84, 0.95),
                        stop:1 rgba(30, 215, 96, 0.95)
                    );
                    color: #000000;
                    font-size: 14px;
                    font-weight: 600;
                    padding: 16px 32px;
                    border-radius: 8px;
                }
            """,
            "info": """
                QLabel {
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba(52, 152, 219, 0.95),
                        stop:1 rgba(74, 174, 241, 0.95)
                    );
                    color: #ffffff;
                    font-size: 14px;
                    font-weight: 600;
                    padding: 16px 32px;
                    border-radius: 8px;
                }
            """,
            "warning": """
                QLabel {
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba(241, 196, 15, 0.95),
                        stop:1 rgba(243, 208, 63, 0.95)
                    );
                    color: #000000;
                    font-size: 14px;
                    font-weight: 600;
                    padding: 16px 32px;
                    border-radius: 8px;
                }
            """,
            "error": """
                QLabel {
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba(231, 76, 60, 0.95),
                        stop:1 rgba(241, 106, 90, 0.95)
                    );
                    color: #ffffff;
                    font-size: 14px;
                    font-weight: 600;
                    padding: 16px 32px;
                    border-radius: 8px;
                }
            """
        }
        self.label.setStyleSheet(styles.get(style, styles["success"]))
        
        # Position at bottom center of parent
        self._position_toast()
        
        # Show with fade in
        self.show()
        self.raise_()
        self.fade_in_anim.start()
        
        # Start hide timer
        self.hide_timer.start(duration)
        
        logger.debug(f"Toast notification: {message}")

    def _position_toast(self):
        """Position the toast at the bottom center of the parent window."""
        if self.parent():
            parent = self.parent()
            self.adjustSize()
            x = (parent.width() - self.width()) // 2
            y = parent.height() - self.height() - 100
            self.move(x, y)

    def _start_fade_out(self):
        """Start fade out animation."""
        self.fade_out_anim.start()
