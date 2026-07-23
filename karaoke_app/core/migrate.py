"""
One-off import of songs prepared by the previous version of the app.

The old build kept a ``download_history.json`` and a ``stems_cache`` folder but
no library. Rather than make the user re-download and re-separate everything,
this walks what is already on disk and files it into the new library. Lyrics
are not fetched here — that would mean a burst of network calls at start-up —
so entries land as ``unknown`` and get resolved the first time they are played.
"""
import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, Optional

from ..audio.lyrics import split_title
from .library import LYRICS_UNKNOWN, Library, SongEntry
from .paths import DATA_DIR, DOWNLOADS_DIR, STEMS_DIR

logger = logging.getLogger(__name__)

LEGACY_HISTORY = DATA_DIR / "download_history.json"
MARKER = DATA_DIR / ".migrated_v2"


def _file_hash(path: Path) -> str:
    """The old cache-directory key: first 8 hex of the file's MD5."""
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()[:8]


def _stems_for(media: Path) -> Optional[tuple]:
    """Find the cached stem pair for a media file, if it was separated."""
    folder = STEMS_DIR / f"{media.stem}_{_file_hash(media)}"
    vocals = folder / f"{media.stem}_vocals.wav"
    instrumental = folder / f"{media.stem}_instrumental.wav"
    if vocals.exists() and instrumental.exists():
        return vocals, instrumental
    return None


def _legacy_entries() -> Dict[str, Dict]:
    if not LEGACY_HISTORY.exists():
        return {}
    try:
        with open(LEGACY_HISTORY, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {}
    return {Path(item.get("file_path", "")).name: item
            for item in data.get("downloads", []) if item.get("file_path")}


def run(library: Library, force: bool = False) -> int:
    """Import anything on disk that the library does not know about yet."""
    if MARKER.exists() and not force:
        return 0
    if not STEMS_DIR.is_dir():
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.touch()
        return 0

    history = _legacy_entries()
    known_media = {Path(entry.media_path).name for entry in library.all()
                   if entry.media_path}
    imported = 0

    for media in sorted(DOWNLOADS_DIR.glob("*")):
        if not media.is_file() or media.suffix.lower() == ".part":
            continue
        if media.name in known_media:
            continue
        try:
            stems = _stems_for(media)
        except OSError:
            continue
        if stems is None:
            continue

        legacy = history.get(media.name, {})
        raw_title = legacy.get("title") or media.stem
        artist, track = split_title(raw_title)
        video_id = legacy.get("video_id") or f"local:{media.stem[:40]}"
        video_exts = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}

        library.put(SongEntry(
            id=video_id,
            title=track or raw_title,
            artist=artist,
            duration=float(legacy.get("duration") or 0.0),
            source="youtube" if legacy.get("video_id") else "local",
            url=legacy.get("url", ""),
            thumbnail=legacy.get("thumbnail", ""),
            media_path=str(media),
            video_path=str(media) if media.suffix.lower() in video_exts else "",
            vocals_path=str(stems[0]),
            instrumental_path=str(stems[1]),
            lyrics_state=LYRICS_UNKNOWN,
        ))
        imported += 1
        logger.info("Imported existing song: %s", track or raw_title)

    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.touch()
    if imported:
        logger.info("Migrated %d previously prepared songs into the library",
                    imported)
    return imported
