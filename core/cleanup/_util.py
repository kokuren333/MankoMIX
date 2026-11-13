"""Shared helpers for the cleanup stage: policy access, STFT, FFT band tools.

All helpers are deterministic: fixed windows, fixed hops, no randomness and
no data-dependent thread scheduling.
"""

from __future__ import annotations

import copy
import json
import math
from typing import Any

import numpy as np
from scipy import fft as sfft

from ..errors import InputError

EPS = 1e-20
FLOOR_DB = -300.0


# --- policy -------------------------------------------------------------------

def v(node: Any) -> Any:
    """Return node["value"] for {"value": ...} entries, else node itself."""
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def deep_merge(base: dict, extra: dict | None) -> dict:
    """Recursively merge ``extra`` into a copy of ``base``.

    A scalar in ``extra`` that replaces a {"value": ...} entry only replaces
    the value (the note and confidence stay).
    """
    out = copy.deepcopy(base)
    if not extra:
        return out
    for key, val in extra.items():
        cur = out.get(key)
        if isinstance(cur, dict) and isinstance(val, dict):
            out[key] = deep_merge(cur, val)
        elif isinstance(cur, dict) and "value" in cur and not isinstance(val, dict):
            cur = dict(cur)
            cur["value"] = copy.deepcopy(val)
            out[key] = cur
        else:
            out[key] = copy.deepcopy(val)
    return out


def load_policy(overrides: dict | None = None) -> dict:
    """knowledge/cleanup_policy.json, optionally deep-merged with overrides."""
    try:
        from ..config import load_knowledge
        base = load_knowledge("cleanup_policy")
    except Exception:  # pragma: no cover - fallback when config is unavailable
        from mankomix import repo_data_root
        with open(repo_data_root() / "knowledge" / "cleanup_policy.json", encoding="utf-8") as fh:
            base = json.load(fh)
    return deep_merge(base, overrides)


def band_by_id(policy: dict, band_id: str) -> dict:
    for b in policy["bands"]:
        if b["id"] == band_id:
            return b
    raise KeyError(band_id)


# --- arrays -------------------------------------------------------------------

def as_2d(x) -> tuple[np.ndarray, bool]:
    """Return (float64 [frames, channels], was_1d)."""
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        return a[:, None], True
    if a.ndim != 2:
        raise InputError(f"audio must be 1-D or 2-D [frames, channels], got shape {a.shape}")
    if a.shape[1] > 64 and a.shape[0] <= 64:
        raise InputError(f"audio looks like [channels, frames] (shape {a.shape}); expected [frames, channels]")
    if not np.all(np.isfinite(a)):
        raise InputError("audio contains NaN or infinity")
    return a, False


def restore_shape(a2d: np.ndarray, was_1d: bool) -> np.ndarray:
    return a2d[:, 0] if was_1d else a2d


def mid_side(x2d: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
    """Mid (mean of channels) and, for 2 channels, side = (L - R) / 2."""
    if x2d.shape[1] == 2:
        return 0.5 * (x2d[:, 0] + x2d[:, 1]), 0.5 * (x2d[:, 0] - x2d[:, 1])
    return x2d.mean(axis=1), None


def db10(p: float) -> float:
    p = float(p)
    if not math.isfinite(p) or p <= 0.0:
        return FLOOR_DB
    return max(FLOOR_DB, 10.0 * math.log10(p))


def db20(a: float) -> float:
    a = float(a)
    if not math.isfinite(a) or a <= 0.0:
        return FLOOR_DB
    return max(FLOOR_DB, 20.0 * math.log10(a))


def rnd(val: Any, nd: int = 3) -> Any:
    """Round floats for reports; map non-finite to None."""
    if val is None:
        return None
    if isinstance(val, (bool, np.bool_)):
        return bool(val)
    if isinstance(val, (int, np.integer)):
        return int(val)
    f = float(val)
    if not math.isfinite(f):
        return None
    return round(f, nd)


# --- STFT ---------------------------------------------------------------------

def stft_params(sr: float, policy: dict) -> tuple[int, int]:
    win_s = float(v(policy["stft"]["window_s"]))
    overlap = int(v(policy["stft"]["overlap"]))
    n_fft = 1 << max(6, int(math.ceil(math.log2(max(64.0, win_s * sr)))))
    hop = n_fft // overlap
    return n_fft, hop


def _hann(n: int) -> np.ndarray:
    # periodic Hann: sums to a constant under 4x overlap (squared: 1.5)
    return (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)).astype(np.float32)


