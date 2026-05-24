"""
Bar-locked audio looper — multi-track with overdub and undo.

A :class:`Looper` is a bank of N parallel :class:`LoopTrack`s. Each track has
its own buffer, position and undo history; all tracks share the same length
so they loop in lockstep at the project tempo (no cross-track drift).

Per-track state machine::

    idle            ->  empty, nothing happens
    armed_record    ->  waiting for an external start cue (next downbeat)
    armed_overdub   ->  waiting for next downbeat, then adds layers
    recording       ->  writing master into the buffer (replace, one pass)
    overdub         ->  playing AND adding incoming master into the buffer
    playing         ->  playing the buffer back

Overdub is true monitor-style: every track sees the *dry* input snapshot, not
the loop playback from sibling tracks — so layering never feeds back into a
neighbouring loop. Undo keeps the last few buffer snapshots (one is pushed
before each record / overdub session) so a take can be unwound one step at a
time.

Designed to live inside the audio callback: :meth:`Looper.process` mutates the
master buffer in place.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


class LoopTrack:
    """One track in the loop bank — own buffer, state, position, undo."""

    IDLE = "idle"
    ARMED_RECORD = "armed_record"
    ARMED_OVERDUB = "armed_overdub"
    RECORDING = "recording"
    OVERDUB = "overdub"
    PLAYING = "playing"

    MAX_UNDO = 4                # cap on saved snapshots

    def __init__(self, sample_rate: int = 44100):
        self._sample_rate: int = int(sample_rate)
        self._state: str = self.IDLE
        self._buffer: Optional[np.ndarray] = None
        self._length: int = 0
        self._pos: int = 0
        self._undo: list[np.ndarray] = []

    # ---- read-only views --------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def position_frac(self) -> float:
        if self._length <= 0:
            return 0.0
        return self._pos / self._length

    @property
    def has_content(self) -> bool:
        return self._buffer is not None and bool(np.any(self._buffer))

    @property
    def has_undo(self) -> bool:
        return bool(self._undo)

    # ---- configuration ----------------------------------------------

    def configure(self, length: int) -> None:
        """Re-allocate the buffer to ``length`` samples (resets state)."""
        length = max(0, int(length))
        if length == self._length:
            return
        self._length = length
        self._buffer = (np.zeros((length, 2), dtype=np.float32)
                        if length > 0 else None)
        self._pos = 0
        self._undo.clear()
        self._state = self.IDLE

    # ---- transitions ------------------------------------------------

    def arm_record(self) -> None:
        if self._length <= 0:
            return
        self._state = self.ARMED_RECORD

    def arm_overdub(self) -> None:
        if self._length <= 0 or not self.has_content:
            return
        self._state = self.ARMED_OVERDUB

    def start_record_now(self,
                         preroll: Optional[np.ndarray] = None) -> None:
        """Begin capturing (replace mode); previous content goes to undo.

        If ``preroll`` is given, it is written to the very start of the
        buffer before the live recording resumes from where the pre-roll
        ends. That lets the engine compensate for the trigger latency
        between the actual musical downbeat and the moment this command
        is dispatched, so the loop's sample 0 is the downbeat audio
        instead of the audio 30-50 ms later.
        """
        if self._buffer is None:
            return
        self._push_undo()
        self._buffer.fill(0.0)
        self._pos = 0
        if preroll is not None and len(preroll) > 0:
            n = min(len(preroll), self._length)
            self._buffer[:n] = preroll[-n:]   # last n samples in chronological order
            self._pos = n
        self._state = self.RECORDING

    def start_overdub_now(self) -> None:
        """Begin overdubbing; the pre-overdub buffer is saved for undo."""
        if self._buffer is None:
            return
        self._push_undo()
        self._pos = 0
        self._state = self.OVERDUB

    def stop_overdub(self) -> None:
        """End the overdub session, keep what was added."""
        if self._state == self.OVERDUB:
            self._state = self.PLAYING

    def cancel(self) -> None:
        """Drop the pending arm / partial take / overdub session."""
        if self._state in (self.RECORDING, self.OVERDUB):
            # Restore the pre-session snapshot we pushed at start_*_now.
            self.undo()
        elif self._state in (self.ARMED_RECORD, self.ARMED_OVERDUB):
            self._state = self.PLAYING if self.has_content else self.IDLE

    def clear(self) -> None:
        if self._buffer is not None:
            self._buffer.fill(0.0)
        self._pos = 0
        self._undo.clear()
        self._state = self.IDLE

    def undo(self) -> None:
        """Restore the most recent snapshot (one record / overdub ago)."""
        if not self._undo or self._buffer is None:
            return
        prev = self._undo.pop()
        self._buffer[:] = prev
        self._state = self.PLAYING if self.has_content else self.IDLE

    def _push_undo(self) -> None:
        if self._buffer is None:
            return
        self._undo.append(self._buffer.copy())
        if len(self._undo) > self.MAX_UNDO:
            self._undo.pop(0)


    # ---- audio path -------------------------------------------------

    def process(self, master: np.ndarray, incoming: np.ndarray,
                frames: int) -> None:
        """Run one stereo block through the track, in place.

        ``incoming`` is the snapshot of master *before* any track in the bank
        contributed — overdub uses that so layering never picks up sibling
        loops' playback as input.
        """
        if self._buffer is None or self._length <= 0:
            return

        if self._state == self.RECORDING:
            remaining = self._length - self._pos
            n = frames if frames < remaining else remaining
            if n > 0:
                self._buffer[self._pos:self._pos + n] = incoming[:n]
                self._pos += n
            if self._pos >= self._length:
                self._state = self.PLAYING
                self._pos = 0
            return

        if self._state in (self.PLAYING, self.OVERDUB):
            end = self._pos + frames
            if end <= self._length:
                master[:frames] += self._buffer[self._pos:end]
                if self._state == self.OVERDUB:
                    self._buffer[self._pos:end] += incoming[:frames]
                self._pos = end
                if self._pos >= self._length:
                    self._pos = 0
            else:
                first = self._length - self._pos
                master[:first] += self._buffer[self._pos:self._length]
                if self._state == self.OVERDUB:
                    self._buffer[self._pos:self._length] += incoming[:first]
                remaining = frames - first
                if remaining > 0:
                    master[first:first + remaining] += self._buffer[:remaining]
                    if self._state == self.OVERDUB:
                        self._buffer[:remaining] += \
                            incoming[first:first + remaining]
                self._pos = remaining


class Looper:
    """Bank of N parallel :class:`LoopTrack`s sharing a bar-locked length."""

    NUM_TRACKS = 4

    def __init__(self, sample_rate: int):
        self.sample_rate = int(sample_rate)
        self._bars = 4
        self._beats_per_bar = 4
        self._bpm = 120.0
        self._length = 0
        self.tracks: list[LoopTrack] = [
            LoopTrack(sample_rate) for _ in range(self.NUM_TRACKS)
        ]

    @property
    def bars(self) -> int:
        return self._bars

    @property
    def length(self) -> int:
        return self._length

    @property
    def num_tracks(self) -> int:
        return len(self.tracks)

    def track(self, idx: int) -> Optional[LoopTrack]:
        if 0 <= idx < len(self.tracks):
            return self.tracks[idx]
        return None

    def configure(self, bars: int, bpm: float,
                  beats_per_bar: int = 4) -> None:
        self._bars = max(1, int(bars))
        self._beats_per_bar = max(1, int(beats_per_bar))
        self._bpm = max(20.0, float(bpm))
        new_length = int(round(
            self._bars * self._beats_per_bar
            * (60.0 / self._bpm) * self.sample_rate
        ))
        if new_length != self._length:
            self._length = new_length
            for t in self.tracks:
                t.configure(new_length)

    def any_active(self) -> bool:
        """True when at least one track is producing or capturing audio."""
        for t in self.tracks:
            if t.state in ("recording", "playing", "overdub"):
                return True
        return False

    def process(self, master: np.ndarray) -> None:
        """Run every track against the master block, in place."""
        if self._length <= 0 or not self.any_active():
            return
        frames = len(master)
        # Snapshot the dry input once: every track overdubs from the same
        # pre-mix master so we never record sibling loops into each other.
        incoming = master.copy()
        for t in self.tracks:
            t.process(master, incoming, frames)
