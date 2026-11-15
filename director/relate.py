"""Look-ahead across the tracks of a project (FBREVIEW FR-3). Read-only.

- ``observe_specs``: FR-1 / FR-2 observation quantities measured on the project as it is
  (``direction_stem_observations``)
- ``stem_relate``: the P-02 masking of every audible track against the others, per band and with
  its top maskers, and the P-22 band owners over the whole song (``direction_stem_relate``)

Both read the track signals through ``stemobs.StemSource`` (no file is written; the cleanup caches
must already be valid). A missing or stale cache raises ``StemCacheError`` before anything is
rendered. The CLI wiring (``direction stems observe / relate``) lives in ``cli/main.py``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from . import query as Q
from . import stemobs as S

# P-22 band edges (sub / bass / lowmid / mid / highmid / air); the same as the core model's p22 bands
BANDS = (("sub", 20.0, 60.0), ("bass", 60.0, 250.0), ("lowmid", 250.0, 500.0), ("mid", 500.0, 2000.0),
         ("highmid", 2000.0, 6000.0), ("air", 6000.0, 20000.0))
TOP_RANGE = (1, 8)
RELATE_NOTE = ("P-02 のモデル値（粗い興奮パターン）。0 に近いほど良いわけではない。band_owners は P-22 の担当の規則を"
               "満たしたトラックだけで、その帯域で鳴っているトラックの一覧ではない。読みは指揮者の〔推定〕")


class StemCacheError(S.StemObsError):
    """The cleanup cache of a track is missing or stale (run clean apply / render first)."""


def _source(project_root: str | Path, variant: str | None) -> S.StemSource:
    """A StemSource whose project opened and whose caches are valid; else an exception (nothing rendered)."""
    src = S.StemSource(project_root, variant)
    src._open()
    if src._error == S.CACHE_ERROR:
        raise StemCacheError(S.CACHE_ERROR)
    if src._error:
        raise S.StemObsError(src._error)
    return src


def _sections(project_root: str | Path) -> list[dict]:
    from .direction import _Project
    return _Project(project_root).sections()


def _r3(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 3) if math.isfinite(f) else None


def observe_specs(project_root: str | Path, specs: dict | list, variant: str | None = None) -> dict:
    """Measure one observation spec or a list of them on the project's current state.

    Each entry is ``{"spec": <the spec>, "result": <stemobs result>}``; a spec that is not measured
    from the tracks (a master target of a single-signal primitive) comes back as an error result
    (use ``direction query`` on a rendered file)."""
    items = specs if isinstance(specs, list) else [specs]
    if not items or not all(isinstance(o, dict) for o in items):
        raise S.StemObsError("specs must be an observation object or a non-empty list of them")
    src = _source(project_root, variant)
    sections = _sections(project_root)
    out = []
    for o in items:
        if not S.needs_stems(o):
            res = {"status": "error", "reason": "stems observe measures track targets (trk_<stem>) and "
                                                "masking / wet_ratio; use direction query for a rendered file"}
        else:
            res = S.observe(src, o, sections=sections)
        out.append({"spec": o, "result": res})
    return {"kind": "direction_stem_observations", "observations": out}


def _band_mean(fcs: list, vals: list, lo: float, hi: float) -> float | None:
    sel = [float(b) for fc, b in zip(fcs, vals)
           if b is not None and lo <= float(fc) < hi and math.isfinite(float(b))]
    return float(sum(sel) / len(sel)) if sel else None


def stem_relate(project_root: str | Path, variant: str | None = None, section: Any = None, top: int = 3) -> dict:
    """The cross-track table of the project's current state (dry signals, mix stage)."""
    from mankomix.core.analysis.stems import band_density, masking_matrix
    if not isinstance(top, int) or isinstance(top, bool) or not TOP_RANGE[0] <= top <= TOP_RANGE[1]:
        raise S.StemObsError(f"top must be an integer {TOP_RANGE[0]} to {TOP_RANGE[1]} (got {top!r})")
    src = _source(project_root, variant)
    stems, sr = src.dry()
    if len(stems) < 2:
        raise S.StemObsError(f"relate needs at least 2 audible tracks (found {len(stems)})")
    n = max(x.shape[0] for x in stems.values())
    try:
        t0, t1 = Q.section_range(section, _sections(project_root), n / sr)
    except Q.QueryError as e:
        raise S.StemObsError(str(e)) from None
    i0, i1 = int(round(t0 * sr)), int(round(t1 * sr))
    cut = {t: x[i0:i1] for t, x in stems.items()}
    ids = sorted(cut)
    meta, genre = src.masking_context(ids)
    mm = masking_matrix(cut, sr, meta, genre=genre)
    fcs = mm.get("bands_hz") or []
    per = {}
    for t in ids:
        pt = (mm.get("per_target") or {}).get(t) or {}
        pb = pt.get("buried_db_by_band") or []
        row = (mm.get("matrix") or {}).get(t) or {}
        maskers = sorted(((m, float(v)) for m, v in row.items() if _r3(v) is not None), key=lambda mv: (-mv[1], mv[0]))
        per[t] = {"buried_db": _r3(pt.get("buried_db")),
                  "by_band": {name: _r3(_band_mean(fcs, pb, lo, hi)) for name, lo, hi in BANDS},
                  "top_maskers": [{"track": m, "buried_db": _r3(v)} for m, v in maskers[:top]]}
    bd = band_density(cut, sr, meta, genre=genre)
    whole = ((bd.get("sections") or [{}])[0] or {}).get("bands") or {}
    owners = {name: [o.get("track") for o in (whole.get(name) or {}).get("owners") or []] for name, _, _ in BANDS}
    return {"kind": "direction_stem_relate", "signal": "mix_stage_dry", "section": section, "tracks": ids,
            "masking": {"overall_db": _r3((mm.get("overall") or {}).get("value")),
                        "lead": (mm.get("vs_lead") or {}).get("lead"),
                        "per_target": per},
            "band_owners": owners,
            "note": RELATE_NOTE}
