"""
Pad assignment — layout driven by PadLayoutSettings.
"""

from __future__ import annotations

import logging

from app.core.models import Pad, PadBank, PadMode, Sample, SampleCategory

log = logging.getLogger(__name__)

CATEGORY_COLORS = {
    SampleCategory.DRUM_HIT:        "#E74C3C",
    SampleCategory.DRUM_LOOP:       "#C0392B",
    SampleCategory.VOCAL_CHOP:      "#F1C40F",
    SampleCategory.VOCAL_PHRASE:    "#F39C12",
    SampleCategory.BASS_LOOP:       "#9B59B6",
    SampleCategory.MELODIC_PHRASE:  "#3498DB",
    SampleCategory.FX:              "#1ABC9C",
    SampleCategory.USER:            "#7F8C8D",
}


class PadAssigner:
    def __init__(self, layout=None, grid_size: int = 16):
        self._layout = layout
        self._grid_size = layout.grid_size if layout else grid_size

    def empty_bank(self, name: str = "Bank A") -> PadBank:
        return PadBank(
            name=name,
            pads=[Pad(index=i) for i in range(self._grid_size)],
        )

    def auto_assign(self, samples: list[Sample],
                    bank: PadBank | None = None) -> PadBank:
        if bank is None:
            bank = self.empty_bank()

        if self._layout:
            rows = self._layout.row_config()
        else:
            rows = [
                (4, [SampleCategory.DRUM_HIT],                               PadMode.ONE_SHOT),
                (4, [SampleCategory.VOCAL_CHOP, SampleCategory.VOCAL_PHRASE], PadMode.ONE_SHOT),
                (4, [SampleCategory.MELODIC_PHRASE],                         PadMode.LOOP),
                (4, [SampleCategory.BASS_LOOP, SampleCategory.DRUM_LOOP],    PadMode.LOOP),
            ]

        by_cat: dict[SampleCategory, list[Sample]] = {}
        for s in samples:
            by_cat.setdefault(s.category, []).append(s)

        pad_cursor = 0
        for count, accepted_cats, mode in rows:
            pool: list[Sample] = []
            for cat in accepted_cats:
                pool.extend(by_cat.get(cat, []))
            for offset in range(count):
                if pad_cursor >= len(bank.pads):
                    break
                pad = bank.pads[pad_cursor]
                if offset < len(pool):
                    s = pool[offset]
                    pad.sample_id = s.id
                    pad.mode = mode
                    pad.color = CATEGORY_COLORS.get(s.category, "#888888")
                    pad.label = s.name
                    if s.category == SampleCategory.DRUM_HIT:
                        pad.group = 1
                else:
                    pad.sample_id = None
                    pad.color = "#2C2C2C"
                    pad.label = ""
                pad_cursor += 1

        for i in range(pad_cursor, len(bank.pads)):
            bank.pads[i].sample_id = None
            bank.pads[i].color = "#2C2C2C"
            bank.pads[i].label = ""

        log.info("Auto-assigned %d samples to %d pads",
                 sum(1 for p in bank.pads if p.sample_id),
                 len(bank.pads))
        return bank

    def manual_assign(self, bank: PadBank, pad_index: int, sample: Sample,
                      mode: PadMode = PadMode.ONE_SHOT) -> None:
        if not (0 <= pad_index < len(bank.pads)):
            raise IndexError(pad_index)
        pad = bank.pads[pad_index]
        pad.sample_id = sample.id
        pad.mode = mode
        pad.color = CATEGORY_COLORS.get(sample.category, "#888888")
        pad.label = sample.name