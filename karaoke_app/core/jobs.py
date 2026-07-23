"""
Background work: search, download, lyrics lookup, stem separation.

Every one of these is slow and none of them may touch the GUI thread — the
whole point of the app is that somebody can be mid-chorus while the next song
downloads and separates behind them. So:

* Searches and thumbnails run on a small pool and return in about a second.
* Preparing a song is one runnable that walks lyrics -> download -> separate,
  reporting progress at each stage.
* Separation holds a semaphore so only one demucs pass runs at a time. Two at
  once would thrash memory and, worse, starve the audio callback.
* torch is told to leave a couple of cores alone, so separating a song never
  costs the singer a dropout.
"""
import logging
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ..audio import lyrics as lyrics_api
from ..audio import youtube
from ..audio.youtube import Downloader, SearchResult
from .library import (LYRICS_NONE, LYRICS_PLAIN, LYRICS_SYNCED, Library,
                      SongEntry)
from .paths import DOWNLOADS_DIR, STEMS_DIR
from ..utils import WorkerCancelled

logger = logging.getLogger(__name__)


STAGE_LYRICS = "lyrics"
STAGE_DOWNLOAD = "download"
STAGE_SEPARATE = "separate"
STAGE_READY = "ready"

# Kept in step with SeparationEngine.MAX_INPUT_SECONDS; checked here first so a
# hopeless job is rejected before anything is downloaded.
MAX_SONG_SECONDS = 20 * 60

STAGE_LABELS = {
    STAGE_LYRICS: "Finding lyrics",
    STAGE_DOWNLOAD: "Downloading",
    STAGE_SEPARATE: "Separating stems",
    STAGE_READY: "Ready",
}


class JobCancelled(WorkerCancelled):
    """Raised inside a worker once the user has cancelled its job.

    Subclasses :class:`WorkerCancelled` so the separation engine re-raises it
    untouched instead of wrapping it as a failure.
    """


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


class _SearchSignals(QObject):
    done = Signal(str, list)      # query, [SearchResult]
    failed = Signal(str, str)


class _SearchTask(QRunnable):
    def __init__(self, query: str, limit: int, signals: _SearchSignals, token: int,
                 current_token):
        super().__init__()
        self.query = query
        self.limit = limit
        self.signals = signals
        self.token = token
        self._current_token = current_token
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            results = youtube.search(self.query, self.limit)
        except Exception as exc:
            logger.warning("search failed: %s", exc)
            self.signals.failed.emit(self.query, str(exc))
            return
        # A newer keystroke already superseded this search; drop the answer.
        if self._current_token() != self.token:
            return
        self.signals.done.emit(self.query, results)


# --------------------------------------------------------------------------
# Thumbnails
# --------------------------------------------------------------------------


class _ThumbSignals(QObject):
    loaded = Signal(str, bytes)   # url, raw image bytes


class _ThumbTask(QRunnable):
    def __init__(self, url: str, cache_dir: Path, signals: _ThumbSignals,
                 done: Callable[[str], None]):
        super().__init__()
        self.url = url
        self.cache_dir = cache_dir
        self.signals = signals
        self.done = done
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        import urllib.request
        name = re.sub(r"[^A-Za-z0-9]", "_", self.url)[-60:] + ".img"
        cached = self.cache_dir / name
        try:
            if cached.exists():
                self.signals.loaded.emit(self.url, cached.read_bytes())
                return
            request = urllib.request.Request(
                self.url, headers={"User-Agent": lyrics_api.USER_AGENT})
            with urllib.request.urlopen(request, timeout=8) as response:
                data = response.read()
            if data:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(data)
                self.signals.loaded.emit(self.url, data)
        except Exception:
            pass
        finally:
            # Always release the in-flight guard, or a later card asking for the
            # same image would be told one is already coming and wait forever.
            self.done(self.url)


# --------------------------------------------------------------------------
# Preparing a song
# --------------------------------------------------------------------------


class _PrepareSignals(QObject):
    progress = Signal(str, str, float, str)   # job_id, stage, 0..1, label
    finished = Signal(str, object)            # job_id, SongEntry
    failed = Signal(str, str)                 # job_id, message
    lyricsReady = Signal(str, object)         # song_id, LyricsResult


