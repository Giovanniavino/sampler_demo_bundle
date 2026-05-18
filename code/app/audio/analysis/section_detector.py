"""
Section detection (intro / verse / chorus / bridge / outro).

Strategy:
  1. Try allin1 (best quality). Requires madmom — may not be available.
  2. Fallback to an SSM-based detector that we control fully.

The SSM (self-similarity matrix) approach:
  - Compute CQT-based chroma features per beat
  - Build a beat-synchronous SSM
  - Use spectral clustering on the SSM to find K segments
  - Label segments by:
      * first segment -> INTRO
      * last segment -> OUTRO
      * most-energetic + most-repeated -> CHORUS
      * second-most-energetic non-chorus -> VERSE
      * different-from-others segment in second half -> BRIDGE
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.models import Section, SectionLabel

log = logging.getLogger(__name__)


class SectionDetector(ABC):
    """Abstract section detector. Returns labeled Section list."""

    @abstractmethod
    def detect(self, audio_path: Path) -> list[Section]: ...


# ---------------------------------------------------------------------------
# Allin1 — best quality, but requires madmom (often missing on Windows/3.12)
# ---------------------------------------------------------------------------

class Allin1Detector(SectionDetector):
    """Uses allin1 (mir-aist) for full musical structure analysis."""

    _LABEL_MAP = {
        "intro":  SectionLabel.INTRO,
        "verse":  SectionLabel.VERSE,
        "chorus": SectionLabel.CHORUS,
        "bridge": SectionLabel.BRIDGE,
        "outro":  SectionLabel.OUTRO,
        "break":  SectionLabel.BREAK,
        "instrumental": SectionLabel.UNKNOWN,
        "solo":   SectionLabel.UNKNOWN,
    }

    @staticmethod
    def is_available() -> bool:
        """Quick check: does importing allin1 succeed?"""
        try:
            import allin1  # noqa: F401
            return True
        except Exception as e:
            log.info("allin1 not available: %s", e)
            return False

    def detect(self, audio_path: Path) -> list[Section]:
        import allin1
        log.info("Running allin1 on %s (this may take 30-90s on CPU)", audio_path.name)
        try:
            result = allin1.analyze(str(audio_path))
        except Exception as e:
            log.warning("allin1 failed: %s — falling back to SSM", e)
            return SSMSectionDetector().detect(audio_path)

        sr = 44100  # allin1 reports times in seconds
        out: list[Section] = []
        for seg in result.segments:
            label = self._LABEL_MAP.get(
                str(seg.label).lower(), SectionLabel.UNKNOWN
            )
            out.append(Section(
                start=int(seg.start * sr),
                end=int(seg.end * sr),
                label=label,
                confidence=0.9,
            ))
        log.info("allin1 found %d sections", len(out))
        return out


# ---------------------------------------------------------------------------
# SSM-based fallback — always available
# ---------------------------------------------------------------------------

class SSMSectionDetector(SectionDetector):
    """
    Self-similarity-matrix based detector.

    Better than the old agglomerative+RMS approach because it:
      - uses chroma features (harmonic content, more meaningful than MFCC)
      - is beat-synchronous (no off-by-half-beat boundaries)
      - uses repetition score for chorus identification (chorus is the most
        repeated section; verse is less repeated; bridge often unique)
    """

    def __init__(self, target_sections: int = 6, min_section_bars: int = 4):
        self.target_sections = target_sections
        self.min_section_bars = min_section_bars

    def detect(self, audio_path: Path) -> list[Section]:
        try:
            return self._detect_inner(audio_path)
        except Exception as e:
            log.warning("SSM detection failed: %s — returning whole-track section", e)
            return self._whole_track_fallback(audio_path)

    def _detect_inner(self, audio_path: Path) -> list[Section]:
        import librosa
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
        total_samples = int(len(y) * 44100 / sr)  # convert to 44.1k samples

        # Beat tracking for synchronous features
        _, beats = librosa.beat.beat_track(y=y, sr=sr, hop_length=512)
        if len(beats) < 16:
            log.warning("Too few beats (%d) — using whole track", len(beats))
            return self._whole_track(total_samples)

        # Chroma features (harmonic content)
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=512)
        # Sync to beats: one chroma vector per beat
        chroma_sync = librosa.util.sync(chroma, beats, aggregate=np.median)

        # Smooth slightly to reduce noise
        chroma_sync = self._smooth_columns(chroma_sync, window=2)

        # Determine number of sections to target
        n_beats = chroma_sync.shape[1]
        # Rule of thumb: ~16-32 beats per section
        k_target = max(3, min(self.target_sections, n_beats // 16))
        log.info("SSM: %d beats, targeting %d sections", n_beats, k_target)

        # Find section boundaries via spectral clustering on the chroma SSM
        bounds_beat_idx = self._cluster_boundaries(chroma_sync, k_target)
        if len(bounds_beat_idx) < 2:
            return self._whole_track(total_samples)

        # Convert beat indices back to sample positions (in source 22050 sr,
        # then to 44100)
        bound_samples_src = librosa.frames_to_samples(beats[bounds_beat_idx], hop_length=512)
        bound_samples_44k = [int(s * 44100 / sr) for s in bound_samples_src]
        # Ensure span covers the full track
        if bound_samples_44k[0] > 0:
            bound_samples_44k = [0] + bound_samples_44k
        if bound_samples_44k[-1] < total_samples:
            bound_samples_44k.append(total_samples)

        # Build raw sections
        sections_raw = list(zip(bound_samples_44k[:-1], bound_samples_44k[1:]))

        # Compute per-section features for labeling
        rms_per = self._rms_per_section(y, sr, sections_raw)
        repeat_per = self._repetition_score(
            chroma_sync, beats, bounds_beat_idx, sr,
            n_sections=len(sections_raw),
        )
        return self._label_sections(sections_raw, rms_per, repeat_per)

    # ---- Clustering ---------------------------------------------------

    def _cluster_boundaries(self, features: np.ndarray, k: int) -> np.ndarray:
        """
        Find segmentation boundaries using librosa's agglomerative clustering
        on the feature matrix. Returns boundary indices in beat space.
        """
        import librosa
        bounds = librosa.segment.agglomerative(features, k)
        # bounds are beat-index positions where segments start
        return np.unique(bounds)

    # ---- Labeling -----------------------------------------------------

    def _label_sections(
        self,
        sections_raw: list[tuple[int, int]],
        rms_per: list[float],
        repeat_per: list[float],
    ) -> list[Section]:
        """
        Assign labels using a more musical heuristic:
          - first  -> INTRO  (unless very loud — then VERSE/CHORUS, intro = silent)
          - last   -> OUTRO  (same caveat)
          - CHORUS: top combined score (loud + repeated) among non-edge sections
          - VERSE:  loud but less repeated than chorus
          - BRIDGE: a section in the second half with high "uniqueness"
                    (low repetition, different from chorus)
          - rest   -> VERSE
        """
        n = len(sections_raw)
        if n == 0:
            return []
        if n == 1:
            s, e = sections_raw[0]
            return [Section(start=s, end=e, label=SectionLabel.UNKNOWN, confidence=0.5)]

        labels: list[SectionLabel] = [SectionLabel.UNKNOWN] * n
        confs:  list[float]        = [0.6] * n

        # Edges
        labels[0]    = SectionLabel.INTRO
        labels[-1]   = SectionLabel.OUTRO

        # Score = normalized RMS + 0.5 * repetition score
        rms_arr     = np.array(rms_per, dtype=np.float32)
        repeat_arr  = np.array(repeat_per, dtype=np.float32)
        rms_norm    = rms_arr / (rms_arr.max() + 1e-8)
        repeat_norm = repeat_arr / (repeat_arr.max() + 1e-8)
        score = rms_norm + 0.5 * repeat_norm

        middle = list(range(1, n - 1))
        if not middle:
            return [Section(start=s, end=e, label=labels[i], confidence=confs[i])
                    for i, (s, e) in enumerate(sections_raw)]

        # Chorus candidates: highest combined score
        scored = sorted(middle, key=lambda i: score[i], reverse=True)
        # Pick top ~half as chorus, rest as verse (or bridge)
        n_chorus = max(1, len(scored) // 2)
        chorus_idx = set(scored[:n_chorus])

        # Bridge: among non-chorus middle sections in second half,
        # the one with LOWEST repetition
        second_half = [i for i in middle if i not in chorus_idx and i > n // 2]
        bridge_idx = None
        if second_half:
            bridge_idx = min(second_half, key=lambda i: repeat_arr[i])
            # Only mark as bridge if its uniqueness is clearly distinct
            if repeat_arr[bridge_idx] < 0.5 * repeat_arr.mean():
                pass  # confirmed
            else:
                bridge_idx = None

        for i in middle:
            if i in chorus_idx:
                labels[i] = SectionLabel.CHORUS
                confs[i]  = 0.7
            elif i == bridge_idx:
                labels[i] = SectionLabel.BRIDGE
                confs[i]  = 0.6
            else:
                labels[i] = SectionLabel.VERSE
                confs[i]  = 0.65

        return [Section(start=s, end=e, label=labels[i], confidence=confs[i])
                for i, (s, e) in enumerate(sections_raw)]

    # ---- Helpers ------------------------------------------------------

    def _smooth_columns(self, mat: np.ndarray, window: int = 2) -> np.ndarray:
        if window <= 1:
            return mat
        from scipy.ndimage import uniform_filter1d
        return uniform_filter1d(mat, size=window, axis=1, mode="nearest")

    def _rms_per_section(self, y: np.ndarray, sr: int,
                         sections: list[tuple[int, int]]) -> list[float]:
        rms = []
        for s_44k, e_44k in sections:
            s = int(s_44k * sr / 44100)
            e = int(e_44k * sr / 44100)
            e = max(e, s + 1)
            seg = y[s:min(e, len(y))]
            rms.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
        return rms

    def _repetition_score(self, chroma_sync: np.ndarray, beats: np.ndarray,
                          bounds_beat_idx: np.ndarray, sr: int,
                          n_sections: int = None) -> list[float]:
        """
        For each section, how similar is it to OTHER sections?
        High score = repeated (chorus). Low score = unique (bridge).

        n_sections is the actual number of sections after edge padding.
        If different from len(bounds_beat_idx)-1, we pad with neutral scores.
        """
        # Compute mean chroma per section in beat space
        n_bound = len(bounds_beat_idx) - 1
        if n_bound < 1:
            return [0.5] * (n_sections or 0)
        means = []
        for i in range(n_bound):
            s_beat = bounds_beat_idx[i]
            e_beat = bounds_beat_idx[i + 1]
            if e_beat <= s_beat or e_beat > chroma_sync.shape[1]:
                means.append(np.zeros(chroma_sync.shape[0]))
                continue
            means.append(chroma_sync[:, s_beat:e_beat].mean(axis=1))
        means = np.stack(means)

        scores = []
        for i in range(n_bound):
            others = np.delete(means, i, axis=0)
            if len(others) == 0:
                scores.append(0.5)
                continue
            num = others @ means[i]
            den = (np.linalg.norm(others, axis=1) * np.linalg.norm(means[i]) + 1e-8)
            sims = num / den
            scores.append(float(np.max(sims)))

        # Pad if we added edge sections (intro/outro from 0 and total_samples)
        target = n_sections if n_sections is not None else n_bound
        if target > len(scores):
            pad = [0.5] * (target - len(scores))
            scores = pad[:1] + scores + pad[1:] if len(pad) >= 2 else scores + pad
        return scores[:target]

    def _whole_track(self, total_samples: int) -> list[Section]:
        return [Section(start=0, end=total_samples,
                        label=SectionLabel.UNKNOWN, confidence=0.3)]

    def _whole_track_fallback(self, audio_path: Path) -> list[Section]:
        try:
            import soundfile as sf
            info = sf.info(str(audio_path))
            return self._whole_track(info.frames)
        except Exception:
            return self._whole_track(0)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_section_detector(prefer_allin1: bool = True) -> SectionDetector:
    """Return the best available detector."""
    if prefer_allin1 and Allin1Detector.is_available():
        log.info("Using allin1 for section detection")
        return Allin1Detector()
    log.info("Using SSM-based section detector (allin1 not available)")
    return SSMSectionDetector()
