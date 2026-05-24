"""
Real-time audio effects — per-pad insert chains.

Each pad gets an independent :class:`EffectsChain`:

    EQ3Band -> Compressor -> Reverb -> Delay -> Chorus

Processors are *stateful*: they carry filter / delay-line state between audio
blocks, so the exact same code runs in the streaming audio callback and in the
offline export renderer.

Conventions
-----------
* All processors operate on float32 stereo blocks of shape ``(frames, 2)``.
* ``process()`` accepts any block length; time-based effects internally split
  the block so feedback never overlaps the write region of the same chunk.
* A disabled processor is skipped by the chain entirely (zero cost).
* A chain with nothing enabled passes audio through untouched.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

__all__ = [
    "EQ3Band", "Compressor", "Reverb", "Delay", "Chorus", "EffectsChain",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _blockwise(fn, x: np.ndarray, max_chunk: int) -> np.ndarray:
    """Apply ``fn`` to ``x`` in chunks of at most ``max_chunk`` frames.

    Feedback effects (delay, comb/allpass) are only vectorizable when the
    processed chunk is no longer than their shortest delay line — otherwise a
    block's writes would overlap its own reads. Splitting here keeps every
    processor fully vectorized regardless of the engine's block size.
    """
    n = len(x)
    max_chunk = max(1, int(max_chunk))
    if n <= max_chunk:
        return fn(x)
    out = np.empty_like(x)
    i = 0
    while i < n:
        j = min(i + max_chunk, n)
        out[i:j] = fn(x[i:j])
        i = j
    return out


# ---------------------------------------------------------------------------
# 3-band parametric EQ
# ---------------------------------------------------------------------------

def _peaking(sr: float, f0: float, gain_db: float, q: float):
    """RBJ cookbook peaking-EQ biquad. Returns (b, a), normalized by a0."""
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * f0 / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2.0 * max(0.05, q))
    b = np.array([1.0 + alpha * A, -2.0 * cw, 1.0 - alpha * A])
    a = np.array([1.0 + alpha / A, -2.0 * cw, 1.0 - alpha / A])
    return b / a[0], a / a[0]


def _shelf(sr: float, f0: float, gain_db: float, high: bool):
    """RBJ cookbook low/high-shelf biquad (slope S=1). Returns (b, a)."""
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * f0 / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / 2.0 * np.sqrt(2.0)
    ap = 2.0 * np.sqrt(A) * alpha
    if high:
        b = np.array([
            A * ((A + 1) + (A - 1) * cw + ap),
            -2.0 * A * ((A - 1) + (A + 1) * cw),
            A * ((A + 1) + (A - 1) * cw - ap),
        ])
        a = np.array([
            (A + 1) - (A - 1) * cw + ap,
            2.0 * ((A - 1) - (A + 1) * cw),
            (A + 1) - (A - 1) * cw - ap,
        ])
    else:
        b = np.array([
            A * ((A + 1) - (A - 1) * cw + ap),
            2.0 * A * ((A - 1) - (A + 1) * cw),
            A * ((A + 1) - (A - 1) * cw - ap),
        ])
        a = np.array([
            (A + 1) + (A - 1) * cw + ap,
            -2.0 * ((A - 1) + (A + 1) * cw),
            (A + 1) + (A - 1) * cw - ap,
        ])
    return b / a[0], a / a[0]


class EQ3Band:
    """Low-shelf + mid-peak + high-shelf parametric EQ (three biquads)."""

    def __init__(self, sample_rate: int):
        self.sr = float(sample_rate)
        self.low_gain_db = 0.0
        self.mid_gain_db = 0.0
        self.high_gain_db = 0.0
        self.low_freq = 120.0
        self.mid_freq = 1000.0
        self.high_freq = 6000.0
        self.mid_q = 0.9
        self._dirty = True
        self._bypassed = False
        self._coeffs: list[tuple[np.ndarray, np.ndarray]] = []
        self._zi = [np.zeros((2, 2)) for _ in range(3)]

    def reset(self) -> None:
        for zi in self._zi:
            zi.fill(0.0)
        self._bypassed = False

    def _recompute(self) -> None:
        self._coeffs = [
            _shelf(self.sr, self.low_freq, self.low_gain_db, high=False),
            _peaking(self.sr, self.mid_freq, self.mid_gain_db, self.mid_q),
            _shelf(self.sr, self.high_freq, self.high_gain_db, high=True),
        ]
        self._dirty = False

    def process(self, x: np.ndarray) -> np.ndarray:
        if len(x) == 0:
            return x
        # Bypass when all 3 bands are flat: a 0 dB biquad has b == a so it's
        # mathematically identity, but lfilter still pays the per-call cost.
        # This is the common "EQ enabled, gains untouched" case.
        if (abs(self.low_gain_db) < 0.05 and
                abs(self.mid_gain_db) < 0.05 and
                abs(self.high_gain_db) < 0.05):
            if not self._bypassed:
                # Drain state so re-engagement starts clean (no transient).
                for zi in self._zi:
                    zi.fill(0.0)
                self._bypassed = True
            return x
        self._bypassed = False
        if self._dirty:
            self._recompute()
        y = x.astype(np.float64)
        for i, (b, a) in enumerate(self._coeffs):
            y, self._zi[i] = lfilter(b, a, y, axis=0, zi=self._zi[i])
        return y.astype(np.float32)


# ---------------------------------------------------------------------------
# Compressor
# ---------------------------------------------------------------------------

class Compressor:
    """Feed-forward peak compressor with attack/release smoothing."""

    def __init__(self, sample_rate: int):
        self.sr = float(sample_rate)
        self.threshold_db = -18.0
        self.ratio = 4.0
        self.attack_ms = 10.0
        self.release_ms = 120.0
        self.makeup_db = 0.0
        self._env_db = 0.0       # current gain reduction in dB (<= 0)

    def reset(self) -> None:
        self._env_db = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        if n == 0:
            return x
        peak = np.maximum(np.abs(x[:, 0]), np.abs(x[:, 1]))
        peak = np.maximum(peak, 1e-9)
        level_db = 20.0 * np.log10(peak)
        over = level_db - self.threshold_db
        inv_ratio = 1.0 / max(1.0, self.ratio)
        target = np.where(over > 0.0, over * (inv_ratio - 1.0), 0.0)

        a_att = np.exp(-1.0 / max(1.0, self.attack_ms * 0.001 * self.sr))
        a_rel = np.exp(-1.0 / max(1.0, self.release_ms * 0.001 * self.sr))

        env = self._env_db
        gr = np.empty(n)
        for i in range(n):
            t = target[i]
            # moving toward MORE reduction -> attack, recovering -> release
            coef = a_att if t < env else a_rel
            env = t + coef * (env - t)
            gr[i] = env
        self._env_db = env

        gain = (10.0 ** ((gr + self.makeup_db) / 20.0)).astype(np.float32)
        return x * gain[:, None]


# ---------------------------------------------------------------------------
# Delay
# ---------------------------------------------------------------------------

class Delay:
    """Feedback delay line with wet/dry mix."""

    def __init__(self, sample_rate: int):
        self.sr = float(sample_rate)
        self.time_ms = 300.0
        self.feedback = 0.35
        self.mix = 0.30
        self._max = int(self.sr * 2.0) + 4      # 2 s ceiling
        self._buf = np.zeros((self._max, 2), dtype=np.float32)
        self._w = 0

    def reset(self) -> None:
        self._buf.fill(0.0)
        self._w = 0

    def process(self, x: np.ndarray) -> np.ndarray:
        if len(x) == 0:
            return x
        d = int(self.time_ms * 0.001 * self.sr)
        d = max(1, min(d, self._max - 1))
        return _blockwise(lambda c: self._chunk(c, d), x, d)

    def _chunk(self, c: np.ndarray, d: int) -> np.ndarray:
        L = len(c)
        m = self._max
        w = self._w
        fb = float(np.clip(self.feedback, 0.0, 0.95))
        mix = float(np.clip(self.mix, 0.0, 1.0))

        read_idx = np.arange(w + 1 - d, w + 1 - d + L) % m
        delayed = self._buf[read_idx]
        write_idx = np.arange(w + 1, w + 1 + L) % m
        self._buf[write_idx] = c + fb * delayed
        self._w = (w + L) % m
        return c * (1.0 - mix) + delayed * mix


# ---------------------------------------------------------------------------
# Chorus
# ---------------------------------------------------------------------------

class Chorus:
    """Single-voice chorus: LFO-modulated fractional delay."""

    def __init__(self, sample_rate: int):
        self.sr = float(sample_rate)
        self.rate_hz = 0.8
        self.depth_ms = 4.0
        self.base_ms = 18.0
        self.mix = 0.40
        self._max = int(self.sr * 0.06) + 8
        self._buf = np.zeros((self._max, 2), dtype=np.float32)
        self._w = 0
        self._phase = 0.0

    def reset(self) -> None:
        self._buf.fill(0.0)
        self._w = 0
        self._phase = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        L = len(x)
        if L == 0:
            return x
        m = self._max
        mix = float(np.clip(self.mix, 0.0, 1.0))

        write_idx = np.arange(self._w + 1, self._w + 1 + L) % m
        self._buf[write_idx] = x

        t = np.arange(L)
        omega = 2.0 * np.pi * self.rate_hz / self.sr
        phase = self._phase + omega * t
        delay = (self.base_ms + self.depth_ms * np.sin(phase)) * 0.001 * self.sr
        rpos = np.clip((self._w + 1 + t) - delay, 0.0, None)

        i0 = np.floor(rpos).astype(np.int64)
        frac = (rpos - i0).astype(np.float32)[:, None]
        a = self._buf[i0 % m]
        b = self._buf[(i0 + 1) % m]
        wet = a * (1.0 - frac) + b * frac

        self._w = (self._w + L) % m
        self._phase = float((self._phase + omega * L) % (2.0 * np.pi))
        return x * (1.0 - mix) + wet * mix


# ---------------------------------------------------------------------------
# Reverb (Freeverb-style: 8 parallel combs + 4 series allpasses per channel)
# ---------------------------------------------------------------------------

_COMB_TUNING = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617]
_ALLPASS_TUNING = [556, 441, 341, 225]
_STEREO_SPREAD = 23


class Reverb:
    """Schroeder/Freeverb reverberator with damping and stereo width."""

    def __init__(self, sample_rate: int):
        self.sr = float(sample_rate)
        self.room_size = 0.7
        self.damping = 0.4
        self.wet = 0.35
        self.dry = 0.70
        self.width = 1.0

        scale = self.sr / 44100.0
        self._comb_len = [
            [max(1, int(c * scale)) for c in _COMB_TUNING],
            [max(1, int((c + _STEREO_SPREAD) * scale)) for c in _COMB_TUNING],
        ]
        self._ap_len = [
            [max(1, int(a * scale)) for a in _ALLPASS_TUNING],
            [max(1, int((a + _STEREO_SPREAD) * scale)) for a in _ALLPASS_TUNING],
        ]
        self._comb_buf = [[np.zeros(l) for l in self._comb_len[ch]]
                          for ch in range(2)]
        self._comb_w = [[0] * 8 for _ in range(2)]
        self._comb_zi = [[np.zeros(1) for _ in range(8)] for _ in range(2)]
        self._ap_buf = [[np.zeros(l) for l in self._ap_len[ch]]
                        for ch in range(2)]
        self._ap_w = [[0] * 4 for _ in range(2)]

        self._comb_min = min(min(self._comb_len[0]),
                              min(self._comb_len[1]))
        self._ap_min = min(min(self._ap_len[0]),
                            min(self._ap_len[1]))
        self._feedback = 0.84
        self._damp = 0.2

    def reset(self) -> None:
        for ch in range(2):
            for buf in self._comb_buf[ch]:
                buf.fill(0.0)
            for buf in self._ap_buf[ch]:
                buf.fill(0.0)
            for zi in self._comb_zi[ch]:
                zi.fill(0.0)
            self._comb_w[ch] = [0] * 8
            self._ap_w[ch] = [0] * 4

    def process(self, x: np.ndarray) -> np.ndarray:
        if len(x) == 0:
            return x
        self._feedback = float(np.clip(self.room_size, 0.0, 1.0)) * 0.28 + 0.70
        self._damp = float(np.clip(self.damping, 0.0, 1.0)) * 0.5

        # Mono-summed input feeds both channel banks (Freeverb).
        mono = 0.5 * (x[:, 0].astype(np.float64) +
                       x[:, 1].astype(np.float64))
        inp = mono * 0.015      # Freeverb fixed input gain

        # Combs at FULL block: their delay lines (>= 1116 samples) are
        # always longer than a realistic engine block, so no sub-blocking
        # is needed for correctness. This is the big speed win.
        wet_l = _blockwise(lambda c: self._comb_stage(0, c), inp,
                            self._comb_min)
        wet_r = _blockwise(lambda c: self._comb_stage(1, c), inp,
                            self._comb_min)

        # Allpass chain: smallest delay (~225 samples) is below the typical
        # block size, so this stage still has to sub-block.
        wet_l = _blockwise(lambda c: self._allpass_stage(0, c), wet_l,
                            self._ap_min)
        wet_r = _blockwise(lambda c: self._allpass_stage(1, c), wet_r,
                            self._ap_min)

        w1 = self.wet * 0.5 * (1.0 + self.width)
        w2 = self.wet * 0.5 * (1.0 - self.width)
        out_l = x[:, 0] * self.dry + wet_l * w1 + wet_r * w2
        out_r = x[:, 1] * self.dry + wet_r * w1 + wet_l * w2
        return np.stack([out_l, out_r], axis=1).astype(np.float32)

    def _comb(self, ch: int, ci: int, inp: np.ndarray) -> np.ndarray:
        buf = self._comb_buf[ch][ci]
        clen = len(buf)
        w = self._comb_w[ch][ci]
        L = len(inp)
        idx = np.arange(w, w + L) % clen
        out = buf[idx].copy()
        # one-pole low-pass in the feedback path (damping)
        d = self._damp
        filtered, self._comb_zi[ch][ci] = lfilter(
            [1.0 - d], [1.0, -d], out, zi=self._comb_zi[ch][ci]
        )
        buf[idx] = inp + filtered * self._feedback
        self._comb_w[ch][ci] = (w + L) % clen
        return out

    def _allpass(self, ch: int, ai: int, inp: np.ndarray) -> np.ndarray:
        buf = self._ap_buf[ch][ai]
        alen = len(buf)
        w = self._ap_w[ch][ai]
        L = len(inp)
        idx = np.arange(w, w + L) % alen
        bufout = buf[idx].copy()
        out = -inp + bufout
        buf[idx] = inp + bufout * 0.5
        self._ap_w[ch][ai] = (w + L) % alen
        return out

    def _comb_stage(self, ch: int, inp: np.ndarray) -> np.ndarray:
        """Sum of 8 parallel comb filters for one channel."""
        acc = np.zeros(len(inp), dtype=np.float64)
        for ci in range(8):
            acc += self._comb(ch, ci, inp)
        return acc

    def _allpass_stage(self, ch: int, sig: np.ndarray) -> np.ndarray:
        """4 series allpass filters for one channel."""
        for ai in range(4):
            sig = self._allpass(ch, ai, sig)
        return sig


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------

class EffectsChain:
    """An ordered insert chain of the five processors.

    Effects run in the order EQ -> Compressor -> Reverb -> Delay -> Chorus.
    Each can be toggled independently; a disabled effect is skipped. The chain
    keeps a tail counter so the engine knows to keep feeding it silence while
    reverb/delay are still ringing after the input has stopped.
    """

    EFFECTS = ("eq", "comp", "reverb", "delay", "chorus")
    _TAIL_SECONDS = 3.0

    def __init__(self, sample_rate: int):
        self.sr = float(sample_rate)
        self.eq = EQ3Band(sample_rate)
        self.comp = Compressor(sample_rate)
        self.reverb = Reverb(sample_rate)
        self.delay = Delay(sample_rate)
        self.chorus = Chorus(sample_rate)
        self._enabled = {k: False for k in self.EFFECTS}
        self._tail_remaining = 0

    # ---- configuration ----

    def set_enabled(self, name: str, value: bool) -> None:
        if name in self._enabled:
            self._enabled[name] = bool(value)

    def is_enabled(self, name: str) -> bool:
        return self._enabled.get(name, False)

    def set_param(self, name: str, param: str, value: float) -> None:
        fx = getattr(self, name, None)
        if fx is None or name not in self.EFFECTS:
            return
        if hasattr(fx, param):
            setattr(fx, param, float(value))
            if name == "eq":
                fx._dirty = True

    def get_param(self, name: str, param: str, default: float = 0.0) -> float:
        fx = getattr(self, name, None)
        if fx is None or not hasattr(fx, param):
            return default
        return float(getattr(fx, param))

    @property
    def any_enabled(self) -> bool:
        return any(self._enabled.values())

    @property
    def is_ringing(self) -> bool:
        return self._tail_remaining > 0

    def reset(self) -> None:
        for name in self.EFFECTS:
            getattr(self, name).reset()
        self._tail_remaining = 0

    # ---- processing ----

    def process(self, x: np.ndarray) -> np.ndarray:
        if not self.any_enabled:
            return x
        y = x
        if self._enabled["eq"]:
            y = self.eq.process(y)
        if self._enabled["comp"]:
            y = self.comp.process(y)
        if self._enabled["reverb"]:
            y = self.reverb.process(y)
        if self._enabled["delay"]:
            y = self.delay.process(y)
        if self._enabled["chorus"]:
            y = self.chorus.process(y)

        if self._enabled["reverb"] or self._enabled["delay"]:
            if x.size and float(np.max(np.abs(x))) > 1e-5:
                self._tail_remaining = int(self.sr * self._TAIL_SECONDS)
            else:
                self._tail_remaining = max(0, self._tail_remaining - len(x))
                # Stop early once the wet tail has decayed below audibility,
                # rather than always running the full TAIL_SECONDS.
                if y.size and float(np.max(np.abs(y))) < 1e-4:
                    self._tail_remaining = 0
        else:
            self._tail_remaining = 0

        return np.ascontiguousarray(y, dtype=np.float32)
