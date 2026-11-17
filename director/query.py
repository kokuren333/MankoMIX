"""Observation quantities on rendered audio (minimal ``analyze query``; v2 I-5).

Deterministic and read-only. A primitive is computed on one stereo signal over
the whole song or a time range. Observation quantities never enter the gate;
they are what a direction claims it moves (``direction check`` compares them
with the floor after level matching, R-01).

Primitives (contract: ``docs/DIRECTION_FORMAT.md``):

- ``band_energy``  band power in dB (band_hz)
- ``band_ratio``   band power of band_hz over ref_band_hz, dB
- ``crest``        peak over RMS, dB (band_hz optional)
- ``loudness``     ``integrated`` (LUFS) or ``short_p95`` / ``short_p50`` / ``short_max``
- ``side_ratio``   side power over mid power, dB (band_hz optional)
- ``correlation``  L/R correlation coefficient (band_hz optional)
- ``image_position`` (E_R - E_L) / (E_R + E_L) over the range, E = sum of squares (band_hz optional,
                   4th order zero phase band-pass first); -1..+1, + = right (the ``pan`` direction).
                   An energy balance, not a pan position: a mono source panned to p with the
                   constant-power law reads sin(p*pi/2). Silence is ``status: error``

Only ``target: master`` (a rendered file) is supported here; a track's contribution
inside the mix (``trk_*``) is reported as unsupported. Track targets and the context
primitives are measured by ``director.stemobs`` (FBREVIEW FR-1 / FR-2).

Optional ``view`` (translation view; absent or ``stereo`` = the plain signal,
results unchanged): ``mono`` puts m = (L+R)/2 on both channels before
measuring; ``mono_band`` then band-passes it (``_bandpass``, 4th order, zero
phase) to ``view_band_hz`` (default 150-6000 Hz; lo 80-400, hi 3000-10000).
``side_ratio`` / ``correlation`` / ``image_position`` are refused under a mono view
(no side signal). ``side`` puts (L-R)/2 on both channels and supports only
``band_energy``, ``crest`` and ``loudness``; a silent side is missing data.
The view is computed in memory; no audio is written.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import signal as _sig

from mankomix.core.measure import loudness as L

PRIMITIVES = ("band_energy", "band_ratio", "crest", "loudness", "side_ratio", "correlation", "image_position")
LOUDNESS_STATS = ("integrated", "short_p95", "short_p50", "short_max")
VIEWS = ("stereo", "mono", "mono_band", "side")
MONO_VIEWS = ("mono", "mono_band")
SIDE_PRIMITIVES = ("band_energy", "crest", "loudness")
VIEW_BAND_DEFAULT_HZ = (150.0, 6000.0)
VIEW_BAND_LO_RANGE_HZ = (80.0, 400.0)
VIEW_BAND_HI_RANGE_HZ = (3000.0, 10000.0)
STEREO_ONLY_PRIMITIVES = ("side_ratio", "correlation", "image_position")
FRAME = 8192
EPS = 1e-20


class QueryError(ValueError):
    pass


def _stereo(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    return x[:, :2]


def section_range(section: Any, sections: list[dict] | None, duration_s: float) -> tuple[float, float]:
    """(t0, t1) in seconds for 'all', a section id or {t0_s, t1_s}."""
    if section in (None, "all"):
        return 0.0, duration_s
    if isinstance(section, dict):
        t0, t1 = float(section.get("t0_s", 0.0)), float(section.get("t1_s", duration_s))
    else:
        sec = next((s for s in sections or [] if s.get("id") == section), None)
        if sec is None:
            raise QueryError(f"unknown section '{section}'")
        t0, t1 = float(sec["start_s"]), float(sec["end_s"])
    t0, t1 = max(0.0, t0), min(duration_s, t1)
    if t1 - t0 < 0.4:
        raise QueryError(f"section {section!r} is shorter than 0.4 s")
    return t0, t1


def _band_power_frames(y: np.ndarray, sr: int, band: list[float]) -> np.ndarray:
    """Mean power per frame inside the band (mono signal), linear."""
    lo, hi = float(band[0]), float(band[1])
    if not (0 <= lo < hi):
        raise QueryError(f"bad band {band}")
    n = len(y)
    if n < FRAME:
        y = np.pad(y, (0, FRAME - n))
    f, _, Z = _sig.stft(y, fs=sr, window="hann", nperseg=FRAME, noverlap=FRAME // 2, boundary=None, padded=True)
    m = (f >= lo) & (f < hi)
    if not m.any():
        raise QueryError(f"band {band} holds no FFT bin")
    return (np.abs(Z[m, :]) ** 2).sum(axis=0)


def _db(v: float) -> float:
    return 10.0 * math.log10(max(float(v), EPS))


def _bandpass(y: np.ndarray, sr: int, band: list[float] | None) -> np.ndarray:
    if not band:
        return y
    lo, hi = float(band[0]), float(band[1])
    nyq = sr / 2.0
    hi = min(hi, nyq * 0.999)
    if lo <= 0:
        sos = _sig.butter(4, hi / nyq, btype="lowpass", output="sos")
    else:
        sos = _sig.butter(4, [lo / nyq, hi / nyq], btype="bandpass", output="sos")
    return _sig.sosfiltfilt(sos, y, axis=0)


def view_spec(obs: dict) -> tuple[str, tuple[float, float] | None]:
    """(view, band) of an observation; raises QueryError ('bad_value: ...') for a bad view."""
    view = obs.get("view")
    view = "stereo" if view is None else view
    if not isinstance(view, str) or view not in VIEWS:
        raise QueryError(f"bad_value: unknown view {view!r} (use one of {', '.join(VIEWS)})")
    if view == "side":
        if "view_band_hz" in obs:
            raise QueryError("bad_value: view_band_hz cannot be used with view: side")
        if obs.get("primitive") not in SIDE_PRIMITIVES:
            raise QueryError(f"bad_value: {obs.get('primitive')} has no meaning under view 'side' "
                             f"(use one of {', '.join(SIDE_PRIMITIVES)})")
        return view, None
    vb = obs.get("view_band_hz")
    if view != "mono_band":
        if vb is not None:
            raise QueryError("bad_value: view_band_hz needs view: mono_band")
        if view in MONO_VIEWS and obs.get("primitive") in STEREO_ONLY_PRIMITIVES:
            raise QueryError(f"bad_value: {obs.get('primitive')} has no meaning under view '{view}' (no side signal)")
        return view, None
    if obs.get("primitive") in STEREO_ONLY_PRIMITIVES:
        raise QueryError(f"bad_value: {obs.get('primitive')} has no meaning under view '{view}' (no side signal)")
    if vb is None:
        return view, VIEW_BAND_DEFAULT_HZ
    if not isinstance(vb, (list, tuple)) or len(vb) != 2 or             not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in vb):
        raise QueryError("bad_value: view_band_hz must be [lo, hi] in Hz")
    lo, hi = float(vb[0]), float(vb[1])
    if not (VIEW_BAND_LO_RANGE_HZ[0] <= lo <= VIEW_BAND_LO_RANGE_HZ[1]) or             not (VIEW_BAND_HI_RANGE_HZ[0] <= hi <= VIEW_BAND_HI_RANGE_HZ[1]):
        raise QueryError(f"bad_value: view_band_hz [{lo:g}, {hi:g}] out of range "
                         f"(lo {VIEW_BAND_LO_RANGE_HZ[0]:g}-{VIEW_BAND_LO_RANGE_HZ[1]:g}, "
                         f"hi {VIEW_BAND_HI_RANGE_HZ[0]:g}-{VIEW_BAND_HI_RANGE_HZ[1]:g})")
    return view, (lo, hi)


def apply_view(x: np.ndarray, sr: int, view: str, band: tuple[float, float] | None) -> np.ndarray:
    """The signal as heard through the view (stereo input, stereo output)."""
    if view == "side":
        s = (x[:, 0] - x[:, 1]) / 2.0
        return np.stack([s, s], axis=1)
    if view not in MONO_VIEWS:
        return x
    m = (x[:, 0] + x[:, 1]) / 2.0
    if view == "mono_band":
        m = _bandpass(m, sr, list(band or VIEW_BAND_DEFAULT_HZ))
    return np.stack([m, m], axis=1)


def observe(x: np.ndarray, sr: int, obs: dict, *, sections: list[dict] | None = None,
            gain_db: float = 0.0) -> dict:
    """Compute one observation. ``gain_db`` is applied first (level matching)."""
    if obs.get("view") == "side":
        view_spec(obs)
    prim = obs.get("primitive")
    if prim not in PRIMITIVES:
        raise QueryError(f"unknown primitive '{prim}'")
    target = obs.get("target", "master")
    if target != "master":
        return {"status": "unsupported", "reason": f"target '{target}': only 'master' is supported in v0"}
    view, vband = view_spec(obs)
    x = _stereo(x) * (10.0 ** (gain_db / 20.0))
    if view != "stereo":
        x = apply_view(x, sr, view, vband)
    dur = x.shape[0] / sr
    t0, t1 = section_range(obs.get("section", "all"), sections, dur)
    seg = x[int(round(t0 * sr)):int(round(t1 * sr))]
    if view == "side" and float(np.sum(seg ** 2)) <= EPS:
        return {"status": "error", "reason": "view 'side': the signal is silent in the range"}
    band = obs.get("band_hz")
    mono = seg.mean(axis=1)
    if prim == "band_energy":
        if not band:
            raise QueryError("band_energy needs band_hz")
        p = _band_power_frames(mono, sr, band)
        stat = obs.get("stat", "mean")
        v = {"mean": float(np.mean(p)), "p95": float(np.percentile(p, 95)), "max": float(np.max(p))}.get(stat)
        if v is None:
            raise QueryError(f"band_energy: unknown stat '{stat}'")
        val = _db(v / FRAME)
    elif prim == "band_ratio":
        ref = obs.get("ref_band_hz")
        if not band or not ref:
            raise QueryError("band_ratio needs band_hz and ref_band_hz")
        val = _db(np.mean(_band_power_frames(mono, sr, band))) - _db(np.mean(_band_power_frames(mono, sr, ref)))
    elif prim == "crest":
        y = _bandpass(seg, sr, band)
        peak = float(np.max(np.abs(y)))
        rms = float(np.sqrt(np.mean(y ** 2)))
        val = 20.0 * math.log10(max(peak, 1e-12)) - 20.0 * math.log10(max(rms, 1e-12))
    elif prim == "loudness":
        stat = obs.get("stat", "integrated")
        if stat == "integrated":
            val = float(L.integrated(seg, sr))
        elif stat in LOUDNESS_STATS:
            st = np.asarray(L.short_term(seg, sr), dtype=np.float64)
            st = st[np.isfinite(st)]
            if not len(st):
                raise QueryError("no short-term loudness value")
            val = float({"short_p95": np.percentile(st, 95), "short_p50": np.percentile(st, 50),
                         "short_max": np.max(st)}[stat])
        else:
            raise QueryError(f"loudness: unknown stat '{stat}'")
    elif prim == "side_ratio":
        m = (seg[:, 0] + seg[:, 1]) / 2.0
        s = (seg[:, 0] - seg[:, 1]) / 2.0
        if band:
            val = _db(np.mean(_band_power_frames(s, sr, band))) - _db(np.mean(_band_power_frames(m, sr, band)))
        else:
            val = _db(np.mean(s ** 2)) - _db(np.mean(m ** 2))
    elif prim == "image_position":
        y = _bandpass(seg, sr, band)
        el, er = float(np.sum(y[:, 0] ** 2)), float(np.sum(y[:, 1] ** 2))
        if el + er < EPS:
            return {"status": "error", "reason": "image_position: the signal is silent in the range"}
        val = (er - el) / (er + el)
    else:  # correlation
        y = _bandpass(seg, sr, band)
        a, b = y[:, 0], y[:, 1]
        den = math.sqrt(float(np.sum(a * a)) * float(np.sum(b * b)))
        val = float(np.sum(a * b)) / den if den > 0 else 0.0
    unit = "LUFS" if prim == "loudness" else ("" if prim in ("correlation", "image_position") else "dB")
    digits = 3 if view == "side" else 4
    return {"status": "ok", "value": round(float(val), digits), "unit": unit, "range_s": [round(t0, 3), round(t1, 3)],
            "gain_db": round(float(gain_db), digits)}


def integrated_lufs(x: np.ndarray, sr: int) -> float:
    return float(L.integrated(_stereo(x), sr))
