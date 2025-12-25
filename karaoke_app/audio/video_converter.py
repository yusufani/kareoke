"""
Video Converter Module
Handles detection and conversion of unsupported video codecs (AV1, VP9) to H.264.
"""
import logging
import subprocess
import json
import threading
from pathlib import Path
from typing import Optional, Tuple, Callable

logger = logging.getLogger(__name__)


class VideoConverter:
    """
    Detects and converts videos with unsupported codecs to H.264.
    Automatically converts AV1 and VP9 encoded videos for compatibility.
    """

    # Codecs that may not be hardware-accelerated on all platforms
    UNSUPPORTED_CODECS = {'av1', 'vp9', 'vp8', 'hevc', 'h265'}
    
    # Preferred output codec
    OUTPUT_CODEC = 'libx264'
    
    def __init__(self, converted_dir: Optional[Path] = None):
        """
        Initialize the video converter.

        Args:
            converted_dir: Directory to store converted videos (optional)
        """
        self.converted_dir = converted_dir or Path.home() / ".karaoke_converted"
        self.converted_dir.mkdir(parents=True, exist_ok=True)
        
        # Check if ffmpeg is available
        self.ffmpeg_available = self._check_ffmpeg()
        if not self.ffmpeg_available:
            logger.warning("FFmpeg not found. Video conversion will not be available.")
        else:
            logger.info("VideoConverter initialized with FFmpeg support")

    def _check_ffmpeg(self) -> bool:
        """Check if ffmpeg is available in PATH."""
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def get_video_codec(self, file_path: Path) -> Optional[str]:
        """
        Get the video codec of a file using ffprobe.

        Args:
            file_path: Path to the video file

        Returns:
            Video codec name (lowercase) or None if detection fails
        """
        if not self.ffmpeg_available:
            return None

        try:
            result = subprocess.run(
                [
                    'ffprobe',
                    '-v', 'quiet',
                    '-select_streams', 'v:0',
                    '-show_entries', 'stream=codec_name',
                    '-of', 'json',
                    str(file_path)
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                streams = data.get('streams', [])
                if streams:
                    codec = streams[0].get('codec_name', '').lower()
                    logger.debug(f"Detected video codec: {codec} for {file_path.name}")
                    return codec
        except Exception as e:
            logger.warning(f"Failed to detect video codec: {e}")
        
        return None

    def needs_conversion(self, file_path: Path) -> bool:
        """
        Check if a video file needs conversion due to unsupported codec.

        Args:
            file_path: Path to the video file

        Returns:
            True if conversion is needed
        """
        codec = self.get_video_codec(file_path)
        if codec and codec in self.UNSUPPORTED_CODECS:
            logger.info(f"Video needs conversion: {file_path.name} (codec: {codec})")
            return True
        return False

    def get_converted_path(self, original_path: Path) -> Path:
        """
        Get the path where the converted video would be stored.

        Args:
            original_path: Path to the original video

        Returns:
            Path for the converted video
        """
        # Use same basename but with _h264 suffix
        converted_name = f"{original_path.stem}_h264.mp4"
        return self.converted_dir / converted_name

    def is_already_converted(self, original_path: Path) -> Optional[Path]:
        """
        Check if a converted version already exists.

        Args:
            original_path: Path to the original video

        Returns:
            Path to converted video if exists, None otherwise
        """
        converted_path = self.get_converted_path(original_path)
        if converted_path.exists():
            # Verify it's a valid video
            codec = self.get_video_codec(converted_path)
            if codec and codec not in self.UNSUPPORTED_CODECS:
                logger.info(f"Using cached converted video: {converted_path.name}")
                return converted_path
        return None

    def convert(
        self,
        input_path: Path,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Tuple[Path, bool]:
        """
        Convert a video to H.264 if needed.

        Args:
            input_path: Path to the input video
            progress_callback: Optional callback for progress updates (percentage, message)

        Returns:
            Tuple of (output_path, was_converted)
            - output_path: Path to the video (converted or original)
            - was_converted: True if conversion was performed
        """
        if not self.ffmpeg_available:
            logger.warning("FFmpeg not available, skipping conversion")
            return input_path, False

        # Check if conversion is needed
        if not self.needs_conversion(input_path):
            logger.debug(f"No conversion needed for {input_path.name}")
            return input_path, False

        # Check for cached conversion
        cached = self.is_already_converted(input_path)
        if cached:
            if progress_callback:
                progress_callback(100, "Using cached conversion")
            return cached, True

        # Perform conversion
        output_path = self.get_converted_path(input_path)
        
        if progress_callback:
            progress_callback(0, "Starting video conversion...")

        try:
            logger.info("=" * 60)
            logger.info("VIDEO CONVERSION STARTED")
            logger.info(f"  Input: {input_path.name}")
            logger.info(f"  Output: {output_path.name}")
            logger.info("=" * 60)
            
            # Get video duration for progress calculation
            duration = self._get_duration(input_path)
            logger.info(f"  Duration: {duration:.1f} seconds")
            
            # FFmpeg command for conversion with verbose output
            cmd = [
                'ffmpeg',
                '-y',  # Overwrite output
                '-i', str(input_path),
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-crf', '20',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-movflags', '+faststart',
                '-progress', 'pipe:1',
                '-stats',
                str(output_path)
            ]
            
            logger.info(f"  Command: ffmpeg -y -i [input] -c:v libx264 -preset veryfast ...")
            
            # List for stderr lines
            stderr_lines = []
            
            def read_stderr(pipe, lines_list):
                """Read stderr in a separate thread."""
                try:
                    for line in iter(pipe.readline, ''):
                        line = line.strip()
                        if line:
                            lines_list.append(line)
                            # Log important stderr messages
                            if any(x in line.lower() for x in ['error', 'warning', 'failed', 'invalid']):
                                logger.warning(f"  FFmpeg: {line}")
                            elif 'frame=' in line or 'size=' in line:
                                logger.debug(f"  {line}")
                except:
                    pass
                finally:
                    try:
                        pipe.close()
                    except:
                        pass
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # Start thread to read stderr
            stderr_thread = threading.Thread(target=read_stderr, args=(process.stderr, stderr_lines))
            stderr_thread.daemon = True
            stderr_thread.start()
            
            # Monitor progress from stdout
            last_progress = 0
            speed_info = ""
            
            for line in process.stdout:
                line = line.strip()
                
                if 'out_time_ms=' in line:
                    try:
                        time_ms = int(line.split('=')[1])
                        if duration > 0:
                            progress = min(int((time_ms / 1000000) / duration * 100), 99)
                            if progress != last_progress and progress > 0:
                                last_progress = progress
                                msg = f"Converting: {progress}% {speed_info}".strip()
                                logger.info(f"  {msg}")
                                if progress_callback:
                                    progress_callback(progress, msg)
                    except ValueError:
                        pass
                elif 'speed=' in line:
                    try:
                        speed = line.split('=')[1].strip()
                        if speed and speed != 'N/A':
                            speed_info = f"(speed: {speed})"
                    except:
                        pass
            
            process.wait()
            stderr_thread.join(timeout=2)
            
            # Log completion status
            logger.info("=" * 60)
            if process.returncode == 0 and output_path.exists():
                file_size = output_path.stat().st_size / (1024 * 1024)
                logger.info("CONVERSION SUCCESSFUL!")
                logger.info(f"  Output size: {file_size:.1f} MB")
                logger.info("=" * 60)
                if progress_callback:
                    progress_callback(100, "Conversion complete!")
                return output_path, True
            else:
                logger.error("CONVERSION FAILED!")
                logger.error(f"  Return code: {process.returncode}")
                if stderr_lines:
                    logger.error("  FFmpeg stderr (last 20 lines):")
                    for line in stderr_lines[-20:]:
                        logger.error(f"    {line}")
                logger.info("=" * 60)
                if progress_callback:
                    progress_callback(0, "Conversion failed!")
                return input_path, False

        except Exception as e:
            logger.error(f"Video conversion error: {e}", exc_info=True)
            return input_path, False

    def _get_duration(self, file_path: Path) -> float:
        """Get video duration in seconds."""
        try:
            result = subprocess.run(
                [
                    'ffprobe',
                    '-v', 'quiet',
                    '-select_streams', 'v:0',
                    '-show_entries', 'format=duration',
                    '-of', 'json',
                    str(file_path)
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return float(data.get('format', {}).get('duration', 0))
        except Exception:
            pass
        return 0

    def cleanup_converted(self, original_path: Path):
        """
        Remove the converted version of a file.

        Args:
            original_path: Path to the original video
        """
        converted_path = self.get_converted_path(original_path)
        if converted_path.exists():
            try:
                converted_path.unlink()
                logger.info(f"Removed converted file: {converted_path.name}")
            except Exception as e:
                logger.warning(f"Failed to remove converted file: {e}")
