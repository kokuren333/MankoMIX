"""Stem-mix renderer (docs/SPEC.md 6.1.5, 6.5.1, 6.5.2, 9.2, 9.6; D-036, D-054).

Signal flow (fixed, per track)::

    clips -> [conform: resample to the project rate, head alignment, silence padding]
          -> clip gain x fades (muted clips are silent)
          -> track chain (dsp.engine.render_chain, stage "track")      = pre-fader
          -> track fader: gain_db x gain automation                    = post-fader
          -> pan (pan law by measured center attenuation) + width
          -> output bus  (and sends: pre- or post-fader, always post-pan)

    buses, in topological order of the routing graph:
          sum of inputs -> bus chain (stage "bus") -> bus gain_db -> output bus
    the single bus of kind "mix" is the end of the graph (stereo float64).

Conventions
-----------
* Time is counted in samples at the project sample rate (``timebase.sample_rate``).
  ``source_start`` / ``length`` / ``timeline_start`` / fades of a clip and the
  ``start`` / ``length`` of an excerpt all use that unit. ``length: null`` on a
  clip means "to the end of the asset".
* Conform policy (D-054) applied at render time only: assets whose rate differs
  from the project rate are resampled with ``scipy.signal.resample_poly`` (the
  reference backend, D-057); every asset starts at timeline sample 0 + the clip's
  ``timeline_start`` (head alignment); a clip that reaches past the end of its
  asset, and every track after its last clip, is silence. Each conversion that
  was applied is listed in ``record["conform"]["applied"]``.
* Mono assets are upmixed to dual mono inside the track (both channels equal).
  A track whose clips are all mono is panned with the mono pan law as long as
  its channels are still identical after the chain; otherwise it is treated as
  a stereo source. Assets with more than two channels are rejected.
* Fades: ``fade_in`` / ``fade_out`` are lengths in samples inside the clip.
  The curve is ``clip.fade_curve``: ``"equal_power"`` (default, quarter sine,
  -3 dB at the midpoint) or ``"linear"``. Gain at clip sample k (0-based):
  fade-in ``curve(k / fade_in)`` for k < fade_in; fade-out ``curve(j / fade_out)``
  with j = length - 1 - k for the last ``fade_out`` samples. Both multiply where
  they overlap. A split point without fades is a sample-exact butt splice.
* Gain automation (SPEC 9.2, v1 = gain only): ``track.automation.gain_db`` is a
  list of ``[timeline_sample, dB]`` breakpoints (or ``{"at", "value"}`` objects),
  linear in dB between breakpoints, held before the first and after the last.
  It multiplies the static ``gain_db`` (fader).
* Pan (SPEC 6.5.2): ``track.pan = {position -1..1, width >= 0}``; optional
  ``preset`` (``PAN_PRESETS``: L, LC, C, RC, R) + ``fine`` are used only when
  ``position`` is absent. The law is the measured per-channel attenuation of a
  centered mono source, ``mix.pan_law_center_db`` (default -3 dB = constant
  power; -4.5 dB and -6 dB = linear-sum law are supported, any value in
  [-6, 0]). Mono sources: L = m*gL(pos), R = m*gR(pos). Stereo sources: width
  scales the side signal (S = (L-R)/2; 0 = mono, 1 = as is, > 1 = wider), then
  a balance control normalised to the center gains (a centered stereo source is
  untouched; the far side follows the law; the near side is never boosted).
  This matches ``dsp.reference.basic.pan``.
* Sends: ``{bus, level_db (default 0), pre_fader (default false)}``. A post-fader
  send taps the panned post-fader signal; a pre-fader send taps the panned
  pre-fader signal (after the track chain, before the fader). Muting a track
  also mutes its sends. With any track soloed (``track.solo`` or the ``solo``
  argument), the other tracks are silent; buses keep running (solo-safe returns).
* Excerpts (SPEC 7.2 previews): ``start`` / ``length`` select a window of the
  timeline. When every active processor is stateless (gain, pan) the excerpt is
  bit-identical to the same slice of a full render. Otherwise the window is
  extended by a pre-roll (default 5 s, or ``preroll`` samples) and a post-roll
  (1 s) and the record says ``exact: false`` unless the pre-roll reached the
  timeline start and the post-roll its end.
* ``sr``: output rate. Rendering always happens at the project rate; a
  different ``sr`` resamples the result once at the end (recorded).
* The "Before" reference of D-036 is ``static_sum``: every stem asset at gain
  0 dB, stereo as is (mono to both channels), head-aligned, plain sum. It does
  not apply the pan law, clip edits, fades, mutes or any processing. It equals
  ``render_mix`` of an untouched project only when every stem is stereo (a
  centered stereo source passes the pan stage untouched); a mono stem is
  ``center_db`` lower in ``render_mix`` than in ``static_sum``.

Determinism: identical project data, assets, engine version and seed give
identical output (no randomness except what the engine derives from ``seed``).

Per-track render cache (performance only): the pre-fader signal of a track
(clips -> conform -> chain) over a processing window is kept in a
process-local LRU keyed by everything it depends on (asset sha256 + file
stat, applied cleanup plan hash, clip layout, canonical engine chain, project
rate, timeline length, window, seed, engine version). Mix-plan iterations that
change one track re-render only that track. A cache hit replays the render
record side effects (conform entries, backends, warnings, cleanup facts), so
outputs and records are identical with and without the cache.
``MANKOMIX_RENDER_CACHE_MB`` sets the budget (default 512; 0 disables).
"""

from __future__ import annotations

import copy
import math
import os
import threading
from collections import OrderedDict
from fractions import Fraction
from typing import Any

import numpy as np

import mankomix

from . import audio_io
from .errors import InputError, ValidationError
from .hashing import canonical_hash
from .ingest.checks import length_at_rate, project_sample_rate

# Discrete pan presets (first layer of SPEC 6.5.2's "LCR presets + fine").
PAN_PRESETS = {"L": -1.0, "LC": -0.5, "C": 0.0, "RC": 0.5, "R": 1.0}
# Pan laws documented and tested; any center attenuation in [-6, 0] dB works.
PAN_LAWS_DB = (-3.0, -4.5, -6.0)
DEFAULT_PAN_LAW_DB = -3.0

