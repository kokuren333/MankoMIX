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
        issue("info", "no_gpu", "no NVIDIA GPU detected; stem separation will use CPU models (M6)")

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
        "models": {"status": "registry not implemented until M6"},
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Project lifecycle
# ---------------------------------------------------------------------------

@_face_safe
def init_project(path: str | Path, *, title: str, genre: str | None = None) -> dict:
    p = Path(path)
    if (p / "project.json").exists():
        raise InputError(f"a project already exists here: {p.name}")
    if p.exists() and not p.is_dir():
        raise InputError(f"not a folder: {p.name}")
    if not title or not str(title).strip():
        raise InputError("title must not be empty")
    proj = _mod("project").Project.create(p, title=title, genre=genre)
    if not (Path(proj.root) / "project.json").is_file():
        proj.save(actor="human", op="init", reason="create project")
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
    for s in sources:
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
def profile_list() -> dict:
    cfg = _mod("config")
    profiles = [{"id": p.get("id"), "label": _label(p)} for p in _items(cfg.load_profiles(), "profiles")]
    try:
        deliveries = [{"id": d.get("id"), "use": d.get("use")} for d in _items(cfg.load_deliveries(), "formats")]
    except MankoError:
        deliveries = []
    return {"profiles": profiles, "deliveries": deliveries}


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
def objective_list() -> dict:
    cfg = _mod("config")
    raw = cfg.load_objectives()
    items = _items(raw, "objectives")
    default = raw.get("default") if isinstance(raw, dict) else None
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


@_face_safe
def verify(project_path: str | Path, variant: str | None = None, recheck_codecs: bool = False,
           *, strict: bool = False) -> dict:
    """Verify a rendered variant. The result carries ``passed`` and ``exit_code``
    (0 pass, 1 fail/incomplete); with ``strict=True`` a non-pass raises VerifyFailed."""
    proj = _open(project_path)
    vid = _variant_or_default(proj, variant)
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
