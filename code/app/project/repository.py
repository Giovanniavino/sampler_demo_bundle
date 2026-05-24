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
import shutil
from dataclasses import asdict, is_dataclass
from datetime import datetime
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
            normalized=d["normalized"],
            cutoff_hz=d.get("cutoff_hz", 20000.0),
            highpass_hz=d.get("highpass_hz", 20.0),
            pan=d.get("pan", 0.0),
            loop_beats=d.get("loop_beats", 0),
            loop_ready=d.get("loop_ready", False),
            bpm=d.get("bpm"),
            root_note=d.get("root_note"), tags=d.get("tags", []),
        )

    def _mk_pad(self, d) -> Pad:
        return Pad(
            index=d["index"], sample_id=d.get("sample_id"),
            mode=PadMode(d["mode"]), color=d["color"], label=d["label"],
            muted=d["muted"], group=d["group"],
            choke_self=d.get("choke_self", False),
        )

    def _mk_bank(self, d) -> PadBank:
        return PadBank(
            id=d["id"], name=d["name"],
            pads=[self._mk_pad(p) for p in d["pads"]],
        )


def safe_name(name: str) -> str:
    """Sanitize a name for use as a folder / file name."""
    cleaned = "".join(
        c for c in (name or "") if c.isalnum() or c in "-_. "
    ).strip()
    return cleaned or "untitled"


class KitRepository(ProjectRepository):
    """
    Reads and writes self-contained *kit* folders — the unit the hardware
    device stores on its (virtual) SD card.

        <kit_dir>/
            kit.json           # metadata + project graph, RELATIVE audio paths
            stems/*.wav         # copied stem audio
            samples/*.wav       # copied audio for path-based (rendered) samples

    Region-based samples carry no file: they reference a stem + start/end,
    so only the stem audio needs to travel with the kit.
    """

    def save_kit(self, project: Project, kit_dir: Path,
                 kit_name: str | None = None) -> Path:
        """Write a project to a kit folder, copying its audio in."""
        kit_dir = Path(kit_dir)
        stems_dir = kit_dir / "stems"
        samples_dir = kit_dir / "samples"
        stems_dir.mkdir(parents=True, exist_ok=True)
        samples_dir.mkdir(parents=True, exist_ok=True)

        data = _to_jsonable(project)

        # Copy stem audio, rewrite each path relative to the kit folder.
        for sd, stem in zip(data.get("stems", []), project.stems):
            src = Path(stem.path) if stem.path else None
            if src and src.exists():
                dest = stems_dir / f"{stem.stem_type.value}.wav"
                if src.resolve() != dest.resolve():
                    shutil.copy2(src, dest)
                sd["path"] = f"stems/{dest.name}"
            else:
                sd["path"] = None

        # Copy audio for path-based samples; region samples keep path None.
        for sd, sample in zip(data.get("samples", []), project.samples):
            src = Path(sample.path) if sample.path else None
            if src and src.exists():
                dest = samples_dir / f"{sample.id}.wav"
                if src.resolve() != dest.resolve():
                    shutil.copy2(src, dest)
                sd["path"] = f"samples/{dest.name}"
            else:
                sd["path"] = None

        # The original imported song is not part of a portable kit.
        for src_data in data.get("sources", []):
            src_data["path"] = None

        kit = {
            "schema_version": self.SCHEMA_VERSION,
            "kit_name": safe_name(kit_name or project.name),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "project": data,
        }
        kit_json = kit_dir / "kit.json"
        with kit_json.open("w", encoding="utf-8") as f:
            json.dump(kit, f, indent=2, ensure_ascii=False)
        log.info("Saved kit to %s", kit_dir)
        return kit_json

    def load_kit(self, kit_dir: Path) -> Project:
        """Reconstruct a Project from a kit folder (audio paths absolute)."""
        kit_dir = Path(kit_dir)
        with (kit_dir / "kit.json").open("r", encoding="utf-8") as f:
            kit = json.load(f)
        p = kit["project"]
        proj = Project(
            id=p["id"], name=p["name"], version=p["version"],
            active_bank_id=p.get("active_bank_id"),
            sources=[self._mk_source(x) for x in p.get("sources", [])],
            stems=[self._mk_stem(x) for x in p.get("stems", [])],
            analyses=[self._mk_analysis(x) for x in p.get("analyses", [])],
            samples=[self._mk_sample(x) for x in p.get("samples", [])],
            banks=[self._mk_bank(x) for x in p.get("banks", [])],
        )
        # Resolve relative audio paths against the kit folder.
        for stem in proj.stems:
            if stem.path and not stem.path.is_absolute():
                stem.path = (kit_dir / stem.path).resolve()
        for sample in proj.samples:
            if sample.path and not sample.path.is_absolute():
                sample.path = (kit_dir / sample.path).resolve()
        log.info("Loaded kit from %s", kit_dir)
        return proj

    def validate_kit(self, kit_dir: Path) -> tuple[bool, list[str]]:
        """Check a kit: kit.json parses and every referenced file exists."""
        kit_dir = Path(kit_dir)
        kit_json = kit_dir / "kit.json"
        if not kit_json.exists():
            return False, ["kit.json is missing"]
        try:
            with kit_json.open("r", encoding="utf-8") as f:
                kit = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            return False, [f"kit.json is unreadable: {e}"]
        p = kit.get("project")
        if not isinstance(p, dict):
            return False, ["kit.json has no 'project' section"]

        errors: list[str] = []
        for stem in p.get("stems", []):
            rel = stem.get("path")
            if rel and not (kit_dir / rel).exists():
                errors.append(f"missing stem audio: {rel}")
        for sample in p.get("samples", []):
            rel = sample.get("path")
            if rel and not (kit_dir / rel).exists():
                errors.append(f"missing sample audio: {rel}")
        return (not errors), errors

    # ---- Presets (pad layout only — no audio, no samples) -------------

    def save_preset(self, name: str, pads: list[Pad],
                    presets_dir: Path) -> Path:
        """Save a pad layout (mode / group / color / label) as a preset."""
        presets_dir = Path(presets_dir)
        presets_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": self.SCHEMA_VERSION,
            "name": name,
            "pads": [
                {"index": p.index, "mode": p.mode.value,
                 "color": p.color, "label": p.label, "group": p.group,
                 "choke_self": p.choke_self}
                for p in pads
            ],
        }
        path = presets_dir / f"{safe_name(name)}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info("Saved preset %s", path)
        return path

    def load_preset(self, path: Path) -> list[dict]:
        """Return the pad-config dicts stored in a preset file."""
        with Path(path).open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("pads", [])
