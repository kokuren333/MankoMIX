"""Small measurements shared by the mastering planner, verifier and report.

These are narrow, self-contained helpers for the master-stage decisions
(S-03, S-04, generic tonal check, listening-point times). The general
measurement vector lives in core/measure/vector.py.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import butter, sosfiltfilt, welch

EPS = 1e-20


def as_stereo(x) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    if a.shape[1] == 1:
        a = np.repeat(a, 2, axis=1)
    return a[:, :2]


def band_filter(x: np.ndarray, sr: int, lo: float | None, hi: float | None, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth band/low/high-pass along axis 0."""
    nyq = sr / 2.0
    if hi is not None and hi >= nyq * 0.98:
        hi = None
    if lo is not None and lo <= 0:
        lo = None
    if lo is None and hi is None:
        return np.asarray(x, dtype=np.float64)
    if lo is None:
        sos = butter(order, hi / nyq, btype="lowpass", output="sos")
    elif hi is None:
        sos = butter(order, lo / nyq, btype="highpass", output="sos")
    else:
        sos = butter(order, [lo / nyq, hi / nyq], btype="bandpass", output="sos")
    return sosfiltfilt(sos, x, axis=0)


def band_energy_ratios(x, sr: int, bands: list[dict]) -> dict:
    """Fraction of total (mid-channel) power in each band (P-07 style)."""
    a = as_stereo(x)
    mid = a.mean(axis=1)
    if mid.size < 256:
        return {b["id"]: None for b in bands}
    f, p = welch(mid, fs=sr, nperseg=min(8192, mid.size))
    total = float(np.sum(p[(f >= 20.0) & (f <= min(20000.0, sr / 2.0))])) + EPS
    out = {}
    for b in bands:
        lo, hi = b["range_hz"]
        m = (f >= lo) & (f < min(hi, sr / 2.0))
        out[b["id"]] = float(np.sum(p[m]) / total)
    return out


def mono_loss_db(x, sr: int, lo: float | None, hi: float | None) -> float | None:
    """Level loss (dB) of the mono fold (L+R)/2 relative to the stereo mean power, in a band."""
    a = band_filter(as_stereo(x), sr, lo, hi)
    e_st = float(np.mean(a[:, 0] ** 2 + a[:, 1] ** 2) / 2.0)
    if e_st < 1e-12:
        return None
    e_mono = float(np.mean(((a[:, 0] + a[:, 1]) / 2.0) ** 2))
    return float(10.0 * math.log10(e_st / max(e_mono, EPS)))


def windowed_correlation(x, sr: int, lo: float | None, hi: float | None, window_s: float,
                         silence_db: float = -60.0) -> np.ndarray:
    """L/R correlation per non-overlapping window in a band. Silent windows are nan."""
    a = band_filter(as_stereo(x), sr, lo, hi)
    n = max(1, int(round(window_s * sr)))
    k = a.shape[0] // n
    if k == 0:
        return np.array([], dtype=float)
    blk = a[: k * n].reshape(k, n, 2)
    l, r = blk[:, :, 0], blk[:, :, 1]
    ll, rr, lr = np.sum(l * l, axis=1), np.sum(r * r, axis=1), np.sum(l * r, axis=1)
    rms_db = 10.0 * np.log10((ll + rr) / (2.0 * n) + EPS)
    corr = lr / np.sqrt(ll * rr + EPS)
    corr[rms_db < silence_db] = np.nan
    return corr


def negative_persistence(corr: np.ndarray, window_s: float, threshold: float = 0.0) -> dict:
    """Longest run (s) and fraction of windows with correlation below threshold."""
    valid = corr[np.isfinite(corr)]
    if valid.size == 0:
        return {"longest_run_s": 0.0, "negative_fraction": 0.0, "windows": 0, "min_corr": None}
    neg = np.isfinite(corr) & (corr < threshold)
    longest = run = 0
    for v in neg:
        run = run + 1 if v else 0
        longest = max(longest, run)
    return {"longest_run_s": float(longest * window_s),
            "negative_fraction": float(np.sum(neg) / valid.size),
            "windows": int(valid.size),
            "min_corr": float(np.min(valid))}


def section_times(x, sr: int) -> dict:
    """Start times (s) of the loudest and quietest 3 s regions from short-term loudness."""
    from .measure import loudness as _ld

    st = np.asarray(_ld.short_term(x, sr), dtype=float)
    dur = as_stereo(x).shape[0] / float(sr)
    out = {"duration_s": dur, "loudest_start_s": 0.0, "quietest_start_s": None,
           "loudest_lufs": None, "quietest_lufs": None}
    if st.size == 0:
        return out
    hop = 0.1
    ok = np.isfinite(st) & (st > -70.0)
    if not np.any(ok):
        return out
    i_max = int(np.nanargmax(np.where(ok, st, -np.inf)))
    i_min = int(np.nanargmin(np.where(ok, st, np.inf)))
    # short_term value i covers the 3 s window [i * hop, i * hop + 3 s) (loudness.short_term).
    def start(i: int) -> float:
        return float(max(0.0, min(dur, i * hop)))
    out.update(loudest_start_s=round(start(i_max), 1), quietest_start_s=round(start(i_min), 1),
               loudest_lufs=float(st[i_max]), quietest_lufs=float(st[i_min]))
    return out


def sone_ratio(db: float) -> float:
    """Perceived loudness ratio for a level difference (about 2x per +10 dB)."""
    return float(2.0 ** (float(db) / 10.0))


def finite_or_none(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None
