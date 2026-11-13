"""Remix operations on the canonical project (docs/SPEC.md 9.3, 9.5; R-04, R-22, D-048, D-051).

Every operation is a mutation of project.json committed through
``Project.apply_patch`` with the caller's ``actor``, so it is validated,
journaled as one entry (``op`` = the operation name) and can be undone with
``journal.undo``. Source assets are never modified; removed or replaced
assets stay in the project and are flagged ``unused: true`` while no clip
refers to them.

Time is in samples at the project sample rate (SPEC 9.2). Tracks are audio
tracks (``kind: "audio"``, D-051).

Added and replacement material is imported with the file adapter (import
checks, SPEC 6.1.4) and diagnosed for tempo / key consistency against the
project; mismatches are reported, never corrected: no time-stretch and no
pitch-shift in v1 (D-048).

Imports are staged on an in-memory copy of the project (the adapter copies the
file into assets/ and fills the copy), then committed once together with the
remix change, so that ``stem_add`` / ``stem_replace`` are one journal entry
and one undo step. The project sample rate never changes once it is set:
added assets at another rate are resampled at render time (D-054).
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

import mankomix

from . import audio_io, journal
from . import mixrender as mr
from .errors import InputError, ValidationError
from .hashing import canonical_hash
from .ingest import naming
from .ingest.checks import length_at_rate
from .jsonpatch import json_equal
from .project import Project, check_relpath
from .schema import to_pointer

ROLE_VOCAB = ("vocals", "backing_vocals", "drums", "percussion", "bass", "guitar", "keyboard", "synth",
              "strings", "brass", "woodwinds", "fx", "other")

# Tempo / key consistency diagnosis (reporting only, D-048).
BPM_TOLERANCE_PCT = 1.5          # relative tempo difference still reported as a match
LOW_CONFIDENCE_BELOW = 0.5       # same as knowledge thresholds music.low_confidence_below
ANALYSIS_CACHE_DIR = "cache/remix"
ANALYSIS_CACHE_VERSION = 1
PITCH_CLASSES = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6,
                 "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


# --------------------------------------------------------------------------
# commit helpers


def _fine_diff(a: Any, b: Any, base: list | None = None) -> list[dict]:
    """JSON patch from a to b; equal-length arrays are diffed per index (finer than replace-all)."""
    base = base or []
    if json_equal(a, b):
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        ops: list[dict] = [{"op": "remove", "path": to_pointer(base + [k])} for k in a if k not in b]
        for k in b:
            if k not in a:
                ops.append({"op": "add", "path": to_pointer(base + [k]), "value": copy.deepcopy(b[k])})
            else:
                ops.extend(_fine_diff(a[k], b[k], base + [k]))
        return ops
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b) and base:
        ops = []
        for i, (x, y) in enumerate(zip(a, b)):
            ops.extend(_fine_diff(x, y, base + [i]))
        return ops
    return [{"op": "replace", "path": to_pointer(base), "value": copy.deepcopy(b)}]


def _commit(project: Project, new: dict, *, actor: str, op: str, reason: str) -> int | None:
    """Apply ``new`` as one journaled patch. Returns the journal seq (None when nothing changed)."""
    journal.check_actor(actor)
    ops = _fine_diff(project.data, new)
    if not ops:
        return None
    project.apply_patch(ops, actor=actor, reason=reason, op=op)
    return journal.last_seq(project.root)


def _result(op: str, seq: int | None, **kw) -> dict:
    out = {"op": op, "changed": seq is not None, "journal_seq": seq}
    out.update(kw)
    return out


# --------------------------------------------------------------------------
# lookups


def _rate(data: dict) -> int:
    return mr.project_rate(data)


def _track(data: dict, track_id: str) -> dict:
    return mr.find_track(data, track_id)


def _clip(data: dict, clip_id: str) -> tuple[dict, dict]:
    for t in data.get("tracks") or []:
        for c in t.get("clips") or []:
            if c.get("id") == clip_id:
                return t, c
    raise InputError(f"unknown clip '{clip_id}'")


def _all_ids(data: dict) -> set[str]:
    ids: set[str] = set()
    for key in ("assets", "tracks", "buses", "references", "variants", "sections"):
        for x in data.get(key) or []:
            if isinstance(x, dict) and isinstance(x.get("id"), str):
                ids.add(x["id"])
    for t in data.get("tracks") or []:
        for sub in ("clips", "chain"):
            for x in t.get(sub) or []:
                if isinstance(x, dict) and isinstance(x.get("id"), str):
                    ids.add(x["id"])
    for b in data.get("buses") or []:
        for x in b.get("chain") or []:
            if isinstance(x, dict) and isinstance(x.get("id"), str):
                ids.add(x["id"])
    return ids


def _new_id(data: dict, base: str, taken: set[str] | None = None) -> str:
    taken = taken if taken is not None else _all_ids(data)
    i = 2
    cand = base
    while cand in taken:
        cand = f"{base}_{i}"
        i += 1
    taken.add(cand)
    return cand


def _asset(data: dict, asset_id: str) -> dict:
    for a in data.get("assets") or []:
        if a.get("id") == asset_id:
            return a
    raise InputError(f"unknown asset '{asset_id}'",
                     details={"valid": [a.get("id") for a in data.get("assets") or []]})


def _refresh_unused(data: dict) -> list[str]:
    """Flag assets no clip refers to (full mix excluded) with ``unused: true``. Returns their ids."""
    used = {c.get("asset") for t in data.get("tracks") or [] for c in t.get("clips") or []}
    fid = data.get("fullmix_asset")
    unused = []
    for a in data.get("assets") or []:
        if a.get("id") in used or a.get("id") == fid or a.get("origin") == "reference_fullmix":
            a.pop("unused", None)
        else:
            a["unused"] = True
            unused.append(a["id"])
    return unused


def _clip_len(data: dict, clip: dict) -> int:
    return mr.clip_length(data, clip, _rate(data))


def _check_samples(name: str, v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, np.integer)) or v < 0:
        raise InputError(f"{name} must be a non-negative integer number of samples")
    return int(v)


def _r22(data: dict, track_ids: list[str]) -> list[dict]:
    return mr.separated_notes(data, track_ids)


# --------------------------------------------------------------------------
# listing


def stem_list(project: Project) -> dict:
    """Tracks with role, lead, level, pan, routing and clips; unused assets; R-22 notes."""
    data = project.data
    pr = _rate(data) if data.get("assets") else None
    by_id = {a.get("id"): a for a in data.get("assets") or []}
    tracks = []
    for t in data.get("tracks") or []:
        clips = []
        for c in t.get("clips") or []:
            clips.append({"id": c.get("id"), "asset": c.get("asset"),
                          "source_start": c.get("source_start", 0), "timeline_start": c.get("timeline_start", 0),
                          "length": _clip_len(data, c) if pr else c.get("length"),
                          "gain_db": c.get("gain_db", 0.0), "fade_in": c.get("fade_in", 0),
                          "fade_out": c.get("fade_out", 0), "muted": bool(c.get("muted", False))})
        assets = sorted({c.get("asset") for c in t.get("clips") or []})
        tracks.append({
            "id": t.get("id"), "kind": t.get("kind", "audio"), "role": t.get("role"),
            "is_lead": bool(t.get("is_lead", False)), "stem": mr.is_stem_track(data, t),
            "muted": bool(t.get("muted", False)), "solo": bool(t.get("solo", False)),
            "gain_db": t.get("gain_db", 0.0), "pan": t.get("pan", {"position": 0.0, "width": 1.0}),
            "output": t.get("output"), "sends": t.get("sends", []), "chain_length": len(t.get("chain") or []),
            "assets": assets, "origins": sorted({(by_id.get(a) or {}).get("origin") for a in assets} - {None}),
            "clips": clips,
        })
    return {
        "sample_rate": pr,
        "timeline_length": mr.timeline_length(data, pr) if pr else None,
        "tracks": tracks,
        "unused_assets": [a.get("id") for a in data.get("assets") or [] if a.get("unused")],
        "lead": next((t.get("id") for t in data.get("tracks") or [] if t.get("is_lead")), None),
        "notes": _r22(data, [t.get("id") for t in data.get("tracks") or []]),
    }


# --------------------------------------------------------------------------
# import staging and consistency diagnosis


class _StagedProject(Project):
    """In-memory copy of a project used to stage an import; ``save`` records instead of writing."""

    saved: dict | None = None

    def save(self, *, actor: str = "planner", op: str = "save", reason: str = "") -> None:  # noqa: D401
        self.saved = {"actor": actor, "op": op, "reason": reason}


def _conform_at(assets: list[dict], pr: int, length: int) -> list[dict]:
    """Conform entries (D-054 format) for a fixed project rate."""
    applied = []
    for a in assets:
        sr = int(a["sample_rate"])
        if sr != pr:
            applied.append({"asset": a["id"], "from_rate": sr, "to_rate": pr, "action": "resample_at_render"})
        if length_at_rate(a["length_samples"], sr, pr) < length:
            applied.append({"asset": a["id"], "from_rate": sr, "to_rate": pr, "action": "pad_silence_at_render"})
    return applied


def _stage_import(project: Project, src, *, role: str | None, mode: str, actor: str) -> tuple[dict, dict, dict]:
    """Import one file into a staged copy. Returns (staged data, import record, new asset)."""
    path = Path(src)
    if not path.is_file():
        raise InputError(f"input file not found: {path.name}")
    if not audio_io.is_audio_file(path):
        raise InputError(f"not an audio file: {path.name}")
    if role is not None and role not in ROLE_VOCAB:
        raise InputError(f"unknown role '{role}'", details={"vocabulary": list(ROLE_VOCAB)})
    if role is None:
        kw_role, kw_source = naming.keyword_role(naming.stem_of(path.name))
        if kw_role == "fullmix":
            kw_role, kw_source = "other", naming.RS_DEFAULT
    else:
        kw_role, kw_source = role, naming.RS_USER

    old = project.data
    staged = _StagedProject(project.root, copy.deepcopy(old), base=None, disk_hash=None)
    from .adapters.file import FileAdapter
    # A list (not a bare path) so a single file is not classified as the full mix.
    rec = FileAdapter().fetch([path], staged, mode=mode, actor=actor, roles={path.name: kw_role})
    data = staged.data
    if not rec.get("assets_added"):
        dup = next((s for s in rec.get("skipped") or [] if s.get("reason") == "duplicate"), None)
        if dup is not None:
            return data, rec, _asset(old, dup["duplicate_of"])
        raise InputError(f"'{path.name}' was not imported", details={"skipped": rec.get("skipped")})
    aid = rec["assets_added"][0]
    asset = _asset(data, aid)
    asset["origin"] = "added"
    asset["role_source"] = kw_source
    if kw_source != naming.RS_USER:
        asset["role_note"] = naming.NOTE_KEYWORD if kw_source == naming.RS_KEYWORD else naming.NOTE_UNKNOWN

    # Keep the project's identity: provenance, the lead and an already fixed sample rate do not
    # change (D-054); the adapter's lead estimate is meant for a first import only.
    old_lead = {t.get("id"): t.get("is_lead") for t in old.get("tracks") or []}
    for t in data.get("tracks") or []:
        if t.get("id") in old_lead:
            if old_lead[t["id"]] is None:
                t.pop("is_lead", None)
            else:
                t["is_lead"] = old_lead[t["id"]]
        else:
            t["is_lead"] = False
    if isinstance(data.get("objective"), dict) and isinstance(old.get("objective"), dict):
        data["objective"]["lead_stem"] = old["objective"].get("lead_stem")
    if "provenance" in old:
        data["provenance"] = copy.deepcopy(old["provenance"])
    old_tb = old.get("timebase") or {}
    if old_tb.get("sample_rate"):
        pr = int(old_tb["sample_rate"])
        tb = data.setdefault("timebase", {})
        length = max([int(old_tb.get("length_samples") or 0)]
                     + [length_at_rate(a["length_samples"], a["sample_rate"], pr) for a in data["assets"]])
        tb["sample_rate"] = pr
        tb["length_samples"] = length
        tb["conform_policy"] = {**(old_tb.get("conform_policy") or {}),
                                "applied": _conform_at(data["assets"], pr, length)}
        ing = data.get("ingest")
        if isinstance(ing, dict) and isinstance(ing.get("conform"), dict):
            ing["conform"]["sample_rate"] = pr
            ing["conform"]["length_samples"] = length
    # A project with a mix bus not called bus_mix: route the new track there, drop the adapter's bus_mix.
    mixes = [b for b in data.get("buses") or [] if b.get("kind") == "mix"]
    if len(mixes) > 1:
        orig = next(b["id"] for b in old.get("buses") or [] if b.get("kind") == "mix")
        data["buses"] = [b for b in data["buses"] if not (b.get("kind") == "mix" and b["id"] != orig)]
        for t in data.get("tracks") or []:
            if t.get("output") not in {b["id"] for b in data["buses"]}:
                t["output"] = orig
    return data, rec, asset


def _cleanup_copies(project: Project, rec: dict, data: dict) -> None:
    if rec.get("mode") != "copy":
        return
    for aid in rec.get("assets_added") or []:
        try:
            a = _asset(data, aid)
            (Path(project.root) / a["path"]).unlink(missing_ok=True)
        except (InputError, OSError):
            pass


def _cache_path(project: Project, key: str) -> Path:
    return Path(project.root).joinpath(*ANALYSIS_CACHE_DIR.split("/")) / f"music_{key}.json"


def _music_summary(x: np.ndarray, sr: int) -> dict:
    from .analysis.music import analyze_music
    m = analyze_music(x, sr)
    return {"bpm": m.get("bpm"), "bpm_confidence": m.get("bpm_confidence"),
            "bpm_alternatives": m.get("bpm_alternatives", [])[:2], "key": m.get("key"),
            "key_confidence": m.get("key_confidence"), "duration_s": m.get("duration_s")}


def _cached_music(project: Project, key: str, compute) -> dict:
    path = _cache_path(project, key)
    if path.is_file():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if stored.get("version") == ANALYSIS_CACHE_VERSION:
                return stored["music"]
        except (OSError, ValueError, KeyError):
            pass
    music = compute()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": ANALYSIS_CACHE_VERSION, "music": music}, ensure_ascii=False),
                        encoding="utf-8")
    except OSError:
        pass
    return music


def project_music(project: Project) -> dict | None:
    """Tempo / key of the current static stem sum (cached by the summed assets' hashes)."""
    data = project.data
    ids = []
    fid = mr.fullmix_asset_id(data)
    for t in mr.stem_tracks(data):
        for c in t.get("clips") or []:
            if c.get("asset") not in ids and c.get("asset") != fid:
                ids.append(c.get("asset"))
    if not ids:
        return None
    by_id = {a["id"]: a for a in data.get("assets") or []}
    key = canonical_hash({"static_sum": [[a, by_id[a].get("sha256")] for a in ids]})[:24]

    def compute():
        x, sr, _ = mr.static_sum(project, assets=ids)
        return _music_summary(x, sr)

    return _cached_music(project, key, compute)


def asset_music(project: Project, asset: dict, path: Path | None = None) -> dict:
    """Tempo / key of one asset (cached by sha256)."""
    def compute():
        x, sr = audio_io.read(path if path is not None else project.asset_path(asset["id"]))
        return _music_summary(x, sr)

    return _cached_music(project, "asset_" + str(asset.get("sha256"))[:24], compute)


def _parse_key(key: str | None) -> tuple[int, str] | None:
    if not key or not isinstance(key, str):
        return None
    parts = key.split()
    if len(parts) != 2 or parts[0] not in PITCH_CLASSES or parts[1] not in ("major", "minor"):
        return None
    return PITCH_CLASSES[parts[0]], parts[1]


def diagnose_consistency(project_music_: dict | None, asset_music_: dict, *, timebase: dict | None = None) -> dict:
    """Compare tempo and key of new material with the project. Reporting only (D-048).

    The project reference is ``timebase.bpm`` / ``timebase.key`` when declared,
    else the analysis of the static stem sum.
    """
    tb = timebase or {}
    ref = project_music_ or {}
    out: dict[str, Any] = {"action": "reported_only", "time_stretch": False, "pitch_shift": False,
                           "rule": "D-048", "project_analysis": project_music_, "asset_analysis": asset_music_}

    # tempo
    ref_bpm = tb.get("bpm") or ref.get("bpm")
    ref_src = "timebase" if tb.get("bpm") else ("static_sum_analysis" if ref.get("bpm") else None)
    ref_conf = 1.0 if ref_src == "timebase" else (ref.get("bpm_confidence") or 0.0)
    new_bpm, new_conf = asset_music_.get("bpm"), asset_music_.get("bpm_confidence") or 0.0
    tempo: dict[str, Any] = {"project_bpm": _round(ref_bpm, 2), "project_source": ref_src,
                             "asset_bpm": _round(new_bpm, 2)}
    if not ref_bpm or not new_bpm:
        tempo.update(status="unknown", level="info")
    else:
        ratio = float(new_bpm) / float(ref_bpm)
        oct_ = round(math.log2(ratio))
        dev_pct = 100.0 * (ratio / (2.0 ** oct_) - 1.0)
        tempo.update(ratio=round(ratio, 4), difference_bpm=round(float(new_bpm) - float(ref_bpm), 2),
                     stretch_needed_pct=round(100.0 * (float(ref_bpm) / float(new_bpm) - 1.0), 2))
        if abs(dev_pct) <= BPM_TOLERANCE_PCT and oct_ == 0:
            tempo["status"] = "match"
        elif abs(dev_pct) <= BPM_TOLERANCE_PCT and abs(oct_) == 1:
            tempo["status"] = "half_or_double"
        else:
            tempo["status"] = "mismatch"
        low = min(ref_conf, new_conf) < LOW_CONFIDENCE_BELOW
        tempo["confidence"] = "low" if low else "ok"
        tempo["level"] = "warning" if tempo["status"] == "mismatch" and not low else "info"
    out["tempo"] = tempo

    # key
    ref_key = tb.get("key") or ref.get("key")
    ksrc = "timebase" if tb.get("key") else ("static_sum_analysis" if ref.get("key") else None)
    kconf = 1.0 if ksrc == "timebase" else (ref.get("key_confidence") or 0.0)
    a, b = _parse_key(ref_key), _parse_key(asset_music_.get("key"))
    key: dict[str, Any] = {"project_key": ref_key, "project_source": ksrc, "asset_key": asset_music_.get("key")}
    if a is None or b is None:
        key.update(status="unknown", level="info")
    else:
        semis = (b[0] - a[0]) % 12
        semis = semis - 12 if semis > 6 else semis
        if a == b:
            status = "match"
        elif a[1] != b[1] and ((a[1] == "major" and (a[0] + 9) % 12 == b[0])
                               or (a[1] == "minor" and (a[0] + 3) % 12 == b[0])):
            status = "relative"
        else:
            status = "mismatch"
        low = min(kconf, asset_music_.get("key_confidence") or 0.0) < LOW_CONFIDENCE_BELOW
        key.update(status=status, semitones=semis, confidence="low" if low else "ok",
                   level="warning" if status == "mismatch" and not low else "info")
    out["key"] = key
    msgs = []
    if tempo.get("status") == "mismatch":
        msgs.append(f"tempo differs: asset {tempo['asset_bpm']} BPM vs project {tempo['project_bpm']} BPM; "
                    "not stretched (D-048)")
    if key.get("status") == "mismatch":
        msgs.append(f"key differs: asset {key['asset_key']} vs project {key['project_key']}; "
                    "not pitch-shifted (D-048)")
    out["messages"] = msgs
    out["status"] = "mismatch" if msgs else ("unknown" if "unknown" in (tempo["status"], key["status"]) else "ok")
    return out


def _round(v, nd):
    return None if v is None else round(float(v), nd)


def _consistency_summary(diag: dict) -> dict:
    """Compact form stored on the track (the full analyses stay in cache/)."""
    return {"status": diag["status"], "action": "reported_only", "rule": "D-048",
            "tempo": {k: v for k, v in diag["tempo"].items() if k != "level"},
            "key": {k: v for k, v in diag["key"].items() if k != "level"}}


def _asset_checks(rec: dict, aid: str) -> list[dict]:
    return [c for c in rec.get("checks") or [] if c.get("asset") == aid]


# --------------------------------------------------------------------------
# operations


def stem_add(project: Project, src, *, role: str | None = None, actor: str, mode: str = "copy",
             reason: str = "", diagnose: bool = True) -> dict:
    """Import a file as a new stem track (origin "added"), with import checks and a tempo/key report."""
    journal.check_actor(actor)
    if role is not None and role not in ROLE_VOCAB:
        raise InputError(f"unknown role '{role}'", details={"vocabulary": list(ROLE_VOCAB)})
    ref_music = project_music(project) if diagnose else None
    data, rec, asset = _stage_import(project, src, role=role, mode=mode, actor=actor)
    if not rec.get("assets_added"):
        raise InputError(f"the same audio is already in the project as asset '{asset['id']}'",
                         details={"duplicate_of": asset["id"]})
    aid = asset["id"]
    tid = next(t["id"] for t in data["tracks"] if any(c.get("asset") == aid for c in t.get("clips") or []))
    try:
        diag = None
        if diagnose:
            path = Path(src) if asset.get("linked") else Path(project.root) / asset["path"]
            diag = diagnose_consistency(ref_music, asset_music(project, asset, path),
                                        timebase=project.data.get("timebase"))
            _track(data, tid)["consistency"] = _consistency_summary(diag)
        _refresh_unused(data)
        why = reason or f"stem add: {Path(src).name} as {asset['role']} ({tid})"
        seq = _commit(project, data, actor=actor, op="stem_add", reason=why)
    except Exception:
        _cleanup_copies(project, rec, data)
        raise
    return _result("stem_add", seq, track=tid, asset=aid, role=asset["role"], origin="added",
                   checks=_asset_checks(rec, aid), warnings=rec.get("warnings", []),
                   consistency=diag, notes=_r22(project.data, [tid]))


def stem_replace(project: Project, track_id: str, src, *, keep_chain: bool = True, actor: str,
                 mode: str = "copy", reason: str = "", diagnose: bool = True) -> dict:
    """Point a track's clips at another asset (a file to import, or an existing asset id).

    Clips that used the track's primary asset (the first clip's asset) now use
    the new one; a clip that covered the whole old asset is resized to the
    whole new asset. ``keep_chain=False`` clears the track chain and resets
    cleanup to automatic. The old asset stays in the project (``unused`` when
    nothing refers to it any more).
    """
    journal.check_actor(actor)
    track0 = _track(project.data, track_id)
    if not track0.get("clips"):
        raise InputError(f"track '{track_id}' has no clips to replace")
    rec: dict = {}
    existing = isinstance(src, str) and any(a.get("id") == src for a in project.data.get("assets") or [])
    ref_music = project_music(project) if diagnose else None
    if existing:
        data = copy.deepcopy(project.data)
        asset = _asset(data, src)
    else:
        data, rec, asset = _stage_import(project, src, role=track0.get("role"), mode=mode, actor=actor)
        added = set(rec.get("tracks_added") or [])
        data["tracks"] = [t for t in data["tracks"] if t["id"] not in added]
    try:
        pr = _rate(data)
        track = _track(data, track_id)
        old_aid = track["clips"][0]["asset"]
        if old_aid == asset["id"]:
            raise InputError(f"track '{track_id}' already uses asset '{asset['id']}'")
        old_len = mr.asset_length_at(_asset(data, old_aid), pr)
        new_len = mr.asset_length_at(asset, pr)
        swapped = []
        for c in track["clips"]:
            if c.get("asset") != old_aid:
                continue
            whole = int(c.get("source_start", 0) or 0) == 0 and c.get("length") in (None, old_len)
            c["asset"] = asset["id"]
            if whole and c.get("length") is not None:
                c["length"] = new_len
            swapped.append(c["id"])
        if not keep_chain:
            track["chain"] = []
            track["cleanup"] = {"enabled": True, "plan": "auto", "overrides": {}}
        diag = None
        if diagnose:
            path = (Path(src) if (not existing and asset.get("linked")) else
                    (Path(project.root) / asset["path"] if not asset.get("linked") else None))
            diag = diagnose_consistency(ref_music, asset_music(project, asset, path),
                                        timebase=project.data.get("timebase"))
            track["consistency"] = _consistency_summary(diag)
        unused = _refresh_unused(data)
        why = reason or f"stem replace: {track_id} {old_aid} -> {asset['id']} (chain {'kept' if keep_chain else 'cleared'})"
        seq = _commit(project, data, actor=actor, op="stem_replace", reason=why)
    except Exception:
        _cleanup_copies(project, rec, data)
        raise
    return _result("stem_replace", seq, track=track_id, old_asset=old_aid, asset=asset["id"], clips=swapped,
                   keep_chain=keep_chain, length_change=new_len - old_len, unused_assets=unused,
                   checks=_asset_checks(rec, asset["id"]) if rec else [], consistency=diag,
                   notes=_r22(project.data, [track_id]))


def stem_remove(project: Project, track_id: str, *, actor: str, reason: str = "") -> dict:
    """Remove a track. Its assets stay in the project and are flagged unused."""
    data = copy.deepcopy(project.data)
    _track(data, track_id)
    data["tracks"] = [t for t in data["tracks"] if t.get("id") != track_id]
    mix = data.get("mix") or {}
    if track_id in (mix.get("declared_depth_order") or []):
        mix["declared_depth_order"] = [t for t in mix["declared_depth_order"] if t != track_id]
    obj = data.get("objective") or {}
    if obj.get("lead_stem") == track_id:
        obj["lead_stem"] = None
    for v in data.get("variants") or []:
        if isinstance(v.get("track_overrides"), dict):
            v["track_overrides"].pop(track_id, None)
    unused = _refresh_unused(data)
    seq = _commit(project, data, actor=actor, op="stem_remove", reason=reason or f"stem remove: {track_id}")
    return _result("stem_remove", seq, track=track_id, unused_assets=unused)


def _split(data: dict, track: dict, clip: dict, at: int, taken: set[str]) -> tuple[dict, dict]:
    """Split ``clip`` at timeline sample ``at`` (strictly inside). Returns (left, right)."""
    ts = int(clip.get("timeline_start", 0) or 0)
    length = _clip_len(data, clip)
    if not ts < at < ts + length:
        raise InputError(f"split point {at} is not inside clip '{clip['id']}' ({ts}..{ts + length})")
    k = at - ts
    right = copy.deepcopy(clip)
    right["id"] = _new_id(data, f"{clip['id']}_b", taken)
    right["source_start"] = int(clip.get("source_start", 0) or 0) + k
    right["timeline_start"] = at
    right["length"] = length - k
    right["fade_in"] = 0
    right["fade_out"] = min(int(clip.get("fade_out", 0) or 0), length - k)
    clip["length"] = k
    clip["fade_out"] = 0
    clip["fade_in"] = min(int(clip.get("fade_in", 0) or 0), k)
    idx = next(i for i, c in enumerate(track["clips"]) if c is clip)
    track["clips"].insert(idx + 1, right)
    return clip, right


def clip_split(project: Project, clip_id: str, at_sample: int, *, actor: str, reason: str = "") -> dict:
    """Split a clip at a timeline position; the two halves play exactly as before."""
    at = _check_samples("at_sample", at_sample)
    data = copy.deepcopy(project.data)
    track, clip = _clip(data, clip_id)
    left, right = _split(data, track, clip, at, _all_ids(data))
    seq = _commit(project, data, actor=actor, op="clip_split", reason=reason or f"split {clip_id} at {at}")
    return _result("clip_split", seq, track=track["id"], left=left["id"], right=right["id"], at=at,
                   notes=_r22(project.data, [track["id"]]))


def _isolate_range(data: dict, track: dict, start: int, end: int) -> list[dict]:
    """Split the track's clips at start/end; return the clips lying inside [start, end)."""
    taken = _all_ids(data)
    for at in (start, end):
        for c in list(track.get("clips") or []):
            ts = int(c.get("timeline_start", 0) or 0)
            if ts < at < ts + _clip_len(data, c):
                _split(data, track, c, at, taken)
    inside = []
    for c in track.get("clips") or []:
        ts = int(c.get("timeline_start", 0) or 0)
        if ts >= start and ts + _clip_len(data, c) <= end and _clip_len(data, c) > 0:
            inside.append(c)
    return inside


def _range_args(start, end) -> tuple[int, int]:
    s, e = _check_samples("start", start), _check_samples("end", end)
    if e <= s:
        raise InputError("end must be greater than start")
    return s, e


def range_mute(project: Project, track_id: str, start: int, end: int, *, actor: str, reason: str = "") -> dict:
    """Mute [start, end) of a track: split the clips at the edges and mute the pieces inside."""
    s, e = _range_args(start, end)
    data = copy.deepcopy(project.data)
    track = _track(data, track_id)
    inside = _isolate_range(data, track, s, e)
    if not inside:
        raise InputError(f"track '{track_id}' has no clip inside {s}..{e}")
    for c in inside:
        c["muted"] = True
    seq = _commit(project, data, actor=actor, op="range_mute",
                  reason=reason or f"mute {track_id} {s}..{e}")
    return _result("range_mute", seq, track=track_id, start=s, end=e, muted_clips=[c["id"] for c in inside],
                   notes=_r22(project.data, [track_id]))


def range_replace(project: Project, track_id: str, start: int, end: int, src_asset_id: str, *,
                  source_start: int = 0, actor: str, reason: str = "") -> dict:
    """Mute [start, end) of a track and place a clip of another asset there (from ``source_start``)."""
    s, e = _range_args(start, end)
    ss = _check_samples("source_start", source_start)
    data = copy.deepcopy(project.data)
    track = _track(data, track_id)
    asset = _asset(data, src_asset_id)
    if asset.get("id") == data.get("fullmix_asset") or asset.get("origin") == "reference_fullmix":
        raise InputError("the full mix is a reference and cannot be placed on a stem track")
    pr = _rate(data)
    avail = mr.asset_length_at(asset, pr) - ss
    if avail <= 0:
        raise InputError(f"source_start {ss} is past the end of asset '{src_asset_id}'")
    inside = _isolate_range(data, track, s, e)
    for c in inside:
        c["muted"] = True
    cid = _new_id(data, f"clp_{track_id.removeprefix('trk_')}_r")
    new = {"id": cid, "asset": src_asset_id, "source_start": ss, "length": e - s, "timeline_start": s,
           "gain_db": 0.0, "fade_in": 0, "fade_out": 0, "muted": False}
    track.setdefault("clips", []).append(new)
    track["clips"].sort(key=lambda c: int(c.get("timeline_start", 0) or 0))
    _refresh_unused(data)
    seq = _commit(project, data, actor=actor, op="range_replace",
                  reason=reason or f"replace {track_id} {s}..{e} with {src_asset_id}@{ss}")
    warnings = []
    if avail < e - s:
        warnings.append(f"asset '{src_asset_id}' ends {e - s - avail} samples before the range end; "
                        "the rest is silence")
    return _result("range_replace", seq, track=track_id, start=s, end=e, clip=cid, asset=src_asset_id,
                   muted_clips=[c["id"] for c in inside], warnings=warnings,
                   notes=_r22(project.data, [track_id]))


def clip_move(project: Project, clip_id: str, timeline_start: int, *, actor: str, reason: str = "") -> dict:
    """Move a clip on the timeline (samples at the project rate)."""
    ts = _check_samples("timeline_start", timeline_start)
    data = copy.deepcopy(project.data)
    track, clip = _clip(data, clip_id)
    old = int(clip.get("timeline_start", 0) or 0)
    clip["timeline_start"] = ts
    seq = _commit(project, data, actor=actor, op="clip_move", reason=reason or f"move {clip_id} {old} -> {ts}")
    return _result("clip_move", seq, track=track["id"], clip=clip_id, old_timeline_start=old, timeline_start=ts,
                   notes=_r22(project.data, [track["id"]]))


def set_role(project: Project, track_id: str, role: str, *, is_lead: bool | None = None, actor: str,
             reason: str = "") -> dict:
    """Change a track's role and, optionally, make it (or stop it being) the single lead."""
    if role not in ROLE_VOCAB:
        raise InputError(f"unknown role '{role}'", details={"vocabulary": list(ROLE_VOCAB)})
    data = copy.deepcopy(project.data)
    track = _track(data, track_id)
    track["role"] = role
    imp = track.get("importance")
    if isinstance(imp, dict) and imp.get("source") == "default":
        from .adapters.file import DEFAULT_IMPORTANCE
        imp["value"] = DEFAULT_IMPORTANCE.get(role, 0.3)
    obj = data.get("objective") or {}
    if is_lead is True:
        for t in data.get("tracks") or []:
            if t.get("is_lead") and t is not track:
                t["is_lead"] = False
        track["is_lead"] = True
        obj["lead_stem"] = track_id
    elif is_lead is False:
        track["is_lead"] = False
        if obj.get("lead_stem") == track_id:
            obj["lead_stem"] = None
    seq = _commit(project, data, actor=actor, op="set_role",
                  reason=reason or f"role {track_id} -> {role}" + ("" if is_lead is None else f", lead={is_lead}"))
    return _result("set_role", seq, track=track_id, role=role, is_lead=bool(track.get("is_lead", False)),
                   lead=obj.get("lead_stem"))


_SUBTYPE_DEPTH = {"FLOAT": "32f", "PCM_24": 24, "PCM_16": 16}


def stem_export(project: Project, track_ids: list[str] | None = None, *, processed: bool = True,
                out_dir: str = "renders/stems", subtype: str = "FLOAT", variant_id: str | None = None,
                seed: int | None = None) -> dict:
    """Write one stereo WAV per track (full timeline from sample 0) plus ``manifest.json``.

    processed=True: the track as it sits in the mix (clips, chain, fader, pan;
    no bus processing, no sends), track mute/solo ignored. processed=False: the
    edited clip layout only (clip gains, fades, clip mutes; no chain, fader or
    pan). ``subtype``: FLOAT (32-bit float), PCM_24 or PCM_16 (TPDF dither with a
    fixed seed derived from the project, via the export module).
    Returns {files, manifest, tracks, notes, warnings}; all paths project-relative.
    Nothing in project.json changes (renders are regenerable).
    """
    if subtype not in _SUBTYPE_DEPTH:
        raise InputError(f"unsupported subtype '{subtype}'", details={"valid": list(_SUBTYPE_DEPTH)})
    problem = check_relpath(out_dir)
    if problem:
        raise InputError(f"out_dir: {problem}")
    data = project.data
    stems = [t["id"] for t in mr.stem_tracks(data)]
    ids = stems if track_ids is None else list(track_ids)
    for tid in ids:
        if tid not in stems:
            raise InputError(f"'{tid}' is not a stem track", details={"valid": stems})
    if not ids:
        raise InputError("no stem tracks to export")
    from mankomix.dsp import engine
    project_hash = project.content_hash()
    base_seed = engine.seed_from_hash(project_hash) if seed is None else int(seed)
    signals: dict[str, np.ndarray] = {}
    render_rec: dict
    if processed:
        ov = {t["id"]: {"muted": False, "solo": False} for t in data.get("tracks") or []
              if t.get("muted") or t.get("solo") or t["id"] in ids}
        _, sr, render_rec = mr.render_mix(project, variant_id=variant_id, seed=base_seed,
                                          stems_out=signals, overrides=ov, measure=False)
    else:
        render_rec = {"tracks": []}
        sr = mr.project_rate(data)
        for tid in ids:
            x, sr, r = mr.render_track(project, tid, seed=base_seed, apply_chain=False, apply_fader=False,
                                       variant_id=variant_id)
            signals[tid] = x
            render_rec["tracks"].append(r)
        render_rec["conform"] = render_rec["tracks"][0]["conform"] if render_rec["tracks"] else {}
    out_root = Path(project.root).joinpath(*out_dir.split("/"))
    delivery = {"id": f"stem_export_{subtype.lower()}", "container": "wav", "sample_rate": "native",
                "bit_depth": _SUBTYPE_DEPTH[subtype], "dither": "tpdf", "channels": 2}
    from .hashing import sha256_file
    files, entries, warnings = [], [], []
    by_track = {t["id"]: t for t in data.get("tracks") or []}
    for tid in ids:
        x = signals.get(tid)
        if x is None:
            raise ValidationError(f"track '{tid}' produced no signal")
        path = out_root / f"{tid}.wav"
        w = engine.export_audio(x, sr, delivery, path, seed=engine.seed_from_hash(f"{project_hash}:{tid}")
                                if seed is None else base_seed)
        rel = project.rel(path)
        files.append(rel)
        warnings += [f"{tid}: {m}" for m in w.get("warnings") or []]
        assets = sorted({c.get("asset") for c in by_track[tid].get("clips") or []})
        entries.append({"track": tid, "role": by_track[tid].get("role"), "file": rel,
                        "sha256": sha256_file(path), "frames": w["frames"], "sample_rate": w["sample_rate"],
                        "bit_depth": w["bit_depth"], "dithered": w["dithered"],
                        "sample_peak_dbfs": w["sample_peak_dbfs"], "true_peak_dbtp": w["true_peak_dbtp"],
                        "assets": assets})
    notes = _r22(data, ids)
    by_asset = {a["id"]: a for a in data.get("assets") or []}
    used_assets = sorted({a for e in entries for a in e["assets"]})
    manifest = {
        "kind": "stem_export",
        "engine_version": mankomix.ENGINE_VERSION,
        "project_id": data.get("id"),
        "project_hash": project_hash,
        "variant": variant_id,
        "processed": processed,
        "definition": ("track as it sits in the mix: clips, chain, fader, pan; no bus processing, no sends"
                       if processed else "edited clip layout only: clip gain, fades, clip mutes; no chain, "
                                         "fader or pan"),
        "alignment": "every file starts at timeline sample 0",
        "sample_rate": sr,
        "subtype": subtype,
        "seed": None if seed is None else base_seed,
        "seed_rule": "seed_from_hash(project_hash + ':' + track_id)" if seed is None else "fixed",
        "pan_law_center_db": (data.get("mix") or {}).get("pan_law_center_db"),
        "assets": [{"id": a, "sha256": by_asset.get(a, {}).get("sha256"), "origin": by_asset.get(a, {}).get("origin")}
                   for a in used_assets],
        "conform": render_rec.get("conform"),
        "backends": render_rec.get("backends", {}),
        "files": entries,
        "notes": notes,
        "warnings": warnings,
    }
    out_root.mkdir(parents=True, exist_ok=True)
    mpath = out_root / "manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"op": "stem_export", "files": files, "manifest": project.rel(mpath), "tracks": ids,
            "processed": processed, "sample_rate": sr, "subtype": subtype, "notes": notes, "warnings": warnings}


__all__ = [
    "stem_list", "stem_add", "stem_replace", "stem_remove", "clip_split", "range_mute", "range_replace",
    "clip_move", "set_role", "stem_export", "diagnose_consistency", "project_music", "asset_music",
    "ROLE_VOCAB", "BPM_TOLERANCE_PCT",
]
