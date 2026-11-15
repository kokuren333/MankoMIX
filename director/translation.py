"""Translation observation (翻訳観察): how a master holds up on a small mono playback.

``direction check --translation`` adds a ``translation`` block to the outcome
(design: ``_private/design/UPGRADE2_PROPOSAL.md`` §3.5). The block is a
reference value only: no claim, expectation, guard, summary, calibration or
gate reads it. Without the flag the outcome is unchanged.

Every quantity is an observation of ``director.query`` under a view
(``stereo`` / ``mono`` / ``mono_band``), computed in memory on the rendered
floor and result (the result after the same level matching as the
observations). No audio is written.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from . import query as Q

NOTE = "参考値。どの判定にも入らない（主張・期待・ガード・summary・ゲート）"
MONO_BAND_HZ = [float(Q.VIEW_BAND_DEFAULT_HZ[0]), float(Q.VIEW_BAND_DEFAULT_HZ[1])]
LOW_FUND_HZ = [40.0, 150.0]          # low fundamentals (stereo)
LOW_HARM_HZ = [150.0, 400.0]         # their harmonics as a small speaker passes them (mono_band)
PRESENCE_HZ = [1000.0, 4000.0]
BODY_HZ = [150.0, 1000.0]
KEYS = ("mono_fold_lu", "small_speaker_lu", "low_harmonic_db", "presence_db", "crest_db")
DIGITS = 4


def _v(x: np.ndarray, sr: int, obs: dict, gain_db: float) -> float | None:
    try:
        r = Q.observe(x, sr, obs, gain_db=gain_db)
    except Q.QueryError:
        return None
    return float(r["value"]) if r.get("status") == "ok" else None


def _sub(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(a - b, DIGITS)


def measure(x: np.ndarray, sr: int, gain_db: float = 0.0) -> dict[str, float | None]:
    """The five translation quantities of one signal (after ``gain_db``)."""
    mb = {"view": "mono_band"}
    lu_st = _v(x, sr, {"primitive": "loudness"}, gain_db)
    lu_mono = _v(x, sr, {"primitive": "loudness", "view": "mono"}, gain_db)
    lu_band = _v(x, sr, {"primitive": "loudness", **mb}, gain_db)
    harm = _v(x, sr, {"primitive": "band_energy", "band_hz": LOW_HARM_HZ, **mb}, gain_db)
    fund = _v(x, sr, {"primitive": "band_energy", "band_hz": LOW_FUND_HZ}, gain_db)
    pres = _v(x, sr, {"primitive": "band_ratio", "band_hz": PRESENCE_HZ, "ref_band_hz": BODY_HZ, **mb}, gain_db)
    crest = _v(x, sr, {"primitive": "crest", **mb}, gain_db)
    return {
        "mono_fold_lu": _sub(lu_mono, lu_st),
        "small_speaker_lu": _sub(lu_band, lu_st),
        "low_harmonic_db": _sub(harm, fund),
        "presence_db": round(pres, DIGITS) if pres is not None else None,
        "crest_db": round(crest, DIGITS) if crest is not None else None,
    }


def block(result: np.ndarray, floor: np.ndarray, sr: int, match_gain_db: float) -> dict[str, Any]:
    """The outcome's ``translation`` block: {note, view, <key>: {floor, result, change}}.

    ``match_gain_db`` is the level-matching gain applied to the result (as for the
    observations); the floor is measured as rendered.
    """
    f = measure(floor, sr, 0.0)
    r = measure(result, sr, float(match_gain_db))
    out: dict[str, Any] = {"note": NOTE, "view": {"mono_band_hz": list(MONO_BAND_HZ)}}
    for k in KEYS:
        out[k] = {"floor": f[k], "result": r[k], "change": _sub(r[k], f[k])}
    return out
