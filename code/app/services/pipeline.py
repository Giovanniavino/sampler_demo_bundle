"""
Pipeline facade — orchestrates the full import flow.

Noise reduction positions:
  FAST mode:
    1. NR on full mix (pre-separation, fast profile)
    2. Separate stems
    3. Analyze + slice

  QUALITY mode:
    1. NR on full mix (pre-separation, quality_pre profile)
    2. Separate stems
    3. NR on each stem individually (post-separation, quality_post profile)
    4. Analyze + slice
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

import soundfile as sf

from app.audio.analysis.analyzer import Analyzer, LibrosaAnalyzer
from app.audio.dsp.noise_reduction import reduce_noise_file
from app.audio.separation.separator import DemucsSeparator, Separator
from app.audio.slicing.auto_slicer import AutoSlicer
from app.audio.slicing.pad_assigner import PadAssigner
from app.core.models import AudioSource, Project
from app.core.settings import AppSettings

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str], None]


class SamplerPipeline:
    def __init__(
        self,
        cache_dir: Path,
        settings: Optional[AppSettings] = None,
        separator: Optional[Separator] = None,
        analyzer: Optional[Analyzer] = None,
        slicer: Optional[AutoSlicer] = None,
        assigner: Optional[PadAssigner] = None,
    ):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings or AppSettings()
        self.separator = separator or DemucsSeparator(
            model_name=self.settings.demucs_model
        )
        self.analyzer = analyzer or LibrosaAnalyzer()
        self.slicer = slicer or AutoSlicer(self.settings.to_slicer_config())
        self.assigner = assigner or PadAssigner(
            layout=self.settings.pad_layout
        )

    def import_track(
        self,
        audio_path: Path,
        project: Optional[Project] = None,
        progress: Optional[ProgressCb] = None,
    ) -> Project:
        project = project or Project(name=audio_path.stem)
        rep = lambda p, m: (progress(p, m) if progress else None)

        # 1) Read audio metadata
        rep(0.02, "Reading audio file")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        info = sf.info(str(audio_path))
        source = AudioSource(
            path=audio_path,
            sample_rate=info.samplerate,
            channels=info.channels,
            duration_samples=info.frames,
        )
        project.sources.append(source)

        # 2) Noise reduction — PRE separation (always)
        sep_input = audio_path
        if self.settings.noise_reduction_pre:
            rep(0.05, "Noise reduction (pre-separation)…")
            tmp = Path(tempfile.mkdtemp()) / f"nr_pre_{audio_path.name}"
            try:
                sep_input = reduce_noise_file(
                    audio_path,
                    profile=self.settings.nr_pre_profile,
                    out_path=tmp,
                )
                # Update source to point at cleaned file for analysis
                source.path = sep_input
            except Exception as e:
                log.warning("Pre-separation NR failed: %s — using original", e)
                sep_input = audio_path

        # 3) Stem separation
        rep(0.10, "Separating stems")
        stem_dir = self.cache_dir / source.id
        try:
            stems = self.separator.separate(
                source, stem_dir,
                progress=lambda p, m: rep(0.10 + 0.50 * p, m),
            )
        except Exception as e:
            log.exception("Separation failed")
            raise RuntimeError(f"Stem separation failed: {e}")
        project.stems.extend(stems)

        # 4) Noise reduction — POST separation (quality mode only, per stem)
        if self.settings.noise_reduction_post:
            n = len(stems)
            for i, stem in enumerate(stems):
                rep(0.62 + 0.08 * i / max(1, n),
                    f"Noise reduction on {stem.stem_type.value}…")
                try:
                    reduce_noise_file(
                        stem.path,
                        profile=self.settings.nr_post_profile,
                        out_path=stem.path,   # in-place
                    )
                except Exception as e:
                    log.warning("Post-sep NR failed on %s: %s", stem.stem_type, e)

        # 5) Analysis
        rep(0.72, "Analyzing BPM, beats, sections…")
        try:
            analysis = self.analyzer.analyze(source, stems)
        except Exception as e:
            log.exception("Analysis failed")
            raise RuntimeError(f"Analysis failed: {e}")
        project.analyses.append(analysis)
        rep(0.82, f"BPM: {analysis.bpm:.1f}, {len(analysis.beats)} beats")

        # 6) Auto-slice
        rep(0.87, "Slicing samples…")
        samples = self.slicer.slice_all(stems, analysis)
        project.samples.extend(samples)

        # 7) Pad assignment
        rep(0.95, "Assigning pads…")
        bank = self.assigner.auto_assign(samples)
        project.banks.append(bank)
        project.active_bank_id = bank.id

        rep(1.0, "Ready")
        log.info(
            "Pipeline complete: %d stems, %d samples, %d pads filled",
            len(stems), len(samples),
            sum(1 for p in bank.pads if p.sample_id),
        )
        return project