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
    # Force the editor view window to span the whole stem so the fractions
    # below map predictably to absolute stem samples.
    controller._view_start_sample = 0
    controller._view_end_sample = 10000
    controller.engine.register_calls.clear()

    controller.setCurrentSampleRegion(0.2, 0.6)

    assert sample.start_sample == 2000
    assert sample.end_sample == 6000
    assert controller.engine.register_calls == []

    controller.commitCurrentSampleRegion()

    assert controller.engine.register_calls == [(2000, 6000)]


def test_engine_trigger_click_is_processed_in_callback():
    engine = SounddevicePlaybackEngine(sample_rate=1000, block_size=8)
    mono = np.linspace(-0.25, 0.25, 16, dtype=np.float32)
    click = np.stack([mono, mono], axis=1)

    engine.trigger_click(click)

    out = np.zeros((8, 2), dtype=np.float32)
    engine._callback(out, 8, None, None)

    assert np.any(out != 0.0)


def test_metronome_uses_engine_trigger_click(qt_app):
    calls = []

    class Engine:
        sample_rate = 44100

        def trigger_click(self, audio):
            calls.append(audio.copy())

    metronome = Metronome()
    metronome.set_engine(Engine())

    metronome._play_click(is_downbeat=True)

    assert len(calls) == 1
    click = calls[0]
    assert click.ndim == 2
    assert click.shape[1] == 2
