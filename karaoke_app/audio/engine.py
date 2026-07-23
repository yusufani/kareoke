"""
The real-time karaoke engine.

One output stream pulls the whole mix; each microphone runs on its own input
stream feeding a ring buffer. Keeping the mics on separate streams instead of a
single duplex device is what makes "four singers on four different mics" work
at all — they are physically different clocks, and a jitter buffer per mic is
the only honest way to reconcile them.

Nothing in the callback path allocates unpredictably, logs, or touches Qt. The
GUI polls :attr:`position` on a timer instead of being signalled from the audio
thread, so a busy interface can never stall playback — which is the whole point
of being able to queue up the next song while somebody is still singing.
"""
import logging
import threading
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy import signal

from .fx import Limiter, MicStrip
from .timescale import PitchTimeShifter, StemReader

logger = logging.getLogger(__name__)

MAX_MICS = 4
DEFAULT_SAMPLE_RATE = 44100


class _Ring:
    """Single-producer / single-consumer mono ring buffer with drift control."""

    def __init__(self, capacity: int):
        self.capacity = int(capacity)
        self.buffer = np.zeros(self.capacity, dtype=np.float32)
        self.write = 0
        self.read = 0
        self.lock = threading.Lock()

    @property
    def available(self) -> int:
        return (self.write - self.read) % self.capacity

    def push(self, block: np.ndarray) -> None:
        count = len(block)
        if count >= self.capacity:
            block = block[-(self.capacity - 1):]
            count = len(block)
        with self.lock:
            end = self.write + count
            if end <= self.capacity:
                self.buffer[self.write:end] = block
            else:
                head = self.capacity - self.write
                self.buffer[self.write:] = block[:head]
                self.buffer[:end - self.capacity] = block[head:]
            self.write = end % self.capacity
            # Overrun: the consumer fell behind, so drop the stale audio rather
            # than let latency grow without bound.
            if (self.write - self.read) % self.capacity < count:
                self.read = (self.write + 1) % self.capacity

    def pop(self, count: int, out: np.ndarray) -> None:
        with self.lock:
            have = (self.write - self.read) % self.capacity
            # Trim runaway latency caused by a mic clock running fast.
            if have > count * 6:
                self.read = (self.write - count * 3) % self.capacity
                have = count * 3
            take = min(count, have)
            if take:
                end = self.read + take
                if end <= self.capacity:
                    out[:take] = self.buffer[self.read:end]
                else:
                    head = self.capacity - self.read
                    out[:head] = self.buffer[self.read:]
                    out[head:take] = self.buffer[:end - self.capacity]
                self.read = end % self.capacity
            if take < count:
                out[take:] = 0.0


