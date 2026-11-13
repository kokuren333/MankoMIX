"""Model registry: official catalogue, BYOW registrations, weight cache (SPEC 12, S-10).

- The official catalogue is ``registry/models.json`` (validated by the schema
  and by the catalogue rules below). Only ``verified`` entries can be pulled
  without an explicit ``allow_candidate`` flag.
- BYOW ("bring your own weights") registrations live in the user's local
  settings (``settings_dir()/byow.json``), never in a project. Registering
  hashes the user's file; it is never copied, downloaded or redistributed.
- Downloaded official weights live in ``settings_dir()/models/<id>/``. Every
  download is checked against the pinned sha256 before it is kept.
- Nothing here downloads anything that is not pinned in the catalogue, and
  the separation path (``resolve_for_run``) never downloads at all.

All public functions return JSON-safe dicts without absolute paths.
"""

from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, BinaryIO

from . import config
from .errors import EnvironmentProblem, InputError, ValidationError
from .hashing import canonical_hash, sha256_file
from . import schema as _schema
from .schema import issue, raise_on_errors

BYOW_FILE = "byow.json"
MODELS_SUBDIR = "models"
VERIFY_CACHE = ".verify_cache.json"
PULLABLE_STATUS = {"verified"}
CANDIDATE_STATUS = {"candidate", "draft"}
PRIMARY_EVIDENCE = {"model_card", "license_file", "author_statement", "distribution_metadata", "repository_metadata"}
UNKNOWN_LICENSES = {"unknown"}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_CHUNK = 1 << 20
USER_AGENT = "mankomix-model-registry"
DOWNLOAD_TIMEOUT_S = 60

BYOW_NOTICE = ("BYOW weights are registered by the user. MankoMIX does not download, copy or redistribute "
               "them; checking their license is the user's responsibility (SPEC 12.4).")


# --- locations ---------------------------------------------------------------------

def models_dir() -> Path:
    return config.settings_dir() / MODELS_SUBDIR


def byow_path() -> Path:
    return config.settings_dir() / BYOW_FILE


def _today() -> str:
    return _dt.date.today().isoformat()


# --- catalogue validation -----------------------------------------------------------------

def catalog_issues(doc: Any) -> list[dict]:
    """Schema checks plus the rules of the official catalogue (SPEC 12.2)."""
    out = _schema.check_registry(doc)
    if not isinstance(doc, dict) or not isinstance(doc.get("models"), list):
        return out
    ids = set()
    for i, m in enumerate(doc["models"]):
        if not isinstance(m, dict):
            continue
        ids.add(m.get("id"))
        base = ["models", i]
        if m.get("tier") != "official":
            out.append(issue("error", base + ["tier"], "the official catalogue may only hold tier 'official' "
                                                      "(BYOW registrations live in local settings)"))
        lic = m.get("license") if isinstance(m.get("license"), dict) else {}
        if m.get("status") == "verified":
            kinds = {e.get("kind") for e in lic.get("evidence") or [] if isinstance(e, dict)}
            if not kinds & PRIMARY_EVIDENCE:
                out.append(issue("error", base + ["license", "evidence"],
                                 "a verified entry needs at least one primary evidence item "
                                 f"(kind one of: {', '.join(sorted(PRIMARY_EVIDENCE))})"))
            files = _declared_files(m)
            if not files:
                out.append(issue("error", base + ["weights"], "a verified entry must pin its weight files"))
            names = [f.get("name") for f in files]
            if len(set(names)) != len(names) or any(not n for n in names):
                out.append(issue("error", base + ["weights"], "weight file names must be present and unique"))
            if not isinstance(m.get("runtime"), dict) or not m["runtime"].get("backend"):
                out.append(issue("error", base + ["runtime"], "a verified entry needs runtime.backend"))
        if m.get("status") in CANDIDATE_STATUS and not m.get("status_reason"):
            out.append(issue("warning", base + ["status"], "candidate entry without status_reason"))
    for mode, mid in (doc.get("defaults") or {}).items():
        if mid is None:
            continue
        match = [m for m in doc["models"] if isinstance(m, dict) and m.get("id") == mid]
        if not match:
            out.append(issue("error", ["defaults", mode], f"unknown model '{mid}'"))
        elif match[0].get("status") != "verified":
            out.append(issue("error", ["defaults", mode], f"default model '{mid}' is not verified"))
    return out