STATELESS_TYPES = frozenset({"gain", "pan"})
DEFAULT_PREROLL_S = 5.0
DEFAULT_POSTROLL_S = 1.0
FADE_CURVES = ("equal_power", "linear")
RESAMPLER = "scipy.signal.resample_poly"
_ENGINE_KEYS = ("id", "type", "params", "backend", "bypass", "note")


# --------------------------------------------------------------------------
# small helpers


def _db_to_lin(db: float) -> float:
    return float(10.0 ** (float(db) / 20.0))


def _r(v: Any, nd: int = 4) -> float | None:
    """JSON-safe rounded float (None for -inf/nan)."""
    if v is None:
        return None
    v = float(v)
    return round(v, nd) if math.isfinite(v) else None


def _peak_db(x: np.ndarray) -> float | None:
    if x.size == 0:
        return None
    p = float(np.max(np.abs(x)))
    return round(20.0 * math.log10(p), 4) if p > 0 else None


def _lufs(x: np.ndarray, sr: int) -> float | None:
    from .measure import loudness as ld
    if x.shape[0] < int(0.4 * sr):
        return None
    return _r(ld.integrated(x, sr))


def resample(x: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
    """Render-time resampling with the reference backend (resample_poly, D-057)."""
    if int(from_sr) == int(to_sr):
        return x
    from scipy.signal import resample_poly
    f = Fraction(int(to_sr), int(from_sr))
    return resample_poly(x, f.numerator, f.denominator, axis=0)


def engine_chain(chain: list[dict] | None) -> list[dict]:
    """Project processors -> engine steps: drop 'reason' etc.; enabled=false -> bypass."""
    out = []
    for p in chain or []:
        step = {k: copy.deepcopy(p[k]) for k in _ENGINE_KEYS if k in p and p[k] is not None}
        if p.get("enabled") is False:
            step["bypass"] = True
        out.append(step)
    return out


def _active_steps(chain: list[dict] | None) -> list[dict]:
    return [p for p in chain or [] if p.get("enabled") is not False and not p.get("bypass")]


def chain_is_stateful(chain: list[dict] | None) -> bool:
    """True when some active step depends on past/future samples (anything but gain/pan)."""
    return any(p.get("type") not in STATELESS_TYPES for p in _active_steps(chain))


# --------------------------------------------------------------------------
# pan


def pan_position(preset: str | None = None, fine: float = 0.0) -> float:
    """Position from a discrete preset (L, LC, C, RC, R) plus a fine offset, clamped to [-1, 1]."""
    base = 0.0
    if preset is not None:
        key = str(preset).upper()
        if key not in PAN_PRESETS:
            raise InputError(f"unknown pan preset '{preset}'", details={"valid": list(PAN_PRESETS)})
        base = PAN_PRESETS[key]
    return float(min(1.0, max(-1.0, base + float(fine or 0.0))))


def track_pan(track: dict) -> tuple[float, float]:
    """(position, width) of a track's pan field."""
    pan = track.get("pan") if isinstance(track.get("pan"), dict) else {}
    if pan.get("position") is not None:
        pos = float(pan["position"])
    elif pan.get("preset") is not None:
        pos = pan_position(pan.get("preset"), pan.get("fine", 0.0))
    else:
        pos = 0.0
    width = float(pan.get("width", 1.0) if pan.get("width") is not None else 1.0)
    if not -1.0 <= pos <= 1.0:
        raise InputError(f"pan position {pos} outside [-1, 1]")
    if width < 0:
        raise InputError(f"pan width {width} must be >= 0")
    return pos, width


def pan_gains(position: float, center_db: float = DEFAULT_PAN_LAW_DB) -> tuple[float, float]:
    """Per-channel gains for a mono source.

    gL = cos(theta)^k, gR = sin(theta)^k, theta = (position + 1) * pi / 4, with k
    chosen so that the center gain is exactly ``center_db``:
    k = center_db / (20 log10 cos(pi/4)). k = 1: -3.01 dB (constant power),
    k = 1.5: -4.5 dB, k = 2: -6.02 dB (linear sum), k = 0: no attenuation.
    """
    if not -6.0 - 1e-9 <= center_db <= 0.0:
        raise InputError(f"pan law center attenuation {center_db} dB outside [-6, 0]")
    k = center_db / (20.0 * math.log10(math.cos(math.pi / 4.0)))
    theta = (float(position) + 1.0) * math.pi / 4.0
    c, s = math.cos(theta), math.sin(theta)
    if k == 0.0:
        return (1.0 if c > 1e-15 else 0.0), (1.0 if s > 1e-15 else 0.0)
    gl = 0.0 if c <= 1e-15 else c ** k
    gr = 0.0 if s <= 1e-15 else s ** k
    return gl, gr


def pan_coefficients(position: float, width: float = 1.0, center_db: float = DEFAULT_PAN_LAW_DB,
                     *, mono: bool = False) -> dict:
    """Gains applied by :func:`pan_stereo`, for records and tests."""
    gl, gr = pan_gains(position, center_db)
    if mono:
        return {"mode": "mono_pan", "gain_l": gl, "gain_r": gr, "width": None}
    g0l, g0r = pan_gains(0.0, center_db)
    bl = min(1.0, gl / g0l) if g0l > 0 else 1.0
    br = min(1.0, gr / g0r) if g0r > 0 else 1.0
    return {"mode": "stereo_balance", "gain_l": bl, "gain_r": br, "width": float(width)}


def pan_stereo(x: np.ndarray, position: float = 0.0, width: float = 1.0,
               center_db: float = DEFAULT_PAN_LAW_DB, *, mono: bool = False) -> np.ndarray:
    """Pan (and set the width of) a track signal; returns a stereo float64 array.

    A 1-channel input, or ``mono=True``, uses the mono pan law (the mid signal is
    panned; width does not apply). Otherwise width scales the side signal and a
    balance control following the same law positions the stereo image.
    """
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    if a.shape[1] > 2:
        raise InputError("pan_stereo: only mono or stereo input is supported")
    is_mono = mono or a.shape[1] == 1
    co = pan_coefficients(position, width, center_db, mono=is_mono)
    if is_mono:
        m = a[:, 0] if a.shape[1] == 1 else 0.5 * (a[:, 0] + a[:, 1])
        return np.stack([m * co["gain_l"], m * co["gain_r"]], axis=1)
    left, right = a[:, 0], a[:, 1]
    if width != 1.0:
        mid = 0.5 * (left + right)
        side = 0.5 * (left - right) * float(width)
        left, right = mid + side, mid - side
    return np.stack([left * co["gain_l"], right * co["gain_r"]], axis=1)


# --------------------------------------------------------------------------
# project helpers


def project_rate(data: dict) -> int:
    pr = (data.get("timebase") or {}).get("sample_rate")
    if pr:
        return int(pr)
    assets = [a for a in data.get("assets") or [] if a.get("sample_rate")]
    if not assets:
        raise InputError("the project has no sample rate and no assets")
    return project_sample_rate(assets)


def _assets_by_id(data: dict) -> dict:
    return {a.get("id"): a for a in data.get("assets") or [] if isinstance(a, dict)}


def fullmix_asset_id(data: dict) -> str | None:
    fid = data.get("fullmix_asset")
    return fid if fid in _assets_by_id(data) else None


def is_stem_track(data: dict, track: dict) -> bool:
    """Tracks that carry stems (the full mix is a reference, never a track of the mix)."""
    if track.get("role") == "fullmix":
        return False
    fid = fullmix_asset_id(data)
    clips = track.get("clips") or []
    return not (fid is not None and clips and all(c.get("asset") == fid for c in clips))


def stem_tracks(data: dict) -> list[dict]:
    return [t for t in data.get("tracks") or [] if isinstance(t, dict) and is_stem_track(data, t)]


def find_track(data: dict, track_id: str) -> dict:
    for t in data.get("tracks") or []:
        if isinstance(t, dict) and t.get("id") == track_id:
            return t
    raise InputError(f"unknown track '{track_id}'",
                     details={"valid": [t.get("id") for t in data.get("tracks") or []]})


def asset_length_at(asset: dict, pr: int) -> int:
    n, sr = asset.get("length_samples"), asset.get("sample_rate")
    if n is None or not sr:
        raise InputError(f"asset '{asset.get('id')}' has no length / sample rate recorded")
    return length_at_rate(int(n), int(sr), int(pr))


def clip_length(data: dict, clip: dict, pr: int) -> int:
    """Resolved clip length in project samples (``length: null`` = to the end of the asset)."""
    if clip.get("length") is not None:
        return int(clip["length"])
    asset = _assets_by_id(data).get(clip.get("asset"))
    if asset is None:
        raise InputError(f"clip '{clip.get('id')}' refers to unknown asset '{clip.get('asset')}'")
    return max(0, asset_length_at(asset, pr) - int(clip.get("source_start", 0) or 0))


def timeline_length(data: dict, pr: int | None = None) -> int:
    """Project length: max of timebase.length_samples and the end of every stem clip."""
    pr = pr or project_rate(data)
    total = int((data.get("timebase") or {}).get("length_samples") or 0)
    for t in stem_tracks(data):
        for c in t.get("clips") or []:
            total = max(total, int(c.get("timeline_start", 0) or 0) + clip_length(data, c, pr))
    return total


def separated_notes(data: dict, track_ids: list[str] | None = None) -> list[dict]:
    """R-22 notes for tracks whose clips use separated stems."""
    by_id = _assets_by_id(data)
    out = []
    for t in data.get("tracks") or []:
        if track_ids is not None and t.get("id") not in track_ids:
            continue
        sep = sorted({c.get("asset") for c in t.get("clips") or []
                      if (by_id.get(c.get("asset")) or {}).get("origin") == "separated"})
        if sep:
            out.append({"rule": "R-22", "track": t.get("id"), "assets": sep,
                        "message": "separated stem: contains bleed from other parts; use it for balance "
                                   "adjustments, keep processing amounts small (R-22)"})
    return out


def apply_track_overrides(data: dict, overrides: dict | None) -> dict:
    """Return a copy of ``data`` with per-track parameter diffs applied (SPEC 9.4).

    ``overrides = {track_id: {key: value}}``; a ``pan`` dict is merged one level
    deep, every other key replaces the track's value. ``id`` cannot be changed.
    """
    out = copy.deepcopy(data)
    if not overrides:
        return out
    if not isinstance(overrides, dict):
        raise InputError("track overrides must be an object {track_id: {param: value}}")
    for tid, diff in overrides.items():
        track = find_track(out, tid)
        if not isinstance(diff, dict):
            raise InputError(f"overrides for track '{tid}' must be an object")
        for k, v in diff.items():
            if k == "id":
                raise InputError("track overrides cannot change the track id")
            if k == "pan" and isinstance(v, dict) and isinstance(track.get("pan"), dict):
                track["pan"] = {**track["pan"], **copy.deepcopy(v)}
            else:
                track[k] = copy.deepcopy(v)
    return out


def apply_bus_overrides(data: dict, overrides: dict | None) -> dict:
    """Return a copy of ``data`` with per-bus parameter diffs applied (``variants[].bus_overrides``,
    SPEC 9.4): ``{bus_id: {key: value}}``; every key replaces the bus's value, ``id`` cannot change."""
    out = copy.deepcopy(data)
    if not overrides:
        return out
    if not isinstance(overrides, dict):
        raise InputError("bus overrides must be an object {bus_id: {param: value}}")
    buses = {b.get("id"): b for b in out.get("buses") or [] if isinstance(b, dict)}
    for bid, diff in overrides.items():
        if bid not in buses:
            raise InputError(f"bus overrides refer to unknown bus '{bid}'", details={"valid": sorted(buses)})
        if not isinstance(diff, dict):
            raise InputError(f"overrides for bus '{bid}' must be an object")
        for k, v in diff.items():
            if k == "id":
                raise InputError("bus overrides cannot change the bus id")
            buses[bid][k] = copy.deepcopy(v)
    return out


def _variant(data: dict, variant_id: str) -> dict:
    for v in data.get("variants") or []:
        if v.get("id") == variant_id:
            return v
    raise InputError(f"unknown variant '{variant_id}'",
                     details={"valid": [v.get("id") for v in data.get("variants") or []]})


def effective_data(project, *, variant_id: str | None = None, overrides: dict | None = None) -> tuple[dict, dict]:
    """Project data with the variant's ``track_overrides`` / ``bus_overrides`` and then ``overrides`` applied."""
    data = project.data
    applied: dict[str, list[str]] = {}
    if variant_id is not None:
        v = _variant(data, variant_id)
        vo = v.get("track_overrides") or {}
        data = apply_track_overrides(data, vo)
        for tid, d in vo.items():
            applied.setdefault(tid, []).extend(sorted(d))
        bo = v.get("bus_overrides") or {}
        if bo:
            data = apply_bus_overrides(data, bo)
            for bid, d in bo.items():
                applied.setdefault(bid, []).extend(sorted(d))
    if overrides:
        data = apply_track_overrides(data, overrides)
        for tid, d in overrides.items():
            applied.setdefault(tid, []).extend(sorted(d))
    return data, applied


# --------------------------------------------------------------------------
# render context


class _Ctx:
    def __init__(self, project, data: dict, seed: int):
        self.project = project
        self.data = data
        self.pr = project_rate(data)
        self.total = timeline_length(data, self.pr)
        self.seed = int(seed)
        self.assets = _assets_by_id(data)
        self.audio: dict[str, np.ndarray] = {}
        self.applied: list[dict] = []
        self.pads: set[str] = set()
        self.warnings: list[str] = []
        self.backends: dict[str, Any] = {}
        self.used_assets: list[str] = []
        self.cleaned: dict[str, set[str]] = {}  # asset id -> plan hashes of the cleaned audio used
        self.meta: dict[str, tuple[int, int]] = {}  # audio key -> (file rate, frames at the project rate)
        self.registered: set[str] = set()
        self.touches: list[tuple] | None = None  # asset uses recorded for the track cache

    def asset_audio(self, aid: str, cleanup: dict | None = None) -> np.ndarray:
        """Audio of an asset at the project rate; ``cleanup`` (an applied cleanup entry)
        selects the cleaned cache instead of the raw asset (regenerated if missing)."""
        key = aid if cleanup is None else f"{aid}#clean:{cleanup.get('plan_hash')}"
        if key in self.audio:
            self._touch(aid, cleanup, key)
            return self.audio[key]
        asset = self.assets.get(aid)
        if asset is None:
            raise InputError(f"unknown asset '{aid}'")
        if cleanup is not None:
            from .cleanstage import asset_audio_path
            path = asset_audio_path(self.project, aid, cleanup)
        else:
            path = self.project.asset_path(aid)
        x, sr = audio_io.read(path)
        if x.shape[1] > 2:
            raise InputError(f"asset '{aid}' has {x.shape[1]} channels; v1 renders mono or stereo stems only")
        if sr != self.pr:
            x = resample(x, sr, self.pr)
        x = np.ascontiguousarray(x, dtype=np.float64)
        x.setflags(write=False)
        self.audio[key] = x
        self.meta[key] = (int(sr), int(x.shape[0]))
        self._touch(aid, cleanup, key)
        return x

    def _touch(self, aid: str, cleanup: dict | None, key: str) -> None:
        sr, frames = self.meta[key]
        if self.touches is not None:
            self.touches.append((aid, None if cleanup is None else copy.deepcopy(cleanup), sr, frames))
        self.register_asset(aid, cleanup, sr, frames)

    def register_asset(self, aid: str, cleanup: dict | None, sr: int, frames: int) -> None:
        """Record facts of an asset use (cleanup, conform, used assets) once per audio key."""
        key = aid if cleanup is None else f"{aid}#clean:{cleanup.get('plan_hash')}"
        if key in self.registered:
            return
        self.registered.add(key)
        if cleanup is not None:
            self.cleaned.setdefault(aid, set()).add(str(cleanup.get("plan_hash")))
        if sr != self.pr:
            f = Fraction(self.pr, sr)
            self.applied.append({"asset": aid, "from_rate": int(sr), "to_rate": self.pr,
                                 "action": "resample_at_render", "backend": RESAMPLER,
                                 "up": f.numerator, "down": f.denominator})
            self.backends.setdefault("resample", _resampler_version())
        if aid not in self.used_assets:
            self.used_assets.append(aid)
        if frames < self.total and aid not in self.pads:
            self.pads.add(aid)
            self.applied.append({"asset": aid, "from_rate": int(sr), "to_rate": self.pr,
                                 "action": "pad_silence_at_render", "asset_length": int(frames),
                                 "project_length": int(self.total)})

    def cleanup_record(self) -> dict:
        """Which assets entered the render cleaned (SPEC 6.4, 9.6)."""
        return {"applied": bool(self.cleaned),
                "assets": [{"asset": aid, "sha256": (self.assets.get(aid) or {}).get("sha256"),
                            "plan_hash": h} for aid in sorted(self.cleaned) for h in sorted(self.cleaned[aid])]}

    def conform_record(self) -> dict:
        policy = (self.data.get("timebase") or {}).get("conform_policy") or {}
        return {"policy": {k: policy.get(k) for k in ("sample_rate", "alignment", "short_assets")},
                "project_rate": self.pr, "alignment": "head", "applied": list(self.applied)}

    def run_chain(self, x: np.ndarray, chain: list[dict] | None, stage: str) -> tuple[np.ndarray, list[dict]]:
        steps = engine_chain(chain)
        if not steps:
            return x, []
        from mankomix.dsp import engine
        try:
            res = engine.render_chain(x, self.pr, steps, stage=stage, seed=self.seed)
        except ValueError as exc:
            raise ValidationError(f"cannot render {stage} chain: {exc}",
                                  details={"rule": getattr(exc, "rule", None),
                                           "step": getattr(exc, "step", None)}) from None
        self.backends.update(res.backends)
        self.warnings.extend(w for w in res.warnings if not w.startswith("S-09: DC"))
        if self.touches is not None:
            self.touches.append(("__chain__", dict(res.backends),
                                 [w for w in res.warnings if not w.startswith("S-09: DC")]))
        y = np.asarray(res.audio, dtype=np.float64)
        if y.shape[1] == 1:
            y = np.concatenate([y, y], axis=1)
        records = [{k: s.get(k) for k in ("id", "type", "backend", "bypass", "in_peak", "out_peak")
                    if k in s} for s in res.steps]
        return y, records


def _resampler_version() -> dict:
    import scipy
    return {"backend": RESAMPLER, "scipy": scipy.__version__}


def _curve(u: np.ndarray, kind: str) -> np.ndarray:
    if kind == "linear":
        return u
    return np.sin(0.5 * np.pi * u)


def _clip_envelope(k: np.ndarray, length: int, clip: dict) -> np.ndarray | None:
    """Fade envelope at clip-relative sample indices ``k`` (None when there are no fades)."""
    fi = min(int(clip.get("fade_in", 0) or 0), length)
    fo = min(int(clip.get("fade_out", 0) or 0), length)
    if fi <= 0 and fo <= 0:
        return None
    kind = clip.get("fade_curve") or "equal_power"
    if kind not in FADE_CURVES:
        raise InputError(f"clip '{clip.get('id')}': unknown fade_curve '{kind}'", details={"valid": FADE_CURVES})
    env = np.ones(k.shape[0], dtype=np.float64)
    if fi > 0:
        m = k < fi
        env[m] *= _curve(k[m] / fi, kind)
    if fo > 0:
        j = (length - 1) - k
        m = j < fo
        env[m] *= _curve(j[m] / fo, kind)
    return env


def _automation_env(track: dict, w0: int, n: int) -> np.ndarray | None:
    auto = track.get("automation") if isinstance(track.get("automation"), dict) else {}
    pts = auto.get("gain_db") or []
    if not pts:
        return None
    xs, ys = [], []
    for p in pts:
        if isinstance(p, dict):
            at, val = p.get("at"), p.get("value")
        else:
            at, val = p[0], p[1]
        xs.append(float(at))
        ys.append(float(val))
    order = np.argsort(np.asarray(xs), kind="stable")
    xs_a, ys_a = np.asarray(xs)[order], np.asarray(ys)[order]
    t = np.arange(w0, w0 + n, dtype=np.float64)
    return 10.0 ** (np.interp(t, xs_a, ys_a) / 20.0)


def _track_source(ctx: _Ctx, track: dict, w0: int, w1: int) -> tuple[np.ndarray, int, list[str]]:
    """Clip layout of a track on [w0, w1): (stereo signal, source channel count, clip ids used)."""
    n = w1 - w0
    buf = np.zeros((n, 2), dtype=np.float64)
    channels: set[int] = set()
    used: list[str] = []
    for clip in track.get("clips") or []:
        aid = clip.get("asset")
        asset = ctx.assets.get(aid)
        if asset is None:
            raise InputError(f"clip '{clip.get('id')}' refers to unknown asset '{aid}'")
        ch = int(asset.get("channels") or 2)
        if clip.get("muted"):
            continue
        ts = int(clip.get("timeline_start", 0) or 0)
        ss = int(clip.get("source_start", 0) or 0)
        length = clip_length(ctx.data, clip, ctx.pr)
        a, b = max(ts, w0), min(ts + length, w1)
        if a >= b:
            channels.add(ch)
            continue
        from .cleanstage import track_cleanup_entry
        src = ctx.asset_audio(aid, track_cleanup_entry(track, aid))
        channels.add(src.shape[1])
        used.append(clip.get("id"))
        i0, i1 = ss + (a - ts), ss + (b - ts)
        seg = src[min(i0, src.shape[0]):min(i1, src.shape[0])]
        if seg.shape[1] == 1:
            seg = np.repeat(seg, 2, axis=1)
        g = _db_to_lin(clip.get("gain_db", 0.0) or 0.0)
        env = _clip_envelope(np.arange(a - ts, a - ts + seg.shape[0], dtype=np.float64), length, clip)
        if env is not None:
            seg = seg * (env * g)[:, None]
        elif g != 1.0:
            seg = seg * g
        buf[a - w0:a - w0 + seg.shape[0]] += seg  # the part past the asset end stays silent
    return buf, (1 if channels == {1} else 2), used


# --------------------------------------------------------------------------
# per-track render cache (performance only; see the module docstring)


_CACHE_LOCK = threading.Lock()
_TRACK_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_CACHE_STATS = {"hits": 0, "misses": 0, "bytes": 0}
DEFAULT_CACHE_MB = 512


def _cache_budget() -> int:
    try:
        mb = float(os.environ.get("MANKOMIX_RENDER_CACHE_MB", DEFAULT_CACHE_MB))
    except ValueError:
        mb = DEFAULT_CACHE_MB
    return max(0, int(mb * 1024 * 1024))


def clear_track_cache() -> None:
    with _CACHE_LOCK:
        _TRACK_CACHE.clear()
        _CACHE_STATS.update(hits=0, misses=0, bytes=0)


def track_cache_info() -> dict:
    with _CACHE_LOCK:
        return {"entries": len(_TRACK_CACHE), "budget_bytes": _cache_budget(), **_CACHE_STATS}


def _file_stamp(path) -> list:
    try:
        st = os.stat(path)
        return [os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns]
    except OSError:
        return [str(path), None, None]


def _track_key(ctx: _Ctx, track: dict, w0: int, w1: int, chain: list[dict] | None) -> str | None:
    """Everything the pre-fader signal of ``track`` on [w0, w1) depends on (None: do not cache)."""
    from .cleanstage import track_cleanup_entry
    clips = []
    for clip in track.get("clips") or []:
        aid = clip.get("asset")
        asset = ctx.assets.get(aid)
        if asset is None:
            return None
        ce = track_cleanup_entry(track, aid)
        try:
            stamp = _file_stamp(ctx.project.asset_path(aid))
        except Exception:  # noqa: BLE001 - an unresolvable asset is reported by the real render
            return None
        clips.append({"clip": clip, "asset": asset, "file": stamp,
                      "cleanup": None if ce is None else {"plan_hash": ce.get("plan_hash"),
                                                          "asset_sha256": ce.get("asset_sha256")}})
    try:
        return canonical_hash({"v": 1, "engine": mankomix.ENGINE_VERSION, "pr": ctx.pr, "total": ctx.total,
                               "window": [int(w0), int(w1)], "seed": ctx.seed, "clips": clips,
                               "chain": engine_chain(chain),
                               "native": os.environ.get("MANKOMIX_NATIVE_LIB")})
    except (TypeError, ValueError):
        return None


def _track_pre(ctx: _Ctx, track: dict, w0: int, w1: int,
               chain: list[dict] | None) -> tuple[np.ndarray, int, list[str], list[dict]]:
    """Pre-fader signal of a track on [w0, w1): clips -> conform -> chain (cached)."""
    budget = _cache_budget()
    key = _track_key(ctx, track, w0, w1, chain) if budget > 0 else None
    if key is not None:
        with _CACHE_LOCK:
            hit = _TRACK_CACHE.get(key)
            if hit is not None:
                _TRACK_CACHE.move_to_end(key)
                _CACHE_STATS["hits"] += 1
        if hit is not None:
            for t in hit["touches"]:
                if t[0] == "__chain__":
                    ctx.backends.update(t[1])
                    ctx.warnings.extend(t[2])
                else:
                    ctx.register_asset(*t)
            return hit["x"].copy(), hit["src_ch"], list(hit["clips"]), copy.deepcopy(hit["steps"])
    outer = ctx.touches
    ctx.touches = [] if key is not None else outer
    try:
        x, src_ch, clips = _track_source(ctx, track, w0, w1)
        steps: list[dict] = []
        if chain:
            x, steps = ctx.run_chain(x, chain, "track")
        touches = ctx.touches
    finally:
        ctx.touches = outer
    if key is not None:
        if outer is not None:
            outer.extend(touches)
        stored = np.array(x, dtype=np.float64, copy=True)
        stored.setflags(write=False)
        size = int(stored.nbytes)
        with _CACHE_LOCK:
            _CACHE_STATS["misses"] += 1
            if size <= budget:
                old = _TRACK_CACHE.pop(key, None)
                if old is not None:
                    _CACHE_STATS["bytes"] -= int(old["x"].nbytes)
                _TRACK_CACHE[key] = {"x": stored, "src_ch": src_ch, "clips": list(clips),
                                     "steps": copy.deepcopy(steps), "touches": touches}
                _CACHE_STATS["bytes"] += size
                while _CACHE_STATS["bytes"] > budget and _TRACK_CACHE:
                    _, ev = _TRACK_CACHE.popitem(last=False)
                    _CACHE_STATS["bytes"] -= int(ev["x"].nbytes)
    return x, src_ch, clips, steps


def _window(ctx: _Ctx, start: int | None, length: int | None, stateful: bool,
            preroll: int | None) -> tuple[int, int, int, int]:
    """(s0, n, w0, w1): requested excerpt and the processing window around it."""
    total = ctx.total
    s0 = 0 if start is None else int(start)
    if s0 < 0:
        raise InputError("start must be >= 0")
    if total == 0:
        raise InputError("nothing to render: the timeline is empty")
    if s0 >= total:
        raise InputError(f"start {s0} is past the end of the timeline ({total} samples)")
    n = total - s0 if length is None else min(int(length), total - s0)
    if n <= 0:
        raise InputError("length must be > 0")
    if stateful:
        pre = int(round(DEFAULT_PREROLL_S * ctx.pr)) if preroll is None else max(0, int(preroll))
        post = int(round(DEFAULT_POSTROLL_S * ctx.pr))
    else:
        pre = post = 0
    w0 = max(0, s0 - pre)
    w1 = min(total, s0 + n + post)
    return s0, n, w0, w1


def _range_record(ctx: _Ctx, s0: int, n: int, w0: int, w1: int, stateful: bool) -> dict:
    exact = (not stateful) or (w0 == 0 and w1 == ctx.total)
    return {"start": s0, "length": n, "timeline_length": ctx.total, "excerpt": not (s0 == 0 and n == ctx.total),
            "preroll": s0 - w0, "postroll": w1 - (s0 + n), "exact": exact}


def _finish(ctx: _Ctx, x: np.ndarray, sr: int | None) -> tuple[np.ndarray, int]:
    out_sr = ctx.pr if sr is None else int(sr)
    if out_sr != ctx.pr:
        f = Fraction(out_sr, ctx.pr)
        x = resample(x, ctx.pr, out_sr)
        ctx.applied.append({"asset": None, "from_rate": ctx.pr, "to_rate": out_sr, "action": "resample_output",
                            "backend": RESAMPLER, "up": f.numerator, "down": f.denominator})
        ctx.backends.setdefault("resample", _resampler_version())
    return np.ascontiguousarray(x, dtype=np.float64), out_sr


def _base_record(ctx: _Ctx, kind: str, applied: dict | None = None, variant_id: str | None = None) -> dict:
    proj = ctx.project
    rec = {
        "kind": kind,
        "engine_version": mankomix.ENGINE_VERSION,
        "project_id": proj.data.get("id"),
        "project_hash": proj.content_hash(),
        "seed": ctx.seed,
    }
    if applied:
        rec["variant"] = variant_id
        rec["overrides_applied"] = applied
        rec["effective_hash"] = canonical_hash(ctx.data)
    elif variant_id is not None:
        rec["variant"] = variant_id
    return rec


def _asset_hashes(ctx: _Ctx) -> list[dict]:
    return [{"id": aid, "sha256": ctx.assets[aid].get("sha256"), "origin": ctx.assets[aid].get("origin")}
            for aid in sorted(ctx.used_assets)]


# --------------------------------------------------------------------------
# public API


def render_track(project, track_id: str, *, sr: int | None = None, seed: int = 0, start: int | None = None,
                 length: int | None = None, apply_chain: bool = True, apply_fader: bool = True,
                 preroll: int | None = None, variant_id: str | None = None,
                 overrides: dict | None = None) -> tuple[np.ndarray, int, dict]:
    """Render one track, pre-pan: clips -> chain (stage "track") -> fader. Stereo float64.

    ``apply_chain=False`` skips the track chain; ``apply_fader=False`` skips the
    track gain and gain automation (clip gains and fades always apply). Track
    mute/solo flags are ignored here (they belong to the mix).
    """
    data, applied = effective_data(project, variant_id=variant_id, overrides=overrides)
    ctx = _Ctx(project, data, seed)
    track = find_track(data, track_id)
    chain = track.get("chain") if apply_chain else None
    stateful = chain_is_stateful(chain)
    s0, n, w0, w1 = _window(ctx, start, length, stateful, preroll)
    x, src_ch, clips, steps = _track_pre(ctx, track, w0, w1, chain)
    if apply_fader:
        g = _db_to_lin(track.get("gain_db", 0.0) or 0.0)
        env = _automation_env(track, w0, w1 - w0)
        x = x * g if env is None else x * (env * g)[:, None]
    x = x[s0 - w0:s0 - w0 + n]
    x, out_sr = _finish(ctx, x, sr)
    rec = _base_record(ctx, "track", applied, variant_id)
    rec.update({
        "track": track_id, "role": track.get("role"), "sample_rate": out_sr, "project_rate": ctx.pr,
        "frames": int(x.shape[0]), "channels": 2, "source_channels": src_ch,
        "range": _range_record(ctx, s0, n, w0, w1, stateful),
        "apply_chain": bool(apply_chain), "apply_fader": bool(apply_fader), "clips": clips, "chain": steps,
        "peak_dbfs": _peak_db(x), "conform": ctx.conform_record(), "assets": _asset_hashes(ctx),
        "cleanup": ctx.cleanup_record(), "backends": ctx.backends, "warnings": ctx.warnings,
        "notes": separated_notes(data, [track_id]),
    })
    return x, out_sr, rec


def _mix_bus_id(data: dict) -> str:
    mixes = [b.get("id") for b in data.get("buses") or [] if b.get("kind") == "mix"]
    if len(mixes) != 1:
        raise ValidationError(f"exactly one bus of kind 'mix' is required (found {len(mixes)})")
    return mixes[0]


def bus_order(data: dict) -> list[str]:
    """Topological order of the bus graph (inputs before outputs); raises on loops / unknown buses."""
    buses = {b.get("id"): b for b in data.get("buses") or [] if isinstance(b, dict)}
    mix = _mix_bus_id(data)
    out: dict[str, str] = {}
    for bid, b in buses.items():
        if bid == mix:
            if b.get("output"):
                raise ValidationError("the mix bus is the final bus and has no output")
            continue
        dest = b.get("output") or mix
        if dest not in buses:
            raise ValidationError(f"bus '{bid}' outputs to unknown bus '{dest}'")
        if dest == bid:
            raise ValidationError(f"bus routing loop: '{bid}' outputs to itself")
        out[bid] = dest
    indeg = {bid: 0 for bid in buses}
    for dest in out.values():
        indeg[dest] += 1
    ready = [bid for bid in buses if indeg[bid] == 0]  # project order, deterministic
    order: list[str] = []
    while ready:
        bid = ready.pop(0)
        order.append(bid)
        dest = out.get(bid)
        if dest is not None:
            indeg[dest] -= 1
            if indeg[dest] == 0:
                ready.append(dest)
    if len(order) != len(buses):
        stuck = sorted(b for b in buses if b not in order)
        raise ValidationError("bus routing loop: " + ", ".join(stuck), details={"buses": stuck})
    return order


def render_mix(project, *, variant_id: str | None = None, sr: int | None = None, seed: int = 0,
               start: int | None = None, length: int | None = None, solo: list[str] | None = None,
               mute: list[str] | None = None, stems_out: dict | None = None, overrides: dict | None = None,
               preroll: int | None = None, measure: bool = True) -> tuple[np.ndarray, int, dict]:
    """Render the stem mix to stereo float64 at the project rate (or ``sr``).

    ``solo`` / ``mute``: extra track ids soloed / muted for this render only.
    ``stems_out``: optional dict filled with ``{track_id: post-fader, post-pan
    stereo signal}`` (same range and rate as the output) for audible tracks.
    ``overrides``: in-memory per-track parameter diffs (applied after the
    variant's ``track_overrides``). ``measure``: per-track / per-bus peak and
    integrated loudness in the record.
    """
    data, applied = effective_data(project, variant_id=variant_id, overrides=overrides)
    ctx = _Ctx(project, data, seed)
    order = bus_order(data)
    mix_id = _mix_bus_id(data)
    buses = {b["id"]: b for b in data.get("buses") or []}
    center_db = float((data.get("mix") or {}).get("pan_law_center_db", DEFAULT_PAN_LAW_DB))
    tracks = stem_tracks(data)
    known = {t.get("id") for t in data.get("tracks") or []}
    for tid in list(solo or []) + list(mute or []):
        if tid not in known:
            raise InputError(f"unknown track '{tid}'", details={"valid": sorted(known)})
    solo_set = set(solo or []) | {t["id"] for t in tracks if t.get("solo")}
    mute_set = set(mute or []) | {t["id"] for t in tracks if t.get("muted")}

    def audible(t: dict) -> bool:
        return t["id"] not in mute_set and (not solo_set or t["id"] in solo_set)

    active = [t for t in tracks if audible(t)]
    for t in active:
        dest = t.get("output") or mix_id
        if dest not in buses:
            raise ValidationError(f"track '{t['id']}' outputs to unknown bus '{dest}'")
        for s in t.get("sends") or []:
            if s.get("bus") not in buses:
                raise ValidationError(f"track '{t['id']}' sends to unknown bus '{s.get('bus')}'")
    stateful = any(chain_is_stateful(t.get("chain")) for t in active) or \
        any(chain_is_stateful(b.get("chain")) for b in buses.values())
    s0, n, w0, w1 = _window(ctx, start, length, stateful, preroll)
    lo, hi = s0 - w0, s0 - w0 + n
    bus_in = {bid: np.zeros((w1 - w0, 2), dtype=np.float64) for bid in order}

    track_recs: list[dict] = []
    for t in tracks:
        tid = t["id"]
        trec: dict[str, Any] = {"id": tid, "role": t.get("role"), "output": t.get("output") or mix_id,
                                "muted": tid in mute_set, "soloed": tid in solo_set, "audible": audible(t)}
        if not audible(t):
            track_recs.append(trec)
            continue
        x, src_ch, clips, steps = _track_pre(ctx, t, w0, w1, t.get("chain"))
        pre = x
        g = _db_to_lin(t.get("gain_db", 0.0) or 0.0)
        env = _automation_env(t, w0, w1 - w0)
        post = pre * g if env is None else pre * (env * g)[:, None]
        pos, width = track_pan(t)
        mono = src_ch == 1 and np.array_equal(pre[:, 0], pre[:, 1])
        panned = pan_stereo(post, pos, width, center_db, mono=mono)
        bus_in[trec["output"]] += panned
        co = pan_coefficients(pos, width, center_db, mono=mono)
        send_recs = []
        panned_pre = None
        for s in t.get("sends") or []:
            lvl = _db_to_lin(s.get("level_db", 0.0) if s.get("level_db") is not None else 0.0)
            if s.get("pre_fader"):
                if panned_pre is None:
                    panned_pre = pan_stereo(pre, pos, width, center_db, mono=mono)
                bus_in[s["bus"]] += panned_pre * lvl
            else:
                bus_in[s["bus"]] += panned * lvl
            send_recs.append({"bus": s["bus"], "level_db": s.get("level_db", 0.0),
                              "pre_fader": bool(s.get("pre_fader", False))})
        out_slice = panned[lo:hi]
        if stems_out is not None:
            stems_out[tid] = out_slice.copy()
        trec.update({
            "source_channels": src_ch, "clips": clips, "chain": steps, "gain_db": t.get("gain_db", 0.0),
            "automation": env is not None,
            "pan": {"position": pos, "width": width, "mode": co["mode"],
                    "gain_l_db": _r(20 * math.log10(co["gain_l"]) if co["gain_l"] > 0 else None, 6),
                    "gain_r_db": _r(20 * math.log10(co["gain_r"]) if co["gain_r"] > 0 else None, 6)},
            "sends": send_recs,
        })
        if measure:
            trec["peak_dbfs"] = _peak_db(out_slice)
            trec["lufs_i"] = _lufs(out_slice, ctx.pr)
        track_recs.append(trec)

    bus_recs: list[dict] = []
    mix = None
    for bid in order:
        b = buses[bid]
        y, steps = ctx.run_chain(bus_in[bid], b.get("chain"), "bus")
        g = _db_to_lin(b.get("gain_db", 0.0) or 0.0)
        if g != 1.0:
            y = y * g
        brec = {"id": bid, "kind": b.get("kind"), "output": None if bid == mix_id else (b.get("output") or mix_id),
                "chain": steps, "gain_db": b.get("gain_db", 0.0)}
        if measure:
            brec["peak_dbfs"] = _peak_db(y[lo:hi])
            brec["lufs_i"] = _lufs(y[lo:hi], ctx.pr)
        bus_recs.append(brec)
        if bid == mix_id:
            mix = y
        else:
            bus_in[brec["output"]] += y
    assert mix is not None
    out, out_sr = _finish(ctx, mix[lo:hi], sr)
    if stems_out is not None and out_sr != ctx.pr:
        for tid in list(stems_out):
            stems_out[tid] = resample(stems_out[tid], ctx.pr, out_sr)
    rec = _base_record(ctx, "stem_mix", applied, variant_id)
    rec.update({
        "sample_rate": out_sr, "project_rate": ctx.pr, "frames": int(out.shape[0]), "channels": 2,
        "range": _range_record(ctx, s0, n, w0, w1, stateful),
        "pan_law_center_db": center_db, "bus_order": order,
        "conform": ctx.conform_record(), "assets": _asset_hashes(ctx), "cleanup": ctx.cleanup_record(),
        "tracks": track_recs, "buses": bus_recs,
        "peak_dbfs": _peak_db(out), "backends": ctx.backends, "warnings": ctx.warnings,
        "notes": separated_notes(data, [t["id"] for t in active]),
    })
    return out, out_sr, rec


def static_sum(project, sr: int | None = None, *, assets: list[str] | None = None,
               cleaned: bool = False) -> tuple[np.ndarray, int, dict]:
    """The "Before" reference (D-036): plain sum of the stem assets, gain 0 dB, no processing.

    Every stem asset (each once, in track order; the full mix and unused assets
    excluded) is head-aligned at timeline sample 0, resampled to the project
    rate when needed and summed stereo as is (mono to both channels). Clip
    edits, gains, fades, mutes, pan law and chains are all ignored.
    ``assets`` selects the asset ids explicitly. ``cleaned=True`` sums the
    cleaned audio of every asset whose cleanup was applied (the cleaned
    reference of the S-08 baseline); the default is the raw "Before".
    """
    data = project.data
    ctx = _Ctx(project, data, 0)
    if assets is None:
        fid = fullmix_asset_id(data)
        ids: list[str] = []
        for t in stem_tracks(data):
            for c in t.get("clips") or []:
                aid = c.get("asset")
                if aid not in ids and aid != fid and (ctx.assets.get(aid) or {}).get("origin") != "reference_fullmix":
                    ids.append(aid)
    else:
        ids = list(assets)
    if not ids:
        raise InputError("no stem assets to sum")
    total = max([int((data.get("timebase") or {}).get("length_samples") or 0)]
                + [asset_length_at(ctx.assets[a], ctx.pr) if a in ctx.assets else 0 for a in ids])
    ctx.total = total
    out = np.zeros((total, 2), dtype=np.float64)
    entries: dict = {}
    if cleaned:
        from .cleanstage import applied_entry
        entries = {aid: applied_entry(data, aid) for aid in ids}
    for aid in ids:
        x = ctx.asset_audio(aid, entries.get(aid))
        if x.shape[1] == 1:
            out[:x.shape[0]] += x  # broadcast to both channels
        else:
            out[:x.shape[0]] += x
    out, out_sr = _finish(ctx, out, sr)
    rec = _base_record(ctx, "static_sum")
    rec.update({"definition": "D-036: stem assets at gain 0 dB, stereo as is, head-aligned, unprocessed sum",
                "sample_rate": out_sr, "project_rate": ctx.pr, "frames": int(out.shape[0]), "channels": 2,
                "summed_assets": ids, "conform": ctx.conform_record(), "assets": _asset_hashes(ctx),
                "cleanup": {**ctx.cleanup_record(), "requested": bool(cleaned)},
                "backends": ctx.backends, "peak_dbfs": _peak_db(out)})
    return out, out_sr, rec


__all__ = [
    "PAN_PRESETS", "PAN_LAWS_DB", "DEFAULT_PAN_LAW_DB", "FADE_CURVES",
    "render_track", "render_mix", "static_sum", "pan_stereo", "pan_gains", "pan_coefficients",
    "pan_position", "track_pan", "bus_order", "engine_chain", "chain_is_stateful", "apply_track_overrides",
    "effective_data", "apply_bus_overrides", "stem_tracks", "is_stem_track", "find_track", "clip_length", "timeline_length",
    "project_rate", "asset_length_at", "separated_notes", "resample", "clear_track_cache", "track_cache_info",
]
