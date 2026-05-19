"""
MIDI keyboard auto-detection and classification.

Identifies connected MIDI input devices, classifies them by key count
(4 / 8 / 12 / 25 / 32 / 49 / 61 / 76 / 88), and finds the middle C position.

Strategy:
  - Use mido.get_input_names() to discover devices
  - Probe each device by listening for note-on events for a short window
    (or use static heuristics from device name)
  - Map MIDI note range to keyboard size:
      4 keys  → notes 60-63       (C4-D#4)
      8 keys  → notes 60-67       (C4-G4)
      12 keys → notes 60-71       (C4-B4)
      25 keys → notes 48-72       (C3-C5)
      32 keys → notes 41-72       (F2-C5)
      49 keys → notes 36-84       (C2-C6)
      61 keys → notes 36-96       (C2-C7)
      76 keys → notes 28-103      (E1-G7)
      88 keys → notes 21-108      (A0-C8) — standard piano
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MidiKeyboardInfo:
    """Describes a detected/classified MIDI keyboard."""
    port_name: str
    key_count: int             # 0 if no keyboard / unknown
    note_range_low: int        # lowest playable MIDI note (60 if unknown)
    note_range_high: int       # highest playable MIDI note (60 if unknown)
    middle_c_note: int = 60    # MIDI middle C is always note 60
    is_connected: bool = True
    is_keyboard: bool = True   # False if device is not a piano-like controller

    @property
    def display_name(self) -> str:
        """Human-readable label, e.g. '88-key piano' or 'Generic MIDI'."""
        if not self.is_keyboard or self.key_count == 0:
            return "No keyboard detected"
        kind = self._classify_kind()
        return f"{self.key_count}-key {kind}"

    def _classify_kind(self) -> str:
        if self.key_count >= 88:
            return "piano"
        if self.key_count >= 49:
            return "keyboard"
        if self.key_count >= 25:
            return "mini-keyboard"
        return "controller"

    def is_middle_c_visible(self) -> bool:
        """True if MIDI note 60 (middle C) is reachable on this keyboard."""
        return self.note_range_low <= self.middle_c_note <= self.note_range_high


# Standard mapping: key count → (note_low, note_high)
KEYBOARD_RANGES = {
    4:  (60, 63),
    8:  (60, 67),
    12: (60, 71),
    25: (48, 72),
    32: (41, 72),
    37: (41, 77),
    49: (36, 84),
    61: (36, 96),
    76: (28, 103),
    88: (21, 108),
}


def classify_by_name(name: str) -> Optional[int]:
    """
    Try to infer keyboard size from the port name.
    Returns key count or None.
    """
    name_lower = name.lower()
    # Common patterns: "Akai MPK Mini 25", "Arturia 61", "Yamaha P-88"
    for kc in sorted(KEYBOARD_RANGES.keys(), reverse=True):
        # Match exact key count (e.g. "61-key", "25 keys", "88-note")
        patterns = [rf"\b{kc}\b", rf"{kc}-?key", rf"{kc}-?note"]
        if any(re.search(p, name_lower) for p in patterns):
            return kc

    # Brand-specific heuristics
    if "mpk mini" in name_lower or "minilab" in name_lower:
        return 25
    if "launchkey 25" in name_lower or "novation 25" in name_lower:
        return 25
    if "launchkey 49" in name_lower:
        return 49
    if "launchkey 61" in name_lower:
        return 61
    if "p-45" in name_lower or "p-125" in name_lower or "p-88" in name_lower:
        return 88
    if "casio cdp" in name_lower or "px-160" in name_lower:
        return 88
    if "kontrol s49" in name_lower:
        return 49
    if "kontrol s61" in name_lower:
        return 61
    if "kontrol s88" in name_lower or "kontrol s8" in name_lower:
        return 88

    return None


def detect_keyboards(probe_seconds: float = 1.0) -> list[MidiKeyboardInfo]:
    """
    Detect all connected MIDI keyboards. Tries name-based classification
    first; only probes via listening if the name is unclear.

    probe_seconds: max time per device to listen for notes (0 = name only).
    Returns list of MidiKeyboardInfo, one per connected device.
    """
    try:
        import mido
    except ImportError as e:
        log.warning("mido not installed: %s", e)
        return []

    ports = []
    try:
        ports = mido.get_input_names()
    except Exception as e:
        log.warning("MIDI port listing failed: %s", e)
        return []

    if not ports:
        log.info("No MIDI input devices found")
        return []

    keyboards = []
    for port_name in ports:
        kb_size = classify_by_name(port_name)

        if kb_size is None and probe_seconds > 0:
            # Listen briefly to infer range
            kb_size = _probe_via_listening(port_name, probe_seconds)

        if kb_size is None:
            # Unknown — default to 49-key MIDI controller
            kb_size = 49

        note_low, note_high = KEYBOARD_RANGES[kb_size]
        keyboards.append(MidiKeyboardInfo(
            port_name=port_name,
            key_count=kb_size,
            note_range_low=note_low,
            note_range_high=note_high,
            middle_c_note=60,
            is_connected=True,
            is_keyboard=True,
        ))
        log.info("Detected MIDI keyboard: %s (%d keys, range %d-%d)",
                 port_name, kb_size, note_low, note_high)

    return keyboards


def _probe_via_listening(port_name: str, timeout: float) -> Optional[int]:
    """
    Briefly listen on the port for note-on events. If notes are detected,
    infer keyboard size from the range. Returns None if no notes received.
    """
    try:
        import mido
        import time
        notes_seen = set()
        port = mido.open_input(port_name)
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            for msg in port.iter_pending():
                if msg.type == "note_on" and msg.velocity > 0:
                    notes_seen.add(msg.note)
        port.close()

        if not notes_seen:
            return None

        # Estimate range from observed notes (very rough)
        low, high = min(notes_seen), max(notes_seen)
        span = high - low + 1
        # Pick the nearest standard size that covers the observed range
        for kc in sorted(KEYBOARD_RANGES.keys()):
            if span <= KEYBOARD_RANGES[kc][1] - KEYBOARD_RANGES[kc][0] + 1:
                return kc
        return 88
    except Exception as e:
        log.debug("Listening probe failed for %s: %s", port_name, e)
        return None


def best_keyboard(keyboards: list[MidiKeyboardInfo]) -> Optional[MidiKeyboardInfo]:
    """
    Pick the best keyboard from a list (largest key count wins).
    Returns None if list is empty.
    """
    if not keyboards:
        return None
    return max(keyboards, key=lambda k: k.key_count)


def map_pads_to_notes(pad_count: int,
                      keyboard: MidiKeyboardInfo) -> list[int]:
    """
    Map N pads to MIDI notes centered around middle C.
    Returns list[int] of length pad_count.

    Examples:
      pad_count=16, 88-key keyboard:
        → notes 60, 61, 62, ..., 75 (C4 to D#5)
      pad_count=16, 25-key keyboard:
        → notes 48, 49, ..., 63 (C3 to D#4)
    """
    if keyboard.key_count == 0 or not keyboard.is_keyboard:
        # Fallback: start at C2 (note 36, standard MPC range)
        return list(range(36, 36 + pad_count))

    # Center the pad range around middle C, clipped to the keyboard
    start = max(keyboard.note_range_low, keyboard.middle_c_note - pad_count // 2)
    end = start + pad_count
    if end > keyboard.note_range_high + 1:
        end = keyboard.note_range_high + 1
        start = max(keyboard.note_range_low, end - pad_count)

    return list(range(start, start + pad_count))
