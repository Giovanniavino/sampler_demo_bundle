"""
QML-facing controller.
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
from app.audio.separation.separator import DemucsSeparator, DummySeparator
from app.audio.slicing.pad_assigner import CATEGORY_COLORS
from app.core.models import Pad, PadMode, Project, Sample
from app.core.settings import AppSettings
from app.services.pipeline import SamplerPipeline

log = logging.getLogger(__name__)

SETTINGS_PATH = Path("data/settings.json")


# ---------------------------------------------------------------------------
# Pad list model
# ---------------------------------------------------------------------------

class PadGridModel(QAbstractListModel):
    IndexRole    = Qt.ItemDataRole.UserRole + 1
    LabelRole    = Qt.ItemDataRole.UserRole + 2
    ColorRole    = Qt.ItemDataRole.UserRole + 3
    HasSampleRole = Qt.ItemDataRole.UserRole + 4
    ActiveRole   = Qt.ItemDataRole.UserRole + 5
    ModeRole     = Qt.ItemDataRole.UserRole + 6

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
        if role == self.IndexRole:     return p.index
        if role == self.LabelRole:     return p.label or f"Pad {p.index + 1}"
        if role == self.ColorRole:     return p.color
        if role == self.HasSampleRole: return p.sample_id is not None
        if role == self.ActiveRole:    return p.index in self._active
        if role == self.ModeRole:      return p.mode.value
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
# Import worker
# ---------------------------------------------------------------------------

class ImportWorker(QObject):
    progress = pyqtSignal(float, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, pipeline: SamplerPipeline, audio_path: Path):
        super().__init__()
        self.pipeline = pipeline
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

    projectChanged    = pyqtSignal()
    bpmChanged        = pyqtSignal()
    statusChanged     = pyqtSignal()
    importProgress    = pyqtSignal(float, str)
    importDone        = pyqtSignal()
    importError       = pyqtSignal(str)
    settingsChanged   = pyqtSignal()
    sampleEditorOpen  = pyqtSignal(int, str, float, float, float)
    # sampleEditorOpen args: pad_index, sample_name, gain_db, fade_in_ms, fade_out_ms

    def __init__(self, cache_dir: Path, use_demucs: bool = True):
        super().__init__()
        self._settings = AppSettings.load(SETTINGS_PATH)
        self._rebuild_pipeline(use_demucs)
        self._rebuild_engine()

        self._project: Optional[Project] = None
        self._status = "Ready. Load a track to begin."
        self._bpm = 0.0
        self._pad_model = PadGridModel()
        self._import_thread: Optional[QThread] = None
        # press-hold-loop tracking: {pad_index: is_looping_due_to_hold}
        self._hold_looping: dict[int, bool] = {}

    # ---- Helpers -------------------------------------------------------

    def _rebuild_pipeline(self, use_demucs: bool = True):
        pb = self._settings.playback
        sep = DemucsSeparator() if use_demucs else DummySeparator()
        from app.audio.slicing.auto_slicer import AutoSlicer
        from app.audio.slicing.pad_assigner import PadAssigner
        slicer = AutoSlicer(self._settings.to_slicer_config())
        assigner = PadAssigner(layout=self._settings.pad_layout)
        self.pipeline = SamplerPipeline(
            cache_dir=Path("data/cache"),
            separator=sep,
            slicer=slicer,
            assigner=assigner,
        )

    def _rebuild_engine(self):
        pb = self._settings.playback
        if hasattr(self, 'engine') and self.engine:
            try:
                self.engine.stop()
            except Exception:
                pass
        self.engine = SounddevicePlaybackEngine(
            sample_rate=pb.sample_rate,
            block_size=pb.block_size,
        )
        self.engine.start()

    @staticmethod
    def _qml_file_to_path(file_url: str) -> Path:
        if file_url.startswith("file"):
            return Path(QUrl(file_url).toLocalFile())
        return Path(file_url)

    # ---- QML properties -----------------------------------------------

    @pyqtProperty(QObject, constant=True)
    def padModel(self):
        return self._pad_model

    @pyqtProperty(str, notify=statusChanged)
    def status(self):
        return self._status

    @pyqtProperty(float, notify=bpmChanged)
    def bpm(self):
        return self._bpm

    @pyqtProperty(str, notify=projectChanged)
    def trackName(self):
        if self._project and self._project.sources:
            return Path(str(self._project.sources[0].path)).stem
        return ""

    # Settings exposed as flat properties for QML bindings
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
    @pyqtProperty(int, notify=settingsChanged)
    def nLoopsPerStem(self): return self._settings.slicing.n_loops_per_stem
    @pyqtProperty(int, notify=settingsChanged)
    def drumLoopBars(self): return self._settings.slicing.drum_loop_bars
    @pyqtProperty(int, notify=settingsChanged)
    def bassLoopBars(self): return self._settings.slicing.bass_loop_bars
    @pyqtProperty(int, notify=settingsChanged)
    def melodyPhraseBars(self): return self._settings.slicing.melody_phrase_bars

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
        self._hold_looping[pad_index] = False

    @pyqtSlot(int)
    def releasePad(self, pad_index: int):
        if not self._project:
            return
        bank = self._project.active_bank()
        if not bank:
            return
        pad = bank.pads[pad_index]
        # If press-hold-loop is on and we were looping due to hold, stop now
        if self._settings.playback.press_hold_loop:
            if self._hold_looping.get(pad_index):
                self.engine.release_pad(pad)
                self._hold_looping[pad_index] = False
        if pad.mode in (PadMode.HOLD, PadMode.GATE):
            self.engine.release_pad(pad)
        self._pad_model.set_active(pad_index, False)

    @pyqtSlot(int)
    def padHoldTick(self, pad_index: int):
        """
        Called from QML timer while a pad is held.
        Implements press-and-hold-loop: once the sample would have ended,
        switch to loop mode for this pad (temporarily) until released.
        QML timer runs every ~100ms while pad is pressed.
        """
        if not self._settings.playback.press_hold_loop:
            return
        if not self._project or self._hold_looping.get(pad_index):
            return
        bank = self._project.active_bank()
        if not bank:
            return
        pad = bank.pads[pad_index]
        if not pad.sample_id:
            return
        sample = self._project.sample_by_id(pad.sample_id)
        if not sample:
            return
        # If in ONE_SHOT and sample duration elapsed, start looping
        if pad.mode == PadMode.ONE_SHOT:
            dur_ms = sample.length_samples / max(1, self.engine.sample_rate) * 1000
            # We don't have a voice timer, so we re-trigger in loop mode
            # (this creates a seamless loop from the next hold-tick)
            old_mode = pad.mode
            pad.mode = PadMode.LOOP
            self.engine.trigger_pad(pad, sample)
            pad.mode = old_mode
            self._hold_looping[pad_index] = True
            self._pad_model.notify_mode_changed(pad_index)

    @pyqtSlot()
    def stopAll(self):
        self.engine.stop_all()
        for p in (self._project.active_bank().pads if self._project else []):
            self._pad_model.set_active(p.index, False)
        self._hold_looping.clear()

    @pyqtSlot(int)
    def cyclePadMode(self, pad_index: int):
        if not self._project:
            return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)):
            return
        pad = bank.pads[pad_index]
        if not pad.sample_id:
            return
        order = [PadMode.ONE_SHOT, PadMode.LOOP, PadMode.HOLD, PadMode.GATE]
        try:
            i = order.index(pad.mode)
        except ValueError:
            i = -1
        pad.mode = order[(i + 1) % len(order)]
        self.engine.release_pad(pad)
        self._pad_model.notify_mode_changed(pad_index)
        self._set_status(f"Pad {pad_index + 1}: {pad.mode.value}")

    @pyqtSlot(int, str)
    def setPadMode(self, pad_index: int, mode_value: str):
        if not self._project:
            return
        bank = self._project.active_bank()
        if not bank or not (0 <= pad_index < len(bank.pads)):
            return
        try:
            new_mode = PadMode(mode_value)
        except ValueError:
            return
        pad = bank.pads[pad_index]
        pad.mode = new_mode
        self.engine.release_pad(pad)
        self._pad_model.notify_mode_changed(pad_index)
        self._set_status(f"Pad {pad_index + 1}: {pad.mode.value}")

    # ---- QML slots — sample editor ------------------------------------

    @pyqtSlot(int)
    def openSampleEditor(self, pad_index: int):
        """Ctrl+click on pad: emit signal that opens the sample editor panel."""
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
        sr = self.engine.sample_rate
        fade_in_ms  = sample.fade_in_samples  / sr * 1000
        fade_out_ms = sample.fade_out_samples / sr * 1000
        self.sampleEditorOpen.emit(
            pad_index, sample.name,
            sample.gain_db, fade_in_ms, fade_out_ms,
        )

    @pyqtSlot(int, float, float, float)
    def applySampleEdit(self, pad_index: int,
                        gain_db: float, fade_in_ms: float, fade_out_ms: float):
        """Save edited values to the Sample and re-render the buffer."""
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
        sr = self.engine.sample_rate
        sample.gain_db         = float(gain_db)
        sample.fade_in_samples  = max(0, int(fade_in_ms  / 1000 * sr))
        sample.fade_out_samples = max(0, int(fade_out_ms / 1000 * sr))
        # Re-render the cached buffer
        self.engine.register_sample(sample)
        self._set_status(
            f"{sample.name}: gain {gain_db:+.1f} dB, "
            f"fade in {fade_in_ms:.0f}ms, fade out {fade_out_ms:.0f}ms"
        )

    # ---- QML slots — settings -----------------------------------------

    @pyqtSlot(
        float, float, float, int,   # vocal phrase
        int, int,                   # vocal chop
        int, int,                   # drum hit
        int, int, int, int,         # loops
    )
    def applySlicingSettings(
        self,
        min_vocal_phrase_ms, max_vocal_phrase_ms,
        vocal_phrase_min_gap_ms, max_vocal_phrases,
        vocal_chop_length_ms, max_vocal_chops,
        drum_hit_length_ms, max_drum_hits,
        n_loops_per_stem, drum_loop_bars, bass_loop_bars, melody_phrase_bars,
    ):
        s = self._settings.slicing
        s.min_vocal_phrase_ms    = min_vocal_phrase_ms
        s.max_vocal_phrase_ms    = max_vocal_phrase_ms
        s.vocal_phrase_min_gap_ms = vocal_phrase_min_gap_ms
        s.max_vocal_phrases      = int(max_vocal_phrases)
        s.vocal_chop_length_ms   = int(vocal_chop_length_ms)
        s.max_vocal_chops        = int(max_vocal_chops)
        s.drum_hit_length_ms     = int(drum_hit_length_ms)
        s.max_drum_hits          = int(max_drum_hits)
        s.n_loops_per_stem       = int(n_loops_per_stem)
        s.drum_loop_bars         = int(drum_loop_bars)
        s.bass_loop_bars         = int(bass_loop_bars)
        s.melody_phrase_bars     = int(melody_phrase_bars)
        self._save_and_notify()

    @pyqtSlot(int, int, int, int, int, int, int)
    def applyPadLayout(
        self,
        pads_drum_hit, pads_drum_loop,
        pads_vocal_chop, pads_vocal_phrase,
        pads_melody, pads_bass_loop, grid_size,
    ):
        pl = self._settings.pad_layout
        pl.pads_drum_hit    = int(pads_drum_hit)
        pl.pads_drum_loop   = int(pads_drum_loop)
        pl.pads_vocal_chop  = int(pads_vocal_chop)
        pl.pads_vocal_phrase = int(pads_vocal_phrase)
        pl.pads_melody      = int(pads_melody)
        pl.pads_bass_loop   = int(pads_bass_loop)
        pl.grid_size        = int(grid_size)
        self._save_and_notify()
        # If a project is loaded, re-run pad assignment with new layout
        if self._project:
            self._reslice_with_new_settings()

    @pyqtSlot(int, int, bool, bool, bool)
    def applyPlaybackSettings(
        self, block_size, sample_rate,
        press_hold_loop, auto_normalize_stems, auto_choke_drums,
    ):
        pb = self._settings.playback
        pb.block_size           = int(block_size)
        pb.sample_rate          = int(sample_rate)
        pb.press_hold_loop      = bool(press_hold_loop)
        pb.auto_normalize_stems = bool(auto_normalize_stems)
        pb.auto_choke_drums     = bool(auto_choke_drums)
        self._save_and_notify()
        self._rebuild_engine()
        # Re-load stems into new engine if project exists
        if self._project:
            self.engine.load_stems(self._project.stems)
            for s in self._project.samples:
                self.engine.register_sample(s)

    def _reslice_with_new_settings(self):
        """Re-run only slicing + pad assignment (fast, no stem separation)."""
        from app.audio.slicing.auto_slicer import AutoSlicer
        from app.audio.slicing.pad_assigner import PadAssigner
        slicer = AutoSlicer(self._settings.to_slicer_config())
        assigner = PadAssigner(layout=self._settings.pad_layout)
        # Clear old samples and banks
        self._project.samples.clear()
        self._project.banks.clear()
        # Re-slice from existing stems + analyses
        for analysis in self._project.analyses:
            stems = [s for s in self._project.stems
                     if s.source_id == analysis.source_id]
            new_samples = slicer.slice_all(stems, analysis)
            self._project.samples.extend(new_samples)
        bank = assigner.auto_assign(self._project.samples)
        self._project.banks.append(bank)
        self._project.active_bank_id = bank.id
        # Update engine + UI
        for s in self._project.samples:
            self.engine.register_sample(s)
        self._pad_model.set_pads(bank.pads)
        self._set_status(
            f"Re-sliced: {len(self._project.samples)} samples, "
            f"{sum(1 for p in bank.pads if p.sample_id)} pads filled"
        )

    def _save_and_notify(self):
        self._settings.save(SETTINGS_PATH)
        self.settingsChanged.emit()

    # ---- Import internals ---------------------------------------------

    def _start_import(self, path: Path):
        if self._import_thread and self._import_thread.isRunning():
            self._set_status("Import already running.")
            return
        self._rebuild_pipeline()
        self._import_thread = QThread()
        self._worker = ImportWorker(self.pipeline, path)
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
        self._set_status(f"{int(p * 100)}% — {msg}")
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
            self.bpmChanged.emit()
        self._set_status(f"Loaded. {len(project.samples)} samples ready.")
        self.projectChanged.emit()
        self.importDone.emit()

    def _on_import_error(self, msg: str):
        self._set_status(f"Error: {msg}")
        self.importError.emit(msg)

    def _set_status(self, s: str):
        self._status = s
        self.statusChanged.emit()