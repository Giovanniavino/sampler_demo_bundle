"""Tests for the v3 fixes: NR levels, drum quantize, settings, normalize."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.audio.dsp.noise_reduction import reduce_noise_array
from app.audio.slicing.auto_slicer import AutoSlicer, SlicerConfig
from app.core.models import AnalysisResult, Beat, Stem, StemType, Transient
from app.core.settings import AppSettings, PlaybackSettings


# ---------------------------------------------------------------------------
# Noise reduction levels
# ---------------------------------------------------------------------------

def _make_test_signal(sr: int = 22050, dur: float = 1.0,
                       freq: float = 440, noise: float = 0.05) -> np.ndarray:
    t = np.linspace(0, dur, int(sr * dur), dtype=np.float32)
    clean = np.sin(2 * np.pi * freq * t)
    noisy = clean + np.random.randn(len(t)).astype(np.float32) * noise
    return np.stack([noisy, noisy], axis=1)


def test_nr_off_is_passthrough():
    """'off' must not modify the signal."""
    sig = _make_test_signal()
    out = reduce_noise_array(sig, 22050, profile="off")
    np.testing.assert_array_equal(sig, out)


def test_nr_light_preserves_most_energy():
    """Light NR should keep at least 70% of RMS (was killing 80% before)."""
    sig = _make_test_signal()
    out = reduce_noise_array(sig, 22050, profile="light")
    rms_in = np.sqrt(np.mean(sig ** 2))
    rms_out = np.sqrt(np.mean(out ** 2))
    ratio = rms_out / rms_in
    assert ratio > 0.7, f"Light NR killed too much energy: ratio={ratio:.2f}"


def test_nr_unknown_profile_passthrough():
    sig = _make_test_signal()
    out = reduce_noise_array(sig, 22050, profile="not_a_thing")
    # Should return audio unchanged (or close to it) on unknown profile
    assert out.shape == sig.shape
    assert out.dtype == np.float32


# ---------------------------------------------------------------------------
# Drum 16th-note quantize
# ---------------------------------------------------------------------------

def test_sixteenth_grid_construction():
    slicer = AutoSlicer()
    # Beats at 0, 22050, 44100 (one beat = 0.5s @ 44.1kHz)
    beats = [0, 22050, 44100]
    grid = slicer._build_sixteenth_grid(beats)
    # Expect 4 points per beat interval -> 8 + final endpoint = 9
    assert len(grid) == 9
    # First and last must be at beat positions
    assert grid[0] == 0
    assert grid[-1] == 44100
    # Step should be 5512 samples (22050/4)
    assert abs(grid[1] - 5512) <= 1


def test_quantize_snaps_within_tolerance():
    slicer = AutoSlicer()
    grid = [0, 5000, 10000, 15000]
    tolerance = 500
    # Within tolerance -> snap
    assert slicer._quantize_to_grid(5300, grid, tolerance) == 5000
    # Just outside -> keep
    assert slicer._quantize_to_grid(5800, grid, tolerance) == 5800
    # Empty grid -> keep
    assert slicer._quantize_to_grid(1234, [], 100) == 1234
    # Zero tolerance -> keep
    assert slicer._quantize_to_grid(5100, grid, 0) == 5100


def test_quantize_picks_nearest_neighbor():
    slicer = AutoSlicer()
    grid = [0, 1000, 2000, 3000]
    # 1700 is closer to 2000 (300) than to 1000 (700)
    assert slicer._quantize_to_grid(1700, grid, 500) == 2000
    # 1200 is closer to 1000 (200) than to 2000 (800)
    assert slicer._quantize_to_grid(1200, grid, 500) == 1000


# ---------------------------------------------------------------------------
# Settings persistence + NR levels
# ---------------------------------------------------------------------------

def test_settings_save_load_roundtrip(tmp_path: Path):
    p = tmp_path / "settings.json"
    s = AppSettings()
    s.quality_mode = "fast"
    s.playback.nr_level_pre = "light"
    s.playback.nr_level_post = "off"
    s.playback.press_hold_loop = False
    s.save(p)
    loaded = AppSettings.load(p)
    assert loaded.quality_mode == "fast"
    assert loaded.playback.nr_level_pre == "light"
    assert loaded.playback.nr_level_post == "off"
    assert loaded.playback.press_hold_loop is False


def test_settings_nr_helpers_respect_levels():
    s = AppSettings()
    s.playback.nr_level_pre = "off"
    s.playback.nr_level_post = "off"
    assert s.noise_reduction_pre is False
    assert s.noise_reduction_post is False

    s.playback.nr_level_pre = "light"
    s.playback.nr_level_post = "strong"
    assert s.noise_reduction_pre is True
    assert s.noise_reduction_post is True
    assert s.nr_pre_profile == "light"
    assert s.nr_post_profile == "strong"


def test_press_hold_loop_default_off():
    """Was True by default, caused the double-trigger bug. Must default False."""
    s = PlaybackSettings()
    assert s.press_hold_loop is False
