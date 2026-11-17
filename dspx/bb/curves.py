"""BB-05: curves and modulation on an absolute sample clock.

API: evaluate_curve(points, positions, interp='linear') evaluates y (including
dB y) directly, with constant endpoint extension. sample_curve uses seconds
and Python's round(t*sr); later points win on a shared sample. phase_positions,
periodic_curve, lfo and bandlimited_random take start_sample, never an
accumulated phase state. bandlimited_random adds bounded Fourier noise without
changing the existing lfo random walk or sample-and-hold sequences.
period_ms resolves the existing note vocabulary lazily, avoiding registry
import cycles. fade_shape supplies normalized amplitude envelopes.

The monotone cubic is an original implementation of the secant/tangent and
circle limiter construction in Fritsch & Carlson, SIAM J. Numer. Anal. (1980).
"""
from __future__ import annotations

import math
import numpy as np

from mankomix.dsp.errors import ParamError


def _points(points):
    a = np.asarray(points, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] != 2 or not len(a) or not np.isfinite(a).all():
        raise ParamError('curve needs finite [x, y] points')
    if np.any(np.diff(a[:, 0]) <= 0):
        raise ParamError('curve x must be strictly ascending')
    return a


def evaluate_curve(points, positions, interp='linear'):
    """Evaluate a nonempty curve at scalar/array x, preserving y's units."""
    a = _points(points)
    q = np.asarray(positions, dtype=np.float64)
    if not np.isfinite(q).all() or interp not in ('linear', 'smooth'):
        raise ParamError('finite positions and linear/smooth interpolation required')
    x, y = a.T
    if interp == 'linear' or len(x) == 1:
        return np.interp(q, x, y)
    h = np.diff(x)
    d = np.diff(y) / h
    m = np.r_[d[0], (d[:-1] + d[1:]) / 2, d[-1]]
    for k, slope in enumerate(d):
        if slope == 0:
            m[k:k + 2] = 0
        else:
            if m[k] * slope < 0:
                m[k] = 0
            if m[k + 1] * slope < 0:
                m[k + 1] = 0
            norm = math.hypot(m[k] / slope, m[k + 1] / slope)
            if norm > 3:
                m[k:k + 2] *= 3 / norm
    i = np.clip(np.searchsorted(x, q, side='right') - 1, 0, len(h) - 1)
    u = np.clip((q - x[i]) / h[i], 0, 1)
    return ((2*u**3 - 3*u**2 + 1)*y[i] + (u**3 - 2*u**2 + u)*h[i]*m[i]
            + (-2*u**3 + 3*u**2)*y[i+1] + (u**3 - u**2)*h[i]*m[i+1])


def _clock(frames, sr, start_sample):
    if (isinstance(frames, bool) or int(frames) != frames or frames < 0 or
            isinstance(sr, bool) or int(sr) != sr or sr <= 0 or
            isinstance(start_sample, bool) or int(start_sample) != start_sample or start_sample < 0):
        raise ParamError('frames/start_sample must be nonnegative integers; sr positive')
    return np.arange(int(start_sample), int(start_sample) + int(frames), dtype=np.int64)


def sample_curve(points, frames, sr, *, start_sample=0, interp='linear'):
    """Sample seconds/y knots; colliding rounded knots retain the later y."""
    a = _points(points)
    knots = {}
    for t, y in a:
        knots[int(round(float(t) * sr))] = y
    return evaluate_curve(list(knots.items()), _clock(frames, sr, start_sample), interp)


def period_ms(period_ms=500.0, *, note='none', bpm=0.0):
    """Resolve milliseconds or NOTE_VALUES; reject unknown/too-slow tempo."""
    from mankomix.dsp.processors import NOTE_VALUES, note_ms
    if not math.isfinite(bpm) or bpm < 0 or 0 < bpm < 20 or note not in NOTE_VALUES:
        raise ParamError('bpm must be 0 or >=20 and note must be in NOTE_VALUES')
    if note != 'none':
        if bpm <= 0:
            raise ParamError('a note value needs bpm > 0')
        return note_ms(note, bpm)
    if not math.isfinite(period_ms) or period_ms <= 0:
        raise ParamError('period_ms must be positive and finite')
    return float(period_ms)


def phase_positions(frames, sr, *, start_sample=0, period_ms=500.0,
                    note='none', bpm=0.0, origin_s=0.0, phase=0.0, wrap=True):
    """Cycles from absolute integer positions, fractional periods kept exact."""
    samples = _clock(frames, sr, start_sample)
    if not math.isfinite(origin_s) or origin_s < 0 or not math.isfinite(phase):
        raise ParamError('invalid modulation origin or phase')
    duration = globals()['period_ms'](period_ms, note=note, bpm=bpm) * sr / 1000
    p = (samples - int(round(origin_s * sr))) / duration + phase
    return np.remainder(p, 1.0) if wrap else p


def periodic_curve(points, frames, sr, *, interp='linear', **clock):
    """Repeat a phase/y curve (x in [0,1]); endpoints extend to the seam."""
    a = _points(points)
    if a[0, 0] < 0 or a[-1, 0] > 1:
        raise ParamError('periodic curve x must be in [0,1]')
    return evaluate_curve(a, phase_positions(frames, sr, **clock), interp)


def modulation_seed(project_seed, item_id, parameter_seed=0):
    """Combine project seed, chain item ID and seed knob by canonical hashing.

    Reuses the existing 63-bit dither seed convention; no Python hash().
    """
    from mankomix.core.hashing import canonical_hash
    from mankomix.dsp.engine import seed_from_hash
    return seed_from_hash(canonical_hash({'project_seed': int(project_seed),
                                         'item_id': str(item_id),
                                         'seed': int(parameter_seed)}))


