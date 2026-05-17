"""End-to-end pipeline test using synthetic audio.

This is the most important test in the project: if this passes, the whole
flow from audio file to playable pads works.
"""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.audio.separation.separator import BandSplitSeparator
from app.services.pipeline import SamplerPipeline


@pytest.fixture
def synthetic_song(tmp_path: Path) -> Path:
    """Generate a 4-second 120 BPM kick+hat track."""
    sr = 44100
    duration_s = 4.0
    bpm = 120.0
    beat_sec = 60.0 / bpm
    n = int(sr * duration_s)
    mix = np.zeros(n, dtype=np.float32)

    # Kick on every beat
    for i in range(int(duration_s / beat_sec)):
        start = int(i * beat_sec * sr)
        kick_len = int(0.2 * sr)
        t = np.arange(kick_len) / sr
        freq = 120 * np.exp(-t * 30) + 40
        kick = np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-t * 8)
        end = min(start + kick_len, n)
        mix[start:end] += kick[:end - start] * 0.8

    # Hi-hat on offbeats
    rng = np.random.RandomState(42)
    for i in range(int(duration_s / beat_sec * 2)):
        start = int(i * beat_sec * 0.5 * sr)
        hh_len = int(0.05 * sr)
        noise = rng.randn(hh_len).astype(np.float32)
        env = np.exp(-np.arange(hh_len) / sr * 60)
        end = min(start + hh_len, n)
        mix[start:end] += noise[:end - start] * env[:end - start] * 0.2

    mix = (mix / max(abs(mix).max(), 1e-9) * 0.7).astype(np.float32)
    stereo = np.column_stack([mix, mix])

    out = tmp_path / "test_song.wav"
    sf.write(str(out), stereo, sr)
    return out


def test_full_pipeline_band_split(synthetic_song: Path, tmp_path: Path):
    """The full pipeline must produce stems, analysis, samples, and pads."""
    pipeline = SamplerPipeline(
        cache_dir=tmp_path / "cache",
        separator=BandSplitSeparator(),
    )
    project = pipeline.import_track(synthetic_song)

    # Stems: band split produces 3
    assert len(project.stems) == 3
    stem_types = {s.stem_type.value for s in project.stems}
    assert stem_types == {"bass", "drums", "other"}
    # Each stem file must exist and have correct duration
    for stem in project.stems:
        assert stem.path.exists()
        info = sf.info(str(stem.path))
        assert info.frames == stem.duration_samples

    # Analysis: BPM should be in the ballpark of 120
    assert len(project.analyses) == 1
    analysis = project.analyses[0]
    assert 100 < analysis.bpm < 140, f"Bad BPM: {analysis.bpm}"
    assert len(analysis.beats) >= 4
    assert len(analysis.transients) >= 4

    # Samples: must produce at least drum hits
    assert len(project.samples) > 0
    has_drum_hits = any(s.category.value == "drum_hit" for s in project.samples)
    assert has_drum_hits, "No drum hits produced from clearly percussive material"

    # Pads: at least the drum row must be filled
    bank = project.active_bank()
    assert bank is not None
    drum_pads_filled = sum(1 for p in bank.pads[:4] if p.sample_id is not None)
    assert drum_pads_filled >= 1, "Drum row should have at least 1 pad"


def test_pipeline_rejects_missing_file(tmp_path: Path):
    pipeline = SamplerPipeline(
        cache_dir=tmp_path / "cache",
        separator=BandSplitSeparator(),
    )
    with pytest.raises(FileNotFoundError):
        pipeline.import_track(Path("/nonexistent/file.wav"))
