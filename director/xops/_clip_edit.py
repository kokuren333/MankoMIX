"""Read-only clip editing helpers; no operation registration or core mutation."""
import copy
import math
import numpy as np
from mankomix.core import mixrender as mr
from mankomix.core.project import Project
from mankomix.core.measure import loudness as L


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def resolve(move, numeric, enums, extra=(), required=()):
    raw = move.get('params')
    if not isinstance(raw, dict):
        raise ValueError('params must be an object')
    unknown = set(raw)-set(numeric)-set(enums)-set(extra)
    if unknown:
        raise ValueError('unknown parameter: '+', '.join(sorted(unknown)))
    if any(k not in raw for k in required):
        raise ValueError('required parameter: '+', '.join(required))
    p = copy.deepcopy(raw)
    for k, (lo, hi, default) in numeric.items():
        if k not in p and default is None:
            continue
        v = p.setdefault(k, default)
        if not number(v) or not lo <= v <= hi:
            raise ValueError(f'{k} needs a finite value in [{lo}, {hi}]')
    for k, (choices, default) in enums.items():
        v = p.setdefault(k, default)
        if not isinstance(v, str) or v not in choices:
            raise ValueError('invalid '+k)
    if 'section' in move and 'section' in p:
        raise ValueError('write section only once')
    if 'section' in move:
        p['section'] = copy.deepcopy(move['section'])
    return p


def validate(move, ctx, resolver):
    try:
        p = resolver(move)
        tid = move.get('target')
        if not isinstance(tid, str) or not tid.startswith('trk_') or (
                ctx.project is not None and tid not in ctx.project.tracks()):
            raise ValueError('target must name an existing track')
        peers = p.get('group', [])
        if not isinstance(peers, list) or len(peers) > 32 or any(
                not isinstance(t, str) or not t.startswith('trk_') or
                (ctx.project is not None and t not in ctx.project.tracks()) for t in peers):
            raise ValueError('group needs at most 32 existing peer track IDs')
        if len(set(peers)) != len(peers) or tid in peers:
            raise ValueError('group must be unique and exclude target')
        if ctx.project is not None:
            section_bounds(p.get('section'), ctx.project.data, ctx.project.rate,
                           point=p.get('where') == 'cross')
        elif p.get('section') is not None and not isinstance(p['section'], str):
            section_bounds(p['section'], None, 1, point=p.get('where') == 'cross')
    except (ValueError, TypeError, KeyError) as exc:
        ctx.err('bad_value', str(exc))


def section_bounds(section, data, sr, *, point=False):
    n = data['timebase']['length_samples'] if data is not None else None
    if section is None or section == 'all':
        return (0, n)
    if point and number(section):
        a = b = section
    elif isinstance(section, dict) and set(section) == {'t0_s', 't1_s'}:
        a, b = section['t0_s'], section['t1_s']
    elif isinstance(section, str) and ',' in section:
        try:
            a, b = map(float, section.split(','))
        except ValueError as exc:
            raise ValueError('section needs t0,t1 seconds') from exc
    elif isinstance(section, str):
        if data is None:
            return None
        s = next((s for s in data.get('sections', []) if s['id'] == section), None)
        if s is None:
            raise ValueError('unknown section')
        a, b = s['start_s'], s['end_s']
    else:
        raise ValueError('invalid section')
    if not number(a) or not number(b) or a < 0 or (a > b if point else a >= b):
        raise ValueError('invalid section bounds')
    a, b = round(a*sr), round(b*sr)
    if n is not None and b > n:
        raise ValueError('section exceeds project timeline')
    if not point and b <= a:
        raise ValueError('section is shorter than one sample')
    return a, b


def source(root, move, p):
    from mankomix.director import edit
    x, sr, data = edit.raw_track(root, move['target'])
    a, b = interval(data, move['target'], p, sr)
    if not 0 <= a < b <= len(x):
        raise ValueError('source interval exceeds project timeline')
    return x, sr, data, a, b


def interval(data, target, p, sr):
    track = next((t for t in data['tracks'] if t['id'] == target), None)
    if track is None:
        raise ValueError('target must name an existing track')
    clips = [c for c in track['clips'] if not c.get('muted')]
    if not clips:
        raise ValueError('target has no audible clips')
    if p.get('section') is None:
        a = min(c['timeline_start'] for c in clips)
        b = max(c['timeline_start']+mr.clip_length(data, c, sr) for c in clips)
    else:
        a, b = section_bounds(p['section'], data, sr)
    if not 0 <= a < b <= data['timebase']['length_samples']:
        raise ValueError('source interval exceeds project timeline')
    return a, b


def render_clips(root, track, clips):
    from mankomix.director import edit
    project = Project.open(root)
    data = copy.deepcopy(project.data)
    t = mr.find_track(data, track)
    t['clips'] = copy.deepcopy(clips)
    t.pop('cleanup', None)
    return mr.render_track(edit._RawView(project, data), track,
                           apply_chain=False, apply_fader=False)[0]


def finite(v):
    return float(v) if np.isfinite(v) else None


def measures(x, sr):
    return {'lufs_i': finite(L.integrated(x, sr)),
            'peak_dbfs': finite(L.sample_peak_dbfs(x)),
            'true_peak_dbtp': finite(L.true_peak_dbtp(x, sr))}


def record(x, y, sr, **extra):
    return {'confidence': 'measured', 'input_frames': len(x), 'calculated_frames': len(y),
            'fitted_frames': len(x), 'before': measures(x, sr), 'after': measures(y, sr),
            **extra}


def fitted(y, n):
    z = np.zeros((n, y.shape[1]), dtype=np.float64)
    z[:min(n, len(y))] = y[:n]
    return z
