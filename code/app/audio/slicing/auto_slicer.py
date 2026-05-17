"""
Auto sample generation.

Given stems + analysis, produce a set of Sample records:
  - DRUMS  -> drum hits distributed across the song + bar-aligned drum loops
  - VOCALS -> vocal chops distributed + bar-aligned vocal phrases
  - BASS   -> bass loops from different parts of the song
  - OTHER  -> melodic phrases from different parts of the song

Everything is non-destructive: samples reference stems by id + start/end.

Boundary refinement:
  - Slice start/end are snapped to the nearest zero crossing within a small
    window (~10ms). This kills clicks at trigger and at end-of-buffer.
  - For drum HITS we don't snap the start (we want the attack), only the end.
  - For LOOPS we snap both ends so wrap-around is click-free.

Distribution strategy (NEW):
  - For LOOPS, we don't take the first N bar-windows. Instead, we sample
    N windows distributed across the entire song (e.g. for N=4: at 10%, 35%,
    60%, 85% of the song's duration). This gives variety even on long tracks.
  - For DRUM HITS, after picking the strongest transients, we additionally
    enforce a minimum spacing so hits aren't clustered in one section.
  - For VOCAL CHOPS, same as drum hits: enforce spacing across the track.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np

from app.audio.dsp.zero_crossing import find_zero_crossing
from app.core.models import (
    AnalysisResult, Sample, SampleCategory, Stem, StemType, Transient,
)

log = logging.getLogger(__name__)


@dataclass
class SlicerConfig:
    # Drum hits
    max_drum_hits: int = 16              # cap per stem
    drum_hit_length_ms: int = 400
    # Min spacing between drum hits, in BEATS. 1.0 = at least 1 beat apart.
    # Prevents grabbing 32 nearly-identical kicks from a 4-on-floor section.
    drum_hit_min_spacing_beats: float = 1.0

    # Loops
    n_loops_per_stem: int = 4            # how many loop variations per stem
    drum_loop_bars: int = 2
    bass_loop_bars: int = 2
    melody_phrase_bars: int = 4
    vocal_phrase_bars: int = 4
    vocal_chop_length_ms: int = 1500
    max_vocal_chops: int = 8
    vocal_chop_min_spacing_beats: float = 2.0

    # Sample shape
    default_fade_in_samples: int = 64
    default_fade_out_samples: int = 256
    zc_window_ms: float = 10.0


class AutoSlicer:
    def __init__(self, config: SlicerConfig | None = None):
        self.cfg = config or SlicerConfig()

    # ---- Entry ---------------------------------------------------------

    def slice_all(self, stems: list[Stem], analysis: AnalysisResult) -> list[Sample]:
        samples: list[Sample] = []
        beats_pos = [b.position for b in analysis.beats]
        bpm = analysis.bpm or 120.0

        # Average samples-per-beat across the track (more robust than 60/BPM)
        samples_per_beat = self._samples_per_beat(beats_pos, bpm,
                                                   stems[0].sample_rate if stems else 44100)

        for stem in stems:
            audio = self._load_stem_audio(stem)
            zc_window = self._zc_window_samples(stem.sample_rate)

            if stem.stem_type == StemType.DRUMS:
                samples.extend(self._slice_drums(
                    stem, analysis, bpm, audio, zc_window, samples_per_beat))
            elif stem.stem_type == StemType.VOCALS:
                samples.extend(self._slice_vocals(
                    stem, analysis, beats_pos, bpm, audio, zc_window, samples_per_beat))
            elif stem.stem_type == StemType.BASS:
                samples.extend(self._slice_distributed_loops(
                    stem, beats_pos, self.cfg.bass_loop_bars,
                    SampleCategory.BASS_LOOP, "Bass loop",
                    audio, zc_window, bpm,
                ))
            elif stem.stem_type in (StemType.OTHER, StemType.PIANO, StemType.GUITAR):
                samples.extend(self._slice_distributed_loops(
                    stem, beats_pos, self.cfg.melody_phrase_bars,
                    SampleCategory.MELODIC_PHRASE, f"{stem.stem_type.value} phrase",
                    audio, zc_window, bpm,
                ))

        log.info("Auto-slicer produced %d samples", len(samples))
        return samples

    # ---- Drums ---------------------------------------------------------

    def _slice_drums(self, stem: Stem, analysis: AnalysisResult, bpm: float,
                     audio: Optional[np.ndarray], zc_window: int,
                     samples_per_beat: int) -> list[Sample]:
        out: list[Sample] = []
        hit_len = int(self.cfg.drum_hit_length_ms / 1000 * stem.sample_rate)

        # 1) Drum hits — distributed across the track with min-spacing.
        # Strategy: take all transients above a strength threshold, then greedily
        # pick the strongest while enforcing min spacing in samples.
        min_spacing = int(self.cfg.drum_hit_min_spacing_beats * samples_per_beat)
        picked = self._pick_spaced_transients(
            analysis.transients, max_n=self.cfg.max_drum_hits, min_spacing=min_spacing,
        )
        # Sort chronologically for nicer pad layout
        picked.sort(key=lambda t: t.position)
        for i, t in enumerate(picked):
            start = t.position
            end = min(t.position + hit_len, stem.duration_samples)
            end = self._snap(audio, end, zc_window, "nearest")
            out.append(self._mk_sample(
                stem, start, end,
                name=f"Drum hit {i+1:02d}",
                category=SampleCategory.DRUM_HIT,
            ))

        # 2) Drum loops — distributed across the song
        out.extend(self._slice_distributed_loops(
            stem, [b.position for b in analysis.beats], self.cfg.drum_loop_bars,
            SampleCategory.DRUM_LOOP, "Drum loop",
            audio, zc_window, bpm,
        ))
        return out

    # ---- Vocals --------------------------------------------------------

    def _slice_vocals(self, stem: Stem, analysis: AnalysisResult,
                      beats: list[int], bpm: float,
                      audio: Optional[np.ndarray], zc_window: int,
                      samples_per_beat: int) -> list[Sample]:
        out: list[Sample] = []

        # Vocal chops: distributed across the track
        chop_positions = self._vocal_onsets(stem)
        chop_len = int(self.cfg.vocal_chop_length_ms / 1000 * stem.sample_rate)
        min_spacing = int(self.cfg.vocal_chop_min_spacing_beats * samples_per_beat)
        # Convert positions to Transient-like objects for the spacer
        pseudo_transients = [Transient(position=p, strength=1.0) for p in chop_positions]
        picked = self._pick_spaced_transients(
            pseudo_transients, max_n=self.cfg.max_vocal_chops, min_spacing=min_spacing,
        )
        picked.sort(key=lambda t: t.position)
        for i, t in enumerate(picked):
            start = self._snap(audio, t.position, zc_window, "backward")
            end = min(t.position + chop_len, stem.duration_samples)
            end = self._snap(audio, end, zc_window, "nearest")
            out.append(self._mk_sample(
                stem, start, end,
                name=f"Vocal chop {i+1:02d}",
                category=SampleCategory.VOCAL_CHOP,
            ))

        # Vocal phrases: distributed loops
        out.extend(self._slice_distributed_loops(
            stem, beats, self.cfg.vocal_phrase_bars,
            SampleCategory.VOCAL_PHRASE, "Vocal phrase",
            audio, zc_window, bpm,
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

    # ---- Distributed bar-aligned loops --------------------------------

    def _slice_distributed_loops(
        self, stem: Stem, beats: list[int], bars: int,
        category: SampleCategory, name_prefix: str,
        audio: Optional[np.ndarray], zc_window: int, bpm: float,
    ) -> list[Sample]:
        """
        Produce N loop variations DISTRIBUTED across the track.

        Strategy: build all possible non-overlapping bar-aligned windows of the
        requested length, then pick N of them spaced evenly through the list.
        This guarantees variety: with N=4 on a 100-bar song, we get loops from
        roughly the beginning, ~1/3, ~2/3, and near the end.
        """
        n_target = self.cfg.n_loops_per_stem
        windows = list(self._bar_windows(beats, bars))
        if not windows:
            return []

        # Filter out windows beyond stem duration (defensive)
        windows = [(s, e) for s, e in windows if e <= stem.duration_samples]
        if not windows:
            return []

        # Pick N windows evenly distributed across the list of available windows
        n = min(n_target, len(windows))
        if n == 1:
            indices = [0]
        else:
            # np.linspace gives evenly-spaced positions; cast to int and dedupe
            raw = np.linspace(0, len(windows) - 1, n)
            indices = sorted(set(int(round(x)) for x in raw))

        out: list[Sample] = []
        for i, idx in enumerate(indices):
            s, e = windows[idx]
            s_snap = self._snap(audio, s, zc_window, "nearest")
            e_snap = self._snap(audio, min(e, stem.duration_samples),
                                 zc_window, "nearest")
            # Annotate position in track for transparency
            pos_pct = int(100 * s / max(1, stem.duration_samples))
            out.append(self._mk_sample(
                stem, s_snap, e_snap,
                name=f"{name_prefix} {i+1} ({pos_pct}%)",
                category=category,
                bpm=bpm,
            ))
        return out

    # ---- Transient selection with spacing -----------------------------

    def _pick_spaced_transients(
        self, transients: list[Transient], max_n: int, min_spacing: int,
    ) -> list[Transient]:
        """
        Greedy selection: take strongest transients but skip any that fall
        within `min_spacing` samples of an already-picked one.

        This avoids the failure mode where 32 "drum hits" are all from a
        single chorus section because that's where the strongest hits are.
        """
        if not transients:
            return []
        # Sort by strength descending
        candidates = sorted(transients, key=lambda t: t.strength, reverse=True)
        picked: list[Transient] = []
        picked_positions: list[int] = []  # kept sorted for fast bisect

        import bisect
        for t in candidates:
            if len(picked) >= max_n:
                break
            # Check distance to nearest already-picked
            pos = t.position
            i = bisect.bisect_left(picked_positions, pos)
            too_close = False
            if i > 0 and pos - picked_positions[i - 1] < min_spacing:
                too_close = True
            if (not too_close and i < len(picked_positions)
                    and picked_positions[i] - pos < min_spacing):
                too_close = True
            if too_close:
                continue
            picked.append(t)
            bisect.insort(picked_positions, pos)
        return picked

    # ---- Helpers -------------------------------------------------------

    def _samples_per_beat(self, beats: list[int], bpm: float, sr: int) -> int:
        """Compute samples-per-beat from actual beat positions if possible."""
        if len(beats) >= 2:
            diffs = np.diff(beats)
            # Use median to be robust against outliers
            return int(np.median(diffs))
        return int(sr * 60 / max(1.0, bpm))

    def _bar_windows(self, beats: list[int], bars: int,
                     beats_per_bar: int = 4) -> Iterable[tuple[int, int]]:
        """Yield non-overlapping (start, end) sample windows of `bars` bars."""
        step = beats_per_bar * bars
        for i in range(0, len(beats) - step, step):
            yield beats[i], beats[i + step]

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

    def _zc_window_samples(self, sr: int) -> int:
        return max(1, int(self.cfg.zc_window_ms / 1000 * sr))

    def _snap(self, audio: Optional[np.ndarray], pos: int,
              window: int, direction: str) -> int:
        if audio is None or len(audio) == 0:
            return pos
        return find_zero_crossing(audio, pos, window_samples=window, direction=direction)

    def _load_stem_audio(self, stem: Stem) -> Optional[np.ndarray]:
        """Load stem as mono float32 for ZC analysis. Returns None on failure."""
        if not stem.path:
            return None
        try:
            import soundfile as sf
            data, _ = sf.read(str(stem.path), dtype="float32", always_2d=True)
            return data.mean(axis=1) if data.ndim == 2 else data
        except Exception as e:
            log.warning("Could not load stem %s for ZC snapping: %s", stem.path, e)
            return None