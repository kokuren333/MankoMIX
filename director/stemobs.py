"""Track-context observation quantities (FBREVIEW FR-1 / FR-2). Read-only.

An observation whose ``target`` is a track (``trk_<stem>``) is measured on the
signal of that track inside the mix stage, rendered by core
(``mixrender.render_mix``) from the project as it is:

- ``path: "dry"`` (default): the track as it enters its output bus (cleaned
  clips -> track chain -> fader / gain automation -> pan / width), i.e. the
  ``stems_out`` entry of one render of the whole mix
- ``path: "solo"``: the mix bus output with only that track audible (send
  returns and bus processing included; before the master stage)

The six single-signal primitives of ``query`` are computed exactly as on the
master (``query.observe`` on that signal). No level matching: a track signal is
before the master stage, so it is measured at gain 0 (``gain_db: 0.0``,
``signal: "mix_stage"``, ``path``).

Context primitives (``CONTEXT_PRIMITIVES``; not in ``query.PRIMITIVES`` because
one signal is not enough):

- ``masking``: ``core.analysis.stems.masking_matrix`` (P-02) on the dry
  signals of every audible track; ``target: trk_x`` -> buried dB of x against
  all others (``against: trk_y`` -> one pair; ``band_hz`` -> mean over the ERB
  bands whose centre is in [lo, hi)); ``target: "all"`` -> the weighted overall
- ``wet_ratio``: A = the solo render, B = the same with the track's sends
  emptied; 10*log10(E(A-B) / E(B)) dB, floored at -120.0 (no send)

Nothing is written into the project: the cleanup caches must already be valid
(core would regenerate a missing cache inside the project); otherwise the
observation is ``status: error`` and nothing is rendered. Renders are kept in
the process (``StemSource``) and use ``measure=False``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from . import query as Q

CONTEXT_PRIMITIVES = ("masking", "wet_ratio")
NEW_PRIMITIVES = ("image_position",) + CONTEXT_PRIMITIVES
PATHS = ("dry", "solo")
WET_FLOOR_DB = -120.0
SIGNAL = "mix_stage"
CACHE_ERROR = "整音の cache が無いか古い。先に clean apply／render する"
EPS = Q.EPS


class StemObsError(ValueError):
    pass


def is_track_target(target: Any) -> bool:
    return isinstance(target, str) and target.startswith("trk_") and len(target) > 4


def needs_stems(obs: dict) -> bool:
    """True when the observation is measured from the project's tracks (not from a rendered file)."""
    return is_track_target(obs.get("target", "master")) or obs.get("primitive") in CONTEXT_PRIMITIVES


def all_primitives() -> tuple[str, ...]:
    return tuple(Q.PRIMITIVES) + CONTEXT_PRIMITIVES


def _band_ok(band: Any) -> bool:
    return (isinstance(band, (list, tuple)) and len(band) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in band)
            and 0 <= float(band[0]) < float(band[1]))


