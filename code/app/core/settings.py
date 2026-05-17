"""
AppSettings — all user-configurable parameters in one place.

The GUI settings panel reads/writes this object. The pipeline and engine
read it at run-time. Persisted to data/settings.json.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class SlicingSettings:
    # --- Vocal phrases ---
    min_vocal_phrase_ms: float = 1500.0
    max_vocal_phrase_ms: float = 12000.0
    vocal_phrase_min_gap_ms: float = 700.0
    max_vocal_phrases: int = 6
    # --- Vocal chops ---
    vocal_chop_length_ms: int = 1200
    max_vocal_chops: int = 6
    # --- Drum hits ---
    drum_hit_length_ms: int = 400
    max_drum_hits: int = 16
    drum_hit_min_spacing_beats: float = 1.0
    # --- Loops ---
    n_loops_per_stem: int = 4
    drum_loop_bars: int = 2
    bass_loop_bars: int = 2
    melody_phrase_bars: int = 4


@dataclass
class PadLayoutSettings:
    # How many pads each category gets. Total must fit inside grid_size.
    pads_drum_hit: int = 4
    pads_drum_loop: int = 2
    pads_vocal_chop: int = 3
    pads_vocal_phrase: int = 1
    pads_melody: int = 3
    pads_bass_loop: int = 3
    grid_size: int = 16       # total pad count; changing this resizes the grid

    def row_config(self) -> list[tuple[int, list, str]]:
        """
        Build the layout as (count, [categories], default_mode_value) triples,
        in display order. Called by PadAssigner.
        """
        from app.core.models import PadMode, SampleCategory
        rows = []
        if self.pads_drum_hit > 0:
            rows.append((self.pads_drum_hit,
                         [SampleCategory.DRUM_HIT], PadMode.ONE_SHOT))
        if self.pads_vocal_chop + self.pads_vocal_phrase > 0:
            rows.append((self.pads_vocal_chop + self.pads_vocal_phrase,
                         [SampleCategory.VOCAL_CHOP,
                          SampleCategory.VOCAL_PHRASE], PadMode.ONE_SHOT))
        if self.pads_melody > 0:
            rows.append((self.pads_melody,
                         [SampleCategory.MELODIC_PHRASE], PadMode.LOOP))
        if self.pads_bass_loop + self.pads_drum_loop > 0:
            rows.append((self.pads_bass_loop + self.pads_drum_loop,
                         [SampleCategory.BASS_LOOP,
                          SampleCategory.DRUM_LOOP], PadMode.LOOP))
        return rows


@dataclass
class PlaybackSettings:
    sample_rate: int = 44100       # 44100 | 48000
    block_size: int = 512          # 128 | 256 | 512 | 1024
    # Press-and-hold loop: if the pad is still held when the sample ends,
    # it loops automatically until released.
    press_hold_loop: bool = True
    # Choke group auto-assign for drum hits
    auto_choke_drums: bool = True
    # Normalize each stem to -6 dBFS before slicing
    auto_normalize_stems: bool = False

    @property
    def latency_ms(self) -> float:
        return round(self.block_size / self.sample_rate * 1000, 1)


@dataclass
class AppSettings:
    slicing: SlicingSettings = field(default_factory=SlicingSettings)
    pad_layout: PadLayoutSettings = field(default_factory=PadLayoutSettings)
    playback: PlaybackSettings = field(default_factory=PlaybackSettings)

    # ---- Persistence --------------------------------------------------

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
        log.info("Settings saved to %s", path)

    @classmethod
    def load(cls, path: Path) -> "AppSettings":
        if not path.exists():
            return cls()
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            return cls(
                slicing=SlicingSettings(**raw.get("slicing", {})),
                pad_layout=PadLayoutSettings(**raw.get("pad_layout", {})),
                playback=PlaybackSettings(**raw.get("playback", {})),
            )
        except Exception as e:
            log.warning("Failed to load settings (%s), using defaults", e)
            return cls()

    def to_slicer_config(self):
        """Convert to the SlicerConfig used by AutoSlicer."""
        from app.audio.slicing.auto_slicer import SlicerConfig
        s = self.slicing
        return SlicerConfig(
            max_drum_hits=s.max_drum_hits,
            drum_hit_length_ms=s.drum_hit_length_ms,
            drum_hit_min_spacing_beats=s.drum_hit_min_spacing_beats,
            n_loops_per_stem=s.n_loops_per_stem,
            drum_loop_bars=s.drum_loop_bars,
            bass_loop_bars=s.bass_loop_bars,
            melody_phrase_bars=s.melody_phrase_bars,
            max_vocal_phrases=s.max_vocal_phrases,
            min_vocal_phrase_ms=s.min_vocal_phrase_ms,
            max_vocal_phrase_ms=s.max_vocal_phrase_ms,
            vocal_phrase_min_gap_ms=s.vocal_phrase_min_gap_ms,
            vocal_chop_length_ms=s.vocal_chop_length_ms,
            max_vocal_chops=s.max_vocal_chops,
        )
