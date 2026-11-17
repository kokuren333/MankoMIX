"""BB-01: deterministic synthetic fixtures and measurements, never pytest-collected.

Arrays are float64 (frames, channels); levels use amplitude-reference dBFS
(a full-scale sine has RMS -3.0103 dBFS). Exact zero is -inf, never a floor.
No audio is written. Basic tones reuse tests.fixtures.synth; random sources
explicitly use numpy.random.PCG64. Measurements are independent of processor
statistics and gain-computer functions.

Echo density follows Abel & Huang, AES 121 (2006), paper 6985:
https://aes.org/publications/elibrary/elibrary-page/?id=13819
This is an original rectangular-window implementation of the published
Gaussian exceedance definition, not a port of third-party source code.
"""

from __future__ import annotations

import math
import numpy as np
from scipy import ndimage, signal

from mankomix.dsp import engine, processors as P
from mankomix.dsp.errors import ParamError
from tests.fixtures import synth as _synth


def audio(x):
    """Validate finite nonempty audio and return its 2-D float64 view."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if x.ndim != 2 or min(x.shape) < 1 or not np.isfinite(x).all():
        raise ValueError("expected finite nonempty (frames, channels) audio")
    return x


def db(value):
    """Amplitude to dB, preserving digital zero as negative infinity."""
    value = float(value)
    if value < 0 or not math.isfinite(value):
        raise ValueError("amplitude must be finite and nonnegative")
    return 20 * math.log10(value) if value else -math.inf


def rms(x):
    return float(np.sqrt(np.mean(audio(x) ** 2)))


def rms_dbfs(x):
    return db(rms(x))


def peak_dbfs(x):
    return db(np.max(np.abs(audio(x))))


def _layout(sr, seconds, channels):
    if int(sr) != sr or sr <= 0 or int(channels) != channels or channels < 1:
        raise ValueError("sr and channels must be positive integers")
    n = round(sr * seconds)
    if n < 1:
        raise ValueError("duration must contain at least one sample")
    return n, int(channels)


def _repeat(x, channels):
    return np.repeat(np.asarray(x, dtype=np.float64)[:, None], channels, axis=1)


def sine(freq=1000.0, dbfs=-20.0, phase=0.0, *, sr=48000, seconds=1.0,
         channels=1, seed=0):
    """Peak-calibrated sinusoid; seed is accepted for a uniform fixture API."""
    _layout(sr, seconds, channels)
    if not 0 < freq < sr / 2:
        raise ValueError("frequency must be below Nyquist")
    return _synth.sine(freq, dbfs, phase, sr=sr, seconds=seconds, channels=channels)


def sweep(f0=20.0, f1=20000.0, dbfs=-20.0, *, sr=48000, seconds=2.0,
          channels=1, seed=0):
    """Logarithmic swept sine, peak-calibrated."""
    _layout(sr, seconds, channels)
    if not 0 < min(f0, f1) <= max(f0, f1) < sr / 2:
        raise ValueError("sweep frequencies must be below Nyquist")
    return _synth.sweep(f0, f1, dbfs, sr=sr, seconds=seconds, channels=channels)


def white_noise(dbfs=-20.0, *, sr=48000, seconds=1.0, channels=1, seed=0):
    """Independent Gaussian channels, each normalised to the requested RMS."""
    n, ch = _layout(sr, seconds, channels)
    x = np.random.Generator(np.random.PCG64(seed)).standard_normal((n, ch))
    return x * (10 ** (dbfs / 20) / np.sqrt(np.mean(x * x, axis=0)))


def pink_noise(dbfs=-20.0, *, sr=48000, seconds=1.0, channels=1, seed=0,
               fmin=10.0):
    """FFT-shaped 1/f power noise, no DC, exact RMS per channel."""
    x = white_noise(0, sr=sr, seconds=seconds, channels=channels, seed=seed)
    f = np.fft.rfftfreq(len(x), 1 / sr)
    shape = np.zeros_like(f)
    mask = f >= max(fmin, np.finfo(float).eps)
    shape[mask] = f[mask] ** -0.5
    y = np.fft.irfft(np.fft.rfft(x, axis=0) * shape[:, None], n=len(x), axis=0)
    norm = np.sqrt(np.mean(y * y, axis=0))
    if np.any(norm == 0):
        raise ValueError("duration/fmin leave no pink-noise bins")
    return y * (10 ** (dbfs / 20) / norm)


def impulse(at_s=0.0, dbfs=0.0, *, sr=48000, seconds=1.0, channels=1, seed=0):
    _layout(sr, seconds, channels)
    return _synth.impulse(at_s, dbfs, sr=sr, seconds=seconds, channels=channels)


def tone_burst(freq=1000.0, dbfs=-12.0, *, rise_ms=10.0, decay_ms=300.0,
               start_s=0.0, sr=48000, seconds=0.5, channels=1, seed=0):
    """Linear rise to peak followed by exponential decay (decay_ms is tau)."""
    if rise_ms < 0 or decay_ms <= 0 or start_s < 0:
        raise ValueError("invalid burst envelope")
    x = sine(freq, dbfs, sr=sr, seconds=seconds, channels=channels)
    t = np.arange(len(x)) / sr - start_s
    rise = rise_ms / 1000
    env = np.where(t >= rise, np.exp(-np.maximum(t - rise, 0) / (decay_ms / 1000)),
                   np.clip(t / max(rise, 1 / sr), 0, 1))
    env[t < 0] = 0
    return x * env[:, None]


def level_steps(levels_dbfs=(-48, -6, -48), durations_s=0.5, *, carrier="square",
                freq=1000.0, sr=48000, channels=1, seed=0):
    """Level staircase. Square has constant absolute value, ideal for GR probes.

    Sine levels specify peak; square/constant levels specify both RMS and peak.
    Each boundary is rounded independently on the cumulative time grid.
    """
    levels = np.asarray(levels_dbfs, dtype=float)
    durations = np.broadcast_to(durations_s, levels.shape)
    if levels.ndim != 1 or not len(levels) or np.any(durations <= 0):
        raise ValueError("levels and positive durations must have equal lengths")
    edges = np.rint(np.r_[0, np.cumsum(durations)] * sr).astype(int)
    _layout(sr, float(np.sum(durations)), channels)
    if np.any(np.diff(edges) < 1):
        raise ValueError("every step must contain samples")
    amp = np.repeat(10 ** (levels / 20), np.diff(edges))
    k = np.arange(len(amp))
    if carrier == "square":
        wave = 1.0 - 2.0 * (k % 2)
    elif carrier == "constant":
        wave = np.ones(len(k))
    elif carrier == "sine":
        if not 0 < freq < sr / 2:
            raise ValueError("frequency must be below Nyquist")
        wave = np.cos(2 * np.pi * freq * k / sr)
    else:
        raise ValueError("carrier must be square, constant or sine")
    return _repeat(amp * wave, channels)


def two_tone(low_hz=60.0, high_hz=7000.0, dbfs=-6.0, amplitude_ratio=4.0, *,
             sr=48000, seconds=1.0, channels=1, seed=0):
    """SMPTE tones (60/7000 Hz, 4:1); sum of peak amplitudes equals dbfs."""
    if amplitude_ratio <= 0:
        raise ValueError("amplitude_ratio must be positive")
    lo = sine(low_hz, 0, sr=sr, seconds=seconds, channels=channels)
    hi = sine(high_hz, 0, sr=sr, seconds=seconds, channels=channels)
    return (amplitude_ratio * lo + hi) * 10 ** (dbfs / 20) / (1 + amplitude_ratio)


def drum(kind="kick", dbfs=-6.0, *, sr=48000, seconds=0.5, channels=1, seed=0):
    """Synthetic one-shot kick, snare or hat; peak-calibrated, zero initial state."""
    n, ch = _layout(sr, seconds, channels)
    t = np.arange(n) / sr
    noise = np.random.Generator(np.random.PCG64(seed)).standard_normal(n)
    if kind == "kick":
        phase = 2 * np.pi * (55 * t + 105 * 0.025 * (1 - np.exp(-t / 0.025)))
        x = np.sin(phase) * np.exp(-t / 0.12) + 0.03 * noise * np.exp(-t / 0.001)
    elif kind in ("snare", "hat"):
        cutoff = min(1000 if kind == "snare" else 7000, 0.35 * sr)
        hiss = signal.sosfilt(signal.butter(4, cutoff, "highpass", fs=sr, output="sos"), noise)
        x = hiss * np.exp(-t / (0.07 if kind == "snare" else 0.018))
        if kind == "snare":
            x += 0.5 * np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05)
    else:
        raise ValueError("kind must be kick, snare or hat")
    return _repeat(x * (10 ** (dbfs / 20) / np.max(np.abs(x))), ch)


def kick_train(bpm=120.0, dbfs=-6.0, *, sr=48000, seconds=2.0, channels=1,
               seed=0, beats=None):
    """Kick sequence at beat positions (default every quarter note)."""
    n, ch = _layout(sr, seconds, channels)
    if bpm <= 0:
        raise ValueError("bpm must be positive")
    if beats is None:
        beats = np.arange(math.ceil(seconds * bpm / 60))
    out = np.zeros((n, ch))
    for i, beat in enumerate(beats):
        at = round(float(beat) * 60 / bpm * sr)
        if at < 0:
            raise ValueError("negative beat position")
        if at < n:
            hit = drum("kick", dbfs, sr=sr, seconds=0.5, channels=ch, seed=[seed, i])
            count = min(len(hit), n - at)
            out[at:at + count] += hit[:count]
    return out


def glottal_source(f0=100.0, *, sr=48000, seconds=1.0, channels=1, seed=0):
    """Fractional-sample pulse train with a causal glottal low-pass pulse shape.

    f0 accepts Hz, a callable of sample times, one Hz value per sample, or
    (seconds, Hz) control-point pairs (linear interpolation, held endpoints).
    """
    n, ch = _layout(sr, seconds, channels)
    t = np.arange(n) / sr
    values = np.asarray(f0(t) if callable(f0) else f0, dtype=float)
    if values.ndim == 2 and values.shape[1] == 2:
        if len(values) < 2 or np.any(np.diff(values[:, 0]) <= 0):
            raise ValueError("f0 control-point times must increase")
        values = np.interp(t, values[:, 0], values[:, 1])
    hz = np.broadcast_to(values, (n,))
    if not np.isfinite(hz).all() or np.any(hz <= 0) or np.any(hz >= sr / 2):
        raise ValueError("f0 must be positive and below Nyquist")
    cycles = np.r_[0.0, np.cumsum(hz[:-1]) / sr]
    crossing = np.flatnonzero(np.diff(np.floor(cycles)) > 0) + 1
    pulses = np.zeros(n)
    pulses[0] = 1
    # Deposit a crossing between adjacent samples rather than quantising its time.
    frac = (np.ceil(cycles[crossing - 1]) - cycles[crossing - 1]) / (hz[crossing - 1] / sr)
    # At an exactly integral previous phase, the next crossing is one cycle later.
    frac = np.where(frac <= 0, 1.0, frac)
    np.add.at(pulses, crossing - 1, 1 - frac)
    np.add.at(pulses, crossing, frac)
    a = math.exp(-2 * math.pi * min(1500, 0.2 * sr) / sr)
    return _repeat(signal.lfilter([1 - a], [1, -a], pulses), ch)


def formant_sos(formants_hz=(700, 1200, 2500), bandwidths_hz=70.0, *, sr=48000):
    """Three to five stable all-pole resonators; pole angles encode formants."""
    f = np.asarray(formants_hz, dtype=float)
    bw = np.broadcast_to(bandwidths_hz, f.shape)
    if f.ndim != 1 or not 3 <= len(f) <= 5 or np.any(f <= 0) or np.any(f >= sr / 2):
        raise ValueError("supply three to five formants below Nyquist")
    if np.any(bw <= 0) or not np.isfinite(f).all() or not np.isfinite(bw).all():
        raise ValueError("formants and bandwidths must be finite and positive")
    r = np.exp(-np.pi * bw / sr)
    return np.column_stack([1 - r, np.zeros_like(r), np.zeros_like(r), np.ones_like(r),
                            -2 * r * np.cos(2 * np.pi * f / sr), r * r])


def vowel(f0=100.0, formants_hz=(700, 1200, 2500), dbfs=-12.0, *,
          bandwidths_hz=70.0, sr=48000, seconds=1.0, channels=1, seed=0):
    """Glottal pulses through 3-5 formants, normalised to the requested peak."""
    source = glottal_source(f0, sr=sr, seconds=seconds, channels=channels, seed=seed)
    y = signal.sosfilt(formant_sos(formants_hz, bandwidths_hz, sr=sr), source, axis=0)
    return y * (10 ** (dbfs / 20) / np.max(np.abs(y)))


def render(ptype, x, sr, params=None, *, stage="bus", seed=0):
    """All processor measurements enter through the public reference engine."""
    return engine.render_chain(x, sr, [{"id": "harness", "type": ptype,
                                       "params": dict(params or {})}], stage=stage, seed=seed)


def render_excerpt(ptype, x, sr, start, stop, params=None, *, stage="bus", seed=0):
    """Independent offline excerpt: replay full context from zero, then crop.

    Whole-context replay also supports noncausal/offline processors. Passing
    x[start:stop] would reset state and change the processor's time origin.
    This checks the supported offline contract, not a streaming-state API.
    """
    if not 0 <= start < stop <= len(x):
        raise ValueError("invalid excerpt bounds")
    result = render(ptype, x, sr, params, stage=stage, seed=seed)
    if result.sr != sr:
        raise ValueError("excerpt sample indices require unchanged sample rate")
    return result.audio[start:stop]


def static_characteristic(ptype, levels_dbfs, *, params=None, sr=48000, channels=1,
                          settle_s=0.5, measure_s=0.1, carrier="square", freq=1000.0,
                          stage="bus", seed=0):
    """Independent level sweep -> steady RMS input/output/positive GR table.

    Include sufficient settling for the processor. Square/constant have no
    detector ripple; sine input levels are peak values, table values are RMS.
    Makeup is included in net GR (negative GR means net amplification).
    """
    rows = []
    for level in levels_dbfs:
        x = level_steps([level], settle_s + measure_s, carrier=carrier, freq=freq,
                        sr=sr, channels=channels)
        y = render(ptype, x, sr, params, stage=stage, seed=seed).audio
        count = max(1, round(measure_s * sr))
        inp, out = rms_dbfs(x[-count:]), rms_dbfs(y[-count:])
        rows.append({"input_dbfs": inp, "output_dbfs": out, "gr_db": inp - out})
    return rows


def step_response_time(trace, sr, start, initial, final, *, method="63"):
    """Interpolated step crossing in either direction; start is first new sample.

    The pre-step value is at t=0, trace[start] at t=1/sr. '63' measures
    1-exp(-1). '10-90' returns the rise/fall interval and its one-pole
    equivalent tau=interval/log(9). Units are seconds, not milliseconds.
    Missing crossings and zero-sized steps raise ValueError.
    """
    a = np.asarray(trace, dtype=float).reshape(-1)
    if method not in ("63", "10-90") or final == initial or not 0 <= start < len(a):
        raise ValueError("invalid step measurement")
    progress = np.r_[0.0, (a[start:] - initial) / (final - initial)]

    def cross(q):
        hits = np.flatnonzero(progress >= q)
        if not len(hits):
            raise ValueError(f"step never reaches {q}")
        i = int(hits[0])
        return (i - 1 + (q - progress[i - 1]) / (progress[i] - progress[i - 1])) / sr

    duration = cross(1 - math.exp(-1)) if method == "63" else cross(0.9) - cross(0.1)
    return {"method": method, "time_s": float(duration),
            "tau_s": float(duration if method == "63" else duration / math.log(9))}


def dynamics_times(ptype="compressor", *, params=None, sr=48000, channels=1,
                   low_dbfs=-48, high_dbfs=-6, method="63", stage="bus"):
    """Measure dB gain ballistics from a constant-magnitude low/high/low step.

    Segment lengths are >=12 declared attack/release time constants. The
    last 1% of each segment supplies the measured steady asymptote. This is
    for multiplicative dynamics without a separate audio delay/filter path.
    Select a peak detector to isolate gain ballistics: an RMS detector adds
    its own moving-window response, which is included in this measurement.
    """
    p = P.validate_params(ptype, params)
    pre = max(0.05, 12 * p["release_ms"] / 1000)
    high = max(0.05, 12 * p["attack_ms"] / 1000)
    tail = max(0.05, 12 * p["release_ms"] / 1000)
    edges = np.rint(np.cumsum([pre, high, tail]) * sr).astype(int)
    x = level_steps([low_dbfs, high_dbfs, low_dbfs], [pre, high, tail], sr=sr, channels=channels)
    y = render(ptype, x, sr, p, stage=stage).audio
    gr = -20 * np.log10(np.maximum(np.abs(y[:, 0] / x[:, 0]), np.finfo(float).tiny))
    a, b, c = edges
    baseline = float(np.mean(gr[max(0, a - max(1, a // 100)):a]))
    plateau = float(np.mean(gr[b - max(1, (b - a) // 100):b]))
    released = float(np.mean(gr[c - max(1, (c - b) // 100):c]))
    attack = step_response_time(gr[:b], sr, a, baseline, plateau, method=method)
    release = step_response_time(gr, sr, b, float(gr[b - 1]), released, method=method)
    return {"attack": attack, "release": release, "steady_gr_db": plateau}


def null(a, b):
    """Unaligned difference RMS/peak in linear units and dBFS; shapes must match."""
    a, b = audio(a), audio(b)
    if a.shape != b.shape:
        raise ValueError("null inputs must have identical shapes")
    d = a - b
    r, p = rms(d), float(np.max(np.abs(d)))
    return {"rms": r, "peak": p, "rms_dbfs": db(r), "peak_dbfs": db(p),
            "bit_identical": a.tobytes() == b.tobytes()}


def latency(x, reference=None, *, method="impulse", max_lag=None):
    """Integer latency; positive means x lags reference. No fractional alignment.

    Impulse mode returns the largest absolute sample index. Correlation sums
    per-channel correlations (so antiphase stereo does not cancel). Undefined
    silence raises ValueError; equal-magnitude ties prefer the smallest lag.
    """
    x = audio(x)
    if not np.any(x):
        raise ValueError("latency is undefined for silence")
    if method == "impulse":
        return int(np.argmax(np.max(np.abs(x), axis=1)))
    if method != "correlation" or reference is None:
        raise ValueError("correlation needs reference audio")
    ref = audio(reference)
    if ref.shape[1] != x.shape[1] or not np.any(ref):
        raise ValueError("correlation needs nonzero matching channels")
    corr = sum(signal.correlate(x[:, c], ref[:, c], mode="full", method="fft")
               for c in range(x.shape[1]))
    lags = signal.correlation_lags(len(x), len(ref))
    mask = np.ones(len(lags), dtype=bool) if max_lag is None else np.abs(lags) <= max_lag
    if not np.any(mask):
        raise ValueError("empty lag search")
    return int(lags[mask][np.argmax(np.abs(corr[mask]))])


def compensated_null(reference, x, *, max_lag=None):
    """Estimate integer delay, null overlapping samples, report discarded edges.

    Padding is excluded, never used to improve the residual silently. Polarity
    is not corrected. Large shifts can leave short overlap; see overlap_frames.
    """
    ref, x = audio(reference), audio(x)
    lag = latency(x, ref, method="correlation", max_lag=max_lag)
    r0, x0 = max(0, -lag), max(0, lag)
    count = min(len(ref) - r0, len(x) - x0)
    result = null(ref[r0:r0 + count], x[x0:x0 + count])
    return {**result, "latency_samples": lag, "overlap_frames": count,
            "reference_discarded": len(ref) - count, "output_discarded": len(x) - count}


def _tone_fit(x, sr, frequencies):
    x = audio(x)
    f = np.asarray(frequencies, dtype=float)
    if np.any(f <= 0) or np.any(f >= sr / 2) or len(np.unique(f)) != len(f):
        raise ValueError("fit frequencies must be distinct and below Nyquist")
    phase = 2 * np.pi * np.arange(len(x))[:, None] * f[None, :] / sr
    basis = np.column_stack([np.ones(len(x)), np.cos(phase), np.sin(phase)])
    coefs, _, rank, _ = np.linalg.lstsq(basis, x, rcond=None)
    if rank != basis.shape[1]:
        raise ValueError("signal too short for an identifiable tone fit")
    amps = np.sqrt(coefs[1:1 + len(f)] ** 2 + coefs[1 + len(f):] ** 2)
    return amps, basis, coefs


def thd(x, sr, fundamental_hz, *, max_order=10):
    """Least-squares harmonic amplitudes through max_order, below Nyquist.

    THD is sqrt(sum harmonic powers)/fundamental. THD+N is the RMS of the
    residual after DC and fundamental removal divided by fundamental RMS,
    over the entire available bandwidth. No window or spectral-bin leakage.
    Multi-channel powers are pooled; supply a steady segment without transients.
    """
    if max_order < 2:
        raise ValueError("max_order must be at least two")
    orders = np.arange(1, max_order + 1)
    orders = orders[orders * fundamental_hz < sr / 2]
    if len(orders) < 2:
        raise ValueError("no harmonic below Nyquist")
    amps, basis, coefs = _tone_fit(x, sr, orders * fundamental_hz)
    fundamental_power = float(np.mean(amps[0] ** 2) / 2)
    if fundamental_power <= np.finfo(float).tiny:
        raise ValueError("fundamental has zero power")
    m = len(orders)
    fundamental = basis[:, [0, 1, m + 1]] @ coefs[[0, 1, m + 1]]
    ratio = float(np.sqrt(np.sum(np.mean(amps[1:] ** 2, axis=1)) / (2 * fundamental_power)))
    noise_ratio = rms(audio(x) - fundamental) / math.sqrt(fundamental_power)
    return {"thd_ratio": ratio, "thd_db": db(ratio), "thdn_ratio": noise_ratio,
            "thdn_db": db(noise_ratio), "orders": orders.tolist(),
            "harmonic_peak_amplitudes": np.sqrt(np.mean(amps ** 2, axis=1)).tolist()}


def imd_smpte(x, sr, *, low_hz=60.0, high_hz=7000.0, sideband_orders=4):
    """SMPTE-style IMD: RSS of high-tone +/- n*low sidebands / high tone.

    Default stimulus is 4:1 peak amplitudes. This reports the explicit
    sideband convention, without a hardware analyser's weighting filter.
    """
    if sideband_orders < 1 or high_hz <= low_hz * sideband_orders:
        raise ValueError("invalid SMPTE sideband range")
    sidebands = [high_hz + sign * k * low_hz for k in range(1, sideband_orders + 1)
                 for sign in (-1, 1) if high_hz + sign * k * low_hz < sr / 2]
    amps, _, _ = _tone_fit(x, sr, [low_hz, high_hz, *sidebands])
    denominator = float(np.sum(amps[1] ** 2))
    if denominator <= np.finfo(float).tiny:
        raise ValueError("high tone has zero power")
    ratio = float(np.sqrt(np.sum(amps[2:] ** 2) / denominator))
    return {"imd_ratio": ratio, "imd_db": db(ratio), "sidebands_hz": sidebands}


def rms_envelope(x, sr, *, window_ms=10.0, hop_ms=None):
    """Causal trailing RMS per channel; initial window is zero-padded.

    Full-rate output by default; hop_ms subsamples at indices 0, hop, 2*hop.
    """
    x = audio(x)
    w = max(1, round(window_ms * sr / 1000))
    if window_ms <= 0 or (hop_ms is not None and hop_ms <= 0):
        raise ValueError("window and hop must be positive")
    power = ndimage.uniform_filter1d(x * x, size=w, axis=0, mode="constant", origin=(w - 1) // 2)
    return np.sqrt(np.maximum(power, 0))[::1 if hop_ms is None else max(1, round(hop_ms * sr / 1000))]


def band_level(x, sr, lo_hz, hi_hz):
    """Rectangular FFT-bin band RMS, Parseval calibrated including DC/Nyquist.

    Range is [lo, hi), except Nyquist is included when hi=sr/2. For short or
    nonperiodic signals choose a long segment to control edge leakage.
    """
    x = audio(x)
    if not 0 <= lo_hz < hi_hz <= sr / 2:
        raise ValueError("band must lie inside [0, Nyquist]")
    f = np.fft.rfftfreq(len(x), 1 / sr)
    keep = (f >= lo_hz) & ((f < hi_hz) | ((hi_hz == sr / 2) & (f == hi_hz)))
    weights = np.full(len(f), 2.0)
    weights[0] = 1
    if len(x) % 2 == 0:
        weights[-1] = 1
    power = np.abs(np.fft.rfft(x, axis=0)) ** 2
    level = math.sqrt(float(np.sum(power[keep] * weights[keep, None]) / (len(x) ** 2 * x.shape[1])))
    return {"rms": level, "dbfs": db(level), "bins": int(np.sum(keep))}


def edc(ir):
    """Schroeder reverse energy integral, pooled channels, dB relative to total.

    Silence returns all -inf. No noise-floor subtraction or tail correction.
    """
    h = audio(ir)
    energy = np.cumsum(np.mean(h * h, axis=1)[::-1])[::-1]
    if energy[0] == 0:
        return np.full(len(h), -np.inf)
    with np.errstate(divide="ignore"):
        return 10 * np.log10(energy / energy[0])


def _octave_filter(ir, sr, center_hz):
    lo, hi = center_hz / math.sqrt(2), min(center_hz * math.sqrt(2), 0.49 * sr)
    if not 0 < lo < hi:
        raise ValueError("octave band is outside Nyquist")
    return signal.sosfilt(signal.butter(4, [lo, hi], "bandpass", fs=sr, output="sos"), audio(ir), axis=0)


def decay_fit(ir, sr, *, method="T20", band_hz=None):
    """EDC line fit: T20 -5..-25, T30 -5..-35, EDT 0..-10 dB.

    Returns extrapolated 60 dB decay and R-squared; None when the recorded
    decay does not span the fit interval or is not decreasing. Filter is a
    causal fourth-order Butterworth octave (same convention as existing tests).
    """
    ranges = {"T20": (-5, -25), "T30": (-5, -35), "EDT": (0, -10)}
    top, bottom = ranges[method.upper()]
    curve = edc(ir if band_hz is None else _octave_filter(ir, sr, band_hz))
    lower = np.flatnonzero(curve <= bottom)
    upper = np.flatnonzero(curve <= top)
    if not len(lower) or not len(upper) or lower[0] <= upper[0] + 2:
        return None
    indices = np.arange(upper[0], lower[0])
    values = curve[indices]
    if not np.isfinite(values).all():
        return None
    slope, intercept = np.polyfit(indices / sr, values, 1)
    if slope >= 0:
        return None
    residual = values - (slope * indices / sr + intercept)
    total = float(np.sum((values - np.mean(values)) ** 2))
    return {"rt60_s": float(-60 / slope), "slope_db_per_s": float(slope),
            "r_squared": float(1 - np.sum(residual ** 2) / total) if total else 1.0,
            "fit_db": [top, bottom], "fit_samples": [int(indices[0]), int(lower[0])]}


def rt60(ir, sr, *, method="T20", band_hz=None):
    fit = decay_fit(ir, sr, method=method, band_hz=band_hz)
    return None if fit is None else fit["rt60_s"]


def edt(ir, sr, *, band_hz=None):
    """Early decay time, extrapolated from 0..-10 dB to 60 dB, seconds."""
    return rt60(ir, sr, method="EDT", band_hz=band_hz)


def octave_rt60(ir, sr, *, centers_hz=(125, 250, 500, 1000, 2000, 4000, 8000), method="T20"):
    return {float(f): rt60(ir, sr, method=method, band_hz=f) for f in centers_hz if f * math.sqrt(2) < sr / 2}


def echo_density(ir, sr, *, window_ms=20.0, hop_ms=1.0):
    """Abel-Huang normalised echo density, one column per channel, no clipping.

    Each complete rectangular window counts |h| > sqrt(mean(h**2)), assuming
    zero-mean IR, divided by erfc(1/sqrt(2)). Gaussian tails approach 1 and
    can exceed 1; silence is 0. Only complete windows are returned, with their
    center times. The threshold is recomputed for every window, not sample.
    """
    h = audio(ir)
    if window_ms <= 0 or hop_ms <= 0:
        raise ValueError("window and hop must be positive")
    w, hop = max(1, round(window_ms * sr / 1000)), max(1, round(hop_ms * sr / 1000))
    starts = range(0, len(h) - w + 1, hop)
    rows, times = [], []
    for start in starts:
        part = h[start:start + w]
        sigma = np.sqrt(np.mean(part * part, axis=0))
        rows.append(np.mean(np.abs(part) > sigma, axis=0) / math.erfc(1 / math.sqrt(2)))
        times.append((start + (w - 1) / 2) / sr)
    return {"times_s": np.asarray(times), "density": np.asarray(rows).reshape(-1, h.shape[1])}


def late_correlation(ir, sr, *, start_s=0.1, end_s=None):
    """Zero-lag Pearson L/R correlation on an explicitly selected late tail.

    Undefined mono, empty or zero-variance tails return None, never zero.
    """
    h = audio(ir)
    if h.shape[1] != 2:
        return None
    tail = h[round(start_s * sr):None if end_s is None else round(end_s * sr)]
    if len(tail) < 2 or np.any(np.std(tail, axis=0) == 0):
        return None
    return float(np.corrcoef(tail.T)[0, 1])


def ringing_spectrum(ir, sr, *, start_s=0.1, end_s=None, lo_hz=125, hi_hz=8000):
    """RT6: mean FFT power in contiguous 1/3-octave bands of the late tail.

    Bandwidth-normalised power (rather than integrated energy) avoids the
    +1 dB/band slope of white noise. Returns adjacent absolute dB differences.
    All-zero adjacent bands differ by zero; a zero/nonzero pair is infinite.
    Restrict the range to the intended wet passband when testing cut filters.
    """
    h = audio(ir)[round(start_s * sr):None if end_s is None else round(end_s * sr)]
    h = audio(h)
    if not 0 < lo_hz < hi_hz <= sr / 2:
        raise ValueError("invalid spectral range")
    f = np.fft.rfftfreq(len(h), 1 / sr)
    power = np.mean(np.abs(np.fft.rfft(h, axis=0)) ** 2, axis=1) / len(h) ** 2
    centers, levels = [], []
    center = float(lo_hz)
    while center <= hi_hz * (1 + 1e-12):
        keep = (f >= center / 2 ** (1 / 6)) & (f < center * 2 ** (1 / 6))
        if np.any(keep):
            centers.append(center)
            p = float(np.mean(power[keep]))
            levels.append(10 * math.log10(p) if p else -math.inf)
        center *= 2 ** (1 / 3)
    differences = [0.0 if a == b else abs(a - b) for a, b in zip(levels, levels[1:])]
    return {"centers_hz": centers, "power_db": levels, "adjacent_db": differences,
            "max_adjacent_db": max(differences, default=math.nan)}


def fundamental_frequency(x, sr, *, low_hz=50, high_hz=2000):
    """Hann FFT peak with log-parabolic interpolation, for isolated steady tones."""
    h = audio(x)[:, 0]
    spec = np.abs(np.fft.rfft((h - np.mean(h)) * np.hanning(len(h))))
    f = np.fft.rfftfreq(len(h), 1 / sr)
    bins = np.flatnonzero((f >= low_hz) & (f <= high_hz))
    if not len(bins) or not np.any(spec[bins]):
        raise ValueError("no measurable tone in search range")
    k = int(bins[np.argmax(spec[bins])])
    shift = 0.0
    if 0 < k < len(spec) - 1:
        a, b, c = np.log(np.maximum(spec[k - 1:k + 2], np.finfo(float).tiny))
        denominator = a - 2 * b + c
        if denominator:
            shift = float(np.clip(0.5 * (a - c) / denominator, -0.5, 0.5))
    return (k + shift) * sr / len(h)


def _invalid_cases(definition, params):
    cases = [("unknown_id", {**params, "__harness_unknown__": 0})]
    for spec in definition["params"]:
        pid, kind = spec["id"], spec["type"]
        if kind in ("float", "int", "float_array"):
            for label, value in (("below", spec["min"] - 1), ("above", spec["max"] + 1)):
                cases.append((f"{pid}:{label}", {**params, pid: [value] if kind == "float_array" else value}))
        if kind == "float_array":
            cases.append((f"{pid}:max_length", {**params, pid: [spec["min"]] * (spec["max_len"] + 1)}))
            band_arrays = {"widths", "threshold_db", "ratio", "attack_ms", "release_ms",
                           "makeup_db", "range_db", "hold_ms", "attack_db", "sustain_db",
                           "up_gain_db", "up_threshold_db", "up_ratio", "up_max_gain_db"}
            if "crossovers_hz" in params and pid in band_arrays:
                count = len(params["crossovers_hz"]) + 1
                wrong = 1 if count != 1 else 2
                cases.append((f"{pid}:band_count", {**params, pid: [spec["min"]] * wrong}))
    return cases


def run_common_tests(ptype, *, neutral=None, neutral_null_dbfs=-120, params=None,
                     stages=None, srs=(44100, 48000, 96000), feedback=False,
                     adds_noise=False, seconds=0.25, seed=0, sr_probe=None,
                     invalid_params=None, block_renderer=None, latency_probe=None,
                     declared_latency=None, offline_latency=0, latency_params=None,
                     neutral_peak_dbfs=None, dc_limit_dbfs=-120):
    """Execute CT-1..8 through engine.render_chain; return per-test diagnostics.

    CT-2: the engine has no persistent-state block-processing API. Unless a
    block_renderer adapter is supplied, replace 64/1024/full streaming with
    two bit-identical full renders AND an independent excerpt render which
    replays full context from zero. This is the supported offline/excerpt
    contract, not proof of streaming block invariance. Adapters must preserve
    state and use render_chain (not reset it independently per chunk); their
    call is block_renderer(x, sr, params, *, block_size, stage, seed).

    neutral=None makes CT-4 explicitly not applicable. CT-4 limits RMS null;
    optional neutral_peak_dbfs additionally limits the difference peak.
    For CT-5 fixed zero
    latency can be checked entirely offline. A nonzero realtime declaration
    additionally requires latency_probe(x, sr, params, *, stage, seed) giving
    the uncompensated response; offline output must match offline_latency
    (default zero). Dynamic declarations require declared_latency (integer or
    callable(sr, validated_params)); otherwise CT-5 fails, not silently skips.
    latency_params optionally overrides the tested settings to isolate latency
    from intentional musical delay, e.g. a reverb's pre-delay or a pitch shift.
    The override and both measured delays are included in the result.

    CT-6 auto-tests numeric bounds, unknown ID and array max lengths. Extra
    invalid_params maps are needed for type-specific cross-array mismatches
    (e.g. band counts). A type without arrays records length as not applicable.

    CT-7 renders every sr x mono/stereo x stage and requires declaration-based
    measurements. Gain has built-in frequency/level checks. Other types must
    supply sr_probe(x, y, sr, validated_params) -> dict with boolean 'passed'
    and measured quantities (e.g. cutoff or attack/release). Finite audio alone
    cannot certify a declared frequency/time constant; a missing probe fails.

    CT-8 excites a full-scale seeded bipolar signal and, for feedback=True,
    follows it by 60 seconds of zero input in the SAME render, testing the
    peak of the last 1 second < -120 dBFS. Each CT traps exceptions into a
    failed result so assert_common_tests can report all failing items.
    """
    definition = P.describe(ptype)
    p = P.validate_params(ptype, params)
    stages = (stages,) if isinstance(stages, str) else tuple(definition["stages"] if stages is None else stages)
    if not stages or not srs or seconds <= 0:
        raise ValueError("stages, sample rates and duration must be nonempty")
    results = {}
    sr = int(srs[0])
    x = white_noise(-20, sr=sr, seconds=seconds, channels=2, seed=seed)

    def check(name, fn):
        try:
            value = fn()
            value["passed"] = bool(value["passed"])
            results[name] = value
        except Exception as exc:
            results[name] = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}

    def deterministic():
        measurements = {}
        for stage in stages:
            a = render(ptype, x, sr, p, stage=stage, seed=seed).audio
            b = render(ptype, x, sr, p, stage=stage, seed=seed).audio
            measurements[stage] = null(a, b)
        return {"passed": all(v["bit_identical"] for v in measurements.values()), "measurements": measurements}

    def blocks():
        measurements = {}
        for stage in stages:
            full = render(ptype, x, sr, p, stage=stage, seed=seed).audio
            repeated = render(ptype, x, sr, p, stage=stage, seed=seed).audio
            values = {"full_repeat": null(full, repeated)}
            if block_renderer is None:
                start, stop = len(x) // 3, len(x)
                part = render_excerpt(ptype, x, sr, start, stop, p, stage=stage, seed=seed)
                values["excerpt"] = null(full[start:stop], part)
            else:
                for size in (64, 1024, len(x)):
                    y = block_renderer(x, sr, p, block_size=size, stage=stage, seed=seed)
                    values[str(size)] = null(full, y)
            measurements[stage] = values
        return {"passed": all(v["bit_identical"] for rows in measurements.values() for v in rows.values()),
                "mode": "full_repeat_and_context_replay_excerpt" if block_renderer is None else "stateful_blocks",
                "measurements": measurements}

    def silence():
        values = {}
        for stage in stages:
            y = render(ptype, np.zeros_like(x), sr, p, stage=stage, seed=seed).audio
            dc = float(np.max(np.abs(np.mean(y, axis=0))))
            values[stage] = {"peak_dbfs": peak_dbfs(y), "dc_dbfs": db(dc), "finite": bool(np.isfinite(y).all())}
        return {"passed": all(v["finite"] and v["dc_dbfs"] <= dc_limit_dbfs and
                              (adds_noise or v["peak_dbfs"] == -math.inf) for v in values.values()),
                "adds_noise": adds_noise, "dc_limit_dbfs": dc_limit_dbfs, "measurements": values}

    def neutral_check():
        if neutral is None:
            return {"passed": True, "applicable": False, "reason": "no neutral setting declared"}
        values = {stage: null(x, render(ptype, x, sr, {**p, **neutral}, stage=stage, seed=seed).audio)
                  for stage in stages}
        return {"passed": all(v["rms_dbfs"] <= neutral_null_dbfs and
                              (neutral_peak_dbfs is None or v["peak_dbfs"] <= neutral_peak_dbfs)
                              for v in values.values()), "applicable": True,
                "limit_dbfs": neutral_null_dbfs, "peak_limit_dbfs": neutral_peak_dbfs, "measurements": values}

    def latency_check():
        values = []
        lp = P.validate_params(ptype, {**p, **(latency_params or {})})
        declared = definition["realtime"]["latency_samples"] if declared_latency is None else declared_latency
        for rate in srs:
            expected = declared(rate, lp) if callable(declared) else declared
            if not isinstance(expected, (int, np.integer)) or expected < 0:
                raise ValueError("dynamic latency requires an integer declaration/resolver")
            pulse = impulse(at_s=0.01, sr=rate, seconds=max(seconds, 0.1), channels=1)
            for stage in stages:
                y = render(ptype, pulse, rate, lp, stage=stage, seed=seed).audio
                measured = latency(y) - round(0.01 * rate)
                if latency_probe is not None:
                    raw = latency_probe(pulse, rate, lp, stage=stage, seed=seed)
                    raw_latency = latency(raw) - round(0.01 * rate)
                else:
                    raw_latency = measured if expected == 0 else None
                values.append({"sr": rate, "stage": stage, "declared_samples": int(expected),
                               "raw_measured_samples": raw_latency, "offline_samples": measured,
                               "passed": raw_latency == expected and measured == offline_latency})
        return {"passed": all(v["passed"] for v in values), "params": lp, "measurements": values}

    def validation():
        cases = _invalid_cases(definition, p)
        cases += [(f"explicit:{i}", {**p, **bad}) for i, bad in enumerate(invalid_params or [])]
        values = {}
        for label, bad in cases:
            try:
                render(ptype, x[:64], sr, bad, stage=stages[0], seed=seed)
            except ParamError as exc:
                values[label] = {"passed": True, "exception": type(exc).__name__}
            except Exception as exc:
                values[label] = {"passed": False, "exception": type(exc).__name__}
            else:
                values[label] = {"passed": False, "exception": None}
        arrays = any(v["type"] == "float_array" for v in definition["params"])
        return {"passed": all(v["passed"] for v in values.values()), "measurements": values,
                "array_length": "max_length and explicit cross-array cases" if arrays else "not applicable: no array parameters"}

    def sample_rates():
        values = []
        for rate in srs:
            for channels in (1, 2):
                tone = sine(1000, -20, sr=rate, seconds=max(seconds, 0.1), channels=channels)
                for stage in stages:
                    y = render(ptype, tone, rate, p, stage=stage, seed=seed).audio
                    if sr_probe is not None:
                        measurement = dict(sr_probe(tone, y, rate, p))
                    elif ptype == "gain":
                        f = fundamental_frequency(y, rate, low_hz=900, high_hz=1100)
                        gain = rms_dbfs(y) - rms_dbfs(tone)
                        measurement = {"frequency_hz": f, "gain_db": gain, "expected_gain_db": p["gain_db"],
                                       "passed": abs(f - 1000) <= 1 and abs(gain - p["gain_db"]) <= 0.01}
                    else:
                        measurement = {"passed": False, "reason": "sr_probe required for declared frequency/time measurements"}
                    shape_ok = y.shape == tone.shape
                    values.append({"sr": rate, "channels": channels, "stage": stage,
                                   **measurement, "shape_preserved": shape_ok,
                                   "passed": bool(measurement["passed"]) and shape_ok and bool(np.isfinite(y).all())})
        return {"passed": all(v["passed"] for v in values), "measurements": values}

    def full_scale():
        values = []
        for rate in srs:
            noise = white_noise(0, sr=rate, seconds=seconds, channels=2, seed=seed)
            excited = np.where(noise >= 0, 1.0, -1.0)
            if feedback:
                excited = np.concatenate([excited, np.zeros((60 * rate, 2))])
            for stage in stages:
                y = render(ptype, excited, rate, p, stage=stage, seed=seed).audio
                tail = peak_dbfs(y[-rate:]) if feedback else None
                finite = bool(np.isfinite(y).all())
                values.append({"sr": rate, "stage": stage, "finite": finite,
                               "peak_dbfs": peak_dbfs(y), "tail_peak_dbfs": tail,
                               "passed": finite and (not feedback or tail < -120)})
        return {"passed": all(v["passed"] for v in values), "feedback": feedback, "measurements": values}

    for key, fn in zip((f"CT-{i}" for i in range(1, 9)),
                       (deterministic, blocks, silence, neutral_check, latency_check, validation, sample_rates, full_scale)):
        check(key, fn)
    return results


def assert_common_tests(ptype, **kwargs):
    """Return diagnostics, or raise with every failed CT and its measured values."""
    results = run_common_tests(ptype, **kwargs)
    failures = {name: row for name, row in results.items() if not row["passed"]}
    if failures:
        raise AssertionError(f"{ptype} common-test failures: {failures!r}")
    return results
