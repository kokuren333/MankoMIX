"""Variant rendering with S-01/S-02 loop and render manifests (SPEC 6.6.2, 6.7, 9.6).

For every output (profile x delivery) of a variant:

1. render the master chain (stage "master") on the master input,
2. export through the export module (resample / dither once, S-05),
3. measure the exported file: true peak (S-01) and the codec round-trip
   true peak for each codec of the profile that ffmpeg can encode (S-02),
4. if a ceiling is exceeded, lower the limiter ceiling by the configured
   step and re-render (bounded iterations). The limiter drive follows the
   ceiling down by the same amount while the output stays inside the
   profile's loudness window (floor + margin): a lower ceiling then does not
   make the limiter work harder than planned (R-14, S-08). Below that the
   drive is kept and the extra gain reduction is recorded.

An ``archive_f32`` master of the planned chain is written once per variant.
Every file gets a manifest (project hash, asset hashes, cleanup plan hashes,
engine and backend versions, definition hashes, dither seed, iterations). Manifests contain
project-relative paths only.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import mankomix

from . import audio_io, config
from .errors import InputError
from .hashing import canonical_hash, sha256_file
from .mastering import (codec_after_ceiling, definition_hashes, effective_ceiling, engine_chain, find_variant,
                        limiter_ceiling, loudness_window, objective_ids, thresholds, tv, validate_master_chain,
                        with_limiter_ceiling)
from .measure import loudness as ld
from .routes import fullmix_asset_id, load_master_input, select_route, stem_tracks

MANIFEST_SUFFIX = ".manifest.json"
ARCHIVE_DELIVERY = "archive_f32"


# --------------------------------------------------------------------------
# small helpers


def seed_inputs(variant: dict, asset_hashes: list[str], profile_id: str | None, delivery_id: str) -> dict:
    """What determines one render: input asset hashes, the variant's objective /
    route / master chain / outputs, and the output's profile + delivery ids (SPEC 9.6).

    Other variants and unrelated project fields do not enter, so editing them
    does not change this render's dither.
    """
    master = variant.get("master") or {}
    return {
        "assets": sorted(h for h in asset_hashes if h),
        "variant": {
            "id": variant.get("id"),
            "objective": variant.get("objective"),
            "route": master.get("route_detail") or master.get("route"),
            "chain": master.get("chain") or [],
            "outputs": variant.get("outputs") or [],
        },
        "output": {"profile": profile_id, "delivery": delivery_id},
    }


def dither_seed(inputs: dict) -> tuple[int, str]:
    """(32-bit seed, sha256 of the canonical seed inputs)."""
    h = canonical_hash(inputs)
    return int(h[:8], 16), h


def output_ext(delivery: dict) -> str:
    c = delivery.get("container", "wav")
    if isinstance(c, list):
        c = c[0] if c else "wav"
    return {"aiff": "aiff", "flac": "flac"}.get(c, "wav")


def output_name(profile_id: str, delivery: dict) -> str:
    return f"{profile_id}__{delivery['id']}.{output_ext(delivery)}"


def manifest_path_for(audio_path: Path) -> Path:
    return audio_path.with_name(audio_path.stem + MANIFEST_SUFFIX)


def variant_dir(project, variant_id: str) -> Path:
    return Path(project.root) / "renders" / variant_id


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False, sort_keys=False)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text + "\n")


def _json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, Path):
        return obj.name
    return obj


def ffmpeg_info() -> dict:
    """{available, version, configuration, build} of the user's ffmpeg (never bundled)."""
    try:
        from mankomix.dsp import ffmpeg_backend as fb
    except ImportError:
        return {"available": False}
    try:
        if not fb.available():
            return {"available": False}
        vi = fb.version_info() or {}
        return {"available": True, "version": vi.get("version"), "configuration": vi.get("configuration"),
                "build": vi.get("build")}
    except Exception as exc:  # environment problems are recorded, not fatal
        return {"available": False, "error": str(exc)}