def byow_issues(doc: Any) -> list[dict]:
    out = _schema.check_registry(doc)
    if not isinstance(doc, dict) or not isinstance(doc.get("models"), list):
        return out
    for i, m in enumerate(doc["models"]):
        if not isinstance(m, dict):
            continue
        if m.get("tier") != "byow":
            out.append(issue("error", ["models", i, "tier"], "BYOW registrations must have tier 'byow'"))
        w = m.get("weights") if isinstance(m.get("weights"), dict) else {}
        if not isinstance(w.get("sha256"), str) or not w.get("path"):
            out.append(issue("error", ["models", i, "weights"], "BYOW registration needs weights.path and sha256"))
    return out


def load_catalog() -> dict:
    """The official catalogue (validated). Raises ValidationError when a rule is broken."""
    doc = config.load_registry()
    raise_on_errors(catalog_issues(doc), "registry/models.json")
    return doc


def load_byow() -> dict:
    path = byow_path()
    if not path.is_file():
        return {"schema_version": 1, "models": []}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise EnvironmentProblem("BYOW registration file is unreadable", details={"error": str(exc)}) from exc
    raise_on_errors(byow_issues(doc), "local BYOW registrations")
    return doc


def _save_byow(doc: dict) -> None:
    raise_on_errors(byow_issues(doc), "local BYOW registrations")
    path = byow_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except OSError as exc:
        raise EnvironmentProblem("cannot write BYOW registrations", details={"error": str(exc)}) from exc


# --- entries ----------------------------------------------------------------------------------

def _declared_files(entry: dict) -> list[dict]:
    """Weight files of an entry: [{name, source_url, sha256, size_bytes, role?, path?}]."""
    w = entry.get("weights") if isinstance(entry.get("weights"), dict) else {}
    if w.get("files"):
        return [dict(f) for f in w["files"] if isinstance(f, dict)]
    if entry.get("tier") == "byow" and w.get("path"):
        return [{"name": w.get("filename") or Path(w["path"]).name, "path": w["path"],
                 "sha256": w.get("sha256"), "size_bytes": w.get("size_bytes")}]
    if w.get("source_url") and w.get("sha256"):
        name = w.get("filename") or _name_from_url(w["source_url"])
        return [{"name": name, "source_url": w["source_url"], "sha256": w["sha256"],
                 "size_bytes": w.get("size_bytes")}]
    return []


def _name_from_url(url: str) -> str:
    tail = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    tail = re.sub(r"[^A-Za-z0-9_.-]", "_", tail) or "weights.bin"
    return tail


def model_sha256(entry: dict) -> str | None:
    """One sha256 identifying the weights (single file: its hash; several: hash of the name->hash map)."""
    files = _declared_files(entry)
    if not files or any(not f.get("sha256") for f in files):
        return None
    if len(files) == 1:
        return files[0]["sha256"]
    return canonical_hash({f["name"]: f["sha256"] for f in files})


def _all_entries() -> list[dict]:
    return list(load_catalog()["models"]) + list(load_byow()["models"])


def _find(model_id: str) -> dict:
    if not isinstance(model_id, str) or not model_id:
        raise InputError("model id must be a non-empty string")
    entries = _all_entries()
    for m in entries:
        if m.get("id") == model_id:
            return m
    raise InputError(f"unknown model '{model_id}'", details={"kind": "model", "id": model_id,
                                                             "valid": [m.get("id") for m in entries]})


def _local_file(entry: dict, f: dict) -> Path:
    if entry.get("tier") == "byow":
        return Path(f["path"])
    return models_dir() / entry["id"] / f["name"]


def _license_view(entry: dict) -> dict:
    lic = copy.deepcopy(entry.get("license") or {})
    return {
        "code": lic.get("code"),
        "weights": lic.get("weights"),
        "usage_restrictions": lic.get("usage_restrictions"),
        "evidence": lic.get("evidence") or [],
        "caveats": lic.get("caveats") or [],
    }


