"""Cross-track ducking (UPGRADE2 §2): the ``duck`` op of a direction.

A key track's band envelope is turned into gain automation on a target track
(the same drawing path the floor planner already uses for its kick -> bass
ducking). Nothing here touches the core or the DSP: the key signal is read with
the public ``render_track`` (after cleanup, before the chain and the fader), the
hits and the envelope are computed here, and the result is a list of
``[sample, dB]`` break points written by ``direction.build_proposal``.

- the defaults follow the floor's ``knowledge/mix_rules.json`` ``ducking`` (read
  only), except ``depth_db`` (2.0 dB, shallower than the floor)
- the release is a note value by default (R-11, U-22); a release written in ms
  is recorded with the nearest note value and the deviation when the tempo is
  known; the recovery is verified on the envelope (``recovery``) and a poor
  ratio is a note, never a refusal
- ``merge_automation`` sums two break-point lists exactly (dB, piecewise linear;
  U-23)

The target goes down over its whole band (the key band only chooses the hits):
a band-limited duck on the target needs an external key in the DSP (UD-8).
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np

from mankomix.core.hashing import canonical_hash
from mankomix.dsp import processors as P

from . import query as Q

OP = "duck"
HOP_MS = 5.0
ACTIVE_DB = -150.0
EPS = 1e-20
DEPTH_DEFAULT_DB = 2.0
RECOVERED_MIN = 0.8
RELEASE_NOTES = tuple(n for n in P.NOTE_VALUES if n != "none")
DIGITS = 4

# id -> (lo, hi, may be a range [lo, hi])
PARAMS: dict[str, tuple[float, float, bool]] = {
    "depth_db": (0.5, 6.0, True),
    "key_lo_hz": (20.0, 2000.0, False),
    "key_hi_hz": (60.0, 12000.0, False),
    "trigger_below_p95_db": (3.0, 24.0, True),
    "attack_ms": (1.0, 30.0, True),
    "release_ms": (30.0, 600.0, True),
    "min_interval_ms": (30.0, 500.0, False),
}
KEY_LO_DEFAULT_HZ = 40.0
KEY_HI_DEFAULT_HZ = 120.0
KEY_BAND_RATIO = 1.5
ALLOWED = set(PARAMS) | {"key", "release_note"}

_HITS_CACHE: dict[str, list[int]] = {}


def floor_rules() -> dict:
    """The floor planner's ducking values (``knowledge/mix_rules.json``, read only)."""
    from mankomix.core import config
    return dict(config.load_knowledge("mix_rules").get("ducking") or {})


def defaults() -> dict:
    dk = floor_rules()
    return {"depth_db": DEPTH_DEFAULT_DB, "key_lo_hz": KEY_LO_DEFAULT_HZ, "key_hi_hz": KEY_HI_DEFAULT_HZ,
            "trigger_below_p95_db": float(dk.get("trigger_db_below_p95", 6.0)),
            "attack_ms": float(dk.get("attack_ms", 5.0)),
            "min_interval_ms": float(dk.get("min_interval_ms", 80.0)),
            "release_note_default": str(dk.get("release_note_default", "1/8")),
            "release_ms_without_bpm": float(dk.get("release_ms_without_bpm", 120.0))}


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _is_range(v: Any) -> bool:
    return isinstance(v, list) and len(v) == 2 and all(_num(x) for x in v)


