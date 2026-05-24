"""Tests for the per-pad DSP effects module (app.audio.dsp.effects)."""

import numpy as np
import pytest

from app.audio.dsp.effects import (
    Chorus, Compressor, Delay, EffectsChain, EQ3Band, Reverb,
)

SR = 44100


def _sine(freq, n, amp=0.5):
    t = np.arange(n) / SR
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def _silence(n):
    return np.zeros((n, 2), dtype=np.float32)


def _finite_stereo(out, n):
    assert out.shape == (n, 2)
    assert out.dtype == np.float32
    assert np.all(np.isfinite(out))


# ---------------------------------------------------------------------------
# Per-processor sanity: shape, dtype, finiteness, silence stays silent-ish
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("factory", [EQ3Band, Compressor, Reverb, Delay, Chorus])
def test_processor_silence_in_finite_out(factory):
    fx = factory(SR)
    out = fx.process(_silence(512))
    _finite_stereo(out, 512)
    assert np.max(np.abs(out)) < 1e-6


@pytest.mark.parametrize("factory", [EQ3Band, Compressor, Reverb, Delay, Chorus])
def test_processor_signal_in_finite_out(factory):
    fx = factory(SR)
    out = fx.process(_sine(440, 1024))
    _finite_stereo(out, 1024)


@pytest.mark.parametrize("factory", [EQ3Band, Compressor, Reverb, Delay, Chorus])
def test_processor_empty_block(factory):
    fx = factory(SR)
    out = fx.process(_silence(0))
    assert out.shape == (0, 2)


# ---------------------------------------------------------------------------
# EQ: shelves actually boost / cut
# ---------------------------------------------------------------------------

def test_eq_high_shelf_boost_and_cut():
    sig = _sine(12000, 4096, amp=0.3)
    in_rms = float(np.sqrt(np.mean(sig ** 2)))

    boost = EQ3Band(SR)
    boost.high_gain_db = 12.0
    out_rms = float(np.sqrt(np.mean(boost.process(sig) ** 2)))
    assert out_rms > in_rms * 1.5

    cut = EQ3Band(SR)
    cut.high_gain_db = -12.0
    out_rms = float(np.sqrt(np.mean(cut.process(sig) ** 2)))
    assert out_rms < in_rms * 0.7


def test_eq_flat_is_near_identity():
    """All gains at 0 dB -> output matches input closely."""
    sig = _sine(1000, 2048, amp=0.4)
    out = EQ3Band(SR).process(sig)
    assert np.max(np.abs(out - sig)) < 1e-3


# ---------------------------------------------------------------------------
# Compressor: loud signal turned down, quiet signal left alone
# ---------------------------------------------------------------------------

def test_compressor_reduces_loud_signal():
    comp = Compressor(SR)
    comp.threshold_db = -18.0
    comp.ratio = 8.0
    loud = _sine(440, SR, amp=0.9)        # 1 s, well above threshold
    out = comp.process(loud)
    tail = out[-SR // 4:]                  # after the envelope settles
    assert np.max(np.abs(tail)) < 0.45
    assert np.max(np.abs(tail)) < np.max(np.abs(loud))


def test_compressor_passes_quiet_signal():
    comp = Compressor(SR)
    comp.threshold_db = -18.0
    comp.ratio = 8.0
    quiet = _sine(440, 2048, amp=0.02)     # below threshold
    out = comp.process(quiet)
    assert np.max(np.abs(out - quiet)) < 1e-3


# ---------------------------------------------------------------------------
# Delay: an impulse reappears one delay-time later
# ---------------------------------------------------------------------------

def test_delay_echo_appears_later():
    delay = Delay(SR)
    delay.time_ms = 512.0 / SR * 1000.0    # exactly 512 samples
    delay.feedback = 0.5
    delay.mix = 1.0                        # fully wet

    impulse = _silence(256)
    impulse[0] = [1.0, 1.0]
    block0 = delay.process(impulse)
    block1 = delay.process(_silence(256))
    block2 = delay.process(_silence(256))

    assert np.sum(np.abs(block0)) < 1e-6   # dry suppressed by mix=1
    assert np.sum(np.abs(block1)) < 1e-6
    assert np.sum(np.abs(block2)) > 0.5    # the echo lands here


# ---------------------------------------------------------------------------
# Reverb: an impulse produces a decaying tail
# ---------------------------------------------------------------------------

def test_reverb_produces_tail():
    reverb = Reverb(SR)
    impulse = _silence(512)
    impulse[0] = [1.0, 1.0]
    reverb.process(impulse)
    tail_energy = 0.0
    for _ in range(20):
        blk = reverb.process(_silence(512))
        _finite_stereo(blk, 512)
        tail_energy += float(np.sum(np.abs(blk)))
    assert tail_energy > 0.0


# ---------------------------------------------------------------------------
# Block-size independence: state carries correctly across calls
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("factory", [Delay, Reverb])
def test_block_split_matches_single_call(factory):
    np.random.seed(1)
    sig = (np.random.randn(2000, 2).astype(np.float32) * 0.2)

    whole = factory(SR).process(sig.copy())

    chunked_fx = factory(SR)
    pieces = [chunked_fx.process(sig[i:i + 333].copy())
              for i in range(0, len(sig), 333)]
    chunked = np.concatenate(pieces, axis=0)

    assert np.max(np.abs(whole - chunked)) < 1e-4


# ---------------------------------------------------------------------------
# EffectsChain
# ---------------------------------------------------------------------------

def test_chain_disabled_is_passthrough():
    chain = EffectsChain(SR)
    sig = _sine(440, 512)
    out = chain.process(sig)
    assert np.array_equal(out, sig)
    assert not chain.any_enabled


def test_chain_enabled_effect_changes_signal():
    chain = EffectsChain(SR)
    chain.set_enabled("reverb", True)
    sig = _sine(440, 512, amp=0.5)
    out = chain.process(sig)
    _finite_stereo(out, 512)
    assert np.max(np.abs(out - sig)) > 1e-4


def test_chain_set_param_routes_to_processor():
    chain = EffectsChain(SR)
    chain.set_param("delay", "feedback", 0.6)
    assert chain.delay.feedback == pytest.approx(0.6)
    chain.set_param("eq", "mid_gain_db", -4.0)
    assert chain.eq.mid_gain_db == pytest.approx(-4.0)
    assert chain.eq._dirty


def test_chain_reverb_tail_tracking():
    chain = EffectsChain(SR)
    chain.set_enabled("reverb", True)
    chain.process(_sine(440, 512, amp=0.8))
    assert chain.is_ringing
    chain.process(_silence(int(SR * 4)))    # 4 s of silence > 3 s tail
    assert not chain.is_ringing


def test_chain_no_tail_without_time_effects():
    chain = EffectsChain(SR)
    chain.set_enabled("eq", True)
    chain.process(_sine(440, 512, amp=0.8))
    assert not chain.is_ringing
