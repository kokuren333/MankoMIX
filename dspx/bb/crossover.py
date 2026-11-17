"""BB-02 complementary crossovers and the shared MB parameter block.

API: mb_params() returns fresh declarations; validate_mb(params, sr=None)
checks edges/phase; expand_band_params(params, defaults) expands empty arrays.
split_bands(x, sr, crossovers_hz, phase='minimum', order=4, compensate=True)
returns (list of float64 audio bands, metadata). recombine_bands(bands) sums
in band order. Linear FIR design and complementary subtraction are duplicated
from this repository's dsp/reference/stereo.py; that implementation is intact.
Minimum phase uses a right-branching LR4/LR8 tree. Every earlier low branch
receives the allpass sum of each later split, so the total is a product of
allpasses, including for more than two bands. No third-party code is ported.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _e


def mb_params():
    return [_a('crossovers_hz', 'Hz', 20, 20000, 5, [150, 2500], 'Ascending crossover frequencies.'),
            _e('phase', ['minimum', 'linear'], 'minimum', 'Crossover phase response.')]


def validate_mb(params, sr=None):
    """Return band count; reject invalid MB values with ParamError."""
    edges = params.get('crossovers_hz', [150, 2500])
    if not isinstance(edges, (tuple, list)) or len(edges) > 5:
        raise ParamError('crossovers_hz must have at most five frequencies')
    if any(isinstance(f, bool) or not isinstance(f, (int, float)) or
           not np.isfinite(f) or not 20 <= f <= 20000 for f in edges):
        raise ParamError('crossovers_hz must be finite frequencies in [20, 20000]')
    if any(b <= a for a, b in zip(edges, edges[1:])):
        raise ParamError('crossovers_hz must be strictly ascending')
    if params.get('phase', 'minimum') not in ('minimum', 'linear'):
        raise ParamError('phase must be minimum or linear')
    if sr is not None and (sr <= 0 or any(f >= .98 * sr / 2 for f in edges)):
        raise ParamError('crossover frequency must be below 0.98 * Nyquist')
    return len(edges) + 1


def expand_band_params(params, defaults):
    """Return {id: list}; [] means the supplied scalar default in every band.

    Range validation belongs to each processor's declarations. Optional
    features such as up_threshold_db=[] (disabled) should be handled by the
    caller before expansion, rather than supplied in defaults.
    """
    count = validate_mb(params)
    out = {}
    for key, default in defaults.items():
        values = params.get(key, [])
        if not isinstance(values, (tuple, list)) or (values and len(values) != count):
            raise ParamError(f'{key} must be empty or have {count} band values')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not np.isfinite(v) for v in values):
            raise ParamError(f'{key} must contain finite numbers')
        out[key] = list(values) if values else [float(default)] * count
    return out


def taps_for(f_lowest, sr):
    """Same odd Kaiser FIR length as the original stereo processor."""
    tw = max(f_lowest * .5, 10.0)
    n, _ = signal.kaiserord(90.0, tw / (sr / 2.0))
    return int(min(max(n, 255), 1 << 15)) | 1


def lr_sos(freq, sr, order=4):
    """Return (low_sos, high_sos) for an LR4 or LR8 split."""
    if order not in (4, 8):
        raise ParamError('LR order must be 4 or 8')
    if not 0 < freq < .98 * sr / 2:
        raise ParamError('LR frequency must be below 0.98 * Nyquist')
    low = signal.butter(order // 2, freq, 'lowpass', fs=sr, output='sos')
    high = signal.butter(order // 2, freq, 'highpass', fs=sr, output='sos')
    return np.vstack([low, low]), np.vstack([high, high])


def split_bands(x, sr, crossovers_hz, phase='minimum', *, order=4, compensate=True):
    """Split (frames, channels) audio; raw linear output retains FIR delay.

    Compensated linear output has the original length and time alignment.
    Raw output has the same length, so callers must append latency samples
    before splitting if they need the complete tail. Minimum phase has no
    fixed latency and deliberately retains its allpass phase response.
    """
    validate_mb(dict(crossovers_hz=crossovers_hz, phase=phase), sr)
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2:
        raise ParamError('audio must have shape (frames, channels)')
    edges, n = list(crossovers_hz), len(x)
    taps = taps_for(min(edges), sr) if edges and phase == 'linear' else 0
    delay = (taps - 1) // 2 if taps else 0
    meta = {'latency_samples': delay, 'latency_compensated': bool(compensate),
            'fir_taps': taps, 'phase': phase, 'order': order, 'band_count': len(edges) + 1}
    if not edges or not n:
        return [x.copy() for _ in range(len(edges) + 1)], meta
    if phase == 'linear':
        start = delay if compensate else 0
        lps = []
        for f in edges:
            h = signal.firwin(taps, f, window=('kaiser', signal.kaiser_beta(90.0)), fs=sr)
            lps.append(signal.oaconvolve(x, h[:, None], mode='full', axes=0)[start:start+n])
        full = x.copy() if compensate else np.pad(x, ((delay, 0), (0, 0)))[:n]
        bands = [lps[0]] + [b-a for a, b in zip(lps, lps[1:])] + [full-lps[-1]]
    else:
        filters = [lr_sos(f, sr, order) for f in edges]
        bands, rest = [], x
        for i, (low, high) in enumerate(filters):
            band = signal.sosfilt(low, rest, axis=0)
            rest = signal.sosfilt(high, rest, axis=0)
            for later_low, later_high in filters[i+1:]:
                band = (signal.sosfilt(later_low, band, axis=0) +
                        signal.sosfilt(later_high, band, axis=0))
            bands.append(band)
        bands.append(rest)
    return bands, meta


def recombine_bands(bands):
    """Sum equally shaped bands in a fixed order."""
    if not bands:
        raise ParamError('at least one band is required')
    y = np.zeros_like(bands[0], dtype=np.float64)
    for band in bands:
        if band.shape != y.shape:
            raise ParamError('band shapes must match')
        y += band
    return y


def split_mb(x, sr, params, **kwargs):
    """MB dictionary convenience wrapper for split_bands."""
    validate_mb(params, sr)
    return split_bands(x, sr, params.get('crossovers_hz', [150, 2500]),
                       params.get('phase', 'minimum'), **kwargs)
