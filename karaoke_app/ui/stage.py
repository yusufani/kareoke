"""
The stage — the big area the singer actually looks at.

It has two faces and a switch between them:

* **Lyrics.** The whole sheet scrolls past, the line being sung held near the
  middle and lit word by word, the lines around it dimmed so you can read ahead
  and see where you are in the song.
* **Video.** The original upload, muted, with our separated stems providing the
  audio. Used automatically when no lyrics exist anywhere, and available on
  demand for any song whose video has been downloaded.

LRCLIB timestamps describe the studio recording, so an upload with an intro
scene runs early. :mod:`karaoke_app.audio.sync` detects that from the vocal stem
and the offset can also be nudged by hand from the bar at the bottom.
"""
import bisect
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient,
                           QPainter, QPen, QRadialGradient)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..audio.lyrics import LyricsResult
from ..audio.sync import apply_offset
from ..core.library import SongEntry
from . import theme
from .theme import qc
from .widgets import Badge, EqualizerBackdrop, ProgressStrip, button, label

logger = logging.getLogger(__name__)


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


class _Word:
    """One word's box within a laid-out line."""

    __slots__ = ("text", "x", "y", "advance", "weight")

    def __init__(self, text: str, x: float, y: float, advance: float,
                 weight: float):
        self.text, self.x, self.y = text, x, y
        self.advance, self.weight = advance, weight


class _Line:
    """One lyric line, wrapped and positioned within the scrolling sheet."""

    __slots__ = ("top", "height", "words", "total_weight")

    def __init__(self, top: float, height: float, words: List[_Word]):
        self.top, self.height, self.words = top, height, words
        self.total_weight = sum(w.weight for w in words) or 1.0


