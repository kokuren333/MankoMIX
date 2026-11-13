"""Data loaders (objectives/, profiles/, knowledge/, registry/) and local settings.

Data files are read from ``mankomix.repo_data_root()``, validated once and
cached. Getters return deep copies, so callers may mutate what they get.

Local settings (linked-asset locations, BYOW registrations, ...) live outside
the repository and outside every project: in ``$MANKOMIX_HOME`` if set, else
``~/.mankomix`` (SPEC 9.1, 12.4).
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from mankomix import repo_data_root

from . import schema as _schema
from .errors import EnvironmentProblem, InputError, ValidationError

_lock = threading.Lock()
_cache: dict[str, Any] = {}

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def clear_cache() -> None:
    """Forget cached data files (and compiled schemas)."""
    with _lock:
        _cache.clear()
    _schema.load_schema.cache_clear()
    _schema._validator.cache_clear()


def _read_json(rel: str) -> Any:
    path = repo_data_root() / rel
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise EnvironmentProblem(f"data file missing: {rel}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"data file is not valid JSON: {rel}: {exc}") from exc


def _cached(key: str, loader) -> Any:
    with _lock:
        if key in _cache:
            return _cache[key]
    value = loader()
    with _lock:
        _cache.setdefault(key, value)
        return _cache[key]


def _validated(rel: str, check) -> Any:
    def load():
        doc = _read_json(rel)
        _schema.raise_on_errors(check(doc), rel)
        return doc
    return _cached(rel, load)


def _unknown(kind: str, ident: Any, valid: list[str]) -> InputError:
    return InputError(f"unknown {kind} '{ident}'; valid: {', '.join(valid)}",
                      details={"kind": kind, "id": ident, "valid": valid})


# --- media profiles / delivery formats ---------------------------------------

def load_deliveries() -> dict:
    return copy.deepcopy(_validated("profiles/delivery_formats.json", _schema.check_deliveries))


def load_profiles() -> dict:
    deliveries = _validated("profiles/delivery_formats.json", _schema.check_deliveries)
    doc = _validated("profiles/media_profiles.json", lambda d: _schema.check_profiles(d, deliveries))
    return copy.deepcopy(doc)


def profile_ids(*, include_aliases: bool = False) -> list[str]:
    ids = []
    for p in load_profiles()["profiles"]:
        ids.append(p["id"])
        if include_aliases:
            ids.extend(p.get("aliases") or [])
    return ids


def resolve_profile_id(profile_id: str) -> str:
    """Canonical profile id for an id or alias (e.g. 'mv' -> 'youtube')."""
    for p in load_profiles()["profiles"]:
        if profile_id == p["id"] or profile_id in (p.get("aliases") or []):
            return p["id"]
    raise _unknown("media profile", profile_id, profile_ids(include_aliases=True))


def get_profile(profile_id: str) -> dict:
    canonical = resolve_profile_id(profile_id)
    for p in load_profiles()["profiles"]:
        if p["id"] == canonical:
            return p
    raise _unknown("media profile", profile_id, profile_ids(include_aliases=True))  # pragma: no cover


def delivery_ids() -> list[str]:
    return [f["id"] for f in load_deliveries()["formats"]]


def get_delivery(delivery_id: str) -> dict:
    for f in load_deliveries()["formats"]:
        if f["id"] == delivery_id:
            return f
    raise _unknown("delivery format", delivery_id, delivery_ids())


# --- objectives ---------------------------------------------------------------

def load_objectives() -> dict:
    return copy.deepcopy(_validated("objectives/catalog.json", _schema.check_objectives))


def objective_ids() -> list[str]:
    return [o["id"] for o in load_objectives()["objectives"]]


def get_objective(objective_id: str) -> dict:
    for o in load_objectives()["objectives"]:
        if o["id"] == objective_id:
            return o
    raise _unknown("objective", objective_id, objective_ids())


# --- knowledge ----------------------------------------------------------------

def load_knowledge(name: str) -> dict:
    """Generic loader for knowledge/<name>.json."""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise InputError(f"invalid knowledge name '{name}'")
    rel = f"knowledge/{name}.json"
    if not (repo_data_root() / rel).is_file():
        valid = sorted(p.stem for p in (repo_data_root() / "knowledge").glob("*.json"))
        raise _unknown("knowledge file", name, valid)
    return copy.deepcopy(_cached(rel, lambda: _read_json(rel)))


def load_genre_priors() -> dict:
    return load_knowledge("genre_priors")


def genre_ids() -> list[str]:
    return [g["id"] for g in load_genre_priors().get("genres", [])]


def get_genre_prior(genre_id: str) -> dict:
    for g in load_genre_priors().get("genres", []):
        if g["id"] == genre_id:
            return g
    raise _unknown("genre", genre_id, genre_ids())


def load_vocabulary() -> dict:
    return load_knowledge("vocabulary")


# --- model registry -------------------------------------------------------------

def load_registry() -> dict:
    return copy.deepcopy(_validated("registry/models.json", _schema.check_registry))


# --- local settings (outside the repository and the project) -------------------

def settings_dir() -> Path:
    home = os.environ.get("MANKOMIX_HOME")
    if home:
        return Path(home)
    return Path.home() / ".mankomix"


def settings_path() -> Path:
    return settings_dir() / "settings.json"


def load_settings() -> dict:
    path = settings_path()
    if not path.is_file():
        return {"schema_version": 1}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise EnvironmentProblem("local settings file is unreadable", details={"error": str(exc)}) from exc
    if not isinstance(data, dict):
        raise EnvironmentProblem("local settings file is not a JSON object")
    return data


def save_settings(settings: dict) -> None:
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        text = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError as exc:
        raise EnvironmentProblem("cannot write local settings", details={"error": str(exc)}) from exc


def _check_sha(sha: str) -> None:
    if not isinstance(sha, str) or not _SHA_RE.match(sha):
        raise InputError("sha256 must be 64 lowercase hex characters")


def set_linked_location(sha: str, path: str | os.PathLike[str]) -> None:
    """Remember where the file of a linked asset (identified by sha256) lives."""
    _check_sha(sha)
    settings = load_settings()
    settings.setdefault("linked_assets", {})[sha] = str(Path(path).resolve())
    save_settings(settings)


def get_linked_location(sha: str) -> Path | None:
    _check_sha(sha)
    loc = load_settings().get("linked_assets", {}).get(sha)
    return Path(loc) if loc else None


def remove_linked_location(sha: str) -> None:
    _check_sha(sha)
    settings = load_settings()
    if settings.get("linked_assets", {}).pop(sha, None) is not None:
        save_settings(settings)