class _LyricsTask(QRunnable):
    """Resolve one song's lyrics after the fact.

    Songs migrated from the old app, and songs whose first lookup came back
    empty, get a second chance here — the search runs while the song is already
    playing, and the stage swaps over the moment it lands.
    """

    def __init__(self, entry: SongEntry, manager: "JobManager"):
        super().__init__()
        self.entry = entry
        self.manager = manager
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        entry = self.entry
        try:
            found = lyrics_api.fetch(
                f"{entry.artist} - {entry.title}" if entry.artist else entry.title,
                "", entry.duration, entry.artist, entry.title)
            lyrics_api.save_cached(entry.id, found)
            entry.lyrics_state = (LYRICS_SYNCED if found.synced
                                  else LYRICS_PLAIN if found.found else LYRICS_NONE)
            entry.lyrics_source = found.source
            entry.lyrics_path = str(lyrics_api._cache_path(entry.id))
            # A matched database record usually names the song better than a
            # YouTube title does — but only adopt it when it agrees with what we
            # parsed. LRCLIB has its share of records filed the wrong way round,
            # and swapping our guess for theirs would just be wrong differently.
            if found.found and found.track and lyrics_api.agrees(
                    entry.title, entry.artist, found.track, found.artist):
                entry.title = found.track
                if found.artist:
                    entry.artist = found.artist
            self.manager.library.put(entry)
        except Exception as exc:
            logger.warning("Late lyrics lookup failed for %s: %s", entry.title, exc)
            return
        self.manager.signals.lyricsReady.emit(entry.id, found)


class _PrepareTask(QRunnable):
    """lyrics -> download -> separate, for one song."""

    def __init__(self, job_id: str, item: SearchResult, manager: "JobManager"):
        super().__init__()
        self.job_id = job_id
        self.item = item
        self.manager = manager
        self.setAutoDelete(True)

    # -- helpers ----------------------------------------------------------
    def _check(self) -> None:
        if self.manager.is_cancelled(self.job_id):
            raise JobCancelled()

    def _emit(self, stage: str, fraction: float, label: str = "") -> None:
        self.manager.signals.progress.emit(
            self.job_id, stage, max(0.0, min(1.0, fraction)),
            label or STAGE_LABELS.get(stage, stage))

    # -- the job ----------------------------------------------------------
    @Slot()
    def run(self) -> None:
        try:
            entry = self._prepare()
        except JobCancelled:
            logger.info("job %s cancelled", self.job_id)
            self.manager.signals.failed.emit(self.job_id, "Cancelled")
            return
        except Exception as exc:
            logger.error("job %s failed: %s", self.job_id, exc, exc_info=True)
            self.manager.signals.failed.emit(self.job_id, str(exc))
            return
        finally:
            self.manager.forget(self.job_id)
        self.manager.signals.finished.emit(self.job_id, entry)

    def _prepare(self) -> SongEntry:
        item = self.item
        existing = self.manager.library.get(item.video_id)
        if existing and existing.has_stems:
            self._emit(STAGE_READY, 1.0, "Already in library")
            return existing

        # Bail before spending bandwidth. A two-hour mix is never what somebody
        # meant to sing, and separating one needs more memory than any laptop
        # has (see SeparationEngine.MAX_INPUT_SECONDS).
        if item.duration and item.duration > MAX_SONG_SECONDS:
            minutes = int(item.duration) // 60
            raise ValueError(
                f"That upload is {minutes} minutes long. Encore prepares tracks "
                f"up to {MAX_SONG_SECONDS // 60} minutes — pick a single song "
                f"rather than a full mix or a live set."
            )

        artist, track = lyrics_api.split_title(item.title, item.channel)

        # 1. Lyrics. The outcome decides whether we need the video at all.
        self._check()
        self._emit(STAGE_LYRICS, 0.15)
        found = lyrics_api.load_cached(item.video_id)
        if found is None:
            found = lyrics_api.fetch(item.title, item.channel, item.duration,
                                     artist, track)
            lyrics_api.save_cached(item.video_id, found)
        state = (LYRICS_SYNCED if found.synced
                 else LYRICS_PLAIN if found.found else LYRICS_NONE)
        want_video = state == LYRICS_NONE
        self._emit(STAGE_LYRICS, 1.0,
                   "Synced lyrics found" if found.synced
                   else "Lyrics found" if found.found else "No lyrics — will use video")

        # 2. Media. Audio only when the stage will show text.
        self._check()
        self._emit(STAGE_DOWNLOAD, 0.0)

        def on_download(fraction: float, label: str) -> None:
            self._emit(STAGE_DOWNLOAD, fraction, f"{label} {int(fraction * 100)}%"
                       if label == "Downloading" else label)

        media = self.manager.downloader.download(
            item.video_id, want_video, on_download,
            lambda: self.manager.is_cancelled(self.job_id))
        self._emit(STAGE_DOWNLOAD, 1.0)

        # 3. Stems. Serialised — one demucs pass at a time.
        self._check()
        self._emit(STAGE_SEPARATE, 0.0, "Waiting for separator")
        self.manager.separation_slot.acquire()
        try:
            self._check()
            engine = self.manager.separation_engine()

            def on_separate(percent: int, message: str) -> None:
                if self.manager.is_cancelled(self.job_id):
                    raise JobCancelled()
                self._emit(STAGE_SEPARATE, percent / 100.0,
                           f"Separating stems {percent}%")

            vocals, instrumental = engine.separate(media, on_separate)
        finally:
            self.manager.separation_slot.release()

        entry = SongEntry(
            id=item.video_id,
            title=track or item.title,
            artist=artist,
            duration=item.duration,
            source="youtube",
            url=item.url,
            thumbnail=item.thumbnail,
            media_path=str(media),
            video_path=str(media) if want_video else "",
            vocals_path=str(vocals),
            instrumental_path=str(instrumental),
            lyrics_state=state,
            lyrics_source=found.source,
            lyrics_path=str(lyrics_api._cache_path(item.video_id)),
        )
        self.manager.library.put(entry)
        self._emit(STAGE_READY, 1.0, "Ready")
        return entry


