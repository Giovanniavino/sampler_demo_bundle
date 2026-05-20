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

from app.audio.slicing.sample_quality import (
    QualityConfig, filter_samples,
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
    # Quantize drum hits to the nearest 16th-note grid if within this many ms.
    # 0 disables quantize. 30ms is the MPC default — tight but keeps groove.
    drum_quantize_tolerance_ms: float = 30.0

    # Loops
    n_loops_per_stem: int = 4            # how many loop variations per stem
    drum_loop_bars: int = 2
    bass_loop_bars: int = 2
    melody_phrase_bars: int = 4

    # Vocal phrases — natural-length, detected by silence-gating
    max_vocal_phrases: int = 6           # cap full-phrase samples
    min_vocal_phrase_ms: float = 1500.0  # ignore anything shorter than this
    max_vocal_phrase_ms: float = 12000.0 # cap phrase length
    # Pauses inside a phrase shorter than this don't split it.
    # Higher = longer, more musical phrases (good for full vocal lines)
    # Lower  = more atomic phrases (good for chops)
    vocal_phrase_min_gap_ms: float = 700.0

    # Vocal chops — short percussive cuts from the START of each phrase
    vocal_chop_length_ms: int = 1200
    max_vocal_chops: int = 6

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

        log.info("Auto-slicer produced %d raw samples", len(samples))

        # Quality pass: drop silent/empty samples, trim dead air, flag
        # quiet samples for normalization. Big boost to perceived quality.
        samples = self._apply_quality_filter(samples, stems)

        log.info("Auto-slicer final: %d samples after quality filter",
                 len(samples))
        return samples

    def _apply_quality_filter(self, samples: list[Sample],
                              stems: list[Stem]) -> list[Sample]:
        """Reject silent samples and trim/normalize the survivors."""
        # Build a cache of mono stem audio + sample rates
        stem_by_id = {s.id: s for s in stems}
        audio_cache: dict[str, Optional[np.ndarray]] = {}

        def load_audio(stem_id: str):
            if stem_id not in audio_cache:
                stem = stem_by_id.get(stem_id)
                audio_cache[stem_id] = (
                    self._load_stem_audio(stem) if stem else None
                )
            return audio_cache[stem_id]

        def get_sr(stem_id: str) -> int:
            stem = stem_by_id.get(stem_id)
            return stem.sample_rate if stem else 44100

        # Drum hits get attack-preserving treatment (don't trim the start)
        drum_cats = {SampleCategory.DRUM_HIT}

        kept, rejected = filter_samples(
            samples,
            stem_audio_loader=load_audio,
            sample_rate_getter=get_sr,
            cfg=QualityConfig(),
            drum_categories=drum_cats,
        )
        return kept

    # ---- Drums ---------------------------------------------------------

    def _slice_drums(self, stem: Stem, analysis: AnalysisResult, bpm: float,
                     audio: Optional[np.ndarray], zc_window: int,
                     samples_per_beat: int) -> list[Sample]:
        out: list[Sample] = []
        hit_len = int(self.cfg.drum_hit_length_ms / 1000 * stem.sample_rate)

        # 1) Drum hits — distributed across the track with min-spacing.
        min_spacing = int(self.cfg.drum_hit_min_spacing_beats * samples_per_beat)
        picked = self._pick_spaced_transients(
            analysis.transients, max_n=self.cfg.max_drum_hits, min_spacing=min_spacing,
        )
        picked.sort(key=lambda t: t.position)

        # Build 16th-note grid for quantization
        sixteenth_grid = self._build_sixteenth_grid(
            [b.position for b in analysis.beats]
        )
        tolerance = int(self.cfg.drum_quantize_tolerance_ms
                         / 1000 * stem.sample_rate)

        for i, t in enumerate(picked):
            # Quantize start to nearest 16th IF within tolerance,
            # otherwise leave the transient where librosa found it
            start = self._quantize_to_grid(t.position, sixteenth_grid, tolerance)
            end = min(start + hit_len, stem.duration_samples)
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

    # ---- 16th-note grid + quantize ------------------------------------

    def _build_sixteenth_grid(self, beats: list[int]) -> list[int]:
        """4 grid points per beat (16th notes). Linear interpolation."""
        if len(beats) < 2:
            return list(beats)
        grid = []
        for i in range(len(beats) - 1):
            b0, b1 = beats[i], beats[i + 1]
            step = (b1 - b0) / 4
            for k in range(4):
                grid.append(int(b0 + step * k))
        grid.append(beats[-1])
        return grid

    def _quantize_to_grid(self, position: int, grid: list[int],
                          tolerance: int) -> int:
        """Snap to nearest grid point if within tolerance; else unchanged."""
        if not grid or tolerance <= 0:
            return position
        import bisect
        i = bisect.bisect_left(grid, position)
        candidates = []
        if i > 0:          candidates.append(grid[i - 1])
        if i < len(grid):  candidates.append(grid[i])
        if not candidates:
            return position
        nearest = min(candidates, key=lambda x: abs(x - position))
        return nearest if abs(nearest - position) <= tolerance else position

    # ---- Vocals --------------------------------------------------------

    def _slice_vocals(self, stem: Stem, analysis: AnalysisResult,
                      beats: list[int], bpm: float,
                      audio: Optional[np.ndarray], zc_window: int,
                      samples_per_beat: int) -> list[Sample]:
        """
        Vocal slicing strategy (NEW):

        1. Take the song's SECTIONS (verse, chorus, bridge from section_detector).
        2. For each section, check if the vocal stem has energy in it.
           - If yes → make a sample for the entire section, named like
             "Vocal phrase - Chorus 1", "Vocal phrase - Verse 2", etc.
           - If no  → skip (instrumental section)
        3. Split very long sections (>max_vocal_phrase_ms) into halves so a
           4-bar pad doesn't have a 30-second chorus on it.
        4. Snap start/end to beat boundaries so phrases start on a downbeat.
        5. Vocal chops are still cut from the start of each section that
           contains vocals.
        """
        out: list[Sample] = []
        if stem.path is None or not analysis.sections:
            # Fall back to old phrase detection if no sections
            return self._slice_vocals_legacy(stem, analysis, beats, bpm,
                                               audio, zc_window, samples_per_beat)

        # Load vocal stem audio for energy detection
        vocal_audio = self._load_stem_audio(stem)
        if vocal_audio is None:
            return self._slice_vocals_legacy(stem, analysis, beats, bpm,
                                               audio, zc_window, samples_per_beat)

        max_len_samples = int(self.cfg.max_vocal_phrase_ms / 1000 * stem.sample_rate)
        min_len_samples = int(self.cfg.min_vocal_phrase_ms / 1000 * stem.sample_rate)

        # Count occurrences of each label for naming (Verse 1, Verse 2, ...)
        from collections import defaultdict
        counters: dict[str, int] = defaultdict(int)

        all_phrases: list[tuple[int, int, str]] = []   # (start, end, label_name)

        for section in analysis.sections:
            label = section.label.value
            if label in ("intro", "outro", "unknown", "break"):
                # These rarely have full vocal phrases worth sampling
                continue

            # Check vocal energy in this section
            sec_start = max(0, min(section.start, len(vocal_audio)))
            sec_end   = max(0, min(section.end,   len(vocal_audio)))
            if sec_end - sec_start < min_len_samples:
                continue
            seg = vocal_audio[sec_start:sec_end]
            rms = float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0
            if rms < 0.005:  # essentially silent vocal section
                continue

            # Split long sections in halves (or thirds for huge ones)
            length = sec_end - sec_start
            if length <= max_len_samples:
                parts = [(sec_start, sec_end)]
            else:
                n_parts = int(np.ceil(length / max_len_samples))
                step = length // n_parts
                # Snap each split point to the nearest beat for musicality
                parts = []
                for i in range(n_parts):
                    p_start = sec_start + i * step
                    p_end = sec_start + (i + 1) * step if i < n_parts - 1 else sec_end
                    p_start = self._snap_to_nearest_beat(p_start, beats)
                    p_end   = self._snap_to_nearest_beat(p_end, beats)
                    if p_end > p_start:
                        parts.append((p_start, p_end))

            for part_idx, (p_start, p_end) in enumerate(parts):
                counters[label] += 1
                num = counters[label]
                part_suffix = f" pt{part_idx + 1}" if len(parts) > 1 else ""
                name = f"{label.title()} {num}{part_suffix}"
                all_phrases.append((p_start, p_end, name))

        # Cap to max_vocal_phrases (most musically interesting sections first:
        # chorus > verse > bridge — so keep ordering by label priority)
        priority = {"chorus": 0, "verse": 1, "bridge": 2}
        all_phrases.sort(key=lambda p: (priority.get(p[2].split()[0].lower(), 3), p[0]))
        all_phrases = all_phrases[: self.cfg.max_vocal_phrases]
        # Re-sort chronologically for nicer pad layout
        all_phrases.sort(key=lambda p: p[0])

        for start, end, name in all_phrases:
            s_snap = self._snap(audio, start, zc_window, "backward")
            e_snap = self._snap(audio, end, zc_window, "nearest")
            out.append(self._mk_sample(
                stem, s_snap, e_snap,
                name=name,
                category=SampleCategory.VOCAL_PHRASE,
                bpm=bpm,
            ))

        # Vocal chops: short cuts from the START of each phrase
        chop_len = int(self.cfg.vocal_chop_length_ms / 1000 * stem.sample_rate)
        n_chops = min(self.cfg.max_vocal_chops, len(all_phrases))
        if n_chops > 0:
            if n_chops == 1:
                chop_indices = [0]
            else:
                raw = np.linspace(0, len(all_phrases) - 1, n_chops)
                chop_indices = sorted(set(int(round(x)) for x in raw))
            for i, idx in enumerate(chop_indices):
                p_start, p_end, name = all_phrases[idx]
                chop_end = min(p_start + chop_len, p_end, stem.duration_samples)
                if chop_end <= p_start:
                    continue
                s_snap = self._snap(audio, p_start, zc_window, "backward")
                e_snap = self._snap(audio, chop_end, zc_window, "nearest")
                short_name = name.replace("Verse", "V.").replace("Chorus", "C.") \
                                  .replace("Bridge", "B.")
                out.append(self._mk_sample(
                    stem, s_snap, e_snap,
                    name=f"Chop {short_name}",
                    category=SampleCategory.VOCAL_CHOP,
                ))

        if not out:
            log.info("Section-based vocal slicing produced nothing — "
                     "falling back to phrase detection")
            return self._slice_vocals_legacy(stem, analysis, beats, bpm,
                                               audio, zc_window, samples_per_beat)
        return out

    def _snap_to_nearest_beat(self, position: int, beats: list[int]) -> int:
        """Snap to the nearest beat position. Used for phrase boundaries."""
        if not beats:
            return position
        import bisect
        i = bisect.bisect_left(beats, position)
        candidates = []
        if i > 0:           candidates.append(beats[i - 1])
        if i < len(beats):  candidates.append(beats[i])
        if not candidates:
            return position
        return min(candidates, key=lambda b: abs(b - position))

    def _slice_vocals_legacy(self, stem: Stem, analysis: AnalysisResult,
                              beats: list[int], bpm: float,
                              audio: Optional[np.ndarray], zc_window: int,
                              samples_per_beat: int) -> list[Sample]:
        """Old phrase-detection-based vocal slicing — kept as fallback."""
        out: list[Sample] = []
        if stem.path is None:
            return out
        from code.app.audio.dsp.vocal_phrase import (
            PhraseDetectionConfig, detect_vocal_phrases,
        )
        phrase_cfg = PhraseDetectionConfig(
            max_phrases=self.cfg.max_vocal_phrases,
            min_phrase_ms=self.cfg.min_vocal_phrase_ms,
            max_phrase_ms=self.cfg.max_vocal_phrase_ms,
            min_gap_ms=self.cfg.vocal_phrase_min_gap_ms,
        )
        phrases = detect_vocal_phrases(stem.path, phrase_cfg)
        if not phrases:
            return out

        for i, (s, e) in enumerate(phrases):
            s_snap = self._snap(audio, s, zc_window, "backward")
            e_snap = self._snap(audio, e, zc_window, "nearest")
            out.append(self._mk_sample(
                stem, s_snap, e_snap,
                name=f"Vocal phrase {i+1}",
                category=SampleCategory.VOCAL_PHRASE,
                bpm=bpm,
            ))
        return out

    # ---- Phrase merging -----------------------------------------------

    def _merge_phrases_to_min_length(
        self, phrases: list[tuple[int, int]],
        min_len_samples: int, max_len_samples: int,
    ) -> list[tuple[int, int]]:
        """
        Merge adjacent phrases (including the silence between them) so that
        each result is at least min_len_samples long, without exceeding
        max_len_samples.

        We do a single forward pass: keep extending the current phrase by
        absorbing the next one until length >= min_len, then commit and start
        a new phrase from the next index.

        This is what makes "1.5 second minimum" work even on material that
        only has 0.7s natural phrases — we just stitch them together along
        with the natural gap, which sounds more musical than padding silence.
        """
        if not phrases:
            return []
        # Sort defensively
        phrases = sorted(phrases, key=lambda p: p[0])
        merged: list[tuple[int, int]] = []
        i = 0
        while i < len(phrases):
            s, e = phrases[i]
            j = i + 1
            while (e - s) < min_len_samples and j < len(phrases):
                next_s, next_e = phrases[j]
                # Don't merge if absorbing the next one would exceed the max
                if (next_e - s) > max_len_samples:
                    break
                e = next_e
                j += 1
            # Truncate if somehow still over max (shouldn't happen, but safe)
            if (e - s) > max_len_samples:
                e = s + max_len_samples
            merged.append((s, e))
            i = j
        return merged

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
