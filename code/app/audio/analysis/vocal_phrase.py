"""
Vocal phrase detection via silence-gating (a.k.a. simple VAD).

We don't want fixed-length vocal slices because they cut mid-word or mid-phrase.
Instead we find "regions of singing" — contiguous spans where the vocal stem
has energy above a noise floor, separated by silences long enough to count as
a phrase break.

Algorithm:
  1. Compute frame-wise RMS energy on the vocal stem.
  2. Pick a noise floor (percentile-based, robust to bleed and reverb tails).
  3. Mark each frame as VOICED (above floor) or SILENT.
  4. Collapse short gaps: a silence shorter than min_gap_ms is filled with
     VOICED so a breath in the middle of a phrase doesn't split it.
  5. Drop short voiced regions: anything shorter than min_phrase_ms is noise.
  6. Pad each phrase by attack/release ms so we don't clip consonants.

Returns a list of (start_sample, end_sample) tuples.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class PhraseDetectionConfig:
    # Noise-floor percentile of frame RMS. Frames louder than this percentile
    # of the energy distribution are considered "voiced". 25 is a good default
    # for music; bleed-heavy stems may need 35-45.
    noise_floor_percentile: float = 25.0
    # Multiplier above the percentile to set the actual threshold. >1 makes
    # the gate stricter (drops more borderline frames).
    threshold_multiplier: float = 1.4

    # Time-domain parameters (in milliseconds)
    frame_hop_ms: float = 23.2          # ~1024 samples at 44.1k
    min_gap_ms: float = 350.0           # silences shorter than this are merged
    min_phrase_ms: float = 600.0        # phrases shorter than this are dropped
    pre_pad_ms: float = 80.0            # extra audio before the detected start
    post_pad_ms: float = 200.0          # extra audio after the detected end
    max_phrase_ms: float = 10000.0      # cap, just to keep pad samples sane

    # Limit how many phrases we return (best/loudest kept)
    max_phrases: int = 8


def detect_vocal_phrases(
    audio_path: Path,
    config: Optional[PhraseDetectionConfig] = None,
) -> list[tuple[int, int]]:
    """
    Return a list of (start_sample, end_sample) regions where the vocal sings.
    Uses librosa if available; otherwise falls back to a pure-numpy RMS.
    """
    cfg = config or PhraseDetectionConfig()
    y, sr = _load_mono(audio_path)
    if y is None or len(y) == 0:
        return []

    hop = max(1, int(cfg.frame_hop_ms / 1000 * sr))
    rms = _frame_rms(y, hop)
    if len(rms) == 0:
        return []

    # 1) Noise floor + threshold
    floor = float(np.percentile(rms, cfg.noise_floor_percentile))
    threshold = floor * cfg.threshold_multiplier
    voiced_mask = rms > threshold

    # 2) Merge short gaps within phrases (e.g. a breath)
    min_gap_frames = max(1, int(cfg.min_gap_ms / cfg.frame_hop_ms))
    voiced_mask = _fill_short_gaps(voiced_mask, min_gap_frames)

    # 3) Extract contiguous voiced regions
    regions_frames = _runs(voiced_mask)

    # 4) Filter by length and pad
    min_phrase_frames = max(1, int(cfg.min_phrase_ms / cfg.frame_hop_ms))
    max_phrase_samples = int(cfg.max_phrase_ms / 1000 * sr)
    pre_pad = int(cfg.pre_pad_ms / 1000 * sr)
    post_pad = int(cfg.post_pad_ms / 1000 * sr)

    n_samples = len(y)
    phrases: list[tuple[int, int, float]] = []  # (start, end, mean_rms)
    for f_start, f_end in regions_frames:
        if (f_end - f_start) < min_phrase_frames:
            continue
        s = max(0, f_start * hop - pre_pad)
        e = min(n_samples, f_end * hop + post_pad)
        if e - s > max_phrase_samples:
            e = s + max_phrase_samples
        if e <= s:
            continue
        mean_rms = float(np.mean(rms[f_start:f_end]))
        phrases.append((s, e, mean_rms))

    if not phrases:
        log.warning("No vocal phrases detected (floor=%.5f, threshold=%.5f)",
                    floor, threshold)
        return []

    # 5) Sort by loudness, keep top N, then re-sort chronologically
    phrases.sort(key=lambda p: p[2], reverse=True)
    phrases = phrases[:cfg.max_phrases]
    phrases.sort(key=lambda p: p[0])

    log.info("Detected %d vocal phrases (floor=%.5f, threshold=%.5f)",
             len(phrases), floor, threshold)
    return [(s, e) for s, e, _ in phrases]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _load_mono(path: Path) -> tuple[Optional[np.ndarray], int]:
    """Load audio as mono float32. Returns (audio, sample_rate)."""
    try:
        import soundfile as sf
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        mono = data.mean(axis=1) if data.ndim == 2 else data
        return mono.astype(np.float32), int(sr)
    except Exception as e:
        log.warning("Failed to load %s: %s", path, e)
        return None, 44100


def _frame_rms(y: np.ndarray, hop: int) -> np.ndarray:
    """Frame-wise RMS energy. Pure numpy, no librosa dependency."""
    n_frames = (len(y) + hop - 1) // hop
    if n_frames == 0:
        return np.zeros(0, dtype=np.float32)
    rms = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        start = i * hop
        end = min(start + hop, len(y))
        if end > start:
            seg = y[start:end]
            rms[i] = float(np.sqrt(np.mean(seg * seg)))
    return rms


def _fill_short_gaps(mask: np.ndarray, min_gap_frames: int) -> np.ndarray:
    """Set False runs shorter than min_gap_frames to True."""
    if min_gap_frames <= 1:
        return mask
    out = mask.copy()
    runs = _runs(~mask)  # silence runs
    for s, e in runs:
        if (e - s) < min_gap_frames:
            # But don't fill silences at the very edges of the track
            if s > 0 and e < len(mask):
                out[s:e] = True
    return out


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Find contiguous True runs as (start_inclusive, end_exclusive)."""
    if len(mask) == 0:
        return []
    # Pad with False on both sides so diffs find edges
    padded = np.concatenate([[False], mask, [False]])
    diff = np.diff(padded.astype(np.int8))
    starts = np.where(diff == 1)[0]
    ends = np.where(diff == -1)[0]
    return list(zip(starts.tolist(), ends.tolist()))