class LyricsView(QWidget):
    """The scrolling lyric sheet.

    The whole song is laid out once and then scrolled, rather than swapping two
    labels: a singer needs to see what is coming and how much is left, and a
    two-line window shows neither. The line being sung sits a little above
    centre — the natural reading position, and it leaves room for the next few
    lines underneath.
    """

    # How far down the viewport the active line is held.
    FOCUS = 0.42
    # Room left for the song title above and the control bar below.
    TOP_INSET = 46.0
    BOTTOM_INSET = 52.0
    # Per-frame easing towards the target scroll. Fast enough to keep up with a
    # seek, slow enough that a line change glides instead of jumping.
    EASING = 0.22

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.header = ""
        self.lines: List[Tuple[float, str]] = []
        self.index = -1
        self.progress = 0.0

        self._layout: List[_Line] = []
        self._layout_key = None
        self._font: Optional[QFont] = None
        self._scroll = 0.0
        self._target = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    # -- content ----------------------------------------------------------
    def set_lyrics(self, header: str, lines: List[Tuple[float, str]]) -> None:
        self.header = header
        self.lines = list(lines)
        self.index = -1
        self.progress = 0.0
        self._layout_key = None
        self._scroll = self._target = 0.0
        self.update()

    def set_position(self, index: int, progress: float) -> None:
        changed = index != self.index
        if not changed and abs(progress - self.progress) < 0.002:
            return
        self.index = index
        self.progress = max(0.0, min(1.0, progress))
        self.update()

    # -- layout -----------------------------------------------------------
    def _pick_font(self, width: int) -> QFont:
        size = max(19.0, min(31.0, width / 30.0))
        return theme.ui_font(size, QFont.Weight.Bold)

    def _build(self) -> None:
        key = (id(self.lines), len(self.lines), self.width(), self.height())
        if key == self._layout_key:
            return
        self._layout_key = key
        self._layout = []
        if not self.lines or self.width() < 80:
            return

        self._font = self._pick_font(self.width())
        metrics = QFontMetrics(self._font)
        space = metrics.horizontalAdvance(" ")
        row_height = metrics.height() * 1.24
        gap = row_height * 0.42
        content = self.width() - 2 * max(56, self.width() * 0.10)
        left = (self.width() - content) / 2.0

        top = 0.0
        for _, text in self.lines:
            words = text.split()
            if not words:
                # Blank lines are the instrumental gaps; keep them as breathing
                # room so the sheet's shape matches the song's.
                self._layout.append(_Line(top, row_height * 0.7, []))
                top += row_height * 0.7 + gap
                continue

            rows, row, row_width = [], [], 0.0
            for word in words:
                advance = metrics.horizontalAdvance(word)
                extra = advance if not row else space + advance
                if row and row_width + extra > content:
                    rows.append((row, row_width))
                    row, row_width = [(word, advance)], advance
                else:
                    row.append((word, advance))
                    row_width += extra
            if row:
                rows.append((row, row_width))

            boxes: List[_Word] = []
            for row_index, (row_words, width) in enumerate(rows):
                x = left + (content - width) / 2.0
                y = row_index * row_height
                for word, advance in row_words:
                    boxes.append(_Word(word, x, y, advance, float(syllables(word))))
                    x += advance + space
            height = row_height * len(rows)
            self._layout.append(_Line(top, height, boxes))
            top += height + gap

    def _scroll_target(self) -> float:
        if not self._layout:
            return 0.0
        index = max(0, min(self.index, len(self._layout) - 1))
        line = self._layout[index]
        return line.top + line.height / 2.0 - self.height() * self.FOCUS

    def advance(self) -> None:
        """Ease the sheet towards where it should be. Called once per frame."""
        self._build()
        self._target = self._scroll_target()
        delta = self._target - self._scroll
        if abs(delta) < 0.5:
            self._scroll = self._target
            return
        self._scroll += delta * self.EASING
        self.update()

    # -- painting ---------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._build()

        if not self._layout or self._font is None:
            self._draw_header(painter)
            return
        painter.setFont(self._font)
        # Keep the sheet clear of the title above and the control bar below.
        painter.setClipRect(QRectF(0, self.TOP_INSET, self.width(),
                                   max(0, self.height() - self.TOP_INSET
                                       - self.BOTTOM_INSET)))

        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0.0, QColor("#FF9EC2"))
        gradient.setColorAt(0.5, QColor("#FFFFFF"))
        gradient.setColorAt(1.0, QColor("#B7A8FF"))
        bright = QPen(QBrush(gradient), 1)
        plain = QPen(qc("#EEF0F8"))

        top_limit, bottom_limit = self.TOP_INSET, self.height() - self.BOTTOM_INSET
        for index, line in enumerate(self._layout):
            y = line.top - self._scroll
            if y + line.height < top_limit or y > bottom_limit:
                continue
            if not line.words:
                continue

            distance = abs(index - self.index)
            if index == self.index:
                self._paint_active(painter, line, y, bright, plain)
                continue

            # Read-ahead lines stay legible; the ones already sung fade further,
            # which is what tells you at a glance where you are.
            opacity = 0.34 if index > self.index else 0.20
            opacity *= max(0.30, 1.0 - distance * 0.12)
            painter.setOpacity(opacity)
            painter.setPen(plain)
            row = self._font.pointSizeF() * 1.8
            flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            for word in line.words:
                painter.drawText(
                    QRectF(word.x, y + word.y, word.advance + 2, row),
                    flags, word.text)
        painter.setOpacity(1.0)
        self._draw_edges(painter)
        self._draw_header(painter)

    def _paint_active(self, painter: QPainter, line: _Line, y: float,
                      bright: QPen, plain: QPen) -> None:
        """The line being sung: dim underneath, lit up to the wipe position."""
        row = self._font.pointSizeF() * 1.8
        target = self.progress * line.total_weight
        running = 0.0

        for word in line.words:
            box = QRectF(word.x, y + word.y, word.advance + 2, row)
            flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            painter.setOpacity(0.38)
            painter.setPen(plain)
            painter.drawText(box, flags, word.text)

            filled = (target - running) / word.weight if word.weight else 0.0
            running += word.weight
            if filled <= 0.0:
                continue

            painter.setOpacity(1.0)
            painter.setPen(bright)
            if filled >= 1.0:
                painter.drawText(box, flags, word.text)
            else:
                painter.save()
                painter.setClipRect(QRectF(box.left(), box.top(),
                                           word.advance * filled, box.height()))
                painter.drawText(box, flags, word.text)
                painter.restore()
        painter.setOpacity(1.0)

    def _draw_header(self, painter: QPainter) -> None:
        if not self.header:
            return
        painter.setClipping(False)
        painter.setOpacity(1.0)
        painter.setFont(theme.ui_font(11, QFont.Weight.Medium, spacing=30))
        painter.setPen(QPen(qc(theme.TEXT_FAINT)))
        painter.drawText(QRectF(0, 12, self.width(), 22),
                         Qt.AlignmentFlag.AlignCenter, self.header.upper())

    def _draw_edges(self, painter: QPainter) -> None:
        """Fade the sheet out where it is clipped.

        The two veils use the backdrop's own colours at those heights, so the
        lines dissolve into the background rather than meeting a hard line.
        """
        painter.setClipping(False)
        painter.setPen(Qt.PenStyle.NoPen)

        top = QLinearGradient(0, self.TOP_INSET - 12, 0, self.TOP_INSET + 34)
        top.setColorAt(0.0, QColor("#160E2A"))
        painter.setBrush(QColor("#160E2A"))
        painter.drawRect(QRectF(0, 0, self.width(), self.TOP_INSET - 12))
        top.setColorAt(1.0, QColor(22, 14, 42, 0))
        painter.setBrush(QBrush(top))
        painter.drawRect(QRectF(0, 0, self.width(), self.TOP_INSET + 34))

        base = self.height() - self.BOTTOM_INSET
        bottom = QLinearGradient(0, base - 34, 0, base + 20)
        bottom.setColorAt(0.0, QColor(8, 6, 14, 0))
        bottom.setColorAt(1.0, QColor("#080610"))
        painter.setBrush(QBrush(bottom))
        painter.drawRect(QRectF(0, base - 34, self.width(), 54))


