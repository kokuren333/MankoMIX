"""T01-11: offline K-weighted, bounded, slope-limited gain riding."""
import numpy as np
from scipy.ndimage import gaussian_filter1d
from mankomix.core.measure import loudness as L
from . import OpSpec, MixResult
from . import _w4g as W

NUMERIC = {
    'offset_db': (-12, 12, 0, False), 'range_up_db': (0, 6, 2, True),
    'range_down_db': (0, 6, 2, True), 'window_ms': (100, 3000, 400, False),
    'smooth_ms': (50, 2000, 300, False), 'max_slope_db_s': (1, 40, 12, False),
    'gate_below_db': (-72, -20, -40, False), 'simplify_tol_db': (.05, 1, .2, False)}
ENUMS = {'mode': (('self', 'against'), 'self')}


def validate(move, ctx):
    p = W.validate(move, ctx, NUMERIC, ENUMS, ('against',))
    if p.get('mode', 'self') == 'against':
        against = p.get('against')
        if not isinstance(against, str) or not against.startswith(('trk_', 'bus_')) or against == move.get('target'):
            ctx.err('bad_target', 'against needs a different track or bus ID')
        elif ctx.project is not None and against not in {**ctx.project.tracks(), **ctx.project.buses()}:
            ctx.err('unknown_target', 'unknown against track or bus')


def levels(x, sr, samples, window_ms):
    y = L.k_weight(x, sr)
    power = (y*y) @ L.channel_weights(y.shape[1])
    sums = np.r_[0., np.cumsum(power)]
    width = max(1, round(window_ms*sr/1000))
    lo = np.maximum(0, samples-width//2)
    hi = np.minimum(len(x), samples+(width+1)//2)
    return -.691+W.db((sums[hi]-sums[lo])/np.maximum(1, hi-lo))


def simplify(samples, values, tolerance):
    """Ramer-Douglas-Peucker with vertical dB error on the sample grid."""
    keep = {0, len(samples)-1}
    stack = [(0, len(samples)-1)]
    while stack:
        a, b = stack.pop()
        if b-a < 2:
            continue
        pred = values[a]+(values[b]-values[a])*(samples[a+1:b]-samples[a])/(samples[b]-samples[a])
        errors = abs(values[a+1:b]-pred)
        i = int(np.argmax(errors))+a+1
        if errors[i-a-1] > tolerance:
            keep.add(i)
            stack.extend(((a, i), (i, b)))
    return [[int(samples[i]), float(values[i])] for i in sorted(keep)]


def curve(x, sr, p, against=None, bounded=False):
    samples, _, hop, active, _ = W.activity(x, sr, p['gate_below_db'])
    if not len(samples) or not active.any():
        return [], {'before': W.distribution([]), 'after': W.distribution([]), 'active_frames': 0}
    level = levels(x, sr, samples, p['window_ms'])
    target = np.median(level[active]) if against is None else levels(against, sr, samples, p['window_ms'])+p['offset_db']
    desired = np.clip(target-level, -p['range_down_db'], p['range_up_db'])
    # Hold the last active request before symmetric (zero-phase) smoothing.
    held = 0.
    for i in range(len(desired)):
        if active[i]:
            held = desired[i]
        desired[i] = held
    smooth = gaussian_filter1d(desired, max(.5, p['smooth_ms']*sr/(1000*hop)), mode='nearest')
    gain = np.zeros(len(samples))
    previous = 0. if bounded else float(smooth[0])
    step = p['max_slope_db_s']*hop/sr
    for i in range(len(gain)):
        if active[i] and (i == 0 or active[i-1]):
            previous += float(np.clip(smooth[i]-previous, -step, step))
        gain[i] = previous
    if bounded:
        gain[0] = 0.
        gain[-1] = 0.
        # A silent edge has zero permissible movement, including the tail.
        for i in range(len(gain)-2, -1, -1):
            limit = step if active[i] and active[i+1] else 0.
            gain[i] = np.clip(gain[i], gain[i+1]-limit, gain[i+1]+limit)
    # Preserve silence boundaries so simplification cannot draw through a hold.
    keep = {0, len(samples)-1}
    for a, b in W.runs(~active):
        keep.update((max(0, a-1), a, b-1, min(b, len(samples)-1)))
    knots = {}
    ordered = sorted(keep)
    for a, b in zip(ordered, ordered[1:]):
        for s, g in simplify(samples[a:b+1], gain[a:b+1], p['simplify_tol_db']):
            knots[s] = g
    points = [[s, g] for s, g in sorted(knots.items())]
    actual = np.interp(samples, np.array(points)[:, 0], np.array(points)[:, 1])
    y = x*10**(np.interp(np.arange(len(x)), samples, actual)[:, None]/20)
    return points, {'before': W.distribution(level[active]),
                    'after': W.distribution(levels(y, sr, samples, p['window_ms'])[active]),
                    'active_frames': int(active.sum()), 'gain': W.distribution(actual),
                    'max_slope_db_s': float(np.max(abs(np.diff(actual)))*sr/hop) if len(actual)>1 else 0.}


def expand(project, move):
    p = W.params(move, NUMERIC, ENUMS)
    x, sr = W.audio(project.root, move['target'])
    a, b = W.scope(project, move, x, sr)
    against = None
    if p['mode'] == 'against':
        against, _ = W.audio(project.root, p['against'])
        against = against[a:b]
    points, measurements = curve(x[a:b], sr, p, against, bounded='section' in move)
    points = W.fence([[s+a, g] for s, g in points], a, b, len(x))
    return MixResult(W.clean({'params': p, 'section_samples': [a, b], 'measurements': measurements,
                              'signal': 'cleaned_pre_chain', 'confidence': 'high' if measurements['active_frames'] else 'low'}), points=points)


OPS = {'ride': OpSpec('mix', ('target',), validate, expand=expand, time_varying=True, section=True)}
