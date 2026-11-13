"""Cleanup stage integrated into projects (SPEC 6.4, 6.6.1, 6.7, 6.8 section 7, 9.1, 10.2; R-20, R-31).

The signal processing lives in ``core/cleanup`` (diagnose, plan_cleanup,
run_cleanup, noise baseline, S-08 check). This module connects it to a
project:

* ``plan_clean``: one R-31 proposal for the stage. Stems are cleaned one by
  one (SPEC 6.4.3: artifacts concentrate in single stems); the full mix is a
  target when the mastering route is the full-mix route (2mix only, or
  separated stems only). Assets where nothing is detected land in
  ``skipped`` with the reason (SPEC 6.4.2 step 1), and so do tracks whose
  ``cleanup.enabled`` is false.
* ``apply_clean``: approves the proposal. The project stores, per track
  (``tracks[].cleanup``) and for the full mix (``fullmix_cleanup``), the
  mode (``plan: "auto" | "custom"``), the overrides and what was applied
  (asset sha256 + plan hash per asset). Everything else is regenerable:

  - ``cache/clean/<asset_sha16>_<plan_hash16>.wav``: cleaned audio (32-bit
    float) with a JSON sidecar (full hashes, file sha256),
  - ``renders/delta/<asset_id>.wav``: the removed component (input minus
    output) for listening (SPEC 6.4.3),
  - ``analysis/cleanup_<asset_id>.json``: the cleanup record (steps run /
    light / skip, removed energy, P-21 side effects, S-07 residual measured on
    the stored file, over-suppression check and rerun),
  - ``analysis/noise_baseline.json``: P-16 of the cleaned material per asset
    and for the master inputs (cleaned full mix, cleaned static stem sum),
    the reference of the S-08 noise-return guard.

  The journal gets one ``clean_apply`` entry.
* The plan itself is not stored: it is re-derived from the asset and the
  stored overrides (``plan_cleanup`` is deterministic) and checked against
  the stored plan hash, so the project alone reproduces the cleaned audio
  (SPEC 9.1, 9.6). A missing cache is regenerated on demand with identical
  bytes; a plan-hash mismatch (cleanup policy or engine changed) is an
  error that asks for a new plan / apply.
"""

from __future__ import annotations

import copy
import json
import math
import time
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from . import audio_io
from .cleanup import (noise_baseline, noise_return_check, null_test_residual_dbfs, plan_cleanup,
                      run_cleanup)
from .cleanup._util import load_policy, v
from .cleanup.pipeline import PLAN_VERSION, STEPS
from .errors import InputError, ValidationError
from .hashing import canonical_hash, sha256_file

CACHE_DIR = "cache/clean"
DELTA_DIR = "renders/delta"
BASELINE_FILE = "analysis/noise_baseline.json"
RECORD_DIR = "analysis"
FULLMIX_KEY = "fullmix_cleanup"
STAGE = "clean"
APPLIED_VERSION = 1

# Diagnosis keys shown in the proposal (the full metrics stay in the record).
_SUMMARY_KEYS = ("noise_floor_dbfs", "noise_floor_hf_dbfs", "hf_ceiling_hz", "shimmer_index_db",
                 "shimmer_flatness", "shimmer_modulation", "shimmer_signal_corr", "side_shimmer_index_db",
                 "click_count", "head_click", "lowmid_density_db", "sibilant_seconds")


# --------------------------------------------------------------------------
# small helpers


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(x) for k, x in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist())
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, Path):
        return obj.name
    return obj


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_json_safe(obj), indent=2, ensure_ascii=False, allow_nan=False)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text + "\n")
    tmp.replace(path)


def write_f32_wav(path: Path, x: np.ndarray, sr: int) -> None:
    """Deterministic 32-bit float WAV (WAVE_FORMAT_IEEE_FLOAT, fmt + fact + data).

    libsndfile adds a PEAK chunk with a time stamp to float WAV files, so its
    bytes differ between writes; the cache must be byte-identical when it is
    regenerated (SPEC 9.6, 16.3)."""
    import struct
    a = np.asarray(x, dtype="<f4")
    if a.ndim == 1:
        a = a[:, None]
    frames, ch = a.shape
    data = np.ascontiguousarray(a).tobytes()
    fmt = struct.pack("<HHIIHHH", 3, ch, int(sr), int(sr) * ch * 4, ch * 4, 32, 0)
    fact = struct.pack("<I", frames)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"fact" + struct.pack("<I", 4) + fact
            + b"data" + struct.pack("<I", len(data)) + data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", len(body)) + body)
    tmp.replace(path)


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError):
        return None


def _rel_join(root: Path, rel: str) -> Path:
    return Path(root).joinpath(*PurePosixPath(rel).parts)


def _r(x: Any, nd: int = 3) -> Any:
    return round(float(x), nd) if isinstance(x, (int, float)) and math.isfinite(float(x)) else None


def _merge_overrides(base: dict | None, extra: dict | None) -> dict:
    """Step overrides from ``extra`` replace those of ``base``; ``policy`` is deep-merged."""
    out = copy.deepcopy(base or {})
    for k, val in (extra or {}).items():
        if k == "policy" and isinstance(out.get("policy"), dict) and isinstance(val, dict):
            from .cleanup._util import deep_merge
            out["policy"] = deep_merge(out["policy"], val)
        else:
            out[k] = copy.deepcopy(val)
    return out


