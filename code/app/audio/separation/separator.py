"""
Stem separation.

The Separator interface lets us swap models without touching callers.
Default implementation uses Demucs (htdemucs / htdemucs_6s).

Heavy imports (torch, demucs) are deferred inside methods so the GUI starts
fast and we can run unit tests without the model installed.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from math import gcd
from pathlib import Path
from typing import Callable, Optional

from app.core.models import AudioSource, Stem, StemType

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str], None]  # (0..1, message)


class Separator(ABC):
    """Abstract source separator."""

    @abstractmethod
    def separate(
        self,
        source: AudioSource,
        output_dir: Path,
        progress: Optional[ProgressCb] = None,
    ) -> list[Stem]:
        """Run separation, write stems to output_dir, return Stem records."""

    def is_available(self) -> tuple[bool, str]:
        """Return (ok, message). Override to check deps before running."""
        return True, "ok"


# Mapping from Demucs internal names to our StemType
_DEMUCS_NAME_MAP = {
    "vocals": StemType.VOCALS,
    "drums": StemType.DRUMS,
    "bass": StemType.BASS,
    "other": StemType.OTHER,
    "piano": StemType.PIANO,
    "guitar": StemType.GUITAR,
}


class DemucsSeparator(Separator):
    """
    Demucs-based separator.

    model_name:
        - 'htdemucs'    : 4 stems (vocals, drums, bass, other) - fast, good
        - 'htdemucs_6s' : 6 stems (adds piano, guitar) - slower
        - 'htdemucs_ft' : fine-tuned, best quality, slowest
    """

    def __init__(self, model_name: str = "htdemucs", device: str = "auto"):
        self.model_name = model_name
        self.device = device
        self._model = None  # lazy

    def _load_model(self):
        if self._model is not None:
            return self._model

        # Deferred imports so the rest of the app can run without demucs.
        import torch
        from demucs.pretrained import get_model

        if self.device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info("Loading Demucs model %r on %s", self.model_name, self.device)

        model = get_model(self.model_name)
        model.to(self.device)
        model.eval()
        self._model = model
        return model

    def is_available(self) -> tuple[bool, str]:
        try:
            import torch  # noqa: F401
            from demucs.pretrained import get_model  # noqa: F401
            return True, "demucs available"
        except ImportError as e:
            return False, (
                f"Demucs not installed ({e}). "
                "Install with: pip install -r requirements-ai.txt"
            )

    def separate(
        self,
        source: AudioSource,
        output_dir: Path,
        progress: Optional[ProgressCb] = None,
    ) -> list[Stem]:
        import numpy as np
        import soundfile as sf
        import torch

        if not source.path or not source.path.exists():
            raise FileNotFoundError(f"Source audio missing: {source.path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(0.05, "Loading model")
        model = self._load_model()

        if progress:
            progress(0.15, "Reading audio")
        audio, sr = self._read_audio(source.path)

        if sr != model.samplerate:
            audio = self._resample_audio(audio, sr, model.samplerate)
            sr = model.samplerate

        # Demucs expects (channels, samples), batched.
        wav = torch.from_numpy(np.ascontiguousarray(audio.T))
        wav = wav.to(self.device).unsqueeze(0)

        if progress:
            progress(0.25, "Separating stems (this can take a while)")
        with torch.no_grad():
            sources = self._apply_model(model, wav)
        sources = sources.squeeze(0).cpu()

        stems: list[Stem] = []
        for i, name in enumerate(model.sources):
            stem_type = _DEMUCS_NAME_MAP.get(name, StemType.OTHER)
            out_path = output_dir / f"{stem_type.value}.wav"
            stem_audio = np.ascontiguousarray(sources[i].transpose(0, 1).numpy())
            sf.write(str(out_path), stem_audio, sr)
            stem = Stem(
                source_id=source.id,
                stem_type=stem_type,
                path=out_path,
                sample_rate=sr,
                channels=stem_audio.shape[1],
                duration_samples=stem_audio.shape[0],
            )
            stems.append(stem)
            log.info("Wrote stem %s -> %s", stem_type.value, out_path)
            if progress:
                frac = 0.25 + 0.7 * (i + 1) / len(model.sources)
                progress(frac, f"Saved {stem_type.value}")

        if progress:
            progress(1.0, "Done")
        return stems

    def _apply_model(self, model, wav):
        from demucs.apply import apply_model

        return apply_model(model, wav, shifts=1, overlap=0.25, progress=False)

    def _read_audio(self, path: Path):
        import numpy as np
        import soundfile as sf

        audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if audio.shape[1] == 1:
            audio = np.repeat(audio, 2, axis=1)
        elif audio.shape[1] > 2:
            log.warning(
                "Source has %d channels; downmixing to stereo for Demucs",
                audio.shape[1],
            )
            mono = audio.mean(axis=1, dtype=np.float32)
            audio = np.repeat(mono[:, None], 2, axis=1)
        return np.ascontiguousarray(audio, dtype=np.float32), sr

    def _resample_audio(self, audio, src_sr: int, dst_sr: int):
        from scipy.signal import resample_poly

        factor = gcd(src_sr, dst_sr)
        up = dst_sr // factor
        down = src_sr // factor
        resampled = resample_poly(audio, up, down, axis=0)
        return resampled.astype(audio.dtype, copy=False)


class BandSplitSeparator(Separator):
    """
    Fallback separator that splits the source into 3 frequency bands and
    labels them as drums (transients/highs), bass (lows), other (mids).

    This is NOT real source separation - it is just a band split. But it:
      - produces 3 distinct stem files
      - lets the full downstream pipeline (analyzer, slicer, pad assigner)
        run and be tested without torch / demucs installed
      - sounds vaguely musical on simple material (the bass band really is
        the bass, the high band is mostly cymbals/hats)

    Use DemucsSeparator for real results. Use this for smoke testing,
    CI, or environments without GPU/torch.
    """

    def __init__(self, low_cut_hz: float = 200.0, high_cut_hz: float = 4000.0):
        self.low_cut_hz = low_cut_hz
        self.high_cut_hz = high_cut_hz

    def separate(self, source, output_dir, progress=None):
        import numpy as np
        import soundfile as sf
        from scipy.signal import butter, sosfiltfilt

        output_dir.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(0.05, "Reading audio")
        data, sr = sf.read(str(source.path), dtype="float32", always_2d=True)

        if progress:
            progress(0.2, "Splitting low band (bass)")
        sos_low = butter(4, self.low_cut_hz, btype="low", fs=sr, output="sos")
        bass = sosfiltfilt(sos_low, data, axis=0).astype(np.float32)

        if progress:
            progress(0.45, "Splitting high band (drums)")
        sos_high = butter(4, self.high_cut_hz, btype="high", fs=sr, output="sos")
        drums = sosfiltfilt(sos_high, data, axis=0).astype(np.float32)

        if progress:
            progress(0.7, "Splitting mid band (other)")
        sos_band = butter(
            4,
            [self.low_cut_hz, self.high_cut_hz],
            btype="band",
            fs=sr,
            output="sos",
        )
        other = sosfiltfilt(sos_band, data, axis=0).astype(np.float32)

        stems_data = [
            (StemType.BASS, bass),
            (StemType.DRUMS, drums),
            (StemType.OTHER, other),
        ]
        out_stems: list[Stem] = []
        for i, (stype, audio) in enumerate(stems_data):
            out_path = output_dir / f"{stype.value}.wav"
            sf.write(str(out_path), audio, sr)
            out_stems.append(
                Stem(
                    source_id=source.id,
                    stem_type=stype,
                    path=out_path,
                    sample_rate=sr,
                    channels=audio.shape[1],
                    duration_samples=audio.shape[0],
                )
            )
            if progress:
                progress(0.7 + 0.1 * (i + 1), f"Wrote {stype.value}")

        if progress:
            progress(1.0, "Band split complete")
        return out_stems

    def is_available(self) -> tuple[bool, str]:
        try:
            import scipy.signal  # noqa: F401
            return True, "band split available"
        except ImportError as e:
            return False, f"scipy not installed: {e}"


# Backwards compat alias - old code references DummySeparator
class DummySeparator(BandSplitSeparator):
    """Deprecated: use BandSplitSeparator. Kept for import compatibility."""

    pass
