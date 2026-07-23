"""
Song library.

One JSON file holding every song the user has prepared: where the media lives,
where its separated stems live, and what we found out about its lyrics. The
library is the single source of truth the UI renders from — the drawer's
"Library" tab, the queue and the stage all read entries out of here.
"""
import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from .paths import LIBRARY_FILE

logger = logging.getLogger(__name__)


LYRICS_SYNCED = "synced"
LYRICS_PLAIN = "plain"
LYRICS_NONE = "none"
LYRICS_UNKNOWN = "unknown"


@dataclass
class SongEntry:
    """A prepared song: media on disk, stems on disk, lyrics resolved."""

    id: str
    title: str
    artist: str = ""
    duration: float = 0.0
    source: str = "youtube"          # youtube | local
    url: str = ""
    thumbnail: str = ""
    media_path: str = ""             # audio (or video) file that was downloaded
    video_path: str = ""             # set when we kept a video for the fallback stage
    vocals_path: str = ""
    instrumental_path: str = ""
    lyrics_state: str = LYRICS_UNKNOWN
    lyrics_source: str = ""
    lyrics_path: str = ""            # cached JSON with the parsed lines
    added_at: float = field(default_factory=time.time)
    play_count: int = 0

    # -- convenience ------------------------------------------------------
    @property
    def has_stems(self) -> bool:
        return bool(
            self.vocals_path
            and self.instrumental_path
            and Path(self.vocals_path).exists()
            and Path(self.instrumental_path).exists()
        )

    @property
    def has_synced_lyrics(self) -> bool:
        return self.lyrics_state == LYRICS_SYNCED

    @property
    def has_any_lyrics(self) -> bool:
        return self.lyrics_state in (LYRICS_SYNCED, LYRICS_PLAIN)

    @property
    def has_video(self) -> bool:
        return bool(self.video_path and Path(self.video_path).exists())

    @property
    def display_artist(self) -> str:
        return self.artist or "Unknown artist"

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "SongEntry":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class Library:
    """Thread-safe JSON-backed collection of :class:`SongEntry`."""

    def __init__(self, path: Path = LIBRARY_FILE):
        self.path = Path(path)
        self._entries: Dict[str, SongEntry] = {}
        self._lock = threading.RLock()
        self.load()

    def load(self) -> None:
        with self._lock:
            self._entries.clear()
            if not self.path.exists():
                return
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read library (%s); starting empty", exc)
                return
            for item in raw.get("songs", []):
                try:
                    entry = SongEntry.from_dict(item)
                except TypeError:
                    continue
                self._entries[entry.id] = entry
            logger.info("Library loaded: %d songs", len(self._entries))

    def save(self) -> None:
        with self._lock:
            payload = {
                "version": 2,
                "songs": [e.to_dict() for e in self._entries.values()],
            }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
            tmp.replace(self.path)
        except OSError as exc:
            logger.warning("Could not save library: %s", exc)

    # -- access -----------------------------------------------------------
    def get(self, song_id: str) -> Optional[SongEntry]:
        with self._lock:
            return self._entries.get(song_id)

    def all(self) -> List[SongEntry]:
        """Most recently added first."""
        with self._lock:
            return sorted(self._entries.values(), key=lambda e: e.added_at, reverse=True)

    def put(self, entry: SongEntry) -> SongEntry:
        with self._lock:
            self._entries[entry.id] = entry
        self.save()
        return entry

    def remove(self, song_id: str) -> None:
        with self._lock:
            self._entries.pop(song_id, None)
        self.save()

    def prune_missing(self) -> int:
        """Drop entries whose stems have been deleted from disk."""
        removed = 0
        with self._lock:
            for song_id in list(self._entries):
                if not self._entries[song_id].has_stems:
                    del self._entries[song_id]
                    removed += 1
        if removed:
            self.save()
            logger.info("Pruned %d library entries with missing stems", removed)
        return removed
