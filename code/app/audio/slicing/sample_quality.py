"""
Sample quality filtering & enhancement for the auto-slicer.

Goals:
  1. REJECT low-quality samples:
     - Pure silence or near-silence (RMS below threshold)
     - Samples that are mostly silent (only a tiny fraction has energy)
     - Samples too short to be useful after trimming
  2. IMPROVE perceived quality:
     - Auto-trim leading/trailing silence so a pad triggers instantly
     - Flag samples that should be normalized (very quiet but not silent)

The filter operates on Sample records by inspecting the underlying stem audio.
It is non-destructive: it adjusts start_sample/end_sample and the `normalized`
flag, or drops the sample entirely.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QualityConfig:
    """Thresholds for sample quality filtering."""
    # A sample whose peak RMS is below this is considered silent → rejected.
    min_rms: float = 0.008
    # A sample must have at least this fraction of frames above the noise
    # floor, otherwise it's "mostly silent" → rejected.
    min_active_fraction: float = 0.10
    # Frames quieter than (peak * this) count as silence for trimming.
    silence_rel_threshold: float = 0.06
    # After trimming, a sample shorter than this (ms) is rejected.
    min_length_after_trim_ms: float = 120.0
    # Samples whose peak is below this get their `normalized` flag set so the
    # engine brings them up to a usable level.
    normalize_below_peak: float = 0.25
    # RMS analysis frame size (ms)
    frame_ms: float = 20.0
    # Don't trim more than this fraction off either end (safety: keep attacks)
    max_trim_fraction: float = 0.45


@dataclass
class QualityReport:
    """Outcome of evaluating one sample."""
    keep: bool
    new_start: int
    new_end: int
    should_normalize: bool
    reason: str = ""


def evaluate_sample(audio_mono: np.ndarray,
                    start: int, end: int,
                    sample_rate: int,
                    cfg: QualityConfig,
                    is_drum_hit: bool = False) -> QualityReport:
    """
    Evaluate a sample region [start, end] of a mono stem.

    Returns a QualityReport telling the caller whether to keep the sample,
    the (possibly trimmed) boundaries, and whether to normalize it.

    is_drum_hit: if True, we DON'T trim the start (preserve the attack
    transient) and we use a more lenient length requirement.
    """
    n = len(audio_mono)
    start = max(0, min(start, n))
    end = max(start, min(end, n))
    region = audio_mono[start:end]

    if len(region) == 0:
        return QualityReport(False, start, end, False, "empty region")

    # Overall energy
    peak = float(np.max(np.abs(region)))
    rms = float(np.sqrt(np.mean(region * region)))

    if peak < 1e-6 or rms < cfg.min_rms:
        return QualityReport(False, start, end, False,
                             f"silent (rms={rms:.4f})")

    # Frame-wise RMS to measure how much of the sample is actually "active"
    frame = max(1, int(cfg.frame_ms / 1000 * sample_rate))
    n_frames = max(1, len(region) // frame)
    frame_rms = np.empty(n_frames, dtype=np.float32)
    for i in range(n_frames):
        seg = region[i * frame:(i + 1) * frame]
        frame_rms[i] = float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0

    active_threshold = peak * cfg.silence_rel_threshold
    active_mask = frame_rms > active_threshold
    active_fraction = float(active_mask.sum()) / len(active_mask)

    if active_fraction < cfg.min_active_fraction:
        return QualityReport(False, start, end, False,
                             f"mostly silent (active={active_fraction:.2f})")

    # Trim leading/trailing silence (find first/last active frame)
    active_indices = np.where(active_mask)[0]
    first_active = int(active_indices[0])
    last_active = int(active_indices[-1])

    trim_start_frames = first_active
    trim_end_frames = (len(active_mask) - 1) - last_active

    # Safety cap: don't trim too aggressively
    max_trim_frames = int(len(active_mask) * cfg.max_trim_fraction)
    trim_start_frames = min(trim_start_frames, max_trim_frames)
    trim_end_frames = min(trim_end_frames, max_trim_frames)

    new_start = start
    new_end = end
    if not is_drum_hit:
        # Trim both ends for non-drum samples
        new_start = start + trim_start_frames * frame
        new_end = end - trim_end_frames * frame
    else:
        # For drum hits, keep the attack — only trim trailing silence
        new_end = end - trim_end_frames * frame

    new_start = max(start, min(new_start, end))
    new_end = max(new_start + 1, min(new_end, end))

    # Length check after trim
    length_ms = (new_end - new_start) / sample_rate * 1000
    min_len = cfg.min_length_after_trim_ms * (0.5 if is_drum_hit else 1.0)
    if length_ms < min_len:
        return QualityReport(False, new_start, new_end, False,
                             f"too short after trim ({length_ms:.0f}ms)")

    # Normalize flag for quiet-but-valid samples
    should_normalize = peak < cfg.normalize_below_peak

    return QualityReport(True, int(new_start), int(new_end),
                         should_normalize, "ok")


def filter_samples(samples: list,
                   stem_audio_loader,
                   sample_rate_getter,
                   cfg: Optional[QualityConfig] = None,
                   drum_categories: Optional[set] = None) -> tuple[list, int]:
    """
    Filter a list of Sample records, rejecting low-quality ones and
    trimming/normalizing the rest.

    Args:
      samples: list of Sample objects (must have source_stem_id,
               start_sample, end_sample, category, normalized).
      stem_audio_loader: callable(stem_id) -> mono np.ndarray or None.
                         Should be cached by the caller for performance.
      sample_rate_getter: callable(stem_id) -> int sample rate.
      cfg: QualityConfig (defaults used if None).
      drum_categories: set of SampleCategory values treated as drum hits
                       (attack-preserving). If None, nothing is treated as drum.

    Returns:
      (kept_samples, num_rejected)
    """
    cfg = cfg or QualityConfig()
    drum_categories = drum_categories or set()

    kept = []
    rejected = 0
    audio_cache: dict[str, Optional[np.ndarray]] = {}

    for s in samples:
        stem_id = getattr(s, "source_stem_id", None)
        if stem_id is None:
            # Can't evaluate — keep it to be safe
            kept.append(s)
            continue

        if stem_id not in audio_cache:
            audio_cache[stem_id] = stem_audio_loader(stem_id)
        audio = audio_cache[stem_id]

        if audio is None:
            # Couldn't load — keep it (don't punish for IO failure)
            kept.append(s)
            continue

        sr = sample_rate_getter(stem_id)
        is_drum = getattr(s, "category", None) in drum_categories

        report = evaluate_sample(
            audio, s.start_sample, s.end_sample, sr, cfg, is_drum_hit=is_drum
        )

        if not report.keep:
            rejected += 1
            log.debug("Rejected '%s': %s",
                      getattr(s, "name", "?"), report.reason)
            continue

        # Apply trim + normalize flag
        s.start_sample = report.new_start
        s.end_sample = report.new_end
        if report.should_normalize:
            s.normalized = True
        kept.append(s)

    if rejected:
        log.info("Quality filter: kept %d, rejected %d silent/low-quality",
                 len(kept), rejected)
    return kept, rejected