def codec_true_peaks(y: np.ndarray, sr: int, codecs: list[str], ceiling: float, th: dict) -> dict:
    """S-02: encode/decode each codec and re-measure TP. Unavailable -> not_run."""
    bitrates = tv(th, "s02_codec", "bitrates", default={}) or {}
    out = {}
    try:
        from mankomix.dsp import ffmpeg_backend as fb
        have = bool(fb.available())
    except ImportError:
        fb, have = None, False
    for codec in codecs:
        br = bitrates.get(codec, "256k")
        rec = {"codec": codec, "bitrate": br, "ceiling_dbtp": ceiling}
        if not have:
            rec.update(status="not_run", reason="ffmpeg not available")
            out[codec] = rec
            continue
        try:
            rt = fb.encode_decode_roundtrip(y, sr, codec, br, return_info=True)
        except Exception as exc:
            rt = None
            rec["reason"] = f"round trip failed: {exc}"
        if rt is None:
            rec.update(status="not_run")
            rec.setdefault("reason", "encoder not available in this ffmpeg build")
            out[codec] = rec
            continue
        yy, ssr = rt[0], rt[1]
        if len(rt) > 2 and isinstance(rt[2], dict):
            rec["encoder"] = rt[2].get("encoder")
        tp = float(ld.true_peak_dbtp(yy, ssr))
        rec.update(status="pass" if tp <= ceiling + 1e-9 else "fail", true_peak_dbtp=round(tp, 3))
        out[codec] = rec
    return out


def _step_backends(steps) -> list[dict]:
    out = []
    for st in steps or []:
        d = {k: st.get(k) for k in ("id", "type", "backend", "backend_version", "version") if st.get(k) is not None}
        for key in ("fallback", "stats"):
            if key in st and (key == "fallback" or st.get("type") in ("denoise_ml", "amp_sim")):
                d[key] = _json_safe(st[key])
        out.append(d)
    return out


def _add_mix_provenance(manifest: dict, mix_record: dict | None) -> None:
    """Append executed mix facts without changing manifests for ordinary mixes."""
    from mankomix.dspx.bb.ml import report_records
    mix_record = mix_record or {}
    steps = []
    for group, scope in (("tracks", "track_id"), ("buses", "bus_id")):
        for item in mix_record.get(group) or []:
            for step in _step_backends(item.get("chain")):
                if "fallback" in step or "stats" in step:
                    steps.append(dict(step, **{scope: item.get("id")}))
    if not steps:
        return
    manifest["steps"].extend(steps)
    manifest["render_warnings"].extend(_json_safe(mix_record.get("warnings") or []))
    records = report_records(steps)
    manifest["model_records"] = _json_safe(records)
    manifest["models"] = list(manifest["models"])
    manifest["models"].extend(_json_safe([r for r in records
                                         if not r.get("fallback_used") and not r.get("inference_skipped")]))


def _asset_records(project, route: str) -> list[dict]:
    data = project.data
    ids = []
    if route == "full_mix":
        fid = fullmix_asset_id(data)
        if fid:
            ids.append(fid)
    else:
        for t in stem_tracks(data):
            for c in t.get("clips", []) or []:
                if c.get("asset") and c["asset"] not in ids:
                    ids.append(c["asset"])
    recs = []
    for a in data.get("assets", []) or []:
        if a.get("id") in ids:
            recs.append({"id": a["id"], "path": a.get("path"), "sha256": a.get("sha256")})
    return recs


def _cleanup_record(project, route: str) -> dict:
    from .cleanstage import route_cleanup_record
    return route_cleanup_record(project, route)


def _drive_db(chain: list[dict]) -> float | None:
    """Limiter drive: the loudness_gain step of the master chain (slot 5)."""
    for p in chain or []:
        if p.get("type") == "loudness_gain" and p.get("enabled", True) is not False:
            return float((p.get("params") or {}).get("gain_db", 0.0))
    return None


def _with_drive(chain: list[dict], ceiling: float, drive_db: float | None) -> list[dict]:
    out = with_limiter_ceiling(chain, ceiling)
    if drive_db is not None:
        for p in out:
            if p.get("type") == "loudness_gain":
                p["params"]["gain_db"] = round(float(drive_db), 3)
                break
    return out


def _render_master(x, sr, chain):
    from mankomix.dsp import engine
    return engine.render_chain(x, sr, engine_chain(chain), stage="master", seed=0)


def _export(audio, sr, delivery, path: Path, seed: int) -> dict:
    from mankomix.dsp import engine
    rec = engine.export_audio(audio, sr, delivery, path, seed=seed)
    return rec if isinstance(rec, dict) else {}


def variant_route(project, variant: dict) -> str:
    m = variant.get("master") or {}
    r = m.get("route_detail") or m.get("route")
    if r in (None, "auto"):
        return select_route(project)["route"]
    return {"fullmix": "full_mix"}.get(r, r)


def _objective_for(project, variant):
    return variant.get("objective") or project.data.get("objective")


# --------------------------------------------------------------------------
# main entry