def _is_step_overrides(d: dict) -> bool:
    return bool(d) and all(k in STEPS or k == "policy" for k in d)


def plan_hash(plan: dict) -> str:
    """sha256 of what determines the cleaned audio: plan version, rate, input
    fingerprint, per-step action + parameters, skip flag and the policy."""
    core = {
        "version": plan.get("version"),
        "sr": plan.get("sr"),
        "input": (plan.get("input") or {}).get("sha256"),
        "steps": {k: {"action": s.get("action"), "params": s.get("params")}
                  for k, s in (plan.get("steps") or {}).items()},
        "skip_all": bool(plan.get("skip_all")),
        "policy": plan.get("policy"),
    }
    return canonical_hash(_json_safe(core))


# --------------------------------------------------------------------------
# project structure


def _fullmix_id(data: dict) -> str | None:
    from .routes import fullmix_asset_id
    return fullmix_asset_id(data)


def _stem_tracks(data: dict) -> list[dict]:
    from .routes import stem_tracks
    return stem_tracks(data)


def _asset_tracks(data: dict) -> dict[str, list[dict]]:
    """{asset id: [stem tracks using it]} in project order (full mix excluded)."""
    fid = _fullmix_id(data)
    out: dict[str, list[dict]] = {}
    for t in _stem_tracks(data):
        for c in t.get("clips") or []:
            aid = c.get("asset")
            if not aid or aid == fid:
                continue
            lst = out.setdefault(aid, [])
            if t not in lst:
                lst.append(t)
    return out


def _cfg(holder: dict | None) -> dict:
    c = (holder or {}).get("cleanup") if holder is not None else None
    return c if isinstance(c, dict) else {}


def _fullmix_cfg(data: dict) -> dict:
    c = data.get(FULLMIX_KEY)
    return c if isinstance(c, dict) else {}


def _entry_in(cfg: dict, aid: str) -> dict | None:
    if cfg.get("enabled") is False:
        return None
    e = ((cfg.get("applied") or {}).get("assets") or {}).get(aid)
    return e if isinstance(e, dict) else None


def track_cleanup_entry(track: dict, asset_id: str) -> dict | None:
    """Applied-cleanup entry of ``asset_id`` on ``track`` that changes audio (None: raw asset)."""
    e = _entry_in(_cfg(track), asset_id)
    return e if e is not None and not e.get("skipped") else None


def fullmix_cleanup_entry(data: dict) -> dict | None:
    fid = _fullmix_id(data)
    if fid is None:
        return None
    e = _entry_in(_fullmix_cfg(data), fid)
    return e if e is not None and not e.get("skipped") else None


def applied_entry(data: dict, asset_id: str, *, include_skipped: bool = False) -> dict | None:
    """Applied entry of an asset: the full-mix record, else the first stem track that has one."""
    cands = []
    if asset_id == _fullmix_id(data):
        cands.append(_entry_in(_fullmix_cfg(data), asset_id))
    for t in _asset_tracks(data).get(asset_id, []):
        cands.append(_entry_in(_cfg(t), asset_id))
    for e in cands:
        if e is not None and (include_skipped or not e.get("skipped")):
            return e
    return None


def cleaned_assets(data: dict, route: str | None = None) -> dict[str, dict]:
    """{asset id: applied entry} of the assets that enter ``route`` cleaned.

    ``route``: "full_mix" (the full mix only), "stem_mix" / "stem_sum" (stems of
    audible tracks), None (everything cleaned)."""
    out: dict[str, dict] = {}
    if route in (None, "full_mix", "fullmix"):
        fid = _fullmix_id(data)
        e = fullmix_cleanup_entry(data)
        if fid is not None and e is not None:
            out[fid] = e
    if route in (None, "stem_mix", "stem_sum"):
        tracks = _stem_tracks(data)
        solo = any(t.get("solo") for t in tracks)
        for t in tracks:
            if route is not None and (t.get("muted") or (solo and not t.get("solo"))):
                continue
            for c in t.get("clips") or []:
                aid = c.get("asset")
                if aid in out or (route is not None and c.get("muted")):
                    continue
                e = track_cleanup_entry(t, aid)
                if e is not None:
                    out[aid] = e
    return out


# --------------------------------------------------------------------------
# file locations


def cache_rel(asset_sha: str, phash: str) -> str:
    return f"{CACHE_DIR}/{asset_sha[:16]}_{phash[:16]}.wav"


def delta_rel(asset_id: str) -> str:
    return f"{DELTA_DIR}/{asset_id}.wav"


def record_rel(asset_id: str) -> str:
    return f"{RECORD_DIR}/cleanup_{asset_id}.json"


def _sidecar(p: Path) -> Path:
    return p.with_suffix(".json")


# --------------------------------------------------------------------------
# planning


def _read_raw(project, asset_id: str) -> tuple[np.ndarray, int]:
    x, sr = audio_io.read(project.asset_path(asset_id))
    return np.ascontiguousarray(x, dtype=np.float64), int(sr)


