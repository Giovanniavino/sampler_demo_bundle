"""
Zero-crossing utilities for click-free slice boundaries.

Snapping slice boundaries to zero crossings is the cheapest, most effective
way to eliminate clicks at sample triggers and at loop wrap-around points.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

Direction = Literal["nearest", "forward", "backward"]


def find_zero_crossing(
    audio: np.ndarray,
    position: int,
    window_samples: int = 441,
    direction: Direction = "nearest",
    prefer_rising: bool = False,
) -> int:
    """Find a zero crossing near `position`. Returns original position if none found."""
    n = audio.shape[0]
    if n == 0:
        return 0
    position = max(0, min(position, n - 1))

    if audio.ndim == 2:
        mono = audio.mean(axis=1)
    else:
        mono = audio

    if direction == "nearest":
        lo = max(0, position - window_samples)
        hi = min(n, position + window_samples + 1)
    elif direction == "forward":
        lo = position
        hi = min(n, position + window_samples + 1)
    else:
        lo = max(0, position - window_samples)
        hi = position + 1

    if hi - lo < 2:
        return position

    seg = mono[lo:hi]
    signs = np.sign(seg)
    sign_changes = np.where(np.diff(signs) != 0)[0]

    if prefer_rising:
        sign_changes = np.array([
            i for i in sign_changes if signs[i] <= 0 and signs[i + 1] > 0
        ], dtype=int)

    if len(sign_changes) == 0:
        return position

    candidates = sign_changes + lo
    nearest = candidates[np.argmin(np.abs(candidates - position))]
    return int(nearest)