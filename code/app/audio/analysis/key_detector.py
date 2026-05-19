"""
Musical key detection via Krumhansl-Schmuckler key profiles.

Approach:
  1. Extract chroma vector (12-dim, one slot per pitch class) from the audio
  2. Average over the whole track
  3. Correlate against all 24 candidate keys (12 major + 12 minor)
  4. Return the key with highest correlation
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Krumhansl-Kessler experimental key profiles
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                    2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                    2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def detect_key(audio_path: Path, max_seconds: float = 60.0) -> tuple[str, float]:
    """
    Detect the musical key. Returns ("C minor", 0.83) or ("?", 0.0) on failure.

    max_seconds caps how much audio to analyze (key estimation on the first
    minute is plenty and 5x faster than the whole song).
    """
    try:
        import librosa
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True,
                              duration=max_seconds)
        if len(y) < sr:
            return "?", 0.0

        # Chroma via CQT — more stable than STFT for tonal estimation
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
        if np.sum(chroma) < 1e-6:
            return "?", 0.0

        best_score = -1.0
        best_label = "?"
        for i in range(12):
            for mode_name, profile in (("major", _MAJOR), ("minor", _MINOR)):
                rotated = np.roll(profile, i)
                # Pearson correlation
                num = np.sum((chroma - chroma.mean()) * (rotated - rotated.mean()))
                den = (np.sqrt(np.sum((chroma - chroma.mean()) ** 2)) *
                       np.sqrt(np.sum((rotated - rotated.mean()) ** 2)) + 1e-9)
                score = float(num / den)
                if score > best_score:
                    best_score = score
                    best_label = f"{NOTES[i]} {mode_name}"
        log.info("Key detected: %s (confidence %.2f)", best_label, best_score)
        return best_label, best_score
    except Exception as e:
        log.warning("Key detection failed: %s", e)
        return "?", 0.0