class VideoFace(QWidget):
    """The original upload, muted, behind our own audio."""

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
        self.title = label("", 24, QFont.Weight.Bold)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle = label("", 13, color=theme.TEXT_DIM)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)

        self._failed = False
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
            self.player.errorOccurred.connect(self._on_error)
            self.available = True
        except Exception as exc:
            logger.warning("Video playback unavailable (%s); using a still stage", exc)

    def _on_error(self, error, message: str = "") -> None:
        """A codec the platform cannot decode — usually AV1. Stop trying and
        show the still card instead of hammering the decoder every frame."""
        from PySide6.QtMultimedia import QMediaPlayer
        if error == QMediaPlayer.Error.NoError:
            return
        logger.warning("Video decode failed (%s); showing a still card", message)
        self._failed = True
        if self.player is not None:
            self.player.stop()
        if self.video is not None:
            self.video.setVisible(False)
        self.subtitle.setText("This video's format can't be played here — "
                              "the audio is still separated and mixed")
        self._placeholder.setVisible(True)

    def resizeEvent(self, event) -> None:
        if self.video is not None:
            self.video.setGeometry(self.rect())
        self._placeholder.setGeometry(self.rect())

    def set_song(self, entry: Optional[SongEntry], note: str = "") -> None:
        self._failed = False
        self.title.setText(entry.title if entry else "")
        self.subtitle.setText(note or (f"{entry.display_artist} · original video"
                                       if entry else ""))
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
        # Check the codec before handing the file to the player. AV1 fails at
        # the decode level without ever emitting an error signal — the player
        # thinks the media loaded fine and just spews "no pixel format" every
        # frame — so waiting for errorOccurred does not work. This is the only
        # reliable place to stop it.
        from ..audio.youtube import is_playable_video
        if not is_playable_video(path):
            logger.info("Video %s uses a codec the player can't show; still card",
                        path.name)
            self._failed = True
            self.player.stop()
            self.player.setSource(QUrl())
            if self.video is not None:
                self.video.setVisible(False)
            self.subtitle.setText("This video's format can't be played here — "
                                  "the audio is still separated and mixed")
            self._placeholder.setVisible(True)
            return

        self._placeholder.setVisible(False)
        if self.video is not None:
            self.video.setVisible(True)
        self.player.setSource(QUrl.fromLocalFile(str(path)))

    def sync(self, position: float, playing: bool, speed: float) -> None:
        """Keep the picture on top of the audio without fighting it."""
        if self.player is None or self._failed or self.player.source().isEmpty():
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


