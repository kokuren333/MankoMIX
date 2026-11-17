"""Absolute-clock utilities for the time/creative processors.

API: definition, curve_param, grid_params construct fresh declarations;
validate_grid checks tempo/pattern relationships; grid returns (k, start, end)
per sample, with independently rounded boundaries; active_mask samples binary
seconds curves; seam_gain returns linear fades; mix_active preserves bypass
samples bit for bit. All clocks start at sample zero (full-context rendering).
"""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _i, _e


def definition(name, params, implemented=False):
    return dict(type=name, name=name.replace('_', ' ').title(),
                description='Single-input, length-preserving reference effect.',
                stages=['track', 'bus'], master_slot=None, offline_only=False,
                backends=['reference'], implemented=implemented,
                realtime=dict(block_ok=False, latency_samples=0, allocates=True), params=params)


def curve_param(pid, limit, xmin, xmax, ymin, ymax, unit='s'):
    return dict(id=pid, type='curve', unit=None, x_unit=unit, x_min=xmin,
                x_max=xmax, y_min=ymin, y_max=ymax, max_points=limit,
                default=[], description='Ordered control points.')


def note_choices():
    # Same vocabulary as the engine, without importing its registration table.
    return ['none']+[f'1/{d}{m}' for d in (1, 2, 4, 8, 16, 32, 64) for m in ('', 'd', 't')]


def grid_params(pattern=True):
    ps = [_e('step_note', note_choices(), '1/16', 'Step note or none.'),
          _f('bpm', 'BPM', 0, 400, 0, 'Explicit fixed tempo.'),
          _f('step_ms', 'ms', 5, 4000, 125, 'Free step duration.'),
          _f('origin_s', 's', 0, 36000, 0, 'Absolute grid origin.'),
          curve_param('active', 256, 0, 36000, 0, 1)]
    if pattern:
        ps += [_i('steps', None, 1, 64, 16, 'Pattern length.'),
               _f('swing', None, 0, .75, 0, 'Delay of even numbered (one-based) steps.')]
    return ps


def validate_grid(p, arrays=(), *, resolve_tempo=True):
    from mankomix.dspx.bb.curves import period_ms
    note = p['step_note'] if resolve_tempo or p['bpm'] else 'none'
    period_ms(p['step_ms'], note=note, bpm=p['bpm'])
    for name in arrays:
        if p[name] and len(p[name]) != p['steps']:
            raise ParamError(name + ' must be empty or have steps entries')
    validate_active(p)


def validate_active(p):
    if any(y not in (0, 1) for _, y in p.get('active', [])):
        raise ParamError('active must contain binary values')


def grid(frames, sr, p):
    from mankomix.dspx.bb.curves import period_ms
    duration = period_ms(p['step_ms'], note=p['step_note'], bpm=p['bpm'])*sr/1000
    origin = p['origin_s']*sr
    swing = p.get('swing', 0)
    # Include sufficient negative boundaries so pre-origin samples are handled.
    first = int(np.floor(-origin/duration))-2
    last = int(np.ceil((frames-origin)/duration))+3
    ks = np.arange(first, last, dtype=np.int64)
    boundaries = np.rint(origin+(ks+(ks % 2)*swing)*duration).astype(np.int64)
    ix = np.searchsorted(boundaries, np.arange(frames), side='right')-1
    return ks[ix], boundaries[ix], boundaries[ix+1]


def active_mask(p, frames, sr):
    points = p.get('active', [])
    if not points:
        return np.ones(frames, dtype=bool)
    knots = np.rint(np.asarray(points)[:, 0]*sr).astype(np.int64)
    ix = np.clip(np.searchsorted(knots, np.arange(frames), side='right')-1, 0, len(knots)-1)
    return np.asarray(points)[ix, 1].astype(bool)


def seam_gain(position, length, fade):
    if fade <= 0:
        return np.ones_like(position, dtype=float)
    fade = np.minimum(fade, np.maximum(1, length/2))
    return np.clip(np.minimum(position/fade, (length-1-position)/fade), 0, 1)


def mix_active(x, wet, p, sr):
    y = x.copy()
    use = active_mask(p, len(x), sr)
    m = p.get('mix', 1)
    if m == 1:
        y[use] = wet[use]
    elif m:
        y[use] = x[use]+m*(wet[use]-x[use])
    return y


def causal_read(x, positions, current_samples):
    """Sinc256 reads limited to input available at each output sample.

    Reuse BB-09 for settled reads; truncate/renormalize the kernel only during
    the first 128 samples of read-clock lag. Exact integer reads stay exact.
    """
    from mankomix.dspx.bb.delayline import read_samples
    positions, now = np.asarray(positions), np.asarray(current_samples)
    out = read_samples(x, positions, 'sinc256')
    short = (np.floor(positions)+128 > now) & (positions != np.floor(positions))
    if np.any(short):
        pos = positions[short]
        offsets = np.arange(-127, 129)
        ix = np.floor(pos).astype(np.int64)[:, None]+offsets
        d = pos[:, None]-ix
        w = np.sinc(d)*(.5+.5*np.cos(np.pi*d/128))
        w *= ix <= now[short, None]
        w /= w.sum(axis=1, keepdims=True)
        for c in range(x.shape[1]):
            v = np.where((ix >= 0) & (ix < len(x)), x[np.clip(ix, 0, max(0, len(x)-1)), c], 0)
            out[short, c] = np.sum(v*w, axis=1)
    return out
