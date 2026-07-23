"""
YouTube search and download, via yt-dlp. No API key, no quota.

Two things matter here beyond "it downloads":

* **Search is flat.** ``extract_flat`` scrapes one results page instead of
  resolving every video, which turns a 20-result search from ~30 s into ~1 s.
* **We decide the format from the lyrics outcome.** If synced lyrics exist the
  stage never shows a picture, so we grab audio only — far smaller and faster.
  Only when lyrics are missing do we pull the video for the fallback stage.
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urlparse, parse_qs

import yt_dlp

from ..utils import WorkerCancelled

logger = logging.getLogger(__name__)


_YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com",
             "music.youtube.com", "youtu.be", "www.youtu.be",
             "youtube-nocookie.com")

# Deliberately no player_client override. Pinning the client is a common
# "speed-up" that quietly strips the format list on some videos, and a song
# that cannot be downloaded is worse than one that takes an extra second.
_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "ignoreerrors": False,
    "nocheckcertificate": True,
    "retries": 3,
    "socket_timeout": 20,
}


@dataclass
class SearchResult:
    """One row in the search list."""

    video_id: str
    title: str
    channel: str = ""
    duration: float = 0.0
    views: int = 0
    thumbnail: str = ""

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def duration_str(self) -> str:
        if not self.duration:
            return "--:--"
        total = int(self.duration)
        return f"{total // 60}:{total % 60:02d}"

    @property
    def views_str(self) -> str:
        n = self.views or 0
        if n >= 1_000_000_000:
            return f"{n / 1_000_000_000:.1f}B views"
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M views"
        if n >= 1_000:
            return f"{n / 1_000:.0f}K views"
        return f"{n} views" if n else ""


def is_youtube_url(text: str) -> bool:
    text = (text or "").strip()
    if not text or " " in text:
        return False
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    try:
        return urlparse(text).netloc.lower() in _YT_HOSTS
    except ValueError:
        return False


def extract_video_id(url: str) -> Optional[str]:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        match = re.match(r"/([A-Za-z0-9_-]{11})", parsed.path)
        return match.group(1) if match else None
    if "youtube" in host:
        video_ids = parse_qs(parsed.query).get("v")
        if video_ids:
            return video_ids[0][:11]
        match = re.search(r"/(?:embed|v|shorts|live)/([A-Za-z0-9_-]{11})", parsed.path)
        if match:
            return match.group(1)
    return None


def _thumb_for(video_id: str, info: Optional[dict] = None) -> str:
    if info:
        thumbs = info.get("thumbnails") or []
        if thumbs:
            return thumbs[-1].get("url", "")
        if info.get("thumbnail"):
            return info["thumbnail"]
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def search(query: str, limit: int = 20) -> List[SearchResult]:
    """Search YouTube, or resolve a pasted link into a single result."""
    query = (query or "").strip()
    if not query:
        return []

    if is_youtube_url(query):
        info = probe(query)
        return [info] if info else []

    opts = dict(_BASE_OPTS)
    opts.update({"extract_flat": "in_playlist", "skip_download": True})

    results: List[SearchResult] = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(f"ytsearch{int(limit)}:{query}", download=False)
    except Exception as exc:
        logger.warning("YouTube search failed for %r: %s", query, exc)
        return []

    for item in (data or {}).get("entries") or ():
        if not item:
            continue
        video_id = item.get("id") or ""
        if len(video_id) != 11:
            continue
        results.append(
            SearchResult(
                video_id=video_id,
                title=item.get("title") or "Untitled",
                channel=item.get("channel") or item.get("uploader") or "",
                duration=float(item.get("duration") or 0.0),
                views=int(item.get("view_count") or 0),
                thumbnail=_thumb_for(video_id, item),
            )
        )
    logger.info("YouTube search %r -> %d results", query, len(results))
    return results


def probe(url_or_id: str) -> Optional[SearchResult]:
    """Resolve one video's metadata without downloading it."""
    video_id = extract_video_id(url_or_id) or (
        url_or_id if re.fullmatch(r"[A-Za-z0-9_-]{11}", url_or_id or "") else None
    )
    if not video_id:
        return None
    try:
        with yt_dlp.YoutubeDL(dict(_BASE_OPTS, skip_download=True)) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                    download=False)
    except Exception as exc:
        logger.warning("Could not read video %s: %s", video_id, exc)
        return None
    if not info:
        return None
    return SearchResult(
        video_id=video_id,
        title=info.get("title") or "Untitled",
        channel=info.get("channel") or info.get("uploader") or "",
        duration=float(info.get("duration") or 0.0),
        views=int(info.get("view_count") or 0),
        thumbnail=_thumb_for(video_id, info),
    )


