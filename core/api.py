"""Core API facade (SPEC 3.1, A-1).

This module is the only entry point the faces use. The CLI calls these
functions now; the MCP server and the GUI server must call the very same
functions so that no face gains a feature the others lack (SPEC 10.1).

Rules every function here follows:

- returns a JSON-serialisable dict;
- never puts absolute paths in results or error messages (project-relative
  paths or bare file names only, SPEC 10.1 / A-11);
- raises ``MankoError`` subclasses for expected failures, so every face can
  map them to the same exit codes / error payloads.

Heavy and sibling modules are imported lazily so that ``doctor`` keeps
working even when parts of the environment are broken.
"""

from __future__ import annotations

import functools
import hashlib
import importlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .errors import EnvironmentProblem, InputError, MankoError, ValidationError

SUBPROCESS_TIMEOUT_S = 10
GPU_TIMEOUT_S = 5
STEM_SUM_ID = "stem_sum"
ANALYSIS_DIR = "analysis"

__all__ = [
    "doctor", "init_project", "import_files", "status", "validate_project", "analyze",
    "measure_audio", "compare_audio", "history", "undo", "checkout", "set_value", "patch",
    "profile_list", "profile_show", "objective_list", "objective_show",
    "route", "master_plan", "master_apply", "render", "export", "verify", "report",
    "objective_set", "objective_validate", "reference_add", "reference_list", "reference_remove",
    "plan_propose", "plan_apply", "plan_reject", "planner_run", "gate_check", "project_get",
    "knowledge_lookup", "clean_plan", "clean_apply", "clean_delta", "mix_plan", "mix_apply",
    "stem_list", "stem_add", "stem_replace", "stem_remove", "stem_move", "stem_split", "stem_mute",
    "stem_range_replace", "stem_role", "stem_edit", "stem_export", "run",
]


# ---------------------------------------------------------------------------
# Path scrubbing (no absolute paths leave the core)
# ---------------------------------------------------------------------------

_WIN_ABS = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"'<>|*?]*")


def _norm(p: str) -> str:
    s = p.replace("\\", "/").rstrip("/")
    return s.lower() if os.name == "nt" else s


def _known_roots(project_root: Path | None, extra: list[Path] | None = None) -> list[tuple[str, bool]]:
    """(normalised absolute prefix, is_project_root) longest first."""
    roots: list[tuple[str, bool]] = []
    if project_root is not None:
        roots.append((_norm(str(Path(project_root).resolve())), True))
    cands: list[Path] = list(extra or [])
    cands += [Path.cwd(), Path.home(), Path(tempfile.gettempdir())]
    for c in cands:
        try:
            roots.append((_norm(str(Path(c).resolve())), False))
        except OSError:
            continue
    seen: set[str] = set()
    out = []
    for r, is_proj in sorted(roots, key=lambda t: (-len(t[0]), not t[1])):
        if r and r not in seen and len(r) > 3:
            seen.add(r)
            out.append((r, is_proj))
    return out


def _scrub_str(s: str, roots: list[tuple[str, bool]]) -> str:
    if not s or ("/" not in s and "\\" not in s):
        return s
    for root, is_proj in roots:
        # Build a pattern for the root in either slash style, case-insensitive on Windows.
        parts = [re.escape(x) for x in root.split("/")]
        pat = r"[\\/]".join(parts) + r"(?:[\\/][^\s\"'<>|*?]*)?"
        flags = re.IGNORECASE if os.name == "nt" else 0

        def repl(m: re.Match, _root=root, _proj=is_proj) -> str:
            full = m.group(0).replace("\\", "/")
            tail = full[len(_root):].lstrip("/")
            if _proj:
                return tail or "."
            return tail.rsplit("/", 1)[-1] if tail else "."

        s = re.sub(pat, repl, s, flags=flags)
    s = _WIN_ABS.sub(lambda m: m.group(0).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1], s)
    return s


def _scrub(obj: Any, roots: list[tuple[str, bool]]) -> Any:
    if isinstance(obj, str):
        return _scrub_str(obj, roots)
    if isinstance(obj, dict):
        return {(_scrub_str(k, roots) if isinstance(k, str) else k): _scrub(v, roots) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_scrub(v, roots) for v in obj]
    return obj


