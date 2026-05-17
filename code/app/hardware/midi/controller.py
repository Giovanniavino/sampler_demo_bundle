"""
MIDI I/O. Maps incoming MIDI note-on/off and CC to pad triggers and encoder
events. Outgoing: feedback on RGB pads (sysex / note velocity color schemes
on common controllers like Akai APC / Launchpad / MPC).

We use `mido` for portability. The class is decoupled from the engine via
callbacks, so the same controller can drive the Python engine today and the
C++ engine tomorrow.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class MidiPadEvent:
    pad_index: int
    velocity: int          # 0 = release
    channel: int = 0


@dataclass
class MidiEncoderEvent:
    encoder_index: int
    delta: int             # +1 / -1


PadCb = Callable[[MidiPadEvent], None]
EncoderCb = Callable[[MidiEncoderEvent], None]


# A small default note->pad map (Akai-style 4x4 starting at C1=36)
DEFAULT_PAD_NOTE_BASE = 36
DEFAULT_PAD_COUNT = 16

# Common encoder CCs (configurable per controller profile)
DEFAULT_ENCODER_CCS = [16, 17, 18, 19, 20, 21, 22, 23]


class MidiController:
    def __init__(
        self,
        on_pad: Optional[PadCb] = None,
        on_encoder: Optional[EncoderCb] = None,
        pad_note_base: int = DEFAULT_PAD_NOTE_BASE,
        pad_count: int = DEFAULT_PAD_COUNT,
        encoder_ccs: list[int] | None = None,
    ):
        self.on_pad = on_pad
        self.on_encoder = on_encoder
        self.pad_note_base = pad_note_base
        self.pad_count = pad_count
        self.encoder_ccs = encoder_ccs or DEFAULT_ENCODER_CCS
        self._in_port = None
        self._out_port = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ---- Connection ---------------------------------------------------

    @staticmethod
    def list_inputs() -> list[str]:
        try:
            import mido
            return mido.get_input_names()
        except Exception as e:
            log.warning("MIDI listing failed: %s", e)
            return []

    def open(self, in_name: str, out_name: Optional[str] = None) -> None:
        import mido
        self._in_port = mido.open_input(in_name)
        if out_name:
            self._out_port = mido.open_output(out_name)
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        log.info("MIDI opened: in=%s out=%s", in_name, out_name)

    def close(self) -> None:
        self._running = False
        if self._in_port:
            self._in_port.close()
        if self._out_port:
            self._out_port.close()

    # ---- Output (pad feedback) ----------------------------------------

    def set_pad_color(self, pad_index: int, color: tuple[int, int, int]) -> None:
        """Most consumer controllers use a velocity color table. Subclass and
        override to implement vendor sysex (Push 2 / Launchpad Pro / etc.)."""
        if self._out_port is None:
            return
        import mido
        note = self.pad_note_base + pad_index
        # Default: use note velocity 0..127 mapped from luma
        luma = int((color[0] + color[1] + color[2]) / 3)
        self._out_port.send(mido.Message("note_on", note=note, velocity=luma))

    # ---- Read loop ----------------------------------------------------

    def _read_loop(self) -> None:
        for msg in self._iter_messages():
            if not self._running:
                break
            self._dispatch(msg)

    def _iter_messages(self):
        # Blocking iteration on mido port
        while self._running and self._in_port is not None:
            for msg in self._in_port.iter_pending():
                yield msg

    def _dispatch(self, msg) -> None:
        if msg.type == "note_on" or msg.type == "note_off":
            note = msg.note
            pad_index = note - self.pad_note_base
            if 0 <= pad_index < self.pad_count and self.on_pad:
                velocity = msg.velocity if msg.type == "note_on" else 0
                self.on_pad(MidiPadEvent(pad_index=pad_index,
                                          velocity=velocity,
                                          channel=msg.channel))
        elif msg.type == "control_change":
            if msg.control in self.encoder_ccs and self.on_encoder:
                # Many encoders send 1 / 127 for +1 / -1 (relative mode)
                delta = 1 if msg.value < 64 else -1
                idx = self.encoder_ccs.index(msg.control)
                self.on_encoder(MidiEncoderEvent(encoder_index=idx, delta=delta))
