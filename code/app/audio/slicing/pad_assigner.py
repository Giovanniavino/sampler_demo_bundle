"""
Pad assignment.

Default policy for a 4x4 MPC-style grid:
    row 0 (pads 0-3)   -> drum hits
    row 1 (pads 4-7)   -> vocals (chops + phrases)
    row 2 (pads 8-11)  -> melodic phrases (other / piano / guitar)
    row 3 (pads 12-15) -> bass loops + drum loops

Colors follow category, so the UI can tint pads without extra metadata.
"""

from __future__ import annotations

import logging

from app.core.models import Pad, PadBank, PadMode, Sample, SampleCategory

log = logging.getLogger(__name__)


# Stem-style palette. Hex with no alpha; the UI applies opacity for muted pads.
CATEGORY_COLORS = {
    SampleCategory.DRUM_HIT:        "#E74C3C",  # red
    SampleCategory.DRUM_LOOP:       "#C0392B",  # dark red
    SampleCategory.VOCAL_CHOP:      "#F1C40F",  # yellow
    SampleCategory.VOCAL_PHRASE:    "#F39C12",  # orange
    SampleCategory.BASS_LOOP:       "#9B59B6",  # purple
    SampleCategory.MELODIC_PHRASE:  "#3498DB",  # blue
    SampleCategory.FX:              "#1ABC9C",  # teal
    SampleCategory.USER:            "#7F8C8D",  # gray
}

DEFAULT_GRID_SIZE = 16  # 4x4

# (start_pad_index, count, accepted_categories, default_mode)
_DEFAULT_ROWS = [
    (0,  4, [SampleCategory.DRUM_HIT],                              PadMode.ONE_SHOT),
    (4,  4, [SampleCategory.VOCAL_CHOP, SampleCategory.VOCAL_PHRASE], PadMode.ONE_SHOT),
    (8,  4, [SampleCategory.MELODIC_PHRASE],                        PadMode.LOOP),
    (12, 4, [SampleCategory.BASS_LOOP, SampleCategory.DRUM_LOOP],   PadMode.LOOP),
]


class PadAssigner:
    def __init__(self, grid_size: int = DEFAULT_GRID_SIZE):
        self.grid_size = grid_size

    def empty_bank(self, name: str = "Bank A") -> PadBank:
        return PadBank(
            name=name,
            pads=[Pad(index=i) for i in range(self.grid_size)],
        )

    def auto_assign(self, samples: list[Sample], bank: PadBank | None = None) -> PadBank:
        if bank is None:
            bank = self.empty_bank()

        by_cat: dict[SampleCategory, list[Sample]] = {}
        for s in samples:
            by_cat.setdefault(s.category, []).append(s)

        for start, count, accepted, mode in _DEFAULT_ROWS:
            # Pool of candidates for this row, in category-priority order
            pool: list[Sample] = []
            for cat in accepted:
                pool.extend(by_cat.get(cat, []))

            for offset in range(count):
                pad_idx = start + offset
                if pad_idx >= len(bank.pads):
                    break
                pad = bank.pads[pad_idx]
                if offset < len(pool):
                    s = pool[offset]
                    pad.sample_id = s.id
                    pad.mode = mode
                    pad.color = CATEGORY_COLORS.get(s.category, "#888888")
                    pad.label = s.name
                    # Choke group: drum hits choke each other on the same pad row
                    if s.category == SampleCategory.DRUM_HIT:
                        pad.group = 1
                else:
                    pad.sample_id = None
                    pad.color = "#2C2C2C"
                    pad.label = ""

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
