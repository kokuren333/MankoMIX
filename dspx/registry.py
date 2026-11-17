"""Deterministic discovery of extension declarations and implementations.

Modules expose SPECS, IMPLS and optionally TIME_VARYING, COMPOSITES,
RESOLVE_PARAMS, SCHEMA_PATCH and CROSS_VALIDATE. A RESOLVE_PARAMS function
returns a fresh raw parameter dict before scalar defaults/validation. A
SCHEMA_PATCH function modifies its type's params schema in place.
Each CROSS_VALIDATE function accepts resolved params and raises
ParamError for invalid relationships; its return value is ignored.
Each COMPOSITES value takes validated params and returns a list of chain items.
Definition modules must not import dsp.processors (use dspx.params instead).
"""
from __future__ import annotations

import copy
import importlib
from pathlib import Path

_TABLES = None


def _collect():
    global _TABLES
    if _TABLES is None:
        definitions, impls, tv, expansions, validators = [], {}, set(), {}, {}
        resolvers, schema_patches = {}, {}
        names = set()
        for path in sorted((Path(__file__).parent / "procs").glob("*.py"), key=lambda p: p.name):
            if path.name == "__init__.py":
                continue
            mod = importlib.import_module(f"{__package__}.procs.{path.stem}")
            for spec in mod.SPECS:
                name = spec["type"]
                if name in names:
                    raise ImportError(f"duplicate DSP extension type: {name}")
                names.add(name)
                definitions.append(copy.deepcopy(spec))
            for target, source in ((impls, mod.IMPLS), (expansions, getattr(mod, "COMPOSITES", {})),
                                   (validators, getattr(mod, "CROSS_VALIDATE", {})),
                                   (resolvers, getattr(mod, "RESOLVE_PARAMS", {})),
                                   (schema_patches, getattr(mod, "SCHEMA_PATCH", {}))):
                overlap = target.keys() & source.keys()
                if overlap:
                    raise ImportError(f"duplicate DSP extension registration: {sorted(overlap)}")
                if any(not callable(fn) for fn in source.values()):
                    raise ImportError(f"non-callable DSP implementation in {path.name}")
                target.update(source)
            tv.update(getattr(mod, "TIME_VARYING", ()))
        if (impls.keys() | expansions.keys() | validators.keys() | resolvers.keys()
                | schema_patches.keys() | tv) - names:
            raise ImportError("DSP extension metadata refers to an undeclared type")
        for spec in definitions:
            name = spec["type"]
            if bool(spec.get("composite")) != (name in expansions):
                raise ImportError(f"composite declaration/expander mismatch: {name}")
            if name in expansions and name in impls:
                raise ImportError(f"composite cannot also have an implementation: {name}")
        _TABLES = definitions, impls, frozenset(tv), expansions, validators, resolvers, schema_patches
    return _TABLES


def _tables():
    tables = _collect()
    # _PROCESSORS contains only the original definitions, also during engine import.
    # Collection is cached before importing processors, so either import order works.
    from mankomix.dsp import processors
    overlap = {d["type"] for d in tables[0]} & {d["type"] for d in processors._PROCESSORS}
    if overlap:
        raise ImportError(f"DSP extension shadows an existing type: {sorted(overlap)}")
    return tables


def specs() -> list[dict]:
    return copy.deepcopy(_tables()[0])


def implementations() -> dict:
    return dict(_tables()[1])


def time_varying_types() -> frozenset:
    return _tables()[2]


def composites() -> dict:
    return dict(_tables()[3])


def cross_validators() -> dict:
    """Return type-specific validators called after base parameter validation."""
    return dict(_tables()[4])


def param_resolvers() -> dict:
    """Return raw-parameter resolvers called before scalar default expansion."""
    return dict(_tables()[5])


def schema_patches() -> dict:
    """Return in-place params-schema patches for declared extension types."""
    return dict(_tables()[6])
