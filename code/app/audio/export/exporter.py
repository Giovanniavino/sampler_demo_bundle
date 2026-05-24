"""
Offline export.

Two paths feed the same WAV writer:

* ``render_sequence`` — renders a :class:`RecordedSequence` deterministically
  into a stereo buffer. Each pad's voices are summed into a per-pad timeline,
  run through that pad's effects chain, then mixed into the master (which gets
  the master chain). Event timestamps map to sample-accurate offsets.
* the live bounce — the engine captures its real-time output to memory; the
  controller hands that buffer straight to :func:`write_wav`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from app.audio.dsp.effects import EffectsChain
from app.audio.recording.recording import EventKind, RecordedSequence
from app.core.models import Pad, PadMode

log = logging.getLogger(__name__)

_RENDER_BLOCK = 8192          # effects are run over the timeline in chunks
_RELEASE_FADE_SEC = 0.005     # anti-click fade when a voice is cut short
_TAIL_SEC = 3.0               # headroom for reverb / delay tails


def write_wav(path, audio: np.ndarray, sample_rate: int) -> Path:
    """Write a stereo float buffer to a 16-bit WAV file."""
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    if data.ndim == 1:
        data = np.stack([data, data], axis=1)
    sf.write(str(path), data, int(sample_rate), subtype="PCM_16")
    log.info("Wrote WAV: %s (%d frames)", path, len(data))
    return path


def render_sequence(sequence: RecordedSequence,
                     sample_buffers: dict[str, np.ndarray],
                     pads: list[Pad],
                     sample_rate: int,
                     pad_chains: Optional[dict[int, EffectsChain]] = None,
                     master_chain: Optional[EffectsChain] = None
                     ) -> np.ndarray:
    """Render a recorded sequence offline into a stereo float32 buffer.

    ``sample_buffers`` maps sample id -> already-rendered stereo audio (the
    engine's baked buffers). ``pads`` supplies pad index -> sample id + mode.
    Effects chains, if given, are reset before use and processed block-wise.
    """
    pad_by_index = {p.index: p for p in pads}
    events = sorted(sequence.events, key=lambda e: e.timestamp_ms)

    def to_samples(ms: float) -> int:
        return int(round(ms / 1000.0 * sample_rate))

    # Total render length: sequence duration, extended to fit any sample
    # that is still playing when the sequence ends.
    total = to_samples(sequence.duration_ms)
    for ev in events:
        if ev.kind != EventKind.NOTE_ON:
            continue
        pad = pad_by_index.get(ev.pad_index)
        if not pad or not pad.sample_id:
            continue
        buf = sample_buffers.get(pad.sample_id)
        if buf is None:
            continue
        total = max(total, to_samples(ev.timestamp_ms) + len(buf))

    if total <= 0:
        return np.zeros((0, 2), dtype=np.float32)
    total += int(sample_rate * _TAIL_SEC)

    # Sum each pad's voices into its own timeline buffer.
    per_pad: dict[int, np.ndarray] = {}
    for i, ev in enumerate(events):
        if ev.kind != EventKind.NOTE_ON:
            continue
        pad = pad_by_index.get(ev.pad_index)
        if not pad or not pad.sample_id:
            continue
        buf = sample_buffers.get(pad.sample_id)
        if buf is None or len(buf) == 0:
            continue

        onset = to_samples(ev.timestamp_ms)
        if onset >= total:
            continue

        next_off, next_on = _next_events(events, i, ev.pad_index, to_samples)
        seg = _render_voice(buf, pad.mode, onset, next_off, next_on,
                            total, sample_rate)
        if seg is None:
            continue

        pbuf = per_pad.get(ev.pad_index)
        if pbuf is None:
            pbuf = np.zeros((total, 2), dtype=np.float32)
            per_pad[ev.pad_index] = pbuf
        end = min(total, onset + len(seg))
        pbuf[onset:end] += seg[:end - onset]

    # Mix pads (through their chains) into the master, then the master chain.
    master = np.zeros((total, 2), dtype=np.float32)
    for pad_index, pbuf in per_pad.items():
        chain = pad_chains.get(pad_index) if pad_chains else None
        if chain is not None and chain.any_enabled:
            chain.reset()
            master += _process_in_blocks(chain, pbuf)
        else:
            master += pbuf

    if master_chain is not None and master_chain.any_enabled:
        master_chain.reset()
        master = _process_in_blocks(master_chain, master)

    np.clip(master, -1.0, 1.0, out=master)
    return master


def _next_events(events, i, pad_index, to_samples):
    """Return (next NOTE_OFF, next NOTE_ON) sample offsets for this pad."""
    next_off = None
    next_on = None
    for ev in events[i + 1:]:
        if ev.pad_index != pad_index:
            continue
        if ev.kind == EventKind.NOTE_OFF and next_off is None:
            next_off = to_samples(ev.timestamp_ms)
        elif ev.kind == EventKind.NOTE_ON and next_on is None:
            next_on = to_samples(ev.timestamp_ms)
        if next_off is not None and next_on is not None:
            break
    return next_off, next_on


def _render_voice(buf, mode, onset, next_off, next_on, total, sr):
    """Build one voice segment for a NOTE_ON, honoring its pad mode."""
    buf_len = len(buf)

    if mode == PadMode.LOOP:
        stop = next_off if next_off is not None else total
        length = min(stop, total) - onset
        if length <= 0:
            return None
        reps = int(np.ceil(length / buf_len))
        return np.tile(buf, (reps, 1))[:length]

    if mode == PadMode.GATE:
        stop = next_off if next_off is not None else onset + buf_len
        length = min(max(0, stop - onset), buf_len)
        if length <= 0:
            return None
        seg = buf[:length].copy()
        _apply_release_fade(seg, sr)
        return seg

    if mode == PadMode.HOLD:
        stop = next_on if next_on is not None else onset + buf_len
        length = min(max(0, stop - onset), buf_len)
        if length <= 0:
            return None
        seg = buf[:length].copy()
        if length < buf_len:
            _apply_release_fade(seg, sr)
        return seg

    return buf  # ONE_SHOT: full sample


def _apply_release_fade(seg, sr):
    n = min(len(seg), max(1, int(_RELEASE_FADE_SEC * sr)))
    if n > 1:
        seg[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)[:, None]


def _process_in_blocks(chain: EffectsChain, buf: np.ndarray) -> np.ndarray:
    out = np.empty_like(buf)
    n = len(buf)
    i = 0
    while i < n:
        j = min(i + _RENDER_BLOCK, n)
        out[i:j] = chain.process(buf[i:j])
        i = j
    return out
