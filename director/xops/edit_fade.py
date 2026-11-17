"""Core clip fades where representable; BB-18 for other curves and crossfades."""
import copy
import numpy as np
from mankomix.core import mixrender as mr
from mankomix.dspx.bb.curves import fade_shape
from . import OpSpec, ClipPlan, DerivedPlan
from . import _clip_edit as H

SHAPES = ['linear', 'equal_power', 's_curve', 'exp', 'log']


def resolve(move):
    raw = move.get('params')
    cross = isinstance(raw, dict) and raw.get('where') == 'cross'
    p = H.resolve(move, {'in_ms': (0, 60000, 10), 'out_ms': (0, 60000, 10),
                          'cross_ms': (1, 5000, 20)},
                  {'where': (['in', 'out', 'both', 'cross'], None),
                   'shape': (SHAPES, 'equal_power' if cross else 's_curve'),
                   'cross_law': (['auto', 'equal_power', 'equal_gain'], 'auto')},
                  {'clip', 'section'}, required=('where',))
    if 'clip' in p and (not isinstance(p['clip'], str) or not p['clip']):
        raise ValueError('clip must be a clip ID')
    if cross and p.get('section') is None:
        raise ValueError('cross needs a section selecting one edit boundary')
    return p


def validate(move, ctx):
    H.validate(move, ctx, resolve)
    if ctx.project is not None and isinstance(move.get('params'), dict) and isinstance(move['params'].get('clip'), str):
        track = next((t for t in ctx.project.data['tracks'] if t['id'] == move.get('target')), None)
        if track is not None and move['params']['clip'] not in {c['id'] for c in track['clips']}:
            ctx.err('bad_value', 'clip does not belong to target')


def calculator(root):
    def calculate(x, sr, p):
        total = np.zeros((p['project_frames'], x.shape[1]))
        n = np.arange(len(total))
        for clip in p['render_clips']:
            y = H.render_clips(root, p['track'], [clip])
            rule = p['envelopes'].get(clip['id'])
            if rule is not None:
                if 'cross_start' in rule:
                    u = np.clip((n-rule['cross_start'])/max(1, rule['cross_length']-1), 0, 1)
                    # Shape warps time; the selected law fixes gain complementarity.
                    u = fade_shape(u, p['shape']) if p['shape'] not in ('linear', 'equal_power') else u
                    if p['resolved_law'] == 'equal_power':
                        env = np.sin(np.pi*u/2) if rule['side'] == 'right' else np.cos(np.pi*u/2)
                    else:
                        env = u if rule['side'] == 'right' else 1-u
                    if rule['side'] == 'left':
                        env[n >= rule['cross_start']+rule['cross_length']-1] = 0
                    y *= env[:, None]
                else:
                    k = n-clip['timeline_start']
                    env = np.ones(len(y))
                    if rule['fade_in']:
                        env *= fade_shape(k/rule['fade_in'], p['shape'])
                    if rule['fade_out']:
                        env *= fade_shape((clip['length']-1-k)/rule['fade_out'], p['shape'])
                    y *= env[:, None]
            total += y
        return total[p['start']:p['end']]
    return calculate


