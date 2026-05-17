"""Smoke tests that run without torch/librosa/sounddevice installed."""

from app.core.models import (
    AnalysisResult, Beat, Pad, PadBank, PadMode, Project, Sample,
    SampleCategory, Section, SectionLabel, Stem, StemType, Transient,
)
from app.audio.slicing.pad_assigner import PadAssigner


def test_default_grid_assignment_layout():
    """Categories should map to predictable rows."""
    samples = [
        Sample(name=f"hit{i}", category=SampleCategory.DRUM_HIT) for i in range(6)
    ] + [
        Sample(name=f"chop{i}", category=SampleCategory.VOCAL_CHOP) for i in range(3)
    ] + [
        Sample(name="mel", category=SampleCategory.MELODIC_PHRASE),
        Sample(name="bass", category=SampleCategory.BASS_LOOP),
    ]
    bank = PadAssigner().auto_assign(samples)
    # Row 0: drum hits
    assert all(bank.pads[i].sample_id is not None for i in range(4))
    # Row 1: vocals (3 chops -> 3 filled, 1 empty)
    filled_row_1 = sum(1 for i in range(4, 8) if bank.pads[i].sample_id)
    assert filled_row_1 == 3
    # Row 2: only 1 melodic sample
    filled_row_2 = sum(1 for i in range(8, 12) if bank.pads[i].sample_id)
    assert filled_row_2 == 1
    # Row 3: only 1 bass loop
    filled_row_3 = sum(1 for i in range(12, 16) if bank.pads[i].sample_id)
    assert filled_row_3 == 1


def test_choke_group_set_on_drum_hits():
    samples = [Sample(name="kick", category=SampleCategory.DRUM_HIT)]
    bank = PadAssigner().auto_assign(samples)
    assert bank.pads[0].group == 1


def test_sample_length_helper():
    s = Sample(start_sample=1000, end_sample=5000)
    assert s.length_samples == 4000


def test_project_lookups():
    stem = Stem(stem_type=StemType.DRUMS)
    sample = Sample(name="a", source_stem_id=stem.id)
    bank = PadBank(name="A", pads=[Pad(index=0, sample_id=sample.id)])
    proj = Project(stems=[stem], samples=[sample], banks=[bank],
                   active_bank_id=bank.id)
    assert proj.sample_by_id(sample.id) is sample
    assert proj.stem_by_id(stem.id) is stem
    assert proj.active_bank() is bank


def test_pad_modes_enum_values():
    # Ensure enum values match what QML/JSON expects
    assert PadMode.ONE_SHOT.value == "one_shot"
    assert PadMode.LOOP.value == "loop"
    assert SampleCategory.DRUM_HIT.value == "drum_hit"
    assert SectionLabel.CHORUS.value == "chorus"
    assert StemType.VOCALS.value == "vocals"
