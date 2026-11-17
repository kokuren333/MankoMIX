"""First-order tilt around a prewarped pivot, or a FIR of its magnitude.

Uses scipy.signal's public bilinear/SOS API (SciPy 1.18.1, BSD-3-Clause);
no implementation code was copied. See third_party/W1b_APIS.md.
"""
import numpy as np
from scipy import signal
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _e, _f
from mankomix.dspx.bb.fir import resolution_taps, design_linear_fir, apply_fir


def design_sos(p, sr):
    if p["pivot_hz"] >= .49*sr:
        raise ParamError("tilt_eq: pivot_hz must be below 0.98 * Nyquist")
    g = 10.0 ** (p["tilt_db"]/20)
    w = 2*sr*np.tan(np.pi*p["pivot_hz"]/sr)
    b, a = signal.bilinear([g, w], [1, w*g], fs=sr)
    return signal.tf2sos(b, a)


def design(p, sr):
    sos = design_sos(p, sr)
    return design_linear_fir(lambda f: np.abs(signal.sosfreqz(sos, worN=f, fs=sr)[1]),
                             sr, resolution_taps(sr, "mid"))


def tilt_eq(x, sr, p, *, seed=0):
    sos = design_sos(p, sr)
    if p["phase"] == "linear":
        y, stats = apply_fir(x, design(p, sr), sr, neutral=p["tilt_db"] == 0)
    else:
        y = x.copy() if p["tilt_db"] == 0 else signal.sosfilt(sos, x, axis=0)
        stats = {"latency_samples": 0, "phase_cost": {"phase_type": "minimum"}}
    return y, sr, stats


SPECS = [{"type": "tilt_eq", "description": "Monotonic first-order tilt around a unity pivot.",
          "params": [_f("pivot_hz", "Hz", 100, 10000, 650, "Unity-gain pivot."),
                     _f("tilt_db", "dB", -6, 6, 0, "High-end gain; opposite low-end gain."),
                     _e("phase", ["minimum", "linear"], "minimum", "Filter phase.")],
          "stages": ["track", "bus", "master"], "master_slot": 1,
          "realtime": {"block_ok": True, "latency_samples": 0, "allocates": True,
                       "latency_rule": "linear: (resolution_taps(sr,'mid')-1)/2; minimum: 0; compensated offline"},
          "offline_only": False, "backends": ["reference"], "implemented": True}]
IMPLS = {"tilt_eq": tilt_eq}