class _StageBar(QWidget):
    """The strip along the bottom of the stage: what is showing, and the nudge."""

    faceChanged = Signal(str)          # "lyrics" | "video"
    offsetNudged = Signal(float)       # seconds to add
    videoRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(34)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.badge = Badge("", theme.GREEN)
        layout.addWidget(self.badge)

        self.lyrics_button = button("Lyrics", "BtnChip", height=26, checkable=True)
        self.lyrics_button.clicked.connect(lambda: self.faceChanged.emit("lyrics"))
        self.video_button = button("Video", "BtnChip", height=26, checkable=True)
        self.video_button.clicked.connect(self._on_video)
        layout.addWidget(self.lyrics_button)
        layout.addWidget(self.video_button)

        self.nudge_host = QWidget()
        nudge = QHBoxLayout(self.nudge_host)
        nudge.setContentsMargins(0, 0, 0, 0)
        nudge.setSpacing(4)
        earlier = button("−", "BtnChip", height=26, width=26,
                         tooltip="Lyrics are late — pull them earlier (]).")
        earlier.clicked.connect(lambda: self.offsetNudged.emit(-0.25))
        self.readout = label("sync 0.00s", 10.5, color=theme.TEXT_DIM, mono=True)
        self.readout.setToolTip("Timing offset applied to the lyrics for this song")
        later = button("+", "BtnChip", height=26, width=26,
                       tooltip="Lyrics are early — push them later ([).")
        later.clicked.connect(lambda: self.offsetNudged.emit(0.25))
        nudge.addWidget(earlier)
        nudge.addWidget(self.readout)
        nudge.addWidget(later)
        layout.addWidget(self.nudge_host)
        layout.addStretch(1)

        self._has_video = False

    def _on_video(self) -> None:
        self.faceChanged.emit("video") if self._has_video else self.videoRequested.emit()

    def set_state(self, face: str, has_lyrics: bool, has_video: bool,
                  badge_text: str, badge_colour: str, offset: float,
                  auto: bool) -> None:
        self._has_video = has_video
        self.badge.setText(badge_text)
        self.badge.set_color(badge_colour)
        self.badge.setVisible(bool(badge_text))
        self.badge.adjustSize()

        self.lyrics_button.setVisible(has_lyrics)
        self.lyrics_button.setChecked(face == "lyrics")
        self.video_button.setVisible(True)
        self.video_button.setChecked(face == "video")
        self.video_button.setText("Video" if has_video else "Get video")
        self.video_button.setToolTip(
            "Show the original video instead of the lyrics" if has_video else
            "Download the original video for this song and show it here")

        self.nudge_host.setVisible(has_lyrics and face == "lyrics")
        suffix = "  auto" if auto and offset else ""
        self.readout.setText(f"sync {offset:+.2f}s{suffix}")
        self.readout.setStyleSheet(
            f"color: {theme.GREEN if offset else theme.TEXT_DIM}; background: transparent;")


