"""saturator and clipper (reference backend), oversampled to limit aliasing.

Up/down sampling uses scipy's polyphase resampler, which is linear phase and
delay-compensated, so the processed signal stays time-aligned with the input
(dry/wet mixing is sample-accurate).
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy import signal


@lru_cache(maxsize=8)
def _os_filter(factor: int) -> np.ndarray:
    """Interpolation / decimation FIR: 64 taps per phase, Kaiser beta 10 (~100 dB stopband),
    cutoff at the original Nyquist; flat (< 0.01 dB) to ~0.9 x Nyquist."""
    h = signal.firwin(64 * factor + 1, 1.0 / factor, window=("kaiser", 10.0))
    h.setflags(write=False)
    return h


def _oversampled(x: np.ndarray, factor: int, fn) -> np.ndarray:
    if factor <= 1:
        return fn(x)
    h = _os_filter(factor)
    up = signal.resample_poly(x, factor, 1, axis=0, window=h.copy())
    up = fn(up)
    return signal.resample_poly(up, 1, factor, axis=0, window=h.copy())[: x.shape[0]]


def harmonic_profile(curve, f0: float = 1000.0, sr: int = 48000, amplitude: float = 0.5) -> dict:
    """Measure the harmonic character of a static curve on a sine (SPEC 6.5.2: measured, not assumed)."""
    n = sr  # 1 s -> 1 Hz bins, f0 on an exact bin
    t = np.arange(n) / sr
    y = curve(amplitude * np.sin(2 * math.pi * f0 * t)[:, None])[:, 0]
    spec = np.abs(np.fft.rfft(y * signal.windows.hann(n))) + 1e-20
    fund = spec[int(f0)]
    even = sum(spec[int(f0 * k)] ** 2 for k in (2, 4, 6, 8) if f0 * k < sr / 2)
    odd = sum(spec[int(f0 * k)] ** 2 for k in (3, 5, 7, 9) if f0 * k < sr / 2)
    e_db = 10 * math.log10(even / fund ** 2 + 1e-30)
    o_db = 10 * math.log10(odd / fund ** 2 + 1e-30)
    thd = 10 * math.log10((even + odd) / fund ** 2 + 1e-30)
    return {"probe": {"freq_hz": f0, "amplitude": amplitude},
            "even_db": round(e_db, 2), "odd_db": round(o_db, 2), "thd_db": round(thd, 2),
            "dominant": "even" if e_db > o_db + 1 else "odd" if o_db > e_db + 1 else "mixed"}


def _dc_block(x: np.ndarray, sr: int, fc: float = 5.0) -> np.ndarray:
    b, a = signal.butter(1, fc, btype="highpass", fs=sr)
    return signal.lfilter(b, a, x, axis=0)


def saturator_curve(p: dict):
    g = 10.0 ** (p["drive_db"] / 20.0)
    if p["mode"] == "tanh":
        def curve(u):
            return np.tanh(g * u) / g
    else:
        bias = 0.5 * p["asymmetry"]
        tb = math.tanh(bias)
        slope0 = 1.0 - tb * tb  # derivative at 0, so the small-signal gain stays 1

        def curve(u):
            return (np.tanh(g * u + bias) - tb) / (g * slope0)
    return curve


def saturator(x: np.ndarray, sr: int, p: dict, **_):
    curve = saturator_curve(p)
    wet = _oversampled(x, int(p["oversample"]), curve)
    if p["mode"] == "asymmetric":
        wet = _dc_block(wet, sr)
    mix = p["mix"]
    y = (mix * wet + (1.0 - mix) * x) * 10.0 ** (p["output_db"] / 20.0)
    return y, sr, {"harmonics": harmonic_profile(curve), "oversample": int(p["oversample"]),
                   "latency_samples": 0, "dc_blocker_hz": 5.0 if p["mode"] == "asymmetric" else None}


def clipper_curve(p: dict):
    c = 10.0 ** (p["ceiling_db"] / 20.0)
    g = 10.0 ** (p["drive_db"] / 20.0)
    if p["mode"] == "hard":
        def curve(u):
            return np.clip(g * u, -c, c)
    else:
        t = c * (1.0 - p["softness"])
        span = c - t

        def curve(u):
            v = g * u
            a = np.abs(v)
            if span <= 0:
                return np.clip(v, -c, c)
            out = np.where(a <= t, a, t + span * np.tanh((a - t) / span))
            return np.sign(v) * out
    return curve


def clipper(x: np.ndarray, sr: int, p: dict, **_):
    curve = clipper_curve(p)
    g = 10.0 ** (p["drive_db"] / 20.0)
    c = 10.0 ** (p["ceiling_db"] / 20.0)
    clipped_frac = float(np.mean(np.abs(x * g) > c)) if x.size else 0.0
    y = _oversampled(x, int(p["oversample"]), curve)
    return y, sr, {"harmonics": harmonic_profile(curve, amplitude=min(1.0, 2.0 * c / g)),
                   "frac_samples_over_ceiling_in": round(clipped_frac, 6),
                   "oversample": int(p["oversample"]), "latency_samples": 0,
                   "note": "downsampling can overshoot the clip level slightly; the limiter sets the true-peak ceiling"}
