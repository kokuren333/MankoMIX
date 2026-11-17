"""BB-09: independently derived fractional and feedback delay primitives.

API (all audio is float64, frames x channels, zero initial history):
``read_samples(x, positions, method='sinc8')``: zero-extended absolute reads;
positions are frames or frames x channels. Methods: integer, lagrange3, sinc8,
sinc256 (precision alignment; not the eight-point musical delay kernel).
``fractional_delay(x, delay_samples, method='sinc8')``: offline, same length.
``DelayLine(max_delay, channels, method='sinc8').process(x, delays,
feedback=0, loop=None, matrix=None, block_size=1024)``: persistent causal
feedback line. Delays are scalar, channel vector, or frames x channels.
``loop(block)`` processes each delayed block before feedback; it must preserve
shape and state across calls. Matrix maps delayed channels to written channels.
The returned wet signal precedes loop processing. Integer reads need >=1 sample;
fractional reads need >=2 (Lagrange) / >=4 (sinc8) / >=128 (sinc256) samples.
``LoopFilter(sr, channels, lowcut=0, highcut=0)``: persistent 12 dB/oct loop EQ.
``integer_feedback(x, delay, feedback)``: fast uncoupled integer comb.

Lagrange uses four polynomial basis weights. The sinc kernels use a continuous
Hann window, normalised for DC. No third-party code is copied.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _e, _f, _i


def _kernel(positions, method):
    base = np.floor(positions).astype(np.int64)
    frac = positions - base
    if method == "integer":
        return np.rint(positions).astype(np.int64)[..., None], np.ones(positions.shape + (1,))
    if method == "lagrange3":
        offsets = np.arange(-1, 3)
        weights = []
        for j in offsets:
            w = np.ones_like(frac)
            for k in offsets:
                if k != j:
                    w = w * ((frac - k) / (j - k))
            weights.append(w)
        weights = np.stack(weights, axis=-1)
    elif method in ("sinc8", "sinc256"):
        radius = 4 if method == "sinc8" else 128
        offsets = np.arange(1-radius, radius+1)
        distance = frac[..., None] - offsets
        weights = np.sinc(distance) * (0.5 + 0.5 * np.cos(np.pi * distance / radius))
        weights /= np.sum(weights, axis=-1, keepdims=True)
    else:
        raise ValueError("method must be integer, lagrange3, sinc8 or sinc256")
    # Exact integer reads, including signed zeros, do not traverse a sinc kernel.
    weights = np.where((frac == 0)[..., None], (offsets == 0).astype(float), weights)
    return base[..., None] + offsets, weights


def read_samples(x, positions, method="sinc8"):
    """Vectorised absolute read with zero extension outside the supplied signal."""
    x = np.asarray(x, dtype=np.float64)
    pos = np.asarray(positions, dtype=np.float64)
    if x.ndim != 2 or pos.ndim not in (1, 2) or not np.isfinite(pos).all():
        raise ValueError("expected finite positions and frames x channels audio")
    if pos.ndim == 1:
        pos = np.broadcast_to(pos[:, None], (len(pos), x.shape[1]))
    if pos.shape[1] != x.shape[1]:
        raise ValueError("position channel count differs from audio")
    indices, weights = _kernel(pos, method)
    y = np.zeros(pos.shape)
    if not len(x):
        return y
    for k in range(indices.shape[-1]):
        ix = indices[..., k]
        v = x[np.clip(ix, 0, len(x) - 1), np.arange(x.shape[1])]
        y += np.where((ix >= 0) & (ix < len(x)), v, 0) * weights[..., k]
    return y


def fractional_delay(x, delay_samples, method="sinc8"):
    """Offline zero-extended delay; centred interpolation has no added latency."""
    d = np.asarray(delay_samples, dtype=np.float64)
    if np.any(d < 0) or not np.isfinite(d).all():
        raise ValueError("delay must be finite and nonnegative")
    if d.ndim == 0 and d == 0:
        return np.asarray(x, dtype=np.float64).copy()
    if d.ndim == 0:
        # Fixed delays need one kernel, not frames*channels*taps storage.
        indices, weights = _kernel(np.array([-float(d)]), method)
        y = np.zeros_like(x, dtype=np.float64)
        for offset, weight in zip(indices[0], weights[0]):
            if weight == 0:
                continue
            a, b = max(0, -int(offset)), min(len(x), len(x)-int(offset))
            if b > a:
                y[a:b] += x[a+offset:b+offset] * weight
        return y
    positions = np.arange(len(x), dtype=np.float64)
    if d.ndim == 2 or (d.ndim == 1 and len(d) == x.shape[1]):
        positions = positions[:, None]
    return read_samples(x, positions - d, method)


class DelayLine:
    """Persistent ring buffer, with causally independent reads batched in NumPy."""

    def __init__(self, max_delay, channels, method="sinc8"):
        if not np.isfinite(max_delay) or max_delay < 1 or channels < 1:
            raise ValueError("positive capacity and channel count required")
        _kernel(np.array([0.0]), method)
        self.max_delay = float(max_delay)
        self.channels = int(channels)
        self.method = method
        self.buffer = np.zeros((int(np.ceil(max_delay)) + 16, channels))
        self.position = 0

    def process(self, x, delays, feedback=0.0, loop=None, matrix=None, block_size=1024):
        x = np.asarray(x, dtype=np.float64)
        if x.ndim != 2 or x.shape[1] != self.channels or not np.isfinite(x).all():
            raise ValueError("invalid audio shape or nonfinite input")
        if not 0 <= feedback <= 1 or block_size < 1:
            raise ValueError("feedback must be in [0,1], block_size >= 1")
        ds = np.broadcast_to(np.asarray(delays, dtype=np.float64), x.shape)
        if not np.isfinite(ds).all() or np.any(ds < 1) or np.any(ds > self.max_delay):
            raise ValueError("delay outside configured capacity")
        if self.method == "integer" and np.any(ds != np.rint(ds)):
            raise ValueError("integer method requires integer delays")
        mat = np.eye(self.channels) if matrix is None else np.asarray(matrix, dtype=float)
        if mat.shape != (self.channels, self.channels) or not np.isfinite(mat).all():
            raise ValueError("invalid feedback matrix")
        out = np.zeros_like(x)
        start = 0
        while start < len(x):
            # Determine a safe chunk using the whole candidate's earliest read.
            end = min(start + int(block_size), len(x))
            d = ds[start:end]
            reserve = {"integer": 0, "lagrange3": 2, "sinc8": 4, "sinc256": 128}[self.method]
            safe = np.ceil(d).astype(int) - np.where(d == np.floor(d), 0, reserve)
            step = int(np.min(safe))
            if step < 1:
                raise ValueError("fractional read would require future feedback samples")
            end = min(end, start + step)
            absolute = self.position + np.arange(end - start)
            indices, weights = _kernel(absolute[:, None] - ds[start:end], self.method)
            wet = np.zeros((end - start, self.channels))
            for k in range(indices.shape[-1]):
                ix = indices[..., k]
                v = self.buffer[ix % len(self.buffer), np.arange(self.channels)]
                wet += np.where(ix >= 0, v, 0) * weights[..., k]
            processed = wet if loop is None else np.asarray(loop(wet), dtype=np.float64)
            if processed.shape != wet.shape:
                raise ValueError("loop callback must preserve shape")
            routed = np.zeros_like(wet)
            for target in range(self.channels):
                for source in range(self.channels):
                    routed[:, target] += processed[:, source] * mat[target, source]
            self.buffer[absolute % len(self.buffer)] = x[start:end] + feedback * routed
            out[start:end] = wet
            self.position += end - start
            start = end
        return out


class LoopFilter:
    """Stateful unity-bounded Butterworth high/low cut in the feedback path."""

    def __init__(self, sr, channels, lowcut=0, highcut=0):
        sections = []
        for cutoff, kind in ((lowcut, "highpass"), (highcut, "lowpass")):
            if cutoff:
                if cutoff >= sr / 2:
                    if kind == "lowpass":
                        continue
                    raise ParamError("lowcut must lie below Nyquist")
                sections.append(signal.butter(2, cutoff, kind, fs=sr, output="sos"))
        self.sos = np.concatenate(sections) if sections else None
        self.zi = np.zeros((len(self.sos), 2, channels)) if sections else None

    def __call__(self, x):
        if self.sos is None or not len(x):
            return x
        y, self.zi = signal.sosfilt(self.sos, x, axis=0, zi=self.zi)
        return y


def integer_feedback(x, delay, feedback):
    """Vectorised scalar integer comb, wet[n] = x[n-D] + f*wet[n-D]."""
    d = int(delay)
    if d < 1 or d != delay or not 0 <= feedback <= 1:
        raise ValueError("positive integer delay and feedback in [0,1] required")
    n, ch = x.shape
    if not n:
        return x.copy()
    padded = np.zeros((int(np.ceil(n / d)) * d, ch))
    padded[:n] = x
    rows = padded.reshape((-1, d, ch))
    return signal.lfilter([0, 1], [1, -feedback], rows, axis=0).reshape((-1, ch))[:n]


def sd_params():
    """SD declarations, kept explicit until BB-14 provides the common block."""
    return [_f("duck_db", "dB", 0, 24, 0, "Wet attenuation while dry RMS exceeds threshold."),
            _f("duck_threshold_db", "dBFS", -80, 0, -40, "Dry RMS threshold."),
            _f("duck_attack_ms", "ms", 0.1, 200, 10, "Duck attack time."),
            _f("duck_release_ms", "ms", 5, 3000, 250, "Duck release time.")]


def dl_params():
    notes = ["none"] + [f"1/{d}{m}" for d in (1, 2, 4, 8, 16, 32, 64) for m in ("", "d", "t")]
    return [_f("time_ms", "ms", 0.1, 4000, 250, "Left delay time."),
            _e("note", notes, "none", "Tempo-synchronised duration."),
            _f("bpm", "BPM", 0, 400, 0, "Tempo; zero means unknown."),
            _f("feedback", None, 0, 0.95, 0.3, "Feedback gain."),
            _f("mix", None, 0, 1, 0.2, "Wet proportion."),
            _f("lowcut_hz", "Hz", 0, 2000, 0, "12 dB/oct feedback highpass; zero bypasses."),
            _f("highcut_hz", "Hz", 0, 24000, 0, "12 dB/oct feedback lowpass; zero bypasses."),
            _i("seed", None, 0, 65535, 0, "Deterministic seed.")] + sd_params()


def delay_ms(p):
    if 0 < p["bpm"] < 20:
        raise ParamError("bpm must be zero or at least 20")
    if p.get("note", "none") == "none":
        return p.get("time_ms")
    if not p["bpm"]:
        raise ParamError("note requires bpm > 0")
    from mankomix.dsp.processors import note_ms
    ms = note_ms(p["note"], p["bpm"])
    if ms > 4000:
        raise ParamError("note duration exceeds 4000 ms")
    return ms


def feedback_limit(delay_ms, output_gain=1.0):
    """Conservative CT-8 bound, without credit for loop-filter attenuation.

    Reserve the initial delay and the harness's final one-second window.
    For |input| <= 1, bound the stored state by 1/(1-f) and the output by
    output_gain*f**N/(1-f), N=floor(59000/delay_ms)-1. Use the longest
    individual line for crossed feedback, and the last tap for multitap.
    A small strict margin keeps the bound below 1e-6, not equal to it.
    """
    repeats = max(1, int(np.floor(59000.0 / delay_ms)) - 1)
    low, high = 0.0, 0.95
    threshold = 1e-6 * (1 - 1e-9)
    if output_gain * high ** repeats / (1 - high) <= threshold:
        return high
    for _ in range(64):
        candidate = (low + high) / 2
        if output_gain * candidate ** repeats / (1 - candidate) <= threshold:
            low = candidate
        else:
            high = candidate
    return low


def validate_feedback(p, delay_ms, output_gain=1.0):
    """Reject feedback/time combinations that cannot meet the CT-8 bound."""
    maximum = feedback_limit(delay_ms, output_gain)
    if abs(p["feedback"]) > maximum:
        raise ParamError(f"feedback: maximum allowed feedback is {maximum:.17g} "
                         f"for delay {delay_ms:.17g} ms (60 s / -120 dB CT-8 bound)")


def duck_wet(dry, wet, sr, p):
    """Self RMS duck with piecewise constant targets and exponential smoothing."""
    if not p["duck_db"] or not len(dry):
        return wet
    size = max(1, round(0.01 * sr))
    power = np.mean(dry * dry, axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(power)))
    ix = np.arange(len(dry))
    rms2 = (cumulative[ix + 1] - cumulative[np.maximum(ix + 1 - size, 0)]) / size
    active = rms2 > 10 ** (p["duck_threshold_db"] / 10)
    cuts = np.r_[0, np.flatnonzero(active[1:] != active[:-1]) + 1, len(dry)]
    gain = np.empty(len(dry))
    state = 0.0
    for a, b in zip(cuts, cuts[1:]):
        target = p["duck_db"] if active[a] else 0.0
        tau = p["duck_attack_ms"] if active[a] else p["duck_release_ms"]
        coef = np.exp(-1 / (tau * 0.001 * sr))
        values, _ = signal.lfilter([1 - coef], [1, -coef], np.full(b - a, target), zi=[coef * state])
        gain[a:b] = values
        state = values[-1]
    return wet * (10 ** (-gain / 20))[:, None]


def spatial_stats(x, sr, delay=None):
    """R-10 measurements only; no quality threshold or warning is introduced."""
    stats = {"latency_samples": 0}
    if delay is not None:
        from mankomix.dsp.reference.space import haas_region
        stats["haas"] = {**haas_region(delay), "within_1_35_ms": 1 <= delay <= 35}
        stats["first_notch_hz"] = 1000 / (2 * delay) if delay else None
    if x.shape[1] != 2:
        return stats
    from mankomix.dsp.reference.space import mono_fold
    stats["mono"] = mono_fold(x[:, 0], x[:, 1])
    energies = np.sum(x * x, axis=0)
    stats["level_difference_db"] = float(10 * np.log10(energies[1] / energies[0])) if np.all(energies > 0) else None
    # Rectangular FFT, disjoint 1/3 octave bins; ratios need no FFT scaling.
    n = len(x)
    if n:
        from scipy.fft import rfft, rfftfreq
        spectrum = rfft(x, axis=0, workers=1)
        frequencies = rfftfreq(n, 1 / sr)
        worst, worst_hz = None, None
        for center in 1000 * 2.0 ** (np.arange(-17, 14) / 3):
            mask = (frequencies >= center / 2 ** (1 / 6)) & (frequencies < center * 2 ** (1 / 6))
            band = spectrum[mask]
            den = float(np.sum(np.abs(band) ** 2) / 2)
            num = float(np.sum(np.abs((band[:, 0] + band[:, 1]) / 2) ** 2))
            if den > 0:
                loss = float(10 * np.log10(max(num / den, 1e-300)))
                if worst is None or loss < worst:
                    worst, worst_hz = loss, float(center)
        stats["mono_worst_third_octave_db"] = worst
        stats["mono_worst_third_octave_hz"] = worst_hz
    return stats


def definition(kind, params, *, implemented=True, master=False, channel=False, latency_rule=None):
    rt = {"block_ok": True, "latency_samples": 0, "allocates": True}
    if latency_rule:
        rt["latency_rule"] = latency_rule
    return {"type": kind, "implemented": implemented, "description": kind.replace("_", " "),
            "params": params, "stages": ["track", "bus"] + (["master"] if master else []),
            "master_slot": 4 if master else None, "realtime": rt, "offline_only": False,
            "backends": ["reference"], "channel_ok": channel}
