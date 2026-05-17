"""
QML-facing controller. The only object QML imports from Python.

It owns the Project, pipeline, and playback engine. QML talks to it via
slots/properties; it emits signals when state changes so the UI redraws.

Threading:
  - Long jobs (import_track) run on a QThread worker; we signal back to the
    GUI thread when done. Never block the GUI thread.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QAbstractListModel, QModelIndex, QObject, QThread, Qt, QUrl,
    pyqtProperty, pyqtSignal, pyqtSlot,
)

from app.audio.playback.engine import SounddevicePlaybackEngine
from app.audio.separation.separator import DemucsSeparator, DummySeparator
from app.audio.slicing.pad_assigner import CATEGORY_COLORS
from app.core.models import Pad, PadMode, Project, Sample
from app.services.pipeline import SamplerPipeline

log = logging.getLogger(__name__)


def _qml_file_to_path(file_url: str) -> Path:
    """Convert QML FileDialog values to local filesystem paths."""
    raw = str(file_url).strip()
    url = QUrl(raw)
    if url.isLocalFile():
        return Path(url.toLocalFile())
    return Path(raw)


# ---------------------------------------------------------------------------
# Pad list model (exposed to QML as a model for a GridView)
# ---------------------------------------------------------------------------

class PadGridModel(QAbstractListModel):
    IndexRole   = Qt.ItemDataRole.UserRole + 1
    LabelRole   = Qt.ItemDataRole.UserRole + 2
    ColorRole   = Qt.ItemDataRole.UserRole + 3
    HasSampleRole = Qt.ItemDataRole.UserRole + 4
    ActiveRole  = Qt.ItemDataRole.UserRole + 5
    ModeRole    = Qt.ItemDataRole.UserRole + 6

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
        # Notify just that one row
        for row, p in enumerate(self._pads):
            if p.index == pad_index:
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [self.ActiveRole])
                break


# ---------------------------------------------------------------------------
# Import worker (background thread)
# ---------------------------------------------------------------------------

class ImportWorker(QObject):
    progress = pyqtSignal(float, str)
    finished = pyqtSignal(object)             # emits Project
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

    # Signals exposed to QML
    projectChanged = pyqtSignal()
    bpmChanged = pyqtSignal()
    statusChanged = pyqtSignal()
    importProgress = pyqtSignal(float, str)
    importDone = pyqtSignal()
    importError = pyqtSignal(str)

    def __init__(self, cache_dir: Path, use_demucs: bool = True):
        super().__init__()
        separator = DemucsSeparator() if use_demucs else DummySeparator()
        self.pipeline = SamplerPipeline(cache_dir=cache_dir, separator=separator)
        self.engine = SounddevicePlaybackEngine()
        self.engine.start()

        self._project: Optional[Project] = None
        self._status = "Ready. Load a track to begin."
        self._bpm = 0.0
        self._pad_model = PadGridModel()
        self._import_thread: Optional[QThread] = None

    # ---- QML-accessible properties ------------------------------------

    @pyqtProperty(QObject, constant=True)
    def padModel(self):  # noqa: N802
        return self._pad_model

    @pyqtProperty(str, notify=statusChanged)
    def status(self):
        return self._status

    @pyqtProperty(float, notify=bpmChanged)
    def bpm(self):
        return self._bpm

    @pyqtProperty(str, notify=projectChanged)
    def trackName(self):  # noqa: N802
        if self._project and self._project.sources:
            return Path(str(self._project.sources[0].path)).stem
        return ""

    # ---- QML-callable slots -------------------------------------------

    @pyqtSlot(str)
    def loadTrack(self, file_url: str):  # noqa: N802
        """file_url comes from QML FileDialog (file:// URL or plain path)."""
        path = _qml_file_to_path(file_url)
        if not path.exists():
            self._set_status(f"File not found: {path}")
            return
        self._set_status(f"Loading {path.name}...")
        self._start_import(path)

    @pyqtSlot(int)
    def triggerPad(self, pad_index: int):  # noqa: N802
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

    @pyqtSlot(int)
    def releasePad(self, pad_index: int):  # noqa: N802
        if not self._project:
            return
        bank = self._project.active_bank()
        if not bank:
            return
        pad = bank.pads[pad_index]
        if pad.mode in (PadMode.HOLD, PadMode.GATE):
            self.engine.release_pad(pad)
        self._pad_model.set_active(pad_index, False)

    @pyqtSlot()
    def stopAll(self):  # noqa: N802
        self.engine.stop_all()
        for p in (self._project.active_bank().pads if self._project else []):
            self._pad_model.set_active(p.index, False)

    # ---- Internals ----------------------------------------------------

    def _start_import(self, path: Path):
        # Cancel any in-flight import
        if self._import_thread and self._import_thread.isRunning():
            self._set_status("Another import is already running.")
            return

        self._import_thread = QThread()
        self._worker = ImportWorker(self.pipeline, path)
        self._worker.moveToThread(self._import_thread)

        self._import_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_imported)
        self._worker.error.connect(self._on_import_error)
        # Cleanup
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
        # Load stems & register samples into the playback engine
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
