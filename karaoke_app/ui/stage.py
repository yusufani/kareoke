"""
The stage — the big area the singer actually looks at.

It has three faces and picks one per song:

* **Synced lyrics.** The good case. Time-stamped lines from LRCLIB, the current
  one large and gradient-filled, the next one dim underneath.
* **Unsynced lyrics.** Words but no timings, so lines are paced evenly across
  the song. An estimate, and labelled as one.
* **Video.** No lyrics anywhere, so the original YouTube video plays instead —
  muted, with our separated stems providing the audio, and its position nudged
  back into line whenever it drifts.

Overlays (record indicator, background-download toast, source badge) float over
whichever face is showing.
"""
import bisect
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient,
                           QPainter, QPen, QRadialGradient)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..audio.lyrics import LyricsResult
from ..core.library import SongEntry
from . import theme
from .theme import qc
from .widgets import Badge, EqualizerBackdrop, ProgressStrip, label

logger = logging.getLogger(__name__)


class _Backdrop(QWidget):
    """Radial wash plus animated bars, shared by every stage face."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.bars = EqualizerBackdrop(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def resizeEvent(self, event) -> None:
        self.bars.setGeometry(self.rect())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        gradient = QRadialGradient(self.width() / 2, 0,
                                   max(self.width(), self.height()) * 1.2)
        gradient.setColorAt(0.0, QColor("#1A1030"))
        gradient.setColorAt(0.55, QColor("#0B0714"))
        gradient.setColorAt(1.0, QColor("#060409"))
        painter.fillRect(self.rect(), QBrush(gradient))


# Vowels of both languages the app is used in, plus the accented forms that
# survive in loan words. Counting vowel *groups* gives a syllable estimate that
# is exact for Turkish and close enough for English.
_VOWELS = set("aeıioöuüâîûAEIİOÖUÜÂÎÛ" + "aeiouyAEIOUY")


def syllables(word: str) -> int:
    """Rough syllable count — how long a word takes to sing."""
    count, in_vowel = 0, False
    for character in word:
        is_vowel = character in _VOWELS
        if is_vowel and not in_vowel:
            count += 1
        in_vowel = is_vowel
    return max(1, count)


class LyricsView(QWidget):
    """Paints the current and next lyric line, wiping through it word by word.

    LRCLIB timestamps a *line*, not a word, so the words are spread across the
    line's own span weighted by syllable count — a three-syllable word gets
    three times the time of a one-syllable word. That is an estimate, but it is
    the estimate a singer's eye expects, and it turns a static line into the
    moving highlight that makes karaoke readable.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.header = ""
        self.current = ""
        self.upcoming = ""
        self.progress = 0.0          # 0..1 through the current line
        self._layout_key = None
        self._layout: List = []
        self._layout_font: Optional[QFont] = None
        self._weights: List[float] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_lines(self, header: str, current: str, upcoming: str) -> None:
        if (header, current, upcoming) == (self.header, self.current, self.upcoming):
            return
        self.header, self.current, self.upcoming = header, current, upcoming
        self._layout_key = None
        self.update()

    def set_progress(self, progress: float) -> None:
        progress = max(0.0, min(1.0, progress))
        if abs(progress - self.progress) < 0.002:
            return
        self.progress = progress
        self.update()

    # -- layout -----------------------------------------------------------
    def _fit(self, text: str, box: QRectF, start: float, minimum: float,
             weight: int) -> QFont:
        """Largest font size at which ``text`` fits in ``box``."""
        size = start
        while size > minimum:
            font = theme.ui_font(size, weight)
            metrics = QFontMetrics(font)
            bounds = metrics.boundingRect(
                box.toRect(),
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), text)
            if bounds.height() <= box.height() and bounds.width() <= box.width():
                return font
            size -= 2
        return theme.ui_font(minimum, weight)

    def _build_layout(self, box: QRectF) -> None:
        """Wrap the current line into rows of positioned words.

        Cached: the wipe moves every frame but the words do not, and laying out
        text thirty times a second for no reason is exactly the kind of work
        that should not compete with the audio thread.
        """
        key = (self.current, round(box.width()), round(box.height()))
        if key == self._layout_key:
            return
        self._layout_key = key
        self._layout = []
        self._weights = []

        words = self.current.split()
        if not words:
            return

        font = self._fit(self.current, box, 46, 20, QFont.Weight.Bold)
        self._layout_font = font
        metrics = QFontMetrics(font)
        space = metrics.horizontalAdvance(" ")
        line_height = metrics.height() * 1.18

        rows, row, row_width = [], [], 0.0
        for word in words:
            advance = metrics.horizontalAdvance(word)
            extra = advance if not row else space + advance
            if row and row_width + extra > box.width():
                rows.append((row, row_width))
                row, row_width = [(word, advance)], advance
            else:
                row.append((word, advance))
                row_width += extra
        if row:
            rows.append((row, row_width))

        total_height = line_height * len(rows)
        top = box.top() + (box.height() - total_height) / 2.0
        for index, (row_words, width) in enumerate(rows):
            x = box.left() + (box.width() - width) / 2.0
            y = top + index * line_height
            for word, advance in row_words:
                self._layout.append((word, x, y, advance, line_height))
                self._weights.append(float(syllables(word)))
                x += advance + space

    def _wipe_position(self):
        """Where the highlight has reached: ``(word_index, fraction)``."""
        if not self._weights:
            return 0, 0.0
        total = sum(self._weights)
        target = self.progress * total
        running = 0.0
        for index, weight in enumerate(self._weights):
            if running + weight >= target:
                return index, (target - running) / weight if weight else 0.0
            running += weight
        return len(self._weights) - 1, 1.0

    # -- painting ---------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        width, height = self.width(), self.height()
        margin = max(48, width * 0.08)
        content = QRectF(margin, 0, width - margin * 2, height)

        if self.header:
            painter.setFont(theme.ui_font(11.5, QFont.Weight.Medium, spacing=30))
            painter.setPen(QPen(qc(theme.TEXT_FAINT)))
            painter.drawText(QRectF(content.x(), height * 0.20, content.width(), 26),
                             Qt.AlignmentFlag.AlignCenter, self.header.upper())

        main_box = QRectF(content.x(), height * 0.30, content.width(), height * 0.30)
        if self.current:
            self._build_layout(main_box)
            self._paint_current(painter, main_box)

        next_box = QRectF(content.x(), height * 0.62, content.width(), height * 0.18)
        if self.upcoming:
            painter.setFont(self._fit(self.upcoming, next_box, 24, 13,
                                      QFont.Weight.Medium))
            painter.setPen(QPen(qc("rgba(238,240,248,0.35)")))
            painter.drawText(next_box,
                             int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                             self.upcoming)

    def _paint_current(self, painter: QPainter, box: QRectF) -> None:
        if not self._layout or self._layout_font is None:
            return
        painter.setFont(self._layout_font)
        gradient = QLinearGradient(box.left(), 0, box.right(), 0)
        gradient.setColorAt(0.0, QColor("#FF9EC2"))
        gradient.setColorAt(0.5, QColor("#FFFFFF"))
        gradient.setColorAt(1.0, QColor("#B7A8FF"))

        active, fraction = self._wipe_position()
        metrics = QFontMetrics(self._layout_font)

        for index, (word, x, y, advance, line_height) in enumerate(self._layout):
            rect = QRectF(x, y, advance, line_height)
            baseline = QRectF(x, y, advance, line_height)

            # Everything is drawn dim first, so the singer can read ahead.
            painter.setOpacity(0.30)
            painter.setPen(QPen(QBrush(gradient), 1))
            painter.drawText(baseline, int(Qt.AlignmentFlag.AlignVCenter
                                           | Qt.AlignmentFlag.AlignLeft), word)

            if index > active:
                continue
            painter.setOpacity(1.0)
            if index < active:
                painter.drawText(baseline, int(Qt.AlignmentFlag.AlignVCenter
                                               | Qt.AlignmentFlag.AlignLeft), word)
            else:
                # The word being sung fills left to right, so the highlight
                # sweeps through it rather than snapping on.
                painter.save()
                painter.setClipRect(QRectF(rect.left(), rect.top(),
                                           advance * fraction, rect.height()))
                painter.drawText(baseline, int(Qt.AlignmentFlag.AlignVCenter
                                               | Qt.AlignmentFlag.AlignLeft), word)
                painter.restore()
        painter.setOpacity(1.0)


