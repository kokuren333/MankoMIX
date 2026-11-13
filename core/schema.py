"""JSON Schema loading and validation of the data files (schemas/, SPEC 4.8, 5, 12).

Every validation function returns a list of issues in the shared shape
``{"level": "error"|"warning", "path": "/json/pointer", "message": str}``.
Checks that JSON Schema cannot express (weight sums, unique ids, cross-file
references) live here next to the schema validation.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from mankomix import repo_data_root

from .errors import EnvironmentProblem, ValidationError

SCHEMA_NAMES = ("project", "objective", "profile", "delivery", "registry", "report")
WEIGHT_SUM_TOLERANCE = 1e-6


def schema_dir() -> Path:
    return repo_data_root() / "schemas"


def to_pointer(parts: Iterable[Any]) -> str:
    """RFC 6901 JSON pointer from path parts ("" for the document root)."""
    out = []
    for p in parts:
        out.append(str(p).replace("~", "~0").replace("/", "~1"))
    return "".join("/" + p for p in out)


def issue(level: str, path: str | Iterable[Any], message: str) -> dict:
    if not isinstance(path, str):
        path = to_pointer(path)
    return {"level": level, "path": path, "message": message}


def errors_only(issues: list[dict]) -> list[dict]:
    return [i for i in issues if i["level"] == "error"]


def raise_on_errors(issues: list[dict], what: str) -> None:
    errs = errors_only(issues)
    if errs:
        head = "; ".join(f"{e['path'] or '/'}: {e['message']}" for e in errs[:5])
        more = f" (+{len(errs) - 5} more)" if len(errs) > 5 else ""
        raise ValidationError(f"{what} is invalid: {head}{more}", details={"issues": issues})


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    if name not in SCHEMA_NAMES:
        raise ValueError(f"unknown schema '{name}'")
    path = schema_dir() / f"{name}.schema.json"
    try:
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
    except OSError as exc:
        raise EnvironmentProblem(f"schema file missing: schemas/{name}.schema.json") from exc
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=None)
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(name))


def schema_issues(name: str, instance: Any) -> list[dict]:
    """Validate ``instance`` against schemas/<name>.schema.json."""
    out = []
    errors = sorted(_validator(name).iter_errors(instance), key=lambda e: (list(map(str, e.absolute_path)), e.message))
    for err in errors:
        out.append(issue("error", list(err.absolute_path), _message(err)))
    return out


def _message(err) -> str:
    # For combinators, surface the most specific sub-error instead of a blob of the instance.
    if err.validator in ("oneOf", "anyOf") and err.context:
        best = min(err.context, key=lambda e: (len(e.absolute_path) * -1, len(e.message)))
        return best.message
    msg = err.message
    if len(msg) > 300:
        msg = msg[:297] + "..."
    return msg


def _dup_ids(items: list, base: list, key: str = "id") -> list[dict]:
    seen: dict[str, int] = {}
    out = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get(key), str):
            continue
        ident = item[key]
        if ident in seen:
            out.append(issue("error", base + [i, key], f"duplicate id '{ident}' (first at index {seen[ident]})"))
        else:
            seen[ident] = i
    return out


# --- objectives -------------------------------------------------------------

def check_objectives(doc: Any) -> list[dict]:
    """Schema + semantic checks for objectives/catalog.json or a single objective file."""
    out = schema_issues("objective", doc)
    if not isinstance(doc, dict):
        return out
    if "objectives" in doc and isinstance(doc["objectives"], list):
        objs = doc["objectives"]
        base: list = ["objectives"]
        out += _dup_ids(objs, base)
        default = doc.get("default")
        ids = {o.get("id") for o in objs if isinstance(o, dict)}
        if default is not None and default not in ids:
            out.append(issue("error", ["default"], f"default objective '{default}' is not defined"))
        for i, obj in enumerate(objs):
            out += _objective_semantics(obj, base + [i])
    else:
        out += _objective_semantics(doc, [])
    return out


def _objective_semantics(obj: Any, base: list) -> list[dict]:
    out: list[dict] = []
    if not isinstance(obj, dict) or obj.get("kind") != "score":
        return out  # gate objectives are pass/fail and carry no weights
    terms = obj.get("terms")
    if not isinstance(terms, list) or not terms:
        return out
    weights = [t.get("weight") for t in terms if isinstance(t, dict)]
    if not all(isinstance(w, (int, float)) and not isinstance(w, bool) for w in weights):
        return out  # schema already reports the bad weight
    total = float(sum(weights))
    if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
        out.append(issue("error", base + ["terms"],
                         f"term weights of objective '{obj.get('id')}' sum to {total:.6g}, expected 1.0"))
    seen = set()
    for j, t in enumerate(terms):
        if not isinstance(t, dict):
            continue
        key = (t.get("metric"), t.get("variant"))
        if key in seen:
            out.append(issue("error", base + ["terms", j], f"duplicate term {key[0]} variant {key[1]!r}"))
        seen.add(key)
    return out


# --- media profiles / delivery formats --------------------------------------

def check_deliveries(doc: Any) -> list[dict]:
    out = schema_issues("delivery", doc)
    if isinstance(doc, dict) and isinstance(doc.get("formats"), list):
        out += _dup_ids(doc["formats"], ["formats"])
    return out


def check_profiles(doc: Any, deliveries_doc: Any = None) -> list[dict]:
    out = schema_issues("profile", doc)
    if not isinstance(doc, dict) or not isinstance(doc.get("profiles"), list):
        return out
    profiles = doc["profiles"]
    out += _dup_ids(profiles, ["profiles"])
    names: dict[str, str] = {p["id"]: p["id"] for p in profiles if isinstance(p, dict) and isinstance(p.get("id"), str)}
    delivery_ids = None
    if isinstance(deliveries_doc, dict) and isinstance(deliveries_doc.get("formats"), list):
        delivery_ids = {f.get("id") for f in deliveries_doc["formats"] if isinstance(f, dict)}
    for i, p in enumerate(profiles):
        if not isinstance(p, dict):
            continue
        for a in p.get("aliases") or []:
            if a in names:
                out.append(issue("error", ["profiles", i, "aliases"], f"alias '{a}' collides with '{names[a]}'"))
            else:
                names[a] = p.get("id")
        loud = p.get("loudness") or {}
        tgt, win = loud.get("target_lufs_i"), loud.get("window_lufs_i")
        if isinstance(win, list) and len(win) == 2 and all(isinstance(v, (int, float)) for v in win):
            if win[0] > win[1]:
                out.append(issue("error", ["profiles", i, "loudness", "window_lufs_i"], "window is not ordered [low, high]"))
            elif isinstance(tgt, (int, float)) and not (win[0] <= tgt <= win[1]):
                out.append(issue("error", ["profiles", i, "loudness", "target_lufs_i"], "target is outside window_lufs_i"))
        tp = p.get("true_peak") or {}
        rng, ceil = tp.get("range_dbtp"), tp.get("ceiling_dbtp")
        if isinstance(rng, list) and len(rng) == 2 and isinstance(ceil, (int, float)):
            if not (min(rng) <= ceil <= max(rng)):
                out.append(issue("error", ["profiles", i, "true_peak", "ceiling_dbtp"], "ceiling is outside range_dbtp"))
        dd = p.get("default_delivery")
        if delivery_ids is not None and dd not in delivery_ids:
            out.append(issue("error", ["profiles", i, "default_delivery"], f"unknown delivery format '{dd}'"))
    return out


# --- registry / report -------------------------------------------------------

def check_registry(doc: Any) -> list[dict]:
    out = schema_issues("registry", doc)
    if isinstance(doc, dict) and isinstance(doc.get("models"), list):
        out += _dup_ids(doc["models"], ["models"])
        for i, m in enumerate(doc["models"]):
            lic = m.get("license") if isinstance(m, dict) else None
            if isinstance(lic, dict) and isinstance(lic.get("weights"), str) and lic["weights"].lower() == "unknown":
                out.append(issue("warning", ["models", i, "license", "weights"],
                                 "weights license is unknown; the user is responsible (BYOW)"))
    return out


def check_report(doc: Any) -> list[dict]:
    return schema_issues("report", doc)


CHECKS = {
    "objective": check_objectives,
    "profile": check_profiles,
    "delivery": check_deliveries,
    "registry": check_registry,
    "report": check_report,
}
