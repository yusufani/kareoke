"""
Real-time tempo and key shifting.

Singers need two independent controls: *speed* (slow the song down to learn it)
and *key* (move it into their range). Doing either naively — just reading the
samples faster — moves both at once, which is why the two stages here are
separate:

    source --> WSOLA time-stretch by T --> linear resample by p --> output

with ``p = 2**(semitones/12)`` and ``T = p / speed``. The stretch changes
duration without touching pitch; the resample then moves pitch by exactly ``p``
and undoes ``p`` worth of the duration change, leaving overall speed at
``speed``.

Cost matters: the common case is speed 1.0 and key 0, where the whole engine is
bypassed and playback is a plain array slice. The machinery only spins up once
the user actually turns a knob.
"""
import logging
from typing import List

import numpy as np
from scipy import signal

logger = logging.getLogger(__name__)


class StemReader:
    """Zero-padding random-access view over a set of equal-length stems.

    Holds a scratch buffer so a read on the audio thread allocates nothing.
    """

    def __init__(self, stems: List[np.ndarray], channels: int = 2,
                 scratch: int = 8192):
        self.stems = [np.ascontiguousarray(s, dtype=np.float32) for s in stems]
        self.channels = channels
        self.total = min((len(s) for s in self.stems), default=0)
        self.gains = np.zeros(len(self.stems), dtype=np.float32)
        self._scratch = np.zeros((scratch, channels), dtype=np.float32)

    def set_gains(self, gains) -> None:
        self.gains[:] = gains

    def read(self, start: int, count: int) -> np.ndarray:
        if count <= 0:
            return self._scratch[:0]
        if count > len(self._scratch):
            self._scratch = np.zeros((count, self.channels), dtype=np.float32)
        out = self._scratch[:count]
        out[:] = 0.0
        start = max(0, int(start))
        if start >= self.total:
            return out
        end = min(start + count, self.total)
        length = end - start
        for stem, gain in zip(self.stems, self.gains):
            if gain:
                out[:length] += stem[start:end] * gain
        return out


class PitchTimeShifter:
    """Streaming WSOLA time-stretch followed by a resampler.

    Not thread-safe: it is driven exclusively from the audio callback.
    """

    def __init__(self, sample_rate: int = 44100, channels: int = 2,
                 frame: int = 2048, hop: int = 512, search: int = 256):
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame = frame
        self.hop = hop
        self.search = search
        self.overlap = frame - hop

        window = np.hanning(frame).astype(np.float32)
        # Overlapping Hann windows at hop = frame/4 sum to frame/(2*hop).
        self._window = window / ((frame / hop) / 2.0)

        self.speed = 1.0
        self.semitones = 0.0
        self._ratio = 1.0        # p — resample ratio, i.e. the pitch factor
        self._stretch = 1.0      # T — time-stretch factor
        self.bypass = True

        self._analysis = 0.0     # un-adjusted read pointer, in source frames
        self._template = np.zeros(self.overlap, dtype=np.float32)
        self._ola = np.zeros((frame + hop, channels), dtype=np.float32)
        self._res_buf = np.zeros((0, channels), dtype=np.float32)
        self._phase = 0.0
        self._primed = False

    # -- configuration ----------------------------------------------------
    def configure(self, speed: float, semitones: float) -> None:
        speed = float(np.clip(speed, 0.5, 2.0))
        semitones = float(np.clip(semitones, -12.0, 12.0))
        if speed == self.speed and semitones == self.semitones:
            return
        self.speed = speed
        self.semitones = semitones
        self._ratio = float(2.0 ** (semitones / 12.0))
        self._stretch = self._ratio / speed
        was_bypassed = self.bypass
        self.bypass = abs(speed - 1.0) < 1e-6 and abs(semitones) < 1e-6
        if was_bypassed != self.bypass:
            self._reset_buffers()
        logger.debug("timescale: speed=%.2f key=%+.1f bypass=%s",
                     speed, semitones, self.bypass)

    def seek(self, position_frames: float) -> None:
        self._analysis = max(0.0, float(position_frames))
        self._reset_buffers()

    @property
    def position(self) -> float:
        """Current read position in source frames."""
        return self._analysis

    def _reset_buffers(self) -> None:
        self._ola[:] = 0.0
        self._res_buf = np.zeros((0, self.channels), dtype=np.float32)
        self._template[:] = 0.0
        self._phase = 0.0
        self._primed = False

    # -- the audio-thread entry point -------------------------------------
    def read(self, reader: StemReader, count: int) -> np.ndarray:
        """Produce ``count`` output frames of mixed, shifted audio."""
        if count <= 0:
            return np.zeros((0, self.channels), dtype=np.float32)

        if self.bypass:
            start = int(self._analysis)
            block = reader.read(start, count).copy()
            self._analysis = start + count
            return block

        needed = int(self._phase + count * self._ratio) + 3
        while len(self._res_buf) < needed:
            self._res_buf = np.concatenate([self._res_buf, self._ola_step(reader)])

        index = self._phase + np.arange(count, dtype=np.float64) * self._ratio
        base = index.astype(np.int64)
        frac = (index - base).astype(np.float32)[:, None]
        block = (self._res_buf[base] * (1.0 - frac)
                 + self._res_buf[base + 1] * frac).astype(np.float32)

        last = float(index[-1])
        consumed = int(last)
        if consumed:
            self._res_buf = self._res_buf[consumed:]
        self._phase = last - consumed + self._ratio
        return block

    # -- WSOLA ------------------------------------------------------------
    def _ola_step(self, reader: StemReader) -> np.ndarray:
        """Emit one synthesis hop of pitch-preserving, time-stretched audio."""
        start = self._align(reader)
        self._ola[:self.frame] += reader.read(start, self.frame) * self._window[:, None]

        out = self._ola[:self.hop].copy()
        self._ola[:-self.hop] = self._ola[self.hop:]
        self._ola[-self.hop:] = 0.0

        # Remember what naturally follows this frame so the next one can be
        # chosen to continue the waveform rather than cut across it.
        tail = reader.read(start + self.hop, self.overlap)
        self._template = tail.mean(axis=1).astype(np.float32)

        # The analysis pointer advances by a fixed 1/T per synthesis hop; the
        # WSOLA search offset is deliberately *not* accumulated into it, or the
        # effective stretch factor would drift over a whole song.
        self._analysis += self.hop / self._stretch
        return out

    def _align(self, reader: StemReader) -> int:
        """Offset near the analysis pointer that best continues the last frame."""
        nominal = max(0, int(self._analysis))
        if not self._primed:
            self._primed = True
            return nominal

        low = max(0, nominal - self.search)
        region = reader.read(low, self.overlap + 2 * self.search)
        mono = region.mean(axis=1).astype(np.float32)

        # Normalised cross-correlation, FFT-based so the search is nearly free.
        scores = signal.correlate(mono, self._template, mode="valid", method="fft")
        energy = signal.correlate(mono * mono, np.ones(self.overlap, dtype=np.float32),
                                  mode="valid", method="fft")
        best = int(np.argmax(scores / np.sqrt(np.maximum(energy, 1e-9))))
        return low + best
