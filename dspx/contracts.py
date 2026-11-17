"""Validation and JSON Schema additions for the BB-00 parameter types."""
import copy

from mankomix.dsp.errors import ParamError


def validate_params(type, params, legacy):
    from mankomix.dsp import processors as P
    out = legacy(type, params)
    for spec in P.PROCESSORS[type]["params"]:
        pid, kind = spec["id"], spec["type"]
        if kind == "asset":
            from .assets import resolve
            resolve(spec["registry"], out[pid])
        elif kind == "curve":
            limit = spec["max_points"]
            if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 65536:
                raise ParamError(f"{pid}: max_points must be an integer in [0, 65536]")
            value = out[pid]
            if not isinstance(value, list) or len(value) > limit:
                raise ParamError(f"{pid}: curve must be a list of at most {limit} points")
            points, previous = [], None
            for pair in value:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ParamError(f"{pid}: curve points must be [x, y]")
                x, y = (P._num(v, pid, "float") for v in pair)
                if not spec["x_min"] <= x <= spec["x_max"] or not spec["y_min"] <= y <= spec["y_max"]:
                    raise ParamError(f"{pid}: curve point out of range")
                if previous is not None and x <= previous:
                    raise ParamError(f"{pid}: curve x values must be strictly ascending")
                points.append([x, y])
                previous = x
            out[pid] = points
    from .registry import cross_validators
    validator = cross_validators().get(type)
    if validator is not None:
        validator(out)
    return out


def param_schema(spec, legacy):
    kind = spec["type"]
    if kind not in ("curve", "asset"):
        return legacy(spec)
    if kind == "curve":
        result = {"type": "array", "maxItems": spec["max_points"], "items": {
            "type": "array", "minItems": 2, "maxItems": 2,
            "items": {"type": "number"}, "prefixItems": [
                {"type": "number", "minimum": spec["x_min"], "maximum": spec["x_max"]},
                {"type": "number", "minimum": spec["y_min"], "maximum": spec["y_max"]}]}}
    else:
        result = {"type": "string"}
    result["default"] = copy.deepcopy(spec["default"])
    result["description"] = spec["description"] + (f" [{spec['unit']}]" if spec.get("unit") else "")
    return result


def graph_schema(legacy):
    schema = legacy()
    for variant in schema["items"]["oneOf"]:
        variant["properties"]["channel"] = {"enum": ["stereo", "mid", "side", "left", "right"]}
    return schema