def license_record(entry: dict) -> dict:
    """Compact license record for project / render manifest / Mix Report."""
    lic = entry.get("license") or {}
    return {
        "code": lic.get("code"),
        "weights": lic.get("weights"),
        "usage_restrictions": lic.get("usage_restrictions"),
        "caveats": list(lic.get("caveats") or []),
        "evidence_urls": [e["url"] for e in lic.get("evidence") or [] if isinstance(e, dict) and e.get("url")],
    }


def _public_entry(entry: dict) -> dict:
    """Entry without local absolute paths."""
    e = copy.deepcopy(entry)
    w = e.get("weights")
    if isinstance(w, dict) and "path" in w:
        w["path"] = Path(w["path"]).name
    return e


# --- verification cache (size + mtime -> sha256), local settings only ------------------------

def _cache_path() -> Path:
    return models_dir() / VERIFY_CACHE


def _load_cache() -> dict:
    try:
        with open(_cache_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(cache, fh, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass  # the cache is an optimisation only


def _file_sha(path: Path, *, use_cache: bool) -> str:
    st = path.stat()
    key = str(path.resolve())
    cache = _load_cache()
    hit = cache.get(key)
    if use_cache and isinstance(hit, dict) and hit.get("size") == st.st_size and hit.get("mtime_ns") == st.st_mtime_ns:
        return hit["sha256"]
    sha = sha256_file(path)
    cache[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha}
    _save_cache(cache)
    return sha


def _forget_cache(paths: list[Path]) -> None:
    cache = _load_cache()
    changed = False
    for p in paths:
        try:
            key = str(p.resolve())
        except OSError:
            continue
        if cache.pop(key, None) is not None:
            changed = True
    if changed:
        _save_cache(cache)


def _check_files(entry: dict, *, use_cache: bool) -> list[dict]:
    out = []
    for f in _declared_files(entry):
        p = _local_file(entry, f)
        rec = {"name": f["name"], "expected_sha256": f.get("sha256"), "size_bytes": f.get("size_bytes")}
        if not p.is_file():
            rec.update(state="missing", ok=False)
        else:
            sha = _file_sha(p, use_cache=use_cache)
            rec.update(state="ok" if sha == f.get("sha256") else "sha256_mismatch", ok=sha == f.get("sha256"),
                       sha256=sha, size_bytes=p.stat().st_size)
        out.append(rec)
    return out


def _install_state(entry: dict) -> str:
    files = _declared_files(entry)
    if not files:
        return "not_pinned"
    present = [_local_file(entry, f).is_file() for f in files]
    if all(present):
        return "registered" if entry.get("tier") == "byow" else "installed"
    if any(present):
        return "partial"
    return "file_missing" if entry.get("tier") == "byow" else "not_installed"


# --- public API --------------------------------------------------------------------------------------

def _summary(entry: dict, defaults: dict) -> dict:
    rt = entry.get("runtime") or {}
    lic = entry.get("license") or {}
    return {
        "id": entry["id"],
        "tier": entry.get("tier"),
        "status": entry.get("status"),
        "task": entry.get("task"),
        "stems": entry.get("stems") or [],
        "architecture": entry.get("architecture"),
        "backend": rt.get("backend"),
        "cpu_ok": rt.get("cpu_ok"),
        "light": rt.get("light"),
        "min_vram_gb": rt.get("min_vram_gb"),
        "license_weights": lic.get("weights"),
        "usage_restrictions": lic.get("usage_restrictions"),
        "size_bytes": sum(int(f.get("size_bytes") or 0) for f in _declared_files(entry)) or None,
        "state": _install_state(entry),
        "default_for": sorted(k for k, v in defaults.items() if v == entry["id"]),
    }


def model_list() -> dict:
    cat = load_catalog()
    byow = load_byow()
    defaults = cat.get("defaults") or {}
    models = [_summary(m, defaults) for m in cat["models"]] + [_summary(m, {}) for m in byow["models"]]
    return {
        "models": models,
        "defaults": defaults,
        "excluded_from_standard_route": cat.get("excluded_from_standard_route") or [],
        "weights_location": f"<MANKOMIX_HOME>/{MODELS_SUBDIR}",
        "byow_notice": BYOW_NOTICE,
    }


def model_show(model_id: str) -> dict:
    entry = _find(model_id)
    defaults = load_catalog().get("defaults") or {}
    out = _summary(entry, defaults)
    out.update({
        "entry": _public_entry(entry),
        "license": _license_view(entry),
        "attribution": entry.get("attribution"),
        "status_reason": entry.get("status_reason"),
        "model_sha256": model_sha256(entry),
        "files": [{"name": f["name"], "sha256": f.get("sha256"), "size_bytes": f.get("size_bytes"),
                   "source_url": f.get("source_url"), "present": _local_file(entry, f).is_file()}
                  for f in _declared_files(entry)],
    })
    if entry.get("tier") == "byow":
        out["byow_notice"] = BYOW_NOTICE
    return out


def _open_url(url: str) -> BinaryIO:
    """Open a download stream. Module-level so tests can replace it."""
    if not url.lower().startswith(("https://", "http://")):
        raise InputError("only http(s) download URLs are allowed")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        return urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S)  # noqa: S310 - pinned catalogue URL
    except OSError as exc:
        raise EnvironmentProblem(f"download failed: {exc}", details={"url": url}) from exc


def _download(url: str, dest: Path, expected_sha: str, expected_size: int | None) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    size = 0
    try:
        with _open_url(url) as src, open(part, "wb") as out:
            while True:
                block = src.read(_CHUNK)
                if not block:
                    break
                h.update(block)
                size += len(block)
                out.write(block)
    except (OSError, EnvironmentProblem) as exc:
        part.unlink(missing_ok=True)
        if isinstance(exc, EnvironmentProblem):
            raise
        raise EnvironmentProblem(f"download failed: {exc}", details={"url": url}) from exc
    sha = h.hexdigest()
    if sha != expected_sha or (expected_size is not None and size != expected_size):
        part.unlink(missing_ok=True)
        raise ValidationError(
            f"downloaded file '{dest.name}' does not match the pinned sha256; it was discarded",
            details={"name": dest.name, "expected_sha256": expected_sha, "sha256": sha,
                     "expected_size": expected_size, "size": size, "url": url})
    os.replace(part, dest)
    _forget_cache([dest])
    return {"sha256": sha, "size_bytes": size}


def _check_pullable(entry: dict, allow_candidate: bool) -> list[str]:
    warnings: list[str] = []
    if entry.get("tier") == "byow":
        raise InputError(f"'{entry['id']}' is a BYOW registration; BYOW weights are never downloaded",
                         details={"id": entry["id"]})
    lic = entry.get("license") or {}
    if lic.get("usage_restrictions") != "none":
        raise InputError(f"'{entry['id']}' has usage restrictions and cannot be pulled", details={"id": entry["id"]})
    status = entry.get("status")
    if status in PULLABLE_STATUS:
        return warnings
    if status in CANDIDATE_STATUS and allow_candidate:
        warnings.append(f"'{entry['id']}' is a {status} entry (license evidence not fully verified): "
                        f"{entry.get('status_reason') or 'see registry'}")
        return warnings
    raise InputError(f"'{entry['id']}' has status '{status}' and is not pulled"
                     + ("; pass allow_candidate to pull a candidate" if status in CANDIDATE_STATUS else ""),
                     details={"id": entry["id"], "status": status, "status_reason": entry.get("status_reason")})


def model_pull(model_id: str, *, allow_candidate: bool = False, force: bool = False) -> dict:
    """Download the weights of a catalogue entry into the local cache and verify them."""
    cat = load_catalog()
    entry = next((m for m in cat["models"] if m.get("id") == model_id), None)
    if entry is None:
        byow = next((m for m in load_byow()["models"] if m.get("id") == model_id), None)
        if byow is not None:
            _check_pullable(byow, allow_candidate)
        raise InputError(f"unknown model '{model_id}'; only catalogue entries can be pulled",
                         details={"kind": "model", "id": model_id, "valid": [m["id"] for m in cat["models"]]})
    warnings = _check_pullable(entry, allow_candidate)
    files = _declared_files(entry)
    if not files:
        raise InputError(f"'{model_id}' has no pinned download (source_url + sha256)", details={"id": model_id})
    results = []
    for f in files:
        dest = _local_file(entry, f)
        if dest.is_file() and not force:
            if _file_sha(dest, use_cache=True) == f["sha256"]:
                results.append({"name": f["name"], "action": "present", "sha256": f["sha256"],
                                "size_bytes": dest.stat().st_size})
                continue
            warnings.append(f"'{f['name']}' was present but did not match; downloading again")
        got = _download(f["source_url"], dest, f["sha256"], f.get("size_bytes"))
        results.append({"name": f["name"], "action": "downloaded", **got})
    return {
        "id": model_id,
        "status": entry.get("status"),
        "state": _install_state(entry),
        "files": results,
        "model_sha256": model_sha256(entry),
        "license": _license_view(entry),
        "attribution": entry.get("attribution"),
        "caveats": (entry.get("license") or {}).get("caveats") or [],
        "notice": "Weights were downloaded from the official distribution point and verified by sha256. "
                  "Show the attribution when you publish results made with this model.",
        "warnings": warnings,
    }


def model_register(path: str | os.PathLike[str], *, id: str, license_weights: str,
                   license_code: str | None = None, usage_restrictions: str = "unknown",
                   evidence_url: str | None = None, task: str = "separation",
                   architecture: str | None = None, stems: list[str] | None = None,
                   runtime: dict | None = None, attribution: str = "", note: str = "",
                   replace: bool = False) -> dict:
    """Register user-supplied weights (BYOW). The file is hashed, never copied."""
    p = Path(path)
    if not p.is_file():
        raise InputError(f"weights file not found: {p.name}")
    if not isinstance(id, str) or not _ID_RE.match(id):
        raise InputError("model id must match ^[a-z0-9][a-z0-9_.-]*$")
    if not isinstance(license_weights, str) or not license_weights.strip():
        raise InputError("license_weights is required (use 'unknown' if you do not know it)")
    license_weights = license_weights.strip()
    if any(m.get("id") == id for m in load_catalog()["models"]):
        raise InputError(f"'{id}' is an official catalogue id; choose another id for a BYOW registration")
    if evidence_url is not None and not re.match(r"^https?://\S+$", evidence_url):
        raise InputError("evidence_url must be an http(s) URL")
    if stems is not None and (not isinstance(stems, list) or not all(isinstance(s, str) and s for s in stems)):
        raise InputError("stems must be a list of names")
    if runtime is not None and not isinstance(runtime, dict):
        raise InputError("runtime must be a JSON object")
    doc = load_byow()
    existing = [m for m in doc["models"] if m.get("id") == id]
    if existing and not replace:
        raise InputError(f"a BYOW model '{id}' is already registered (pass replace to overwrite)")

    warnings = []
    if license_weights.lower() in UNKNOWN_LICENSES:
        warnings.append("weights license is 'unknown'; this is recorded in every project and Mix Report "
                        "that uses the model, and the user is responsible for the license")
    if usage_restrictions.strip().lower() not in ("none",):
        warnings.append(f"usage restrictions: '{usage_restrictions}'. BYOW models are never part of the "
                        "official catalogue")

    evidence = [{"kind": "user_declaration", "checked_on": _today(),
                 "note": note or "declared by the user at registration"}]
    if evidence_url:
        evidence.insert(0, {"url": evidence_url, "checked_on": _today(), "kind": "user_declaration",
                            "note": "URL given by the user"})
    st = p.stat()
    sha = sha256_file(p)
    entry = {
        "id": id,
        "task": task,
        "stems": list(stems or []),
        "architecture": architecture or "unknown",
        "runtime": dict(runtime or {}),
        "weights": {"filename": p.name, "path": str(p.resolve()), "sha256": sha, "size_bytes": st.st_size},
        "license": {
            "code": license_code,
            "weights": license_weights,
            "usage_restrictions": usage_restrictions.strip() or "unknown",
            "evidence": evidence,
            "caveats": ["BYOW: license declared by the user; not checked by MankoMIX."],
        },
        "attribution": attribution,
        "tier": "byow",
        "status": "registered",
        "registered_on": _today(),
    }
    doc["models"] = [m for m in doc["models"] if m.get("id") != id] + [entry]
    _save_byow(doc)
    cache = _load_cache()
    cache[str(p.resolve())] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha}
    _save_cache(cache)
    return {"id": id, "tier": "byow", "status": "registered", "file": p.name, "sha256": sha,
            "size_bytes": st.st_size, "license": _license_view(entry), "warnings": warnings,
            "replaced": bool(existing), "notice": BYOW_NOTICE}


