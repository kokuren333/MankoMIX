"""Internal oversampled peak detector (kept inside dsp/ so dsp does not depend on core).

The signal is upsampled by an integer factor (>= 4, BS.1770 style) with a
Kaiser-windowed polyphase FIR, block by block with overlap so memory stays
bounded for full-length songs. ``peak_per_sample`` returns, for every input
sample n, the largest absolute oversampled value inside [n, n+1) across all
channels (stereo-linked).
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy import signal

_BLOCK = 1 << 16
_TAPS_PER_PHASE = 32
_BETA = 8.0
TARGET_RATE = 192000


def default_factor(sr: int | None, minimum: int = 4) -> int:
    """Oversampling factor: at least ``minimum`` and an effective rate of at least 192 kHz."""
    if not sr:
        return minimum
    return max(int(minimum), -(-TARGET_RATE // int(sr)))


def detector_factor(sr: int | None, requested: int) -> int:
    """Smallest multiple of the BS.1770-style factor (>= 4x, >= 192 kHz) that is >= ``requested``.

    Being a multiple means the detector grid contains every point a standard
    meter at the base factor evaluates, so with the same interpolator the
    limiter never reads below such a meter.
    """
    base = default_factor(sr, 4)
    k = max(1, -(-int(requested) // base))
    return base * k


@lru_cache(maxsize=8)
def _upsample_fir(factor: int) -> np.ndarray:
    """Kaiser-windowed sinc interpolator with its cutoff at the input Nyquist (Nyquist filter).

    Phase 0 passes the input samples unchanged; the other phases interpolate.
    The window spans _TAPS_PER_PHASE input samples whatever the factor, so the
    grid of factor k*f contains the grid of factor f exactly.
    """
    half = factor * _TAPS_PER_PHASE // 2
    n = np.arange(-half, half + 1)
    h = np.sinc(n / factor) * np.kaiser(2 * half + 1, _BETA)
    h[(n % factor == 0) & (n != 0)] = 0.0
    h = h / factor  # resample_poly multiplies by ``up`` itself
    h.setflags(write=False)
    return h


def _as2d(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return x[:, None] if x.ndim == 1 else x


def peak_per_sample(x: np.ndarray, factor: int = 4) -> np.ndarray:
    """Max |oversampled value| in each input sample interval [n, n+1), linked across channels."""
    x = _as2d(x)
    n = x.shape[0]
    out = np.zeros(n, dtype=np.float64)
    if n == 0:
        return out
    if factor <= 1:
        return np.max(np.abs(x), axis=1)
    h = _upsample_fir(factor)
    pad = _TAPS_PER_PHASE  # input samples of context on each side (> half filter length)
    for start in range(0, n, _BLOCK):
        stop = min(n, start + _BLOCK)
        lo, hi = start - pad, stop + pad
        seg = np.zeros((hi - lo, x.shape[1]))
        s_lo, s_hi = max(lo, 0), min(hi, n)
        seg[s_lo - lo:s_hi - lo] = x[s_lo:s_hi]
        up = signal.resample_poly(seg, factor, 1, axis=0, window=h.copy())
        core = up[pad * factor:(pad + stop - start) * factor]
        core = np.max(np.abs(core), axis=1)
        out[start:stop] = core.reshape(stop - start, factor).max(axis=1)
    # the original sample itself is part of the interval as well
    np.maximum(out, np.max(np.abs(x), axis=1), out=out)
    return out


def true_peak_linear(x: np.ndarray, factor: int = 4) -> float:
    x = _as2d(x)
    if x.size == 0:
        return 0.0
    return float(np.max(peak_per_sample(x, factor)))


def true_peak_dbtp(x: np.ndarray, sr: int | None = None, factor: int | None = None) -> float:
    """True peak in dBTP. Default factor: >= 4x and >= 192 kHz effective rate."""
    tp = true_peak_linear(x, factor or default_factor(sr))
    return float(20.0 * np.log10(tp)) if tp > 0 else float("-inf")


def sample_peak_dbfs(x: np.ndarray) -> float:
    x = np.asarray(x)
    if x.size == 0:
        return float("-inf")
    p = float(np.max(np.abs(x)))
    return float(20.0 * np.log10(p)) if p > 0 else float("-inf")
