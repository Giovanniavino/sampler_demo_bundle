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

from app.audio.dsp.effects import EffectsChain
from app.audio.playback.engine import SounddevicePlaybackEngine
from app.audio.separation.heuristic import HeuristicSeparator
from app.audio.separation.separator import DemucsSeparator, DummySeparator
from app.audio.slicing.pad_assigner import CATEGORY_COLORS
from app.audio.metronome import Metronome
from app.audio.recording import Recorder, Player, RecordedSequence
from app.hardware.device_sync import DeviceManager
from app.core.models import Pad, PadMode, Project, Sample, SampleCategory
from app.core.settings import (
    DRUM_PRESETS, LOOP_PRESETS, VOCAL_PRESETS, AppSettings,
)
from app.services.pipeline import SamplerPipeline

log = logging.getLogger(__name__)

SETTINGS_PATH = Path("data/settings.json")


def _default_fx_state() -> dict:
    """Default per-chain effect parameters (mirrors EffectsChain defaults)."""
    return {
        "eq":     {"enabled": False, "low_gain_db": 0.0,
                   "mid_gain_db": 0.0, "high_gain_db": 0.0},
        "comp":   {"enabled": False, "threshold_db": -18.0, "ratio": 4.0,
                   "attack_ms": 10.0, "release_ms": 120.0, "makeup_db": 0.0},
        "reverb": {"enabled": False, "room_size": 0.7, "damping": 0.4,
                   "wet": 0.35, "dry": 0.70, "width": 1.0},
        "delay":  {"enabled": False, "time_ms": 300.0,
                   "feedback": 0.35, "mix": 0.30},
        "chorus": {"enabled": False, "rate_hz": 0.8,
                   "depth_ms": 4.0, "mix": 0.40},
    }


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
        if role == self.ColorRole:      return p.color or "#888888"
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
# Stem Browser model (for manual sample creation from stems)
# ---------------------------------------------------------------------------

