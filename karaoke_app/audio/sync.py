"""
Lyric timing offset detection.

LRCLIB timestamps describe the *studio recording*. A YouTube upload often is not
that: official videos open with a spoken scene, uploads carry channel intros,
live versions start with applause. When that happens every line arrives early by
however long the intro is, and the words race ahead of the singer.

The separated vocal stem makes this measurable. If the stem is silent for the
first twenty seconds, then nobody is singing during those twenty seconds, and
any lyric line scheduled inside that silence is provably wrong — so the whole
sheet gets pushed back by the length of the lead-in.

Deliberately one-directional. Vocal energy detected *before* the first lyric is
almost always bleed from the instrumental separation or a breath, not evidence
that the lyrics are late, and shifting on that would break songs that are
already correct. Across a sixteen-song library this rule flagged exactly the two
that were wrong and left the other fourteen alone.

Anything it cannot prove is left at zero for the singer to nudge by hand.
"""
import logging
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

FRAME_RATE = 50.0        # analysis frames per second
ACTIVE_DB = -38.0        # relative to the stem's own loud passages
SUSTAIN_SECONDS = 0.4    # ignore clicks and breaths
MIN_SHIFT = 2.5          # below this, assume it is already aligned
MAX_SHIFT = 90.0         # beyond this, assume the detection is wrong
MIN_LINES_IN_SILENCE = 2 # how many impossible lines make it conclusive


def first_vocal_onset(vocals_path: Path) -> Optional[float]:
    """When singing convincingly starts in an isolated vocal stem.

    Returns None if the stem never gets going — an instrumental, or a
    separation that produced nothing.
    """
    try:
        info = sf.info(str(vocals_path))
        hop = max(1, int(info.samplerate / FRAME_RATE))
        data, _ = sf.read(str(vocals_path), dtype="float32", always_2d=True)
    except Exception as exc:
        logger.debug("Could not read %s for onset detection: %s", vocals_path, exc)
        return None

    mono = np.abs(data.mean(axis=1))
    frames = len(mono) // hop
    if frames < 2:
        return None
    envelope = mono[:frames * hop].reshape(frames, hop).max(axis=1)

    # Threshold relative to the stem's own loud passages, so a quietly mixed
    # vocal is measured on its own terms.
    reference = float(np.percentile(envelope, 98)) or 1.0
    decibels = 20.0 * np.log10(np.maximum(envelope, 1e-7) / reference)

    needed = int(SUSTAIN_SECONDS * FRAME_RATE)
    run = 0
    for index, loud in enumerate(decibels > ACTIVE_DB):
        run = run + 1 if loud else 0
        if run >= needed:
            return (index - needed + 1) / FRAME_RATE
    return None


def estimate_offset(vocals_path: Path,
                    lines: Sequence[Tuple[float, str]]) -> Tuple[float, str]:
    """Seconds to add to every lyric timestamp, plus why.

    An offset of zero means "no evidence of a problem", which is the answer
    whenever the measurement is not conclusive.
    """
    timed = [t for t, _ in lines if t >= 0]
    if len(timed) < 3:
        return 0.0, ""

    onset = first_vocal_onset(Path(vocals_path))
    if onset is None:
        return 0.0, ""

    shift = onset - timed[0]
    if shift < MIN_SHIFT:
        return 0.0, ""
    if shift > MAX_SHIFT:
        logger.info("Ignoring an implausible %.1fs lyric offset", shift)
        return 0.0, ""

    # The proof: lines scheduled while the stem is provably silent.
    impossible = sum(1 for t in timed if t < onset)
    if impossible < MIN_LINES_IN_SILENCE:
        return 0.0, ""

    reason = (f"vocals start at {onset:.1f}s but {impossible} lines were "
              f"scheduled before that")
    logger.info("Lyric offset %+.2fs — %s", shift, reason)
    return round(shift, 2), reason


def apply_offset(lines: Sequence[Tuple[float, str]],
                 offset: float) -> List[Tuple[float, str]]:
    """Shift timed lines, leaving untimed ones (-1.0) alone."""
    if not offset:
        return list(lines)
    return [((t + offset) if t >= 0 else t, s) for t, s in lines]
