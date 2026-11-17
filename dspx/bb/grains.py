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


def grain_window_gain(params):
    """Window calibration before the existing 1/sqrt(expected overlap).

    A coherent Hann pair needs sqrt(2) for constant-overlap reconstruction.
    Other configurations use unit mean-square windows for uncorrelated grains.
    This opt-in calibration leaves all legacy primitives unchanged.
    """
    kind = params.get("window", "hann")
    overlap = params["grain_ms"] * params["density_hz"] / 1000
    coherent = (kind == "hann" and abs(overlap - 2) < 1e-12
                and all(params.get(k, 0) == 0 for k in
                        ("spray_ms", "jitter", "pitch_semitones", "pitch_spread",
                         "reverse", "pan_spread", "level_spread_db"))
                and not any(params.get("pitch_quantize", [])))
    if coherent:
        return float(np.sqrt(2)), "coherent_cola"
    return _grain_energy_gain(kind), "window_energy"


def _grain_energy_gain(kind):
    """Mean-square integral of the existing continuous window convention."""
    if kind == "hann":
        return float(np.sqrt(8 / 3))
    if kind == "tukey":
        return float(np.sqrt(16 / 11))
    # Fixed midpoint quadrature; the 5% cosine tapers make the integrand smooth.
    u = (np.arange(32768, dtype=np.float64) + .5) / 32768
    return float(1 / np.sqrt(np.mean(grain_window(u, kind) ** 2)))


def grain_feedback_bounds(params, *, delay_ms=None, sr=None):
    """Conservative peak-gain / longest-age CT-8 envelope for the new renderer.

    Static validation rejects unsafe continuous-time combinations. Runtime
    validation also includes sample lookaround, fractional interpolation and
    the loop filter's absolute impulse sum. No filter attenuation is credited.
    The return value contains the maximum permitted *parameter* feedback.
    """
    length = params["grain_ms"] / 1000
    overlap = length * params["density_hz"]
    jitter = .49 * params["jitter"]
    count = int(np.ceil(overlap + 2 * jitter)) + 1
    if params.get("window", "hann") == "hann":
        # Partition a hop into cells. For each cell, independently move every
        # center toward it by the maximum jitter plus half a cell. This bounds
        # the continuous supremum, rather than merely sampling the sum.
        phase = (np.arange(1024) + .5) / 1024
        total = np.zeros_like(phase)
        radius = int(np.ceil(overlap / 2 + jitter)) + 1
        for k in range(-radius, radius + 2):
            distance = np.maximum(abs(phase - k) - jitter - .5 / 1024, 0)
            total += np.where(distance < overlap / 2,
                              .5 + .5 * np.cos(2 * np.pi * distance / overlap), 0)
        window_sum = min(float(np.max(total)), float(count))
        if not jitter and abs(overlap - 2) < 1e-12:
            window_sum = 1.0
    else:
        window_sum = float(count)
    gain, mode = grain_window_gain(params)
    pan = np.sqrt(1 + np.sin(params["pan_spread"] * np.pi / 2))
    gain *= window_sum / np.sqrt(overlap) * pan * 10 ** (params.get("level_spread_db", 0) / 20)
    pitches = params.get("pitch_quantize", [])
    maximum_pitch = max(pitches) if pitches else params["pitch_semitones"] + params["pitch_spread"]
    minimum_pitch = min(pitches) if pitches else params["pitch_semitones"] - params["pitch_spread"]
    rates = [2 ** (minimum_pitch / 12), 2 ** (maximum_pitch / 12)]
    if params["reverse"]:
        rates += [-v for v in rates]
    deviation = max(abs(v - 1) for v in rates)
    # Static validation has no sample rate; the runtime check closes that gap.
    lookaround = 9 / sr if sr is not None else 0
    if delay_ms is not None:
        age = max(delay_ms / 1000 + params["spray_ms"] / 1000 + deviation * length / 2,
                  deviation * length + lookaround)
    else:
        age = params["buffer_s"] + (4 / sr if sr is not None else 0)
        if mode == "coherent_cola" and params["speed"] == 1:
            age = 5 / sr if sr is not None else 0
    if sr is not None:
        # A sinc8 row has absolute sum < 2 (verified independently in tests).
        # Only the clean live head is guaranteed integral for every rate.
        integral = (mode == "coherent_cola" and
                    (delay_ms is None and params["speed"] == 1 or
                     delay_ms is not None and float(delay_ms * sr / 1000).is_integer()))
        if not integral:
            gain *= 2
        if delay_ms is not None:
            age += lookaround
    # Exponentially weighted peak norm: |A|_lambda <= G*exp(lambda*D).
    # Thus |wet(t)| <= G*exp(-lambda*(t-D)) /
    # (1-f*G*exp(lambda*D)*|filter|_lambda), for unit bounded past input.
    # Reserve the final measurement second and a 100x decay margin before
    # allocating .98 to feedback. The resulting tail bound is <= 5e-7,
    # strictly below CT-8's 1e-6. This also includes IIR memory.
    if age >= 59:
        decay, filter_gain = 0.0, float("inf")
        maximum = 0.0
    else:
        decay = np.log(1e8 * max(1.0, gain)) / (59 - age)
        filter_gain = _grain_loop_peak_bound(sr, params, decay) if sr is not None else 1.0
        maximum = min(.9, .98 * np.exp(-decay * age) / gain / filter_gain)
    return {"feedback_max": float(maximum), "loop_peak_gain_bound": float(gain),
            "history_age_bound_s": float(age), "decay_bound_per_s": float(decay),
            "weighted_filter_gain_bound": float(filter_gain)}


