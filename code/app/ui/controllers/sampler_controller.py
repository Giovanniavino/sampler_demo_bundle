"""
QML-facing controller — updated with quality mode + preset settings.
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

    projectChanged   = pyqtSignal()
    bpmChanged       = pyqtSignal()
    statusChanged    = pyqtSignal()
    importProgress   = pyqtSignal(float, str)
    importDone       = pyqtSignal()
    importError      = pyqtSignal(str)
    settingsChanged  = pyqtSignal()
    needsQualityMode = pyqtSignal()          # emitted when mode not yet chosen
    sampleEditorOpen = pyqtSignal(int, str, float, float, float)

    def __init__(self, cache_dir: Path, use_demucs: bool = True):
        super().__init__()
        self._cache_dir  = cache_dir
        self._use_demucs = use_demucs
        self._settings   = AppSettings.load(SETTINGS_PATH)
        self._project: Optional[Project] = None
        self._status  = "Ready. Load a track to begin."
        self._bpm     = 0.0
        self._pad_model = PadGridModel()
        self._import_thread: Optional[QThread] = None
        self._hold_looping: dict[int, bool] = {}
        # Time of last trigger per pad (for press-hold-loop). Engine sample
        # rate so we can compute "is the sample over yet" cheaply.
        self._trigger_time_samples: dict[int, int] = {}
        self._trigger_sample_len: dict[int, int] = {}
        self._trigger_wallclock: dict[int, float] = {}
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

    @pyqtProperty(str, notify=statusChanged)
    def status(self): return self._status

    @pyqtProperty(float, notify=bpmChanged)
    def bpm(self): return self._bpm

    @pyqtProperty(str, notify=projectChanged)
    def trackName(self):
        if self._project and self._project.sources:
            return Path(str(self._project.sources[0].path)).stem
        return ""

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

    # Custom values (only used when preset == "Custom")
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
        """Called from first-launch dialog. mode: 'fast' or 'quality'."""
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
        """Let the user re-choose from settings."""
        self._settings.quality_mode = None
        self._settings.save(SETTINGS_PATH)
        self.settingsChanged.emit()
        self.needsQualityMode.emit()

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
        # Record when this trigger happened and how long the sample is.
        # Used by padHoldTick to wait until the sample actually finishes.
        import time
        self._trigger_wallclock[pad_index] = time.monotonic()
        self._trigger_sample_len[pad_index] = sample.length_samples

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
        """
        Called periodically by QML while a pad is held down.
        Only re-triggers in loop mode AFTER the original sample has ended.
        Previously it was firing at 80ms after the press, causing a double
        trigger that sounded like the sample played twice.
        """
        if not self._settings.playback.press_hold_loop: return
        if not self._project or self._hold_looping.get(pad_index): return
        bank = self._project.active_bank()
        if not bank: return
        pad = bank.pads[pad_index]
        if not pad.sample_id: return
        sample = self._project.sample_by_id(pad.sample_id)
        if not sample: return

        # Only trigger the hold-loop AFTER the original playback would end.
        # Add a small safety margin (50ms) so we don't overlap.
        import time
        trigger_t = self._trigger_wallclock.get(pad_index, 0)
        sample_len_samples = self._trigger_sample_len.get(pad_index, 0)
        if not trigger_t or not sample_len_samples:
            return
        sample_dur_s = sample_len_samples / max(1, self.engine.sample_rate)
        elapsed = time.monotonic() - trigger_t
        # Add small grace period to avoid clicks
        if elapsed < sample_dur_s - 0.05:
            return  # not yet — sample still playing

        if pad.mode == PadMode.ONE_SHOT:
            old_mode = pad.mode
            pad.mode = PadMode.LOOP
            self.engine.trigger_pad(pad, sample)
            pad.mode = old_mode
            self._hold_looping[pad_index] = True
            # Reset the timer so future ticks don't re-retrigger
            self._trigger_wallclock[pad_index] = time.monotonic() + 999.0

    @pyqtSlot()
    def stopAll(self):
        self.engine.stop_all()
        for p in (self._project.active_bank().pads if self._project else []):
            self._pad_model.set_active(p.index, False)
        self._hold_looping.clear()

    @pyqtSlot(int)
    def cyclePadMode(self, pad_index: int):
        """Cycle between ONE_SHOT and LOOP only (Hold/Gate available via
        setPadMode for advanced users)."""
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

    # ---- QML slots — sample editor ------------------------------------

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
        self._set_status(
            f"{sample.name}: {gain_db:+.1f} dB  "
            f"fade in {fade_in_ms:.0f}ms  fade out {fade_out_ms:.0f}ms"
        )

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
        """Re-run slicing+pad assignment with current settings (no re-separation)."""
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
        filled = sum(1 for p in bank.pads if p.sample_id)
        self._set_status(
            f"Re-sliced: {len(self._project.samples)} samples, "
            f"{filled} pads filled"
        )

    def _save_and_notify(self):
        self._settings.save(SETTINGS_PATH)
        self.settingsChanged.emit()

    # ---- Import internals ---------------------------------------------

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
            self.bpmChanged.emit()
        self._set_status(f"Loaded — {len(project.samples)} samples ready.")
        self.projectChanged.emit()
        self.importDone.emit()

    def _on_import_error(self, msg: str):
        self._set_status(f"Error: {msg}")
        self.importError.emit(msg)

    def _set_status(self, s: str):
        self._status = s
        self.statusChanged.emit()