def _diagnosis_summary(plan: dict) -> dict:
    m = (plan.get("diagnosis") or {}).get("metrics") or {}
    out = {k: m.get(k) for k in _SUMMARY_KEYS if k in m}
    out["detected"] = sorted(k for k, s in (plan.get("steps") or {}).items() if s.get("proposed") != "skip")
    return _json_safe(out)


def _proposal_plan(plan: dict) -> dict:
    """The plan as shown in a proposal: without the (large) policy, with its hash."""
    p = {k: copy.deepcopy(val) for k, val in plan.items() if k != "policy"}
    p["policy_hash"] = canonical_hash(_json_safe(plan.get("policy") or {}))
    return _json_safe(p)


def _overrides_for(call: dict | None, aid: str, tracks: list[dict]) -> dict:
    if not call:
        return {}
    if _is_step_overrides(call):
        return copy.deepcopy(call)
    out: dict = {}
    for t in tracks:
        out = _merge_overrides(out, call.get(t.get("id")))
    return _merge_overrides(out, call.get(aid))


def _default_targets(project) -> tuple[list[str], dict]:
    from .routes import select_route
    data = project.data
    route = select_route(project)
    ids = list(_asset_tracks(data))
    fid = _fullmix_id(data)
    if fid is not None and (route["route"] == "full_mix" or not ids):
        ids.append(fid)
    return ids, route


def _resolve_targets(project, targets) -> tuple[list[str], dict | None]:
    data = project.data
    if targets is None:
        return _default_targets(project)
    if isinstance(targets, str):
        targets = [targets]
    by_track = {t.get("id"): t for t in data.get("tracks") or []}
    assets = {a.get("id") for a in data.get("assets") or []}
    fid = _fullmix_id(data)
    ids: list[str] = []
    for tgt in targets:
        if tgt in ("fullmix", "full_mix"):
            if fid is None:
                raise InputError("the project has no full mix")
            tgt = fid
        if tgt in assets:
            cand = [tgt]
        elif tgt in by_track:
            cand = [c.get("asset") for c in by_track[tgt].get("clips") or [] if c.get("asset")]
        else:
            raise InputError(f"unknown cleanup target '{tgt}' (asset id, track id or 'fullmix')",
                             details={"assets": sorted(assets), "tracks": sorted(by_track)})
        for aid in cand:
            if aid not in ids:
                ids.append(aid)
    return ids, None


def plan_clean(project, *, targets: list[str] | str | None = None, overrides: dict | None = None) -> dict:
    """Diagnose the used assets and propose a cleanup plan per asset (R-31).

    ``targets``: asset ids, track ids or "fullmix" (default: every stem asset,
    plus the full mix when the mastering route is the full-mix route or no
    stems exist). ``overrides``: step overrides for every target
    (``{"spectral_reduction": "light", "policy": {...}}``) or keyed by asset /
    track id. They are merged over the overrides stored in the project.
    Nothing is written.
    """
    t0 = time.perf_counter()
    data = project.data
    ids, route = _resolve_targets(project, targets)
    if not ids:
        raise InputError("nothing to clean: the project has no stems and no full mix")
    fid = _fullmix_id(data)
    at = _asset_tracks(data)
    assets = {a.get("id"): a for a in data.get("assets") or []}
    items: list[dict] = []
    skipped: list[dict] = []
    for aid in ids:
        a = assets.get(aid) or {}
        is_fm = aid == fid
        tracks = [] if is_fm else at.get(aid, [])
        base = {"asset": aid, "kind": "fullmix" if is_fm else "stem", "role": a.get("role"),
                "origin": a.get("origin"), "tracks": [t.get("id") for t in tracks],
                "track": tracks[0].get("id") if tracks else None}
        if is_fm:
            cfgs = [_fullmix_cfg(data)]
        else:
            if not tracks:
                skipped.append({**base, "reason": "asset is not used by any stem track", "code": "unused"})
                continue
            cfgs = [_cfg(t) for t in tracks]
        enabled = [c for c in cfgs if c.get("enabled") is not False]
        if not enabled:
            skipped.append({**base, "reason": "cleanup disabled (cleanup.enabled = false)", "code": "disabled"})
            continue
        stored = {}
        for c in enabled:
            stored = _merge_overrides(stored, c.get("overrides") if isinstance(c.get("overrides"), dict) else {})
        eff = _merge_overrides(stored, _overrides_for(overrides, aid, tracks))
        ta = time.perf_counter()
        x, sr = _read_raw(project, aid)
        plan = plan_cleanup(x, sr, overrides=copy.deepcopy(eff))
        ph = plan_hash(plan)
        entry = {**base, "asset_sha256": a.get("sha256"), "sample_rate": sr, "overrides": _json_safe(eff),
                 "mode": "custom" if eff else "auto", "plan_hash": ph,
                 "steps": {k: s["action"] for k, s in plan["steps"].items()},
                 "diagnosis": _diagnosis_summary(plan),
                 "reasons": {k: s.get("reasons") for k, s in plan["steps"].items()},
                 "alternatives": {k: s.get("alternatives") for k, s in plan["steps"].items()},
                 "plan": _proposal_plan(plan), "seconds": round(time.perf_counter() - ta, 3)}
        if plan.get("skip_all"):
            entry["reason"] = "; ".join(plan.get("reasons") or ["all steps skipped"])
            entry["code"] = "nothing_detected" if not eff else "all_steps_skipped"
            skipped.append(entry)
        else:
            items.append(entry)
    preference = {
        "rule": "SPEC 6.4.3",
        "ja": "ステムがある場合はステム単位で整音する。2mix しかない場合（またはフルミックス経路）は 2mix に対して行う",
        "en": "Stems are cleaned one by one when they exist; the 2-mix is cleaned when it is the only input "
              "(or the master input of the full-mix route)",
    }
    prop = {
        "kind": "clean_proposal", "stage": STAGE, "version": PLAN_VERSION,
        "project_hash": project.content_hash(),
        "route": route, "preference": preference, "rules": ["R-20", "R-31", "D-011", "D-041"],
        "items": items, "skipped": skipped,
        "alternatives": [
            {"action": "reject", "effect": "keep the raw assets; S-08 then guards against the uncleaned input"},
            {"action": "override", "effect": "lighten or skip single steps per asset or track "
                                             "(e.g. {'spectral_reduction': 'light'})"},
        ],
        "neural_completion": {"used": False, "rule": "D-041",
                              "note": "HF completion is deterministic DSP; neural completion is opt-in only"},
        "operations": ["approve", "reject"],
        "seconds": round(time.perf_counter() - t0, 3),
    }
    prop["proposal_id"] = "cln_" + canonical_hash(_json_safe(
        {"items": [(i["asset"], i["plan_hash"]) for i in items],
         "skipped": [(s["asset"], s.get("plan_hash"), s.get("code")) for s in skipped]}))[:12]
    return _json_safe(prop)


