"""Mastering route selection and master-input loading (SPEC 6.6.1, R-21).

Routes:

- ``full_mix``: the 2-mix asset is the master input, cleaned when a cleanup
  was applied to it (SPEC 6.6.1: "the 2mix with cleanup only"; see
  core/cleanstage.py). Default when a full mix exists and no mix-stage result
  exists, and the default when the only stems are separated ones.
- ``stem_mix``: the mix-stage output is the master input: the stem mix
  rendered by ``core.mixrender.render_mix`` (clips, cleaned stems, track
  chains, faders and gain automation, pan, sends, buses and the mix-bus
  chain, seed 0). With a variant, its ``track_overrides`` / ``bus_overrides``
  apply (SPEC 9.4), so variants with different mixes get different master
  inputs. The S-08 noise baseline of this route (``cleanstage.route_baseline``)
  is measured on this same signal: the guard checks that mastering does not
  raise the noise of the mix it is given.
- ``stem_sum``: only stems exist and no mix stage has run. The master input
  is a static, unprocessed, head-aligned sum of the track clips (clip gain,
  track gain and mutes respected; no track chains, no pan). This is a
  documented stand-in until the M4 mix stage.

Stem routes read the cleaned audio of every stem whose track has an applied
cleanup (the same rule as core/mixrender.py).

The project file stores ``master.route`` with the schema vocabulary
("fullmix" / "stem_mix"); the finer route name is kept in
``master.route_detail``.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import resample_poly

from . import audio_io
from .errors import InputError

ROUTES = ("full_mix", "stem_mix", "stem_sum")
SCHEMA_ROUTE = {"full_mix": "fullmix", "stem_mix": "stem_mix", "stem_sum": "stem_mix"}


# --------------------------------------------------------------------------
# helpers


def _assets_by_id(data: dict) -> dict:
    return {a.get("id"): a for a in data.get("assets", []) or []}


def fullmix_asset_id(data: dict) -> str | None:
    """Asset id of the full mix: ``fullmix_asset`` or an asset with role fullmix."""
    fid = data.get("fullmix_asset")
    assets = _assets_by_id(data)
    if fid and fid in assets:
        return fid
    for a in data.get("assets", []) or []:
        if a.get("role") == "fullmix" or a.get("origin") == "reference_fullmix":
            return a.get("id")
    return None


def stem_tracks(data: dict) -> list[dict]:
    """Tracks that carry stems (not the full mix)."""
    fid = fullmix_asset_id(data)
    out = []
    for t in data.get("tracks", []) or []:
        if t.get("role") == "fullmix":
            continue
        clips = t.get("clips", []) or []
        if clips and all(c.get("asset") == fid for c in clips):
            continue
        out.append(t)
    return out


def _stem_origins(data: dict) -> set[str]:
    assets = _assets_by_id(data)
    origins = set()
    for t in stem_tracks(data):
        for c in t.get("clips", []) or []:
            a = assets.get(c.get("asset"))
            if a is not None:
                origins.add(a.get("origin") or "native_stem")
    return origins


def has_mix_results(data: dict) -> bool:
    """True when a mix stage has been applied (any track or bus chain, or a mix record)."""
    mix = data.get("mix") or {}
    if mix.get("applied") or mix.get("plan_applied"):
        return True
    for t in stem_tracks(data):
        if t.get("chain"):
            return True
    for b in data.get("buses", []) or []:
        if b.get("chain"):
            return True
    return False


# --------------------------------------------------------------------------
# route selection


def select_route(project) -> dict:
    """Choose the mastering route (R-21). Returns {route, reason, rule}."""
    data = project.data
    fid = fullmix_asset_id(data)
    stems = stem_tracks(data)
    origins = _stem_origins(data)
    mixed = has_mix_results(data)

    if not stems and fid is None:
        raise InputError("project has neither a full mix nor stems; nothing to master")

    if stems and mixed:
        if origins and origins <= {"separated"} and fid is not None:
            return {"route": "full_mix", "rule": "R-21",
                    "reason": {"ja": "ステムは分離由来のみ。再合算でアーティファクトが累積しうるため、フルミックス経路を既定とした",
                               "en": "Only separated stems exist; re-summing can accumulate artifacts, so the full-mix route is the default"}}
        return {"route": "stem_mix", "rule": "R-21",
                "reason": {"ja": "ステムとミックス段の結果があるため、ステムミックス経路を選んだ",
                           "en": "Stems with mix-stage results exist, so the stem-mix route was chosen"}}

    if fid is not None:
        if stems and origins and origins <= {"separated"}:
            return {"route": "full_mix", "rule": "R-21",
                    "reason": {"ja": "ステムは分離由来のみ。再合算でアーティファクトが累積しうるため、フルミックス経路を既定とした",
                               "en": "Only separated stems exist; re-summing can accumulate artifacts, so the full-mix route is the default"}}
        return {"route": "full_mix", "rule": "R-21",
                "reason": {"ja": "2mix があり、ミックス段の結果がまだないため、フルミックス経路を選んだ",
                           "en": "A 2-mix exists and no mix-stage result exists yet, so the full-mix route was chosen"}}

    return {"route": "stem_sum", "rule": "R-21",
            "reason": {"ja": "ステムのみでミックス段の結果がない。ステムを無加工・ゲイン 0 で合算したものをマスター入力とした（M4 のミックス段までの代替）",
                       "en": "Only stems and no mix-stage result: the unprocessed unity-gain sum of the stems is the master input (stand-in until the M4 mix stage)"}}


# --------------------------------------------------------------------------
# master input


def project_rate(data: dict, fallback: int | None = None) -> int:
    sr = (data.get("timebase") or {}).get("sample_rate")
    if sr:
        return int(sr)
    if fallback:
        return int(fallback)
    for a in data.get("assets", []) or []:
        if a.get("sample_rate"):
            return int(a["sample_rate"])
    return 48000


def _to_stereo(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if x.shape[1] == 1:
        return np.repeat(x, 2, axis=1)
    return x[:, :2].copy()


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """In-memory polyphase resampling (scipy). Identity when rates match."""
    if int(sr_in) == int(sr_out):
        return x
    g = math.gcd(int(sr_in), int(sr_out))
    up, down = int(sr_out) // g, int(sr_in) // g
    return resample_poly(x, up, down, axis=0)


def _read_asset(project, asset_id: str, sr: int, cleanup: dict | None = None) -> np.ndarray:
    """Asset audio at ``sr`` (stereo); ``cleanup`` (applied cleanup entry) reads the cleaned cache."""
    from .cleanstage import asset_audio_path
    path = asset_audio_path(project, asset_id, cleanup)
    x, sr_in = audio_io.read(path)
    return _to_stereo(resample(x, sr_in, sr))


def _db_to_lin(db: float) -> float:
    return float(10.0 ** (float(db) / 20.0))


def load_master_input(project, route: str | dict | None = None, *,
                      variant_id: str | None = None) -> tuple[np.ndarray, int]:
    """Return (x[frames, 2] float64, project sample rate) for the given route.

    ``variant_id``: the variant whose mix overrides apply on the ``stem_mix`` route (ignored when the
    variant does not exist yet, e.g. while its first master plan is being made)."""
    if isinstance(route, dict):
        route = route.get("route")
    if route is None:
        route = select_route(project)["route"]
    if route == "fullmix":
        route = "full_mix"
    data = project.data
    sr = project_rate(data)

    if route == "full_mix":
        fid = fullmix_asset_id(data)
        if fid is None:
            raise InputError("route full_mix needs a full-mix asset")
        from .cleanstage import fullmix_cleanup_entry
        return _read_asset(project, fid, sr, fullmix_cleanup_entry(data)), sr

    if route not in ("stem_sum", "stem_mix"):
        raise InputError(f"unknown mastering route: {route}")

    if route == "stem_mix":
        from .mixrender import render_mix
        known = {v.get("id") for v in data.get("variants") or [] if isinstance(v, dict)}
        vid = variant_id if variant_id in known else None
        x, rsr, _ = render_mix(project, variant_id=vid, seed=0, measure=False)
        return x, int(rsr)

    tracks = stem_tracks(data)
    solo = any(t.get("solo") for t in tracks)
    pieces = []
    cache: dict[str, np.ndarray] = {}
    for t in tracks:
        if t.get("muted") or (solo and not t.get("solo")):
            continue
        tgain = _db_to_lin(t.get("gain_db", 0.0) or 0.0)
        for c in t.get("clips", []) or []:
            if c.get("muted"):
                continue
            aid = c.get("asset")
            from .cleanstage import track_cleanup_entry
            ce = track_cleanup_entry(t, aid)
            key = aid if ce is None else f"{aid}#clean:{ce.get('plan_hash')}"
            if key not in cache:
                cache[key] = _read_asset(project, aid, sr, ce)
            src = cache[key]
            s0 = int(c.get("source_start", 0) or 0)
            n = c.get("length")
            seg = src[s0:] if n is None else src[s0:s0 + int(n)]
            seg = seg * (tgain * _db_to_lin(c.get("gain_db", 0.0) or 0.0))
            fi, fo = int(c.get("fade_in", 0) or 0), int(c.get("fade_out", 0) or 0)
            if fi > 0 and seg.shape[0] > 0:
                k = min(fi, seg.shape[0])
                seg = seg.copy()
                seg[:k] *= np.linspace(0.0, 1.0, k, endpoint=False)[:, None]
            if fo > 0 and seg.shape[0] > 0:
                k = min(fo, seg.shape[0])
                seg = seg.copy()
                seg[-k:] *= np.linspace(1.0, 0.0, k, endpoint=True)[:, None]
            pieces.append((int(c.get("timeline_start", 0) or 0), seg))

    if not pieces:
        raise InputError("no audible clips to sum for the master input")
    length = (data.get("timebase") or {}).get("length_samples")
    end = max(start + seg.shape[0] for start, seg in pieces)
    total = max(int(length or 0), end)
    out = np.zeros((total, 2), dtype=np.float64)
    for start, seg in pieces:
        out[start:start + seg.shape[0]] += seg
    return out, sr


def route_warnings(route: str) -> list[dict]:
    if route == "stem_sum":
        return [{"code": "stem_sum_stand_in", "rule": "R-21",
                 "message": {"ja": "マスター入力はステムの無加工合算（ゲイン 0）。ミックス段（M4）が実装されるまでの代替",
                             "en": "Master input is the unprocessed unity-gain stem sum, a stand-in until the M4 mix stage"}}]
    return []
