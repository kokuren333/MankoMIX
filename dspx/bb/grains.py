"""Deterministic, zero-extended granular overlap-add primitives.

API: ``event_random(seed, parameter_seed=0, first=0, count=1)`` returns
``(count, 7)`` PCG64 draws, seekable by event number. ``grain_window(u, kind)``
evaluates unit-peak windows on [0, 1). ``plan_grains(frames, sr, params, *,
seed=0, delay_samples=None)`` returns immutable Grain records, including the
right overhang needed for overlap-add at the last sample. ``render_grains(x,
sr, params, *, seed=0, delay_samples=None, block_size=1024)`` returns (wet,
metadata). A delay selects delay-buffer mode; otherwise params selects live
or scrub. Audio is float64 frames x channels, with zero initial history.

This is an independent implementation of the supplied time-domain granular
definition, using BB-09 interpolation and BB-05 curve evaluation. No external
implementation is copied. Hann and Tukey have peak one; exponential windows
retain their tapered exponential amplitude. Normalization is literally
1/sqrt(grain_seconds*density), including in coherent configurations.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Grain:
    """Absolute sample geometry; signed rate includes reverse playback."""

    index: int
    center: float
    start: int
    stop: int
    source_center: float
    rate: float
    pitch_semitones: float
    pan: float
    level: float
    causal_shift: float


def event_random(seed, parameter_seed=0, first=0, count=1):
    """Seek within one PCG64 stream; always consume seven draws per event.

    Columns: time, position, pitch, reverse, pan, level, quantized pitch.
    The engine has already combined project seed and chain item ID.
    """
    if first < 0 or count < 0:
        raise ValueError("event indices and count must be nonnegative")
    stream = np.random.PCG64(np.random.SeedSequence([int(seed), int(parameter_seed)]))
    stream.advance(7 * int(first))
    return np.random.Generator(stream).random((int(count), 7))


def grain_window(u, kind="hann"):
    """Unit-peak Hann, alpha=.5 Tukey, or tapered exp(+-6u) windows.

    Exponential windows use a 5% cosine taper at both endpoints. Values
    outside [0,1) are zero. No window-energy correction is applied.
    """
    u = np.asarray(u, dtype=np.float64)
    v = np.clip(u, 0, 1)
    if kind == "hann":
        w = 0.5 - 0.5 * np.cos(2 * np.pi * v)
    elif kind == "tukey":
        w = np.where(v < .25, .5 - .5 * np.cos(4 * np.pi * v),
                     np.where(v > .75, .5 - .5 * np.cos(4 * np.pi * (1 - v)), 1.0))
    elif kind in ("exp_decay", "exp_attack"):
        q = v if kind == "exp_decay" else 1 - v
        edge = np.minimum(np.minimum(v, 1 - v) / .05, 1)
        w = np.exp(-6 * q) * (.5 - .5 * np.cos(np.pi * edge))
    else:
        raise ValueError("unknown grain window")
    return np.where((u >= 0) & (u < 1), w, 0.0)


def plan_grains(frames, sr, params, *, seed=0, delay_samples=None):
    """Plan centers on an absolute clock, with bounded nonaccumulating jitter.

    Jitter displaces each center by at most .49 of an interval. Causal modes
    shift a grain backwards only when its read would cross the current output
    sample's sinc8 lookahead. Live read heads wrap inside the recent buffer;
    speed zero holds the first complete grain until that audio ages out.
    Scrub curves use BB-05's rounded sample grid and may read future input.
    """
    from .curves import sample_curve
    from mankomix.dsp.errors import ParamError

    if frames < 0 or sr <= 0:
        raise ValueError("nonnegative frames and positive sample rate required")
    if delay_samples is not None and (not np.isfinite(delay_samples) or delay_samples < 0):
        raise ValueError("delay_samples must be finite and nonnegative")
    if not frames:
        return ()
    length = float(params["grain_ms"]) * sr / 1000
    half = length / 2
    hop = sr / float(params["density_hz"])
    count = int(np.ceil((frames + half) / hop)) + 2
    draws = event_random(seed, params.get("seed", 0), count=count)
    centers = (np.arange(count) + .49 * params["jitter"] * (2 * draws[:, 0] - 1)) * hop
    centers[0] = max(0.0, centers[0])
    scrub = delay_samples is None and params.get("mode", "live") == "scrub"
    positions = None
    if scrub:
        positions = sample_curve(params["position"], int(np.ceil(centers[-1])) + 1, sr)
    result = []
    for k, (center, r) in enumerate(zip(centers, draws)):
        start, stop = max(0, int(np.ceil(center - half))), min(frames, int(np.ceil(center + half)))
        if stop <= start:
            continue
        quantize = params.get("pitch_quantize", [])
        pitch = (float(quantize[min(int(r[6] * len(quantize)), len(quantize) - 1)]) if quantize
                 else params["pitch_semitones"] + params["pitch_spread"] * (2 * r[2] - 1))
        if pitch / 12 > 1000:
            raise ParamError("grain pitch exceeds finite float64 playback geometry")
        rate = 2.0 ** (pitch / 12) * (-1 if r[3] < params["reverse"] else 1)
        if delay_samples is not None:
            source = center - delay_samples
        elif scrub:
            # Far out-of-file reads are all zero; avoid overflowing seconds
            # to samples for otherwise valid finite curve coordinates.
            source = min(positions[int(round(center))], (frames + length * abs(rate) + 10) / sr) * sr
        else:
            raw = params["speed"] * center + (1 - params["speed"]) * half
            lower = center - params["buffer_s"] * sr
            source = raw if lower <= raw <= center else center - (center - raw) % (params["buffer_s"] * sr)
        source += params["spray_ms"] * sr / 1000 * (2 * r[1] - 1)
        shift = 0.0
        if not scrub:
            # sinc8's largest index is floor(position)+4. Keep all reads
            # before the current write, even at pitch/reverse extremes.
            shift = max(0.0, source - center + abs(rate - 1) * half + 5)
            source -= shift
        result.append(Grain(k, float(center), start, stop, float(source), float(rate), pitch,
                            params["pan_spread"] * (2 * r[4] - 1),
                            10.0 ** (params.get("level_spread_db", 0) * (2 * r[5] - 1) / 20), shift))
    return tuple(result)


def render_grains(x, sr, params, *, seed=0, delay_samples=None, block_size=1024):
    """Render normalized overlap-add and optional post-normalization feedback.

    Feedback reads precede writes. Adaptive chunks never read unwritten
    samples and preserve addition order for bit identity across block sizes.
    The loop filter affects feedback only. No limiter or tail truncation is
    hidden here: unstable parameter combinations remain a specification issue.
    """
    from .delayline import LoopFilter, read_samples

    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2 or not np.isfinite(x).all() or sr <= 0 or block_size < 1:
        raise ValueError("finite frames x channels audio and positive rate/block size required")
    plans = plan_grains(len(x), sr, params, seed=seed, delay_samples=delay_samples)
    length = params["grain_ms"] * sr / 1000
    overlap = params["grain_ms"] * params["density_hz"] / 1000
    norm = 1 / np.sqrt(overlap)
    feedback = params["feedback"]
    history = np.zeros_like(x) if feedback else x
    wet = np.zeros_like(x)
    loop = LoopFilter(sr, x.shape[1], params.get("lowcut_hz", 0), params.get("highcut_hz", 0))
    # Bound every sinc read in a chunk below the chunk's first write.
    safe = len(x) or 1
    if feedback and plans:
        safe = max(1, int(np.floor(min(
            g.center - g.source_center - abs(g.rate - 1) * length / 2 -
            (0 if g.rate.is_integer() and (g.source_center - g.rate * g.center).is_integer() else 4)
            for g in plans))))
    active, cursor = [], 0
    for a in range(0, len(x), min(int(block_size), safe)):
        b = min(len(x), a + min(int(block_size), safe))
        active = [g for g in active if g.stop > a]
        while cursor < len(plans) and plans[cursor].start < b:
            active.append(plans[cursor])
            cursor += 1
        for g in active:
            lo, hi = max(a, g.start), min(b, g.stop)
            if hi <= lo:
                continue
            samples = np.arange(lo, hi, dtype=np.float64)
            offset = g.source_center - g.rate * g.center
            pos = offset + g.rate * samples
            method = "integer" if g.rate.is_integer() and offset.is_integer() else "sinc8"
            values = read_samples(history, np.clip(pos, -8, len(history) + 8), method)
            if delay_samples is None and params.get("mode", "live") == "live":
                values[pos < samples - params["buffer_s"] * sr] = 0
            weights = grain_window((samples - g.center) / length + .5, params.get("window", "hann"))
            values *= (weights * norm * g.level)[:, None]
            if x.shape[1] == 2 and g.pan:
                angle = (g.pan + 1) * np.pi / 4
                values *= np.sqrt(2) * np.array([np.cos(angle), np.sin(angle)])
            wet[lo:hi] += values
        if feedback:
            history[a:b] = x[a:b] + feedback * loop(wet[a:b])
    stats = {"grain_count": sum(0 <= g.center < len(x) for g in plans),
             "expected_overlap": float(overlap), "normalization_gain": float(norm),
             "random_draws_per_grain": 7, "latency_samples": 0,
             "max_causal_shift_samples": max((g.causal_shift for g in plans), default=0.0),
             "feedback": feedback}
    return wet, stats