class _ImportTask(QRunnable):
    """Same pipeline for a local audio/video file the user dropped in."""

    def __init__(self, job_id: str, path: Path, manager: "JobManager"):
        super().__init__()
        self.job_id = job_id
        self.path = Path(path)
        self.manager = manager
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        job_id = self.job_id
        try:
            artist, track = lyrics_api.split_title(self.path.stem)
            song_id = "local:" + re.sub(r"[^A-Za-z0-9]", "_", self.path.stem)[:60]

            self.manager.signals.progress.emit(job_id, STAGE_LYRICS, 0.3,
                                               "Finding lyrics")
            found = (lyrics_api.load_sidecar(self.path)
                     or lyrics_api.load_cached(song_id)
                     or lyrics_api.fetch(self.path.stem, "", 0.0, artist, track))
            lyrics_api.save_cached(song_id, found)
            state = (LYRICS_SYNCED if found.synced
                     else LYRICS_PLAIN if found.found else LYRICS_NONE)

            self.manager.signals.progress.emit(job_id, STAGE_SEPARATE, 0.0,
                                               "Waiting for separator")
            self.manager.separation_slot.acquire()
            try:
                engine = self.manager.separation_engine()

                def on_separate(percent: int, message: str) -> None:
                    if self.manager.is_cancelled(job_id):
                        raise JobCancelled()
                    self.manager.signals.progress.emit(
                        job_id, STAGE_SEPARATE, percent / 100.0,
                        f"Separating stems {percent}%")

                vocals, instrumental = engine.separate(self.path, on_separate)
            finally:
                self.manager.separation_slot.release()

            video_exts = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
            entry = SongEntry(
                id=song_id,
                title=track or self.path.stem,
                artist=artist,
                source="local",
                media_path=str(self.path),
                video_path=str(self.path) if self.path.suffix.lower() in video_exts else "",
                vocals_path=str(vocals),
                instrumental_path=str(instrumental),
                lyrics_state=state,
                lyrics_source=found.source,
                lyrics_path=str(lyrics_api._cache_path(song_id)),
            )
            self.manager.library.put(entry)
            self.manager.signals.progress.emit(job_id, STAGE_READY, 1.0, "Ready")
        except JobCancelled:
            self.manager.signals.failed.emit(job_id, "Cancelled")
            return
        except Exception as exc:
            logger.error("import failed: %s", exc, exc_info=True)
            self.manager.signals.failed.emit(job_id, str(exc))
            return
        finally:
            self.manager.forget(job_id)
        self.manager.signals.finished.emit(job_id, entry)


# --------------------------------------------------------------------------
# Manager
# --------------------------------------------------------------------------


