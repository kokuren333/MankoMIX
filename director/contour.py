"""Reference-only master contours (X-08); never used by evaluation or calibration."""
from __future__ import annotations

import numpy as np

from mankomix.core.measure import loudness as L
from . import edit as E
from . import query as Q

NOTE = "落差・傾き・空白が残ったかを見る参考値。大きいほど良いわけではない"
KEYS = ("lufs_s_mean", "side_ratio_db", "bright_db", "low_db", "slope_db_per_s")


def _number(value):
    return round(float(value), 3) if value is not None and np.isfinite(value) else None


def _difference(result, floor):
    return result - floor if result is not None and floor is not None else None


def _pair(floor, result):
    return {"floor": _number(floor), "result": _number(result),
            "change": _number(_difference(result, floor))}


def _segment(x, sr, t0, t1):
    return x[max(0, round(t0 * sr)):max(0, min(len(x), round(t1 * sr)))]


def _observe(x, sr, spec):
    try:
        value = Q.observe(x, sr, spec)
    except Q.QueryError:
        return None
    return value.get("value") if value.get("status") == "ok" else None


def _measure(x, sr):
    """Use complete 3 s windows wholly inside a section; retain finite values only."""
    values = dict.fromkeys(KEYS)
    if not len(x):
        return values
    st = np.asarray(L.short_term(x, sr), dtype=np.float64)
    valid = np.isfinite(st)
    if valid.any():
        values["lufs_s_mean"] = float(np.mean(st[valid]))
        if np.count_nonzero(valid) >= 2:
            times = np.arange(len(st), dtype=np.float64)[valid] * L.HOP_S
            times -= np.mean(times)
            levels = st[valid] - np.mean(st[valid])
            values["slope_db_per_s"] = float(np.dot(times, levels) / np.dot(times, times))
    values["side_ratio_db"] = _observe(x, sr, {"primitive": "side_ratio"})
    values["bright_db"] = _observe(x, sr, {"primitive": "band_ratio", "band_hz": [4000, 12000],
                                          "ref_band_hz": [250, 4000]})
    values["low_db"] = _observe(x, sr, {"primitive": "band_ratio", "band_hz": [20, 120],
                                       "ref_band_hz": [0, sr / 2]})
    return values


def _gap_windows(floor, sr):
    """Union of quiet 50 ms RMS windows on a 10 ms grid, at most 16 in time order."""
    levels, hop, win = E.frame_levels(E._power(floor), sr)
    if not len(levels):
        return []
    quiet = levels < float(np.percentile(levels, 95)) - 30.0
    edges = np.diff(np.r_[False, quiet, False].astype(np.int8))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    windows = []
    for first, end in zip(starts, ends):
        a, b = int(first * hop), min(len(floor), int((end - 1) * hop + win))
        if 0.080 - 1e-12 <= (b - a) / sr <= 2.0 + 1e-12:
            windows.append((a / sr, b / sr))
            if len(windows) == 16:
                break
    return windows


def _residual(x, sr, t0, t1):
    """Full-band channel-mean RMS dBFS in the floor-defined gap, -200 for silence."""
    seg = _segment(x, sr, t0, t1)
    return Q._db(float(np.mean(E._power(seg)))) if len(seg) else None


def block(result: np.ndarray, floor: np.ndarray, sr: int, match_gain_db: float,
          sections: list[dict]) -> dict:
    """Compare rendered masters after applying check's level-match gain to the result.

    Sections follow the floor proposal's order. Differences use unrounded
    values; all reported numbers are rounded to three decimal places.
    """
    floor = Q._stereo(floor)
    result = Q._stereo(result) * (10.0 ** (float(match_gain_db) / 20.0))
    rows, measured = {}, []
    for section in sections:
        sid = section["id"]
        t0, t1 = float(section["start_s"]), float(section["end_s"])
        f = _measure(_segment(floor, sr, t0, t1), sr)
        r = _measure(_segment(result, sr, t0, t1), sr)
        rows[sid] = {key: _pair(f[key], r[key]) for key in KEYS}
        measured.append((sid, f["lufs_s_mean"], r["lufs_s_mean"]))
    steps = []
    for previous, current in zip(measured, measured[1:]):
        steps.append({"from": previous[0], "to": current[0],
                      **_pair(_difference(current[1], previous[1]),
                              _difference(current[2], previous[2]))})
    gaps = [{"t0_s": _number(a), "t1_s": _number(b),
             "residual_db": _pair(_residual(floor, sr, a, b), _residual(result, sr, a, b))}
            for a, b in _gap_windows(floor, sr)]
    return {"note": NOTE, "sections": rows, "steps": steps, "gaps": gaps}
