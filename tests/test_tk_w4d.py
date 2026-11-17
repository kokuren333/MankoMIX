"""W4d production-op acceptance; all projects and audio stay temporary."""
import copy
import json
import shutil
import numpy as np
import pytest
from scipy import signal
from mankomix.core import mixrender as mr
from mankomix.core.project import Project
from mankomix.core.measure import loudness as L
from mankomix.director import commands as C, derived as B, edit as E, xops as X, direction as D
from mankomix.director.xops import _clip_edit as H, edit_stretch as S, edit_stretch_extreme as EX
from mankomix.director.xops import edit_varispeed as V, edit_fade as F, edit_normalize as N
from mankomix.dspx.bb.curves import fade_shape
from tests import test_upgrade2_duck as T, toolimpl_harness as A
from tests.test_tk_w4_0 import move, doc


@pytest.fixture(autouse=True)
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path/'home'))


@pytest.fixture
def song(tmp_path):
    t = np.arange(T.SR*2)/T.SR
    tone = .1*np.sin(2*np.pi*440*t)
    return T._make(tmp_path/'song', {'bass': np.column_stack([tone, tone*.5]), 'vocals': tone[:, None]*.6})


def apply(root, m, name='dir_w4d'):
    return X.apply_edit(root, {'id': name}, m, X.OPS[m['op']], actor='human')


def test_registered_defaults():
    names = ['edit_stretch', 'edit_stretch_extreme', 'edit_varispeed', 'edit_reverse', 'edit_fade', 'edit_normalize']
    assert all(X.OPS[n].stage == 'edit' and X.OPS[n].code_version for n in names)
    p = S.resolve(move('edit_stretch', ratio=2))
    assert (p['quality'], p['transients'], p['fit'], p['map']) == ('high', .7, 'keep_start', [])
    p = EX.resolve(move('edit_stretch_extreme'))
    assert (p['ratio'], p['window_s'], p['onset'], p['seed'], p['max_out_s']) == (8, .25, 0, 0, 600)
    assert F.resolve(move('edit_fade', where='in'))['shape'] == 's_curve'
    assert F.resolve(move('edit_fade', where='cross', section=.5))['shape'] == 'equal_power'
    p = N.resolve(move('edit_normalize', mode='peak', to_db=-20))
    assert (p['scope'], p['group'], p['max_gain_db'], p['ceiling_db']) == ('track', [], 20, -1)
    assert X.OPS['edit_normalize'].group_limit == 32


@pytest.mark.parametrize('op,params', [
    ('edit_stretch', {'ratio': 0}), ('edit_stretch', {'ratio': 4.01}),
    ('edit_stretch', {'ratio': 1, 'bpm_from': 100, 'bpm_to': 100}),
    ('edit_stretch', {'bpm_from': 100}), ('edit_stretch', {'bpm_from': 400, 'bpm_to': 20}),
    ('edit_stretch', {'ratio': 1, 'quality': 'fast'}), ('edit_stretch', {'ratio': 1, 'transients': True}),
    ('edit_stretch', {'map': [[0, 0], [1, .5], [.8, 1]]}),
    ('edit_stretch', {'map': [[0, 0]]*1025}), ('edit_stretch', {'ratio': 1, 'typo': 1}),
    ('edit_stretch_extreme', {'ratio': 201}), ('edit_stretch_extreme', {'window_s': .01}),
    ('edit_stretch_extreme', {'onset': 2}), ('edit_stretch_extreme', {'seed': 1.2}),
    ('edit_stretch_extreme', {'seed': 65536}), ('edit_stretch_extreme', {'max_out_s': 3601}),
    ('edit_varispeed', {'speed': .1}), ('edit_varispeed', {'semitones': 25}),
    ('edit_varispeed', {'speed': 1, 'semitones': 0}), ('edit_varispeed', {}),
    ('edit_varispeed', {'ramp': [[0, 1], [0, 2]]}), ('edit_varispeed', {'ramp': [[0, 1], [1, 5]]}),
    ('edit_reverse', {'fade_ms': -1}), ('edit_reverse', {'tail_ms': 10001}),
    ('edit_fade', {}), ('edit_fade', {'where': 'in', 'shape': 'unknown'}),
    ('edit_fade', {'where': 'cross'}), ('edit_fade', {'where': 'cross', 'section': .5, 'cross_ms': 0}),
    ('edit_fade', {'where': 'in', 'clip': []}), ('edit_normalize', {'mode': 'peak'}),
    ('edit_normalize', {'mode': 'peak', 'to_db': 1}),
    ('edit_normalize', {'mode': 'rms', 'to_db': -20, 'max_gain_db': 41}),
    ('edit_normalize', {'mode': 'rms', 'to_db': -20, 'ceiling_db': -13}),
    ('edit_normalize', {'mode': 'peak', 'to_db': -20, 'scope': 'group', 'group': ['trk_bass']}),
    ('edit_normalize', {'mode': 'peak', 'to_db': -20, 'group': ['trk_vocals']}),
    ('edit_normalize', {'mode': 'peak', 'to_db': float('nan')}),
])
def test_bad_params_readonly(song, op, params):
    before = C._snapshot(song)
    errors = []
    ctx = X.ValidationContext(D._Project(song), {}, '', lambda w, c, m: errors.append((c, m)))
    X.OPS[op].validate(move(op, **params), ctx)
    assert errors
    assert C._snapshot(song) == before


