"""
AI-powered sample analyzer — detects phrases, hits, breaks, and core regions
with automatic color assignment.

Categories and colors:
  PHRASE  → BLUE   (vocal/melodic phrase, > 600ms with sustained energy)
  HIT     → RED    (drum/percussion onset, < 300ms with sharp attack)
  BREAK   → GRAY   (silence > 200ms)
  CORE    → BRIGHT (the 0.5-2s "essence" of a phrase/hit — visual highlight)

The CORE region is computed as the most energetic 0.5-2s window inside
a PHRASE. For HITs, the core is the entire hit (they're already short).

Output: list of SampleAnnotation objects, ordered by start time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


class AnnotationKind(str, Enum):
    """Type of detected region."""
    PHRASE = "phrase"   # vocal/melodic phrase → BLUE
    HIT = "hit"         # drum/percussion onset → RED
    BREAK = "break"     # silence > 200ms → GRAY
    CORE = "core"       # highlight: essence of a phrase → BRIGHT


# Standard color palette (hex strings, ready for QML)
COLORS = {
    AnnotationKind.PHRASE: "#3D8EF0",  # blue
    AnnotationKind.HIT:    "#E74C3C",  # red
    AnnotationKind.BREAK:  "#7878A0",  # gray
    AnnotationKind.CORE:   "#F1C40F",  # bright yellow (overlay)
}


@dataclass(frozen=True)
class SampleAnnotation:
    """A detected region with kind, position, color, and optional label."""
    kind: AnnotationKind
    start_sample: int
    end_sample: int
    sample_rate: int
    color: str
    label: str = ""             # e.g., "vocal phrase 3", "drum hit"
    confidence: float = 1.0     # 0..1, detection certainty
    parent_idx: Optional[int] = None  # index of parent phrase (if this is a CORE)

    @property
    def duration_ms(self) -> float:
        return ((self.end_sample - self.start_sample) / self.sample_rate) * 1000

    @property
    def start_seconds(self) -> float:
        return self.start_sample / self.sample_rate

    @property
    def end_seconds(self) -> float:
        return self.end_sample / self.sample_rate


@dataclass(frozen=True)
class AnalyzerConfig:
    """Tunable parameters for sample analysis."""
    # Phrase detection
    phrase_min_ms: float = 600.0           # minimum phrase length
    phrase_max_ms: float = 12000.0         # maximum phrase length
    phrase_silence_gap_ms: float = 300.0   # silence to split phrases

    # Hit detection
    hit_min_ms: float = 50.0
    hit_max_ms: float = 300.0
    hit_min_strength: float = 0.4          # 0..1 onset strength threshold

    # Break detection
    break_min_ms: float = 200.0

    # Core isolation
    core_min_ms: float = 500.0
    core_max_ms: float = 2000.0

    # Energy floor (percentile of RMS to ignore as silence)
    silence_percentile: float = 20.0


def analyze_sample(audio_path: Path,
                    config: Optional[AnalyzerConfig] = None) -> list[SampleAnnotation]:
    """
    Run full analysis on an audio file.
    Returns annotations sorted by start_sample.
    """
    cfg = config or AnalyzerConfig()

    try:
        import librosa
    except ImportError as e:
        log.warning("librosa not installed: %s", e)
        return []

    try:
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    except Exception as e:
        log.exception("Failed to load %s: %s", audio_path, e)
        return []

    if len(y) == 0:
        return []

    annotations: list[SampleAnnotation] = []

    # 1. Detect phrases (sustained voiced regions)
    phrases = _detect_phrases(y, sr, cfg)
    for i, (s, e) in enumerate(phrases):
        annotations.append(SampleAnnotation(
            kind=AnnotationKind.PHRASE,
            start_sample=s, end_sample=e, sample_rate=sr,
            color=COLORS[AnnotationKind.PHRASE],
            label=f"phrase {i + 1}",
            confidence=0.85,
        ))

        # 2. Compute core region within this phrase
        core_s, core_e = _isolate_core(y, sr, s, e, cfg)
        if core_e > core_s:
            annotations.append(SampleAnnotation(
                kind=AnnotationKind.CORE,
                start_sample=core_s, end_sample=core_e, sample_rate=sr,
                color=COLORS[AnnotationKind.CORE],
                label=f"core of phrase {i + 1}",
                confidence=0.75,
                parent_idx=i,
            ))

    # 3. Detect hits (sharp onsets)
    hits = _detect_hits(y, sr, cfg)
    for i, (s, e, strength) in enumerate(hits):
        # Skip hits that fall inside a phrase (they're already covered)
        if _is_inside_any(s, phrases):
            continue
        annotations.append(SampleAnnotation(
            kind=AnnotationKind.HIT,
            start_sample=s, end_sample=e, sample_rate=sr,
            color=COLORS[AnnotationKind.HIT],
            label=f"hit {i + 1}",
            confidence=min(1.0, strength),
        ))

    # 4. Detect breaks (silence > 200ms)
    breaks = _detect_breaks(y, sr, cfg)
    for i, (s, e) in enumerate(breaks):
        annotations.append(SampleAnnotation(
            kind=AnnotationKind.BREAK,
            start_sample=s, end_sample=e, sample_rate=sr,
            color=COLORS[AnnotationKind.BREAK],
            label=f"break {i + 1}",
            confidence=0.9,
        ))

    annotations.sort(key=lambda a: a.start_sample)
    log.info("Analyzed %s: %d annotations (P=%d, H=%d, B=%d, C=%d)",
             audio_path.name, len(annotations),
             sum(1 for a in annotations if a.kind == AnnotationKind.PHRASE),
             sum(1 for a in annotations if a.kind == AnnotationKind.HIT),
             sum(1 for a in annotations if a.kind == AnnotationKind.BREAK),
             sum(1 for a in annotations if a.kind == AnnotationKind.CORE))
    return annotations


# ---------------------------------------------------------------------------
# Detection sub-routines
# ---------------------------------------------------------------------------

def _detect_phrases(y: np.ndarray, sr: int,
                     cfg: AnalyzerConfig) -> list[tuple[int, int]]:
    """
    Detect sustained voiced regions using a silence gate.
    Returns list of (start_sample, end_sample) at sr=sr.
    """
    hop = max(1, int(sr * 0.025))  # 25ms frame hop
    rms = _frame_rms(y, hop)
    if len(rms) == 0:
        return []

    # Hybrid threshold: max of (percentile-based floor) and (relative-to-peak)
    # This handles both noisy backgrounds AND clean studio audio.
    max_rms = float(rms.max()) if len(rms) else 0.0
    if max_rms < 1e-6:
        return []  # Pure silence
    silence_floor = float(np.percentile(rms, cfg.silence_percentile))
    threshold_floor = silence_floor * 1.5
    threshold_relative = max_rms * 0.1   # 10% of peak = voiced
    threshold = max(threshold_floor, threshold_relative * 0.5)
    # Cap threshold so it can't exceed half the peak (otherwise nothing passes)
    threshold = min(threshold, max_rms * 0.5)

    voiced = rms > threshold

    # Merge short silences
    min_gap = max(1, int(cfg.phrase_silence_gap_ms / 25))
    voiced = _fill_short_gaps(voiced, min_gap)

    # Extract contiguous regions
    runs = _runs(voiced)

    # Filter and convert to samples
    min_frames = max(1, int(cfg.phrase_min_ms / 25))
    max_samples = int(cfg.phrase_max_ms / 1000 * sr)
    phrases = []
    for f_start, f_end in runs:
        if f_end - f_start < min_frames:
            continue
        s = f_start * hop
        e = min(len(y), f_end * hop)
        if e - s > max_samples:
            e = s + max_samples
        phrases.append((int(s), int(e)))

    return phrases


def _detect_hits(y: np.ndarray, sr: int,
                  cfg: AnalyzerConfig) -> list[tuple[int, int, float]]:
    """
    Detect sharp percussive onsets.
    Returns list of (start_sample, end_sample, strength).
    """
    try:
        import librosa
    except ImportError:
        return []

    hop = 512
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    if len(onset_env) == 0:
        return []

    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, hop_length=hop, backtrack=True, units="frames"
    )

    max_strength = float(onset_env.max()) or 1.0
    hit_duration_samples = int(cfg.hit_max_ms / 1000 * sr)
    hits = []
    # backtrack=True returns the frame at the onset's lead-in (local min),
    # where the strength is near zero. Search ahead for the actual peak.
    SEARCH_WINDOW = 5  # frames (~58ms at hop=512, sr=22050)
    for f in onset_frames:
        f = int(f)
        # Find peak strength within the next SEARCH_WINDOW frames
        win_end = min(len(onset_env), f + SEARCH_WINDOW + 1)
        if f >= len(onset_env) or win_end <= f:
            continue
        peak_strength = float(onset_env[f:win_end].max())
        strength = peak_strength / max_strength
        if strength < cfg.hit_min_strength:
            continue
        s = f * hop
        e = min(len(y), s + hit_duration_samples)
        hits.append((s, e, strength))

    return hits


def _detect_breaks(y: np.ndarray, sr: int,
                    cfg: AnalyzerConfig) -> list[tuple[int, int]]:
    """
    Detect silence regions longer than cfg.break_min_ms.
    Returns list of (start_sample, end_sample).
    """
    hop = max(1, int(sr * 0.025))
    rms = _frame_rms(y, hop)
    if len(rms) == 0:
        return []

    max_rms = float(rms.max())
    if max_rms < 1e-6:
        return []
    # Silence is anything below 10% of peak (and below percentile floor)
    silence_floor = float(np.percentile(rms, cfg.silence_percentile))
    silence_threshold = min(silence_floor * 1.2, max_rms * 0.1)
    silent_mask = rms <= silence_threshold

    min_break_frames = max(1, int(cfg.break_min_ms / 25))
    runs = _runs(silent_mask)
    breaks = []
    for f_start, f_end in runs:
        if f_end - f_start < min_break_frames:
            continue
        # Skip leading/trailing silence
        if f_start == 0 or f_end >= len(silent_mask):
            continue
        s = f_start * hop
        e = min(len(y), f_end * hop)
        breaks.append((int(s), int(e)))

    return breaks


def _isolate_core(y: np.ndarray, sr: int, start: int, end: int,
                   cfg: AnalyzerConfig) -> tuple[int, int]:
    """
    Find the most energetic 0.5-2s window inside a phrase region.
    Returns (core_start, core_end) in samples.
    """
    region = y[start:end]
    if len(region) == 0:
        return start, end

    target_len_samples = int(cfg.core_min_ms / 1000 * sr)
    max_len_samples = int(cfg.core_max_ms / 1000 * sr)

    # Use 100ms windows to find the most energetic stretch
    win = max(1, int(sr * 0.1))
    if len(region) <= target_len_samples:
        return start, end

    # Compute RMS in sliding windows
    rms = _frame_rms(region, win)
    if len(rms) == 0:
        return start, end

    # Window of target_len_samples in frames
    target_frames = max(1, target_len_samples // win)
    max_frames = max(target_frames + 1, max_len_samples // win)

    # Find the window with the highest average RMS
    if len(rms) <= target_frames:
        return start, end

    # Smoothed RMS for the search
    smoothed = np.convolve(rms, np.ones(target_frames) / target_frames, mode="valid")
    if len(smoothed) == 0:
        return start, end

    peak_idx = int(np.argmax(smoothed))
    # Expand the window slightly to max_frames if energy stays high
    expand_threshold = smoothed[peak_idx] * 0.7
    left = peak_idx
    right = peak_idx + target_frames
    while right - left < max_frames:
        # Try to expand left
        if left > 0 and rms[left - 1] > expand_threshold:
            left -= 1
        # Try to expand right
        elif right < len(rms) and rms[right] > expand_threshold:
            right += 1
        else:
            break

    core_start = start + left * win
    core_end = min(end, start + right * win)
    return int(core_start), int(core_end)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frame_rms(y: np.ndarray, hop: int) -> np.ndarray:
    """Frame-wise RMS energy."""
    if hop <= 0:
        return np.zeros(0, dtype=np.float32)
    n_frames = (len(y) + hop - 1) // hop
    rms = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        start = i * hop
        end = min(start + hop, len(y))
        if end > start:
            seg = y[start:end]
            rms[i] = float(np.sqrt(np.mean(seg * seg)))
    return rms


def _fill_short_gaps(mask: np.ndarray, min_gap_frames: int) -> np.ndarray:
    """Bridge short False runs in a True/False mask."""
    if min_gap_frames <= 1:
        return mask
    out = mask.copy()
    gaps = _runs(~mask)
    for s, e in gaps:
        if (e - s) < min_gap_frames and 0 < s and e < len(mask):
            out[s:e] = True
    return out


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Find contiguous True runs as (start, end_exclusive)."""
    if len(mask) == 0:
        return []
    padded = np.concatenate([[False], mask, [False]])
    diff = np.diff(padded.astype(np.int8))
    starts = np.where(diff == 1)[0]
    ends = np.where(diff == -1)[0]
    return list(zip(starts.tolist(), ends.tolist()))


def _is_inside_any(point: int, regions: list[tuple[int, int]]) -> bool:
    """True if `point` falls inside any (start, end) range."""
    return any(start <= point < end for start, end in regions)
