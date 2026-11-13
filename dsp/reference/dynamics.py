"""compressor and true-peak limiter (reference backend)."""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from .truepeak import detector_factor, peak_per_sample

_TINY = 1e-12


def gr_stats(gr_db: np.ndarray) -> dict:
    """Gain-reduction statistics (positive dB = reduction). Used for P-18 and R-11 checks."""
    if gr_db.size == 0:
        return {"median_db": 0.0, "p95_db": 0.0, "max_db": 0.0, "mean_db": 0.0, "frac_over_1db": 0.0}
    return {
        "median_db": round(float(np.median(gr_db)), 4),
        "p95_db": round(float(np.percentile(gr_db, 95)), 4),
        "max_db": round(float(np.max(gr_db)), 4),
        "mean_db": round(float(np.mean(gr_db)), 4),
        "frac_over_1db": round(float(np.mean(gr_db > 1.0)), 6),
    }


# ---------------------------------------------------------------------------
# compressor
# ---------------------------------------------------------------------------

def static_curve_db(level_db: np.ndarray, threshold: float, ratio: float, knee: float) -> np.ndarray:
    """Output level for an input level (soft knee, Giannoulis/Massberg/Reiss form)."""
    x = np.asarray(level_db, dtype=np.float64)
    y = x.copy()
    over = x - threshold
    slope = 1.0 / ratio - 1.0
    if knee > 0:
        in_knee = np.abs(over) * 2.0 <= knee
        y[in_knee] = x[in_knee] + slope * (over[in_knee] + knee / 2.0) ** 2 / (2.0 * knee)
        above = over * 2.0 > knee
    else:
        above = over > 0
    y[above] = threshold + over[above] / ratio
    return y


def _smooth_gr(gr: np.ndarray, a_att: float, a_rel: float) -> np.ndarray:
    """Decoupled attack/release one-pole smoothing of a gain-reduction trace (dB)."""
    out = np.empty_like(gr)
    prev = 0.0
    ia, ir = 1.0 - a_att, 1.0 - a_rel
    vals = gr.tolist()
    res = [0.0] * len(vals)
    for i, g in enumerate(vals):
        if g > prev:
            prev = a_att * prev + ia * g
        else:
            prev = a_rel * prev + ir * g
        res[i] = prev
    out[:] = res
    return out


def _coef(ms: float, sr: int) -> float:
    return math.exp(-1.0 / (ms * 1e-3 * sr))


