"""
Pipeline facade.

Single entry point used by UI/CLI:
    pipeline.import_track(path) -> Project (fully populated)

Each stage is delegated to its own class so we can mock/replace them in tests
and swap implementations (e.g. Demucs -> Open-Unmix) at the composition root.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

import soundfile as sf

from app.audio.analysis.analyzer import Analyzer, LibrosaAnalyzer
from app.audio.separation.separator import DemucsSeparator, Separator
from app.audio.slicing.auto_slicer import AutoSlicer
from app.audio.slicing.pad_assigner import PadAssigner
from app.core.models import AudioSource, Project

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str], None]


class SamplerPipeline:
    def __init__(
        self,
        cache_dir: Path,
        separator: Optional[Separator] = None,
        analyzer: Optional[Analyzer] = None,
        slicer: Optional[AutoSlicer] = None,
        assigner: Optional[PadAssigner] = None,
    ):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.separator = separator or DemucsSeparator()
        self.analyzer = analyzer or LibrosaAnalyzer()
        self.slicer = slicer or AutoSlicer()
        self.assigner = assigner or PadAssigner()

    def import_track(
        self,
        audio_path: Path,
        project: Optional[Project] = None,
        progress: Optional[ProgressCb] = None,
    ) -> Project:
        project = project or Project(name=audio_path.stem)
        report = lambda p, m: (progress(p, m) if progress else None)

        # 0) Pre-flight
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        ok, msg = self.separator.is_available()
        if not ok:
            raise RuntimeError(f"Separator unavailable: {msg}")

        # 1) Read audio metadata
        report(0.02, "Reading audio file")
        try:
            info = sf.info(str(audio_path))
        except Exception as e:
            raise RuntimeError(
                f"Could not read audio file {audio_path.name}. "
                f"Make sure it's a valid mp3/wav/flac/ogg. ({e})"
            )
        if info.frames < info.samplerate:  # < 1 second
            log.warning("Audio is very short (%.2fs); results may be poor",
                        info.frames / info.samplerate)

        source = AudioSource(
            path=audio_path,
            sample_rate=info.samplerate,
            channels=info.channels,
            duration_samples=info.frames,
        )
        project.sources.append(source)

        # 2) Separation
        report(0.05, "Separating stems")
        stem_dir = self.cache_dir / source.id
        try:
            stems = self.separator.separate(
                source, stem_dir,
                progress=lambda p, m: report(0.05 + 0.55 * p, m),
            )
        except Exception as e:
            log.exception("Separation failed")
            raise RuntimeError(f"Stem separation failed: {e}")
        project.stems.extend(stems)

        # 3) Analysis
        report(0.65, "Analyzing")
        try:
            analysis = self.analyzer.analyze(source, stems)
        except Exception as e:
            log.exception("Analysis failed")
            raise RuntimeError(f"Audio analysis failed: {e}")
        project.analyses.append(analysis)
        report(0.8, f"BPM: {analysis.bpm:.1f}, {len(analysis.beats)} beats")

        # 4) Auto-slice
        report(0.85, "Slicing samples")
        samples = self.slicer.slice_all(stems, analysis)
        if not samples:
            log.warning("No samples produced — track may be too short or "
                        "transient detection failed")
        project.samples.extend(samples)

        # 5) Pad assignment
        report(0.95, "Assigning pads")
        bank = self.assigner.auto_assign(samples)
        project.banks.append(bank)
        project.active_bank_id = bank.id

        report(1.0, "Ready")
        log.info("Pipeline complete: %d stems, %d samples, %d pads filled",
                 len(stems), len(samples),
                 sum(1 for p in bank.pads if p.sample_id))
        return project
