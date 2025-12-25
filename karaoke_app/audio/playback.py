"""
Audio Playback Module
Handles synchronized playback of vocal and instrumental stems with real-time mixing.
Includes microphone pass-through with effects and recording support.
"""
import logging
import threading
import time
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import soundfile as sf
import sounddevice as sd

from .voice_effects import VoiceEffects
from .recording_manager import RecordingManager


logger = logging.getLogger(__name__)


class StemPlayer:
    """
    Manages synchronized playback of two audio stems with independent volume control.
    Also handles microphone pass-through with voice effects and recording.
    """

    def __init__(self, recordings_dir: Optional[Path] = None):
        """
        Initialize the stem player.

        Args:
            recordings_dir: Directory for saving recordings (optional)
        """
        self.vocals_data: Optional[np.ndarray] = None
        self.instrumental_data: Optional[np.ndarray] = None
        self.sample_rate: int = 44100
        self.duration: float = 0.0

        # Playback state
        self.is_playing: bool = False
        self.is_loaded: bool = False
        self.current_position: float = 0.0  # Position in seconds

        # Volume controls (0.0 to 1.0)
        self.vocals_volume: float = 1.0
        self.instrumental_volume: float = 1.0
        self.microphone_volume: float = 0.7

        # Mute controls
        self.vocals_muted: bool = False
        self.instrumental_muted: bool = False
        self.microphone_muted: bool = False

        # Microphone settings
        self.microphone_enabled: bool = False
        self.microphone_device_id: Optional[int] = None
        
        # Voice effects
        self.voice_effects = VoiceEffects(self.sample_rate)
        
        # Recording manager
        if recordings_dir:
            self.recording_manager = RecordingManager(recordings_dir, self.sample_rate)
        else:
            self.recording_manager = None

        # Audio stream
        self.stream: Optional[sd.Stream] = None
        self.playback_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

        # Position update callback
        self.position_callback: Optional[Callable[[float], None]] = None

        # Microphone input buffer (for real-time mixing)
        self._mic_buffer: Optional[np.ndarray] = None
        self._mic_buffer_lock = threading.Lock()

        logger.info("StemPlayer initialized with microphone support")

    def load_stems(self, vocals_path: Path, instrumental_path: Path):
        """
        Load vocal and instrumental stems.

        Args:
            vocals_path: Path to vocals WAV file
            instrumental_path: Path to instrumental WAV file

        Raises:
            Exception: If loading fails
        """
        try:
            logger.info(f"Loading stems: {vocals_path.name}, {instrumental_path.name}")

            # Load vocals
            vocals_data, vocals_sr = sf.read(str(vocals_path), dtype='float32')

            # Load instrumental
            instrumental_data, instrumental_sr = sf.read(str(instrumental_path), dtype='float32')

            # Ensure same sample rate
            if vocals_sr != instrumental_sr:
                raise ValueError(
                    f"Sample rate mismatch: vocals={vocals_sr}, instrumental={instrumental_sr}"
                )

            self.sample_rate = vocals_sr
            
            # Update voice effects sample rate
            self.voice_effects.sample_rate = self.sample_rate

            # Ensure both are stereo
            if vocals_data.ndim == 1:
                vocals_data = np.column_stack([vocals_data, vocals_data])
            if instrumental_data.ndim == 1:
                instrumental_data = np.column_stack([instrumental_data, instrumental_data])

            # Ensure same length (pad shorter one with zeros)
            max_len = max(len(vocals_data), len(instrumental_data))
            if len(vocals_data) < max_len:
                padding = np.zeros((max_len - len(vocals_data), vocals_data.shape[1]))
                vocals_data = np.vstack([vocals_data, padding])
            if len(instrumental_data) < max_len:
                padding = np.zeros((max_len - len(instrumental_data), instrumental_data.shape[1]))
                instrumental_data = np.vstack([instrumental_data, padding])

            self.vocals_data = vocals_data
            self.instrumental_data = instrumental_data
            self.duration = len(vocals_data) / self.sample_rate
            self.current_position = 0.0
            self.is_loaded = True

            logger.info(f"Stems loaded. Duration: {self.duration:.2f}s, SR: {self.sample_rate}Hz")

        except Exception as e:
            logger.error(f"Failed to load stems: {str(e)}", exc_info=True)
            raise Exception(f"Failed to load audio stems: {str(e)}")

    def play(self):
        """Start or resume playback."""
        if not self.is_loaded:
            logger.warning("Cannot play: no stems loaded")
            return

        if self.is_playing:
            logger.warning("Already playing")
            return

        logger.info(f"Starting playback from position {self.current_position:.2f}s")
        self.is_playing = True
        self.stop_event.clear()

        # Start playback in a separate thread
        self.playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self.playback_thread.start()

    def pause(self):
        """Pause playback."""
        if self.is_playing:
            logger.info("Pausing playback")
            self.is_playing = False
            self.stop_event.set()

            if self.playback_thread:
                self.playback_thread.join(timeout=1.0)

            if self.stream and self.stream.active:
                self.stream.stop()

    def stop(self):
        """Stop playback and reset position."""
        logger.info("Stopping playback")
        self.pause()
        self.current_position = 0.0

        # Only call callback if not during shutdown (Qt objects may be deleted)
        try:
            if self.position_callback:
                self.position_callback(0.0)
        except RuntimeError:
            # Qt object already deleted during shutdown
            pass

    def seek(self, position: float):
        """
        Seek to a specific position.

        Args:
            position: Position in seconds
        """
        if not self.is_loaded:
            return

        # Clamp position
        position = max(0.0, min(position, self.duration))

        was_playing = self.is_playing

        # Stop playback if playing
        if was_playing:
            self.pause()

        self.current_position = position
        logger.info(f"Seeked to {position:.2f}s")

        if self.position_callback:
            self.position_callback(position)

        # Resume playback if it was playing
        if was_playing:
            self.play()

    def set_vocals_volume(self, volume: float):
        """
        Set vocals volume.

        Args:
            volume: Volume level (0.0 to 1.0)
        """
        self.vocals_volume = max(0.0, min(1.0, volume))

    def set_instrumental_volume(self, volume: float):
        """
        Set instrumental volume.

        Args:
            volume: Volume level (0.0 to 1.0)
        """
        self.instrumental_volume = max(0.0, min(1.0, volume))

    def set_microphone_volume(self, volume: float):
        """
        Set microphone volume.

        Args:
            volume: Volume level (0.0 to 1.0)
        """
        self.microphone_volume = max(0.0, min(1.0, volume))

    def set_vocals_muted(self, muted: bool):
        """Mute or unmute vocals."""
        self.vocals_muted = muted

    def set_instrumental_muted(self, muted: bool):
        """Mute or unmute instrumental."""
        self.instrumental_muted = muted

    def set_microphone_muted(self, muted: bool):
        """Mute or unmute microphone."""
        self.microphone_muted = muted

    def set_microphone_enabled(self, enabled: bool):
        """Enable or disable microphone pass-through."""
        was_playing = self.is_playing
        old_position = self.current_position
        
        # Need to restart playback to switch stream type
        if was_playing:
            self.pause()
        
        self.microphone_enabled = enabled
        if enabled:
            self.voice_effects.enable()
            logger.info("Microphone enabled")
        else:
            self.voice_effects.disable()
            logger.info("Microphone disabled")
        
        # Resume playback with new stream configuration
        if was_playing:
            self.current_position = old_position
            self.play()

    def set_microphone_device(self, device_id: Optional[int]):
        """
        Set the microphone device to use.

        Args:
            device_id: Device ID or None for default
        """
        self.microphone_device_id = device_id
        logger.info(f"Microphone device set to: {device_id}")

    def set_reverb_intensity(self, intensity: float):
        """Set reverb effect intensity (0.0 to 1.0)."""
        self.voice_effects.set_reverb_intensity(intensity)

    def set_echo_delay(self, delay_ms: float):
        """Set echo delay in milliseconds (50 to 500)."""
        self.voice_effects.set_echo_delay(delay_ms)

    def set_echo_feedback(self, feedback: float):
        """Set echo feedback amount (0.0 to 0.8)."""
        self.voice_effects.set_echo_feedback(feedback)

    def set_effects_enabled(self, enabled: bool):
        """Enable or disable voice effects."""
        if enabled:
            self.voice_effects.enable()
        else:
            self.voice_effects.disable()

    def start_recording(self, song_name: str = "Unknown"):
        """Start recording the performance."""
        if self.recording_manager:
            self.recording_manager.start_recording(song_name)

    def stop_recording(self) -> Optional[Path]:
        """Stop recording and return the saved file path."""
        if self.recording_manager:
            return self.recording_manager.stop_recording()
        return None

    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self.recording_manager.is_recording if self.recording_manager else False

    def get_recording_duration(self) -> float:
        """Get current recording duration in seconds."""
        return self.recording_manager.get_recording_duration() if self.recording_manager else 0.0

    def get_position(self) -> float:
        """Get current playback position in seconds."""
        return self.current_position

    def get_duration(self) -> float:
        """Get total duration in seconds."""
        return self.duration

    def _playback_loop(self):
        """Internal playback loop (runs in separate thread)."""
        try:
            # Calculate starting frame
            start_frame = int(self.current_position * self.sample_rate)

            # Chunk size depends on whether microphone is enabled
            # Smaller = lower latency for mic, but more CPU usage
            if self.microphone_enabled:
                chunk_size = 256  # ~6ms latency at 44100Hz - good for real-time monitoring
            else:
                chunk_size = 2048  # ~46ms - efficient for playback only

            # Create bidirectional audio stream if microphone enabled
            if self.microphone_enabled:
                device = (self.microphone_device_id, None)  # (input, output)
                self.stream = sd.Stream(
                    samplerate=self.sample_rate,
                    device=device,
                    channels=(1, 2),  # Mono input, stereo output
                    dtype='float32',
                    blocksize=chunk_size,
                    latency='low',  # Request low-latency mode
                    callback=self._audio_callback_wrapper(start_frame, chunk_size)
                )
            else:
                # Output-only stream
                self.stream = sd.OutputStream(
                    samplerate=self.sample_rate,
                    channels=2,
                    dtype='float32',
                    blocksize=chunk_size
                )
            
            self.stream.start()

            if self.microphone_enabled:
                # Callback-based mode: just wait for completion
                current_frame = start_frame
                total_frames = len(self.vocals_data)
                
                while self.is_playing and current_frame < total_frames:
                    if self.stop_event.is_set():
                        break
                    time.sleep(0.05)
                    # Position is updated in callback
                    current_frame = int(self.current_position * self.sample_rate)
            else:
                # Manual write mode (no microphone)
                current_frame = start_frame
                total_frames = len(self.vocals_data)

                last_callback_time = time.time()
                callback_interval = 0.1  # Update position every 100ms

                while self.is_playing and current_frame < total_frames:
                    if self.stop_event.is_set():
                        break

                    # Calculate chunk end
                    chunk_end = min(current_frame + chunk_size, total_frames)

                    # Get audio chunks
                    vocals_chunk = self.vocals_data[current_frame:chunk_end]
                    instrumental_chunk = self.instrumental_data[current_frame:chunk_end]

                    # Apply volume and mute
                    vocals_gain = self.vocals_volume if not self.vocals_muted else 0.0
                    instrumental_gain = self.instrumental_volume if not self.instrumental_muted else 0.0

                    # Mix chunks
                    mixed = (vocals_chunk * vocals_gain) + (instrumental_chunk * instrumental_gain)

                    # Prevent clipping
                    max_val = np.abs(mixed).max()
                    if max_val > 1.0:
                        mixed = mixed / max_val

                    # Add to recording if active
                    if self.recording_manager and self.recording_manager.is_recording:
                        self.recording_manager.add_audio_chunk(mixed)

                    # Write to stream
                    self.stream.write(mixed)

                    # Update position
                    current_frame = chunk_end
                    self.current_position = current_frame / self.sample_rate

                    # Callback for position updates (don't spam)
                    current_time = time.time()
                    if current_time - last_callback_time >= callback_interval:
                        if self.position_callback:
                            self.position_callback(self.current_position)
                        last_callback_time = current_time

            # Playback finished
            if int(self.current_position * self.sample_rate) >= len(self.vocals_data):
                self.current_position = 0.0
                if self.position_callback:
                    self.position_callback(0.0)

            self.is_playing = False

            if self.stream:
                self.stream.stop()
                self.stream.close()
                self.stream = None

        except Exception as e:
            logger.error(f"Playback error: {str(e)}", exc_info=True)
            self.is_playing = False

    def _audio_callback_wrapper(self, start_frame: int, chunk_size: int):
        """Create a closure for the audio callback with state."""
        current_frame = [start_frame]
        total_frames = len(self.vocals_data)
        last_callback_time = [time.time()]
        callback_interval = 0.1

        def audio_callback(indata, outdata, frames, time_info, status):
            """Audio callback for bidirectional stream."""
            if status:
                logger.warning(f"Audio callback status: {status}")

            # Get current frame
            frame = current_frame[0]
            
            if frame >= total_frames or not self.is_playing:
                outdata.fill(0)
                return

            # Calculate chunk end
            chunk_end = min(frame + frames, total_frames)
            actual_frames = chunk_end - frame

            # Get audio chunks
            vocals_chunk = self.vocals_data[frame:chunk_end]
            instrumental_chunk = self.instrumental_data[frame:chunk_end]

            # Apply volume and mute
            vocals_gain = self.vocals_volume if not self.vocals_muted else 0.0
            instrumental_gain = self.instrumental_volume if not self.instrumental_muted else 0.0

            # Mix stems
            mixed = (vocals_chunk * vocals_gain) + (instrumental_chunk * instrumental_gain)

            # Add microphone input if enabled and not muted
            if self.microphone_enabled and not self.microphone_muted:
                # Convert mono input to stereo
                mic_data = indata[:actual_frames, 0] if indata.ndim > 1 else indata[:actual_frames]
                mic_stereo = np.column_stack([mic_data, mic_data])
                
                # Apply voice effects
                mic_processed = self.voice_effects.process(mic_stereo)
                
                # Apply microphone volume and add to mix
                mixed += mic_processed * self.microphone_volume

            # Prevent clipping
            max_val = np.abs(mixed).max()
            if max_val > 1.0:
                mixed = mixed / max_val

            # Pad if needed
            if actual_frames < frames:
                padded = np.zeros((frames, 2), dtype=np.float32)
                padded[:actual_frames] = mixed
                mixed = padded

            # Write to output
            outdata[:] = mixed

            # Add to recording if active
            if self.recording_manager and self.recording_manager.is_recording:
                self.recording_manager.add_audio_chunk(mixed[:actual_frames])

            # Update position
            current_frame[0] = chunk_end
            self.current_position = chunk_end / self.sample_rate

            # Position callback
            current_time = time.time()
            if current_time - last_callback_time[0] >= callback_interval:
                if self.position_callback:
                    self.position_callback(self.current_position)
                last_callback_time[0] = current_time

        return audio_callback

    def cleanup(self):
        """Clean up resources."""
        self.stop()
        
        # Stop recording if active
        if self.recording_manager and self.recording_manager.is_recording:
            self.recording_manager.stop_recording()
        
        if self.stream:
            self.stream.close()
            self.stream = None

        logger.info("StemPlayer cleaned up")

    def __del__(self):
        """Destructor."""
        self.cleanup()
