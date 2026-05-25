"""
Playback engine — FIXED + EXTENDED:
  - Pitch/time stretch now WORKS (librosa fallback when pyrubberband missing)
  - Cutoff (low-pass filter) per sample
  - Pan (stereo positioning) per sample
  - Global project pitch (applied on top of per-sample pitch)
  - GATE mode (stop on release), HOLD mode (re-trigger on next press)
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

from app.audio.dsp.effects import EffectsChain
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
    audio: np.ndarray
    position: int = 0
    loop: bool = False
    gate: bool = False     # if True, release_pad stops voice immediately
    hold: bool = False     # if True, voice keeps playing until next trigger
    pad_index: int = -1
    group: int = 0
    active: bool = True
    loop_seamless: bool = False    # buffer pre-baked: skip callback crossfade


@dataclass
class _Command:
    kind: str
    payload: dict = field(default_factory=dict)


class SounddevicePlaybackEngine(PlaybackEngine):
    """
    Python playback engine with WORKING DSP (pitch, time, cutoff, pan).
    """

    MAX_VOICES = 32
    MAX_PADS = 32

    def __init__(self, sample_rate: int = 44100, block_size: int = 512,
                  channels: int = 2, output_device: Optional[str] = None):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.channels = channels
        self.output_device = output_device  # None = system default

        self._stem_audio: dict[str, np.ndarray] = {}
        self._sample_buffers: dict[str, np.ndarray] = {}
        self._samples: dict[str, Sample] = {}

        self._voices: list[_Voice] = []
        self._stem_mutes: dict[StemType, bool] = {}
        self._cmd_queue: "queue.Queue[_Command]" = queue.Queue(maxsize=256)
        self._stream = None
        self._lock = threading.Lock()

        # NEW: global project pitch (in semitones), applied to all samples
        self._global_pitch_semitones: float = 0.0

        # NEW: project-level BPM (used when sample.bpm is None for loop sync)
        self._project_bpm: float = 0.0

        # NEW: per-pad insert effect chains + an optional master chain.
        # Chains are created up-front (disabled = zero cost) so the audio
        # callback never has to allocate them.
        self._pad_chains: dict[int, EffectsChain] = {
            i: EffectsChain(sample_rate) for i in range(self.MAX_PADS)
        }
        self._master_chain = EffectsChain(sample_rate)

        # NEW: live output capture for bounce-to-disk. None = not capturing.
        self._capture_blocks: Optional[list[np.ndarray]] = None
        # Hard cap (~10 min) so a forgotten bounce can never grow the buffer
        # until the process runs out of memory.
        self._capture_max_blocks = int(
            600.0 * sample_rate / max(1, block_size)) + 8

    def set_project_bpm(self, bpm: float) -> None:
        """Set the project BPM, used for loop-to-grid quantization
        when a sample doesn't have its own BPM."""
        new_bpm = max(0.0, float(bpm))
        if abs(new_bpm - self._project_bpm) < 0.01:
            return
        self._project_bpm = new_bpm
        # Re-render samples that use loop_beats > 0 (loop sync enabled)
        for sid, sample in list(self._samples.items()):
            if getattr(sample, "loop_beats", 0) > 0:
                buf = self._render_sample(sample)
                if buf is not None:
                    self._sample_buffers[sid] = buf

    @property
    def project_bpm(self) -> float:
        return self._project_bpm

    # ---- Device discovery ---------------------------------------------

    @staticmethod
    def list_output_devices() -> list[dict]:
        """
        Return a deduplicated list of audio OUTPUT devices.

        sounddevice/PortAudio lists the same physical device once per host API
        (on Windows: MME, WASAPI, DirectSound, WDM-KS), which produces many
        duplicates. We keep ONE entry per device name, preferring the best
        host API available (WASAPI > WDM-KS > DirectSound > MME on Windows;
        first-seen elsewhere).

        Each dict: { 'index': int, 'name': str, 'channels': int,
                     'default_samplerate': float, 'is_default': bool,
                     'hostapi': str }
        """
        try:
            import sounddevice as sd
        except ImportError:
            return []

        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            default_out_idx = sd.default.device[1] if sd.default.device else -1
        except Exception as e:
            log.warning("Failed to query audio devices: %s", e)
            return []

        # Host API preference ranking (higher = better). Names vary by OS.
        api_rank = {
            "Windows WASAPI": 100,
            "Windows WDM-KS": 80,
            "Windows DirectSound": 60,
            "MME": 40,
            "Core Audio": 100,     # macOS
            "ALSA": 100,           # Linux
            "JACK Audio Connection Kit": 90,
            "PulseAudio": 70,
        }

        def api_name(api_idx: int) -> str:
            if 0 <= api_idx < len(hostapis):
                return hostapis[api_idx].get("name", "")
            return ""

        # Group candidates by a normalized device name
        best_by_name: dict[str, dict] = {}
        for i, dev in enumerate(devices):
            if dev.get("max_output_channels", 0) <= 0:
                continue
            raw_name = dev.get("name", f"Device {i}")
            # Normalize: strip the host API suffix some drivers append
            name = raw_name.strip()
            this_api = api_name(dev.get("hostapi", -1))
            rank = api_rank.get(this_api, 10)

            entry = {
                "index": i,
                "name": name,
                "channels": dev.get("max_output_channels", 2),
                "default_samplerate": float(dev.get("default_samplerate", 44100)),
                "is_default": (i == default_out_idx),
                "hostapi": this_api,
                "_rank": rank,
            }

            existing = best_by_name.get(name)
            if existing is None or rank > existing["_rank"]:
                best_by_name[name] = entry
            elif existing is not None and i == default_out_idx:
                # Always keep the system-default index if it matches this name
                existing["is_default"] = True

        # Strip the internal _rank key and sort: default first, then by name
        result = []
        for entry in best_by_name.values():
            entry.pop("_rank", None)
            result.append(entry)
        result.sort(key=lambda e: (not e["is_default"], e["name"].lower()))
        return result

    @staticmethod
    def get_default_output_device_name() -> str:
        """Return the name of the system default output device."""
        try:
            import sounddevice as sd
            default_out_idx = sd.default.device[1]
            devs = sd.query_devices()
            if 0 <= default_out_idx < len(devs):
                return devs[default_out_idx].get("name", "Default").strip()
        except Exception:
            pass
        return "Default"

    # ---- Public API ----------------------------------------------------

    def set_global_pitch(self, semitones: float) -> None:
        """Set global pitch shift, applied to all samples. Triggers re-render."""
        if abs(semitones - self._global_pitch_semitones) < 0.01:
            return
        self._global_pitch_semitones = float(semitones)
        # Re-render all samples
        for sid, sample in list(self._samples.items()):
            buf = self._render_sample(sample)
            if buf is not None:
                self._sample_buffers[sid] = buf

    @property
    def global_pitch_semitones(self) -> float:
        return self._global_pitch_semitones

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
            "choke_self": getattr(pad, "choke_self", False),
        }))

    def release_pad(self, pad: Pad) -> None:
        self._cmd_queue.put_nowait(_Command("release", {"pad_index": pad.index}))

    def stop_all(self) -> None:
        self._cmd_queue.put_nowait(_Command("stop_all"))

    def stop_pad(self, pad_index: int) -> None:
        """Thread-safe: stop all voices for a specific pad."""
        self._cmd_queue.put_nowait(_Command("stop_pad", {"pad_index": pad_index}))

    def trigger_click(self, click_audio: np.ndarray) -> None:
        """
        Thread-safe metronome click injection.
        click_audio: stereo float32 array (N, 2).
        """
        self._cmd_queue.put_nowait(_Command("click", {"audio": click_audio}))

    def set_stem_mute(self, stem_type: StemType, muted: bool) -> None:
        self._stem_mutes[stem_type] = muted

    # ---- Effects -------------------------------------------------------

    def _enqueue(self, cmd: "_Command") -> None:
        """Put a command on the queue, dropping it if the queue is full.

        Used for effect parameter changes: a dropped update is benign (the
        next one wins) and this must never raise on the UI thread.
        """
        try:
            self._cmd_queue.put_nowait(cmd)
        except queue.Full:
            log.debug("Command queue full, dropped %s", cmd.kind)

    def set_pad_effect_enabled(self, pad_index: int, effect: str,
                               enabled: bool) -> None:
        self._enqueue(_Command("fx_enable", {
            "target": "pad", "pad_index": pad_index,
            "effect": effect, "enabled": enabled,
        }))

    def set_pad_effect_param(self, pad_index: int, effect: str,
                             param: str, value: float) -> None:
        self._enqueue(_Command("fx_param", {
            "target": "pad", "pad_index": pad_index,
            "effect": effect, "param": param, "value": value,
        }))

    def set_master_effect_enabled(self, effect: str, enabled: bool) -> None:
        self._enqueue(_Command("fx_enable", {
            "target": "master", "effect": effect, "enabled": enabled,
        }))

    def set_master_effect_param(self, effect: str, param: str,
                                value: float) -> None:
        self._enqueue(_Command("fx_param", {
            "target": "master", "effect": effect,
            "param": param, "value": value,
        }))

    # ---- Output capture (live bounce) ----------------------------------

    def start_capture(self) -> None:
        """Begin recording the post-effects stereo master to memory."""
        self._capture_blocks = []

    def stop_capture(self) -> Optional[np.ndarray]:
        """Stop capturing and return the recorded stereo audio as (N, 2)."""
        blocks = self._capture_blocks
        self._capture_blocks = None
        if not blocks:
            return None
        return np.concatenate(blocks, axis=0)

    @property
    def is_capturing(self) -> bool:
        return self._capture_blocks is not None

    @property
    def sample_buffers(self) -> dict[str, np.ndarray]:
        """Rendered (baked-DSP) audio buffer for each registered sample."""
        return self._sample_buffers

    def start(self) -> None:
        import sounddevice as sd

        # Determine a safe channel count for the chosen device.
        channels = self.channels
        if self.output_device is not None:
            try:
                info = sd.query_devices(self.output_device, "output")
                max_ch = int(info.get("max_output_channels", 2))
                if max_ch < 1:
                    raise ValueError("Device reports 0 output channels")
                # Use 2 if supported, else clamp to what the device offers
                channels = min(self.channels, max_ch)
                if channels < 1:
                    channels = 1
            except Exception as e:
                log.warning("Could not query device '%s': %s",
                            self.output_device, e)
                # Fall back to default device
                self.output_device = None
                channels = self.channels

        kwargs = dict(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=channels,
            dtype="float32",
            callback=self._callback,
        )
        if self.output_device is not None:
            kwargs["device"] = self.output_device

        try:
            self._stream = sd.OutputStream(**kwargs)
            self._stream.start()
            self.channels = channels  # remember what actually worked
            log.info("Audio stream started @ %dHz / block=%d / device=%s / ch=%d",
                      self.sample_rate, self.block_size,
                      self.output_device or "default", channels)
        except Exception as e:
            log.error("Failed to open OutputStream on device '%s': %s",
                      self.output_device, e)
            # Retry once on the system default device with 2 channels
            self._stream = None
            if self.output_device is not None:
                log.info("Retrying on system default device")
                self.output_device = None
                self.channels = 2
                try:
                    self._stream = sd.OutputStream(
                        samplerate=self.sample_rate,
                        blocksize=self.block_size,
                        channels=2,
                        dtype="float32",
                        callback=self._callback,
                    )
                    self._stream.start()
                    log.info("Audio stream started on default device (fallback)")
                    return
                except Exception as e2:
                    log.error("Fallback also failed: %s", e2)
                    self._stream = None
            # Re-raise so the caller can surface the problem without crashing
            raise RuntimeError(
                f"Could not open audio device: {e}"
            ) from e

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    # ---- Audio callback ------------------------------------------------

    def _callback(self, outdata, frames, time_info, status):
        if status:
            log.warning("Audio callback status: %s", status)

        while True:
            try:
                cmd = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            self._apply_command(cmd)

        outdata.fill(0.0)
        out_channels = outdata.shape[1]

        # Idle fast path: with nothing playing, no effect tail ringing,
        # and no loop being recorded or played back, the output is silence
        # — skip all per-pad mixing entirely.
        if not self._voices and not self._any_chain_ringing():
            if self._capture_blocks is not None:
                self._append_capture(np.zeros((frames, 2), dtype=np.float32))
            return

        # Voices are mixed into per-pad buffers so each pad can run its own
        # insert effects chain. Voices with pad_index < 0 (metronome clicks,
        # browser previews) go to a dry bus and bypass all effects.
        pad_mix: dict[int, np.ndarray] = {}
        dry = np.zeros((frames, 2), dtype=np.float32)

        remaining: list[_Voice] = []
        for v in self._voices:
            if not v.active:
                continue
            if v.pad_index >= 0:
                target = pad_mix.get(v.pad_index)
                if target is None:
                    target = np.zeros((frames, 2), dtype=np.float32)
                    pad_mix[v.pad_index] = target
            else:
                target = dry

            buf = v.audio
            buf_len = len(buf)
            end = v.position + frames
            if end <= buf_len:
                target[:] += buf[v.position:end]
                v.position = end
                remaining.append(v)
            else:
                tail = buf_len - v.position
                if tail > 0:
                    target[:tail] += buf[v.position:]
                if v.loop and buf_len > 0:
                    leftover = frames - tail
                    if leftover <= 0:
                        v.position = 0
                        remaining.append(v)
                        continue

                    # Seamless voices have the wrap baked into the buffer
                    # (see _render_sample): sample 0 IS the natural
                    # continuation of sample length-1 in the underlying
                    # stem, so we can wrap with a hard cut — no crossfade
                    # needed, and no double-play of the first samples.
                    if not v.loop_seamless:
                        # Legacy fallback for buffers without pre-baked
                        # loop closure (e.g. path-based samples).
                        xfade = min(int(0.005 * self.sample_rate),
                                    buf_len // 4, tail)
                        if xfade > 0 and tail >= xfade:
                            ramp_in = np.linspace(0.0, 1.0, xfade,
                                                  dtype=np.float32)[:, None]
                            ramp_out = 1.0 - ramp_in
                            target[tail - xfade:tail] *= ramp_out
                            head = buf[:xfade] * ramp_in
                            target[tail - xfade:tail] += head

                    if leftover < buf_len:
                        target[tail:tail + leftover] += buf[:leftover]
                        v.position = leftover
                    else:
                        v.position = 0
                    remaining.append(v)
        self._voices = remaining

        # Sum the dry bus and every pad (through its chain) into the master.
        master = dry
        for pad_index, pbuf in pad_mix.items():
            chain = self._pad_chains.get(pad_index)
            if chain is not None and chain.any_enabled:
                master += chain.process(pbuf)
            else:
                master += pbuf

        # Pads with no input this block but still ringing (reverb/delay tail).
        silence = np.zeros((frames, 2), dtype=np.float32)
        for pad_index, chain in self._pad_chains.items():
            if pad_index in pad_mix:
                continue
            if chain.any_enabled and chain.is_ringing:
                master += chain.process(silence)

        # Master insert chain (applied to the summed mix).
        if self._master_chain.any_enabled:
            master = self._master_chain.process(master)

        np.clip(master, -1.0, 1.0, out=master)

        # Capture the post-effects stereo master for live bounce.
        self._append_capture(master)

        # Map the stereo master onto the device's channel layout.
        if out_channels == 2:
            outdata[:] = master
        elif out_channels == 1:
            # Downmix to mono
            outdata[:, 0] = master.mean(axis=1)
        else:
            # More than 2 channels: put stereo on first two, silence the rest
            outdata[:, 0] = master[:, 0]
            if out_channels >= 2:
                outdata[:, 1] = master[:, 1]
            # channels 2..N already zeroed by outdata.fill(0.0)

        np.clip(outdata, -1.0, 1.0, out=outdata)

    def _any_chain_ringing(self) -> bool:
        """True if any pad or the master chain still has a reverb/delay tail."""
        if self._master_chain.is_ringing:
            return True
        return any(c.is_ringing for c in self._pad_chains.values())

    def _append_capture(self, block: np.ndarray) -> None:
        """Append one stereo block to the live-bounce buffer, size-capped."""
        blocks = self._capture_blocks
        if blocks is not None and len(blocks) < self._capture_max_blocks:
            blocks.append(np.array(block, dtype=np.float32))

    def _apply_command(self, cmd: _Command) -> None:
        if cmd.kind == "trigger":
            sid = cmd.payload["sample_id"]
            buf = self._sample_buffers.get(sid)
            if buf is None:
                return
            mode: PadMode = cmd.payload["mode"]
            group = cmd.payload["group"]
            pad_index = cmd.payload["pad_index"]

            # Choke group
            if group > 0:
                for v in self._voices:
                    if v.group == group:
                        v.active = False

            # HOLD, LOOP, and per-pad self-choke all replace instead of
            # stacking: stop any voice already running on this pad first.
            choke_self = cmd.payload.get("choke_self", False)
            if choke_self or mode in (PadMode.HOLD, PadMode.LOOP):
                for v in self._voices:
                    if v.pad_index == pad_index:
                        v.active = False

            if len(self._voices) >= self.MAX_VOICES:
                self._voices.pop(0)

            sample_obj = self._samples.get(sid)
            seamless = bool(
                sample_obj is not None
                and getattr(sample_obj, "loop_ready", False)
            )
            self._voices.append(_Voice(
                sample_id=sid,
                audio=buf,
                loop=(mode == PadMode.LOOP),
                gate=(mode == PadMode.GATE),
                hold=(mode == PadMode.HOLD),
                pad_index=pad_index,
                group=group,
                loop_seamless=seamless,
            ))

        elif cmd.kind == "release":
            pad_index = cmd.payload["pad_index"]
            for v in self._voices:
                if v.pad_index == pad_index and v.gate:
                    # GATE: stop on release
                    v.active = False
                # HOLD: do NOT stop on release — keeps playing
                # LOOP: do NOT stop on release — manual stop needed

        elif cmd.kind == "stop_all":
            for v in self._voices:
                v.active = False

        elif cmd.kind == "stop_pad":
            pad_index = cmd.payload["pad_index"]
            for v in self._voices:
                if v.pad_index == pad_index:
                    v.active = False

        elif cmd.kind == "click":
            audio = cmd.payload["audio"]
            if audio is not None and len(audio) > 0:
                if len(self._voices) >= self.MAX_VOICES:
                    self._voices.pop(0)
                self._voices.append(_Voice(
                    sample_id="__metronome_click__",
                    audio=audio,
                    loop=False, gate=False, hold=False,
                    pad_index=-1, group=-1, active=True,
                ))

        elif cmd.kind == "fx_enable":
            chain = self._fx_chain(cmd.payload)
            if chain is not None:
                chain.set_enabled(cmd.payload["effect"],
                                  cmd.payload["enabled"])

        elif cmd.kind == "fx_param":
            chain = self._fx_chain(cmd.payload)
            if chain is not None:
                chain.set_param(cmd.payload["effect"],
                                cmd.payload["param"],
                                cmd.payload["value"])

    def _fx_chain(self, payload: dict) -> Optional[EffectsChain]:
        """Resolve an fx command payload to its target EffectsChain."""
        if payload.get("target") == "master":
            return self._master_chain
        return self._pad_chains.get(payload.get("pad_index", -1))

    # ---- Rendering -----------------------------------------------------

    def _render_sample(self, sample: Sample) -> Optional[np.ndarray]:
        """Render a sample with all effects baked in: pitch, time-stretch,
        cutoff, pan, fades, gain, reverse.

        Loop-ready samples (``sample.loop_ready=True``) that come from a stem
        get the "extra tail" trick: we load a short slice past ``end_sample``
        from the stem, process it through the same DSP, and at the end blend
        it into the first samples of the buffer. The buffer's sample 0 is
        then the natural continuation of sample length-1 — wrap is perfectly
        seamless, no crossfade needed at playback.
        """
        loop_ready = getattr(sample, "loop_ready", False)
        loop_beats = int(getattr(sample, "loop_beats", 0) or 0)
        # The "extras" bake works cleanly only when:
        #   - source is a stem (we can read audio past end_sample),
        #   - loop_beats == 0 (otherwise quantize-to-beats would warp the
        #     extras along with the loop and the bake math falls apart).
        can_bake = (
            loop_ready and loop_beats == 0
            and sample.source_stem_id
            and sample.source_stem_id in self._stem_audio
        )
        extra_raw = 0

        # 1) Load raw audio
        if sample.path and sample.path.exists():
            import soundfile as sf
            buf, sr = sf.read(str(sample.path), dtype="float32", always_2d=True)
            if sr != self.sample_rate:
                buf = self._resample(buf, sr, self.sample_rate)
            # Apply start/end crop if the sample defines a sub-region.
            # A path-based sample may still carry start/end relative to the file.
            total = len(buf)
            start = max(0, min(getattr(sample, "start_sample", 0), total))
            end = getattr(sample, "end_sample", 0)
            # Only crop if end is a meaningful value within the file and
            # the region is smaller than the whole file.
            if end and end > start and end <= total and (start > 0 or end < total):
                s2, e2 = self._snap_zero_crossings(buf, start, end)
                buf = buf[s2:e2].copy()
        elif sample.source_stem_id and sample.source_stem_id in self._stem_audio:
            src = self._stem_audio[sample.source_stem_id]
            start, end = self._snap_zero_crossings(
                src, sample.start_sample, sample.end_sample
            )
            if can_bake:
                # Pull up to 20 ms of audio past the loop end for the bake.
                target_extra = int(0.020 * self.sample_rate)
                extra_raw = min(target_extra, max(0, len(src) - end))
            buf = src[start:end + extra_raw].copy()
        else:
            log.warning("Sample %s has no playable source", sample.name)
            return None

        if buf.size == 0:
            return None

        if buf.shape[1] == 1:
            buf = np.repeat(buf, 2, axis=1)

        # 2) Reverse (BEFORE pitch/time so semantics are intuitive)
        if sample.reverse:
            buf = buf[::-1].copy()

        # 3) Pitch + time stretch (combined: per-sample + global pitch)
        total_pitch = sample.pitch_semitones + self._global_pitch_semitones
        if abs(total_pitch) > 0.01 or abs(sample.time_stretch - 1.0) > 0.01:
            buf = self._pitch_time(buf, total_pitch, sample.time_stretch)

        # 3b) NEW: Loop sync to BPM grid
        # When loop_beats > 0, fine-time-stretch the buffer so its length
        # equals exactly N beats at the sample (or project) BPM. This keeps
        # looped playback locked to the musical grid.
        loop_beats = int(getattr(sample, "loop_beats", 0) or 0)
        if loop_beats > 0:
            bpm = sample.bpm if sample.bpm else self._project_bpm
            if bpm and bpm > 0:
                buf = self._quantize_to_beats(buf, bpm, loop_beats)

        # 4a) High-pass filter (rumble / mud removal)
        highpass_hz = getattr(sample, "highpass_hz", 20.0)
        if highpass_hz > 21.0:  # only apply if user moved it off 20 Hz
            buf = self._apply_highpass(buf, highpass_hz)

        # 4) Cutoff (low-pass filter)
        cutoff_hz = getattr(sample, "cutoff_hz", 20000.0)
        if cutoff_hz < 19999.0:  # only apply if user moved it
            buf = self._apply_lowpass(buf, cutoff_hz)

        # 5) Pan (stereo positioning, -1.0 = full L, +1.0 = full R)
        pan = getattr(sample, "pan", 0.0)
        if abs(pan) > 0.01:
            buf = self._apply_pan(buf, pan)

        # 6) Gain
        if sample.gain_db != 0.0:
            buf *= 10 ** (sample.gain_db / 20.0)

        # 7) Boundary handling — three paths.
        n = len(buf)
        anti_click = min(int(0.002 * self.sample_rate), n // 4)

        if can_bake and extra_raw > 0:
            # Bake the extras into the start of the buffer so the wrap is
            # the natural continuation of the loop end.
            stretch = max(0.01, float(sample.time_stretch))
            extra_post = int(round(extra_raw * stretch))
            extra_post = min(extra_post, max(0, n - 64))
            if extra_post > 0:
                playable_len = n - extra_post
                xfade = min(extra_post, playable_len // 4)
                if xfade > 0:
                    ramp_in = np.linspace(
                        0.0, 1.0, xfade, dtype=np.float32)[:, None]
                    ramp_out = 1.0 - ramp_in
                    extras = buf[playable_len:playable_len + xfade].copy()
                    orig_start = buf[:xfade].copy()
                    buf[:xfade] = extras * ramp_out + orig_start * ramp_in
                buf = buf[:playable_len].copy()
            # No fades applied: zero-crossing snap on start/end keeps both
            # ends near zero, the bake makes the wrap continuous in waveform.
        elif loop_ready:
            # Stem-less or beat-locked loop: skip user fades, keep only the
            # tiny anti-click so wrap doesn't dip too much.
            fin = anti_click
            fout = anti_click
            if fin > 0:
                ramp = np.linspace(
                    0.0, 1.0, fin, dtype=np.float32)[:, None]
                buf[:fin] *= ramp
            if fout > 0:
                ramp = np.linspace(
                    1.0, 0.0, fout, dtype=np.float32)[:, None]
                buf[-fout:] *= ramp
        else:
            # Regular sample (one-shot, gate, hold): full user-controlled fades.
            fin = max(min(sample.fade_in_samples, n // 2), anti_click)
            fout = max(min(sample.fade_out_samples, n // 2), anti_click)
            if fin > 0:
                ramp = np.linspace(
                    0.0, 1.0, fin, dtype=np.float32)[:, None]
                buf[:fin] *= ramp
            if fout > 0:
                ramp = np.linspace(
                    1.0, 0.0, fout, dtype=np.float32)[:, None]
                buf[-fout:] *= ramp

        if sample.normalized:
            peak = float(np.max(np.abs(buf))) or 1.0
            buf /= peak

        return np.ascontiguousarray(buf, dtype=np.float32)

    def _snap_zero_crossings(self, src: np.ndarray, start: int, end: int,
                              search_window: int = 256) -> tuple[int, int]:
        n = len(src)
        start = max(0, min(start, n - 1))
        end = max(start + 1, min(end, n))

        def _nearest_zc(pos: int) -> int:
            lo = max(0, pos - search_window)
            hi = min(n - 1, pos + search_window)
            window = src[lo:hi, 0]
            if window.size < 2:
                return pos
            signs = np.signbit(window)
            zcs = np.where(np.diff(signs))[0]
            if len(zcs) == 0:
                return pos
            target = pos - lo
            best = zcs[np.argmin(np.abs(zcs - target))]
            return lo + int(best)

        return _nearest_zc(start), _nearest_zc(end)

    # ---- DSP -----------------------------------------------------------

    def _pitch_time(self, buf: np.ndarray, semitones: float,
                     stretch: float) -> np.ndarray:
        """
        Apply pitch shift + time stretch.

        Strategy (in order of preference):
          1. pyrubberband — best quality, may not be installed
          2. librosa — always available, decent quality
          3. simple resampling — last resort (changes pitch AND duration)
        """
        # Try pyrubberband first
        try:
            import pyrubberband as pyrb
            out = buf
            if abs(stretch - 1.0) > 0.01:
                out = pyrb.time_stretch(out, self.sample_rate, stretch)
            if abs(semitones) > 0.01:
                out = pyrb.pitch_shift(out, self.sample_rate, semitones)
            return np.ascontiguousarray(out.astype(np.float32))
        except Exception as e:
            log.debug("pyrubberband unavailable: %s", e)

        # Fallback: librosa
        try:
            import librosa
            # librosa works on mono or (channels, samples) — we have (samples, 2)
            # so we transpose
            mono_left = np.ascontiguousarray(buf[:, 0])
            mono_right = np.ascontiguousarray(buf[:, 1])

            if abs(stretch - 1.0) > 0.01:
                # librosa.effects.time_stretch: rate > 1 = faster, < 1 = slower
                # Our convention: time_stretch=2 means twice as long (slower)
                # So rate = 1 / stretch
                rate = 1.0 / max(0.01, stretch)
                mono_left = librosa.effects.time_stretch(mono_left, rate=rate)
                mono_right = librosa.effects.time_stretch(mono_right, rate=rate)

            if abs(semitones) > 0.01:
                mono_left = librosa.effects.pitch_shift(
                    mono_left, sr=self.sample_rate, n_steps=semitones
                )
                mono_right = librosa.effects.pitch_shift(
                    mono_right, sr=self.sample_rate, n_steps=semitones
                )

            min_len = min(len(mono_left), len(mono_right))
            out = np.stack([mono_left[:min_len], mono_right[:min_len]], axis=1)
            return np.ascontiguousarray(out.astype(np.float32))
        except Exception as e:
            log.warning("librosa pitch/time failed: %s", e)

        # Last resort: simple resampling for pitch (changes time too)
        if abs(semitones) > 0.01:
            try:
                import librosa
                rate = 2.0 ** (semitones / 12.0)
                indices = np.arange(0, len(buf), rate)
                indices = indices[indices < len(buf)].astype(int)
                return np.ascontiguousarray(buf[indices].astype(np.float32))
            except Exception:
                pass

        return buf

    def _quantize_to_beats(self, buf: np.ndarray, bpm: float,
                            target_beats: int) -> np.ndarray:
        """
        Stretch/compress audio so its total length matches exactly
        `target_beats` at the given BPM.

        Used for "Loop sync to BPM grid" — keeps loop wrap points musically
        accurate even when the source sample length is slightly off.
        """
        if bpm <= 0 or target_beats <= 0 or len(buf) == 0:
            return buf

        samples_per_beat = self.sample_rate * 60.0 / bpm
        target_samples = int(round(target_beats * samples_per_beat))
        if target_samples <= 0:
            return buf

        raw_samples = len(buf)
        # Tolerance: within 5ms = no adjustment needed
        if abs(target_samples - raw_samples) < self.sample_rate * 0.005:
            return buf

        stretch = target_samples / raw_samples
        # Clamp to avoid extreme stretches (>2x or <0.5x means wrong target)
        stretch = max(0.5, min(2.0, stretch))
        return self._pitch_time(buf, semitones=0.0, stretch=stretch)

    @staticmethod
    def suggest_loop_beats(sample_length_samples: int, sample_rate: int,
                            bpm: float) -> int:
        """
        Auto-detect the most likely beat count for a sample by snapping
        to the nearest power-of-2 or musically common beat count.
        Returns 1, 2, 4, 8, 16, or 32 (whatever is closest).
        """
        if bpm <= 0 or sample_length_samples <= 0:
            return 0
        samples_per_beat = sample_rate * 60.0 / bpm
        raw_beats = sample_length_samples / samples_per_beat
        # Common beat counts in music: 1, 2, 4, 8, 16, 32
        candidates = [1, 2, 4, 8, 16, 32]
        # Pick the one closest in log scale (musical perception)
        import math
        log_raw = math.log(max(0.5, raw_beats))
        best = min(candidates, key=lambda c: abs(math.log(c) - log_raw))
        return best

    def _apply_highpass(self, buf: np.ndarray, cutoff_hz: float) -> np.ndarray:
        """Apply high-pass filter (Butterworth, 2nd order, bidirectional)."""
        try:
            from scipy.signal import butter, sosfiltfilt
            nyq = self.sample_rate / 2.0
            normalized_cutoff = max(0.001, min(0.99, cutoff_hz / nyq))
            sos = butter(2, normalized_cutoff, btype="high", output="sos")
            out = np.empty_like(buf)
            for ch in range(buf.shape[1]):
                out[:, ch] = sosfiltfilt(sos, buf[:, ch])
            return np.ascontiguousarray(out.astype(np.float32))
        except Exception as e:
            log.debug("Highpass filter failed: %s", e)
            return buf

    def _apply_lowpass(self, buf: np.ndarray, cutoff_hz: float) -> np.ndarray:
        """Apply low-pass filter (Butterworth, 2nd order, bidirectional)."""
        try:
            from scipy.signal import butter, sosfiltfilt
            nyq = self.sample_rate / 2.0
            normalized_cutoff = max(0.001, min(0.99, cutoff_hz / nyq))
            sos = butter(2, normalized_cutoff, btype="low", output="sos")
            # Apply per channel
            out = np.empty_like(buf)
            for ch in range(buf.shape[1]):
                out[:, ch] = sosfiltfilt(sos, buf[:, ch])
            return np.ascontiguousarray(out.astype(np.float32))
        except Exception as e:
            log.debug("Lowpass filter failed: %s", e)
            return buf

    def _apply_pan(self, buf: np.ndarray, pan: float) -> np.ndarray:
        """
        Constant-power panning.
        pan: -1.0 (full L) to +1.0 (full R), 0.0 = center.
        Uses equal-power law to keep perceived loudness constant.
        """
        pan = max(-1.0, min(1.0, float(pan)))
        # Map [-1, 1] -> [0, pi/2]
        angle = (pan + 1.0) * 0.25 * np.pi
        gain_l = np.cos(angle)
        gain_r = np.sin(angle)
        # Mix stereo to mono first, then pan
        mono = buf.mean(axis=1)
        out = np.stack([mono * gain_l, mono * gain_r], axis=1)
        return np.ascontiguousarray(out.astype(np.float32))

    def _resample(self, data: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        try:
            import librosa
            out = librosa.resample(data.T, orig_sr=src_sr, target_sr=dst_sr).T
            return np.ascontiguousarray(out.astype(np.float32))
        except Exception:
            return data.astype(np.float32)