def _grain_loop_peak_bound(sr, params, decay):
    """Exponentially weighted absolute impulse sum, including IIR memory."""
    from scipy import signal
    from .delayline import LoopFilter

    loop = LoopFilter(sr, 1, params.get("lowcut_hz", 0), params.get("highcut_hz", 0))
    bound = 1.0
    for sos in (() if loop.sos is None else loop.sos):
        # Do not merge close conjugate poles into repeated-pole terms: those
        # have polynomial impulse factors and need a different norm formula.
        residues, poles, direct = signal.residuez(sos[:3], sos[3:], tol=0)
        radii = abs(poles) * np.exp(decay / sr)
        if np.any(radii >= 1):
            return float("inf")
        bound *= max(1.0, float(np.sum(abs(direct) * np.exp(decay / sr * np.arange(len(direct))))
                               + np.sum(abs(residues) / (1 - radii))))
    return bound


def validate_grain_feedback(params, *, delay_ms=None, sr=None):
    """Reject combinations outside the sixty-second full-scale tail bound."""
    from mankomix.dsp.errors import ParamError

    bounds = grain_feedback_bounds(params, delay_ms=delay_ms, sr=sr)
    if params["feedback"] > bounds["feedback_max"]:
        raise ParamError(f"feedback: maximum allowed feedback is {bounds['feedback_max']:.17g} "
                         "for this grain geometry (60 s / -120 dB CT-8 bound)")
    return bounds


def render_calibrated_grains(x, sr, params, *, seed=0, delay_samples=None, block_size=1024):
    """Opt-in COLA/energy calibration with feedback after calibrated output.

    Scaling the old renderer's feedback by c and its returned wet by c is
    algebraically y=c*A(x+f*y); the legacy renderer remains byte-compatible.
    """
    if sr <= 0 or block_size < 1:
        raise ValueError("positive sample rate and block size required")
    ms = None if delay_samples is None else delay_samples * 1000 / sr
    bounds = validate_grain_feedback(params, delay_ms=ms, sr=sr)
    gain, mode = grain_window_gain(params)
    adjusted = {**params, "feedback": params["feedback"] * gain}
    wet, stats = render_grains(x, sr, adjusted, seed=seed, delay_samples=delay_samples,
                               block_size=block_size)
    wet *= gain
    stats.update(bounds, feedback=params["feedback"], window_gain=gain, window_calibration=mode)
    return wet, stats
