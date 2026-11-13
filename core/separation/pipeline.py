"""Stem separation inside a project (SPEC 6.2, 12.2, R-22, S-10, S-11).

``separate()`` runs a registered model on one project asset:

1. resolves the model through the registry (verified local weights only;
   nothing is downloaded here);
2. makes a TEMP copy of the source (preview: the loudest excerpt; full: the
   whole file), resampled to the model rate and normalised to about
   -14 LUFS / -1 dBFS peak; the original asset is never touched;
3. runs ``python -m mankomix.core.separation.worker`` in a subprocess;
4. post-processes cheaply: undo the gain and the resampling, check the head
   alignment against the source (and fix a constant offset), measure the
   residual of the stem sum;
5. writes the stems as new project assets (origin "separated"), optionally
   adds tracks restricted to balance operations (R-22), and records model
   id, sha256, license and attribution in ``ingest.separations``.
"""

from __future__ import annotations

import json
import math
import os
import secrets
import shutil
import subprocess
import sys
import time
from math import gcd
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import resample_poly

import mankomix

from .. import audio_io, registry
from ..errors import EnvironmentProblem, InputError, ValidationError
from ..hashing import sha256_file

MODES = ("preview", "full")
TARGET_LUFS = -14.0
TARGET_PEAK_DBFS = -1.0
PREVIEW_SECONDS = 30.0
MAX_STEMS_WITHOUT_WARNING = 4
HEAD_CHECK_SECONDS = 5.0
HEAD_MAX_LAG_S = 0.05
WORKER_MODULE = "mankomix.core.separation.worker"
DEFAULT_TIMEOUT_S = 3600
RESTRICTION = {
    "operations": ["balance"],
    "rule": "R-22",
    "reason": "separated stem: contains bleed from other parts; use for balance, not surgery",
}
STEM_ROLE = {
    "vocals": "vocals", "drums": "drums", "bass": "bass", "other": "other",
    "instrumental": "other", "accompaniment": "other", "piano": "keyboard", "keys": "keyboard",
    "guitar": "guitar", "strings": "strings", "synth": "synth", "backing_vocals": "backing_vocals",
}


# --- helpers --------------------------------------------------------------------------------------

def _open(project):
    from ..project import Project

    if isinstance(project, Project):
        return project
    return Project.open(project)