def check_params(params: dict, target: Any, where: str, err, *, tracks: dict | None = None,
                 buses: dict | None = None, bpm: float | None = None, has_project: bool = False) -> None:
    """Form, ranges and safety of a duck move's ``params`` (validate's err format)."""
    if not isinstance(params, dict):
        err(where, "bad_value", "duck needs params (an object)")
        return
    extra = sorted(set(params) - ALLOWED)
    if extra:
        err(where, "bad_value", f"unknown duck parameters: {', '.join(extra)}")
    key = params.get("key")
    if not isinstance(key, str) or not key:
        err(where, "missing_field", "duck needs params.key (the track that triggers it)")
    elif key == target:
        err(where, "bad_value", "params.key must be a different track from the target")
    elif key == "master" or key.startswith("bus_") or (buses is not None and key in buses):
        err(where, "bad_target", "params.key must be a track (a bus or the master cannot key a duck)")
    elif has_project and tracks is not None and key not in tracks:
        err(where, "unknown_target", f"unknown key track '{key}'")
    for k, (lo, hi, rng) in PARAMS.items():
        if k not in params:
            continue
        v = params[k]
        vals = None
        if _num(v):
            vals = [float(v)]
        elif rng and _is_range(v):
            vals = [float(x) for x in v]
        if vals is None:
            err(where, "bad_value", f"{k} must be a number" + (" or a range [lo, hi]" if rng else
                                                            " (key_lo_hz / key_hi_hz are two separate keys)"
                                                            if k.startswith("key_") else ""))
            continue
        for x in vals:
            if not lo <= x <= hi:
                err(where, "param_range", f"{k} {x:g} outside [{lo:g}, {hi:g}]")
    klo = params.get("key_lo_hz", KEY_LO_DEFAULT_HZ)
    khi = params.get("key_hi_hz", KEY_HI_DEFAULT_HZ)
    if _num(klo) and _num(khi) and float(khi) < KEY_BAND_RATIO * float(klo):
        err(where, "param_range", f"key_hi_hz {float(khi):g} must be at least {KEY_BAND_RATIO:g} x key_lo_hz "
                                  f"{float(klo):g}")
    if "release_note" in params and "release_ms" in params:
        err(where, "bad_value", "write release_note or release_ms, not both")
    if "release_note" in params:
        if params["release_note"] not in RELEASE_NOTES:
            err(where, "bad_value", f"release_note must be a note value ({', '.join(RELEASE_NOTES)})")
        elif has_project and not (bpm and bpm > 0):
            err(where, "needs_bpm", "release_note needs the tempo of the floor proposal (tempo.bpm); "
                                    "write release_ms instead")


def floor_bpm(floor_mxp: dict | None) -> float | None:
    v = ((floor_mxp or {}).get("tempo") or {}).get("bpm")
    return float(v) if _num(v) and float(v) > 0 else None


def nearest_note(ms: float, bpm: float) -> tuple[str, float]:
    best, best_ms = RELEASE_NOTES[0], P.note_ms(RELEASE_NOTES[0], bpm)
    for n in RELEASE_NOTES[1:]:
        v = P.note_ms(n, bpm)
        if abs(v - ms) < abs(best_ms - ms):
            best, best_ms = n, v
    return best, best_ms


def release(params: dict, bpm: float | None) -> tuple[float, dict]:
    """(release in ms, the R-11 record). The note value is the default; ms is recorded with the nearest note."""
    d = defaults()
    if "release_ms" in params:
        ms = float(params["release_ms"])
        if bpm:
            note, nms = nearest_note(ms, bpm)
            return ms, {"note": note, "bpm": round(bpm, 3), "ms": round(ms, 2), "note_ms": round(nms, 2),
                        "deviation_ms": round(ms - nms, 2), "written": "ms", "rule": "R-11"}
        return ms, {"note": None, "bpm": None, "ms": round(ms, 2), "written": "ms", "rule": "R-11",
                    "note_reason": "tempo unknown: milliseconds used"}
    note = params.get("release_note")
    if note is None and bpm:
        note = d["release_note_default"]
    if note is not None:
        if not bpm:
            raise ValueError("needs_bpm: release_note needs the tempo of the floor proposal (tempo.bpm)")
        ms = P.note_ms(note, bpm)
        return ms, {"note": note, "bpm": round(bpm, 3), "ms": round(ms, 2), "rule": "R-11"}
    ms = d["release_ms_without_bpm"]
    return ms, {"note": None, "bpm": None, "ms": round(ms, 2), "rule": "R-11",
                "note_reason": "tempo unknown: milliseconds used"}