class Stage(QWidget):
    """Everything inside the big left-hand area."""

    offsetChanged = Signal(str, float)   # song id, new offset
    videoRequested = Signal(str)         # song id

    SECONDS_PER_SYLLABLE = 0.34

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumWidth(420)
        self._entry: Optional[SongEntry] = None
        self._lyrics: Optional[LyricsResult] = None
        self._times: List[float] = []
        self._duration = 0.0
        self._index = -2            # -2 means "nothing rendered yet"
        self._line_start = 0.0
        self._line_span = 0.0
        self._face = "idle"
        self._auto_offset = False

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

        self.bar = _StageBar(self)
        self.bar.faceChanged.connect(self.show_face)
        self.bar.offsetNudged.connect(self.nudge_offset)
        self.bar.videoRequested.connect(self._request_video)
        self.bar.setVisible(False)

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

        self.bar.setGeometry(14, rect.height() - 44, max(360, rect.width() - 28), 34)
        self.rec_pill.move(14, 14)
        self.toast.adjustSize()
        self.toast.move(rect.width() - self.toast.width() - 14, 14)

    # -- content ----------------------------------------------------------
    def set_song(self, entry: Optional[SongEntry], lyrics: Optional[LyricsResult],
                 duration: float) -> None:
        self._entry = entry
        self._lyrics = lyrics
        self._duration = max(duration, 0.1)
        self._index = -2
        self._times = []
        self._auto_offset = bool(lyrics and lyrics.offset)

        if entry is None:
            self.show_face("idle")
            self.bar.setVisible(False)
            self.video_face.set_song(None)
            return

        self.bar.setVisible(True)
        if lyrics is not None and lyrics.found:
            self._rebuild_lines()
            self.show_face("lyrics")
        else:
            self.video_face.set_song(
                entry, "" if entry.has_video else
                f"{entry.display_artist} · no lyrics found and no video yet")
            self.show_face("video")
        self._refresh_bar()

    def _rebuild_lines(self) -> None:
        """Apply the offset and work out when each line is sung."""
        lyrics = self._lyrics
        if lyrics is None or not lyrics.found:
            return
        shifted = apply_offset(lyrics.lines, lyrics.offset)
        if lyrics.synced:
            self._times = [t for t, _ in shifted]
        else:
            # No timings at all: pace the lines evenly across the song.
            count = len(shifted)
            lead = min(6.0, self._duration * 0.04)
            span = max(self._duration - lead - 4.0, 1.0)
            self._times = [lead + span * i / max(count, 1) for i in range(count)]

        header = ""
        if self._entry is not None:
            header = f"{self._entry.title} — {self._entry.display_artist}"
        self.lyrics_view.set_lyrics(header, shifted)
        self._index = -2

    # -- faces ------------------------------------------------------------
    def show_face(self, face: str) -> None:
        if face == "video" and not (self._entry and self._entry.has_video) \
                and self._lyrics and self._lyrics.found:
            return
        self._face = face
        self.lyrics_view.setVisible(face == "lyrics")
        self.video_face.setVisible(face == "video")
        self.idle.setVisible(face == "idle")
        if face == "video":
            self.video_face.set_song(
                self._entry, "" if (self._entry and self._entry.has_video) else
                "the video for this song has not been downloaded")
        else:
            self.video_face.stop()
        self._refresh_bar()

    def _request_video(self) -> None:
        if self._entry is not None:
            self.videoRequested.emit(self._entry.id)

    def _refresh_bar(self) -> None:
        entry, lyrics = self._entry, self._lyrics
        if entry is None:
            return
        has_lyrics = bool(lyrics and lyrics.found)
        if not has_lyrics:
            text, colour = ("▶  Lyrics not found — playing video"
                            if entry.has_video else
                            "▶  No lyrics and no video for this track"), theme.TEXT_DIM
        elif lyrics.synced:
            text, colour = "≡  Synced lyrics", theme.GREEN
        else:
            text, colour = "≈  Lyrics (timing estimated)", theme.BLUE
        self.bar.set_state(self._face, has_lyrics, entry.has_video, text, colour,
                           lyrics.offset if lyrics else 0.0, self._auto_offset)

    # -- offset -----------------------------------------------------------
    def invalidate(self) -> None:
        """Force the next tick to repaint, after a seek or a song change."""
        self._index = -2

    def nudge_offset(self, delta: float) -> None:
        if self._lyrics is None or not self._lyrics.found or self._entry is None:
            return
        self._lyrics.offset = round(self._lyrics.offset + delta, 2)
        self._auto_offset = False
        self._rebuild_lines()
        self._refresh_bar()
        self.offsetChanged.emit(self._entry.id, self._lyrics.offset)

    # -- per-frame --------------------------------------------------------
    def tick(self, position: float, playing: bool, speed: float) -> None:
        if self._entry is None:
            return
        if self.video_face.isVisible():
            self.video_face.sync(position, playing, speed)
        else:
            self._render(position)
            self.lyrics_view.advance()
        self.backdrop.bars.set_level(0.85 if playing else 0.3)

    def _render(self, position: float) -> None:
        if not self._times or self._lyrics is None:
            return
        index = bisect.bisect_right(self._times, position) - 1
        if index != self._index:
            self._index = index
            text = self._lyrics.lines[index][1] if 0 <= index < len(self._lyrics.lines) else ""
            self._line_start, self._line_span = self._span_for(index, text)
        progress = ((position - self._line_start) / self._line_span
                    if self._line_span > 0 else 0.0)
        self.lyrics_view.set_position(index, progress)

    def _span_for(self, index: int, text: str) -> Tuple[float, float]:
        """How long the singer actually has to get through one line.

        The gap to the next timestamp is an upper bound, not the answer: before
        an instrumental break it can be twenty seconds, and a highlight crawling
        across four words for that long is useless. So the line gets whichever
        is shorter — the gap, or the time its syllables need.
        """
        if not (0 <= index < len(self._times)):
            return 0.0, 0.0
        start = self._times[index]
        gap = (self._times[index + 1] - start if index + 1 < len(self._times)
               else max(2.0, self._duration - start))
        needed = sum(syllables(w) for w in text.split()) * self.SECONDS_PER_SYLLABLE
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
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(310, 50)
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
