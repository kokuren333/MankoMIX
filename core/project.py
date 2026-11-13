"""Project folder and canonical project.json (SPEC 9).

A project is a folder (``<name>.mmx/``) holding ``project.json`` (the canonical
document), ``journal.jsonl`` (append-only history) and the asset / analysis /
render / report / cache folders. Every write is validated, written atomically
(temp file + os.replace) under a folder lock, and journaled.

Concurrent writers (GUI and CLI/MCP on the same project): a writer whose copy
is stale re-applies its own changes on top of the latest project.json (three-
way merge, or the patch itself for ``apply_patch``); if that is not possible a
ValidationError is raised and nothing is written (SPEC 9.5).
"""

from __future__ import annotations

import copy
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import mankomix

from . import config, journal
from . import jsonpatch
from .errors import EnvironmentProblem, InputError, ValidationError
from .hashing import canonical_hash, sha256_bytes
from .schema import errors_only, issue, raise_on_errors, schema_issues, to_pointer

PROJECT_FILE = "project.json"
LOCK_FILE = ".mmx.lock"
SUBDIRS = ("assets", "analysis", "renders", "reports", "cache")

_PATH_KEYS = {"path", "vector", "file", "dir"}
_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home|mnt|Volumes|private|tmp|var|root)/)")


# --- defaults -------------------------------------------------------------------

def default_conform_policy() -> dict:
    return {"sample_rate": "majority", "alignment": "head", "short_assets": "pad_silence_at_render"}


def default_project_data(*, title: str, project_id: str | None = None, genre: str | None = None) -> dict:
    if project_id is None:
        project_id = "prj_" + secrets.token_hex(5)
    elif not project_id.startswith("prj_"):
        project_id = "prj_" + project_id
    return {
        "schema_version": 1,
        "id": project_id,
        "title": title,
        "genre": genre,
        "timebase": {
            "sample_rate": None,
            "bpm": None,
            "key": None,
            "length_samples": None,
            "conform_policy": default_conform_policy(),
        },
        "provenance": {
            "source": None,
            "service": None,
            "input_kind": None,
            "detected_by": None,
            "declared_by_user": False,
            "notes": "",
        },
        "assets": [],
        "fullmix_asset": None,
        "tracks": [],
        "buses": [{"id": "bus_mix", "kind": "mix", "chain": []}],
        "mix": {"pan_law_center_db": -3.0, "declared_depth_order": []},
        "objective": {
            "blend": [{"id": "comfort", "weight": 1.0}],
            "intensity": 0.5,
            "overrides": {},
            "lead_stem": None,
        },
        "references": [],
        "listening_assumption": {"system": "speakers_60deg", "level": "moderate"},
        "variants": [],
        "engine": {"min_version": mankomix.__version__},
    }


def dump_project_bytes(data: dict) -> bytes:
    """Deterministic serialization: indent 2, UTF-8, insertion order, trailing newline."""
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"project data is not serializable as JSON: {exc}") from exc
    return (text + "\n").encode("utf-8")


# --- validation -------------------------------------------------------------------

def check_relpath(value: Any) -> str | None:
    """Return a problem description if ``value`` is not a clean project-relative path."""
    if not isinstance(value, str) or not value:
        return "path must be a non-empty string"
    if "\\" in value:
        return "path must use forward slashes (no backslashes)"
    if re.match(r"^[A-Za-z]:", value):
        return "path must be relative (drive letter found)"
    if value.startswith("/"):
        return "path must be relative (leading '/')"
    if ".." in PurePosixPath(value).parts:
        return "path must not contain '..'"
    return None


def validate_project_data(data: Any, root: Path | None = None) -> list[dict]:
    """Schema + semantic checks. Returns issues ``{level, path, message}``."""
    issues = schema_issues("project", data)
    if not isinstance(data, dict):
        return issues
    flagged = {i["path"] for i in issues}
    sem: list[dict] = []
    _check_paths(data, [], sem)
    sem = [i for i in sem if i["path"] not in flagged]
    _check_ids_and_refs(data, sem)
    _check_catalog_refs(data, sem)
    if root is not None:
        _check_files(data, root, sem)
    return issues + sem