# --------------------------------------------------------------------------
# running + storing


def _plan_for(project, aid: str, overrides: dict, x: np.ndarray | None = None,
              sr: int | None = None) -> tuple[dict, np.ndarray, int]:
    if x is None:
        x, sr = _read_raw(project, aid)
    plan = plan_cleanup(x, sr, overrides=copy.deepcopy(overrides or {}))
    return plan, x, int(sr)


def _edited_overrides(item: dict, plan: dict) -> dict:
    """Overrides that reproduce step edits made directly in a proposal item's plan / steps."""
    out: dict = {}
    want_steps = item.get("steps") or {}
    want_plan = ((item.get("plan") or {}).get("steps")) or {}
    for step in STEPS:
        cur = plan["steps"][step]
        w = want_plan.get(step) or {}
        act = want_steps.get(step, w.get("action", cur["action"]))
        params = w.get("params") if isinstance(w.get("params"), dict) else None
        if act != cur["action"] or (params is not None and _json_safe(params) != _json_safe(cur["params"])):
            ov: dict = {"action": act}
            if params is not None:
                ov.update({k: val for k, val in params.items()
                           if _json_safe(val) != _json_safe(cur["params"].get(k))})
            out[step] = ov
    return out


def _record_report(rep: dict) -> dict:
    """The run_cleanup report for the record (click positions trimmed to 50)."""
    rep = copy.deepcopy(rep)
    clicks = ((rep.get("steps") or {}).get("click_repair") or {})
    if isinstance(clicks.get("repaired"), list) and len(clicks["repaired"]) > 50:
        clicks["repaired_total"] = len(clicks["repaired"])
        clicks["repaired"] = clicks["repaired"][:50]
    for key in ("p16_before", "p16_after"):
        m = rep.get(key) or {}
        if isinstance(m.get("clicks"), list) and len(m["clicks"]) > 50:
            m["clicks"] = m["clicks"][:50]
    return rep


