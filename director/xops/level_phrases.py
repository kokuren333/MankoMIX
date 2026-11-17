"""T12-06: constant gain per phrase, with transitions confined to pauses."""
import numpy as np
from mankomix.core.measure import loudness as L
from . import OpSpec, MixResult
from . import _w4g as W

NUMERIC = {
    'to_lufs': (-40, -6, None, False), 'amount': (0, 1, .7, True),
    'range_up_db': (0, 18, 6, True), 'range_down_db': (0, 18, 6, True),
    'pause_ms': (100, 3000, 400, False), 'min_phrase_ms': (200, 10000, 1000, False),
    'gate_below_db': (-72, -20, -40, False), 'transition_ms': (20, 2000, 200, False),
    'noise_floor_guard_db': (0, 24, 12, False)}
ENUMS = {'measure': (('lufs_short_max', 'lufs_phrase', 'rms'), 'lufs_phrase')}


def validate(move, ctx):
    W.validate(move, ctx, NUMERIC, ENUMS)


def measure(x, sr, kind):
    if kind == 'rms':
        return float(W.db(np.mean(x*x)))
    if kind == 'lufs_short_max':
        values = L.short_term(x, sr)
        if len(values):
            return float(np.max(values))
    return float(L.integrated(x, sr))


def curve(x, sr, p, *, protect_start=False, protect_end=False):
    starts, powers, hop, active, reference = W.activity(x, sr, p['gate_below_db'])
    pieces = W.runs(active)
    phrases = []
    for a, b in pieces:
        a, b = int(starts[a]), min(len(x), int(b*hop))
        if phrases and (a-phrases[-1][1] < p['pause_ms']*sr/1000 or b-a < p['min_phrase_ms']*sr/1000):
            phrases[-1][1] = b
        else:
            phrases.append([a, b])
    active_lufs = float(L.integrated(x, sr))
    target = p['to_lufs'] if p['to_lufs'] is not None else active_lufs
    # RMS uses the same scale as the phrase levels when no LUFS target is given.
    if p['measure'] == 'rms' and p['to_lufs'] is None and active.any():
        target = float(W.db(np.mean(powers[active])))
    noise = float(W.db(np.mean(powers[~active]))) if (~active).any() else -300.
    rows = []
    for a, b in phrases:
        level = measure(x[a:b], sr, p['measure'])
        gain = float(np.clip(p['amount']*(target-level), -p['range_down_db'], p['range_up_db'])) if np.isfinite([level, target]).all() else 0.
        rms = float(W.db(np.mean(x[a:b]**2)))
        reason = None
        if not np.isfinite([level, target]).all():
            reason = 'insufficient_loudness_duration_or_silence'
        if gain > 0 and rms-noise <= p['noise_floor_guard_db']:
            gain, reason = 0., 'noise_floor_guard'
        if ((protect_start and a == 0) or (protect_end and b == len(x))):
            gain, reason = 0., 'section_boundary_without_pause'
        rows.append({'start_sample': a, 'end_sample': b, 'level': level, 'gain_db': gain,
                     'not_raised_reason': reason, 'rms_dbfs': rms})
    points = {}
    last_end, last_gain = 0, 0.
    for row in rows:
        a, b, gain = row['start_sample'], row['end_sample'], row['gain_db']
        transition = min(a-last_end, round(p['transition_ms']*sr/1000))
        if a > last_end:
            points[a-transition] = last_gain
        points[a] = gain
        points[b-1] = gain
        last_end, last_gain = b, gain
    if rows and last_end < len(x):
        points[last_end] = last_gain
        points[min(len(x)-1, last_end+round(p['transition_ms']*sr/1000))] = 0.
    before = [r['level'] for r in rows]
    after = [r['level']+r['gain_db'] for r in rows]
    return [[s, v] for s, v in sorted(points.items())], {
        'phrases': rows, 'before': W.distribution(before), 'after': W.distribution(after),
        'to_lufs_resolved': target, 'lufs_active': active_lufs, 'noise_floor_dbfs': noise,
        'activity_reference_dbfs': reference}


def expand(project, move):
    p = W.params(move, NUMERIC, ENUMS)
    x, sr = W.audio(project.root, move['target'])
    a, b = W.scope(project, move, x, sr)
    points, record = curve(x[a:b], sr, p, protect_start=a>0, protect_end=b<len(x))
    for row in record['phrases']:
        for key in ('start_sample', 'end_sample'):
            row[key] += a
    return MixResult(W.clean({'params': p, 'section_samples': [a, b], **record}),
                     points=W.fence([[s+a, g] for s, g in points], a, b, len(x)))


OPS = {'level_phrases': OpSpec('mix', ('target',), validate, expand=expand,
                              time_varying=True, section=True)}
