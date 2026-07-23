"""
Microphone effects chain.

Everything in this file runs inside the audio callback, once per microphone,
every few milliseconds. That budget rules out the obvious implementations:

* Reverb is a Schroeder/Freeverb network of delay lines, not an FIR convolution
  with a 150 ms impulse response. The convolution costs thousands of multiplies
  *per sample*; the delay network costs a handful of vector operations per
  block, because a feedback delay longer than the block never wraps inside it
  and so vectorises exactly.
* Pitch correction is a crossfading delay-line shifter rather than a phase
  vocoder, for the same reason.

Chain order: gate -> high-pass -> compressor -> autotune -> EQ -> echo -> reverb.
Dynamics come before colour so the effects sit on a level-controlled signal.
"""
import logging

import numpy as np
from scipy import signal

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------


class DelayLine:
    """Circular stereo delay line with vectorised block read/write."""

    def __init__(self, length: int, channels: int = 2):
        self.length = max(2, int(length))
        self.buffer = np.zeros((self.length, channels), dtype=np.float32)
        self.pos = 0

    def reset(self) -> None:
        self.buffer[:] = 0.0
        self.pos = 0

    def read_delayed(self, delay: int, count: int) -> np.ndarray:
        """The ``count`` frames ending ``delay`` frames before the write head."""
        start = (self.pos - delay) % self.length
        end = start + count
        if end <= self.length:
            return self.buffer[start:end]
        head = self.length - start
        return np.concatenate([self.buffer[start:], self.buffer[:end - self.length]])

    def write(self, block: np.ndarray) -> None:
        count = len(block)
        end = self.pos + count
        if end <= self.length:
            self.buffer[self.pos:end] = block
        else:
            head = self.length - self.pos
            self.buffer[self.pos:] = block[:head]
            self.buffer[:end - self.length] = block[head:]
        self.pos = end % self.length


class _Comb:
    """Feedback comb filter: ``y[n] = x[n] + g * lp(y[n-d])``."""

    def __init__(self, delay: int, feedback: float, damp: float, channels: int = 2):
        self.delay = delay
        self.feedback = feedback
        self.damp = damp
        self.line = DelayLine(delay + 8, channels)
        self.store = np.zeros(channels, dtype=np.float32)

    def reset(self) -> None:
        self.line.reset()
        self.store[:] = 0.0

    def process(self, block: np.ndarray) -> np.ndarray:
        delayed = self.line.read_delayed(self.delay, len(block)).copy()
        # One-pole damping on the feedback path, applied to the block mean —
        # a per-sample recursion here would cost more than the whole reverb.
        damped = delayed * (1.0 - self.damp) + self.store * self.damp
        self.store = damped[-1].copy() if len(damped) else self.store
        self.line.write(block + damped * self.feedback)
        return delayed


class _AllPass:
    """Schroeder all-pass: ``y[n] = -g*x[n] + x[n-d] + g*y[n-d]``."""

    def __init__(self, delay: int, gain: float = 0.5, channels: int = 2):
        self.delay = delay
        self.gain = gain
        self.line = DelayLine(delay + 8, channels)

    def reset(self) -> None:
        self.line.reset()

    def process(self, block: np.ndarray) -> np.ndarray:
        delayed = self.line.read_delayed(self.delay, len(block)).copy()
        self.line.write(block + delayed * self.gain)
        return delayed - block * self.gain


