"""dynamic_eq and deesser (reference backend).

Structure (minimum phase, R-12, R-13):

    band = B(x)                       B: band-pass / low-pass / high-pass (biquad)
    y    = x + (G(t) - 1) * band      G(t): linear band gain from the gain computer

For a fixed G this is exactly a second-order peaking (or shelving) filter
``1 + (G - 1) * B(z)``: the bilinear image of ``(s^2 + G*s/Q + 1) / (s^2 + s/Q + 1)``,
whose zeros stay in the left half plane for every G > 0, so the processor is
minimum phase at every instant. Because G enters linearly, a time-varying gain
needs no per-sample coefficient update and the whole render is vectorised.

``bw_oct`` is the bandwidth of the band-pass between its -3 dB points (the
same octave convention as the ``eq`` notch); the gain change at the centre is
exactly G. With a cut the -6 dB-down width narrows a little (constant-Q band).
Shelves use a second-order Butterworth split at ``freq_hz`` (``bw_oct`` unused).

Gain computer: the band is measured with a causal RMS detector (window of two
periods of ``freq_hz``, 1..50 ms), linked across channels. Above
``threshold_db`` the band is pulled toward the threshold (infinite ratio)
until ``|range_db|`` is used up; ``range_db < 0`` cuts, ``> 0`` boosts. The dB
trace is smoothed with decoupled attack/release ballistics (ballistics.py).
Below the threshold the gain is exactly 1, so the output is bit-identical to
the input.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

from . import ballistics
from .dynamics import gr_stats

_TINY = 1e-12


def band_sos(shape: str, freq_hz: float, bw_oct: float, sr: int) -> np.ndarray:
    """Second-order section of the band filter B(z) (unity gain in its passband)."""
    w0 = 2.0 * math.pi * freq_hz / sr
    cw, sw = math.cos(w0), math.sin(w0)
    if shape == "peak":
        # RBJ band-pass, constant 0 dB peak gain; octave bandwidth with the bilinear-warp correction
        alpha = sw * math.sinh(math.log(2.0) / 2.0 * bw_oct * w0 / sw)
        b = [alpha, 0.0, -alpha]
        a = [1.0 + alpha, -2.0 * cw, 1.0 - alpha]
    else:
        alpha = sw / (2.0 * math.sqrt(0.5))  # Butterworth, Q = 1/sqrt(2)
        if shape == "low_shelf":
            b = [(1.0 - cw) / 2.0, 1.0 - cw, (1.0 - cw) / 2.0]
        elif shape == "high_shelf":
            b = [(1.0 + cw) / 2.0, -(1.0 + cw), (1.0 + cw) / 2.0]
        else:
            raise ValueError(f"unknown dynamic band shape {shape!r}")
        a = [1.0 + alpha, -2.0 * cw, 1.0 - alpha]
    a0 = a[0]
    return np.array([[b[0] / a0, b[1] / a0, b[2] / a0, 1.0, a[1] / a0, a[2] / a0]])


def detector_window_ms(freq_hz: float) -> float:
    return float(min(50.0, max(1.0, 2000.0 / freq_hz)))


def _linked_rms(band: np.ndarray, sr: int, window_ms: float) -> np.ndarray:
    from .dynamics import rms_detector
    det = rms_detector(band, sr, window_ms)
    linked = det[:, 0].copy()
    for c in range(1, det.shape[1]):
        np.maximum(linked, det[:, c], out=linked)
    return linked


def dynamic_band(x: np.ndarray, sr: int, *, shape: str, freq_hz: float, bw_oct: float,
                 threshold_db: float, range_db: float, attack_ms: float, release_ms: float,
                 ballistics_impl: str = "auto"):
    """Core of dynamic_eq / deesser. Returns (y, gain_db_trace, info)."""
    sos = band_sos(shape, freq_hz, bw_oct, sr)
    band = signal.sosfilt(sos, x, axis=0)
    win = detector_window_ms(freq_hz)
    level = 20.0 * np.log10(np.maximum(_linked_rms(band, sr, win), _TINY))
    target = np.clip(level - threshold_db, 0.0, abs(range_db))   # dB of gain change (>= 0)
    a_att, a_rel = ballistics.coef(attack_ms, sr), ballistics.coef(release_ms, sr)
    if range_db == 0.0 or not np.any(target > 0.0):
        mag, impl = np.zeros(x.shape[0]), "none"
    else:
        mag, impl = ballistics.smooth(target, a_att, a_rel, impl=ballistics_impl)
    sign = -1.0 if range_db < 0 else 1.0
    gain_db = sign * mag
    if np.any(mag > 0.0):
        g = np.exp(gain_db * (math.log(10.0) / 20.0)) - 1.0
        y = x + g[:, None] * band
    else:
        y = x.copy()
    info = {"band": {"shape": shape, "freq_hz": freq_hz,
                     "bw_oct": bw_oct if shape == "peak" else None,
                     "filter": "rbj_bandpass" if shape == "peak" else "butterworth_2nd_order"},
            "detector": {"type": "rms", "window_ms": round(win, 3), "stereo_link": True,
                         "max_level_db": round(float(np.max(level)), 3) if level.size else None},
            "phase": "minimum", "ballistics": impl, "latency_samples": 0}
    return y, gain_db, info


def _activity(mag: np.ndarray, sr: int, thresh_db: float = 0.5) -> dict:
    on = mag > thresh_db
    frac = float(np.count_nonzero(on) / on.size) if on.size else 0.0
    edges = np.count_nonzero(np.diff(on.astype(np.int8)) == 1) + (1 if on.size and on[0] else 0)
    return {"active_frac": round(frac, 6), "events": int(edges),
            "active_threshold_db": thresh_db}


def dynamic_eq(x: np.ndarray, sr: int, p: dict, *, ballistics_impl: str = "auto", **_):
    y, gain_db, info = dynamic_band(x, sr, shape=p["shape"], freq_hz=p["freq_hz"], bw_oct=p["bw_oct"],
                                    threshold_db=p["threshold_db"], range_db=p["range_db"],
                                    attack_ms=p["attack_ms"], release_ms=p["release_ms"],
                                    ballistics_impl=ballistics_impl)
    mag = np.abs(gain_db)
    act = _activity(mag, sr)
    stats = dict(info)
    stats.update({
        "direction": "cut" if p["range_db"] < 0 else "boost" if p["range_db"] > 0 else "none",
        "gain_change": gr_stats(mag),
        "activity": act,
        "times_ms": {"attack": p["attack_ms"], "release": p["release_ms"]},
    })
    if act["active_frac"] > 0.8:
        stats["note"] = ("R-13: the band is active most of the time; a constant problem is better "
                         "served by a static EQ")
    return y, sr, stats


def deesser(x: np.ndarray, sr: int, p: dict, *, ballistics_impl: str = "auto", **_):
    y, gain_db, info = dynamic_band(x, sr, shape="peak", freq_hz=p["freq_hz"], bw_oct=p["bw_oct"],
                                    threshold_db=p["threshold_db"], range_db=-p["range_db"],
                                    attack_ms=p["attack_ms"], release_ms=p["release_ms"],
                                    ballistics_impl=ballistics_impl)
    mag = np.abs(gain_db)
    lo = p["freq_hz"] * 2.0 ** (-p["bw_oct"] / 2.0)
    hi = p["freq_hz"] * 2.0 ** (p["bw_oct"] / 2.0)
    stats = dict(info)
    stats.update({
        "mode": "split_band",
        "band_hz": [round(lo, 1), round(hi, 1)],
        "gain_reduction": gr_stats(mag),
        "activity": _activity(mag, sr),
        "times_ms": {"attack": p["attack_ms"], "release": p["release_ms"]},
    })
    return y, sr, stats