class Downloader:
    """Fetches a video's media into ``download_dir``."""

    # Audio only — what we use when the song has lyrics and the stage shows
    # text. Each selector falls through to a looser one; YouTube regularly
    # serves a video with no m4a at all.
    AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio/best[height<=480]/best"
    # Capped video — the fallback stage renders at most 1080p, and a 4K pull
    # would waste minutes of the singer's time for no visible gain.
    VIDEO_FORMAT = (
        "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
        "bestvideo[height<=1080]+bestaudio/"
        "best[height<=1080][ext=mp4]/best[height<=1080]/best"
    )

    def __init__(self, download_dir: Path):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def existing(self, video_id: str, want_video: bool) -> Optional[Path]:
        """Return a previously downloaded file for this video, if usable."""
        audio_exts = {".m4a", ".webm", ".opus", ".mp3", ".wav"}
        video_exts = {".mp4", ".mkv", ".webm"}
        best: Optional[Path] = None
        for path in self.download_dir.glob(f"*[[]{video_id}[]]*"):
            if not path.is_file() or path.stat().st_size == 0:
                continue
            suffix = path.suffix.lower()
            if want_video and suffix in video_exts:
                return path
            if not want_video and suffix in audio_exts | video_exts:
                best = best or path
        return best

    def download(
        self,
        video_id: str,
        want_video: bool,
        progress: Optional[Callable[[float, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Path:
        """Download and return the media path. Blocking — call from a worker."""
        cached = self.existing(video_id, want_video)
        if cached:
            logger.info("Reusing cached media for %s: %s", video_id, cached.name)
            if progress:
                progress(1.0, "Cached")
            return cached

        template = str(self.download_dir / "%(title).80s [%(id)s].%(ext)s")
        opts = dict(_BASE_OPTS)
        opts.update({
            "format": self.VIDEO_FORMAT if want_video else self.AUDIO_FORMAT,
            "outtmpl": template,
            "merge_output_format": "mp4" if want_video else None,
            "progress_hooks": [self._hook(progress, should_cancel)],
            "concurrent_fragment_downloads": 4,
        })
        if not want_video:
            # Normalise the container so soundfile/ffmpeg always cope.
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "0",
            }]

        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            if "format is not available" not in str(exc):
                raise
            # Some uploads simply do not carry the containers we asked for.
            logger.warning("Preferred format unavailable for %s; taking whatever "
                           "YouTube offers", video_id)
            opts["format"] = "best"
            opts.pop("postprocessors", None)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

        path = self._resolve_path(info, video_id, want_video)
        if path is None or not path.exists():
            raise FileNotFoundError(f"Download finished but no file appeared for {video_id}")
        logger.info("Downloaded %s -> %s (%.1f MB)", video_id, path.name,
                    path.stat().st_size / 1e6)
        return path

    def _resolve_path(self, info: Optional[dict], video_id: str,
                      want_video: bool) -> Optional[Path]:
        """yt-dlp renames files during post-processing; find what it actually wrote."""
        for key in ("filepath", "_filename"):
            candidate = (info or {}).get(key)
            if candidate and Path(candidate).exists():
                return Path(candidate)
        downloads = (info or {}).get("requested_downloads") or []
        for entry in downloads:
            candidate = entry.get("filepath") or entry.get("_filename")
            if candidate and Path(candidate).exists():
                return Path(candidate)
        return self.existing(video_id, want_video)

    @staticmethod
    def _hook(progress, should_cancel):
        def hook(status):
            if should_cancel and should_cancel():
                raise _Cancelled()
            if not progress:
                return
            state = status.get("status")
            if state == "downloading":
                total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
                done = status.get("downloaded_bytes") or 0
                if total:
                    progress(min(done / total, 0.999), "Downloading")
                else:
                    progress(0.0, f"Downloading {done / 1e6:.1f} MB")
            elif state == "finished":
                progress(1.0, "Converting")
        return hook


class _Cancelled(WorkerCancelled):
    """Raised inside a yt-dlp hook to unwind a cancelled download."""
