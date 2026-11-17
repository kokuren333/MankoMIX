"""Direction documents: parse, validate, apply and check (minimal version; v2 I-2, I-4, I-6).

A direction is a Markdown file written by the director (the PM layer) with
exactly one ```json direction fenced block (contract: ``docs/DIRECTION_FORMAT.md``).
This module turns its moves into the existing pipeline's inputs and checks
what came out. The core never imports it; it only calls the public API.

- ``validate``: shape, op / required fields, processor parameter ranges, the
  invariant area (v2 f.2), quantity references, the review tier E1-E3
- ``apply``: the moves on top of the floor mix -> one ``mxp_`` proposal with a
  ``move_ref`` on every item the direction adds or changes -> the existing
  ``plan apply``; ``cleanup_override`` -> the existing ``clean plan --apply``;
  ``master_target`` is returned for ``master plan --target-lufs``
- ``check``: claims and expectations against the floor (level matched),
  ``move_ref`` coverage, the gate definition hash before/after, convergence
  with the floor -> ``directions/dir_<id>.outcome.json``

Nothing here relaxes a gate: thresholds, profiles and the master chain are
never written.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from mankomix import repo_data_root
from mankomix.core import audio_io
from mankomix.core.hashing import canonical_hash
from mankomix.dsp import processors as P

from . import kb as kbmod
from . import query as Q
from . import stemobs as S

FORMAT_VERSION = 1
OWNER = "director"
DIRECTIONS_DIR = "directions"

OPS = {
    "chain_add": ("mix", ("target", "processor", "params")),
    "chain_param": ("mix", ("target", "replaces", "params")),
    "chain_remove": ("mix", ("target", "replaces")),
    "gain": ("mix", ("target", "params")),
    "gain_curve": ("mix", ("target", "params")),
    "pan": ("mix", ("target", "params")),
    "send": ("mix", ("target", "params")),
    "bus_add": ("mix", ("target", "params")),
    "cleanup_override": ("clean", ("target", "params")),
    "master_target": ("master", ("params",)),
    # the edit (declutter) stage (UPGRADE2 §1): optional, decided and applied before every other move
    "edit_trim": ("edit", ("target", "params")),
    "edit_gate": ("edit", ("target", "params")),
    # cross-track ducking (UPGRADE2 §2): gain automation on the target keyed by another track's hits
    "duck": ("mix", ("target", "params")),
    "duck_curve": ("mix", ("target", "params")),
    # placement (FBREVIEW FR-5): azimuth / width / distance -> pan, fader, air shelf and a room send,
    # expanded into the existing pan / gain / chain_add / send moves
    "place": ("mix", ("target", "params")),
}
EDIT_OPS = ("edit_trim", "edit_gate")
from . import xops as X

def _edit_ops():
    return EDIT_OPS + tuple(name for name, spec in X.specs(OPS).items() if spec.stage == "edit")


# place parameters (FR-5): id -> (lo, hi, default, a range [lo, hi] + select allowed); room is a bus id
PLACE_PARAMS = {
    "azimuth": (-1.0, 1.0, None, True),
    "width": (0.0, 2.0, None, True),
    "distance": (1.0, 8.0, None, True),
    "level_db_per_doubling": (0.0, 6.0, 2.0, False),
    "air_db_per_doubling": (0.0, 3.0, 1.0, False),
    "air_freq_hz": (2000.0, 10000.0, 5000.0, False),
    "near_send_db": (-40.0, -12.0, -24.0, False),
    "send_db_per_doubling": (0.0, 6.0, 4.0, False),
}
PLACE_MODEL = ("level_db_per_doubling", "air_db_per_doubling", "air_freq_hz", "near_send_db", "send_db_per_doubling")
PLACE_SEND_MAX_DB = -3.0
PLACE_SHELF_BW_OCT = 1.9
SELECTS = ("mid", "min", "max")
DIRECTIONS = ("up", "down", "not_worse")
MASTER_ONLY = ("limiter", "clipper", "dither", "resample", "loudness_gain")
# keys that belong to the invariant area (v2 f.2); a direction may not carry them anywhere
FORBIDDEN_KEYS = ("plan_margin_db", "ceiling_dbtp", "window_lufs_i", "target_lufs_i", "max_gr_db", "gr_p95_max_db",
                  "deadband", "deadband_db", "guard_terms", "thresholds", "codec_checks", "true_peak",
                  "dither", "limiter")
GATE_DEFINITIONS = ("knowledge/thresholds.json", "knowledge/rules.json", "knowledge/objective_metrics.json",
                    "profiles/media_profiles.json", "knowledge/mix_rules.json")
LEAD = "trk_vocals"
from mankomix.dspx.registry import time_varying_types

TIME_VARYING = frozenset(("compressor", "dynamic_eq", "deesser", "aw.pressure4")) | time_varying_types()
RAMP_S = 0.02
_FENCE_RE = re.compile(r"^```json[ \t]+direction[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
_P_RE = re.compile(r"^P-\d{2}(:[a-z][a-z0-9_]*)?$")   # P-nn or P-nn:<qualifier> (e.g. P-02:vs_lead)
# optional fields of the reference (原液) path (UPDATE_PROPOSAL §1.4); the form only, not the kb contents
ORIGINS = ("catalog", "case", "new", "reference")
_SLUG = r"[a-z0-9][a-z0-9_-]*"
_WORK_RE = re.compile(rf"^work_{_SLUG}$")
_LIKE_RE = re.compile(rf"^(work|eng)_{_SLUG}$")
# Only the slug characters right after "ref:" are taken, so the free-text basis may go on with any
# delimiter ("ref:work_x、§4", "（ref:work_x）の読み", "ref:work_x§4"). A non-work id is bad_ref.
# Only a "ref:" directly followed by at least one slug character is checked: "ref: work_x §4",
# "cf. ref: none" or a bare "ref:" are prose, not a reference basis (GATE_R2 N-a).
# The front boundary is ASCII-only: Python's \b treats Japanese letters as word characters, so
# "の読みref:eng_x" would escape the check; "xref:" / "_ref:" stay out of scope as before.
_REF_BASIS_RE = re.compile(r"(?<![A-Za-z0-9_])ref:([A-Za-z0-9_-]+)")
_SHA_RE = re.compile(r"^[0-9a-f]{16,64}$")


class DirectionError(ValueError):
    pass


# ---------------------------------------------------------------------------
# documents and ids
# ---------------------------------------------------------------------------

def canonical_block(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def direction_id(block: dict) -> str:
    return "dir_" + hashlib.sha256(canonical_block(block).encode("utf-8")).hexdigest()[:12]


def body_after_front_matter(raw: bytes) -> bytes:
    """Bytes after the line that closes the front matter (the 2nd '---' line); all bytes if none."""
    lines = raw.splitlines(keepends=True)
    seen = 0
    pos = 0
    for ln in lines:
        pos += len(ln)
        if ln.strip() == b"---":
            seen += 1
            if seen == 2:
                return raw[pos:]
    return raw


def analysis_id(raw: bytes) -> str:
    return "ana_" + hashlib.sha256(body_after_front_matter(raw)).hexdigest()[:12]


def parse_document(path: str | Path) -> dict:
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    try:
        meta, _ = kbmod.parse_front_matter(text)
    except kbmod.FrontMatterError as e:
        raise DirectionError(f"front matter: {e}") from None
    blocks = _FENCE_RE.findall(text.replace("\r\n", "\n"))
    if len(blocks) != 1:
        raise DirectionError(f"a direction needs exactly one ```json direction block (found {len(blocks)})")
    try:
        block = json.loads(blocks[0])
    except ValueError as e:
        raise DirectionError(f"the direction block is not valid JSON: {e}") from None
    if not isinstance(block, dict):
        raise DirectionError("the direction block must be a JSON object")
    return {"path": path, "raw": raw, "meta": meta or {}, "block": block, "id": direction_id(block)}


# ---------------------------------------------------------------------------
# context: the project the direction is applied to
# ---------------------------------------------------------------------------

def _read_json(p: Path) -> Any:
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


class _Project:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        pj = self.root / "project.json"
        if not pj.is_file():
            raise DirectionError("no project.json in the project folder")
        self.data = _read_json(pj)
        mix = self.data.get("mix") or {}
        self.floor_mxp_id = (mix.get("applied") or {}).get("proposal_id")
        self.floor_mxp = None
        if self.floor_mxp_id:
            f = self.root / "cache" / "proposals" / f"{self.floor_mxp_id}.json"
            if f.is_file():
                self.floor_mxp = _read_json(f)

    @property
    def rate(self) -> int:
        tb = self.data.get("timebase") or {}
        return int(tb.get("sample_rate") or tb.get("rate") or 48000)

    def tracks(self) -> dict:
        return {t.get("id"): t for t in self.data.get("tracks") or []}

    def buses(self) -> dict:
        return {b.get("id"): b for b in self.data.get("buses") or []}

    def sections(self) -> list[dict]:
        return list((self.floor_mxp or {}).get("sections") or [])

    def variant(self, vid: str | None = None) -> dict | None:
        vs = self.data.get("variants") or []
        if vid is None:
            return vs[0] if vs else None
        return next((v for v in vs if v.get("id") == vid), None)

    def floor_items(self) -> dict:
        """processor id -> (holder kind, holder id) for every chain item now in the project."""
        out = {}
        for t in self.data.get("tracks") or []:
            for it in t.get("chain") or []:
                out[it.get("id")] = ("track", t.get("id"))
        for b in self.data.get("buses") or []:
            for it in b.get("chain") or []:
                out[it.get("id")] = ("bus", b.get("id"))
        return out


def _profile(pid: str) -> dict | None:
    from mankomix.core import config
    try:
        return config.get_profile(pid)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

# processor parameters whose value is a list (stereo crossovers_hz / widths): a 2-item list of numbers is
# such a value, never a range [lo, hi], so they are passed through as written and cannot be calibrated.
# Computed over the built-in types only, so extension types cannot change how built-in moves resolve.
from mankomix.dspx.registry import specs as _dspx_specs

_DSPX_TYPES = frozenset(d["type"] for d in _dspx_specs())
ARRAY_PARAM_IDS = frozenset(p["id"] for t, spec in P.PROCESSORS.items() if t not in _DSPX_TYPES
                            for p in spec.get("params") or [] if p.get("type") == "float_array")
_BUILTIN_TYPES = frozenset(t for t in P.PROCESSORS if t not in _DSPX_TYPES)


def _array_param_ids(ptype: str | None) -> frozenset:
    """List/curve parameter IDs for a move's processor type. Built-in types, unknown types and moves
    without a type keep the original global set (byte-identical behaviour for existing directions);
    an extension type uses only its own declared list and curve parameters."""
    if ptype is None or ptype in _BUILTIN_TYPES or ptype not in P.PROCESSORS:
        return ARRAY_PARAM_IDS
    return frozenset(p["id"] for p in P.PROCESSORS[ptype].get("params") or []
                     if p.get("type") in ("float_array", "curve"))


def _move_processor(move: dict, proj=None) -> str | None:
    ptype = move.get("processor") or move.get("type")
    if ptype is None and move.get("op") == "chain_param" and proj is not None:
        holder = {**proj.tracks(), **proj.buses()}.get(move.get("target")) or {}
        item = next((c for c in holder.get("chain") or [] if c.get("id") == move.get("replaces")), {})
        ptype = item.get("type")
    return ptype


def _is_range(v: Any) -> bool:
    return (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                         for x in v))


def _select_of(move: dict, key: str) -> str:
    sel = move.get("select")
    if isinstance(sel, dict):
        return str(sel.get(key, "mid"))
    if isinstance(sel, str):
        return sel
    return "mid"


def resolve_params(move: dict, params: dict | None, sel: dict | None = None,
                   prefix: str | None = None, *, ptype: str | None = None) -> tuple[dict, list[str]]:
    """Ranges [lo, hi] -> one value by ``select`` (mid / min / max; sweep:* falls back to mid in v0).

    ``sel``: values chosen by calibration, keyed ``<prefix>.<param>`` (prefix: the move id, or
    ``<move id>.chain<i>`` for a bus_add chain item); a chosen value must lie inside the range.
    ``ptype`` supplies processor context for nested chain items or chain_param moves.
    Without it the move's processor (or its original bus child) supplies the type."""
    out, notes = {}, []
    if ptype is None:
        ptype = _move_processor(move)
        if ptype is None and move.get("op") == "bus_add":
            child = next((c for c in (move.get("params") or {}).get("chain") or []
                          if c.get("params") is params), {})
            ptype = child.get("type") or child.get("processor")
    array_ids = _array_param_ids(ptype)
    for k, v in (params or {}).items():
        if _is_range(v) and k not in array_ids:
            lo, hi = float(min(v)), float(max(v))
            kid = f"{prefix or move.get('id')}.{k}"
            if sel is not None and kid in sel:
                val = float(sel[kid])
                if not lo - 1e-9 <= val <= hi + 1e-9:
                    raise DirectionError(f"{kid}: chosen value {val} is outside the declared range [{lo}, {hi}]")
                out[k] = round(val, 4)
                continue
            s = _select_of(move, k)
            if s.startswith("sweep:"):
                notes.append(f"{move.get('id')}.{k}: '{s}' is not implemented in v0; the middle of the range is used")
                s = "mid"
            val = {"min": lo, "max": hi}.get(s, (lo + hi) / 2.0)
            if isinstance(v[0], int) and isinstance(v[1], int) and float(val).is_integer():
                val = int(val)
            out[k] = round(val, 4) if isinstance(val, float) else val
        else:
            out[k] = v
    return out, notes


