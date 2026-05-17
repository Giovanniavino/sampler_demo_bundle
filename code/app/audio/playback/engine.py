"""
Playback engine.

Design goal: present a stable API that the GUI talks to. The CONCRETE engine
can be swapped (Python reference -> C++/pybind11) without touching callers.

Architecture:
  - Voices: a fixed pool. One pad trigger -> one voice acquired.
  - Mixer: sums all active voices into the output stream.
  - Stems cache: each Stem is loaded once (numpy float32, stereo) and shared.
  - Audio callback runs on the sounddevice thread; the GUI thread only enqueues
    commands via a lock-free-ish queue (queue.Queue is fine for MVP latency).

When we move to C++:
  - Same trigger/stop API.
  - Voices implemented as a JUCE/CHOC mixer; same Stem cache populated from Python.
  - Pybind11 module exposes the same methods.

For the MVP we use sounddevice (PortAudio). Latency ~20-50ms is fine to validate
the design. For embedded we'll target JACK with period_size=128 (~3ms @ 48k).
"""

from __future__ import annotations

import logging
import threading
import queue
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.models import Pad, PadMode, Sample, Stem, StemType

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class PlaybackEngine(ABC):
    @abstractmethod
    def load_stems(self, stems: list[Stem]) -> None: ...
    @abstractmethod
    def register_sample(self, sample: Sample) -> None: ...
    @abstractmethod
    def trigger_pad(self, pad: Pad, sample: Sample) -> None: ...
    @abstractmethod
    def release_pad(self, pad: Pad) -> None: ...
    @abstractmethod
    def stop_all(self) -> None: ...
    @abstractmethod
    def set_stem_mute(self, stem_type: StemType, muted: bool) -> None: ...
    @abstractmethod
    def start(self) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...


# ---------------------------------------------------------------------------
# Python reference implementation
# ---------------------------------------------------------------------------

@dataclass
class _Voice:
    """One playing instance of a Sample."""
    sample_id: str
    audio: np.ndarray         # (frames, 2) float32, already includes fades & gain
    position: int = 0
    loop: bool = False
    hold: bool = False
    pad_index: int = -1
    group: int = 0
    active: bool = True


@dataclass
class _Command:
    kind: str                 # 'trigger' | 'release' | 'stop_all' | 'mute_stem'
    payload: dict = field(default_factory=dict)


