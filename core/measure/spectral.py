"""Spectral measures: P-04 band crest, P-07 band energy ratios, LTAS.

Levels are mean squares in dB re 1.0, averaged over channels (a full-scale
sine reads -3.01 dB). All values cover the whole signal; the measurement
window is recorded in the output.
"""

from __future__ import annotations

import math

import numpy as np

from .bands import (AUDIBLE_RANGE_HZ, BANDS_P07, BANDS_P22, EDGE_HALF_WIDTH_OCT, Spectrum,
                    clip_bands, erb_grid, third_octave_grid)

CREST_METHOD = ("zero-phase FFT band filter (raised-cosine edges, 1/6 oct half-width); "
                "peak = max |x| over channels, read from the band signal synthesised at >= 16x "
                "the band's top frequency (<= 0.17 dB under-read); rms = sqrt(mean square over "
                "channels) from the filtered spectrum (exact)")


def _db10(v: float):
    return 10.0 * math.log10(v) if v > 0 else None


def _db20(v: float):
    return 20.0 * math.log10(v) if v > 0 else None


def _crest_values(peak: float, ms: float) -> dict:
    pk, rm = _db20(peak), _db10(ms)
    crest = pk - rm if pk is not None and rm is not None else None
    return {"crest_db": crest, "peak_dbfs": pk, "rms_dbfs": rm}


def _band_crest(spec: Spectrum, lo_hz: float, hi_hz: float) -> dict:
    w = spec.band_weights(lo_hz, hi_hz)
    y, _rate = spec.band_signal_reduced(lo_hz, hi_hz, weights=w)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    ms = float(np.dot(spec.mean_bin_power(), w * w))
    return _crest_values(peak, ms)


def measurement_window(spec: Spectrum) -> dict:
    return {"kind": "full_signal", "start_s": 0.0, "end_s": spec.n / spec.sr}


def band_crest(spec: Spectrum, bands=BANDS_P22, *, x: np.ndarray | None = None) -> dict:
    """P-04: per-band crest factor (peak dB - RMS dB) over the whole signal.

    The full-band crest is taken from the time signal `x` when given,
    otherwise from the spectrum.
    """
    out = {}
    for b in clip_bands(bands, spec.sr):
        d = _band_crest(spec, b.lo_hz, b.hi_hz)
        d["range_hz"] = [b.lo_hz, b.hi_hz]
        out[b.name] = d
    if x is not None:
        a = np.asarray(x, dtype=float)
        full = _crest_values(float(np.max(np.abs(a))) if a.size else 0.0,
                             float(np.mean(a * a)) if a.size else 0.0)
    else:
        full = _band_crest(spec, 0.0, spec.sr)
    return {"window": measurement_window(spec), "method": CREST_METHOD,
            "edge_half_width_oct": EDGE_HALF_WIDTH_OCT, "bands": out, "full_band": full}


def band_energy(spec: Spectrum, bands=BANDS_P07,
                total_range_hz: tuple[float, float] = AUDIBLE_RANGE_HZ) -> dict:
    """Band levels and their ratio to the total energy in total_range_hz.

    Per band: level_db (absolute band mean square, dB), ratio_db
    (band / total, dB) and fraction (band / total). For a contiguous band set
    spanning total_range_hz the fractions sum to 1.
    """
    lo, hi = total_range_hz[0], min(total_range_hz[1], spec.sr / 2.0)
    total = spec.mean_power(lo, hi)
    out = {}
    for b in clip_bands(bands, spec.sr):
        e = spec.mean_power(b.lo_hz, b.hi_hz)
        out[b.name] = {"range_hz": [b.lo_hz, b.hi_hz], "level_db": _db10(e),
                       "ratio_db": _db10(e / total) if total > 0 and e > 0 else None,
                       "fraction": e / total if total > 0 else None}
    return {"total_range_hz": [lo, hi], "total_level_db": _db10(total), "bands": out}


def ltas(spec: Spectrum, grid: str = "erb") -> dict:
    """Long-term average spectrum on a fixed grid ("erb" = 1-ERB bands, or "third_octave").

    level_db: band mean square in dB (channel average). density_db: level per
    Hz of bandwidth (dB re 1/Hz), useful to compare bands of unequal width.
    """
    if grid == "erb":
        bands = erb_grid(spec.sr)
    elif grid == "third_octave":
        bands = third_octave_grid(spec.sr)
    else:
        raise ValueError(f"unknown LTAS grid: {grid}")
    lo, hi, center, level, density = [], [], [], [], []
    for b in bands:
        e = spec.mean_power(b.lo_hz, b.hi_hz)
        has_bins = spec.has_bins(b.lo_hz, b.hi_hz)
        lo.append(b.lo_hz)
        hi.append(b.hi_hz)
        center.append(math.sqrt(b.lo_hz * b.hi_hz))
        level.append(_db10(e) if has_bins else None)
        density.append(_db10(e / (b.hi_hz - b.lo_hz)) if has_bins else None)
    return {"grid": grid, "lo_hz": lo, "hi_hz": hi, "center_hz": center,
            "level_db": level, "density_db": density}
