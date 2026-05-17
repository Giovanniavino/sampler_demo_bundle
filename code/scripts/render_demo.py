"""
Offline demo: load the project, trigger every pad in sequence,
render the result to a wav file you can listen to.

Skips the live audio device (we don't have one in CI / sandbox).
Instead, we render directly through the engine's mixing logic.
"""

import sys
import numpy as np
import soundfile as sf
from pathlib import Path

# Make app importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audio.playback.engine import SounddevicePlaybackEngine, _Voice
from app.core.logging_setup import setup_logging
from app.core.models import PadMode
from app.project.repository import ProjectRepository

setup_logging()

PROJECT_DIR = Path("data/projects/test1")
OUT_WAV = Path("data/projects/test1/demo_pad_sequence.wav")
SR = 44100


class OfflineEngine(SounddevicePlaybackEngine):
    """Subclass that doesn't open an audio device — we drive the callback manually."""
    def start(self): pass
    def stop(self): pass

    def render_block(self, frames: int) -> np.ndarray:
        out = np.zeros((frames, 2), dtype=np.float32)
        class _T: pass
        self._callback(out, frames, _T(), None)
        return out


def main():
    repo = ProjectRepository()
    project = repo.load(PROJECT_DIR)

    engine = OfflineEngine(sample_rate=SR, block_size=512)
    engine.load_stems(project.stems)
    for s in project.samples:
        engine.register_sample(s)

    bank = project.active_bank()
    print(f"Loaded project: {len(project.samples)} samples, "
          f"{sum(1 for p in bank.pads if p.sample_id)} pads filled")

    # Build a sequence: trigger pad 0, wait 1s, pad 1, wait 1s, ...
    # then a couple of loops at the end held for 4s each.
    out_chunks = []
    block = 512

    def render_seconds(seconds: float):
        n_blocks = int(seconds * SR / block)
        for _ in range(n_blocks):
            out_chunks.append(engine.render_block(block))

    # 1) Trigger each drum hit pad in sequence
    print("Drum hits...")
    for pad_idx in range(0, 4):
        pad = bank.pads[pad_idx]
        if pad.sample_id:
            sample = project.sample_by_id(pad.sample_id)
            engine.trigger_pad(pad, sample)
        render_seconds(0.5)

    # 2) Trigger vocal chops
    print("Vocal chops...")
    for pad_idx in range(4, 8):
        pad = bank.pads[pad_idx]
        if pad.sample_id:
            sample = project.sample_by_id(pad.sample_id)
            engine.trigger_pad(pad, sample)
        render_seconds(0.8)

    # 3) Hold a melodic phrase (loop) for a few seconds
    print("Melodic loop...")
    mel_pad = bank.pads[8]
    if mel_pad.sample_id:
        s = project.sample_by_id(mel_pad.sample_id)
        engine.trigger_pad(mel_pad, s)
    render_seconds(3.0)

    # 4) Add a bass loop on top
    print("Bass loop layered on top...")
    bass_pad = bank.pads[12]
    if bass_pad.sample_id:
        s = project.sample_by_id(bass_pad.sample_id)
        engine.trigger_pad(bass_pad, s)
    render_seconds(4.0)

    # 5) Trigger drum loop too
    print("Drum loop on top...")
    drum_loop_pad = None
    for p in bank.pads:
        if p.sample_id:
            samp = project.sample_by_id(p.sample_id)
            if samp.category.value == "drum_loop":
                drum_loop_pad = p
                break
    if drum_loop_pad:
        engine.trigger_pad(drum_loop_pad,
                            project.sample_by_id(drum_loop_pad.sample_id))
    render_seconds(4.0)

    # Save
    audio = np.concatenate(out_chunks, axis=0)
    sf.write(str(OUT_WAV), audio, SR)
    print(f"Wrote demo render: {OUT_WAV} ({len(audio)/SR:.1f}s)")
    print(f"Audio: shape={audio.shape}, peak={np.max(np.abs(audio)):.3f}")


if __name__ == "__main__":
    main()
