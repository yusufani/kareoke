"""
Recording Manager Module
Handles recording of karaoke performances to WAV files.
"""
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import numpy as np
import soundfile as sf


logger = logging.getLogger(__name__)


class RecordingManager:
    """
    Manages recording of karaoke performances.
    Records the mixed audio output to WAV files.
    """

    def __init__(self, recordings_dir: Path, sample_rate: int = 44100, channels: int = 2):
        """
        Initialize the recording manager.

        Args:
            recordings_dir: Directory to store recordings
            sample_rate: Audio sample rate
            channels: Number of audio channels
        """
        self.recordings_dir = Path(recordings_dir)
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        
        self.sample_rate = sample_rate
        self.channels = channels
        
        self.is_recording = False
        self.current_file: Optional[Path] = None
        self.current_song_name: Optional[str] = None
        self.start_time: Optional[datetime] = None
        
        # Recording buffer
        self._buffer: List[np.ndarray] = []
        self._lock = threading.Lock()
        
        logger.info(f"RecordingManager initialized. Recordings dir: {recordings_dir}")

    def start_recording(self, song_name: str = "Unknown"):
        """
        Start recording a performance.

        Args:
            song_name: Name of the song being recorded
        """
        if self.is_recording:
            logger.warning("Recording already in progress")
            return
        
        self.current_song_name = self._sanitize_filename(song_name)
        self.start_time = datetime.now()
        
        # Generate filename
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        filename = f"Recording_{self.current_song_name}_{timestamp}.wav"
        self.current_file = self.recordings_dir / filename
        
        # Clear buffer
        with self._lock:
            self._buffer.clear()
        
        self.is_recording = True
        logger.info(f"Recording started: {self.current_file}")

    def stop_recording(self) -> Optional[Path]:
        """
        Stop recording and save to file.

        Returns:
            Path to saved recording file, or None if no recording was in progress
        """
        if not self.is_recording:
            logger.warning("No recording in progress")
            return None
        
        self.is_recording = False
        
        # Combine buffer and save
        with self._lock:
            if not self._buffer:
                logger.warning("Recording buffer is empty")
                return None
            
            # Concatenate all chunks
            audio_data = np.concatenate(self._buffer, axis=0)
            self._buffer.clear()
        
        # Save to file
        try:
            sf.write(
                str(self.current_file),
                audio_data,
                self.sample_rate,
                subtype='PCM_16'
            )
            logger.info(f"Recording saved: {self.current_file} ({len(audio_data)/self.sample_rate:.1f}s)")
            return self.current_file
        except Exception as e:
            logger.error(f"Failed to save recording: {e}")
            return None

    def add_audio_chunk(self, audio_data: np.ndarray):
        """
        Add an audio chunk to the recording buffer.
        Called during playback to capture the mixed output.

        Args:
            audio_data: Audio chunk to add (samples, channels) float32
        """
        if not self.is_recording:
            return
        
        with self._lock:
            # Make a copy to avoid reference issues
            self._buffer.append(audio_data.copy())

    def get_recording_duration(self) -> float:
        """
        Get current recording duration in seconds.

        Returns:
            Duration in seconds
        """
        if not self.is_recording or not self.start_time:
            return 0.0
        
        return (datetime.now() - self.start_time).total_seconds()

    def get_recordings(self) -> List[Path]:
        """
        Get list of all recording files.

        Returns:
            List of recording file paths
        """
        return sorted(
            self.recordings_dir.glob("Recording_*.wav"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

    def delete_recording(self, file_path: Path) -> bool:
        """
        Delete a recording file.

        Args:
            file_path: Path to recording to delete

        Returns:
            True if deleted successfully
        """
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Recording deleted: {file_path}")
                return True
        except Exception as e:
            logger.error(f"Failed to delete recording: {e}")
        return False

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """
        Sanitize a string for use in filenames.

        Args:
            name: String to sanitize

        Returns:
            Sanitized filename-safe string
        """
        # Remove or replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        
        # Limit length
        if len(name) > 50:
            name = name[:50]
        
        return name.strip() or "Unknown"
