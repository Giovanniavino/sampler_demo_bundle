"""Tests for kit + preset persistence (KitRepository)."""

import json

import numpy as np
import soundfile as sf

from app.core.models import (
    Pad, PadBank, PadMode, Project, Sample, SampleCategory, Stem, StemType,
)
from app.project.repository import KitRepository


def _wav(path, seconds=0.2, sr=22050):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.zeros(int(seconds * sr), dtype="float32"), sr)


def _project_with_stem(tmp_path) -> Project:
    stem_path = tmp_path / "src" / "drums.wav"
    _wav(stem_path)
    stem = Stem(stem_type=StemType.DRUMS, path=stem_path,
                sample_rate=22050, duration_samples=4410)
    sample = Sample(name="hit", category=SampleCategory.DRUM_HIT,
                    source_stem_id=stem.id, start_sample=0, end_sample=2000,
                    pan=-0.5, cutoff_hz=8000.0, loop_beats=4)
    pad = Pad(index=0, sample_id=sample.id, mode=PadMode.ONE_SHOT, group=1)
    bank = PadBank(name="A", pads=[pad])
    return Project(name="My Kit", stems=[stem], samples=[sample],
                   banks=[bank], active_bank_id=bank.id)


def test_save_kit_creates_files(tmp_path):
    proj = _project_with_stem(tmp_path)
    kit_dir = tmp_path / "kits" / "my_kit"
    KitRepository().save_kit(proj, kit_dir, kit_name="my_kit")
    assert (kit_dir / "kit.json").exists()
    assert (kit_dir / "stems" / "drums.wav").exists()


def test_kit_roundtrip(tmp_path):
    proj = _project_with_stem(tmp_path)
    kit_dir = tmp_path / "kits" / "rt"
    repo = KitRepository()
    repo.save_kit(proj, kit_dir)
    loaded = repo.load_kit(kit_dir)

    assert loaded.name == proj.name
    assert len(loaded.stems) == 1
    assert len(loaded.samples) == 1
    assert len(loaded.banks) == 1
    # stem audio path resolved to an absolute, existing file
    assert loaded.stems[0].path.is_absolute()
    assert loaded.stems[0].path.exists()
    # pad config preserved
    pad = loaded.banks[0].pads[0]
    assert pad.mode == PadMode.ONE_SHOT
    assert pad.group == 1
    assert pad.sample_id == proj.samples[0].id
    # newer sample fields survive the roundtrip
    s = loaded.samples[0]
    assert s.pan == -0.5
    assert s.cutoff_hz == 8000.0
    assert s.loop_beats == 4


def test_kit_json_uses_relative_paths(tmp_path):
    proj = _project_with_stem(tmp_path)
    kit_dir = tmp_path / "kits" / "rel"
    KitRepository().save_kit(proj, kit_dir)
    data = json.loads((kit_dir / "kit.json").read_text(encoding="utf-8"))
    assert data["project"]["stems"][0]["path"] == "stems/drums.wav"


def test_validate_kit_ok(tmp_path):
    proj = _project_with_stem(tmp_path)
    kit_dir = tmp_path / "kits" / "ok"
    repo = KitRepository()
    repo.save_kit(proj, kit_dir)
    valid, errors = repo.validate_kit(kit_dir)
    assert valid
    assert errors == []


def test_validate_kit_detects_missing_audio(tmp_path):
    proj = _project_with_stem(tmp_path)
    kit_dir = tmp_path / "kits" / "broken"
    repo = KitRepository()
    repo.save_kit(proj, kit_dir)
    (kit_dir / "stems" / "drums.wav").unlink()
    valid, errors = repo.validate_kit(kit_dir)
    assert not valid
    assert any("drums.wav" in e for e in errors)


def test_validate_kit_missing_json(tmp_path):
    valid, errors = KitRepository().validate_kit(tmp_path / "nope")
    assert not valid
    assert errors


def test_preset_roundtrip(tmp_path):
    repo = KitRepository()
    pads = [
        Pad(index=0, mode=PadMode.LOOP, group=2, color="#FF0000", label="A"),
        Pad(index=1, mode=PadMode.GATE, group=0, color="#00FF00", label="B"),
    ]
    path = repo.save_preset("Drums Hard", pads, tmp_path / "presets")
    assert path.exists()

    loaded = repo.load_preset(path)
    assert len(loaded) == 2
    assert loaded[0]["mode"] == "loop"
    assert loaded[0]["group"] == 2
    assert loaded[1]["label"] == "B"