def _jsonable(obj: Any) -> Any:
    """Convert numpy scalars/arrays, Paths and non-finite floats into plain JSON."""
    if obj is None or isinstance(obj, (bool, str, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return obj.name
    if hasattr(obj, "tolist"):          # numpy arrays and scalars
        return _jsonable(obj.tolist())
    if hasattr(obj, "to_dict"):
        return _jsonable(obj.to_dict())
    return str(obj)


def _face_safe(fn: Callable[..., dict]) -> Callable[..., dict]:
    """Make results JSON-safe and strip absolute paths from results and errors."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        extra: list[Path] = []
        for a in list(args) + list(kwargs.values()):
            if isinstance(a, (str, Path)) and a and len(str(a)) < 1024:
                try:
                    p = Path(a)
                    if p.exists():
                        rp = p.resolve()
                        extra.append(rp.parent if rp.is_file() else rp)
                except (OSError, ValueError):
                    pass
            elif isinstance(a, list):
                for item in a:
                    if isinstance(item, (str, Path)):
                        try:
                            rp = Path(item).resolve()
                            extra.append(rp.parent if rp.is_file() else rp)
                        except (OSError, ValueError):
                            pass
        proj = _project_root_hint(args, kwargs)
        roots = _known_roots(proj, extra)
        try:
            result = fn(*args, **kwargs)
        except MankoError as e:
            e.message = _scrub_str(str(e.message), roots)
            e.args = (e.message,)
            e.details = _scrub(_jsonable(e.details), roots)
            raise
        return _scrub(_jsonable(result), roots)

    return wrapper


def _project_root_hint(args: tuple, kwargs: dict) -> Path | None:
    cand = kwargs.get("project_path") or kwargs.get("path") or (args[0] if args else None)
    if isinstance(cand, (str, Path)) and cand:
        try:
            p = Path(cand)
            if p.name == "project.json":
                p = p.parent
            if p.is_dir() or not p.exists():
                return p.resolve()
        except (OSError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# Lazy access to sibling modules
# ---------------------------------------------------------------------------

def _mod(name: str):
    try:
        return importlib.import_module(f"{__package__}.{name}")
    except ImportError as e:
        raise EnvironmentProblem(f"core module '{name}' is not available: {e}") from None


def _open(project_path: str | Path):
    p = Path(project_path)
    if p.name == "project.json" and p.is_file():
        p = p.parent
    if not (p / "project.json").is_file():
        raise InputError(f"not a MankoMIX project (no project.json): {p.name or str(p)}",
                         details={"hint": "pass --project PATH or run inside a project folder"})
    return _mod("project").Project.open(p)


def _asset_list(data: dict) -> list[dict]:
    return [a for a in data.get("assets", []) or [] if isinstance(a, dict)]


def _asset_roles(data: dict) -> dict[str, str]:
    """Map asset id -> role (from tracks first, then the asset record, then fullmix)."""
    roles: dict[str, str] = {}
    for a in _asset_list(data):
        if a.get("role"):
            roles[a["id"]] = a["role"]
    for t in data.get("tracks", []) or []:
        for c in t.get("clips", []) or []:
            if c.get("asset") and t.get("role"):
                roles[c["asset"]] = t["role"]
    for fid in _fullmix_ids(data):
        roles[fid] = "fullmix"
    return roles


def _fullmix_ids(data: dict) -> set[str]:
    ids: set[str] = set()
    if isinstance(data.get("fullmix_asset"), str):
        ids.add(data["fullmix_asset"])
    fm = data.get("fullmix")
    if isinstance(fm, str):
        ids.add(fm)
    elif isinstance(fm, dict):
        for k in ("asset", "asset_id", "id"):
            if isinstance(fm.get(k), str):
                ids.add(fm[k])
    elif isinstance(fm, list):
        ids.update(x for x in fm if isinstance(x, str))
    for a in _asset_list(data):
        if a.get("role") == "fullmix" or a.get("origin") in ("reference_fullmix", "fullmix"):
            ids.add(a["id"])
    return ids


def _stem_ids(data: dict) -> list[str]:
    """Assets that are summed as stems (everything except the reference fullmix)."""
    fm = _fullmix_ids(data)
    track_assets: list[str] = []
    for t in data.get("tracks", []) or []:
        if t.get("role") == "fullmix":
            continue
        for c in t.get("clips", []) or []:
            aid = c.get("asset")
            if aid and aid not in fm and aid not in track_assets:
                track_assets.append(aid)
    if track_assets:
        return track_assets
    return [a["id"] for a in _asset_list(data) if a["id"] not in fm]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _project_rate(data: dict) -> int | None:
    sr = (data.get("timebase") or {}).get("sample_rate")
    if sr:
        return int(sr)
    rates = [int(a["sample_rate"]) for a in _asset_list(data) if a.get("sample_rate")]
    if not rates:
        return None
    counts = Counter(rates)
    return max(counts, key=lambda r: (counts[r], r))   # majority, ties -> higher rate


def _count_levels(items: list[dict]) -> dict[str, int]:
    c = Counter(str(i.get("level", "info")) for i in items if isinstance(i, dict))
    return dict(sorted(c.items()))


def _analyzer_version() -> str:
    vec = _mod("measure.vector")
    for name in ("ANALYZER_VERSION", "VERSION", "__version__"):
        v = getattr(vec, name, None)
        if v:
            return str(v)
    return str(_probe_analyzer_version())


@functools.lru_cache(maxsize=1)
def _probe_analyzer_version() -> str:
    import numpy as np
    vec = _mod("measure.vector")
    t = np.arange(48000) / 48000.0
    x = 0.1 * np.sin(2 * np.pi * 1000.0 * t)
    return str(vec.measure_signal(np.stack([x, x], axis=1), 48000).get("analyzer_version", "unknown"))


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

_REQUIRED_PACKAGES = ("numpy", "scipy", "soundfile", "jsonschema")
_OPTIONAL_PACKAGES = ("pyloudnorm", "librosa")
_ROUNDTRIP_ENCODERS = {
    "aac": ("aac",),
    "opus": ("libopus", "opus"),
    "mp3": ("libmp3lame",),
    "vorbis": ("libvorbis", "vorbis"),
    "flac": ("flac",),
}


def _run(cmd: list[str], timeout: float = SUBPROCESS_TIMEOUT_S) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None


def _pkg_version(name: str) -> str | None:
    from importlib import metadata
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def parse_ffmpeg_build(version_output: str) -> dict:
    """Parse ``ffmpeg -version`` output into version + license-relevant build flags.

    Only license flags are reported; the full configuration line can contain
    absolute build paths and is therefore never returned.
    """
    lines = version_output.splitlines()
    first = lines[0].strip() if lines else ""
    m = re.match(r"\S+ version (\S+)", first)
    version = m.group(1) if m else None
    config = ""
    for ln in lines:
        if ln.strip().startswith("configuration:"):
            config = ln
            break
    flags = sorted({f for f in ("--enable-gpl", "--enable-nonfree", "--enable-version3")
                    if re.search(re.escape(f) + r"(?![\w-])", config)})
    if "--enable-nonfree" in flags:
        build = "nonfree"
    elif "--enable-gpl" in flags:
        build = "gpl"
    elif config:
        build = "lgpl"
    else:
        build = "unknown"
    v3 = "--enable-version3" in flags
    license_name = {"lgpl": "LGPL-3.0-or-later" if v3 else "LGPL-2.1-or-later",
                    "gpl": "GPL-3.0-or-later" if v3 else "GPL-2.0-or-later",
                    "nonfree": "nonfree (not redistributable)",
                    "unknown": "unknown"}[build]
    return {"version": version, "build": build, "license": license_name, "license_flags": flags}


def parse_ffmpeg_encoders(encoders_output: str) -> dict:
    """Return {round-trip codec: chosen encoder or None} from ``ffmpeg -encoders``."""
    audio: dict[str, bool] = {}
    for ln in encoders_output.splitlines():
        m = re.match(r"^\s*([A-Z.]{6})\s+(\S+)\s", ln)
        if m and m.group(1)[0] == "A":
            audio[m.group(2)] = "X" in m.group(1)       # experimental flag
    result = {}
    for codec, names in _ROUNDTRIP_ENCODERS.items():
        chosen = next((n for n in names if n in audio), None)
        result[codec] = {"available": chosen is not None, "encoder": chosen,
                         "experimental": bool(chosen and audio[chosen])}
    return result


def _strict_mode(arg: bool | None) -> tuple[bool, str]:
    if arg is not None:
        return bool(arg), "argument"
    env = os.environ.get("MANKOMIX_STRICT_LGPL")
    if env is not None and env.strip() != "":
        return env.strip().lower() in ("1", "true", "yes", "on"), "environment"
    try:
        settings = _mod("config").load_settings() or {}
        val = settings.get("strict_lgpl")
        if val is None and isinstance(settings.get("ffmpeg"), dict):
            val = settings["ffmpeg"].get("strict_lgpl")
        if val is not None:
            return bool(val), "settings"
    except Exception:  # settings are optional for doctor
        pass
    return False, "default"


def _doctor_models(issue: Callable[[str, str, str], None]) -> dict:
    """Model registry state for doctor: counts per tier/status and what is available locally.

    Only file presence is checked here (no hashing); ``model verify`` re-hashes."""
    try:
        res = _mod("registry").model_list()
    except MankoError as e:
        issue("warning", "model_registry_unreadable", f"model registry could not be read: {e.message}")
        return {"status": "error", "message": e.message}
    models = [m for m in res.get("models") or [] if isinstance(m, dict)]
    official = [m for m in models if m.get("tier") == "official"]
    verified = [m for m in official if m.get("status") == "verified"]
    candidate = [m for m in official if m.get("status") != "verified"]
    byow = [m for m in models if m.get("tier") == "byow"]
    downloaded = sorted(m["id"] for m in official if m.get("state") == "installed")
    partial = sorted(m["id"] for m in official if m.get("state") == "partial")
    byow_ok = sorted(m["id"] for m in byow if m.get("state") == "registered")
    byow_missing = sorted(m["id"] for m in byow if m.get("state") != "registered")
    if byow_missing:
        issue("warning", "byow_weights_missing",
              "registered BYOW weights are not at their registered location: " + ", ".join(byow_missing))
    if not downloaded and not byow_ok:
        issue("info", "no_models_available",
              "no separation model is available locally (only needed for stem separation); "
              "see `mankomix model list` and `mankomix model pull <id>`")
    return {
        "status": "ok" if (downloaded or byow_ok) else "none_available",
        "official": len(verified),
        "candidate": len(candidate),
        "byow": len(byow),
        "downloaded": downloaded,
        "partial": partial,
        "byow_available": byow_ok,
        "byow_missing": byow_missing,
        "defaults": res.get("defaults") or {},
        "weights_location": res.get("weights_location"),
    }


@_face_safe
def doctor(strict_lgpl: bool | None = None) -> dict:
    """Inspect the environment (SPEC 10.2 doctor, 13.3)."""
    from mankomix import ENGINE_VERSION

    issues: list[dict] = []

    def issue(level: str, code: str, message: str) -> None:
        issues.append({"level": level, "code": code, "message": message})

    py = sys.version_info
    py_ok = (py.major, py.minor) >= (3, 11)
    if not py_ok:
        issue("error", "python_version", "Python 3.11 or newer is required")

    packages = {}
    for name in _REQUIRED_PACKAGES:
        v = _pkg_version(name)
        packages[name] = {"installed": v is not None, "version": v, "required": True}
        if v is None:
            issue("error", "missing_package", f"required package '{name}' is not installed")
    for name in _OPTIONAL_PACKAGES:
        v = _pkg_version(name)
        packages[name] = {"installed": v is not None, "version": v, "required": False}

    strict, strict_src = _strict_mode(strict_lgpl)

    ffmpeg: dict[str, Any] = {"found": False, "version": None, "build": None, "license": None,
                              "license_flags": [], "encoders": {}}
    exe = shutil.which("ffmpeg")
    if exe is None:
        issue("warning", "ffmpeg_missing",
              "ffmpeg not found on PATH: lossy decoding, rendering (M2+) and codec round-trip checks are "
              "unavailable. MankoMIX never bundles or downloads ffmpeg; install an LGPL build yourself.")
        if strict:
            issue("error", "strict_lgpl_no_ffmpeg", "strict LGPL mode is on but no ffmpeg build is available")
    else:
        ffmpeg["found"] = True
        out = _run([exe, "-hide_banner", "-version"]) or _run([exe, "-version"])
        if out is None or out.returncode != 0:
            issue("warning", "ffmpeg_unusable", "ffmpeg was found but '-version' failed")
        else:
            ffmpeg.update(parse_ffmpeg_build(out.stdout))
            # -hide_banner suppresses the first line on some builds; retry for the version.
            if ffmpeg["version"] is None:
                out2 = _run([exe, "-version"])
                if out2 is not None:
                    ffmpeg.update(parse_ffmpeg_build(out2.stdout))
        enc = _run([exe, "-hide_banner", "-encoders"])
        if enc is not None and enc.returncode == 0:
            ffmpeg["encoders"] = parse_ffmpeg_encoders(enc.stdout)
            missing = [c for c, e in ffmpeg["encoders"].items() if not e["available"]]
            if missing:
                issue("info", "roundtrip_encoders_missing",
                      "codec round-trip checks for " + ", ".join(missing) + " will be recorded as 'not run'")
        build = ffmpeg.get("build")
        if build == "gpl":
            issue("warning", "ffmpeg_gpl_build",
                  "ffmpeg is a GPL build. MankoMIX still runs it (external process only, LGPL features only); "
                  "the build configuration is recorded in render manifests and the Mix Report. "
                  "An LGPL build is recommended.")
        elif build == "nonfree":
            issue("warning", "ffmpeg_nonfree_build",
                  "STRONG WARNING: ffmpeg is a nonfree build, which is not redistributable. MankoMIX only "
                  "calls it as an external process and never distributes it; outputs record this build. "
                  "Use an LGPL build for anything you share.")
        elif build == "unknown":
            issue("warning", "ffmpeg_build_unknown", "could not determine the ffmpeg build configuration")
        if strict and build != "lgpl":
            issue("error", "strict_lgpl_violation",
                  f"strict LGPL mode is on and the ffmpeg build is '{build}', not LGPL")

    ffprobe_exe = shutil.which("ffprobe")
    ffprobe: dict[str, Any] = {"found": ffprobe_exe is not None, "version": None}
    if ffprobe_exe:
        out = _run([ffprobe_exe, "-version"])
        if out is not None and out.returncode == 0:
            ffprobe["version"] = parse_ffmpeg_build(out.stdout)["version"]

    gpu: dict[str, Any] = {"status": "none", "devices": []}
    smi = shutil.which("nvidia-smi")
    if smi:
        out = _run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader"], timeout=GPU_TIMEOUT_S)
        if out is not None and out.returncode == 0:
            for ln in out.stdout.splitlines():
                if ln.strip():
                    name, _, mem = ln.partition(",")
                    gpu["devices"].append({"name": name.strip(), "memory_total": mem.strip() or None})
            if gpu["devices"]:
                gpu["status"] = "nvidia"
    if gpu["status"] == "none":
        issue("info", "no_gpu", "no NVIDIA GPU detected; stem separation will use CPU models")

    models = _doctor_models(issue)

    levels = {i["level"] for i in issues}
    overall = "error" if "error" in levels else "warning" if "warning" in levels else "ok"
    return {
        "status": overall,
        "engine_version": ENGINE_VERSION,
        "python": {"version": f"{py.major}.{py.minor}.{py.micro}", "ok": py_ok},
        "packages": packages,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "strict_lgpl": {"enabled": strict, "source": strict_src},
        "gpu": gpu,
        "models": models,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Project lifecycle
# ---------------------------------------------------------------------------

@_face_safe
def init_project(path: str | Path, *, title: str, genre: str | None = None, project_id: str | None = None,
                 actor: str = "human") -> dict:
    """Create a project. ``project_id`` fixes the id (``prj_`` is prefixed when missing).

    The creation entry of the journal is written by ``Project.create`` (recorded as
    the engine); ``actor`` is used when the project has to be saved here.
    """
    p = Path(path)
    if (p / "project.json").exists():
        raise InputError(f"a project already exists here: {p.name}")
    if p.exists() and not p.is_dir():
        raise InputError(f"not a folder: {p.name}")
    if not title or not str(title).strip():
        raise InputError("title must not be empty")
    if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
        raise InputError("project_id must be a non-empty string")
    _mod("journal").check_actor(actor)
    proj = _mod("project").Project.create(p, title=title, genre=genre, project_id=project_id)
    if not (Path(proj.root) / "project.json").is_file():
        proj.save(actor=actor, op="init", reason="create project")
    data = proj.data
    return {"created": True, "project": Path(proj.root).name, "id": data.get("id"), "title": data.get("title"),
            "genre": data.get("genre"), "schema_version": data.get("schema_version")}


@_face_safe
def import_files(project_path: str | Path, sources: list[str], *, mode: str = "copy",
                 provenance: dict | None = None, actor: str = "human") -> dict:
    if mode not in ("copy", "link"):
        raise InputError(f"unknown import mode '{mode}' (use copy or link)")
    if not sources:
        raise InputError("no sources given")
    for s in sources:
        if not Path(s).exists():
            raise InputError(f"source not found: {Path(s).name}")
    if provenance is not None and not isinstance(provenance, dict):
        raise InputError("provenance must be a JSON object")
    proj = _open(project_path)
    adapter = _mod("adapters.file").FileAdapter()
    records = []
    checks = None
    # Several loose files are one set (e.g. a Suno export given file by file: numbered stems and
    # "0 <title>" as the full mix); a single file is a 2-mix; folders are read one by one.
    groups: list[Any] = ([[str(x) for x in sources]] if len(sources) > 1 and all(Path(x).is_file() for x in sources)
                         else list(sources))
    for s in groups:
        rec = adapter.fetch(s, proj, mode=mode, provenance=provenance, actor=actor)
        if isinstance(rec, dict) and isinstance(rec.get("checks"), list):
            # The adapter checks the whole project after each fetch; the last result is current.
            checks = rec.pop("checks")
        records.append(rec)
    if checks is None:
        checks = _mod("ingest.checks").run_checks(proj) or []
    ingest = proj.data.get("ingest")
    if not isinstance(ingest, dict):
        ingest = {}
        proj.data["ingest"] = ingest
    ingest["checks"] = checks
    # No-op (no journal entry) when the adapter already stored the same checks.
    proj.save(actor=actor, op="import", reason=f"import {len(sources)} source(s) via file adapter ({mode})")
    return {
        "imported": records,
        "assets": len(_asset_list(proj.data)),
        "check_counts": _count_levels(checks),
        "checks": checks,
    }


@_face_safe
def status(project_path: str | Path) -> dict:
    proj = _open(project_path)
    data = proj.data
    roles = _asset_roles(data)
    fm = sorted(_fullmix_ids(data))
    index = data.get("analysis_index") or {}
    try:
        aver = _analyzer_version()
    except MankoError:
        aver = None

    def cache_state(key: str, sha: str | None) -> str:
        rec = index.get(key)
        if not isinstance(rec, dict):
            return "missing"
        if not (Path(proj.root) / rec.get("path", f"{ANALYSIS_DIR}/{key}.json")).is_file():
            return "missing"
        if sha is not None and rec.get("sha256") != sha:
            return "stale"
        if aver is not None and rec.get("analyzer_version") != aver:
            return "stale"
        return "fresh"

    assets = []
    for a in _asset_list(data):
        assets.append({
            "id": a.get("id"), "path": a.get("path"), "role": roles.get(a.get("id")),
            "sample_rate": a.get("sample_rate"), "channels": a.get("channels"),
            "length_samples": a.get("length_samples"), "origin": a.get("origin"),
            "analysis": cache_state(a.get("id"), a.get("sha256")),
        })
    tracks = [{"id": t.get("id"), "role": t.get("role"), "is_lead": t.get("is_lead", False),
               "assets": [c.get("asset") for c in t.get("clips", []) or []]}
              for t in data.get("tracks", []) or []]
    checks = (data.get("ingest") or {}).get("checks") or []
    states = Counter(a["analysis"] for a in assets)
    if STEM_SUM_ID in index:
        states[f"{STEM_SUM_ID}:{cache_state(STEM_SUM_ID, None)}"] += 1
    try:
        entries = _mod("journal").list_entries(proj.root, limit=5) or []
    except MankoError:
        entries = []
    return {
        "project": Path(proj.root).name,
        "id": data.get("id"),
        "title": data.get("title"),
        "genre": data.get("genre"),
        "timebase": data.get("timebase"),
        "provenance": data.get("provenance"),
        "assets": assets,
        "tracks": tracks,
        "fullmix": fm[0] if len(fm) == 1 else (fm or None),
        "check_counts": _count_levels(checks),
        "analysis": {"analyzer_version": aver, "states": dict(sorted(states.items()))},
        "last_journal": [_entry_summary(e) for e in list(entries)[-5:] if isinstance(e, dict)],
    }


@_face_safe
def validate_project(project_path: str | Path) -> dict:
    proj = _open(project_path)
    issues = proj.validate() or []
    counts = _count_levels(issues)
    if counts.get("error"):
        raise ValidationError(f"project has {counts['error']} validation error(s)",
                              details={"issues": issues, "counts": counts})
    return {"valid": True, "counts": counts, "issues": issues}


# ---------------------------------------------------------------------------
# Analysis and measurement
# ---------------------------------------------------------------------------

def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def _cached(root: Path, index: dict, key: str, sha: str, aver: str) -> bool:
    rec = index.get(key)
    if not isinstance(rec, dict):
        return False
    if rec.get("sha256") != sha or rec.get("analyzer_version") != aver:
        return False
    f = root / rec.get("path", f"{ANALYSIS_DIR}/{key}.json")
    if not f.is_file():
        return False
    try:
        stored = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return stored.get("sha256") == sha and stored.get("analyzer_version") == aver


def _stem_sum_signal(proj, stem_ids: list[str], rate: int):
    """Static unprocessed sum: gain 0 dB, head-aligned, at the project rate."""
    import numpy as np
    from scipy.signal import resample_poly

    audio_io = _mod("audio_io")
    signals = []
    for aid in stem_ids:
        x, sr = audio_io.read(proj.asset_path(aid))
        if sr != rate:
            g = math.gcd(int(rate), int(sr))
            x = resample_poly(x, rate // g, sr // g, axis=0)
        signals.append(x)
    n = max(s.shape[0] for s in signals)
    ch = max(s.shape[1] for s in signals)
    out = np.zeros((n, ch), dtype=np.float64)
    for s in signals:
        if s.shape[1] == ch:
            out[: s.shape[0]] += s
        elif s.shape[1] == 1:
            out[: s.shape[0]] += s[:, :1]          # mono broadcast to every channel
        else:
            out[: s.shape[0], : s.shape[1]] += s[:, :ch]
    return out


@_face_safe
def analyze(project_path: str | Path, *, force: bool = False, actor: str = "human") -> dict:
    """Measure every asset and the static stem sum; cache by sha256 + analyzer version (SPEC 6.3)."""
    proj = _open(project_path)
    root = Path(proj.root)
    vec = _mod("measure.vector")
    aver = _analyzer_version()
    data = proj.data
    old_index = data.get("analysis_index") if isinstance(data.get("analysis_index"), dict) else {}
    index = dict(old_index)
    results = []
    warnings = []
    current: dict[str, str] = {}

    for a in _asset_list(data):
        aid = a["id"]
        src = Path(proj.asset_path(aid))
        if not src.is_file():
            raise InputError(f"asset file missing for {aid}: {src.name}")
        sha = _sha256_file(src)
        current[aid] = sha
        if a.get("sha256") and a["sha256"] != sha:
            warnings.append({"level": "warning", "asset": aid,
                             "message": "asset content differs from the recorded sha256"})
        rel = f"{ANALYSIS_DIR}/{aid}.json"
        if not force and _cached(root, index, aid, sha, aver):
            results.append({"asset": aid, "cached": True, "path": rel})
            continue
        vector = _jsonable(vec.measure_file(src))
        av = str(vector.get("analyzer_version", aver)) if isinstance(vector, dict) else aver
        _write_json(root / rel, {"asset": aid, "sha256": sha, "analyzer_version": av, "vector": vector})
        index[aid] = {"path": rel, "sha256": sha, "analyzer_version": av}
        results.append({"asset": aid, "cached": False, "path": rel})

    stems = [s for s in _stem_ids(data) if s in current]
    stem_sum = None
    if stems:
        rate = _project_rate(data) or 48000
        key_src = json.dumps({"rate": rate, "stems": [[s, current[s]] for s in sorted(stems)]}, sort_keys=True)
        sha = hashlib.sha256(key_src.encode("utf-8")).hexdigest()
        rel = f"{ANALYSIS_DIR}/{STEM_SUM_ID}.json"
        if not force and _cached(root, index, STEM_SUM_ID, sha, aver):
            stem_sum = {"asset": STEM_SUM_ID, "cached": True, "path": rel, "stems": len(stems)}
        else:
            x = _stem_sum_signal(proj, stems, rate)
            vector = _jsonable(vec.measure_signal(x, rate))
            av = str(vector.get("analyzer_version", aver)) if isinstance(vector, dict) else aver
            _write_json(root / rel, {"asset": STEM_SUM_ID, "sha256": sha, "analyzer_version": av,
                                     "inputs": sorted(stems), "sample_rate": rate, "vector": vector})
            index[STEM_SUM_ID] = {"path": rel, "sha256": sha, "analyzer_version": av, "inputs": sorted(stems)}
            stem_sum = {"asset": STEM_SUM_ID, "cached": False, "path": rel, "stems": len(stems)}

    # Drop index entries for assets that no longer exist.
    for k in list(index):
        if k != STEM_SUM_ID and k not in current:
            index.pop(k)
    if not stems:
        index.pop(STEM_SUM_ID, None)

    saved = False
    if index != old_index:
        data["analysis_index"] = index
        proj.save(actor=actor, op="analyze", reason=f"analysis (analyzer {aver})")
        saved = True
    measured = sum(1 for r in results if not r["cached"]) + (1 if stem_sum and not stem_sum["cached"] else 0)
    return {
        "analyzer_version": aver,
        "assets": results,
        "stem_sum": stem_sum,
        "measured": measured,
        "cached": len(results) + (1 if stem_sum else 0) - measured,
        "saved": saved,
        "warnings": warnings,
    }


def _check_audio_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_file():
        raise InputError(f"audio file not found: {p.name or str(path)}")
    return p


@_face_safe
def measure_audio(path: str | Path) -> dict:
    p = _check_audio_path(path)
    audio_io = _mod("audio_io")
    inf = audio_io.info(p).to_dict()
    vector = _mod("measure.vector").measure_file(p)
    return {"file": p.name, "info": inf, "vector": vector}


@_face_safe
def compare_audio(path_a: str | Path, path_b: str | Path) -> dict:
    a = _check_audio_path(path_a)
    b = _check_audio_path(path_b)
    audio_io = _mod("audio_io")
    xa, sra = audio_io.read(a)
    xb, srb = audio_io.read(b)
    out: dict[str, Any] = {"a": a.name, "b": b.name}
    if sra != srb:
        # In-memory only (files are never modified): bring b to a's rate for the comparison.
        from scipy.signal import resample_poly
        g = math.gcd(int(sra), int(srb))
        xb = resample_poly(xb, sra // g, srb // g, axis=0)
        out["resampled"] = {"file": "b", "from_hz": int(srb), "to_hz": int(sra)}
        srb = sra
    out["comparison"] = _mod("measure.compare").compare(xa, sra, xb, srb)
    return out


# ---------------------------------------------------------------------------
# History and editing
# ---------------------------------------------------------------------------

_ENTRY_SUMMARY_KEYS = ("seq", "ts", "actor", "op", "reason", "undoes", "target_seq", "after_hash")


def _entry_summary(e: dict) -> dict:
    out = {k: e[k] for k in _ENTRY_SUMMARY_KEYS if k in e}
    if isinstance(e.get("patch"), list):
        out["patch_ops"] = len(e["patch"])
    return out


@_face_safe
def history(project_path: str | Path, limit: int | None = 20, *, detail: bool = False) -> dict:
    """Journal entries, oldest first (the most recent ``limit``). ``detail`` adds the patches."""
    proj = _open(project_path)
    if limit is not None and int(limit) < 1:
        raise InputError("limit must be >= 1")
    entries = list(_mod("journal").list_entries(proj.root, limit=limit) or [])
    if not detail:
        entries = [_entry_summary(e) for e in entries if isinstance(e, dict)]
    return {"entries": entries, "count": len(entries)}


def _project_summary(proj) -> dict:
    try:
        h = proj.content_hash()
    except Exception:
        h = None
    return {"content_hash": h}


@_face_safe
def undo(project_path: str | Path, actor: str = "human") -> dict:
    proj = _open(project_path)
    res = _mod("journal").undo(proj, actor)
    return {"undone": _entry_summary(res) if isinstance(res, dict) else res,
            **_project_summary(_open(project_path))}


@_face_safe
def checkout(project_path: str | Path, seq: int, actor: str = "human") -> dict:
    proj = _open(project_path)
    try:
        seq = int(seq)
    except (TypeError, ValueError):
        raise InputError(f"journal sequence must be an integer: {seq!r}") from None
    res = _mod("journal").checkout(proj, seq, actor)
    return {"checked_out": seq, "entry": _entry_summary(res) if isinstance(res, dict) else res,
            **_project_summary(_open(project_path))}


def _parse_json_value(text: Any, what: str) -> Any:
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except ValueError as e:
        raise InputError(f"{what} is not valid JSON: {e.msg}",
                         details={"hint": "strings must be quoted, e.g. '\"text\"'"}) from None


@_face_safe
def set_value(project_path: str | Path, pointer: str, value_json: Any, actor: str = "human",
              reason: str | None = None) -> dict:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise InputError(f"not a JSON pointer: {pointer!r} (must start with '/')")
    value = _parse_json_value(value_json, "value")
    proj = _open(project_path)
    res = proj.set(pointer, value, actor=actor, reason=reason or f"set {pointer}")
    out = {"set": pointer, "value": value, **_project_summary(proj)}
    if isinstance(res, dict):
        out["result"] = res
    return out


@_face_safe
def patch(project_path: str | Path, ops: Any, actor: str = "human", reason: str | None = None) -> dict:
    ops = _parse_json_value(ops, "patch")
    if isinstance(ops, dict) and "op" in ops:
        ops = [ops]
    if not isinstance(ops, list) or not all(isinstance(o, dict) for o in ops):
        raise InputError("patch must be a JSON array of RFC 6902 operations")
    proj = _open(project_path)
    res = proj.apply_patch(ops, actor=actor, reason=reason or f"patch ({len(ops)} op(s))")
    out = {"applied": len(ops), **_project_summary(proj)}
    if isinstance(res, dict):
        out["result"] = res
    return out


# ---------------------------------------------------------------------------
# Profiles and objectives (data, SPEC 4.8 / 5)
# ---------------------------------------------------------------------------

def _items(obj: Any, key: str) -> list[dict]:
    if isinstance(obj, dict):
        if isinstance(obj.get(key), list):
            return [x for x in obj[key] if isinstance(x, dict)]
        if all(isinstance(v, dict) for v in obj.values()):
            return [{"id": k, **v} if "id" not in v else v for k, v in obj.items()]
        return []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    return []


def _label(item: dict) -> Any:
    lab = item.get("label")
    if isinstance(lab, dict):
        return lab.get("en") or lab.get("ja") or next(iter(lab.values()), None)
    return lab


@_face_safe
def profile_list(full: bool = False) -> dict:
    """Media profiles and delivery formats (ids and labels; ``full`` returns the complete definitions)."""
    cfg = _mod("config")
    raw_profiles = _items(cfg.load_profiles(), "profiles")
    try:
        raw_deliveries = _items(cfg.load_deliveries(), "formats")
    except MankoError:
        raw_deliveries = []
    if full:
        return {"profiles": raw_profiles, "deliveries": raw_deliveries}
    profiles = [{"id": p.get("id"), "label": _label(p)} for p in raw_profiles]
    deliveries = [{"id": d.get("id"), "use": d.get("use")} for d in raw_deliveries]
    return {"profiles": profiles, "deliveries": deliveries}


@_face_safe
def delivery_list() -> dict:
    """Delivery formats (container, rate, bit depth, dither), SPEC 5.3."""
    return {"formats": _items(_mod("config").load_deliveries(), "formats")}


def _lookup(getter, ident: str, kind: str):
    try:
        item = getter(ident)
    except MankoError:
        raise
    except (KeyError, LookupError, ValueError):
        item = None
    if not item:
        raise InputError(f"unknown {kind}: {ident}")
    return item


@_face_safe
def profile_show(id: str) -> dict:
    cfg = _mod("config")
    try:
        prof = _lookup(cfg.get_profile, id, "profile")
        return {"kind": "profile", "profile": prof}
    except InputError:
        # Delivery formats share the profile namespace on the CLI (`profile show distributor_44k16`).
        for d in _items(cfg.load_deliveries(), "formats"):
            if d.get("id") == id:
                return {"kind": "delivery", "delivery": d}
        raise


@_face_safe
def objective_list(full: bool = False) -> dict:
    """Objective catalogue (ids and labels; ``full`` returns the complete definitions)."""
    cfg = _mod("config")
    raw = cfg.load_objectives()
    items = _items(raw, "objectives")
    default = raw.get("default") if isinstance(raw, dict) else None
    if full:
        return {"default": default, "note": raw.get("note") if isinstance(raw, dict) else None,
                "objectives": items}
    return {"default": default,
            "objectives": [{"id": o.get("id"), "spec_id": o.get("spec_id"), "kind": o.get("kind"),
                            "label": _label(o)} for o in items]}


@_face_safe
def objective_show(id: str) -> dict:
    cfg = _mod("config")
    return {"objective": _lookup(cfg.get_objective, id, "objective")}


# ---------------------------------------------------------------------------
# Mastering path (M2): route, master plan/apply, render/export, verify, report
# ---------------------------------------------------------------------------

PROPOSAL_DIR = "cache/proposals"


def _variant_or_default(proj, variant: str | None) -> str:
    variants = [v.get("id") for v in proj.data.get("variants", []) or [] if isinstance(v, dict)]
    if variant:
        if variant not in variants:
            raise InputError(f"unknown variant '{variant}'", details={"valid": variants})
        return variant
    if len(variants) == 1:
        return variants[0]
    raise InputError("specify a variant", details={"valid": variants})


def _parse_outputs(outputs: Any) -> list[dict] | None:
    """None, ["profile:delivery", ...] or [{"profile", "delivery"}, ...]."""
    if outputs is None:
        return None
    if isinstance(outputs, (str, dict)):
        outputs = [outputs]
    out = []
    for o in outputs:
        if isinstance(o, dict):
            if not o.get("profile") or not o.get("delivery"):
                raise InputError("an output needs 'profile' and 'delivery'")
            out.append({"profile": o["profile"], "delivery": o["delivery"]})
        elif isinstance(o, str) and ":" in o:
            prof, dl = o.split(":", 1)
            out.append({"profile": prof.strip(), "delivery": dl.strip()})
        else:
            raise InputError(f"output '{o}' must look like 'profile:delivery'")
    return out


@_face_safe
def route(project_path: str | Path) -> dict:
    """Mastering route selection (R-21)."""
    proj = _open(project_path)
    return _mod("routes").select_route(proj)


@_face_safe
def master_plan(project_path: str | Path, *, profile: str, delivery: str | None = None,
                objective: Any = None, variant: str | None = None, target_lufs: float | None = None,
                apply: bool = False, actor: str = "human") -> dict:
    """Propose a master chain (R-31). The proposal is saved under cache/proposals/;
    with ``apply=True`` it is also written into the variant."""
    proj = _open(project_path)
    mastering = _mod("mastering")
    obj = _parse_json_value(objective, "objective") if isinstance(objective, str) and objective.strip()[:1] in "{[" else objective
    proposal = mastering.plan_master(proj, variant_id=variant, profile_id=profile, delivery_id=delivery,
                                     objective=obj, target_lufs=target_lufs)
    path = Path(proj.root) / PROPOSAL_DIR / f"{proposal['proposal_id']}.json"
    _write_json(path, proposal)
    result = {"proposal": proposal, "proposal_path": proj.rel(path), "applied": False}
    if apply:
        mastering.apply_master_plan(proj, proposal, actor=actor)
        # Same record as plan_apply / planner_run / mix_plan / clean_plan with apply=True: the saved
        # proposal says it was applied (and plan_reject refuses it).
        _mark_proposal(path, proposal, status="applied",
                       applied={"actor": actor, "at": _now_iso(), "journal_seq": _journal_seq(proj)})
        result["applied"] = True
        result["project"] = _project_summary(proj)
    return result


def _load_proposal(proj, proposal_or_path: Any) -> dict:
    if isinstance(proposal_or_path, dict):
        return proposal_or_path
    if not isinstance(proposal_or_path, (str, Path)) or not str(proposal_or_path).strip():
        raise InputError("proposal must be a dict, a JSON text, a proposal id or a file path")
    text = str(proposal_or_path).strip()
    if text.startswith("{"):
        return _parse_json_value(text, "proposal")
    candidates = [Path(text), Path(proj.root) / text, Path(proj.root) / PROPOSAL_DIR / f"{text}.json"]
    for c in candidates:
        if c.is_file():
            try:
                with open(c, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, ValueError) as e:
                raise InputError(f"cannot read proposal {c.name}: {e}") from None
    raise InputError(f"proposal not found: {Path(text).name}",
                     details={"hint": f"pass a proposal id, a JSON file, or {PROPOSAL_DIR}/<id>.json"})


@_face_safe
def master_apply(project_path: str | Path, proposal_or_path: Any, actor: str = "human") -> dict:
    """Apply a master proposal (dict, JSON text, proposal id or file) to its variant."""
    proj = _open(project_path)
    proposal = _load_proposal(proj, proposal_or_path)
    _mod("mastering").apply_master_plan(proj, proposal, actor=actor)
    return {"applied": True, "variant": proposal.get("variant"), "proposal_id": proposal.get("proposal_id"),
            "send_back": proposal.get("send_back"), "project": _project_summary(proj)}


@_face_safe
def render(project_path: str | Path, variant: str | None = None, outputs: Any = None) -> dict:
    """Render a variant's outputs (all, or the given 'profile:delivery' subset) with manifests."""
    proj = _open(project_path)
    vid = _variant_or_default(proj, variant)
    return _mod("render").render_variant(proj, vid, outputs=_parse_outputs(outputs))


@_face_safe
def export(project_path: str | Path, variant: str | None = None) -> dict:
    """Final export: every output of the variant plus the archive master."""
    proj = _open(project_path)
    vid = _variant_or_default(proj, variant)
    return _mod("render").render_variant(proj, vid, outputs=None)


AGAINST_CHECKS = ("P-03", "S-01", "S-02")


def _verify_against(proj, vid: str, profiles: list[str]) -> dict:
    """SPEC 15.2 verification-only profiles: the variant's existing rendered outputs judged against
    other profiles' hard delivery checks (P-03 loudness window, S-01 effective ceiling incl. the
    conditional one, S-02 codec round trip). Nothing is rendered and project.json is not changed;
    the result is written to reports/verify_<variant>__against.json."""
    cfg, mastering, render_mod = _mod("config"), _mod("mastering"), _mod("render")
    ld, audio_io = _mod("measure.loudness"), _mod("audio_io")
    v = mastering.find_variant(proj.data, vid) or {}
    th = mastering.thresholds()
    files = []
    for o in v.get("outputs") or []:
        prof, dl = cfg.get_profile(o["profile"]), cfg.get_delivery(o["delivery"])
        path = render_mod.variant_dir(proj, vid) / render_mod.output_name(prof["id"], dl)
        if path.is_file():
            files.append((o, path))
    if not files:
        raise InputError(f"variant '{vid}' has no rendered output; run render first")
    measured = []
    for o, path in files:
        y, sr = audio_io.read(path)
        measured.append((o, path, y, sr, float(ld.integrated(y, sr)), float(ld.true_peak_dbtp(y, sr))))
    rank = {"fail": 3, "not_run": 2, "pass": 0, "not_applicable": 0}
    out: dict[str, Any] = {}
    for pid in profiles:
        prof = cfg.get_profile(pid)
        per = []
        for o, path, y, sr, lufs, tp in measured:
            checks: dict = {}
            window = mastering.loudness_window(prof)
            if window is None:
                checks["P-03"] = {"status": "not_applicable", "measured": {"lufs_i": round(lufs, 2)},
                                  "reason": "profile has no loudness window"}
            else:
                ok = window[0] - 1e-6 <= lufs <= window[1] + 1e-6
                checks["P-03"] = {"status": "pass" if ok else "fail", "measured": {"lufs_i": round(lufs, 2)},
                                  "window_lufs_i": window}
            ceiling = mastering.effective_ceiling(prof, lufs, None)
            checks["S-01"] = {"status": "pass" if tp <= ceiling + 1e-9 else "fail",
                              "measured": {"true_peak_dbtp": round(tp, 3)}, "ceiling_dbtp": ceiling,
                              "conditional_applied": ceiling < float((prof.get("true_peak") or {})
                                                                     .get("ceiling_dbtp", -1.0))}
            codecs = list(prof.get("codec_checks") or [])
            if not codecs:
                checks["S-02"] = {"status": "not_applicable", "reason": "profile declares no codec checks"}
            else:
                cc = mastering.codec_after_ceiling(prof, th)
                res = render_mod.codec_true_peaks(y, sr, codecs, cc, th)
                sts = [r["status"] for r in res.values()]
                checks["S-02"] = {"status": "fail" if "fail" in sts else "not_run" if "not_run" in sts else "pass",
                                  "codec_after_ceiling_dbtp": cc, "codecs": res}
            worst = max((c["status"] for c in checks.values()), key=lambda st: rank.get(st, 0))
            overall = "fail" if worst == "fail" else "incomplete" if worst == "not_run" else "pass"
            per.append({"file": proj.rel(path), "rendered_for": {"profile": o["profile"], "delivery": o["delivery"]},
                        "overall": overall, "failed": sorted(k for k, c in checks.items() if c["status"] == "fail"),
                        "checks": checks})
        overall = ("fail" if any(x["overall"] == "fail" for x in per)
                   else "incomplete" if any(x["overall"] == "incomplete" for x in per) else "pass")
        out[prof["id"]] = {"overall": overall, "failed": sorted({k for x in per for k in x["failed"]}),
                           "outputs": per}
    rep_ = {"schema_version": 1, "kind": "verify_against_report", "variant": vid,
            "project_hash": proj.content_hash(), "checks": list(AGAINST_CHECKS),
            "definition": "rendered outputs of the variant judged against other profiles (SPEC 15.2); "
                          "no re-render, project unchanged",
            "profiles": out, "passed": all(p["overall"] == "pass" for p in out.values())}
    path = Path(proj.root) / "reports" / f"verify_{vid}__against.json"
    _write_json(path, _jsonable(rep_))
    rep_["path"] = proj.rel(path)
    rep_["exit_code"] = 0 if rep_["passed"] else 1
    return rep_


@_face_safe
def verify(project_path: str | Path, variant: str | None = None, recheck_codecs: bool = False,
           *, profiles: list[str] | str | None = None, strict: bool = False) -> dict:
    """Verify a rendered variant. The result carries ``passed`` and ``exit_code``
    (0 pass, 1 fail/incomplete); with ``strict=True`` a non-pass raises VerifyFailed.
    ``profiles``: verification-only profiles (SPEC 15.2) instead: the existing rendered master is
    judged against those profiles' P-03 / S-01 / S-02 without re-rendering or changing the project."""
    proj = _open(project_path)
    vid = _variant_or_default(proj, variant)
    if profiles:
        res = _verify_against(proj, vid, _list_arg(profiles, "profiles"))
        if strict and not res["passed"]:
            from .errors import VerifyFailed
            raise VerifyFailed(f"verification against profiles failed for variant '{vid}'",
                               details={"path": res.get("path")})
        return res
    res = _mod("verify").verify_variant(proj, vid, recheck_codecs=recheck_codecs)
    res["exit_code"] = 0 if res.get("passed") else 1
    if strict and not res.get("passed"):
        from .errors import VerifyFailed
        raise VerifyFailed(f"verification {res.get('overall')} for variant '{vid}'",
                           details={"overall": res.get("overall"), "path": res.get("path")})
    return res


@_face_safe
def report(project_path: str | Path, variant: str | None = None, lang: str = "both", write: bool = True) -> dict:
    """Mix Report. ``write`` saves reports/report_<variant>.json (+ .ja.md / .en.md)."""
    proj = _open(project_path)
    vid = _variant_or_default(proj, variant)
    rep_mod = _mod("report")
    result: dict = {"variant": vid}
    if lang not in ("ja", "en", "both"):
        raise InputError(f"unsupported report language '{lang}'", details={"valid": ["ja", "en", "both"]})
    if write:
        result["paths"] = rep_mod.write_report(proj, vid)
        with open(Path(proj.root) / result["paths"]["json"], encoding="utf-8") as fh:
            result["report"] = rep_mod.resolve_language(json.load(fh), lang)
    else:
        result["report"] = rep_mod.build_report(proj, vid, lang=lang)
    if lang in ("ja", "en"):
        result["markdown"] = rep_mod.render_markdown(result["report"], lang)
    return result


# ---------------------------------------------------------------------------
# Objectives, references, stage plans, gate, knowledge (M3: SPEC 4.6, 4.7, 4.8,
# 7.2, 7.3, 10.2, 10.3, R-31)
# ---------------------------------------------------------------------------

_OBJECTIVE_CLI_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*(\s*:\s*[0-9.]+)?(\s*\+\s*[A-Za-z_][A-Za-z0-9_]*(\s*:\s*[0-9.]+)?)*\s*$")
_PROPOSAL_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _objective_arg(spec: Any) -> Any:
    """Objective spec from a dict, JSON text or the CLI form ('comfort:0.6+bass_heavy:0.4')."""
    if spec is None or isinstance(spec, dict):
        return spec
    if isinstance(spec, str):
        s = spec.strip()
        if not s:
            raise InputError("objective must not be empty")
        if s[:1] in "{[":
            return _parse_json_value(s, "objective")
        if not _OBJECTIVE_CLI_RE.match(s):
            raise InputError(f"objective '{s}' must look like 'id', 'id:intensity' or 'id:w+id:w'")
        return s
    raise InputError("objective must be an object, JSON text or 'id[:weight][+id:weight...]'")


@_face_safe
def objective_set(project_path: str | Path, spec: Any, *, variant: str | None = None,
                  actor: str = "human") -> dict:
    """Set the project objective (or a variant's override): blend, intensity, overrides, lead (SPEC 4.7).

    ``spec``: {"blend": [...], "intensity", "overrides", "lead_stem"}, JSON text, or the
    CLI form 'comfort:0.6+bass_heavy:0.4' / 'bass_heavy:0.7'. Constraints are never relaxed.
    """
    if spec is None:
        raise InputError("an objective is required, e.g. 'comfort' or 'comfort:0.6+bass_heavy:0.4'")
    proj = _open(project_path)
    return _mod("objectives").set_objective(proj, _objective_arg(spec), variant_id=variant, actor=actor)


def _definition_arg(path_or_json: Any) -> tuple[Any, str]:
    """-> (object to validate, source label). Files must be .json; other strings are specs."""
    if isinstance(path_or_json, (dict, list)):
        return path_or_json, "inline"
    if isinstance(path_or_json, Path):
        path_or_json = str(path_or_json)
    if not isinstance(path_or_json, str) or not path_or_json.strip():
        raise InputError("pass an objective definition: a .json file, inline JSON or an objective spec")
    s = path_or_json.strip()
    if s[:1] in "{[":
        return _parse_json_value(s, "objective definition"), "inline"
    if s.lower().endswith(".json"):
        p = Path(s)
        if not p.is_file():
            raise InputError(f"objective definition file not found: {p.name}")
        try:
            return json.loads(p.read_text(encoding="utf-8")), p.name
        except (OSError, ValueError) as e:
            raise InputError(f"cannot read {p.name} as JSON: {e}") from None
    if _OBJECTIVE_CLI_RE.match(s):
        return s, "inline"
    raise InputError(f"not a .json file, JSON text or objective spec: {Path(s).name}")


@_face_safe
def objective_validate(path_or_json: Any) -> dict:
    """Validate an objective definition (SPEC 4.8) or an objective spec (4.7).

    Accepts a definition / catalog ({"objectives": [...]}) as a .json file or inline
    JSON, or a spec ({"blend": ...} or 'comfort:0.6+bass_heavy:0.4'). Checks unknown
    metric ids, unknown variants, weight sums, declared params and any attempt to
    relax a safety invariant. Raises ValidationError when there are errors.
    """
    O = _mod("objectives")
    obj, source = _definition_arg(path_or_json)
    if isinstance(obj, str) or (isinstance(obj, dict) and "blend" in obj and "terms" not in obj
                                and "objectives" not in obj):
        kind = "spec"
        spec = O.normalize_spec(obj)
        issues = O.validate_objective_spec(spec)
        ids = [b.get("id") for b in spec.get("blend") or [] if isinstance(b, dict)]
    else:
        kind = "catalog" if isinstance(obj, dict) and isinstance(obj.get("objectives"), list) else "definition"
        issues = O.validate_objective_definition(obj)
        if kind == "catalog":
            ids = [o.get("id") for o in obj["objectives"] if isinstance(o, dict)]
        else:
            ids = [obj.get("id")] if isinstance(obj, dict) else []
    counts = _count_levels(issues)
    out = {"valid": not counts.get("error"), "kind": kind, "source": source, "ids": ids,
           "counts": counts, "issues": issues}
    if counts.get("error"):
        raise ValidationError(f"objective {kind} has {counts['error']} error(s)", details=out)
    return out


@_face_safe
def reference_add(project_path: str | Path, audio_path: str | Path, *, label: str | None = None,
                  actor: str = "human") -> dict:
    """Register a reference track: only its measurement vector is stored, never the audio (4.6, D-039)."""
    p = _check_audio_path(audio_path)
    proj = _open(project_path)
    res = _mod("reference").reference_add(proj, p, label=label, actor=actor)
    res["target_source"] = "references"
    return res


@_face_safe
def reference_list(project_path: str | Path) -> dict:
    """Registered references (vectors) and where objective targets come from."""
    return _mod("reference").reference_list(_open(project_path))


@_face_safe
def reference_remove(project_path: str | Path, ref_id: str, *, actor: str = "human") -> dict:
    """Remove a reference and its stored vector."""
    if not isinstance(ref_id, str) or not ref_id.strip():
        raise InputError("reference id must be a non-empty string")
    proj = _open(project_path)
    res = _mod("reference").reference_remove(proj, ref_id.strip(), actor=actor)
    res["remaining"] = len(proj.data.get("references") or [])
    return res


# -- stage proposals (R-31: approve and apply / reject and request an alternative) --

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _proposal_file(proj, proposal_id: str) -> Path:
    if not isinstance(proposal_id, str) or not _PROPOSAL_ID_RE.match(proposal_id):
        raise InputError(f"not a proposal id: {proposal_id!r}")
    return Path(proj.root) / PROPOSAL_DIR / f"{proposal_id}.json"


def _save_proposal(proj, proposal: dict) -> str:
    path = _proposal_file(proj, proposal["proposal_id"])
    _write_json(path, _jsonable(proposal))
    return proj.rel(path)


def _load_stage_proposal(proj, proposal_or_id: Any) -> tuple[dict, Path | None]:
    """A proposal given as a dict, JSON text, an id under cache/proposals/, or a path inside the project."""
    if isinstance(proposal_or_id, dict):
        pid = proposal_or_id.get("proposal_id")
        f = _proposal_file(proj, pid) if isinstance(pid, str) and _PROPOSAL_ID_RE.match(pid) else None
        return proposal_or_id, (f if f is not None and f.is_file() else None)
    if not isinstance(proposal_or_id, (str, Path)) or not str(proposal_or_id).strip():
        raise InputError("proposal must be an object, JSON text, a proposal id or a project-relative file")
    text = str(proposal_or_id).strip()
    if text.startswith("{"):
        prop = _parse_json_value(text, "proposal")
        if not isinstance(prop, dict):
            raise InputError("proposal must be a JSON object")
        return _load_stage_proposal(proj, prop)
    root = Path(proj.root).resolve()
    if _PROPOSAL_ID_RE.match(text) and not text.lower().endswith(".json"):
        cand = _proposal_file(proj, text)
    else:
        p = Path(text)
        cand = (p if p.is_absolute() else root / p).resolve()
        if cand != root and not cand.is_relative_to(root):
            raise InputError(f"proposal files must be inside the project: {p.name}",
                             details={"hint": "pass the proposal id, or the JSON itself (CLI: '@file')"})
    if not cand.is_file():
        raise InputError(f"proposal not found: {Path(text).name}",
                         details={"hint": f"pass a proposal id from {PROPOSAL_DIR}/, or the proposal JSON"})
    try:
        with open(cand, encoding="utf-8") as fh:
            prop = json.load(fh)
    except (OSError, ValueError) as e:
        raise InputError(f"cannot read proposal {cand.name}: {e}") from None
    if not isinstance(prop, dict):
        raise InputError(f"proposal {cand.name} is not a JSON object")
    return prop, cand


def _mark_proposal(path: Path | None, proposal: dict, **fields) -> None:
    if path is None:
        return
    stored = dict(proposal)
    stored.update(fields)
    _write_json(path, _jsonable(stored))


def _r4(x: Any) -> Any:
    return round(x, 4) if isinstance(x, float) and math.isfinite(x) else x


def proposal_summary(prop: dict) -> dict:
    """Token-cheap view of a stage proposal: chain, score breakdown, constraints, gate, open issues.
    Mix and cleanup proposals (no chain / planner keys) get their own summaries."""
    stage = _STAGE_ALIASES.get(prop.get("stage"), prop.get("stage"))
    if stage == "clean":
        return clean_proposal_summary(prop)
    if stage == "mix":
        return mix_proposal_summary(prop)
    ev = prop.get("objective_evaluation") or {}
    gate = ev.get("gate") or {}
    planner = prop.get("planner") or {}
    return {
        "proposal_id": prop.get("proposal_id"), "stage": prop.get("stage"), "status": prop.get("status"),
        "variant": prop.get("variant"), "profile": prop.get("profile"), "delivery": prop.get("delivery"),
        "chain": [{"id": p.get("id"), "type": p.get("type"), "params": p.get("params")} for p in prop.get("chain") or []],
        "score": _r4(ev.get("score")), "scope": ev.get("scope"),
        "breakdown": [{"objective": t.get("objective"), "metric": t.get("key"), "status": t.get("status"),
                       "value": _r4(t.get("value")), "penalty": _r4(t.get("penalty")),
                       "weight": _r4(t.get("effective_weight")), "contribution": _r4(t.get("contribution"))}
                      for t in ev.get("terms") or []],
        "constraints": ev.get("constraints"),
        "gate": {"status": gate.get("status"),
                 "checks": [{"id": c.get("id"), "status": c.get("status"), "reason": c.get("reason")}
                            for c in gate.get("checks") or []]} if gate else None,
        "converged": planner.get("converged"), "reason": planner.get("reason"),
        "iterations": max(0, len(planner.get("iterations") or []) - 1),
        "unresolved": sorted({u.get("code") for u in planner.get("unresolved") or [] if u.get("code")}),
        "send_back": prop.get("send_back"),
        "warnings": [w.get("code") for w in prop.get("warnings") or []],
        "operations": prop.get("operations"),
    }


_STAGE_ALIASES = {"cleanup": "clean"}


def _proposal_author(actor: str) -> str:
    """Who authored a proposal: an agent's request is an agent proposal; otherwise the planner made it."""
    return "agent" if actor == "agent" else "planner"


@_face_safe
def plan_propose(project_path: str | Path, stage: str = "master", *, variant: str | None = None,
                 profile: str | None = None, delivery: str | None = None, objective: Any = None,
                 max_iter: int | None = None, targets: list[str] | str | None = None, overrides: Any = None,
                 actor: str = "human") -> dict:
    """Propose a stage plan (R-31) for ``stage`` "clean", "mix" or "master" (default).

    master: the deterministic planner refines the master chain against the objective (level-matched
    previews, small moves). mix: the mix-stage planner (SPEC 6.5.1 fixed order; with ``variant`` the
    plan is stored as the variant's track overrides; ``max_iter`` default 4). clean: one cleanup plan
    per stem (or the 2-mix on the full-mix route); ``targets`` / ``overrides`` select assets and
    lighten steps. Every proposal carries parameters, rationale with rule ids, alternatives and (mix,
    master) the per-metric evaluation. Saved under cache/proposals/<id>.json; nothing is applied.
    ``actor`` records who asked for it (an agent's proposal awaits approval in the GUI, D-035).
    """
    proj = _open(project_path)
    _mod("journal").check_actor(actor)
    if max_iter is not None and (isinstance(max_iter, bool) or int(max_iter) < 0):
        raise InputError("max_iter must be >= 0")
    stage = _STAGE_ALIASES.get(stage, stage) if isinstance(stage, str) else stage
    if stage == "clean":
        if any(v is not None for v in (variant, profile, delivery, objective)):
            raise InputError("the cleanup stage takes targets / overrides, not variant, profile, delivery or objective")
        prop, rel = _clean_propose(proj, targets=targets, overrides=overrides, actor=actor)
    elif stage == "mix":
        if targets is not None or overrides is not None:
            raise InputError("targets / overrides belong to the cleanup stage")
        prop, rel = _mix_propose(proj, variant=variant, objective=objective,
                                 max_iter=MIX_MAX_ITER if max_iter is None else int(max_iter), excerpt=True,
                                 actor=actor)
    else:
        if targets is not None or overrides is not None:
            raise InputError("targets / overrides belong to the cleanup stage")
        prop = _mod("planner").propose(proj, stage, variant_id=variant, profile_id=profile, delivery_id=delivery,
                                       max_iter=None if max_iter is None else int(max_iter),
                                       objective=_objective_arg(objective))
        _stamp_proposal(prop, actor)
        rel = _save_proposal(proj, prop)
    return {"proposal_id": prop["proposal_id"], "proposal_path": rel, "stage": prop.get("stage"),
            "applied": False, "summary": stage_summary(prop), "proposal": prop}


def _editable_processors(prop: dict) -> list[dict]:
    """Processors whose parameters an approval may edit: the master chain, or every processor of a
    mix proposal's changes (track chains, FX bus chains, mix-bus chain)."""
    if prop.get("stage") == "mix":
        ch = prop.get("changes") or {}
        procs = [p for d in (ch.get("tracks") or {}).values() if isinstance(d, dict) for p in d.get("chain") or []]
        procs += [p for b in ch.get("buses") or [] if isinstance(b, dict) for p in b.get("chain") or []]
        procs += list(ch.get("mix_chain") or [])
        return [p for p in procs if isinstance(p, dict)]
    return [p for p in prop.get("chain") or [] if isinstance(p, dict)]


def _apply_edits(prop: dict, edits: Any, actor: str) -> tuple[dict, list[str]]:
    """Proposal with edited processor parameters: {processor id: {param: value}} (R-31: every
    proposal can be edited before it is applied). Only parameters the processor already has."""
    edits = _parse_json_value(edits, "edits")
    if not isinstance(edits, dict) or not all(isinstance(v, dict) for v in edits.values()):
        raise InputError('edits must be an object {"<processor id>": {"<param>": value}}')
    prop = json.loads(json.dumps(prop))
    chain = _editable_processors(prop)
    counts = Counter(p.get("id") for p in chain)
    by_id = {p.get("id"): p for p in chain}
    changed: list[str] = []
    for pid, params in edits.items():
        proc = by_id.get(pid)
        if proc is None:
            raise InputError(f"proposal {prop.get('proposal_id')} has no processor '{pid}'",
                             details={"processors": list(by_id)})
        if counts[pid] > 1:
            raise InputError(f"processor id '{pid}' is ambiguous in proposal {prop.get('proposal_id')}")
        current = proc.get("params") if isinstance(proc.get("params"), dict) else {}
        for k, v in params.items():
            if k not in current:
                raise InputError(f"processor '{pid}' has no parameter '{k}'", details={"params": sorted(current)})
            if isinstance(current[k], (int, float)) and not isinstance(current[k], bool) and                     (isinstance(v, bool) or not isinstance(v, (int, float))):
                raise InputError(f"parameter '{pid}.{k}' must be a number")
            if current[k] != v:
                current[k] = v
                changed.append(f"{pid}.{k}")
        proc["params"] = current
    if changed:
        prop["edits"] = {"by": actor, "at": _now_iso(), "params": edits, "changed": changed}
    return prop, changed


@_face_safe
def plan_apply(project_path: str | Path, proposal_or_id: Any, *, edits: Any = None,
               actor: str = "human") -> dict:
    """Approve and apply a stage proposal (R-31) of any stage (clean, mix, master).

    master: the variant stores the chain, the objective evaluation (score + per-metric breakdown,
    constraints, gate) and the decisions. mix: track gains / pans / chains / sends / automation, the
    FX bus and the mix-bus chain go to the project (or the variant's track overrides) with
    ``mix.applied`` / ``mix.decisions`` / ``mix.evaluation``. clean: cleaned audio, delta, records and
    noise baselines are written and the per-track plan is stored. ``edits`` ({processor id: {param:
    value}}) changes parameters of the proposed processors before applying (mix, master)."""
    proj = _open(project_path)
    prop, path = _load_stage_proposal(proj, proposal_or_id)
    if prop.get("status") == "rejected":
        raise InputError(f"proposal {prop.get('proposal_id')} was rejected; propose again to get a new plan",
                         details={"rejection": prop.get("rejection")})
    stage = _STAGE_ALIASES.get(prop.get("stage"), prop.get("stage"))
    if stage == "clean":
        if edits not in (None, {}, ""):
            raise InputError("cleanup proposals are changed through overrides: propose again with overrides "
                             "(e.g. {\"spectral_reduction\": \"light\"})")
        return {**_clean_apply(proj, prop, path, actor), "project": _project_summary(proj)}
    changed: list[str] = []
    if edits not in (None, {}, ""):
        prop, changed = _apply_edits(prop, edits, actor)
    if stage == "mix":
        out = {**_mix_apply(proj, prop, path, actor), "project": _project_summary(proj)}
    else:
        res = _mod("planner").apply(proj, prop, actor=actor)
        entries = _mod("journal").list_entries(proj.root, limit=1) or [{}]
        _mark_proposal(path, prop, status="applied",
                       applied={"actor": actor, "at": _now_iso(), "journal_seq": entries[-1].get("seq")})
        variant = _mod("mastering").find_variant(proj.data, prop.get("variant")) or {}
        out = {**res, "evaluation_stored": bool(variant.get("evaluation")),
               "decisions_stored": bool(variant.get("decisions")),
               "score": (variant.get("evaluation") or {}).get("score"),
               "send_back": prop.get("send_back"), "project": _project_summary(proj)}
    if changed:
        out["edited"] = changed
        out["note"] = ("the stored objective evaluation was computed for the proposed parameters; "
                       "propose again to evaluate the edited processors")
    return out


@_face_safe
def plan_reject(project_path: str | Path, proposal_id: str, reason: str, *, actor: str = "human") -> dict:
    """Reject a proposal and ask for an alternative (R-31). The rejection is journaled (op
    'plan_reject', no change to the project) and recorded in the proposal file."""
    if not isinstance(reason, str) or not reason.strip():
        raise InputError("a reason is required to reject a proposal")
    proj = _open(project_path)
    prop, path = _load_stage_proposal(proj, proposal_id)
    pid = prop.get("proposal_id") or str(proposal_id)
    if prop.get("status") == "applied":
        raise InputError(f"proposal {pid} is already applied; use undo to revert it")

    def compute(latest, _raw_hash):
        if latest is None:
            raise InputError("project.json has disappeared from the project folder")
        return latest

    entry = proj._commit(compute, actor=actor, op="plan_reject", reason=f"reject {pid}: {reason.strip()}",
                         patch=[], extra={"proposal_id": pid, "stage": prop.get("stage")}, force=True) or {}
    rejection = {"reason": reason.strip(), "actor": actor, "at": entry.get("ts") or _now_iso(),
                 "journal_seq": entry.get("seq")}
    _mark_proposal(path, prop, status="rejected", rejection=rejection)
    return {"rejected": True, "proposal_id": pid, "stage": prop.get("stage"), "rejection": rejection,
            "alternatives": prop.get("alternatives") or [],
            "next": {"ja": "目的関数、強度、プロファイル、反復回数などを変えて plan propose で別案を求める",
                     "en": "request an alternative with plan propose (change the objective, intensity, profile or iterations)"}}


@_face_safe
def planner_run(project_path: str | Path, *, variant: str | None = None, profile: str | None = None,
                delivery: str | None = None, objective: Any = None, max_iter: int = 6, apply: bool = False,
                actor: str = "planner") -> dict:
    """Run the planner loop (SPEC 7.2): measure -> propose -> preview -> evaluate, up to ``max_iter``
    iterations; the result is saved as a proposal and applied only with ``apply=True``."""
    proj = _open(project_path)
    _mod("journal").check_actor(actor)
    if max_iter is None or isinstance(max_iter, bool) or int(max_iter) < 0:
        raise InputError("max_iter must be >= 0")
    planner = _mod("planner")
    prop = planner.propose(proj, "master", variant_id=variant, profile_id=profile, delivery_id=delivery,
                           max_iter=int(max_iter), objective=_objective_arg(objective))
    _stamp_proposal(prop, actor)
    rel = _save_proposal(proj, prop)
    its = (prop.get("planner") or {}).get("iterations") or []
    out = {"proposal_id": prop["proposal_id"], "proposal_path": rel, "applied": False,
           "iterations": [{"i": it.get("i"), "score": _r4(it.get("score")),
                           "improvement": _r4(it.get("improvement")), "move": it.get("move")} for it in its],
           "score_start": _r4(its[0].get("score")) if its else None,
           "score_final": _r4((prop.get("objective_evaluation") or {}).get("score")),
           "converged": (prop.get("planner") or {}).get("converged"),
           "reason": (prop.get("planner") or {}).get("reason"),
           "unresolved": (prop.get("planner") or {}).get("unresolved"),
           "summary": proposal_summary(prop)}
    if apply:
        planner.apply(proj, prop, actor=actor)
        entries = _mod("journal").list_entries(proj.root, limit=1) or [{}]
        prop["status"] = "applied"
        prop["applied"] = {"actor": actor, "at": _now_iso(), "journal_seq": entries[-1].get("seq")}
        _write_json(Path(proj.root) / rel, _jsonable(prop))
        out["applied"] = True
        out["summary"]["status"] = "applied"
        out["project"] = _project_summary(proj)
    return out


# ---------------------------------------------------------------------------
# Cleanup and mix stages (SPEC 6.4, 6.5, 7.2, 10.2, 10.3; R-20, R-22, R-31). The stage
# modules (core/cleanstage.py, core/mixplan.py) make the proposals; this facade saves them
# under cache/proposals/ with a status, applies them and marks them applied.
# ---------------------------------------------------------------------------

MIX_MAX_ITER = 4


def _stamp_proposal(prop: dict, actor: str) -> dict:
    prop["status"] = "proposed"
    prop["proposed_at"] = _now_iso()
    prop["author"] = _proposal_author(actor)
    prop["requested_by"] = actor
    return prop


def _gate_brief(gate: Any) -> dict | None:
    """{status, failed[]} from a gate given as {checks: {id: status}} or {checks: [{id, status}]}."""
    if not isinstance(gate, dict):
        return None
    checks = gate.get("checks")
    if isinstance(checks, dict):
        failed = sorted(k for k, v in checks.items() if (v.get("status") if isinstance(v, dict) else v) == "fail")
    else:
        failed = sorted(c.get("id") for c in checks or [] if isinstance(c, dict) and c.get("status") == "fail")
    return {"status": gate.get("status"), "failed": failed}


def _failed_constraints(constraints: Any) -> list[str]:
    if not isinstance(constraints, dict):
        return []
    return sorted(k for k, v in constraints.items() if (v.get("status") if isinstance(v, dict) else v) == "fail")


def clean_proposal_summary(prop: dict) -> dict:
    """Token-cheap view of a cleanup proposal: per asset the steps that run, and what is skipped why."""
    route = prop.get("route")
    items = [{"asset": i.get("asset"), "kind": i.get("kind"), "track": i.get("track"), "role": i.get("role"),
              "mode": i.get("mode"), "plan_hash": (i.get("plan_hash") or "")[:12] or None,
              "steps": {k: a for k, a in sorted((i.get("steps") or {}).items()) if a != "skip"}}
             for i in prop.get("items") or [] if isinstance(i, dict)]
    skipped = [{"asset": s.get("asset"), "kind": s.get("kind"), "code": s.get("code"), "reason": s.get("reason")}
               for s in prop.get("skipped") or [] if isinstance(s, dict)]
    return {"proposal_id": prop.get("proposal_id"), "stage": "clean", "status": prop.get("status"),
            "route": route.get("route") if isinstance(route, dict) else route,
            "items": items, "skipped": skipped, "to_apply": len(items),
            "rules": prop.get("rules"), "operations": prop.get("operations")}


def mix_proposal_summary(prop: dict) -> dict:
    """Token-cheap view of a mix proposal: steps in the fixed order, kept moves, score, gate, open issues."""
    ev = prop.get("objective_evaluation") or {}
    meas = prop.get("measurements") or {}
    moves = [m for m in prop.get("moves") or [] if isinstance(m, dict)]
    kept = [m for m in moves if m.get("status") == "kept"]
    route = prop.get("route")
    return {
        "proposal_id": prop.get("proposal_id"), "stage": "mix", "status": prop.get("status"),
        "variant": prop.get("variant"), "lead": prop.get("lead"),
        "route": route.get("route") if isinstance(route, dict) else route,
        "balance_only": prop.get("balance_only"),
        "steps": [{"n": s.get("n"), "id": s.get("id"), "status": s.get("status"), "kept": len(s.get("kept") or [])}
                  for s in prop.get("order") or [] if isinstance(s, dict)],
        "moves": {"kept": len(kept), "rejected": len(moves) - len(kept)},
        "kept": [{"id": m.get("id"), "step": m.get("step"), "kind": m.get("kind"),
                  "target": m.get("track") or m.get("bus"), "rules": m.get("rules")} for m in kept[:40]],
        "score_start": _r4((meas.get("start") or {}).get("score")), "score": _r4(ev.get("score")),
        "scope": ev.get("scope"), "failed_constraints": _failed_constraints(ev.get("constraints")),
        "gate": _gate_brief(ev.get("gate")),
        "unresolved": sorted({u.get("code") for u in prop.get("unresolved") or [] if isinstance(u, dict) and u.get("code")}),
        "arrangement": [{"id": a.get("id"), "kind": a.get("kind"), "status": a.get("status")}
                        for a in prop.get("arrangement") or [] if isinstance(a, dict)],
        "operations": prop.get("operations"),
    }


def stage_summary(prop: dict) -> dict:
    """The summary of a proposal of any stage."""
    return proposal_summary(prop)


def _list_arg(value: Any, what: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = [x.strip() for x in value.split(",") if x.strip()]
    if not isinstance(value, (list, tuple)) or not all(isinstance(x, str) and x for x in value):
        raise InputError(f"{what} must be a list of ids (or a comma-separated string)")
    return list(value)


def _object_arg(value: Any, what: str) -> dict | None:
    if value is None or value == "":
        return None
    value = _parse_json_value(value, what) if isinstance(value, str) else value
    if not isinstance(value, dict):
        raise InputError(f"{what} must be a JSON object")
    return value


def _journal_seq(proj) -> int | None:
    entries = _mod("journal").list_entries(proj.root, limit=1) or [{}]
    return entries[-1].get("seq")


def _clean_propose(proj, *, targets: Any, overrides: Any, actor: str) -> tuple[dict, str]:
    prop = _mod("planner").propose(proj, "clean", targets=_list_arg(targets, "targets"),
                                   overrides=_object_arg(overrides, "overrides"))
    _stamp_proposal(prop, actor)
    return prop, _save_proposal(proj, prop)


def _clean_todo(prop: dict) -> int:
    return len(prop.get("items") or []) + sum(1 for s in prop.get("skipped") or [] if s.get("plan_hash"))


def _clean_apply(proj, prop: dict, path: Path | None, actor: str) -> dict:
    if prop.get("stage") != "clean":
        raise InputError(f"proposal {prop.get('proposal_id')} is a '{prop.get('stage')}' proposal, not a cleanup proposal")
    _mod("journal").check_actor(actor)
    res = _mod("planner").apply(proj, prop, actor=actor)
    _mark_proposal(path, prop, status="applied", applied={"actor": actor, "at": _now_iso(),
                                                          "journal_seq": _journal_seq(proj)})
    return res


def _mix_propose(proj, *, variant: str | None, objective: Any, max_iter: Any, excerpt: bool,
                 actor: str) -> tuple[dict, str]:
    if max_iter is None or isinstance(max_iter, bool) or int(max_iter) < 0:
        raise InputError("max_iter must be >= 0")
    if variant is not None and _mod("mastering").find_variant(proj.data, variant) is None:
        raise InputError(f"unknown variant '{variant}'", details={"valid": _variant_ids(proj.data)})
    prop = _mod("planner").propose(proj, "mix", variant_id=variant, objective=_objective_arg(objective),
                                   max_iter=int(max_iter), excerpt=bool(excerpt))
    _stamp_proposal(prop, actor)
    return prop, _save_proposal(proj, prop)


def _mix_apply(proj, prop: dict, path: Path | None, actor: str) -> dict:
    if prop.get("stage") != "mix":
        raise InputError(f"proposal {prop.get('proposal_id')} is a '{prop.get('stage')}' proposal, not a mix proposal")
    _mod("journal").check_actor(actor)
    _mod("planner").apply(proj, prop, actor=actor)
    _mark_proposal(path, prop, status="applied", applied={"actor": actor, "at": _now_iso(),
                                                          "journal_seq": _journal_seq(proj)})
    vid = prop.get("variant")
    holder = (_mod("mastering").find_variant(proj.data, vid) or {}).get("mix") if vid else proj.data.get("mix")
    holder = holder if isinstance(holder, dict) else {}
    ev = prop.get("objective_evaluation") or {}
    return {"applied": True, "stage": "mix", "proposal_id": prop.get("proposal_id"), "variant": vid,
            "tracks_changed": sorted((prop.get("changes") or {}).get("tracks") or {}),
            "buses_added": [b.get("id") for b in (prop.get("changes") or {}).get("buses") or []],
            "evaluation_stored": bool(holder.get("evaluation")), "decisions_stored": bool(holder.get("decisions")),
            "score": _r4(ev.get("score")), "gate": _gate_brief(ev.get("gate")),
            "route": _mod("routes").select_route(proj)["route"]}


@_face_safe
def clean_plan(project_path: str | Path, *, targets: list[str] | str | None = None, overrides: Any = None,
               apply: bool = False, actor: str = "human") -> dict:
    """Propose the cleanup stage (SPEC 6.4, R-31): diagnose each stem (or the 2-mix on the full-mix
    route) and plan the steps; assets where nothing is detected are listed as skipped with the
    reason. ``targets``: asset ids, track ids or "fullmix"; ``overrides``: step overrides for every
    target ({"spectral_reduction": "light"}) or keyed by asset / track id. Saved under
    cache/proposals/; ``apply=True`` also applies it."""
    proj = _open(project_path)
    _mod("journal").check_actor(actor)
    prop, rel = _clean_propose(proj, targets=targets, overrides=overrides, actor=actor)
    out = {"proposal_id": prop["proposal_id"], "proposal_path": rel, "stage": "clean", "applied": False,
           "summary": clean_proposal_summary(prop), "proposal": prop}
    if apply:
        if _clean_todo(prop):
            out["apply"] = _clean_apply(proj, prop, Path(proj.root) / rel, actor)
            out["applied"] = True
            out["summary"]["status"] = "applied"
        else:
            out["note"] = "nothing to apply"
    return out


@_face_safe
def clean_apply(project_path: str | Path, proposal_or_id: Any, *, actor: str = "human") -> dict:
    """Approve and apply a cleanup proposal (id, JSON or project-relative file): cleaned audio,
    delta, records and noise baselines are written; the per-track plan goes to project.json."""
    proj = _open(project_path)
    prop, path = _load_stage_proposal(proj, proposal_or_id)
    if prop.get("stage") != "clean":
        raise InputError(f"proposal {prop.get('proposal_id')} is a '{prop.get('stage')}' proposal, "
                         "not a cleanup proposal")
    if prop.get("status") == "rejected":
        raise InputError(f"proposal {prop.get('proposal_id')} was rejected; propose again to get a new plan",
                         details={"rejection": prop.get("rejection")})
    return {**_clean_apply(proj, prop, path, actor), "project": _project_summary(proj)}


def _cleanup_target(proj, target: str) -> str:
    data = proj.data
    assets = {a.get("id") for a in _asset_list(data)}
    if target in assets:
        return target
    if target in ("fullmix", "full_mix"):
        fm = sorted(_fullmix_ids(data))
        if not fm:
            raise InputError("the project has no full mix")
        return fm[0]
    for t in data.get("tracks") or []:
        if t.get("id") == target:
            for c in t.get("clips") or []:
                if c.get("asset"):
                    return c["asset"]
            raise InputError(f"track '{target}' has no clips")
    raise InputError(f"unknown cleanup target '{target}' (asset id, track id or 'fullmix')",
                     details={"assets": sorted(assets)})


STEM_SUM_DELTA = "renders/delta/stem_sum_delta.wav"


def _stem_sum_delta(proj, *, required: bool = True) -> dict | None:
    """The removed component of the whole stem set (SPEC 15.2: one delta for the main sample):
    the unprocessed stem sum (the D-036 "Before": every stem asset at 0 dB, head-aligned, project
    rate) minus the same sum of the cleaned stems, i.e. the unity-gain sum of every stem's cleanup
    delta. The reference full mix is not part of it. Rewritten only when the cleanup changes."""
    mr, cs, hashing = _mod("mixrender"), _mod("cleanstage"), _mod("hashing")
    data = proj.data
    fid = mr.fullmix_asset_id(data)
    stems = [aid for aid in _stem_ids(data) if aid != fid]
    applied = {aid: cs.applied_entry(data, aid) for aid in stems}
    cleaned = {aid: e for aid, e in applied.items() if e is not None}
    if not cleaned:
        if required:
            raise InputError("no cleanup changed any stem; run clean plan / apply first (or nothing was detected)")
        return None
    key = hashing.canonical_hash({"stems": [(aid, (_asset_by_id(data, aid) or {}).get("sha256")) for aid in stems],
                                  "cleaned": {aid: e.get("plan_hash") for aid, e in sorted(cleaned.items())}})
    path = Path(proj.root).joinpath(*STEM_SUM_DELTA.split("/"))
    side = path.with_name(path.stem + ".json")
    try:
        stored = json.loads(side.read_text(encoding="utf-8")) if side.is_file() else {}
    except (OSError, ValueError):
        stored = {}
    if not path.is_file() or stored.get("key") != key or stored.get("file_sha256") != _sha256_file(path):
        raw, sr, _ = mr.static_sum(proj)
        cl, sr2, _ = mr.static_sum(proj, cleaned=True)
        n = max(raw.shape[0], cl.shape[0])
        d = _pad_frames(raw, n) - _pad_frames(cl, n)
        cs.write_f32_wav(path, d, int(sr))
        _write_json(side, {"kind": "stem_sum_delta", "key": key, "sample_rate": int(sr),
                           "definition": "unprocessed stem sum minus the cleaned stem sum (D-036 alignment)",
                           "stems": stems, "cleaned": sorted(cleaned), "file_sha256": _sha256_file(path)})
    return {"asset": "stems", "delta": STEM_SUM_DELTA, "stems": stems, "cleaned": sorted(cleaned),
            "plan_hashes": {aid: e.get("plan_hash") for aid, e in sorted(cleaned.items())}}


def _pad_frames(x, n: int):
    import numpy as np
    if x.shape[0] >= n:
        return x[:n]
    return np.concatenate([x, np.zeros((n - x.shape[0], x.shape[1]), dtype=x.dtype)], axis=0)


def _asset_by_id(data: dict, aid: str) -> dict | None:
    return next((a for a in _asset_list(data) if a.get("id") == aid), None)


@_face_safe
def clean_delta(project_path: str | Path, asset_id: str) -> dict:
    """Write (if missing) and return the removed component of an asset's applied cleanup
    (input minus output, SPEC 6.4.3) for listening. ``asset_id``: asset id, track id or "fullmix";
    "stems" gives the delta of the whole stem set (unprocessed stem sum minus cleaned stem sum)."""
    proj = _open(project_path)
    if asset_id == "stems":
        return _stem_sum_delta(proj)
    aid = _cleanup_target(proj, asset_id)
    cs = _mod("cleanstage")
    rel = cs.delta(proj, aid)
    entry = cs.applied_entry(proj.data, aid, include_skipped=True) or {}
    rec = cs.cleanup_record(proj, aid) or {}
    return {"asset": aid, "delta": rel, "record": cs.record_rel(aid), "plan_hash": entry.get("plan_hash"),
            "steps": {k: s.get("action") for k, s in (rec.get("steps") or {}).items()},
            "removed_energy": (rec.get("report") or {}).get("removed_energy")}


@_face_safe
def mix_plan(project_path: str | Path, *, variant: str | None = None, objective: Any = None,
             max_iter: int = MIX_MAX_ITER, excerpt: bool = True, apply: bool = False,
             actor: str = "human") -> dict:
    """Propose the mix stage (SPEC 6.5, R-31): static balance, arrangement suggestions, subtractive
    EQ, dynamics, additive EQ, space, mix bus, measured after every step on level-matched previews
    (``excerpt``: representative excerpts; false = full length). ``variant`` plans a variant's mix
    (stored as its track overrides, SPEC 9.4). Saved under cache/proposals/; ``apply=True`` applies it."""
    proj = _open(project_path)
    _mod("journal").check_actor(actor)
    prop, rel = _mix_propose(proj, variant=variant, objective=objective, max_iter=max_iter, excerpt=excerpt,
                             actor=actor)
    out = {"proposal_id": prop["proposal_id"], "proposal_path": rel, "stage": "mix", "applied": False,
           "summary": mix_proposal_summary(prop), "decision_texts": prop.get("decision_texts"), "proposal": prop}
    if apply:
        out["apply"] = _mix_apply(proj, prop, Path(proj.root) / rel, actor)
        out["applied"] = True
        out["summary"]["status"] = "applied"
    return out


@_face_safe
def mix_apply(project_path: str | Path, proposal_or_id: Any, *, edits: Any = None, actor: str = "human") -> dict:
    """Approve and apply a mix proposal (id, JSON or project-relative file). ``edits``
    ({processor id: {param: value}}) changes proposed processor parameters first."""
    proj = _open(project_path)
    prop, path = _load_stage_proposal(proj, proposal_or_id)
    if prop.get("stage") != "mix":
        raise InputError(f"proposal {prop.get('proposal_id')} is a '{prop.get('stage')}' proposal, not a mix proposal")
    if prop.get("status") == "rejected":
        raise InputError(f"proposal {prop.get('proposal_id')} was rejected; propose again to get a new plan",
                         details={"rejection": prop.get("rejection")})
    changed: list[str] = []
    if edits not in (None, {}, ""):
        prop, changed = _apply_edits(prop, edits, actor)
    out = {**_mix_apply(proj, prop, path, actor), "project": _project_summary(proj)}
    if changed:
        out["edited"] = changed
        out["note"] = ("the stored objective evaluation was computed for the proposed parameters; "
                       "propose again to evaluate the edited processors")
    return out


# ---------------------------------------------------------------------------
# Remix operations on stems (SPEC 9.3; core/remix.py). Times are samples at the project
# rate; every time argument also accepts seconds written as "12.5s".
# ---------------------------------------------------------------------------

STEM_EDIT_OPS = ("split", "mute", "move", "role", "range_replace", "remove")


def _samples_arg(proj, value: Any, name: str) -> int:
    if isinstance(value, bool) or value is None:
        raise InputError(f"{name} must be a sample count (or seconds as '1.5s')")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        try:
            if s.endswith("s"):
                return int(round(float(s[:-1]) * _mod("mixrender").project_rate(proj.data)))
            return int(s)
        except ValueError:
            pass
    raise InputError(f"{name} must be a sample count (or seconds as '1.5s'), got {value!r}")


def _remix():
    return _mod("remix")


@_face_safe
def stem_list(project_path: str | Path) -> dict:
    """Tracks (role, lead, level, pan, routing, clips), unused assets and R-22 notes."""
    return _remix().stem_list(_open(project_path))


@_face_safe
def stem_add(project_path: str | Path, source: str | Path, *, role: str | None = None, mode: str = "copy",
             reason: str = "", actor: str = "human") -> dict:
    """Import a file as a new stem track (import checks + tempo / key consistency report, D-048)."""
    if not Path(source).is_file():
        raise InputError(f"source not found: {Path(source).name}")
    if mode not in ("copy", "link"):
        raise InputError(f"unknown import mode '{mode}' (use copy or link)")
    return _remix().stem_add(_open(project_path), str(source), role=role, actor=actor, mode=mode, reason=reason)


@_face_safe
def stem_replace(project_path: str | Path, track_id: str, source: str | Path | None = None, *,
                 asset: str | None = None, keep_chain: bool = True, mode: str = "copy", reason: str = "",
                 actor: str = "human") -> dict:
    """Point a track's clips at another audio file (``source``, imported) or an existing ``asset``."""
    if (source is None) == (asset is None):
        raise InputError("give exactly one of source (a file to import) or asset (an existing asset id)")
    proj = _open(project_path)
    if asset is not None:
        if asset not in {a.get("id") for a in _asset_list(proj.data)}:
            raise InputError(f"unknown asset '{asset}'")
        src: Any = asset
    else:
        if not Path(source).is_file():
            raise InputError(f"source not found: {Path(source).name}")
        src = str(source)
    return _remix().stem_replace(proj, track_id, src, keep_chain=keep_chain, actor=actor, mode=mode, reason=reason)


@_face_safe
def stem_remove(project_path: str | Path, track_id: str, *, reason: str = "", actor: str = "human") -> dict:
    """Remove a track; its assets stay in the project, flagged unused."""
    return _remix().stem_remove(_open(project_path), track_id, actor=actor, reason=reason)


@_face_safe
def stem_move(project_path: str | Path, clip_id: str, timeline_start: int | str, *, reason: str = "",
              actor: str = "human") -> dict:
    """Move a clip on the timeline (samples, or seconds as '1.5s')."""
    proj = _open(project_path)
    return _remix().clip_move(proj, clip_id, _samples_arg(proj, timeline_start, "timeline_start"),
                              actor=actor, reason=reason)


@_face_safe
def stem_split(project_path: str | Path, clip_id: str, at: int | str, *, reason: str = "",
               actor: str = "human") -> dict:
    """Split a clip at a timeline position; both halves play exactly as before."""
    proj = _open(project_path)
    return _remix().clip_split(proj, clip_id, _samples_arg(proj, at, "at"), actor=actor, reason=reason)


@_face_safe
def stem_mute(project_path: str | Path, track_id: str, start: int | str, end: int | str, *, reason: str = "",
              actor: str = "human") -> dict:
    """Mute [start, end) of a track (the clips are split at the edges, the pieces inside muted)."""
    proj = _open(project_path)
    return _remix().range_mute(proj, track_id, _samples_arg(proj, start, "start"), _samples_arg(proj, end, "end"),
                               actor=actor, reason=reason)


@_face_safe
def stem_range_replace(project_path: str | Path, track_id: str, start: int | str, end: int | str, asset: str, *,
                       source_start: int | str = 0, reason: str = "", actor: str = "human") -> dict:
    """Mute [start, end) of a track and place a clip of another asset there (from ``source_start``)."""
    proj = _open(project_path)
    return _remix().range_replace(proj, track_id, _samples_arg(proj, start, "start"), _samples_arg(proj, end, "end"),
                                  asset, source_start=_samples_arg(proj, source_start, "source_start"),
                                  actor=actor, reason=reason)


@_face_safe
def stem_role(project_path: str | Path, track_id: str, role: str, *, is_lead: bool | None = None,
              reason: str = "", actor: str = "human") -> dict:
    """Change a track's role and, optionally, make it (or stop it being) the single lead."""
    return _remix().set_role(_open(project_path), track_id, role, is_lead=is_lead, actor=actor, reason=reason)


@_face_safe
def stem_edit(project_path: str | Path, op: str, *, track: str | None = None, clip: str | None = None,
              start: int | str | None = None, end: int | str | None = None, at: int | str | None = None,
              timeline_start: int | str | None = None, role: str | None = None, is_lead: bool | None = None,
              asset: str | None = None, source_start: int | str = 0, reason: str = "",
              actor: str = "human") -> dict:
    """One remix edit selected by ``op``: split (clip, at), mute (track, start, end), move (clip,
    timeline_start), role (track, role, is_lead), range_replace (track, start, end, asset,
    source_start), remove (track). Times in samples or seconds ('1.5s')."""
    need = {"split": ("clip", "at"), "mute": ("track", "start", "end"), "move": ("clip", "timeline_start"),
            "role": ("track", "role"), "range_replace": ("track", "start", "end", "asset"), "remove": ("track",)}
    if op not in need:
        raise InputError(f"unknown stem edit '{op}'", details={"valid": list(STEM_EDIT_OPS)})
    given = {"track": track, "clip": clip, "start": start, "end": end, "at": at, "timeline_start": timeline_start,
             "role": role, "asset": asset}
    missing = [k for k in need[op] if given[k] is None]
    if missing:
        raise InputError(f"stem edit '{op}' needs: {', '.join(missing)}")
    if op == "split":
        return stem_split(project_path, clip, at, reason=reason, actor=actor)
    if op == "mute":
        return stem_mute(project_path, track, start, end, reason=reason, actor=actor)
    if op == "move":
        return stem_move(project_path, clip, timeline_start, reason=reason, actor=actor)
    if op == "role":
        return stem_role(project_path, track, role, is_lead=is_lead, reason=reason, actor=actor)
    if op == "range_replace":
        return stem_range_replace(project_path, track, start, end, asset, source_start=source_start,
                                  reason=reason, actor=actor)
    return stem_remove(project_path, track, reason=reason, actor=actor)


@_face_safe
def stem_export(project_path: str | Path, tracks: list[str] | str | None = None, *, processed: bool = True,
                out_dir: str = "renders/stems", subtype: str = "FLOAT", variant: str | None = None) -> dict:
    """Write one stereo WAV per stem track (full timeline from sample 0) plus manifest.json under
    ``out_dir`` (project-relative). processed: as the track sits in the mix (chain, fader, pan);
    otherwise the edited clip layout only. ``subtype``: FLOAT, PCM_24 or PCM_16 (TPDF dither)."""
    proj = _open(project_path)
    if variant is not None and _mod("mastering").find_variant(proj.data, variant) is None:
        raise InputError(f"unknown variant '{variant}'", details={"valid": _variant_ids(proj.data)})
    return _remix().stem_export(proj, _list_arg(tracks, "tracks"), processed=processed, out_dir=out_dir,
                                subtype=subtype, variant_id=variant)


# ---------------------------------------------------------------------------
# One-shot pipeline (SPEC 6, 7.1, 10.2 `run`): the planner alone, from the input files to
# verified masters and the Mix Report (core/pipeline.py).
# ---------------------------------------------------------------------------

@_face_safe
def run(sources: list[str], *, objective: Any = "comfort", profile: str | list[str] = "streaming_universal",
        delivery: str | list[str] | None = None, variants: Any = None, out: str | Path | None = None,
        project: str | Path | None = None, genre: str | None = None, title: str | None = None,
        separate: bool = False, mode: str = "copy", variant_mix: bool = False,
        mix_max_iter: int = MIX_MAX_ITER, master_max_iter: int = 6, excerpt: bool = True,
        actor: str = "planner") -> dict:
    """Run every stage with the planner only (no agent, SPEC 7.1): create or open the project, import
    as-is, analyze, clean (plan + apply; skipped when nothing is detected), mix (plan + apply when
    stems exist; a 2-mix alone takes the full-mix route), master per variant (planner loop, applied),
    render, verify, Mix Report (ja + en) and copy the deliverables (masters, manifests, reports) to
    ``out``. A failed stage gate stops the run with the stage, the reason and ``exit_code`` (1 for a
    failed gate or verification). ``objective``: 'id', 'id:intensity' or 'a:0.6+b:0.4';
    ``profile`` / ``delivery``: one or several (every profile gets every delivery); ``variants``:
    [{objective, profile, delivery}] instead. ``project`` defaults to '<name>.mmx' next to ``out``
    (or in the current folder)."""
    return _mod("pipeline").run(sources, objective=objective, profile=profile, delivery=delivery,
                                variants=variants, out=out, project=project, genre=genre, title=title,
                                separate=separate, mode=mode, variant_mix=variant_mix, mix_max_iter=mix_max_iter,
                                master_max_iter=master_max_iter, excerpt=excerpt, actor=actor)


@_face_safe
def gate_check(project_path: str | Path, variant: str | None = None) -> dict:
    """Translation gate OF-5 (SPEC 4.5) on a variant's rendered master (or an in-memory render of its
    chain, or the unprocessed input when the project has no variant). ``exit_code`` is 0 only for 'pass';
    'incomplete' (checks that cannot be evaluated, e.g. lead checks without stems) is never a pass."""
    proj = _open(project_path)
    data = proj.data
    variants = [v.get("id") for v in data.get("variants", []) or [] if isinstance(v, dict)]
    vid = None if (variant is None and not variants) else _variant_or_default(proj, variant)
    mastering, render_mod, routes = _mod("mastering"), _mod("render"), _mod("routes")
    O, cfg = _mod("objectives"), _mod("config")
    v = mastering.find_variant(data, vid) if vid else None
    outputs = (v or {}).get("outputs") or []
    profile = outputs[0].get("profile") if outputs else None
    source, file_rel = "input", None
    archive = None
    if v is not None:
        ad = cfg.get_delivery(render_mod.ARCHIVE_DELIVERY)
        archive = render_mod.variant_dir(proj, vid) / f"master__{render_mod.ARCHIVE_DELIVERY}.{render_mod.output_ext(ad)}"
    if archive is not None and archive.is_file():
        x, sr = _mod("audio_io").read(archive)
        source, file_rel = "render", proj.rel(archive)
    else:
        route = render_mod.variant_route(proj, v) if v is not None else routes.select_route(proj)["route"]
        x, sr = routes.load_master_input(proj, route, variant_id=vid)
        chain = ((v or {}).get("master") or {}).get("chain")
        if chain:
            x = mastering._render(x, sr, chain).audio
            source = "in_memory_render"
    resolved = O.resolve_objective(proj, variant=vid)
    g = _mod("gate").evaluate_gate(x, sr, stems=None, meta=resolved.get("stems_meta"), profile=profile,
                                   lead=(resolved.get("lead") or {}).get("stem"),
                                   strict_mono=bool((resolved.get("gate") or {}).get("strict_mono_fold")))
    notes = list(g.get("notes") or [])
    if resolved.get("stems"):
        notes.append("stem signals are not passed at the master stage; lead checks need the mix stage (M4)")
    g["notes"] = notes
    explain = {"pass": "every required check passed",
               "fail": "a required check failed: the candidate is a correction target regardless of its score (SPEC 4.1)",
               "incomplete": "some required checks could not be evaluated (see each check's reason); incomplete is never a pass"}
    return {"variant": vid, "source": source, "file": file_rel, **g,
            "status_meaning": explain.get(g.get("status")), "exit_code": 0 if g.get("pass") else 1}


@_face_safe
def project_get(project_path: str | Path, pointer: str | None = None) -> dict:
    """project.json, or the sub-tree at an RFC 6901 JSON pointer ('' or None = whole document)."""
    ptr = pointer or ""
    if ptr and not ptr.startswith("/"):
        raise InputError(f"not a JSON pointer: {ptr!r} (must start with '/')")
    data = _open(project_path).data
    if not ptr:
        return {"pointer": "", "value": data}
    try:
        value = _mod("jsonpatch").resolve(data, ptr)
    except ValidationError as e:
        raise InputError(e.message) from None
    return {"pointer": ptr, "value": value}


@_face_safe
def knowledge_lookup(query: str | None = None, *, id: str | None = None, kind: str | None = None,
                     source: str | None = None, limit: int = 20, detail: bool = False) -> dict:
    """Look up knowledge data (SPEC 7.3, 10.3): rules R-01..R-33, perceptual vocabulary and bands,
    genre priors, thresholds, objective metric tables. Free text matches ids, labels and notes."""
    return _mod("knowledge").knowledge_lookup(query, id=id, kind=kind, source=source, limit=limit, detail=detail)


# ---------------------------------------------------------------------------
# Model registry and stem separation (M6: SPEC 6.2, 12, S-10, S-11, D-060)
# ---------------------------------------------------------------------------

def _model_entries() -> dict[str, dict]:
    reg = _mod("registry")
    entries = list(reg.load_catalog().get("models") or []) + list(reg.load_byow().get("models") or [])
    return {m["id"]: m for m in entries if isinstance(m, dict) and m.get("id")}


def _license_block(entry: dict) -> dict:
    lic = entry.get("license") if isinstance(entry.get("license"), dict) else {}
    return {"code": lic.get("code"), "weights": lic.get("weights"),
            "usage_restrictions": lic.get("usage_restrictions"),
            "evidence": [e for e in lic.get("evidence") or [] if isinstance(e, dict)],
            "caveats": list(lic.get("caveats") or [])}


@_face_safe
def model_list() -> dict:
    """Registered models: the official catalogue and local BYOW registrations, with local state
    (``installed`` = weights present). Weights are never bundled (SPEC 12.1)."""
    res = _mod("registry").model_list()
    entries = _model_entries()
    for m in res.get("models") or []:
        e = entries.get(m.get("id")) or {}
        m["installed"] = m.get("state") in ("installed", "registered")
        m["license"] = _license_block(e)
        m["attribution"] = e.get("attribution")
        if e.get("status_reason"):
            m["status_reason"] = e["status_reason"]
    return res


@_face_safe
def model_show(id: str) -> dict:
    """One model: license with evidence, attribution, pinned files and whether they are present."""
    return _mod("registry").model_show(id)


@_face_safe
def model_pull(id: str, *, allow_candidate: bool = False, force: bool = False) -> dict:
    """Download a catalogue model from its pinned official source and verify the sha256.
    Only 'verified' entries are pulled unless ``allow_candidate`` (SPEC 12.2, S-10)."""
    return _mod("registry").model_pull(id, allow_candidate=allow_candidate, force=force)


@_face_safe
def model_register(path: str | Path, *, id: str, license_weights: str, license_code: str | None = None,
                   usage_restrictions: str = "unknown", evidence_url: str | None = None,
                   task: str = "separation", architecture: str | None = None, stems: list[str] | None = None,
                   runtime: dict | None = None, attribution: str = "", note: str = "",
                   replace: bool = False) -> dict:
    """Register your own weights (BYOW, SPEC 12.4): the file is hashed in place, never copied,
    downloaded or redistributed; the declared license is recorded and is the user's responsibility."""
    runtime = _parse_json_value(runtime, "runtime") if isinstance(runtime, str) else runtime
    if isinstance(stems, str):
        stems = [s.strip() for s in stems.split(",") if s.strip()]
    return _mod("registry").model_register(
        path, id=id, license_weights=license_weights, license_code=license_code,
        usage_restrictions=usage_restrictions, evidence_url=evidence_url, task=task,
        architecture=architecture, stems=stems, runtime=runtime, attribution=attribution, note=note,
        replace=replace)


@_face_safe
def model_verify(id: str) -> dict:
    """Re-hash a model's local weight files (no cache) against the pinned sha256."""
    return _mod("registry").model_verify(id)


@_face_safe
def model_remove(id: str) -> dict:
    """Official model: delete the downloaded weights. BYOW: forget the registration (file untouched)."""
    return _mod("registry").model_remove(id)


@_face_safe
def separate(project_path: str | Path, *, model: str | None = None, source: str | None = None,
             mode: str = "preview", stems: list[str] | None = None, device: str = "auto",
             allow_candidate: bool = False, add_tracks: bool | None = None, excerpt_s: float | None = None,
             actor: str = "human") -> dict:
    """Separate a project asset (default: the full mix) into stems with a registered model (SPEC 6.2).

    ``mode`` 'preview' separates the loudest excerpt (``excerpt_s``, default 30 s) and adds assets
    only; 'full' separates the whole file and also adds tracks restricted to balance operations
    (R-22). The model runs in a worker subprocess (D-060); nothing is downloaded here (S-10) and
    the source asset is never modified (S-11)."""
    _mod("journal").check_actor(actor)
    if isinstance(stems, str):
        stems = [s.strip() for s in stems.split(",") if s.strip()]
    proj = _open(project_path)
    kw: dict[str, Any] = {}
    if excerpt_s is not None:
        kw["excerpt_s"] = float(excerpt_s)
    return _mod("separation").separate(proj, model_id=model, source_asset=source, mode=mode, stems=stems,
                                       device=device, allow_candidate=allow_candidate, add_tracks=add_tracks,
                                       actor=actor, **kw)


@_face_safe
def separation_list(project_path: str | Path) -> dict:
    """Separation records of a project (model id and sha256, license, attribution, stems)."""
    recs = _mod("separation").separation_records(_open(project_path))
    return {"separations": recs, "count": len(recs)}


# ---------------------------------------------------------------------------
# Views for the GUI and the other faces (M8, SPEC 11, 15.2). Read-only compositions
# of project data, proposals, renders, verification and analysis results; every
# face gets the same view (SPEC 10.1).
# ---------------------------------------------------------------------------

LISTEN_DIR = "cache/listen"


class NotGenerated(InputError):
    code = "not_generated"


def _write_json_atomic(path: Path, obj: Any) -> None:
    """Like _write_json, with a unique temp file (the GUI server reads views from several threads)."""
    import threading
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def _file_key(path: Path) -> str:
    st = path.stat()
    return f"{path.name}|{st.st_size}|{st.st_mtime_ns}"


def _safe_name(rel: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", rel).strip("_")[:120] or "x"


def _listen_cached(proj, name: str, key: str, compute: Callable[[], Any]) -> Any:
    """Derived data cached under cache/listen/<name>.json, recomputed when ``key`` changes."""
    f = Path(proj.root) / LISTEN_DIR / f"{_safe_name(name)}.json"
    try:
        stored = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(stored, dict) and stored.get("key") == key:
            return stored.get("value")
    except (OSError, ValueError):
        pass
    value = _jsonable(compute())
    try:
        _write_json_atomic(f, {"key": key, "value": value})
    except OSError:
        pass   # only a cache
    return value


def _variant_ids(data: dict) -> list[str]:
    return [v.get("id") for v in data.get("variants", []) or [] if isinstance(v, dict)]


def _find_variant(data: dict, vid: str | None) -> dict | None:
    return next((v for v in data.get("variants", []) or [] if isinstance(v, dict) and v.get("id") == vid), None)


def _rendered_files(proj, vid: str) -> dict:
    """Rendered files of a variant on disk: archive master and outputs (Paths or None)."""
    render_mod, cfg = _mod("render"), _mod("config")
    vdir = render_mod.variant_dir(proj, vid)
    out: dict[str, Any] = {"archive": None, "outputs": []}
    try:
        ad = cfg.get_delivery(render_mod.ARCHIVE_DELIVERY)
        archive = vdir / f"master__{render_mod.ARCHIVE_DELIVERY}.{render_mod.output_ext(ad)}"
        out["archive"] = archive if archive.is_file() else None
    except MankoError:
        pass
    for o in (_find_variant(proj.data, vid) or {}).get("outputs") or []:
        try:
            prof = cfg.get_profile(o.get("profile"))
            d = cfg.get_delivery(o.get("delivery"))
        except MankoError:
            continue
        p = vdir / render_mod.output_name(prof["id"], d)
        out["outputs"].append({"profile": prof["id"], "delivery": d["id"], "path": p if p.is_file() else None})
    return out


def _after_file(proj, vid: str | None) -> Path | None:
    if not vid:
        return None
    files = _rendered_files(proj, vid)
    return files["archive"] or next((o["path"] for o in files["outputs"] if o["path"]), None)


def _route_of(proj, vid: str | None) -> str:
    v = _find_variant(proj.data, vid) if vid else None
    if v is not None:
        return _mod("render").variant_route(proj, v)
    return _mod("routes").select_route(proj)["route"]


def _before_file(proj, vid: str | None) -> tuple[Path | None, str, str | None]:
    """The unprocessed 'before' of SPEC 15.2 -> (file, kind, analysis key).

    Full-mix route: the full-mix asset itself. Stem routes: the static stem sum (gain 0 dB,
    no processing), written once to cache/listen/ and keyed by the stem hashes and the rate."""
    data = proj.data
    route = _route_of(proj, vid)
    fm = _mod("routes").fullmix_asset_id(data)
    if route == "full_mix" and fm:
        p = Path(proj.asset_path(fm))
        return (p if p.is_file() else None), "fullmix", fm
    ids = {a.get("id") for a in _asset_list(data)}
    stems = [s for s in _stem_ids(data) if s in ids]
    if not stems:
        return None, "none", None
    rate = _project_rate(data) or 48000
    shas = {a["id"]: a.get("sha256") for a in _asset_list(data)}
    key = hashlib.sha256(json.dumps({"rate": rate, "stems": [[s, shas.get(s)] for s in sorted(stems)]},
                                    sort_keys=True).encode("utf-8")).hexdigest()[:16]
    d = Path(proj.root) / LISTEN_DIR
    f = d / f"before_stem_sum_{key}.wav"
    if not f.is_file():
        import threading

        import numpy as np
        x = _stem_sum_signal(proj, stems, rate)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{f.stem}.{os.getpid()}.{threading.get_ident()}.tmp.wav"
        _mod("audio_io").write(tmp, x.astype(np.float32), rate, subtype="FLOAT")
        os.replace(tmp, f)
        for old in d.glob("before_stem_sum_*.wav"):
            if old != f:
                try:
                    old.unlink()
                except OSError:
                    pass
    return f, "stem_sum", STEM_SUM_ID


def _level(proj, path: Path) -> dict:
    def compute():
        x, sr = _mod("audio_io").read(path)
        ld = _mod("measure.loudness")
        lufs, tp = float(ld.integrated(x, sr)), float(ld.true_peak_dbtp(x, sr))
        return {"lufs_i": round(lufs, 2) if math.isfinite(lufs) else None,
                "true_peak_dbtp": round(tp, 2) if math.isfinite(tp) else None}
    return _listen_cached(proj, "level_" + proj.rel(path), _file_key(path), compute)


def _label2(ja: str, en: str) -> dict:
    return {"ja": ja, "en": en}


@_face_safe
def variant_list(project_path: str | Path) -> dict:
    """Variants (objective x media profile) with their objective blend, outputs and render state."""
    proj = _open(project_path)
    data = proj.data
    out = []
    for v in data.get("variants", []) or []:
        if not isinstance(v, dict):
            continue
        obj = v.get("objective") if isinstance(v.get("objective"), dict) else data.get("objective")
        obj = obj if isinstance(obj, dict) else None
        blend = sorted([b for b in (obj or {}).get("blend") or [] if isinstance(b, dict)],
                       key=lambda b: -float(b.get("weight") or 0))
        outs = [o for o in v.get("outputs") or [] if isinstance(o, dict)]
        files = _rendered_files(proj, v["id"])
        out.append({
            "id": v.get("id"), "label": v.get("label"),
            "objectives": [b.get("id") for b in blend], "objective": obj,
            "profile": outs[0].get("profile") if outs else "",
            "deliveries": [o.get("delivery") for o in outs],
            "intensity": (obj or {}).get("intensity"),
            "available": True,
            "has_master_chain": bool((v.get("master") or {}).get("chain")),
            "rendered": files["archive"] is not None or any(o["path"] for o in files["outputs"]),
        })
    return {"variants": out, "count": len(out)}


def _proposal_files(proj) -> list[Path]:
    d = Path(proj.root) / PROPOSAL_DIR
    if not d.is_dir():
        return []
    files = [p for p in d.glob("*.json") if p.is_file()]
    return sorted(files, key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)


_PROPOSAL_STATUS = {"proposed": "pending", "pending": "pending", "applied": "applied", "rejected": "rejected"}


def proposal_view(prop: dict) -> dict:
    """A stage proposal as reviewable steps (target, processor with rule ids, editable params) plus
    status and author: what a reviewer approves, edits or rejects (R-31, D-035)."""
    stage = prop.get("stage")
    steps: list[dict] = []
    if isinstance(prop.get("steps"), list):
        steps = [s for s in prop["steps"] if isinstance(s, dict)]
    elif stage == "clean":
        for i in prop.get("items") or []:
            if not isinstance(i, dict):
                continue
            params = {k: a for k, a in sorted((i.get("steps") or {}).items())}
            steps.append({"target": i.get("track") or i.get("asset"),
                          "processor": {"id": f"cleanup:{i.get('asset')}", "type": "cleanup", "params": params,
                                        "reason": "R-20: " + ", ".join(f"{k}={a}" for k, a in params.items()
                                                                     if a != "skip")},
                          "editable": []})
    elif stage == "mix":
        ch = prop.get("changes") or {}
        for tid, d in (ch.get("tracks") or {}).items():
            for p in (d or {}).get("chain") or []:
                if isinstance(p, dict):
                    steps.append({"target": tid, "processor": {**p, "reason": p.get("reason", "")},
                                  "editable": sorted(p.get("params") or {})})
        for b in ch.get("buses") or []:
            for p in (b or {}).get("chain") or []:
                if isinstance(p, dict):
                    steps.append({"target": b.get("id"), "processor": {**p, "reason": p.get("reason", "")},
                                  "editable": sorted(p.get("params") or {})})
        for p in ch.get("mix_chain") or []:
            if isinstance(p, dict):
                steps.append({"target": ch.get("mix_bus") or "mix", "processor": {**p, "reason": p.get("reason", "")},
                              "editable": sorted(p.get("params") or {})})
    else:
        for p in prop.get("chain") or []:
            if not isinstance(p, dict):
                continue
            proc = dict(p)
            proc.setdefault("reason", "")
            params = proc.get("params") if isinstance(proc.get("params"), dict) else {}
            steps.append({"target": p.get("target") or "master", "processor": proc, "editable": sorted(params)})
    ev = prop.get("objective_evaluation") or {}
    score = ev.get("score")
    vid = prop.get("variant")
    sc = f" (score {score:.3f})" if isinstance(score, (int, float)) else ""
    rej = prop.get("rejection") if isinstance(prop.get("rejection"), dict) else {}
    edits = prop.get("edits") if isinstance(prop.get("edits"), dict) else {}
    return {
        "id": prop.get("proposal_id"), "proposal_id": prop.get("proposal_id"),
        "stage": "cleanup" if stage == "clean" else stage, "variant": vid,
        "author": prop.get("author") or "planner",
        "status": _PROPOSAL_STATUS.get(prop.get("status") or "proposed", "pending"),
        "created_at": prop.get("proposed_at"),
        "summary": _label2(f"{stage} の計画" + (f"（{vid}）" if vid else "") + sc,
                           f"{stage} plan" + (f" for {vid}" if vid else "") + sc),
        "steps": steps,
        "score": _r4(score),
        "alternatives": prop.get("alternatives") or [],
        "reject_reason": rej.get("reason"),
        "edited": edits.get("changed"),
    }


@_face_safe
def proposal_list(project_path: str | Path, *, variant: str | None = None, stage: str | None = None,
                  status: str | None = None) -> dict:
    """Stage proposals saved under cache/proposals/ (planner and agent proposals, any status),
    newest first, as reviewable steps. ``status``: pending, applied or rejected."""
    proj = _open(project_path)
    stage = _STAGE_ALIASES.get(stage, stage) if stage else None
    out = []
    for f in _proposal_files(proj):
        try:
            prop = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(prop, dict) or not prop.get("proposal_id"):
            continue
        if (variant and prop.get("variant") != variant) or (stage and prop.get("stage") != stage):
            continue
        view = proposal_view(prop)
        if status and view["status"] != status:
            continue
        out.append(view)
    return {"proposals": out, "count": len(out)}


@_face_safe
def proposal_get(project_path: str | Path, proposal_id: str) -> dict:
    """One saved proposal: its reviewable view and the full proposal."""
    proj = _open(project_path)
    f = _proposal_file(proj, proposal_id)
    if not f.is_file():
        raise NotGenerated(f"proposal not found: {proposal_id}")
    try:
        prop = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputError(f"cannot read proposal {f.name}: {e}") from None
    return {"view": proposal_view(prop), "proposal": prop}


_CHECK_STATUS = {"pass": "pass", "fail": "fail", "warning": "warning", "not_run": "not_run",
                 "not_evaluated": "not_run", "incomplete": "not_run", "missing": "fail"}
_STATUS_RANK = {"fail": 3, "warning": 2, "not_run": 1, "pass": 0}


def _first_measured(check: dict) -> Any:
    m = check.get("measured")
    if isinstance(m, dict) and m:
        return next(iter(m.values()))
    return check.get("value")


def _s08_worst_delta(check: dict) -> tuple[str | None, Any, Any]:
    """(key, delta_db, tolerance_db) of the judged S-08 metric with the largest delta - tolerance.
    s08_check nests the values under ``deltas``; metrics that could not be judged are skipped."""
    best: tuple[float, str, Any, Any] | None = None
    for k, d in (check.get("deltas") or {}).items():
        if not isinstance(d, dict) or d.get("pass") is None:
            continue
        try:
            excess = float(d["delta_db"]) - float(d["tolerance_db"])
        except (KeyError, TypeError, ValueError):
            continue
        if best is None or excess > best[0]:
            best = (excess, k, d.get("delta_db"), d.get("tolerance_db"))
    return (None, None, None) if best is None else best[1:]


def verification_view(report: dict, variant: dict | None = None) -> dict:
    """A verify report (reports/verify_<variant>.json) as constraint, profile, codec and noise rows.
    Checks that could not run stay 'not_run', never 'pass' (SPEC 6.7)."""
    outputs = [o for o in report.get("outputs") or [] if isinstance(o, dict)]
    worst: dict[str, tuple[str, dict, dict]] = {}
    profiles, codecs = [], []
    noise: dict | None = None
    for o in outputs:
        checks = o.get("checks") if isinstance(o.get("checks"), dict) else {}
        for cid, c in checks.items():
            if not isinstance(c, dict):
                continue
            st = _CHECK_STATUS.get(str(c.get("status")))
            if st is None:          # not_applicable
                continue
            if cid not in worst or _STATUS_RANK[st] > _STATUS_RANK[worst[cid][0]]:
                worst[cid] = (st, c, o)
        meas = o.get("measured") or {}
        profiles.append({"profile": o.get("profile"), "delivery": o.get("delivery"),
                         "status": _CHECK_STATUS.get(str(o.get("overall")), "not_run"),
                         "lufs_i": meas.get("lufs_i"), "true_peak_dbtp": meas.get("true_peak_dbtp"),
                         "note": (checks.get("render") or {}).get("reason")})
        s02 = checks.get("S-02") if isinstance(checks.get("S-02"), dict) else {}
        for codec, r in (s02.get("codecs") or {}).items():
            if isinstance(r, dict):
                codecs.append({"codec": codec, "status": _CHECK_STATUS.get(str(r.get("status")), "not_run"),
                               "true_peak_dbtp": r.get("true_peak_dbtp"),
                               "ceiling_dbtp": s02.get("codec_after_ceiling_dbtp"),
                               "note": f"{o.get('profile')} / {o.get('delivery')}"
                                       + (f": {r['reason']}" if r.get("reason") else "")})
        s08 = checks.get("S-08")
        if isinstance(s08, dict):
            st08 = _CHECK_STATUS.get(str(s08.get("status")), "not_run")
            if noise is None or _STATUS_RANK.get(st08, 1) > _STATUS_RANK.get(noise["status"], 1):
                key, delta, tol = _s08_worst_delta(s08)
                noise = {"status": st08, "metric": key, "delta_db": delta, "tolerance_db": tol,
                         "note": s08.get("reason") or (f"{o.get('profile')} / {o.get('delivery')}"
                                                       if len(outputs) > 1 else None)}
    constraints = []
    for cid in sorted(worst):
        st, c, o = worst[cid]
        limit = c.get("ceiling_dbtp", c.get("window_lufs_i", c.get("limit")))
        value = _first_measured(c)
        if cid == "S-08" and value is None and limit is None:
            _k, value, limit = _s08_worst_delta(c)
        constraints.append({"id": cid, "status": st, "value": value, "limit": limit,
                            "note": c.get("reason") or (f"{o.get('profile')} / {o.get('delivery')}"
                                                        if len(outputs) > 1 else None)})
    g = ((variant or {}).get("evaluation") or {}).get("gate") or {}
    gate = {"status": _CHECK_STATUS.get(str(g.get("status")), "not_run") if g else "not_run",
            "checks": [{"id": c.get("id"), "label": c.get("label") or c.get("id"),
                        "status": _CHECK_STATUS.get(str(c.get("status")), "not_run"), "note": c.get("reason")}
                       for c in g.get("checks") or [] if isinstance(c, dict)]}
    return {"schema_version": 1, "variant": report.get("variant"),
            "overall": _CHECK_STATUS.get(str(report.get("overall")), "not_run"),
            "constraints": constraints, "gate": gate, "profiles": profiles,
            "noise_return": noise or {"status": "not_run", "delta_db": None, "tolerance_db": None,
                                      "note": "no rendered output"},
            "codec": codecs}


@_face_safe
def verification_get(project_path: str | Path, variant: str | None = None) -> dict:
    """The last verification of a variant (reports/verify_<variant>.json) without re-running it,
    as constraint/profile/codec rows; ``stale`` when the project changed since."""
    proj = _open(project_path)
    vid = _variant_or_default(proj, variant)
    f = Path(proj.root) / "reports" / f"verify_{vid}.json"
    if not f.is_file():
        raise NotGenerated(f"variant '{vid}' has not been verified yet",
                           details={"hint": "run verify (CLI `mankomix verify`, MCP verify_run)"})
    try:
        rep = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputError(f"cannot read {f.name}: {e}") from None
    view = verification_view(rep, _find_variant(proj.data, vid))
    try:
        stale = rep.get("project_hash") != proj.content_hash()
    except Exception:
        stale = None
    return {**view, "passed": rep.get("passed"), "stale": stale, "path": proj.rel(f),
            "outputs": rep.get("outputs"), "archive": rep.get("archive")}


@_face_safe
def audio_set(project_path: str | Path, variant: str | None = None) -> dict:
    """Listening set of a variant (SPEC 15.2): before (unprocessed: the full mix, or the static
    stem sum), after (the rendered master), the cleanup delta, and the level-match gain that lowers
    the louder side (``match_gain_db`` <= 0 applied to ``match_target``). Paths are project-relative."""
    proj = _open(project_path)
    vid = _variant_or_default(proj, variant)
    after = _after_file(proj, vid)
    before, kind, _key = _before_file(proj, vid)
    fm = _mod("routes").fullmix_asset_id(proj.data)
    fm_path = Path(proj.asset_path(fm)) if fm else None
    deltas: dict[str, str] = {}
    ddir = Path(proj.root) / "renders" / "delta"
    if ddir.is_dir():
        for p in sorted(ddir.glob("*.wav")):
            deltas[p.stem] = proj.rel(p)
    if kind == "fullmix" and fm:
        delta = deltas.get(fm)
    else:
        sd = _stem_sum_delta(proj, required=False)       # one delta for the whole stem set (SPEC 15.2)
        if sd is not None:
            delta = sd["delta"]
            deltas[Path(STEM_SUM_DELTA).stem] = sd["delta"]
        else:
            delta = next(iter(deltas.values())) if len(deltas) == 1 else None
    out: dict[str, Any] = {
        "variant": vid, "before_kind": kind,
        "files": {"before": proj.rel(before) if before else None, "after": proj.rel(after) if after else None,
                  "delta": delta, "before_level_matched": None,
                  "fullmix_reference": proj.rel(fm_path) if (kind != "fullmix" and fm_path is not None
                                                             and fm_path.is_file()) else None},
        "deltas": deltas, "match_gain_db": 0.0, "match_target": "after", "measurements": {},
    }
    if before is not None:
        out["measurements"]["before"] = _level(proj, before)
    if after is not None:
        out["measurements"]["after"] = _level(proj, after)
    lb = (out["measurements"].get("before") or {}).get("lufs_i")
    la = (out["measurements"].get("after") or {}).get("lufs_i")
    if lb is not None and la is not None:
        if lb > la:
            out["match_target"], out["match_gain_db"] = "before", round(la - lb, 2)
        else:
            out["match_target"], out["match_gain_db"] = "after", round(lb - la, 2)
        out["note"] = _label2("レベルマッチ: 大きい方を下げて統合ラウドネスを揃える（R-01）",
                              "level match: the louder side is lowered to equal integrated loudness (R-01)")
    elif after is None:
        out["note"] = _label2("処理後の音声がまだない。render を実行する", "no rendered output yet: run render")
    return out


def _vector_of(proj, index: dict, key: str | None) -> dict | None:
    if not key:
        return None
    rec = index.get(key) if isinstance(index, dict) else None
    rel = rec.get("path") if isinstance(rec, dict) and rec.get("path") else f"{ANALYSIS_DIR}/{key}.json"
    try:
        stored = json.loads((Path(proj.root) / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = stored.get("vector") if isinstance(stored, dict) else None
    return v if isinstance(v, dict) else None


def _file_vector(proj, path: Path) -> dict:
    return _listen_cached(proj, "vector_" + proj.rel(path), _file_key(path),
                          lambda: _mod("measure.vector").measure_file(path))


def _st_series(proj, path: Path, hop_s: float = 1.0) -> list:
    def compute():
        x, sr = _mod("audio_io").read(path)
        ld = _mod("measure.loudness")
        st = ld.short_term(x, sr)
        step = max(1, int(round(hop_s / ld.HOP_S)))
        return [round(float(v), 2) if math.isfinite(float(v)) and float(v) > ld.ABS_GATE_LUFS else None
                for v in st[::step]]
    return _listen_cached(proj, f"series_{hop_s}_" + proj.rel(path), _file_key(path), compute)


def _g(d: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _num(v: Any, nd: int = 2) -> Any:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
        return round(float(v), nd)
    return None


def _centroid_hz(vec: dict) -> float | None:
    lt = _g(vec, "LTAS", "third_octave") or {}
    num = den = 0.0
    for c, lv in zip(lt.get("center_hz") or [], lt.get("level_db") or []):
        if isinstance(lv, (int, float)) and isinstance(c, (int, float)):
            p = 10.0 ** (lv / 10.0)
            num += c * p
            den += p
    return round(num / den, 1) if den > 0 else None


_METRIC_ROWS = (
    ("integrated_lufs", ("P-03", "integrated_lufs"), "LUFS", "Integrated loudness", "in_range"),
    ("true_peak_dbtp", ("P-14", "true_peak_dbtp"), "dBTP", "True peak", "lower"),
    ("lra_lu", ("P-03", "lra_lu"), "LU", "Loudness range", "in_range"),
    ("plr_db", ("P-03", "plr_db"), "dB", "Peak to loudness ratio", "higher"),
    ("psr_db", ("P-03", "psr_db"), "dB", "Peak to short-term ratio", "higher"),
    ("correlation", ("P-05", "full_band", "correlation"), "", "Stereo correlation", "higher"),
    ("mono_loss_db", ("P-06", "full_band", "mono_loss_db"), "dB", "Mono fold-down loss", "lower"),
)


@_face_safe
def analysis_view(project_path: str | Path, variant: str | None = None) -> dict:
    """Cached measurements arranged for display (SPEC 11.2 analysis and mix map): short-term
    loudness over time, LTAS, band correlation, stem placement, ingest diagnostics and key metrics,
    before (unprocessed) and after (the variant's rendered master, when there is one). Needs
    ``analyze`` first; derived data is cached under cache/listen/, project.json is not changed."""
    proj = _open(project_path)
    data = proj.data
    vid = None if (variant is None and not _variant_ids(data)) else _variant_or_default(proj, variant)
    index = data.get("analysis_index") if isinstance(data.get("analysis_index"), dict) else {}
    vb = None
    before, kind, key = None, "none", None
    if index:
        before, kind, key = _before_file(proj, vid)
        vb = _vector_of(proj, index, key)
    if before is None or vb is None:
        raise NotGenerated("no analysis yet: run analyze first",
                           details={"hint": "CLI `mankomix analyze`, MCP analyze_run"})
    after = _after_file(proj, vid)
    va = _file_vector(proj, after) if after is not None else None

    lt_b = _g(vb, "LTAS", "third_octave") or {}
    lt_a = _g(va, "LTAS", "third_octave") or {}
    a_map = {round(c, 1): lv for c, lv in zip(lt_a.get("center_hz") or [], lt_a.get("level_db") or [])}
    freqs = [round(c, 1) for c in lt_b.get("center_hz") or []]
    bands_b = _g(vb, "P-05", "bands") or {}
    bands_a = _g(va, "P-05", "bands") or {}
    band_rows = []
    for bid, b in bands_b.items():
        rng = (b or {}).get("range_hz") or [None, None]
        band_rows.append({"id": bid, "lo_hz": rng[0], "hi_hz": rng[1],
                          "before": _num((b or {}).get("correlation"), 3),
                          "after": _num((bands_a.get(bid) or {}).get("correlation"), 3) if va else None})

    stems = []
    depth_order = [t for t in (_g(data, "mix", "declared_depth_order") or []) if isinstance(t, str)]
    for t in data.get("tracks", []) or []:
        if not isinstance(t, dict) or t.get("role") == "fullmix" or t.get("muted"):
            continue
        aids = [c.get("asset") for c in t.get("clips") or [] if isinstance(c, dict) and c.get("asset")]
        vec = _vector_of(proj, index, aids[0]) if aids else None
        if vec is None:
            continue
        lufs = _num(_g(vec, "P-03", "integrated_lufs"))
        tid = t.get("id")
        declared = tid in depth_order
        depth = (1.0 - depth_order.index(tid) / max(1, len(depth_order))) if declared else 0.5
        stems.append({"track": tid, "role": t.get("role"), "centroid_hz": _centroid_hz(vec),
                      "depth": round(depth, 3), "depth_source": "declared" if declared else "default",
                      "level_db": None if lufs is None else round(lufs + float(t.get("gain_db") or 0.0), 2),
                      "pan": _num(_g(t, "pan", "position"), 3) or 0.0})

    level_map = {"error": "fail", "warning": "warning", "info": "ok"}
    diagnostics = [{"id": c.get("check") or c.get("id"), "metric": c.get("check"),
                    "label": c.get("message") or c.get("check"), "value": None,
                    "status": level_map.get(str(c.get("level")), "ok"), "note": c.get("asset")}
                   for c in (_g(data, "ingest", "checks") or []) if isinstance(c, dict)]

    metrics = [{"id": mid, "label": label, "unit": unit, "better": better,
                "before": _num(_g(vb, *path), 3), "after": _num(_g(va, *path), 3) if va else None}
               for mid, path, unit, label, better in _METRIC_ROWS]

    def pair(*path):
        return {"before": _num(_g(vb, *path)), "after": _num(_g(va, *path)) if va else None}

    return {
        "schema_version": 1, "variant": vid, "before_kind": kind,
        "files": {"before": proj.rel(before), "after": proj.rel(after) if after else None},
        "loudness": {"hop_s": 1.0, "before": _st_series(proj, before),
                     "after": _st_series(proj, after) if after is not None else None,
                     "integrated_lufs": pair("P-03", "integrated_lufs"),
                     "true_peak_dbtp": pair("P-14", "true_peak_dbtp"), "lra_lu": pair("P-03", "lra_lu")},
        "ltas": {"freqs_hz": freqs, "before": [_num(v) for v in lt_b.get("level_db") or []],
                 "after": [_num(a_map.get(f)) for f in freqs] if va else None, "reference": None},
        "band_correlation": {"bands": band_rows},
        "stems": stems,
        "masking": [],
        "diagnostics": diagnostics,
        "metrics": metrics,
        "notes": ["metrics are not level-matched; masking pairs need the mix-stage analysis (M4)"],
    }


__all__ += [
    "model_list", "model_show", "model_pull", "model_register", "model_verify", "model_remove",
    "separate", "separation_list", "delivery_list", "variant_list", "proposal_list", "proposal_get",
    "proposal_view", "verification_view", "verification_get", "audio_set", "analysis_view", "NotGenerated",
]