class VideoFace(QWidget):
    """The fallback face: the original video, muted, behind our own audio."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.available = False
        self.player = None
        self.video = None
        self._audio = None
        self._placeholder = QWidget(self)

        layout = QVBoxLayout(self._placeholder)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)
        self.title = label("", 26, QFont.Weight.Bold)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle = label("", 14, color=theme.TEXT_DIM)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)

        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget

            self.video = QVideoWidget(self)
            self.video.setStyleSheet("background: #060409;")
            self.player = QMediaPlayer(self)
            # Silent: the mix the singer hears comes from our own engine, and
            # the video's own audio track would double every word.
            self._audio = QAudioOutput(self)
            self._audio.setVolume(0.0)
            self.player.setAudioOutput(self._audio)
            self.player.setVideoOutput(self.video)
            self.player.setLoops(1)
            self.available = True
        except Exception as exc:
            logger.warning("Video playback unavailable (%s); using a still stage", exc)

    def resizeEvent(self, event) -> None:
        if self.video is not None:
            self.video.setGeometry(self.rect())
        self._placeholder.setGeometry(self.rect())

    def set_song(self, entry: Optional[SongEntry]) -> None:
        self.title.setText(entry.title if entry else "")
        self.subtitle.setText(f"{entry.display_artist} · original video" if entry else "")
        path = Path(entry.video_path) if entry and entry.has_video else None
        if self.player is None:
            self._placeholder.setVisible(True)
            return
        if path is None:
            self.player.stop()
            self.player.setSource(QUrl())
            if self.video is not None:
                self.video.setVisible(False)
            self._placeholder.setVisible(True)
            return
        self._placeholder.setVisible(False)
        if self.video is not None:
            self.video.setVisible(True)
        self.player.setSource(QUrl.fromLocalFile(str(path)))

    def sync(self, position: float, playing: bool, speed: float) -> None:
        """Keep the picture on top of the audio without fighting it."""
        if self.player is None or self.player.source().isEmpty():
            return
        from PySide6.QtMultimedia import QMediaPlayer

        if abs(self.player.playbackRate() - speed) > 0.01:
            self.player.setPlaybackRate(speed)
        state = self.player.playbackState()
        if playing and state != QMediaPlayer.PlaybackState.PlayingState:
            self.player.play()
        elif not playing and state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()

        target = int(position * 1000)
        if abs(self.player.position() - target) > 400:
            self.player.setPosition(target)

    def stop(self) -> None:
        if self.player is not None:
            self.player.stop()


class Stage(QWidget):
    """Everything inside the big left-hand area."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumWidth(420)
        self._entry: Optional[SongEntry] = None
        self._lyrics: Optional[LyricsResult] = None
        self._times: List[float] = []
        self._synced = False
        self._duration = 0.0
        self._index = -1
        self._line_start = 0.0
        self._line_span = 0.0

        self.backdrop = _Backdrop(self)
        self.lyrics_view = LyricsView(self)
        self.video_face = VideoFace(self)
        self.video_face.setVisible(False)

        self.idle = QWidget(self)
        idle_layout = QVBoxLayout(self.idle)
        idle_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        idle_layout.setSpacing(10)
        headline = label("Nothing loaded", 26, QFont.Weight.Bold)
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = label("Add a song and Encore will look up its lyrics automatically",
                     13.5, color=theme.TEXT_DIM)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        idle_layout.addWidget(headline)
        idle_layout.addWidget(hint)

        # -- overlays
        self.source_badge = Badge("", theme.GREEN, self)
        self.source_badge.setVisible(False)

        self.rec_pill = _RecordPill(self)
        self.rec_pill.setVisible(False)

        self.toast = _DownloadToast(self)
        self.toast.setVisible(False)

    # -- layout -----------------------------------------------------------
    def resizeEvent(self, event) -> None:
        rect = self.rect()
        self.backdrop.setGeometry(rect)
        self.lyrics_view.setGeometry(rect)
        self.video_face.setGeometry(rect)
        self.idle.setGeometry(rect)

        self.source_badge.adjustSize()
        self.source_badge.move(14, rect.height() - self.source_badge.height() - 14)
        self.rec_pill.move(14, 14)
        self.toast.adjustSize()
        self.toast.move(rect.width() - self.toast.width() - 14, 14)

    # -- content ----------------------------------------------------------
    def set_song(self, entry: Optional[SongEntry], lyrics: Optional[LyricsResult],
                 duration: float) -> None:
        self._entry = entry
        self._lyrics = lyrics
        self._duration = max(duration, 0.1)
        self._index = -1
        self._synced = bool(lyrics and lyrics.synced)
        self._times = []

        if entry is None:
            self._show_face("idle")
            self.source_badge.setVisible(False)
            self.video_face.set_song(None)
            return

        if lyrics is not None and lyrics.found:
            if self._synced:
                self._times = [t for t, _ in lyrics.lines]
                self.source_badge.setText("≡  Synced lyrics")
                self.source_badge.set_color(theme.GREEN)
            else:
                # Pace the lines evenly. It is a guess, and it says so.
                count = len(lyrics.lines)
                lead = min(6.0, self._duration * 0.04)
                span = max(self._duration - lead - 4.0, 1.0)
                self._times = [lead + span * i / max(count, 1) for i in range(count)]
                self.source_badge.setText("≈  Lyrics (timing estimated)")
                self.source_badge.set_color(theme.BLUE)
            self.video_face.set_song(None)
            self._show_face("lyrics")
        else:
            self.source_badge.setText("▶  Lyrics not found — playing video"
                                      if entry.has_video else
                                      "▶  No lyrics and no video for this track")
            self.source_badge.set_color(theme.TEXT_DIM)
            self.video_face.set_song(entry)
            self._show_face("video")

        self.source_badge.setVisible(True)
        self.source_badge.adjustSize()
        self.resizeEvent(None)
        self._render_lines(0.0)

    def _show_face(self, face: str) -> None:
        self.lyrics_view.setVisible(face == "lyrics")
        self.video_face.setVisible(face == "video")
        self.idle.setVisible(face == "idle")
        if face != "video":
            self.video_face.stop()

    # -- per-frame updates ------------------------------------------------
    def tick(self, position: float, playing: bool, speed: float) -> None:
        if self._entry is None:
            return
        if self.video_face.isVisible():
            self.video_face.sync(position, playing, speed)
        else:
            self._render_lines(position)
        self.backdrop.bars.set_level(0.85 if playing else 0.3)

    # A comfortable singing pace: about three syllables a second.
    SECONDS_PER_SYLLABLE = 0.34

    def _render_lines(self, position: float) -> None:
        if not self._times or self._lyrics is None:
            return
        index = bisect.bisect_right(self._times, position) - 1
        lines = self._lyrics.lines

        if index != self._index:
            self._index = index
            current = lines[index][1] if 0 <= index < len(lines) else ""
            upcoming = lines[index + 1][1] if 0 <= index + 1 < len(lines) else ""
            if index < 0:
                current, upcoming = "", lines[0][1] if lines else ""
            header = ""
            if self._entry is not None:
                header = f"{self._entry.title} — {self._entry.display_artist}"
            self.lyrics_view.set_lines(header, current or "♪", upcoming)
            self._line_start, self._line_span = self._span_for(index, current)

        if self._line_span > 0:
            self.lyrics_view.set_progress((position - self._line_start)
                                          / self._line_span)
        else:
            self.lyrics_view.set_progress(0.0)

    def _span_for(self, index: int, text: str) -> Tuple[float, float]:
        """How long the singer actually has to get through one line.

        The gap to the next timestamp is an upper bound, not the answer: before
        an instrumental break it can be twenty seconds, and a highlight crawling
        across four words for twenty seconds is useless. So the line is given
        whichever is shorter — the gap, or the time its syllables need.
        """
        if not (0 <= index < len(self._times)):
            return 0.0, 0.0
        start = self._times[index]
        gap = (self._times[index + 1] - start if index + 1 < len(self._times)
               else max(2.0, self._duration - start))
        needed = sum(syllables(word) for word in text.split()) * self.SECONDS_PER_SYLLABLE
        return start, max(0.05, min(gap, max(0.8, needed)))