def stft(x1d: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    """Complex64 STFT [frames, bins]. The signal is zero-padded by n_fft on
    both sides so every input sample is fully covered by overlapping frames."""
    n = x1d.shape[0]
    total = n + 2 * n_fft
    rem = (total - n_fft) % hop
    if rem:
        total += hop - rem
    xp = np.zeros(total, dtype=np.float32)
    xp[n_fft:n_fft + n] = x1d
    frames = np.lib.stride_tricks.sliding_window_view(xp, n_fft)[::hop]
    w = _hann(n_fft)
    return sfft.rfft(frames * w, axis=1).astype(np.complex64, copy=False)


def istft(spec: np.ndarray, n_fft: int, hop: int, length: int) -> np.ndarray:
    """Weighted overlap-add inverse of :func:`stft` (float64 output)."""
    t = spec.shape[0]
    w = _hann(n_fft).astype(np.float64)
    frames = sfft.irfft(spec, n=n_fft, axis=1).astype(np.float64) * w
    r = n_fft // hop
    chunks = np.zeros((t + r - 1, hop))
    wsum = np.zeros((t + r - 1, hop))
    fr = frames.reshape(t, r, hop)
    w2 = (w * w).reshape(r, hop)
    for i in range(r):
        chunks[i:i + t] += fr[:, i, :]
        wsum[i:i + t] += w2[i]
    out = chunks.reshape(-1)
    ws = wsum.reshape(-1)
    out = np.divide(out, ws, out=np.zeros_like(out), where=ws > 1e-8)
    return out[n_fft:n_fft + length]


def stft_freqs(sr: float, n_fft: int) -> np.ndarray:
    return np.arange(n_fft // 2 + 1) * (sr / n_fft)


def power_norm(n_fft: int) -> float:
    """Factor turning sum_k |X_k|^2 of one frame into mean-square (Parseval,
    Hann window, one-sided spectrum)."""
    w = _hann(n_fft).astype(np.float64)
    return 2.0 / (n_fft * float(np.sum(w * w)))


def bin_range(freqs: np.ndarray, lo: float, hi: float) -> slice:
    k0 = int(np.searchsorted(freqs, lo, side="left"))
    k1 = int(np.searchsorted(freqs, hi, side="left"))
    return slice(k0, max(k0, k1))


# --- full-length FFT tools ----------------------------------------------------

def _fft_len(n: int, pad: int) -> int:
    return sfft.next_fast_len(n + pad, real=True)


def _dct_freqs(n: int, sr: float) -> np.ndarray:
    # DCT-II basis k has frequency k * sr / (2 n)
    return np.arange(n) * (sr / (2.0 * n))


def crossover_highpass(sig2d: np.ndarray, sr: float, fc: float, transition: float) -> np.ndarray:
    """Zero-phase high-pass of each channel in the DCT-II domain: gain exactly
    0 at and below fc, raised-cosine rise to exactly 1 at fc + transition.

    The DCT implies an even-symmetric extension at both file edges, so there
    is no wrap-around and no truncation of filter ringing: the DCT spectrum of
    the result is exactly zero at and below fc (to rounding), including for
    events at the very first or last sample."""
    n = sig2d.shape[0]
    f = _dct_freqs(n, sr)
    h = np.zeros_like(f)
    t = max(transition, 1e-9)
    ramp = (f > fc) & (f < fc + t)
    h[ramp] = 0.5 - 0.5 * np.cos(np.pi * (f[ramp] - fc) / t)
    h[f >= fc + t] = 1.0
    out = np.empty_like(sig2d)
    for c in range(sig2d.shape[1]):
        col = sig2d[:, c]
        if not np.any(col):
            out[:, c] = 0.0
            continue
        out[:, c] = sfft.idct(sfft.dct(col, type=2, norm="ortho") * h, type=2, norm="ortho")
    return out


def dct_lowpass(sig2d: np.ndarray, sr: float, fc: float) -> np.ndarray:
    """Brick-wall low-pass in the DCT-II domain (keeps components at or below
    fc). Used for the S-07 null test: the even-symmetric extension keeps the
    file edges from leaking into the low band."""
    n = sig2d.shape[0]
    h = (_dct_freqs(n, sr) <= fc).astype(np.float64)
    out = np.empty_like(sig2d)
    for c in range(sig2d.shape[1]):
        out[:, c] = sfft.idct(sfft.dct(sig2d[:, c], type=2, norm="ortho") * h, type=2, norm="ortho")
    return out


def brickwall_lowpass(sig2d: np.ndarray, sr: float, fc: float) -> np.ndarray:
    """Zero-phase brick-wall low-pass via a zero-padded FFT (keeps bins at or
    below fc). Edge events leak through the zero-padding discontinuity."""
    n = sig2d.shape[0]
    nfft = _fft_len(n, max(int(sr // 2), 4096))
    f = np.arange(nfft // 2 + 1) * (sr / nfft)
    h = (f <= fc).astype(np.float64)
    out = np.empty_like(sig2d)
    for c in range(sig2d.shape[1]):
        out[:, c] = sfft.irfft(sfft.rfft(sig2d[:, c], nfft) * h, nfft)[:n]
    return out


def band_energies(x2d: np.ndarray, sr: float, bands: list[tuple[str, float, float]]) -> dict:
    """Energy (sum of squares over all channels, Parseval) per [lo, hi) band."""
    n = x2d.shape[0]
    nfft = sfft.next_fast_len(max(n, 1), real=True)  # zero padding keeps Parseval
    f = np.arange(nfft // 2 + 1) * (sr / nfft)
    p = np.zeros(f.shape[0])
    for c in range(x2d.shape[1]):
        spec = sfft.rfft(x2d[:, c], nfft)
        p += spec.real ** 2 + spec.imag ** 2
    # one-sided weighting so that bins sum to the time-domain energy
    w = np.full_like(f, 2.0)
    w[0] = 1.0
    if nfft % 2 == 0:
        w[-1] = 1.0
    p *= w / nfft
    out = {}
    for name, lo, hi in bands:
        sel = (f >= lo) & (f < hi)
        out[name] = float(np.sum(p[sel]))
    return out
