import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

pytest.importorskip("torch")

from app.audio.separation.separator import DemucsSeparator
from app.core.models import AudioSource, StemType


class _FakeModel:
    samplerate = 44100
    sources = ["vocals", "drums", "bass", "other"]

    def to(self, device):
        self.device = device
        return self

    def eval(self):
        return self


def _fake_apply_model(captured: dict, model: _FakeModel, wav):
    captured["shape"] = tuple(wav.shape)
    captured["device"] = str(wav.device)
    return wav.unsqueeze(1).repeat(1, len(model.sources), 1, 1)


def test_demucs_separator_uses_soundfile_io_without_torchaudio(monkeypatch, tmp_path: Path):
    samples = 4096
    left = np.linspace(-0.5, 0.5, samples, dtype=np.float32)
    right = np.linspace(0.5, -0.5, samples, dtype=np.float32)
    stereo = np.column_stack([left, right])

    audio_path = tmp_path / "input.wav"
    sf.write(str(audio_path), stereo, 44100)
    source = AudioSource(
        path=audio_path,
        sample_rate=44100,
        channels=2,
        duration_samples=samples,
    )

    separator = DemucsSeparator(device="cpu")
    fake_model = _FakeModel()
    captured: dict = {}

    monkeypatch.setattr(separator, "_load_model", lambda: fake_model)
    monkeypatch.setattr(
        separator,
        "_apply_model",
        lambda model, wav: _fake_apply_model(captured, model, wav),
    )
    monkeypatch.setitem(sys.modules, "torchaudio", None)

    stems = separator.separate(source, tmp_path / "stems")

    assert captured["shape"] == (1, 2, samples)
    assert len(stems) == 4
    assert {stem.stem_type for stem in stems} == {
        StemType.VOCALS,
        StemType.DRUMS,
        StemType.BASS,
        StemType.OTHER,
    }
    for stem in stems:
        assert stem.path is not None and stem.path.exists()
        info = sf.info(str(stem.path))
        assert info.frames == samples
        assert info.channels == 2
        assert stem.sample_rate == 44100
        assert stem.duration_samples == samples
