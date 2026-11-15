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

FORMAT_VERSION = 1
OWNER = "director"
DIRECTIONS_DIR = "directions"

OPS = {
    "chain_add": ("mix", ("target", "processor", "params")),
    "chain_param": ("mix", ("target", "replaces", "params")),
    "chain_remove": ("mix", ("target", "replaces")),
    "gain": ("mix", ("target", "params")),
    "pan": ("mix", ("target", "params")),
    "send": ("mix", ("target", "params")),
    "bus_add": ("mix", ("target", "params")),
    "cleanup_override": ("clean", ("target", "params")),
    "master_target": ("master", ("params",)),
}
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
TIME_VARYING = ("compressor", "dynamic_eq", "deesser", "aw.pressure4")
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
                   prefix: str | None = None) -> tuple[dict, list[str]]:
    """Ranges [lo, hi] -> one value by ``select`` (mid / min / max; sweep:* falls back to mid in v0).

    ``sel``: values chosen by calibration, keyed ``<prefix>.<param>`` (prefix: the move id, or
    ``<move id>.chain<i>`` for a bus_add chain item); a chosen value must lie inside the range."""
    out, notes = {}, []
    for k, v in (params or {}).items():
        if _is_range(v):
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


def _ends(params: dict) -> list[dict]:
    """The parameter sets at both ends of every range (both ends must be inside the declared range)."""
    if not any(_is_range(v) for v in params.values()):
        return [params]
    lo = {k: (min(v) if _is_range(v) else v) for k, v in params.items()}
    hi = {k: (max(v) if _is_range(v) else v) for k, v in params.items()}
    return [lo, hi]


def _check_proc_params(ptype: str, params: dict, stage: str, where: str, errors: list) -> dict | None:
    ends = _ends(params)
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


