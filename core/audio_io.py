"""Audio file I/O shared by every module.

Reading never modifies the source file (S-11). Data is returned as float64
arrays shaped (frames, channels). Formats libsndfile understands are read
directly; anything else is decoded through an external ffmpeg process
(SPEC 13.3: ffmpeg is called, never linked). Nothing here resamples.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .errors import EnvironmentProblem, InputError

LOSSLESS_EXT = {".wav", ".aif", ".aiff", ".flac"}
LOSSY_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".opus"}
AUDIO_EXT = LOSSLESS_EXT | LOSSY_EXT


@dataclass
class AudioInfo:
    sample_rate: int
    channels: int
    frames: int
    duration_s: float
    container: str        # e.g. "wav", "flac", "aiff", "mp3"
    subtype: str          # e.g. "PCM_24", "FLOAT", "unknown"
    lossy: bool

    def to_dict(self) -> dict:
        return asdict(self)


def is_audio_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXT


def info(path: str | Path) -> AudioInfo:
    p = Path(path)
    if not p.is_file():
        raise InputError(f"audio file not found: {p.name}")
    lossy = p.suffix.lower() in LOSSY_EXT
    try:
        i = sf.info(str(p))
        return AudioInfo(int(i.samplerate), int(i.channels), int(i.frames),
                         float(i.frames) / float(i.samplerate),
                         (i.format or p.suffix.lstrip(".")).lower(), str(i.subtype or "unknown"), lossy)
    except Exception:
        data, sr = _ffmpeg_decode(p)
        return AudioInfo(sr, data.shape[1], data.shape[0], data.shape[0] / sr,
                         p.suffix.lstrip(".").lower(), "unknown", lossy)


def read(path: str | Path, *, dtype: str = "float64") -> tuple[np.ndarray, int]:
    """Return (data[frames, channels], sample_rate). Never resamples."""
    p = Path(path)
    if not p.is_file():
        raise InputError(f"audio file not found: {p.name}")
    try:
        data, sr = sf.read(str(p), dtype=dtype, always_2d=True)
        return data, int(sr)
    except Exception:
        data, sr = _ffmpeg_decode(p)
        return data.astype(dtype, copy=False), sr


def write(path: str | Path, data: np.ndarray, sample_rate: int, *, subtype: str = "FLOAT",
          format: str | None = None) -> None:
    """Write audio. subtype: FLOAT, DOUBLE, PCM_16, PCM_24.

    For <= 2 channels with PCM subtypes, libsndfile writes WAVE_FORMAT_PCM
    (SPEC 5.3 requires plain PCM for 16/24-bit WAV deliveries).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(data)
    if arr.ndim == 1:
        arr = arr[:, None]
    fmt = format or {".wav": "WAV", ".flac": "FLAC", ".aif": "AIFF", ".aiff": "AIFF"}.get(p.suffix.lower(), "WAV")
    sf.write(str(p), arr, int(sample_rate), subtype=subtype, format=fmt)


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def _ffmpeg_decode(p: Path) -> tuple[np.ndarray, int]:
    exe = ffmpeg_path()
    if exe is None:
        raise EnvironmentProblem(f"cannot decode {p.name}: ffmpeg not found on PATH")
    probe = subprocess.run([exe, "-hide_banner", "-i", str(p)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    sr, ch = 48000, 2
    m = re.search(r"Audio:.*?(\d+) Hz, ([^,]+)", probe.stderr)
    if m:
        sr = int(m.group(1))
        layout = m.group(2).strip()
        n = re.match(r"(\d+)", layout)
        ch = 1 if layout.startswith("mono") else 2 if layout.startswith("stereo") else int(n.group(1)) if n else 2
    out = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-i", str(p), "-f", "f32le",
                          "-acodec", "pcm_f32le", "-ac", str(ch), "-ar", str(sr), "-"],
                         capture_output=True)
    if out.returncode != 0:
        raise InputError(f"cannot decode {p.name}: {out.stderr.decode('utf-8', 'replace')[:200]}")
    data = np.frombuffer(out.stdout, dtype="<f4").astype(np.float64).reshape(-1, ch)
    return data, sr
