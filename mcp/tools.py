"""MCP tool table (SPEC 10.3): one declarative entry per core API function.

Every tool wraps exactly one function of ``mankomix.core.api`` (SPEC 10.1:
the CLI and MCP faces wrap the core 1:1; no face has logic of its own). The
input schema of a tool is derived from the API function's signature, so a
new API function becomes a tool by adding one ``ToolSpec`` line. Entries
whose API function does not exist yet are skipped (``hasattr`` guard) and
show up automatically once the function lands in ``core/api.py``.

Face-level adaptation is limited to:

- path arguments are resolved inside the workspace root (``workspace.py``);
- the ``actor`` argument is always ``"agent"`` (SPEC 9.5 journal);
- results are summarised by default; ``detail: "full"`` returns everything;
- long tools accept ``async: true`` and run as a job (``jobs.py``).
"""

from __future__ import annotations

import ast
import inspect
import json
import logging
import math
import re
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from mankomix.core import api
from mankomix.core.errors import InputError, MankoError

from .jobs import FAILED, FINISHED, JobManager
from .workspace import Workspace

log = logging.getLogger("mankomix.mcp")

ACTOR = "agent"
DETAILS = ("summary", "full")

# Parameter kinds, by API parameter name.
_PROJECT_PARAMS = {"project_path"}
_PATH_PARAMS = {"path", "file", "path_a", "path_b", "source", "out", "out_dir", "weights"}
_PATH_SUFFIXES = ("_path", "_dir", "_file", "_folder")
_PATHS_PARAMS = {"sources", "files", "paths"}


# ---------------------------------------------------------------------------
# summaries (token-cheap views; detail="full" bypasses them)
# ---------------------------------------------------------------------------

def _r(x: Any, nd: int = 2) -> Any:
    if isinstance(x, float):
        return round(x, nd) if math.isfinite(x) else None
    return x


