"""
Audio analysis: BPM, beat tracking, transient detection, section labeling.

Primary library: librosa (always installed).
Optional upgrades:
  - madmom for higher-quality beat/downbeat (RNN-based)
  - msaf or pyannote-derived models for section segmentation

We expose one Analyzer interface; default implementation uses librosa with
graceful fallbacks. Each sub-analyzer is decoupled, so swapping just the
beat tracker (e.g. to madmom) is a one-class change.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.models import (
    AnalysisResult, AudioSource, Beat, Section, SectionLabel, Stem,
    StemType, Transient,
)

log = logging.getLogger(__name__)


class Analyzer(ABC):
    @abstractmethod
    def analyze(self, source: AudioSource, stems: list[Stem]) -> AnalysisResult: ...


class LibrosaAnalyzer(Analyzer):
    """
    Reasonable default: librosa for everything.

    Strategy:
      - BPM + beats on the FULL mix (more harmonic info -> stable tracking)
      - Transients on the DRUMS stem if available, else full mix
      - Sections via librosa's recurrence-matrix segmentation, then a heuristic
        label (intro/verse/chorus/bridge/outro) based on position and energy.
    """

    def __init__(self, hop_length: int = 512, section_detector=None):
        self.hop_length = hop_length
        self._section_detector = section_detector

    # ---- Public --------------------------------------------------------

    def analyze(self, source: AudioSource, stems: list[Stem]) -> AnalysisResult:
        import librosa

        if not source.path:
            raise ValueError("AudioSource has no path")

        y, sr = librosa.load(str(source.path), sr=None, mono=True)
        log.info("Analyzing %s (sr=%d, %.1fs)", source.path.name, sr, len(y) / sr)

        bpm, beats = self._beats(y, sr)
        downbeats = self._downbeat_indices(len(beats))
        beat_objs = [
            Beat(position=int(b), is_downbeat=(i in downbeats))
            for i, b in enumerate(beats)
        ]

        drums = next((s for s in stems if s.stem_type == StemType.DRUMS), None)
        transients = self._transients(drums.path if drums else source.path, sr)

        # Use the dedicated section detector (allin1 or SSM fallback).
        # Lazy import to keep startup time low.
        if self._section_detector is None:
            from app.audio.analysis.section_detector import make_section_detector
            self._section_detector = make_section_detector(prefer_allin1=True)
        sections = self._section_detector.detect(source.path)

        return AnalysisResult(
            source_id=source.id,
            bpm=float(bpm),
            bpm_confidence=0.8,
            beats=beat_objs,
            sections=sections,
            transients=transients,
        )

    # ---- Internals -----------------------------------------------------

    def _beats(self, y: np.ndarray, sr: int) -> tuple[float, np.ndarray]:
        import librosa
        tempo, beat_frames = librosa.beat.beat_track(
            y=y, sr=sr, hop_length=self.hop_length, units="frames"
        )
        beat_samples = librosa.frames_to_samples(beat_frames, hop_length=self.hop_length)
        # librosa can return tempo as scalar or 1-elem array
        tempo_val = float(np.atleast_1d(tempo)[0])
        return tempo_val, beat_samples

    def _downbeat_indices(self, n_beats: int) -> set[int]:
        """Naive 4/4 assumption: every 4th beat is a downbeat.
        Replace with madmom's DBNDownBeatTrackingProcessor for accuracy."""
        return {i for i in range(0, n_beats, 4)}

    def _transients(self, path: Path, sr: int) -> list[Transient]:
        import librosa
        y, sr = librosa.load(str(path), sr=sr, mono=True)
        # backtrack=True snaps to local minima (start of the hit)
        onset_frames = librosa.onset.onset_detect(
            y=y, sr=sr, hop_length=self.hop_length, backtrack=True, units="frames"
        )
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=self.hop_length)
        positions = librosa.frames_to_samples(onset_frames, hop_length=self.hop_length)

        # Normalize strength to 0..1
        if len(onset_env):
            env_max = float(onset_env.max()) or 1.0
            strengths = [float(onset_env[min(f, len(onset_env) - 1)]) / env_max
                         for f in onset_frames]
        else:
            strengths = [1.0] * len(positions)

        return [Transient(position=int(p), strength=s)
                for p, s in zip(positions, strengths)]

    def _sections(self, y: np.ndarray, sr: int) -> list[Section]:
        """
        Use librosa.segment to get boundaries, then label heuristically.

        Heuristic:
          - First section -> INTRO
          - Last section  -> OUTRO
          - Among middle sections, the ones with highest RMS energy and
            longest duration get CHORUS; the others VERSE; one in the
            second half gets BRIDGE if it stands out spectrally.
        Good enough for an MVP; replace later with a proper SSM-based labeler.
        """
        import librosa
        try:
            bounds = librosa.segment.agglomerative(
                librosa.feature.mfcc(y=y, sr=sr, hop_length=self.hop_length),
                k=min(8, max(2, int(len(y) / sr / 20))),  # ~ 1 section per 20s
            )
            bound_samples = librosa.frames_to_samples(bounds, hop_length=self.hop_length)
            bound_samples = np.concatenate([[0], bound_samples, [len(y)]])
            bound_samples = np.unique(bound_samples)
        except Exception as e:
            log.warning("Section detection failed: %s", e)
            return [Section(start=0, end=len(y), label=SectionLabel.UNKNOWN)]

        # Compute RMS per section for chorus heuristic
        sections_raw = list(zip(bound_samples[:-1], bound_samples[1:]))
        rms_per = []
        for s, e in sections_raw:
            seg = y[s:e]
            rms_per.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)

        sections: list[Section] = []
        n = len(sections_raw)
        if n == 0:
            return sections

        # Rank middle sections by energy
        middle_idx = list(range(1, n - 1)) if n > 2 else []
        ranked = sorted(middle_idx, key=lambda i: rms_per[i], reverse=True)
        chorus_set = set(ranked[: max(1, len(ranked) // 2)])

        for i, (s, e) in enumerate(sections_raw):
            if i == 0:
                label = SectionLabel.INTRO
            elif i == n - 1:
                label = SectionLabel.OUTRO
            elif i in chorus_set:
                label = SectionLabel.CHORUS
            else:
                label = SectionLabel.VERSE
            sections.append(Section(start=int(s), end=int(e), label=label))

        return sections