def model_verify(model_id: str) -> dict:
    """Re-hash the local weight files of a model (no cache) and compare with the pinned hashes."""
    entry = _find(model_id)
    files = _check_files(entry, use_cache=False)
    ok = bool(files) and all(f["ok"] for f in files)
    return {"id": model_id, "tier": entry.get("tier"), "ok": ok, "state": _install_state(entry),
            "files": files, "model_sha256": model_sha256(entry)}


def model_remove(model_id: str) -> dict:
    """Official: delete the downloaded weights. BYOW: forget the registration (the user's file stays)."""
    entry = _find(model_id)
    if entry.get("tier") == "byow":
        doc = load_byow()
        doc["models"] = [m for m in doc["models"] if m.get("id") != model_id]
        _save_byow(doc)
        _forget_cache([Path(entry["weights"]["path"])])
        return {"id": model_id, "tier": "byow", "removed": "registration",
                "note": "the weights file itself was not touched"}
    folder = models_dir() / model_id
    removed = []
    paths = []
    for f in _declared_files(entry):
        p = _local_file(entry, f)
        paths.append(p)
        for q in (p, p.with_name(p.name + ".part")):
            if q.is_file():
                q.unlink()
                if q == p:
                    removed.append(f["name"])
    _forget_cache(paths)
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass
    return {"id": model_id, "tier": "official", "removed": "weights", "files": removed}


