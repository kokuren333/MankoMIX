"""One symmetric FIR for a sum of analog EQ prototype magnitudes.

Analog transfer functions: Audio EQ Cookbook, W3C Note 2021-06-08,
https://www.w3.org/TR/audio-eq-cookbook/ (formula reference, no code copied).
"""
import numpy as np
from scipy import fft

from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _e, _f
from mankomix.dspx.bb.fir import RESOLUTIONS, resolution_taps, design_linear_fir, apply_fir


def magnitude(f, p):
    """Unwarped analog peaks, unity-slope shelves and Butterworth cuts."""
    f = np.asarray(f, dtype=np.float64)
    db = np.zeros_like(f)
    for center, gain, bw in zip(p["freq_hz"], p["gain_db"], p["bw_oct"]):
        r = f / center
        A = 10.0 ** (gain / 40)
        inv_q = 2*np.sinh(np.log(2)*bw/2)
        num = (1-r*r)**2 + (r*A*inv_q)**2
        den = (1-r*r)**2 + (r/A*inv_q)**2
        db += 10*np.log10(num/den)
    for prefix in ("low", "high"):
        center, gain = p[f"{prefix}_shelf_hz"], p[f"{prefix}_shelf_db"]
        if center and gain:
            r = f / center
            A = 10.0 ** (gain / 40)
            low = 10*np.log10(A*A*((A-r*r)**2+2*A*r*r)/((1-A*r*r)**2+2*A*r*r))
            db += low if prefix == "low" else gain-low
    for kind in ("hpf", "lpf"):
        center = p[f"{kind}_hz"]
        if center:
            order = p[f"{kind}_slope_db_oct"] // 6
            r = np.maximum(f, np.finfo(float).tiny) / center
            exponent = (2*order*np.log(r)) * (-1 if kind == "hpf" else 1)
            db -= 10/np.log(10) * np.logaddexp(0, exponent)
    return 10.0 ** (db/20)


def neutral(p):
    return (not any(p["gain_db"]) and not p["hpf_hz"] and not p["lpf_hz"]
            and not (p["low_shelf_hz"] and p["low_shelf_db"])
            and not (p["high_shelf_hz"] and p["high_shelf_db"]))


def design(p, sr):
    """Return the one combined symmetric FIR; reject cross-array mismatches."""
    if not len(p["freq_hz"]) == len(p["gain_db"]) == len(p["bw_oct"]):
        raise ParamError("linear_eq: freq_hz, gain_db and bw_oct must have equal lengths")
    taps = resolution_taps(sr, p["resolution"])
    if neutral(p):
        h = np.zeros(taps)
        h[taps//2] = 1
        return h
    return design_linear_fir(lambda f: magnitude(f, p), sr, taps, beta=.5)


def linear_eq(x, sr, p, *, seed=0):
    h = design(p, sr)
    y, stats = apply_fir(x, h, sr, neutral=neutral(p))
    # Record actual error even for sub-100 Hz / sub-0.3-oct settings.
    nfft = 1 << (8*len(h)-1).bit_length()
    f = fft.rfftfreq(nfft, 1/sr)
    actual = np.abs(fft.rfft(h, nfft, workers=1))
    target = magnitude(f, p)
    error = np.abs(20*np.log10(np.maximum(actual, 1e-15)/np.maximum(target, 1e-15)))
    stats["magnitude_error_db"] = {"above_100_hz": round(float(np.max(error[f >= 100])), 6),
                                  "below_100_hz": round(float(np.max(error[f < 100])), 6),
                                  "narrow_band": any(b < .3 for b in p["bw_oct"])}
    return y, sr, stats


SPECS = [{"type": "linear_eq", "description": "Combined analog-magnitude linear-phase EQ.",
          "params": [
              _a("freq_hz", "Hz", 10, 24000, 16, [], "Peak centres."),
              _a("gain_db", "dB", -24, 24, 16, [], "Peak gains; same length as freq_hz."),
              _a("bw_oct", "oct", .02, 6, 16, [], "Peak bandwidths; same length as freq_hz."),
              _f("low_shelf_hz", "Hz", 0, 2000, 0, "Low shelf midpoint; zero disables."),
              _f("low_shelf_db", "dB", -24, 24, 0, "Low shelf gain."),
              _f("high_shelf_hz", "Hz", 0, 20000, 0, "High shelf midpoint; zero disables."),
              _f("high_shelf_db", "dB", -24, 24, 0, "High shelf gain."),
              _f("hpf_hz", "Hz", 0, 2000, 0, "High-pass cutoff; zero disables."),
              _e("hpf_slope_db_oct", [12, 24, 48], 24, "High-pass slope.", "dB/oct"),
              _f("lpf_hz", "Hz", 0, 24000, 0, "Low-pass cutoff; zero disables."),
              _e("lpf_slope_db_oct", [12, 24, 48], 24, "Low-pass slope.", "dB/oct"),
              _e("resolution", RESOLUTIONS, "mid", "FIR resolution at 48 kHz.")],
          "stages": ["track", "bus", "master"], "master_slot": 1,
          "realtime": {"block_ok": True, "latency_samples": 0, "allocates": True,
                       "latency_rule": "(resolution_taps(sr,resolution)-1)/2; compensated offline"},
          "offline_only": False, "backends": ["reference"], "implemented": False}]
IMPLS = {"linear_eq": linear_eq}
