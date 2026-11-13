"""Stereo measures: P-05 (band correlation, side ratio), P-06 (mono loss),
and the low-band negative-correlation persistence used by S-03.

Conventions (documented contract):
- L = channel 0, R = channel 1. Extra channels are ignored.
- M = (L + R) / 2, S = (L - R) / 2.
- side_ratio = E_S / (E_M + E_S)   (0 = mono, 0.5 = uncorrelated, 1 = anti-phase)
- mono fold = M. level_change_db = 10*log10(E_M / ((E_L + E_R) / 2)).
  0 dB for identical channels, -3.01 dB for equal uncorrelated channels,
  -inf (reported as null, cancelled=True) for inverted channels.
  mono_loss_db = -level_change_db (positive = level lost when folded).
- Band energies come from the full-length FFT (bands.Spectrum), so values
  are exact over the whole signal.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import butter, sosfiltfilt

from .bands import BANDS_P22, AUDIBLE_RANGE_HZ, Spectrum, clip_bands

MONO_CONVENTION = ("M=(L+R)/2; level_change_db=10*log10(E_M/((E_L+E_R)/2)); "
                   "mono_loss_db=-level_change_db")
_EPS = 1e-20


def _stereo_from_sums(pl: float, pr: float, c: float) -> dict:
    tot = pl + pr
    if tot <= _EPS:
        return {"correlation": None, "side_ratio": None, "level_change_db": None,
                "mono_loss_db": None, "cancelled": False, "silent": True}
    corr = c / math.sqrt(pl * pr) if pl > _EPS and pr > _EPS else None
    if corr is not None:
        corr = max(-1.0, min(1.0, corr))
    e_m = 0.25 * (tot + 2.0 * c)
    e_s = 0.25 * (tot - 2.0 * c)
    e_m, e_s = max(e_m, 0.0), max(e_s, 0.0)
    side = e_s / (e_m + e_s) if (e_m + e_s) > 0 else None
    ratio = e_m / (0.5 * tot)
    cancelled = ratio < 1e-9  # deeper than -90 dB: treat as total cancellation
    lc = None if cancelled else 10.0 * math.log10(ratio)
    return {"correlation": corr, "side_ratio": side, "level_change_db": lc,
            "mono_loss_db": None if lc is None else -lc, "cancelled": bool(cancelled),
            "silent": False}


def band_stereo(spec: Spectrum, bands=BANDS_P22) -> dict:
    """Per-band correlation, side ratio and mono level change, plus full band.

    Returns {"bands": {name: {...}}, "full_band": {...}} or None for mono.
    """
    if spec.channels < 2:
        return None
    pl_bins, pr_bins = spec.bin_power(0), spec.bin_power(1)
    cross = spec.bin_cross(0, 1)
    out = {}
    for b in clip_bands(bands, spec.sr):
        d = _stereo_from_sums(spec.band_sum(pl_bins, b.lo_hz, b.hi_hz),
                              spec.band_sum(pr_bins, b.lo_hz, b.hi_hz),
                              spec.band_sum(cross, b.lo_hz, b.hi_hz))
        d["range_hz"] = [b.lo_hz, b.hi_hz]
        out[b.name] = d
    lo, hi = AUDIBLE_RANGE_HZ
    hi = min(hi, spec.sr / 2.0)
    full = _stereo_from_sums(spec.band_sum(pl_bins, lo, hi), spec.band_sum(pr_bins, lo, hi),
                             spec.band_sum(cross, lo, hi))
    full["range_hz"] = [lo, hi]
    return {"bands": out, "full_band": full}


def low_band_negative_persistence(x, sr: float, *, cutoff_hz: float = 120.0,
                                  frame_s: float = 0.1, hp_hz: float = 20.0,
                                  threshold: float = 0.0,
                                  silence_dbfs: float = -70.0) -> dict | None:
    """S-03 measure: how long the band below `cutoff_hz` stays anti-correlated.

    L and R are band-passed hp_hz..cutoff_hz with a zero-phase Butterworth
    (4th order, applied forward and backward). In consecutive frames of
    `frame_s` the correlation sum(l*r)/sqrt(sum(l^2) sum(r^2)) is computed.
    Frames whose low-band level (mean of L/R mean squares) is below
    `silence_dbfs` are inactive: they never count as negative and they break
    runs. Returns None for mono input.
    """
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1 or a.shape[1] < 2:
        return None
    a = np.where(np.isfinite(a[:, :2]), a[:, :2], 0.0)
    flen = max(1, int(round(frame_s * sr)))
    n_frames = a.shape[0] // flen
    result = {"cutoff_hz": float(cutoff_hz), "highpass_hz": float(hp_hz), "frame_s": flen / sr,
              "threshold": float(threshold), "silence_dbfs": float(silence_dbfs),
              "frames": int(n_frames), "active_frames": 0, "negative_frames": 0,
              "negative_fraction": 0.0, "negative_fraction_of_all": 0.0,
              "longest_negative_run_s": 0.0, "min_correlation": None,
              "median_correlation": None}
    if n_frames == 0:
        return result
    hi = min(cutoff_hz, 0.45 * sr)
    sos = butter(4, [hp_hz, hi], btype="bandpass", fs=sr, output="sos")
    y = sosfiltfilt(sos, a, axis=0)[: n_frames * flen].reshape(n_frames, flen, 2)
    ell, r = y[:, :, 0], y[:, :, 1]
    ll = np.einsum("ij,ij->i", ell, ell)
    rr = np.einsum("ij,ij->i", r, r)
    lr = np.einsum("ij,ij->i", ell, r)
    level = 0.5 * (ll + rr) / flen
    active = level > 10.0 ** (silence_dbfs / 10.0)
    denom = np.sqrt(ll * rr)
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.where(denom > 0, lr / np.where(denom > 0, denom, 1.0), 0.0)
    neg = active & (corr < threshold)
    longest = run = 0
    for v in neg:
        run = run + 1 if v else 0
        longest = max(longest, run)
    n_act = int(active.sum())
    result.update({
        "active_frames": n_act,
        "negative_frames": int(neg.sum()),
        "negative_fraction": float(neg.sum() / n_act) if n_act else 0.0,
        "negative_fraction_of_all": float(neg.sum() / n_frames),
        "longest_negative_run_s": longest * flen / sr,
        "min_correlation": float(corr[active].min()) if n_act else None,
        "median_correlation": float(np.median(corr[active])) if n_act else None,
    })
    return result