def _materialize(project, aid: str, overrides: dict, *, expect_hash: str | None = None,
                 tracks: list[str] | None = None, kind: str | None = None) -> dict:
    """Run the cleanup of one asset and write cache, delta and record. Returns the applied entry
    plus the record (key ``_record``) and the baseline (key ``_baseline``)."""
    t0 = time.perf_counter()
    root = Path(project.root)
    asset = project.asset(aid)
    asha = asset.get("sha256") or ""
    plan, x, sr = _plan_for(project, aid, overrides)
    ph = plan_hash(plan)
    if expect_hash is not None and ph != expect_hash:
        raise ValidationError(
            f"the cleanup plan of '{aid}' no longer matches the applied plan (cleanup policy, engine or "
            f"asset changed); run clean plan / apply again",
            details={"asset": aid, "applied_plan_hash": expect_hash, "current_plan_hash": ph})
    policy = plan.get("policy") or load_policy()
    xover = float(v(policy["crossover"]["frequency_hz"]))
    limit = float(v(policy["s07"]["residual_limit_dbfs"]))
    rec_rel = record_rel(aid)
    entry: dict = {"asset_sha256": asha, "plan_hash": ph, "plan_version": plan.get("version"),
                   "overrides": _json_safe(overrides or {}), "skipped": bool(plan.get("skip_all")),
                   "steps": {k: s["action"] for k, s in plan["steps"].items()},
                   "record_path": rec_rel}
    record: dict = {
        "kind": "cleanup_record", "schema_version": 1, "asset": aid, "asset_kind": kind,
        "tracks": tracks or [], "asset_sha256": asha, "plan_hash": ph, "plan_version": plan.get("version"),
        "sample_rate": sr, "overrides": _json_safe(overrides or {}),
        "mode": "custom" if overrides else "auto",
        "steps": {k: {"action": s["action"], "proposed": s.get("proposed"), "params": s.get("params"),
                      "reasons": s.get("reasons"), "overridden": s.get("overridden")}
                  for k, s in plan["steps"].items()},
        "diagnosis": (plan.get("diagnosis") or {}).get("metrics"),
        "neural_completion_used": False,
    }
    if plan.get("skip_all"):
        base = noise_baseline(x, sr, policy=policy, metrics=(plan.get("diagnosis") or {}).get("metrics"))
        record.update({"skipped": True, "reasons": plan.get("reasons") or ["all steps skipped"],
                       "s07": {"residual_dbfs": -300.0, "limit_dbfs": limit, "crossover_hz": xover,
                               "pass": True, "note": "nothing processed: the output is the input"},
                       "noise_baseline": base, "files": {}})
        entry["s07_pass"] = True
    else:
        res = run_cleanup(x, sr, plan)
        crel = cache_rel(asha, ph)
        cpath = _rel_join(root, crel)
        write_f32_wav(cpath, res.audio, sr)
        stored, _ = audio_io.read(cpath)
        _write_json(_sidecar(cpath), {"kind": "cleanup_cache", "asset": aid, "asset_sha256": asha,
                                      "plan_hash": ph, "file_sha256": sha256_file(cpath),
                                      "sample_rate": sr, "frames": int(stored.shape[0]),
                                      "channels": int(stored.shape[1]), "format": "wav_f32"})
        drel = delta_rel(aid)
        dpath = _rel_join(root, drel)
        delta = x - stored
        write_f32_wav(dpath, delta, sr)
        _write_json(_sidecar(dpath), {"kind": "cleanup_delta", "asset": aid, "asset_sha256": asha,
                                      "plan_hash": ph, "file_sha256": sha256_file(dpath),
                                      "definition": "input - cleaned output (removed component)"})
        resid_file = null_test_residual_dbfs(x, stored, sr, xover)
        rep = _record_report(res.report)
        s07 = dict(rep.get("s07") or {})
        s07.update({"residual_stored_dbfs": _r(resid_file),
                    "pass": bool(s07.get("pass")) and resid_file <= limit,
                    "stored_note": "residual re-measured on the stored 32-bit float cache file"})
        rep["s07"] = s07
        record.update({"skipped": False, "report": rep, "s07": s07,
                       "noise_baseline": rep.get("noise_baseline"),
                       "files": {"cache": crel, "delta": drel}})
        entry["s07_pass"] = bool(s07["pass"])
    record["seconds"] = round(time.perf_counter() - t0, 3)
    _write_json(_rel_join(root, rec_rel), record)
    entry["_record"] = record
    entry["_baseline"] = record["noise_baseline"]
    return entry


def _public(entry: dict) -> dict:
    return {k: val for k, val in entry.items() if not k.startswith("_")}


def _cache_valid(project, asset_sha: str, phash: str) -> Path | None:
    p = _rel_join(Path(project.root), cache_rel(asset_sha, phash))
    side = _read_json(_sidecar(p))
    if not p.is_file() or side is None:
        return None
    if side.get("asset_sha256") != asset_sha or side.get("plan_hash") != phash:
        return None
    if side.get("file_sha256") != sha256_file(p):
        return None
    return p


def ensure_cleaned(project, asset_id: str, entry: dict) -> Path | None:
    """Path of the cleaned audio for an applied entry (None when nothing was processed).

    Valid only if the cache matches the asset sha256 and the plan hash;
    otherwise the cleanup is re-run deterministically from the asset and the
    stored overrides (identical bytes) and the cache, delta and record are
    rewritten."""
    if entry is None or entry.get("skipped"):
        return None
    asha = project.asset(asset_id).get("sha256") or ""
    if entry.get("asset_sha256") and entry["asset_sha256"] != asha:
        raise ValidationError(f"asset '{asset_id}' changed since its cleanup was applied; run clean apply again",
                              details={"asset": asset_id})
    p = _cache_valid(project, asha, entry["plan_hash"])
    if p is not None:
        return p
    _materialize(project, asset_id, entry.get("overrides") or {}, expect_hash=entry["plan_hash"])
    p = _cache_valid(project, asha, entry["plan_hash"])
    if p is None:  # pragma: no cover - write failure
        raise ValidationError(f"cannot regenerate the cleanup cache of '{asset_id}'")
    return p


def cleaned_asset_path(project, asset_id: str) -> Path | None:
    """Cleaned audio of an asset (regenerated on demand), or None if no cleanup changes it."""
    e = applied_entry(project.data, asset_id)
    return ensure_cleaned(project, asset_id, e) if e is not None else None


def asset_audio_path(project, asset_id: str, entry: dict | None) -> Path:
    """The file to read for an asset: the cleaned cache for an applied entry, else the asset."""
    p = ensure_cleaned(project, asset_id, entry) if entry is not None else None
    return p if p is not None else project.asset_path(asset_id)