def full_params(params: dict) -> dict:
    """The resolved params with the defaults filled in (no release: see ``release``)."""
    d = defaults()
    out = {k: float(params.get(k, d[k])) for k in ("depth_db", "key_lo_hz", "key_hi_hz", "trigger_below_p95_db",
                                                   "attack_ms", "min_interval_ms")}
    out["key"] = params.get("key")
    return out


# ---------------------------------------------------------------------------
# hits and envelope (the floor's _ducking procedure, defined here)
# ---------------------------------------------------------------------------

def _frame_power(x: np.ndarray, hop: int) -> np.ndarray:
    a = x if x.ndim == 2 else x[:, None]
    pw = (a * a).mean(axis=1)
    n = pw.size // hop
    if n == 0:
        return np.array([float(pw.sum())])
    return pw[:n * hop].reshape(n, hop).mean(axis=1)


def detect_hits(x: np.ndarray, sr: int, p: dict) -> list[int]:
    """Onsets (samples) of the key band: rising crossings of p95 - trigger over the 5 ms frame power."""
    band = Q._bandpass(np.asarray(x, dtype=np.float64), sr, [p["key_lo_hz"], p["key_hi_hz"]])
    hop = max(1, int(HOP_MS * 1e-3 * sr))
    env = 10.0 * np.log10(_frame_power(band, hop) + EPS)
    act = env > ACTIVE_DB
    if not act.any():
        return []
    thr = float(np.percentile(env[act], 95)) - float(p["trigger_below_p95_db"])
    above = env > thr
    onsets = np.flatnonzero(above & ~np.concatenate([[False], above[:-1]])) * hop
    mi = int(float(p["min_interval_ms"]) * 1e-3 * sr)
    keep: list[int] = []
    for o in onsets:
        if not keep or o - keep[-1] >= mi:
            keep.append(int(o))
    return keep


def envelope(hits: list[int], sr: int, depth_db: float, attack_ms: float, release_ms: float) -> list[list]:
    """Three break points per hit: [hit - attack, 0], [hit, -depth], [end, 0]; positions strictly increasing.

    end = min(hit + release, next hit - attack - 1 sample)."""
    att = int(round(attack_ms * 1e-3 * sr))
    rel = int(round(release_ms * 1e-3 * sr))
    dep = -round(float(depth_db), DIGITS)
    pts: list[list] = []
    for i, o in enumerate(hits):
        a0 = max(0, o - att)
        if pts and a0 <= pts[-1][0]:
            a0 = pts[-1][0] + 1
        h = max(o, a0 + 1)
        end = o + rel
        if i + 1 < len(hits):
            end = min(end, hits[i + 1] - att - 1)
        end = max(end, h + 1)
        pts += [[int(a0), 0.0], [int(h), dep], [int(end), 0.0]]
    return pts


def recovery(hits: list[int], sr: int, attack_ms: float, release_ms: float) -> dict:
    """How many hits recover to 0 dB with their full release before the next hit starts to pull down."""
    att = int(round(attack_ms * 1e-3 * sr))
    rel = int(round(release_ms * 1e-3 * sr))
    n = len(hits)
    rec = sum(1 for i, o in enumerate(hits) if i + 1 >= n or o + rel < hits[i + 1] - att)
    iv = np.diff(np.asarray(hits, dtype=np.float64)) * 1000.0 / sr if n > 1 else np.array([])
    return {"hits": n, "recovered": rec, "recovered_ratio": round(rec / n, DIGITS) if n else None,
            "median_interval_ms": round(float(np.median(iv)), 2) if iv.size else None,
            "release_ms": round(float(release_ms), 2)}


