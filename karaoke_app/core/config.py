"""
Persistent application configuration.

A tiny JSON-backed store. Writes are debounced by the caller (the UI saves on
dialog close, not on every slider tick) so this stays a plain synchronous file.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict

from .paths import CONFIG_FILE

logger = logging.getLogger(__name__)


# Bumped when a stored value would carry a since-fixed problem forward. Version 2
# retires the microphone effect settings written before the echo and autotune
# rework, which froze a preset that produced an audible repeat train.
FX_VERSION = 2

DEFAULTS: Dict[str, Any] = {
    "fx_version": FX_VERSION,
    # Devices — stored by name so they survive re-plugging, resolved to an
    # index at stream-open time.
    "output_device": None,
    "mic_devices": [None, None, None, None],
    "mic_count": 2,
    # Mixer
    "vocals_volume": 0.18,
    "instrumental_volume": 0.85,
    "master_volume": 0.80,
    "mic_volumes": [0.76, 0.64, 0.70, 0.70],
    "mic_muted": [False, True, True, True],
    # Every mic starts clean. Effects are something you switch on, not something
    # that surprises you the first time you speak into a microphone.
    "mic_presets": ["Dry", "Dry", "Dry", "Dry"],
    "mic_fx": None,  # filled in by the mixer on first run
    # Behaviour
    "ducking": True,
    "gate": True,
    # 0.5 maps to unity on the mic bus (the slider spans 0..2x). Anything above
    # unity by default invites acoustic feedback on laptop speakers.
    "monitor": 0.50,
    "auto_lyrics": True,
    # 256 frames is ~5.8 ms at 44.1 kHz. Measured worst case for the mixer plus
    # four fully-loaded mic chains is well under half a millisecond per block,
    # so the smaller buffer buys real monitoring latency at no risk.
    "block_size": 256,
    "prefer_gpu": True,
}


class Config:
    """Dict-like config with defaults and JSON persistence."""

    def __init__(self, path: Path = CONFIG_FILE):
        self.path = Path(path)
        self._data: Dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        stored: Dict[str, Any] = {}
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    stored = loaded
                    self._data.update(stored)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read config (%s); using defaults", exc)
            return
        self._migrate(stored)

    def _migrate(self, stored: Dict[str, Any]) -> None:
        """Drop stored values that a newer release has reason to override.

        The version has to be read from the file, not from the merged data —
        the merged copy already carries the current default and would always
        look up to date.
        """
        if stored and int(stored.get("fx_version", 1)) < FX_VERSION:
            logger.info("Resetting microphone effects to the reworked defaults")
            self._data["mic_fx"] = DEFAULTS["mic_fx"]
            self._data["mic_presets"] = list(DEFAULTS["mic_presets"])
            self._data["monitor"] = DEFAULTS["monitor"]
            self._data["fx_version"] = FX_VERSION
            self.save()

    def save(self) -> None:
        # Only settings that differ from the shipped defaults are written. A
        # value frozen into the file the first time the app ran would otherwise
        # override every later improvement to that default — which is how a
        # tuned buffer size ends up stuck at whatever the first release used.
        stored = {key: value for key, value in self._data.items()
                  if key not in DEFAULTS or value != DEFAULTS[key]}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(stored, handle, indent=2, ensure_ascii=False)
            tmp.replace(self.path)
        except OSError as exc:
            logger.warning("Could not save config: %s", exc)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, **kwargs: Any) -> None:
        self._data.update(kwargs)

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)