class StemBrowserModel(QAbstractListModel):
    """Lists the available stems (drums/bass/vocals/other) for the browser."""
    StemIdRole       = Qt.ItemDataRole.UserRole + 1
    StemTypeRole     = Qt.ItemDataRole.UserRole + 2
    DisplayNameRole  = Qt.ItemDataRole.UserRole + 3
    DurationRole     = Qt.ItemDataRole.UserRole + 4
    IsSelectedRole   = Qt.ItemDataRole.UserRole + 5
    ColorRole        = Qt.ItemDataRole.UserRole + 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stems = []
        self._selected_idx = 0

    def roleNames(self):
        return {
            self.StemIdRole:      b"stemId",
            self.StemTypeRole:    b"stemType",
            self.DisplayNameRole: b"displayName",
            self.DurationRole:    b"durationSec",
            self.IsSelectedRole:  b"isSelected",
            self.ColorRole:       b"color",
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._stems)

    def data(self, index, role):
        if not index.isValid():
            return None
        st = self._stems[index.row()]
        if role == self.StemIdRole:       return st.get("stem_id", "")
        if role == self.StemTypeRole:     return st.get("stem_type", "")
        if role == self.DisplayNameRole:  return st.get("display_name", "")
        if role == self.DurationRole:     return st.get("duration_sec", 0.0)
        if role == self.IsSelectedRole:   return index.row() == self._selected_idx
        if role == self.ColorRole:        return st.get("color", "#888888")
        return None

    def set_stems(self, stems: list[dict]):
        self.beginResetModel()
        self._stems = stems
        self._selected_idx = 0 if stems else -1
        self.endResetModel()

    def select(self, index: int):
        if 0 <= index < len(self._stems):
            old = self._selected_idx
            self._selected_idx = index
            for i in (old, index):
                if 0 <= i < len(self._stems):
                    idx = self.index(i, 0)
                    self.dataChanged.emit(idx, idx, [self.IsSelectedRole])

    def selected_stem_id(self) -> Optional[str]:
        if 0 <= self._selected_idx < len(self._stems):
            return self._stems[self._selected_idx].get("stem_id")
        return None




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
    fxChanged                   = pyqtSignal()
    # New signals
    midiKeyboardsDetected       = pyqtSignal()
    midiKeyboardSelected        = pyqtSignal()
    bpmDetected                 = pyqtSignal()
    sampleAnnotationsAnalyzed   = pyqtSignal()
    outputDevicesRefreshed      = pyqtSignal()
    outputDeviceChanged         = pyqtSignal()
    playbackPositionChanged     = pyqtSignal()
    # NEW: Transport / Metronome / Recording
    metronomeStateChanged       = pyqtSignal()
    beatTick                    = pyqtSignal(int, bool)  # beat_index, is_downbeat
    recordStateChanged          = pyqtSignal()
    playerStateChanged          = pyqtSignal()
    sequenceUpdated             = pyqtSignal()
    bounceStateChanged          = pyqtSignal()
    looperStateChanged          = pyqtSignal()
    looperBarsChanged           = pyqtSignal()
    deviceStateChanged          = pyqtSignal()
    # NEW: Stem Browser
    browserStemsChanged         = pyqtSignal()
    browserSelectionChanged     = pyqtSignal()
    browserStemViewChanged      = pyqtSignal()
    browserPlayheadChanged      = pyqtSignal()

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
        # Pads with a LOOP voice currently running (drives tap-to-toggle).
        self._looping_pads: set[int] = set()
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
        # View window: the slice of the STEM shown in the editor waveform.
        # This is the sample region plus a context margin on each side.
        self._view_start_sample: int = 0
        self._view_end_sample: int = 1
        self._view_context_fraction: float = 0.15  # 15% margin each side

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

        # NEW: output device list & selection
        self._output_devices: list[dict] = []
        self._selected_output_device: Optional[str] = None  # None = system default

        # NEW: Stem Browser state ────────────────────────────────────────
        self._stem_browser_model = StemBrowserModel()
        self._browser_stem_id: Optional[str] = None      # currently viewed stem
        self._browser_peaks: list[float] = []            # peaks of viewed stem
        self._browser_view_start: int = 0                # view window (samples)
        self._browser_view_end: int = 1
        self._browser_sel_start: int = 0                 # selection (samples)
        self._browser_sel_end: int = 1
        self._browser_active_marker: str = "start"       # "start" or "end"
        self._browser_peak_cache: dict[str, list[float]] = {}
        # Browser preview playhead tracking
        self._browser_preview_active: bool = False
        self._browser_preview_start: int = 0
        self._browser_preview_end: int = 1
        self._browser_playhead_frac: float = 0.0

        # NEW: per-stem annotation cache (auto-analyzed on pad select)
        self._stem_annotation_cache: dict[str, list[dict]] = {}

        # NEW: playback position tracking (for waveform playhead)
        self._playback_position_frac: float = 0.0
        self._position_timer: Optional[object] = None  # QTimer set up below

        # NEW: Metronome + Recorder + Player
        self._metronome = Metronome(self)
        self._recorder = Recorder(self)
        self._player = Player(
            trigger_cb=self._playback_trigger,
            release_cb=self._playback_release,
            parent=self,
        )
        # Wire signals
        self._metronome.beat.connect(self._on_metronome_beat)
        self._metronome.count_in_finished.connect(self._on_count_in_done)
        self._recorder.stateChanged.connect(self._on_record_state_changed)
        self._recorder.eventLogged.connect(self._on_event_logged)
        self._player.playbackStateChanged.connect(self._on_player_state)

        self._current_beat: int = 0
        self._is_downbeat: bool = False
        self._quantize_percent: float = 0.0  # 0 = no quantize

        # NEW: per-pad + master effect state. Source of truth: pushed to the
        # engine, and used to build chains for offline export.
        self._pad_fx: dict[int, dict] = {}
        self._master_fx: dict = _default_fx_state()
        self._pending_bounce = None       # last live bounce, awaiting save
        # NEW: per-track looper mirror (updated by the position-timer poll).
        self._looper_bars: int = 4
        self._loop_preroll_ms: float = 40.0   # see engine.set_loop_preroll_ms
        self._looper_states: list[str] = ["idle"] * 4
        self._looper_positions: list[float] = [0.0] * 4
        self._looper_undo_available: list[bool] = [False] * 4
        self._track_armed_record: list[bool] = [False] * 4
        self._track_armed_overdub: list[bool] = [False] * 4
        self._last_modified_track: int = 0

        # NEW: virtual hardware device sync (see app.hardware.virtual_device).
        self._device_manager = DeviceManager(cache_dir=cache_dir, parent=self)
        self._device_manager.connectionChanged.connect(
            self._on_device_connection_changed)
        self._device_manager.errorOccurred.connect(self._on_device_error)
        self._device_kits: list[str] = []
        self._device_presets: list[str] = []
        self._device_storage: dict = {
            "total": 0, "free": 0, "used": 0, "sd_path": ""}
        self._device_log: list[str] = []

        # Last-known set of pads with an active voice (drives auto-dim via
        # the 30 Hz position timer — see _update_playback_position).
        self._active_pads_state: set[int] = set()

        self._rebuild_engine()

        # Inject engine into metronome so it can play clicks
        self._metronome.set_engine(self.engine)

        # Start position tracking timer (60 FPS)
        from PyQt6.QtCore import QTimer
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(33)  # ~30 Hz
        self._position_timer.timeout.connect(self._update_playback_position)
        self._position_timer.start()

    # ---- Helpers -------------------------------------------------------

    def _rebuild_engine(self):
        pb = self._settings.playback
        old_engine = getattr(self, "engine", None)
        if old_engine:
            try: old_engine.stop()
            except Exception: pass
        self.engine = SounddevicePlaybackEngine(
            sample_rate=pb.sample_rate,
            block_size=pb.block_size,
            output_device=self._selected_output_device,
        )
        try:
            self.engine.start()
        except Exception as e:
            log.error("Engine start failed: %s", e)
            # The engine may have reset output_device to None during its
            # internal fallback. Sync our state so the UI reflects reality.
            self._selected_output_device = getattr(
                self.engine, "output_device", None
            )
            self._set_status(f"Audio device error — using default. ({e})")
            # Try one clean rebuild on the default device
            try:
                self.engine = SounddevicePlaybackEngine(
                    sample_rate=pb.sample_rate,
                    block_size=pb.block_size,
                    output_device=None,
                )
                self.engine.start()
                self._selected_output_device = None
            except Exception as e2:
                log.error("Default device also failed: %s", e2)
                self._set_status(
                    "No working audio device found. Check your settings."
                )
        self._apply_all_fx_to_engine()

    def _build_pipeline(self) -> SamplerPipeline:
        from app.audio.slicing.auto_slicer import AutoSlicer
        from app.audio.slicing.pad_assigner import PadAssigner
        sep = None
        if self._use_demucs:
            sep = DemucsSeparator(model_name=self._settings.demucs_model)
            # Verify Demucs is actually installed; if not, fall back gracefully
            try:
                available, msg = sep.is_available()
            except Exception:
                available, msg = False, "Demucs check failed"
            if not available:
                log.warning("Demucs unavailable (%s) — falling back to "
                            "heuristic separator", msg)
                self._set_status(
                    "AI separation not installed — using basic separation"
                )
                sep = HeuristicSeparator()
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
        """Start position of the sample, as a fraction of the VIEW WINDOW."""
        s = self._current_sample()
        if not s: return 0.0
        vlen = self._view_end_sample - self._view_start_sample
        if vlen <= 0: return 0.0
        return max(0.0, min(1.0,
            (s.start_sample - self._view_start_sample) / vlen))

    @pyqtProperty(float, notify=currentSampleChanged)
    def currentSampleEndFrac(self):
        """End position of the sample, as a fraction of the VIEW WINDOW."""
        s = self._current_sample()
        if not s: return 1.0
        vlen = self._view_end_sample - self._view_start_sample
        if vlen <= 0: return 1.0
        return max(0.0, min(1.0,
            (s.end_sample - self._view_start_sample) / vlen))

    @pyqtProperty(float, notify=currentSampleChanged)
    def currentStemDurationSec(self):
        """Duration of the VIEW WINDOW in seconds (what the waveform shows)."""
        s = self._current_sample()
        if not s: return 0.0
        stem = self._project.stem_by_id(s.source_stem_id) if self._project else None
        if not stem: return 0.0
        vlen = self._view_end_sample - self._view_start_sample
        return vlen / max(1, stem.sample_rate)

    @pyqtProperty(float, notify=currentSampleChanged)
    def currentSampleDurationSec(self):
        """Duration of the SAMPLE itself (start..end) in seconds."""
        s = self._current_sample()
        if not s: return 0.0
        stem = self._project.stem_by_id(s.source_stem_id) if self._project else None
        if not stem: return 0.0
        return (s.end_sample - s.start_sample) / max(1, stem.sample_rate)

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

    # --- NEW: cutoff, pan, global pitch ---
    @pyqtProperty(float, notify=editorParamsChanged)
    def currentSampleCutoffHz(self):
        s = self._current_sample()
        return float(getattr(s, "cutoff_hz", 20000.0)) if s else 20000.0

    @pyqtProperty(float, notify=editorParamsChanged)
    def currentSampleHighpassHz(self):
        s = self._current_sample()
        return float(getattr(s, "highpass_hz", 20.0)) if s else 20.0

    @pyqtProperty(float, notify=editorParamsChanged)
    def currentSamplePan(self):
        s = self._current_sample()
        return float(getattr(s, "pan", 0.0)) if s else 0.0

    @pyqtProperty(float, notify=settingsChanged)
    def globalPitchSemitones(self):
        return getattr(self.engine, "global_pitch_semitones", 0.0)

    # --- NEW: loop sync to BPM grid ---
    @pyqtProperty(int, notify=editorParamsChanged)
    def currentSampleLoopBeats(self):
        s = self._current_sample()
        return int(getattr(s, "loop_beats", 0)) if s else 0

    @pyqtProperty(float, notify=editorParamsChanged)
    def currentSampleEffectiveBpm(self):
        """BPM that would be used for loop sync (sample's bpm or project bpm)."""
        s = self._current_sample()
        if s and getattr(s, "bpm", None):
            return float(s.bpm)
        return float(getattr(self.engine, "project_bpm", 0.0))

    @pyqtProperty(int, notify=editorParamsChanged)
    def currentSampleSuggestedBeats(self):
        """Auto-detected beat count for the current sample length."""
        s = self._current_sample()
        if not s or not self._project:
            return 0
        # Use the stem for accurate length
        if s.source_stem_id:
            stem = self._project.stem_by_id(s.source_stem_id)
            if stem:
                length = max(0, s.end_sample - s.start_sample)
                bpm = self.currentSampleEffectiveBpm
                if bpm > 0 and length > 0:
                    return SounddevicePlaybackEngine.suggest_loop_beats(
                        length, stem.sample_rate, bpm
                    )
        return 0

    # --- NEW: Output device properties ---
    @pyqtProperty(list, notify=outputDevicesRefreshed)
    def outputDevices(self):
        """List of available audio output devices (dicts)."""
        return self._output_devices

    @pyqtProperty(str, notify=outputDeviceChanged)
    def currentOutputDevice(self):
        """Name of the currently selected output device, or 'Default'."""
        if self._selected_output_device:
            return self._selected_output_device
        try:
            return SounddevicePlaybackEngine.get_default_output_device_name()
        except Exception:
            return "Default"

    # --- NEW: Stems output folder property ---
    @pyqtProperty(str, notify=settingsChanged)
    def stemsOutputDir(self):
        """User-chosen folder where stems get saved. Empty = default cache."""
        return getattr(self._settings, "stems_output_dir", "") or ""

    @pyqtProperty(str, notify=settingsChanged)
    def stemsOutputDirDisplay(self):
        """Human-friendly display: real path or '(default cache folder)'."""
        d = getattr(self._settings, "stems_output_dir", "") or ""
        if not d:
            return "(default cache folder)"
        return d

    # --- NEW: Metronome properties ---
    @pyqtProperty(bool, notify=metronomeStateChanged)
    def metronomeEnabled(self):
        return self._metronome.enabled

    @pyqtProperty(int, notify=metronomeStateChanged)
    def metronomeCountInBars(self):
        return self._metronome.count_in_bars

    @pyqtProperty(int, notify=beatTick)
    def currentBeat(self):
        return self._current_beat

    @pyqtProperty(bool, notify=beatTick)
    def isDownbeat(self):
        return self._is_downbeat

    @pyqtProperty(bool, notify=metronomeStateChanged)
    def isCountIn(self):
        return self._metronome.is_count_in

    # --- NEW: Recording properties ---
    @pyqtProperty(bool, notify=recordStateChanged)
    def isRecording(self):
        return self._recorder.is_recording

    @pyqtProperty(bool, notify=recordStateChanged)
    def isRecordArmed(self):
        """True if we're waiting for count-in to finish."""
        return self._metronome.is_count_in and not self._recorder.is_recording

    @pyqtProperty(int, notify=sequenceUpdated)
    def recordedEventCount(self):
        return self._recorder.event_count

    @pyqtProperty(float, notify=settingsChanged)
    def quantizePercent(self):
        return self._quantize_percent

    # --- NEW: Player properties ---
    @pyqtProperty(bool, notify=playerStateChanged)
    def isPlayingSequence(self):
        return self._player.is_playing

    @pyqtProperty(bool, notify=playerStateChanged)
    def isPausedSequence(self):
        return self._player.is_paused

    @pyqtProperty(bool, notify=sequenceUpdated)
    def hasRecordedSequence(self):
        return self._recorder.event_count > 0 or self._player._sequence is not None

    # --- NEW: Stem Browser properties ---
    @pyqtProperty(QObject, constant=True)
    def stemBrowserModel(self): return self._stem_browser_model

    @pyqtProperty(list, notify=browserStemViewChanged)
    def browserPeaks(self): return self._browser_peaks

    @pyqtProperty(float, notify=browserPlayheadChanged)
    def browserPlayheadFrac(self):
        """Playhead position as fraction of the view window (0 if not playing)."""
        return self._browser_playhead_frac

    @pyqtProperty(bool, notify=browserPlayheadChanged)
    def browserIsPreviewing(self):
        return self._browser_preview_active

    @pyqtProperty(str, notify=browserStemViewChanged)
    def browserStemName(self):
        st = self._project.stem_by_id(self._browser_stem_id) if (
            self._project and self._browser_stem_id) else None
        if not st:
            return ""
        return st.stem_type.value if hasattr(st.stem_type, "value") else str(st.stem_type)

    @pyqtProperty(float, notify=browserSelectionChanged)
    def browserSelStartFrac(self):
        """Selection start as fraction of the browser view window."""
        vlen = self._browser_view_end - self._browser_view_start
        if vlen <= 0: return 0.0
        return max(0.0, min(1.0,
            (self._browser_sel_start - self._browser_view_start) / vlen))

    @pyqtProperty(float, notify=browserSelectionChanged)
    def browserSelEndFrac(self):
        """Selection end as fraction of the browser view window."""
        vlen = self._browser_view_end - self._browser_view_start
        if vlen <= 0: return 1.0
        return max(0.0, min(1.0,
            (self._browser_sel_end - self._browser_view_start) / vlen))

    @pyqtProperty(float, notify=browserSelectionChanged)
    def browserSelStartSec(self):
        st = self._project.stem_by_id(self._browser_stem_id) if (
            self._project and self._browser_stem_id) else None
        sr = st.sample_rate if st else 44100
        return self._browser_sel_start / sr

    @pyqtProperty(float, notify=browserSelectionChanged)
    def browserSelEndSec(self):
        st = self._project.stem_by_id(self._browser_stem_id) if (
            self._project and self._browser_stem_id) else None
        sr = st.sample_rate if st else 44100
        return self._browser_sel_end / sr

    @pyqtProperty(float, notify=browserSelectionChanged)
    def browserSelDurationSec(self):
        st = self._project.stem_by_id(self._browser_stem_id) if (
            self._project and self._browser_stem_id) else None
        sr = st.sample_rate if st else 44100
        return (self._browser_sel_end - self._browser_sel_start) / sr

    @pyqtProperty(str, notify=browserSelectionChanged)
    def browserActiveMarker(self): return self._browser_active_marker

    # --- NEW: Playback position (for waveform playhead) ---
    @pyqtProperty(float, notify=playbackPositionChanged)
    def playbackPositionFrac(self):
        """
        Fractional position (0..1) within the currently playing voice of
        the current pad. Returns 0 if nothing is playing.
        """
        return self._playback_position_frac

    @pyqtProperty(bool, notify=playbackPositionChanged)
    def isPlaying(self):
        """True if a voice exists for the current pad."""
        if self._current_pad_index < 0:
            return False
        try:
            for v in getattr(self.engine, "_voices", []):
                if v.pad_index == self._current_pad_index and v.active:
                    return True
        except Exception:
            pass
        return False

    def _update_playback_position(self):
        """Called by QTimer to push playback position to UI."""
        new_pos = 0.0
        if self._current_pad_index >= 0:
            try:
                for v in getattr(self.engine, "_voices", []):
                    if v.pad_index == self._current_pad_index and v.active:
                        if len(v.audio) > 0:
                            # Within sample boundaries [start, end]
                            # The audio buffer is already cropped to [start, end]
                            new_pos = v.position / len(v.audio)
                        break
            except Exception:
                pass
        # Map to [start_frac, end_frac] of stem
        if new_pos > 0:
            s = self._current_sample()
            if s:
                start_f = self.currentSampleStartFrac
                end_f = self.currentSampleEndFrac
                # The voice plays the rendered audio (start..end of stem)
                # so new_pos (0..1 of voice audio) maps to (start..end) of stem
                new_pos = start_f + (end_f - start_f) * new_pos

        if abs(new_pos - self._playback_position_frac) > 0.001:
            self._playback_position_frac = new_pos
            self.playbackPositionChanged.emit()

        # Browser preview playhead (pad_index == -2)
        if self._browser_preview_active:
            bpos = 0.0
            found = False
            try:
                for v in getattr(self.engine, "_voices", []):
                    if v.pad_index == -2 and v.active and len(v.audio) > 0:
                        voice_frac = v.position / len(v.audio)
                        # Map voice progress onto the browser view window
                        vstart = self._browser_view_start
                        vlen = self._browser_view_end - self._browser_view_start
                        if vlen > 0:
                            abs_pos = (self._browser_preview_start
                                       + voice_frac
                                       * (self._browser_preview_end
                                          - self._browser_preview_start))
                            bpos = (abs_pos - vstart) / vlen
                        found = True
                        break
            except Exception:
                pass
            if not found:
                # Preview finished
                self._browser_preview_active = False
                bpos = 0.0
            if abs(bpos - self._browser_playhead_frac) > 0.001 or not found:
                self._browser_playhead_frac = max(0.0, min(1.0, bpos))
                self.browserPlayheadChanged.emit()

        # Sync pad active state with the actual engine voices so a one-shot
        # pad stays lit for the full duration of its sample (and loop / hold
        # pads dim within ~33 ms of their voice ending).
        try:
            active_now = {v.pad_index
                          for v in self.engine._voices
                          if v.active and v.pad_index >= 0}
        except Exception:
            active_now = set()
        prev = self._active_pads_state
        for idx in active_now - prev:
            self._pad_model.set_active(idx, True)
        for idx in prev - active_now:
            self._pad_model.set_active(idx, False)
        self._active_pads_state = active_now

        # Mirror the engine's per-track looper state on the UI thread so
        # QML can react via notify signals.
        eng = getattr(self, "engine", None)
        if eng is not None:
            changed = False
            for i in range(4):
                new_state = eng.looper_track_state(i)
                new_pos = eng.looper_track_position(i)
                new_undo = eng.looper_track_has_undo(i)
                if (new_state != self._looper_states[i]
                        or abs(new_pos - self._looper_positions[i]) > 0.005
                        or new_undo != self._looper_undo_available[i]):
                    self._looper_states[i] = new_state
                    self._looper_positions[i] = new_pos
                    self._looper_undo_available[i] = new_undo
                    changed = True
            if changed:
                self.looperStateChanged.emit()

    @pyqtProperty(list, notify=currentSampleChanged)
    def currentSampleBeats(self):
        """Beat positions as fractions of the VIEW WINDOW (for grid overlay)."""
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
        vstart = self._view_start_sample
        vlen = self._view_end_sample - self._view_start_sample
        if vlen <= 0: return []
        out = []
        for b in beats:
            pos = (
                getattr(b, "start_samples", None)
                or getattr(b, "position_samples", None)
                or getattr(b, "sample", None)
                or 0
            )
            f = (pos - vstart) / vlen
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
            # NEW: propagate detected BPM to engine
            try:
                self.engine.set_project_bpm(self._detected_bpm)
            except AttributeError:
                pass
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
        # LOOP pads toggle: tapping a running loop stops it instead of
        # stacking another overlapping loop voice.
        if pad.mode == PadMode.LOOP and pad_index in self._looping_pads:
            self.engine.stop_pad(pad_index)
            self._looping_pads.discard(pad_index)
            self._pad_model.set_active(pad_index, False)
            self._set_current_pad(pad_index)
            if self._recorder.is_recording:
                self._recorder.log_release(pad_index)
            return
        self.engine.trigger_pad(pad, sample)
        self._pad_model.set_active(pad_index, True)
        if pad.mode == PadMode.LOOP:
            self._looping_pads.add(pad_index)
        self._hold_looping[pad_index] = False
        import time
        self._trigger_wallclock[pad_index] = time.monotonic()
        self._trigger_sample_len[pad_index] = sample.length_samples
        self._set_current_pad(pad_index)
        # NEW: log event for recording
        if self._recorder.is_recording:
            self._recorder.log_trigger(pad_index, velocity=100)

    @pyqtSlot(int)
    def releasePad(self, pad_index: int):
        if not self._project: return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)): return
        pad = bank.pads[pad_index]
        # LOOP pads are toggled by triggerPad — finger-up does nothing,
        # the loop keeps running until the pad is tapped again.
        if pad.mode == PadMode.LOOP:
            return
        if self._settings.playback.press_hold_loop:
            if self._hold_looping.get(pad_index):
                self.engine.release_pad(pad)
                self._hold_looping[pad_index] = False
        if pad.mode in (PadMode.HOLD, PadMode.GATE):
            self.engine.release_pad(pad)
            self._pad_model.set_active(pad_index, False)
        # ONE_SHOT: don't dim here — the position timer turns off the light
        # when the voice actually ends, so the pad stays lit for the full
        # sample (Serato-style visual feedback).
        if self._recorder.is_recording:
            self._recorder.log_release(pad_index)

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
        self._looping_pads.clear()

    @pyqtSlot(int)
    def stopPad(self, pad_index: int):
        """
        Stop a specific pad's playback (works for LOOP, HOLD, GATE, ONE_SHOT).
        Routed through the engine command queue (thread-safe).
        """
        if not self._project:
            return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)):
            return
        pad = bank.pads[pad_index]
        try:
            self.engine.release_pad(pad)
            # Thread-safe stop via command queue
            if hasattr(self.engine, "stop_pad"):
                self.engine.stop_pad(pad_index)
        except Exception as e:
            log.warning("stopPad failed: %s", e)
        self._pad_model.set_active(pad_index, False)
        self._hold_looping[pad_index] = False
        self._looping_pads.discard(pad_index)

    @pyqtSlot(int)
    def cyclePadMode(self, pad_index: int):
        if not self._project: return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)): return
        pad = bank.pads[pad_index]
        if not pad.sample_id: return
        cycle = [PadMode.ONE_SHOT, PadMode.LOOP, PadMode.HOLD, PadMode.GATE]
        idx = cycle.index(pad.mode) if pad.mode in cycle else 0
        pad.mode = cycle[(idx + 1) % len(cycle)]
        self.engine.release_pad(pad)
        self._pad_model.notify_mode_changed(pad_index)
        self._sync_loop_ready(pad)
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
        self._sync_loop_ready(pad)

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

    # --- NEW: cutoff, pan, global pitch slots ---
    @pyqtSlot(float)
    def setCurrentSampleCutoff(self, hz: float):
        clamped = max(20.0, min(20000.0, float(hz)))
        self._apply_to_current(lambda s: setattr(s, "cutoff_hz", clamped))

    @pyqtSlot(float)
    def setCurrentSampleHighpass(self, hz: float):
        clamped = max(20.0, min(20000.0, float(hz)))
        self._apply_to_current(lambda s: setattr(s, "highpass_hz", clamped))

    @pyqtSlot(float)
    def setCurrentSamplePan(self, pan: float):
        clamped = max(-1.0, min(1.0, float(pan)))
        self._apply_to_current(lambda s: setattr(s, "pan", clamped))

    @pyqtSlot(float)
    def setGlobalPitch(self, semitones: float):
        """Apply global pitch shift to ALL samples in the project."""
        clamped = max(-24.0, min(24.0, float(semitones)))
        try:
            self.engine.set_global_pitch(clamped)
        except AttributeError:
            log.warning("Engine does not support global pitch")
            return
        self.settingsChanged.emit()
        self._set_status(f"Global pitch: {clamped:+.1f} semitones")

    # --- NEW: Loop sync to BPM grid ---
    @pyqtSlot(int)
    def setCurrentSampleLoopBeats(self, beats: int):
        """
        Lock loop length to N beats at sample/project BPM.
        Pass 0 to disable BPM sync (free-running loop).
        """
        n = max(0, min(64, int(beats)))
        self._apply_to_current(lambda s: setattr(s, "loop_beats", n))
        if n > 0:
            self._set_status(
                f"Loop locked to {n} beats @ "
                f"{self.currentSampleEffectiveBpm:.1f} BPM"
            )
        else:
            self._set_status("Loop BPM sync: OFF")

    @pyqtSlot()
    def autoSyncCurrentSampleLoop(self):
        """Auto-detect the best beat count and lock the loop to it."""
        s = self._current_sample()
        if not s:
            return
        suggested = self.currentSampleSuggestedBeats
        if suggested > 0:
            self.setCurrentSampleLoopBeats(suggested)
        else:
            self._set_status("Cannot auto-sync: BPM unknown")

    # --- NEW: Output device slots ---
    @pyqtSlot()
    def refreshOutputDevices(self):
        """Scan available audio output devices."""
        try:
            self._output_devices = SounddevicePlaybackEngine.list_output_devices()
            self._set_status(f"Found {len(self._output_devices)} output device(s)")
            self.outputDevicesRefreshed.emit()
        except Exception as e:
            log.warning("Failed to refresh output devices: %s", e)
            self._set_status(f"Device scan error: {e}")

    @pyqtSlot(str)
    def setOutputDevice(self, device_name: str):
        """
        Switch audio output to a specific device by name.
        Pass empty string or 'Default' to use system default.
        Rebuilds the audio engine and reloads stems/samples.
        Falls back gracefully if the device can't be opened.
        """
        new_device = device_name if device_name and device_name != "Default" else None
        self._switch_device(new_device)

    @pyqtSlot(int)
    def setOutputDeviceByIndex(self, device_index: int):
        """
        Switch audio output by PortAudio device index (more reliable than
        name — names can be duplicated across host APIs). Pass -1 for the
        system default.
        """
        self._switch_device(device_index if device_index >= 0 else None)

    def _switch_device(self, new_device):
        """Shared device-switch logic. new_device may be int index, str name,
        or None (system default)."""
        if new_device == self._selected_output_device:
            return

        self._selected_output_device = new_device
        self._rebuild_engine()

        # _rebuild_engine may have reverted to default on failure.
        # Re-wire the metronome to the (possibly new) engine instance.
        try:
            self._metronome.set_engine(self.engine)
        except Exception:
            pass

        # Reload stems and samples into the new engine
        if self._project:
            try:
                self.engine.load_stems(self._project.stems)
                for s in self._project.samples:
                    self.engine.register_sample(s)
            except Exception as e:
                log.warning("Reloading samples after device switch failed: %s", e)

        actual = self._selected_output_device
        if actual is None:
            self._set_status("Output device: Default")
        else:
            self._set_status(f"Output device set (#{actual})"
                             if isinstance(actual, int)
                             else f"Output device: {actual}")
        self.outputDeviceChanged.emit()

    # --- NEW: Stems output folder slot ---
    @pyqtSlot(str)
    def setStemsOutputDir(self, folder_url: str):
        """
        Set the folder where stems will be saved for new track imports.
        Accepts a file:// URL (from FolderDialog) or a plain path.
        Pass empty string to reset to the default cache folder.
        """
        if folder_url:
            path = self._qml_file_to_path(folder_url)
            folder_str = str(path)
        else:
            folder_str = ""

        # Persist into settings
        if hasattr(self._settings, "stems_output_dir"):
            self._settings.stems_output_dir = folder_str
        else:
            # Fallback if user hasn't applied the settings patch yet
            try:
                setattr(self._settings, "stems_output_dir", folder_str)
            except Exception:
                log.warning("Settings has no 'stems_output_dir' attribute. "
                            "Apply PATCH_settings.md to enable persistence.")
                self.settingsChanged.emit()
                return

        self._save_and_notify()
        if folder_str:
            self._set_status(f"Stems output folder: {folder_str}")
        else:
            self._set_status("Stems output folder reset to default cache")

    # ===================================================================
    # NEW: Transport / Metronome / Recording slots
    # ===================================================================

    @pyqtSlot()
    def toggleMetronome(self):
        """Turn metronome on/off."""
        if self._metronome.enabled:
            self._metronome.stop()
            self._set_status("Metronome: OFF")
        else:
            # Use detected/loaded BPM
            bpm = self._effective_bpm()
            if bpm <= 0:
                self._set_status("Cannot start metronome: BPM unknown")
                return
            self._metronome.set_bpm(bpm)
            self._metronome.start()
            self._set_status(f"Metronome: ON @ {bpm:.1f} BPM")
        self.metronomeStateChanged.emit()

    @pyqtSlot(int)
    def setCountInBars(self, bars: int):
        """Set how many bars of count-in to play before recording. 0=off."""
        self._metronome.set_count_in_bars(int(bars))
        self._set_status(f"Count-in: {bars} bars")
        self.metronomeStateChanged.emit()

    @pyqtSlot(float)
    def setQuantizePercent(self, percent: float):
        """0 = no quantize, 100 = fully snapped to beat."""
        self._quantize_percent = max(0.0, min(100.0, float(percent)))
        self._set_status(f"Quantize: {self._quantize_percent:.0f}%")
        self.settingsChanged.emit()

    @pyqtSlot()
    def armRecord(self):
        """
        Start recording with optional count-in. If count-in bars > 0,
        plays metronome for those bars first, then begins recording.
        Otherwise starts recording immediately.
        """
        if self._recorder.is_recording:
            self._set_status("Already recording")
            return
        bpm = self._effective_bpm()
        if bpm <= 0:
            self._set_status("Cannot record: BPM unknown")
            return
        self._metronome.set_bpm(bpm)

        if self._metronome.count_in_bars > 0:
            # Start count-in; _on_count_in_done() will start actual recording
            if self._metronome.start_count_in():
                self._set_status(
                    f"Count-in: {self._metronome.count_in_bars} bars…"
                )
                self.recordStateChanged.emit()
                self.metronomeStateChanged.emit()
                return

        # No count-in — start immediately
        self._start_recording_now(bpm)

    def _start_recording_now(self, bpm: float):
        self._recorder.start(bpm=bpm)
        self._set_status(f"● Recording @ {bpm:.1f} BPM")
        self.recordStateChanged.emit()

    @pyqtSlot()
    def stopRecord(self):
        """Stop recording and store the sequence."""
        if not self._recorder.is_recording:
            return
        self._recorder.stop()
        seq = self._recorder.sequence
        if self._quantize_percent > 0:
            seq = seq.quantized(self._quantize_percent)
        self._player.load_sequence(seq)
        self._set_status(
            f"Recorded {len(seq.events)} events ({seq.duration_ms/1000:.1f}s)"
        )
        self.recordStateChanged.emit()
        self.sequenceUpdated.emit()

    @pyqtSlot()
    def playSequence(self):
        """Play back the recorded sequence."""
        if self._recorder.event_count == 0 and not self._player._sequence:
            self._set_status("No recording to play")
            return
        # If recorder has fresh data not yet loaded, load it now
        if self._recorder.event_count > 0 and not self._player._sequence:
            seq = self._recorder.sequence
            if self._quantize_percent > 0:
                seq = seq.quantized(self._quantize_percent)
            self._player.load_sequence(seq)
        self._player.play()

    @pyqtSlot()
    def pauseSequence(self):
        self._player.pause()

    @pyqtSlot()
    def stopSequence(self):
        self._player.stop()

    @pyqtSlot()
    def seekToStart(self):
        self._player.seek_to_start()

    @pyqtSlot()
    def seekForward(self):
        self._player.seek_forward_beats(1)

    @pyqtSlot()
    def seekBackward(self):
        self._player.seek_backward_beats(1)

    @pyqtSlot()
    def clearSequence(self):
        self._recorder.clear()
        self._player.stop()
        self._player._sequence = None
        self._set_status("Sequence cleared")
        self.sequenceUpdated.emit()
        self.playerStateChanged.emit()

    # ===================================================================
    # NEW: Stem Browser slots (manual sample creation)
    # ===================================================================

    @pyqtSlot()
    def openStemBrowser(self):
        """Populate the stem browser with the project's stems."""
        if not self._project or not self._project.stems:
            self._set_status("No stems available — load a track first")
            return
        stem_colors = {
            "drums":  "#E74C3C",
            "bass":   "#9B59B6",
            "vocals": "#3D8EF0",
            "other":  "#1ABC9C",
            "piano":  "#F39C12",
            "guitar": "#E67E22",
        }
        stems_data = []
        for st in self._project.stems:
            stype = st.stem_type.value if hasattr(st.stem_type, "value") \
                else str(st.stem_type)
            stems_data.append({
                "stem_id": st.id,
                "stem_type": stype,
                "display_name": stype.capitalize(),
                "duration_sec": st.duration_samples / max(1, st.sample_rate),
                "color": stem_colors.get(stype, "#888888"),
            })
        self._stem_browser_model.set_stems(stems_data)
        self.browserStemsChanged.emit()
        # Auto-select the first stem
        if stems_data:
            self.selectBrowserStem(0)

    @pyqtSlot(int)
    def selectBrowserStem(self, index: int):
        """Select a stem to view in the browser by model index."""
        self._stem_browser_model.select(index)
        stem_id = self._stem_browser_model.selected_stem_id()
        if not stem_id:
            return
        self._browser_stem_id = stem_id
        stem = self._project.stem_by_id(stem_id)
        if not stem:
            return
        # Reset view to whole stem, selection to first 2 seconds
        self._browser_view_start = 0
        self._browser_view_end = max(1, stem.duration_samples)
        self._browser_sel_start = 0
        two_sec = min(stem.duration_samples, stem.sample_rate * 2)
        self._browser_sel_end = max(1, two_sec)
        self._browser_active_marker = "start"
        self._refresh_browser_peaks()
        self.browserStemViewChanged.emit()
        self.browserSelectionChanged.emit()

    def _refresh_browser_peaks(self):
        """Compute peaks for the browser's current stem view window."""
        if not self._browser_stem_id or not self._project:
            self._browser_peaks = []
            return
        stem = self._project.stem_by_id(self._browser_stem_id)
        if not stem or not stem.path or not stem.path.exists():
            self._browser_peaks = []
            return
        cache_key = (
            f"{self._browser_stem_id}:"
            f"{self._browser_view_start}:{self._browser_view_end}"
        )
        cached = self._browser_peak_cache.get(cache_key)
        if cached is not None:
            self._browser_peaks = cached
            return
        from app.audio.dsp.waveform_peaks import compute_region_peaks
        peaks = compute_region_peaks(
            stem.path, self._browser_view_start, self._browser_view_end,
            num_bins=600,
        )
        self._browser_peak_cache[cache_key] = peaks
        self._browser_peaks = peaks

    @pyqtSlot(str)
    def setBrowserActiveMarker(self, marker: str):
        """Set which marker the controls move: 'start' or 'end'."""
        if marker in ("start", "end"):
            self._browser_active_marker = marker
            self.browserSelectionChanged.emit()

    @pyqtSlot()
    def toggleBrowserActiveMarker(self):
        """Switch between START and END marker (Tab key / button)."""
        self._browser_active_marker = (
            "end" if self._browser_active_marker == "start" else "start"
        )
        self.browserSelectionChanged.emit()

    @pyqtSlot(float)
    def nudgeBrowserMarker(self, amount_sec: float):
        """
        Move the active marker by amount_sec (can be negative).
        Used by arrow keys / rotary encoder.
        """
        if not self._browser_stem_id or not self._project:
            return
        stem = self._project.stem_by_id(self._browser_stem_id)
        if not stem:
            return
        delta = int(amount_sec * stem.sample_rate)
        min_gap = max(1, stem.sample_rate // 20)  # 50ms minimum selection

        if self._browser_active_marker == "start":
            new_start = self._browser_sel_start + delta
            new_start = max(0, min(new_start, self._browser_sel_end - min_gap))
            self._browser_sel_start = new_start
        else:
            new_end = self._browser_sel_end + delta
            new_end = max(self._browser_sel_start + min_gap,
                          min(new_end, stem.duration_samples))
            self._browser_sel_end = new_end
        self.browserSelectionChanged.emit()

    @pyqtSlot(float, float)
    def setBrowserSelection(self, start_frac: float, end_frac: float):
        """Set selection from view-window fractions (mouse drag)."""
        if not self._browser_stem_id or not self._project:
            return
        stem = self._project.stem_by_id(self._browser_stem_id)
        if not stem:
            return
        vstart = self._browser_view_start
        vlen = self._browser_view_end - self._browser_view_start
        a = max(0.0, min(1.0, min(start_frac, end_frac)))
        b = max(0.0, min(1.0, max(start_frac, end_frac)))
        min_gap = max(1, stem.sample_rate // 20)
        self._browser_sel_start = int(vstart + a * vlen)
        self._browser_sel_end = max(self._browser_sel_start + min_gap,
                                    int(vstart + b * vlen))
        self.browserSelectionChanged.emit()

    @pyqtSlot()
    def previewBrowserSelection(self):
        """Play the current browser selection through the engine."""
        if not self._browser_stem_id or not self._project:
            return
        stem = self._project.stem_by_id(self._browser_stem_id)
        if not stem:
            return
        # Build a temporary sample for preview
        temp = Sample(
            name="__browser_preview__",
            category=SampleCategory.USER,
            source_stem_id=self._browser_stem_id,
            start_sample=self._browser_sel_start,
            end_sample=self._browser_sel_end,
        )
        try:
            self.engine.register_sample(temp)
            pad = Pad(index=-2, sample_id=temp.id)  # -2 = browser preview
            self.engine.trigger_pad(pad, temp)
            # Remember for playhead tracking
            self._browser_preview_active = True
            self._browser_preview_start = self._browser_sel_start
            self._browser_preview_end = self._browser_sel_end
        except Exception as e:
            log.warning("Browser preview failed: %s", e)

    @pyqtSlot(int)
    def assignBrowserSelectionToPad(self, pad_index: int):
        """
        Create a new Sample from the current browser selection and assign it
        to the given pad. This is the core 'manual chop' action.
        """
        if not self._browser_stem_id or not self._project:
            self._set_status("No stem selected")
            return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)):
            self._set_status("Invalid pad")
            return
        stem = self._project.stem_by_id(self._browser_stem_id)
        if not stem:
            return

        stype = stem.stem_type.value if hasattr(stem.stem_type, "value") \
            else str(stem.stem_type)
        new_sample = Sample(
            name=f"{stype.capitalize()} chop",
            category=SampleCategory.USER,
            source_stem_id=self._browser_stem_id,
            start_sample=self._browser_sel_start,
            end_sample=self._browser_sel_end,
        )
        self._project.samples.append(new_sample)
        try:
            self.engine.register_sample(new_sample)
        except Exception as e:
            log.warning("Register new sample failed: %s", e)

        # Assign to pad
        pad = bank.pads[pad_index]
        pad.sample_id = new_sample.id
        pad.label = new_sample.name
        stem_colors = {
            "drums": "#E74C3C", "bass": "#9B59B6", "vocals": "#3D8EF0",
            "other": "#1ABC9C", "piano": "#F39C12", "guitar": "#E67E22",
        }
        pad.color = stem_colors.get(stype, "#888888")

        # Refresh pad model
        self._pad_model.set_pads(bank.pads)
        self._set_status(
            f"Assigned {new_sample.name} "
            f"({self.browserSelDurationSec:.2f}s) to pad {pad_index + 1}"
        )

    @pyqtSlot(str, int)
    def loadSampleFromFile(self, file_url: str, pad_index: int):
        """
        Scenario A: load an external audio file directly onto a pad.
        Creates a path-based Sample (no stem needed).
        """
        path = self._qml_file_to_path(file_url)
        if not path.exists():
            self._set_status(f"File not found: {path}")
            return
        if not self._project:
            # Create a minimal project so we have a bank to assign into
            self._set_status("Load a track first to create a pad bank")
            return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)):
            self._set_status("Invalid pad")
            return

        # Determine the file's length in samples
        try:
            import soundfile as sf
            info = sf.info(str(path))
            total_samples = int(info.frames)
            sr = int(info.samplerate)
        except Exception as e:
            log.warning("Could not read file info: %s", e)
            total_samples = 0
            sr = 44100

        new_sample = Sample(
            name=path.stem,
            category=SampleCategory.USER,
            path=path,
            start_sample=0,
            end_sample=total_samples,
        )
        self._project.samples.append(new_sample)
        try:
            self.engine.register_sample(new_sample)
        except Exception as e:
            log.warning("Register file sample failed: %s", e)

        pad = bank.pads[pad_index]
        pad.sample_id = new_sample.id
        pad.label = new_sample.name
        pad.color = "#F1C40F"  # user files = yellow
        self._pad_model.set_pads(bank.pads)
        self._set_status(f"Loaded '{path.name}' to pad {pad_index + 1}")

    def _on_metronome_beat(self, beat_index: int, is_downbeat: bool):
        self._current_beat = int(beat_index)
        self._is_downbeat = bool(is_downbeat)
        self.beatTick.emit(self._current_beat, self._is_downbeat)
        # On the downbeat, fire any armed loop track (record or overdub)
        # so the take always lands on a bar boundary.
        if is_downbeat:
            for i in range(4):
                if self._track_armed_record[i]:
                    self.engine.looper_start_record(i)
                    self._track_armed_record[i] = False
                    self._last_modified_track = i
                elif self._track_armed_overdub[i]:
                    self.engine.looper_start_overdub(i)
                    self._track_armed_overdub[i] = False
                    self._last_modified_track = i

    def _on_count_in_done(self):
        # Count-in finished: stop metronome (unless user wanted it on)
        # and start recording
        bpm = self._effective_bpm()
        was_metro_enabled = self._metronome.enabled
        # Stop metronome — user can re-enable it if they want
        self._metronome.stop()
        self._start_recording_now(bpm)
        self.metronomeStateChanged.emit()

    def _on_record_state_changed(self):
        self.recordStateChanged.emit()

    def _on_event_logged(self):
        self.sequenceUpdated.emit()

    def _on_player_state(self):
        self.playerStateChanged.emit()

    def _playback_trigger(self, pad_index: int, velocity: int):
        """Called by Player for each recorded NOTE_ON event."""
        if not self._project:
            return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)):
            return
        pad = bank.pads[pad_index]
        if not pad.sample_id:
            return
        sample = self._project.sample_by_id(pad.sample_id)
        if not sample:
            return
        self.engine.trigger_pad(pad, sample)
        self._pad_model.set_active(pad_index, True)
        if pad.mode == PadMode.LOOP:
            self._looping_pads.add(pad_index)

    def _playback_release(self, pad_index: int):
        """Called by Player for each recorded NOTE_OFF event."""
        if not self._project:
            return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)):
            return
        pad = bank.pads[pad_index]
        if pad.mode == PadMode.LOOP:
            self.engine.stop_pad(pad_index)
            self._looping_pads.discard(pad_index)
        else:
            self.engine.release_pad(pad)
        self._pad_model.set_active(pad_index, False)

    def _effective_bpm(self) -> float:
        """Best available BPM: project BPM > detected > 0."""
        if self._detected_bpm > 0:
            return self._detected_bpm
        if self._bpm > 0:
            return self._bpm
        return 0.0

    # ---- Keyboard shortcuts ----
    @pyqtSlot(str, result=int)
    def keyToPadIndex(self, key: str) -> int:
        """
        Map a keyboard key (1-char string) to a pad index.
        Layout (4 rows × 4 cols by default, expandable):
          Row 1: 1 2 3 4 5 6
          Row 2: Q W E R T Y
          Row 3: A S D F G H
          Row 4: Z X C V B N
        Returns -1 if no mapping.
        """
        if not key:
            return -1
        k = key.upper()
        cols = self._pad_grid_cols()
        rows_layout = {
            "1234567890": 0,
            "QWERTYUIOP": 1,
            "ASDFGHJKL":  2,
            "ZXCVBNM":    3,
        }
        for chars, row in rows_layout.items():
            if k in chars:
                col = chars.index(k)
                if col >= cols:
                    return -1
                pad_index = row * cols + col
                if self._project:
                    bank = self._project.active_bank()
                    if bank and 0 <= pad_index < len(bank.pads):
                        return pad_index
                return -1
        return -1

    def _pad_grid_cols(self) -> int:
        """Match the QML grid column logic."""
        gs = self._settings.pad_layout.grid_size
        if gs <= 16:
            return 4
        if gs <= 25:
            return 5
        return 6

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
        self._looping_pads.clear()
        # Mark loop-pad samples as loop_ready *before* rendering so the
        # first render already skips the seam-killing user fades.
        bank = project.active_bank()
        if bank:
            for p in bank.pads:
                if p.sample_id and p.mode == PadMode.LOOP:
                    s = project.sample_by_id(p.sample_id)
                    if s is not None:
                        s.loop_ready = True
        self.engine.load_stems(project.stems)
        for s in project.samples:
            self.engine.register_sample(s)
        if bank:
            self._pad_model.set_pads(bank.pads)
        if project.analyses:
            self._bpm = project.analyses[0].bpm
            self._key = project.analyses[0].key or ""
            self.bpmChanged.emit()
            # NEW: propagate project BPM to engine for loop sync
            try:
                self.engine.set_project_bpm(self._bpm)
            except AttributeError:
                pass
        self._stem_peak_cache.clear()
        self._stem_annotation_cache.clear()  # NEW: reset annotations cache
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
            "cutoff_hz":         getattr(sample, "cutoff_hz", 20000.0),
            "highpass_hz":       getattr(sample, "highpass_hz", 20.0),
            "pan":               getattr(sample, "pan", 0.0),
            "loop_beats":        getattr(sample, "loop_beats", 0),
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
            # NEW: auto-load annotations for this stem (cached)
            self._auto_load_annotations_for_current()
        self.currentSampleChanged.emit()
        self.editorParamsChanged.emit()
        self.fxChanged.emit()

    def _auto_load_annotations_for_current(self):
        """Load (or compute & cache) annotations for the current sample's stem."""
        s = self._current_sample()
        if not s or not s.source_stem_id or not self._project:
            self._annotation_model.set_annotations([])
            return

        stem_id = s.source_stem_id
        # Check cache first — cached annotations are in absolute samples,
        # so remap them to the current view window.
        if stem_id in self._stem_annotation_cache:
            self._remap_annotations_to_view(stem_id)
            return

        # Not cached — analyze now (background-safe but fast for stems)
        stem = self._project.stem_by_id(stem_id)
        if not stem or not stem.path or not stem.path.exists():
            self._annotation_model.set_annotations([])
            return

        try:
            from app.audio.analysis.sample_analyzer import analyze_sample
            annotations = analyze_sample(stem.path)
            # Cache in ABSOLUTE samples so we can remap to any view window
            abs_ann = []
            for ann in annotations:
                abs_ann.append({
                    "start_sample": ann.start_sample,
                    "end_sample": ann.end_sample,
                    "kind": ann.kind.value,
                    "color": ann.color,
                    "label": ann.label,
                })
            self._stem_annotation_cache[stem_id] = abs_ann
            self._remap_annotations_to_view(stem_id)
        except Exception as e:
            log.warning("Auto-analysis failed: %s", e)
            self._annotation_model.set_annotations([])

    def _remap_annotations_to_view(self, stem_id: str):
        """
        Convert cached absolute-sample annotations into VIEW-WINDOW fractions
        and push to the model. Only annotations overlapping the view are kept.
        """
        abs_ann = self._stem_annotation_cache.get(stem_id)
        if not abs_ann:
            self._annotation_model.set_annotations([])
            return
        vstart = self._view_start_sample
        vlen = self._view_end_sample - self._view_start_sample
        if vlen <= 0:
            self._annotation_model.set_annotations([])
            return
        qml_ann = []
        for a in abs_ann:
            # Skip annotations entirely outside the view window
            if a["end_sample"] < vstart or a["start_sample"] > self._view_end_sample:
                continue
            sf = (a["start_sample"] - vstart) / vlen
            ef = (a["end_sample"] - vstart) / vlen
            qml_ann.append({
                "start_frac": max(0.0, min(1.0, sf)),
                "end_frac": max(0.0, min(1.0, ef)),
                "kind": a["kind"],
                "color": a["color"],
                "label": a["label"],
            })
        self._annotation_model.set_annotations(qml_ann)

    def _recompute_view_window(self):
        """
        Set the view window = sample region + context margin on each side,
        clamped to the stem bounds. This is the slice of audio the editor
        waveform displays (DAW-style: you see the chop, not the whole song).
        """
        s = self._current_sample()
        if not s or not s.source_stem_id or not self._project:
            self._view_start_sample = 0
            self._view_end_sample = 1
            return
        stem = self._project.stem_by_id(s.source_stem_id)
        if not stem or stem.duration_samples <= 0:
            self._view_start_sample = 0
            self._view_end_sample = 1
            return

        sample_len = max(1, s.end_sample - s.start_sample)
        margin = int(sample_len * self._view_context_fraction)
        vstart = max(0, s.start_sample - margin)
        vend = min(stem.duration_samples, s.end_sample + margin)
        if vend <= vstart:
            vend = min(stem.duration_samples, vstart + sample_len)
        self._view_start_sample = vstart
        self._view_end_sample = max(vstart + 1, vend)

    def _refresh_current_peaks(self):
        """
        Compute waveform peaks for the CURRENT VIEW WINDOW (sample + margin),
        not the whole stem. Cached per (stem_id, view_start, view_end) so
        re-selecting the same pad is instant but moving markers refreshes.
        """
        s = self._current_sample()
        if not s or not s.source_stem_id:
            self._current_peaks = []
            return
        stem = self._project.stem_by_id(s.source_stem_id)
        if not stem or not stem.path or not stem.path.exists():
            self._current_peaks = []
            return

        # Recompute the view window first
        self._recompute_view_window()

        cache_key = (
            f"{s.source_stem_id}:{self._view_start_sample}:{self._view_end_sample}"
        )
        cached = self._stem_peak_cache.get(cache_key)
        if cached is not None:
            self._current_peaks = cached
            return

        from app.audio.dsp.waveform_peaks import compute_region_peaks
        peaks = compute_region_peaks(
            stem.path,
            self._view_start_sample,
            self._view_end_sample,
            num_bins=600,
        )
        self._stem_peak_cache[cache_key] = peaks
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
        """
        Update the sample region (start/end) WITHOUT re-rendering audio.
        The fractions are relative to the VIEW WINDOW (what the waveform
        shows), not the whole stem. Use during interactive drag — call
        commitCurrentSampleRegion() on release to re-render + refresh peaks.
        """
        s = self._current_sample()
        if not s or not s.source_stem_id: return
        stem = self._project.stem_by_id(s.source_stem_id)
        if not stem: return
        a = max(0.0, min(1.0, min(start_frac, end_frac)))
        b = max(0.0, min(1.0, max(start_frac, end_frac)))
        min_samples = max(1, stem.sample_rate // 20)
        self._ensure_originals(s)

        # Map view-window fractions → absolute stem samples
        vstart = self._view_start_sample
        vlen = self._view_end_sample - self._view_start_sample
        s.start_sample = int(vstart + a * vlen)
        s.end_sample = max(
            s.start_sample + min_samples,
            int(vstart + b * vlen),
        )
        # Clamp to stem bounds
        s.start_sample = max(0, min(s.start_sample, stem.duration_samples - 1))
        s.end_sample = max(s.start_sample + min_samples,
                           min(s.end_sample, stem.duration_samples))
        # Emit so QML bindings refresh (marker positions, duration display)
        self.currentSampleChanged.emit()

    @pyqtSlot()
    def commitCurrentSampleRegion(self):
        """
        Re-render the audio buffer for the current sample AND recompute the
        view-window waveform peaks so the displayed shape matches the new
        region (DAW-style: drag end, waveform + duration update on release).
        """
        s = self._current_sample()
        if not s: return
        try:
            self.engine.register_sample(s)
        except Exception as e:
            log.warning("commitCurrentSampleRegion: register failed: %s", e)
        # Recompute view window + peaks for the new region
        self._refresh_current_peaks()
        # Remap annotations to the new view window too
        s2 = self._current_sample()
        if s2 and s2.source_stem_id in self._stem_annotation_cache:
            self._remap_annotations_to_view(s2.source_stem_id)
        self.editorParamsChanged.emit()
        self.currentSampleChanged.emit()

    # ===================================================================
    # NEW: Effects (per-pad insert chains + master) & audio export
    # ===================================================================

    def _get_pad_fx(self, pad_index: int) -> dict:
        """Effect state for a pad, created from defaults on first access."""
        state = self._pad_fx.get(pad_index)
        if state is None:
            state = _default_fx_state()
            self._pad_fx[pad_index] = state
        return state

    def _build_chain(self, state: dict) -> EffectsChain:
        """Build a configured EffectsChain from a saved fx-state dict."""
        chain = EffectsChain(self._settings.playback.sample_rate)
        for effect, params in state.items():
            for key, value in params.items():
                if key == "enabled":
                    chain.set_enabled(effect, bool(value))
                else:
                    chain.set_param(effect, key, float(value))
        return chain

    def _apply_all_fx_to_engine(self):
        """Push the full effect state to the (possibly rebuilt) engine."""
        eng = getattr(self, "engine", None)
        if eng is None:
            return
        for pad_index, state in self._pad_fx.items():
            for effect, params in state.items():
                for key, value in params.items():
                    if key == "enabled":
                        eng.set_pad_effect_enabled(pad_index, effect,
                                                   bool(value))
                    else:
                        eng.set_pad_effect_param(pad_index, effect, key,
                                                 float(value))
        for effect, params in self._master_fx.items():
            for key, value in params.items():
                if key == "enabled":
                    eng.set_master_effect_enabled(effect, bool(value))
                else:
                    eng.set_master_effect_param(effect, key, float(value))

    @pyqtProperty("QVariantMap", notify=fxChanged)
    def currentPadFx(self):
        """Effect state of the currently selected pad (for the FX panel)."""
        if self._current_pad_index < 0:
            return _default_fx_state()
        return self._get_pad_fx(self._current_pad_index)

    @pyqtProperty("QVariantMap", notify=fxChanged)
    def masterFx(self):
        return self._master_fx

    @pyqtProperty(int, notify=fxChanged)
    def fxPadIndex(self):
        return self._current_pad_index

    @pyqtSlot(str, bool)
    def setPadFxEnabled(self, effect: str, enabled: bool):
        if self._current_pad_index < 0:
            return
        state = self._get_pad_fx(self._current_pad_index)
        if effect in state:
            state[effect]["enabled"] = bool(enabled)
            self.engine.set_pad_effect_enabled(
                self._current_pad_index, effect, bool(enabled))
            self.fxChanged.emit()

    @pyqtSlot(str, str, float)
    def setPadFxParam(self, effect: str, param: str, value: float):
        if self._current_pad_index < 0:
            return
        state = self._get_pad_fx(self._current_pad_index)
        if effect in state and param in state[effect]:
            state[effect][param] = float(value)
            self.engine.set_pad_effect_param(
                self._current_pad_index, effect, param, float(value))
            self.fxChanged.emit()

    @pyqtSlot(str, bool)
    def setMasterFxEnabled(self, effect: str, enabled: bool):
        if effect in self._master_fx:
            self._master_fx[effect]["enabled"] = bool(enabled)
            self.engine.set_master_effect_enabled(effect, bool(enabled))
            self.fxChanged.emit()

    @pyqtSlot(str, str, float)
    def setMasterFxParam(self, effect: str, param: str, value: float):
        if effect in self._master_fx and param in self._master_fx[effect]:
            self._master_fx[effect][param] = float(value)
            self.engine.set_master_effect_param(effect, param, float(value))
            self.fxChanged.emit()

    @pyqtSlot()
    def resetCurrentPadFx(self):
        """Reset the selected pad's effects to defaults."""
        if self._current_pad_index < 0:
            return
        self._pad_fx[self._current_pad_index] = _default_fx_state()
        self._apply_all_fx_to_engine()
        self.fxChanged.emit()
        self._set_status(
            f"Effects reset for pad {self._current_pad_index + 1}")

    @pyqtProperty(bool, notify=sequenceUpdated)
    def canExportSequence(self):
        seq = self._player._sequence
        return bool(seq and seq.events)

    @pyqtProperty(bool, notify=bounceStateChanged)
    def isBouncing(self):
        eng = getattr(self, "engine", None)
        return bool(eng and eng.is_capturing)

    @pyqtSlot(str)
    def exportSequenceToFile(self, file_url: str):
        """Render the recorded sequence offline and write it to a WAV file."""
        seq = self._player._sequence
        if not seq or not seq.events:
            self._set_status("No sequence to export")
            return
        if not self._project:
            self._set_status("No project loaded")
            return
        bank = self._project.active_bank()
        pads = bank.pads if bank else []
        path = self._export_path(file_url)
        from app.audio.export.exporter import render_sequence, write_wav
        try:
            pad_chains = {idx: self._build_chain(self._get_pad_fx(idx))
                          for idx in self._pad_fx}
            master_chain = self._build_chain(self._master_fx)
            audio = render_sequence(
                seq, self.engine.sample_buffers, pads,
                self._settings.playback.sample_rate,
                pad_chains, master_chain,
            )
            write_wav(path, audio, self._settings.playback.sample_rate)
            self._set_status(f"Exported sequence → {path.name}")
        except Exception as e:
            log.error("Sequence export failed: %s", e)
            self._set_status(f"Export failed: {e}")

    @pyqtSlot()
    def startBounce(self):
        """Start capturing the live audio output to memory."""
        eng = getattr(self, "engine", None)
        if eng is None:
            return
        eng.start_capture()
        self._set_status("● Bouncing live output…")
        self.bounceStateChanged.emit()

    @pyqtSlot()
    def stopBounce(self):
        """Stop the live bounce; the captured audio is held until saved."""
        eng = getattr(self, "engine", None)
        if eng is None:
            return
        self._pending_bounce = eng.stop_capture()
        self.bounceStateChanged.emit()
        if self._pending_bounce is None or len(self._pending_bounce) == 0:
            self._set_status("Bounce was empty — nothing captured")
            return
        secs = len(self._pending_bounce) / max(
            1, self._settings.playback.sample_rate)
        self._set_status(
            f"Bounce stopped ({secs:.1f}s) — choose where to save")

    @pyqtSlot(str)
    def saveBounceToFile(self, file_url: str):
        """Write the most recent live bounce to a WAV file."""
        if self._pending_bounce is None or len(self._pending_bounce) == 0:
            self._set_status("No bounce to save")
            return
        path = self._export_path(file_url)
        from app.audio.export.exporter import write_wav
        try:
            write_wav(path, self._pending_bounce,
                      self._settings.playback.sample_rate)
            self._set_status(f"Bounce saved → {path.name}")
        except Exception as e:
            log.error("Bounce save failed: %s", e)
            self._set_status(f"Bounce save failed: {e}")

    @staticmethod
    def _export_path(file_url: str) -> Path:
        path = SamplerController._qml_file_to_path(file_url)
        if path.suffix.lower() != ".wav":
            path = path.with_suffix(".wav")
        return path

    # ===================================================================
    # NEW: Virtual device (kits + presets) sync
    # ===================================================================

    def _on_device_connection_changed(self):
        if self._device_manager.is_connected():
            self._device_log_add("Connected to device")
            self._refresh_device_lists()
        else:
            self._device_log_add("Disconnected from device")
        self.deviceStateChanged.emit()

    def _on_device_error(self, msg: str):
        self._device_log_add(f"Error: {msg}")
        self.deviceStateChanged.emit()

    def _device_log_add(self, msg: str):
        self._device_log.insert(0, msg)
        del self._device_log[12:]

    def _refresh_device_lists(self):
        self._device_kits = self._device_manager.list_kits()
        self._device_presets = self._device_manager.list_presets()
        self._device_storage = self._device_manager.get_storage_info()

    def _apply_preset(self, pad_cfgs: list[dict]):
        """Apply a preset's pad config (mode / color / label / group)."""
        if not self._project:
            return
        bank = self._project.active_bank()
        if not bank:
            return
        by_index = {p.index: p for p in bank.pads}
        for cfg in pad_cfgs:
            pad = by_index.get(cfg.get("index"))
            if pad is None:
                continue
            try:
                pad.mode = PadMode(cfg.get("mode", pad.mode.value))
            except (ValueError, TypeError):
                pass
            pad.color = cfg.get("color", pad.color)
            pad.label = cfg.get("label", pad.label)
            pad.group = int(cfg.get("group", pad.group) or 0)
            pad.choke_self = bool(cfg.get("choke_self", pad.choke_self))
        self._pad_model.set_pads(bank.pads)

    @pyqtProperty(bool, notify=deviceStateChanged)
    def deviceConnected(self):
        return self._device_manager.is_connected()

    @pyqtProperty(str, notify=deviceStateChanged)
    def deviceSdPath(self):
        return self._device_storage.get("sd_path", "")

    @pyqtProperty(list, notify=deviceStateChanged)
    def deviceKits(self):
        return self._device_kits

    @pyqtProperty(list, notify=deviceStateChanged)
    def devicePresets(self):
        return self._device_presets

    @pyqtProperty(list, notify=deviceStateChanged)
    def deviceLog(self):
        return self._device_log

    @pyqtProperty(str, notify=deviceStateChanged)
    def deviceStorageText(self):
        s = self._device_storage
        total = s.get("total", 0)
        if not total:
            return "—"
        gb = 1024 ** 3
        return (f"{s.get('used', 0) / gb:.2f} GB used  /  "
                f"{s.get('free', 0) / gb:.1f} GB free")

    @pyqtProperty(float, notify=deviceStateChanged)
    def deviceStorageFraction(self):
        total = self._device_storage.get("total", 0)
        if not total:
            return 0.0
        return max(0.0, min(1.0,
            self._device_storage.get("used", 0) / total))

    @pyqtSlot()
    def connectDevice(self):
        if self._device_manager.connect():
            self._set_status("Device connected")
        else:
            self._set_status(
                "Device not found — is virtual_device running?")

    @pyqtSlot()
    def disconnectDevice(self):
        self._device_manager.disconnect()

    @pyqtSlot()
    def refreshDevice(self):
        if not self._device_manager.is_connected():
            return
        self._refresh_device_lists()
        self.deviceStateChanged.emit()

    @pyqtSlot(str)
    def pushCurrentProjectToDevice(self, kit_name: str):
        if not self._project:
            self._set_status("No project to push")
            return
        name = (kit_name or "").strip() or (self._project.name or "kit")
        if self._device_manager.push_kit(name, self._project):
            self._device_log_add(f"Kit '{name}' pushed")
            self._set_status(f"Kit '{name}' pushed to device")
            self._refresh_device_lists()
        else:
            self._set_status("Kit push failed")
        self.deviceStateChanged.emit()

    @pyqtSlot(str)
    def loadKitFromDevice(self, kit_name: str):
        project = self._device_manager.load_kit(kit_name)
        if project is None:
            self._set_status(f"Could not load kit '{kit_name}'")
            return
        self._on_imported(project)
        self._device_log_add(f"Kit '{kit_name}' loaded")
        self.deviceStateChanged.emit()

    @pyqtSlot(str)
    def deleteKitFromDevice(self, kit_name: str):
        if self._device_manager.delete_kit(kit_name):
            self._device_log_add(f"Kit '{kit_name}' deleted")
            self._refresh_device_lists()
        self.deviceStateChanged.emit()

    @pyqtSlot(str)
    def savePresetToDevice(self, name: str):
        if not self._project:
            self._set_status("No project loaded")
            return
        bank = self._project.active_bank()
        if not bank:
            self._set_status("No pads to save")
            return
        nm = (name or "").strip() or "preset"
        if self._device_manager.save_preset(nm, bank.pads):
            self._device_log_add(f"Preset '{nm}' saved")
            self._refresh_device_lists()
        self.deviceStateChanged.emit()

    @pyqtSlot(str)
    def loadPresetFromDevice(self, name: str):
        pads = self._device_manager.load_preset(name)
        if not pads:
            self._set_status(f"Preset '{name}' is empty")
            return
        self._apply_preset(pads)
        self._device_log_add(f"Preset '{name}' applied")
        self._set_status(f"Preset '{name}' applied")

    @pyqtSlot()
    def openDeviceSd(self):
        self._device_manager.open_sd_in_explorer()

    # ===================================================================
    # NEW: Pad behavior (mode / choke group / self-choke)
    # ===================================================================

    def _current_pad(self):
        if not self._project or self._current_pad_index < 0:
            return None
        bank = self._project.active_bank()
        if not bank or self._current_pad_index >= len(bank.pads):
            return None
        return bank.pads[self._current_pad_index]

    def _sync_loop_ready(self, pad):
        """Match sample.loop_ready to pad.mode == LOOP and re-render if needed.

        A loop-ready sample is rendered without the longer user fade-in /
        fade-out so the loop seam doesn't dip into near-silence.
        """
        if not pad or not pad.sample_id or not self._project:
            return
        sample = self._project.sample_by_id(pad.sample_id)
        if sample is None:
            return
        want = (pad.mode == PadMode.LOOP)
        if getattr(sample, "loop_ready", False) == want:
            return
        sample.loop_ready = want
        try:
            self.engine.register_sample(sample)
        except Exception as e:
            log.warning("loop_ready re-render failed: %s", e)

    @pyqtProperty(str, notify=currentSampleChanged)
    def currentPadMode(self):
        pad = self._current_pad()
        return pad.mode.value if pad else "one_shot"

    @pyqtProperty(int, notify=currentSampleChanged)
    def currentPadGroup(self):
        pad = self._current_pad()
        return pad.group if pad else 0

    @pyqtProperty(bool, notify=currentSampleChanged)
    def currentPadChokeSelf(self):
        pad = self._current_pad()
        return getattr(pad, "choke_self", False) if pad else False

    @pyqtSlot(str)
    def setCurrentPadMode(self, mode_value: str):
        pad = self._current_pad()
        if pad is None:
            return
        try:
            new_mode = PadMode(mode_value)
        except ValueError:
            return
        pad.mode = new_mode
        self._pad_model.notify_mode_changed(pad.index)
        # Leaving LOOP — drop the looping bookkeeping for this pad.
        if new_mode != PadMode.LOOP:
            self._looping_pads.discard(pad.index)
        # Re-render the sample as loop-ready (or not) for a seamless seam.
        self._sync_loop_ready(pad)
        self.currentSampleChanged.emit()

    @pyqtSlot(int)
    def setCurrentPadGroup(self, group: int):
        pad = self._current_pad()
        if pad is None:
            return
        pad.group = max(0, int(group))
        self.currentSampleChanged.emit()

    @pyqtSlot(bool)
    def setCurrentPadChokeSelf(self, value: bool):
        pad = self._current_pad()
        if pad is None:
            return
        pad.choke_self = bool(value)
        self.currentSampleChanged.emit()

    # ---- Loop sync to BPM grid ----------------------------------------

    @pyqtProperty(int, notify=currentSampleChanged)
    def currentSampleLoopBeats(self):
        s = self._current_sample()
        return getattr(s, "loop_beats", 0) if s else 0

    @pyqtSlot(int)
    def setCurrentSampleLoopBeats(self, beats: int):
        s = self._current_sample()
        if s is None:
            return
        s.loop_beats = max(0, int(beats))
        try:
            self.engine.register_sample(s)
        except Exception as e:
            log.warning("loop_beats re-render failed: %s", e)
        self.currentSampleChanged.emit()
        self.editorParamsChanged.emit()

    @pyqtSlot()
    def autoDetectLoopBeats(self):
        s = self._current_sample()
        if s is None:
            return
        bpm = self._effective_bpm()
        if bpm <= 0:
            self._set_status("Can't auto-detect: project BPM is unknown")
            return
        sr = self._settings.playback.sample_rate
        suggested = SounddevicePlaybackEngine.suggest_loop_beats(
            s.length_samples, sr, bpm)
        if suggested > 0:
            s.loop_beats = int(suggested)
            try:
                self.engine.register_sample(s)
            except Exception as e:
                log.warning("loop_beats re-render failed: %s", e)
            self._set_status(f"Auto loop sync: {suggested} beats")
            self.currentSampleChanged.emit()
            self.editorParamsChanged.emit()

    # ===================================================================
    # NEW: Bar-locked looper (captures master, replays in tempo)
    # ===================================================================

    @pyqtProperty(int, notify=looperBarsChanged)
    def looperBars(self):
        return self._looper_bars

    @pyqtProperty(list, notify=looperStateChanged)
    def looperStates(self):
        return list(self._looper_states)

    @pyqtProperty(list, notify=looperStateChanged)
    def looperPositionFracs(self):
        return list(self._looper_positions)

    @pyqtProperty(list, notify=looperStateChanged)
    def looperUndoAvailable(self):
        return list(self._looper_undo_available)

    @pyqtSlot(int)
    def setLooperBars(self, n: int):
        n = max(1, min(32, int(n)))
        if n == self._looper_bars:
            return
        self._looper_bars = n
        self.looperBarsChanged.emit()

    @pyqtProperty(float, notify=looperBarsChanged)
    def loopPrerollMs(self):
        return self._loop_preroll_ms

    @pyqtSlot(float)
    def setLoopPrerollMs(self, ms: float):
        """Compensation for trigger latency: how many ms of recent master
        history to splice into the loop's start when recording fires."""
        ms = max(0.0, min(100.0, float(ms)))
        if abs(ms - self._loop_preroll_ms) < 0.5:
            return
        self._loop_preroll_ms = ms
        eng = getattr(self, "engine", None)
        if eng is not None:
            eng.set_loop_preroll_ms(ms)
        self.looperBarsChanged.emit()

    def _ensure_metronome_for_loop(self) -> bool:
        """Make sure metronome + BPM are usable before arming a loop track."""
        bpm = self._effective_bpm()
        if bpm <= 0:
            self._set_status("Looper needs a BPM — load a track first")
            return False
        if not self._metronome.enabled:
            self._metronome.set_bpm(bpm)
            self._metronome.start()
            self.metronomeStateChanged.emit()
        self.engine.looper_configure(self._looper_bars, bpm, 4)
        return True

    @pyqtSlot(int)
    def toggleLooperTrack(self, idx: int):
        """One-tap cycle on a single track's button.

        - idle           -> arm record (fires on next downbeat)
        - playing        -> arm overdub (adds a layer on next downbeat)
        - overdub        -> stop overdub (keep the layer just added)
        - armed_*        -> cancel
        - recording      -> cancel (drop the partial take)
        """
        if not (0 <= idx < 4):
            return
        state = self._looper_states[idx]
        if state == "idle":
            if not self._ensure_metronome_for_loop():
                return
            self.engine.looper_arm_record(idx)
            self._track_armed_record[idx] = True
            self._track_armed_overdub[idx] = False
            self._set_status(
                f"T{idx + 1}: armed record — {self._looper_bars} bar(s)")
        elif state == "playing":
            if not self._ensure_metronome_for_loop():
                return
            self.engine.looper_arm_overdub(idx)
            self._track_armed_overdub[idx] = True
            self._track_armed_record[idx] = False
            self._set_status(f"T{idx + 1}: armed overdub")
        elif state == "overdub":
            self.engine.looper_stop_overdub(idx)
            self._last_modified_track = idx
            self._set_status(f"T{idx + 1}: overdub stopped")
        elif state in ("armed_record", "armed_overdub", "recording"):
            self.engine.looper_cancel(idx)
            self._track_armed_record[idx] = False
            self._track_armed_overdub[idx] = False
            self._set_status(f"T{idx + 1}: cancelled")

    @pyqtSlot(int)
    def armLooperRecord(self, idx: int):
        """Explicit re-record: arms RECORD on a track (will overwrite)."""
        if not (0 <= idx < 4):
            return
        if not self._ensure_metronome_for_loop():
            return
        self.engine.looper_arm_record(idx)
        self._track_armed_record[idx] = True
        self._track_armed_overdub[idx] = False
        self._set_status(
            f"T{idx + 1}: re-record armed — {self._looper_bars} bar(s)")

    @pyqtSlot(int)
    def clearLooperTrack(self, idx: int):
        if not (0 <= idx < 4):
            return
        self.engine.looper_clear(idx)
        self._track_armed_record[idx] = False
        self._track_armed_overdub[idx] = False
        self._set_status(f"T{idx + 1}: cleared")

    @pyqtSlot(int)
    def undoLooperTrack(self, idx: int):
        if not (0 <= idx < 4):
            return
        self.engine.looper_undo(idx)
        self._last_modified_track = idx
        self._set_status(f"T{idx + 1}: undo")

    @pyqtSlot()
    def undoLooperLast(self):
        """Undo on the most recently modified track (last take / overdub)."""
        self.undoLooperTrack(self._last_modified_track)

    def _on_import_error(self, msg: str):
        self._set_status(f"Error: {msg}")
        self.importError.emit(msg)

    def _set_status(self, s: str):
        self._status = s
        self.statusChanged.emit()