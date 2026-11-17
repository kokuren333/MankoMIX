"""Reverse a raw source interval through BB-18, with optional source tail."""
import copy
import numpy as np
from . import OpSpec, DerivedPlan
from . import _clip_edit as H
from mankomix.core import mixrender as mr
from mankomix.dspx.bb.curves import fade_shape


def resolve(move):
    return H.resolve(move, {'fade_ms': (0, 200, 5), 'tail_ms': (0, 10000, 0)}, {}, {'section'})


def validate(move, ctx):
    H.validate(move, ctx, resolve)


def calculator(root):
    def calculate(x, sr, p):
        if p['tail_samples']:
            raw = H.render_clips(root, p['track'], p['read_clips'])
            x = raw[p['start']:p['end']+p['tail_samples']]
        y = x[::-1].copy()[:p['end']-p['start']]
        fade = min(len(y), round(p['fade_ms']*sr/1000))
        if fade:
            u = np.arange(len(y))
            env = fade_shape(u/fade, 'equal_power')*fade_shape((len(y)-1-u)/fade, 'equal_power')
            y *= env[:, None]
        return y
    return calculate


def derive(root, move):
    p = resolve(move)
    x, sr, data, a, b = H.source(root, move, p)
    tail = round(p['tail_ms']*sr/1000)
    if b+tail > len(x):
        raise ValueError('reverse tail exceeds project timeline')
    clips = copy.deepcopy(mr.find_track(data, move['target'])['clips'])
    if tail:
        clips = [c for c in clips if not c.get('muted') and
                 max(a, c['timeline_start']) < min(b, c['timeline_start']+mr.clip_length(data, c, sr))]
        for c in clips:
            length = mr.clip_length(data, c, sr)
            if c['timeline_start'] < b <= c['timeline_start']+length < b+tail:
                extended = b+tail-c['timeline_start']
                asset = next(v for v in data['assets'] if v['id'] == c['asset'])
                if c.get('source_start', 0)+extended > mr.asset_length_at(asset, sr):
                    raise ValueError('reverse tail has insufficient source handle')
                c['length'] = extended
    p.update(track=move['target'], start=a, end=b, tail_samples=tail, read_clips=clips, seed=0)
    calc = calculator(root)
    y = calc(x[a:b].copy(), sr, p)
    return DerivedPlan(a, b, p, calc, record=H.record(x[a:b], y, sr))


OPS = {'edit_reverse': OpSpec('edit', ('target', 'params'), validate,
                               derive=derive, code_version='w4d-reverse-1')}
