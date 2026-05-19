"""
Advanced BPM detection — fractional precision + time signature detection.

Improvements over the basic LibrosaAnalyzer:
  1. **Fractional BPM** — uses librosa.beat.beat_track with higher precision
     via the `bpm` parameter override. Returns float, not rounded int.
  2. **Time signature detection** — uses beat-strength patterns to infer
     4/4, 3/4, 6/8 (binary vs ternary subdivisions).
  3. **Confidence score** — based on beat consistency (std/mean of inter-beat
     intervals). Low std = high confidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BpmDetectionResult:
    """Result of BPM detection. Includes fractional precision and confidence."""
    bpm: float                                # Fractional BPM (e.g. 120.47)
    confidence: float                         # 0..1
    time_signature: tuple[int, int]           # (numerator, denominator)
    beats: list[int]                          # Beat positions in samples
    downbeats: list[int]                      # Downbeat positions in samples
    inter_beat_std_ms: float                  # ms; low = stable tempo


def detect_bpm(audio_path: Path,
                user_override_bpm: Optional[float] = None) -> BpmDetectionResult:
    """
    Detect BPM with fractional precision + time signature.

    user_override_bpm: if provided, uses this value (with confidence=1.0)
                       and only re-runs beat tracking to align grid.
    """
    try:
        import librosa
    except ImportError as e:
        log.warning("librosa not installed: %s", e)
        return _empty_result()

    try:
        y, sr = librosa.load(str(audio_path), sr=None, mono=True)
        if len(y) < sr * 5:  # need at least 5s for reliable detection
            log.warning("Audio too short (<5s) for reliable BPM detection")
            return _empty_result()

        if user_override_bpm:
            bpm = float(user_override_bpm)
            tempo_arr, beat_frames = librosa.beat.beat_track(
                y=y, sr=sr, hop_length=512, start_bpm=bpm, units="frames"
            )
            confidence = 1.0  # user-asserted
        else:
            # Default librosa beat tracker — returns fractional BPM
            tempo_arr, beat_frames = librosa.beat.beat_track(
                y=y, sr=sr, hop_length=512, units="frames"
            )
            bpm = float(np.atleast_1d(tempo_arr)[0])
            confidence = _compute_beat_confidence(y, sr, beat_frames)

        beat_samples = librosa.frames_to_samples(beat_frames, hop_length=512)
        beat_positions = [int(b) for b in beat_samples]

        # Inter-beat interval stats
        ibi_ms = _inter_beat_intervals_ms(beat_positions, sr)

        # Time signature inference
        time_sig = _detect_time_signature(y, sr, beat_frames, beat_samples)

        # Downbeats based on time signature
        downbeats = _detect_downbeats(beat_positions, time_sig[0])

        return BpmDetectionResult(
            bpm=round(bpm, 2),
            confidence=round(confidence, 2),
            time_signature=time_sig,
            beats=beat_positions,
            downbeats=downbeats,
            inter_beat_std_ms=round(ibi_ms, 1),
        )
    except Exception as e:
        log.exception("BPM detection failed: %s", e)
        return _empty_result()


def _empty_result() -> BpmDetectionResult:
    return BpmDetectionResult(
        bpm=0.0, confidence=0.0,
        time_signature=(4, 4),
        beats=[], downbeats=[],
        inter_beat_std_ms=0.0,
    )


def _compute_beat_confidence(y: np.ndarray, sr: int,
                              beat_frames: np.ndarray) -> float:
    """
    Confidence based on:
      - low std of inter-beat intervals (stable tempo)
      - high mean onset strength at beat positions
    """
    if len(beat_frames) < 4:
        return 0.3

    import librosa
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    if len(onset_env) == 0:
        return 0.5

    # Beat-aligned onset strengths
    valid_frames = [f for f in beat_frames if f < len(onset_env)]
    if not valid_frames:
        return 0.5
    beat_strengths = onset_env[valid_frames]
    mean_strength = float(beat_strengths.mean())
    onset_max = float(onset_env.max()) or 1.0
    strength_score = min(1.0, mean_strength / onset_max)

    # Inter-beat interval stability
    diffs = np.diff(beat_frames).astype(np.float32)
    if len(diffs) == 0:
        return 0.5
    rel_std = float(diffs.std() / (diffs.mean() + 1e-6))
    stability_score = max(0.0, 1.0 - rel_std * 2)

    return 0.6 * stability_score + 0.4 * strength_score


def _inter_beat_intervals_ms(beats: list[int], sr: int) -> float:
    """Standard deviation of inter-beat intervals in milliseconds."""
    if len(beats) < 2:
        return 0.0
    diffs = np.diff(beats)
    return float((diffs.std() / sr) * 1000)


def _detect_time_signature(y: np.ndarray, sr: int,
                            beat_frames: np.ndarray,
                            beat_samples: np.ndarray) -> tuple[int, int]:
    """
    Infer time signature by analyzing the metric structure of beat strengths.

    Strategy:
      - Group beats into windows of 6 and 4
      - Check which grouping produces stronger metric accents (downbeats)
      - 4/4: every 4th beat is stronger
      - 3/4: every 3rd beat is stronger
      - 6/8: every 6th beat is stronger (or pairs of 3)
    """
    import librosa

    if len(beat_frames) < 12:
        return (4, 4)

    try:
        # Energy at each beat position
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
        valid = [f for f in beat_frames if 0 <= f < len(onset_env)]
        if len(valid) < 12:
            return (4, 4)

        beat_energies = np.array([onset_env[f] for f in valid])

        # Try patterns of 3, 4, 6
        scores = {}
        for grouping in [3, 4, 6]:
            scores[grouping] = _evaluate_grouping(beat_energies, grouping)

        # Pick best grouping
        best_group = max(scores, key=scores.get)

        # Decide denominator: if 3 wins, default to 3/4; if 6 wins, 6/8; else 4/4
        if best_group == 3:
            # Could be 3/4 or 6/8 — distinguish by relative strength
            if scores[6] > scores[3] * 0.85:
                return (6, 8)
            return (3, 4)
        elif best_group == 6:
            return (6, 8)
        else:
            return (4, 4)
    except Exception as e:
        log.debug("Time signature detection failed: %s", e)
        return (4, 4)


def _evaluate_grouping(energies: np.ndarray, group_size: int) -> float:
    """
    Score how well energies fit a metric grouping.
    High score = strong every Nth beat = consistent meter.
    """
    if len(energies) < group_size * 2:
        return 0.0

    # Average energy at each phase within the group
    phase_means = np.zeros(group_size)
    for phase in range(group_size):
        phase_energies = energies[phase::group_size]
        phase_means[phase] = phase_energies.mean()

    # Score = (peak phase / mean phases) — measures how prominent the downbeat is
    peak = phase_means.max()
    mean = phase_means.mean()
    if mean < 1e-6:
        return 0.0
    return float(peak / mean)


def _detect_downbeats(beats: list[int], beats_per_bar: int) -> list[int]:
    """Mark every Nth beat as a downbeat."""
    if not beats:
        return []
    return [b for i, b in enumerate(beats) if i % beats_per_bar == 0]


def time_signature_to_string(time_sig: tuple[int, int]) -> str:
    """Format time signature as '4/4' string."""
    return f"{time_sig[0]}/{time_sig[1]}"
