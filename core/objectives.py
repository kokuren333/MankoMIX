"""Objective functions: resolution, measurement mapping and evaluation (SPEC 4).

Public API (wrapped 1:1 by core/api.py, the CLI and MCP):

    parse_objective_arg(text) -> spec
    validate_objective_definition(obj) -> issues
    validate_objective_spec(spec) -> issues
    set_objective(project, spec, *, variant_id=None, actor="human") -> resolved summary
    resolve_objective(project_or_spec, *, variant=None, ...) -> resolved
    measure_for_objective(x, sr, resolved, ...) -> measurements
    evaluate(measurements, resolved) -> evaluation
    evaluate_constraints(measurements) -> {S-nn: status}, details

General form (4.1):
    1. any safety invariant S-nn failing -> the candidate is rejected (no score)
    2. score = sum(w_i * penalty_i)  (0 is ideal; penalties are in [0, 1])
    3. the translation gate (OF-5) is reported separately (core/gate.py)

Rules applied here:
- R-01: every spectral penalty is computed on level-matched signals (the
  measurement modules normalise to a common integrated loudness).
- R-17: targets come from the reference distribution when references exist;
  otherwise from broad generic priors, and the evaluation says so.
- R-33 / 4.10: a genre prior only changes INITIAL term weights and target
  ranges, with provenance recorded; references and explicit user settings win.
- 4.3: constraints are evaluated from knowledge/thresholds.json and the media
  profile only. Nothing in the objective (blend, intensity, overrides, genre)
  reaches them, so they can never be relaxed.
- Metrics that cannot be measured yet (no stems, no cleanup stage, no limiter
  statistics, no "before" signal) are marked "not_measured" and their weight
  is redistributed proportionally inside the same objective; the
  redistribution is recorded, never silent.

Data: objectives/catalog.json (terms, weights, declared params),
knowledge/objective_metrics.json (targets, scales, intensity limits),
knowledge/masking_model.json, knowledge/thresholds_m3.json,
knowledge/thresholds.json, knowledge/genre_priors.json.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any

import numpy as np

from . import config
from .errors import InputError, ValidationError
from .hashing import canonical_hash
from .schema import check_objectives, issue

CONSTRAINT_IDS = tuple(f"S-{i:02d}" for i in range(1, 12))
METRIC_IDS = tuple(f"P-{i:02d}" for i in range(1, 23))

# Variants each metric understands (None = the metric's default form).
KNOWN_VARIANTS: dict[str, set] = {
    "P-01": {None},
    "P-02": {None, "overall", "vs_lead", "low_to_mid", "time_axis", "temporal"},
    "P-03": {None, "plr", "psr", "lra", "lra_density"},
    "P-04": {None, "kick_band"},
    "P-05": {None, "width_restraint"},
    "P-06": {None},
    "P-07": {None, "sub+bass", "sub", "bass", "playable_band"},
    "P-08": {None},
    "P-09": {None},
    "P-10": {None},
    "P-11": {None, "two_sided"},
    "P-12": {None},
    "P-13": {None},
    "P-14": {None},
    "P-15": {None, "lead"},
    "P-16": {None},
    "P-17": {None},
    "P-18": {None},
    "P-19": {None},
    "P-20": {None},
    "P-21": {None},
    "P-22": {None},
}

# Metrics that need stems (stem context) to be measured exactly.
STEM_METRICS = {"P-02", "P-09", "P-10", "P-13", "P-22"}

_RELAX_RE = re.compile(r"relax|waive|suspend|disable|bypass|ignore_constraint|constraints?_override", re.I)
_CONSTRAINT_KEY_RE = re.compile(r"^S-\d\d$")

ELEMENTS = ("balance", "panning", "frequency", "depth", "dynamics", "interest")


# --------------------------------------------------------------------------
# data


def metric_table() -> dict:
    """knowledge/objective_metrics.json (initial, calibratable values)."""
    return config.load_knowledge("objective_metrics")


def _masking() -> dict:
    return config.load_knowledge("masking_model")


def _m3() -> dict:
    return config.load_knowledge("thresholds_m3")


def _th() -> dict:
    return config.load_knowledge("thresholds")


def _tv(th: dict, *path, default=None):
    cur = th
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    if isinstance(cur, dict) and "value" in cur:
        return cur["value"]
    return cur


def canonical_variant(metric: str, variant: str | None) -> str | None:
    aliases = (metric_table().get("variant_aliases") or {}).get(metric) or {}
    if variant is None:
        return aliases.get("default")
    return aliases.get(variant, variant)


def term_key(metric: str, variant: str | None) -> str:
    return metric if not variant else f"{metric}:{variant}"


def _json_safe(obj):
    from .measure.vector import json_safe
    return json_safe(obj)


def _rp(value, lo, hi, scale) -> float | None:
    from .analysis.perceptual import range_penalty
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return float(range_penalty(v, lo, hi, float(scale)))


# --------------------------------------------------------------------------
# spec parsing and validation


def parse_objective_arg(text: str) -> dict:
    """CLI form -> objective spec.

    "comfort"                      -> blend [comfort 1.0], intensity 0.5
    "bass_heavy:0.7"               -> blend [bass_heavy 1.0], intensity 0.7 (SPEC 10.2)
    "comfort:0.6+bass_heavy:0.4"   -> blend weights 0.6 / 0.4, intensity 0.5
    """
    if not isinstance(text, str) or not text.strip():
        raise InputError("objective must be a non-empty string")
    parts = [p.strip() for p in text.split("+") if p.strip()]
    spec: dict = {"blend": [], "intensity": 0.5, "overrides": {}, "lead_stem": None}
    for part in parts:
        name, _, w = part.partition(":")
        try:
            weight = float(w) if w else 1.0
        except ValueError:
            raise InputError(f"bad weight in objective '{part}'") from None
        spec["blend"].append({"id": name.strip(), "weight": weight})
    if len(parts) == 1 and ":" in parts[0]:
        spec["intensity"] = spec["blend"][0]["weight"]
        spec["blend"][0]["weight"] = 1.0
    return spec


def _catalog() -> dict[str, dict]:
    return {o["id"]: o for o in config.load_objectives()["objectives"]}


def _scan_relaxation(node: Any, path: list, out: list[dict]) -> None:
    """Any key that names a constraint or a relaxation is an attempt to relax S-nn (4.3)."""
    if isinstance(node, dict):
        for k, v in node.items():
            ks = str(k)
            if _CONSTRAINT_KEY_RE.match(ks) or _RELAX_RE.search(ks):
                out.append(issue("error", path + [ks],
                                 f"'{ks}': safety invariants (S-nn) cannot be relaxed, overridden or "
                                 "weighted by an objective (SPEC 4.3)"))
            _scan_relaxation(v, path + [ks], out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _scan_relaxation(v, path + [i], out)


def validate_objective_definition(obj: Any) -> list[dict]:
    """Checks for `mankomix objective validate` (SPEC 4.8).

    Accepts a single objective definition or a catalog ({"objectives": [...]}).
    Reports: schema errors, unknown metric ids (e.g. P-99), unknown variants,
    term weights not summing to 1, duplicate terms, and any attempt to relax a
    safety invariant (fields named after S-nn or relax/waive/disable/...).
    Returns issues [{level, path, message}].
    """
    out = list(check_objectives(obj))
    if not isinstance(obj, dict):
        return out
    items = [(["objectives", i], o) for i, o in enumerate(obj.get("objectives") or [])] \
        if isinstance(obj.get("objectives"), list) else [([], obj)]
    seen_msgs = {(i["path"], i["message"]) for i in out}
    extra: list[dict] = []
    for base, o in items:
        if not isinstance(o, dict):
            continue
        _scan_relaxation({k: v for k, v in o.items() if k != "constraints_emphasis"}, base, extra)
        for j, t in enumerate(o.get("terms") or []):
            if not isinstance(t, dict):
                continue
            m, v = t.get("metric"), t.get("variant")
            if m not in METRIC_IDS:
                extra.append(issue("error", base + ["terms", j, "metric"],
                                   f"unknown metric id '{m}' (valid: P-01..P-22, SPEC 4.2)"))
            elif v not in KNOWN_VARIANTS[m]:
                valid = sorted(x for x in KNOWN_VARIANTS[m] if x)
                extra.append(issue("error", base + ["terms", j, "variant"],
                                   f"unknown variant '{v}' for {m}; valid: {', '.join(valid) or '(none)'}"))
        for k in o.get("constraints_emphasis") or []:
            if not (isinstance(k, str) and k in CONSTRAINT_IDS):
                extra.append(issue("error", base + ["constraints_emphasis"], f"unknown constraint '{k}'"))
    for e in extra:
        if (e["path"], e["message"]) not in seen_msgs:
            out.append(e)
            seen_msgs.add((e["path"], e["message"]))
    return out


def _param_ok(value, decl: dict) -> str | None:
    rng = decl.get("range")
    default = decl.get("default")
    if isinstance(default, list) or (default is None and isinstance(value, list)):
        if not (isinstance(value, list) and len(value) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
            return "expected a [lo, hi] pair of numbers"
        if value[0] > value[1]:
            return "lo must not exceed hi"
        vals = value
    elif isinstance(default, (int, float)) and not isinstance(default, bool):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "expected a number"
        vals = [value]
    else:
        vals = [value] if isinstance(value, (int, float)) else []
    if isinstance(rng, list) and len(rng) == 2:
        for v in vals:
            if not (rng[0] <= v <= rng[1]):
                return f"value {v} outside the declared range {rng}"
    return None


def validate_objective_spec(spec: Any) -> list[dict]:
    """Checks a project/variant objective spec: blend ids, weights, intensity, declared overrides."""
    out: list[dict] = []
    if not isinstance(spec, dict):
        return [issue("error", [], "objective spec must be an object")]
    cat = _catalog()
    blend = spec.get("blend")
    if not isinstance(blend, list) or not blend:
        out.append(issue("error", ["blend"], "blend must be a non-empty list"))
        blend = []
    seen = set()
    for j, b in enumerate(blend):
        if not isinstance(b, dict):
            out.append(issue("error", ["blend", j], "blend entry must be an object"))
            continue
        oid = b.get("id")
        if oid not in cat:
            out.append(issue("error", ["blend", j, "id"], f"unknown objective '{oid}'; valid: {', '.join(cat)}"))
        elif cat[oid].get("kind") == "gate":
            out.append(issue("error", ["blend", j, "id"],
                             f"'{oid}' is a gate (pass/fail, always applied) and cannot be blended"))
        if oid in seen:
            out.append(issue("error", ["blend", j, "id"], f"objective '{oid}' appears twice in blend"))
        seen.add(oid)
        w = b.get("weight")
        if not isinstance(w, (int, float)) or isinstance(w, bool) or not math.isfinite(w) or w <= 0:
            out.append(issue("error", ["blend", j, "weight"], "blend weight must be a number > 0"))
    inten = spec.get("intensity", 0.5)
    if not isinstance(inten, (int, float)) or isinstance(inten, bool) or not (0.0 <= inten <= 1.0):
        out.append(issue("error", ["intensity"], "intensity must be a number within [0, 1]"))
    overrides = spec.get("overrides") or {}
    if not isinstance(overrides, dict):
        out.append(issue("error", ["overrides"], "overrides must be an object"))
        overrides = {}
    _scan_relaxation(overrides, ["overrides"], out)
    for oid, params in overrides.items():
        if oid not in cat:
            out.append(issue("error", ["overrides", oid], f"overrides for unknown objective '{oid}'"))
            continue
        if not isinstance(params, dict):
            out.append(issue("error", ["overrides", oid], "overrides must be an object of parameters"))
            continue
        declared = cat[oid].get("params") or {}
        for pname, value in params.items():
            if _CONSTRAINT_KEY_RE.match(str(pname)) or _RELAX_RE.search(str(pname)):
                continue  # already reported by the relaxation scan
            if pname not in declared:
                out.append(issue("error", ["overrides", oid, pname],
                                 f"'{pname}' is not a parameter declared by objective '{oid}' "
                                 f"(declared: {', '.join(declared) or 'none'})"))
                continue
            prob = _param_ok(value, declared[pname])
            if prob:
                out.append(issue("error", ["overrides", oid, pname], prob))
        if oid not in seen:
            out.append(issue("warning", ["overrides", oid], f"objective '{oid}' is not in the blend; override unused"))
    lead = spec.get("lead_stem")
    if lead is not None and not isinstance(lead, str):
        out.append(issue("error", ["lead_stem"], "lead_stem must be a track id or null"))
    _scan_relaxation({k: v for k, v in spec.items() if k not in ("overrides",)}, [], out)
    return out


def normalize_spec(spec: dict | str | None) -> dict:
    if spec is None:
        spec = {"blend": [{"id": config.load_objectives().get("default", "comfort"), "weight": 1.0}]}
    if isinstance(spec, str):
        spec = parse_objective_arg(spec)
    out = copy.deepcopy(spec)
    out.setdefault("intensity", 0.5)
    out.setdefault("overrides", {})
    out.setdefault("lead_stem", None)
    return out


# --------------------------------------------------------------------------
# resolution


def _project_parts(project_or_spec, variant: str | None):
    """-> (spec, project_data or None, project or None, spec_source)."""
    proj = None
    data = None
    if hasattr(project_or_spec, "data") and hasattr(project_or_spec, "root"):
        proj = project_or_spec
        data = proj.data
    elif isinstance(project_or_spec, dict) and "blend" not in project_or_spec and "objective" in project_or_spec:
        data = project_or_spec
    if data is None:
        return normalize_spec(project_or_spec), None, None, "argument"
    spec, src = data.get("objective"), "project"
    if variant is not None:
        v = next((v for v in data.get("variants") or [] if v.get("id") == variant), None)
        if v is not None and v.get("objective") is not None:
            spec, src = v["objective"], f"variant:{variant}"
    return normalize_spec(spec), data, proj, src


def stems_meta(data: dict | None) -> dict:
    """{track_id: {role, is_lead, importance, name}} for the stem tracks of a project."""
    meta: dict = {}
    if not data:
        return meta
    fid = data.get("fullmix_asset")
    for t in data.get("tracks") or []:
        if not isinstance(t, dict) or t.get("role") == "fullmix":
            continue
        clips = t.get("clips") or []
        if clips and fid and all(c.get("asset") == fid for c in clips):
            continue
        meta[str(t["id"])] = {"role": t.get("role"), "is_lead": bool(t.get("is_lead")),
                              "importance": t.get("importance"), "name": t.get("name", "")}
    return meta


def resolve_lead(spec: dict, meta: dict) -> dict:
    """Lead declaration (4.7): declared lead_stem, else a vocals stem marked as estimated."""
    declared = spec.get("lead_stem")
    if declared:
        if meta and declared not in meta:
            raise InputError(f"lead_stem '{declared}' is not a stem track of the project",
                             details={"tracks": sorted(meta)})
        return {"stem": declared, "estimated": False, "source": "declared"}
    flagged = [t for t, m in meta.items() if m.get("is_lead")]
    if flagged:
        return {"stem": flagged[0], "estimated": False, "source": "track_is_lead"}
    voc = [t for t, m in meta.items() if m.get("role") == "vocals"]
    if voc:
        return {"stem": voc[0], "estimated": True, "source": "estimated_from_role",
                "note": "no lead declared: the first 'vocals' stem is assumed to be the lead (4.7)"}
    if meta:
        return {"stem": None, "estimated": True, "source": "none",
                "note": "no lead declared and no vocals stem: lead-dependent terms are not measured"}
    return {"stem": None, "estimated": True, "source": "no_stems",
            "note": "2mix only: the lead is not separable; lead-dependent terms are not measured"}


def _emph_matches(entry: str, metric: str, variant: str | None) -> bool:
    if not isinstance(entry, str) or not entry.startswith("P-"):
        return False
    m, _, v = entry.partition(":")
    if m != metric:
        return False
    if not v:
        return True
    cv = canonical_variant(metric, variant) if variant else None
    tokens = set(v.split("_")) | {v, canonical_variant(metric, v) or v}
    if cv is None:
        return False
    return cv in tokens or any(t and t in cv.split("_") for t in tokens)


def _lerp_bounds(base, limit, t: float, sense: str):
    out = []
    for b, l in zip(base, limit):
        if b is None or l is None:
            out.append(b)
            continue
        v = b + t * (l - b)
        if sense == "raise_to_target":
            v = max(b, v)
        elif sense in ("minimize", "minimize_excess"):
            v = min(b, v)
        out.append(v)
    return out


def _ref_scalar(refdist: dict | None, key: str) -> dict | None:
    if not refdist:
        return None
    s = (refdist.get("scalars") or {}).get(key)
    if not s or s.get("median") is None:
        return None
    return s


def _ref_range(refdist, key: str, fallback_scale: float):
    s = _ref_scalar(refdist, key)
    if s is None:
        return None
    mins = (metric_table().get("reference") or {}).get("scalar_min_half_width") or {}
    half = max(float(s.get("iqr") or 0.0) / 2.0, float(mins.get(key, 0.0)))
    return [s["median"] - half, s["median"] + half], f"references (n={refdist.get('n')})"


def _target_for(metric: str, variant: str | None, sense: str, oid: str, intensity: float,
                overrides: dict, genre_prior: dict | None, genre_id: str | None, refdist: dict | None) -> dict:
    """Target range for one term: base (reference / genre / generic), intensity move, overrides."""
    tbl = (metric_table().get("metrics") or {}).get(metric) or {}
    cv = canonical_variant(metric, variant)
    row = tbl.get(cv or "default") or tbl.get("default") or {}
    exempt = oid in ((metric_table().get("intensity") or {}).get("exempt_objectives") or ["comfort"])
    tgt: dict = {"source": "generic", "intensity_applied": False}
    params = (overrides or {}).get(oid) or {}

    if row.get("mode") in ("module", "external"):
        tgt.update({"mode": row["mode"], "source": "module" if row["mode"] == "module" else row.get("source")})
        if metric == "P-01":
            tgt["source"] = "references" if refdist and refdist.get("p01") else "generic_prior"
        return tgt

    base = None
    scale = row.get("scale")
    limit = row.get("limit")
    extra: dict = {}
    if metric == "P-02":
        pen = _masking()["penalties"][cv or "overall"]
        base, scale = [0.0, float(pen["ok_max_db"])], float(pen["scale_db"])
        tgt["source"] = "masking_model"
    elif metric == "P-03":
        if cv is None:
            plr = _ref_range(refdist, "P-03:plr", 3.0)
            lra = _ref_range(refdist, "P-03:lra", 3.0)
            extra = {"plr_db": plr[0] if plr else row["plr_db"], "lra_lu": lra[0] if lra else row["lra_lu"]}
            tgt["source"] = plr[1] if plr else "generic"
            base = None
        else:
            r = _ref_range(refdist, f"P-03:{'lra' if cv == 'lra_density' else cv}", row["scale"])
            base, tgt["source"] = (r[0], r[1]) if r else (list(row["base"]), "generic")
            if cv == "lra_density":
                extra["density_p95_p10_lu"] = row.get("density_p95_p10_lu")
    elif metric == "P-04":
        extra = {"bands": row["bands"], "loss_ok_db": row["loss_ok_db"]}
        base = [None, float(row["loss_ok_db"])]
    elif metric == "P-05":
        r = _ref_range(refdist, "P-05:width_restraint", row["scale"])
        base, tgt["source"] = (r[0], r[1]) if r else (list(row["base"]), "generic")
    elif metric == "P-06":
        base = list(row["base"])
    elif metric == "P-07":
        rng = list(row["range_hz"])
        if oid == "bass_heavy" and "sub_band_hz" in params and cv in ("sub+bass", None):
            rng = [float(params["sub_band_hz"][0]), rng[1]]
            tgt["param_source"] = "user_override"
        if oid == "club_impact" and "kick_band_hz" in params and cv == "playable_band":
            rng = [float(v) for v in params["kick_band_hz"]]
            tgt["param_source"] = "user_override"
        extra["range_hz"] = rng
        r = _ref_range(refdist, f"P-07:{cv}", row["scale"]) if rng == list(row["range_hz"]) else None
        base, tgt["source"] = (r[0], r[1]) if r else (list(row["base"]), "generic")
    elif metric == "P-08":
        p = _masking()["p08"]
        base, scale = [float(p["target_index_db_min"]), None], float(p["scale_db"])
        tgt["source"] = "masking_model"
    elif metric == "P-10":
        p = _masking()["p10"]
        scale = float(p["scale_db"])
        base, tgt["source"] = list(map(float, p["generic_target_db"])), "generic"
        if genre_prior:
            t = genre_prior.get("p10_target_db") or {}
            if isinstance(t.get("range"), list) and len(t["range"]) == 2:
                base, tgt["source"] = [float(v) for v in t["range"]], f"genre_prior:{genre_id}"
            elif t.get("relative") in p["relative_targets_db"]:
                base = [float(v) for v in p["relative_targets_db"][t["relative"]]]
                tgt["source"] = f"genre_prior:{genre_id}:relative_{t['relative']}"
            tgt["provisional"] = True
        shift = float(row.get("limit_shift_db", 0.0))
        limit = [base[0] + shift, base[1] + shift] if shift else None
        if params.get("p10_target_db") is not None:
            base = [float(v) for v in params["p10_target_db"]]
            tgt["source"] = "user_override"
            limit = None  # an explicit user target is not moved by intensity
    elif metric == "P-11":
        c = _m3()["p11_harshness"]
        if cv == "two_sided":
            base, scale = list(c["presence_range_db"]), float(c["presence_penalty_scale_db"])
        else:
            r = _ref_range(refdist, "P-11", c["ltas_penalty_scale_db"])
            if r:
                base, tgt["source"] = [None, r[0][1]], r[1]
            else:
                base = list(c["ltas_prominence_range_db"])
            scale = float(c["ltas_penalty_scale_db"])
            extra = {"peaky_frame_pct": list(c["peaky_frame_pct_range"]), "peaky_scale": c["peaky_frame_pct_scale"]}
        tgt["source"] = tgt["source"] if tgt["source"] != "generic" else "thresholds_m3"
    elif metric == "P-14":
        base, scale = [None, None], float(row.get("scale", 1.0))
        extra["ceiling_from"] = "profile"
    elif metric == "P-15":
        p = _masking()["p15"]
        base, scale = [float(p["dr_db_min"]), None], float(p["dr_scale_db"])
        tgt["source"] = "masking_model"
    elif metric == "P-17":
        c = _m3()["p17_sibilance"]
        base, scale = list(c["peak_prominence_range_db"]), float(c["peak_prominence_scale_db"])
        extra = {"event_pct": list(c["event_pct_range"]), "event_scale": c["event_pct_scale"]}
        tgt["source"] = "thresholds_m3"
    elif metric == "P-18":
        warn = float(_tv(_th(), "p18_limiter_dependency", "gr_p95_warn_db", default=4.0))
        base, scale = [None, warn], float(row.get("scale", 2.0))
        tgt["source"] = "thresholds"

    tgt["base"] = base
    if base is not None and limit is not None and not exempt and intensity > 0:
        tgt["range"] = _lerp_bounds(base, limit, float(intensity), sense)
        tgt["intensity_applied"] = True
        tgt["limit"] = limit
    else:
        tgt["range"] = base
        if limit is not None:
            tgt["limit"] = limit
        if exempt and limit is not None:
            tgt["intensity_note"] = f"'{oid}' is the comfort baseline: intensity does not move its targets"
    tgt["scale"] = scale
    tgt.update(extra)
    return tgt


def resolve_objective(project_or_spec, *, variant: str | None = None, genre: str | None = None,
                      references: dict | None = None, meta: dict | None = None, spec=None) -> dict:
    """Resolve an objective for evaluation.

    project_or_spec: a Project, a project data dict, an objective spec dict
    ({blend, intensity, overrides, lead_stem}) or a CLI string ("bass_heavy:0.7").
    variant: variant id whose objective override applies (project input only).
    genre / references / meta: explicit context when no project is given
    (references = output of core.reference.reference_distribution).
    spec: an objective spec (dict or CLI string) evaluated in the project's
    context (genre, references, stems) instead of the stored objective.

    Returns {spec, spec_source, blend, intensity, overrides, lead, genre, reference,
    terms[], constraints, gate, notes, provenance, definitions}.
    """
    spec_arg = spec
    spec, data, proj, spec_source = _project_parts(project_or_spec, variant)
    if spec_arg is not None:
        spec, spec_source = normalize_spec(spec_arg), "argument"
    issues = [i for i in validate_objective_spec(spec) if i["level"] == "error"]
    if issues:
        raise ValidationError("invalid objective", details={"issues": issues})
    cat = _catalog()
    notes: list[dict] = []
    provenance: list[dict] = []

    # blend normalised to sum 1
    total = float(sum(b["weight"] for b in spec["blend"]))
    blend = [{"id": b["id"], "weight": b["weight"] / total, "weight_input": b["weight"],
              "spec_id": cat[b["id"]].get("spec_id"), "label": cat[b["id"]].get("label"),
              "provisional": bool(cat[b["id"]].get("provisional"))} for b in spec["blend"]]
    intensity = float(spec.get("intensity", 0.5))
    for b in blend:
        if b["provisional"]:
            notes.append({"code": "provisional_objective", "objective": b["id"],
                          "text": f"'{b['id']}' is provisional: the evidence behind it is weak (SPEC 4.4)"})

    # genre (declared only, never inferred: D-053)
    gid = genre if genre is not None else (data.get("genre") if data else None)
    gp = None
    if gid:
        try:
            gp = config.get_genre_prior(gid)
        except InputError:
            notes.append({"code": "unknown_genre", "text": f"unknown genre '{gid}': generic initial values used"})
            gid = None
    genre_info: dict = {"id": gid, "applied": gp is not None}
    if gp is None:
        notes.append({"code": "genre_unset", "rule": "D-053",
                      "text": "genre not declared: generic initial values were used (genre is never inferred from audio)"})
    else:
        genre_info.update({"low_end_lead": gp.get("low_end_lead"), "emphasis": gp.get("emphasis", []),
                           "objective_tilt": gp.get("objective_tilt", {}),
                           "stem_importance_order": gp.get("stem_importance_order"),
                           "evidence": gp.get("evidence")})
        notes.append({"code": "genre_prior", "rule": "R-33",
                      "text": f"genre prior '{gid}' sets initial weights and target ranges only (practice level); "
                              "references and explicit user settings take precedence"})
        for oid, how in (gp.get("objective_tilt") or {}).items():
            in_blend = any(b["id"] == oid for b in blend)
            notes.append({"code": "genre_objective_tilt", "objective": oid,
                          "text": f"genre '{gid}' suggests to {how} '{oid}'"
                                  + (" (already in the blend; the blend weights are the user's setting and are not changed)"
                                     if in_blend else " (suggestion only; the blend is the user's setting)")})
        if any(isinstance(e, str) and e.startswith("S-") for e in gp.get("emphasis", [])):
            notes.append({"code": "genre_constraint_emphasis",
                          "text": "genre emphasises constraints " + ", ".join(e for e in gp["emphasis"] if e.startswith("S-"))
                                  + ": reported with priority; constraints are never relaxed nor tightened by a prior"})

    # references (R-17)
    refdist = references
    if refdist is None and proj is not None and proj.data.get("references"):
        from . import reference as _ref
        refdist = _ref.reference_distribution(proj)
    if refdist and refdist.get("n"):
        ref_info = {"source": "references", "n": refdist["n"], "ids": refdist.get("ids", [])}
    else:
        refdist = None
        ref_info = {"source": "generic_prior", "n": 0}
        notes.append({"code": "generic_prior", "rule": "R-17",
                      "text": "no references registered: targets are broad generic priors, not genre-specific (SPEC 4.6)"})

    # lead (4.7)
    meta = meta if meta is not None else stems_meta(data)
    lead = resolve_lead(spec, meta)
    if lead.get("estimated") and lead.get("stem"):
        notes.append({"code": "lead_estimated", "text": lead["note"]})

    # terms
    factor = float((metric_table().get("genre") or {}).get("emphasis_factor", 1.5))
    emphasis = list(gp.get("emphasis", [])) if gp else []
    terms: list[dict] = []
    for b in blend:
        od = cat[b["id"]]
        raw = []
        for t in od.get("terms") or []:
            w = float(t["weight"])
            hit = [e for e in emphasis if _emph_matches(e, t["metric"], t.get("variant"))]
            raw.append((t, w, w * factor if hit else w, hit))
        s = sum(r[2] for r in raw) or 1.0
        for t, w0, w1, hit in raw:
            wn = w1 / s
            src = f"genre_prior:{gid}:emphasis" if hit else "catalog"
            if hit:
                provenance.append({"objective": b["id"], "metric": t["metric"], "variant": t.get("variant"),
                                   "field": "weight", "from": round(w0, 6), "to": round(wn, 6),
                                   "source": f"genre_prior:{gid}", "emphasis": hit})
            tgt = _target_for(t["metric"], t.get("variant"), t["sense"], b["id"], intensity,
                              spec.get("overrides") or {}, gp, gid, refdist)
            if str(tgt.get("source", "")).startswith("genre_prior"):
                provenance.append({"objective": b["id"], "metric": t["metric"], "variant": t.get("variant"),
                                   "field": "target", "to": tgt.get("base"), "source": tgt["source"]})
            terms.append({
                "objective": b["id"], "metric": t["metric"], "variant": t.get("variant"),
                "variant_canonical": canonical_variant(t["metric"], t.get("variant")),
                "key": term_key(t["metric"], t.get("variant")),
                "sense": t["sense"], "weight_catalog": w0, "weight_in_objective": wn,
                "blend_weight": b["weight"], "weight": b["weight"] * wn, "weight_source": src,
                "target": tgt,
            })

    # constraints are fixed: everything in 4.3, emphasis is only for reporting
    emph_c = sorted({c for b in blend for c in (cat[b["id"]].get("constraints_emphasis") or [])})
    constraints = {"ids": list(CONSTRAINT_IDS), "emphasis": emph_c,
                   "source": "knowledge/thresholds.json + media profile",
                   "relaxable": False,
                   "note": "blend, intensity, overrides and genre never relax a constraint (SPEC 4.3)"}
    gate = {"objective": "translation", "spec_id": "OF-5", "always_applied": True,
            "strict_mono_fold": bool(gp and any(e == "P-06:gate" for e in gp.get("emphasis", [])))}

    defs = {"catalog": canonical_hash(config.load_objectives()),
            "objective_metrics": canonical_hash(metric_table()),
            "genre_priors": canonical_hash(config.load_genre_priors()) if gp else None}
    return _json_safe({
        "spec": spec, "spec_source": spec_source, "variant": variant,
        "blend": blend, "intensity": intensity, "overrides": spec.get("overrides") or {},
        "lead": lead, "genre": genre_info, "reference": ref_info,
        "reference_distribution": refdist,
        "terms": terms, "constraints": constraints, "gate": gate,
        "notes": notes, "provenance": provenance, "definitions": defs,
        "stems": sorted(meta),
        "stems_meta": meta,
    })


def set_objective(project, spec, *, variant_id: str | None = None, actor: str = "human") -> dict:
    """`objective set`: validate and write the objective (project or variant override)."""
    spec = normalize_spec(spec)
    issues = validate_objective_spec(spec)
    errs = [i for i in issues if i["level"] == "error"]
    if errs:
        raise ValidationError("invalid objective", details={"issues": errs})
    meta = stems_meta(project.data)
    resolve_lead(spec, meta)  # raises on an unknown lead stem
    clean = {"blend": [{"id": b["id"], "weight": float(b["weight"])} for b in spec["blend"]],
             "intensity": float(spec["intensity"]), "overrides": spec.get("overrides") or {},
             "lead_stem": spec.get("lead_stem")}
    if variant_id is None:
        project.data["objective"] = clean
        where = "project"
    else:
        v = next((v for v in project.data.get("variants") or [] if v.get("id") == variant_id), None)
        if v is None:
            raise InputError(f"unknown variant '{variant_id}'")
        v["objective"] = clean
        where = f"variant:{variant_id}"
    project.save(actor=actor, op="objective_set", reason=f"objective set ({where})")
    res = resolve_objective(project, variant=variant_id)
    return {"set": where, "objective": clean, "warnings": [i for i in issues if i["level"] != "error"],
            "resolved": summarize_resolved(res)}


def summarize_resolved(res: dict) -> dict:
    """Short form for agents (token saving, 7.2)."""
    return {"blend": [{"id": b["id"], "weight": round(b["weight"], 4)} for b in res["blend"]],
            "intensity": res["intensity"], "lead": res["lead"], "genre": res["genre"].get("id"),
            "reference": res["reference"],
            "terms": [{"objective": t["objective"], "key": t["key"], "weight": round(t["weight"], 4),
                       "target": t["target"].get("range"), "target_source": t["target"].get("source")}
                      for t in res["terms"]],
            "notes": [n.get("code") for n in res["notes"]]}


# --------------------------------------------------------------------------
# measurement


def needed_metrics(resolved: dict) -> set[str]:
    return {t["metric"] for t in resolved.get("terms", [])}


def band_ratio_db(vector: dict, lo_hz: float, hi_hz: float) -> float | None:
    """10*log10(E[lo, hi) / E(rest)) from the ERB LTAS of a measurement vector."""
    lt = ((vector or {}).get("LTAS") or {}).get("erb") or {}
    centers = lt.get("center_hz")
    levels = lt.get("level_db")
    if not centers or not levels:
        return None
    c = np.asarray(centers, dtype=np.float64)
    lv = np.asarray([v if v is not None else -400.0 for v in levels], dtype=np.float64)
    p = 10.0 ** (lv / 10.0)
    sel = (c >= lo_hz) & (c < hi_hz)
    a, b = float(p[sel].sum()), float(p[~sel].sum())
    if a <= 0 or b <= 0:
        return None
    return 10.0 * math.log10(a / b)


def reference_scalars(vector: dict, perceptual: dict | None) -> dict:
    """Scalar features of one reference (used as target distributions, R-17)."""
    tbl = metric_table()["metrics"]
    p03 = (vector or {}).get("P-03") or {}
    p05 = ((vector or {}).get("P-05") or {}).get("full_band") or {}
    out = {
        "P-07:sub+bass": band_ratio_db(vector, *tbl["P-07"]["sub+bass"]["range_hz"]),
        "P-07:sub": band_ratio_db(vector, *tbl["P-07"]["sub"]["range_hz"]),
        "P-07:bass": band_ratio_db(vector, *tbl["P-07"]["bass"]["range_hz"]),
        "P-07:playable_band": band_ratio_db(vector, *tbl["P-07"]["playable_band"]["range_hz"]),
        "P-03:plr": p03.get("plr_db"),
        "P-03:psr": p03.get("psr_db"),
        "P-03:lra": p03.get("lra_lu"),
        "P-05:width_restraint": p05.get("side_ratio"),
        "P-11": ((perceptual or {}).get("P-11") or {}).get("ltas_prominence_db"),
    }
    return _json_safe(out)


def _lowpass(x, sr: float, hz: float):
    from scipy import signal as ss
    a = np.asarray(x, dtype=np.float64)
    sos = ss.butter(6, hz, btype="lowpass", fs=float(sr), output="sos")
    return ss.sosfiltfilt(sos, a, axis=0)


def _perceptual(x, sr: float, needs: set, reference: dict | None, sections) -> dict:
    """Only the 2mix perceptual proxies the terms need (shared analysis context)."""
    from .analysis import perceptual as pc
    out: dict = {}
    ctx = pc._Ctx(x, sr) if hasattr(pc, "_Ctx") else None
    if ctx is not None:
        out["level_match"] = ctx.level_match()
        if "P-01" in needs:
            out["P-01"] = pc._ltas_deviation(ctx, reference, None)
        if "P-11" in needs:
            out["P-11"] = pc._harshness(ctx)
        if "P-17" in needs:
            out["P-17"] = pc._sibilance(ctx)
        if "P-19" in needs:
            out["P-19"] = pc._smoothness(ctx)
        if "P-20" in needs:
            out["P-20"] = pc._section_contrast(ctx, sections)
    else:  # pragma: no cover - public fallback
        if "P-01" in needs:
            out["P-01"] = pc.ltas_deviation(x, sr, reference)
        if "P-11" in needs:
            out["P-11"] = pc.harshness(x, sr)
        if "P-17" in needs:
            out["P-17"] = pc.sibilance(x, sr)
        if "P-19" in needs:
            out["P-19"] = pc.spectral_smoothness(x, sr)
        if "P-20" in needs:
            out["P-20"] = pc.section_contrast(x, sr, sections)
    return _json_safe(out)


def constraint_facts(x, sr: int, vector: dict, *, boundary_hz: float) -> dict:
    """Signal facts behind S-03 / S-04 / S-09 (same measures as core/verify.py)."""
    from . import master_analysis as ma
    th = _th()
    band = _tv(th, "s04_mono_loss", "lead_clarity_band_hz", default=[300, 5000])
    a = np.asarray(x, dtype=np.float64)
    stereo = a.ndim == 2 and a.shape[1] >= 2
    return _json_safe({
        "boundary_hz": boundary_hz,
        "stereo": stereo,
        "low_band_mono_loss_db": ma.mono_loss_db(a, sr, 20.0, boundary_hz) if stereo else None,
        "lead_clarity_mono_loss_db": ma.mono_loss_db(a, sr, float(band[0]), float(band[1])) if stereo else None,
        "low_band_persistence": ((vector.get("P-05") or {}).get("low_band_persistence")),
        "health": vector.get("health"),
        "true_peak_dbtp": (vector.get("P-14") or {}).get("true_peak_dbtp"),
    })


def measure_for_objective(x, sr: int, resolved: dict, *, before=None, before_p20: dict | None = None,
                          sections: list | None = None, stems: dict | None = None,
                          stems_before: dict | None = None, profile: dict | str | None = None,
                          ceiling_dbtp: float | None = None, limiter: dict | None = None,
                          cleanup: dict | None = None, chain: list | None = None,
                          gate: bool = False, bpm: float | None = None,
                          key_tonic_hz: float | None = None, extra_metrics=None) -> dict:
    """Measure what the resolved objective needs (plus the constraint facts).

    x: processed signal [frames, channels]; before: the unprocessed signal (for
    preservation metrics P-12 / P-20). stems: {track_id: array} (optional; the
    stem-context metrics need them). limiter: limiter GR stats (P-18).
    cleanup: {"P-16": {...penalty}, "P-21": {...}} once the cleanup stage exists.
    chain: master chain (S-06 order check). gate: also run OF-5.
    extra_metrics: metric ids to measure even if no term needs them (safety valves).
    """
    from .measure import measure_signal
    if isinstance(profile, str):
        profile = config.get_profile(profile)
    pa = (profile or {}).get("playback_assumptions") or {}
    boundary = float(pa.get("mono_low_band_hz") or _tv(_th(), "s03_low_band_phase", "boundary_hz", default=120.0))
    needs = needed_metrics(resolved) | set(extra_metrics or ())
    vec = measure_signal(x, sr, low_band_hz=boundary)
    perceptual_needs = set(needs) & {"P-01", "P-11", "P-17", "P-19", "P-20"}
    if "P-20" in needs and before is None and before_p20 is None:
        perceptual_needs.discard("P-20")
    if "P-20" in perceptual_needs and sections is None and before_p20 is not None:
        sections = before_p20.get("sections")
    perc = _perceptual(x, sr, perceptual_needs, (resolved.get("reference_distribution") or {}).get("p01"),
                       sections) if perceptual_needs else {}
    meas: dict = {"vector": vec, "perceptual": perc, "stems": None, "mix_proxies": {},
                  "limiter": limiter, "cleanup": cleanup,
                  "context": {"sample_rate": int(sr), "profile": (profile or {}).get("id"),
                              "ceiling_dbtp": ceiling_dbtp, "boundary_hz": boundary,
                              "lead": resolved.get("lead"), "has_before": before is not None,
                              "has_stems": bool(stems)}}
    if "P-20" in perceptual_needs:
        from .analysis.perceptual import contrast_change, section_contrast
        bp = before_p20 if before_p20 is not None else section_contrast(before, sr, sections)
        meas["perceptual"]["P-20_change"] = contrast_change(bp, perc["P-20"])
    if before is not None and ({"P-12", "P-04"} & needs):
        from .analysis.stems import transient_retention
        meas["mix_proxies"]["P-12"] = transient_retention(before, x, sr)
    if stems and (needs & (STEM_METRICS | {"P-08", "P-15", "P-12"})):
        from .analysis.stems import measure_stem_context
        meta = {}
        lead = (resolved.get("lead") or {}).get("stem")
        for t in stems:
            m = dict((resolved.get("stems_meta") or {}).get(t) or {})
            meta[t] = {"role": m.get("role", "other"), "is_lead": t == lead, "importance": m.get("importance")}
        meas["stems"] = measure_stem_context(stems, sr, meta, genre=(resolved.get("genre") or {}).get("id"),
                                             bpm=bpm, key_tonic_hz=key_tonic_hz,
                                             before=stems_before, after=stems if stems_before else None)
    if not stems:
        if "P-08" in needs:
            from .analysis.stems import harmonic_completion
            r = harmonic_completion(_lowpass(x, sr, metric_table()["gate"]["pitch"]["mix_lowpass_hz"]), sr)
            r["proxy"] = "2mix low-passed (no bass stem)"
            meas["mix_proxies"]["P-08"] = r
        if "P-15" in needs:
            from .analysis.stems import reverb_metrics
            r = reverb_metrics(x, sr)
            r["proxy"] = "2mix (no stems)"
            meas["mix_proxies"]["P-15"] = r
    meas["constraint_facts"] = constraint_facts(x, sr, vec, boundary_hz=boundary)
    if chain is not None:
        meas["chain"] = chain
    if gate:
        from . import gate as _gate
        meas["gate"] = _gate.evaluate_gate(x, sr, stems=stems, meta=resolved.get("stems_meta"),
                                           profile=profile, lead=(resolved.get("lead") or {}).get("stem"),
                                           strict_mono=bool((resolved.get("gate") or {}).get("strict_mono_fold")))
    return _json_safe(meas)


# --------------------------------------------------------------------------
# constraints


def evaluate_constraints(measurements: dict) -> tuple[dict, dict]:
    """S-nn statuses from measurement facts. Thresholds: knowledge/thresholds.json + profile.

    Returns ({S-nn: pass|fail|not_evaluated}, {S-nn: details}).
    """
    th = _th()
    facts = measurements.get("constraint_facts") or {}
    ctx = measurements.get("context") or {}
    st: dict = {c: "not_evaluated" for c in CONSTRAINT_IDS}
    det: dict = {c: {"reason": "not measured at this stage"} for c in CONSTRAINT_IDS}

    tp = facts.get("true_peak_dbtp")
    ceiling = ctx.get("ceiling_dbtp")
    if ceiling is None:
        ceiling = -1.0
        c_src = "S-01 default (-1.0 dBTP; no profile given)"
    else:
        c_src = f"profile {ctx.get('profile')}"
    if tp is not None:
        st["S-01"] = "pass" if tp <= ceiling + 1e-9 else "fail"
        det["S-01"] = {"true_peak_dbtp": tp, "ceiling_dbtp": ceiling, "ceiling_source": c_src,
                       "oversample": ((measurements.get("vector") or {}).get("P-14") or {}).get("oversample")}
    elif facts:
        st["S-01"] = "pass"
        det["S-01"] = {"true_peak_dbtp": None, "note": "silent signal"}
    codec = measurements.get("codec")
    if codec:
        lim = codec.get("ceiling_dbtp")
        worst = codec.get("worst_true_peak_dbtp")
        if worst is not None and lim is not None:
            st["S-02"] = "pass" if worst <= lim else "fail"
            det["S-02"] = codec
    else:
        det["S-02"] = {"reason": "codec round trip is checked at render/verify time, not on previews"}

    pers = facts.get("low_band_persistence")
    if facts.get("stereo") is False:
        st["S-03"], det["S-03"] = "pass", {"note": "mono signal: no anti-phase possible"}
    elif pers:
        max_run = float(_tv(th, "s03_low_band_phase", "max_persistence_s", default=1.0))
        max_frac = float(_tv(th, "s03_low_band_phase", "max_negative_fraction", default=0.1))
        run, frac = float(pers.get("longest_negative_run_s") or 0.0), float(pers.get("negative_fraction") or 0.0)
        st["S-03"] = "pass" if (run <= max_run and frac <= max_frac) else "fail"
        det["S-03"] = {"boundary_hz": facts.get("boundary_hz"), "longest_negative_run_s": run,
                       "negative_fraction": frac, "limits": {"max_persistence_s": max_run,
                                                             "max_negative_fraction": max_frac}}

    if facts.get("stereo") is False:
        st["S-04"], det["S-04"] = "pass", {"note": "mono signal: no mono-fold loss"}
    elif facts:
        low_max = float(_tv(th, "s04_mono_loss", "low_band_max_db", default=1.5))
        lead_max = float(_tv(th, "s04_mono_loss", "lead_clarity_max_db", default=3.0))
        low, lead = facts.get("low_band_mono_loss_db"), facts.get("lead_clarity_mono_loss_db")
        ok = (low is None or low <= low_max) and (lead is None or lead <= lead_max)
        st["S-04"] = "pass" if ok else "fail"
        det["S-04"] = {"low_band_mono_loss_db": low, "lead_clarity_mono_loss_db": lead,
                       "limits": {"low_band_max_db": low_max, "lead_clarity_max_db": lead_max},
                       "note": "full-mix proxy for the lead band"}

    chain = measurements.get("chain")
    if chain is not None:
        try:
            from .mastering import check_chain_order
            r = check_chain_order(chain)
            st["S-06"], det["S-06"] = r["status"], r
        except Exception as exc:  # pragma: no cover - depends on the mastering module
            det["S-06"] = {"reason": f"order check unavailable: {exc}"}

    h = facts.get("health")
    if h:
        dc_max = float(_tv(th, "s09_health", "dc_offset_max", default=0.001))
        dc = max((abs(v) for v in h.get("dc_offset") or [0.0]), default=0.0)
        bad = []
        if h.get("nan_count") or h.get("inf_count"):
            bad.append("non-finite samples")
        if h.get("clipped_samples"):
            bad.append("clipped samples")
        if dc > dc_max:
            bad.append("DC offset")
        st["S-09"] = "fail" if bad else "pass"
        det["S-09"] = {"problems": bad, "dc_offset_max": dc, "dc_limit": dc_max,
                       "clipped_samples": h.get("clipped_samples"), "nan_count": h.get("nan_count")}
    cleanup = measurements.get("cleanup") or {}
    for c in ("S-07", "S-08"):
        if isinstance(cleanup.get(c), dict) and cleanup[c].get("status") in ("pass", "fail"):
            st[c], det[c] = cleanup[c]["status"], cleanup[c]
    return st, det


# --------------------------------------------------------------------------
# terms


def _nm(reason: str, **kw) -> dict:
    return {"status": "not_measured", "value": None, "penalty": None, "reason": reason, **kw}


def _ok(value, penalty, target=None, **kw) -> dict:
    if penalty is None:
        return _nm("metric returned no value", value=value, **kw)
    return {"status": "measured", "value": value, "penalty": float(min(1.0, max(0.0, penalty))),
            "target": target, **kw}


def term_value(measurements: dict, term: dict) -> dict:
    """Value and penalty of one resolved term from a measurement bundle."""
    m, cv = term["metric"], term.get("variant_canonical")
    tgt = term.get("target") or {}
    rng = tgt.get("range")
    lo, hi = (rng if isinstance(rng, list) and len(rng) == 2 else [None, None])
    scale = tgt.get("scale")
    vec = measurements.get("vector") or {}
    perc = measurements.get("perceptual") or {}
    stems = measurements.get("stems")
    prox = measurements.get("mix_proxies") or {}
    cleanup = measurements.get("cleanup") or {}

    if m == "P-01":
        r = perc.get("P-01")
        if not r:
            return _nm("2mix perceptual measurement missing")
        return _ok(r.get("weighted_rms_deviation_db"), r.get("penalty"),
                   {"source": (r.get("reference") or {}).get("source")},
                   unit="dB (ISO 226 weighted RMS deviation)",
                   largest_deviations=r.get("largest_deviations"), generic_prior=r.get("generic_prior"))
    if m == "P-02":
        if not stems:
            return _nm("needs stems (masking is an inter-stem metric)", needs="stems")
        p = (stems.get("P-02") or {}).get(cv or "overall") or {}
        if cv == "vs_lead" and not p.get("available", True):
            return _nm(p.get("reason") or "no lead")
        if cv == "low_to_mid":
            v = p.get("value")
        elif cv == "time_axis":
            v = p.get("value")
        else:
            v = p.get("value")
        if v is None:
            return _nm("masking value not available", detail=p.get("reason"))
        return _ok(v, _rp(v, lo, hi, scale), rng, unit="dB buried")
    if m == "P-03":
        p03 = vec.get("P-03") or {}
        if cv is None:
            plr, lra = p03.get("plr_db"), p03.get("lra_lu")
            ps = [x for x in (_rp(plr, *tgt["plr_db"], scale), _rp(lra, *tgt["lra_lu"], scale)) if x is not None]
            if not ps:
                return _nm("PLR/LRA not available (signal shorter than 3 s?)")
            return _ok({"plr_db": plr, "lra_lu": lra}, max(ps), {"plr_db": tgt["plr_db"], "lra_lu": tgt["lra_lu"]},
                       unit="dB / LU")
        key = {"plr": "plr_db", "psr": "psr_db", "lra": "lra_lu", "lra_density": "lra_lu"}[cv]
        v = p03.get(key)
        if v is None:
            return _nm(f"{key} not available (signal shorter than 3 s?)")
        pen = _rp(v, lo, hi, scale)
        if cv == "lra_density":
            p10, p95 = p03.get("short_term_p10"), p03.get("short_term_p95")
            dens = (p95 - p10) if (p10 is not None and p95 is not None) else None
            dr = tgt.get("density_p95_p10_lu") or [None, None]
            pd = _rp(dens, dr[0], dr[1], scale) if dens is not None else None
            pen = max(x for x in (pen, pd) if x is not None) if (pen is not None or pd is not None) else None
            return _ok({"lra_lu": v, "short_term_p95_p10_lu": dens}, pen, rng, unit="LU")
        return _ok(v, pen, rng, unit=key)
    if m == "P-04":
        r = prox.get("P-12") or {}
        bands = r.get("bands") or {}
        if not bands:
            return _nm("needs the unprocessed signal (preservation metric)", needs="before")
        losses = [max(0.0, -bands[b]["delta_db"]) for b in tgt.get("bands", []) if b in bands
                  and bands[b].get("delta_db") is not None]
        if not losses:
            return _nm("no crest values in the selected bands")
        v = float(np.mean(losses))
        return _ok(v, _rp(v, None, tgt.get("loss_ok_db", 1.5), scale), rng, unit="dB crest loss")
    if m == "P-05":
        p05 = vec.get("P-05") or {}
        if not p05.get("available"):
            return _nm("mono signal: width not applicable")
        v = (p05.get("full_band") or {}).get("side_ratio")
        return _ok(v, _rp(v, lo, hi, scale), rng, unit="side ratio")
    if m == "P-06":
        p06 = vec.get("P-06") or {}
        if not p06.get("available"):
            return _nm("mono signal: mono fold not applicable")
        bands = p06.get("bands") or {}
        if any(b.get("cancelled") for b in bands.values()):
            return _ok("cancelled", 1.0, rng, unit="dB mono loss")
        vals = [b["mono_loss_db"] for b in bands.values() if b.get("mono_loss_db") is not None]
        v = max(vals) if vals else None
        return _ok(v, _rp(v, lo, hi, scale), rng, unit="dB mono loss")
    if m == "P-07":
        r = tgt.get("range_hz") or [20.0, 250.0]
        v = band_ratio_db(vec, float(r[0]), float(r[1]))
        return _ok(v, _rp(v, lo, hi, scale), rng, unit="dB band/rest", range_hz=r)
    if m == "P-08":
        p = (stems or {}).get("P-08") if stems else prox.get("P-08")
        if not p:
            return _nm("no bass stem and no 2mix proxy")
        v = p.get("index_db")
        return _ok(v, _rp(v, lo, hi, scale), rng, unit="dB harmonic index", proxy=p.get("proxy"))
    if m == "P-09":
        if not stems:
            return _nm("needs stems (depth order is per stem)", needs="stems")
        p = stems.get("P-09") or {}
        return _ok(p.get("kendall_tau", p.get("lead_rank")), p.get("penalty"), None, unit="penalty",
                   order=p.get("estimated_order_front_to_back"))
    if m == "P-10":
        if not stems:
            return _nm("needs stems (lead vs accompaniment)", needs="stems")
        p = stems.get("P-10") or {}
        v = p.get("value")
        if v is None:
            return _nm(p.get("reason") or "no lead")
        verdict = None if lo is None else ("buried" if v < lo else ("floating" if hi is not None and v > hi else "ok"))
        return _ok(v, _rp(v, lo, hi, scale), rng, unit="dB", verdict=verdict,
                   lead_is_estimate=p.get("lead_is_estimate"))
    if m == "P-11":
        r = perc.get("P-11")
        if not r or r.get("penalty") is None:
            return _nm("no active signal")
        v = r.get("ltas_prominence_db")
        if cv == "two_sided":
            return _ok(v, _rp(v, lo, hi, scale), rng, unit="dB presence")
        pl = _rp(v, lo, hi, scale)
        pk = tgt.get("peaky_frame_pct") or [None, None]
        pp = _rp(r.get("peaky_frame_pct"), pk[0], pk[1], tgt.get("peaky_scale") or 15.0)
        # mean (not max) of the long-term excess and the share of peaky frames: the
        # frame share saturates quickly, the mean keeps the term responsive to small moves
        ps = [x for x in (pl, pp) if x is not None]
        return _ok(v, float(np.mean(ps)) if ps else None, rng, unit="dB prominence",
                   peaky_frame_pct=r.get("peaky_frame_pct"), combine="mean(ltas_excess, peaky_frames)")
    if m == "P-12":
        if stems and (stems.get("P-12") or {}).get("penalty") is not None:
            p = stems["P-12"]
            return _ok(p.get("penalty"), p.get("penalty"), None, unit="penalty", scope="stems")
        p = prox.get("P-12")
        if not p:
            return _nm("needs the unprocessed signal (preservation metric)", needs="before")
        return _ok(p.get("mean_crest_loss_db"), p.get("penalty"), None, unit="dB crest loss",
                   attack_ratio_delta_db=p.get("attack_ratio_delta_db"), scope="2mix")
    if m == "P-13":
        if not stems:
            return _nm("needs stems (kick and bass separately)", needs="stems")
        p = stems.get("P-13") or {}
        return _ok(p.get("cents_difference"), p.get("penalty"), None, unit="cents")
    if m == "P-14":
        ceiling = (measurements.get("context") or {}).get("ceiling_dbtp")
        ceiling = -1.0 if ceiling is None else ceiling
        v = (vec.get("P-14") or {}).get("true_peak_dbtp")
        return _ok(v, _rp(v, None, ceiling, scale or 1.0), [None, ceiling], unit="dBTP")
    if m == "P-15":
        if stems:
            p15 = stems.get("P-15") or {}
            if cv == "lead":
                lead = p15.get("lead")
                p = (p15.get("per_stem") or {}).get(lead) if lead else None
            else:
                ps = list((p15.get("per_stem") or {}).values())
                lead = p15.get("lead")
                p = (p15.get("per_stem") or {}).get(lead) if lead else (ps[0] if ps else None)
            if not p:
                return _nm("no lead stem for D/R")
        else:
            if cv == "lead":
                return _nm("needs stems (lead D/R)", needs="stems")
            p = prox.get("P-15")
            if not p:
                return _nm("reverb metrics missing")
        v = p.get("dr_db")
        return _ok(v, _rp(v, lo, hi, scale), rng, unit="dB D/R", rough=True, proxy=p.get("proxy"))
    if m in ("P-16", "P-21"):
        p = cleanup.get(m)
        if not p or p.get("penalty") is None:
            return _nm("cleanup stage measurements not available yet (M5)", needs="cleanup")
        return _ok(p.get("value"), p.get("penalty"), None)
    if m == "P-17":
        r = perc.get("P-17")
        if not r or r.get("penalty") is None:
            return _nm("no sibilance-band activity")
        v = r.get("p99_prominence_db")
        pe = tgt.get("event_pct") or [None, None]
        ps = [x for x in (_rp(v, lo, hi, scale), _rp(r.get("event_pct"), pe[0], pe[1], tgt.get("event_scale") or 4.0))
              if x is not None]
        return _ok(v, float(np.mean(ps)) if ps else None, rng, unit="dB p99 prominence",
                   event_pct=r.get("event_pct"), combine="mean(peak_prominence, event_share)")
    if m == "P-18":
        lim = measurements.get("limiter")
        if not lim or lim.get("gr_p95_db") is None:
            return _nm("limiter statistics not available", needs="limiter")
        v = lim["gr_p95_db"]
        return _ok(v, _rp(v, lo, hi, scale), rng, unit="dB GR p95")
    if m == "P-19":
        r = perc.get("P-19")
        if not r:
            return _nm("2mix perceptual measurement missing")
        return _ok(r.get("rms_deviation_db"), r.get("penalty"), None, unit="dB",
                   transferred_from="loudspeaker preference research (SPEC 4.2 note)")
    if m == "P-20":
        r = perc.get("P-20_change")
        if not r:
            return _nm("needs the unprocessed signal (contrast preservation, R-26)", needs="before")
        return _ok(r.get("shrink_db"), r.get("penalty"), r.get("range"), unit="dB shrink",
                   warning=r.get("warning"))
    if m == "P-22":
        if not stems:
            return _nm("needs stems (owners per band)", needs="stems")
        p = stems.get("P-22") or {}
        return _ok(p.get("max_count"), p.get("penalty"), None, unit="owners per band (max)")
    return _nm(f"unknown metric {m}")


def evaluate(measurements: dict, resolved: dict) -> dict:
    """SPEC 4.1: constraints first (reject), weighted penalty sum, gate separately.

    Returns {score, score_unconstrained, terms[], constraints, constraint_details,
    rejected, gate, redistribution[], notes}. score is None for a rejected candidate.
    """
    constraints, cdet = evaluate_constraints(measurements)
    rejected = any(v == "fail" for v in constraints.values())
    rows = []
    for t in resolved["terms"]:
        r = term_value(measurements, t)
        rows.append({"objective": t["objective"], "metric": t["metric"], "variant": t.get("variant"),
                     "key": t["key"], "sense": t["sense"], "weight": t["weight"],
                     "effective_weight": 0.0, "value": r.get("value"), "target": r.get("target", (t.get("target") or {}).get("range")),
                     "target_source": (t.get("target") or {}).get("source"),
                     "penalty": r.get("penalty"), "contribution": 0.0, "status": r["status"],
                     **({"reason": r["reason"]} if r.get("reason") else {}),
                     **{k: v for k, v in r.items() if k not in ("status", "value", "penalty", "target", "reason")}})
    redistribution = []
    notes = []
    for b in resolved["blend"]:
        mine = [r for r in rows if r["objective"] == b["id"]]
        measured_w = sum(r["weight"] for r in mine if r["status"] == "measured")
        total_w = sum(r["weight"] for r in mine)
        missing = [r for r in mine if r["status"] != "measured"]
        if measured_w <= 0:
            if mine:
                notes.append({"code": "objective_unmeasured", "objective": b["id"],
                              "text": f"no term of '{b['id']}' could be measured; it does not contribute"})
                redistribution.append({"objective": b["id"], "moved_weight": total_w, "to": None,
                                       "terms": [r["key"] for r in missing],
                                       "reasons": {r["key"]: r.get("reason") for r in missing}})
            continue
        f = total_w / measured_w
        for r in mine:
            if r["status"] == "measured":
                r["effective_weight"] = r["weight"] * f
        if missing:
            redistribution.append({"objective": b["id"], "moved_weight": total_w - measured_w,
                                   "factor": f, "terms": [r["key"] for r in missing],
                                   "reasons": {r["key"]: r.get("reason") for r in missing},
                                   "rule": "proportional to the measured terms of the same objective"})
    eff_sum = sum(r["effective_weight"] for r in rows)
    if eff_sum > 0 and abs(eff_sum - 1.0) > 1e-9:
        for r in rows:
            r["effective_weight"] /= eff_sum
        notes.append({"code": "weights_renormalised",
                      "text": "objectives without measurable terms dropped; remaining weights renormalised to 1"})
    for r in rows:
        if r["status"] == "measured":
            r["contribution"] = r["effective_weight"] * r["penalty"]
    raw = float(sum(r["contribution"] for r in rows)) if eff_sum > 0 else None
    if rejected:
        notes.append({"code": "rejected", "rule": "SPEC 4.1",
                      "text": "a safety invariant failed: the candidate is rejected before scoring",
                      "failed": [k for k, v in constraints.items() if v == "fail"]})
    by_obj = {}
    for b in resolved["blend"]:
        mine = [r for r in rows if r["objective"] == b["id"] and r["status"] == "measured"]
        by_obj[b["id"]] = float(sum(r["contribution"] for r in mine))
    return _json_safe({
        "score": None if rejected else raw,
        "score_unconstrained": raw,
        "score_by_objective": by_obj,
        "terms": rows,
        "constraints": constraints,
        "constraint_details": cdet,
        "rejected": rejected,
        "gate": measurements.get("gate") or {"status": "not_evaluated", "pass": False, "checks": []},
        "redistribution": redistribution,
        "notes": notes,
        "level_matched": True,
        "rule": "R-01: penalties use level-matched measurements",
    })


__all__ = [
    "CONSTRAINT_IDS", "METRIC_IDS", "KNOWN_VARIANTS", "ELEMENTS",
    "parse_objective_arg", "normalize_spec", "validate_objective_definition", "validate_objective_spec",
    "resolve_objective", "resolve_lead", "stems_meta", "set_objective", "summarize_resolved",
    "measure_for_objective", "constraint_facts", "band_ratio_db", "reference_scalars",
    "evaluate_constraints", "term_value", "evaluate", "metric_table",
]
