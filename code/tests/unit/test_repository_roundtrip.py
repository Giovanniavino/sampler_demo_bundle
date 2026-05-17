"""Verify the JSON repository roundtrips a project correctly."""

from pathlib import Path

from app.audio.slicing.pad_assigner import PadAssigner
from app.core.models import (
    AnalysisResult, AudioSource, Beat, Pad, PadBank, Project, Sample,
    SampleCategory, Section, SectionLabel, Stem, StemType, Transient,
)
from app.project.repository import ProjectRepository


def _make_project() -> Project:
    src = AudioSource(path=Path("/tmp/song.wav"), sample_rate=44100,
                      channels=2, duration_samples=44100 * 10)
    stem = Stem(source_id=src.id, stem_type=StemType.DRUMS,
                path=Path("/tmp/drums.wav"), sample_rate=44100,
                channels=2, duration_samples=44100 * 10)
    samples = [
        Sample(name="hit01", category=SampleCategory.DRUM_HIT,
               source_stem_id=stem.id, start_sample=0, end_sample=2000),
        Sample(name="loop01", category=SampleCategory.DRUM_LOOP,
               source_stem_id=stem.id, start_sample=2000, end_sample=10000),
    ]
    analysis = AnalysisResult(
        source_id=src.id, bpm=120.0,
        beats=[Beat(position=i * 22050, is_downbeat=(i % 4 == 0)) for i in range(8)],
        sections=[Section(start=0, end=44100, label=SectionLabel.INTRO),
                  Section(start=44100, end=88200, label=SectionLabel.CHORUS)],
        transients=[Transient(position=1000, strength=0.9)],
    )
    bank = PadAssigner().auto_assign(samples)
    return Project(name="Test", sources=[src], stems=[stem],
                   analyses=[analysis], samples=samples,
                   banks=[bank], active_bank_id=bank.id)


def test_roundtrip(tmp_path: Path):
    proj = _make_project()
    repo = ProjectRepository()
    repo.save(proj, tmp_path)

    loaded = repo.load(tmp_path)
    assert loaded.name == proj.name
    assert len(loaded.sources) == 1
    assert len(loaded.stems) == 1
    assert loaded.stems[0].stem_type == StemType.DRUMS
    assert len(loaded.samples) == 2
    assert loaded.samples[0].category == SampleCategory.DRUM_HIT
    assert len(loaded.analyses) == 1
    assert loaded.analyses[0].bpm == 120.0
    assert loaded.analyses[0].sections[1].label == SectionLabel.CHORUS
    assert loaded.active_bank() is not None
    assert loaded.active_bank().pads[0].sample_id == proj.samples[0].id