class MicInput:
    """A physical microphone feeding a ring buffer from its own stream."""

    def __init__(self, index: int, sample_rate: int, block_size: int):
        self.index = index
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.device: Optional[int] = None
        self.stream: Optional[sd.InputStream] = None
        self.ring = _Ring(sample_rate)  # one second of slack
        self.peak = 0.0
        self.error = ""

    def open(self, device: Optional[int]) -> bool:
        self.close()
        self.device = device
        if device is None:
            return False
        try:
            self.stream = sd.InputStream(
                device=device,
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.block_size,
                latency="low",
                callback=self._callback,
            )
            self.stream.start()
            self.error = ""
            logger.info("Mic %d open on device %s", self.index + 1, device)
            return True
        except Exception as exc:
            self.error = str(exc)
            self.stream = None
            logger.warning("Could not open mic %d on device %s: %s",
                           self.index + 1, device, exc)
            return False

    def close(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    @property
    def active(self) -> bool:
        return self.stream is not None

    def _callback(self, indata, frames, time_info, status) -> None:
        block = indata[:, 0] if indata.ndim > 1 else indata
        self.peak = float(np.abs(block).max()) if frames else 0.0
        self.ring.push(block)

    def read(self, count: int, out: np.ndarray) -> None:
        if self.stream is None:
            out[:] = 0.0
        else:
            self.ring.pop(count, out)


class _Smoothed:
    """A gain that ramps across a block instead of stepping — no zipper noise."""

    __slots__ = ("value", "target")

    def __init__(self, value: float = 0.0):
        self.value = float(value)
        self.target = float(value)

    def ramp(self, frames: int, out: np.ndarray) -> float:
        """Fill ``out[:frames]`` with the ramp and return the new value."""
        if self.value == self.target:
            out[:frames] = self.value
        else:
            out[:frames] = np.linspace(self.value, self.target, frames,
                                       dtype=np.float32)
            self.value = self.target
        return self.value


class KaraokeEngine:
    """Playback, mixing, microphones, recording."""

    def __init__(self, block_size: int = 512):
        self.block_size = int(block_size)
        self.sample_rate = DEFAULT_SAMPLE_RATE
        self.channels = 2

        self.loaded = False
        self.playing = False
        self.duration = 0.0
        self._total_frames = 0
        self._position = 0.0          # audible position, seconds
        self._finished = False

        self._reader: Optional[StemReader] = None
        self._shifter = PitchTimeShifter(self.sample_rate, self.channels)
        self._limiter = Limiter(self.sample_rate)
        self._lock = threading.RLock()

        # Mixer state
        self.vocals = _Smoothed(0.18)
        self.instrumental = _Smoothed(0.85)
        self.master = _Smoothed(0.80)
        self.vocals_muted = False
        self.instrumental_muted = False
        self.mics: List[MicStrip] = [MicStrip(self.sample_rate) for _ in range(MAX_MICS)]
        self._mic_gains = [_Smoothed(0.0) for _ in range(MAX_MICS)]
        self.inputs: List[MicInput] = [
            MicInput(i, self.sample_rate, self.block_size) for i in range(MAX_MICS)
        ]
        self.mic_count = 2

        # Transport extras
        self.speed = 1.0
        self.key = 0
        self.loop_in: Optional[float] = None
        self.loop_out: Optional[float] = None
        self.ducking = True
        self.gate_enabled = True
        # Global trim on the microphone bus. 1.0 is unity; the settings slider
        # maps 0..100 onto 0..2 so there is headroom for a quiet capsule.
        self.monitor = 1.2

        # Recording
        self._recording = False
        self._rec_chunks: List[np.ndarray] = []
        self._rec_lock = threading.Lock()
        self._rec_start_pos = 0.0
        self._rec_started_at = 0.0

        self._output: Optional[sd.OutputStream] = None
        self._output_device: Optional[int] = None
        self._output_latency = 0.0
        self.xruns = 0

        # Scratch buffers, allocated once and reused by the callback.
        self._gain_ramp = np.zeros(4096, dtype=np.float32)
        self._mic_mono = np.zeros(4096, dtype=np.float32)

    # -- device plumbing --------------------------------------------------
    def start_audio(self, output_device: Optional[int] = None) -> bool:
        """Open (or reopen) the output stream. Safe to call repeatedly."""
        with self._lock:
            self._close_output()
            self._output_device = output_device
            try:
                info = sd.query_devices(output_device, "output") if output_device is not None \
                    else sd.query_devices(kind="output")
                rate = int(info.get("default_samplerate") or DEFAULT_SAMPLE_RATE)
            except Exception:
                rate = DEFAULT_SAMPLE_RATE
            rate = rate if rate in (44100, 48000, 88200, 96000) else DEFAULT_SAMPLE_RATE

            try:
                self._output = sd.OutputStream(
                    device=output_device,
                    samplerate=rate,
                    channels=self.channels,
                    dtype="float32",
                    blocksize=self.block_size,
                    latency="low",
                    callback=self._callback,
                )
                self._output.start()
            except Exception as exc:
                logger.error("Could not open output device %s: %s", output_device, exc)
                self._output = None
                return False

            latency = self._output.latency
            self._output_latency = float(latency[1] if isinstance(latency, tuple) else latency)
            if rate != self.sample_rate:
                self._retune(rate)
            logger.info("Output open: %d Hz, block %d, latency %.1f ms",
                        rate, self.block_size, self._output_latency * 1000)
            return True

    def _retune(self, rate: int) -> None:
        """Move every rate-dependent component onto a new sample rate."""
        self.sample_rate = rate
        self._limiter = Limiter(rate)
        self._shifter = PitchTimeShifter(rate, self.channels)
        self._shifter.configure(self.speed, self.key)
        for strip in self.mics:
            strip.set_sample_rate(rate)
        for mic in self.inputs:
            was = mic.device if mic.active else None
            mic.close()
            mic.sample_rate = rate
            mic.ring = _Ring(rate)
            if was is not None:
                mic.open(was)

    def open_mics(self, devices: List[Optional[int]]) -> None:
        with self._lock:
            for index, mic in enumerate(self.inputs):
                wanted = devices[index] if index < len(devices) else None
                if index >= self.mic_count:
                    wanted = None
                if wanted == mic.device and mic.active:
                    continue
                mic.open(wanted)

    def set_mic_count(self, count: int) -> None:
        self.mic_count = max(1, min(MAX_MICS, int(count)))

    def _close_output(self) -> None:
        if self._output is not None:
            try:
                self._output.stop()
                self._output.close()
            except Exception:
                pass
            self._output = None

    # -- loading ----------------------------------------------------------
    def load(self, vocals_path: Path, instrumental_path: Path) -> float:
        """Load a song's stems. Blocking — call from a worker thread."""
        vocals = _read_stereo(Path(vocals_path))
        instrumental = _read_stereo(Path(instrumental_path))

        rate = vocals[1]
        vocal_data, inst_data = vocals[0], instrumental[0]
        if instrumental[1] != rate:
            inst_data = _resample(inst_data, instrumental[1], rate)
        if rate != self.sample_rate:
            vocal_data = _resample(vocal_data, rate, self.sample_rate)
            inst_data = _resample(inst_data, rate, self.sample_rate)

        length = max(len(vocal_data), len(inst_data))
        vocal_data = _pad_to(vocal_data, length)
        inst_data = _pad_to(inst_data, length)

        reader = StemReader([vocal_data, inst_data], self.channels,
                            scratch=max(8192, self.block_size * 8))
        with self._lock:
            was_playing = self.playing
            self.playing = False
            self._reader = reader
            self._total_frames = length
            self.duration = length / self.sample_rate
            self._position = 0.0
            self._finished = False
            self.loop_in = self.loop_out = None
            self._shifter.seek(0.0)
            self._limiter.reset()
            self.loaded = True
            if was_playing:
                self.playing = True
        logger.info("Loaded stems: %.1f s @ %d Hz", self.duration, self.sample_rate)
        return self.duration

    def unload(self) -> None:
        with self._lock:
            self.playing = False
            self.loaded = False
            self._reader = None
            self._total_frames = 0
            self.duration = 0.0
            self._position = 0.0

    # -- transport --------------------------------------------------------
    def play(self) -> None:
        if not self.loaded:
            return
        if self._finished:
            self.seek(0.0)
        self._finished = False
        self.playing = True

    def pause(self) -> None:
        self.playing = False

    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def stop(self) -> None:
        self.playing = False
        self.seek(0.0)

    def seek(self, seconds: float) -> None:
        if not self.loaded:
            return
        seconds = float(np.clip(seconds, 0.0, max(self.duration - 0.05, 0.0)))
        with self._lock:
            self._shifter.seek(seconds * self.sample_rate)
            self._position = seconds
            self._finished = False
            self._limiter.reset()

    @property
    def position(self) -> float:
        """Where the listener actually is, compensating for output latency."""
        if self.playing:
            return max(0.0, self._position - self._output_latency)
        return self._position

    @property
    def finished(self) -> bool:
        """True once the song ran to its end; cleared by seek/play."""
        return self._finished

    def set_speed(self, speed: float) -> None:
        self.speed = float(np.clip(speed, 0.5, 1.5))
        self._shifter.configure(self.speed, self.key)

    def set_key(self, semitones: int) -> None:
        self.key = int(np.clip(semitones, -6, 6))
        self._shifter.configure(self.speed, self.key)

    # -- mixer ------------------------------------------------------------
    def set_vocals(self, volume: float) -> None:
        self.vocals.target = float(np.clip(volume, 0.0, 1.0))

    def set_instrumental(self, volume: float) -> None:
        self.instrumental.target = float(np.clip(volume, 0.0, 1.0))

    def set_master(self, volume: float) -> None:
        self.master.target = float(np.clip(volume, 0.0, 1.0))

    def mic_peak(self, index: int) -> float:
        return self.inputs[index].peak if 0 <= index < MAX_MICS else 0.0

    # -- recording --------------------------------------------------------
    @property
    def recording(self) -> bool:
        return self._recording

    def start_recording(self) -> None:
        with self._rec_lock:
            self._rec_chunks = []
        self._rec_start_pos = self.position
        self._rec_started_at = time.time()
        self._recording = True

    def stop_recording(self, destination: Path) -> Optional[dict]:
        """Write the take to disk; returns its metadata, or None if empty."""
        self._recording = False
        with self._rec_lock:
            chunks, self._rec_chunks = self._rec_chunks, []
        if not chunks:
            return None
        audio = np.concatenate(chunks, axis=0)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            sf.write(str(destination), audio, self.sample_rate, subtype="PCM_16")
        except Exception as exc:
            logger.error("Could not save take: %s", exc)
            return None
        return {
            "path": str(destination),
            "start": self._rec_start_pos,
            "end": self.position,
            "length": len(audio) / self.sample_rate,
        }

    @property
    def recording_duration(self) -> float:
        return time.time() - self._rec_started_at if self._recording else 0.0

    # -- the audio callback ----------------------------------------------
    def _callback(self, outdata, frames, time_info, status) -> None:
        if status:
            self.xruns += 1

        if frames > len(self._gain_ramp):
            self._gain_ramp = np.zeros(frames, dtype=np.float32)
            self._mic_mono = np.zeros(frames, dtype=np.float32)
        ramp = self._gain_ramp[:frames]

        reader = self._reader
        if self.playing and reader is not None:
            vocal_gain = 0.0 if self.vocals_muted else self.vocals.target
            inst_gain = 0.0 if self.instrumental_muted else self.instrumental.target
            if self._recording and self.ducking:
                inst_gain *= 0.5          # -6 dB, so the mic sits on top
                vocal_gain *= 0.5
            reader.set_gains((vocal_gain, inst_gain))
            mix = self._shifter.read(reader, frames)
            self._position = self._shifter.position / self.sample_rate

            loop_in, loop_out = self.loop_in, self.loop_out
            if self._position >= self.duration - 1e-3:
                # Flag it and let the GUI's poll advance the queue; calling back
                # into Qt from the audio thread would be a deadlock waiting to
                # happen.
                self.playing = False
                self._finished = True
            elif loop_out is not None and loop_in is not None and self._position >= loop_out:
                # Inlined seek: the lock must never be taken on this thread.
                self._shifter.seek(loop_in * self.sample_rate)
                self._position = loop_in
                self._limiter.reset()
        else:
            mix = np.zeros((frames, self.channels), dtype=np.float32)

        for index in range(self.mic_count):
            source = self.inputs[index]
            if not source.active:
                continue
            strip = self.mics[index]
            gain = self._mic_gains[index]
            gain.target = 0.0 if strip.muted else strip.volume * self.monitor
            if gain.value == 0.0 and gain.target == 0.0:
                continue
            mono = self._mic_mono[:frames]
            source.read(frames, mono)
            strip.gate.enabled = self.gate_enabled
            stereo = np.repeat(mono[:, None], self.channels, axis=1)
            processed = strip.process(stereo)
            gain.ramp(frames, ramp)
            mix += processed * ramp[:, None]

        self.master.ramp(frames, ramp)
        mix *= ramp[:, None]
        mix = self._limiter.process(mix)

        outdata[:] = mix
        if self._recording:
            with self._rec_lock:
                self._rec_chunks.append(mix.copy())

    # -- shutdown ---------------------------------------------------------
    def cleanup(self) -> None:
        self.playing = False
        self._recording = False
        for mic in self.inputs:
            mic.close()
        self._close_output()
        logger.info("Engine stopped (%d xruns this session)", self.xruns)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _read_stereo(path: Path):
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    return np.ascontiguousarray(data, dtype=np.float32), int(rate)


def _resample(data: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return data
    from math import gcd
    divisor = gcd(int(source_rate), int(target_rate))
    up, down = target_rate // divisor, source_rate // divisor
    resampled = signal.resample_poly(data, up, down, axis=0)
    return np.ascontiguousarray(resampled, dtype=np.float32)


def _pad_to(data: np.ndarray, length: int) -> np.ndarray:
    if len(data) >= length:
        return data[:length]
    padding = np.zeros((length - len(data), data.shape[1]), dtype=np.float32)
    return np.vstack([data, padding])