def cleanup_record(project, asset_id: str) -> dict | None:
    """The cleanup record of an asset (regenerated if missing or stale), or None if not applied."""
    e = applied_entry(project.data, asset_id, include_skipped=True)
    if e is None:
        return None
    rec = _read_json(_rel_join(Path(project.root), record_rel(asset_id)))
    if rec is None or rec.get("plan_hash") != e.get("plan_hash") or rec.get("asset_sha256") != e.get("asset_sha256"):
        _materialize(project, asset_id, e.get("overrides") or {}, expect_hash=e.get("plan_hash"))
        rec = _read_json(_rel_join(Path(project.root), record_rel(asset_id)))
    return rec


def delta(project, asset_id: str) -> str:
    """Project-relative path of the removed-component audio of an asset (written if missing)."""
    e = applied_entry(project.data, asset_id, include_skipped=True)
    if e is None:
        raise InputError(f"no cleanup applied to '{asset_id}'; run clean plan / apply first")
    if e.get("skipped"):
        raise InputError(f"cleanup of '{asset_id}' was skipped (nothing detected): there is no removed component")
    rel = delta_rel(asset_id)
    p = _rel_join(Path(project.root), rel)
    side = _read_json(_sidecar(p))
    if (not p.is_file() or side is None or side.get("plan_hash") != e["plan_hash"]
            or side.get("asset_sha256") != e.get("asset_sha256") or side.get("file_sha256") != sha256_file(p)):
        _materialize(project, asset_id, e.get("overrides") or {}, expect_hash=e["plan_hash"])
    return project.rel(p)


# --------------------------------------------------------------------------
# apply


def _load_baselines(project) -> dict:
    b = _read_json(_rel_join(Path(project.root), BASELINE_FILE)) or {}
    if b.get("kind") != "noise_baselines":
        b = {}
    b.setdefault("kind", "noise_baselines")
    b.setdefault("schema_version", 1)
    b.setdefault("assets", {})
    b.setdefault("routes", {})
    return b


def _write_baselines(project, b: dict) -> str:
    b["note"] = ("P-16 of the cleaned material (SPEC 6.4.3), the reference of the S-08 noise-return guard; "
                 "regenerable from project.json and the assets")
    p = _rel_join(Path(project.root), BASELINE_FILE)
    _write_json(p, b)
    return project.rel(p)