# --- used by core.separation ------------------------------------------------------------------------

def default_model(mode: str) -> str | None:
    return (load_catalog().get("defaults") or {}).get(mode)


def resolve_for_run(model_id: str, *, allow_candidate: bool = False) -> dict:
    """Entry + verified local files for running a model. Never downloads (S-10)."""
    entry = _find(model_id)
    warnings: list[str] = []
    if entry.get("tier") == "official":
        _check_pullable(entry, allow_candidate)
    else:
        lw = str((entry.get("license") or {}).get("weights") or "").lower()
        if lw in UNKNOWN_LICENSES:
            warnings.append(f"BYOW model '{model_id}' has an unknown weights license (user responsibility)")
        warnings.append(f"BYOW model '{model_id}': license declared by the user, not checked by MankoMIX")
    files = _check_files(entry, use_cache=True)
    if not files:
        raise InputError(f"'{model_id}' has no weight files")
    missing = [f["name"] for f in files if f["state"] == "missing"]
    if missing:
        hint = (f"run `mankomix model pull {model_id}`" if entry.get("tier") == "official"
                else "the registered weights file is not at its registered location")
        raise EnvironmentProblem(f"weights of '{model_id}' are not available locally; {hint}",
                                 details={"id": model_id, "missing": missing})
    bad = [f["name"] for f in files if not f["ok"]]
    if bad:
        raise ValidationError(f"weights of '{model_id}' do not match their pinned sha256",
                              details={"id": model_id, "files": bad})
    paths = {f["name"]: _local_file(entry, f) for f in _declared_files(entry)}
    roles = {f["name"]: f.get("role") for f in _declared_files(entry)}
    return {"entry": copy.deepcopy(entry), "paths": paths, "roles": roles, "model_sha256": model_sha256(entry),
            "warnings": warnings}


__all__ = [
    "catalog_issues", "byow_issues", "load_catalog", "load_byow", "models_dir", "byow_path",
    "model_list", "model_show", "model_pull", "model_register", "model_verify", "model_remove",
    "model_sha256", "license_record", "default_model", "resolve_for_run", "BYOW_NOTICE",
]
