"""
Core domain models for the sampler.

These are pure data classes (no I/O, no audio processing). They define the
schema that flows between modules: separation -> analysis -> slicing -> pads.

Design notes:
- All audio offsets are in SAMPLES (int), not seconds. Sample-accurate.
  We carry sample_rate alongside so conversion to seconds is trivial.
- IDs are UUID4 strings, generated at creation. Stable across save/load.
- Models are frozen-ish: we use dataclasses with explicit setters only where
  mutation is meaningful (e.g. pad assignment).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StemType(str, Enum):
    """Stems produced by source separation. String values so JSON-friendly."""
    VOCALS = "vocals"
    DRUMS = "drums"
    BASS = "bass"
    OTHER = "other"          # melody / instruments bucket from 4-stem Demucs
    PIANO = "piano"          # only if a 6-stem model is used
    GUITAR = "guitar"


class SampleCategory(str, Enum):
    """High-level category used for pad coloring and auto-assignment."""
    DRUM_HIT = "drum_hit"
    DRUM_LOOP = "drum_loop"
    VOCAL_CHOP = "vocal_chop"
    VOCAL_PHRASE = "vocal_phrase"
    BASS_LOOP = "bass_loop"
    MELODIC_PHRASE = "melodic_phrase"
    FX = "fx"
    USER = "user"            # manually created by the user


class PadMode(str, Enum):
    ONE_SHOT = "one_shot"    # plays from start to end on trigger
    LOOP = "loop"            # loops until re-triggered or stopped
    HOLD = "hold"            # plays while pad held, stops on release
    GATE = "gate"            # like hold but with envelope


class SectionLabel(str, Enum):
    INTRO = "intro"
    VERSE = "verse"
    CHORUS = "chorus"
    BRIDGE = "bridge"
    OUTRO = "outro"
    BREAK = "break"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Audio source & stems
# ---------------------------------------------------------------------------

@dataclass
class AudioSource:
    """The original imported audio file."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    path: Optional[Path] = None
    sample_rate: int = 44100
    channels: int = 2
    duration_samples: int = 0

    @property
    def duration_seconds(self) -> float:
        return self.duration_samples / self.sample_rate if self.sample_rate else 0.0


@dataclass
class Stem:
    """A separated stem, stored as a wav file on disk."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str = ""
    stem_type: StemType = StemType.OTHER
    path: Optional[Path] = None
    sample_rate: int = 44100
    channels: int = 2
    duration_samples: int = 0


# ---------------------------------------------------------------------------
# Analysis results
# ---------------------------------------------------------------------------

@dataclass
class Beat:
    """A single beat marker. position in samples relative to source start."""
    position: int
    is_downbeat: bool = False
    confidence: float = 1.0


@dataclass
class Section:
    """A musical section (verse, chorus, ...)."""
    start: int          # samples
    end: int            # samples
    label: SectionLabel = SectionLabel.UNKNOWN
    confidence: float = 1.0


@dataclass
class Transient:
    """A detected onset / hit, mostly on drum stems."""
    position: int       # samples
    strength: float = 1.0


@dataclass
class AnalysisResult:
    """Aggregated analysis for one AudioSource."""
    source_id: str
    bpm: float = 0.0
    bpm_confidence: float = 0.0
    beats: list[Beat] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    transients: list[Transient] = field(default_factory=list)
    key: Optional[str] = None            # e.g. "C minor" — optional, future
    time_signature: tuple[int, int] = (4, 4)


# ---------------------------------------------------------------------------
# Samples & pads
# ---------------------------------------------------------------------------

@dataclass
class Sample:
    """
    A playable sample. It either references a region of a stem (lightweight,
    no audio duplication) OR a standalone wav file (e.g. user-rendered slice
    after destructive edits).
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    category: SampleCategory = SampleCategory.USER

    # Either source_stem_id + start/end, OR path. Mutually exclusive in spirit.
    source_stem_id: Optional[str] = None
    start_sample: int = 0
    end_sample: int = 0
    path: Optional[Path] = None           # if rendered to its own file

    # Playback parameters
    gain_db: float = 0.0
    pitch_semitones: float = 0.0
    time_stretch: float = 1.0             # 1.0 = no stretch
    reverse: bool = False
    fade_in_samples: int = 64
    fade_out_samples: int = 256
    normalized: bool = False
    # NEW: extended playback parameters
    cutoff_hz: float = 20000.0            # low-pass filter, 20kHz = off
    highpass_hz: float = 20.0             # high-pass filter, 20Hz = off
    pan: float = 0.0 
    loop_beats: int = 0
    loop_ready: bool = False              # render without user fades for seamless looping

    # Metadata
    bpm: Optional[float] = None
    root_note: Optional[int] = None       # MIDI note number
    tags: list[str] = field(default_factory=list)

    @property
    def length_samples(self) -> int:
        return max(0, self.end_sample - self.start_sample)


@dataclass
class Pad:
    """One pad in the matrix. Index is grid position; sample_id is what plays."""
    index: int                            # 0..N-1
    sample_id: Optional[str] = None
    mode: PadMode = PadMode.ONE_SHOT
    color: str = "#888888"                # hex, drives UI tinting
    label: str = ""
    muted: bool = False
    group: int = 0                        # choke group: pads with same >0 group cut each other
    choke_self: bool = False              # if True, re-triggering this pad cuts its own previous voice


@dataclass
class PadBank:
    """A bank is a snapshot of all pads. Banks let users switch layouts."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Bank A"
    pads: list[Pad] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Project (root aggregate)
# ---------------------------------------------------------------------------

@dataclass
class Project:
    """Root aggregate. Everything the user has loaded/created lives here."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Untitled Project"
    version: int = 1

    sources: list[AudioSource] = field(default_factory=list)
    stems: list[Stem] = field(default_factory=list)
    analyses: list[AnalysisResult] = field(default_factory=list)
    samples: list[Sample] = field(default_factory=list)
    banks: list[PadBank] = field(default_factory=list)
    active_bank_id: Optional[str] = None

    # Convenience lookups (not persisted, rebuilt on load)
    def sample_by_id(self, sid: str) -> Optional[Sample]:
        return next((s for s in self.samples if s.id == sid), None)

    def stem_by_id(self, stem_id: str) -> Optional[Stem]:
        return next((s for s in self.stems if s.id == stem_id), None)

    def active_bank(self) -> Optional[PadBank]:
        if not self.active_bank_id:
            return self.banks[0] if self.banks else None
        return next((b for b in self.banks if b.id == self.active_bank_id), None)