@pytest.mark.parametrize('op,params', [
    ('edit_stretch', {'ratio': 1.25}), ('edit_stretch_extreme', {'ratio': 2, 'window_s': .05}),
    ('edit_varispeed', {'speed': 2}), ('edit_reverse', {'fade_ms': 5}),
    ('edit_fade', {'where': 'both', 'shape': 'linear'}), ('edit_fade', {'where': 'both', 'shape': 's_curve'}),
    ('edit_normalize', {'mode': 'peak', 'to_db': -25}),
])
def test_plan_readonly_apply_regenerate_revert(song, tmp_path, op, params):
    m = move(op, **params)
    parsed = doc(tmp_path, [m])
    before = C._snapshot(song)
    raw = E.raw_track(song, 'trk_bass')[0]
    data = copy.deepcopy(Project.open(song).data)
    validated = D.validate(parsed, song)
    assert validated['ok'], validated['errors']
    D.build_proposal(D._Project(song), parsed)
    p, p2 = X.OPS[op].derive(song, m), X.OPS[op].derive(song, m)
    assert p.params == p2.params and p.record == p2.record
    assert C._snapshot(song) == before
    r = apply(song, m)
    assert Project.open(song).data['timebase'] == data['timebase']
    assert r['confidence'] == 'measured'
    if isinstance(p, X.DerivedPlan):
        row = B._ledger(song, 'dir_w4d')['derived']['m01']
        result = Project.open(song).asset_path(row['result']['asset'])
        sha = row['result']['sha256']
        result.unlink()
        shutil.rmtree(song/'cache'/'derived')
        regenerated = B.regenerate(song, 'dir_w4d', 'm01', calculate=p.calculate)
        assert regenerated['sha256'] == sha
    else:
        assert Project.open(song).data['assets'] == data['assets']
        assert not (song/'cache'/'derived').exists()
    E.revert(song, 'dir_w4d', actor='human')
    np.testing.assert_array_equal(E.raw_track(song, 'trk_bass')[0], raw)
    assert Project.open(song).data['tracks'] == data['tracks']


