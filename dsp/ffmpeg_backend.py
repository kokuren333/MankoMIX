"""ffmpeg backend: the user's ffmpeg, called only as an external process (SPEC 3.2, 13.3).

Only features present in LGPL builds are used on the standard path: the
native ``aac`` encoder, ``libmp3lame`` (LGPL), ``libopus`` / ``libvorbis``
(BSD) with the native encoders as fallback, and ``aresample`` with the
built-in swr resampler. No rubberband, no libfdk, no soxr.

Temporary files live in a private temp directory and ffmpeg is run with that
directory as cwd and bare file names, so neither stderr nor our exception
messages carry absolute paths.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

_TIMEOUT_MIN_S = 60.0

# codec -> (candidate encoders in order of preference, file extension, extra args per encoder)
CODECS: dict[str, dict] = {
    "aac": {"encoders": ["aac"], "ext": ".m4a"},
    "opus": {"encoders": ["libopus", "opus"], "ext": ".opus"},
    "mp3": {"encoders": ["libmp3lame"], "ext": ".mp3"},
    "ogg_vorbis": {"encoders": ["libvorbis", "vorbis"], "ext": ".ogg"},
}
_EXPERIMENTAL = {"opus", "vorbis"}
_OPUS_RATES = (48000, 24000, 16000, 12000, 8000)


class FFmpegError(RuntimeError):
    pass


def _exe() -> str | None:
    return shutil.which("ffmpeg")


def available() -> bool:
    return _exe() is not None


def _run(args: list[str], *, input: bytes | None = None, timeout: float = _TIMEOUT_MIN_S,
         cwd: str | None = None, text: bool = False) -> subprocess.CompletedProcess:
    exe = _exe()
    if exe is None:
        raise FFmpegError("ffmpeg not found on PATH")
    kw: dict = {"capture_output": True, "timeout": timeout, "cwd": cwd}
    if text:
        kw.update(text=True, encoding="utf-8", errors="replace")
    else:
        kw["input"] = input
    try:
        return subprocess.run([exe, "-hide_banner", *args], **kw)
    except subprocess.TimeoutExpired as e:
        raise FFmpegError(f"ffmpeg timed out after {e.timeout:.0f} s") from None


def _stderr_tail(proc: subprocess.CompletedProcess, n: int = 300) -> str:
    err = proc.stderr
    if isinstance(err, bytes):
        err = err.decode("utf-8", errors="replace")
    return (err or "").strip()[-n:]


def classify_build(configuration: str) -> str:
    """'nonfree' if --enable-nonfree, 'gpl' if --enable-gpl, otherwise 'lgpl'."""
    flags = set(configuration.split())
    if "--enable-nonfree" in flags:
        return "nonfree"
    if "--enable-gpl" in flags:
        return "gpl"
    return "lgpl"


def parse_version_output(text: str) -> dict:
    version = None
    m = re.search(r"ffmpeg version (\S+)", text)
    if m:
        version = m.group(1)
    conf = ""
    m = re.search(r"^\s*configuration:(.*)$", text, flags=re.M)
    if m:
        conf = m.group(1).strip()
    flags = conf.split()
    return {
        "version": version,
        "configuration": conf,
        "build": classify_build(conf),
        "version3": "--enable-version3" in flags,
        "gpl_only_components": sorted(f for f in flags if f in {
            "--enable-librubberband", "--enable-libx264", "--enable-libx265", "--enable-libxvid",
            "--enable-libvidstab", "--enable-frei0r", "--enable-libfdk-aac"}),
    }


@lru_cache(maxsize=1)
def version_info() -> dict | None:
    """{version, configuration, build: lgpl|gpl|nonfree, ...} or None when ffmpeg is missing."""
    if not available():
        return None
    proc = _run(["-version"], text=True, timeout=30)
    return parse_version_output(proc.stdout or "")


def parse_encoders_output(text: str) -> set[str]:
    out: set[str] = set()
    started = False
    for line in text.splitlines():
        if not started:
            if line.strip().startswith("------"):
                started = True
            continue
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6:
            out.add(parts[1])
    return out


@lru_cache(maxsize=1)
def _encoders_cached() -> frozenset[str]:
    if not available():
        return frozenset()
    proc = _run(["-encoders"], text=True, timeout=30)
    return frozenset(parse_encoders_output(proc.stdout or ""))


def encoders() -> set[str]:
    """Names of the encoders the user's ffmpeg build offers (empty when ffmpeg is missing)."""
    return set(_encoders_cached())


def pick_encoder(codec: str, available_encoders=None) -> str | None:
    if codec not in CODECS:
        raise ValueError(f"unknown codec {codec!r}; known: {sorted(CODECS)}")
    have = encoders() if available_encoders is None else set(available_encoders)
    for enc in CODECS[codec]["encoders"]:
        if enc in have:
            return enc
    return None


def _as2d(x) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return x[:, None] if x.ndim == 1 else x


def estimate_delay(ref: np.ndarray, dec: np.ndarray, sr: int, *, seconds: float = 5.0,
                   max_lag_s: float = 0.25) -> int:
    """Lag (samples) of ``dec`` relative to ``ref`` from cross-correlation of the first seconds."""
    from scipy import signal

    n = min(ref.shape[0], int(seconds * sr))
    a = ref[:n].mean(axis=1)
    max_lag = int(max_lag_s * sr)
    b = dec[: n + max_lag].mean(axis=1)
    if n == 0 or not np.any(a) or not np.any(b):
        return 0
    c = signal.correlate(b, a, mode="full", method="fft")
    lags = np.arange(-(a.shape[0] - 1), b.shape[0])
    sel = (lags >= -max_lag) & (lags <= max_lag)
    return int(lags[sel][np.argmax(c[sel])])


