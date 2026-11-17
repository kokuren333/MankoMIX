"""BB-18 audio derivations, without registering direction ops or changing core.

``apply`` accepts ``calculate(segment_float64, sample_rate, params) -> audio``.
The segment is read exactly like edit.raw_track (raw clips, no cleanup/chain/
fader). Callers must resolve defaults and include every processing dependency
(including seeds) in params, and change code_version when their code changes.
``keep_length`` truncates/pads to the input range; ``keep_start`` keeps the
calculated length. Both reject placements past the timeline or over unrelated
clips. Audio is carried in a full original-asset-length DOUBLE WAV so ingest
never sees a short derived segment. range_replace plays only its fitted head.

Records live under ``derived`` in the existing FB2 edits ledger. ``revert``
restores complete clip layouts, in reverse application order, through one
validated core patch. ``regenerate`` repairs missing registered audio from the
cache or the recorded raw layout and a caller-supplied versioned calculator.
Existing edit.revert does not dispatch these records; W4 must call this API.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable

import numpy as np

from mankomix.core import api, audio_io, journal, mixrender as mr, remix
from mankomix.core.hashing import sha256_file
from mankomix.core.project import Project
from . import edit

Calculator = Callable[[np.ndarray, int, dict], np.ndarray]
CACHE_VERSION = 1


class DerivedError(ValueError):
    """Invalid derivation, stale layout, unavailable recipe, or hash mismatch."""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _audio_hash(x: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(x, dtype="<f8").tobytes()).hexdigest()


def _identifier(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise DerivedError("ledger identifiers must contain only letters, digits, '_' or '-'")


def _path(root: Path, direction: str) -> Path:
    _identifier(direction)
    return edit.ledger_path(root, direction)


def _save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def _ledger(root: Path, direction: str) -> dict:
    path = _path(root, direction)
    if not path.is_file():
        return {"kind": "direction_edits", "schema_version": 1, "direction": direction,
                "journal_seq_before": journal.last_seq(root), "measure": edit.measure_record(),
                "moves": {}, "derived": {}, "reverted": False}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("kind") != "direction_edits" or value.get("direction") != direction:
        raise DerivedError("not a matching FB2 edit ledger")
    value.setdefault("derived", {})
    return value


def cache_key(source: dict, op: str, params: dict, code_version: str, **placement) -> str:
    """Deterministic SHA256 of source hashes/layout, resolved op params and code version.

    Placement includes input range, fit and destination, since they affect the
    cached carrier. No project path, direction ID, move ID or clock is included.
    """
    return _hash({"cache_version": CACHE_VERSION, "source": source, "op": op,
                  "params": params, "code_version": code_version, **placement})


def _cache(root: Path, key: str) -> Path:
    if re.fullmatch(r"[0-9a-f]{64}", key) is None:
        raise DerivedError("invalid cache key")
    return root / "cache" / "derived" / f"{key}.wav"


def _sample(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0:
        raise DerivedError(f"{name} must be a non-negative integer sample position")
    return int(value)


def _verify_sources(project: Project, source: dict) -> None:
    by_id = {a["id"]: a for a in project.data["assets"]}
    for row in source["assets"]:
        asset = by_id.get(row["id"])
        if asset is None or asset.get("sha256") != row["sha256"]:
            raise DerivedError(f"source asset '{row['id']}' changed or is unavailable")
        if sha256_file(project.asset_path(row["id"])) != row["sha256"]:
            raise DerivedError(f"source sha256 mismatch: {row['id']}")


def _calculate(root: Path, entry: dict, x: np.ndarray, calculate: Calculator) -> tuple[Path, dict]:
    source = entry["source"]
    start, end = entry["start"], entry["end"]
    y = np.asarray(calculate(x[start:end].copy(), source["sample_rate"], copy.deepcopy(entry["params"])),
                   dtype=np.float64)
    if y.ndim != 2 or y.shape[1] != x.shape[1] or not np.isfinite(y).all():
        raise DerivedError("calculator must return finite (frames, input_channels) audio")
    frames = int(y.shape[0])
    fitted = end - start if entry["fit"] == "keep_length" else frames
    dest = entry["timeline_start"]
    if fitted <= 0 or dest + fitted > source["frames"]:
        raise DerivedError("derived clip would leave the existing timeline")
    if fitted > source["carrier_frames"]:
        raise DerivedError("derived clip exceeds the original asset length")
    # Only the input range may be displaced. Anything outside it must remain audible.
    for clip in source["clips"]:
        if clip.get("muted"):
            continue
        a, b = clip["timeline_start"], clip["timeline_start"] + entry["clip_lengths"][clip["id"]]
        for lo, hi in ((a, min(b, start)), (max(a, end), b)):
            if max(lo, dest) < min(hi, dest + fitted):
                raise DerivedError("derived clip overlaps a clip outside the input range")
    carrier = np.zeros((source["carrier_frames"], x.shape[1]), dtype=np.float64)
    n = min(frames, fitted)
    carrier[:n] = y[:n]
    path = _cache(root, entry["key"])
    # Verify a regenerated result before replacing any existing cache/asset.
    temp = path.with_suffix(".tmp.wav")
    audio_io.write(temp, carrier, source["sample_rate"], subtype="DOUBLE")
    result = {"sha256": sha256_file(temp), "calculated_frames": frames, "fitted_frames": fitted}
    expected = entry.get("result")
    if expected and any(result[k] != expected[k] for k in result):
        temp.unlink()
        raise DerivedError("regenerated sha256 or length differs from the ledger")
    temp.replace(path)
    _save(path.with_suffix(".json"), result)
    return path, result


def _cached(root: Path, entry: dict) -> tuple[Path, dict] | None:
    path = _cache(root, entry["key"])
    meta = path.with_suffix(".json")
    result = entry.get("result")
    if result is None and meta.is_file():
        result = json.loads(meta.read_text(encoding="utf-8"))
    if result and path.is_file() and sha256_file(path) == result["sha256"]:
        return path, result
    return None


def _restore(path: Path, dest: Path, sha: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(dest.suffix + ".tmp")
    shutil.copyfile(path, temp)
    if sha256_file(temp) != sha:
        temp.unlink()
        raise DerivedError("restored result sha256 mismatch")
    temp.replace(dest)


def apply(root: str | Path, direction: str, move: str, track: str, start: int, end: int, *,
          op: str, params: dict, code_version: str, calculate: Calculator,
          fit: str = "keep_length", timeline_start: int | None = None, actor: str = "agent") -> dict:
    """Calculate/cache, import an audio asset, range-replace and record one derived move.

    All positions are project-rate samples. Reusing a move ID is refused, even
    after revert. Existing FB2 move records are preserved verbatim. A failed
    placement may leave an unused registered asset, but restores the clip layout.
    """
    root = Path(root)
    _identifier(move)
    journal.check_actor(actor)
    ledger = _ledger(root, direction)
    if move in ledger["derived"] or move in ledger.get("moves", {}):
        raise DerivedError(f"move '{move}' already has a ledger record")
    if fit not in ("keep_start", "keep_length") or not isinstance(params, dict):
        raise DerivedError("invalid fit or params")
    if not op or not code_version or not isinstance(op, str) or not isinstance(code_version, str):
        raise DerivedError("op and code_version must be non-empty strings")
    start, end = _sample(start, "start"), _sample(end, "end")
    dest = start if timeline_start is None else _sample(timeline_start, "timeline_start")
    x, sr, data = edit.raw_track(root, track)
    if end <= start or end > x.shape[0] or dest >= x.shape[0]:
        raise DerivedError("input range or placement is outside the timeline")
    track_data = mr.find_track(data, track)
    clips = copy.deepcopy(track_data.get("clips") or [])
    lengths = {c["id"]: mr.clip_length(data, c, sr) for c in clips}
    if not any(max(start, c["timeline_start"]) < min(end, c["timeline_start"] + lengths[c["id"]])
               for c in clips):
        raise DerivedError("input range has no source clip")
    project = Project.open(root)
    ids = {c["asset"] for c in clips}
    source = {"assets": [{"id": a["id"], "sha256": a["sha256"]} for a in data["assets"] if a["id"] in ids],
              "clips": clips, "sample_rate": sr, "frames": int(x.shape[0]),
              "carrier_frames": max(mr.asset_length_at(a, sr) for a in data["assets"]),
              "raw_sha256": _audio_hash(x)}
    _verify_sources(project, source)
    placement = {"start": start, "end": end, "timeline_start": dest, "fit": fit}
    # JSON round-trip rejects non-JSON/non-finite params and isolates the caller's data.
    params = json.loads(_json(params))
    key = cache_key(source, op, params, code_version, **placement)
    entry = {"kind": "derived", "op": op, "track": track, "params": params,
             "code_version": code_version, "key": key, "source": source, "clip_lengths": lengths,
             **placement, "offset_samples": dest - start, "status": "pending"}
    cached = _cached(root, entry)
    path, result = cached if cached else _calculate(root, entry, x, calculate)
    entry["result"] = dict(result)
    # Core deduplicates by recorded hash, even when the registered file was
    # deleted. Repair that file before the importer checks/reuses the asset.
    existing = next((a for a in project.data["assets"] if a["sha256"] == result["sha256"]), None)
    if existing:
        dest_path = project.asset_path(existing["id"])
        if not dest_path.is_file() and not existing.get("linked"):
            _restore(path, dest_path, result["sha256"])
        elif sha256_file(dest_path) != result["sha256"]:
            raise DerivedError("registered result sha256 mismatch")
    # The existing staged stem import performs file copying, hashing and checks.
    # Drop only its newly created track before committing the registered asset.
    staged, rec, asset = remix._stage_import(project, path, role=track_data.get("role") or "other",
                                            mode="copy", actor=actor)
    added = set(rec.get("tracks_added") or [])
    staged["tracks"] = [t for t in staged["tracks"] if t["id"] not in added]
    remix._refresh_unused(staged)
    try:
        seq = remix._commit(project, staged, actor=actor, op="derived_import",
                            reason=f"direction {direction} move {move}: derived asset")
    except Exception:
        remix._cleanup_copies(project, rec, staged)
        raise
    entry["result"]["asset"] = asset["id"]
    entry["import_journal_seq"] = seq
    reason = f"direction {direction} move {move}: derived placement"
    try:
        if (dest, dest + result["fitted_frames"]) != (start, end):
            api.stem_mute(root, track, start, end, actor=actor, reason=reason)
        placed = api.stem_range_replace(root, track, dest, dest + result["fitted_frames"], asset["id"],
                                        source_start=0, actor=actor, reason=reason)
    except Exception:
        current = Project.open(root)
        rollback = copy.deepcopy(current.data)
        mr.find_track(rollback, track)["clips"] = clips
        remix._refresh_unused(rollback)
        remix._commit(current, rollback, actor=actor, op="derived_rollback", reason=reason)
        raise
    after = Project.open(root).data
    entry.update({"clip": placed["clip"], "muted_clips": placed["muted_clips"],
                  "journal_seq": placed["journal_seq"], "after_clips": copy.deepcopy(mr.find_track(after, track)["clips"]),
                  "status": "applied"})
    # Include pieces muted by the preceding source-range mute for shifted/resized clips.
    before_muted = {c["id"] for c in clips if c.get("muted")}
    entry["muted_clips"] = [c["id"] for c in entry["after_clips"]
                            if c.get("muted") and c["id"] not in before_muted]
    ledger["derived"][move] = entry
    ledger["reverted"] = False
    _save(_path(root, direction), ledger)
    return copy.deepcopy(entry)


def revert(root: str | Path, direction: str, move: str | None = None, *, actor: str = "human") -> dict:
    """Restore derived layouts in reverse application order, with stale-layout protection.

    FB2 edit moves remain unchanged. Revert derived moves before reverting any
    earlier edit moves on their tracks. Repeating a completed revert is a no-op.
    """
    root = Path(root)
    if not _path(root, direction).is_file():
        raise DerivedError(f"no edit ledger for {direction}")
    ledger = _ledger(root, direction)
    records = ledger["derived"]
    if move is not None and records.get(move, {}).get('group'):
        raise DerivedError('revert the complete group through direction edit revert')
    if move is not None and move not in records:
        raise DerivedError(f"unknown derived move '{move}'")
    targets = [mid for mid, row in records.items() if row["status"] == "applied" and (move is None or mid == move)
               and not row.get('group')]
    project = Project.open(root)
    data = copy.deepcopy(project.data)
    for mid in reversed(targets):
        row = records[mid]
        track = mr.find_track(data, row["track"])
        if track["clips"] != row["after_clips"]:
            raise DerivedError(f"{mid}: clip layout changed; revert later moves first")
        track["clips"] = copy.deepcopy(row["source"]["clips"])
    remix._refresh_unused(data)
    seq = remix._commit(project, data, actor=actor, op="derived_revert", reason=f"direction {direction}: revert derived")
    for mid in targets:
        records[mid].update(status="reverted", reverted_journal_seq=seq)
    ledger["reverted"] = not any(row.get("status") == "applied" for group in (ledger.get("moves", {}), records)
                                  for row in group.values())
    if targets:
        _save(_path(root, direction), ledger)
    return {"kind": "direction_derived_revert", "direction": direction,
            "reverted_moves": targets, "journal_seq": seq, "ledger_reverted": ledger["reverted"]}


def regenerate(root: str | Path, direction: str, move: str, *, calculate: Calculator | None = None) -> dict:
    """Ensure a ledger result exists and matches its SHA256, without changing project.json.

    Cache hits need no calculator. Cache misses require the exact recorded
    op/code_version implementation. Missing source assets (including earlier
    derivations) must be restored first. Changed source/result hashes are errors.
    """
    root = Path(root)
    records = _ledger(root, direction)["derived"]
    if move not in records:
        raise DerivedError(f"unknown derived move '{move}'")
    entry = records[move]
    project = Project.open(root)
    asset = next((a for a in project.data["assets"] if a["id"] == entry["result"]["asset"]), None)
    if asset is None or asset["sha256"] != entry["result"]["sha256"] or asset.get("linked"):
        raise DerivedError("registered result asset changed or is unavailable")
    dest = project.asset_path(asset["id"])
    if dest.is_file():
        if sha256_file(dest) != entry["result"]["sha256"]:
            raise DerivedError("registered result sha256 mismatch")
        return {"asset": asset["id"], "sha256": asset["sha256"], "regenerated": False}
    cached = _cached(root, entry)
    if cached:
        path, _ = cached
    else:
        if calculate is None:
            raise DerivedError(f"calculator required for {entry['op']} at version {entry['code_version']}")
        _verify_sources(project, entry["source"])
        data = copy.deepcopy(project.data)
        track = mr.find_track(data, entry["track"])
        track["clips"] = copy.deepcopy(entry["source"]["clips"])
        track.pop("cleanup", None)
        x, sr, _ = mr.render_track(edit._RawView(project, data), entry["track"], apply_chain=False,
                                    apply_fader=False, length=entry["source"]["frames"])
        if sr != entry["source"]["sample_rate"] or _audio_hash(x) != entry["source"]["raw_sha256"]:
            raise DerivedError("recorded raw source no longer renders identically")
        path, _ = _calculate(root, entry, x, calculate)
    _restore(path, dest, entry["result"]["sha256"])
    return {"asset": asset["id"], "sha256": asset["sha256"], "regenerated": True}


_resource_undo = ContextVar('direction_resource_undo', default=None)


@contextmanager
def transaction(root, *, actor):
    """Compensate failed multi-resource operations through core; retain journal history.

    Failed attempts leave no registered assets, placements or ledger rows. New
    cache/files are removed; pre-existing caches are expendable. Journal entries
    are never truncated: the compensation is itself an ordinary core patch.
    """
    root = Path(root)
    before = copy.deepcopy(Project.open(root).data)
    files = {p.relative_to(root) for p in root.rglob('*') if p.is_file()}
    ledgers = {p: p.read_bytes() for p in (root / 'directions').glob('*.edits.json')}
    parent_undo = _resource_undo.get()
    undo = []
    token = _resource_undo.set(undo)
    try:
        yield
    except BaseException:
        remix._commit(Project.open(root), before, actor=actor, op='xop_rollback',
                      reason='rollback failed direction resource transaction')
        for p in root.rglob('*'):
            if p.is_file() and p.relative_to(root) not in files:
                p.unlink()
        for p, contents in ledgers.items():
            p.write_bytes(contents)
        for p, contents in reversed(undo):
            if contents is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(contents)
        raise
    else:
        if parent_undo is not None:
            parent_undo.extend(undo)
    finally:
        _resource_undo.reset(token)


def _source_segment(root, track, start, end):
    """A reproducible raw snapshot, also used by non-audio derivations."""
    start, end = _sample(start, 'start'), _sample(end, 'end')
    x, sr, data = edit.raw_track(root, track)
    if not start < end <= len(x):
        raise DerivedError('control input is outside the timeline')
    clips = copy.deepcopy(mr.find_track(data, track).get('clips') or [])
    ids = {c['asset'] for c in clips}
    source = {'track': track, 'clips': clips, 'sample_rate': sr, 'frames': len(x),
              'assets': [{'id': a['id'], 'sha256': a['sha256']} for a in data['assets'] if a['id'] in ids],
              'raw_sha256': _audio_hash(x)}
    _verify_sources(Project.open(root), source)
    return x[start:end].copy(), source


def _control_payload(value):
    if not isinstance(value, dict) or value.get('kind') != 'control':
        raise DerivedError('control calculator must return a kind=control payload')
    value = dict(value)
    values = np.asarray(value.get('values'), dtype=np.float64)
    hop, origin = float(value.get('hop_s', .005)), float(value.get('origin_s', 0))
    if (values.ndim not in (2, 3) or not all(values.shape) or not np.isfinite(values).all()
            or np.any(values < 0) or values.ndim == 3 and values.shape[2] not in (1, 2)
            or not np.isfinite(hop) or hop <= 0 or not np.isfinite(origin) or origin < 0):
        raise DerivedError('invalid control dimensions, amplitudes or timing')
    if 'centers_hz' in value:
        centers = np.asarray(value['centers_hz'], dtype=np.float64)
        if (centers.shape != (values.shape[1],) or not np.isfinite(centers).all()
                or np.any(centers <= 0) or np.any(np.diff(centers) <= 0)):
            raise DerivedError('invalid control band centers')
        value['centers_hz'] = centers.tolist()
    value.update(values=values.tolist(), hop_s=hop, origin_s=origin)
    return json.loads(_json(value))


def prepare_control(root, *, track, start, end, op, params, code_version, calculate):
    """Read/calculate only. Return a JSON recipe and payload; create no files."""
    if not isinstance(params, dict) or not isinstance(code_version, str) or not code_version:
        raise DerivedError('control needs resolved params and code_version')
    params = json.loads(_json(params))
    x, source = _source_segment(root, track, start, end)
    payload = _control_payload(calculate(x, source['sample_rate'], copy.deepcopy(params)))
    sha = _hash(payload)
    return {'kind': 'control', 'op': op, 'params': params, 'code_version': code_version,
            'source': source, 'start': int(start), 'end': int(end),
            'key': cache_key(source, op, params, code_version, start=int(start), end=int(end), kind='control'),
            'result': {'asset': 'ctl_' + sha, 'sha256': sha}, 'payload': payload}


def _control_paths(root, entry):
    aid = entry['result']['asset']
    if re.fullmatch(r'ctl_[0-9a-f]{64}', aid) is None:
        raise DerivedError('invalid control asset ID')
    return (Path(root) / 'assets' / 'derived' / f'{aid}.json',
            Path(root) / 'cache' / 'derived' / f"{entry['key']}.control.json")


def _locator(asset):
    from mankomix.core.config import settings_dir
    if re.fullmatch(r'ctl_[0-9a-f]{64}', asset) is None:
        raise LookupError(asset)
    return settings_dir() / 'derived' / f'{asset}.json'


_control_root = ContextVar('direction_control_root', default=None)
_planned_controls = ContextVar('direction_planned_controls', default={})


@contextmanager
def control_context(root=None, planned=None):
    """Scope project selection/planned payloads without writing or global retargeting."""
    a = _control_root.set(Path(root).resolve() if root is not None else None)
    b = _planned_controls.set(planned or {})
    try:
        yield
    finally:
        _planned_controls.reset(b)
        _control_root.reset(a)


def resolve_control(asset):
    """Persistent resolver. Explicit context wins; locator fallback supports raw core renders.

    The user settings index contains only locations, never authoritative payloads.
    Project copies/moves can use control_context(new_root) or the CLI --project.
    Every read checks the content hash embedded in the ID, including planned data.
    """
    locator = _locator(asset)
    if asset in _planned_controls.get():
        payload = _planned_controls.get()[asset]
    else:
        root = _control_root.get()
        if root is None:
            root = Path.cwd()
            if not (root / 'assets' / 'derived' / f'{asset}.json').is_file():
                if not locator.is_file():
                    raise LookupError(asset)
                root = Path(json.loads(locator.read_text(encoding='utf-8'))['root'])
        path = root / 'assets' / 'derived' / f'{asset}.json'
        if not path.is_file():
            raise LookupError(asset)
        payload = json.loads(path.read_text(encoding='utf-8'))
    if _hash(payload) != asset.removeprefix('ctl_'):
        raise DerivedError('control result sha256 mismatch')
    return _control_payload(payload)


def install_control_resolver():
    from mankomix.dspx.bb.band_envelopes import install_control_resolver as install
    install(resolve_control)


def apply_control(root, direction, move, name, prepared, *, actor='agent'):
    """Register a prepared control in a separate non-audio ledger/asset namespace."""
    root = Path(root)
    _identifier(move)
    _identifier(name)
    journal.check_actor(actor)
    entry = copy.deepcopy(prepared)
    payload = entry.pop('payload')
    if _hash(payload) != entry['result']['sha256']:
        raise DerivedError('prepared control sha256 mismatch')
    _verify_sources(Project.open(root), entry['source'])
    _, current_source = _source_segment(root, entry['source']['track'], entry['start'], entry['end'])
    if current_source != entry['source']:
        raise DerivedError('control source changed after planning')
    ledger = _ledger(root, direction)
    key = f'{move}__{name}'
    if key in ledger.get('controls', {}):
        raise DerivedError('control already registered for this move/name')
    dest, cache = _control_paths(root, entry)
    for path in (dest, cache):
        if path.is_file() and _hash(json.loads(path.read_text(encoding='utf-8'))) != entry['result']['sha256']:
            raise DerivedError('existing control sha256 mismatch')
        _save(path, payload)
    entry.update(status='applied', owner='director', move_ref=f'{direction}/{move}', name=name,
                 path=dest.relative_to(root).as_posix())
    ledger.setdefault('controls', {})[key] = entry
    ledger['reverted'] = False
    _save(_path(root, direction), ledger)
    # Location only; a different process can resolve the content-addressed ID.
    locator = _locator(entry['result']['asset'])
    undo = _resource_undo.get()
    if undo is not None:
        undo.append((locator, locator.read_bytes() if locator.is_file() else None))
    _save(locator, {'root': str(root.resolve())})
    install_control_resolver()
    return entry


def regenerate_control(root, direction, move, name, *, calculate=None):
    """Repair missing control/cache from the exact recorded raw snapshot and version."""
    root = Path(root)
    entry = _ledger(root, direction).get('controls', {}).get(f'{move}__{name}')
    if entry is None:
        raise DerivedError('unknown control recipe')
    dest, cache = _control_paths(root, entry)
    payload = None
    for path in (dest, cache):
        if path.is_file():
            value = json.loads(path.read_text(encoding='utf-8'))
            if _hash(value) != entry['result']['sha256']:
                raise DerivedError('control result sha256 mismatch')
            payload = value
    existed = dest.is_file()
    if payload is None:
        if calculate is None:
            raise DerivedError(f"calculator required for {entry['op']} at version {entry['code_version']}")
        project = Project.open(root)
        _verify_sources(project, entry['source'])
        data = copy.deepcopy(project.data)
        track = mr.find_track(data, entry['source']['track'])
        track['clips'] = copy.deepcopy(entry['source']['clips'])
        track.pop('cleanup', None)
        x, sr, _ = mr.render_track(edit._RawView(project, data), track['id'], apply_chain=False,
                                    apply_fader=False, length=entry['source']['frames'])
        if sr != entry['source']['sample_rate'] or _audio_hash(x) != entry['source']['raw_sha256']:
            raise DerivedError('recorded control source no longer renders identically')
        payload = _control_payload(calculate(x[entry['start']:entry['end']].copy(), sr,
                                             copy.deepcopy(entry['params'])))
        if _hash(payload) != entry['result']['sha256']:
            raise DerivedError('regenerated control sha256 differs from ledger')
    for path in (dest, cache):
        if not path.is_file():
            _save(path, payload)
    return {**entry['result'], 'regenerated': not existed}


def regenerate_group(root, direction, move, *, calculators=None):
    """Regenerate all member assets; calculators maps each track to its exact version."""
    from .xops._group import regenerate
    return regenerate(root, direction, move, calculators=calculators)


def regenerate_node(root, direction, move, name, *, audio=None):
    """Repair generated node audio from cache or the exact version's supplied waveform."""
    from .xops._resources import regenerate
    return regenerate(root, direction, move, name, audio=audio)
