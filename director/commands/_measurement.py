"""In-memory audio sources and finite JSON for W4b measurement commands.

Master audio is rendered through the current variant's unchanged master chain.
Bus taps replay the existing mixer primitives, including pre-fader sends,
without changing routing or installing callbacks into the mixer.
"""
from copy import deepcopy
from pathlib import Path
import numpy as np

from mankomix.core import audio_io, mixrender as MR, mastering as M, routes
from mankomix.core.errors import InputError
from mankomix.core.project import Project
from mankomix.dsp.engine import render_chain
from mankomix.director import query as Q, stemobs as S


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def add_source(parser):
    parser.add_argument('--target', default='master')
    parser.add_argument('--section')


def project(args, *, preflight=True):
    p = Project.open(args.project or '.')
    vs = p.data.get('variants') or []
    v = vs[0] if vs else None
    if not preflight:
        return p, v
    data, _ = MR.effective_data(p, variant_id=v['id'] if v else None)
    err = S.cleanup_cache_error(p, MR.stem_tracks(data))
    if err:
        raise InputError(err)
    # Full-mix cleanup follows a separate route from stem cleanup.
    from mankomix.core import cleanstage as C
    ce = C.fullmix_cleanup_entry(data)
    if ce:
        aid = routes.fullmix_asset_id(data)
        sha = p.asset(aid).get('sha256') or ''
        if (ce.get('asset_sha256') not in (None, sha)
                or C._cache_valid(p, sha, str(ce.get('plan_hash'))) is None):
            raise InputError(S.CACHE_ERROR)
    return p, v


def master_input(p, v, mute=None):
    route = (v or {}).get('master', {}).get('route_detail') or (v or {}).get('master', {}).get('route')
    name = route.get('route') if isinstance(route, dict) else route
    if name is None:
        name = routes.select_route(p)['route']
    if mute and name == 'stem_mix':
        x, sr, _ = MR.render_mix(p, variant_id=v['id'] if v else None, mute=mute, measure=False)
        return x, int(sr)
    if mute:
        p = deepcopy(p)
        for t in p.data.get('tracks') or []:
            if t['id'] in mute:
                t['muted'] = True
    return routes.load_master_input(p, route, variant_id=v['id'] if v else None)


def master(p, v, mute=None):
    x, sr = master_input(p, v, mute)
    chain = (v or {}).get('master', {}).get('chain') or []
    if not chain:
        raise InputError('master measurement requires a planned master chain')
    result = render_chain(x, sr, M.engine_chain(chain), stage='master', seed=0)
    return result.audio, result.sr


def bus_audio(p, v, target):
    data, _ = MR.effective_data(p, variant_id=v['id'] if v else None)
    buses = {b['id']: b for b in data.get('buses') or []}
    if target not in buses:
        raise InputError(f'unknown bus {target!r}')
    ctx = MR._Ctx(p, data, 0)
    mix_id = MR._mix_bus_id(data)
    order = MR.bus_order(data)
    inputs = {b: np.zeros((ctx.total, 2), dtype=np.float64) for b in order}
    tracks = MR.stem_tracks(data)
    solos = {t['id'] for t in tracks if t.get('solo')}
    center = float((data.get('mix') or {}).get('pan_law_center_db', MR.DEFAULT_PAN_LAW_DB))
    for t in tracks:
        if t.get('muted') or (solos and t['id'] not in solos):
            continue
        pre, channels, _, _ = MR._track_pre(ctx, t, 0, ctx.total, t.get('chain'))
        env = MR._automation_env(t, 0, ctx.total)
        gain = MR._db_to_lin(t.get('gain_db', 0) or 0)
        post = pre*gain if env is None else pre*(env*gain)[:, None]
        pos, width = MR.track_pan(t)
        mono = channels == 1 and np.array_equal(pre[:, 0], pre[:, 1])
        panned = MR.pan_stereo(post, pos, width, center, mono=mono)
        inputs[t.get('output') or mix_id] += panned
        for s in t.get('sends') or []:
            sent = MR.pan_stereo(pre, pos, width, center, mono=mono) if s.get('pre_fader') else panned
            inputs[s['bus']] += sent*MR._db_to_lin(s.get('level_db', 0) or 0)
    selected = None
    for bid in order:
        b = buses[bid]
        y, _ = ctx.run_chain(inputs[bid], b.get('chain'), 'bus')
        gain = MR._db_to_lin(b.get('gain_db', 0) or 0)
        if gain != 1:
            y = y*gain
        if bid == target:
            selected = y.copy()
        if bid != mix_id:
            inputs[b.get('output') or mix_id] += y
    return selected, ctx.pr


def interval(x, sr, root, section):
    from mankomix.director.direction import _Project
    if isinstance(section, str) and ',' in section:
        try:
            a, b = map(float, section.split(','))
            if not np.isfinite([a, b]).all() or not 0 <= a < b <= len(x)/sr:
                raise ValueError
            section = {'t0_s': a, 't1_s': b}
        except ValueError:
            raise InputError('section/excerpt requires t0,t1 within the audio') from None
    try:
        a, b = Q.section_range(section, _Project(root).sections(), len(x)/sr)
    except Q.QueryError as e:
        raise InputError(str(e)) from None
    if len(x) < .4*sr:
        raise InputError('at least 0.4 seconds of audio is required')
    return round(a*sr), round(b*sr)


def source(args, target=None):
    target = target or getattr(args, 'target', 'master')
    audio = getattr(args, 'audio', None)
    p, v = project(args, preflight=not bool(audio))
    if audio:
        x, sr = audio_io.read(Path(audio))
        signal = 'audio'
    elif target == 'master':
        x, sr = master(p, v)
        signal = 'master_current_variant'
    elif target.startswith('bus_'):
        x, sr = bus_audio(p, v, target)
        signal = 'bus_post_chain_fader'
    else:
        src = S.StemSource(p.root, v['id'] if v else None)
        try:
            x, sr = src.mix() if target == 'mix' else src.track(target, 'dry')
        except S.StemObsError as e:
            raise InputError(str(e)) from None
        signal = 'mix_stage'
    x = Q._stereo(x)
    if not np.isfinite(x).all():
        raise InputError('audio must be finite')
    a, b = interval(x, sr, p.root, getattr(args, 'section', None))
    return x, sr, a, b, {'target': target, 'signal': signal, 'sample_rate': int(sr),
                         'range_s': [a/sr, b/sr]}


def number(value, lo, hi, label):
    if not np.isfinite(value) or not lo <= value <= hi:
        raise InputError(f'{label} must be in [{lo}, {hi}]')
    return value
