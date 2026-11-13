"""Localized click/pop repair (SPEC 6.4.2 step 2).

Detection: the magnitude of a high-passed signal (derivative-like emphasis
of the click energy) is summarised as block peaks. A block is a click
candidate when its peak stands far above the local median block peak *and*
the blocks 6-12 ms before and after are back near the local level and well
below the candidate (a click is short; a drum hit or a consonant is not).

Repair: the click region (a few ms) is replaced by a least-squares cubic
bridge fitted to the context on both sides (no LPC). The low band of the
repair is later discarded by the cleanup crossover (S-07), so only the part
of the click above the crossover is removed.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage
from scipy.signal import butter, sosfilt

from ._util import as_2d, load_policy, restore_shape, v


def _hp_abs(x2d: np.ndarray, sr: float, fc: float) -> np.ndarray:
    """|high-pass(x)| (4th-order Butterworth, causal, zero initial state, so an
    abrupt non-zero start counts as a step from silence), max over channels."""
    fc = min(fc, 0.45 * sr)
    sos = butter(4, fc, btype="highpass", fs=sr, output="sos")
    return np.abs(sosfilt(sos, x2d, axis=0)).max(axis=1)


def detect_clicks(x, sr: float, *, policy: dict | None = None,
                  region_s: tuple[float, float] | None = None) -> list[dict]:
    """Click positions as [{start, end, peak, ratio_db, time_s, length_ms}]
    (sample indices). ``region_s`` limits the search to (t0, t1) seconds."""
    pol = (policy or load_policy())["clicks"]
    x2d, _ = as_2d(x)
    n = x2d.shape[0]
    blk = max(4, int(round(float(v(pol["block_ms"])) * 1e-3 * sr)))
    if n < blk * 8:
        return []
    d = _hp_abs(x2d, sr, float(v(pol["highpass_hz"])))
    nb = n // blk
    blocks = d[:nb * blk].reshape(nb, blk)
    bpeak = blocks.max(axis=1)
    lw = max(5, int(round(float(v(pol["local_window_ms"])) / float(v(pol["block_ms"])))) | 1)
    local = ndimage.median_filter(bpeak, size=lw, mode="mirror")
    ratio = float(v(pol["peak_ratio"]))
    abs_min = float(v(pol["abs_min"]))
    iso = float(v(pol["isolation_ratio"]))
    drop = float(v(pol["isolation_drop"]))
    cand = (bpeak > ratio * np.maximum(local, 1e-12)) & (bpeak > abs_min)
    # isolation: blocks 6..12 ms away on both sides must be back near the
    # local level and well below the candidate (a click is short; a drum hit
    # or a consonant decays slowly)
    bms = float(v(pol["block_ms"]))
    near0 = max(1, int(round(6.0 / bms)))
    near1 = max(near0 + 1, int(round(12.0 / bms)))
    lim = np.minimum(iso * np.maximum(local, abs_min / ratio), drop * bpeak)
    ok = np.ones(nb, bool)
    for off in range(near0, near1 + 1):
        after = np.zeros(nb)
        after[:-off] = bpeak[off:]
        before = np.zeros(nb)
        before[off:] = bpeak[:-off]
        ok &= (after <= lim) & (before <= lim)
    cand &= ok
    if region_s is not None:
        b0 = int(region_s[0] * sr) // blk
        b1 = int(np.ceil(region_s[1] * sr / blk))
        mask = np.zeros(nb, bool)
        mask[max(0, b0):max(0, min(nb, b1))] = True
        cand &= mask
    idx = np.flatnonzero(cand)
    ext = float(v(pol["extent_ratio"]))
    max_len = max(2, int(round(float(v(pol["max_ms"])) * 1e-3 * sr)))
    pad = max(1, int(round(float(v(pol["pad_ms"])) * 1e-3 * sr))) + 1
    clicks: list[dict] = []
    for b in idx:
        s0 = b * blk
        p = s0 + int(np.argmax(blocks[b]))
        lev = max(local[b], 1e-12)
        lo = max(0, p - max_len // 2)
        hi = min(n, p + max_len // 2 + 1)
        above = np.flatnonzero(d[lo:hi] > ext * lev)
        a = lo + int(above[0]) if above.size else p
        e = lo + int(above[-1]) + 1 if above.size else p + 1
        a = max(0, a - pad)
        e = min(n, e + pad)
        item = {"start": int(a), "end": int(e), "peak": int(p),
                "ratio_db": round(float(20.0 * np.log10(bpeak[b] / lev)), 2)}
        if clicks and a <= clicks[-1]["end"]:
            last = clicks[-1]
            last["end"] = max(last["end"], item["end"])
            if item["ratio_db"] > last["ratio_db"]:
                last["peak"], last["ratio_db"] = item["peak"], item["ratio_db"]
        else:
            clicks.append(item)
    for c in clicks:
        c["time_s"] = round(c["peak"] / sr, 6)
        c["length_ms"] = round((c["end"] - c["start"]) * 1e3 / sr, 3)
    return clicks


def repair_clicks(x, sr: float, clicks: list[dict], *, policy: dict | None = None) -> np.ndarray:
    """Return a copy of x with each click region replaced by a cubic bridge."""
    pol = (policy or load_policy())["clicks"]
    x2d, was_1d = as_2d(x)
    y = x2d.copy()
    n = y.shape[0]
    ctx = max(8, int(round(float(v(pol["context_ms"])) * 1e-3 * sr)))
    for c in clicks:
        a, e = int(c["start"]), int(c["end"])
        if e <= a:
            continue
        # before the file start the signal is taken as silence
        left = np.arange(a - ctx, a)
        right = np.arange(e, min(n, e + ctx))
        pos = np.concatenate([left, right])
        gap = np.arange(a, e)
        vals = np.zeros((pos.size, y.shape[1]))
        inside = pos >= 0
        vals[inside] = y[pos[inside]]
        if pos.size < 4:
            y[a:e] = 0.0
            continue
        centre = 0.5 * (a + e - 1)
        scale = max(1.0, 0.5 * (pos.max() - pos.min()))
        u = (pos - centre) / scale
        ug = (gap - centre) / scale
        deg = 3 if right.size >= 2 else 1
        vand = np.vander(u, deg + 1)
        vg = np.vander(ug, deg + 1)
        coef, *_ = np.linalg.lstsq(vand, vals, rcond=None)
        y[a:e] = vg @ coef
    return restore_shape(y, was_1d)