class Reverb:
    """Freeverb-style room.

    One knob again: it sets both the wet mix *and* the room size, so a low
    setting is a small tight room rather than a cathedral turned down. A long
    tail at a low level still sounds like a cathedral — just a distant one.
    """

    _COMBS = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)
    _ALLPASS = (556, 441, 341, 225)
    MIN_DECAY = 0.62
    MAX_DECAY = 0.88

    def __init__(self, sample_rate: int = 44100, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self.amount = 0.0
        self._build()
        self.set_amount(0.0)

    def set_amount(self, amount: float) -> None:
        self.amount = max(0.0, min(1.0, amount))
        decay = self.MIN_DECAY + (self.MAX_DECAY - self.MIN_DECAY) * self.amount
        for comb in self.combs:
            comb.feedback = decay

    def _build(self) -> None:
        scale = self.sample_rate / 44100.0
        self.combs = [
            _Comb(max(8, int(d * scale)), self.MIN_DECAY, 0.28, self.channels)
            for d in self._COMBS
        ]
        self.allpasses = [
            _AllPass(max(8, int(d * scale)), 0.5, self.channels)
            for d in self._ALLPASS
        ]
        # The shortest all-pass bounds how much we can process at once without
        # the feedback wrapping inside a single block.
        self.max_chunk = min(a.delay for a in self.allpasses)

    def set_sample_rate(self, sample_rate: int) -> None:
        if sample_rate != self.sample_rate:
            self.sample_rate = sample_rate
            self._build()
            self.set_amount(self.amount)

    def reset(self) -> None:
        for unit in self.combs + self.allpasses:
            unit.reset()

    def process(self, block: np.ndarray) -> np.ndarray:
        if self.amount <= 0.001 or not len(block):
            return block
        out = np.empty_like(block)
        for offset in range(0, len(block), self.max_chunk):
            chunk = block[offset:offset + self.max_chunk]
            wet = np.zeros_like(chunk)
            for comb in self.combs:
                wet += comb.process(chunk)
            wet *= 0.125
            for allpass in self.allpasses:
                wet = allpass.process(wet)
            # The dry path is left alone below about half wet: dipping the voice
            # to make room for its own reverb is what makes a mix sound washed.
            out[offset:offset + len(chunk)] = chunk * (1.0 - self.amount * 0.25) \
                + wet * (self.amount * 0.75)
        return out.astype(np.float32)


class Echo:
    """Feedback delay.

    One knob drives all three parameters, because that is what a singer means by
    "a bit of echo": a small setting should be one faint slap close behind the
    voice, and only a large setting should repeat. Holding feedback at a fixed
    floor — as an earlier version did — turned a nominal 8 % into a train of six
    audible repeats stretching over half a second.
    """

    MIN_DELAY_MS = 130.0
    MAX_DELAY_MS = 380.0

    def __init__(self, sample_rate: int = 44100, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self.amount = 0.0
        self.delay_ms = self.MIN_DELAY_MS
        self.feedback = 0.0
        self.line = DelayLine(int(sample_rate * 1.5), channels)

    def set_amount(self, amount: float) -> None:
        self.amount = max(0.0, min(1.0, amount))
        self.feedback = 0.55 * self.amount
        self.delay_ms = self.MIN_DELAY_MS + \
            (self.MAX_DELAY_MS - self.MIN_DELAY_MS) * self.amount

    def set_sample_rate(self, sample_rate: int) -> None:
        if sample_rate != self.sample_rate:
            self.sample_rate = sample_rate
            self.line = DelayLine(int(sample_rate * 1.5), self.channels)

    def reset(self) -> None:
        self.line.reset()

    def process(self, block: np.ndarray) -> np.ndarray:
        if self.amount <= 0.001 or not len(block):
            return block
        delay = int(self.delay_ms * self.sample_rate / 1000.0)
        delay = max(len(block) + 1, min(delay, self.line.length - 1))
        delayed = self.line.read_delayed(delay, len(block)).copy()
        self.line.write(block + delayed * self.feedback)
        # 0.7 caps the wet level: an echo as loud as the voice is a fault, not
        # an effect, and it is the first thing to feed back through speakers.
        return (block + delayed * self.amount * 0.7).astype(np.float32)


class ShelfEQ:
    """Low and high shelving pair, ±12 dB, driven by two 0..1 knobs."""

    def __init__(self, sample_rate: int = 44100, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self.bass = 0.5
        self.treble = 0.5
        self._sos = None
        self._zi = None
        self._dirty = True

    def set_sample_rate(self, sample_rate: int) -> None:
        if sample_rate != self.sample_rate:
            self.sample_rate = sample_rate
            self._dirty = True

    def set(self, bass: float, treble: float) -> None:
        if abs(bass - self.bass) > 1e-4 or abs(treble - self.treble) > 1e-4:
            self.bass, self.treble = bass, treble
            self._dirty = True

    @property
    def flat(self) -> bool:
        return abs(self.bass - 0.5) < 0.02 and abs(self.treble - 0.5) < 0.02

    def reset(self) -> None:
        self._dirty = True

    def _design(self) -> None:
        sections = []
        for gain_knob, freq, kind in ((self.bass, 180.0, "low"),
                                      (self.treble, 3800.0, "high")):
            gain_db = (gain_knob - 0.5) * 24.0
            if abs(gain_db) < 0.4:
                continue
            sections.append(_shelf_sos(self.sample_rate, freq, gain_db, kind))
        self._sos = np.vstack(sections) if sections else None
        self._zi = (np.zeros((len(self._sos), 2, self.channels), dtype=np.float64)
                    if self._sos is not None else None)
        self._dirty = False

    def process(self, block: np.ndarray) -> np.ndarray:
        if self._dirty:
            self._design()
        if self._sos is None or not len(block):
            return block
        out, self._zi = signal.sosfilt(self._sos, block, axis=0, zi=self._zi)
        return out.astype(np.float32)


def _shelf_sos(sample_rate: int, freq: float, gain_db: float, kind: str) -> np.ndarray:
    """RBJ cookbook shelving biquad, returned as a single SOS row."""
    amp = 10.0 ** (gain_db / 40.0)
    omega = 2.0 * np.pi * freq / sample_rate
    cos_w, sin_w = np.cos(omega), np.sin(omega)
    alpha = sin_w / 2.0 * np.sqrt((amp + 1.0 / amp) * (1.0 / 0.9 - 1.0) + 2.0)
    two_sqrt_a_alpha = 2.0 * np.sqrt(amp) * alpha

    if kind == "low":
        b0 = amp * ((amp + 1) - (amp - 1) * cos_w + two_sqrt_a_alpha)
        b1 = 2 * amp * ((amp - 1) - (amp + 1) * cos_w)
        b2 = amp * ((amp + 1) - (amp - 1) * cos_w - two_sqrt_a_alpha)
        a0 = (amp + 1) + (amp - 1) * cos_w + two_sqrt_a_alpha
        a1 = -2 * ((amp - 1) + (amp + 1) * cos_w)
        a2 = (amp + 1) + (amp - 1) * cos_w - two_sqrt_a_alpha
    else:
        b0 = amp * ((amp + 1) + (amp - 1) * cos_w + two_sqrt_a_alpha)
        b1 = -2 * amp * ((amp - 1) + (amp + 1) * cos_w)
        b2 = amp * ((amp + 1) + (amp - 1) * cos_w - two_sqrt_a_alpha)
        a0 = (amp + 1) - (amp - 1) * cos_w + two_sqrt_a_alpha
        a1 = 2 * ((amp - 1) - (amp + 1) * cos_w)
        a2 = (amp + 1) - (amp - 1) * cos_w - two_sqrt_a_alpha

    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


class NoiseGate:
    """Silences the mic between phrases. Smoothly ramped, so it never clicks."""

    def __init__(self, sample_rate: int = 44100, threshold_db: float = -46.0,
                 attack_ms: float = 4.0, release_ms: float = 140.0):
        self.sample_rate = sample_rate
        self.enabled = True
        self.threshold = 10.0 ** (threshold_db / 20.0)
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self._gain = 0.0

    def reset(self) -> None:
        self._gain = 0.0

    def process(self, block: np.ndarray) -> np.ndarray:
        if not self.enabled or not len(block):
            return block
        level = float(np.abs(block).max())
        target = 1.0 if level > self.threshold else 0.0
        block_ms = len(block) / self.sample_rate * 1000.0
        span = self.attack_ms if target > self._gain else self.release_ms
        coefficient = min(1.0, block_ms / max(span, 1e-6))
        new_gain = self._gain + (target - self._gain) * coefficient
        ramp = np.linspace(self._gain, new_gain, len(block), dtype=np.float32)
        self._gain = new_gain
        return (block * ramp[:, None]).astype(np.float32)


class Autotune:
    """Pulls the singer onto the nearest semitone.

    Pitch is detected by FFT autocorrelation over a rolling window, then the
    signal is shifted by a crossfading pair of taps in a delay line — the cheap
    harmoniser trick. ``amount`` blends between the sung pitch and the snapped
    one, so 0.2 nudges and 1.0 is the hard robotic effect.
    """

    WINDOW = 2048
    # 512 frames is ~11 ms. The grain has to be long enough to carry a pitch
    # period and short enough that the shifted copy still reads as the same
    # voice — a longer one is heard as a second singer a beat behind.
    GRAIN = 512

    # "snap" pulls to the nearest semitone — correction. "robot" pulls to one
    # fixed note no matter what you sing, which is the monotone that reads as a
    # machine rather than a singer.
    SNAP = "snap"
    ROBOT = "robot"
    ROBOT_MIDI = 57.0        # A3, 220 Hz

    def __init__(self, sample_rate: int = 44100, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self.amount = 0.0
        self.mode = self.SNAP
        self.robot_midi = self.ROBOT_MIDI
        self._seen: list = []          # detected pitches, for picking the lock note
        self._locked: float = 0.0      # 0 until the singer's range is known
        self._history = np.zeros(self.WINDOW, dtype=np.float32)
        self._line = DelayLine(self.GRAIN * 6, channels)
        self._read_offset = 0.0
        self._ratio = 1.0

    def set_sample_rate(self, sample_rate: int) -> None:
        if sample_rate != self.sample_rate:
            self.sample_rate = sample_rate
            self.reset()

    def reset(self) -> None:
        self._history[:] = 0.0
        self._line.reset()
        self._read_offset = 0.0
        self._ratio = 1.0
        self._seen.clear()
        self._locked = 0.0

    def _lock(self, midi: float) -> float:
        """The single note robot mode holds, learned from what is being sung.

        Uses the median of the first couple of seconds of detected pitch, so one
        stray octave error cannot set the note, and then never moves — a lock
        that drifts is a melody, not a monotone.
        """
        if self._locked:
            return self._locked
        self._seen.append(midi)
        if len(self._seen) >= 40:
            self._locked = float(round(float(np.median(self._seen))))
            logger.debug("robot voice locked to MIDI %.0f", self._locked)
            return self._locked
        # Until there is enough to judge, hold the first note heard.
        return float(round(self._seen[0]))

    def _detect(self) -> float:
        """Fundamental frequency of the rolling window, or 0 if unvoiced."""
        window = self._history
        if float(np.abs(window).max()) < 0.008:
            return 0.0
        centred = window - window.mean()
        spectrum = np.fft.rfft(centred, n=self.WINDOW * 2)
        autocorr = np.fft.irfft(spectrum * np.conj(spectrum))[:self.WINDOW]
        if autocorr[0] <= 1e-9:
            return 0.0
        lo = int(self.sample_rate / 1000.0)   # 1000 Hz ceiling
        hi = int(self.sample_rate / 70.0)     # 70 Hz floor
        hi = min(hi, self.WINDOW - 1)
        if hi <= lo:
            return 0.0
        segment = autocorr[lo:hi]
        peak = int(np.argmax(segment))
        if segment[peak] / autocorr[0] < 0.35:   # too noisy to be a pitch
            return 0.0
        return self.sample_rate / float(lo + peak)

    def process(self, block: np.ndarray) -> np.ndarray:
        count = len(block)
        if self.amount <= 0.001 or not count:
            return block

        mono = block.mean(axis=1).astype(np.float32)
        keep = min(count, self.WINDOW)
        self._history = np.concatenate([self._history[keep:], mono[-keep:]])

        freq = self._detect()
        if freq > 0.0:
            midi = 69.0 + 12.0 * np.log2(freq / 440.0)
            if self.mode == self.ROBOT:
                # One note, held. The note is learned from the singer's own
                # first few phrases rather than fixed in advance: a bass forced
                # up to A3 and a soprano dragged down to it both sound broken,
                # and re-picking the note per phrase would not be a monotone at
                # all — it would just be a different melody.
                correction = self._lock(midi) - midi
                limit = 9.0
            else:
                correction = round(midi) - midi
                limit = 2.0
            correction = float(np.clip(correction, -limit, limit))
            target = float(2.0 ** ((correction * self.amount) / 12.0))
            target = float(np.clip(target, 0.6, 1.7))
        else:
            target = 1.0
        # Glide towards the target. Correction should sound sung, so it eases;
        # a robot should not glide at all, so it snaps.
        glide = 0.9 if self.mode == self.ROBOT else 0.35
        self._ratio += (target - self._ratio) * glide

        self._line.write(block)
        if abs(self._ratio - 1.0) < 1e-4:
            return block

        # The delay window is frozen for the duration of a block, so the read
        # index must advance at r *per output sample* simply to track the
        # signal — advancing it at (r - 1) instead re-reads almost the same
        # sample 256 times and turns a voice into a buzz at the block rate.
        # Between blocks the window itself moves on by `count`, so the carried
        # offset advances by only (r - 1) * count.
        span = self.GRAIN + count + 4
        buffer = self._line.read_delayed(span, span).copy()
        index = self._read_offset + np.arange(count, dtype=np.float64) * self._ratio
        self._read_offset = (self._read_offset
                             + count * (self._ratio - 1.0)) % self.GRAIN

        # Two taps half a grain apart, each wrapped, each weighted by a raised
        # cosine that is exactly zero where *that* tap wraps — so neither
        # discontinuity is ever audible.
        first = index % self.GRAIN
        second = (index + self.GRAIN / 2.0) % self.GRAIN
        weight = 0.5 * (1.0 - np.cos(2.0 * np.pi * first / self.GRAIN))
        weight = weight.astype(np.float32)[:, None]
        wet = (_interp_taps(buffer, first) * weight
               + _interp_taps(buffer, second) * (1.0 - weight))
        return (block * (1.0 - self.amount) + wet * self.amount).astype(np.float32)


def _interp_taps(buffer: np.ndarray, positions: np.ndarray) -> np.ndarray:
    base = positions.astype(np.int64)
    frac = (positions - base).astype(np.float32)[:, None]
    return buffer[base] * (1.0 - frac) + buffer[base + 1] * frac


class Compressor:
    """Gentle downward compressor with block-ramped gain (no zipper noise)."""

    def __init__(self, sample_rate: int = 44100, threshold_db: float = -18.0,
                 ratio: float = 3.0, attack_ms: float = 10.0,
                 release_ms: float = 150.0, makeup_db: float = 4.0):
        self.sample_rate = sample_rate
        self.threshold_db = threshold_db
        self.ratio = ratio
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.makeup = float(10.0 ** (makeup_db / 20.0))
        self._gain = 1.0

    def reset(self) -> None:
        self._gain = 1.0

    def process(self, block: np.ndarray) -> np.ndarray:
        frames = len(block)
        if not frames:
            return block
        peak = float(np.abs(block).max())
        if peak < 1e-6:
            target = 1.0
        else:
            over = 20.0 * np.log10(peak) - self.threshold_db
            target = 1.0 if over <= 0 else float(
                10.0 ** ((-over * (1.0 - 1.0 / self.ratio)) / 20.0)
            )
        block_ms = frames / self.sample_rate * 1000.0
        span = self.attack_ms if target < self._gain else self.release_ms
        coefficient = min(1.0, block_ms / max(span, 1e-6))
        new_gain = self._gain + (target - self._gain) * coefficient
        ramp = np.linspace(self._gain, new_gain, frames, dtype=np.float32) * self.makeup
        self._gain = new_gain
        return (block * ramp[:, None]).astype(np.float32)


class HighPass:
    """Stateful high-pass — strips rumble and plosives off the microphone."""

    def __init__(self, sample_rate: int = 44100, cutoff_hz: float = 85.0,
                 channels: int = 2, order: int = 4):
        self.sample_rate = sample_rate
        self.cutoff_hz = cutoff_hz
        self.channels = channels
        self.order = order
        self._design()

    def _design(self) -> None:
        nyquist = self.sample_rate / 2.0
        wn = min(max(self.cutoff_hz / nyquist, 1e-4), 0.99)
        self._sos = signal.butter(self.order, wn, btype="highpass", output="sos")
        # sosfilt wants (sections, 2, channels) when filtering along axis 0.
        self._zi = np.zeros((len(self._sos), 2, self.channels), dtype=np.float64)

    def set_sample_rate(self, sample_rate: int) -> None:
        if sample_rate != self.sample_rate:
            self.sample_rate = sample_rate
            self._design()

    def reset(self) -> None:
        self._design()

    def process(self, block: np.ndarray) -> np.ndarray:
        if not len(block):
            return block
        out, self._zi = signal.sosfilt(self._sos, block, axis=0, zi=self._zi)
        return out.astype(np.float32)


class Limiter:
    """Soft limiter with instant attack and a slow, ramped release."""

    def __init__(self, sample_rate: int = 44100, ceiling: float = 0.97,
                 release_ms: float = 120.0):
        self.sample_rate = sample_rate
        self.ceiling = ceiling
        self.release_ms = release_ms
        self._gain = 1.0

    def reset(self) -> None:
        self._gain = 1.0

    def process(self, block: np.ndarray) -> np.ndarray:
        frames = len(block)
        if not frames:
            return block
        peak = float(np.abs(block).max())
        target = 1.0 if peak <= self.ceiling else self.ceiling / peak
        if target < self._gain:
            new_gain = target
        else:
            block_ms = frames / self.sample_rate * 1000.0
            coefficient = min(1.0, block_ms / max(self.release_ms, 1e-6))
            new_gain = self._gain + (target - self._gain) * coefficient
        ramp = np.linspace(self._gain, new_gain, frames, dtype=np.float32)
        self._gain = new_gain
        return (block * ramp[:, None]).astype(np.float32)


# --------------------------------------------------------------------------
# Presets and the full strip
# --------------------------------------------------------------------------

PRESETS = {
    # "Studio" is the one people leave switched on, so it carries no discrete
    # echo at all — just a short room. The obviously-an-effect presets are the
    # ones that repeat.
    "Dry":          {"reverb": 0,  "echo": 0,  "tune": 0,  "bass": 50, "treble": 50},
    "Studio":       {"reverb": 18, "echo": 0,  "tune": 0,  "bass": 50, "treble": 55},
    "Arena":        {"reverb": 60, "echo": 18, "tune": 0,  "bass": 55, "treble": 52},
    "Echo River":   {"reverb": 40, "echo": 62, "tune": 0,  "bass": 48, "treble": 58},
    "Cathedral":    {"reverb": 88, "echo": 0,  "tune": 0,  "bass": 45, "treble": 48},
    "Autotune Pop": {"reverb": 20, "echo": 0,  "tune": 85, "bass": 52, "treble": 62},
    "Robot":        {"reverb": 10, "echo": 0,  "tune": 100, "bass": 42, "treble": 70},
}

# Presets that lock the voice to a single note instead of correcting it to the
# nearest one. Kept out of PRESETS because it is a mode, not a knob position.
PRESET_MODES = {"Robot": "robot"}

FX_PARAMS = ("reverb", "echo", "tune", "bass", "treble")

# Short enough to sit on two lines in the 112 px label column.
FX_LABELS = {
    "reverb": ("Reverb", "Oda yankısı, dolgunluk"),
    "echo": ("Echo", "Gecikmeli tekrar"),
    "tune": ("Autotune", "Sesi notaya çeker"),
    "bass": ("Bass", "Pes tonların gücü"),
    "treble": ("Treble", "Netlik ve parlaklık"),
}


class MicStrip:
    """One microphone's full signal path, plus its mixer state."""

    def __init__(self, sample_rate: int = 44100, channels: int = 2):
        self.sample_rate = sample_rate
        self.volume = 0.7
        self.muted = False
        self.device = None
        self.preset = "Dry"
        self.params = dict(PRESETS["Dry"])
        self.mode = "snap"

        self.gate = NoiseGate(sample_rate)
        self.highpass = HighPass(sample_rate, channels=channels)
        self.compressor = Compressor(sample_rate)
        self.autotune = Autotune(sample_rate, channels)
        self.eq = ShelfEQ(sample_rate, channels)
        self.echo = Echo(sample_rate, channels)
        self.reverb = Reverb(sample_rate, channels)
        self.apply_params()

    def set_sample_rate(self, sample_rate: int) -> None:
        if sample_rate == self.sample_rate:
            return
        self.sample_rate = sample_rate
        for unit in (self.gate, self.highpass, self.compressor, self.autotune,
                     self.eq, self.echo, self.reverb):
            setter = getattr(unit, "set_sample_rate", None)
            if setter:
                setter(sample_rate)
            else:
                unit.sample_rate = sample_rate
        self.apply_params()

    def set_preset(self, name: str) -> None:
        if name in PRESETS:
            self.preset = name
            self.params = dict(PRESETS[name])
            self.mode = PRESET_MODES.get(name, "snap")
            self.apply_params()

    def set_param(self, key: str, value: float) -> None:
        """``value`` is the 0..100 slider position from the UI."""
        if key not in FX_PARAMS:
            return
        self.params[key] = float(np.clip(value, 0, 100))
        self.preset = self._match_preset()
        self.apply_params()

    def _match_preset(self) -> str:
        for name, values in PRESETS.items():
            if PRESET_MODES.get(name, "snap") != self.mode:
                continue
            if all(abs(self.params[k] - values[k]) < 0.5 for k in FX_PARAMS):
                return name
        return "Custom"

    def apply_params(self) -> None:
        self.autotune.mode = self.mode
        self.reverb.set_amount(self.params["reverb"] / 100.0)
        self.echo.set_amount(self.params["echo"] / 100.0)
        self.autotune.amount = self.params["tune"] / 100.0
        self.eq.set(self.params["bass"] / 100.0, self.params["treble"] / 100.0)

    def reset(self) -> None:
        for unit in (self.gate, self.highpass, self.compressor, self.autotune,
                     self.eq, self.echo, self.reverb):
            unit.reset()

    def process(self, block: np.ndarray) -> np.ndarray:
        """Run one mic block through the chain. Returns a new array."""
        out = self.gate.process(block)
        out = self.highpass.process(out)
        out = self.compressor.process(out)
        out = self.autotune.process(out)
        out = self.eq.process(out)
        out = self.echo.process(out)
        out = self.reverb.process(out)
        return out