def cross_plan(root, move, p, x, sr, data, clips):
    lo, hi = H.section_bounds(p['section'], data, sr, point=True)
    live = sorted([c for c in clips if not c.get('muted')], key=lambda c: c['timeline_start'])
    pairs = [(a, b) for a, b in zip(live, live[1:])
             if a['timeline_start']+mr.clip_length(data, a, sr) == b['timeline_start']
             and lo <= b['timeline_start'] <= hi
             and ('clip' not in p or p['clip'] in (a['id'], b['id']))]
    if len(pairs) != 1:
        raise ValueError('cross section must select exactly one adjacent clip boundary')
    left, right = pairs[0]
    boundary = right['timeline_start']
    count = max(2, round(p['cross_ms']*sr/1000))
    before, after = count//2, count-count//2
    ll, rl = mr.clip_length(data, left, sr), mr.clip_length(data, right, sr)
    assets = {a['id']: a for a in data['assets']}
    if (before > ll or after > rl or right.get('source_start', 0) < before or
            left.get('source_start', 0)+ll+after > mr.asset_length_at(assets[left['asset']], sr)):
        raise ValueError('cross has insufficient source handles')
    start, end = boundary-before, boundary+after
    # Correlation uses the actual overlapping handles, before either inner fade.
    left.update(length=ll+after, fade_out=0)
    right.update(source_start=right.get('source_start', 0)-before,
                 timeline_start=start, length=rl+before, fade_in=0)
    a = H.render_clips(root, move['target'], [left])[start:end].ravel()
    b = H.render_clips(root, move['target'], [right])[start:end].ravel()
    a, b = a-a.mean(), b-b.mean()
    denom = np.linalg.norm(a)*np.linalg.norm(b)
    corr = float(np.dot(a, b)/denom) if denom > 0 else 0.
    law = p['cross_law']
    if law == 'auto':
        law = 'equal_gain' if corr >= .5 else 'equal_power'
    p.update(resolved_law=law, correlation=corr,
             envelopes={left['id']: {'cross_start': start, 'cross_length': count, 'side': 'left'},
                        right['id']: {'cross_start': start, 'cross_length': count, 'side': 'right'}})
    return left['timeline_start'], right['timeline_start']+right['length']


def derive(root, move):
    from mankomix.director.edit import raw_track
    p = resolve(move)
    x, sr, data = raw_track(root, move['target'])
    clips = copy.deepcopy(mr.find_track(data, move['target'])['clips'])
    if p['where'] == 'cross':
        a, b = cross_plan(root, move, p, x, sr, data, clips)
    else:
        lo, hi = H.section_bounds(p.get('section'), data, sr)
        selected = [c for c in clips if not c.get('muted') and
                    ('clip' not in p or c['id'] == p['clip']) and
                    max(lo, c['timeline_start']) < min(hi, c['timeline_start']+mr.clip_length(data, c, sr))]
        if not selected:
            raise ValueError('no audible selected clip')
        changes, envelopes = {}, {}
        representable = p['shape'] in ('linear', 'equal_power')
        for c in selected:
            length = mr.clip_length(data, c, sr)
            fields = {'fade_curve': p['shape']}
            rule = {'fade_in': 0, 'fade_out': 0}
            for side in ('in', 'out'):
                if p['where'] in (side, 'both'):
                    fields['fade_'+side] = min(length, round(p[side+'_ms']*sr/1000))
                    rule['fade_'+side] = fields['fade_'+side]
                elif c.get('fade_'+side, 0) and c.get('fade_curve', 'equal_power') != p['shape']:
                    representable = False
            changes[c['id']] = fields
            envelopes[c['id']] = rule
        a = min(c['timeline_start'] for c in selected)
        b = max(c['timeline_start']+mr.clip_length(data, c, sr) for c in selected)
        if representable:
            changed = [dict(c, **changes.get(c['id'], {})) for c in clips]
            y = H.render_clips(root, move['target'], changed)
            return ClipPlan(changes, p, H.record(x[a:b], y[a:b], sr,
                           reason='core clip envelope; requested ends replace existing fades'))
        for c in selected:
            c['length'] = mr.clip_length(data, c, sr)
            for side in ('in', 'out'):
                if p['where'] in (side, 'both'):
                    c['fade_'+side] = 0
        p['envelopes'] = envelopes
    p.update(track=move['target'], render_clips=clips, start=a, end=b, project_frames=len(x), seed=0)
    calc = calculator(root)
    y = calc(x[a:b].copy(), sr, p)
    rec = H.record(x[a:b], y, sr, shape=p['shape'], correlation=p.get('correlation'),
                   cross_law=p.get('resolved_law'),
                   reason='BB-18 envelope; requested ends replace existing fades; other ends retained')
    return DerivedPlan(a, b, p, calc, record=rec)


OPS = {'edit_fade': OpSpec('edit', ('target', 'params'), validate,
                            derive=derive, code_version='w4d-fade-1')}