def apply_clean(project, proposal: dict, *, actor: str = "human") -> dict:
    """Approve a ``plan_clean`` proposal: run the cleanup per asset, store the per-track plan
    (mode, overrides, applied plan hashes) and write cache, delta, records and noise baselines.
    Journal op ``clean_apply``."""
    if not isinstance(proposal, dict) or proposal.get("stage") != STAGE:
        raise InputError("not a cleanup proposal (stage 'clean')")
    if proposal.get("status") == "rejected":
        raise InputError("the proposal was rejected; plan again")
    t0 = time.perf_counter()
    data = project.data
    fid = _fullmix_id(data)
    at = _asset_tracks(data)
    todo = list(proposal.get("items") or []) + [s for s in proposal.get("skipped") or [] if s.get("plan_hash")]
    if not todo:
        raise InputError("the proposal has nothing to apply")
    results: list[dict] = []
    entries: dict[str, dict] = {}
    for item in todo:
        aid = item.get("asset")
        asset = project.asset(aid)
        if item.get("asset_sha256") and item["asset_sha256"] != asset.get("sha256"):
            raise ValidationError(f"asset '{aid}' changed since the proposal was made; plan again")
        ov = copy.deepcopy(item.get("overrides") or {})
        plan, x, sr = _plan_for(project, aid, ov)
        if item.get("plan_hash") and plan_hash(plan) != item["plan_hash"]:
            edits = _edited_overrides(item, plan)
            if not edits:
                raise ValidationError(f"the cleanup plan of '{aid}' differs from the proposal "
                                      f"(policy or engine changed); plan again", details={"asset": aid})
            ov = _merge_overrides(ov, edits)
        is_fm = aid == fid
        tracks = [] if is_fm else [t.get("id") for t in at.get(aid, [])]
        e = _materialize(project, aid, ov, tracks=tracks, kind="fullmix" if is_fm else "stem")
        entries[aid] = e
        rec = e["_record"]
        results.append({"asset": aid, "kind": "fullmix" if is_fm else "stem", "tracks": tracks,
                        "plan_hash": e["plan_hash"], "skipped": e["skipped"], "steps": e["steps"],
                        "s07": {k: (rec.get("s07") or {}).get(k) for k in
                                ("residual_dbfs", "residual_stored_dbfs", "limit_dbfs", "pass")},
                        "oversuppression_rerun": ((rec.get("report") or {}).get("oversuppression") or {}).get("rerun"),
                        "p21_pass": ((rec.get("report") or {}).get("p21") or {}).get("pass"),
                        "files": {**(rec.get("files") or {}), "record": e["record_path"]},
                        "seconds": rec.get("seconds")})

    # project.json: per track / full mix, additive to existing cleanup fields
    pid = proposal.get("proposal_id")
    ops: list[dict] = []
    for i, t in enumerate(data.get("tracks") or []):
        mine = {aid: e for aid, e in entries.items() if aid != fid and t in at.get(aid, [])}
        if not mine:
            continue
        cfg = copy.deepcopy(_cfg(t))
        if cfg.get("enabled") is False:
            continue
        cfg.setdefault("enabled", True)
        applied = cfg.get("applied") if isinstance(cfg.get("applied"), dict) else {}
        assets_ap = dict(applied.get("assets") or {})
        for aid, e in mine.items():
            assets_ap[aid] = _public(e)
        ovs = [assets_ap[a].get("overrides") for a in mine]
        cfg["overrides"] = copy.deepcopy(ovs[0]) if ovs and all(o == ovs[0] for o in ovs) else cfg.get("overrides", {})
        cfg["plan"] = "custom" if any(assets_ap[a].get("overrides") for a in assets_ap) else "auto"
        cfg["applied"] = {"version": APPLIED_VERSION, "proposal_id": pid,
                          "plan_hash": canonical_hash({a: assets_ap[a]["plan_hash"] for a in sorted(assets_ap)}),
                          "assets": assets_ap}
        ops.append({"op": "replace" if "cleanup" in t else "add", "path": f"/tracks/{i}/cleanup", "value": cfg})
    if fid is not None and fid in entries:
        cfg = copy.deepcopy(_fullmix_cfg(data))
        cfg.setdefault("enabled", True)
        e = _public(entries[fid])
        cfg["overrides"] = copy.deepcopy(e.get("overrides") or {})
        cfg["plan"] = "custom" if cfg["overrides"] else "auto"
        cfg["applied"] = {"version": APPLIED_VERSION, "proposal_id": pid, "plan_hash": e["plan_hash"],
                          "assets": {fid: e}}
        ops.append({"op": "replace" if FULLMIX_KEY in data else "add", "path": f"/{FULLMIX_KEY}", "value": cfg})
    summary = ", ".join(f"{r['asset']}={'skip' if r['skipped'] else r['plan_hash'][:8]}" for r in results)
    project.apply_patch(ops, actor=actor, reason=f"apply cleanup {pid or ''}: {summary}".strip(), op="clean_apply")

    # noise baselines (S-08 reference)
    b = _load_baselines(project)
    for aid, e in entries.items():
        b["assets"][aid] = {"asset_sha256": e["asset_sha256"], "plan_hash": e["plan_hash"],
                            "cleaned": not e["skipped"], "baseline": e["_baseline"]}
    if fid is not None and fid in entries:
        e = entries[fid]
        b["routes"]["full_mix"] = {"source": "cleaned full mix" if not e["skipped"] else
                                   "full mix (cleanup skipped: nothing detected)",
                                   "asset": fid, "plan_hash": e["plan_hash"], "baseline": e["_baseline"]}
    if any(aid != fid for aid in entries):
        from .mixrender import static_sum
        try:
            xs, ssr, srec = static_sum(project, cleaned=True)
        except InputError:
            xs = None
        if xs is not None:
            cl = srec.get("cleanup") or {}
            b["routes"]["stem_sum"] = {"source": "static sum of the stems (cleaned where applied)",
                                       "cleaned_assets": cl.get("assets") or [],
                                       "summed_assets": srec.get("summed_assets"),
                                       "baseline": noise_baseline(xs, ssr)}
    bpath = _write_baselines(project, b)
    return {"applied": True, "stage": STAGE, "proposal_id": pid, "assets": results,
            "noise_baseline_path": bpath, "s07_pass": all(r["s07"]["pass"] for r in results),
            "seconds": round(time.perf_counter() - t0, 3)}


# --------------------------------------------------------------------------
# verification helpers (S-07, S-08) and records for manifests / reports


def s07_check(project, route: str) -> dict:
    """S-07 for a master route from the cleanup records of the assets that enter it."""
    cl = cleaned_assets(project.data, route)
    if not cl:
        return {"status": "not_applicable", "rule": "S-07",
                "reason": "no cleanup changes the master input of this route (low band untouched)"}
    per = {}
    for aid in sorted(cl):
        rec = cleanup_record(project, aid) or {}
        s = rec.get("s07") or {}
        per[aid] = {"residual_dbfs": s.get("residual_dbfs"), "residual_stored_dbfs": s.get("residual_stored_dbfs"),
                    "limit_dbfs": s.get("limit_dbfs"), "crossover_hz": s.get("crossover_hz"),
                    "pass": s.get("pass"), "plan_hash": cl[aid].get("plan_hash")}
    missing = [a for a, r in per.items() if r["pass"] is None]
    if any(r["pass"] is False for r in per.values()):
        st = "fail"
    elif missing:
        st = "not_run"
    else:
        st = "pass"
    return {"status": st, "rule": "S-07", "assets": per,
            "method": "null test: peak of (cleaned - input) after a brick-wall low-pass at the crossover",
            **({"missing": missing} if missing else {})}


