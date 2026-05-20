"""
Metronome — generates click sounds and beat-tick signals synced to BPM.

Architecture:
  - Uses a QTimer that fires once per beat (interval = 60000/bpm ms).
  - On each tick: emits beat() signal (for UI blink) and pushes a click
    sample into the audio engine.
  - Count-in: when armed for recording, plays N bars of clicks (1/2/4)
    before triggering the actual record start.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

log = logging.getLogger(__name__)


@dataclass
class _FallbackClickVoice:
    """
    Duck-typed voice used when the engine's internal _Voice class can't be
    imported (e.g. in isolated tests). Matches the fields the audio callback
    reads: audio, position, loop, gate, hold, pad_index, group, active.
    """
    audio: np.ndarray
    position: int = 0
    loop: bool = False
    gate: bool = False
    hold: bool = False
    pad_index: int = -1
    group: int = -1
    active: bool = True
    sample_id: str = "__metronome_click__"


@dataclass(frozen=True)
class ClickProfile:
    """Frequency + duration of metronome clicks. Downbeat = higher pitch."""
    downbeat_freq: float = 1320.0     # Hz (a sharp tick at E6)
    beat_freq: float = 880.0          # Hz (a tick at A5)
    click_duration_ms: float = 30.0
    click_amplitude: float = 0.45


class Metronome(QObject):
    """
    Beat clock + click generator. Drives:
      - beat(beat_index, is_downbeat) — emitted on every tick (UI blink)
      - count_in_finished() — emitted after count-in bars complete
    """
    beat = pyqtSignal(int, bool)         # (beat_index, is_downbeat)
    count_in_finished = pyqtSignal()
    started = pyqtSignal()
    stopped = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._enabled = False
        self._bpm = 120.0
        self._beats_per_bar = 4
        self._beat_index = 0
        self._sample_rate = 44100
        self._engine = None
        self._profile = ClickProfile()

        # Count-in state
        self._count_in_bars = 0           # 0 = no count-in
        self._count_in_remaining = 0      # beats left in count-in
        self._is_count_in = False

        # Pre-rendered click audio (mono float32)
        self._click_downbeat: Optional[np.ndarray] = None
        self._click_normal: Optional[np.ndarray] = None

    # ---- Public API ----

    def set_engine(self, engine) -> None:
        """Inject the playback engine for click sound delivery."""
        self._engine = engine
        if engine:
            self._sample_rate = getattr(engine, "sample_rate", 44100)
            self._render_clicks()

    def set_bpm(self, bpm: float) -> None:
        self._bpm = max(20.0, min(500.0, float(bpm)))
        if self._timer.isActive():
            self._timer.setInterval(self._interval_ms())

    def set_beats_per_bar(self, n: int) -> None:
        self._beats_per_bar = max(1, min(16, int(n)))

    def set_count_in_bars(self, bars: int) -> None:
        """Bars of count-in before recording starts. 0 = no count-in."""
        self._count_in_bars = max(0, min(8, int(bars)))

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def bpm(self) -> float:
        return self._bpm

    @property
    def beats_per_bar(self) -> int:
        return self._beats_per_bar

    @property
    def count_in_bars(self) -> int:
        return self._count_in_bars

    @property
    def is_count_in(self) -> bool:
        return self._is_count_in

    def start(self) -> None:
        """Start the metronome (clicks audible)."""
        if self._bpm <= 0:
            log.warning("Cannot start metronome: BPM is 0")
            return
        self._enabled = True
        self._beat_index = 0
        self._is_count_in = False
        self._timer.start(self._interval_ms())
        self.started.emit()
        # Click on the first beat immediately
        self._on_tick()

    def stop(self) -> None:
        self._enabled = False
        self._is_count_in = False
        self._count_in_remaining = 0
        self._timer.stop()
        self.stopped.emit()

    def start_count_in(self) -> bool:
        """
        Start count-in. After count_in_bars are completed, emits
        count_in_finished. Returns False if no count-in is configured.
        """
        if self._count_in_bars <= 0:
            return False
        if self._bpm <= 0:
            log.warning("Cannot start count-in: BPM is 0")
            return False
        self._is_count_in = True
        self._enabled = True
        self._beat_index = 0
        self._count_in_remaining = self._count_in_bars * self._beats_per_bar
        self._timer.start(self._interval_ms())
        self.started.emit()
        self._on_tick()
        return True

    # ---- Internals ----

    def _interval_ms(self) -> int:
        return max(1, int(60000.0 / self._bpm))

    def _on_tick(self) -> None:
        is_downbeat = (self._beat_index % self._beats_per_bar == 0)
        self.beat.emit(self._beat_index, is_downbeat)
        self._play_click(is_downbeat)
        self._beat_index += 1

        # Handle count-in completion
        if self._is_count_in:
            self._count_in_remaining -= 1
            if self._count_in_remaining <= 0:
                self._is_count_in = False
                self.count_in_finished.emit()
                # Continue ticking only if metronome should remain on
                # (caller decides — typically turns it off after rec starts)

    def _play_click(self, is_downbeat: bool) -> None:
        if not self._engine:
            return
        click = self._click_downbeat if is_downbeat else self._click_normal
        if click is None or len(click) == 0:
            return
        try:
            # Convert mono click to stereo
            stereo = np.stack([click, click], axis=1).astype(np.float32)
            # Prefer the thread-safe queue API
            if hasattr(self._engine, "trigger_click"):
                self._engine.trigger_click(stereo)
            else:
                # Fallback for engines without the queue API (tests)
                self._inject_click_voice(click)
        except Exception as e:
            log.debug("Click injection failed: %s", e)

    def _inject_click_voice(self, mono_click: np.ndarray) -> None:
        """Inject the click as a transient voice into the engine."""
        # Convert mono click to stereo (matches engine expectation)
        stereo = np.stack([mono_click, mono_click], axis=1).astype(np.float32)

        if not hasattr(self._engine, "_voices"):
            return

        # Try to use the engine's real _Voice class; fall back to a duck-typed
        # object with the same attributes if the import path differs.
        voice = None
        try:
            from app.audio.playback.engine import _Voice
            voice = _Voice(
                sample_id="__metronome_click__",
                audio=stereo,
                position=0,
                loop=False,
                gate=False,
                hold=False,
                pad_index=-1,
                group=-1,
                active=True,
            )
        except Exception:
            voice = _FallbackClickVoice(stereo)

        # Keep voice list cap
        max_voices = getattr(self._engine, "MAX_VOICES", 32)
        if len(self._engine._voices) >= max_voices:
            self._engine._voices.pop(0)
        self._engine._voices.append(voice)

    def _render_clicks(self) -> None:
        """Pre-render click samples for downbeat and normal beat."""
        sr = self._sample_rate
        dur_samples = max(1, int(self._profile.click_duration_ms / 1000 * sr))
        t = np.arange(dur_samples, dtype=np.float32) / sr

        # Exponential decay envelope
        envelope = np.exp(-t * 80.0)

        # Downbeat: higher freq
        self._click_downbeat = (
            self._profile.click_amplitude * envelope
            * np.sin(2 * np.pi * self._profile.downbeat_freq * t)
        ).astype(np.float32)
        # Normal beat: lower freq, slightly quieter
        self._click_normal = (
            self._profile.click_amplitude * 0.7 * envelope
            * np.sin(2 * np.pi * self._profile.beat_freq * t)
        ).astype(np.float32)