"""
Auto sample generation.

Given stems + analysis, produce a set of Sample records:
  - DRUMS  -> one Sample per transient (drum_hit), capped to N
  - DRUMS  -> a few 1-2 bar drum loops aligned to downbeats
  - VOCALS -> vocal chops on transients in vocal stem (silence-gated)
            + 4-8 bar vocal phrases aligned to sections
  - BASS   -> bass loops aligned to bars
  - OTHER  -> melodic phrases aligned to sections

Everything is non-destructive: samples reference stems by id + start/end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from app.core.models import (
    AnalysisResult, Sample, SampleCategory, Stem, StemType, Transient,
)

log = logging.getLogger(__name__)


@dataclass
class SlicerConfig:
    max_drum_hits: int = 32
    drum_hit_length_ms: int = 400          # max length of one drum hit slice
    drum_loop_bars: int = 2
    vocal_chop_length_ms: int = 1500
    vocal_phrase_bars: int = 4
    bass_loop_bars: int = 2
    melody_phrase_bars: int = 4
    default_fade_in_samples: int = 64
    default_fade_out_samples: int = 256


class AutoSlicer:
    def __init__(self, config: SlicerConfig | None = None):
        self.cfg = config or SlicerConfig()

    # ---- Entry ---------------------------------------------------------

    def slice_all(self, stems: list[Stem], analysis: AnalysisResult) -> list[Sample]:
        samples: list[Sample] = []
        beats_pos = [b.position for b in analysis.beats]
        bpm = analysis.bpm or 120.0

        for stem in stems:
            if stem.stem_type == StemType.DRUMS:
                samples.extend(self._slice_drums(stem, analysis, bpm))
            elif stem.stem_type == StemType.VOCALS:
                samples.extend(self._slice_vocals(stem, analysis, beats_pos, bpm))
            elif stem.stem_type == StemType.BASS:
                samples.extend(self._slice_loops(
                    stem, beats_pos, self.cfg.bass_loop_bars,
                    SampleCategory.BASS_LOOP, "Bass loop"
                ))
            elif stem.stem_type in (StemType.OTHER, StemType.PIANO, StemType.GUITAR):
                samples.extend(self._slice_loops(
                    stem, beats_pos, self.cfg.melody_phrase_bars,
                    SampleCategory.MELODIC_PHRASE, f"{stem.stem_type.value} phrase"
                ))

        log.info("Auto-slicer produced %d samples", len(samples))
        return samples

    # ---- Drums ---------------------------------------------------------

    def _slice_drums(self, stem: Stem, analysis: AnalysisResult, bpm: float) -> list[Sample]:
        out: list[Sample] = []
        # 1) Drum hits from transients
        hit_len = int(self.cfg.drum_hit_length_ms / 1000 * stem.sample_rate)
        # Sort transients by strength, take strongest, keep chronological order
        strongest = sorted(analysis.transients,
                           key=lambda t: t.strength, reverse=True)[:self.cfg.max_drum_hits]
        strongest = sorted(strongest, key=lambda t: t.position)

        # Fallback: if zero transients (e.g. very synthetic source), slice on beats
        if not strongest and analysis.beats:
            beat_positions = [b.position for b in analysis.beats[:self.cfg.max_drum_hits]]
            strongest = [Transient(position=p, strength=0.5) for p in beat_positions]

        for i, t in enumerate(strongest):
            end = min(t.position + hit_len, stem.duration_samples)
            if end - t.position < int(0.02 * stem.sample_rate):  # < 20ms, skip
                continue
            out.append(self._mk_sample(
                stem, t.position, end,
                name=f"Drum hit {i+1:02d}",
                category=SampleCategory.DRUM_HIT,
            ))

        # 2) Drum loops aligned to bars
        beats = [b.position for b in analysis.beats]
        for i, (s, e) in enumerate(self._bar_windows(beats, self.cfg.drum_loop_bars)):
            if i >= 4:
                break
            if e - s < int(0.1 * stem.sample_rate):  # too short
                continue
            out.append(self._mk_sample(
                stem, s, min(e, stem.duration_samples),
                name=f"Drum loop {i+1}",
                category=SampleCategory.DRUM_LOOP,
                bpm=bpm,
            ))
        return out

    # ---- Vocals --------------------------------------------------------

    def _slice_vocals(self, stem: Stem, analysis: AnalysisResult,
                      beats: list[int], bpm: float) -> list[Sample]:
        out: list[Sample] = []
        # Detect silence-gated transients in the vocal stem itself
        chop_positions = self._vocal_onsets(stem)
        chop_len = int(self.cfg.vocal_chop_length_ms / 1000 * stem.sample_rate)
        for i, p in enumerate(chop_positions[:16]):
            end = min(p + chop_len, stem.duration_samples)
            out.append(self._mk_sample(
                stem, p, end,
                name=f"Vocal chop {i+1:02d}",
                category=SampleCategory.VOCAL_CHOP,
            ))

        # Long vocal phrases aligned to bars (good for chorus loops)
        for i, (s, e) in enumerate(self._bar_windows(beats, self.cfg.vocal_phrase_bars)):
            if i >= 4:
                break
            out.append(self._mk_sample(
                stem, s, min(e, stem.duration_samples),
                name=f"Vocal phrase {i+1}",
                category=SampleCategory.VOCAL_PHRASE,
                bpm=bpm,
            ))
        return out

    def _vocal_onsets(self, stem: Stem) -> list[int]:
        """Detect onsets in vocal stem with energy gate (skip silent segments)."""
        try:
            import librosa
            y, sr = librosa.load(str(stem.path), sr=None, mono=True)
            rms = librosa.feature.rms(y=y, hop_length=512)[0]
            gate = rms.mean() * 0.6
            onset_frames = librosa.onset.onset_detect(
                y=y, sr=sr, hop_length=512, backtrack=True, units="frames"
            )
            keep = [f for f in onset_frames
                    if f < len(rms) and rms[f] > gate]
            return list(librosa.frames_to_samples(keep, hop_length=512))
        except Exception as e:
            log.warning("Vocal onset detection failed: %s", e)
            return []

    # ---- Generic bar-aligned loops ------------------------------------

    def _slice_loops(self, stem: Stem, beats: list[int], bars: int,
                     category: SampleCategory, name_prefix: str) -> list[Sample]:
        out: list[Sample] = []
        for i, (s, e) in enumerate(self._bar_windows(beats, bars)):
            if i >= 4:
                break
            out.append(self._mk_sample(
                stem, s, min(e, stem.duration_samples),
                name=f"{name_prefix} {i+1}",
                category=category,
            ))
        return out

    # ---- Helpers -------------------------------------------------------

    def _bar_windows(self, beats: list[int], bars: int,
                     beats_per_bar: int = 4) -> Iterable[tuple[int, int]]:
        """Yield (start, end) sample windows of `bars` bars, aligned to beats.

        If we don't have enough beats for a full bar, fall back to time-based
        windows using whatever beats we do have, so short tracks still produce
        at least one loop.
        """
        step = beats_per_bar * bars
        if len(beats) > step:
            for i in range(0, len(beats) - step, step):
                yield beats[i], beats[i + step]
            return
        # Fallback: use any window we can build
        if len(beats) >= 2:
            yield beats[0], beats[-1]

    def _mk_sample(self, stem: Stem, start: int, end: int,
                   name: str, category: SampleCategory,
                   bpm: float | None = None) -> Sample:
        return Sample(
            name=name,
            category=category,
            source_stem_id=stem.id,
            start_sample=int(start),
            end_sample=int(end),
            fade_in_samples=self.cfg.default_fade_in_samples,
            fade_out_samples=self.cfg.default_fade_out_samples,
            bpm=bpm,
        )
