"""
QML-facing controller — INTEGRATED with:
  - MIDI keyboard auto-detection & classification
  - Fractional BPM detection with time signature & confidence
  - AI-powered sample analysis (phrase/hit/break detection with colors)
  - Bilingual key detection (EN/IT)

All new features exposed via PyQt signals/properties for QML visualization.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QAbstractListModel, QModelIndex, QObject, QThread, Qt,
    QUrl, pyqtProperty, pyqtSignal, pyqtSlot,
)

from app.audio.playback.engine import SounddevicePlaybackEngine
from app.audio.separation.heuristic import HeuristicSeparator
from app.audio.separation.separator import DemucsSeparator, DummySeparator
from app.audio.slicing.pad_assigner import CATEGORY_COLORS
from app.core.models import Pad, PadMode, Project, Sample
from app.core.settings import (
    DRUM_PRESETS, LOOP_PRESETS, VOCAL_PRESETS, AppSettings,
)
from app.services.pipeline import SamplerPipeline

log = logging.getLogger(__name__)

SETTINGS_PATH = Path("data/settings.json")


# ---------------------------------------------------------------------------
# Pad list model
# ---------------------------------------------------------------------------

class PadGridModel(QAbstractListModel):
    IndexRole     = Qt.ItemDataRole.UserRole + 1
    LabelRole     = Qt.ItemDataRole.UserRole + 2
    ColorRole     = Qt.ItemDataRole.UserRole + 3
    HasSampleRole = Qt.ItemDataRole.UserRole + 4
    ActiveRole    = Qt.ItemDataRole.UserRole + 5
    ModeRole      = Qt.ItemDataRole.UserRole + 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pads: list[Pad] = []
        self._active: set[int] = set()

    def roleNames(self):
        return {
            self.IndexRole:     b"padIndex",
            self.LabelRole:     b"label",
            self.ColorRole:     b"color",
            self.HasSampleRole: b"hasSample",
            self.ActiveRole:    b"active",
            self.ModeRole:      b"mode",
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._pads)

    def data(self, index, role):
        if not index.isValid():
            return None
        p = self._pads[index.row()]
        if role == self.IndexRole:      return p.index
        if role == self.LabelRole:      return p.label or f"Pad {p.index + 1}"
        if role == self.ColorRole:      return p.color
        if role == self.HasSampleRole:  return p.sample_id is not None
        if role == self.ActiveRole:     return p.index in self._active
        if role == self.ModeRole:       return p.mode.value
        return None

    def set_pads(self, pads: list[Pad]):
        self.beginResetModel()
        self._pads = pads
        self._active.clear()
        self.endResetModel()

    def set_active(self, pad_index: int, active: bool):
        if active:
            self._active.add(pad_index)
        else:
            self._active.discard(pad_index)
        for row, p in enumerate(self._pads):
            if p.index == pad_index:
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [self.ActiveRole])
                break

    def notify_mode_changed(self, pad_index: int):
        for row, p in enumerate(self._pads):
            if p.index == pad_index:
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [self.ModeRole])
                break


# ---------------------------------------------------------------------------
# Annotation model (for sample analysis results)
# ---------------------------------------------------------------------------

class AnnotationModel(QAbstractListModel):
    """Exposes sample annotations (phrases, hits, breaks, cores) to QML."""
    StartRole   = Qt.ItemDataRole.UserRole + 1
    EndRole     = Qt.ItemDataRole.UserRole + 2
    KindRole    = Qt.ItemDataRole.UserRole + 3
    ColorRole   = Qt.ItemDataRole.UserRole + 4
    LabelRole   = Qt.ItemDataRole.UserRole + 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._annotations = []

    def roleNames(self):
        return {
            self.StartRole:  b"startFrac",
            self.EndRole:    b"endFrac",
            self.KindRole:   b"kind",
            self.ColorRole:  b"color",
            self.LabelRole:  b"label",
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._annotations)

    def data(self, index, role):
        if not index.isValid():
            return None
        ann = self._annotations[index.row()]
        if role == self.StartRole:  return ann.get("start_frac", 0.0)
        if role == self.EndRole:    return ann.get("end_frac", 1.0)
        if role == self.KindRole:   return ann.get("kind", "")
        if role == self.ColorRole:  return ann.get("color", "#888888")
        if role == self.LabelRole:  return ann.get("label", "")
        return None

    def set_annotations(self, annotations: list[dict]):
        """Set list of annotation dicts with keys:
        start_frac, end_frac, kind, color, label"""
        self.beginResetModel()
        self._annotations = annotations
        self.endResetModel()


# ---------------------------------------------------------------------------
# MIDI Keyboard model
# ---------------------------------------------------------------------------

class MidiKeyboardModel(QAbstractListModel):
    """Lists available MIDI keyboards."""
    PortNameRole     = Qt.ItemDataRole.UserRole + 1
    DisplayNameRole  = Qt.ItemDataRole.UserRole + 2
    KeyCountRole     = Qt.ItemDataRole.UserRole + 3
    IsSelectedRole   = Qt.ItemDataRole.UserRole + 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keyboards = []
        self._selected_idx = -1

    def roleNames(self):
        return {
            self.PortNameRole:    b"portName",
            self.DisplayNameRole: b"displayName",
            self.KeyCountRole:    b"keyCount",
            self.IsSelectedRole:  b"isSelected",
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._keyboards)

    def data(self, index, role):
        if not index.isValid():
            return None
        kb = self._keyboards[index.row()]
        if role == self.PortNameRole:     return kb.get("port_name", "")
        if role == self.DisplayNameRole:  return kb.get("display_name", "")
        if role == self.KeyCountRole:     return kb.get("key_count", 0)
        if role == self.IsSelectedRole:   return index.row() == self._selected_idx
        return None

    def set_keyboards(self, keyboards: list[dict]):
        """Set list of keyboard dicts with keys:
        port_name, display_name, key_count"""
        self.beginResetModel()
        self._keyboards = keyboards
        self._selected_idx = 0 if keyboards else -1
        self.endResetModel()

    def select_keyboard(self, index: int):
        if 0 <= index < len(self._keyboards):
            old_idx = self._selected_idx
            self._selected_idx = index
            if old_idx >= 0:
                idx = self.index(old_idx, 0)
                self.dataChanged.emit(idx, idx, [self.IsSelectedRole])
            idx = self.index(index, 0)
            self.dataChanged.emit(idx, idx, [self.IsSelectedRole])

    def selected_keyboard(self) -> Optional[dict]:
        if 0 <= self._selected_idx < len(self._keyboards):
            return self._keyboards[self._selected_idx]
        return None


# ---------------------------------------------------------------------------
# Import worker
# ---------------------------------------------------------------------------

class ImportWorker(QObject):
    progress = pyqtSignal(float, str)
    finished = pyqtSignal(object)
    error    = pyqtSignal(str)

    def __init__(self, pipeline: SamplerPipeline, audio_path: Path):
        super().__init__()
        self.pipeline   = pipeline
        self.audio_path = audio_path

    @pyqtSlot()
    def run(self):
        try:
            project = self.pipeline.import_track(
                self.audio_path,
                progress=lambda p, m: self.progress.emit(p, m),
            )
            self.finished.emit(project)
        except Exception as e:
            log.exception("Import failed")
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------

class SamplerController(QObject):

    projectChanged              = pyqtSignal()
    bpmChanged                  = pyqtSignal()
    statusChanged               = pyqtSignal()
    importProgress              = pyqtSignal(float, str)
    importDone                  = pyqtSignal()
    importError                 = pyqtSignal(str)
    settingsChanged             = pyqtSignal()
    needsQualityMode            = pyqtSignal()
    sampleEditorOpen            = pyqtSignal(int, str, float, float, float)
    currentSampleChanged        = pyqtSignal()
    editorParamsChanged         = pyqtSignal()
    zoomChanged                 = pyqtSignal()
    # New signals
    midiKeyboardsDetected       = pyqtSignal()
    midiKeyboardSelected        = pyqtSignal()
    bpmDetected                 = pyqtSignal()
    sampleAnnotationsAnalyzed   = pyqtSignal()

    def __init__(self, cache_dir: Path, use_demucs: bool = True):
        super().__init__()
        self._cache_dir  = cache_dir
        self._use_demucs = use_demucs
        self._settings   = AppSettings.load(SETTINGS_PATH)
        self._project: Optional[Project] = None
        self._status  = "Ready. Load a track to begin."
        self._bpm     = 0.0
        self._key     = ""
        self._pad_model = PadGridModel()
        self._import_thread: Optional[QThread] = None
        self._hold_looping: dict[int, bool] = {}
        self._trigger_time_samples: dict[int, int] = {}
        self._trigger_sample_len: dict[int, int] = {}
        self._trigger_wallclock: dict[int, float] = {}

        # Current sample editor state ──────────────────────────────────
        self._current_pad_index: int = -1
        self._current_peaks: list[float] = []
        self._stem_peak_cache: dict[str, list[float]] = {}
        self._sample_originals: dict[str, dict] = {}
        self._zoom_start: float = 0.0
        self._zoom_end:   float = 1.0
        self._snap_to_beats: bool = False

        # NEW: MIDI, BPM, sample analysis models ────────────────────────
        self._midi_keyboard_model = MidiKeyboardModel()
        self._midi_keyboards: list[dict] = []
        self._selected_midi_keyboard: Optional[dict] = None

        self._detected_bpm: float = 0.0
        self._detected_time_signature: str = "4/4"
        self._bpm_confidence: float = 0.0
        self._detected_key: str = ""
        self._detected_key_lang: str = "en"

        self._annotation_model = AnnotationModel()
        self._annotations: list[dict] = []

        self._rebuild_engine()

    # ---- Helpers -------------------------------------------------------

    def _rebuild_engine(self):
        pb = self._settings.playback
        if hasattr(self, 'engine') and self.engine:
            try: self.engine.stop()
            except Exception: pass
        self.engine = SounddevicePlaybackEngine(
            sample_rate=pb.sample_rate,
            block_size=pb.block_size,
        )
        self.engine.start()

    def _build_pipeline(self) -> SamplerPipeline:
        from app.audio.slicing.auto_slicer import AutoSlicer
        from app.audio.slicing.pad_assigner import PadAssigner
        if self._use_demucs:
            sep = DemucsSeparator(model_name=self._settings.demucs_model)
        else:
            sep = HeuristicSeparator()
        return SamplerPipeline(
            cache_dir=self._cache_dir,
            settings=self._settings,
            separator=sep,
            slicer=AutoSlicer(self._settings.to_slicer_config()),
            assigner=PadAssigner(layout=self._settings.pad_layout),
        )

    @staticmethod
    def _qml_file_to_path(file_url: str) -> Path:
        if file_url.startswith("file"):
            return Path(QUrl(file_url).toLocalFile())
        return Path(file_url)

    # ---- QML properties -----------------------------------------------

    @pyqtProperty(QObject, constant=True)
    def padModel(self): return self._pad_model

    @pyqtProperty(QObject, constant=True)
    def midiKeyboardModel(self): return self._midi_keyboard_model

    @pyqtProperty(QObject, constant=True)
    def annotationModel(self): return self._annotation_model

    @pyqtProperty(str, notify=statusChanged)
    def status(self): return self._status

    @pyqtProperty(float, notify=bpmChanged)
    def bpm(self): return self._bpm

    @pyqtProperty(str, notify=bpmChanged)
    def trackKey(self): return self._key

    @pyqtProperty(str, notify=projectChanged)
    def trackName(self):
        if self._project and self._project.sources:
            return Path(str(self._project.sources[0].path)).stem
        return ""

    # --- NEW: MIDI, BPM, Sample Analysis Properties ---

    @pyqtProperty(float, notify=bpmDetected)
    def detectedBpm(self): return self._detected_bpm

    @pyqtProperty(str, notify=bpmDetected)
    def detectedTimeSignature(self): return self._detected_time_signature

    @pyqtProperty(float, notify=bpmDetected)
    def bpmConfidence(self): return self._bpm_confidence

    @pyqtProperty(str, notify=bpmDetected)
    def detectedKeyEnglish(self): return self._detected_key

    @pyqtProperty(str, notify=bpmDetected)
    def detectedKeyItalian(self):
        """Return Italian translation of detected key (if available)."""
        from app.audio.analysis.key_detector_bilingual import translate_key
        if not self._detected_key:
            return ""
        return translate_key(self._detected_key, "it")

    # --- Current sample editor properties ---
    @pyqtProperty(int, notify=currentSampleChanged)
    def currentPadIndex(self): return self._current_pad_index

    @pyqtProperty(str, notify=currentSampleChanged)
    def currentSampleName(self):
        s = self._current_sample()
        return s.name if s else ""

    @pyqtProperty(list, notify=currentSampleChanged)
    def currentPeaks(self): return self._current_peaks

    @pyqtProperty(float, notify=currentSampleChanged)
    def currentSampleStartFrac(self):
        s = self._current_sample()
        if not s: return 0.0
        stem = self._project.stem_by_id(s.source_stem_id) if self._project else None
        if not stem or stem.duration_samples <= 0: return 0.0
        return max(0.0, min(1.0, s.start_sample / stem.duration_samples))

    @pyqtProperty(float, notify=currentSampleChanged)
    def currentSampleEndFrac(self):
        s = self._current_sample()
        if not s: return 1.0
        stem = self._project.stem_by_id(s.source_stem_id) if self._project else None
        if not stem or stem.duration_samples <= 0: return 1.0
        return max(0.0, min(1.0, s.end_sample / stem.duration_samples))

    @pyqtProperty(float, notify=currentSampleChanged)
    def currentStemDurationSec(self):
        s = self._current_sample()
        if not s: return 0.0
        stem = self._project.stem_by_id(s.source_stem_id) if self._project else None
        if not stem: return 0.0
        return stem.duration_samples / max(1, stem.sample_rate)

    # --- Editor: per-sample params ---
    @pyqtProperty(float, notify=editorParamsChanged)
    def currentSampleGainDb(self):
        s = self._current_sample()
        return float(getattr(s, "gain_db", 0.0)) if s else 0.0

    @pyqtProperty(float, notify=editorParamsChanged)
    def currentSamplePitchSemitones(self):
        s = self._current_sample()
        return float(getattr(s, "pitch_semitones", 0.0)) if s else 0.0

    @pyqtProperty(float, notify=editorParamsChanged)
    def currentSampleTimeStretch(self):
        s = self._current_sample()
        return float(getattr(s, "time_stretch", 1.0)) if s else 1.0

    @pyqtProperty(bool, notify=editorParamsChanged)
    def currentSampleReverse(self):
        s = self._current_sample()
        return bool(getattr(s, "reverse", False)) if s else False

    @pyqtProperty(float, notify=editorParamsChanged)
    def currentSampleFadeInMs(self):
        s = self._current_sample()
        if not s: return 0.0
        sr = getattr(self.engine, "sample_rate", 44100)
        return getattr(s, "fade_in_samples", 0) / sr * 1000.0

    @pyqtProperty(float, notify=editorParamsChanged)
    def currentSampleFadeOutMs(self):
        s = self._current_sample()
        if not s: return 0.0
        sr = getattr(self.engine, "sample_rate", 44100)
        return getattr(s, "fade_out_samples", 0) / sr * 1000.0

    # --- Beats for snap ---
    @pyqtProperty(list, notify=currentSampleChanged)
    def currentSampleBeats(self):
        s = self._current_sample()
        if not s or not self._project: return []
        stem = self._project.stem_by_id(s.source_stem_id)
        if not stem or stem.duration_samples <= 0: return []
        analysis = next(
            (a for a in self._project.analyses
             if getattr(a, "source_id", None) == getattr(stem, "source_id", None)),
            None,
        )
        if not analysis: return []
        beats = getattr(analysis, "beats", None) or []
        total = float(stem.duration_samples)
        out = []
        for b in beats:
            pos = (
                getattr(b, "start_samples", None)
                or getattr(b, "position_samples", None)
                or getattr(b, "sample", None)
                or 0
            )
            f = pos / total
            if 0.0 <= f <= 1.0:
                out.append(float(f))
        return out

    @pyqtProperty(bool, notify=editorParamsChanged)
    def snapToBeats(self): return self._snap_to_beats

    @pyqtProperty(float, notify=zoomChanged)
    def zoomStart(self): return self._zoom_start

    @pyqtProperty(float, notify=zoomChanged)
    def zoomEnd(self): return self._zoom_end

    @pyqtProperty(bool, notify=settingsChanged)
    def qualityModeChosen(self):
        return self._settings.quality_mode is not None

    @pyqtProperty(str, notify=settingsChanged)
    def qualityMode(self):
        return self._settings.quality_mode or ""

    # ---- Preset properties --------------------------------------------

    @pyqtProperty(str, notify=settingsChanged)
    def vocalPreset(self): return self._settings.slicing.vocal_preset
    @pyqtProperty(str, notify=settingsChanged)
    def drumPreset(self):  return self._settings.slicing.drum_preset
    @pyqtProperty(str, notify=settingsChanged)
    def loopPreset(self):  return self._settings.slicing.loop_preset

    @pyqtProperty(float, notify=settingsChanged)
    def minVocalPhraseMs(self): return self._settings.slicing.min_vocal_phrase_ms
    @pyqtProperty(float, notify=settingsChanged)
    def maxVocalPhraseMs(self): return self._settings.slicing.max_vocal_phrase_ms
    @pyqtProperty(float, notify=settingsChanged)
    def vocalPhraseMinGapMs(self): return self._settings.slicing.vocal_phrase_min_gap_ms
    @pyqtProperty(int, notify=settingsChanged)
    def maxVocalPhrases(self): return self._settings.slicing.max_vocal_phrases
    @pyqtProperty(int, notify=settingsChanged)
    def vocalChopLengthMs(self): return self._settings.slicing.vocal_chop_length_ms
    @pyqtProperty(int, notify=settingsChanged)
    def maxVocalChops(self): return self._settings.slicing.max_vocal_chops
    @pyqtProperty(int, notify=settingsChanged)
    def drumHitLengthMs(self): return self._settings.slicing.drum_hit_length_ms
    @pyqtProperty(int, notify=settingsChanged)
    def maxDrumHits(self): return self._settings.slicing.max_drum_hits
    @pyqtProperty(float, notify=settingsChanged)
    def drumHitMinSpacingBeats(self):
        return self._settings.slicing.drum_hit_min_spacing_beats
    @pyqtProperty(int, notify=settingsChanged)
    def nLoopsPerStem(self): return self._settings.slicing.n_loops_per_stem
    @pyqtProperty(int, notify=settingsChanged)
    def drumLoopBars(self): return self._settings.slicing.drum_loop_bars
    @pyqtProperty(int, notify=settingsChanged)
    def bassLoopBars(self): return self._settings.slicing.bass_loop_bars
    @pyqtProperty(int, notify=settingsChanged)
    def melodyPhraseBars(self): return self._settings.slicing.melody_phrase_bars

    # Pad layout
    @pyqtProperty(int, notify=settingsChanged)
    def padsDrumHit(self): return self._settings.pad_layout.pads_drum_hit
    @pyqtProperty(int, notify=settingsChanged)
    def padsDrumLoop(self): return self._settings.pad_layout.pads_drum_loop
    @pyqtProperty(int, notify=settingsChanged)
    def padsVocalChop(self): return self._settings.pad_layout.pads_vocal_chop
    @pyqtProperty(int, notify=settingsChanged)
    def padsVocalPhrase(self): return self._settings.pad_layout.pads_vocal_phrase
    @pyqtProperty(int, notify=settingsChanged)
    def padsMelody(self): return self._settings.pad_layout.pads_melody
    @pyqtProperty(int, notify=settingsChanged)
    def padsBassLoop(self): return self._settings.pad_layout.pads_bass_loop
    @pyqtProperty(int, notify=settingsChanged)
    def gridSize(self): return self._settings.pad_layout.grid_size

    # Playback
    @pyqtProperty(int, notify=settingsChanged)
    def blockSize(self): return self._settings.playback.block_size
    @pyqtProperty(int, notify=settingsChanged)
    def sampleRate(self): return self._settings.playback.sample_rate
    @pyqtProperty(float, notify=settingsChanged)
    def latencyMs(self): return self._settings.playback.latency_ms
    @pyqtProperty(bool, notify=settingsChanged)
    def pressHoldLoop(self): return self._settings.playback.press_hold_loop
    @pyqtProperty(bool, notify=settingsChanged)
    def autoNormalizeStems(self): return self._settings.playback.auto_normalize_stems
    @pyqtProperty(bool, notify=settingsChanged)
    def autoChokeDrums(self): return self._settings.playback.auto_choke_drums

    @pyqtProperty(str, notify=settingsChanged)
    def nrLevelPre(self): return self._settings.playback.nr_level_pre

    @pyqtProperty(str, notify=settingsChanged)
    def nrLevelPost(self): return self._settings.playback.nr_level_post

    # ---- QML slots — quality mode -------------------------------------

    @pyqtSlot(str)
    def setQualityMode(self, mode: str):
        if mode not in ("fast", "quality"):
            return
        self._settings.quality_mode = mode
        self._settings.save(SETTINGS_PATH)
        self.settingsChanged.emit()
        self._set_status(
            f"Mode: {'⚡ Fast' if mode == 'fast' else '✦ Quality'} — Load a track to begin."
        )

    @pyqtSlot()
    def resetQualityMode(self):
        self._settings.quality_mode = None
        self._settings.save(SETTINGS_PATH)
        self.settingsChanged.emit()
        self.needsQualityMode.emit()

    # ---- NEW: QML slots — MIDI detection ---

    @pyqtSlot()
    def detectMidiKeyboards(self):
        """Auto-detect connected MIDI keyboards."""
        try:
            from app.hardware.midi.detector import detect_keyboards
            keyboards = detect_keyboards(probe_seconds=0.5)
            self._midi_keyboards = [
                {
                    "port_name": kb.port_name,
                    "display_name": kb.display_name,
                    "key_count": kb.key_count,
                }
                for kb in keyboards
            ]
            self._midi_keyboard_model.set_keyboards(self._midi_keyboards)
            if self._midi_keyboards:
                self._selected_midi_keyboard = self._midi_keyboards[0]
                self._set_status(f"Detected {len(self._midi_keyboards)} MIDI keyboard(s)")
            else:
                self._set_status("No MIDI keyboards detected")
            self.midiKeyboardsDetected.emit()
        except Exception as e:
            log.warning("MIDI detection failed: %s", e)
            self._set_status(f"MIDI detection error: {e}")

    @pyqtSlot(int)
    def selectMidiKeyboard(self, index: int):
        """Select a MIDI keyboard by model index."""
        self._midi_keyboard_model.select_keyboard(index)
        self._selected_midi_keyboard = self._midi_keyboard_model.selected_keyboard()
        if self._selected_midi_keyboard:
            self._set_status(f"Selected: {self._selected_midi_keyboard['display_name']}")
        self.midiKeyboardSelected.emit()

    # ---- NEW: QML slots — BPM detection ---

    @pyqtSlot()
    def detectBpmOfCurrentSource(self):
        """Detect BPM of the currently loaded audio source."""
        if not self._project or not self._project.sources:
            self._set_status("No audio source loaded")
            return

        try:
            from app.audio.analysis.bpm_detector import detect_bpm
            source = self._project.sources[0]
            if not source.path:
                self._set_status("Source has no path")
                return

            result = detect_bpm(source.path)
            self._detected_bpm = result.bpm
            self._detected_time_signature = f"{result.time_signature[0]}/{result.time_signature[1]}"
            self._bpm_confidence = result.confidence

            # Also detect key
            try:
                from app.audio.analysis.key_detector_bilingual import detect_key_bilingual
                key_result = detect_key_bilingual(source.path)
                self._detected_key = key_result.english if key_result else ""
            except Exception:
                self._detected_key = ""

            self._set_status(
                f"BPM: {self._detected_bpm:.2f}  "
                f"Time Sig: {self._detected_time_signature}  "
                f"Confidence: {self._bpm_confidence:.2f}  "
                f"Key: {self._detected_key}"
            )
            self.bpmDetected.emit()
        except Exception as e:
            log.warning("BPM detection failed: %s", e)
            self._set_status(f"BPM detection error: {e}")

    # ---- NEW: QML slots — Sample analysis ---

    @pyqtSlot()
    def analyzeSampleForAnnotations(self):
        """Analyze currently selected sample and detect phrases/hits/breaks."""
        if not self._project:
            self._set_status("No project loaded")
            return

        s = self._current_sample()
        if not s or not s.source_stem_id:
            self._set_status("No sample selected")
            return

        stem = self._project.stem_by_id(s.source_stem_id)
        if not stem or not stem.path or not stem.path.exists():
            self._set_status("Sample stem file not found")
            return

        try:
            from app.audio.analysis.sample_analyzer import analyze_sample
            annotations = analyze_sample(stem.path)

            # Convert to QML-friendly dicts (fractions 0..1)
            total_samples = float(stem.duration_samples)
            qml_annotations = []
            for ann in annotations:
                start_frac = ann.start_sample / total_samples
                end_frac = ann.end_sample / total_samples
                qml_annotations.append({
                    "start_frac": max(0.0, min(1.0, start_frac)),
                    "end_frac": max(0.0, min(1.0, end_frac)),
                    "kind": ann.kind.value,
                    "color": ann.color,
                    "label": ann.label,
                })

            self._annotations = qml_annotations
            self._annotation_model.set_annotations(qml_annotations)
            self._set_status(f"Analyzed: {len(annotations)} regions detected")
            self.sampleAnnotationsAnalyzed.emit()
        except Exception as e:
            log.warning("Sample analysis failed: %s", e)
            self._set_status(f"Analysis error: {e}")

    # ---- QML slots — pad interaction ----------------------------------

    @pyqtSlot(str)
    def loadTrack(self, file_url: str):
        path = self._qml_file_to_path(file_url)
        if not path.exists():
            self._set_status(f"File not found: {path}")
            return
        self._set_status(f"Loading {path.name}…")
        self._start_import(path)

    @pyqtSlot(int)
    def triggerPad(self, pad_index: int):
        if not self._project: return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)): return
        pad = bank.pads[pad_index]
        if not pad.sample_id: return
        sample = self._project.sample_by_id(pad.sample_id)
        if not sample: return
        self.engine.trigger_pad(pad, sample)
        self._pad_model.set_active(pad_index, True)
        self._hold_looping[pad_index] = False
        import time
        self._trigger_wallclock[pad_index] = time.monotonic()
        self._trigger_sample_len[pad_index] = sample.length_samples
        self._set_current_pad(pad_index)

    @pyqtSlot(int)
    def releasePad(self, pad_index: int):
        if not self._project: return
        bank = self._project.active_bank()
        if not bank: return
        pad = bank.pads[pad_index]
        if self._settings.playback.press_hold_loop:
            if self._hold_looping.get(pad_index):
                self.engine.release_pad(pad)
                self._hold_looping[pad_index] = False
        if pad.mode in (PadMode.HOLD, PadMode.GATE):
            self.engine.release_pad(pad)
        self._pad_model.set_active(pad_index, False)

    @pyqtSlot(int)
    def padHoldTick(self, pad_index: int):
        if not self._settings.playback.press_hold_loop: return
        if not self._project or self._hold_looping.get(pad_index): return
        bank = self._project.active_bank()
        if not bank: return
        pad = bank.pads[pad_index]
        if not pad.sample_id: return
        sample = self._project.sample_by_id(pad.sample_id)
        if not sample: return
        import time
        trigger_t = self._trigger_wallclock.get(pad_index, 0)
        sample_len_samples = self._trigger_sample_len.get(pad_index, 0)
        if not trigger_t or not sample_len_samples:
            return
        sample_dur_s = sample_len_samples / max(1, self.engine.sample_rate)
        elapsed = time.monotonic() - trigger_t
        if elapsed < sample_dur_s - 0.05:
            return
        if pad.mode == PadMode.ONE_SHOT:
            old_mode = pad.mode
            pad.mode = PadMode.LOOP
            self.engine.trigger_pad(pad, sample)
            pad.mode = old_mode
            self._hold_looping[pad_index] = True
            self._trigger_wallclock[pad_index] = time.monotonic() + 999.0

    @pyqtSlot()
    def stopAll(self):
        self.engine.stop_all()
        for p in (self._project.active_bank().pads if self._project else []):
            self._pad_model.set_active(p.index, False)
        self._hold_looping.clear()

    @pyqtSlot(int)
    def cyclePadMode(self, pad_index: int):
        if not self._project: return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)): return
        pad = bank.pads[pad_index]
        if not pad.sample_id: return
        pad.mode = PadMode.LOOP if pad.mode == PadMode.ONE_SHOT else PadMode.ONE_SHOT
        self.engine.release_pad(pad)
        self._pad_model.notify_mode_changed(pad_index)
        self._set_status(f"Pad {pad_index + 1}: {pad.mode.value}")

    @pyqtSlot(int, str)
    def setPadMode(self, pad_index: int, mode_value: str):
        if not self._project: return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)): return
        try: new_mode = PadMode(mode_value)
        except ValueError: return
        pad = bank.pads[pad_index]
        pad.mode = new_mode
        self.engine.release_pad(pad)
        self._pad_model.notify_mode_changed(pad_index)

    # ---- QML slots — sample editor -----------

    @pyqtSlot(int)
    def openSampleEditor(self, pad_index: int):
        if not self._project: return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)): return
        pad = bank.pads[pad_index]
        if not pad.sample_id: return
        sample = self._project.sample_by_id(pad.sample_id)
        if not sample: return
        sr = self.engine.sample_rate
        self.sampleEditorOpen.emit(
            pad_index, sample.name, sample.gain_db,
            sample.fade_in_samples / sr * 1000,
            sample.fade_out_samples / sr * 1000,
        )

    @pyqtSlot(int, float, float, float)
    def applySampleEdit(self, pad_index: int,
                        gain_db: float, fade_in_ms: float, fade_out_ms: float):
        if not self._project: return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)): return
        pad = bank.pads[pad_index]
        if not pad.sample_id: return
        sample = self._project.sample_by_id(pad.sample_id)
        if not sample: return
        sr = self.engine.sample_rate
        sample.gain_db          = float(gain_db)
        sample.fade_in_samples  = max(0, int(fade_in_ms  / 1000 * sr))
        sample.fade_out_samples = max(0, int(fade_out_ms / 1000 * sr))
        self.engine.register_sample(sample)
        self.editorParamsChanged.emit()
        self._set_status(
            f"{sample.name}: {gain_db:+.1f} dB  "
            f"fade in {fade_in_ms:.0f}ms  fade out {fade_out_ms:.0f}ms"
        )

    # ---- Granular per-param slots ---

    def _apply_to_current(self, mutator) -> Optional[Sample]:
        s = self._current_sample()
        if not s: return None
        self._ensure_originals(s)
        mutator(s)
        try:
            self.engine.register_sample(s)
        except Exception as e:
            log.warning("register_sample failed: %s", e)
        self.editorParamsChanged.emit()
        return s

    @pyqtSlot(float)
    def setCurrentSampleGain(self, db: float):
        self._apply_to_current(lambda s: setattr(s, "gain_db", float(db)))

    @pyqtSlot(float)
    def setCurrentSamplePitch(self, semitones: float):
        self._apply_to_current(
            lambda s: setattr(s, "pitch_semitones", float(semitones)))

    @pyqtSlot(float)
    def setCurrentSampleTimeStretch(self, factor: float):
        f = max(0.25, min(4.0, float(factor)))
        self._apply_to_current(lambda s: setattr(s, "time_stretch", f))

    @pyqtSlot(bool)
    def setCurrentSampleReverse(self, value: bool):
        self._apply_to_current(lambda s: setattr(s, "reverse", bool(value)))

    @pyqtSlot(float)
    def setCurrentSampleFadeInMs(self, ms: float):
        sr = self.engine.sample_rate
        n  = max(0, int(float(ms) / 1000 * sr))
        self._apply_to_current(lambda s: setattr(s, "fade_in_samples", n))

    @pyqtSlot(float)
    def setCurrentSampleFadeOutMs(self, ms: float):
        sr = self.engine.sample_rate
        n  = max(0, int(float(ms) / 1000 * sr))
        self._apply_to_current(lambda s: setattr(s, "fade_out_samples", n))

    @pyqtSlot()
    def resetCurrentSample(self):
        s = self._current_sample()
        if not s: return
        orig = self._sample_originals.get(s.id)
        if not orig: return
        for k, v in orig.items():
            setattr(s, k, v)
        try:
            self.engine.register_sample(s)
        except Exception:
            pass
        self.editorParamsChanged.emit()
        self.currentSampleChanged.emit()
        self._set_status(f"{s.name}: reset to defaults")

    @pyqtSlot()
    def previewCurrentSample(self):
        if self._current_pad_index < 0 or not self._project: return
        bank = self._project.active_bank()
        if not bank: return
        pad = bank.pads[self._current_pad_index]
        s = self._current_sample()
        if not s or not pad: return
        try:
            self.engine.trigger_pad(pad, s)
        except Exception as e:
            log.warning("preview failed: %s", e)

    @pyqtSlot(bool)
    def setSnapToBeats(self, value: bool):
        self._snap_to_beats = bool(value)
        self.editorParamsChanged.emit()

    @pyqtSlot(float, float)
    def setWaveformZoom(self, start_frac: float, end_frac: float):
        a = max(0.0, min(1.0, float(start_frac)))
        b = max(0.0, min(1.0, float(end_frac)))
        if b - a < 0.02:
            return
        self._zoom_start, self._zoom_end = a, b
        self.zoomChanged.emit()

    @pyqtSlot()
    def resetWaveformZoom(self):
        self._zoom_start, self._zoom_end = 0.0, 1.0
        self.zoomChanged.emit()

    # ---- QML slots — settings -----------------------------------------

    @pyqtSlot(str)
    def applyVocalPreset(self, name: str):
        self._settings.slicing.apply_vocal_preset(name)
        self._save_and_notify()

    @pyqtSlot(str)
    def applyDrumPreset(self, name: str):
        self._settings.slicing.apply_drum_preset(name)
        self._save_and_notify()

    @pyqtSlot(str)
    def applyLoopPreset(self, name: str):
        self._settings.slicing.apply_loop_preset(name)
        self._save_and_notify()

    @pyqtSlot(float, float, float, int, int, int)
    def applyVocalCustom(self, min_ms, max_ms, gap_ms,
                         max_phrases, chop_ms, max_chops):
        s = self._settings.slicing
        s.vocal_preset            = "Custom"
        s.min_vocal_phrase_ms     = min_ms
        s.max_vocal_phrase_ms     = max_ms
        s.vocal_phrase_min_gap_ms = gap_ms
        s.max_vocal_phrases       = int(max_phrases)
        s.vocal_chop_length_ms    = int(chop_ms)
        s.max_vocal_chops         = int(max_chops)
        self._save_and_notify()

    @pyqtSlot(int, int, float)
    def applyDrumCustom(self, hit_ms, max_hits, spacing_beats):
        s = self._settings.slicing
        s.drum_preset                  = "Custom"
        s.drum_hit_length_ms           = int(hit_ms)
        s.max_drum_hits                = int(max_hits)
        s.drum_hit_min_spacing_beats   = float(spacing_beats)
        self._save_and_notify()

    @pyqtSlot(int, int, int, int)
    def applyLoopCustom(self, n_loops, drum_bars, bass_bars, melody_bars):
        s = self._settings.slicing
        s.loop_preset         = "Custom"
        s.n_loops_per_stem    = int(n_loops)
        s.drum_loop_bars      = int(drum_bars)
        s.bass_loop_bars      = int(bass_bars)
        s.melody_phrase_bars  = int(melody_bars)
        self._save_and_notify()

    @pyqtSlot(int, int, int, int, int, int, int)
    def applyPadLayout(self, pads_drum_hit, pads_drum_loop,
                       pads_vocal_chop, pads_vocal_phrase,
                       pads_melody, pads_bass_loop, grid_size):
        pl = self._settings.pad_layout
        pl.pads_drum_hit    = int(pads_drum_hit)
        pl.pads_drum_loop   = int(pads_drum_loop)
        pl.pads_vocal_chop  = int(pads_vocal_chop)
        pl.pads_vocal_phrase = int(pads_vocal_phrase)
        pl.pads_melody      = int(pads_melody)
        pl.pads_bass_loop   = int(pads_bass_loop)
        pl.grid_size        = int(grid_size)
        self._save_and_notify()
        if self._project:
            self._reslice_with_new_settings()

    @pyqtSlot(int, int, bool, bool, bool, str, str)
    def applyPlaybackSettings(self, block_size, sample_rate,
                              press_hold_loop, auto_normalize, auto_choke,
                              nr_level_pre, nr_level_post):
        pb = self._settings.playback
        pb.block_size           = int(block_size)
        pb.sample_rate          = int(sample_rate)
        pb.press_hold_loop      = bool(press_hold_loop)
        pb.auto_normalize_stems = bool(auto_normalize)
        pb.auto_choke_drums     = bool(auto_choke)
        if nr_level_pre in ("off", "light", "strong"):
            pb.nr_level_pre = nr_level_pre
        if nr_level_post in ("off", "light", "strong"):
            pb.nr_level_post = nr_level_post
        self._save_and_notify()
        self._rebuild_engine()
        if self._project:
            self.engine.load_stems(self._project.stems)
            for s in self._project.samples:
                self.engine.register_sample(s)

    @pyqtSlot()
    def reslice(self):
        if self._project:
            self._reslice_with_new_settings()

    def _reslice_with_new_settings(self):
        from app.audio.slicing.auto_slicer import AutoSlicer
        from app.audio.slicing.pad_assigner import PadAssigner
        slicer   = AutoSlicer(self._settings.to_slicer_config())
        assigner = PadAssigner(layout=self._settings.pad_layout)
        self._project.samples.clear()
        self._project.banks.clear()
        for analysis in self._project.analyses:
            stems = [s for s in self._project.stems
                     if s.source_id == analysis.source_id]
            self._project.samples.extend(slicer.slice_all(stems, analysis))
        bank = assigner.auto_assign(self._project.samples)
        self._project.banks.append(bank)
        self._project.active_bank_id = bank.id
        for s in self._project.samples:
            self.engine.register_sample(s)
        self._pad_model.set_pads(bank.pads)
        self._sample_originals.clear()
        self._current_pad_index = -1
        self._current_peaks = []
        self.currentSampleChanged.emit()
        self.editorParamsChanged.emit()
        filled = sum(1 for p in bank.pads if p.sample_id)
        self._set_status(
            f"Re-sliced: {len(self._project.samples)} samples, "
            f"{filled} pads filled"
        )

    def _save_and_notify(self):
        self._settings.save(SETTINGS_PATH)
        self.settingsChanged.emit()

    # ---- Import internals -----

    def _start_import(self, path: Path):
        if self._import_thread and self._import_thread.isRunning():
            self._set_status("Import already running.")
            return
        pipeline = self._build_pipeline()
        self._import_thread = QThread()
        self._worker = ImportWorker(pipeline, path)
        self._worker.moveToThread(self._import_thread)
        self._import_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_imported)
        self._worker.error.connect(self._on_import_error)
        self._worker.finished.connect(self._import_thread.quit)
        self._worker.error.connect(self._import_thread.quit)
        self._import_thread.finished.connect(self._worker.deleteLater)
        self._import_thread.finished.connect(self._import_thread.deleteLater)
        self._import_thread.start()

    def _on_progress(self, p: float, msg: str):
        self._set_status(f"{int(p * 100)}%  {msg}")
        self.importProgress.emit(p, msg)

    def _on_imported(self, project: Project):
        self._project = project
        self.engine.load_stems(project.stems)
        for s in project.samples:
            self.engine.register_sample(s)
        bank = project.active_bank()
        if bank:
            self._pad_model.set_pads(bank.pads)
        if project.analyses:
            self._bpm = project.analyses[0].bpm
            self._key = project.analyses[0].key or ""
            self.bpmChanged.emit()
        self._stem_peak_cache.clear()
        self._sample_originals.clear()
        self._current_pad_index = -1
        self._current_peaks = []
        self._zoom_start, self._zoom_end = 0.0, 1.0
        self.zoomChanged.emit()
        self.currentSampleChanged.emit()
        self.editorParamsChanged.emit()
        self._set_status(f"Loaded — {len(project.samples)} samples ready.")
        self.projectChanged.emit()
        self.importDone.emit()

    # ── Sample editor helpers ──────────────────────────────────────

    def _current_sample(self):
        if not self._project or self._current_pad_index < 0:
            return None
        bank = self._project.active_bank()
        if not bank or self._current_pad_index >= len(bank.pads):
            return None
        pad = bank.pads[self._current_pad_index]
        if not pad.sample_id:
            return None
        return self._project.sample_by_id(pad.sample_id)

    def _ensure_originals(self, sample: Sample):
        if sample.id in self._sample_originals:
            return
        self._sample_originals[sample.id] = {
            "start_sample":      getattr(sample, "start_sample", 0),
            "end_sample":        getattr(sample, "end_sample", 0),
            "gain_db":           getattr(sample, "gain_db", 0.0),
            "pitch_semitones":   getattr(sample, "pitch_semitones", 0.0),
            "time_stretch":      getattr(sample, "time_stretch", 1.0),
            "reverse":           getattr(sample, "reverse", False),
            "fade_in_samples":   getattr(sample, "fade_in_samples", 0),
            "fade_out_samples":  getattr(sample, "fade_out_samples", 0),
        }

    def _set_current_pad(self, pad_index: int):
        if pad_index == self._current_pad_index:
            return
        self._current_pad_index = pad_index
        self._zoom_start, self._zoom_end = 0.0, 1.0
        self.zoomChanged.emit()
        self._refresh_current_peaks()
        s = self._current_sample()
        if s:
            self._ensure_originals(s)
        self.currentSampleChanged.emit()
        self.editorParamsChanged.emit()

    def _refresh_current_peaks(self):
        s = self._current_sample()
        if not s or not s.source_stem_id:
            self._current_peaks = []
            return
        cached = self._stem_peak_cache.get(s.source_stem_id)
        if cached is not None:
            self._current_peaks = cached
            return
        stem = self._project.stem_by_id(s.source_stem_id)
        if not stem or not stem.path or not stem.path.exists():
            self._current_peaks = []
            return
        from app.audio.dsp.waveform_peaks import compute_peaks
        peaks = compute_peaks(stem.path, num_bins=400)
        self._stem_peak_cache[s.source_stem_id] = peaks
        self._current_peaks = peaks

    @pyqtSlot(int)
    def selectPad(self, pad_index: int):
        if not self._project: return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)): return
        if bank.pads[pad_index].sample_id:
            self._set_current_pad(pad_index)

    @pyqtSlot(float, float)
    def setCurrentSampleRegion(self, start_frac: float, end_frac: float):
        s = self._current_sample()
        if not s or not s.source_stem_id: return
        stem = self._project.stem_by_id(s.source_stem_id)
        if not stem: return
        a = max(0.0, min(1.0, min(start_frac, end_frac)))
        b = max(0.0, min(1.0, max(start_frac, end_frac)))
        min_samples = stem.sample_rate // 20
        self._ensure_originals(s)
        s.start_sample = int(a * stem.duration_samples)
        s.end_sample = max(s.start_sample + min_samples,
                            int(b * stem.duration_samples))
        self.engine.register_sample(s)
        self.currentSampleChanged.emit()

    def _on_import_error(self, msg: str):
        self._set_status(f"Error: {msg}")
        self.importError.emit(msg)

    def _set_status(self, s: str):
        self._status = s
        self.statusChanged.emit()