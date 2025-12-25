"""
Voice Effects Module
Provides real-time audio effects for karaoke (reverb, echo).
"""
import logging
from typing import Optional
import numpy as np
from scipy import signal


logger = logging.getLogger(__name__)


class VoiceEffects:
    """
    Real-time voice effects processor.
    Provides reverb and echo effects for microphone input.
    """

    def __init__(self, sample_rate: int = 44100):
        """
        Initialize voice effects processor.

        Args:
            sample_rate: Audio sample rate
        """
        self.sample_rate = sample_rate
        self.enabled = False
        
        # Reverb settings
        self.reverb_enabled = True
        self.reverb_intensity = 0.3  # 0.0 to 1.0
        self.reverb_decay = 0.5  # Decay time factor
        
        # Echo settings
        self.echo_enabled = True
        self.echo_delay_ms = 200  # Delay in milliseconds
        self.echo_feedback = 0.3  # Feedback amount (0.0 to 0.8)
        
        # Internal buffers
        self._echo_buffer: Optional[np.ndarray] = None
        self._echo_buffer_pos = 0
        self._reverb_ir: Optional[np.ndarray] = None
        self._reverb_state: Optional[np.ndarray] = None
        
        # Initialize buffers
        self._init_buffers()
        
        logger.info("VoiceEffects initialized")

    def _init_buffers(self):
        """Initialize internal audio buffers."""
        # Echo buffer (max 1 second delay)
        max_delay_samples = int(self.sample_rate * 1.0)
        self._echo_buffer = np.zeros((max_delay_samples, 2), dtype=np.float32)
        self._echo_buffer_pos = 0
        
        # Generate simple reverb impulse response
        self._generate_reverb_ir()

    def _generate_reverb_ir(self):
        """Generate a simple reverb impulse response."""
        # Duration of reverb tail (in samples)
        # Keep short for low latency - ~150ms is good for real-time karaoke
        duration = int(self.sample_rate * 0.15 * self.reverb_decay)
        
        # Create exponentially decaying noise for reverb
        t = np.linspace(0, 1, duration)
        decay = np.exp(-5 * t)  # Faster decay for tighter reverb
        
        # Random noise modulated by decay curve
        np.random.seed(42)  # Reproducible IR
        noise = np.random.randn(duration)
        self._reverb_ir = (noise * decay).astype(np.float32)
        
        # Normalize
        self._reverb_ir /= np.max(np.abs(self._reverb_ir) + 1e-6)
        
        # Initialize convolution state for each channel (stereo)
        state_len = len(self._reverb_ir) - 1
        self._reverb_state_left = np.zeros(state_len, dtype=np.float32)
        self._reverb_state_right = np.zeros(state_len, dtype=np.float32)

    def set_reverb_intensity(self, intensity: float):
        """
        Set reverb intensity.

        Args:
            intensity: Reverb intensity (0.0 to 1.0)
        """
        self.reverb_intensity = max(0.0, min(1.0, intensity))
        logger.debug(f"Reverb intensity set to {self.reverb_intensity}")

    def set_echo_delay(self, delay_ms: float):
        """
        Set echo delay time.

        Args:
            delay_ms: Echo delay in milliseconds (50 to 500)
        """
        self.echo_delay_ms = max(50, min(500, delay_ms))
        logger.debug(f"Echo delay set to {self.echo_delay_ms}ms")

    def set_echo_feedback(self, feedback: float):
        """
        Set echo feedback amount.

        Args:
            feedback: Echo feedback (0.0 to 0.8)
        """
        self.echo_feedback = max(0.0, min(0.8, feedback))
        logger.debug(f"Echo feedback set to {self.echo_feedback}")

    def process(self, audio_data: np.ndarray) -> np.ndarray:
        """
        Process audio data with effects.

        Args:
            audio_data: Input audio data (samples, channels) float32

        Returns:
            Processed audio data with effects applied
        """
        if not self.enabled:
            return audio_data

        output = audio_data.copy()

        # Apply echo effect
        if self.echo_enabled and self.echo_feedback > 0:
            output = self._apply_echo(output)

        # Apply reverb effect
        if self.reverb_enabled and self.reverb_intensity > 0:
            output = self._apply_reverb(output)

        return output

    def _apply_echo(self, audio_data: np.ndarray) -> np.ndarray:
        """
        Apply echo effect to audio.

        Args:
            audio_data: Input audio data

        Returns:
            Audio with echo applied
        """
        delay_samples = int(self.echo_delay_ms * self.sample_rate / 1000)
        delay_samples = min(delay_samples, len(self._echo_buffer) - 1)
        
        output = np.zeros_like(audio_data)
        
        for i in range(len(audio_data)):
            # Read from delay buffer
            read_pos = (self._echo_buffer_pos - delay_samples) % len(self._echo_buffer)
            delayed = self._echo_buffer[read_pos]
            
            # Mix dry + delayed
            output[i] = audio_data[i] + delayed * self.echo_feedback
            
            # Write to delay buffer (input + feedback)
            self._echo_buffer[self._echo_buffer_pos] = audio_data[i] + delayed * self.echo_feedback * 0.5
            
            # Advance buffer position
            self._echo_buffer_pos = (self._echo_buffer_pos + 1) % len(self._echo_buffer)

        return output

    def _apply_reverb(self, audio_data: np.ndarray) -> np.ndarray:
        """
        Apply reverb effect to audio using convolution.

        Args:
            audio_data: Input audio data

        Returns:
            Audio with reverb applied
        """
        output = np.zeros_like(audio_data)
        
        if audio_data.ndim > 1 and audio_data.shape[1] >= 2:
            # Stereo: process each channel with its own state
            # Left channel
            reverb_left, self._reverb_state_left = signal.lfilter(
                self._reverb_ir, [1.0], audio_data[:, 0], zi=self._reverb_state_left
            )
            output[:, 0] = (1 - self.reverb_intensity) * audio_data[:, 0] + self.reverb_intensity * reverb_left
            
            # Right channel
            reverb_right, self._reverb_state_right = signal.lfilter(
                self._reverb_ir, [1.0], audio_data[:, 1], zi=self._reverb_state_right
            )
            output[:, 1] = (1 - self.reverb_intensity) * audio_data[:, 1] + self.reverb_intensity * reverb_right
        else:
            # Mono
            reverb_signal, self._reverb_state_left = signal.lfilter(
                self._reverb_ir, [1.0], audio_data.flatten(), zi=self._reverb_state_left
            )
            output = (1 - self.reverb_intensity) * audio_data + self.reverb_intensity * reverb_signal.reshape(audio_data.shape)

        return output.astype(np.float32)

    def reset(self):
        """Reset all effect buffers."""
        self._init_buffers()
        logger.debug("VoiceEffects buffers reset")

    def enable(self):
        """Enable effects processing."""
        self.enabled = True
        logger.info("VoiceEffects enabled")

    def disable(self):
        """Disable effects processing."""
        self.enabled = False
        logger.info("VoiceEffects disabled")