def render_variant(project, variant_id: str, *, outputs: list[dict] | None = None) -> dict:
    """Render every output of a variant (or the given subset). Returns a summary dict."""
    data = project.data
    variant = find_variant(data, variant_id)
    if variant is None:
        raise InputError(f"unknown variant '{variant_id}'",
                         details={"valid": [v.get("id") for v in data.get("variants", []) or []]})
    chain = (variant.get("master") or {}).get("chain") or []
    if not chain:
        raise InputError(f"variant '{variant_id}' has no master chain; run master plan/apply first")
    validate_master_chain(chain)
    outs = outputs if outputs is not None else (variant.get("outputs") or [])
    if not outs:
        raise InputError(f"variant '{variant_id}' has no outputs")

    th = thresholds()
    floor_margin = float(tv(th, "loudness", "window_floor_margin_lu", default=0.3))
    step_db = float(tv(th, "s02_codec", "ceiling_step_db", default=0.2))
    max_iter = int(tv(th, "s02_codec", "max_iterations", default=6))
    route = variant_route(project, variant)
    x, sr = load_master_input(project, route, variant_id=variant_id)
    mix_record = getattr(project, "_mix_render_record", None) if route == "stem_mix" else None
    project_hash = project.content_hash()
    obj_ids = objective_ids(_objective_for(project, variant))
    vdir = variant_dir(project, variant_id)
    vdir.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg_info()
    planned_ceiling = limiter_ceiling(chain)
    planned_drive = _drive_db(chain)

    common = {
        "schema_version": 1,
        "kind": "render_manifest",
        "variant": variant_id,
        "project_hash": project_hash,
        "project_id": data.get("id"),
        "route": route,
        "assets": _asset_records(project, route),
        # cleanup plan hashes of the assets that enter the master input cleaned (SPEC 6.4, 9.6)
        "cleanup": _cleanup_record(project, route),
        "engine_version": mankomix.__version__,
        "models": [],
        "input": {"frames": int(x.shape[0]), "sample_rate": int(sr), "channels": int(x.shape[1])},
    }

    base = _render_master(x, sr, chain)
    results = []

    # archive master (once per variant)
    archive = config.get_delivery(ARCHIVE_DELIVERY)
    a_path = vdir / f"master__{ARCHIVE_DELIVERY}.{output_ext(archive)}"
    asset_recs = _asset_records(project, route)
    asset_hashes = [a.get("sha256") for a in asset_recs]
    a_seed, a_seed_hash = dither_seed(seed_inputs(variant, asset_hashes, None, ARCHIVE_DELIVERY))
    a_exp = _export(base.audio, base.sr, archive, a_path, a_seed)
    a_man = dict(common)
    a_man.update({
        "output": {"profile": None, "delivery": ARCHIVE_DELIVERY},
        "file": project.rel(a_path),
        "file_sha256": sha256_file(a_path),
        "chain": chain,
        "steps": _json_safe(_step_backends(base.steps)),
        "render_warnings": _json_safe(list(base.warnings or [])),
        "backends": {"engine": "mankomix.dsp", "dsp": _json_safe(getattr(base, "backends", {}) or {}),
                     "export": _json_safe(a_exp.get("backends") or {}), "ffmpeg": {"used": False}},
        "definitions": definition_hashes(None, archive, obj_ids),
        "dither": {"seed": a_seed, "seed_inputs_sha256": a_seed_hash},
        "export": _json_safe(a_exp),
    })
    _add_mix_provenance(a_man, mix_record)
    _write_json(manifest_path_for(a_path), _json_safe(a_man))
    archive_rec = {"file": project.rel(a_path), "manifest": project.rel(manifest_path_for(a_path))}

    for out in outs:
        profile = config.get_profile(out["profile"])
        delivery = config.get_delivery(out["delivery"])
        path = vdir / output_name(profile["id"], delivery)
        seed, seed_hash = dither_seed(seed_inputs(variant, asset_hashes, profile["id"], delivery["id"]))
        codecs = list(profile.get("codec_checks") or [])
        codec_ceiling = codec_after_ceiling(profile, th)
        ceiling = planned_ceiling
        drive = planned_drive
        window = loudness_window(profile)
        res = base
        iterations = []
        ff_used = False
        status = "fail"
        for it in range(max_iter + 1):
            if it > 0:
                res = _render_master(x, sr, _with_drive(chain, ceiling, drive))
            exp = _export(res.audio, res.sr, delivery, path, seed)
            y, ysr = audio_io.read(path)
            lufs = float(ld.integrated(y, ysr))
            tp = float(ld.true_peak_dbtp(y, ysr))
            out_ceiling = effective_ceiling(profile, lufs, out.get("ceiling_dbtp"))
            codec_res = codec_true_peaks(y, ysr, codecs, codec_ceiling, th) if codecs else {}
            if any(r["status"] != "not_run" for r in codec_res.values()):
                ff_used = True
            s01_ok = tp <= out_ceiling + 1e-9
            s02_ok = all(r["status"] != "fail" for r in codec_res.values())
            iterations.append({
                "iteration": it,
                "limiter_ceiling_dbtp": round(float(ceiling), 3),
                "drive_db": None if drive is None else round(float(drive), 3),
                "lufs_i": round(lufs, 3),
                "true_peak_dbtp": round(tp, 3),
                "s01_ceiling_dbtp": out_ceiling,
                "codecs": {c: {k: r.get(k) for k in ("status", "true_peak_dbtp", "bitrate", "encoder")}
                           for c, r in codec_res.items()},
            })
            if s01_ok and s02_ok:
                status = "pass"
                break
            if it == max_iter:
                break
            # lower the original-side ceiling and re-render (S-02); S-01 overshoot from
            # resampling / dither is handled the same way.
            excess = max(tp - out_ceiling if not s01_ok else 0.0,
                         max([r["true_peak_dbtp"] - codec_ceiling for r in codec_res.values()
                              if r["status"] == "fail"] or [0.0]))
            n_steps = max(1, math.ceil(excess / step_db - 1e-9))
            new_ceiling = max(round(ceiling - n_steps * step_db, 3), -12.0)
            if drive is not None:
                # the drive follows the ceiling (same gain reduction), inside the loudness window
                room = (math.inf if window is None or not math.isfinite(lufs)
                        else max(0.0, lufs - (window[0] + floor_margin)))
                drive = round(drive - min(ceiling - new_ceiling, room), 3)
            ceiling = new_ceiling

        man = dict(common)
        man.update({
            "output": {"profile": profile["id"], "delivery": delivery["id"]},
            "file": project.rel(path),
            "file_sha256": sha256_file(path),
            "chain": _with_drive(chain, ceiling, drive),
            "planned_limiter_ceiling_dbtp": planned_ceiling,
            "final_limiter_ceiling_dbtp": round(float(ceiling), 3),
            "planned_drive_db": planned_drive,
            "final_drive_db": None if drive is None else round(float(drive), 3),
            # ceiling drop not followed by the drive = extra limiter gain reduction vs the plan (S-08 risk)
            "extra_limiting_db": (round(max(0.0, (planned_ceiling - ceiling) - (planned_drive - drive)), 3)
                                  if None not in (planned_ceiling, planned_drive, drive) else None),
            "steps": _json_safe(_step_backends(res.steps)),
            "render_warnings": _json_safe(list(res.warnings or [])),
            "backends": {"engine": "mankomix.dsp", "dsp": _json_safe(getattr(res, "backends", {}) or {}),
                         "export": _json_safe(exp.get("backends") or {}),
                         "ffmpeg": ({"used": True, "purpose": "codec round trip (S-02)",
                                     "version": ff.get("version"), "configuration": ff.get("configuration"),
                                     "build": ff.get("build")} if ff_used else {"used": False})},
            "definitions": definition_hashes(profile, delivery, obj_ids),
            "dither": {"seed": seed, "seed_inputs_sha256": seed_hash,
                       "seed_inputs": "asset sha256s + variant (objective, route, master chain, outputs) + profile/delivery ids"},
            "export": _json_safe(exp),
            "s02": {"status": status, "codec_after_ceiling_dbtp": codec_ceiling,
                    "iterations": iterations, "iteration_count": len(iterations),
                    "codecs": codec_res,
                    "codecs_not_run": [c for c, r in codec_res.items() if r["status"] == "not_run"]},
            "measured": {"lufs_i": round(lufs, 3), "true_peak_dbtp": round(tp, 3)},
        })
        mpath = manifest_path_for(path)
        _add_mix_provenance(man, mix_record)
        _write_json(mpath, _json_safe(man))
        results.append({"profile": profile["id"], "delivery": delivery["id"], "file": project.rel(path),
                        "manifest": project.rel(mpath), "status": status, "iterations": len(iterations),
                        "lufs_i": round(lufs, 2), "true_peak_dbtp": round(tp, 2),
                        "limiter_ceiling_dbtp": round(float(ceiling), 3),
                        "drive_db": None if drive is None else round(float(drive), 3),
                        "codecs": {c: r["status"] for c, r in codec_res.items()}})

    return {"variant": variant_id, "route": route, "archive": archive_rec, "outputs": results}


def load_manifest(project, variant_id: str, profile_id: str | None, delivery_id: str) -> dict | None:
    delivery = config.get_delivery(delivery_id)
    vdir = variant_dir(project, variant_id)
    name = (f"master__{delivery_id}.{output_ext(delivery)}" if profile_id is None
            else output_name(profile_id, delivery))
    p = manifest_path_for(vdir / name)
    if not p.is_file():
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)
