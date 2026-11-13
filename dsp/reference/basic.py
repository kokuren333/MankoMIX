"""gain, pan, loudness_gain (reference backend)."""

from __future__ import annotations

import math

import numpy as np


def db_to_lin(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def gain(x: np.ndarray, sr: int, p: dict, **_):
    g = db_to_lin(p["gain_db"])
    return x * g, sr, {"gain_db": p["gain_db"], "linear": g}


def loudness_gain(x: np.ndarray, sr: int, p: dict, **_):
    y, sr, st = gain(x, sr, p)
    return y, sr, st


def pan_gains(position: float, center_db: float) -> tuple[float, float]:
    """Per-channel gains for a mono source.

    gL = cos(theta)^k, gR = sin(theta)^k with theta = (position + 1) * pi / 4.
    k is chosen so that the center gain is exactly ``center_db``:
    cos(pi/4)^k = 10^(center_db/20)  ->  k = center_db / (20 log10(cos(pi/4))).
    k = 1 is the classic sin/cos constant-power law (-3.01 dB), k = 2 the
    linear-sum law (-6.02 dB), k = 0 no attenuation.
    """
    k = center_db / (20.0 * math.log10(math.cos(math.pi / 4.0)))
    theta = (position + 1.0) * math.pi / 4.0
    c, s = math.cos(theta), math.sin(theta)
    gl = 0.0 if c <= 1e-15 else c ** k
    gr = 0.0 if s <= 1e-15 else s ** k
    if k == 0.0:
        gl, gr = (1.0 if c > 1e-15 else 0.0), (1.0 if s > 1e-15 else 0.0)
    return gl, gr


def pan(x: np.ndarray, sr: int, p: dict, **_):
    gl, gr = pan_gains(p["position"], p["center_db"])
    if x.shape[1] == 1:
        y = np.concatenate([x * gl, x * gr], axis=1)
        mode = "mono_to_stereo"
    elif x.shape[1] == 2:
        # balance: normalise to the center gains so a centered stereo source is untouched,
        # and never boost the near side
        g0l, g0r = pan_gains(0.0, p["center_db"])
        bl = min(1.0, gl / g0l) if g0l > 0 else 1.0
        br = min(1.0, gr / g0r) if g0r > 0 else 1.0
        y = np.stack([x[:, 0] * bl, x[:, 1] * br], axis=1)
        gl, gr = bl, br
        mode = "stereo_balance"
    else:
        raise ValueError("pan: only mono or stereo input is supported")
    return y, sr, {"mode": mode, "gain_l_db": _db(gl), "gain_r_db": _db(gr),
                   "center_db": p["center_db"]}


def _db(g: float) -> float | None:
    return round(20.0 * math.log10(g), 6) if g > 0 else None
