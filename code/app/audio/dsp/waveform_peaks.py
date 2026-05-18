"""
Waveform peaks generator.

To draw a waveform efficiently in QML we precompute one (min, max) pair per
display pixel column. This is the standard 'peaks' representation used by
every DAW. For an 800px-wide waveform we generate ~400 peak pairs.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)


def compute_peaks(audio_path: Path, num_bins: int = 400) -> list[float]:
    """
    Read audio and return a flat list of [min0, max0, min1, max1, ...] values
    in -1..+1 range, suitable for direct QML Canvas drawing.
    """
    try:
        data, _ = sf.read(str(audio_path), dtype='float32', always_2d=True)
        mono = data.mean(axis=1) if data.ndim == 2 else data
        return compute_peaks_from_array(mono, num_bins)
    except Exception as e:
        log.warning("Peaks computation failed for %s: %s", audio_path, e)
        return [0.0] * (num_bins * 2)


def compute_peaks_from_array(audio: np.ndarray, num_bins: int = 400) -> list[float]:
    """
    Same as compute_peaks but from an in-memory array.

    `audio` should be mono (1-D). If 2-D, channels are averaged.
    """
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    n = len(audio)
    if n == 0:
        return [0.0] * (num_bins * 2)

    bin_size = max(1, n // num_bins)
    peaks: list[float] = []
    for i in range(num_bins):
        start = i * bin_size
        end = min(start + bin_size, n)
        if start >= end:
            peaks.extend([0.0, 0.0])
            continue
        seg = audio[start:end]
        peaks.append(float(seg.min()))
        peaks.append(float(seg.max()))
    return peaks
