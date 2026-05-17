"""
Headless CLI to run the full pipeline without the GUI.

Examples:
    python -m scripts.cli_run path/to/song.mp3
    python -m scripts.cli_run song.mp3 --no-demucs --out data/projects/test
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.audio.separation.heuristic import HeuristicSeparator
from app.audio.separation.separator import DemucsSeparator, DummySeparator
from app.core.logging_setup import setup_logging
from app.project.repository import ProjectRepository
from app.services.pipeline import SamplerPipeline


def main() -> int:
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", type=Path, help="Input audio file")
    ap.add_argument("--cache", type=Path, default=Path("data/cache"))
    ap.add_argument("--out",   type=Path, default=Path("data/projects/cli_out"))
    ap.add_argument("--no-demucs", action="store_true",
                    help="Skip Demucs (use a dummy single-stem separator)")
    ap.add_argument("--heuristic", action="store_true",
                    help="Use heuristic DSP separator instead of Demucs (works offline)")
    args = ap.parse_args()

    if not args.audio.exists():
        print(f"Audio not found: {args.audio}", file=sys.stderr)
        return 2

    if args.heuristic:
        separator = HeuristicSeparator()
    elif args.no_demucs:
        separator = DummySeparator()
    else:
        separator = DemucsSeparator()
    pipeline = SamplerPipeline(cache_dir=args.cache, separator=separator)

    def progress(p: float, msg: str):
        print(f"[{int(p*100):3d}%] {msg}")

    project = pipeline.import_track(args.audio, progress=progress)
    out = ProjectRepository().save(project, args.out)
    print(f"Project saved to {out}")

    # Summary
    print(f"  source : {project.sources[0].path.name}")
    print(f"  stems  : {[s.stem_type.value for s in project.stems]}")
    a = project.analyses[0]
    print(f"  BPM    : {a.bpm:.1f}")
    print(f"  beats  : {len(a.beats)}")
    print(f"  trans. : {len(a.transients)}")
    print(f"  sect.  : {[s.label.value for s in a.sections]}")
    print(f"  samples: {len(project.samples)}")
    filled = sum(1 for p in project.active_bank().pads if p.sample_id)
    print(f"  pads   : {filled}/{len(project.active_bank().pads)} filled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