def _check_paths(node: Any, path: list, out: list[dict]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and (k in _PATH_KEYS or k.endswith("_path")):
                problem = check_relpath(v)
                if problem:
                    out.append(issue("error", path + [k], problem))
                    continue
            _check_paths(v, path + [k], out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _check_paths(v, path + [i], out)
    elif isinstance(node, str) and _ABS_RE.match(node):
        out.append(issue("error", path, "absolute path found; the project must only contain relative paths"))


def _items(data: dict, key: str) -> list[tuple[int, dict]]:
    v = data.get(key)
    if not isinstance(v, list):
        return []
    return [(i, x) for i, x in enumerate(v) if isinstance(x, dict)]


def _check_ids_and_refs(data: dict, out: list[dict]) -> None:
    seen: dict[str, str] = {}

    def claim(ident: Any, ptr: list) -> None:
        if not isinstance(ident, str):
            return
        p = to_pointer(ptr)
        if ident in seen:
            out.append(issue("error", p, f"duplicate id '{ident}' (also at {seen[ident]})"))
        else:
            seen[ident] = p

    asset_ids, track_ids, bus_ids = set(), set(), set()
    for i, a in _items(data, "assets"):
        claim(a.get("id"), ["assets", i, "id"])
        asset_ids.add(a.get("id"))
    for i, t in _items(data, "tracks"):
        claim(t.get("id"), ["tracks", i, "id"])
        track_ids.add(t.get("id"))
        for j, c in enumerate(t.get("clips") or []):
            if isinstance(c, dict):
                claim(c.get("id"), ["tracks", i, "clips", j, "id"])
        for j, p in enumerate(t.get("chain") or []):
            if isinstance(p, dict):
                claim(p.get("id"), ["tracks", i, "chain", j, "id"])
    for i, b in _items(data, "buses"):
        claim(b.get("id"), ["buses", i, "id"])
        bus_ids.add(b.get("id"))
        for j, p in enumerate(b.get("chain") or []):
            if isinstance(p, dict):
                claim(p.get("id"), ["buses", i, "chain", j, "id"])
    for key in ("references", "variants", "sections"):
        for i, x in _items(data, key):
            claim(x.get("id"), [key, i, "id"])
    for i, v in _items(data, "variants"):
        local: set[str] = set()
        for j, p in enumerate(((v.get("master") or {}).get("chain")) or []):
            if isinstance(p, dict) and isinstance(p.get("id"), str):
                if p["id"] in local:
                    out.append(issue("error", ["variants", i, "master", "chain", j, "id"],
                                     f"duplicate processor id '{p['id']}'"))
                local.add(p["id"])

    # references between objects
    for i, t in _items(data, "tracks"):
        for j, c in enumerate(t.get("clips") or []):
            if isinstance(c, dict) and c.get("asset") not in asset_ids:
                out.append(issue("error", ["tracks", i, "clips", j, "asset"], f"unknown asset '{c.get('asset')}'"))
        if "output" in t and t["output"] not in bus_ids:
            out.append(issue("error", ["tracks", i, "output"], f"unknown bus '{t['output']}'"))
        for j, s in enumerate(t.get("sends") or []):
            if isinstance(s, dict) and s.get("bus") not in bus_ids:
                out.append(issue("error", ["tracks", i, "sends", j, "bus"], f"unknown bus '{s.get('bus')}'"))

    mix_buses = [i for i, b in _items(data, "buses") if b.get("kind") == "mix"]
    if len(mix_buses) != 1:
        out.append(issue("error", ["buses"], f"exactly one bus of kind 'mix' is required (found {len(mix_buses)})"))
    outputs: dict[str, str] = {}
    for i, b in _items(data, "buses"):
        if "output" in b:
            if b["output"] not in bus_ids:
                out.append(issue("error", ["buses", i, "output"], f"unknown bus '{b['output']}'"))
            elif b["output"] == b.get("id"):
                out.append(issue("error", ["buses", i, "output"], "a bus cannot output to itself"))
            else:
                outputs[b.get("id")] = b["output"]
        if b.get("kind") == "mix" and "output" in b:
            out.append(issue("error", ["buses", i, "output"], "the mix bus is the final bus and has no output"))
    for start in outputs:
        cur, visited = start, set()
        while cur in outputs:
            if cur in visited:
                out.append(issue("error", ["buses"], f"bus routing cycle involving '{start}'"))
                break
            visited.add(cur)
            cur = outputs[cur]

    fm = data.get("fullmix_asset")
    if fm is not None and fm not in asset_ids:
        out.append(issue("error", ["fullmix_asset"], f"unknown asset '{fm}'"))

    mix = data.get("mix")
    if isinstance(mix, dict):
        for j, tid in enumerate(mix.get("declared_depth_order") or []):
            if tid not in track_ids:
                out.append(issue("error", ["mix", "declared_depth_order", j], f"unknown track '{tid}'"))

    roles = {t.get("role") for _, t in _items(data, "tracks")}
    obj = data.get("objective")
    if isinstance(obj, dict):
        lead = obj.get("lead_stem")
        if lead is not None and lead not in track_ids and lead not in roles:
            out.append(issue("warning", ["objective", "lead_stem"],
                             f"lead_stem '{lead}' matches no track id or track role"))

    shas: dict[str, int] = {}
    for i, a in _items(data, "assets"):
        sha = a.get("sha256")
        if isinstance(sha, str):
            if sha in shas:
                out.append(issue("warning", ["assets", i, "sha256"],
                                 f"same content as assets[{shas[sha]}] (duplicate file)"))
            else:
                shas[sha] = i


def _check_objective_spec(obj: Any, base: list, out: list[dict], catalog: dict) -> None:
    if not isinstance(obj, dict):
        return
    seen = set()
    for j, item in enumerate(obj.get("blend") or []):
        if not isinstance(item, dict):
            continue
        oid = item.get("id")
        if oid not in catalog:
            out.append(issue("error", base + ["blend", j, "id"],
                             f"unknown objective '{oid}'; valid: {', '.join(catalog)}"))
        elif catalog[oid].get("kind") == "gate":
            out.append(issue("error", base + ["blend", j, "id"],
                             f"'{oid}' is a gate (pass/fail, always applied) and cannot be blended"))
        if oid in seen:
            out.append(issue("error", base + ["blend", j, "id"], f"objective '{oid}' appears twice in blend"))
        seen.add(oid)
        w = item.get("weight")
        if isinstance(w, (int, float)) and not isinstance(w, bool) and w <= 0:
            out.append(issue("error", base + ["blend", j, "weight"], "blend weight must be > 0"))
    inten = obj.get("intensity")
    if isinstance(inten, (int, float)) and not isinstance(inten, bool) and not (0.0 <= inten <= 1.0):
        out.append(issue("error", base + ["intensity"], "intensity must be within [0, 1]"))
    for k in (obj.get("overrides") or {}):
        if k not in catalog:
            out.append(issue("error", base + ["overrides", k], f"overrides for unknown objective '{k}'"))


def _check_catalog_refs(data: dict, out: list[dict]) -> None:
    catalog = {o["id"]: o for o in config.load_objectives()["objectives"]}
    _check_objective_spec(data.get("objective"), ["objective"], out, catalog)

    genre = data.get("genre")
    if isinstance(genre, str):
        valid = config.genre_ids()
        if genre not in valid:
            out.append(issue("error", ["genre"], f"unknown genre '{genre}'; valid: {', '.join(valid)}"))

    profiles = set(config.profile_ids(include_aliases=True))
    deliveries = set(config.delivery_ids())
    for i, v in _items(data, "variants"):
        _check_objective_spec(v.get("objective"), ["variants", i, "objective"], out, catalog)
        for j, o in enumerate(v.get("outputs") or []):
            if not isinstance(o, dict):
                continue
            if "profile" in o and o["profile"] not in profiles:
                out.append(issue("error", ["variants", i, "outputs", j, "profile"],
                                 f"unknown media profile '{o['profile']}'"))
            if "delivery" in o and o["delivery"] not in deliveries:
                out.append(issue("error", ["variants", i, "outputs", j, "delivery"],
                                 f"unknown delivery format '{o['delivery']}'"))


def _check_files(data: dict, root: Path, out: list[dict]) -> None:
    for i, a in _items(data, "assets"):
        if a.get("linked") or not isinstance(a.get("path"), str) or check_relpath(a["path"]):
            continue
        if not (root / a["path"]).is_file():
            out.append(issue("warning", ["assets", i, "path"], "asset file is missing from the project folder"))


# --- file helpers ---------------------------------------------------------------------

class _FolderLock:
    """Cross-process lock: a lock file created with O_EXCL inside the project folder."""

    def __init__(self, root: Path, timeout: float = 15.0, stale: float = 30.0):
        self.path = root / LOCK_FILE
        self.timeout = timeout
        self.stale = stale

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()}:{threading.get_ident()}".encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    continue
            except PermissionError:
                pass  # Windows: lock file is being deleted by another process
            if time.monotonic() > deadline:
                raise EnvironmentProblem("project is locked by another writer")
            time.sleep(0.01)

    def __exit__(self, *exc):
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(100):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                # Windows: a reader may hold the target open for a moment.
                if attempt == 99:
                    raise
                time.sleep(0.02)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise EnvironmentProblem(f"cannot write {path.name}", details={"error": str(exc)}) from exc


def _read_bytes(path: Path) -> bytes | None:
    for attempt in range(50):
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.02)
    return None  # pragma: no cover