def lfo(frames, sr, *, shape='sine', rate_hz=1.0, note='none', bpm=0.0,
        start_sample=0, origin_s=0.0, phase=0.0, seed=0, walk_step=0.25,
        item_id=None, parameter_seed=0):
    """Return bipolar sine/triangle/square/saw, S&H, or bounded random walk.

    random/random_walk use a reflected PCG64 walk through cycle anchors and
    quintic smoothstep between them. This is smooth, not a brickwall bandlimit.
    sample_hold (also s&h) holds one PCG64 uniform draw per cycle. Random
    access replays from the earliest cycle (including negative origin cycles),
    so call order, block sizes and excerpt starts cannot change the sequence.
    Pass an already-combined seed, or pass the project seed with item_id and
    parameter_seed to use modulation_seed. Nonrandom waveforms ignore seeds.
    """
    if not math.isfinite(rate_hz) or rate_hz <= 0 or not 0 < walk_step <= 2:
        raise ParamError('rate_hz and walk_step must be positive (walk_step <=2)')
    p = phase_positions(frames, sr, start_sample=start_sample, period_ms=1000/rate_hz,
                        note=note, bpm=bpm, origin_s=origin_s, phase=phase, wrap=False)
    u = np.remainder(p, 1.0)
    if shape == 'sine':
        return np.sin(2*np.pi*u)
    if shape == 'triangle':
        return 1 - 4*np.abs(u - 0.5)
    if shape == 'square':
        return np.where(u < 0.5, 1.0, -1.0)
    if shape in ('saw', 'saw_up'):
        return 2*u - 1
    if shape == 'saw_down':
        return 1 - 2*u
    if shape not in ('sample_hold', 's&h', 'random', 'random_walk'):
        raise ParamError('unknown LFO shape')
    if not len(p):
        return p
    initial = phase_positions(1, sr, period_ms=1000/rate_hz, note=note, bpm=bpm,
                              origin_s=origin_s, phase=phase, wrap=False)[0]
    lo = min(0, math.floor(initial))
    indices = np.floor(p).astype(np.int64) - lo
    if item_id is not None or parameter_seed != 0:
        seed = modulation_seed(seed, item_id or '', parameter_seed)
    rng = np.random.Generator(np.random.PCG64(int(seed)))
    values = rng.uniform(-1, 1, int(indices.max()) + 2)
    if shape in ('sample_hold', 's&h'):
        return values[indices]
    values[0] = 0.0
    for i in range(1, len(values)):
        v = values[i-1] + walk_step * values[i]
        values[i] = 2-v if v > 1 else -2-v if v < -1 else v
    s = u**3*(10 + u*(-15 + 6*u))
    return values[indices] + s*(values[indices+1] - values[indices])


def bandlimited_random(frames, sr, *, rate_hz=1.0, note='none', bpm=0.0,
                       start_sample=0, origin_s=0.0, phase=0.0, seed=0,
                       item_id=None, parameter_seed=0):
    """Bounded, bandlimited random walk from 32 PCG64 Fourier components.

    Independent random phases and 1/f amplitudes give integrated-noise (1/f^2
    power) motion. Frequencies are odd multiples of rate/84, through 3*rate/4;
    rate is the resolved free/tempo cutoff. The guard band keeps finite-window
    spectral leakage below the cutoff test, without clipping or nonlinear
    normalization. The sum of absolute weights bounds the output to [-1, 1]
    independently of render length. No sample-dependent state or FFT is used.

    phase rotates every component by the given cycles, so stereo_phase=.5
    negates the same random motion exactly up to float64 roundoff. origin_s
    shifts the absolute clock. These spectral phases have no single period at
    rate_hz (which specifies a random bandwidth, rather than a periodic LFO).
    Existing lfo random/random_walk behavior is deliberately unchanged.
    """
    if not math.isfinite(rate_hz) or rate_hz <= 0 or not math.isfinite(phase):
        raise ParamError('rate_hz must be positive and phase finite')
    p = phase_positions(frames, sr, start_sample=start_sample, period_ms=1000/rate_hz,
                        note=note, bpm=bpm, origin_s=origin_s, wrap=False)
    if item_id is not None or parameter_seed != 0:
        seed = modulation_seed(seed, item_id or '', parameter_seed)
    rng = np.random.Generator(np.random.PCG64(int(seed)))
    odd = np.arange(1, 64, 2, dtype=np.float64)
    weights = rng.standard_normal(len(odd)) / odd
    offsets = rng.uniform(0, 1, len(odd))
    result = np.zeros(len(p), dtype=np.float64)
    for frequency, weight, offset in zip(odd/84, weights, offsets):
        result += weight*np.sin(2*np.pi*(frequency*p + offset + phase))
    return result / np.sum(np.abs(weights))


def fade_shape(positions, shape='linear', *, floor_db=-120.0):
    """Rising amplitude at u in [0,1]; exp uses a dB-linear floor to unity.

    log is the time reverse complement of exp; s_curve is half a cosine.
    Exact endpoints are 0 and 1 for every shape, including exp/log.
    """
    u = np.clip(np.asarray(positions, dtype=np.float64), 0, 1)
    if not np.isfinite(u).all() or not math.isfinite(floor_db) or floor_db >= 0:
        raise ParamError('finite positions and negative floor_db required')
    if shape == 'linear':
        y = u
    elif shape == 'equal_power':
        y = np.sin(np.pi*u/2)
    elif shape == 's_curve':
        y = (1 - np.cos(np.pi*u))/2
    elif shape == 'exp':
        y = 10**(floor_db*(1-u)/20)
    elif shape == 'log':
        y = 1 - 10**(floor_db*u/20)
    else:
        raise ParamError('unknown fade shape')
    return np.where(u <= 0, 0.0, np.where(u >= 1, 1.0, y))
