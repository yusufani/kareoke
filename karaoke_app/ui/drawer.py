"""
The song drawer: YouTube search on one tab, the prepared library on the other.

It slides over the stage without touching playback — searching, downloading and
separating all happen behind whoever is currently singing.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..audio.youtube import SearchResult
from ..core.jobs import STAGE_DOWNLOAD, STAGE_LYRICS, STAGE_SEPARATE
from ..core.library import (LYRICS_NONE, LYRICS_PLAIN, LYRICS_SYNCED, SongEntry)
from . import theme
from .theme import qc
from .widgets import ElidedLabel, ProgressStrip, Thumbnail, button, label

logger = logging.getLogger(__name__)

STAGE_COLORS = {
    STAGE_LYRICS: theme.GREEN,
    STAGE_DOWNLOAD: theme.BLUE,
    STAGE_SEPARATE: "#B98CFF",
}


class ResultCard(QWidget):
    """One YouTube search hit, with its own prepare-progress state machine."""

    prepare = Signal(object)      # SearchResult
    playNow = Signal(str)         # song id
    queueIt = Signal(str)

    def __init__(self, item: SearchResult, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(11)

        self.thumb = Thumbnail(104, 58, item.video_id)
        self.thumb.set_overlay(item.duration_str)
        layout.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        column.setSpacing(2)
        self.title = QLabel(item.title)
        self.title.setWordWrap(True)
        self.title.setFont(theme.ui_font(12.5, QFont.Weight.DemiBold))
        self.title.setFixedHeight(36)          # two lines, descenders intact
        self.title.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored,
                                 QSizePolicy.Policy.Fixed)
        column.addWidget(self.title)

        meta = " · ".join(part for part in (item.channel, item.views_str) if part)
        column.addWidget(label(meta, 10.5, color="rgba(238,240,248,0.45)"))
        column.addStretch(1)

        self.action_host = QWidget()
        self.action_layout = QHBoxLayout(self.action_host)
        self.action_layout.setContentsMargins(0, 6, 0, 0)
        self.action_layout.setSpacing(6)
        column.addWidget(self.action_host)
        layout.addLayout(column, 1)

        self.download = button("↓ Download", "BtnPill", height=24)
        self.download.clicked.connect(lambda: self.prepare.emit(self.item))

        self.strip = ProgressStrip(theme.BLUE, 4)
        self.stage_label = label("", 10, QFont.Weight.DemiBold, theme.BLUE)
        # One combined readiness caption: the row is only ~280 px wide, and
        # "stems ready" plus a lyrics badge plus two buttons will not fit.
        self.ready_label = label("✓ Ready", 10, QFont.Weight.Bold, theme.GREEN)
        self.play_button = button("▶ Play", "BtnAccent", height=24)
        self.play_button.setFont(theme.ui_font(11, QFont.Weight.Bold))
        self.play_button.clicked.connect(lambda: self.playNow.emit(self.item.video_id))
        self.queue_button = button("+ Queue", "BtnPillGhost", height=24)
        self.queue_button.clicked.connect(lambda: self.queueIt.emit(self.item.video_id))
        self.lyrics_label = label("", 10, color=theme.TEXT_DIM)

        for widget in (self.download, self.strip, self.stage_label,
                       self.ready_label, self.play_button, self.queue_button,
                       self.lyrics_label):
            self.action_layout.addWidget(widget)
        self.action_layout.addStretch(1)
        self.set_idle()

    def _only(self, *visible: QWidget) -> None:
        for index in range(self.action_layout.count()):
            widget = self.action_layout.itemAt(index).widget()
            if widget is not None:
                widget.setVisible(widget in visible)

    def set_idle(self) -> None:
        self._only(self.download)

    def set_busy(self, stage: str, fraction: float, text: str) -> None:
        color = STAGE_COLORS.get(stage, theme.BLUE)
        self.strip.setProgress(fraction, color)
        self.strip.setFixedWidth(120)
        self.stage_label.setText(text)
        self.stage_label.setStyleSheet(f"color: {color};")
        self._only(self.strip, self.stage_label)

    def set_ready(self, entry: Optional[SongEntry]) -> None:
        if entry is not None:
            self.ready_label.setText(f"✓ {_lyrics_caption(entry)}")
            self.ready_label.setStyleSheet(f"color: {_lyrics_color(entry)};")
            self.ready_label.setToolTip("Stems separated and cached")
        self._only(self.ready_label, self.play_button, self.queue_button)

    def set_failed(self, message: str) -> None:
        self.stage_label.setText(message[:48] or "Failed")
        self.stage_label.setStyleSheet(f"color: {theme.RED_LIGHT};")
        self._only(self.stage_label, self.download)


def _lyrics_caption(entry: SongEntry) -> str:
    return {LYRICS_SYNCED: "synced lyrics",
            LYRICS_PLAIN: "lyrics (est. timing)",
            LYRICS_NONE: "video stage"}.get(entry.lyrics_state, "ready")


def _lyrics_color(entry: SongEntry) -> str:
    return {LYRICS_SYNCED: theme.GREEN,
            LYRICS_PLAIN: theme.BLUE}.get(entry.lyrics_state,
                                          "rgba(238,240,248,0.45)")


class LibraryRow(QWidget):
    """One prepared song."""

    playNow = Signal(str)
    queueIt = Signal(str)
    removed = Signal(str)

    def __init__(self, entry: SongEntry, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(11)

        self.thumb = Thumbnail(38, 38, entry.id)
        layout.addWidget(self.thumb)

        column = QVBoxLayout()
        column.setSpacing(1)
        column.addWidget(ElidedLabel(entry.title, 12.5, QFont.Weight.DemiBold))

        duration = ""
        if entry.duration:
            duration = f" · {int(entry.duration) // 60}:{int(entry.duration) % 60:02d}"
        # The lyrics badge keeps its width; the artist gives way first, because
        # which stage a song will use matters more than the last few letters of
        # a featured-artist list. ("stems ✓" is implied — it is in the library.)
        meta = QHBoxLayout()
        meta.setSpacing(5)
        meta.addWidget(ElidedLabel(f"{entry.display_artist}{duration} ·", 10.5,
                                   color="rgba(238,240,248,0.45)"), 1)
        badge = label(_lyrics_caption(entry), 10.5, color=_lyrics_color(entry))
        meta.addWidget(badge, 0)
        column.addLayout(meta)
        layout.addLayout(column, 1)

        play = button("▶ Play", "BtnPillGhost", height=26)
        play.setStyleSheet("border-radius: 13px; border: none;"
                           "background: rgba(255,61,127,0.16); color: #FF6B9E;"
                           "font-size: 11px; font-weight: 700; padding: 0 11px;")
        play.clicked.connect(lambda: self.playNow.emit(entry.id))
        layout.addWidget(play)

        add = button("+", "BtnPillGhost", height=26, width=28, tooltip="Add to queue")
        add.clicked.connect(lambda: self.queueIt.emit(entry.id))
        layout.addWidget(add)

        remove = button("✕", "BtnFlat", height=26, width=22,
                        tooltip="Remove from library")
        remove.clicked.connect(lambda: self.removed.emit(entry.id))
        layout.addWidget(remove)


class _Panel(QWidget):
    """The drawer's sheet.

    Paints its own background rather than relying on a stylesheet rule: the
    window's global sheet sets every QWidget transparent, and which rule wins
    for a plain QWidget depends on details that are not worth depending on. A
    drawer you can see the stage through is not a drawer.
    """

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), qc("rgba(12,14,21,0.985)"))
        painter.setPen(QPen(qc(theme.BORDER_STRONG), 1))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())


class SongDrawer(QWidget):
    """The whole overlay: tabs, search field, result list, library list."""

    PANEL_WIDTH = 430

    prepareRequested = Signal(object)
    playNow = Signal(str)
    queueSong = Signal(str)
    removeSong = Signal(str)
    importRequested = Signal(str)
    searchRequested = Signal(str)
    thumbRequested = Signal(str)
    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.cards: Dict[str, ResultCard] = {}
        self._library_rows: List[LibraryRow] = []
        self._pending_thumbs: Dict[str, List[Thumbnail]] = {}
        # Decoded artwork, so re-opening the drawer is instant and does not go
        # back to disk (let alone the network) for pictures we already have.
        self._thumb_cache: Dict[str, QPixmap] = {}

        # Positioned by hand rather than by a layout, so the panel can slide in
        # from the left edge the way the design does.
        self.scrim = QWidget(self)
        self.scrim.setCursor(Qt.CursorShape.ArrowCursor)
        self.scrim.setStyleSheet("background: rgba(4,5,8,0.35);")
        self.scrim.mousePressEvent = lambda _: self.closed.emit()

        self.panel = _Panel(self)
        self.panel.setFixedWidth(self.PANEL_WIDTH)
        self.panel.raise_()

        self._slide = QPropertyAnimation(self.panel, b"pos", self)
        self._slide.setDuration(220)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        column = QVBoxLayout(self.panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        tabs = QHBoxLayout()
        tabs.setContentsMargins(14, 12, 14, 0)
        tabs.setSpacing(4)
        self.tab_search = button("YouTube search", "BtnTab", checkable=True)
        self.tab_library = button("Library", "BtnTab", checkable=True)
        self.tab_search.setChecked(True)
        self.tab_search.clicked.connect(lambda: self.show_tab("search"))
        self.tab_library.clicked.connect(lambda: self.show_tab("library"))
        tabs.addWidget(self.tab_search, 1)
        tabs.addWidget(self.tab_library, 1)
        column.addLayout(tabs)

        # -- search side
        self.search_page = QWidget()
        search_layout = QVBoxLayout(self.search_page)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)

        field_host = QWidget()
        field_host.setFixedHeight(38)
        field_host.setStyleSheet(
            "QWidget { background: rgba(255,255,255,0.06);"
            f" border: 1px solid {theme.BORDER_STRONG}; border-radius: 10px; }}")
        field_layout = QHBoxLayout(field_host)
        field_layout.setContentsMargins(12, 0, 12, 0)
        field_layout.setSpacing(9)
        magnifier = label("⌕", 16, color=theme.TEXT_FAINT)
        magnifier.setStyleSheet(f"color: {theme.TEXT_FAINT}; border: none;")
        field_layout.addWidget(magnifier)
        self.field = QLineEdit()
        self.field.setPlaceholderText("Search YouTube, or paste a link…")
        self.field.setFont(theme.ui_font(13))
        self.field.setStyleSheet("border: none; background: transparent;")
        self.field.returnPressed.connect(self._search_now)
        self.field.textEdited.connect(self._on_typed)
        field_layout.addWidget(self.field, 1)

        wrapper = QVBoxLayout()
        wrapper.setContentsMargins(14, 12, 14, 8)
        wrapper.setSpacing(7)
        wrapper.addWidget(field_host)
        note = label("Playback keeps running while you browse · "
                     "downloads run in the background",
                     10.5, color=theme.TEXT_FAINT)
        note.setWordWrap(True)
        wrapper.addWidget(note)
        search_layout.addLayout(wrapper)

        self.results_area, self.results_body, self.results_layout = _scroll_column()
        search_layout.addWidget(self.results_area, 1)
        self.results_hint = label("Type a song name to search YouTube.",
                                  12, color=theme.TEXT_GHOST)
        self.results_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.results_layout.insertWidget(0, self.results_hint)

        # -- library side
        self.library_page = QWidget()
        library_layout = QVBoxLayout(self.library_page)
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.setSpacing(0)
        self.library_area, self.library_body, self.library_layout = _scroll_column()
        library_layout.addWidget(self.library_area, 1)

        self.import_button = button("⤒  Import local audio file (MP3, WAV, MP4…)",
                                    "BtnGhost", height=44)
        self.import_button.setStyleSheet(
            "border: 1px dashed rgba(255,255,255,0.15); border-radius: 10px;"
            f"color: {theme.TEXT_DIM}; background: transparent;")
        self.import_button.clicked.connect(self._pick_file)
        import_host = QWidget()
        import_layout = QVBoxLayout(import_host)
        import_layout.setContentsMargins(14, 0, 14, 14)
        import_layout.addWidget(self.import_button)
        library_layout.addWidget(import_host)

        self.library_empty = label(
            "Nothing here yet — search YouTube and hit Download.",
            12, color=theme.TEXT_GHOST)
        self.library_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.library_layout.insertWidget(0, self.library_empty)

        column.addWidget(self.search_page, 1)
        column.addWidget(self.library_page, 1)
        self.library_page.setVisible(False)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(420)
        self._debounce.timeout.connect(self._search_now)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.scrim.setGeometry(0, 0, self.width(), self.height())
        self.panel.setFixedHeight(self.height())
        if self._slide.state() != QPropertyAnimation.State.Running:
            self.panel.move(0, 0)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.panel.setFixedHeight(self.height())
        self.panel.raise_()
        self._slide.stop()
        self._slide.setStartValue(QPoint(-self.PANEL_WIDTH, 0))
        self._slide.setEndValue(QPoint(0, 0))
        self._slide.start()

    # -- tabs -------------------------------------------------------------
    def show_tab(self, name: str) -> None:
        is_search = name == "search"
        self.tab_search.setChecked(is_search)
        self.tab_library.setChecked(not is_search)
        self.search_page.setVisible(is_search)
        self.library_page.setVisible(not is_search)
        if is_search:
            self.field.setFocus()

    # -- search -----------------------------------------------------------
    def _on_typed(self, text: str) -> None:
        self._debounce.start() if len(text.strip()) >= 2 else self._debounce.stop()

    def _search_now(self) -> None:
        query = self.field.text().strip()
        if query:
            self.results_hint.setText("Searching…")
            self.results_hint.setVisible(True)
            self.searchRequested.emit(query)

    def set_results(self, results: List[SearchResult],
                    library: Dict[str, SongEntry]) -> None:
        for card in self.cards.values():
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()

        for index, item in enumerate(results):
            card = ResultCard(item)
            card.prepare.connect(self.prepareRequested)
            card.playNow.connect(self.playNow)
            card.queueIt.connect(self.queueSong)
            entry = library.get(item.video_id)
            if entry is not None and entry.has_stems:
                card.set_ready(entry)
            self.results_layout.insertWidget(index, card)
            self.cards[item.video_id] = card
            self._want_thumb(item.thumbnail, card.thumb)

        self.results_hint.setVisible(not results)
        if not results:
            self.results_hint.setText("No results. Try a different search.")

    def _want_thumb(self, url: str, target: Thumbnail) -> None:
        """Show cached artwork at once, otherwise queue a fetch for it."""
        if not url:
            return
        cached = self._thumb_cache.get(url)
        if cached is not None:
            target.set_image(cached)
            return
        self._pending_thumbs.setdefault(url, []).append(target)
        self.thumbRequested.emit(url)

    def apply_thumbnail(self, url: str, data: bytes) -> None:
        # Pop, don't peek: the images are cached on disk, so a card built by a
        # later search simply asks again. Keeping the list would pin every
        # Thumbnail ever created for the lifetime of the window.
        targets = self._pending_thumbs.pop(url, None)
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return
        if len(self._thumb_cache) > 200:
            self._thumb_cache.clear()
        self._thumb_cache[url] = pixmap
        for widget in targets or ():
            try:
                widget.set_image(pixmap)
            except RuntimeError:
                pass          # the card was rebuilt by a newer search

    def card_for(self, video_id: str) -> Optional[ResultCard]:
        return self.cards.get(video_id)

    # -- library ----------------------------------------------------------
    def set_library(self, entries: List[SongEntry]) -> None:
        # Reparent before deleting. deleteLater() only schedules the delete, so
        # a row merely removed from the layout keeps painting itself at its old
        # position until the event loop gets round to it — which shows up as
        # ghost text behind the new list.
        for row in self._library_rows:
            row.setParent(None)
            row.deleteLater()
        self._library_rows.clear()

        for index, entry in enumerate(entries):
            row = LibraryRow(entry)
            self._library_rows.append(row)
            row.playNow.connect(self.playNow)
            row.queueIt.connect(self.queueSong)
            row.removed.connect(self.removeSong)
            self.library_layout.insertWidget(index, row)
            self._want_thumb(entry.thumbnail, row.thumb)
        self.library_empty.setVisible(not entries)

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import audio or video", str(Path.home()),
            "Media (*.mp3 *.wav *.m4a *.flac *.ogg *.aac *.mp4 *.mkv *.mov *.webm)")
        if path:
            self.importRequested.emit(path)


def _scroll_column():
    """A vertical scroll area whose body layout ends in a stretch.

    The viewport has to be told not to fill itself: by default it paints the
    window colour, which lands on top of the drawer panel and quietly undoes the
    panel's own background.
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.viewport().setAutoFillBackground(False)
    body = QWidget()
    body.setAutoFillBackground(False)
    layout = QVBoxLayout(body)
    layout.setContentsMargins(14, 2, 14, 14)
    layout.setSpacing(8)
    layout.addStretch(1)
    area.setWidget(body)
    return area, body, layout