class JobManager(QObject):
    """Owns the thread pool and the state of everything running in it."""

    search_done = Signal(str, list)
    search_failed = Signal(str, str)
    thumb_loaded = Signal(str, bytes)

    def __init__(self, library: Library, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.library = library
        self.downloader = Downloader(DOWNLOADS_DIR)

        self.pool = QThreadPool(self)
        # Leave headroom: the audio callback and demucs both want CPU.
        self.pool.setMaxThreadCount(max(3, min(6, (os.cpu_count() or 4) - 1)))
        self.separation_slot = threading.Semaphore(1)

        self.signals = _PrepareSignals()
        self._search_signals = _SearchSignals()
        self._thumb_signals = _ThumbSignals()
        self._search_signals.done.connect(self.search_done)
        self._search_signals.failed.connect(self.search_failed)
        self._thumb_signals.loaded.connect(self.thumb_loaded)

        self._cancelled: set = set()
        self._active: Dict[str, str] = {}     # job_id -> song/video id
        self._state_lock = threading.Lock()
        self._search_token = 0
        self._thumb_pending: set = set()
        self._engine = None
        self._engine_lock = threading.Lock()

    # -- separation engine (torch is imported lazily, off the GUI thread) --
    def separation_engine(self):
        with self._engine_lock:
            if self._engine is None:
                import torch
                # Keep a couple of cores free so the audio thread always makes
                # its deadline while a song separates in the background.
                cores = os.cpu_count() or 4
                torch.set_num_threads(max(1, cores - 2))
                from ..audio.separation import SeparationEngine
                self._engine = SeparationEngine(STEMS_DIR)
            return self._engine

    def preload_separator(self) -> None:
        """Warm up torch + the demucs weights so the first song is not slow."""
        class _Warm(QRunnable):
            def __init__(self, manager):
                super().__init__()
                self.manager = manager

            @Slot()
            def run(self) -> None:
                try:
                    self.manager.separation_engine().preload_model()
                except Exception as exc:
                    logger.warning("Could not preload the separator: %s", exc)

        self.pool.start(_Warm(self))

    # -- search -----------------------------------------------------------
    def search(self, query: str, limit: int = 20) -> None:
        with self._state_lock:
            self._search_token += 1
            token = self._search_token
        self.pool.start(_SearchTask(query, limit, self._search_signals, token,
                                    lambda: self._search_token))

    def load_thumbnail(self, url: str) -> None:
        if not url:
            return
        with self._state_lock:
            if url in self._thumb_pending:
                return
            self._thumb_pending.add(url)
        from .paths import DATA_DIR
        self.pool.start(_ThumbTask(url, DATA_DIR / "thumbs", self._thumb_signals,
                                   self._thumb_finished))

    def _thumb_finished(self, url: str) -> None:
        with self._state_lock:
            self._thumb_pending.discard(url)

    # -- preparing --------------------------------------------------------
    def prepare(self, item: SearchResult) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._state_lock:
            self._active[job_id] = item.video_id
        self.pool.start(_PrepareTask(job_id, item, self))
        logger.info("job %s queued: %s", job_id, item.title[:60])
        return job_id

    def resolve_lyrics(self, entry: SongEntry) -> None:
        """Look up lyrics for a song already in the library."""
        self.pool.start(_LyricsTask(entry, self))

    def import_file(self, path: Path) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._state_lock:
            self._active[job_id] = str(path)
        self.pool.start(_ImportTask(job_id, path, self))
        return job_id

    def cancel(self, job_id: str) -> None:
        with self._state_lock:
            self._cancelled.add(job_id)

    def cancel_all(self) -> None:
        with self._state_lock:
            self._cancelled.update(self._active)

    def is_cancelled(self, job_id: str) -> bool:
        with self._state_lock:
            return job_id in self._cancelled

    def forget(self, job_id: str) -> None:
        with self._state_lock:
            self._active.pop(job_id, None)
            self._cancelled.discard(job_id)

    def job_for(self, video_id: str) -> Optional[str]:
        with self._state_lock:
            for job_id, target in self._active.items():
                if target == video_id:
                    return job_id
        return None

    @property
    def busy_count(self) -> int:
        with self._state_lock:
            return len(self._active)

    def shutdown(self) -> None:
        self.cancel_all()
        self.pool.clear()
        self.pool.waitForDone(3000)