def route_baseline(project, route: str, x: np.ndarray | None = None, sr: int | None = None) -> dict:
    """Noise baseline for the S-08 guard of a route: {baseline, source, cleaned}.

    Full-mix route with an applied cleanup: the stored baseline of the cleaned
    full mix (plan hash checked). Otherwise the baseline is measured on the
    master input ``x`` as given (stems cleaned where applied); without any
    cleanup that is the raw input, and the result says so."""
    data = project.data
    cl = cleaned_assets(data, route)
    if route in ("full_mix", "fullmix"):
        fid = _fullmix_id(data)
        e = applied_entry(data, fid, include_skipped=True) if fid else None
        if e is not None:
            stored = (_load_baselines(project)["assets"].get(fid) or {})
            if stored.get("plan_hash") == e.get("plan_hash") and stored.get("baseline"):
                return {"baseline": stored["baseline"], "cleaned": not e.get("skipped"),
                        "source": ("stored: cleaned full mix" if not e.get("skipped")
                                   else "stored: full mix (cleanup skipped: nothing detected)"),
                        "path": BASELINE_FILE, "plan_hash": e.get("plan_hash")}
            rec = cleanup_record(project, fid) or {}
            if rec.get("noise_baseline"):
                return {"baseline": rec["noise_baseline"], "cleaned": not e.get("skipped"),
                        "source": "cleanup record of the full mix", "path": record_rel(fid),
                        "plan_hash": e.get("plan_hash")}
    if x is None:
        from .routes import load_master_input
        x, sr = load_master_input(project, route)
    base = noise_baseline(x, int(sr))
    if cl:
        return {"baseline": base, "cleaned": True,
                "source": "measured on the master input built from cleaned assets",
                "cleaned_assets": sorted(cl)}
    return {"baseline": base, "cleaned": False,
            "source": "measured on the master input as is: no cleanup has been applied, so the guard "
                      "checks that mastering does not raise the noise of the raw input"}


def s08_check(baseline_info: dict, y: np.ndarray, sr: int, out_lufs: float | None) -> dict:
    """S-08 for one rendered output. The gain change is the output's integrated loudness minus the
    baseline's (level metrics are compensated by it; the shimmer index is gain-invariant)."""
    base = baseline_info["baseline"]
    bl = base.get("integrated_lufs")
    if out_lufs is not None and bl is not None and math.isfinite(out_lufs):
        gain, gsrc = float(out_lufs) - float(bl), "output integrated loudness - baseline integrated loudness"
    else:
        gain, gsrc = None, None
    r = noise_return_check(base, y, sr, gain_db=gain)
    judged = [c for c in r["deltas"].values() if c.get("pass") is not None]
    info = {k: baseline_info.get(k) for k in ("source", "cleaned", "path", "plan_hash", "cleaned_assets")
            if baseline_info.get(k) is not None}
    if not judged:
        return {"status": "not_run", "rule": "S-08", "reason": "no P-16 metric measurable on this output",
                "baseline": info, "deltas": r["deltas"]}
    return {"status": "pass" if r["pass"] else "fail", "rule": "S-08", "baseline": info,
            "gain_db": r["gain_db"], "gain_source": gsrc or r["gain_source"],
            "deltas": r["deltas"], "suggestions": r["suggestions"], "note": r["note"]}


def route_cleanup_record(project, route: str) -> dict:
    """Cleanup facts for a render manifest (SPEC 9.6): assets entering the route cleaned, with plan hashes."""
    cl = cleaned_assets(project.data, route)
    return {"applied": bool(cl),
            "assets": [{"asset": aid, "asset_sha256": e.get("asset_sha256"), "plan_hash": e.get("plan_hash"),
                        "plan_version": e.get("plan_version"), "steps": e.get("steps")}
                       for aid, e in sorted(cl.items())],
            "neural_completion_used": False}


def cleanup_summary(project, route: str | None = None) -> dict:
    """Cleanup section of the Mix Report (SPEC 6.8 section 7) from the stored records."""
    data = project.data
    ids = []
    fid = _fullmix_id(data)
    if route in (None, "full_mix", "fullmix") and fid is not None:
        ids.append(fid)
    if route in (None, "stem_mix", "stem_sum"):
        ids += [a for a in _asset_tracks(data) if a not in ids]
    out = []
    for aid in ids:
        e = applied_entry(data, aid, include_skipped=True)
        if e is None:
            continue
        rec = cleanup_record(project, aid) or {}
        rep = rec.get("report") or {}
        out.append({"asset": aid, "skipped": rec.get("skipped"), "reasons": rec.get("reasons"),
                    "steps": {k: s.get("action") for k, s in (rec.get("steps") or {}).items()},
                    "removed_energy": rep.get("removed_energy"), "p21": rep.get("p21"),
                    "s07": rec.get("s07"), "oversuppression": rep.get("oversuppression"),
                    "delta": (rec.get("files") or {}).get("delta"), "record": record_rel(aid),
                    "plan_hash": rec.get("plan_hash")})
    if not out:
        return {"status": "not_applied", "assets": [],
                "note": {"ja": "整音は適用されていない", "en": "No cleanup was applied"}}
    return {"status": "applied", "assets": out, "noise_baseline": BASELINE_FILE,
            "neural_completion_used": False}


__all__ = [
    "plan_clean", "apply_clean", "cleaned_asset_path", "delta", "cleanup_record", "ensure_cleaned",
    "asset_audio_path", "track_cleanup_entry", "fullmix_cleanup_entry", "applied_entry", "cleaned_assets",
    "plan_hash", "s07_check", "s08_check", "route_baseline", "route_cleanup_record", "cleanup_summary",
    "cache_rel", "delta_rel", "record_rel", "BASELINE_FILE",
]
