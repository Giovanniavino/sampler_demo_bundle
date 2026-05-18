"""
AppSettings — all user-configurable parameters.

New in this version:
  - QualityMode: 'fast' or 'quality', chosen once at first launch
  - Preset-based slicing config (Short/Medium/Long/Custom etc.)
  - Noise reduction settings per mode
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

log = logging.getLogger(__name__)

QualityMode = Literal["fast", "quality"]

# ---------------------------------------------------------------------------
# Preset definitions — human-readable names map to technical values
# ---------------------------------------------------------------------------

VOCAL_PRESETS = {
    "Short":  dict(min_vocal_phrase_ms=800,  max_vocal_phrase_ms=5000,  vocal_phrase_min_gap_ms=300),
    "Medium": dict(min_vocal_phrase_ms=1500, max_vocal_phrase_ms=10000, vocal_phrase_min_gap_ms=600),
    "Long":   dict(min_vocal_phrase_ms=3000, max_vocal_phrase_ms=15000, vocal_phrase_min_gap_ms=900),
    "Custom": None,   # values taken directly from slicing settings
}

DRUM_PRESETS = {
    "Punchy":   dict(drum_hit_length_ms=200, max_drum_hits=12, drum_hit_min_spacing_beats=0.5),
    "Standard": dict(drum_hit_length_ms=400, max_drum_hits=16, drum_hit_min_spacing_beats=1.0),
    "Full":     dict(drum_hit_length_ms=700, max_drum_hits=20, drum_hit_min_spacing_beats=2.0),
    "Custom":   None,
}

LOOP_PRESETS = {
    "Tight":    dict(n_loops_per_stem=3, drum_loop_bars=1, bass_loop_bars=1, melody_phrase_bars=2),
    "Standard": dict(n_loops_per_stem=4, drum_loop_bars=2, bass_loop_bars=2, melody_phrase_bars=4),
    "Spacious": dict(n_loops_per_stem=4, drum_loop_bars=4, bass_loop_bars=4, melody_phrase_bars=8),
    "Custom":   None,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SlicingSettings:
    # Preset names (drive the UI; Custom = manual values below)
    vocal_preset: str = "Medium"
    drum_preset:  str = "Standard"
    loop_preset:  str = "Standard"

    # Vocal phrases
    min_vocal_phrase_ms:     float = 1500.0
    max_vocal_phrase_ms:     float = 10000.0
    vocal_phrase_min_gap_ms: float = 600.0
    max_vocal_phrases:       int   = 6
    # Vocal chops
    vocal_chop_length_ms: int = 1200
    max_vocal_chops:      int = 6
    # Drum hits
    drum_hit_length_ms:          int   = 400
    max_drum_hits:               int   = 16
    drum_hit_min_spacing_beats:  float = 1.0
    # Loops
    n_loops_per_stem:    int = 4
    drum_loop_bars:      int = 2
    bass_loop_bars:      int = 2
    melody_phrase_bars:  int = 4

    def apply_vocal_preset(self, name: str):
        if name == "Custom" or name not in VOCAL_PRESETS:
            self.vocal_preset = "Custom"
            return
        self.vocal_preset = name
        for k, v in VOCAL_PRESETS[name].items():
            setattr(self, k, v)

    def apply_drum_preset(self, name: str):
        if name == "Custom" or name not in DRUM_PRESETS:
            self.drum_preset = "Custom"
            return
        self.drum_preset = name
        for k, v in DRUM_PRESETS[name].items():
            setattr(self, k, v)

    def apply_loop_preset(self, name: str):
        if name == "Custom" or name not in LOOP_PRESETS:
            self.loop_preset = "Custom"
            return
        self.loop_preset = name
        for k, v in LOOP_PRESETS[name].items():
            setattr(self, k, v)


@dataclass
class PadLayoutSettings:
    pads_drum_hit:    int = 4
    pads_drum_loop:   int = 2
    pads_vocal_chop:  int = 3
    pads_vocal_phrase: int = 1
    pads_melody:      int = 3
    pads_bass_loop:   int = 3
    grid_size:        int = 16

    def row_config(self):
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
    sample_rate:          int  = 44100
    block_size:           int  = 512
    press_hold_loop:      bool = False    # was True — turn off the bug magnet
    auto_choke_drums:     bool = True
    auto_normalize_stems: bool = False
    # Noise reduction levels per stage: 'off' / 'light' / 'strong'
    # Default light pre + off post — strong NR was killing the audio
    nr_level_pre:  str = "light"
    nr_level_post: str = "off"

    @property
    def latency_ms(self) -> float:
        return round(self.block_size / self.sample_rate * 1000, 1)


@dataclass
class AppSettings:
    # None = not yet chosen → triggers first-launch dialog
    quality_mode: Optional[QualityMode] = None

    slicing:    SlicingSettings    = field(default_factory=SlicingSettings)
    pad_layout: PadLayoutSettings  = field(default_factory=PadLayoutSettings)
    playback:   PlaybackSettings   = field(default_factory=PlaybackSettings)

    # ---- Derived helpers ----------------------------------------------

    @property
    def demucs_model(self) -> str:
        return "htdemucs" if self.quality_mode == "fast" else "htdemucs_ft"

    # ---- Noise reduction (now user-controllable) -----------------------
    # The playback settings hold the user-chosen NR level. The pipeline
    # reads these properties to decide what to do.

    @property
    def noise_reduction_pre(self) -> bool:
        """Apply NR before separation if level is not 'off'."""
        return self.playback.nr_level_pre != "off"

    @property
    def noise_reduction_post(self) -> bool:
        """Apply NR after separation (per-stem) if level is not 'off'."""
        return self.playback.nr_level_post != "off"

    @property
    def nr_pre_profile(self) -> str:
        return self.playback.nr_level_pre

    @property
    def nr_post_profile(self) -> str:
        return self.playback.nr_level_post

    # ---- Persistence --------------------------------------------------

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "AppSettings":
        if not path.exists():
            return cls()
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            return cls(
                quality_mode=raw.get("quality_mode"),
                slicing=SlicingSettings(**raw.get("slicing", {})),
                pad_layout=PadLayoutSettings(**raw.get("pad_layout", {})),
                playback=PlaybackSettings(**raw.get("playback", {})),
            )
        except Exception as e:
            log.warning("Failed to load settings (%s), using defaults", e)
            return cls()

    def to_slicer_config(self):
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