def _walk_keys(o: Any, path: str = ""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield f"{path}.{k}" if path else k, k
            yield from _walk_keys(v, f"{path}.{k}" if path else k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk_keys(v, f"{path}[{i}]")


def _rule_ids() -> set[str]:
    ids: set[str] = set()
    root = repo_data_root() / "knowledge"
    for name in ("rules.json", "mix_rules.json"):
        p = root / name
        if p.is_file():
            ids |= set(re.findall(r'"(R-\d{2})"', p.read_text(encoding="utf-8")))
    return ids


def _ends(params: dict, ptype: str | None = None) -> list[dict]:
    """The parameter sets at both ends of every range (both ends must be inside the declared range)."""
    array_ids = _array_param_ids(ptype)
    if not any(_is_range(v) and k not in array_ids for k, v in params.items()):
        return [params]
    lo = {k: (min(v) if _is_range(v) and k not in array_ids else v) for k, v in params.items()}
    hi = {k: (max(v) if _is_range(v) and k not in array_ids else v) for k, v in params.items()}
    return [lo, hi]


def _check_proc_params(ptype: str, params: dict, stage: str, where: str, errors: list) -> dict | None:
    ends = _ends(params, ptype)
    if len(ends) > 1:
        res = None
        for e in ends:
            res = _check_proc_params(ptype, e, stage, where, errors)
            if res is None:
                return None
        return res
    if ptype not in P.PROCESSORS:
        errors.append({"where": where, "code": "unknown_processor", "message": f"unknown processor '{ptype}'"})
        return None
    stages = P.PROCESSORS[ptype].get("stages") or []
    if stage not in stages:
        errors.append({"where": where, "code": "processor_stage",
                       "message": f"processor '{ptype}' cannot run on a {stage} (stages: {', '.join(stages)})"})
        return None
    try:
        return P.validate_params(ptype, params)
    except (ValueError, TypeError) as e:
        errors.append({"where": where, "code": "param_range", "message": str(e)})
        return None


def _holder_stage(target: str) -> str:
    return "bus" if str(target).startswith("bus_") else "track"


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def place_derive(params: dict) -> dict:
    """The derivation of FR-5 for resolved (single-value) place parameters.

    -> {"model": {5 coefficients}, "derived": {...}, "moves": [(op, processor, params)]}; the moves are
    the existing ops the place stands for (nothing for a zero delta / shelf, no send without room)."""
    model = {k: float(params[k]) if k in params else float(PLACE_PARAMS[k][2]) for k in PLACE_MODEL}
    az, wd, dist, room = params.get("azimuth"), params.get("width"), params.get("distance"), params.get("room")
    moves: list[tuple] = []
    derived = {"position": None if az is None else round(float(az), 2),
               "width": None if wd is None else round(float(wd), 2),
               "delta_db": None, "air_gain_db": None, "send_level_db": None, "send_clamped": None}
    pan = {k: derived[k] for k in ("position", "width") if derived[k] is not None}
    if pan:
        moves.append(("pan", None, pan))
    if dist is not None:
        L = math.log2(float(dist))
        delta = round(-model["level_db_per_doubling"] * L, 2) + 0.0
        air = round(-model["air_db_per_doubling"] * L, 2) + 0.0
        derived["delta_db"], derived["air_gain_db"] = delta, air
        if delta != 0.0:
            moves.append(("gain", None, {"delta_db": delta}))
        if air != 0.0:
            moves.append(("chain_add", "eq", {"shape": "high_shelf", "freq_hz": model["air_freq_hz"],
                                              "gain_db": air, "bw_oct": PLACE_SHELF_BW_OCT, "phase": "minimum"}))
        if room is not None:
            raw = model["near_send_db"] + model["send_db_per_doubling"] * L
            lvl = round(min(raw, PLACE_SEND_MAX_DB), 2) + 0.0
            derived["send_level_db"], derived["send_clamped"] = lvl, raw > PLACE_SEND_MAX_DB
            moves.append(("send", None, {"bus": room, "level_db": lvl, "pre_fader": False}))
    return {"model": model, "derived": derived, "moves": moves}


def _check_place(m: dict, b: dict, where: str, err, *, proj, tracks: dict, buses: dict, errors: list) -> None:
    """Form, ranges and the expanded moves of one place move (FR-5, G-2). Conflicts are checked by the caller."""
    target = m.get("target")
    raw = m.get("params")
    new_buses = {x.get("target") for x in b.get("moves") or [] if x.get("op") == "bus_add"}
    if target == "master" or str(target).startswith("bus_") or target in buses or target in new_buses:
        err(where, "bad_target", "'place' needs a track target")
    elif proj and target not in tracks:
        err(where, "unknown_target", f"unknown target '{target}'")
    if not isinstance(raw, dict):
        return
    unknown = sorted(set(raw) - set(PLACE_PARAMS) - {"room"})
    if unknown:
        err(where, "bad_value", f"unknown place parameters: {', '.join(unknown)}")
    if not ({"azimuth", "width", "distance"} & set(raw)):
        err(where, "missing_field", "place needs azimuth, width and/or distance")
    if "room" in raw:
        room = raw["room"]
        if "distance" not in raw:
            err(f"{where}.room", "missing_field", "room needs distance (the send level follows the distance)")
        if not isinstance(room, str) or not room.startswith("bus_"):
            err(f"{where}.room", "bad_value", f"room must be a bus id (got {room!r})")
        elif proj and room not in buses and room not in new_buses:
            err(f"{where}.room", "unknown_target", f"unknown bus '{room}'")
    ok = True
    for k, (lo, hi, _dflt, ranged) in PLACE_PARAMS.items():
        if k not in raw:
            continue
        v = raw[k]
        vals = None
        if _is_range(v):
            if ranged:
                vals = [float(x) for x in v]
            else:
                err(f"{where}.{k}", "bad_value", f"{k} takes one value (only azimuth / width / distance take a range)")
        elif _num(v):
            vals = [float(v)]
        else:
            err(f"{where}.{k}", "bad_value", f"{k} must be a number" + (" or a range [lo, hi]" if ranged else ""))
        if vals is None:
            ok = False
            continue
        if any(not math.isfinite(x) or not lo <= x <= hi for x in vals):
            err(f"{where}.{k}", "param_range", f"{k} {v} outside [{lo:g}, {hi:g}]")
            ok = False
    if not ok or not isinstance(raw.get("room", ""), str):
        return
    # the expanded moves go through the existing range checks (a range: both ends)
    for end in _ends({k: v for k, v in raw.items()}):
        for op, ptype, p in place_derive(end)["moves"]:
            if op == "pan":
                if "position" in p and not -1.0 <= p["position"] <= 1.0:
                    err(where, "param_range", "position must be in [-1, 1]")
                if "width" in p and not 0.0 <= p["width"] <= 2.0:
                    err(where, "param_range", "width must be in [0, 2]")
            elif op == "gain":
                if not -24.0 <= p["delta_db"] <= 12.0:
                    err(where, "param_range", f"delta_db {p['delta_db']} outside [-24, 12]")
            elif op == "chain_add":
                _check_proc_params(ptype, p, "track", where, errors)
            elif op == "send":
                if not -60.0 <= p["level_db"] <= 6.0:
                    err(where, "param_range", "level_db must be in [-60, 6]")


def _place_conflicts(moves: list, err) -> None:
    """The four conflicts of FR-5 (on one track): two places; a place with azimuth / width and a pan; a place
    with distance and a gain without a section; a place with room and a send to the same bus."""
    places = [m for m in moves if isinstance(m, dict) and m.get("op") == "place" and isinstance(m.get("params"), dict)]
    seen: dict = {}
    for m in places:
        t, p, where = m.get("target"), m["params"], f"moves.{m.get('id')}"
        if t in seen:
            err(where, "conflict", f"two place moves on '{t}' ({seen[t]} and {m.get('id')})")
        else:
            seen[t] = m.get("id")
        for x in moves:
            if not isinstance(x, dict) or x.get("target") != t:
                continue
            xp = x.get("params") if isinstance(x.get("params"), dict) else {}
            if x.get("op") == "pan" and ({"azimuth", "width"} & set(p)):
                err(where, "conflict", f"place with azimuth / width and pan {x.get('id')} on '{t}'")
            elif x.get("op") == "gain" and "distance" in p and x.get("section") in (None, "all"):
                err(where, "conflict", f"place with distance and gain {x.get('id')} (no section) on '{t}'")
            elif x.get("op") == "send" and "room" in p and xp.get("bus") == p.get("room"):
                err(where, "conflict", f"place with room '{p.get('room')}' and send {x.get('id')} to the same bus on '{t}'")


def _validate_reference_fields(b: dict, err) -> None:
    """The optional fields of the reference path: request.like, sources.references.

    Only the form is checked (ids look like work_<slug> / eng_<slug>, hashes are hex); whether the
    cards exist in a kb is not checked, and an empty or missing list is never reported (U-17)."""
    req = b.get("request")
    if isinstance(req, dict) and "like" in req:
        like = req["like"]
        if not isinstance(like, list):
            err("request.like", "bad_value", "request.like must be a list of work_<slug> / eng_<slug> ids")
        else:
            for i, x in enumerate(like):
                if not isinstance(x, str) or not _LIKE_RE.match(x):
                    err(f"request.like[{i}]", "bad_ref", f"{x!r} is not a work_<slug> / eng_<slug> id")
    src = b.get("sources")
    if isinstance(src, dict) and "references" in src:
        refs = src["references"]
        if not isinstance(refs, list):
            err("sources.references", "bad_value", "sources.references must be a list")
            return
        for i, r in enumerate(refs):
            where = f"sources.references[{i}]"
            if not isinstance(r, dict):
                err(where, "bad_value", "each reference is an object {work, study_sha256, refsheet_sha256}")
                continue
            if not isinstance(r.get("work"), str) or not _WORK_RE.match(r["work"]):
                err(f"{where}.work", "bad_ref", f"work must be a work_<slug> id (got {r.get('work')!r})")
            for k in ("study_sha256", "refsheet_sha256"):
                v = r.get(k)
                if v is not None and (not isinstance(v, str) or not _SHA_RE.match(v)):
                    err(f"{where}.{k}", "bad_value", f"{k} must be a lowercase hex SHA-256 (16 to 64 digits) or null")
            extra = sorted(set(r) - {"work", "study_sha256", "refsheet_sha256"})
            if extra:
                err(where, "bad_value", f"unknown keys in a reference: {', '.join(extra)}")


SCENE_KEYS = ("note", "sources")
SCENE_SOURCE_KEYS = ("track", "azimuth", "depth", "note")
SCENE_MAX_SOURCES = 32
SCENE_DEPTH = (1, 5)


def _check_scene(sc: Any, err, *, tracks: dict, has_project: bool, buses: dict, moves: list) -> None:
    """Form and range of the optional ``scene`` (FBREVIEW FR-4, G-2). Never checked: whether every
    track is listed, whether the moves follow it, whether the result matches it."""
    if not isinstance(sc, dict):
        err("scene", "bad_value", "scene must be an object {note?, sources}")
        return
    extra = sorted(set(sc) - (set(SCENE_KEYS) | {"room"}))
    if extra:
        err("scene", "bad_value", f"unknown keys in scene: {', '.join(extra)}")
    if "room" in sc:
        room = sc["room"]
        if not isinstance(room, dict):
            # Preserve the original rejection location for non-object room declarations.
            err("scene", "bad_value", "scene.room must be an object {note, bus?}")
        else:
            _declaration_object(room, "scene.room", ("note", "bus"), err, ("note",))
            if "note" in room:
                _declaration_text(room["note"], "scene.room.note", err)
            if "bus" in room:
                bus = room["bus"]
                if not isinstance(bus, str) or not bus.startswith("bus_"):
                    err("scene.room.bus", "bad_value", "bus must be an id starting with 'bus_'")
                elif has_project and bus not in buses and not any(
                        m.get("op") == "bus_add" and m.get("target") == bus for m in moves):
                    err("scene.room.bus", "unknown_target", f"unknown bus '{bus}'")
    if "note" in sc and not isinstance(sc["note"], str):
        err("scene.note", "bad_value", "scene.note must be a string")
    if "sources" not in sc:
        err("scene.sources", "missing_field", "scene needs sources (1 to 32 entries)")
        return
    srcs = sc["sources"]
    if not isinstance(srcs, list):
        err("scene.sources", "bad_value", "scene.sources must be a list")
        return
    if not 1 <= len(srcs) <= SCENE_MAX_SOURCES:
        err("scene.sources", "param_range", f"scene.sources needs 1 to {SCENE_MAX_SOURCES} entries (found {len(srcs)})")
    seen: set = set()
    for i, s in enumerate(srcs):
        where = f"scene.sources[{i}]"
        if not isinstance(s, dict):
            err(where, "bad_value", "each source is an object {track, azimuth?, depth?, note?}")
            continue
        extra = sorted(set(s) - set(SCENE_SOURCE_KEYS))
        if extra:
            err(where, "bad_value", f"unknown keys in a scene source: {', '.join(extra)}")
        t = s.get("track")
        if "track" not in s:
            err(f"{where}.track", "missing_field", "a scene source needs track")
        elif not S.is_track_target(t):
            err(f"{where}.track", "bad_value", f"track must be a track id (trk_<stem>), not {t!r}")
        elif t in seen:
            err(f"{where}.track", "bad_id", f"track '{t}' is listed twice in scene.sources")
        else:
            seen.add(t)
            if has_project and t not in tracks:
                err(f"{where}.track", "unknown_target", f"unknown track '{t}'")
        if "azimuth" in s:
            a = s["azimuth"]
            if not _num(a):
                err(f"{where}.azimuth", "bad_value", "azimuth must be a number in [-1, 1]")
            elif not -1.0 <= float(a) <= 1.0:
                err(f"{where}.azimuth", "param_range", f"azimuth {a} outside [-1, 1]")
        if "depth" in s:
            d = s["depth"]
            if not isinstance(d, int) or isinstance(d, bool):
                err(f"{where}.depth", "bad_value", "depth must be an integer 1 to 5 (1 = front)")
            elif not SCENE_DEPTH[0] <= d <= SCENE_DEPTH[1]:
                err(f"{where}.depth", "param_range", f"depth {d} outside [1, 5]")
        if "azimuth" not in s and "depth" not in s:
            err(where, "missing_field", "a scene source needs azimuth and/or depth")
        if "note" in s and not isinstance(s["note"], str):
            err(f"{where}.note", "bad_value", "note must be a string")


def _declaration_object(value: Any, where: str, keys: tuple, err, required: tuple = ()) -> bool:
    if not isinstance(value, dict):
        err(where, "bad_value", f"{where} must be an object")
        return False
    extra = sorted(set(value) - set(keys))
    if extra:
        err(where, "bad_value", f"unknown keys in {where}: {', '.join(extra)}")
    for key in required:
        if key not in value:
            err(f"{where}.{key}", "missing_field", f"{where} needs {key}")
    return True


def _declaration_list(value: Any, where: str, limit: int, err) -> list:
    if not isinstance(value, list):
        err(where, "bad_value", f"{where} must be a list")
        return []
    if len(value) > limit:
        err(where, "param_range", f"{where} allows at most {limit} entries (found {len(value)})")
    return value


def _declaration_text(value: Any, where: str, err) -> None:
    if not isinstance(value, str):
        err(where, "bad_value", f"{where} must be a string")
    elif len(value) > 400:
        err(where, "param_range", f"{where} allows at most 400 characters")


def _declaration_track(value: Any, where: str, err, tracks: dict, has_project: bool) -> None:
    if not S.is_track_target(value):
        err(where, "bad_value", f"track must be a track id (trk_<stem>), not {value!r}")
    elif has_project and value not in tracks:
        err(where, "unknown_target", f"unknown track '{value}'")


def _declaration_time(value: Any, where: str, err) -> None:
    if not _num(value):
        err(where, "bad_value", f"{where} must be a finite number")
    elif value < 0:
        err(where, "param_range", f"{where} must be nonnegative")


def _check_frame(fr: Any, err, *, obs: dict, tracks: dict, sections: set, has_project: bool) -> None:
    """X-01 / G-1: declarations only; no coverage, move consistency or review tier checks."""
    keys = ("lead", "yield", "keep", "roughness_ok", "scale", "era", "key_words", "mono_keep",
            "section_roles", "tolerances")
    if not _declaration_object(fr, "frame", keys, err):
        return
    for key in ("lead", "scale"):
        if key in fr:
            _declaration_text(fr[key], f"frame.{key}", err)
    for key in ("yield", "keep", "roughness_ok"):
        if key in fr:
            for i, value in enumerate(_declaration_list(fr[key], f"frame.{key}", 16, err)):
                _declaration_text(value, f"frame.{key}[{i}]", err)
    if "era" in fr and _declaration_object(fr["era"], "frame.era", ("year", "genre", "stance"), err):
        era = fr["era"]
        if "year" in era:
            year = era["year"]
            if not isinstance(year, int) or isinstance(year, bool):
                err("frame.era.year", "bad_value", "year must be an integer 1900 to 2100")
            elif not 1900 <= year <= 2100:
                err("frame.era.year", "param_range", "year must be in [1900, 2100]")
        for key in ("genre", "stance"):
            if key in era:
                _declaration_text(era[key], f"frame.era.{key}", err)
    if "key_words" in fr:
        for i, value in enumerate(_declaration_list(fr["key_words"], "frame.key_words", 64, err)):
            where = f"frame.key_words[{i}]"
            if not _declaration_object(value, where, ("t_s", "text"), err, ("text",)):
                continue
            if "text" in value:
                _declaration_text(value["text"], f"{where}.text", err)
            if "t_s" in value:
                _declaration_time(value["t_s"], f"{where}.t_s", err)
    if "mono_keep" in fr:
        for i, value in enumerate(_declaration_list(fr["mono_keep"], "frame.mono_keep", 16, err)):
            _declaration_track(value, f"frame.mono_keep[{i}]", err, tracks, has_project)
    if "section_roles" in fr:
        vocabulary = ("lead_melody", "counter", "rhythm", "harmony_bed", "ornament", "double",
                      "harmony_vocal", "call_response", "unknown")
        for i, value in enumerate(_declaration_list(fr["section_roles"], "frame.section_roles", 64, err)):
            where = f"frame.section_roles[{i}]"
            if not _declaration_object(value, where, ("section", "lead", "roles"), err, ("section", "roles")):
                continue
            if "section" in value:
                sec = value["section"]
                sw = f"{where}.section"
                # Same section ids / explicit time pair as moves, without audio-length requirements.
                if isinstance(sec, str) and sec:
                    if sec != "all" and has_project and sec not in sections:
                        err(sw, "unknown_section", f"unknown section '{sec}'")
                elif isinstance(sec, dict):
                    _declaration_object(sec, sw, ("t0_s", "t1_s"), err, ("t0_s", "t1_s"))
                    for key in ("t0_s", "t1_s"):
                        if key in sec:
                            _declaration_time(sec[key], f"{sw}.{key}", err)
                    if (all(_num(sec.get(key)) and sec[key] >= 0 for key in ("t0_s", "t1_s"))
                            and sec["t0_s"] >= sec["t1_s"]):
                        err(sw, "param_range", "a time section needs t0_s < t1_s")
                else:
                    err(sw, "bad_value", "section must be a section id or {t0_s, t1_s}")
            if "lead" in value:
                _declaration_track(value["lead"], f"{where}.lead", err, tracks, has_project)
            if "roles" in value:
                roles = value["roles"]
                if not isinstance(roles, dict):
                    err(f"{where}.roles", "bad_value", "roles must be an object mapping track ids to role lists")
                else:
                    for track, role_list in roles.items():
                        rw = f"{where}.roles.{track}"
                        _declaration_track(track, rw, err, tracks, has_project)
                        for j, role in enumerate(_declaration_list(role_list, rw, 16, err)):
                            if role not in vocabulary:
                                err(f"{rw}[{j}]", "bad_value", f"role must be one of {', '.join(vocabulary)}")
    if "tolerances" in fr:
        for i, value in enumerate(_declaration_list(fr["tolerances"], "frame.tolerances", 16, err)):
            where = f"frame.tolerances[{i}]"
            if not _declaration_object(value, where, ("quantity", "range", "note"), err, ("quantity", "range")):
                continue
            if "quantity" in value:
                qty = value["quantity"]
                if not isinstance(qty, str) or not qty.startswith("obs:") or qty[4:] not in obs:
                    err(f"{where}.quantity", "bad_quantity", "quantity must be obs:<id> of an observation in this block")
            if "range" in value:
                limits = value["range"]
                if not _is_range(limits) or not all(_num(x) for x in limits):
                    err(f"{where}.range", "bad_value", "range must be a finite two-number list")
                elif limits[0] >= limits[1]:
                    err(f"{where}.range", "param_range", "range needs lower < upper")
            if "note" in value:
                _declaration_text(value["note"], f"{where}.note", err)


def _check_triage(tr: Any, err, *, moves: list, tracks: dict, has_project: bool) -> None:
    """X-12 / G-1: form only, including a fix without a move or a leave with moves."""
    choices = ("fix", "replace", "regenerate", "leave")
    if not _declaration_object(tr, "triage", ("decision", "options", "findings"), err, ("decision",)):
        return
    if "decision" in tr and tr["decision"] not in choices:
        err("triage.decision", "bad_value", f"decision must be one of {', '.join(choices)}")
    if "options" in tr:
        for i, value in enumerate(_declaration_list(tr["options"], "triage.options", 8, err)):
            where = f"triage.options[{i}]"
            if not _declaration_object(value, where, ("choice", "gains", "loses"), err, ("choice", "gains", "loses")):
                continue
            if "choice" in value and value["choice"] not in choices:
                err(f"{where}.choice", "bad_value", f"choice must be one of {', '.join(choices)}")
            if "gains" in value:
                _declaration_text(value["gains"], f"{where}.gains", err)
            if "loses" in value:
                for j, text in enumerate(_declaration_list(value["loses"], f"{where}.loses", 16, err)):
                    _declaration_text(text, f"{where}.loses[{j}]", err)
    if "findings" in tr:
        move_ids = [m.get("id") for m in moves if isinstance(m, dict)]
        statuses = ("fix", "unknown", "intentional", "no_change")
        for i, value in enumerate(_declaration_list(tr["findings"], "triage.findings", 64, err)):
            where = f"triage.findings[{i}]"
            if not _declaration_object(value, where, ("what", "track", "t_s", "status", "basis", "move"), err,
                                       ("what", "status", "basis")):
                continue
            for key in ("what", "basis"):
                if key in value:
                    _declaration_text(value[key], f"{where}.{key}", err)
            if "status" in value and value["status"] not in statuses:
                err(f"{where}.status", "bad_value", f"status must be one of {', '.join(statuses)}")
            if "track" in value:
                _declaration_track(value["track"], f"{where}.track", err, tracks, has_project)
            if "t_s" in value:
                _declaration_time(value["t_s"], f"{where}.t_s", err)
            if "move" in value and (not isinstance(value["move"], str) or not value["move"]
                                    or value["move"] not in move_ids):
                err(f"{where}.move", "bad_id", "move must name a move id in this block")


def _unmeasured_quantities(b: dict, proj: "_Project | None", warn) -> None:
    """FBREVIEW FR-7 (G-1) as amended by P3 (requirements 8.1): one warning per ledger quantity
    (P-nn[:qualifier]) in a claim, an expectation or a safeguard, with or without a project, in
    order of first appearance. Kind A (the original text): the project's floor variant has
    evaluation terms but none numeric (value or penalty) for the quantity. Kind B: every other case
    (no project, an unevaluated project, or a floor term that is numeric) -- check reads only the
    result variant's terms, which the standard flow does not keep."""
    terms = _terms(proj.root, None) if proj else {}
    counts: dict[str, int] = {}
    qs = list(b.get("claims") or [])
    for m in b.get("moves") or []:
        if isinstance(m, dict):
            qs += list(m.get("expect") or []) + list(m.get("safeguard") or [])
    for q in qs:
        qty = q.get("quantity") if isinstance(q, dict) else None
        if isinstance(qty, str) and _P_RE.match(qty):
            counts[qty] = counts.get(qty, 0) + 1
    for qty, n in counts.items():
        t = terms.get(qty) or terms.get(qty.split(":", 1)[0]) or {}
        if terms and _scalar(t.get("value")) is None and _scalar(t.get("penalty")) is None:
            warn(f"quantities.{qty}", "unmeasured_quantity",
                 f"床の変種の評価項に {qty} の数値（value／penalty）が無い（該当 {n} 件）。direction check は "
                 "not_measured を返す。obs:<id>（masking／wet_ratio／trk 対象の観察量）で測れる")
        else:
            warn(f"quantities.{qty}", "unmeasured_quantity",
                 f"{qty} は台帳指標（該当 {n} 件）。direction check は結果の変種の評価項だけを読み、"
                 "指揮書の結果を測り直さない。標準の流れ（master plan --apply）では評価項が残らず "
                 "not_measured になる。obs:<id> の観察量は check が床と結果の両方を測る")


def _kendall(xs: list[float], ys: list[float]) -> float | None:
    from scipy.stats import kendalltau
    if len(xs) < 3:
        return None
    t = kendalltau(xs, ys).statistic
    return None if t is None or not math.isfinite(float(t)) else round(float(t), 3)


def scene_block(sc: dict, src_t, src_f) -> dict:
    """The reference-only ``scene`` block of an outcome (FBREVIEW FR-4): the declared placement next
    to the measured one, for the floor and the result. Read by no verdict, summary or calibration."""
    def r3(v):
        v = _scalar(v)
        return None if v is None else round(v, 3)

    def obs(src, spec):
        res = S.observe(src, spec)
        return r3(res.get("value")) if res.get("status") == "ok" else None

    def lufs(src, trk):
        try:
            x, sr = src.track(trk, "dry")
        except S.StemObsError:
            return None
        return r3(Q.integrated_lufs(x, sr))

    rows: dict = {}
    depth_rows = []
    for s in sc.get("sources") or []:
        trk = s.get("track")
        row: dict = {}
        if "azimuth" in s:
            row["azimuth"] = s["azimuth"]
            row["expected_image"] = round(math.sin(float(s["azimuth"]) * math.pi / 2.0), 3)
        ip = {"primitive": "image_position", "target": trk, "path": "solo"}
        row["image_position"] = {"floor": obs(src_f, ip), "result": obs(src_t, ip)}
        if "depth" in s:
            row["depth"] = s["depth"]
        wr = {"primitive": "wet_ratio", "target": trk}
        row["wet_ratio_db"] = {"floor": obs(src_f, wr), "result": obs(src_t, wr)}
        row["level_lufs"] = {"floor": lufs(src_f, trk), "result": lufs(src_t, trk)}
        rows[trk] = row
        if "depth" in s and row["wet_ratio_db"]["result"] is not None and row["level_lufs"]["result"] is not None:
            depth_rows.append((float(s["depth"]), row["wet_ratio_db"]["result"], -row["level_lufs"]["result"]))
    n = len(depth_rows)
    return {"note": "参考値。どの判定にも入らない（主張・期待・ガード・summary・ゲート）。奥行きの知覚は 1 つの量で決まらない。"
                    "expected_image は sin(azimuth·π/2) の目安（モノ素材の等電力則の値。ステレオで取り込んだ素材は"
                    "釣り合い則で、これより中央寄りに出る）",
            "sources": rows,
            "depth_consistency": {"n": n,
                                  "tau_wet": _kendall([d[0] for d in depth_rows], [d[1] for d in depth_rows]),
                                  "tau_level": _kendall([d[0] for d in depth_rows], [d[2] for d in depth_rows])}}


def validate(doc: dict, project: str | Path | None = None) -> dict:
    """Validate a parsed direction. ``project``: the project it will be applied to (targets, replaces, sections)."""
    b = doc["block"]
    extensions = X.specs(OPS)
    ops = {**OPS, **{name: (s.stage, s.required) for name, s in extensions.items()}}
    edit_ops = _edit_ops()
    errors: list[dict] = []
    warnings: list[dict] = []
    notes: list[str] = []

    def err(where, code, msg):
        errors.append({"where": where, "code": code, "message": msg})

    def warn(where, code, msg):
        warnings.append({"where": where, "code": code, "message": msg})

    proj = _Project(project) if project is not None else None
    tracks = proj.tracks() if proj else {}
    buses = proj.buses() if proj else {}
    items = proj.floor_items() if proj else {}
    sections = {s.get("id") for s in proj.sections()} if proj else set()

    # document-level
    if b.get("schema_version") != FORMAT_VERSION:
        err("schema_version", "bad_value", f"schema_version must be {FORMAT_VERSION}")
    if b.get("kind") != "direction":
        err("kind", "bad_value", "kind must be 'direction'")
    for k in ("song", "request", "sources", "aims", "variants", "moves", "claims"):
        if k not in b:
            err(k, "missing_field", f"'{k}' is required")
    meta = doc.get("meta") or {}
    if meta.get("id") and meta.get("id") != doc["id"]:
        err("front_matter.id", "id_mismatch", f"front matter id {meta.get('id')} != computed {doc['id']}")
    ana = (b.get("sources") or {}).get("analysis")
    apath = Path(doc["path"]).parent / "analysis.md"
    if apath.is_file():
        aid = analysis_id(apath.read_bytes())
        if ana and ana != aid:
            err("sources.analysis", "id_mismatch", f"sources.analysis {ana} != computed {aid} of analysis.md")
        try:
            ameta, _ = kbmod.parse_front_matter(apath.read_text(encoding="utf-8"))
            if ameta and ameta.get("id") and ameta.get("id") != aid:
                err("analysis.md", "id_mismatch", f"analysis front matter id {ameta.get('id')} != computed {aid}")
        except kbmod.FrontMatterError as e:
            err("analysis.md", "front_matter", str(e))

    # invariant area: forbidden keys anywhere
    for path, key in _walk_keys(b):
        if key in FORBIDDEN_KEYS:
            err(path, "invariant", f"'{key}' belongs to the invariant area (v2 f.2) and cannot be written")
    for bad in ("knowledge/", "profiles/"):
        for m in b.get("moves") or []:
            if bad in canonical_block({k: v for k, v in m.items() if k not in ("basis",)}):
                err(f"moves.{m.get('id')}", "invariant", f"a move may not refer to {bad} (read-only)")

    aims = {a.get("id") for a in b.get("aims") or [] if isinstance(a, dict)}
    obs = {o.get("id"): o for o in b.get("observations") or [] if isinstance(o, dict)}
    for oid, o in obs.items():
        if o.get("primitive") not in Q.PRIMITIVES and o.get("primitive") not in S.CONTEXT_PRIMITIVES:
            err(f"observations.{oid}", "bad_value", f"unknown primitive '{o.get('primitive')}'")
        # track targets (trk_<stem>) and the context primitives are measured by stemobs (FBREVIEW FR-1 / FR-2)
        if (o.get("target", "master") not in ("master", "mix") and not S.is_track_target(o.get("target"))
                and o.get("primitive") not in S.CONTEXT_PRIMITIVES):
            warn(f"observations.{oid}", "unsupported", f"target '{o.get('target')}' is not supported in v0 "
                                                       "(only master); the observation will be reported unsupported")
        # form and range of the fields FR-1 / FR-2 add (G-2); nothing for an observation without them
        for suffix, code, msg in S.spec_errors(o):
            err(f"observations.{oid}{suffix}", code, msg)
        if proj:
            for key in ("target", "against"):
                tv = o.get(key)
                if S.is_track_target(tv) and tv not in tracks:
                    err(f"observations.{oid}" + ("" if key == "target" else ".against"), "unknown_target",
                        f"unknown track '{tv}'")
        sec = o.get("section", "all")
        if isinstance(sec, str) and sec != "all" and proj and sec not in sections:
            err(f"observations.{oid}", "unknown_section", f"unknown section '{sec}'")
        if "ref_value" in o and o["ref_value"] is not None and _scalar(o["ref_value"]) is None:
            err(f"observations.{oid}.ref_value", "bad_value", "ref_value must be a finite number (or null)")
        if ("view" in o or "view_band_hz" in o) and (o.get("primitive") not in S.CONTEXT_PRIMITIVES
                                                    or o.get("view") == "side"):
            # The optional view (UPGRADE2 §3.5 / X-09): the same rule as query.observe, so a written view never
            # fails only at check time
            try:
                Q.view_spec(o)
            except Q.QueryError as e:
                msg = str(e).removeprefix("bad_value: ")
                err(f"observations.{oid}.{'view_band_hz' if 'view_band_hz' in msg else 'view'}", "bad_value", msg)
    _validate_reference_fields(b, err)
    if "scene" in b:
        _check_scene(b["scene"], err, tracks=tracks, has_project=proj is not None,
                     buses=buses, moves=b.get("moves") or [])
    if "frame" in b:
        _check_frame(b["frame"], err, obs=obs, tracks=tracks, sections=sections, has_project=proj is not None)
    if "triage" in b:
        _check_triage(b["triage"], err, moves=b.get("moves") or [], tracks=tracks, has_project=proj is not None)

    def check_quantity(where: str, q: dict):
        qty = q.get("quantity")
        if not isinstance(qty, str) or not (qty.startswith("obs:") or _P_RE.match(qty)):
            err(where, "bad_quantity", f"quantity must be P-nn[:qualifier] or obs:<id> (got {qty!r})")
        elif qty.startswith("obs:") and qty[4:] not in obs:
            err(where, "bad_quantity", f"{qty}: no such observation")
        d = q.get("direction")
        if d not in DIRECTIONS:
            err(where, "bad_value", f"direction must be one of {', '.join(DIRECTIONS)}")
        if d == "not_worse" and not isinstance(q.get("tolerance"), (int, float)):
            err(where, "missing_field", "not_worse needs a numeric tolerance")
        if d in ("up", "down") and not isinstance(q.get("min_delta"), (int, float)):
            err(where, "missing_field", f"'{d}' needs a numeric min_delta")

    claims = b.get("claims") or []
    prim = [c for c in claims if c.get("primary")]
    if not 1 <= len(prim) <= 3:
        err("claims", "primary_count", f"1 to 3 claims must be primary (found {len(prim)})")
    for c in claims:
        check_quantity(f"claims.{c.get('id')}", c)
        if c.get("vs", "floor") != "floor":
            err(f"claims.{c.get('id')}", "bad_value", "claims are made against the floor (vs: floor)")

    # variants and profile
    variants = b.get("variants") or []
    if not variants:
        err("variants", "missing_field", "one variant is required")
    for v in variants:
        pid = v.get("profile")
        prof = _profile(pid) if pid else None
        if prof is None:
            err(f"variants.{v.get('id')}", "bad_value", f"unknown profile '{pid}'")
            continue
        if pid != "streaming_universal" and not v.get("reason"):
            err(f"variants.{v.get('id')}", "missing_field", "a profile other than streaming_universal needs a reason")
        tl = v.get("target_lufs")
        win = ((prof.get("loudness") or {}).get("window_lufs_i"))
        if tl is not None and win and not (win[0] <= float(tl) <= win[1]):
            err(f"variants.{v.get('id')}", "invariant", f"target_lufs {tl} is outside the profile window {win}")
    if len(variants) > 1:
        warn("variants", "unsupported", "v0 applies the first variant only")

    rule_ids = _rule_ids()
    tiers = {}
    seen_ids = set()
    lead_e3 = False
    for m in b.get("moves") or []:
        mid = m.get("id")
        where = f"moves.{mid}"
        if not mid or mid in seen_ids:
            err(where, "bad_id", "every move needs a unique id")
        seen_ids.add(mid)
        op = m.get("op")
        extension = extensions.get(op)
        if op not in ops:
            valid_ops = OPS if any(x.get("op") == "duck_curve" for x in b.get("moves") or []) else {
                k: v for k, v in OPS.items() if k != "duck_curve"}
            err(where, "bad_op", f"unknown op '{op}' (valid: {', '.join(valid_ops)})")
            continue
        stage, req = ops[op]
        if m.get("stage", stage) != stage:
            err(where, "bad_stage", f"op '{op}' runs on stage '{stage}', not '{m.get('stage')}'")
        for k in req:
            if m.get(k) in (None, "", {}):
                err(where, "missing_field", f"op '{op}' needs '{k}'")
        for k in ("aim", "basis", "origin"):
            if not m.get(k):
                err(where, "missing_field", f"'{k}' is required on every move")
        if m.get("aim") and m.get("aim") not in aims:
            err(where, "bad_ref", f"aim '{m.get('aim')}' is not in aims")
        if m.get("origin") and m.get("origin") not in ORIGINS:
            err(where, "bad_value", "origin must be catalog, case, new or reference")
        for ref in _REF_BASIS_RE.findall(str(m.get("basis") or "")):
            if not _WORK_RE.match(ref):
                err(f"{where}.basis", "bad_ref", f"'ref:{ref}': a reference basis names a work card (ref:work_<slug> §n)")
        for q in (m.get("expect") or []) + (m.get("safeguard") or []):
            check_quantity(where, q)
        target = m.get("target")
        proc = m.get("processor")
        if m.get("stage") == "master" or target == "master":
            if op != "master_target":
                err(where, "invariant", "the master chain is left to the master planner (only master_target)")
        if proc in MASTER_ONLY:
            err(where, "invariant", f"'{proc}' is part of the master stage (order, limiter, dither) and cannot be used")
        sec = m.get("section")
        if sec not in (None, "all"):
            if op != "gain" and op not in edit_ops and not (extension and extension.section):
                err(where, "section_scope", "only 'gain' can be limited to a section (other ops: tool_requests)")
            elif isinstance(sec, str) and proj and sec not in sections:
                err(where, "unknown_section", f"unknown section '{sec}'")
            elif isinstance(sec, dict) and not ({"t0_s", "t1_s"} <= set(sec)):
                err(where, "bad_value", "a time section needs t0_s and t1_s")
        params, rnotes = (m.get("params") if isinstance(m.get("params"), dict) else {}, []) if extension or op in ("gain_curve", "duck_curve") \
            else resolve_params(m, m.get("params") or {}, ptype=_move_processor(m, proj))
        notes += rnotes
        # targets
        if op in ("chain_add", "chain_param", "chain_remove", "gain", "pan", "send") and proj:
            if target not in tracks and target not in buses and not any(
                    x.get("op") == "bus_add" and x.get("target") == target for x in b.get("moves") or []):
                err(where, "unknown_target", f"unknown target '{target}'")
            if op in ("gain", "send") and target not in tracks:
                err(where, "bad_target", f"'{op}' needs a track target")
        if op in ("chain_param", "chain_remove") and proj:
            if m.get("replaces") not in items:
                err(where, "unknown_replaces", f"'{m.get('replaces')}' is not a processor of the floor mix")
        raw = m.get("params") or {}
        if extension:
            if extension.stage == "edit":
                if not S.is_track_target(target) or target in buses:
                    err(where, "bad_target", f"'{op}' needs a track target")
                elif proj and target not in tracks:
                    err(where, "unknown_target", f"unknown target '{target}'")
            extension.validate(copy.deepcopy(m), X.ValidationContext(proj, b, where, err))
        elif op == "chain_add":
            _check_proc_params(proc, raw, _holder_stage(target), where, errors)
        elif op == "chain_param" and proj and m.get("replaces") in items:
            kind, hid = items[m["replaces"]]
            holder = (tracks if kind == "track" else buses).get(hid) or {}
            it = next((x for x in holder.get("chain") or [] if x.get("id") == m["replaces"]), None)
            if it is not None:
                _check_proc_params(it.get("type"), {**(it.get("params") or {}), **raw}, kind, where, errors)
        elif op == "gain":
            if not (("gain_db" in params) ^ ("delta_db" in params)):
                err(where, "missing_field", "gain needs exactly one of gain_db / delta_db")
            for k in ("gain_db", "delta_db"):
                if k in params and not -24.0 <= float(params[k]) <= 12.0:
                    err(where, "param_range", f"{k} {params[k]} outside [-24, 12]")
        elif op == "pan":
            if "position" in params and not -1.0 <= float(params["position"]) <= 1.0:
                err(where, "param_range", "position must be in [-1, 1]")
            if "width" in params and not 0.0 <= float(params["width"]) <= 2.0:
                err(where, "param_range", "width must be in [0, 2]")
            if not ({"position", "width"} & set(params)):
                err(where, "missing_field", "pan needs position and/or width")
        elif op == "send":
            if not params.get("bus"):
                err(where, "missing_field", "send needs params.bus")
            elif proj and params["bus"] not in buses and not any(
                    x.get("op") == "bus_add" and x.get("target") == params["bus"] for x in b.get("moves") or []):
                err(where, "unknown_target", f"unknown bus '{params['bus']}'")
            if "level_db" in params and not -60.0 <= float(params["level_db"]) <= 6.0:
                err(where, "param_range", "level_db must be in [-60, 6]")
        elif op == "bus_add":
            if not str(target).startswith("bus_") or (proj and target in buses):
                err(where, "bad_target", "bus_add needs a new id starting with 'bus_'")
            if params.get("output", "bus_mix") != "bus_mix":
                err(where, "bad_value", "a new bus outputs to bus_mix")
            for i, c in enumerate(params.get("chain") or []):
                _check_proc_params(c.get("type") or c.get("processor"), c.get("params") or {}, "bus",
                                   f"{where}.chain[{i}]", errors)
        elif op == "cleanup_override":
            if not isinstance(params.get("overrides"), dict) or not params.get("overrides"):
                err(where, "missing_field", "cleanup_override needs params.overrides (an object)")
        elif op == "master_target":
            tl = params.get("target_lufs")
            prof = _profile((variants[0] if variants else {}).get("profile") or "")
            win = ((prof or {}).get("loudness") or {}).get("window_lufs_i")
            if not isinstance(tl, (int, float)):
                err(where, "missing_field", "master_target needs params.target_lufs")
            elif win and not win[0] <= float(tl) <= win[1]:
                err(where, "invariant", f"target_lufs {tl} is outside the profile window {win}")
        elif op in EDIT_OPS:
            from . import edit as E
            if target == "master" or str(target).startswith("bus_") or (proj and target in buses):
                err(where, "bad_target", f"'{op}' needs a track target")
            elif proj and target not in tracks:
                err(where, "unknown_target", f"unknown target '{target}'")
            E.check_params(op, raw, where, err)
        elif op == "duck":
            from . import duck as K
            if target == "master" or str(target).startswith("bus_") or (proj and target in buses):
                err(where, "bad_target", "'duck' needs a track target (the track that goes down)")
            elif proj and target not in tracks:
                err(where, "unknown_target", f"unknown target '{target}'")
            K.check_params(raw, target, where, err, tracks=tracks, buses=buses,
                           bpm=K.floor_bpm(proj.floor_mxp) if proj else None, has_project=proj is not None)
        elif op == "duck_curve":
            from . import duck_curve as KC
            from .duck import floor_bpm
            KC.check_params(m, b.get("moves") or [], where, err, tracks=tracks, buses=buses,
                            bpm=floor_bpm(proj.floor_mxp) if proj else None, has_project=proj is not None)
        elif op == "gain_curve":
            _check_gain_curve(m, where, err, tracks=tracks, buses=buses, has_project=proj is not None)
        elif op == "place":
            _check_place(m, b, where, err, proj=proj, tracks=tracks, buses=buses, errors=errors)
        # review tier (assigned here, not self-declared). E1 is only the catalog range check: a move
        # taken from another work (origin: reference) is E2 or above (another song's facts are no
        # guarantee here), and citing a theory card (KT-nnnn) never makes a move E1; a place is E2 or above
        tier = "E2"
        cited = set(re.findall(r"R-\d{2}", str(m.get("basis") or "")))
        if m.get("origin") == "catalog" and cited and cited <= rule_ids and not extension and op not in EDIT_OPS and op != "duck" \
                and op != "place" and op != "gain_curve" and op != "duck_curve":
            tier = "E1"
        if op == "master_target":
            prof = _profile((variants[0] if variants else {}).get("profile") or "")
            dflt = ((prof or {}).get("loudness") or {}).get("target_lufs_i")
            if dflt is not None and params.get("target_lufs") is not None and float(params["target_lufs"]) != float(dflt):
                tier = "E3"
        if target == LEAD and ((op == "gain" and sec not in (None, "all"))
                               or (op == "chain_add" and proc in TIME_VARYING) or op in EDIT_OPS
                               or op == "duck" or op == "gain_curve" or op == "duck_curve"
                               or (extension and (extension.stage == "edit" or extension.time_varying))):
            tier = "E3"
            lead_e3 = True
        if tier == "E3" and not b.get("listen_for"):
            warn(where, "listen_for", "an E3 move needs listen_for entries")
        tiers[mid] = tier
    if any(isinstance(m, dict) and m.get("op") == "place" for m in b.get("moves") or []):
        _place_conflicts(b.get("moves") or [], err)
    if lead_e3 and not b.get("listen_for"):
        warn("listen_for", "missing", "E3 moves on the lead need listen_for")
    _unmeasured_quantities(b, proj, warn)
    return {"kind": "direction_validation", "id": doc["id"], "ok": not errors, "errors": errors,
            "warnings": warnings, "tiers": tiers, "notes": notes,
            "moves": len(b.get("moves") or []), "claims": len(claims), "observations": len(obs)}


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def _check_gain_curve(m: dict, where: str, err, *, tracks: dict, buses: dict, has_project: bool) -> None:
    """G-2: fixed limits, with no range values or calibration knobs."""
    allowed = {"id", "op", "stage", "target", "params", "aim", "basis", "origin", "expect", "safeguard",
               "section", "select"}
    if set(m) - allowed:
        err(where, "bad_value", "unknown gain_curve move keys: " + ", ".join(sorted(set(m) - allowed)))
    if "section" in m and m["section"] in (None, "all"):
        err(where, "section_scope", "gain_curve cannot have section; use params.segments")
    target = m.get("target")
    if not S.is_track_target(target) or target in buses:
        err(where, "bad_target", "gain_curve needs a track target")
    elif has_project and target not in tracks:
        err(where, "unknown_target", f"unknown target '{target}'")
    p = m.get("params")
    if not isinstance(p, dict):
        err(where, "bad_value", "gain_curve params must be an object")
        return
    if set(p) - {"ramp_ms", "segments"}:
        err(where, "bad_value", "unknown gain_curve parameters")
    ramp = p.get("ramp_ms", 20)
    if not _num(ramp):
        err(where, "bad_value", "ramp_ms must be a finite number")
    elif not 5 <= ramp <= 200:
        err(where, "param_range", "ramp_ms outside [5, 200]")
    segs = p.get("segments")
    if not isinstance(segs, list):
        err(where, "bad_value" if "segments" in p else "missing_field", "segments must be an array")
        return
    if not 1 <= len(segs) <= 256:
        err(where, "param_range", "segments must contain 1 to 256 entries")
    spans = []
    for i, seg in enumerate(segs):
        w = f"{where}.params.segments[{i}]"
        if not isinstance(seg, dict):
            err(w, "bad_value", "a segment must be an object")
            continue
        if set(seg) - {"t0_s", "t1_s", "delta_db", "why", "hold"}:
            err(w, "bad_value", "unknown segment keys")
        for k in ("t0_s", "t1_s", "delta_db", "why"):
            if k not in seg:
                err(w, "missing_field", f"segment needs {k}")
        t0, t1 = seg.get("t0_s"), seg.get("t1_s")
        if not (_num(t0) and _num(t1)) or not t0 < t1:
            err(w, "bad_value", "segment times must be finite, with t0_s < t1_s")
        else:
            spans.append((t0, t1))
        delta = seg.get("delta_db")
        if not _num(delta):
            err(w, "bad_value", "delta_db must be a finite number (ranges are not supported)")
        elif not -6 <= delta <= 6:
            err(w, "param_range", "delta_db outside [-6, 6]")
        if not isinstance(seg.get("why"), str):
            err(w, "bad_value", "why must be a string")
        elif len(seg["why"]) > 200:
            err(w, "param_range", "why exceeds 200 characters")
        if "hold" in seg and not isinstance(seg["hold"], bool):
            err(w, "bad_value", "hold must be a boolean")
    spans.sort()
    if any(b[0] < a[1] for a, b in zip(spans, spans[1:])):
        err(where, "bad_value", "gain_curve segments overlap")


def gate_definitions_hash() -> dict:
    root = repo_data_root()
    files = {}
    for rel in GATE_DEFINITIONS:
        p = root / rel
        files[rel] = hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else None
    return {"files": files, "combined": canonical_hash(files)[:16]}


def _ref(dir_id: str, mid: str) -> str:
    return f"{dir_id}/{mid}"


def _item(dir_id: str, m: dict, ptype: str, params: dict, holder: str, suffix: str = "") -> dict:
    basis = str(m.get("basis") or "")
    return {"id": f"dr.{holder}.{m['id']}{suffix}", "type": ptype, "params": params,
            "reason": f"direction {dir_id} move {m['id']} (aim {m.get('aim')}): {basis[:120]}",
            "owner": OWNER, "move_ref": _ref(dir_id, m["id"])}


def _automation(rate: int, segs: list[tuple[float, float, float]], base: list | None) -> list:
    if base:
        raise DirectionError("the track already has gain automation; v0 does not merge automation")
    segs = sorted(segs)
    for a, b in zip(segs, segs[1:]):
        if b[0] < a[1] + RAMP_S:
            raise DirectionError("section gains on one track overlap or touch; v0 needs a gap of 20 ms")
    pts: list[list] = []
    r = int(round(RAMP_S * rate))
    for t0, t1, d in segs:
        s0, s1 = int(round(t0 * rate)), int(round(t1 * rate))
        p = [[max(0, s0 - r), 0.0], [s0, d], [s1, d], [s1 + r, 0.0]]
        for q in p:
            if pts and q[0] <= pts[-1][0]:
                q = [pts[-1][0] + 1, q[1]]
            pts.append(q)
    return pts


def build_proposal(proj: _Project, doc: dict, sel: dict | None = None) -> tuple[dict, dict, list[str]]:
    """(mix proposal or None, record, notes). The record lists, per move, what it wrote.

    ``sel``: range values chosen by calibration (``director.calibrate``); without it every range
    resolves to its ``select``."""
    if proj.floor_mxp is None:
        raise DirectionError("the project has no applied floor mix proposal (mix.applied.proposal_id)")
    b = doc["block"]
    extensions = X.specs(OPS)
    dir_id = doc["id"]
    ch = copy.deepcopy(proj.floor_mxp.get("changes") or {})
    ch.setdefault("tracks", {})
    ch.setdefault("buses", [])
    cur = proj.tracks()
    notes: list[str] = []
    record: dict = {"moves": {}, "cleanup": [], "master_target": None}
    sections = proj.sections()
    dur = max((float(s["end_s"]) for s in sections), default=None)

    def track(tid: str) -> dict:
        d = ch["tracks"].setdefault(tid, {})
        t = cur[tid]
        for k in ("chain", "sends"):
            if k not in d:
                d[k] = copy.deepcopy(t.get(k) or [])
        if "gain_db" not in d:
            d["gain_db"] = float(t.get("gain_db", 0.0))
        if "pan" not in d and t.get("pan") is not None:
            d["pan"] = copy.deepcopy(t["pan"])
        return d

    def bus_chain(bid: str) -> list:
        if bid == ch.get("mix_bus"):
            ch["mix_chain_changed"] = True
            return ch.setdefault("mix_chain", [])
        bus = next((x for x in ch["buses"] if x.get("id") == bid), None)
        if bus is None:
            raise DirectionError(f"bus '{bid}' cannot be changed by a direction in v0 (not planner-owned or new)")
        return bus.setdefault("chain", [])

    def find_item(pid: str) -> tuple[list, int]:
        for tid in cur:
            lst = track(tid)["chain"] if any(x.get("id") == pid for x in (cur[tid].get("chain") or [])) else None
            if lst is not None:
                return lst, next(i for i, x in enumerate(lst) if x.get("id") == pid)
        for bus in ch["buses"]:
            for i, x in enumerate(bus.get("chain") or []):
                if x.get("id") == pid:
                    return bus["chain"], i
        for i, x in enumerate(ch.get("mix_chain") or []):
            if x.get("id") == pid:
                ch["mix_chain_changed"] = True
                return ch["mix_chain"], i
        raise DirectionError(f"processor '{pid}' not found in the floor mix")

    seg_gain: dict[str, list] = {}
    ducks: dict[str, list] = {}
    curves: dict[str, list] = {}
    keyed_bands: list = []
    xautomation: dict[str, list] = {}
    # new buses first so sends can reach them
    for m in b.get("moves") or []:
        if m.get("op") != "bus_add":
            continue
        params, n = resolve_params(m, m.get("params") or {}, sel)
        notes += n
        chain = []
        for i, c in enumerate(params.get("chain") or []):
            cp, cn = resolve_params(m, c.get("params") or {}, sel, f"{m['id']}.chain{i}",
                                    ptype=c.get("type") or c.get("processor"))
            notes += cn
            ptype = c.get("type") or c.get("processor")
            chain.append(_item(dir_id, m, ptype, P.validate_params(ptype, cp), m["target"], f".{i + 1}"))
        ch["buses"].append({"id": m["target"], "kind": params.get("kind", "fx"),
                            "name": params.get("name") or f"{m['target']} (direction {dir_id})",
                            "output": params.get("output", "bus_mix"), "owner": OWNER, "chain": chain,
                            "move_ref": _ref(dir_id, m["id"])})
        record["moves"][m["id"]] = {"op": "bus_add", "bus": m["target"], "items": [c["id"] for c in chain]}

    def one(m: dict, params: dict) -> None:
        """One move of the existing ops (a place is expanded into these, FR-5)."""
        op, mid, target = m.get("op"), m.get("id"), m.get("target")
        if op == "chain_add":
            ptype = m["processor"]
            item = _item(dir_id, m, ptype, P.validate_params(ptype, params), target)
            lst = track(target)["chain"] if target in cur else bus_chain(target)
            lst.append(item)
            record["moves"][mid] = {"op": op, "item": item["id"], "params": item["params"]}
        elif op == "chain_param":
            lst, i = find_item(m["replaces"])
            it = copy.deepcopy(lst[i])
            it["params"] = P.validate_params(it["type"], {**(it.get("params") or {}), **params})
            it["move_ref"] = _ref(dir_id, mid)
            it["reason"] = f"{it.get('reason', '')} | changed by direction {dir_id} move {mid}"
            lst[i] = it
            record["moves"][mid] = {"op": op, "item": it["id"], "params": it["params"]}
        elif op == "chain_remove":
            lst, i = find_item(m["replaces"])
            removed = lst.pop(i)
            record["moves"][mid] = {"op": op, "removed": removed.get("id")}
        elif op == "gain":
            d = track(target)
            sec = m.get("section")
            if sec in (None, "all"):
                g = float(params["gain_db"]) if "gain_db" in params else d["gain_db"] + float(params["delta_db"])
                d["gain_db"] = round(g, 4)
                record["moves"][mid] = {"op": op, "track": target, "gain_db": d["gain_db"]}
            else:
                t0, t1 = Q.section_range(sec, sections, dur or 1e9)
                delta = float(params["delta_db"]) if "delta_db" in params else float(params["gain_db"]) - d["gain_db"]
                seg_gain.setdefault(target, []).append((t0, t1, round(delta, 4), mid))
                record["moves"][mid] = {"op": op, "track": target, "section": sec, "range_s": [t0, t1],
                                        "delta_db": round(delta, 4)}
        elif op == "pan":
            if target in cur:
                d = track(target)
                pan = dict(d.get("pan") or {})
                for k in ("position", "width"):
                    if k in params:
                        pan[k] = float(params[k])
                pan.setdefault("position", 0.0)
                pan.setdefault("width", 1.0)
                d["pan"] = pan
                record["moves"][mid] = {"op": op, "track": target, "pan": pan}
            else:
                lst = bus_chain(target)
                made = []
                if "position" in params:
                    it = _item(dir_id, m, "pan", P.validate_params("pan", {"position": float(params["position"])}),
                               target, ".pan")
                    lst.append(it)
                    made.append(it["id"])
                if "width" in params:
                    it = _item(dir_id, m, "stereo", P.validate_params("stereo", {"width": float(params["width"])}),
                               target, ".width")
                    lst.append(it)
                    made.append(it["id"])
                record["moves"][mid] = {"op": op, "bus": target, "items": made}
        elif op == "send":
            d = track(target)
            send = {"bus": params["bus"], "level_db": float(params.get("level_db", -15.0)),
                    "pre_fader": bool(params.get("pre_fader", False)), "owner": OWNER, "move_ref": _ref(dir_id, mid)}
            d["sends"] = [s for s in d["sends"] if s.get("bus") != params["bus"]] + [send]
            record["moves"][mid] = {"op": op, "track": target, "send": send}
        elif op == "cleanup_override":
            record["cleanup"].append({"move": mid, "target": target, "overrides": params["overrides"]})
            record["moves"][mid] = {"op": op, "target": target, "overrides": params["overrides"]}
        elif op == "master_target":
            record["master_target"] = float(params["target_lufs"])
            record["moves"][mid] = {"op": op, "target_lufs": float(params["target_lufs"])}
        elif op == "gain_curve":
            from . import curve
            length = (proj.data.get("timebase") or {}).get("length_samples")
            duration = float(length) / proj.rate if length is not None else dur
            pts = curve.points(proj.rate, params["segments"], params.get("ramp_ms", 20), duration)
            curves.setdefault(target, []).append((mid, pts))
            record["moves"][mid] = {"op": op, "track": target, "ramp_ms": params.get("ramp_ms", 20),
                                    "segments": [{**copy.deepcopy(s), "applied": not s.get("hold", False)}
                                                 for s in params["segments"]], "points": len(pts)}
            notes.append(f"{mid}: {curve.NOTE}")
        elif op == "duck_curve":
            from . import duck_curve as KC
            from .duck import floor_bpm
            try:
                dp = KC.plan(proj.root, m, params, floor_bpm(proj.floor_mxp))
            except ValueError as e:
                raise DirectionError(f"{mid}: {e}") from None
            if dp["band"] == [0, 0]:
                base = cur.get(target, {}).get("automation") or {}
                dp["record"]["floor_automation"] = {"points": len(base.get("gain_db") or []), "owner": base.get("owner")}
                ducks.setdefault(target, []).append((mid, dp["points"]))
            else:
                keyed_bands.append((m, dp))
            record["moves"][mid] = dp["record"]
            notes.extend(dp["notes"])
        elif op == "duck":
            from . import duck as K
            try:
                dp = K.plan(proj.root, m, params, K.floor_bpm(proj.floor_mxp))
            except ValueError as e:
                raise DirectionError(f"{mid}: {e}") from None
            base = cur[target].get("automation") if isinstance(cur[target].get("automation"), dict) else {}
            dp["record"]["floor_automation"] = {"points": len(base.get("gain_db") or []), "owner": base.get("owner")}
            ducks.setdefault(target, []).append((mid, dp["points"]))
            record["moves"][mid] = dp["record"]
            notes.extend(dp["notes"])

    for m in b.get("moves") or []:
        extension = extensions.get(m.get("op"))
        if extension:
            if extension.stage == "edit":
                continue
            result = extension.expand(proj, copy.deepcopy(m))
            if not isinstance(result, X.MixResult) or not isinstance(result.record, dict):
                raise DirectionError(f"{m['op']}: expand must return MixResult with a record")
            target, trace = m.get("target"), []
            if result.points:
                from .duck import merge_automation
                if target not in cur:
                    raise DirectionError(f"{m['op']}: automation needs a track target")
                points = merge_automation([], result.points)
                xautomation.setdefault(target, []).append((m['id'], points))
                trace.append(f"automation:{target}")
            for i, declaration in enumerate(result.chain):
                ptype = declaration["type"]
                params = P.validate_params(ptype, declaration.get("params") or {})
                errors = []
                _check_proc_params(ptype, params, _holder_stage(target), m['id'], errors)
                if target == "master" or ptype in MASTER_ONLY or errors:
                    raise DirectionError(f"{m['op']}: invalid chain declaration")
                item = _item(dir_id, m, ptype, params, target, f".x{i + 1}")
                if target in cur:
                    track(target)["chain"].append(item)
                else:
                    from .duck_curve import bus_chain as extension_bus_chain
                    extension_bus_chain(proj, ch, target).append(item)
                trace.append(item['id'])
            record['moves'][m['id']] = {**copy.deepcopy(result.record), "op": m['op'],
                                        "track": target, "trace": trace}
            notes.extend(result.notes)
            continue
        params, n = resolve_params(m, m.get("params") or {}, sel, ptype=_move_processor(m, proj))
        notes += n
        if m.get("op") == "bus_add":
            continue
        if m.get("op") == "place":
            # FR-5: expanded into pan / gain / chain_add / send moves that carry the place's id (move_ref)
            pd = place_derive(params)
            for op2, ptype, p2 in pd["moves"]:
                sub = {k: v for k, v in m.items() if k not in ("params", "processor")}
                sub.update({"op": op2, "params": p2})
                if ptype:
                    sub["processor"] = ptype
                one(sub, p2)
            record["moves"][m["id"]] = {
                "op": "place", "track": m.get("target"),
                **{k: (None if params.get(k) is None else float(params[k])) for k in ("azimuth", "width", "distance")},
                "room": params.get("room"), "model": pd["model"], "derived": pd["derived"]}
            continue
        one(m, params)
    for m, dp in keyed_bands:
        from . import duck_curve as KC
        target = m["target"]
        if not dp["points"]:
            continue
        params = {"lo_hz": dp["band"][0], "hi_hz": dp["band"][1],
                  "gain": [[at / dp["sr"], db] for at, db in dp["points"]]}
        item = _item(dir_id, m, "band_automation", P.validate_params("band_automation", params), target)
        if target in cur:
            lst = track(target)["chain"]
        else:
            lst = KC.bus_chain(proj, ch, target)
        lst.append(item)
        record["moves"][m["id"]]["item"] = item["id"]
    # New-op automation is a separate column until all ducks have been collected.
    for tid, points in xautomation.items():
        ducks.setdefault(tid, []).extend(points)
    for tid, segs in seg_gain.items():
        if tid in curves:
            continue
        if tid in ducks:
            continue
        d = track(tid)
        pts = _automation(proj.rate, [s[:3] for s in segs], (cur[tid].get("automation") or {}).get("gain_db"))
        d["automation"] = {"gain_db": pts, "owner": OWNER, "reason": f"direction {dir_id}: section gains",
                           "move_ref": [_ref(dir_id, s[3]) for s in segs]}
    for tid, dl in ducks.items():
        if tid in curves:
            continue
        if tid not in cur:
            from . import duck_curve as KC
            KC.merge_bus_ducks(proj, ch, dir_id, tid, dl, b["moves"], record)
            continue
        _merge_ducks(proj, dir_id, tid, dl, seg_gain.get(tid) or [], cur, track)
    for tid, cl in curves.items():
        _merge_curves(proj, dir_id, tid, cl, ducks.get(tid) or [], seg_gain.get(tid) or [], cur, track)
    if any(m.get("op") == "duck_curve" for m in b.get("moves") or []):
        from . import duck_curve as KC
        KC.measure_proposal(proj, ch, record)
    mix_moves = [m for m in b.get("moves") or [] if OPS.get(m.get("op"), ("",))[0] == "mix"
                 or (m.get("op") in extensions and extensions[m['op']].stage == "mix")]
    if not mix_moves:
        return None, record, notes
    fm = proj.floor_mxp
    prop = {k: copy.deepcopy(fm.get(k)) for k in ("stage", "project_id", "lead", "genre", "profile", "tempo",
                                                  "sections", "route", "restrictions", "order", "reorderings",
                                                  "arrangement", "decisions", "unresolved")}
    prop["variant"] = None
    prop["changes"] = ch
    prop["moves"] = []
    prop["notes"] = list(fm.get("notes") or []) + [f"direction {dir_id}: moves on top of the floor mix "
                                                   f"{proj.floor_mxp_id} (the evaluation is the floor's)"]
    ev = copy.deepcopy(fm.get("objective_evaluation") or {})
    ev["note"] = f"floor evaluation of {proj.floor_mxp_id}; the direction's result is judged by direction check"
    prop["objective_evaluation"] = ev
    prop["measurements"] = copy.deepcopy(fm.get("measurements"))
    prop["direction"] = {"id": dir_id, "floor_proposal": proj.floor_mxp_id}
    prop["operations"] = ["approve_and_apply", "reject_and_request_alternative"]
    prop["proposal_id"] = "mxp_" + canonical_hash({"direction": dir_id, "changes": ch})[:12]
    prop["status"] = "proposed"
    prop["author"] = "agent"
    return prop, record, notes


def _merge_curves(proj: _Project, dir_id: str, tid: str, cl: list, dl: list, segs: list,
                  cur: dict, track) -> None:
    """Finalize only gain_curve targets: floor, section gains, ducks, then curves."""
    from . import duck as K
    base = cur[tid].get("automation") if isinstance(cur[tid].get("automation"), dict) else {}
    total = list(base.get("gain_db") or [])
    refs = base.get("move_ref") or []
    refs = list(refs) if isinstance(refs, list) else [refs]
    if segs:
        total = K.merge_automation(total, _automation(proj.rate, [s[:3] for s in segs], None))
        refs += [_ref(dir_id, s[3]) for s in segs]
    for mid, pts in dl + cl:
        total = K.merge_automation(total, pts)
        refs.append(_ref(dir_id, mid))
    d = track(tid)
    d["automation"] = {"gain_db": total, "owner": OWNER,
                       "reason": f"direction {dir_id}: floor + section gains + ducking + gain curves",
                       "move_ref": list(dict.fromkeys(refs))}


def _merge_ducks(proj: _Project, dir_id: str, tid: str, dl: list, segs: list, cur: dict, track) -> None:
    """One automation on a duck target: the floor's automation + this direction's section gains + every
    duck on the track, summed exactly (U-23). Nothing is written when no duck has a hit and no section
    gain is there (the floor's automation then stays as it is)."""
    from . import duck as K
    base = cur[tid].get("automation") if isinstance(cur[tid].get("automation"), dict) else {}
    total = list(base.get("gain_db") or [])
    refs = []
    if segs:
        total = K.merge_automation(total, _automation(proj.rate, [s[:3] for s in segs], None))
        refs += [s[3] for s in segs]
    for mid, pts in dl:
        if pts:
            total = K.merge_automation(total, pts)
            refs.append(mid)
    if not refs:
        return
    what = ["ducking"] + (["section gains"] if segs else []) + (["the floor automation"] if base.get("gain_db") else [])
    d = track(tid)
    d["automation"] = {"gain_db": total, "owner": OWNER, "reason": f"direction {dir_id}: " + " + ".join(what),
                       "move_ref": [_ref(dir_id, r) for r in refs]}


def _director_items(data: dict) -> list[dict]:
    out = []
    for t in data.get("tracks") or []:
        for it in t.get("chain") or []:
            if it.get("owner") == OWNER or it.get("move_ref"):
                out.append({"holder": t.get("id"), **it})
        for s in t.get("sends") or []:
            if s.get("owner") == OWNER:
                out.append({"holder": t.get("id"), "id": f"send:{t.get('id')}->{s.get('bus')}", **s})
        a = t.get("automation")
        if isinstance(a, dict) and a.get("owner") == OWNER:
            out.append({"holder": t.get("id"), "id": f"automation:{t.get('id')}", "move_ref": a.get("move_ref")})
    for bu in data.get("buses") or []:
        if bu.get("owner") == OWNER:
            out.append({"holder": bu.get("id"), "id": f"bus:{bu.get('id')}", "move_ref": bu.get("move_ref")})
        for it in bu.get("chain") or []:
            if it.get("owner") == OWNER or it.get("move_ref"):
                out.append({"holder": bu.get("id"), **it})
    return out


def apply(project: str | Path, doc_path: str | Path, *, actor: str = "agent", validate_first: bool = True,
          calibrate: bool = False) -> dict:
    """Apply a direction to a project that holds the floor mix (a copy; the floor itself is never touched).

    ``calibrate``: choose the range values inside the declared ranges by predicting the claims at the
    mix stage (``director.calibrate``) instead of taking every ``select`` blindly; the choice and every
    prediction are kept in the apply record (``calibration``)."""
    from mankomix.core import api
    from mankomix.core import mixplan
    root = Path(project)
    doc = parse_document(doc_path)
    if validate_first:
        v = validate(doc, root)
        if not v["ok"]:
            return {"kind": "direction_apply", "id": doc["id"], "applied": False, "validation": v}
    proj = _Project(root)
    if _director_items(proj.data):
        raise DirectionError("the project already holds a direction's moves; apply to a fresh copy of the floor")
    ddir = root / DIRECTIONS_DIR
    ddir.mkdir(parents=True, exist_ok=True)
    rec_path = ddir / f"{doc['id']}.apply.json"
    if rec_path.is_file():
        raise DirectionError(f"{doc['id']} was already applied to this project")
    # the edit stage (UPGRADE2 §1, U-19): before calibration, cleanup and the mix; skipped (and its
    # module never imported) when the direction has no edit move
    edit_moves = [m for m in doc["block"].get("moves") or [] if m.get("op") in _edit_ops()]
    edits = None
    if edit_moves:
        from . import edit as E
        extensions = X.specs(OPS)
        builtin_edits = [m for m in edit_moves if m.get('op') in EDIT_OPS]
        edits = E.apply_moves(root, doc, builtin_edits, actor=actor) if builtin_edits else {
            "record": {}, "summary": {"moves": 0, "regions": 0, "refused": 0,
                                      "ledger": f"directions/{doc['id']}.edits.json"}}
        for move in edit_moves:
            if move['op'] not in extensions:
                continue
            try:
                row = X.apply_edit(root, doc, move, extensions[move['op']], actor=actor)
            except ValueError as exc:
                raise DirectionError(f"{move['id']}: {exc}") from exc
            edits['record'][move['id']] = row
            edits['summary']['moves'] += 1
            kind = 'derived' if row['kind'] == 'derived' else 'clip_edits'
            edits['summary'][kind] = edits['summary'].get(kind, 0) + 1
        proj = _Project(root)
    cal = None
    if calibrate:
        from . import calibrate as C
        cal = C.calibrate(root, _without_edit_params(doc) if edit_moves else doc)
    # frozen copies of the director's documents
    shutil.copyfile(doc["path"], ddir / f"{doc['id']}.md")
    apath = Path(doc["path"]).parent / "analysis.md"
    if apath.is_file():
        shutil.copyfile(apath, ddir / f"{doc['id']}.analysis.md")
    prop, record, notes = build_proposal(proj, doc, sel=(cal or {}).get("selection"))
    out: dict = {"kind": "direction_apply", "id": doc["id"], "applied": True, "notes": notes,
                 "gate_definitions": gate_definitions_hash(), "floor_mix_proposal": proj.floor_mxp_id}
    if cal is not None:
        out["calibration"] = cal
    if edits is not None:
        record["moves"].update(edits["record"])
        out["edits"] = edits["summary"]
    if record["cleanup"]:
        cl = []
        for c in record["cleanup"]:
            r = api.clean_plan(str(root), targets=[c["target"]], overrides=c["overrides"], apply=True, actor=actor)
            cl.append({"move": c["move"], "proposal_id": r.get("proposal_id"), "applied": r.get("applied"),
                       "note": r.get("note")})
        out["cleanup"] = cl
    if prop is not None:
        mixplan.save_mix_proposal(_ApiProj(root), prop)
        r = api.plan_apply(str(root), prop["proposal_id"], actor=actor)
        if isinstance(r, dict) and r.get("error"):
            raise DirectionError(f"plan apply failed: {r.get('error')}")
        if prop["changes"].get("bus_overrides"):
            from .duck_curve import apply_bus_overrides
            apply_bus_overrides(root, prop["changes"]["bus_overrides"], actor)
        out["mix_proposal"] = prop["proposal_id"]
        out["mix_changes_sha256"] = canonical_hash(prop["changes"])[:16]
    variant = (doc["block"].get("variants") or [{}])[0]
    out["master"] = {"profile": variant.get("profile", "streaming_universal"),
                     "delivery": (variant.get("delivery") or [None])[0],
                     "target_lufs": record["master_target"] if record["master_target"] is not None
                     else variant.get("target_lufs")}
    out["record"] = record
    rec_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out["record_path"] = f"{DIRECTIONS_DIR}/{rec_path.name}"
    return out


def _without_edit_params(doc: dict) -> dict:
    """The document as calibration sees it: edit moves keep their claims and safeguards but carry no
    parameter, so no edit parameter is ever a calibration knob (§1.3)."""
    d = copy.deepcopy(doc)
    for m in d["block"].get("moves") or []:
        if m.get("op") in _edit_ops():
            m["params"] = {}
    return d


class _ApiProj:
    """The minimum mixplan.save_mix_proposal needs (a root)."""

    def __init__(self, root: Path):
        self.root = root


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def _render_file(root: Path, vid: str, delivery: str = "hires_native") -> Path | None:
    d = root / "renders" / vid
    if not d.is_dir():
        return None
    c = sorted(p for p in d.glob(f"*__{delivery}.wav") if not p.name.startswith("master__"))
    return c[0] if c else None


def _terms(root: Path, vid: str | None) -> dict:
    data = _read_json(root / "project.json")
    vs = data.get("variants") or []
    v = next((x for x in vs if vid is None or x.get("id") == vid), None) or {}
    return {t.get("key"): t for t in (v.get("evaluation") or {}).get("terms") or []}


def _scalar(v: Any) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
        return float(v)
    return None


def _judge(q: dict, floor_v: float | None, test_v: float | None, *, p_floor: dict | None = None,
           p_test: dict | None = None) -> dict:
    d = q.get("direction")
    res = {"quantity": q.get("quantity"), "direction": d, "floor": floor_v, "result": test_v}
    if d == "not_worse" and p_floor is not None and p_test is not None and \
            _scalar(p_floor.get("penalty")) is not None and _scalar(p_test.get("penalty")) is not None:
        dp = float(p_test["penalty"]) - float(p_floor["penalty"])
        res.update({"penalty_floor": round(float(p_floor["penalty"]), 4), "penalty_result": round(float(p_test["penalty"]), 4),
                    "verdict": "met" if dp <= float(q.get("tolerance", 0.0)) else "not_met",
                    "basis": "objective penalty (distance from the target range), tolerance on the penalty"})
        return res
    if floor_v is None or test_v is None:
        res["verdict"] = "not_measured"
        return res
    delta = test_v - floor_v
    res["delta"] = round(delta, 4)
    if d == "up":
        ok = delta >= float(q.get("min_delta", 0.0))
    elif d == "down":
        ok = delta <= -float(q.get("min_delta", 0.0))
    else:
        worse = q.get("worse")
        tol = float(q.get("tolerance", 0.0))
        if worse == "up":
            ok = delta <= tol
        elif worse == "down":
            ok = delta >= -tol
        else:
            ok = abs(delta) <= tol
    res["verdict"] = "met" if ok else "not_met"
    return res


def reference_distance(block: dict, obs_vals: dict) -> dict | None:
    """Distance of the floor and of the result from the reference value, per observation with a
    ``ref_value`` (reference only: U-7). None when no observation carries one (the outcome then has
    no such field and stays byte-identical to the format without it).

    Never read by any verdict: claims, expectations, safeguards and the summary are judged against the
    floor exactly as before, and ``--calibrate`` does not read ``ref_value`` either."""
    with_ref = [o for o in block.get("observations") or []
                if isinstance(o, dict) and _scalar(o.get("ref_value")) is not None]
    if not with_ref:
        return None
    rows = {}
    for o in with_ref:
        ref = float(o["ref_value"])
        ov = obs_vals.get(o.get("id")) or {}
        f, r = _scalar((ov.get("floor") or {}).get("value")), _scalar((ov.get("result") or {}).get("value"))
        df = None if f is None else round(abs(f - ref), 4)
        dr = None if r is None else round(abs(r - ref), 4)
        rows[o.get("id")] = {"ref_value": ref, "floor": df, "result": dr,
                             "change": None if df is None or dr is None else round(dr - df, 4)}
    return {"note": "reference only (U-7): |value - ref_value| for the floor and the result, measured as the "
                    "observation is (result level-matched to the floor); change < 0 = the result is nearer. "
                    "Not part of any verdict: the claims are judged against the floor",
            "by_observation": rows}


def check(project: str | Path, floor: str | Path, doc_path: str | Path, *, variant: str | None = None,
          delivery: str = "hires_native", translation: bool = False, edit_list: bool = False,
          contour: bool = False) -> dict:
    """Judge the applied direction against the floor -> ``directions/dir_<id>.outcome.json``.

    ``translation``: add the ``translation`` block (UPGRADE2 §3.5; reference only, read by no verdict,
    summary or calibration). Without it the outcome is unchanged."""
    root, froot = Path(project), Path(floor)
    doc = parse_document(doc_path)
    b = doc["block"]
    rec_path = root / DIRECTIONS_DIR / f"{doc['id']}.apply.json"
    rec = _read_json(rec_path) if rec_path.is_file() else None
    proj = _Project(root)
    v = proj.variant(variant) or {}
    vid = v.get("id")
    fproj = _Project(froot)
    fv = fproj.variant(vid) or fproj.variant() or {}
    tfile, ffile = _render_file(root, vid, delivery), _render_file(froot, fv.get("id"), delivery)
    out: dict = {"kind": "direction_outcome", "schema_version": 1, "direction": doc["id"],
                 "song": b.get("song"), "pattern": (b.get("request") or {}).get("pattern"),
                 "request": (b.get("request") or {}).get("utterance"), "variant": vid,
                 "files": {"result": tfile.name if tfile else None, "floor": ffile.name if ffile else None}}
    if tfile is None or ffile is None:
        out["status"] = "incomplete"
        out["reason"] = "rendered files missing (render the project and the floor first)"
        return out
    x, sr = audio_io.read(tfile)
    y, sr2 = audio_io.read(ffile)
    if sr != sr2:
        raise DirectionError("the result and the floor have different sample rates")
    lt, lf = Q.integrated_lufs(x, sr), Q.integrated_lufs(y, sr)
    match = lf - lt
    out["loudness"] = {"result_lufs_i": round(lt, 3), "floor_lufs_i": round(lf, 3), "level_match_gain_db": round(match, 3)}
    sections = proj.sections()
    obs_vals: dict = {}
    # Track / mix signals only when requested. StemSource reuses its mix render, or builds it
    # from valid cleanup caches; the delivered masters above are never used as a mix-stage signal.
    src_t = src_f = None
    if any(isinstance(o, dict) and S.needs_stems(o) for o in b.get("observations") or []):
        src_t, src_f = S.StemSource(root, vid), S.StemSource(froot, fv.get("id"))
    for o in b.get("observations") or []:
        if src_t is not None and S.needs_stems(o):
            obs_vals[o.get("id")] = {"floor": S.observe(src_f, o, sections=sections),
                                     "result": S.observe(src_t, o, sections=sections)}
            continue
        try:
            g = match if o.get("level_match", True) else 0.0
            rt = Q.observe(x, sr, o, sections=sections, gain_db=g)
            rf = Q.observe(y, sr, o, sections=sections, gain_db=0.0)
        except Q.QueryError as e:
            rt = rf = {"status": "error", "reason": str(e)}
        obs_vals[o.get("id")] = {"floor": rf, "result": rt}
    out["observations"] = obs_vals
    rd = reference_distance(b, obs_vals)
    if rd is not None:
        out["reference_distance"] = rd
    if translation:
        from . import translation as TR
        out["translation"] = TR.block(x, y, sr, match)
    if edit_list:
        from . import editlist as EL
        out["edit_list"] = EL.block(doc, proj, fproj, rec, result_source=src_t, floor_source=src_f,
                                    variant=vid, floor_variant=fv.get("id"))
    if contour:
        from . import contour as CT
        out["contour"] = CT.block(x, y, sr, match, fproj.sections())
    fr = b.get("frame")
    if isinstance(fr, dict) and "tolerances" in fr:
        # X-01: reuse observations; this block is read by no verdict, summary or calibration.
        rows = []
        for tolerance in fr["tolerances"]:
            ov = obs_vals.get(tolerance["quantity"][4:]) or {}
            values = []
            for side in ("floor", "result"):
                measured = ov.get(side) or {}
                values.append(None if measured.get("status") == "error" else _scalar(measured.get("value")))
            f, r = values
            lo, hi = tolerance["range"]
            rows.append({"quantity": tolerance["quantity"], "range": tolerance["range"],
                         "floor": None if f is None else round(f, 3),
                         "result": None if r is None else round(r, 3),
                         "within": None if f is None or r is None else lo <= r <= hi})
        out["frame"] = {"tolerances": rows, "note": "参考値。どの判定にも入らない"}
    sc = b.get("scene")
    if isinstance(sc, dict):
        # FBREVIEW FR-4: reference only (read by no verdict, summary or calibration); only with a scene
        if src_t is None:
            src_t, src_f = S.StemSource(root, vid), S.StemSource(froot, fv.get("id"))
        out["scene"] = scene_block(sc, src_t, src_f)
        if "room" in sc:
            out["scene"]["room"] = sc["room"]
    tterms, fterms = _terms(root, vid), _terms(froot, fv.get("id"))

    def value(qty: str) -> tuple[float | None, float | None, dict | None, dict | None]:
        if qty.startswith("obs:"):
            ov = obs_vals.get(qty[4:]) or {}
            return ((ov.get("floor") or {}).get("value"), (ov.get("result") or {}).get("value"), None, None)
        base = qty.split(":", 1)[0]
        ft = fterms.get(qty) or fterms.get(base) or {}
        tt = tterms.get(qty) or tterms.get(base) or {}
        return _scalar(ft.get("value")), _scalar(tt.get("value")), (ft or None), (tt or None)

    claims = []
    for c in b.get("claims") or []:
        fv_, tv_, pf, pt = value(c.get("quantity", ""))
        j = _judge(c, fv_, tv_, p_floor=pf, p_test=pt)
        j.update({"id": c.get("id"), "primary": bool(c.get("primary"))})
        claims.append(j)
    out["claims"] = claims
    cal = (rec or {}).get("calibration")
    if isinstance(cal, dict) and cal.get("evaluations"):
        ce = next((e for e in cal["evaluations"] if e.get("label") == cal.get("chosen")), None) or {}
        pred = ce.get("deltas") or {}
        out["calibration"] = {
            "chosen": cal.get("chosen"), "changed": cal.get("changed"),
            "prediction_vs_master": {oid: {"predicted": v, "measured": (lambda r, f: None if r is None or f is None
                                                                        else round(r - f, 4))(
                (obs_vals.get(oid, {}).get("result") or {}).get("value"),
                (obs_vals.get(oid, {}).get("floor") or {}).get("value"))} for oid, v in pred.items()},
            "unreached_in_ranges": cal.get("unreached_in_ranges")}
    mv = []
    for m in b.get("moves") or []:
        for kind in ("expect", "safeguard"):
            for q in m.get(kind) or []:
                fv_, tv_, pf, pt = value(q.get("quantity", ""))
                j = _judge(q, fv_, tv_, p_floor=pf, p_test=pt)
                j.update({"move": m.get("id"), "kind": kind,
                          "note": "evaluated on the combined result (moves are not isolated in v0)"})
                mv.append(j)
    out["move_checks"] = mv
    # move_ref coverage
    items = _director_items(proj.data)
    refs: dict[str, list] = {}
    bad = []
    mids = {m.get("id") for m in b.get("moves") or []}
    for it in items:
        rr = it.get("move_ref")
        for r in (rr if isinstance(rr, list) else [rr]):
            if not isinstance(r, str) or not r.startswith(doc["id"] + "/") or r.split("/", 1)[1] not in mids:
                bad.append({"item": it.get("id"), "move_ref": r})
            else:
                refs.setdefault(r.split("/", 1)[1], []).append(it.get("id"))
    missing = []
    recorded = (rec or {}).get("record", {}).get("moves", {})
    extensions = X.specs(OPS)
    for m in b.get("moves") or []:
        op = m.get("op")
        if op in extensions:
            row = recorded.get(m.get('id')) or {}
            traced = row.get('op') == op and row.get('track') == m.get('target')
            if extensions[op].stage == 'mix':
                traced = traced and isinstance(row.get('trace'), list) and all(
                    item in refs.get(m.get('id'), []) for item in row.get('trace', []))
            else:
                lp = root / DIRECTIONS_DIR / f"{doc['id']}.edits.json"
                group = 'clip_edits' if row.get('kind') == 'clip_edit' else 'derived'
                entry = ((_read_json(lp).get(group) or {}).get(m.get('id')) or {}) if lp.is_file() else {}
                traced = traced and entry.get('op') == op and entry.get('status') == 'applied' \
                    and entry.get('result') == row.get('result')
            if not traced:
                missing.append(m.get('id'))
        elif op in ("chain_add", "chain_param", "send", "bus_add") or (op == "pan" and str(m.get("target")).startswith("bus_")) \
                or (op == "gain" and m.get("section") not in (None, "all")) \
                or op == "gain_curve" \
                or (op in ("duck", "duck_curve") and (recorded.get(m.get("id")) or {}).get("hits") != 0):
            if m.get("id") not in refs:
                missing.append(m.get("id"))
        elif op == "place":
            # FR-5: traced by the apply record; the shelf and the send it added carry its move_ref
            dv = (recorded.get(m.get("id")) or {}).get("derived")
            if not isinstance(dv, dict):
                missing.append(m.get("id"))
            elif ((dv.get("air_gain_db") or 0.0) != 0.0 or dv.get("send_level_db") is not None) \
                    and m.get("id") not in refs:
                missing.append(m.get("id"))
        elif m.get("id") not in recorded:
            missing.append(m.get("id"))
    out["move_ref"] = {"items": len(items), "by_move": refs, "unknown_refs": bad, "moves_without_trace": missing,
                       "ok": not bad and not missing}
    # the edit ledger (only when the direction has an edit move; otherwise the outcome has no such field)
    led_path = root / DIRECTIONS_DIR / f"{doc['id']}.edits.json"
    if led_path.is_file():
        led = _read_json(led_path)
        lmv = led.get("moves") or {}
        out["edits"] = {"moves": len(lmv), "regions": sum(len(e.get("regions") or []) for e in lmv.values()),
                        "refused": sum(len(e.get("refused") or []) for e in lmv.values()),
                        "removed_energy_rel_db": {k: e.get("removed_energy_rel_db") for k, e in lmv.items()},
                        "status": {k: e.get("status") for k, e in lmv.items()},
                        "ledger": f"{DIRECTIONS_DIR}/{led_path.name}", "reverted": bool(led.get("reverted"))}
        if led.get('derived'):
            out['edits']['derived'] = {mid: {k: row.get(k) for k in ('op', 'track', 'status', 'key', 'result')}
                                       for mid, row in led['derived'].items()}
        if led.get('clip_edits'):
            out['edits']['clip_edits'] = {mid: {k: row.get(k) for k in ('op', 'track', 'status', 'params')}
                                          for mid, row in led['clip_edits'].items()}
    # gate definitions before / after
    now = gate_definitions_hash()
    before = (rec or {}).get("gate_definitions")
    out["gate_definitions"] = {"at_apply": (before or {}).get("combined"), "at_check": now["combined"],
                               "unchanged": bool(before) and before.get("combined") == now["combined"]}
    # convergence with the floor
    def mix_state(data: dict) -> str:
        keep = ("gain_db", "pan", "chain", "sends", "automation", "clips")
        return canonical_hash({"tracks": {t.get("id"): {k: t.get(k) for k in keep} for t in data.get("tracks") or []},
                               "buses": data.get("buses")})[:16]
    n = min(x.shape[0], y.shape[0])
    diff = x[:n] * (10 ** (match / 20.0)) - y[:n]
    rms_diff = float(np.sqrt(np.mean(diff ** 2)))
    rms_floor = float(np.sqrt(np.mean(y[:n] ** 2)))
    rel = 20 * math.log10(max(rms_diff, 1e-15) / max(rms_floor, 1e-15))
    same_mix = mix_state(proj.data) == mix_state(fproj.data)
    same_chain = canonical_hash((v.get("master") or {}).get("chain")) == canonical_hash((fv.get("master") or {}).get("chain"))
    out["convergence"] = {"mix_state_equal": same_mix, "master_chain_equal": same_chain,
                          "diff_rms_rel_db": round(rel, 2), "frames_compared": int(n),
                          "converged": same_mix or rel < -60.0}
    prim = [c for c in claims if c.get("primary")]
    out["summary"] = {"primary_met": sum(1 for c in prim if c.get("verdict") == "met"), "primary": len(prim),
                      "claims_met": sum(1 for c in claims if c.get("verdict") == "met"), "claims": len(claims),
                      "safeguards_not_met": [f"{j['move']}:{j['quantity']}" for j in mv
                                             if j["kind"] == "safeguard" and j.get("verdict") == "not_met"]}
    out["status"] = "checked"
    dest = root / DIRECTIONS_DIR / f"{doc['id']}.outcome.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out["outcome_path"] = f"{DIRECTIONS_DIR}/{dest.name}"
    return out


# Declarations may import the public direction helpers; discover after defining them.
X.load(OPS)
