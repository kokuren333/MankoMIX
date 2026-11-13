"""Wiring of the native core into the engine (SPEC 3.2, 9.6).

- ``implementations()`` returns the ``native`` backend table used by
  ``engine.render_chain``: the Airwindows ports (``aw.*`` types) and native
  variants of the dynamics processors whose ballistics run in the native
  kernel (``compressor``, ``dynamic_eq``, ``deesser``; the level detector and
  gain stage stay in numpy, the output is bit-identical to the reference).
- ``fallback_params(type, params)`` maps the parameters of an ``aw.*`` step to
  its declared reference fallback (``processors.PROCESSORS[type]["fallback"]``).

Every implementation has the reference signature
``fn(x, sr, params, *, seed=0) -> (y, sr_out, stats)``. Native processors are
rendered in one block; their latency is compensated (the output is aligned
with the input and keeps its length).
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np

from . import processors as P
from .errors import DSPError

_LN10_20 = math.log(10.0) / 20.0


def native_available() -> bool:
    try:
        from . import native_backend
        return native_backend.available()
    except Exception:  # pragma: no cover - probing must never break rendering
        return False


def unavailable_reason() -> str:
    try:
        from . import native_backend
        return native_backend.load_error() or "native library unavailable"
    except Exception as exc:  # pragma: no cover
        return f"native backend import failed: {exc}"


def native_types() -> list[str]:
    """Processor types implemented only by the native core (``aw.*``)."""
    return [t for t, d in P.PROCESSORS.items() if "native" in d and d["backends"] == ["native"]]


# ---------------------------------------------------------------------------
# measurements recorded for native steps
# ---------------------------------------------------------------------------

def _rms_db(x: np.ndarray) -> float | None:
    if x.size == 0:
        return None
    e = float(np.mean(x * x))
    return round(10.0 * math.log10(e), 4) if e > 0 else None


def _crest_db(x: np.ndarray) -> float | None:
    """Peak-to-RMS ratio (PAR) over the whole signal, all channels pooled."""
    if x.size == 0:
        return None
    e = float(np.mean(x * x))
    pk = float(np.max(np.abs(x)))
    return round(20.0 * math.log10(pk) - 10.0 * math.log10(e), 4) if e > 0 and pk > 0 else None


def _native_render(native_id: str, x: np.ndarray, sr: int, params: dict) -> tuple[np.ndarray, int]:
    from . import native_backend as nb

    n, ch = x.shape
    if ch > nb.MAX_CHANNELS:
        raise DSPError(f"native processor {native_id}: {ch} channels exceed the native limit "
                       f"{nb.MAX_CHANNELS}", rule="backend")
    with nb.NativeProcessor(native_id, sr, ch, params) as proc:
        lat = proc.latency
        buf = np.concatenate([x, np.zeros((lat, ch))], axis=0) if lat else x
        y = proc.process(buf)
    return y[lat:lat + n], lat


def _make_aw(ptype: str) -> Callable:
    d = P.PROCESSORS[ptype]
    nid = d["native"]["id"]
    abstract = d.get("abstract_type")

    def fn(x: np.ndarray, sr: int, p: dict, **_):
        y, lat = _native_render(nid, x, sr, p)
        stats: dict = {
            "native_id": nid,
            "abstract_type": abstract,
            "role": d["native"].get("role"),
            "origin": dict(d["native"]["origin"]),
            "latency_samples": lat,
            "latency_compensated": True,
            "level": {"rms_in_db": _rms_db(x), "rms_out_db": _rms_db(y)},
        }
        c_in, c_out = _crest_db(x), _crest_db(y)
        stats["crest_factor"] = {"in_db": c_in, "out_db": c_out,
                                 "change_db": (round(c_out - c_in, 4)
                                               if c_in is not None and c_out is not None else None)}
        if abstract in ("saturator", "clipper"):
            from .reference.nonlinear import harmonic_profile
            amp = 0.5
            if ptype == "aw.clip_only2":
                c = 10.0 ** (p["ceiling_db"] / 20.0)
                g = 10.0 ** (p["input_gain_db"] / 20.0)
                amp = min(1.0, 2.0 * c / g)

            def curve(u):
                return _native_render(nid, u, 48000, p)[0]
            stats["harmonics"] = harmonic_profile(curve, amplitude=amp)
        if ptype == "aw.pressure4" and stats["crest_factor"]["change_db"] is not None \
                and stats["crest_factor"]["change_db"] > 0:
            stats["note"] = ("measured crest factor increased (Pressure4 at mewiness > 0 can raise "
                             "PAR); do not use it to reduce peak-to-average ratio")
        return y, sr, stats

    fn.__name__ = f"native_{ptype.replace('.', '_')}"
    return fn


def _make_ballistic(fn_ref: Callable) -> Callable:
    def fn(x: np.ndarray, sr: int, p: dict, **kw):
        y, sr_out, stats = fn_ref(x, sr, p, ballistics_impl="native")
        stats = dict(stats)
        stats["native_kernel"] = "mmx_smooth_attack_release"
        return y, sr_out, stats

    fn.__name__ = f"native_{fn_ref.__name__}"
    return fn


def implementations() -> dict[str, Callable]:
    """``native`` backend table (empty when the library is unavailable)."""
    if not native_available():
        return {}
    from . import native_backend as nb
    from .reference import dynamics, dyneq

    table: dict[str, Callable] = {}
    compiled = {info["id"] for info in nb.processors()}
    for t in native_types():
        if P.PROCESSORS[t]["native"]["id"] in compiled:
            table[t] = _make_aw(t)
    if nb.has_smoother():
        table["compressor"] = _make_ballistic(dynamics.compressor)
        table["dynamic_eq"] = _make_ballistic(dyneq.dynamic_eq)
        table["deesser"] = _make_ballistic(dyneq.deesser)
    return table


# ---------------------------------------------------------------------------
# fallbacks (native unavailable)
# ---------------------------------------------------------------------------

def _db_clamped(lin: float, lo: float, hi: float) -> float:
    if lin <= 0:
        return lo
    return float(min(hi, max(lo, 20.0 * math.log10(lin))))


def _fb_purest_drive(p: dict) -> tuple[dict, list[str]]:
    return {"mode": "tanh", "drive_db": 0.0, "mix": p["drive"]}, []


def _fb_clip_only2(p: dict) -> tuple[dict, list[str]]:
    notes = []
    if p["input_gain_db"] < 0:
        notes.append(f"negative input_gain_db {p['input_gain_db']} dropped (clipper drive >= 0)")
    return {"mode": "soft", "softness": 0.1, "ceiling_db": p["ceiling_db"],
            "drive_db": max(0.0, p["input_gain_db"])}, notes


def _fb_console7_channel(p: dict) -> tuple[dict, list[str]]:
    return {"gain_db": round(_db_clamped((p["fader"] * 1.272019649514069) ** 2, -60.0, 24.0), 6)}, []


def _fb_console7_buss(p: dict) -> tuple[dict, list[str]]:
    return {"gain_db": round(_db_clamped(p["master"] * 1.03, -60.0, 24.0), 6)}, []


def _fb_pressure4(p: dict) -> tuple[dict, list[str]]:
    q = p["pressure"]
    notes = [] if p["mewiness"] == 0 else ["mewiness has no counterpart in the compressor (ignored)"]
    return {"threshold_db": -6.0 - 24.0 * q, "ratio": 1.0 + 5.0 * q, "knee_db": 12.0,
            "attack_ms": 10.0, "release_ms": 40.0 + 460.0 * (1.0 - p["speed"]), "detector": "rms",
            "makeup_db": round(_db_clamped(p["output_gain"], -12.0, 24.0), 6)}, notes


_FALLBACK_MAPS: dict[str, Callable[[dict], tuple[dict, list[str]]]] = {
    "aw.purest_drive": _fb_purest_drive,
    "aw.clip_only2": _fb_clip_only2,
    "aw.console7_channel": _fb_console7_channel,
    "aw.console7_buss": _fb_console7_buss,
    "aw.pressure4": _fb_pressure4,
}


def fallback_params(ptype: str, params: dict) -> tuple[str, dict, list[str]]:
    """(reference type, validated params, notes) of the declared fallback of ``ptype``."""
    d = P.PROCESSORS.get(ptype, {})
    fb = d.get("fallback")
    if not fb or ptype not in _FALLBACK_MAPS:
        raise DSPError(f"processor {ptype!r} declares no fallback mapping", rule="backend")
    mapped, notes = _FALLBACK_MAPS[ptype](params)
    return fb["type"], P.validate_params(fb["type"], mapped), notes


__all__ = ["implementations", "fallback_params", "native_available", "native_types",
           "unavailable_reason"]
