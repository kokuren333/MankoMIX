"""Apply a log-frequency dB curve using BB-07's spectral FIR designer."""
import numpy as np
from mankomix.dspx.params import _e, _f
from mankomix.dspx.bb.fir import (RESOLUTIONS, resolution_taps, curve_magnitude,
                                 design_linear_fir, minimum_phase, apply_fir)


def neutral(p):
    return not p["curve"] or not p["amount"] or not any(v for _, v in p["curve"])


def design(p, sr):
    taps = resolution_taps(sr, p["resolution"])
    if neutral(p):
        h = np.zeros(taps if p["phase"] == "linear" else 1)
        h[len(h)//2] = 1
        return h
    h = design_linear_fir(lambda f: curve_magnitude(f, p["curve"], p["amount"]), sr, taps)
    return minimum_phase(h) if p["phase"] == "minimum" else h


def fir_eq(x, sr, p, *, seed=0):
    y, stats = apply_fir(x, design(p, sr), sr, linear=p["phase"] == "linear", neutral=neutral(p))
    return y, sr, stats


SPECS = [{"type": "fir_eq", "description": "FIR EQ from a log-Hz dB curve.",
          "params": [{"id": "curve", "type": "curve", "unit": "dB", "x_unit": "Hz",
                      "x_min": 10, "x_max": 24000, "y_min": -24, "y_max": 24,
                      "max_points": 512, "default": [], "description": "Log-Hz interpolated dB points."},
                     _f("amount", None, 0, 1.5, 1, "Multiplier on curve dB."),
                     _e("phase", ["linear", "minimum"], "linear", "FIR phase."),
                     _e("resolution", RESOLUTIONS, "mid", "FIR resolution at 48 kHz.")],
          "stages": ["track", "bus", "master"], "master_slot": 1,
          "realtime": {"block_ok": True, "latency_samples": 0, "allocates": True,
                       "latency_rule": "linear: (resolution_taps(sr,resolution)-1)/2; minimum: 0; compensated offline"},
          "offline_only": False, "backends": ["reference"], "implemented": True}]
IMPLS = {"fir_eq": fir_eq}