class _RecordPill(QWidget):
    """Blinking REC badge with the take timer."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self._on = True
        self._time = "0:00"
        self._ducking = True
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._blink)

    def set_state(self, seconds: float, ducking: bool) -> None:
        self._time = f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
        self._ducking = ducking
        self.setFixedWidth(248 if ducking else 118)
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _blink(self) -> None:
        self._on = not self._on
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(QPen(qc("rgba(255,69,69,0.45)"), 1))
        painter.setBrush(qc("rgba(255,69,69,0.14)"))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 15, 15)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qc(theme.RED, 1.0 if self._on else 0.35))
        painter.drawEllipse(QRectF(11, self.height() / 2 - 4, 8, 8))

        painter.setFont(theme.ui_font(11.5, QFont.Weight.Bold, spacing=8))
        painter.setPen(QPen(qc(theme.RED_LIGHT)))
        painter.drawText(QRectF(25, 0, 34, self.height()),
                         Qt.AlignmentFlag.AlignVCenter, "REC")

        painter.setFont(theme.mono_font(11))
        painter.setPen(QPen(qc("#FFC7C7")))
        painter.drawText(QRectF(59, 0, 46, self.height()),
                         Qt.AlignmentFlag.AlignVCenter, self._time)

        if self._ducking:
            painter.setPen(QPen(qc("rgba(255,255,255,0.15)"), 1))
            painter.drawLine(105, 8, 105, self.height() - 8)
            painter.setFont(theme.ui_font(9.5))
            painter.setPen(QPen(qc(theme.TEXT_DIM)))
            painter.drawText(QRectF(112, 0, 132, self.height()),
                             Qt.AlignmentFlag.AlignVCenter, "music ducked −6 dB")


class _DownloadToast(QWidget):
    """Top-right pill showing whatever is being prepared in the background."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(310, 50)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"background: rgba(11,13,20,0.88);"
            f"border: 1px solid {theme.BORDER_STRONG};"
            "border-radius: 10px;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 12, 7)
        layout.setSpacing(10)

        icon = QLabel("♪")
        icon.setFixedSize(26, 26)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #2A1B3D, stop:1 #1B2A3D);"
            "border: none; border-radius: 6px; font-size: 12px;")
        layout.addWidget(icon)

        column = QVBoxLayout()
        column.setSpacing(3)
        column.setContentsMargins(0, 0, 0, 0)
        self.title = label("", 11.5, QFont.Weight.DemiBold)
        self.title.setStyleSheet("border: none; background: transparent;")
        self.title.setFixedWidth(244)
        column.addWidget(self.title)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 0, 0, 0)
        self.strip = ProgressStrip(theme.BLUE, 3)
        self.strip.setFixedWidth(104)
        self.strip.setStyleSheet("border: none; background: transparent;")
        self.stage_label = label("", 10, color=theme.TEXT_DIM, mono=True)
        self.stage_label.setStyleSheet(
            f"border: none; background: transparent; color: {theme.TEXT_DIM};")
        row.addWidget(self.strip)
        row.addWidget(self.stage_label, 1)
        column.addLayout(row)
        layout.addLayout(column)

    def show_job(self, title: str, fraction: float, stage_label: str,
                 color: str) -> None:
        metrics = QFontMetrics(self.title.font())
        self.title.setText(metrics.elidedText(title, Qt.TextElideMode.ElideRight, 240))
        self.strip.setProgress(fraction, color)
        self.stage_label.setText(stage_label)
