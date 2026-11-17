"""Shared deterministic measurements for the W4g operations (no writes)."""
from __future__ import annotations

import math
import numpy as np
from mankomix.core.errors import InputError


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate(move, ctx, numeric, enums=None, extra=()):
    target = move.get('target')
    if not isinstance(target, str) or not target.startswith('trk_'):
        ctx.err('bad_target', 'target must be a track ID')
    elif ctx.project is not None and target not in ctx.project.tracks():
        ctx.err('unknown_target', f'unknown track {target}')
    section = move.get('section', (move.get('params') or {}).get('section')
                       if isinstance(move.get('params'), dict) else None)
    if section is not None and section != 'all':
        if isinstance(section, dict):
            a, b = section.get('t0_s'), section.get('t1_s')
            if (set(section) != {'t0_s', 't1_s'} or not number(a) or not number(b)
                    or not 0 <= a < b or b-a < .4-1e-12):
                ctx.err('bad_value', 'section needs finite 0 <= t0_s < t1_s, duration >= 0.4 s')
        elif not isinstance(section, str):
            ctx.err('bad_value', 'section must be an ID or {t0_s,t1_s}')
        elif ctx.project is not None and section not in {s['id'] for s in ctx.project.sections()}:
            ctx.err('unknown_section', 'unknown section ID')
    p = move.get('params', {})
    if not isinstance(p, dict):
        ctx.err('bad_value', 'params must be an object')
        return {}
    enums = enums or {}
    if set(p) - set(numeric) - set(enums) - set(extra):
        ctx.err('bad_value', 'unknown parameters: ' + ', '.join(sorted(set(p)-set(numeric)-set(enums)-set(extra))))
    for k, (lo, hi, default, ranged) in numeric.items():
        v = p.get(k, default)
        if v is None and k not in p:
            continue
        values = v if ranged and isinstance(v, list) and len(v) == 2 else [v]
        if not all(number(x) for x in values):
            ctx.err('bad_value', f'{k} must be finite numeric' + (' or [lo, hi]' if ranged else ''))
        elif any(not lo <= x <= hi for x in values):
            ctx.err('param_range', f'{k} must be in [{lo}, {hi}]')
        elif len(values) == 2 and values[0] > values[1]:
            ctx.err('param_range', f'{k} range must be ascending')
    for k, (choices, default) in enums.items():
        if p.get(k, default) not in choices:
            ctx.err('bad_value', f'{k} must be one of {choices}')
    return p


def params(move, numeric, enums=None):
    out = {k: d for k, (_, _, d, _) in numeric.items()}
    out.update({k: d for k, (_, d) in (enums or {}).items()})
    out.update(move.get('params') or {})
    for k, (_, _, _, ranged) in numeric.items():
        if ranged and isinstance(out[k], list):
            selection = move.get('select', 'mid')
            if isinstance(selection, dict):
                selection = selection.get(k, 'mid')
            lo, hi = out[k]
            out[k] = {'min': lo, 'max': hi}.get(selection, (lo+hi)/2)
    return out


def audio(root, target):
    """Cleaned pre-chain track, or the actual output of an existing bus."""
    from mankomix.director.stemobs import StemSource, StemObsError, cleanup_cache_error
    from mankomix.core import mixrender as mr
    from mankomix.core.project import Project
    src = StemSource(root)
    try:
        if target.startswith('trk_'):
            project = Project.open(root)
            track = next((t for t in project.data.get('tracks', []) if t['id'] == target), None)
            if track is None:
                raise InputError(f'unknown track {target}')
            problem = cleanup_cache_error(project, [track])
            if problem:
                raise InputError(problem)
            x, sr, _ = mr.render_track(project, target, apply_chain=False, apply_fader=False)
            return x, int(sr)
        src.tracks()  # Preflight every cleanup cache before rendering.
        project = Project.open(root)
        data, _ = mr.effective_data(project)
        ctx = mr._Ctx(project, data, 0)
        buses = {b['id']: b for b in data.get('buses') or []}
        if target not in buses:
            raise InputError(f'unknown bus {target}')
        mix = mr._mix_bus_id(data)
        tracks = mr.stem_tracks(data)
        solo = {t['id'] for t in tracks if t.get('solo')}
        buffers = {bid: np.zeros((ctx.total, 2)) for bid in buses}
        center = float((data.get('mix') or {}).get('pan_law_center_db', mr.DEFAULT_PAN_LAW_DB))
        for t in tracks:
            if t.get('muted') or (solo and t['id'] not in solo):
                continue
            pre, channels, _, _ = mr._track_pre(ctx, t, 0, ctx.total, t.get('chain'))
            env = mr._automation_env(t, 0, ctx.total)
            post = pre * 10**(float(t.get('gain_db') or 0)/20)
            if env is not None:
                post = post * env[:, None]
            pos, width = mr.track_pan(t)
            mono = channels == 1 and np.array_equal(pre[:, 0], pre[:, 1])
            panned = mr.pan_stereo(post, pos, width, center, mono=mono)
            buffers[t.get('output') or mix] += panned
            for send in t.get('sends') or []:
                signal = mr.pan_stereo(pre, pos, width, center, mono=mono) if send.get('pre_fader') else panned
                buffers[send['bus']] += signal * 10**(float(send.get('level_db') or 0)/20)
        for bid in mr.bus_order(data):
            bus = buses[bid]
            y, _ = ctx.run_chain(buffers[bid], bus.get('chain'), 'bus')
            y = y * 10**(float(bus.get('gain_db') or 0)/20)
            if bid == target:
                return y, ctx.pr
            if bid != mix:
                buffers[bus.get('output') or mix] += y
    except StemObsError as e:
        raise InputError(str(e)) from None


def scope(project, move, x, sr):
    from mankomix.director.query import section_range
    section = move.get('section', (move.get('params') or {}).get('section'))
    a, b = section_range(section, project.sections(), len(x)/sr)
    return round(a*sr), round(b*sr)


def db(power):
    return 10*np.log10(np.maximum(power, 1e-30))


def frames(x, sr, ms=10):
    hop = max(1, round(ms*sr/1000))
    starts = np.arange(0, len(x), hop)
    powers = np.array([np.mean(x[a:min(len(x), a+hop)]**2) for a in starts])
    return starts, powers, hop


def activity(x, sr, gate):
    starts, powers, hop = frames(x, sr)
    levels = db(powers)
    present = levels > -150
    reference = float(np.median(levels[present])) if present.any() else -300.
    return starts, powers, hop, present & (levels > reference+gate), reference


def runs(mask):
    edges = np.diff(np.r_[False, mask, False].astype(int))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def distribution(values):
    a = np.asarray(values, float)
    a = a[np.isfinite(a)]
    if not len(a):
        return {'min_db': None, 'max_db': None, 'width_db': 0., 'std_db': 0.}
    return {'min_db': float(a.min()), 'max_db': float(a.max()),
            'width_db': float(np.ptp(a)), 'std_db': float(np.std(a))}


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in sorted(value.items())}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return round(float(value), 9) if np.isfinite(value) else None
    return value


def fence(points, start, end, total):
    """Zero outside a selected half-open interval, using one-sample fences."""
    out = {int(s): float(v) for s, v in points if start <= s < end}
    if start:
        out[start-1] = 0.
    if end < total:
        out[end] = 0.
    return [[s, v] for s, v in sorted(out.items())]