def _resample(x: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """x [frames, channels]; scipy polyphase (reference backend, D-057)."""
    if sr_from == sr_to:
        return x
    g = gcd(int(sr_from), int(sr_to))
    return resample_poly(x, sr_to // g, sr_from // g, axis=0)


def _loudest_excerpt(x: np.ndarray, sr: int, seconds: float) -> tuple[int, int]:
    n = x.shape[0]
    length = int(round(seconds * sr))
    if n <= length:
        return 0, n
    block = sr // 2
    nblk = n // block
    e = np.square(x[: nblk * block].mean(axis=1)).reshape(nblk, block).sum(axis=1)
    k = max(1, length // block)
    if nblk <= k:
        return 0, length
    c = np.concatenate([[0.0], np.cumsum(e)])
    sums = c[k:] - c[:-k]
    start = int(np.argmax(sums)) * block
    start = min(start, n - length)
    return start, length


def _normalise_gain(x: np.ndarray, sr: int) -> tuple[float, dict]:
    from ..measure import loudness

    lufs = float(loudness.integrated(x, sr))
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if not math.isfinite(lufs) or peak <= 0.0:
        raise InputError("the source excerpt is silent; nothing to separate")
    gain_db = TARGET_LUFS - lufs
    peak_after = 20 * math.log10(peak) + gain_db
    limited = False
    if peak_after > TARGET_PEAK_DBFS:
        gain_db -= peak_after - TARGET_PEAK_DBFS
        limited = True
    return 10 ** (gain_db / 20), {"target_lufs": TARGET_LUFS, "target_peak_dbfs": TARGET_PEAK_DBFS,
                                  "source_lufs": round(lufs, 2), "gain_db": round(gain_db, 2),
                                  "peak_limited": limited}


def _head_offset(ref: np.ndarray, est: np.ndarray, sr: int) -> int:
    """Lag (samples) of est against ref over the head; positive = est is late."""
    n = min(ref.shape[0], est.shape[0], int(HEAD_CHECK_SECONDS * sr))
    if n < 64:
        return 0
    a = ref[:n].mean(axis=1)
    b = est[:n].mean(axis=1)
    if not np.any(a) or not np.any(b):
        return 0
    size = 1 << int(math.ceil(math.log2(2 * n)))
    corr = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)
    max_lag = int(HEAD_MAX_LAG_S * sr)
    lags = np.concatenate([np.arange(0, max_lag + 1), np.arange(-max_lag, 0)])
    vals = np.concatenate([corr[: max_lag + 1], corr[-max_lag:]])
    return int(lags[int(np.argmax(vals))])


def _shift(x: np.ndarray, lag: int) -> np.ndarray:
    """Move x earlier by lag samples (lag > 0) or later (lag < 0), keeping the length."""
    if lag == 0:
        return x
    out = np.zeros_like(x)
    if lag > 0:
        out[:-lag] = x[lag:]
    else:
        out[-lag:] = x[:lag]
    return out


def _db(v: float) -> float | None:
    return round(20 * math.log10(v), 2) if v > 0 else None


def _unique(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def _worker_env() -> dict:
    env = dict(os.environ)
    root = str(mankomix.repo_data_root())
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["HF_HUB_OFFLINE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_worker(request: dict, work_dir: Path, *, timeout_s: float | None = None) -> dict:
    """Write the request, run the worker subprocess, return its result.json."""
    work_dir.mkdir(parents=True, exist_ok=True)
    req_path = work_dir / "request.json"
    req_path.write_text(json.dumps(request, indent=2), encoding="utf-8")
    cmd = [sys.executable, "-m", WORKER_MODULE, "--request", str(req_path)]
    try:
        proc = subprocess.run(cmd, cwd=str(work_dir), env=_worker_env(), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_s or DEFAULT_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise EnvironmentProblem("separation worker timed out") from exc
    except OSError as exc:
        raise EnvironmentProblem("cannot start the separation worker", details={"error": str(exc)}) from exc
    res_path = Path(request["output_dir"]) / "result.json"
    try:
        result = json.loads(res_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        tail = (proc.stderr or "").strip().splitlines()[-5:]
        raise EnvironmentProblem("separation worker failed without a result",
                                 details={"exit_code": proc.returncode, "stderr_tail": tail})
    if not result.get("ok"):
        cls = InputError if result.get("kind") == "input" else EnvironmentProblem
        raise cls(f"separation failed: {result.get('error')}", details={"exit_code": proc.returncode})
    return result


def _model_rate(entry: dict, fallback: int) -> int:
    rt = entry.get("runtime") or {}
    return int(rt.get("sample_rate") or (rt.get("config") or {}).get("sample_rate") or fallback)


def _pick_source(data: dict, source_asset: str | None) -> str:
    if source_asset:
        return source_asset
    if data.get("fullmix_asset"):
        return data["fullmix_asset"]
    assets = [a for a in data.get("assets") or [] if a.get("origin") != "separated"]
    if len(assets) == 1:
        return assets[0]["id"]
    raise InputError("the project has no full mix; name the asset to separate (source_asset)",
                     details={"assets": [a.get("id") for a in assets]})


def separation_records(project) -> list[dict]:
    """Separation records of a project (for render manifests and the Mix Report)."""
    proj = _open(project)
    return list(((proj.data.get("ingest") or {}).get("separations")) or [])


# --- main entry ------------------------------------------------------------------------------------------

def separate(project, *, model_id: str | None = None, source_asset: str | None = None, mode: str = "preview",
             stems: list[str] | None = None, device: str = "auto", allow_candidate: bool = False,
             add_tracks: bool | None = None, excerpt_s: float = PREVIEW_SECONDS, actor: str = "human",
             timeout_s: float | None = None) -> dict:
    if mode not in MODES:
        raise InputError(f"unknown mode '{mode}' (use preview or full)")
    if device not in ("auto", "cpu", "cuda"):
        raise InputError(f"unknown device '{device}' (use auto, cpu or cuda)")
    if not (isinstance(excerpt_s, (int, float)) and excerpt_s > 0):
        raise InputError("excerpt_s must be > 0")
    proj = _open(project)
    if model_id is None:
        model_id = registry.default_model(mode)
        if model_id is None:
            raise InputError(f"no default model for mode '{mode}'; pass model_id")
    resolved = registry.resolve_for_run(model_id, allow_candidate=allow_candidate)
    entry = resolved["entry"]
    if entry.get("task") != "separation":
        raise InputError(f"model '{model_id}' is not a separation model (task '{entry.get('task')}')")
    rt = entry.get("runtime") or {}
    if not rt.get("backend"):
        raise InputError(f"model '{model_id}' has no runtime backend; it cannot be run")
    warnings: list[str] = list(resolved["warnings"])

    model_stems = list(entry.get("stems") or [])
    if stems is None:
        wanted = model_stems
    else:
        if not isinstance(stems, list) or not stems:
            raise InputError("stems must be a non-empty list")
        unknown = [s for s in stems if s not in model_stems]
        if unknown:
            raise InputError(f"model '{model_id}' does not produce {unknown}", details={"stems": model_stems})
        wanted = list(dict.fromkeys(stems))
    if len(model_stems) > MAX_STEMS_WITHOUT_WARNING or len(wanted) > MAX_STEMS_WITHOUT_WARNING:
        warnings.append(f"more than {MAX_STEMS_WITHOUT_WARNING} stems requested: separation quality drops "
                        "sharply beyond 4 stems (SPEC 6.2)")
    if device == "cpu" and not rt.get("cpu_ok"):
        warnings.append(f"model '{model_id}' is not meant for CPU; it may be very slow")
    if mode == "preview" and not rt.get("light"):
        warnings.append(f"model '{model_id}' is not a light model; previews are faster with "
                        f"'{registry.default_model('preview')}'")

    data = proj.data
    src_id = _pick_source(data, source_asset)
    src = proj.asset(src_id)
    if src.get("origin") == "separated":
        warnings.append("the source is itself a separated stem; bleed accumulates")
    src_path = proj.asset_path(src_id)
    x, sr = audio_io.read(src_path)
    if x.shape[0] == 0:
        raise InputError(f"asset '{src_id}' is empty")

    if mode == "preview":
        start, length = _loudest_excerpt(x, sr, float(excerpt_s))
    else:
        start, length = 0, x.shape[0]
    seg = np.ascontiguousarray(x[start:start + length])
    gain, pre = _normalise_gain(seg, sr)
    rate = _model_rate(entry, sr)

    sep_id = "sep_" + secrets.token_hex(4)
    work = Path(proj.root) / "cache" / f"separation_{sep_id}"
    try:
        tmp_in = _resample(seg * gain, sr, rate).astype(np.float32)
        audio_io.write(work / "input.wav", tmp_in, rate, subtype="FLOAT")
        request = {
            "protocol": 1,
            "backend": rt["backend"],
            "architecture": entry.get("architecture"),
            "config": rt.get("config") or {},
            "weights": {name: str(p) for name, p in resolved["paths"].items()},
            "roles": resolved["roles"],
            "input": str(work / "input.wav"),
            "output_dir": str(work / "out"),
            "device": device,
        }
        t0 = time.perf_counter()
        result = run_worker(request, work, timeout_s=timeout_s)
        wall = time.perf_counter() - t0
        produced = result.get("stems") or {}
        if device == "auto" and result.get("device") == "cpu" and not rt.get("cpu_ok"):
            warnings.append(f"model '{model_id}' ran on the CPU (no GPU available); it is not meant for CPU")
        missing = [s for s in wanted if s not in produced]
        if missing:
            raise EnvironmentProblem(f"worker did not produce stems {missing}", details={"produced": list(produced)})

        outs: dict[str, np.ndarray] = {}
        for stem in wanted:
            y, ysr = audio_io.read(work / "out" / produced[stem])
            y = _resample(y, ysr, sr) / gain
            if y.shape[0] < length:
                y = np.concatenate([y, np.zeros((length - y.shape[0], y.shape[1]))])
            y = y[:length]
            if y.shape[1] != seg.shape[1]:
                y = y.mean(axis=1, keepdims=True) if seg.shape[1] == 1 else np.repeat(y[:, :1], seg.shape[1], axis=1)
            outs[stem] = y
        if not all(np.all(np.isfinite(v)) for v in outs.values()):
            raise ValidationError("separation produced NaN or infinite samples")

        # post-processing: head alignment and residual (only meaningful with every stem)
        post: dict[str, Any] = {"head_offset_samples": None, "head_offset_fixed": False, "residual_db": None}
        if set(wanted) == set(model_stems):
            total = sum(outs.values())
            lag = _head_offset(seg, total, sr)
            post["head_offset_samples"] = lag
            if lag != 0:
                outs = {k: _shift(v, lag) for k, v in outs.items()}
                total = sum(outs.values())
                post["head_offset_fixed"] = True
                warnings.append(f"stems were {lag} samples off against the source; shifted back")
            ref = float(np.sqrt(np.mean(np.square(seg))))
            res = float(np.sqrt(np.mean(np.square(seg - total))))
            post["residual_db"] = _db(res / ref) if ref > 0 else None

        # write assets
        assets = data.setdefault("assets", [])
        tracks = data.setdefault("tracks", [])
        asset_ids = {a["id"] for a in assets}
        track_ids = {t["id"] for t in tracks}
        clip_ids = {c["id"] for t in tracks for c in t.get("clips") or []}
        out_dir = Path(proj.root) / "assets" / "separated"
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        new_assets: list[dict] = []
        model_sha = resolved["model_sha256"]
        stem_records = []
        try:
            for stem, y in outs.items():
                fname = f"{sep_id}_{stem}.wav"
                dest = out_dir / fname
                audio_io.write(dest, y.astype(np.float32), sr, subtype="FLOAT")
                written.append(dest)
                info = audio_io.info(dest)
                role = STEM_ROLE.get(stem, "other")
                aid = _unique(f"ast_sep_{stem}", asset_ids)
                asset_ids.add(aid)
                new_assets.append({
                    "id": aid, "path": f"assets/separated/{fname}", "original_name": fname,
                    "sha256": sha256_file(dest), "format": "wav_f32", "container": "wav", "subtype": "FLOAT",
                    "lossy": False, "channels": info.channels, "sample_rate": info.sample_rate,
                    "length_samples": info.frames, "duration_s": round(info.duration_s, 6),
                    "role": role, "role_source": "default",
                    "role_note": f"stem '{stem}' separated by model '{model_id}'",
                    "origin": "separated", "linked": False,
                    "separation": {"record": sep_id, "model_id": model_id, "model_sha256": model_sha,
                                   "stem": stem, "source_asset": src_id, "mode": mode,
                                   "source_start": start, "length": length},
                })
                stem_records.append({"stem": stem, "asset": aid, "role": role})
        except Exception:
            for w in written:
                w.unlink(missing_ok=True)
            raise
        assets.extend(new_assets)

        if add_tracks is None:
            add_tracks = mode == "full"
        new_tracks: list[dict] = []
        muted: list[str] = []
        if add_tracks:
            from ..adapters.file import DEFAULT_IMPORTANCE
            from ..ingest.checks import length_at_rate

            pr = (data.get("timebase") or {}).get("sample_rate") or sr
            for rec, a in zip(stem_records, new_assets):
                slug = a["id"][len("ast_"):]
                tid = _unique(f"trk_{slug}", track_ids)
                track_ids.add(tid)
                cid = _unique(f"clp_{slug}", clip_ids)
                clip_ids.add(cid)
                track = {
                    "id": tid, "kind": "audio", "name": f"{rec['stem']} (separated)", "role": a["role"],
                    "is_lead": False,
                    "importance": {"value": DEFAULT_IMPORTANCE.get(a["role"], 0.3), "source": "default",
                                   "by_section": {}},
                    "clips": [{"id": cid, "asset": a["id"], "source_start": 0,
                               "length": length_at_rate(a["length_samples"], sr, pr),
                               "timeline_start": length_at_rate(start, sr, pr), "gain_db": 0.0,
                               "fade_in": 0, "fade_out": 0, "muted": False}],
                    "cleanup": {"enabled": True, "plan": "auto", "overrides": {}},
                    "chain": [], "gain_db": 0.0, "pan": {"position": 0.0, "width": 1.0},
                    "sends": [], "output": "bus_mix",
                    "restrictions": dict(RESTRICTION, operations=list(RESTRICTION["operations"])),
                }
                tracks.append(track)
                new_tracks.append(track)
                rec["track"] = tid
            # a native stem that was split further is replaced by its parts: mute its tracks
            for t in tracks:
                if t in new_tracks:
                    continue
                if any(c.get("asset") == src_id for c in t.get("clips") or []) and not t.get("muted"):
                    t["muted"] = True
                    muted.append(t["id"])
            if muted:
                warnings.append(f"tracks {muted} play the separated source and were muted")
            objective = data.get("objective") if isinstance(data.get("objective"), dict) else None
            if not any(t.get("is_lead") for t in tracks) and not (objective or {}).get("lead_stem"):
                vocal = [t for t in tracks if t.get("role") == "vocals" and not t.get("muted")]
                if len(vocal) == 1:
                    vocal[0]["is_lead"] = True
                    if objective is not None:
                        objective["lead_stem"] = vocal[0]["id"]

        record = {
            "id": sep_id,
            "model_id": model_id,
            "model_sha256": model_sha,
            "tier": entry.get("tier"),
            "status": entry.get("status"),
            "architecture": entry.get("architecture"),
            "backend": rt.get("backend"),
            "license": registry.license_record(entry),
            "attribution": entry.get("attribution") or "",
            "source_asset": src_id,
            "source_sha256": src.get("sha256"),
            "mode": mode,
            "excerpt": {"start": start, "length": length, "sample_rate": sr},
            "model_sample_rate": rate,
            "preprocess": pre,
            "postprocess": post,
            "stems": stem_records,
            "restriction": dict(RESTRICTION, operations=list(RESTRICTION["operations"])),
            "device": result.get("device"),
            "worker_elapsed_s": result.get("elapsed_s"),
            "worker_versions": result.get("versions") or {},
            "engine_version": mankomix.ENGINE_VERSION,
            "warnings": list(warnings),
        }
        ingest = data.get("ingest")
        if not isinstance(ingest, dict):
            ingest = {}
            data["ingest"] = ingest
        ingest.setdefault("separations", []).append(record)
        if new_tracks:
            try:
                from ..ingest.checks import run_checks

                ingest["checks"] = run_checks(proj)
            except Exception as exc:  # the separation itself succeeded
                warnings.append(f"import checks could not be refreshed: {exc}")
        try:
            proj.save(actor=actor, op="separate",
                      reason=f"separate '{src_id}' with '{model_id}' ({mode}): {len(new_assets)} stem(s)")
        except Exception:
            for w in written:
                w.unlink(missing_ok=True)
            raise
    finally:
        shutil.rmtree(work, ignore_errors=True)

    return {
        "separation": sep_id,
        "model_id": model_id,
        "model_sha256": model_sha,
        "mode": mode,
        "source_asset": src_id,
        "excerpt": {"start": start, "length": length, "sample_rate": sr,
                    "start_s": round(start / sr, 3), "length_s": round(length / sr, 3)},
        "stems": stem_records,
        "assets_added": [a["id"] for a in new_assets],
        "tracks_added": [t["id"] for t in new_tracks],
        "tracks_muted": muted,
        "device": result.get("device"),
        "elapsed_s": round(wall, 3),
        "worker_elapsed_s": result.get("elapsed_s"),
        "preprocess": pre,
        "postprocess": post,
        "license": registry.license_record(entry),
        "attribution": entry.get("attribution") or "",
        "restriction": RESTRICTION,
        "warnings": warnings,
    }
