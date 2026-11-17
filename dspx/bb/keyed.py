"""BB-14: precomputed keyed gain curves and their audio application.

keyed_envelope(hits, sr, depth_db, attack_ms, release_ms, *, shape, hold_ms)
returns sample/dB knots, with the legacy duck collision/truncation rules.
band_gain(x, sr, gain_db, lo_hz, hi_hz, slope_db_oct=12) applies an additive
Butterworth band gain. Both zero limits select full-band gain. The filter has
zero initial state; excerpt callers must replay audio context from sample zero.
Self-key wet ducking remains available from bb.selfduck, without changing it.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from mankomix.dsp.errors import ParamError


def validate_band(lo_hz, hi_hz, sr=None, *, full_band=False):
    """Validate paired band limits and, at runtime, the Nyquist margin."""
    if full_band and lo_hz == hi_hz == 0:
        return
    if not (np.isfinite(lo_hz) and np.isfinite(hi_hz) and 0 < lo_hz < hi_hz):
        raise ParamError('band limits must be positive and ascending, or both zero for full band')
    if sr is not None and hi_hz >= .98 * sr / 2:
        raise ParamError('band_hi_hz/hi_hz must be below 0.98 * Nyquist')


def band_gain(x, sr, gain_db, lo_hz=0, hi_hz=0, slope_db_oct=12):
    """Apply linked dB gain, preserving exact-zero samples and neutral bytes.

    slope_db_oct is the asymptotic slope on each band edge (12 or 24).
    The bandpass has twice the edge order (4 or 8 poles in total).
    """
    validate_band(lo_hz, hi_hz, sr, full_band=True)
    if slope_db_oct not in (12, 24):
        raise ParamError('slope_db_oct must be 12 or 24')
    x = np.asarray(x, dtype=np.float64)
    db = np.asarray(gain_db, dtype=np.float64)
    if db.shape != (len(x),) or not np.isfinite(db).all():
        raise ParamError('gain_db must have one finite value per frame')
    if not np.any(db):
        return x.copy()
    g = np.power(10.0, db / 20.0)
    if lo_hz == hi_hz == 0:
        return x * g[:, None]
    sos = signal.butter(slope_db_oct // 6, [lo_hz, hi_hz], btype='bandpass', fs=sr, output='sos')
    band = signal.sosfilt(sos, x, axis=0)
    return x + (g - 1)[:, None] * band


def validate_shape(shape, max_points=32, *, monotone=True):
    """Require a nonempty normalized curve with finite, strictly rising x."""
    from .curves import evaluate_curve
    if not isinstance(shape, list) or not 1 <= len(shape) <= max_points:
        raise ParamError(f'shape needs 1..{max_points} points')
    evaluate_curve(shape, [0.0])
    a = np.asarray(shape, dtype=np.float64)
    if np.any((a < 0) | (a > 1)) or (monotone and np.any(np.diff(a[:, 1]) < 0)):
        raise ParamError('shape must be normalized; recovery y must be nondecreasing')


def keyed_envelope(hits, sr, depth_db, attack_ms, release_ms, *, shape=None, hold_ms=0):
    """Compute attack, hold and shaped recovery, retaining legacy duck knots.

    Recovery is compressed when the next attack arrives early. Shape endpoints
    extend by holding; the final anchor always recovers to zero. Shared rounded
    samples use the later point, as in director.curve.points.
    """
    from mankomix.director.duck import envelope
    from .curves import evaluate_curve
    shape = [[0, 0], [1, 1]] if shape is None else shape
    validate_shape(shape)
    if (not np.isfinite([depth_db, attack_ms, release_ms, hold_ms]).all()
            or sr <= 0 or depth_db < 0 or attack_ms < 0 or release_ms <= 0 or hold_ms < 0):
        raise ParamError('invalid keyed envelope times or depth')
    # This branch is intentionally exact, including its depth rounding and
    # near-coincident hits, rather than reconstructing the legacy points.
    base = envelope(hits, sr, depth_db, attack_ms, release_ms)
    if hold_ms == 0 and shape == [[0, 0], [1, 1]]:
        return base
    out = {}
    hold = int(round(hold_ms * sr / 1000))
    for i in range(0, len(base), 3):
        (a, _), (h, dep), (end, _) = base[i:i + 3]
        # hold adds time to release, with the same next-attack ceiling.
        end += hold
        if i + 3 < len(base):
            end = min(end, base[i + 3][0] - 1)
        end = max(end, h + 1)
        recovery = min(h + hold, end - 1)
        out[a], out[h] = 0.0, dep
        out[recovery] = dep
        for u, _ in shape:
            at = int(round(recovery + float(u) * (end - recovery)))
            out[at] = round(float(dep * (1 - evaluate_curve(shape, u))), 9) + 0.0
        out[end] = 0.0
    return [[at, value] for at, value in sorted(out.items())]
