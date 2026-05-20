import numpy as np
import pytest

pytest.importorskip("PyQt6.QtCore")

from PyQt6.QtCore import QCoreApplication

from app.audio.metronome import Metronome
from app.audio.playback.engine import SounddevicePlaybackEngine
from app.core.models import Pad, PadBank, Project, Sample, Stem, StemType
from app.ui.controllers.sampler_controller import SamplerController


@pytest.fixture
def qt_app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


class _DummyEngine:
    def __init__(self):
        self.sample_rate = 44100
        self.register_calls: list[tuple[int, int]] = []
        self.stop_pad_calls: list[int] = []
        self.voice_state = (False, 0.0)

    def start(self):
        pass

    def stop(self):
        pass

    def load_stems(self, stems):
        pass

    def register_sample(self, sample):
        self.register_calls.append((sample.start_sample, sample.end_sample))

    def release_pad(self, pad):
        pass

    def stop_pad_voices(self, pad_index: int):
        self.stop_pad_calls.append(pad_index)
        return True

    def get_pad_voice_state(self, pad_index: int):
        return self.voice_state


def test_trim_preview_does_not_rerender_until_commit(monkeypatch, qt_app, tmp_path):
    def fake_rebuild_engine(self):
        self.engine = _DummyEngine()

    monkeypatch.setattr(SamplerController, "_rebuild_engine", fake_rebuild_engine)

    controller = SamplerController(cache_dir=tmp_path, use_demucs=False)
    stem = Stem(stem_type=StemType.DRUMS, sample_rate=1000, duration_samples=10000)
    sample = Sample(name="trim", source_stem_id=stem.id, start_sample=1000, end_sample=5000)
    pad = Pad(index=0, sample_id=sample.id)
    bank = PadBank(name="A", pads=[pad])
    controller._project = Project(
        stems=[stem],
        samples=[sample],
        banks=[bank],
        active_bank_id=bank.id,
    )
    controller.selectPad(0)
    controller.engine.register_calls.clear()

    controller.previewCurrentSampleRegion(0.2, 0.6)

    assert sample.start_sample == 2000
    assert sample.end_sample == 6000
    assert controller.engine.register_calls == []

    controller.commitCurrentSampleRegion()

    assert controller.engine.register_calls == [(2000, 6000)]

    controller.commitCurrentSampleRegion()

    assert controller.engine.register_calls == [(2000, 6000)]


def test_engine_inject_voice_is_processed_in_callback():
    engine = SounddevicePlaybackEngine(sample_rate=1000, block_size=8)
    audio = np.linspace(-0.25, 0.25, 16, dtype=np.float32)

    assert engine.inject_voice(audio, sample_id="click", pad_index=7)

    out = np.zeros((8, 2), dtype=np.float32)
    engine._callback(out, 8, None, None)

    active, pos = engine.get_pad_voice_state(7)
    assert active is True
    assert pos > 0.0
    assert np.any(out != 0.0)


def test_metronome_uses_engine_inject_voice(qt_app):
    calls = []

    class Engine:
        sample_rate = 44100

        def inject_voice(self, audio, **kwargs):
            calls.append((audio.copy(), kwargs))
            return True

    metronome = Metronome()
    metronome.set_engine(Engine())

    metronome._inject_click_voice(np.array([0.1, 0.05, 0.0], dtype=np.float32))

    assert len(calls) == 1
    audio, kwargs = calls[0]
    assert audio.ndim == 1
    assert kwargs["sample_id"] == "__metronome_click__"
    assert kwargs["pad_index"] == -1
