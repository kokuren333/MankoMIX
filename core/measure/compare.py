"""Level-matched comparison of two signals (R-01, R-25, SPEC 15.2).

Both signals are measured; the louder one (by integrated loudness) is
lowered to the quieter one's integrated loudness and re-measured. Deltas are
always b - a on the matched pair. Level-type deltas (dB of energy) carry
perceived_ratio = 2 ** (delta_db / 10): the loudness power law (+10 dB is
about twice as loud), as required by R-25. Other deltas carry null.
"""

from __future__ import annotations

import numpy as np

from ..errors import InputError
from .loudness import as_frames
from .vector import json_safe, measure_signal

# (path in vector, unit, is a level so perceived_ratio applies)
_SCALAR_METRICS = [
    (("P-03", "integrated_lufs"), "LUFS", True),
    (("P-03", "short_term_max_lufs"), "LUFS", True),
    (("P-03", "short_term_p10"), "LUFS", True),
    (("P-03", "short_term_p50"), "LUFS", True),
    (("P-03", "short_term_p95"), "LUFS", True),
    (("P-03", "momentary_max_lufs"), "LUFS", True),
    (("P-03", "lra_lu"), "LU", False),
    (("P-03", "true_peak_dbtp"), "dBTP", False),
    (("P-03", "sample_peak_dbfs"), "dBFS", False),
    (("P-03", "plr_db"), "dB", False),
    (("P-03", "psr_db"), "dB", False),
]


def _get(vec: dict, path):
    cur = vec
    for p in path:
        if not isinstance(cur, dict) or cur.get(p) is None:
            return None
        cur = cur[p]
    return cur


def _delta(a, b, unit: str, level: bool) -> dict:
    d = None if a is None or b is None else b - a
    return {"a": a, "b": b, "delta": d, "unit": unit,
            "perceived_ratio": (2.0 ** (d / 10.0)) if (level and d is not None) else None}


def _band_names(vec_a: dict, vec_b: dict, section: str, key: str):
    ba = _get(vec_a, (section, key)) or {}
    bb = _get(vec_b, (section, key)) or {}
    return [name for name in ba if name in bb]


def deltas(vec_a: dict, vec_b: dict) -> dict:
    """b - a per metric for two measurement vectors."""
    out: dict = {}
    for path, unit, level in _SCALAR_METRICS:
        out["/".join(path)] = _delta(_get(vec_a, path), _get(vec_b, path), unit, level)
    for name in _band_names(vec_a, vec_b, "P-07", "bands"):
        p = ("P-07", "bands", name, "level_db")
        out["/".join(p)] = _delta(_get(vec_a, p), _get(vec_b, p), "dB", True)
    for name in _band_names(vec_a, vec_b, "P-07", "partition_bands"):
        p = ("P-07", "partition_bands", name, "level_db")
        out["/".join(p)] = _delta(_get(vec_a, p), _get(vec_b, p), "dB", True)
    for name in _band_names(vec_a, vec_b, "P-04", "bands"):
        p = ("P-04", "bands", name, "crest_db")
        out["/".join(p)] = _delta(_get(vec_a, p), _get(vec_b, p), "dB", False)
    for name in _band_names(vec_a, vec_b, "P-05", "bands"):
        for field in ("correlation", "side_ratio"):
            p = ("P-05", "bands", name, field)
            out["/".join(p)] = _delta(_get(vec_a, p), _get(vec_b, p), "ratio", False)
    for name in _band_names(vec_a, vec_b, "P-06", "bands"):
        p = ("P-06", "bands", name, "mono_loss_db")
        out["/".join(p)] = _delta(_get(vec_a, p), _get(vec_b, p), "dB", False)
    return out


def compare(a, sr_a: int, b, sr_b: int, *, low_band_hz: float = 120.0) -> dict:
    """Level-matched comparison of a and b (both [frames, channels])."""
    if int(sr_a) != int(sr_b):
        raise InputError(f"sample rates differ ({sr_a} vs {sr_b}); resample before comparing",
                         details={"sr_a": int(sr_a), "sr_b": int(sr_b)})
    xa, xb = as_frames(a), as_frames(b)
    va = measure_signal(xa, sr_a, low_band_hz=low_band_hz)
    vb = measure_signal(xb, sr_b, low_band_hz=low_band_hz)
    la, lb = va["P-03"]["integrated_lufs"], vb["P-03"]["integrated_lufs"]
    if la is None or lb is None:
        raise InputError("cannot level-match: integrated loudness is undefined (silence or < 400 ms)",
                         details={"integrated_a": la, "integrated_b": lb})
    if la >= lb:
        side, gain = "a", lb - la
    else:
        side, gain = "b", la - lb
    if gain == 0.0:
        ma, mb = va, vb
    elif side == "a":
        ma, mb = measure_signal(xa * 10.0 ** (gain / 20.0), sr_a, low_band_hz=low_band_hz), vb
    else:
        ma, mb = va, measure_signal(xb * 10.0 ** (gain / 20.0), sr_b, low_band_hz=low_band_hz)
    before_il = _delta(la, lb, "LUFS", True)
    return json_safe({
        "match_gain_db": gain,
        "matched_side": side,
        "rule": "R-01: louder side lowered to the quieter integrated loudness; deltas are b - a after matching",
        "before": {"a": va, "b": vb, "integrated_delta": before_il},
        "after_match": {"a": ma, "b": mb},
        "deltas": deltas(ma, mb),
    })
