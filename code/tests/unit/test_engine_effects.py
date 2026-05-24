"""Engine tests: per-pad effects routing and live output capture."""

import numpy as np

from app.audio.playback.engine import SounddevicePlaybackEngine
from app.core.models import Pad, PadMode, Sample

SR = 44100
BLK = 512


def _tone(n, amp=0.4, freq=220.0):
    t = np.arange(n) / SR
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.ascontiguousarray(np.stack([mono, mono], axis=1))


def _new_engine(sample_id, buf):
    eng = SounddevicePlaybackEngine(sample_rate=SR, block_size=BLK)
    eng._sample_buffers[sample_id] = buf
    return eng


def _render_one(eng):
    out = np.zeros((BLK, 2), dtype=np.float32)
    eng._callback(out, BLK, None, None)
    return out


def test_disabled_chains_are_exact_passthrough():
    """With no effects enabled, output equals the raw voice audio."""
    tone = _tone(BLK)
    sample = Sample(name="p")
    pad = Pad(index=0, sample_id=sample.id)
    eng = _new_engine(sample.id, tone)
    eng.trigger_pad(pad, sample)
    out = _render_one(eng)
    np.testing.assert_allclose(out, tone, atol=1e-6)


def test_pad_effect_changes_output():
    tone = _tone(4096)
    sample = Sample(name="t")
    pad = Pad(index=0, sample_id=sample.id)

    control = _new_engine(sample.id, tone)
    control.trigger_pad(pad, sample)
    out_dry = _render_one(control)

    wet = _new_engine(sample.id, tone)
    wet.set_pad_effect_enabled(0, "reverb", True)
    wet.trigger_pad(pad, sample)
    out_wet = _render_one(wet)

    assert np.any(np.abs(out_dry) > 1e-4)
    assert np.max(np.abs(out_wet - out_dry)) > 1e-4


def test_pad_effect_only_affects_its_pad():
    """Enabling an effect on pad 5 must not change a voice on pad 0."""
    tone = _tone(4096)
    sample = Sample(name="t")
    pad0 = Pad(index=0, sample_id=sample.id)

    control = _new_engine(sample.id, tone)
    control.trigger_pad(pad0, sample)
    out_dry = _render_one(control)

    other = _new_engine(sample.id, tone)
    other.set_pad_effect_enabled(5, "reverb", True)
    other.trigger_pad(pad0, sample)
    out = _render_one(other)

    np.testing.assert_allclose(out, out_dry, atol=1e-6)


def test_master_effect_changes_output():
    tone = _tone(4096)
    sample = Sample(name="m")
    pad = Pad(index=2, sample_id=sample.id)

    control = _new_engine(sample.id, tone)
    control.trigger_pad(pad, sample)
    out_dry = _render_one(control)

    wet = _new_engine(sample.id, tone)
    wet.set_master_effect_enabled("reverb", True)
    wet.set_master_effect_param("reverb", "wet", 0.5)
    wet.trigger_pad(pad, sample)
    out = _render_one(wet)

    assert np.max(np.abs(out - out_dry)) > 1e-4


def test_metronome_click_bypasses_pad_effects():
    eng = SounddevicePlaybackEngine(sample_rate=SR, block_size=BLK)
    for i in range(eng.MAX_PADS):
        eng.set_pad_effect_enabled(i, "reverb", True)
    click = _tone(256)
    eng.trigger_click(click)
    out = _render_one(eng)
    # The click is 256 frames; bypassing effects, the rest of the 512-frame
    # block stays exact silence (a reverb tail would smear it).
    assert np.any(np.abs(out[:256]) > 1e-4)
    assert np.max(np.abs(out[256:])) < 1e-6


def test_output_capture_records_master():
    tone = _tone(2000)
    sample = Sample(name="c")
    pad = Pad(index=1, sample_id=sample.id)
    eng = _new_engine(sample.id, tone)

    eng.start_capture()
    assert eng.is_capturing
    eng.trigger_pad(pad, sample)
    for _ in range(4):
        _render_one(eng)
    rec = eng.stop_capture()

    assert not eng.is_capturing
    assert rec is not None
    assert rec.shape == (4 * BLK, 2)
    assert np.any(np.abs(rec) > 1e-4)


def test_loop_retrigger_does_not_stack_voices():
    """Re-triggering a LOOP pad replaces the voice instead of stacking."""
    tone = _tone(BLK * 4)
    sample = Sample(name="loop")
    pad = Pad(index=0, sample_id=sample.id, mode=PadMode.LOOP)
    eng = _new_engine(sample.id, tone)
    eng.trigger_pad(pad, sample)
    eng.trigger_pad(pad, sample)
    eng.trigger_pad(pad, sample)
    _render_one(eng)
    active = [v for v in eng._voices if v.active and v.pad_index == 0]
    assert len(active) == 1


def test_one_shot_with_choke_self_does_not_stack():
    """ONE_SHOT pads with choke_self set replace instead of stacking."""
    tone = _tone(BLK * 8)
    sample = Sample(name="cs")
    pad = Pad(index=0, sample_id=sample.id, mode=PadMode.ONE_SHOT,
              choke_self=True)
    eng = _new_engine(sample.id, tone)
    eng.trigger_pad(pad, sample)
    eng.trigger_pad(pad, sample)
    eng.trigger_pad(pad, sample)
    _render_one(eng)
    active = [v for v in eng._voices if v.active and v.pad_index == 0]
    assert len(active) == 1


def test_one_shot_without_choke_self_still_stacks():
    """ONE_SHOT pads without choke_self keep stacking — drum-roll friendly."""
    tone = _tone(BLK * 8)
    sample = Sample(name="stack")
    pad = Pad(index=0, sample_id=sample.id, mode=PadMode.ONE_SHOT)
    eng = _new_engine(sample.id, tone)
    eng.trigger_pad(pad, sample)
    eng.trigger_pad(pad, sample)
    eng.trigger_pad(pad, sample)
    _render_one(eng)
    active = [v for v in eng._voices if v.active and v.pad_index == 0]
    assert len(active) == 3
