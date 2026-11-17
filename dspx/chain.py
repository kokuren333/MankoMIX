"""Composite expansion, channel targeting and item seeds for engine extensions."""
from __future__ import annotations

import copy

import numpy as np

from mankomix.dsp.errors import ChainError, NumericError, ParamError

CHANNELS = ("stereo", "mid", "side", "left", "right")
CHANNEL_DENIED = frozenset(("pan", "stereo", "limiter", "reverb", "delay", "loudness_gain", "resample", "dither"))


def _check_channel(kind, channel):
    from mankomix.dsp import processors as P
    if channel not in CHANNELS:
        raise ParamError(f"unknown channel target: {channel!r}")
    if channel != "stereo":
        definition = P.PROCESSORS[kind]
        if kind in CHANNEL_DENIED or kind.startswith("aw.") or "export" in definition["stages"] or definition.get("channel_ok") is False:
            raise ParamError(f"processor {kind!r} does not support channel targeting")


def validate_chain(chain, stage, legacy):
    from mankomix.dsp import processors as P
    from .registry import composites
    if not isinstance(chain, list):
        return legacy(chain, stage)
    expanded, metadata, seen = [], {}, set()
    for i, raw in enumerate(chain):
        if not isinstance(raw, dict) or raw.get("type") not in P.PROCESSORS:
            return legacy(chain, stage)
        kind = raw["type"]
        sid = str(raw.get("id") or f"{i:02d}_{kind}")
        if sid in seen:
            raise ChainError(f"duplicate id {sid!r}")
        seen.add(sid)
        clean = {k: v for k, v in raw.items() if k != "channel"}
        clean["id"] = sid
        if "channel" in raw:
            _check_channel(kind, raw["channel"])
        if not P.PROCESSORS[kind].get("composite"):
            expanded.append(clean)
            metadata[sid] = {"channel": raw["channel"]} if "channel" in raw else {}
            continue
        # Check the source's params, stage, keys and implementation status too.
        source = legacy([clean], stage)[0]
        if source.get("fallback"):
            raise ChainError("composites cannot declare a fallback", step=sid)
        expander = composites().get(kind)
        if expander is None:
            raise ParamError(f"missing composite expander: {kind}")
        children = expander(copy.deepcopy(source["params"]))
        if not isinstance(children, list) or not children:
            raise ParamError(f"{kind}: composite expansion must be a nonempty list")
        for n, child in enumerate(children, 1):
            if not isinstance(child, dict) or child.get("type") not in P.PROCESSORS:
                raise ParamError(f"{kind}: invalid composite child")
            if P.PROCESSORS[child["type"]].get("composite"):
                raise ParamError(f"{kind}: composite children must be non-composite types")
            item = {k: raw[k] for k in ("backend", "bypass", "note", "channel") if k in raw}
            item.update(copy.deepcopy(child))
            item["id"] = f"{sid}.{n}"
            if source["bypass"]:
                item["bypass"] = True
            meta = {"composite_of": copy.deepcopy(raw)}
            if "channel" in item:
                _check_channel(item["type"], item["channel"])
                meta["channel"] = item.pop("channel")
            metadata[item["id"]] = meta
            expanded.append(item)
    steps = legacy(expanded, stage)
    for step in steps:
        step.update(metadata[step["id"]])
        channel = step.get("channel", "stereo")
        if channel != "stereo" and step.get("fallback"):
            _check_channel(step["fallback"]["type"], channel)
    return steps


def check_channel_input(steps, audio):
    if audio.shape[1] != 2 and any(s.get("channel", "stereo") != "stereo" for s in steps):
        raise ParamError("channel targeting requires stereo input")


def channel_implementation(fn, step):
    """Run the selected backend on one mono component, retaining the other."""
    channel, sid = step["channel"], step["id"]

    def run(audio, sr, params, *, seed):
        if audio.shape[1] != 2:
            raise ParamError("channel targeting requires stereo input", step=sid)
        if channel in ("left", "right"):
            index = 0 if channel == "left" else 1
            component = audio[:, index:index + 1].copy()
        else:
            mid = (audio[:, 0] + audio[:, 1]) / 2.0
            side = (audio[:, 0] - audio[:, 1]) / 2.0
            component = (mid if channel == "mid" else side)[:, None].copy()
        y, sr_out, stats = fn(component, sr, params, seed=seed)
        y = np.asarray(y, dtype=np.float64)
        if y.ndim == 1:
            y = y[:, None]
        if y.shape != component.shape or sr_out != sr:
            raise NumericError("channel processing must preserve mono shape and sample rate", rule="S-09", step=sid)
        if channel in ("left", "right"):
            result = audio.copy()
            result[:, index] = y[:, 0]
        else:
            if channel == "mid":
                mid = y[:, 0]
            else:
                side = y[:, 0]
            result = np.column_stack((mid + side, mid - side))
        return result, sr_out, stats

    return run


def item_seed(project_seed, sid):
    """SHA-256 of canonical project seed / item ID, first 64 bits unsigned.

    Like engine.seed_from_hash, consume the first sixteen hex digits; retain
    all 64 bits here. Expanded composite IDs are used verbatim.
    """
    from mankomix.core.hashing import canonical_hash
    digest = canonical_hash({'project_seed': int(project_seed), 'item_id': str(sid)})
    return int(digest[:16], 16)


def seed_implementation(fn, kind, sid):
    """Bind the item ID only for registry extensions, after backend selection.

    The processor combines this seed with its seed parameter before PCG64.
    Legacy implementations are returned unchanged, including legacy fallbacks.
    """
    from .registry import implementations
    if kind not in implementations():
        return fn

    def run(audio, sr, params, *, seed):
        return fn(audio, sr, params, seed=item_seed(seed, sid))

    return run


def record_metadata(record, step):
    for key in ("channel", "composite_of"):
        if key in step:
            record[key] = copy.deepcopy(step[key])