def spec_errors(o: dict) -> list[tuple[str, str, str]]:
    """Form and range of the fields FR-1 / FR-2 add (G-2): [(where suffix, code, message)].

    Empty for an observation that uses none of them (an existing direction is untouched)."""
    prim = o.get("primitive")
    target = o.get("target", "master")
    trk = is_track_target(target)
    out: list[tuple[str, str, str]] = []
    if "path" in o:
        p = o.get("path")
        if prim in CONTEXT_PRIMITIVES:
            out.append((".path", "bad_value", f"{prim} has no path (masking is measured dry; wet_ratio compares "
                                              "solo renders with and without the sends)"))
        elif not trk:
            out.append((".path", "bad_value", f"path is for a track target (trk_<stem>) only, not '{target}'"))
        elif p not in PATHS:
            out.append((".path", "bad_value", f"unknown path {p!r} (use one of {', '.join(PATHS)})"))
    if prim in CONTEXT_PRIMITIVES and ("view" in o or "view_band_hz" in o):
        out.append((".view", "bad_value", f"{prim} has no view"))
    if prim == "masking":
        if not (trk or target == "all"):
            out.append((".target", "bad_target", f"masking needs a track target (trk_<stem>) or 'all', not '{target}'"))
        if "against" in o:
            ag = o.get("against")
            if target == "all":
                out.append((".against", "bad_value", "against cannot be used with target 'all'"))
            elif not is_track_target(ag):
                out.append((".against", "bad_value", f"against must be a track id (trk_<stem>), not {ag!r}"))
            elif ag == target:
                out.append((".against", "bad_value", "against must differ from the target"))
            if o.get("band_hz") is not None and target != "all":
                out.append((".band_hz", "bad_value", "band_hz cannot be used with against (one pair is full band)"))
        if target == "all" and o.get("band_hz") is not None:
            out.append((".band_hz", "bad_value", "band_hz cannot be used with target 'all'"))
    elif prim == "wet_ratio":
        if not trk:
            out.append((".target", "bad_target", f"wet_ratio needs a track target (trk_<stem>), not '{target}'"))
    elif prim == "image_position":
        if not (trk or target == "master"):
            out.append((".target", "bad_target", f"image_position needs 'master' or a track target, not '{target}'"))
    elif "against" in o:
        out.append((".against", "bad_value", "against is a field of masking only"))
    if prim in NEW_PRIMITIVES and o.get("band_hz") is not None and not _band_ok(o.get("band_hz")):
        out.append((".band_hz", "bad_value", "band_hz must be [lo, hi] in Hz with 0 <= lo < hi"))
    return out


# ---------------------------------------------------------------------------
# read-only access to the project's track signals
# ---------------------------------------------------------------------------

def cleanup_cache_error(pobj, tracks: list[dict]) -> str | None:
    """``CACHE_ERROR`` when a cleaned clip of ``tracks`` has no valid cleanup cache (core would
    regenerate it inside the project on render), else None. Shared with ``refsheet``."""
    from mankomix.core import cleanstage
    for t in tracks:
        for c in t.get("clips") or []:
            aid = c.get("asset")
            e = cleanstage.track_cleanup_entry(t, aid)
            if e is None:
                continue
            asha = pobj.asset(aid).get("sha256") or ""
            if e.get("asset_sha256") not in (None, asha) or \
                    cleanstage._cache_valid(pobj, asha, str(e.get("plan_hash"))) is None:
                return CACHE_ERROR
    return None


