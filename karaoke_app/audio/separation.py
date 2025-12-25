"""
Audio Separation Module using Demucs v4
Handles stem separation with caching and progress reporting.
"""
import os
import hashlib
import logging
from pathlib import Path
from typing import Tuple, Optional, Callable

import torch
import soundfile as sf
from demucs.pretrained import get_model
from demucs.apply import apply_model


# Configure logging
logger = logging.getLogger(__name__)


class SeparationEngine:
    """Handles audio separation using Demucs."""

    def __init__(self, cache_dir: Path):
        """
        Initialize the separation engine.

        Args:
            cache_dir: Directory to store separated stems
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.model = None
        self.device = self._detect_device()

        logger.info(f"Separation engine initialized. Device: {self.device}")

    def _detect_device(self) -> str:
        """Detect if CUDA GPU is available, otherwise use CPU."""
        if torch.cuda.is_available():
            device = "cuda"
            gpu_name = torch.cuda.get_device_name(0)
            logger.info(f"GPU detected: {gpu_name}")
        else:
            device = "cpu"
            logger.info("No GPU detected, using CPU")
        return device

    def _get_file_hash(self, file_path: Path) -> str:
        """
        Generate MD5 hash of file for cache identification.

        Args:
            file_path: Path to the audio/video file

        Returns:
            MD5 hash string
        """
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            # Read in chunks to handle large files
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _get_stem_paths(self, file_path: Path) -> Tuple[Path, Path]:
        """
        Get the cached stem file paths for a given input file.

        Args:
            file_path: Path to the original audio/video file

        Returns:
            Tuple of (vocals_path, instrumental_path)
        """
        file_hash = self._get_file_hash(file_path)
        base_name = file_path.stem

        # Create a subdirectory for this song
        song_cache_dir = self.cache_dir / f"{base_name}_{file_hash[:8]}"
        song_cache_dir.mkdir(parents=True, exist_ok=True)

        vocals_path = song_cache_dir / f"{base_name}_vocals.wav"
        instrumental_path = song_cache_dir / f"{base_name}_instrumental.wav"

        return vocals_path, instrumental_path

    def check_stems_exist(self, file_path: Path) -> Tuple[bool, Path, Path]:
        """
        Check if stems already exist in cache.

        Args:
            file_path: Path to the audio/video file

        Returns:
            Tuple of (exists: bool, vocals_path: Path, instrumental_path: Path)
        """
        vocals_path, instrumental_path = self._get_stem_paths(file_path)

        exists = (
            vocals_path.exists() and
            instrumental_path.exists() and
            vocals_path.stat().st_size > 0 and
            instrumental_path.stat().st_size > 0
        )

        return exists, vocals_path, instrumental_path

    def _load_model(self):
        """Load the Demucs model."""
        if self.model is None:
            logger.info("Loading Demucs htdemucs model...")
            # Use htdemucs (hybrid transformer) - best quality for 2-stem separation
            self.model = get_model('htdemucs')
            self.model.to(self.device)
            self.model.eval()
            logger.info("Model loaded successfully")

    def preload_model(self):
        """Preload model in background to speed up first separation."""
        logger.info("Preloading AI model in background...")
        self._load_model()
        logger.info("AI model ready!")

    def _extract_audio_from_video(self, file_path: Path) -> Path:
        """
        Extract audio from video files using ffmpeg.
        If file is already audio format, return original path.

        Args:
            file_path: Path to the audio/video file

        Returns:
            Path to audio file (extracted temp WAV or original)
        """
        import ffmpeg

        # Video formats that need extraction
        video_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.flv', '.m4v', '.webm'}

        # If already audio format, return as-is
        if file_path.suffix.lower() not in video_extensions:
            logger.info(f"File is already audio format: {file_path.suffix}")
            return file_path

        # Extract audio to temporary WAV file
        logger.info(f"Extracting audio from video: {file_path.name}")

        # Create temp audio file path (same location as video)
        temp_audio_path = file_path.parent / f"{file_path.stem}_temp_audio.wav"

        try:
            # Use ffmpeg to extract audio as WAV (44.1kHz, stereo)
            (
                ffmpeg
                .input(str(file_path))
                .output(str(temp_audio_path), acodec='pcm_s16le', ac=2, ar='44100')
                .overwrite_output()
                .run(quiet=True, capture_stdout=True, capture_stderr=True)
            )

            logger.info(f"Audio extracted to: {temp_audio_path}")
            return temp_audio_path

        except ffmpeg.Error as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            logger.error(f"FFmpeg extraction failed: {error_msg}")
            raise Exception(f"Failed to extract audio from video: {error_msg}")

    def separate(
        self,
        file_path: Path,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Tuple[Path, Path]:
        """
        Separate audio into vocals and instrumental stems.

        Args:
            file_path: Path to the audio/video file
            progress_callback: Optional callback function(progress: int, message: str)

        Returns:
            Tuple of (vocals_path, instrumental_path)

        Raises:
            Exception: If separation fails
        """
        try:
            # Check if stems already exist
            exists, vocals_path, instrumental_path = self.check_stems_exist(file_path)
            if exists:
                logger.info(f"Stems already exist for {file_path.name}")
                if progress_callback:
                    progress_callback(100, "Stems loaded from cache")
                return vocals_path, instrumental_path

            # Report progress
            if progress_callback:
                progress_callback(5, "Extracting audio from video...")

            # Extract audio from video if needed
            audio_file_path = self._extract_audio_from_video(file_path)

            if progress_callback:
                progress_callback(10, "Loading audio file...")

            # Load audio file using soundfile
            logger.info(f"Loading audio from {audio_file_path}")
            audio_data, sample_rate = sf.read(str(audio_file_path), dtype='float32', always_2d=True)

            # soundfile returns (samples, channels), we need (channels, samples)
            waveform = torch.from_numpy(audio_data.T)

            # Convert to stereo if mono
            if waveform.shape[0] == 1:
                waveform = waveform.repeat(2, 1)

            # Demucs expects 2 channels (stereo)
            if waveform.shape[0] > 2:
                waveform = waveform[:2, :]

            # Clean up temporary audio file if it was created
            if audio_file_path != file_path and audio_file_path.exists():
                logger.info(f"Cleaning up temporary audio file: {audio_file_path}")
                audio_file_path.unlink()

            if progress_callback:
                progress_callback(15, "Loading AI model...")

            # Load model
            self._load_model()

            if progress_callback:
                progress_callback(25, "Separating vocals and instrumental...")

            # Move audio to device
            waveform = waveform.to(self.device)

            # Add batch dimension
            waveform = waveform.unsqueeze(0)

            # Apply separation
            logger.info("Running Demucs separation...")
            with torch.no_grad():
                sources = apply_model(
                    self.model,
                    waveform,
                    device=self.device,
                    split=True,  # Split into chunks for memory efficiency
                    overlap=0.25
                )

            # sources shape: [batch, stems, channels, samples]
            # htdemucs outputs 4 stems: drums, bass, other, vocals
            # We need: vocals (index 3) and instrumental (sum of 0, 1, 2)

            if progress_callback:
                progress_callback(70, "Processing separated stems...")

            # Extract vocals (last stem)
            vocals = sources[0, 3].cpu()  # [channels, samples]

            # Create instrumental by summing other stems
            instrumental = sources[0, [0, 1, 2]].sum(dim=0).cpu()  # [channels, samples]

            if progress_callback:
                progress_callback(80, "Saving stems...")

            # Save stems as WAV files using soundfile
            # Convert from (channels, samples) to (samples, channels) for soundfile
            logger.info(f"Saving vocals to {vocals_path}")
            sf.write(
                str(vocals_path),
                vocals.T.numpy(),  # Transpose to (samples, channels)
                sample_rate,
                subtype='PCM_16'
            )

            logger.info(f"Saving instrumental to {instrumental_path}")
            sf.write(
                str(instrumental_path),
                instrumental.T.numpy(),  # Transpose to (samples, channels)
                sample_rate,
                subtype='PCM_16'
            )

            if progress_callback:
                progress_callback(100, "Separation complete!")

            logger.info("Separation completed successfully")
            return vocals_path, instrumental_path

        except Exception as e:
            logger.error(f"Separation failed: {str(e)}", exc_info=True)
            raise Exception(f"Audio separation failed: {str(e)}")

    def delete_stems(self, file_path: Path):
        """
        Delete cached stems for a file.

        Args:
            file_path: Path to the original audio/video file
        """
        vocals_path, instrumental_path = self._get_stem_paths(file_path)

        if vocals_path.exists():
            vocals_path.unlink()
            logger.info(f"Deleted {vocals_path}")

        if instrumental_path.exists():
            instrumental_path.unlink()
            logger.info(f"Deleted {instrumental_path}")

        # Try to remove the parent directory if empty
        try:
            vocals_path.parent.rmdir()
        except OSError:
            pass  # Directory not empty or doesn't exist
