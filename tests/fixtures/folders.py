"""Synthetic input folders for import tests (docs/SPEC.md 16.2).

Every builder writes into the directory it is given (a pytest tmp dir); no
audio file is ever written inside the repository. Signals are deterministic
(seeded) short tones and noise.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import lfilter

# Suno Studio multitrack export order (numbers 1..12).
SUNO_PARTS = ["Woodwinds", "Brass", "FX", "Synth", "Strings", "Percussion", "Keyboard", "Guitar",
              "Bass", "Drums", "Backing Vocals", "Vocals"]
SUNO_ROLES = {"Woodwinds": "woodwinds", "Brass": "brass", "FX": "fx", "Synth": "synth",
              "Strings": "strings", "Percussion": "percussion", "Keyboard": "keyboard",
              "Guitar": "guitar", "Bass": "bass", "Drums": "drums",
              "Backing Vocals": "backing_vocals", "Vocals": "vocals"}

# File names produced by make_mismatched_folder and what each one exercises.
MISMATCHED = {
    "Vocals.wav": "reference 48 kHz stem",
    "Drums.wav": "48 kHz stem",
    "Bass.wav": "44.1 kHz stem (rate mismatch)",
    "Guitar.wav": "0.2 s shorter (length warning)",
    "Synth.wav": "1.0 s shorter (length reject)",
    "FX.wav": "all zeros (silence reject)",
    "Keys.wav": "hard clipped, PCM_24 (clipping warning, depth mismatch)",
    "Perc.wav": "starts with a step (head click warning)",
}


def _fade_in(x: np.ndarray, sr: int, ms: float = 10.0) -> np.ndarray:
    n = min(len(x), int(sr * ms / 1000.0))
    if n > 0:
        x[:n] *= np.linspace(0.0, 1.0, n, endpoint=False)[:, None]
    return x


def stem_signal(index: int, sr: int, seconds: float, *, amp: float = 0.05, seed: int = 1234,
                channels: int = 2) -> np.ndarray:
    """Deterministic stereo stem: two partials plus a little noise, faded in."""
    n = int(round(sr * seconds))
    rng = np.random.default_rng(seed + index)
    t = np.arange(n) / sr
    f0 = 110.0 * (1.0 + 0.37 * index)
    mono = np.sin(2 * np.pi * f0 * t) + 0.5 * np.sin(2 * np.pi * 2.01 * f0 * t + index)
    x = np.empty((n, channels))
    for c in range(channels):
        x[:, c] = mono * (1.0 - 0.2 * c) + 0.2 * rng.standard_normal(n)
    x *= amp / max(np.max(np.abs(x)), 1e-12)
    return _fade_in(x, sr)


def _write(path: Path, x: np.ndarray, sr: int, subtype: str) -> Path:
    sf.write(str(path), x, sr, subtype=subtype, format="WAV")
    return path


def make_suno_export(dir: Path | str, *, n_stems: int = 12, sr: int = 48000, seconds: float = 3.0,
                     title: str = "テスト 曲 (Mix)", fullmix: bool = True, subtype: str = "FLOAT",
                     parts: list[str] | None = None, seed: int = 1234) -> Path:
    """Folder shaped like an unpacked Suno Studio multitrack export.

    Stems are "<n> <Part>.wav" numbered 1..N. With n_stems < 12 the last
    n_stems parts of the Suno order are used, so numbers differ from the
    12-stem layout (roles must come from names). The "0 <title>.wav" full mix
    is deliberately NOT the exact stem sum (x0.9 plus a gentle low-pass blend),
    like a real Suno export.
    """
    d = Path(dir)
    d.mkdir(parents=True, exist_ok=True)
    if parts is None:
        if not 1 <= n_stems <= len(SUNO_PARTS):
            raise ValueError("n_stems must be 1..12 when parts is not given")
        parts = SUNO_PARTS[len(SUNO_PARTS) - n_stems:]
    total = None
    for i, part in enumerate(parts, start=1):
        x = stem_signal(SUNO_PARTS.index(part) if part in SUNO_PARTS else 20 + i, sr, seconds, seed=seed)
        _write(d / f"{i} {part}.wav", x, sr, subtype)
        total = x.copy() if total is None else total + x
    if fullmix and total is not None:
        a = 0.3  # gentle one-pole low-pass, blended in as a "slight EQ"
        smooth = lfilter([1 - a], [1, -a], total, axis=0)
        mix = 0.9 * (0.8 * total + 0.2 * smooth)
        _write(d / f"0 {title}.wav", mix, sr, subtype)
    return d


def make_mismatched_folder(dir: Path | str, *, seconds: float = 3.0, seed: int = 99) -> Path:
    """Generic stem folder with rate/length/depth mismatches and broken stems.

    See MISMATCHED for the files. 7 files at 48 kHz and 1 at 44.1 kHz, so the
    majority (project) rate is 48 kHz. Longest length is `seconds`.
    """
    d = Path(dir)
    d.mkdir(parents=True, exist_ok=True)
    sr = 48000
    _write(d / "Vocals.wav", stem_signal(0, sr, seconds, seed=seed), sr, "FLOAT")
    _write(d / "Drums.wav", stem_signal(1, sr, seconds, seed=seed), sr, "FLOAT")
    _write(d / "Bass.wav", stem_signal(2, 44100, seconds, seed=seed), 44100, "FLOAT")
    _write(d / "Guitar.wav", stem_signal(3, sr, seconds - 0.2, seed=seed), sr, "FLOAT")
    _write(d / "Synth.wav", stem_signal(4, sr, seconds - 1.0, seed=seed), sr, "FLOAT")
    _write(d / "FX.wav", np.zeros((int(sr * seconds), 2)), sr, "FLOAT")
    n = int(sr * seconds)
    t = np.arange(n) / sr
    clipped = np.clip(1.5 * np.sin(2 * np.pi * 220.0 * t), -1.0, 1.0)
    _write(d / "Keys.wav", _fade_in(np.column_stack([clipped, clipped]), sr), sr, "PCM_24")
    perc = stem_signal(5, sr, seconds, amp=0.05, seed=seed)
    perc[0:int(0.02 * sr)] += 0.5  # 20 ms DC step at the very start: an audible click
    _write(d / "Perc.wav", perc, sr, "FLOAT")
    return d