class StemSource:
    """Track signals of one project state (``variant_id``), rendered on demand and kept in the process.

    ``dry()`` renders the whole mix once (``stems_out``); ``solo(trk)`` renders once per track
    (and once more without its sends for ``wet_ratio``). Never writes into the project."""

    def __init__(self, root: str | Path, variant_id: str | None = None):
        self.root = Path(root)
        self.variant_id = variant_id
        self._opened = False
        self._error: str | None = None
        self._pobj = None
        self._tracks: dict[str, dict] = {}
        self._audible: set[str] = set()
        self._dry: tuple[dict, int] | None = None
        self._solo: dict[tuple[str, bool], tuple[np.ndarray, int]] = {}
        self._meta: tuple[dict, str | None] | None = None

    def _open(self) -> None:
        if self._opened:
            return
        self._opened = True
        from mankomix.core import mixrender as MR
        from mankomix.core.errors import MankoError
        from mankomix.core.project import Project
        try:
            pobj = Project.open(self.root)
            data, _ = MR.effective_data(pobj, variant_id=self.variant_id)
            tracks = MR.stem_tracks(data)
            err = cleanup_cache_error(pobj, tracks)
        except MankoError as e:
            self._error = str(e)
            return
        if err:
            self._error = err
            return
        self._pobj = pobj
        self._tracks = {t["id"]: t for t in tracks}
        soloed = {t["id"] for t in tracks if t.get("solo")}
        self._audible = {t["id"] for t in tracks if not t.get("muted") and (not soloed or t["id"] in soloed)}

    def _ready(self) -> None:
        self._open()
        if self._error:
            raise StemObsError(self._error)

    def check_track(self, tid: str) -> None:
        self._ready()
        if tid not in self._tracks:
            raise StemObsError(f"unknown track '{tid}'")
        if tid not in self._audible:
            raise StemObsError(f"track '{tid}' is muted (not audible in this state)")

    def tracks(self) -> dict[str, dict]:
        self._ready()
        return dict(self._tracks)

    def _render(self, **kw) -> tuple[np.ndarray, int]:
        from mankomix.core import mixrender as MR
        from mankomix.core.errors import MankoError
        try:
            x, sr, _ = MR.render_mix(self._pobj, variant_id=self.variant_id, measure=False, **kw)
        except MankoError as e:
            raise StemObsError(str(e)) from None
        return x, int(sr)

    def dry(self) -> tuple[dict, int]:
        """{track id: stereo signal as it enters its bus} for every audible track, and the rate."""
        self._ready()
        if self._dry is None:
            stems: dict = {}
            _, sr = self._render(stems_out=stems)
            self._dry = ({k: stems[k] for k in sorted(stems)}, sr)
        return self._dry

    def solo(self, tid: str, sends: bool = True) -> tuple[np.ndarray, int]:
        """The mix bus output with only ``tid`` audible (``sends=False``: its sends emptied)."""
        self.check_track(tid)
        key = (tid, bool(sends))
        if key not in self._solo:
            if not sends and not self._tracks[tid].get("sends"):
                self._solo[key] = self.solo(tid, True)       # nothing to empty: the same render
            else:
                ov = None if sends else {tid: {"sends": []}}
                self._solo[key] = self._render(solo=[tid], overrides=ov)
        return self._solo[key]

    def track(self, tid: str, path: str = "dry") -> tuple[np.ndarray, int]:
        self.check_track(tid)
        if path == "solo":
            return self.solo(tid)
        stems, sr = self.dry()
        if tid not in stems:
            raise StemObsError(f"track '{tid}' is not audible in this state")
        return stems[tid], sr

    def masking_context(self, ids: list[str]) -> tuple[dict, str | None]:
        """(meta, genre) for ``masking_matrix``: the resolved objective's stems meta, lead and genre,
        assembled as the floor's evaluation passes them to ``measure_stem_context``
        (``core.objectives.measure_for_objective``)."""
        self._ready()
        if self._meta is None:
            from mankomix.core import objectives as O
            from mankomix.core.errors import MankoError
            try:
                # references={} skips the reference distribution: meta, lead and genre do not depend on it
                resolved = O.resolve_objective(self._pobj, variant=self.variant_id, references={})
            except MankoError as e:
                raise StemObsError(f"objective: {e}") from None
            self._meta = (resolved, (resolved.get("genre") or {}).get("id"))
        resolved, genre = self._meta
        lead = (resolved.get("lead") or {}).get("stem")
        meta = {}
        for t in ids:
            m = dict((resolved.get("stems_meta") or {}).get(t) or {})
            meta[t] = {"role": m.get("role", "other"), "is_lead": t == lead, "importance": m.get("importance")}
        return meta, genre


# ---------------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------------

def _range(obs: dict, sections: list[dict] | None, n: int, sr: int) -> tuple[float, float, int, int]:
    t0, t1 = Q.section_range(obs.get("section", "all"), sections, n / sr)
    return t0, t1, int(round(t0 * sr)), int(round(t1 * sr))


def _ok(value: float, unit: str, t0: float, t1: float, path: str) -> dict:
    return {"status": "ok", "value": round(float(value), 4), "unit": unit, "range_s": [round(t0, 3), round(t1, 3)],
            "gain_db": 0.0, "signal": SIGNAL, "path": path}