def _parse(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"project.json is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError("project.json must contain a JSON object")
    return data


# --- Project ------------------------------------------------------------------------------

class Project:
    root: Path
    data: dict

    def __init__(self, root: Path, data: dict, *, base: dict | None, disk_hash: str | None):
        self.root = Path(root)
        self.data = data
        self._base = base            # data as last read from / written to disk
        self._disk_hash = disk_hash  # sha256 of project.json bytes at that time

    # -- construction --

    @classmethod
    def create(cls, path, *, title: str, project_id: str | None = None, genre: str | None = None) -> "Project":
        root = Path(path)
        if (root / PROJECT_FILE).exists():
            raise InputError(f"a project already exists in '{root.name}'")
        if root.exists() and not root.is_dir():
            raise InputError(f"'{root.name}' exists and is not a folder")
        data = default_project_data(title=title, project_id=project_id, genre=genre)
        raise_on_errors(validate_project_data(data), "project")
        try:
            root.mkdir(parents=True, exist_ok=True)
            for sub in SUBDIRS:
                (root / sub).mkdir(exist_ok=True)
            journal.journal_path(root).touch(exist_ok=True)
        except OSError as exc:
            raise EnvironmentProblem("cannot create the project folder", details={"error": str(exc)}) from exc
        proj = cls(root, data, base=None, disk_hash=None)

        def compute(latest, _raw_hash):
            if latest is not None:
                raise InputError(f"a project already exists in '{root.name}'")
            return data

        proj._commit(compute, actor="planner", op="create", reason=f"create project '{title}'")
        return proj

    @classmethod
    def open(cls, path) -> "Project":
        p = Path(path)
        root = p.parent if (p.name == PROJECT_FILE or p.is_file()) else p
        raw = _read_bytes(root / PROJECT_FILE)
        if raw is None:
            raise InputError(f"no {PROJECT_FILE} found in '{root.name}'")
        data = _parse(raw)
        version = data.get("schema_version")
        if isinstance(version, int) and version > 1:
            raise InputError(f"project schema_version {version} is newer than this engine supports (1)")
        return cls(root, data, base=copy.deepcopy(data), disk_hash=sha256_bytes(raw))

    def reload(self) -> None:
        """Discard local changes and re-read project.json."""
        fresh = Project.open(self.root)
        self.data, self._base, self._disk_hash = fresh.data, fresh._base, fresh._disk_hash

    # -- queries --

    @property
    def project_file(self) -> Path:
        return self.root / PROJECT_FILE

    def validate(self) -> list[dict]:
        return validate_project_data(self.data, self.root)

    def content_hash(self) -> str:
        return canonical_hash(self.data)

    def changed_on_disk(self) -> bool:
        raw = _read_bytes(self.project_file)
        return (sha256_bytes(raw) if raw is not None else None) != self._disk_hash

    def asset(self, asset_id: str) -> dict:
        for a in self.data.get("assets") or []:
            if isinstance(a, dict) and a.get("id") == asset_id:
                return a
        valid = [a.get("id") for a in self.data.get("assets") or [] if isinstance(a, dict)]
        raise InputError(f"unknown asset '{asset_id}'", details={"valid": valid})

    def asset_path(self, asset_id: str) -> Path:
        a = self.asset(asset_id)
        if a.get("linked"):
            sha = a.get("sha256")
            loc = config.get_linked_location(sha) if isinstance(sha, str) else None
            if loc is None:
                raise InputError(f"linked asset '{asset_id}' has no local location registered",
                                 details={"asset": asset_id, "sha256": sha})
            if not loc.is_file():
                raise InputError(f"linked asset '{asset_id}' is not available at its registered location",
                                 details={"asset": asset_id, "sha256": sha})
            return loc
        problem = check_relpath(a.get("path"))
        if problem:
            raise InputError(f"asset '{asset_id}': {problem}")
        return self.root.joinpath(*PurePosixPath(a["path"]).parts)

    def rel(self, path) -> str:
        """Project-relative POSIX path for output. Paths outside the project become 'external/<name>'."""
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        try:
            return p.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return "external/" + p.name

    # -- mutation --

    def save(self, *, actor: str = "planner", op: str = "save", reason: str = "") -> None:
        def compute(latest, raw_hash):
            if raw_hash == self._disk_hash:
                return self.data
            if latest is None:
                raise InputError("project.json has disappeared from the project folder")
            return jsonpatch.merge3(self._base, self.data, latest)

        self._commit(compute, actor=actor, op=op, reason=reason)

    def apply_patch(self, ops: list[dict], *, actor: str, reason: str = "", op: str = "patch") -> None:
        if not isinstance(ops, list):
            raise ValidationError("patch must be a list of operations")
        ops = copy.deepcopy(ops)

        def compute(latest, raw_hash):
            if raw_hash == self._disk_hash:
                current = self.data
            elif latest is None:
                raise InputError("project.json has disappeared from the project folder")
            else:
                current = jsonpatch.merge3(self._base, self.data, latest)
            return jsonpatch.apply_patch(current, ops)

        self._commit(compute, actor=actor, op=op, reason=reason, patch=ops)

    def set(self, pointer: str, value, *, actor: str, reason: str = "") -> None:
        tokens = jsonpatch.parse_pointer(pointer)
        if not tokens:
            raise ValidationError("set needs a non-empty JSON pointer")
        kind = "replace" if jsonpatch.exists(self.data, pointer) else "add"
        self.apply_patch([{"op": kind, "path": pointer, "value": value}], actor=actor, reason=reason, op="set")

    # -- internal --

    def _commit(self, compute: Callable[[dict | None, str | None], dict], *, actor: str, op: str,
                reason: str = "", patch: list | None = None, extra: Callable[[], dict] | dict | None = None,
                force: bool = False) -> dict | None:
        """Validate and write ``compute(latest_on_disk, raw_hash)`` under the folder lock, then journal it.

        Returns the journal entry (without "before"), or None when nothing changed.
        """
        journal.check_actor(actor)
        with _FolderLock(self.root):
            raw = _read_bytes(self.project_file)
            raw_hash = sha256_bytes(raw) if raw is not None else None
            latest = _parse(raw) if raw is not None else None
            new = compute(latest, raw_hash)
            raise_on_errors(validate_project_data(new, self.root), "project")
            data_bytes = dump_project_bytes(new)
            before_hash = canonical_hash(latest) if latest is not None else None
            after_hash = canonical_hash(new)
            if latest is not None and before_hash == after_hash and not force:
                self._sync(new, raw if raw is not None else data_bytes)
                return None
            _atomic_write(self.project_file, data_bytes)
            entry: dict[str, Any] = {
                "actor": actor,
                "op": op,
                "reason": reason,
                "before_hash": before_hash,
                "after_hash": after_hash,
            }
            if latest is not None:
                entry["patch"] = patch if patch is not None else jsonpatch.diff(latest, new)
            if extra:
                entry.update(extra() if callable(extra) else extra)
            entry["before"] = latest
            stored = journal.append(self.root, entry)
            self._sync(new, data_bytes)
        return {k: v for k, v in stored.items() if k != "before"}

    def _sync(self, new: dict, raw: bytes) -> None:
        if new is not self.data:
            self.data = copy.deepcopy(new)
        self._base = copy.deepcopy(new)
        self._disk_hash = sha256_bytes(raw)

    def __repr__(self) -> str:
        return f"Project(id={self.data.get('id')!r}, title={self.data.get('title')!r})"


__all__ = [
    "Project",
    "PROJECT_FILE",
    "SUBDIRS",
    "default_project_data",
    "default_conform_policy",
    "dump_project_bytes",
    "validate_project_data",
    "check_relpath",
    "errors_only",
]