def compressor(x: np.ndarray, sr: int, p: dict, **_):
    n, ch = x.shape
    if p["detector"] == "peak":
        det = np.abs(x)
    else:
        w = max(1, int(round(p["rms_window_ms"] * 1e-3 * sr)))
        det = np.sqrt(np.maximum(ndimage.uniform_filter1d(x * x, size=w, axis=0, mode="constant",
                                                          origin=(w - 1) // 2), 0.0))
    if p["stereo_link"]:
        det = np.max(det, axis=1, keepdims=True)
    level = 20.0 * np.log10(np.maximum(det, _TINY))
    gr = level - static_curve_db(level, p["threshold_db"], p["ratio"], p["knee_db"])
    a_att, a_rel = _coef(p["attack_ms"], sr), _coef(p["release_ms"], sr)
    gr_s = np.stack([_smooth_gr(gr[:, c], a_att, a_rel) for c in range(gr.shape[1])], axis=1)
    g = 10.0 ** ((p["makeup_db"] - gr_s) / 20.0)
    y = x * g
    trace = np.max(gr_s, axis=1)
    st = gr_stats(trace)
    if st["p95_db"] > 10.0:
        scale = "excessive"
    elif st["p95_db"] > 6.0:
        scale = "heavy"
    elif st["p95_db"] >= 3.0:
        scale = "even_out"
    else:
        scale = "light_glue"
    return y, sr, {"gain_reduction": st, "gr_scale": scale, "latency_samples": 0,
                   "times_ms": {"attack": p["attack_ms"], "release": p["release_ms"]}}


# ---------------------------------------------------------------------------
# true-peak limiter
# ---------------------------------------------------------------------------

def _forward_min(g: np.ndarray, L: int) -> np.ndarray:
    """out[n] = min(g[n .. n+L]) (window looking ahead), padded with 1.0 past the end."""
    if L <= 0:
        return g.copy()
    pad = np.concatenate([g, np.ones(L)])
    size = L + 1
    # minimum_filter1d window for index i covers [i - size//2 - origin, i + (size-1)//2 - origin]
    # (origin within [-(size//2), (size-1)//2]); choose the origin so that it starts at i.
    origin = -(size // 2)
    m = ndimage.minimum_filter1d(pad, size=size, mode="nearest", origin=origin)
    return m[: g.shape[0]]


def _release_hold(gr_db: np.ndarray, a: float) -> np.ndarray:
    """r[n] = max(gr[n], a * r[n-1]) -- instant attack, exponential release, vectorised.

    r[n] = max_k<=n gr[k] * a^(n-k) = exp(n*ln a + cummax(ln gr[k] - k*ln a)).
    """
    pos = gr_db > 0
    if not np.any(pos):
        return np.zeros_like(gr_db)
    la = math.log(a)
    k = np.arange(gr_db.shape[0], dtype=np.float64)
    with np.errstate(divide="ignore"):
        lg = np.where(pos, np.log(np.where(pos, gr_db, 1.0)), -np.inf) - k * la
    acc = np.maximum.accumulate(lg)
    with np.errstate(over="ignore", invalid="ignore"):
        r = np.exp(k * la + acc)
    r[~np.isfinite(r)] = 0.0
    return np.maximum(r, gr_db)


def _box_backward(g: np.ndarray, length: int) -> np.ndarray:
    """out[n] = mean(g[n-length+1 .. n]) with g padded by g[0] before the start.

    Padding with g[0] (not 1.0) keeps the guarantee for peaks within the first
    lookahead window: g[0] already includes the forward minimum over [0, L].
    """
    if length <= 1 or g.size == 0:
        return g.copy()
    pad = np.concatenate([np.full(length - 1, g[0]), g])
    c = np.concatenate([[0.0], np.cumsum(pad)])
    out = (c[length:] - c[:-length]) / length
    # cumulative sums can drift by a few ulps; a gain never exceeds 1
    return np.minimum(out, 1.0)


def _limiter_gain(req_peak: np.ndarray, target: float, L: int, a_rel: float) -> np.ndarray:
    g_req = np.minimum(1.0, target / np.maximum(req_peak, _TINY))
    if np.all(g_req >= 1.0):
        return np.ones_like(g_req)
    a = _forward_min(g_req, L)
    gr_db = -20.0 * np.log10(a)
    gr_db = _release_hold(gr_db, a_rel)
    r = 10.0 ** (-gr_db / 20.0)
    # two cascaded boxes; their total span is L + 1 samples, so at every peak the whole
    # averaging window lies inside the forward-min region and the gain is <= g_req there
    l1 = L // 2 + 1
    l2 = L - L // 2 + 1
    g = _box_backward(_box_backward(r, l1), l2)
    return np.minimum(g, 1.0)


def limiter(x: np.ndarray, sr: int, p: dict, **_):
    ceiling = p["ceiling_dbtp"]
    factor = detector_factor(sr, int(p["oversample"]))
    ceil_lin = 10.0 ** (ceiling / 20.0)
    L = max(1, int(round(p["lookahead_ms"] * 1e-3 * sr)))
    a_rel = _coef(p["release_ms"], sr)
    # grids: the detector factor, plus plain 4x when it is not a multiple of 4 (e.g. 10x at
    # 44.1 kHz), so neither a 192 kHz-style meter nor a plain 4x meter reads above the ceiling
    grids = (factor,) if factor % 4 == 0 else (factor, 4)

    def detect(sig):
        out = peak_per_sample(sig, grids[0])
        for f in grids[1:]:
            np.maximum(out, peak_per_sample(sig, f), out=out)
        return out

    pk = detect(x)
    # an inter-sample peak in [n-1, n) or [n, n+1) constrains the gain at sample n
    req = np.maximum(pk, np.concatenate([[0.0], pk[:-1]]))
    in_tp = float(np.max(pk)) if pk.size else 0.0

    margin_db = 0.01
    target = ceil_lin * 10.0 ** (-margin_db / 20.0)
    iterations = 0
    g = np.ones(x.shape[0])
    y = x
    out_tp = in_tp
    while True:
        iterations += 1
        g = _limiter_gain(req, target, L, a_rel)
        y = x * g[:, None]
        out_tp = float(np.max(detect(y))) if y.size else 0.0
        if out_tp <= ceil_lin or iterations >= 6:
            break
        excess_db = 20.0 * math.log10(out_tp / ceil_lin)
        target *= 10.0 ** (-(excess_db + 0.005) / 20.0)
    static_fallback_db = 0.0
    if out_tp > ceil_lin:
        # last-resort guarantee: static trim of the remaining excess
        static_fallback_db = 20.0 * math.log10(out_tp / ceil_lin) + 0.001
        s = 10.0 ** (-static_fallback_db / 20.0)
        y = y * s
        g = g * s
        out_tp = float(np.max(detect(y)))
    gr_db = -20.0 * np.log10(np.maximum(g, _TINY))
    stats = {
        "gain_reduction": gr_stats(gr_db),
        "in_true_peak_dbtp": _db(in_tp),
        "out_true_peak_dbtp": _db(out_tp),
        "ceiling_dbtp": ceiling,
        "detector_oversample": factor,
        "detector_grids": list(grids),
        "lookahead_samples": L,
        "latency_samples": L,
        "latency_compensated": True,
        "iterations": iterations,
        "internal_target_dbtp": round(20.0 * math.log10(target), 4),
        "static_fallback_db": round(static_fallback_db, 4),
    }
    return y, sr, stats


def _db(v: float) -> float | None:
    return round(20.0 * math.log10(v), 4) if v > 0 else None
