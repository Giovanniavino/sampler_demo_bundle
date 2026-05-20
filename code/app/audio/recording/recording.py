"""
Recording — captures pad trigger events and plays them back.

Captures:
  - Pad trigger (note on) with timestamp and velocity
  - Pad release (note off) with timestamp

Features:
  - Quantize: snap event timestamps to nearest beat fraction (0–100%)
  - Playback: schedule recorded events with QTimer
  - Save/Load: serialize sequences to JSON

Use case:
  1. User arms recording (optionally with count-in)
  2. After count-in (if any), recording starts
  3. User taps pads — each trigger/release is logged with wall-clock time
  4. User stops recording
  5. User can play back the sequence (loops through events firing triggerPad)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

log = logging.getLogger(__name__)


class EventKind(str, Enum):
    NOTE_ON = "note_on"
    NOTE_OFF = "note_off"


@dataclass
class RecordedEvent:
    """A single pad event with timing info."""
    timestamp_ms: float    # ms from sequence start
    pad_index: int
    kind: EventKind
    velocity: int = 100    # 0–127

    def to_dict(self) -> dict:
        return {
            "timestamp_ms": self.timestamp_ms,
            "pad_index": self.pad_index,
            "kind": self.kind.value,
            "velocity": self.velocity,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RecordedEvent":
        return cls(
            timestamp_ms=float(d["timestamp_ms"]),
            pad_index=int(d["pad_index"]),
            kind=EventKind(d["kind"]),
            velocity=int(d.get("velocity", 100)),
        )


@dataclass
class RecordedSequence:
    """A recorded performance — list of events + metadata."""
    events: list[RecordedEvent] = field(default_factory=list)
    duration_ms: float = 0.0
    bpm: float = 120.0
    beats_per_bar: int = 4
    name: str = "Take 1"

    def to_dict(self) -> dict:
        return {
            "events": [e.to_dict() for e in self.events],
            "duration_ms": self.duration_ms,
            "bpm": self.bpm,
            "beats_per_bar": self.beats_per_bar,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RecordedSequence":
        return cls(
            events=[RecordedEvent.from_dict(e) for e in d.get("events", [])],
            duration_ms=float(d.get("duration_ms", 0.0)),
            bpm=float(d.get("bpm", 120.0)),
            beats_per_bar=int(d.get("beats_per_bar", 4)),
            name=d.get("name", "Take 1"),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "RecordedSequence":
        with path.open("r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def quantized(self, percent: float) -> "RecordedSequence":
        """
        Return a new sequence with events snapped to the beat grid.
        percent: 0 = no snap, 100 = fully snapped to nearest beat.
        Anything in between linearly interpolates between raw and snapped.
        """
        if percent <= 0 or self.bpm <= 0:
            return self  # no quantization
        amt = max(0.0, min(100.0, percent)) / 100.0
        ms_per_beat = 60000.0 / self.bpm

        new_events = []
        for ev in self.events:
            beat_pos = ev.timestamp_ms / ms_per_beat
            nearest = round(beat_pos)
            snapped_ms = nearest * ms_per_beat
            # Linear blend
            new_ts = ev.timestamp_ms * (1.0 - amt) + snapped_ms * amt
            new_events.append(RecordedEvent(
                timestamp_ms=new_ts,
                pad_index=ev.pad_index,
                kind=ev.kind,
                velocity=ev.velocity,
            ))
        return RecordedSequence(
            events=sorted(new_events, key=lambda e: e.timestamp_ms),
            duration_ms=self.duration_ms,
            bpm=self.bpm,
            beats_per_bar=self.beats_per_bar,
            name=self.name + f" (Q{int(percent)}%)",
        )


class Recorder(QObject):
    """
    Records pad events. The controller calls log_trigger/log_release
    when the user interacts with pads.
    """
    stateChanged = pyqtSignal()
    eventLogged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_recording = False
        self._start_time: Optional[float] = None
        self._sequence = RecordedSequence()

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def event_count(self) -> int:
        return len(self._sequence.events)

    @property
    def sequence(self) -> RecordedSequence:
        return self._sequence

    def start(self, bpm: float, beats_per_bar: int = 4) -> None:
        self._sequence = RecordedSequence(
            bpm=bpm, beats_per_bar=beats_per_bar
        )
        self._start_time = time.monotonic()
        self._is_recording = True
        self.stateChanged.emit()

    def stop(self) -> None:
        if not self._is_recording:
            return
        self._is_recording = False
        if self._start_time:
            self._sequence.duration_ms = (
                time.monotonic() - self._start_time
            ) * 1000.0
        self._start_time = None
        self.stateChanged.emit()

    def log_trigger(self, pad_index: int, velocity: int = 100) -> None:
        if not self._is_recording or self._start_time is None:
            return
        ts_ms = (time.monotonic() - self._start_time) * 1000.0
        self._sequence.events.append(RecordedEvent(
            timestamp_ms=ts_ms,
            pad_index=pad_index,
            kind=EventKind.NOTE_ON,
            velocity=velocity,
        ))
        self.eventLogged.emit()

    def log_release(self, pad_index: int) -> None:
        if not self._is_recording or self._start_time is None:
            return
        ts_ms = (time.monotonic() - self._start_time) * 1000.0
        self._sequence.events.append(RecordedEvent(
            timestamp_ms=ts_ms,
            pad_index=pad_index,
            kind=EventKind.NOTE_OFF,
            velocity=0,
        ))
        self.eventLogged.emit()

    def clear(self) -> None:
        self._sequence = RecordedSequence()
        self.stateChanged.emit()


class Player(QObject):
    """
    Plays back a recorded sequence by scheduling trigger/release callbacks.
    """
    playbackStateChanged = pyqtSignal()
    positionChanged = pyqtSignal()      # current playback time
    playbackFinished = pyqtSignal()

    def __init__(self,
                 trigger_cb: Callable[[int, int], None],
                 release_cb: Callable[[int], None],
                 parent=None):
        super().__init__(parent)
        self._trigger_cb = trigger_cb
        self._release_cb = release_cb
        self._sequence: Optional[RecordedSequence] = None
        self._is_playing = False
        self._is_paused = False
        self._start_time: Optional[float] = None
        self._pause_offset_ms: float = 0.0  # ms of "fast-forward" offset
        self._event_index = 0

        # ~30 Hz tick for scheduling
        self._timer = QTimer(self)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._on_tick)

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def current_ms(self) -> float:
        if self._is_playing and self._start_time is not None:
            return (time.monotonic() - self._start_time) * 1000.0
        return self._pause_offset_ms

    def load_sequence(self, sequence: RecordedSequence) -> None:
        # Always sort by timestamp before playback
        sequence.events.sort(key=lambda e: e.timestamp_ms)
        self._sequence = sequence
        self._event_index = 0
        self._pause_offset_ms = 0.0

    def play(self) -> None:
        if not self._sequence or not self._sequence.events:
            return
        if self._is_paused:
            # Resume from pause: shift start_time so current_ms continues
            self._start_time = time.monotonic() - (self._pause_offset_ms / 1000.0)
            self._is_paused = False
        else:
            self._start_time = time.monotonic() - (self._pause_offset_ms / 1000.0)
            # Advance event index to first unfired event after offset
            self._event_index = 0
            for i, ev in enumerate(self._sequence.events):
                if ev.timestamp_ms >= self._pause_offset_ms:
                    self._event_index = i
                    break
            else:
                self._event_index = len(self._sequence.events)
        self._is_playing = True
        self._timer.start()
        self.playbackStateChanged.emit()

    def pause(self) -> None:
        if not self._is_playing:
            return
        self._pause_offset_ms = self.current_ms
        self._is_playing = False
        self._is_paused = True
        self._timer.stop()
        self.playbackStateChanged.emit()

    def stop(self) -> None:
        self._is_playing = False
        self._is_paused = False
        self._pause_offset_ms = 0.0
        self._event_index = 0
        self._timer.stop()
        self.playbackStateChanged.emit()

    def seek_to_start(self) -> None:
        """Go back to t=0."""
        was_playing = self._is_playing
        self.stop()
        if was_playing:
            self.play()

    def seek_forward_beats(self, beats: int = 1) -> None:
        """Skip forward by N beats."""
        if not self._sequence or self._sequence.bpm <= 0:
            return
        delta = beats * (60000.0 / self._sequence.bpm)
        was_playing = self._is_playing
        if was_playing:
            self.pause()
        new_pos = max(0.0, min(
            self._sequence.duration_ms or self._pause_offset_ms + delta,
            self._pause_offset_ms + delta
        ))
        self._pause_offset_ms = new_pos
        if was_playing:
            self.play()
        self.positionChanged.emit()

    def seek_backward_beats(self, beats: int = 1) -> None:
        """Skip backward by N beats."""
        if not self._sequence or self._sequence.bpm <= 0:
            return
        delta = beats * (60000.0 / self._sequence.bpm)
        was_playing = self._is_playing
        if was_playing:
            self.pause()
        new_pos = max(0.0, self._pause_offset_ms - delta)
        self._pause_offset_ms = new_pos
        if was_playing:
            self.play()
        self.positionChanged.emit()

    def _on_tick(self) -> None:
        if not self._sequence or self._start_time is None:
            return
        now_ms = (time.monotonic() - self._start_time) * 1000.0

        # Fire all events up to current playback position
        events = self._sequence.events
        while (self._event_index < len(events)
               and events[self._event_index].timestamp_ms <= now_ms):
            ev = events[self._event_index]
            try:
                if ev.kind == EventKind.NOTE_ON:
                    self._trigger_cb(ev.pad_index, ev.velocity)
                else:
                    self._release_cb(ev.pad_index)
            except Exception as e:
                log.warning("Playback callback failed: %s", e)
            self._event_index += 1

        # Emit position changed (UI playhead)
        self.positionChanged.emit()

        # End of sequence
        if self._event_index >= len(events):
            if now_ms >= (self._sequence.duration_ms or now_ms):
                self.stop()
                self.playbackFinished.emit()