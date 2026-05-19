"""
Bilingual key detection — extends the existing English-notation key detector
to support both English (C, D, E, ...) and Italian (Do, Re, Mi, ...) labels.

Strategy:
  - Keep `detect_key()` returning English notation (preserves backwards compat)
  - Add `detect_key_bilingual()` that returns both English and Italian labels
  - Provide pure translation utilities for existing key strings
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Direct note translations
NOTE_EN_TO_IT = {
    "C":  "Do",  "C#": "Do#",
    "D":  "Re",  "D#": "Re#",
    "E":  "Mi",
    "F":  "Fa",  "F#": "Fa#",
    "G":  "Sol", "G#": "Sol#",
    "A":  "La",  "A#": "La#",
    "B":  "Si",
}

NOTE_IT_TO_EN = {v: k for k, v in NOTE_EN_TO_IT.items()}

# Mode translations
MODE_EN_TO_IT = {"major": "maggiore", "minor": "minore"}
MODE_IT_TO_EN = {v: k for k, v in MODE_EN_TO_IT.items()}


@dataclass(frozen=True)
class BilingualKey:
    """Key in both English and Italian notation."""
    note_en: str            # "C", "D#", "F", etc.
    note_it: str            # "Do", "Re#", "Fa", etc.
    mode_en: str            # "major" or "minor"
    mode_it: str            # "maggiore" or "minore"
    confidence: float       # 0..1

    @property
    def english(self) -> str:
        """Full English label, e.g. 'C minor'."""
        return f"{self.note_en} {self.mode_en}"

    @property
    def italian(self) -> str:
        """Full Italian label, e.g. 'Do minore'."""
        return f"{self.note_it} {self.mode_it}"

    def in_language(self, lang: str) -> str:
        """Return label in 'en' or 'it'."""
        return self.italian if lang.lower().startswith("it") else self.english


def detect_key_bilingual(audio_path: Path,
                          max_seconds: float = 60.0) -> Optional[BilingualKey]:
    """
    Detect musical key and return labels in both English and Italian.
    Returns None on failure.
    """
    try:
        # Import the existing detect_key (preserves correctness for English)
        from app.audio.analysis.key_detector import detect_key
    except Exception:
        # Fallback if running this file standalone (e.g., in tests)
        from key_detector import detect_key  # type: ignore

    try:
        en_label, confidence = detect_key(audio_path, max_seconds=max_seconds)
        if en_label == "?":
            return None

        # Parse "C minor" or "F# major"
        parts = en_label.rsplit(" ", 1)
        if len(parts) != 2:
            return None
        note_en, mode_en = parts[0], parts[1]
        note_it = NOTE_EN_TO_IT.get(note_en, note_en)
        mode_it = MODE_EN_TO_IT.get(mode_en, mode_en)

        return BilingualKey(
            note_en=note_en,
            note_it=note_it,
            mode_en=mode_en,
            mode_it=mode_it,
            confidence=float(confidence),
        )
    except Exception as e:
        log.warning("Bilingual key detection failed: %s", e)
        return None


def translate_key(key_string: str, to_language: str = "it") -> str:
    """
    Translate a key string between languages.
    Examples:
      translate_key("C minor", "it")     → "Do minore"
      translate_key("Do maggiore", "en") → "C major"
      translate_key("?", "it")           → "?"
    """
    if not key_string or key_string == "?":
        return key_string

    parts = key_string.rsplit(" ", 1)
    if len(parts) != 2:
        return key_string
    note, mode = parts[0], parts[1]

    if to_language.lower().startswith("it"):
        # EN → IT
        note_out = NOTE_EN_TO_IT.get(note, note)
        mode_out = MODE_EN_TO_IT.get(mode.lower(), mode)
    else:
        # IT → EN
        note_out = NOTE_IT_TO_EN.get(note, note)
        mode_out = MODE_IT_TO_EN.get(mode.lower(), mode)

    return f"{note_out} {mode_out}"