def _masking(src: StemSource, obs: dict, sections: list[dict] | None) -> dict:
    from mankomix.core.analysis.stems import masking_matrix
    target = obs.get("target")
    against = obs.get("against")
    for t in (target, against):
        if is_track_target(t):
            src.check_track(t)
    stems, sr = src.dry()
    for t in (target, against):
        if is_track_target(t) and t not in stems:
            raise StemObsError(f"track '{t}' is not audible in this state")
    if len(stems) < 2:
        raise StemObsError(f"masking needs at least 2 audible tracks (found {len(stems)})")
    n = max(x.shape[0] for x in stems.values())
    t0, t1, i0, i1 = _range(obs, sections, n, sr)
    cut = {t: x[i0:i1] for t, x in stems.items()}
    if target != "all" and float(np.sum(cut[target] ** 2)) < EPS:
        raise StemObsError(f"track '{target}' is silent in the range")
    meta, genre = src.masking_context(list(cut))
    mm = masking_matrix(cut, sr, meta, genre=genre)
    band = obs.get("band_hz")
    if target == "all":
        v = (mm.get("overall") or {}).get("value")
    elif against is not None:
        v = ((mm.get("matrix") or {}).get(target) or {}).get(against)
    elif band is not None:
        lo, hi = float(band[0]), float(band[1])
        pb = (mm.get("per_target") or {}).get(target, {}).get("buried_db_by_band") or []
        vals = [b for fc, b in zip(mm.get("bands_hz") or [], pb)
                if b is not None and lo <= float(fc) < hi and math.isfinite(float(b))]
        if not vals:
            raise StemObsError(f"masking: no measured ERB band has its centre in [{lo:g}, {hi:g}) Hz")
        v = float(sum(vals) / len(vals))
    else:
        v = ((mm.get("per_target") or {}).get(target) or {}).get("buried_db")
    if v is None:
        raise StemObsError("masking: the model gave no value (silent or unmeasurable)")
    return _ok(v, "dB", t0, t1, "dry")


def _wet_ratio(src: StemSource, obs: dict, sections: list[dict] | None) -> dict:
    tid = obs.get("target")
    a, sr = src.solo(tid, True)
    b, _ = src.solo(tid, False)
    t0, t1, i0, i1 = _range(obs, sections, a.shape[0], sr)
    band = obs.get("band_hz")
    sa = Q._bandpass(np.asarray(a[i0:i1], dtype=np.float64), sr, band)
    sb = Q._bandpass(np.asarray(b[i0:i1], dtype=np.float64), sr, band)
    eb = float(np.sum(sb ** 2))
    if eb < EPS:
        raise StemObsError(f"track '{tid}' is silent in the range (no dry signal to compare)")
    ed = float(np.sum((sa - sb) ** 2))
    v = WET_FLOOR_DB if ed <= 0.0 else max(WET_FLOOR_DB, 10.0 * math.log10(ed / eb))
    return _ok(v, "dB", t0, t1, "solo")


def observe(src: StemSource, obs: dict, *, sections: list[dict] | None = None) -> dict:
    """One track-context observation on ``src``; errors come back as ``{"status": "error", ...}``."""
    try:
        errs = spec_errors(obs)
        if errs:
            raise StemObsError(f"{errs[0][1]}: {errs[0][2]}")
        prim = obs.get("primitive")
        if prim == "masking":
            return _masking(src, obs, sections)
        if prim == "wet_ratio":
            return _wet_ratio(src, obs, sections)
        if prim not in Q.PRIMITIVES:
            raise StemObsError(f"unknown primitive '{prim}'")
        path = obs.get("path", "dry")
        x, sr = src.track(obs.get("target"), path)
        sub = {k: v for k, v in obs.items() if k not in ("target", "path")}
        res = Q.observe(x, sr, sub, sections=sections, gain_db=0.0)
        if res.get("status") == "ok":
            res.update({"gain_db": 0.0, "signal": SIGNAL, "path": path})
        return res
    except (StemObsError, Q.QueryError) as e:
        return {"status": "error", "reason": str(e)}