@pytest.mark.parametrize('shape,mid', [('linear', .5), ('equal_power', 2**-.5), ('s_curve', .5), ('exp', .001), ('log', .999)])
def test_shapes_and_asset_route(song, shape, mid):
    env = fade_shape(np.linspace(0, 1, 101), shape)
    assert (env[0], env[50], env[-1]) == pytest.approx((0, mid, 1), abs=1e-14)
    assert np.all(np.diff(env) >= 0)
    p = F.derive(song, move('edit_fade', where='both', in_ms=100, out_ms=200, shape=shape))
    assert isinstance(p, X.ClipPlan if shape in ('linear', 'equal_power') else X.DerivedPlan)
    if isinstance(p, X.ClipPlan):
        assert next(iter(p.changes.values())) == {'fade_curve': shape, 'fade_in': round(.1*T.SR), 'fade_out': round(.2*T.SR)}


@pytest.mark.parametrize('quality', ['standard', 'high'])
@pytest.mark.parametrize('ratio', [.25, .8, 1.25, 4])
def test_stretch_length_pitch_ripple_clicks(quality, ratio):
    sr = 24000
    x = A.sine(440, sr=sr, seconds=2)
    p = S.resolve(move('edit_stretch', ratio=ratio, quality=quality))
    y = S.calculate(x, sr, p)
    assert len(y) == round(len(x)*ratio)
    hz = A.fundamental_frequency(y[round(.15*sr):round((2*ratio-.15)*sr)], sr)
    cents = 1200*np.log2(hz/440)
    env = A.rms_envelope(y, sr, window_ms=50)[round(.15*sr):-round(.15*sr)]
    ripple = 20*np.log10(env.max()/env.min())
    clicks = np.zeros((sr*2, 1))
    positions = np.arange(.1, 1.9, .1)*sr
    clicks[positions.astype(int), 0] = .8
    z = S.calculate(clicks, sr, p)
    errors, widths = [], []
    for pos in positions*ratio:
        radius = round(.04*min(1, ratio)*sr)
        a, b = max(0, round(pos)-radius), min(len(z), round(pos)+radius)
        segment = z[a:b, 0]**2
        errors.append(abs(a+np.argmax(segment)-pos)/sr*1000)
        cs = np.cumsum(segment)/max(float(segment.sum()), 1e-30)
        widths.append((np.searchsorted(cs, .95)-np.searchsorted(cs, .05))/sr*1000)
    print(json.dumps({'quality': quality, 'ratio': ratio, 'cents': cents, 'ripple_db': ripple,
                      'click_error_ms': max(errors), 'click_width_ms': max(widths)}))
    assert abs(cents) <= 2
    assert ripple <= (.5 if quality == 'standard' else .2)
    assert max(errors) <= 5 and max(widths) <= (5 if quality == 'standard' else 10)


@pytest.mark.parametrize('quality', ['standard', 'high'])
def test_stretch_map_clicks(quality):
    sr = 24000
    x = np.zeros((2*sr, 2))
    at = np.array([.2, .6, 1.1, 1.7])
    x[np.round(at*sr).astype(int)] = [.8, .4]
    mapping = [[0, 0], [.8, 1], [2, 1.8]]
    p = S.resolve(move('edit_stretch', map=mapping, quality=quality))
    y = S.calculate(x, sr, p)
    assert len(y) == round(1.8*sr)
    expected = np.interp(at, np.array(mapping)[:, 0], np.array(mapping)[:, 1])*sr
    for v in expected:
        lo, hi = round(v)-200, round(v)+200
        assert abs(lo+np.argmax(abs(y[lo:hi, 0]))-v) <= .005*sr
    np.testing.assert_allclose(y[:, 0], y[:, 1]*2, atol=1e-12)


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('speed', [.25, .5, 2, 4])
def test_varispeed_pitch_length_alias(sr, speed):
    x = A.sine(1000, sr=sr, seconds=.6)
    p = V.resolve(move('edit_varispeed', speed=speed))
    y = V.calculate(x, sr, p)
    assert len(y) == round(len(x)/speed)
    hz = A.fundamental_frequency(y[round(.01*sr):-round(.01*sr)], sr, low_hz=100, high_hz=6000)
    assert abs(1200*np.log2(hz/(1000*speed))) <= 1
    if speed > 1:
        high = A.sine(sr*.4, sr=sr, seconds=.6)
        alias = V.calculate(high, sr, p)[round(.02*sr):-round(.02*sr)]
        assert 20*np.log10(max(A.rms(alias), 1e-30)/A.rms(high)) <= -80


