"""
HeuristicSeparator — a DSP-based fallback separator that runs WITHOUT torch/demucs.

It's not AI-quality. But it produces 4 real, distinct wav stems that
downstream code (analyzer, slicer, pad assigner, playback engine) can use
end-to-end. We use it for:
  - environments without GPU/torch
  - first-run smoke tests
  - CI / unit tests
  - the synthetic test track demo

Algorithm:
  - DRUMS  : high-pass + transient emphasis (above ~250 Hz, gated by onset env)
  - BASS   : low-pass <120 Hz
  - VOCALS : center-channel extraction (mid - sides) band-passed 200-4000 Hz
  - OTHER  : the original mix minus drums and bass (rough residual)

The point is not quality. The point is producing 4 valid stem wav files that
exercise the rest of the pipeline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from scipy import signal

from app.audio.separation.separator import Separator
from app.core.models import AudioSource, Stem, StemType

log = logging.getLogger(__name__)


def _butter_lp(audio: np.ndarray, cutoff: float, sr: int, order: int = 4) -> np.ndarray:
    sos = signal.butter(order, cutoff, btype="low", fs=sr, output="sos")
    return signal.sosfiltfilt(sos, audio, axis=0).astype(np.float32)


def _butter_hp(audio: np.ndarray, cutoff: float, sr: int, order: int = 4) -> np.ndarray:
    sos = signal.butter(order, cutoff, btype="high", fs=sr, output="sos")
    return signal.sosfiltfilt(sos, audio, axis=0).astype(np.float32)


def _butter_bp(audio: np.ndarray, low: float, high: float, sr: int, order: int = 4) -> np.ndarray:
    sos = signal.butter(order, [low, high], btype="band", fs=sr, output="sos")
    return signal.sosfiltfilt(sos, audio, axis=0).astype(np.float32)


class HeuristicSeparator(Separator):
    """DSP-only separator. Output is rough but real."""

    def separate(self, source: AudioSource, output_dir: Path, progress=None) -> list[Stem]:
        output_dir.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(0.05, "Loading audio")
        audio, sr = sf.read(str(source.path), dtype="float32", always_2d=True)
        # Ensure stereo
        if audio.shape[1] == 1:
            audio = np.repeat(audio, 2, axis=1)

        results: list[Stem] = []

        # ----- BASS: low-pass below 120 Hz ------------------------------
        if progress: progress(0.20, "Extracting bass")
        bass = _butter_lp(audio, cutoff=120.0, sr=sr)
        results.append(self._save_stem(bass, sr, StemType.BASS, source.id, output_dir))

        # ----- DRUMS: high-pass + transient gate ------------------------
        if progress: progress(0.40, "Extracting drums")
        hp = _butter_hp(audio, cutoff=250.0, sr=sr)
        # Transient envelope from the mono mix
        mono = audio.mean(axis=1)
        env_full = np.abs(signal.hilbert(mono)).astype(np.float32)
        # Gate: emphasize where envelope rises sharply
        env_smooth = np.convolve(env_full, np.ones(int(sr * 0.01)) / (sr * 0.01), mode="same")
        rising = np.maximum(env_full - env_smooth, 0)
        rising = rising / (rising.max() + 1e-8)
        # Stretch to stereo column
        gate = rising[:, None].repeat(2, axis=1).astype(np.float32)
        drums = hp * (0.4 + 0.6 * gate)   # always some HP signal, boosted on transients
        results.append(self._save_stem(drums, sr, StemType.DRUMS, source.id, output_dir))

        # ----- VOCALS: center-channel + bandpass 200-4000 ---------------
        if progress: progress(0.60, "Extracting vocals")
        L = audio[:, 0]
        R = audio[:, 1]
        mid = (L + R) / 2
        sides = (L - R) / 2
        # Mid emphasis: anything in the center is more likely vocal
        # Subtract a portion of sides (instruments panned wide)
        center = mid - 0.5 * np.abs(sides)
        center_stereo = np.stack([center, center], axis=1).astype(np.float32)
        vocals = _butter_bp(center_stereo, low=200.0, high=4000.0, sr=sr)
        # Energy gate to suppress purely instrumental sections
        v_env = np.abs(signal.hilbert(vocals.mean(axis=1)))
        v_env_smooth = np.convolve(v_env, np.ones(int(sr * 0.05)) / (sr * 0.05), mode="same")
        v_gate = v_env_smooth / (v_env_smooth.max() + 1e-8)
        vocals = vocals * v_gate[:, None].astype(np.float32)
        results.append(self._save_stem(vocals, sr, StemType.VOCALS, source.id, output_dir))

        # ----- OTHER: residual ------------------------------------------
        if progress: progress(0.85, "Extracting melody/other")
        # Subtract bass + drums from the original (very rough)
        residual = audio - bass - 0.7 * drums
        # Band-limit so we don't get extreme highs/lows
        other = _butter_bp(residual, low=100.0, high=8000.0, sr=sr)
        results.append(self._save_stem(other, sr, StemType.OTHER, source.id, output_dir))

        if progress: progress(1.0, "Heuristic separation done")
        return results

    def _save_stem(self, audio: np.ndarray, sr: int, stem_type: StemType,
                   source_id: str, out_dir: Path) -> Stem:
        # Normalize each stem to -6 dBFS to keep things audible without clipping
        peak = float(np.max(np.abs(audio))) or 1.0
        if peak > 0:
            audio = (audio / peak * 0.5).astype(np.float32)
        path = out_dir / f"{stem_type.value}.wav"
        sf.write(str(path), audio, sr)
        return Stem(
            source_id=source_id,
            stem_type=stem_type,
            path=path,
            sample_rate=sr,
            channels=audio.shape[1] if audio.ndim == 2 else 1,
            duration_samples=audio.shape[0],
        )
