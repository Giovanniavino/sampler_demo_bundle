"""
Project persistence: JSON for metadata, sidecar wav files for stems/samples.

Layout on disk:
    project_dir/
        project.json          # everything in this file
        stems/
            vocals.wav
            drums.wav
            ...
        samples/
            <sample-id>.wav   # only for rendered samples (user edits)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from app.core.models import (
    AnalysisResult, AudioSource, Beat, Pad, PadBank, PadMode, Project,
    Sample, SampleCategory, Section, SectionLabel, Stem, StemType, Transient,
)

log = logging.getLogger(__name__)


def _to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


class ProjectRepository:
    SCHEMA_VERSION = 1

    def save(self, project: Project, project_dir: Path) -> Path:
        project_dir.mkdir(parents=True, exist_ok=True)
        out_file = project_dir / "project.json"
        data = {
            "schema_version": self.SCHEMA_VERSION,
            "project": _to_jsonable(project),
        }
        with out_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info("Saved project to %s", out_file)
        return out_file

    def load(self, project_dir: Path) -> Project:
        in_file = project_dir / "project.json"
        with in_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        p = data["project"]
        proj = Project(
            id=p["id"], name=p["name"], version=p["version"],
            active_bank_id=p.get("active_bank_id"),
            sources=[self._mk_source(x) for x in p.get("sources", [])],
            stems=[self._mk_stem(x) for x in p.get("stems", [])],
            analyses=[self._mk_analysis(x) for x in p.get("analyses", [])],
            samples=[self._mk_sample(x) for x in p.get("samples", [])],
            banks=[self._mk_bank(x) for x in p.get("banks", [])],
        )
        log.info("Loaded project from %s", in_file)
        return proj

    # ---- Reconstruction helpers ---------------------------------------

    def _path(self, v) -> Path | None:
        return Path(v) if v else None

    def _mk_source(self, d) -> AudioSource:
        return AudioSource(
            id=d["id"], path=self._path(d["path"]),
            sample_rate=d["sample_rate"], channels=d["channels"],
            duration_samples=d["duration_samples"],
        )

    def _mk_stem(self, d) -> Stem:
        return Stem(
            id=d["id"], source_id=d["source_id"],
            stem_type=StemType(d["stem_type"]), path=self._path(d["path"]),
            sample_rate=d["sample_rate"], channels=d["channels"],
            duration_samples=d["duration_samples"],
        )

    def _mk_analysis(self, d) -> AnalysisResult:
        return AnalysisResult(
            source_id=d["source_id"], bpm=d["bpm"],
            bpm_confidence=d["bpm_confidence"],
            beats=[Beat(**b) for b in d["beats"]],
            sections=[Section(start=s["start"], end=s["end"],
                              label=SectionLabel(s["label"]),
                              confidence=s["confidence"]) for s in d["sections"]],
            transients=[Transient(**t) for t in d["transients"]],
            key=d.get("key"),
            time_signature=tuple(d.get("time_signature", (4, 4))),
        )

    def _mk_sample(self, d) -> Sample:
        return Sample(
            id=d["id"], name=d["name"],
            category=SampleCategory(d["category"]),
            source_stem_id=d.get("source_stem_id"),
            start_sample=d["start_sample"], end_sample=d["end_sample"],
            path=self._path(d.get("path")),
            gain_db=d["gain_db"], pitch_semitones=d["pitch_semitones"],
            time_stretch=d["time_stretch"], reverse=d["reverse"],
            fade_in_samples=d["fade_in_samples"], fade_out_samples=d["fade_out_samples"],
            normalized=d["normalized"], bpm=d.get("bpm"),
            root_note=d.get("root_note"), tags=d.get("tags", []),
        )

    def _mk_pad(self, d) -> Pad:
        return Pad(
            index=d["index"], sample_id=d.get("sample_id"),
            mode=PadMode(d["mode"]), color=d["color"], label=d["label"],
            muted=d["muted"], group=d["group"],
        )

    def _mk_bank(self, d) -> PadBank:
        return PadBank(
            id=d["id"], name=d["name"],
            pads=[self._mk_pad(p) for p in d["pads"]],
        )