def _points(a: list) -> tuple[np.ndarray, np.ndarray]:
    xs, ys = [], []
    for p in a or []:
        if isinstance(p, dict):
            xs.append(float(p.get("at")))
            ys.append(float(p.get("value")))
        else:
            xs.append(float(p[0]))
            ys.append(float(p[1]))
    if not xs:
        return np.array([]), np.array([])
    order = np.argsort(np.asarray(xs), kind="stable")
    return np.asarray(xs)[order], np.asarray(ys)[order]


def evaluate(a: list, t: np.ndarray) -> np.ndarray:
    """The automation value (dB) at positions ``t``, as the renderer reads it (linear in dB, ends held)."""
    xs, ys = _points(a)
    if xs.size == 0:
        return np.zeros(len(t))
    return np.interp(np.asarray(t, dtype=np.float64), xs, ys)


def merge_automation(a: list | None, b: list | None) -> list[list]:
    """The exact sum of two break-point lists: the union of positions, each value the sum of both."""
    xa, _ = _points(a or [])
    xb, _ = _points(b or [])
    if xa.size == 0 and xb.size == 0:
        return []
    xs = np.unique(np.concatenate([xa, xb]))
    vals = evaluate(a or [], xs) + evaluate(b or [], xs)
    return [[int(x) if float(x).is_integer() else float(x), round(float(v), 9) + 0.0] for x, v in zip(xs, vals)]


# ---------------------------------------------------------------------------
# a duck move on a project
# ---------------------------------------------------------------------------

def key_hits(root: str | Path, key: str, p: dict) -> tuple[list[int], int]:
    """(hits, sr) of the key track of the project at ``root`` (cached in-process on the project state)."""
    from mankomix.core import mixrender as mr
    from mankomix.core.project import Project
    root = Path(root)
    pj = root / "project.json"
    state = canonical_hash({"root": str(root.resolve()), "project": hashlib.sha256(pj.read_bytes()).hexdigest() if pj.is_file() else None,
                            "key": key, "band": [p["key_lo_hz"], p["key_hi_hz"]],
                            "trigger": p["trigger_below_p95_db"], "min_interval": p["min_interval_ms"]})
    if state in _HITS_CACHE:
        hits, sr = _HITS_CACHE[state]
        return list(hits), sr
    x, sr, _ = mr.render_track(Project.open(root), key, apply_chain=False, apply_fader=False)
    hits = detect_hits(x, sr, p)
    _HITS_CACHE[state] = (list(hits), sr)
    return hits, sr


def plan(root: str | Path, move: dict, params: dict, bpm: float | None) -> dict:
    """The envelope and the record of one duck move (params already resolved from their ranges)."""
    p = full_params(params)
    rel_ms, rel_rec = release(params, bpm)
    hits, sr = key_hits(root, p["key"], p)
    pts = envelope(hits, sr, p["depth_db"], p["attack_ms"], rel_ms)
    rec = recovery(hits, sr, p["attack_ms"], rel_ms)
    record = {"op": OP, "track": move.get("target"), "key": p["key"], "hits": len(hits),
              "depth_db": round(p["depth_db"], DIGITS), "attack_ms": round(p["attack_ms"], DIGITS),
              "release": rel_rec, "recovery": rec, "key_band_hz": [p["key_lo_hz"], p["key_hi_hz"]],
              "trigger_below_p95_db": p["trigger_below_p95_db"], "min_interval_ms": p["min_interval_ms"],
              "points": len(pts)}
    notes = []
    mid = move.get("id")
    if not hits:
        record["note"] = "no hit on the key band: nothing written"
        notes.append(f"{mid}: キー帯域の打点が 0 件（手は何も書いていない）")
    elif rec["recovered_ratio"] is not None and rec["recovered_ratio"] < RECOVERED_MIN:
        notes.append(f"{mid}: 回復が打点間隔に収まらない打点が {rec['hits'] - rec['recovered']}/{rec['hits']}。"
                     "より短い音価を検討")
    return {"points": pts, "record": record, "notes": notes, "sr": sr}