def test_varispeed_ramp_clock():
    sr = 24000
    p = V.resolve(move('edit_varispeed', ramp=[[0, 1], [2, 2]]))
    clock = V.ramp_clock(p['ramp'], 2*sr, sr)
    assert len(clock) == round(2*np.log(2)*sr)
    np.testing.assert_allclose(clock, 2*np.expm1(np.arange(len(clock))/sr*.5)*sr, atol=1e-8)
    x = A.sine(1000, sr=sr, seconds=2)
    y = V.calculate(x, sr, p)
    for t in (.3, .6, 1.):
        freq = A.fundamental_frequency(y[round((t-.02)*sr):round((t+.02)*sr)], sr, low_hz=500, high_hz=2500)
        assert abs(freq-1000*np.exp(.5*t)) < 5


@pytest.mark.parametrize('seed', [0, 65535])
def test_extreme_spectrum_ripple_seed_silence(seed):
    sr = 24000
    x = A.sine(1000, sr=sr, seconds=1)
    p = EX.resolve(move('edit_stretch_extreme', ratio=4, seed=seed))
    p['resolved_seed'] = seed
    y = EX.calculate(x, sr, p)
    assert len(y) == 4*len(x)
    np.testing.assert_array_equal(y, EX.calculate(x, sr, p))
    other = EX.calculate(x, sr, dict(p, resolved_seed=seed+1))
    assert y.tobytes() != other.tobytes()
    env = A.rms_envelope(y, sr, window_ms=50)[sr//4:-sr//4]
    ripple = 20*np.log10(env.max()/env.min())
    f, spec = signal.welch(y[sr//4:-sr//4, 0], sr, nperseg=8192)
    band = (f >= 1000*2**(-1/6)) & (f <= 1000*2**(1/6))
    level_db = 10*np.log10(np.trapezoid(spec[band], f[band])/np.mean(x*x))
    print(json.dumps({'extreme_seed': seed, 'ripple_db': ripple, 'third_octave_change_db': level_db}))
    assert ripple <= .5 and abs(level_db) <= 1
    np.testing.assert_array_equal(EX.calculate(np.zeros_like(x), sr, p), np.zeros((len(y), 1)))
    with pytest.raises(ValueError, match='max_out_s'):
        EX.calculate(x, sr, dict(p, ratio=200, max_out_s=1))


@pytest.mark.parametrize('mode', ['peak', 'true_peak', 'lufs_i', 'lufs_active', 'rms'])
def test_normalize_target_idempotence(song, mode):
    before = E.raw_track(song, 'trk_bass')[0]
    assets = C._snapshot(song/'assets')
    apply(song, move('edit_normalize', mode=mode, to_db=-25))
    after = E.raw_track(song, 'trk_bass')[0]
    value = N.measure(after, T.SR, mode)
    print(json.dumps({'normalize_mode': mode, 'after_db': value}))
    assert abs(value+25) <= .05
    apply(song, move('edit_normalize', 'm02', mode=mode, to_db=-25))
    np.testing.assert_array_equal(E.raw_track(song, 'trk_bass')[0], after)
    assert C._snapshot(song/'assets') == assets
    assert not (song/'cache'/'derived').exists()
    E.revert(song, 'dir_w4d', actor='human')
    np.testing.assert_array_equal(E.raw_track(song, 'trk_bass')[0], before)


def test_normalize_caps_silence():
    sr = 24000
    x = A.sine(440, dbfs=-60, sr=sr)
    p = N.resolve(move('edit_normalize', mode='peak', to_db=-5, max_gain_db=20))
    amount, r = N.gain(x, sr, p)
    assert amount == 20 and r['limited_by'] == ['max_gain_db']
    p.update(mode='rms', to_db=0, max_gain_db=40, ceiling_db=-3)
    amount, r = N.gain(x*100, sr, p)
    assert r['limited_by'] == ['ceiling_db']
    assert r['after_true_peak_dbtp'] <= -3+1e-10
    amount, r = N.gain(np.zeros_like(x), sr, p)
    assert amount == 0 and r['before_db'] is None and r['limited_by'] == ['silence']


@pytest.mark.parametrize('scope', ['track', 'clip', 'group'])
def test_capped_normalize_repeated_gain_is_identical(song, scope):
    params = dict(mode='peak', to_db=0, max_gain_db=1, scope=scope)
    if scope == 'group':
        params['group'] = ['trk_vocals']
    apply(song, move('edit_normalize', **params))
    first = copy.deepcopy(Project.open(song).data['tracks'])
    apply(song, move('edit_normalize', 'm02', **params))
    assert Project.open(song).data['tracks'] == first


def test_clip_curve_seam_rejects_noncore_shapes(song):
    clips = Project.open(song).data['tracks'][0]['clips']
    spec = X.OPS['edit_fade']
    for invalid in ('s_curve', 'exp', 'log', None, []):
        with pytest.raises(ValueError, match='fade_curve'):
            X._clip_entry(clips, move('edit_fade', where='in'), spec,
                          X.ClipPlan({clips[0]['id']: {'fade_curve': invalid}}, {}))


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('channels', [1, 2])
def test_stretch_rate_channels_silence_and_full_scale(sr, channels):
    x = A.sine(1000, dbfs=0, sr=sr, seconds=.5, channels=channels)
    for quality in ('standard', 'high'):
        p = S.resolve(move('edit_stretch', ratio=1.5, quality=quality))
        y = S.calculate(x, sr, p)
        assert y.shape == (round(len(x)*1.5), channels) and np.isfinite(y).all()
        assert abs(1200*np.log2(A.fundamental_frequency(y[sr//10:-sr//10], sr)/1000)) <= 2
        np.testing.assert_array_equal(S.calculate(np.zeros_like(x), sr, p), np.zeros_like(y))


def test_bpm_map_ramp_bounds_and_extreme_onset(song):
    p = S.resolve(move('edit_stretch', bpm_from=120, bpm_to=160))
    assert p['ratio'] == .75
    for module, params in [(S, {'map': [[0, 0], [1, 1]]}), (V, {'ramp': [[0, 1], [1, 2]]})]:
        before = C._snapshot(song)
        with pytest.raises(ValueError, match='cover'):
            module.derive(song, move('edit_stretch' if module is S else 'edit_varispeed', **params))
        assert C._snapshot(song) == before
    sr = 8000
    x = np.zeros((sr, 2))
    x[sr//3] = [1, .5]
    p = EX.resolve(move('edit_stretch_extreme', ratio=2, window_s=.05, onset=1))
    p['resolved_seed'] = 123
    y = EX.calculate(x, sr, p)
    assert y.shape == (2*sr, 2) and np.isfinite(y).all()
    np.testing.assert_allclose(y[:, 0], 2*y[:, 1], atol=1e-12)


@pytest.fixture
def group_song(tmp_path):
    t = np.arange(T.SR)/T.SR
    tone = .001*np.sin(2*np.pi*440*t)
    return T._make(tmp_path/'group', {f'stem{i:02d}': tone[:, None]*(i+1) for i in range(34)})


def test_normalize_32_peers_no_assets(group_song):
    data = copy.deepcopy(Project.open(group_song).data)
    tracks = data['tracks']
    tids = [t['id'] for t in tracks[:33]]
    before = [L.sample_peak_dbfs(E.raw_track(group_song, t)[0]) for t in tids]
    assets = C._snapshot(group_song/'assets')
    m = move('edit_normalize', target=tids[0], mode='peak', to_db=-15, scope='group', group=tids[1:])
    r = apply(group_song, m)
    assert len(r['members']) == 33
    after = [L.sample_peak_dbfs(E.raw_track(group_song, t)[0]) for t in tids]
    assert np.ptp(np.array(after)-before) <= .001
    assert Project.open(group_song).data['tracks'][33:] == tracks[33:]
    assert C._snapshot(group_song/'assets') == assets
    assert not (group_song/'cache'/'derived').exists()
    assert B.regenerate_group(group_song, 'dir_w4d', 'm01') == {}
    from mankomix.director.xops import _group
    assert _group.check(group_song, 'dir_w4d', 'm01', r)
    E.revert(group_song, 'dir_w4d', actor='human')
    assert Project.open(group_song).data['tracks'] == tracks


@pytest.mark.parametrize('clip_only', [True, False])
def test_legacy_group_limit_and_opt_in(group_song, clip_only):
    tids = [t['id'] for t in Project.open(group_song).data['tracks'][:18]]
    plans = {t: X.ClipPlan({}, {}) if clip_only else X.DerivedPlan(0, T.SR, {}, lambda x, sr, p: x.copy()) for t in tids}
    bundle = (X.ClipBundle if clip_only else X.DerivedBundle)(plans, {'identity': True})
    spec = X.OpSpec('edit', ('target',), lambda m, c: None, derive=lambda r, m: bundle, code_version='probe')
    m = move('edit_probe', target=tids[0], group=tids[1:])
    snap = C._snapshot(group_song)
    with pytest.raises(B.DerivedError, match='invalid group size'):
        X.apply_edit(group_song, {'id': 'dir_probe'}, m, spec, actor='human')
    assert C._snapshot(group_song) == snap
    spec = X.OpSpec('edit', ('target',), lambda m, c: None, derive=lambda r, m: bundle, code_version='probe', group_limit=32)
    r = X.apply_edit(group_song, {'id': 'dir_probe'}, m, spec, actor='human')
    assert len(r['members']) == 18
    E.revert(group_song, 'dir_probe', actor='human')


def cross_song(tmp_path, kind='same', correlation=None):
    rng = np.random.Generator(np.random.PCG64(17))
    n = 3*T.SR
    t = np.arange(n)/T.SR
    if kind == 'tone':
        x = .1*np.sin(2*np.pi*440*t)
        z = x.copy()
        z[0] = .03
    else:
        x = rng.standard_normal(n)*.1
        z = x*.9 if kind == 'same' else rng.standard_normal(n)*.1
        if correlation is not None:
            start, end = round(1.4*T.SR), round(1.6*T.SR)
            a = x[start:end]-x[start:end].mean()
            b = z[start:end]-z[start:end].mean()
            b -= np.dot(a, b)/np.dot(a, a)*a
            b *= np.linalg.norm(a)/np.linalg.norm(b)
            z[start:end] = correlation*a+np.sqrt(1-correlation**2)*b
    root = T._make(tmp_path/'cross', {'bass': x[:, None], 'vocals': z[:, None]})
    p = Project.open(root)
    tracks = copy.deepcopy(p.data['tracks'])
    base, other = tracks[0]['clips'][0], tracks[1]['clips'][0]
    tracks[0]['clips'] = [dict(base, source_start=0, timeline_start=0, length=round(1.5*T.SR)),
                          dict(base, id=base['id']+'_right', asset=other['asset'], source_start=round(1.5*T.SR),
                               timeline_start=round(1.5*T.SR), length=round(1.5*T.SR))]
    p.set('/tracks', tracks, actor='human')
    return root


@pytest.mark.parametrize('kind,law,tolerance', [('tone', 'equal_gain', .01), ('noise', 'equal_power', .3)])
def test_cross_rms_revert_regenerate(tmp_path, kind, law, tolerance):
    root = cross_song(tmp_path, kind)
    before = E.raw_track(root, 'trk_bass')[0]
    m = move('edit_fade', where='cross', section=1.5, cross_ms=200, cross_law=law)
    p = F.derive(root, m)
    assert isinstance(p, X.DerivedPlan)
    y = p.calculate(before[p.start:p.end], T.SR, p.params)
    lo, hi = round(1.4*T.SR), round(1.6*T.SR)
    db = 20*np.log10(A.rms(y[lo:hi])/A.rms(before[lo:hi]))
    print(json.dumps({'cross_law': law, 'rms_change_db': db, 'correlation': p.params['correlation']}))
    assert abs(db) <= tolerance
    np.testing.assert_array_equal(y[:lo], before[:lo])
    np.testing.assert_array_equal(y[hi:], before[hi:])
    apply(root, m)
    np.testing.assert_array_equal(E.raw_track(root, 'trk_bass')[0], y)
    row = B._ledger(root, 'dir_w4d')['derived']['m01']
    Project.open(root).asset_path(row['result']['asset']).unlink()
    shutil.rmtree(root/'cache'/'derived')
    B.regenerate(root, 'dir_w4d', 'm01', calculate=p.calculate)
    E.revert(root, 'dir_w4d', actor='human')
    np.testing.assert_array_equal(E.raw_track(root, 'trk_bass')[0], before)


@pytest.mark.parametrize('correlation,law', [(.49, 'equal_power'), (.51, 'equal_gain')])
def test_cross_auto_threshold(tmp_path, correlation, law):
    root = cross_song(tmp_path, 'noise', correlation)
    p = F.derive(root, move('edit_fade', where='cross', section=1.5, cross_ms=200))
    assert p.params['correlation'] == pytest.approx(correlation, abs=1e-7)
    assert p.params['resolved_law'] == law


def test_cross_missing_handles_readonly(tmp_path):
    root = cross_song(tmp_path)
    p = Project.open(root)
    tracks = copy.deepcopy(p.data['tracks'])
    tracks[0]['clips'][1]['source_start'] = 0
    p.set('/tracks', tracks, actor='human')
    snapshot = C._snapshot(root)
    with pytest.raises(ValueError, match='handles'):
        apply(root, move('edit_fade', where='cross', section=1.5))
    assert C._snapshot(root) == snapshot


def test_reverse_section_double_tail(song):
    m = move('edit_reverse', fade_ms=0, section='0.4,1.2')
    before = E.raw_track(song, 'trk_bass')[0]
    p = X.OPS['edit_reverse'].derive(song, m)
    y = p.calculate(before[p.start:p.end], T.SR, p.params)
    np.testing.assert_array_equal(y, before[p.start:p.end][::-1])
    tail = X.OPS['edit_reverse'].derive(song, move('edit_reverse', fade_ms=0, tail_ms=200, section='0.4,1.2'))
    np.testing.assert_array_equal(tail.calculate(before[tail.start:tail.end], T.SR, tail.params),
                                  before[round(.4*T.SR):round(1.4*T.SR)][::-1][:round(.8*T.SR)])
    apply(song, m)
    after = E.raw_track(song, 'trk_bass')[0]
    np.testing.assert_array_equal(after[:p.start], before[:p.start])
    np.testing.assert_array_equal(after[p.end:], before[p.end:])
    apply(song, move('edit_reverse', 'm02', fade_ms=0, section='0.4,1.2'))
    np.testing.assert_array_equal(E.raw_track(song, 'trk_bass')[0], before)


def test_reverse_tail_uses_source_handle_not_next_clip(tmp_path):
    root = cross_song(tmp_path, 'noise')
    track = Project.open(root).data['tracks'][0]
    left = copy.deepcopy(track['clips'][0])
    left['length'] += round(.2*T.SR)
    expected = H.render_clips(root, 'trk_bass', [left])[round(.5*T.SR):round(1.7*T.SR)][::-1][:T.SR]
    p = X.OPS['edit_reverse'].derive(root, move('edit_reverse', fade_ms=0, tail_ms=200, section='.5,1.5'))
    x = E.raw_track(root, 'trk_bass')[0][p.start:p.end]
    np.testing.assert_array_equal(p.calculate(x, T.SR, p.params), expected)


def test_other_end_fade_preserved(song):
    project = Project.open(song)
    tracks = copy.deepcopy(project.data['tracks'])
    c = tracks[0]['clips'][0]
    c.update(fade_out=200, fade_curve='equal_power')
    project.set('/tracks', tracks, actor='human')
    p = F.derive(song, move('edit_fade', where='in', shape='linear', in_ms=20, clip=c['id']))
    assert isinstance(p, X.DerivedPlan)
    before = E.raw_track(song, 'trk_bass')[0]
    y = p.calculate(before[p.start:p.end], T.SR, p.params)
    np.testing.assert_array_equal(y[-200:], before[p.end-200:p.end])


@pytest.mark.parametrize('op,params', [('edit_stretch', {'ratio': 1}), ('edit_varispeed', {'semitones': 0})])
def test_unity_no_assets(song, op, params):
    original = copy.deepcopy(Project.open(song).data)
    r = apply(song, move(op, **params))
    assert r['kind'] == 'clip_edit'
    assert Project.open(song).data['assets'] == original['assets']
    assert Project.open(song).data['tracks'] == original['tracks']
    assert not (song/'cache'/'derived').exists()


def test_normalize_clip_scope(tmp_path):
    root = cross_song(tmp_path, 'tone')
    p = Project.open(root)
    tracks = copy.deepcopy(p.data['tracks'])
    tracks[0]['clips'][1]['gain_db'] = -12
    p.set('/tracks', tracks, actor='human')
    apply(root, move('edit_normalize', mode='peak', to_db=-22, scope='clip'))
    levels = [L.sample_peak_dbfs(H.render_clips(root, 'trk_bass', [c])) for c in Project.open(root).data['tracks'][0]['clips']]
    assert levels == pytest.approx([-22, -22], abs=.05)


def test_direction_apply_check_cli_mixed_revert(song, tmp_path):
    from mankomix.cli import main as cli
    floor = tmp_path/'floor'
    shutil.copytree(song, floor)
    raw = E.raw_track(song, 'trk_bass')[0]
    T._render(floor)
    parsed = doc(tmp_path, [move('edit_fade', where='in', shape='linear'),
                            move('edit_reverse', 'm02', fade_ms=0, section='0.4,1.2'),
                            move('edit_normalize', 'm03', mode='peak', to_db=-25)])
    assert cli.main(['direction', 'validate', str(parsed['path']), '--project', str(song)]) == 0
    r = D.apply(song, parsed['path'])
    assert r['applied']
    T._render(song)
    assert D.check(song, floor, parsed['path'])['move_ref']['ok']
    data = copy.deepcopy(Project.open(song).data)
    with pytest.raises(D.DirectionError, match='already applied'):
        D.apply(song, parsed['path'])
    assert Project.open(song).data == data
    E.revert(song, parsed['id'], actor='human')
    np.testing.assert_array_equal(E.raw_track(song, 'trk_bass')[0], raw)


def test_unused_document_bytes_identical(song, tmp_path, monkeypatch):
    twin, floor = tmp_path/'twin', tmp_path/'floor'
    shutil.copytree(song, twin)
    shutil.copytree(song, floor)
    T._render(floor)
    parsed = doc(tmp_path, [move('gain', delta_db=-1)])
    def capture(root):
        validation = D.canonical_block(D.validate(parsed, root))
        proposal = D.canonical_block(D.build_proposal(D._Project(root), parsed))
        D.apply(root, parsed['path'])
        applied = (root/'directions'/f"{parsed['id']}.apply.json").read_bytes()
        T._render(root)
        checked = D.canonical_block(D.check(root, floor, parsed['path']))
        return validation, proposal, applied, checked
    enabled = capture(song)
    with monkeypatch.context() as patch:
        patch.setattr(X, 'specs', lambda builtins=(): {})
        disabled = capture(twin)
    assert enabled == disabled