def _align(dec: np.ndarray, lag: int, n: int) -> np.ndarray:
    if lag > 0:
        dec = dec[lag:]
    elif lag < 0:
        dec = np.concatenate([np.zeros((-lag, dec.shape[1])), dec])
    if dec.shape[0] >= n:
        return dec[:n]
    return np.concatenate([dec, np.zeros((n - dec.shape[0], dec.shape[1]))])


def encode_decode_roundtrip(x, sr: int, codec: str, bitrate: str | int = "256k", *,
                            return_info: bool = False):
    """Encode with the build's encoder, decode back to float64 at ``sr`` and align to ``x``.

    Returns (decoded, sr) -- or (decoded, sr, info) with ``return_info`` -- or
    None when ffmpeg or a suitable encoder is missing (SPEC 13.3: record as
    "not performed").
    """
    import soundfile as sf

    x = _as2d(x)
    enc = pick_encoder(codec)
    if enc is None:
        return None
    n, ch = x.shape
    br = f"{int(bitrate) // 1000}k" if isinstance(bitrate, int) else str(bitrate)
    timeout = max(_TIMEOUT_MIN_S, 6.0 * n / sr)
    enc_args = ["-c:a", enc, "-b:a", br]
    if enc in _EXPERIMENTAL:
        enc_args += ["-strict", "experimental"]
    if codec == "opus" and sr not in _OPUS_RATES:
        enc_args += ["-ar", "48000"]
    if codec == "mp3" and ch > 2:
        return None
    out_name = "enc" + CODECS[codec]["ext"]
    with tempfile.TemporaryDirectory(prefix="mmx_ff_") as td:
        sf.write(str(Path(td) / "in.wav"), x.astype(np.float32), int(sr), subtype="FLOAT", format="WAV")
        p1 = _run(["-nostdin", "-y", "-v", "error", "-i", "in.wav", *enc_args, out_name],
                  cwd=td, timeout=timeout)
        if p1.returncode != 0:
            raise FFmpegError(f"{codec} encode with {enc} failed: {_stderr_tail(p1)}")
        p2 = _run(["-nostdin", "-v", "error", "-i", out_name, "-f", "f64le", "-acodec", "pcm_f64le",
                   "-ac", str(ch), "-ar", str(int(sr)), "pipe:1"], cwd=td, timeout=timeout)
        if p2.returncode != 0:
            raise FFmpegError(f"{codec} decode failed: {_stderr_tail(p2)}")
        enc_bytes = (Path(td) / out_name).stat().st_size
    dec = np.frombuffer(p2.stdout, dtype="<f8").reshape(-1, ch).astype(np.float64)
    lag = estimate_delay(x, dec, sr)
    aligned = _align(dec, lag, n)
    if not return_info:
        return aligned, int(sr)
    info = {"codec": codec, "encoder": enc, "bitrate": br, "delay_samples": lag,
            "decoded_frames": int(dec.shape[0]), "encoded_bytes": int(enc_bytes),
            "ffmpeg": (version_info() or {}).get("version")}
    return aligned, int(sr), info


def resample(x, sr_in: int, sr_out: int) -> np.ndarray:
    """Resample through ffmpeg's aresample (swr, LGPL). Output length = ceil(n * sr_out / sr_in)."""
    x = _as2d(x)
    n, ch = x.shape
    if sr_in == sr_out:
        return x.copy()
    want = -(-n * int(sr_out) // int(sr_in))
    timeout = max(_TIMEOUT_MIN_S, 6.0 * n / sr_in)
    af = (f"aresample={int(sr_out)}:resampler=swr:filter_size=64:phase_shift=10:cutoff=0.97:"
          "dither_method=0")
    proc = _run(["-nostdin", "-v", "error", "-f", "f64le", "-ar", str(int(sr_in)), "-ac", str(ch),
                 "-i", "pipe:0", "-af", af, "-f", "f64le", "-acodec", "pcm_f64le", "pipe:1"],
                input=np.ascontiguousarray(x, dtype="<f8").tobytes(), timeout=timeout)
    if proc.returncode != 0:
        raise FFmpegError(f"aresample failed: {_stderr_tail(proc)}")
    y = np.frombuffer(proc.stdout, dtype="<f8").reshape(-1, ch).astype(np.float64)
    if y.shape[0] >= want:
        return y[:want]
    return np.concatenate([y, np.zeros((want - y.shape[0], ch))])


def resample_step(x: np.ndarray, sr: int, p: dict, **_):
    """Engine adapter with the backend signature (x, sr, params) -> (y, sr_out, stats)."""
    target = int(p["target_sr"])
    if target == sr:
        return x.copy(), sr, {"resampled": False, "from_sr": sr, "to_sr": sr}
    y = resample(x, sr, target)
    vi = version_info() or {}
    return y, target, {"resampled": True, "from_sr": sr, "to_sr": target, "method": "ffmpeg aresample (swr)",
                       "ffmpeg_version": vi.get("version"), "ffmpeg_build": vi.get("build")}


IMPLEMENTATIONS = {"resample": resample_step}
BACKEND = "ffmpeg"