class SounddevicePlaybackEngine(PlaybackEngine):
    """
    Python playback engine using sounddevice (PortAudio).

    Threading model:
      - GUI thread calls trigger_pad/release_pad -> push Command onto queue
      - Audio thread (sounddevice callback) drains queue, updates voices, mixes
    This keeps the audio callback free of locks/allocations beyond a bounded queue.
    """

    MAX_VOICES = 32

    def __init__(self, sample_rate: int = 44100, block_size: int = 512, channels: int = 2):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.channels = channels

        # Cached stem audio: id -> (frames, channels) float32
        self._stem_audio: dict[str, np.ndarray] = {}
        # Cached sample renders: id -> rendered float32 buffer ready to mix
        self._sample_buffers: dict[str, np.ndarray] = {}
        # Original sample records (for re-rendering on param change)
        self._samples: dict[str, Sample] = {}

        self._voices: list[_Voice] = []
        self._stem_mutes: dict[StemType, bool] = {}
        self._cmd_queue: "queue.Queue[_Command]" = queue.Queue(maxsize=256)
        self._stream = None
        self._lock = threading.Lock()

    # ---- Public API ----------------------------------------------------

    def load_stems(self, stems: list[Stem]) -> None:
        import soundfile as sf
        for stem in stems:
            if not stem.path or not stem.path.exists():
                continue
            data, sr = sf.read(str(stem.path), dtype="float32", always_2d=True)
            if sr != self.sample_rate:
                data = self._resample(data, sr, self.sample_rate)
            if data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            self._stem_audio[stem.id] = data
            log.info("Cached stem %s: %d frames", stem.stem_type.value, len(data))

    def register_sample(self, sample: Sample) -> None:
        """Pre-render a sample buffer with fades and gain baked in."""
        self._samples[sample.id] = sample
        buf = self._render_sample(sample)
        if buf is not None:
            self._sample_buffers[sample.id] = buf

    def trigger_pad(self, pad: Pad, sample: Sample) -> None:
        if sample.id not in self._sample_buffers:
            self.register_sample(sample)
        self._cmd_queue.put_nowait(_Command("trigger", {
            "pad_index": pad.index, "sample_id": sample.id,
            "mode": pad.mode, "group": pad.group,
        }))

    def release_pad(self, pad: Pad) -> None:
        self._cmd_queue.put_nowait(_Command("release", {"pad_index": pad.index}))

    def stop_all(self) -> None:
        self._cmd_queue.put_nowait(_Command("stop_all"))

    def set_stem_mute(self, stem_type: StemType, muted: bool) -> None:
        self._stem_mutes[stem_type] = muted

    def start(self) -> None:
        import sounddevice as sd
        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=self.channels,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        log.info("Audio stream started @ %dHz / block=%d", self.sample_rate, self.block_size)

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    # ---- Audio callback ------------------------------------------------

    def _callback(self, outdata, frames, time_info, status):
        if status:
            log.warning("Audio callback status: %s", status)

        # 1) Drain commands
        while True:
            try:
                cmd = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            self._apply_command(cmd)

        # 2) Mix active voices into outdata
        outdata.fill(0.0)
        if not self._voices:
            return

        remaining: list[_Voice] = []
        for v in self._voices:
            if not v.active:
                continue
            buf = v.audio
            buf_len = len(buf)
            end = v.position + frames
            if end <= buf_len:
                outdata[:] += buf[v.position:end]
                v.position = end
                remaining.append(v)
            else:
                # Voice would run past buffer end
                tail = buf_len - v.position
                if tail > 0:
                    outdata[:tail] += buf[v.position:]
                if v.loop and buf_len > 0:
                    # Loop wrap with a tiny crossfade to avoid clicks.
                    # We overlap the last `xfade` samples of the buffer with
                    # the first `xfade` samples of the next iteration.
                    xfade = min(64, buf_len // 8, tail)  # ~1.5ms at 44.1k
                    leftover = frames - tail
                    if leftover <= 0:
                        v.position = 0
                        remaining.append(v)
                        continue

                    # Crossfade region: outdata[tail-xfade : tail] currently
                    # contains the buffer END. We add an attenuated copy of the
                    # buffer START on top.
                    if xfade > 0 and tail >= xfade:
                        ramp_in = np.linspace(0.0, 1.0, xfade,
                                              dtype=np.float32)[:, None]
                        ramp_out = 1.0 - ramp_in
                        # Apply ramp_out to the existing tail
                        outdata[tail - xfade:tail] *= ramp_out
                        # Add ramp_in * buffer start
                        head = buf[:xfade] * ramp_in
                        outdata[tail - xfade:tail] += head

                    if leftover < buf_len:
                        outdata[tail:tail + leftover] += buf[:leftover]
                        v.position = leftover
                    else:
                        v.position = 0
                    remaining.append(v)
                # else: voice ends, don't keep it
        self._voices = remaining

        # Soft clip
        np.clip(outdata, -1.0, 1.0, out=outdata)

    def _apply_command(self, cmd: _Command) -> None:
        if cmd.kind == "trigger":
            sid = cmd.payload["sample_id"]
            buf = self._sample_buffers.get(sid)
            if buf is None:
                return
            mode: PadMode = cmd.payload["mode"]
            group = cmd.payload["group"]
            pad_index = cmd.payload["pad_index"]

            # Choke group: stop other voices in same group
            if group > 0:
                for v in self._voices:
                    if v.group == group:
                        v.active = False

            # Voice stealing: if at cap, drop oldest
            if len(self._voices) >= self.MAX_VOICES:
                self._voices.pop(0)

            self._voices.append(_Voice(
                sample_id=sid,
                audio=buf,
                loop=(mode == PadMode.LOOP),
                hold=(mode in (PadMode.HOLD, PadMode.GATE)),
                pad_index=pad_index,
                group=group,
            ))

        elif cmd.kind == "release":
            pad_index = cmd.payload["pad_index"]
            for v in self._voices:
                if v.pad_index == pad_index and v.hold:
                    v.active = False

        elif cmd.kind == "stop_all":
            for v in self._voices:
                v.active = False

    # ---- Rendering -----------------------------------------------------

    def _render_sample(self, sample: Sample) -> Optional[np.ndarray]:
        """Return a rendered (frames, 2) float32 buffer for this sample.

        Notes on click-free loops:
          - For a SAMPLE THAT WILL LOOP, baking a hard fade-out into the buffer
            would cause an audible "duck" on every wrap. We therefore apply
            only a tiny edge anti-click ramp (~2ms), not the user fade_out.
          - We also snap start/end of stem regions to the nearest zero-crossing
            within a small search window. This removes the worst click sources.
          - At loop wrap time, the audio callback ALSO does a short crossfade
            (see _callback). The combination kills the click for most material.
        """
        # Case 1: rendered file path
        if sample.path and sample.path.exists():
            import soundfile as sf
            buf, sr = sf.read(str(sample.path), dtype="float32", always_2d=True)
            if sr != self.sample_rate:
                buf = self._resample(buf, sr, self.sample_rate)
        # Case 2: region of a stem (with zero-crossing snap)
        elif sample.source_stem_id and sample.source_stem_id in self._stem_audio:
            src = self._stem_audio[sample.source_stem_id]
            start, end = self._snap_zero_crossings(
                src, sample.start_sample, sample.end_sample
            )
            buf = src[start:end].copy()
        else:
            log.warning("Sample %s has no playable source", sample.name)
            return None

        if buf.size == 0:
            log.warning("Sample %s rendered empty", sample.name)
            return None

        if buf.shape[1] == 1:
            buf = np.repeat(buf, 2, axis=1)

        # Reverse
        if sample.reverse:
            buf = buf[::-1].copy()

        # Pitch / time stretch (Python ref impl). Use rubberband if available; else skip.
        if sample.pitch_semitones != 0.0 or sample.time_stretch != 1.0:
            buf = self._pitch_time(buf, sample.pitch_semitones, sample.time_stretch)

        # Gain
        if sample.gain_db != 0.0:
            buf *= 10 ** (sample.gain_db / 20.0)

        # Edge anti-click ramps (very short, always applied, loop-safe).
        # User-requested fade_in/out are respected, but capped to length/2
        # and only applied if longer than the anti-click floor.
        n = len(buf)
        anti_click = min(int(0.002 * self.sample_rate), n // 4)  # ~2ms
        fin = max(min(sample.fade_in_samples, n // 2), anti_click)
        fout = max(min(sample.fade_out_samples, n // 2), anti_click)
        if fin > 0:
            ramp = np.linspace(0.0, 1.0, fin, dtype=np.float32)[:, None]
            buf[:fin] *= ramp
        if fout > 0:
            ramp = np.linspace(1.0, 0.0, fout, dtype=np.float32)[:, None]
            buf[-fout:] *= ramp

        # Normalize
        if sample.normalized:
            peak = float(np.max(np.abs(buf))) or 1.0
            buf /= peak

        return np.ascontiguousarray(buf, dtype=np.float32)

    def _snap_zero_crossings(self, src: np.ndarray, start: int, end: int,
                             search_window: int = 256) -> tuple[int, int]:
        """Move start/end to the nearest zero-crossing within +/- search_window.

        Reduces clicks on stem slicing. Uses channel 0; stereo correlation is
        good enough on stems where L/R are similar.
        """
        n = len(src)
        start = max(0, min(start, n - 1))
        end = max(start + 1, min(end, n))

        def _nearest_zc(pos: int) -> int:
            lo = max(0, pos - search_window)
            hi = min(n - 1, pos + search_window)
            window = src[lo:hi, 0]
            if window.size < 2:
                return pos
            # zero crossings: sign change
            signs = np.signbit(window)
            zcs = np.where(np.diff(signs))[0]
            if len(zcs) == 0:
                return pos
            # closest to relative target
            target = pos - lo
            best = zcs[np.argmin(np.abs(zcs - target))]
            return lo + int(best)

        return _nearest_zc(start), _nearest_zc(end)

    def _pitch_time(self, buf: np.ndarray, semitones: float, stretch: float) -> np.ndarray:
        """Optional pitch/time using pyrubberband; falls back to passthrough."""
        try:
            import pyrubberband as pyrb
            mono_or_stereo = buf.T  # rubberband expects (channels, samples) or (samples,)
            out = pyrb.time_stretch(buf, self.sample_rate, stretch) if stretch != 1.0 else buf
            if semitones != 0.0:
                out = pyrb.pitch_shift(out, self.sample_rate, semitones)
            return np.ascontiguousarray(out.astype(np.float32))
        except Exception as e:
            log.warning("Pitch/time DSP unavailable: %s", e)
            return buf

    def _resample(self, data: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        try:
            import librosa
            out = librosa.resample(data.T, orig_sr=src_sr, target_sr=dst_sr).T
            return np.ascontiguousarray(out.astype(np.float32))
        except Exception:
            return data.astype(np.float32)