def compact(obj: Any, *, depth: int = 3, max_items: int = 8, max_str: int = 200) -> Any:
    """Generic summary: rounded floats, shallow nesting, short lists and strings."""
    if isinstance(obj, float):
        return _r(obj, 3)
    if isinstance(obj, str):
        return obj if len(obj) <= max_str else obj[: max_str - 1] + "…"
    if isinstance(obj, dict):
        if depth <= 0:
            return f"{{{len(obj)} keys}}"
        return {k: compact(v, depth=depth - 1, max_items=max_items, max_str=max_str) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        if depth <= 0:
            return f"[{len(obj)} items]"
        head = [compact(v, depth=depth - 1, max_items=max_items, max_str=max_str) for v in obj[:max_items]]
        if len(obj) > max_items:
            head.append(f"... {len(obj) - max_items} more")
        return head
    return obj


SMALL_RESULT_CHARS = 1500


def default_summary(r: Any) -> Any:
    """Small results pass through (floats rounded); larger ones are compacted."""
    if len(json.dumps(r, ensure_ascii=False, default=str)) <= SMALL_RESULT_CHARS:
        return compact(r, depth=64, max_items=10_000, max_str=10_000)
    return compact(r)


def _sum_doctor(r: dict) -> dict:
    ff = r.get("ffmpeg") or {}
    models = r.get("models") or {}
    return {"status": r.get("status"), "engine_version": r.get("engine_version"),
            "ffmpeg": {k: ff.get(k) for k in ("found", "version", "build") if k in ff},
            "gpu": (r.get("gpu") or {}).get("status"),
            "models": {k: models.get(k) for k in ("status", "official", "candidate", "byow", "downloaded",
                                                   "byow_available") if k in models},
            "issues": [{"level": i.get("level"), "code": i.get("code")} for i in r.get("issues") or []]}


def _sum_status(r: dict) -> dict:
    tb = r.get("timebase") or {}
    tracks = r.get("tracks") or []
    last = (r.get("last_journal") or [{}])[-1] if r.get("last_journal") else {}
    return {
        "project": r.get("project"), "id": r.get("id"), "title": r.get("title"), "genre": r.get("genre"),
        "sample_rate": tb.get("sample_rate"), "length_samples": tb.get("length_samples"),
        "input_kind": (r.get("provenance") or {}).get("input_kind"),
        "assets": [{"id": a.get("id"), "role": a.get("role"), "analysis": a.get("analysis")}
                   for a in r.get("assets") or []],
        "tracks": len(tracks),
        "lead": next((t.get("id") for t in tracks if t.get("is_lead")), None),
        "fullmix": r.get("fullmix"),
        "check_counts": r.get("check_counts"),
        "analysis": (r.get("analysis") or {}).get("states"),
        "last_journal": {k: last.get(k) for k in ("seq", "actor", "op")} if last else None,
    }


def _issues(items: list, limit: int = 10) -> list[dict]:
    out = [{k: i.get(k) for k in ("check", "level", "asset", "path", "message") if i.get(k) is not None}
           for i in items or [] if isinstance(i, dict) and i.get("level") != "info"]
    return out[:limit] + ([{"more": len(out) - limit}] if len(out) > limit else [])


def _sum_validate(r: dict) -> dict:
    return {"valid": r.get("valid"), "counts": r.get("counts"), "issues": _issues(r.get("issues"))}


def _sum_import(r: dict) -> dict:
    imported = []
    for rec in r.get("imported") or []:
        if not isinstance(rec, dict):
            continue
        imported.append({
            "input_kind": rec.get("input_kind"), "pattern_set": rec.get("pattern_set"),
            "assets_added": rec.get("assets_added"), "tracks_added": len(rec.get("tracks_added") or []),
            "fullmix_asset": rec.get("fullmix_asset"),
            "lead": (rec.get("lead_estimate") or {}).get("track"),
            "skipped": len(rec.get("skipped") or []), "rejects": len(rec.get("rejects") or []),
            "warnings": rec.get("warnings") or [],
        })
    return {"assets": r.get("assets"), "check_counts": r.get("check_counts"), "imported": imported,
            "checks": _issues(r.get("checks"))}


def _sum_analyze(r: dict) -> dict:
    ss = r.get("stem_sum")
    return {"analyzer_version": r.get("analyzer_version"), "assets": len(r.get("assets") or []),
            "measured": r.get("measured"), "cached": r.get("cached"), "saved": r.get("saved"),
            "stem_sum": ss.get("stems") if isinstance(ss, dict) else None,
            "warnings": r.get("warnings") or []}


_LOUDNESS_KEYS = ("integrated_lufs", "short_term_max_lufs", "lra_lu", "true_peak_dbtp", "sample_peak_dbfs",
                  "plr_db", "psr_db")


def _vector_summary(v: dict) -> dict:
    if not isinstance(v, dict):
        return {}
    out: dict[str, Any] = {}
    p03 = v.get("P-03") or {}
    out["loudness"] = {k: _r(p03.get(k)) for k in _LOUDNESS_KEYS if k in p03}
    bands = (v.get("P-07") or {}).get("bands") or {}
    if bands:
        out["band_level_db"] = {b: _r(d.get("level_db"), 1) for b, d in bands.items() if isinstance(d, dict)}
    corr = ((v.get("P-05") or {}).get("full_band") or {}).get("correlation")
    mono = ((v.get("P-06") or {}).get("full_band") or {}).get("mono_loss_db")
    if corr is not None or mono is not None:
        out["stereo"] = {"correlation": _r(corr), "mono_loss_db": _r(mono)}
    h = v.get("health") or {}
    out["health"] = {k: h.get(k) for k in ("nan_count", "inf_count", "clipped_samples", "clip_runs", "silent")
                     if k in h}
    out["measures"] = sorted(k for k in v if re.match(r"^(P-\d+|LTAS)$", str(k)))
    if v.get("notes"):
        out["notes"] = v["notes"]
    return out


def _sum_measure(r: dict) -> dict:
    inf = r.get("info") or {}
    return {"file": r.get("file"),
            "info": {k: inf.get(k) for k in ("sample_rate", "channels", "duration_s", "subtype", "lossy")},
            **_vector_summary(r.get("vector") or {})}


def _sum_compare(r: dict, top: int = 12) -> dict:
    c = r.get("comparison") or {}
    deltas = []
    for k, d in (c.get("deltas") or {}).items():
        if isinstance(d, dict) and isinstance(d.get("delta"), (int, float)) and "partition_bands" not in k:
            deltas.append((k, d))
    deltas.sort(key=lambda kd: -abs(kd[1]["delta"]))
    out = {"a": r.get("a"), "b": r.get("b"),
           "match_gain_db": _r(c.get("match_gain_db")), "matched_side": c.get("matched_side"),
           "rule": c.get("rule"),
           "largest_deltas": {k: {"delta": _r(d["delta"]), "unit": d.get("unit")} for k, d in deltas[:top]},
           "deltas_total": len(c.get("deltas") or {})}
    if r.get("resampled"):
        out["resampled"] = r["resampled"]
    return out


def _sum_project_get(r: dict) -> dict:
    v = r.get("value")
    if r.get("pointer"):
        return {"pointer": r["pointer"], "value": compact(v)}
    if isinstance(v, dict):
        shape = {k: (f"[{len(x)}]" if isinstance(x, list) else f"{{{len(x)}}}" if isinstance(x, dict) else x)
                 for k, x in v.items()}
        return {"pointer": "", "value": shape,
                "hint": "pass pointer (e.g. /tracks/0) or detail='full' for the whole document"}
    return {"pointer": "", "value": compact(v)}


def _keep(r: dict) -> dict:
    return r


def _sum_models(r: dict) -> dict:
    return {"models": [{k: m.get(k) for k in ("id", "tier", "status", "task", "stems", "license_weights",
                                              "usage_restrictions", "state", "installed", "cpu_ok", "light",
                                              "default_for")}
                       for m in r.get("models") or [] if isinstance(m, dict)],
            "defaults": r.get("defaults"), "byow_notice": r.get("byow_notice"),
            "hint": "model_get for license evidence and files; detail='full' for everything"}


def _sum_separate(r: dict) -> dict:
    return {k: r.get(k) for k in ("separation", "model_id", "model_sha256", "mode", "source_asset", "excerpt",
                                  "stems", "assets_added", "tracks_added", "tracks_muted", "device",
                                  "elapsed_s", "attribution", "restriction", "warnings")} | {
        "license": {k: (r.get("license") or {}).get(k) for k in ("code", "weights", "usage_restrictions")},
        "residual_db": (r.get("postprocess") or {}).get("residual_db")}


def _sum_proposals(r: dict) -> dict:
    return {"count": r.get("count"),
            "proposals": [{k: p.get(k) for k in ("id", "stage", "variant", "author", "status", "created_at",
                                                 "score", "reject_reason")} | {"steps": len(p.get("steps") or [])}
                          for p in r.get("proposals") or [] if isinstance(p, dict)]}


def _sum_analysis_view(r: dict) -> dict:
    loud = r.get("loudness") or {}
    return {"variant": r.get("variant"), "before_kind": r.get("before_kind"), "files": r.get("files"),
            "integrated_lufs": loud.get("integrated_lufs"), "true_peak_dbtp": loud.get("true_peak_dbtp"),
            "lra_lu": loud.get("lra_lu"), "metrics": r.get("metrics"),
            "stems": [{k: s.get(k) for k in ("track", "role", "centroid_hz", "level_db", "pan")}
                      for s in r.get("stems") or []],
            "diagnostics": [d for d in r.get("diagnostics") or [] if d.get("status") != "ok"],
            "hint": "detail='full' adds the loudness series, LTAS and band correlation"}


def _sum_plan(r: dict) -> dict:
    """Stage proposal: ids, chain, per-metric breakdown, constraints, gate (the core's own summary)."""
    if not isinstance(r.get("summary"), dict) or "proposal_id" not in r:
        return default_summary(r)
    return {"proposal_id": r["proposal_id"], "proposal_path": r.get("proposal_path"), "applied": r.get("applied"),
            **compact(r["summary"], depth=5, max_items=40)}


def _sum_plan_run(r: dict) -> dict:
    if "proposal_id" not in r:
        return default_summary(r)
    s = r.get("summary") or {}
    return {k: r.get(k) for k in ("proposal_id", "proposal_path", "applied", "score_start", "score_final",
                                  "converged", "reason")} | {
        "iterations": [{"i": it.get("i"), "score": it.get("score"), "improvement": it.get("improvement"),
                        "move": {k: (it.get("move") or {}).get(k) for k in ("kind", "band", "delta_db")}
                        if it.get("move") else None} for it in r.get("iterations") or []],
        "breakdown": compact(s.get("breakdown"), depth=3, max_items=40),
        "gate": s.get("gate"), "constraints": s.get("constraints"),
        "unresolved": sorted({u.get("code") for u in r.get("unresolved") or [] if isinstance(u, dict)}),
    }


def _sum_objective_set(r: dict) -> dict:
    res = r.get("resolved") or {}
    return {"set": r.get("set"), "objective": r.get("objective"), "warnings": r.get("warnings") or [],
            "resolved": {k: res.get(k) for k in ("blend", "intensity", "lead", "genre", "reference", "notes")},
            "terms": len(res.get("terms") or []), "hint": "detail='full' adds the resolved terms and targets"}


def _sum_gate(r: dict) -> dict:
    return {k: r.get(k) for k in ("variant", "source", "file", "profile", "status", "pass", "status_meaning")} | {
        "checks": [{"id": c.get("id"), "status": c.get("status"), "required": c.get("required"),
                    "reason": c.get("reason")} for c in r.get("checks") or []],
        "corrective_suggestions": r.get("corrective_suggestions") or [], "notes": r.get("notes") or []}


def _sum_clean_apply(r: dict) -> dict:
    return {k: r.get(k) for k in ("applied", "stage", "proposal_id", "s07_pass", "noise_baseline_path")} | {
        "assets": [{"asset": a.get("asset"), "kind": a.get("kind"), "skipped": a.get("skipped"),
                    "plan_hash": (a.get("plan_hash") or "")[:12] or None,
                    "s07_pass": (a.get("s07") or {}).get("pass"), "delta": (a.get("files") or {}).get("delta")}
                   for a in r.get("assets") or [] if isinstance(a, dict)],
        "hint": "clean_delta for the removed component of an asset; detail='full' for the records"}


def _sum_mix_apply(r: dict) -> dict:
    return {k: r.get(k) for k in ("applied", "stage", "proposal_id", "variant", "tracks_changed", "buses_added",
                                  "evaluation_stored", "decisions_stored", "score", "gate", "route", "edited",
                                  "note") if k in r}


def _sum_stems(r: dict) -> dict:
    return {"sample_rate": r.get("sample_rate"), "timeline_length": r.get("timeline_length"), "lead": r.get("lead"),
            "tracks": [{k: t.get(k) for k in ("id", "role", "is_lead", "stem", "muted", "gain_db", "chain_length",
                                              "assets")} | {"clips": [{k: c.get(k) for k in
                                                                       ("id", "asset", "timeline_start", "length",
                                                                        "muted")}
                                                                      for c in t.get("clips") or []]}
                       for t in r.get("tracks") or [] if isinstance(t, dict)],
            "unused_assets": r.get("unused_assets"), "notes": r.get("notes")}


def _sum_run(r: dict) -> dict:
    """One-shot pipeline: per-stage status and gate, verification per variant, deliverables."""
    results = r.get("results") or {}
    return {k: r.get(k) for k in ("status", "exit_code", "project", "created", "objective", "route", "stopped_at",
                                  "reason", "error", "summary_file")} | {
        "variants": r.get("variants"),
        "stages": [{k: v for k, v in (("stage", s.get("stage")), ("status", s.get("status")),
                                      ("variant", s.get("variant")), ("gate", (s.get("gate") or {}).get("status")))
                    if v is not None} for s in r.get("stages") or [] if isinstance(s, dict)],
        "verify": {vid: (res.get("verify") or {}).get("overall") for vid, res in results.items()
                   if isinstance(res, dict)},
        "unresolved": [{k: u.get(k) for k in ("stage", "variant", "code", "failed") if u.get(k) is not None}
                       for u in r.get("unresolved") or [] if isinstance(u, dict)],
        "deliverables": (r.get("deliverables") or {}).get("files"),
        "hint": "detail='full' for every stage record; report_get for the Mix Report",
    }


# ---------------------------------------------------------------------------
# declarative table
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    name: str                                   # MCP tool name, group_verb (SPEC 10.3)
    api: tuple[str, ...]                        # candidate core.api names; first one present wins
    description: str
    long: bool = False                          # accepts async=true (job)
    mutates: bool | None = None                 # None: True when the function takes an actor
    rename: dict[str, str] = field(default_factory=dict)        # api param -> tool argument
    schema: dict[str, dict] = field(default_factory=dict)       # per-argument schema overrides
    kinds: dict[str, str] = field(default_factory=dict)         # per-param kind override
    hide: tuple[str, ...] = ()                  # api params not exposed (api default applies)
    summary: Callable[[dict], dict] | None = None
    fallback: Callable[..., dict] | None = None  # used when the API lacks every candidate
    derive: Callable[[dict], None] | None = None  # fill derived defaults into the api kwargs
    derive_ws: Callable[[dict, Any], None] | None = None  # same, with the workspace (path defaults)


def _derive_title(kw: dict) -> None:
    # Same default as `mankomix init`: the folder name without a .mmx suffix.
    if not kw.get("title"):
        kw["title"] = Path(kw["path"]).name.removesuffix(".mmx") or "Untitled"


def _derive_run_project(kw: dict, ws: Any) -> None:
    # Same default as `mankomix run` ('<name>.mmx' next to out), kept inside the workspace.
    if kw.get("project"):
        return
    from mankomix.core.pipeline import default_project_path
    sources = kw.get("sources") or []
    if not sources:
        return
    cand = default_project_path(sources, kw.get("out"))
    try:
        kw["project"] = str(ws.resolve(str(cand), what="project"))
    except InputError:
        kw["project"] = str(ws.root / cand.name)


_P = {"project": {"type": "string", "description": "project folder, relative to the workspace (default '.')"}}

SPECS: list[ToolSpec] = [
    # environment
    ToolSpec("doctor", ("doctor",), "Check dependencies, ffmpeg build/licence, encoders, GPU and models.",
             schema={"strict_lgpl": {"description": "treat a non-LGPL ffmpeg build as an error"}},
             summary=_sum_doctor),
    # project
    ToolSpec("project_init", ("init_project",), "Create a new project folder (project.json, assets/, journal).",
             mutates=True, kinds={"path": "project"}, rename={"path": "project"},
             schema={"title": {"description": "song title (default: folder name)"},
                     "genre": {"description": "genre id for priors, e.g. jpop"}},
             derive=_derive_title),
    ToolSpec("project_open", ("status",), "Open a project and return its summary: assets, tracks, lead, "
             "checks, analysis cache state, last journal entry.", summary=_sum_status),
    ToolSpec("project_get", ("project_get",), "Read project.json, or the value at a JSON pointer.",
             schema={"pointer": {"description": "RFC 6901 pointer, e.g. /tracks/0 ('' = whole document)"}},
             summary=_sum_project_get),
    ToolSpec("project_set", ("set_value",), "Set one value by JSON pointer (schema-validated, journaled).",
             rename={"value_json": "value"}, kinds={"value_json": "json_text"},
             schema={"value": {"description": "new value (any JSON type)"},
                     "pointer": {"description": "JSON pointer, e.g. /tracks/0/gain_db"}},
             summary=_keep),
    ToolSpec("project_patch", ("patch",), "Apply an RFC 6902 JSON patch (schema-validated, journaled).",
             schema={"ops": {"type": "array", "items": {"type": "object"},
                             "description": "RFC 6902 operations"}},
             summary=_keep),
    ToolSpec("project_validate", ("validate_project",), "Validate project.json (schema and invariants).",
             summary=_sum_validate),
    ToolSpec("import_files", ("import_files",), "Import files/folders as-is with the file adapter "
             "(stems, full mix, Suno export sets); runs the import checks.",
             schema={"sources": {"description": "files or folders, relative to the workspace"},
                     "mode": {"enum": ["copy", "link"]},
                     "provenance": {"description": "declared provenance, e.g. {\"service\": \"suno\"}"}},
             summary=_sum_import),
    # analysis
    ToolSpec("analyze_run", ("analyze",), "Measure every asset and the static stem sum (cached by content).",
             long=True, schema={"force": {"description": "ignore the analysis cache"}}, summary=_sum_analyze),
    ToolSpec("measure_audio", ("measure_audio",), "Measure any audio file in the workspace.",
             summary=_sum_measure),
    ToolSpec("compare_audio", ("compare_audio",), "Level-matched comparison of two audio files (b - a).",
             summary=_sum_compare),
    # intent and outlets
    ToolSpec("objective_list", ("objective_list",), "List objective functions (full=true: the complete "
             "definitions).", summary=_keep),
    ToolSpec("objective_get", ("objective_show",), "Show one objective function."),
    ToolSpec("objective_set", ("objective_set",), "Set the project objective (or a variant's override): "
             "blend of objectives with weights, intensity 0-1, declared overrides, lead stem. Safety "
             "invariants (S-nn) are never relaxed.",
             schema={"spec": {"description": "objective spec {blend:[{id,weight}], intensity, overrides, lead_stem} "
                                              "or the short form 'comfort:0.6+bass_heavy:0.4' / 'bass_heavy:0.7'"},
                     "variant": {"description": "variant id to set an override for (default: the project objective)"}},
             summary=_sum_objective_set),
    ToolSpec("objective_validate", ("objective_validate",), "Validate an objective definition (unknown metric "
             "ids, weight sums, declared params, attempts to relax S-nn) or an objective spec.",
             kinds={"path_or_json": "path_or_json"},
             schema={"path_or_json": {"description": "definition or catalog object, JSON text, a .json file "
                                                      "relative to the workspace, or a spec"}}),
    ToolSpec("profile_list", ("profile_list",), "List media profiles and delivery formats "
             "(full=true: the complete definitions).", summary=_keep),
    ToolSpec("delivery_list", ("delivery_list",), "List delivery formats (container, sample rate, bit depth, "
             "dither).", summary=_keep),
    ToolSpec("profile_get", ("profile_show",), "Show one media profile or delivery format."),
    ToolSpec("reference_add", ("reference_add",), "Register a reference track: only its level-matched "
             "measurement vector is stored, never the audio (targets then come from the references).",
             long=True, schema={"audio_path": {"description": "audio file relative to the workspace"}}),
    ToolSpec("reference_list", ("reference_list",), "List registered references and the target source."),
    ToolSpec("reference_remove", ("reference_remove",), "Remove a reference and its stored vector."),
    # stage plans (R-31): propose -> approve and apply / reject and request an alternative
    ToolSpec("plan_propose", ("plan_propose",), "Propose a stage plan: stage 'clean' (cleanup per stem or "
             "the 2-mix), 'mix' (fixed-order mix plan measured per step) or 'master' (planner loop on the chain). "
             "Returns the proposal id and a summary (steps, score breakdown, constraints, translation gate); "
             "nothing is applied.",
             long=True, mutates=True, summary=_sum_plan,
             schema={"stage": {"enum": ["master", "mix", "clean", "cleanup"]},
                     "objective": {"description": "objective for this plan (spec object or 'comfort:0.6+bass_heavy:0.4'); "
                                                  "default: the project's"},
                     "max_iter": {"description": "planner iteration cap (default: master 6, mix 4)"},
                     "targets": {"description": "clean stage: asset ids, track ids or 'fullmix' (default: every stem)"},
                     "overrides": {"description": "clean stage: step overrides, e.g. {\"spectral_reduction\": "
                                                  "\"light\"}, for every target or keyed by asset / track id"}}),
    ToolSpec("plan_apply", ("plan_apply",), "Approve and apply a proposal of any stage (by proposal_id): "
             "cleanup writes cleaned audio and records; mix writes track / bus processing and the decision record; "
             "master stores the chain, the objective evaluation and the decisions. Optional edits change "
             "processor parameters first (mix, master).",
             rename={"proposal_or_id": "proposal"},
             schema={"proposal": {"description": "proposal_id from plan_propose (or the proposal object)"},
                     "edits": {"type": ["object", "null"],
                               "description": "{\"<processor id>\": {\"<param>\": value}} applied before approval"}}),
    ToolSpec("plan_list", ("proposal_list",), "List saved proposals (planner and agent, any status), newest "
             "first, as reviewable steps.", summary=_sum_proposals,
             schema={"stage": {"enum": ["master", "mix", "clean", "cleanup", None]},
                     "status": {"enum": ["pending", "applied", "rejected", None]}}),
    ToolSpec("plan_get", ("proposal_get",), "Show one saved proposal: reviewable steps and the full proposal."),
    ToolSpec("plan_reject", ("plan_reject",), "Reject a proposal with a reason (journaled) and get hints for "
             "requesting an alternative."),
    ToolSpec("plan_run", ("planner_run",), "Run the planner loop for the master stage (measure, preview, "
             "evaluate, iterate up to max_iter); saves the proposal and applies it only with apply=true.",
             long=True, summary=_sum_plan_run),
    ToolSpec("gate_check", ("gate_check",), "Translation gate OF-5 on a variant's master: pass / fail / "
             "incomplete with per-check reasons (incomplete is never a pass).", summary=_sum_gate),
    # history
    ToolSpec("history_list", ("history",), "List journal entries (detail='full' adds the patches).",
             schema={"limit": {"description": "most recent N entries"}}, summary=_keep),
    ToolSpec("history_undo", ("undo",), "Undo the last operation (journaled).", summary=_keep),
    ToolSpec("history_checkout", ("checkout",), "Restore the project to a journal sequence number.",
             summary=_keep),
    # views shared with the GUI (SPEC 10.1: no face has a feature the others lack)
    ToolSpec("variant_list", ("variant_list",), "List variants (objective x media profile) with objective blend, "
             "outputs and render state.", summary=_keep),
    ToolSpec("analysis_get", ("analysis_view",), "Analysis view of the cached measurements: loudness over time, "
             "LTAS, band correlation, stem placement, diagnostics, before/after metrics.", long=True,
             summary=_sum_analysis_view),
    ToolSpec("audio_get", ("audio_set",), "Listening set of a variant: before / after / delta files "
             "(project-relative) and the level-match gain (louder side lowered).", long=True),
    ToolSpec("verify_get", ("verification_get",), "The last verification of a variant without re-running it."),
    # knowledge
    ToolSpec("knowledge_lookup", ("knowledge_lookup",), "Look up knowledge data: decision rules R-01..R-33, "
             "perceptual vocabulary terms and bands, genre priors, thresholds. Free-text match on ids, labels "
             "and notes.",
             schema={"query": {"description": "free text, all words must match (e.g. 'muddy', 'limiter')"},
                     "id": {"description": "exact entry id, e.g. R-14 or komori (returns its data)"},
                     "kind": {"description": "rule, term, band, genre, section, table, ..."},
                     "source": {"description": "knowledge file name without .json, e.g. rules"}},
             summary=_keep),
    # remix operations (SPEC 9.3); times in samples at the project rate or seconds as "1.5s"
    ToolSpec("stems_list", ("stems_list", "stem_list"), "List stem tracks (role, lead, level, pan, routing, "
             "clips), unused assets and R-22 notes.", summary=_sum_stems),
    ToolSpec("stems_add", ("stems_add", "stem_add"), "Import an audio file as a new stem track (import checks, "
             "tempo / key consistency report; no time-stretch or pitch-shift, D-048).", mutates=True,
             schema={"source": {"description": "audio file, relative to the workspace"},
                     "role": {"description": "role (default: estimated from the file name)"},
                     "mode": {"enum": ["copy", "link"]}}),
    ToolSpec("stems_replace", ("stems_replace", "stem_replace"), "Point a track's clips at another audio file "
             "(source, imported) or an existing asset (asset); the chain is kept unless keep_chain=false.",
             mutates=True,
             schema={"source": {"description": "audio file to import, relative to the workspace"},
                     "asset": {"description": "existing asset id (instead of source)"},
                     "mode": {"enum": ["copy", "link"]}}),
    ToolSpec("stems_edit", ("stems_edit", "stem_edit"), "One remix edit selected by op: split (clip, at), mute "
             "(track, start, end), move (clip, timeline_start), role (track, role, is_lead), range_replace (track, "
             "start, end, asset, source_start), remove (track). Times in samples or seconds ('1.5s'). Journaled; "
             "undo with history_undo.", mutates=True,
             schema={"op": {"enum": ["split", "mute", "move", "role", "range_replace", "remove"]},
                     "start": {"description": "range start (samples or '1.5s')"},
                     "end": {"description": "range end, exclusive (samples or '1.5s')"},
                     "at": {"description": "split position on the timeline (samples or '1.5s')"},
                     "timeline_start": {"description": "new clip position (samples or '1.5s')"}}),
    ToolSpec("stems_remove", ("stems_remove", "stem_remove"), "Remove a track (its assets stay, flagged unused).",
             mutates=True),
    ToolSpec("stems_export", ("stems_export", "stem_export"), "Write one WAV per stem track (processed as it "
             "sits in the mix, or the raw clip layout) plus manifest.json under out_dir (project-relative).",
             long=True, mutates=True, kinds={"out_dir": "plain"},
             schema={"out_dir": {"description": "project-relative folder (default renders/stems)"},
                     "subtype": {"enum": ["FLOAT", "PCM_24", "PCM_16"]}}),
    ToolSpec("separate_run", ("separate_run", "separate"), "Separate a project asset (default: the full mix) "
             "into stems with a registered model. mode 'preview' = loudest excerpt, assets only; 'full' = whole "
             "file plus tracks restricted to balance operations (R-22). Never downloads weights.",
             long=True, kinds={"source": "plain"}, summary=_sum_separate,
             schema={"model": {"description": "model id (default: the registry default for the mode)"},
                     "source": {"description": "asset id to separate (default: the full mix)"},
                     "mode": {"enum": ["preview", "full"]}, "device": {"enum": ["auto", "cpu", "cuda"]},
                     "excerpt_s": {"description": "preview excerpt length in seconds (default 30)"}}),
    ToolSpec("separate_list", ("separation_list",), "List the project's separation records (model, sha256, "
             "license, attribution, stems)."),
    ToolSpec("model_list", ("model_list",), "List models (official catalogue and BYOW) with license, status and "
             "local state.", summary=_sum_models),
    ToolSpec("model_get", ("model_show", "model_get"), "Show one model: license evidence, attribution, pinned "
             "files and whether they are present."),
    ToolSpec("model_pull", ("model_pull",), "Download a catalogue model from its pinned official source and "
             "verify the sha256 (verified entries only unless allow_candidate).", long=True, mutates=True),
    ToolSpec("model_register", ("model_register",), "Register your own weights (BYOW): the file is hashed in "
             "place, never copied; the declared license is the user's responsibility.", mutates=True,
             schema={"path": {"description": "weights file, relative to the workspace"},
                     "license_weights": {"description": "license of the weights ('unknown' if not known)"}}),
    ToolSpec("model_verify", ("model_verify",), "Re-hash a model's local weight files against the pinned sha256."),
    ToolSpec("model_remove", ("model_remove",), "Delete downloaded weights (official) or forget a BYOW "
             "registration (the file itself is kept).", mutates=True),
    # cleanup and mix stages (SPEC 6.4, 6.5); plan_propose / plan_apply with a stage do the same
    ToolSpec("clean_plan", ("clean_plan",), "Propose the cleanup stage: diagnose each stem (or the 2-mix on the "
             "full-mix route) and plan the steps; assets where nothing is detected are listed as skipped. "
             "apply=true also applies it.", long=True, mutates=True, summary=_sum_plan,
             schema={"targets": {"description": "asset ids, track ids or 'fullmix' (default: every stem)"},
                     "overrides": {"description": "step overrides, e.g. {\"spectral_reduction\": \"light\"}, for "
                                                  "every target or keyed by asset / track id"}}),
    ToolSpec("clean_apply", ("clean_apply",), "Approve and apply a cleanup proposal (by proposal_id): cleaned "
             "audio, delta, records and noise baselines.", long=True, summary=_sum_clean_apply,
             rename={"proposal_or_id": "proposal"},
             schema={"proposal": {"description": "proposal_id from clean_plan (or the proposal object)"}}),
    ToolSpec("clean_delta", ("clean_delta",), "Write the removed component of an applied cleanup (input minus "
             "output) for listening; returns its project-relative path.", long=True,
             schema={"asset_id": {"description": "asset id, track id or 'fullmix'"}}),
    ToolSpec("mix_plan", ("mix_plan",), "Propose the mix stage in the fixed order (static balance, arrangement "
             "suggestions, subtractive EQ, dynamics, additive EQ, space, mix bus), measured after every step on "
             "level-matched previews. variant= plans a variant's mix (its track overrides). apply=true also "
             "applies it.", long=True, mutates=True, summary=_sum_plan,
             schema={"objective": {"description": "objective for this plan (spec object or 'vocal_forward:0.7'); "
                                                  "default: the project's"},
                     "excerpt": {"description": "evaluate on representative excerpts (false: full length)"}}),
    ToolSpec("mix_apply", ("mix_apply",), "Approve and apply a mix proposal (by proposal_id); optional edits "
             "change processor parameters first.", summary=_sum_mix_apply,
             rename={"proposal_or_id": "proposal"},
             schema={"proposal": {"description": "proposal_id from mix_plan (or the proposal object)"},
                     "edits": {"type": ["object", "null"],
                               "description": "{\"<processor id>\": {\"<param>\": value}} applied before approval"}}),
    ToolSpec("master_plan", ("master_plan",), "Propose a mastering plan."),
    ToolSpec("master_apply", ("master_apply",), "Apply a mastering plan."),
    ToolSpec("render_preview", ("render_preview", "render"), "Render a preview (sections or full length).",
             long=True),
    ToolSpec("render_spectrogram", ("render_spectrogram",), "Render a spectrogram image."),
    ToolSpec("export_run", ("export_run", "export"), "Render the final export for each output.", long=True),
    ToolSpec("verify_run", ("verify_run", "verify"), "Run verification of the rendered outputs."),
    ToolSpec("report_get", ("report_get", "report"), "Get the Mix Report."),
    ToolSpec("pipeline_run", ("run_pipeline", "run"), "One-shot pipeline with the planner only: import as-is, "
             "analyze, clean, mix (stems) or full-mix route (2-mix), master per variant, render, verify, Mix Report; "
             "deliverables (masters, manifests, reports, run_summary.json) to out. Returns per-stage status and "
             "gates; exit_code 1 when a gate or verification failed.",
             long=True, mutates=True, kinds={"project": "path"}, derive_ws=_derive_run_project, summary=_sum_run,
             schema={"sources": {"description": "stem folder, files or a single 2-mix, relative to the workspace"},
                     "objective": {"description": "'comfort', 'bass_heavy:0.7' or 'comfort:0.6+bass_heavy:0.4'"},
                     "profile": {"description": "media profile id, or a list (every profile gets every delivery)"},
                     "delivery": {"description": "delivery format id or a list (default: the profile's)"},
                     "variants": {"description": "[{objective, profile, delivery}] instead of objective / profile "
                                                 "/ delivery"},
                     "out": {"description": "folder for the deliverables, relative to the workspace"},
                     "project": {"description": "project folder (default: '<name>.mmx' next to out)"}}),
]


# ---------------------------------------------------------------------------
# binding: API signature -> JSON Schema + argument conversion
# ---------------------------------------------------------------------------

_JSON_TYPES = {"str": "string", "Path": "string", "PathLike": "string", "int": "integer", "float": "number",
               "bool": "boolean", "dict": "object", "list": "array", "tuple": "array", "None": "null"}


def _schema_from_annotation(ann: Any) -> dict:
    text = ann if isinstance(ann, str) else getattr(ann, "__name__", "") if ann is not inspect.Parameter.empty else ""
    text = str(text or "").replace("typing.", "").replace("Optional[", "").strip()
    if not text or text == "Any":
        return {}
    lit = re.fullmatch(r"Literal\[(.*)\](?:\s*\|\s*None)?", text)
    if lit:
        try:
            values = ast.literal_eval(f"[{lit.group(1)}]")
        except (ValueError, SyntaxError):
            return {}
        return {"enum": values + ([None] if text.rstrip().endswith("None") else [])}
    types: list[str] = []
    item: dict | None = None
    for part in re.split(r"\s*\|\s*", text):
        base = part.split("[", 1)[0].split(".")[-1].strip()
        t = _JSON_TYPES.get(base)
        if t is None:
            return {}
        if t == "array" and "[" in part:
            inner = part[part.index("[") + 1: part.rindex("]")]
            item = _schema_from_annotation(inner)
        if t not in types:
            types.append(t)
    out: dict = {"type": types[0] if len(types) == 1 else types}
    if item:
        out["items"] = item
    return out


def _jsonable_default(v: Any) -> bool:
    try:
        json.dumps(v)
        return True
    except (TypeError, ValueError):
        return False


@dataclass
class Param:
    api: str            # API parameter name
    arg: str | None     # tool argument name (None: injected)
    kind: str           # project | path | paths | actor | detail | json_text | path_or_json | plain
    required: bool
    default: Any = inspect.Parameter.empty


def _kind(name: str, spec: ToolSpec) -> str:
    if name in spec.kinds:
        return spec.kinds[name]
    if name in _PROJECT_PARAMS:
        return "project"
    if name == "actor":
        return "actor"
    if name == "detail":
        return "detail"
    if name in _PATHS_PARAMS:
        return "paths"
    if name in _PATH_PARAMS or name.endswith(_PATH_SUFFIXES):
        return "path"
    return "plain"


@dataclass
class Tool:
    spec: ToolSpec
    fn: Callable[..., dict]
    params: list[Param]
    input_schema: dict
    mutates: bool
    source: str           # "api.<name>" or "stand-in"

    @property
    def name(self) -> str:
        return self.spec.name

    def describe(self) -> dict:
        desc = self.spec.description
        if self.spec.long:
            desc += " Long-running: pass async=true to get a job_id, then poll job_status / job_result."
        return {"name": self.name, "description": desc, "inputSchema": self.input_schema,
                "annotations": {"readOnlyHint": not self.mutates, "destructiveHint": False,
                                "openWorldHint": False}}

    def bind(self, args: dict, ws: Workspace, detail: str) -> tuple[dict, str | None]:
        """Tool arguments -> API keyword arguments; also returns the project key."""
        kw: dict[str, Any] = {}
        key: str | None = None
        for p in self.params:
            if p.kind == "actor":
                kw[p.api] = ACTOR
                continue
            if p.kind == "detail":
                kw[p.api] = detail == "full"
                continue
            if p.arg not in args:
                if p.kind == "project":
                    kw[p.api] = str(ws.resolve(".", what=p.arg))
                    key = "."
                continue
            v = args[p.arg]
            if v is None and not p.required:
                kw[p.api] = None
            elif p.kind == "project":
                rp = ws.resolve(v, what=p.arg)
                kw[p.api] = str(rp)
                key = ws.rel(rp)
            elif p.kind == "path":
                kw[p.api] = str(ws.resolve(v, what=p.arg))
            elif p.kind == "paths":
                if isinstance(v, str):
                    v = [v]
                kw[p.api] = [str(ws.resolve(x, what=p.arg)) for x in v]
            elif p.kind == "json_text":
                kw[p.api] = json.dumps(v, ensure_ascii=False)
            elif p.kind == "path_or_json":
                # a .json file name is a workspace path; objects, JSON text and specs pass through
                if isinstance(v, str) and v.strip().lower().endswith(".json") and v.strip()[:1] not in "{[":
                    kw[p.api] = str(ws.resolve(v.strip(), what=p.arg))
                else:
                    kw[p.api] = v
            else:
                kw[p.api] = v
        if self.spec.derive is not None:
            self.spec.derive(kw)
        if self.spec.derive_ws is not None:
            self.spec.derive_ws(kw, ws)
        return kw, key


def _resolve_fn(spec: ToolSpec) -> tuple[Callable[..., dict] | None, str]:
    for name in spec.api:
        fn = getattr(api, name, None)
        if callable(fn) and not inspect.ismodule(fn) and not inspect.isclass(fn) and not name.startswith("_"):
            return fn, f"api.{name}"
    if spec.fallback is not None:
        return spec.fallback, "stand-in"
    return None, ""


def bind_spec(spec: ToolSpec) -> Tool | None:
    fn, source = _resolve_fn(spec)
    if fn is None:
        return None
    sig = inspect.signature(inspect.unwrap(fn))
    params: list[Param] = []
    props: dict[str, dict] = {}
    required: list[str] = []
    for name, prm in sig.parameters.items():
        if prm.kind in (prm.VAR_POSITIONAL, prm.VAR_KEYWORD) or name in spec.hide:
            continue
        kind = _kind(name, spec)
        has_default = prm.default is not inspect.Parameter.empty
        if kind in ("actor", "detail"):
            params.append(Param(name, None, kind, False, prm.default))
            continue
        arg = spec.rename.get(name, "project" if kind == "project" else name)
        if kind == "project":
            schema = dict(_P["project"])
            req = False                    # defaults to the workspace root
        elif kind == "paths":
            schema = {"type": "array", "items": {"type": "string"}, "minItems": 1}
            req = not has_default
        elif kind == "path":
            schema = {"type": "string", "description": "path relative to the workspace"}
            req = not has_default
        elif kind in ("json_text", "path_or_json"):
            schema = {}
            req = not has_default
        else:
            schema = _schema_from_annotation(prm.annotation)
            req = not has_default
        if has_default and kind != "project" and prm.default is not None and _jsonable_default(prm.default):
            schema["default"] = prm.default
        if name == "title" and spec.derive is _derive_title:
            req = False
        schema.update(spec.schema.get(arg, {}))
        props[arg] = schema
        if req:
            required.append(arg)
        params.append(Param(name, arg, kind, req, prm.default))
    props["detail"] = {"type": "string", "enum": list(DETAILS), "default": "summary",
                       "description": "'full' returns the complete result"}
    if spec.long:
        props["async"] = {"type": "boolean", "default": False,
                          "description": "run as a background job and return a job_id"}
    schema = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    mutates = spec.mutates if spec.mutates is not None else any(p.kind == "actor" for p in params)
    return Tool(spec, fn, params, schema, mutates, source)


# ---------------------------------------------------------------------------
# job tools (server level, not API wrappers)
# ---------------------------------------------------------------------------

_JOB_SCHEMA = {"type": "object", "properties": {
    "job_id": {"type": "string"},
    "detail": {"type": "string", "enum": list(DETAILS), "default": "summary"}},
    "required": ["job_id"], "additionalProperties": False}

JOB_TOOLS = {
    "job_status": {"name": "job_status", "description": "State of a background job (queued, running, "
                   "succeeded, failed).", "inputSchema": _JOB_SCHEMA,
                   "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    "job_result": {"name": "job_result", "description": "Result of a finished background job (summary "
                   "by default; detail='full' for everything). While running it returns the state.",
                   "inputSchema": _JOB_SCHEMA, "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    "job_list": {"name": "job_list", "description": "List background jobs of this server session.",
                 "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                 "annotations": {"readOnlyHint": True, "openWorldHint": False}},
}


# ---------------------------------------------------------------------------
# toolbox: what the server calls
# ---------------------------------------------------------------------------

class ToolError(Exception):
    """A tool-level failure, reported as a result with isError=true."""

    def __init__(self, payload: dict):
        super().__init__(payload.get("message"))
        self.payload = payload


class Toolbox:
    def __init__(self, workspace: Workspace, specs: list[ToolSpec] | None = None):
        self.ws = workspace
        self.tools: dict[str, Tool] = {}
        for spec in specs if specs is not None else SPECS:
            tool = bind_spec(spec)
            if tool is not None:
                self.tools[tool.name] = tool
        self.jobs = JobManager(error_mapper=self._error_payload)
        self._validators: dict[str, Any] = {}

    # -- listing -------------------------------------------------------------

    def list(self) -> list[dict]:
        return [t.describe() for t in self.tools.values()] + list(JOB_TOOLS.values())

    def names(self) -> list[str]:
        return list(self.tools) + list(JOB_TOOLS)

    # -- calling -------------------------------------------------------------

    def call(self, name: str, args: dict | None) -> tuple[dict, bool]:
        """Run a tool; returns (payload, is_error). Never raises for tool-level failures."""
        args = dict(args or {})
        detail = args.get("detail") if args.get("detail") in DETAILS else "summary"
        try:
            if name in JOB_TOOLS:
                self._validate(name, JOB_TOOLS[name]["inputSchema"], args)
                return self._job_tool(name, args), False
            tool = self.tools.get(name)
            if tool is None:
                raise ToolError({"error": "unknown_tool", "message": f"unknown tool: {name}",
                                 "details": {"hint": "call tools/list for the available tools"}})
            self._validate(name, tool.input_schema, args)
            args.pop("detail", None)
            run_async = bool(args.pop("async", False))
            kw, key = tool.bind(args, self.ws, detail)
            if run_async:
                job = self.jobs.submit(name, key if key is not None else "-", args, lambda: tool.fn(**kw))
                return {"job_id": job.id, "state": job.state, "tool": name,
                        "hint": "poll job_status, then job_result"}, False
            if key is not None and (tool.mutates or tool.spec.long):
                self.jobs.check_free(key)
            return self._render(tool, tool.fn(**kw), detail), False
        except ToolError as e:
            return e.payload, True
        except BaseException as e:  # noqa: BLE001 - map everything to an isError result
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            return self._error_payload(e, detail=detail), True

    def _render(self, tool: Tool, result: Any, detail: str) -> dict:
        if not isinstance(result, dict):
            result = {"result": result}
        result = self.ws.scrub(result)
        if detail == "full":
            return result
        summarize = tool.spec.summary or default_summary
        try:
            return summarize(result)
        except Exception:  # a summary must never hide a successful result
            log.warning("summary for %s failed:\n%s", tool.name, traceback.format_exc())
            return default_summary(result)

    def _error_payload(self, e: BaseException, detail: str = "summary") -> dict:
        if isinstance(e, MankoError):
            payload = e.to_dict()
        else:
            log.error("internal error:\n%s", traceback.format_exc())
            payload = {"error": "internal_error", "message": f"{type(e).__name__}: {e}", "details": {}}
        payload = self.ws.scrub(payload)
        if detail != "full" and payload.get("details"):
            payload["details"] = compact(payload["details"], depth=4, max_items=10)
        return payload

    def _validate(self, name: str, schema: dict, args: dict) -> None:
        from jsonschema import Draft202012Validator
        v = self._validators.get(name)
        if v is None:
            v = self._validators[name] = Draft202012Validator(schema)
        errors = sorted(v.iter_errors(args), key=lambda e: list(e.absolute_path))
        if errors:
            msgs = [f"{'/'.join(str(p) for p in e.absolute_path) or '(arguments)'}: {e.message}" for e in errors[:5]]
            raise InputError(f"invalid arguments for {name}: {msgs[0]}", details={"errors": msgs})

    def _job_tool(self, name: str, args: dict) -> dict:
        if name == "job_list":
            return {"jobs": [j.status() for j in self.jobs.list()]}
        job = self.jobs.get(args["job_id"])
        if name == "job_status" or job.state not in FINISHED:
            return job.status()
        if job.state == FAILED:
            raise ToolError({**(job.error or {}), "job_id": job.id})
        tool = self.tools.get(job.tool)
        out = job.status()
        out["result"] = self._render(tool, job.result, args.get("detail", "summary")) if tool else job.result
        return out