def validate(doc: dict, project: str | Path | None = None) -> dict:
    """Validate a parsed direction. ``project``: the project it will be applied to (targets, replaces, sections)."""
    b = doc["block"]
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
        if o.get("primitive") not in Q.PRIMITIVES:
            err(f"observations.{oid}", "bad_value", f"unknown primitive '{o.get('primitive')}'")
        if o.get("target", "master") != "master":
            warn(f"observations.{oid}", "unsupported", f"target '{o.get('target')}' is not supported in v0 "
                                                       "(only master); the observation will be reported unsupported")
        sec = o.get("section", "all")
        if isinstance(sec, str) and sec != "all" and proj and sec not in sections:
            err(f"observations.{oid}", "unknown_section", f"unknown section '{sec}'")
        if "ref_value" in o and o["ref_value"] is not None and _scalar(o["ref_value"]) is None:
            err(f"observations.{oid}.ref_value", "bad_value", "ref_value must be a finite number (or null)")
    _validate_reference_fields(b, err)

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
        if op not in OPS:
            err(where, "bad_op", f"unknown op '{op}' (valid: {', '.join(OPS)})")
            continue
        stage, req = OPS[op]
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
            if op != "gain":
                err(where, "section_scope", "only 'gain' can be limited to a section (other ops: tool_requests)")
            elif isinstance(sec, str) and proj and sec not in sections:
                err(where, "unknown_section", f"unknown section '{sec}'")
            elif isinstance(sec, dict) and not ({"t0_s", "t1_s"} <= set(sec)):
                err(where, "bad_value", "a time section needs t0_s and t1_s")
        params, rnotes = resolve_params(m, m.get("params") or {})
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
        if op == "chain_add":
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
        # review tier (assigned here, not self-declared). E1 is only the catalog range check: a move
        # taken from another work (origin: reference) is E2 or above (another song's facts are no
        # guarantee here), and citing a theory card (KT-nnnn) never makes a move E1
        tier = "E2"
        cited = set(re.findall(r"R-\d{2}", str(m.get("basis") or "")))
        if m.get("origin") == "catalog" and cited and cited <= rule_ids:
            tier = "E1"
        if op == "master_target":
            prof = _profile((variants[0] if variants else {}).get("profile") or "")
            dflt = ((prof or {}).get("loudness") or {}).get("target_lufs_i")
            if dflt is not None and params.get("target_lufs") is not None and float(params["target_lufs"]) != float(dflt):
                tier = "E3"
        if target == LEAD and ((op == "gain" and sec not in (None, "all"))
                               or (op == "chain_add" and proc in TIME_VARYING)):
            tier = "E3"
            lead_e3 = True
        if tier == "E3" and not b.get("listen_for"):
            warn(where, "listen_for", "an E3 move needs listen_for entries")
        tiers[mid] = tier
    if lead_e3 and not b.get("listen_for"):
        warn("listen_for", "missing", "E3 moves on the lead need listen_for")
    return {"kind": "direction_validation", "id": doc["id"], "ok": not errors, "errors": errors,
            "warnings": warnings, "tiers": tiers, "notes": notes,
            "moves": len(b.get("moves") or []), "claims": len(claims), "observations": len(obs)}


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

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
    # new buses first so sends can reach them
    for m in b.get("moves") or []:
        if m.get("op") != "bus_add":
            continue
        params, n = resolve_params(m, m.get("params") or {}, sel)
        notes += n
        chain = []
        for i, c in enumerate(params.get("chain") or []):
            cp, cn = resolve_params(m, c.get("params") or {}, sel, f"{m['id']}.chain{i}")
            notes += cn
            ptype = c.get("type") or c.get("processor")
            chain.append(_item(dir_id, m, ptype, P.validate_params(ptype, cp), m["target"], f".{i + 1}"))
        ch["buses"].append({"id": m["target"], "kind": params.get("kind", "fx"),
                            "name": params.get("name") or f"{m['target']} (direction {dir_id})",
                            "output": params.get("output", "bus_mix"), "owner": OWNER, "chain": chain,
                            "move_ref": _ref(dir_id, m["id"])})
        record["moves"][m["id"]] = {"op": "bus_add", "bus": m["target"], "items": [c["id"] for c in chain]}
    for m in b.get("moves") or []:
        op, mid, target = m.get("op"), m.get("id"), m.get("target")
        params, n = resolve_params(m, m.get("params") or {}, sel)
        notes += n
        if op == "bus_add":
            continue
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
    for tid, segs in seg_gain.items():
        d = track(tid)
        pts = _automation(proj.rate, [s[:3] for s in segs], (cur[tid].get("automation") or {}).get("gain_db"))
        d["automation"] = {"gain_db": pts, "owner": OWNER, "reason": f"direction {dir_id}: section gains",
                           "move_ref": [_ref(dir_id, s[3]) for s in segs]}
    mix_moves = [m for m in b.get("moves") or [] if OPS.get(m.get("op"), ("",))[0] == "mix"]
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
    cal = None
    if calibrate:
        from . import calibrate as C
        cal = C.calibrate(root, doc)
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
          delivery: str = "hires_native") -> dict:
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
    for o in b.get("observations") or []:
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
    for m in b.get("moves") or []:
        op = m.get("op")
        if op in ("chain_add", "chain_param", "send", "bus_add") or (op == "pan" and str(m.get("target")).startswith("bus_")) \
                or (op == "gain" and m.get("section") not in (None, "all")):
            if m.get("id") not in refs:
                missing.append(m.get("id"))
        elif m.get("id") not in recorded:
            missing.append(m.get("id"))
    out["move_ref"] = {"items": len(items), "by_move": refs, "unknown_refs": bad, "moves_without_trace": missing,
                       "ok": not bad and not missing}
    # gate definitions before / after
    now = gate_definitions_hash()
    before = (rec or {}).get("gate_definitions")
    out["gate_definitions"] = {"at_apply": (before or {}).get("combined"), "at_check": now["combined"],
                               "unchanged": bool(before) and before.get("combined") == now["combined"]}
    # convergence with the floor
    def mix_state(data: dict) -> str:
        keep = ("gain_db", "pan", "chain", "sends", "automation")
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
