"""
YouTube Downloader Module
Downloads audio/video from YouTube links using yt-dlp.
Includes download history tracking and duplicate detection.
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Dict, List
from urllib.parse import urlparse, parse_qs

import yt_dlp


logger = logging.getLogger(__name__)


class DownloadHistory:
    """Manages YouTube download history in JSON format."""

    def __init__(self, history_file: Path):
        """
        Initialize the download history manager.

        Args:
            history_file: Path to the history JSON file
        """
        self.history_file = Path(history_file)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        """Create history file if it doesn't exist."""
        if not self.history_file.exists():
            self._save_history({"downloads": []})

    def _load_history(self) -> Dict:
        """Load history from JSON file."""
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"downloads": []}

    def _save_history(self, history: Dict):
        """Save history to JSON file."""
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

    def get_download_by_video_id(self, video_id: str) -> Optional[Dict]:
        """
        Get download entry by YouTube video ID.

        Args:
            video_id: YouTube video ID

        Returns:
            Download entry dict or None if not found
        """
        history = self._load_history()
        for download in history.get("downloads", []):
            if download.get("video_id") == video_id:
                return download
        return None

    def add_download(
        self,
        video_id: str,
        url: str,
        title: str,
        thumbnail: str,
        file_path: Path,
        duration: int,
        file_size_mb: float
    ):
        """
        Add a new download entry to history.

        Args:
            video_id: YouTube video ID
            url: Original URL
            title: Video title
            thumbnail: Thumbnail URL
            file_path: Path to downloaded file
            duration: Duration in seconds
            file_size_mb: File size in MB
        """
        history = self._load_history()
        
        # Remove existing entry for this video_id (if re-downloading)
        history["downloads"] = [
            d for d in history["downloads"]
            if d.get("video_id") != video_id
        ]
        
        # Add new entry at the beginning (most recent first)
        history["downloads"].insert(0, {
            "video_id": video_id,
            "url": url,
            "title": title,
            "thumbnail": thumbnail,
            "downloaded_at": datetime.utcnow().isoformat() + "Z",
            "file_path": str(file_path),
            "duration": duration,
            "file_size_mb": round(file_size_mb, 2)
        })
        
        self._save_history(history)
        logger.info(f"Added to download history: {title}")

    def get_all_downloads(self) -> List[Dict]:
        """
        Get all download entries.

        Returns:
            List of download entry dicts
        """
        history = self._load_history()
        return history.get("downloads", [])

    def remove_download(self, video_id: str):
        """
        Remove a download entry by video ID.

        Args:
            video_id: YouTube video ID
        """
        history = self._load_history()
        history["downloads"] = [
            d for d in history["downloads"]
            if d.get("video_id") != video_id
        ]
        self._save_history(history)
        logger.info(f"Removed from download history: {video_id}")

    def clear_history(self):
        """Clear all download history."""
        self._save_history({"downloads": []})
        logger.info("Download history cleared")


