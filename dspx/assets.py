"""Asset resolver registration; concrete registries are installed by later units.

Resolvers take a string ID and return the asset record, or raise LookupError
for an unknown ID. Tests can replace RESOLVERS entries with monkeypatch.
"""
from mankomix.dsp.errors import ParamError

RESOLVERS = {}


def register(registry: str, resolver) -> None:
    if not isinstance(registry, str) or not registry or not callable(resolver):
        raise ValueError("asset registry requires a name and callable resolver")
    if registry in RESOLVERS:
        raise ValueError(f"asset registry already registered: {registry}")
    RESOLVERS[registry] = resolver


def resolve(registry: str, asset_id: str):
    if not isinstance(asset_id, str):
        raise ParamError("asset ID must be a string")
    if registry not in RESOLVERS:
        raise ParamError(f"unknown asset registry: {registry!r}")
    try:
        record = RESOLVERS[registry](asset_id)
    except LookupError:
        raise ParamError(f"unregistered asset {asset_id!r} in {registry!r}") from None
    if record is None:
        raise ParamError(f"unregistered asset {asset_id!r} in {registry!r}")
    return record


def _resolve_ir(asset_id):
    from .bb.ir import IRS
    return IRS.resolve(asset_id)


register("irs", _resolve_ir)


def _resolve_model(asset_id):
    from .bb.ml import model_entry
    return model_entry(asset_id)


register("models", _resolve_model)