class YouTubeDownloader:
    """Handles YouTube video/audio downloads with history tracking."""

    def __init__(self, download_dir: Path):
        """
        Initialize the YouTube downloader.

        Args:
            download_dir: Directory to store downloaded files
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize download history
        data_dir = self.download_dir.parent / "data"
        self.history = DownloadHistory(data_dir / "download_history.json")
        
        logger.info(f"YouTube downloader initialized. Download dir: {download_dir}")

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        """
        Check if a string is a valid YouTube URL.

        Args:
            url: String to check

        Returns:
            True if valid YouTube URL
        """
        youtube_patterns = [
            r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/',
            r'(https?://)?(www\.)?youtu\.be/',
        ]

        for pattern in youtube_patterns:
            if re.match(pattern, url.strip()):
                return True
        return False

    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        """
        Extract YouTube video ID from URL.

        Args:
            url: YouTube URL

        Returns:
            Video ID or None if not found
        """
        url = url.strip()
        
        # Handle youtu.be short URLs
        if 'youtu.be/' in url:
            match = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', url)
            if match:
                return match.group(1)
        
        # Handle standard youtube.com URLs
        parsed = urlparse(url)
        if 'youtube.com' in parsed.netloc or 'youtube-nocookie.com' in parsed.netloc:
            # Check for /watch?v= format
            query_params = parse_qs(parsed.query)
            if 'v' in query_params:
                return query_params['v'][0]
            
            # Check for /embed/ or /v/ format
            match = re.search(r'/(embed|v)/([a-zA-Z0-9_-]{11})', parsed.path)
            if match:
                return match.group(2)
        
        return None

    def check_cached_download(self, video_id: str) -> Optional[Path]:
        """
        Check if video already downloaded and file exists.

        Args:
            video_id: YouTube video ID

        Returns:
            Path to cached file or None if not found/invalid
        """
        entry = self.history.get_download_by_video_id(video_id)
        if entry:
            file_path = Path(entry["file_path"])
            if file_path.exists():
                logger.info(f"Found cached download: {entry['title']}")
                return file_path
            else:
                # File was deleted, remove from history
                logger.warning(f"Cached file not found, removing from history: {file_path}")
                self.history.remove_download(video_id)
        return None

    def get_history(self) -> List[Dict]:
        """
        Get download history.

        Returns:
            List of download entries
        """
        return self.history.get_all_downloads()

    def download(
        self,
        url: str,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> tuple[Path, bool, str]:
        """
        Download video/audio from YouTube.

        Args:
            url: YouTube URL
            progress_callback: Optional callback function(progress: int, message: str)

        Returns:
            Tuple of (file_path, was_cached, title)
            - file_path: Path to downloaded file
            - was_cached: True if file was loaded from cache
            - title: Video title

        Raises:
            Exception: If download fails
        """
        try:
            if not self.is_youtube_url(url):
                raise ValueError("Invalid YouTube URL")

            # Extract video ID for duplicate detection
            video_id = self.extract_video_id(url)
            if not video_id:
                raise ValueError("Could not extract video ID from URL")

            logger.info(f"Processing YouTube URL: {url} (ID: {video_id})")

            # Check for cached download
            cached_path = self.check_cached_download(video_id)
            if cached_path:
                entry = self.history.get_download_by_video_id(video_id)
                title = entry.get("title", "Unknown") if entry else "Unknown"
                if progress_callback:
                    progress_callback(100, f"Using cached: {title}")
                return cached_path, True, title

            if progress_callback:
                progress_callback(5, "Fetching video info...")

            # yt-dlp options
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': str(self.download_dir / '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'progress_hooks': [self._progress_hook(progress_callback)] if progress_callback else [],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Get video info
                info = ydl.extract_info(url, download=False)
                video_title = info.get('title', 'video')
                thumbnail = info.get('thumbnail', '')
                duration = info.get('duration', 0)

                logger.info(f"Video title: {video_title}")

                if progress_callback:
                    progress_callback(10, f"Downloading: {video_title}")

                # Download
                info = ydl.extract_info(url, download=True)

                # Get downloaded file path
                filename = ydl.prepare_filename(info)
                file_path = Path(filename)

                if not file_path.exists():
                    raise FileNotFoundError(f"Downloaded file not found: {file_path}")

                # Calculate file size
                file_size_mb = file_path.stat().st_size / (1024 * 1024)

                # Save to history
                self.history.add_download(
                    video_id=video_id,
                    url=url,
                    title=video_title,
                    thumbnail=thumbnail,
                    file_path=file_path,
                    duration=duration,
                    file_size_mb=file_size_mb
                )

                if progress_callback:
                    progress_callback(100, "Download complete!")

                logger.info(f"Download completed: {file_path}")
                return file_path, False, video_title

        except Exception as e:
            logger.error(f"YouTube download failed: {str(e)}", exc_info=True)
            raise Exception(f"Failed to download from YouTube: {str(e)}")

    def _progress_hook(self, callback):
        """Create a progress hook for yt-dlp."""
        def hook(d):
            if d['status'] == 'downloading':
                if 'total_bytes' in d:
                    percent = int((d['downloaded_bytes'] / d['total_bytes']) * 100)
                    percent = min(10 + int(percent * 0.9), 99)  # Scale to 10-99%
                    callback(percent, f"Downloading... {percent}%")
                elif 'downloaded_bytes' in d:
                    # Size unknown
                    mb = d['downloaded_bytes'] / (1024 * 1024)
                    callback(50, f"Downloading... {mb:.1f} MB")
            elif d['status'] == 'finished':
                callback(99, "Processing...")

        return hook
