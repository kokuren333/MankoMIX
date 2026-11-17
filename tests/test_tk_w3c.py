"""W3c measured restoration acceptance; unmet requirements stay strict xfail."""
import json
import numpy as np
import pytest
from scipy import signal
from mankomix.dsp import processors as P
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb import ar
from mankomix.dspx.bb import restoration as R
from mankomix.dspx.procs import declick as C
from tests import toolimpl_harness as H

TYPES = ('declick', 'declip', 'interpolate')


@pytest.fixture(autouse=True)
def diagnostic_enable(monkeypatch, request):
    """Only this test module can render an honestly unpublished implementation."""
    for kind in ('declick', 'declip'):
        monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)
    params = getattr(getattr(request.node, 'callspec', None), 'params', {})
    name = request.node.originalname
    unmet = (name == 'test_declick_rp4' and params.get('material') == 'vowel' and params.get('kind') in ('crackle', 'mouth') or
             name == 'test_click_200_detection_and_error' and params.get('material') == 'vowel' or
             name == 'test_declip_sdr_levels_constraints' and params.get('depth') == -6 and params.get('material') in ('vowel', 'mix'))
    if unmet:
        request.node.add_marker(pytest.mark.xfail(strict=True, reason='Measured spec acceptance remains unmet; type stays unpublished.'))


def render(kind, x, sr, params=None):
    return H.render(kind, x, sr, params, stage='track')


def tones(sr, seconds):
    t = np.arange(round(sr*seconds))/sr
    return (.15*np.sin(2*np.pi*223*t)+.08*np.sin(2*np.pi*503*t)+.04*np.sin(2*np.pi*997*t))[:, None]


def sdr(reference, estimate):
    return 10*np.log10(np.sum(reference**2)/max(np.sum((reference-estimate)**2), 1e-30))


@pytest.mark.parametrize('kind', TYPES)
def test_registration(kind):
    d = P.describe(kind)
    assert d['stages'] == ['track', 'bus'] and d['master_slot'] is None
    assert d['offline_only'] and d['backends'] == ['reference']
    assert d['realtime'] == dict(block_ok=False, latency_samples=0, allocates=True)
    from mankomix.dspx.registry import time_varying_types
    assert kind not in time_varying_types()


def test_kind_default_helper_retains_explicit_values():
    raw = dict(kind='mouth', threshold=6, voiced_only=False, band_lo_hz=0)
    p = C.resolve_kind_params(raw)
    assert raw == dict(kind='mouth', threshold=6, voiced_only=False, band_lo_hz=0)
    assert p['threshold'] == 6 and not p['voiced_only'] and p['band_lo_hz'] == 0
    assert p['max_len_ms'] == 8 and p['repair_band'] == 'detect_band'


def test_publication_and_measured_default():
    from mankomix.dspx.procs import declip as D, interpolate as I
    assert not C.SPECS[0]['implemented'] and not D.SPECS[0]['implemented']
    assert I.SPECS[0]['implemented'] and P.PROCESSORS['interpolate']['implemented']
    assert P.validate_params('interpolate', {}) == dict(
        delta=False, t0_s=[], t1_s=[], method='auto', ar_order=512, context_ms=300., fade_ms=2.)
    assert P.validate_params('declip', {}) == dict(amount=1., delta=False, start_s=0., end_s=0.,
        threshold_db=0., min_run=3, max_run_ms=5., ar_order=48, headroom='auto', oversample=1)


@pytest.mark.xfail(strict=True, reason='Engine has no generic conditional-default resolver; declick remains unpublished.')
def test_engine_kind_defaults():
    for kind, defaults in C.KIND_DEFAULTS.items():
        p = P.validate_params('declick', {'kind': kind})
        assert {k: p[k] for k in defaults} == defaults


@pytest.mark.parametrize('kind', TYPES)
def test_common(kind):
    neutral = {'t0_s': [], 't1_s': []} if kind == 'interpolate' else {'amount': 0}
    def probe(x, y, sr, p):
        f = H.fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
        return {'passed': abs(f-1000) <= 1 and H.null(x, y)['rms_dbfs'] <= -120,
                'frequency_hz': f, 'null_dbfs': H.null(x, y)['rms_dbfs']}
    result = H.assert_common_tests(kind, neutral=neutral, seconds=.045, sr_probe=probe,
                                   latency_params=neutral)
    assert result['CT-2']['mode'] == 'full_repeat_and_context_replay_excerpt'


@pytest.mark.parametrize('kind', TYPES)
def test_declared_bounds_defaults_and_execution(kind):
    x = tones(48000, .04)*.001
    defaults = {p['id']: p['default'] for p in P.describe(kind)['params']}
    assert P.validate_params(kind, {}) == defaults
    for spec in P.describe(kind)['params']:
        values = [spec['min'], spec['max']] if spec['type'] in ('int', 'float') else (
            spec['choices'] if spec['type'] == 'enum' else [False, True] if spec['type'] == 'bool' else [])
        for value in values:
            params = {spec['id']: value}
            if spec['id'] == 'start_s' and value:
                params['end_s'] = value  # reject the empty end-of-domain interval
                with pytest.raises(ParamError):
                    P.validate_params(kind, params)
                continue
            if kind == 'interpolate' and spec['id'] == 'method' and value == 'spectral':
                with pytest.raises(ParamError, match='spectral'):
                    P.validate_params(kind, params)
                continue
            if kind == 'declick' and spec['id'] == 'band_lo_hz' and value:
                params['band_hi_hz'] = 24000
            out = render(kind, x, 48000, params).audio
            assert out.shape == x.shape and np.isfinite(out).all()


@pytest.mark.parametrize('kind', ['declick', 'declip'])
def test_rp_bypass_delta_region_records_repeat(kind):
    sr = 16000
    x = tones(sr, .3)
    if kind == 'declick':
        x[1600:1606] += .8
        p = {'protect_transients': 0}
    else:
        x = np.clip(x, -.1, .1)
        p = {'headroom': 'none'}
    y = render(kind, x, sr, p).audio
    assert not np.array_equal(y, x)
    delta = render(kind, x, sr, {**p, 'delta': True}).audio
    assert H.null(x, y+delta)['rms_dbfs'] <= -120
    assert render(kind, x, sr, {**p, 'amount': 0, 'delta': True}).audio.tobytes() == x.tobytes()
    p.update(start_s=.08, end_s=.19)
    result = render(kind, x, sr, p)
    assert result.audio[:1280].tobytes() == x[:1280].tobytes()
    assert result.audio[3040:].tobytes() == x[3040:].tobytes()
    assert result.audio.tobytes() == render(kind, x, sr, p).audio.tobytes()
    # finish is tested against independent sample differences, including stats.
    _, _, stats = R.finish(x, result.audio, sr, P.validate_params(kind, p))
    support = np.zeros(len(x), bool)
    for e in stats['events']:
        a, b = round(e['start_s']*sr), round((e['start_s']+e['length_s'])*sr)
        support[a:b] = True
    np.testing.assert_array_equal(support, np.any(x != result.audio, axis=1))
    assert stats['event_count'] == len(stats['events'])
    assert set(stats['before']) == {'lufs_i', 'sample_peak_dbfs', 'true_peak_dbtp'}


@pytest.mark.parametrize('kind', ['click', 'crackle', 'mouth'])
@pytest.mark.parametrize('material', ['tones', 'pink', 'vowel', 'bursts'])
def test_declick_rp4(kind, material):
    sr = 16000
    x = {'tones': lambda: tones(sr, .5), 'pink': lambda: H.pink_noise(sr=sr, seconds=.5, seed=33),
         'vowel': lambda: H.vowel(sr=sr, seconds=.5),
         'bursts': lambda: np.tile(H.tone_burst(sr=sr, seconds=.2, decay_ms=20), (3, 1))}[material]()
    p = P.validate_params('declick', C.resolve_kind_params({'kind': kind}))
    y = render('declick', x, sr, p).audio
    rel = H.rms_dbfs(y-x)-H.rms_dbfs(x)
    print('RP4', kind, material, rel)
    assert rel <= -60


@pytest.mark.parametrize('material', ['tones', 'vowel'])
def test_click_200_detection_and_error(material):
    sr = 16000
    x = tones(sr, 4.3) if material == 'tones' else H.vowel(sr=sr, seconds=4.3)
    z = x.copy()
    positions = np.round((.15+np.arange(200)*.02)*sr).astype(int)
    lengths = 1+np.arange(200)%40
    for i, (a, n) in enumerate(zip(positions, lengths)):
        z[a:a+n] += (-1)**i*10**((-20+20*(i%11)/10)/20)
    p = P.validate_params('declick', {})
    from mankomix.dspx.procs.declick import declick
    y, _, stats = declick(z, sr, p)
    events = stats['detected_events']
    found, errors, false = 0, [], 0
    for a, n in zip(positions, lengths):
        matches = [e for e in events if round(e['start_s']*sr) < a+n and round((e['start_s']+e['length_s'])*sr) > a]
        found += bool(matches)
        errors.append(H.rms_dbfs(y[a:a+n]-x[a:a+n]))
    for e in events:
        a, b = round(e['start_s']*sr), round((e['start_s']+e['length_s'])*sr)
        false += not any(a < pos+n and b > pos for pos, n in zip(positions, lengths))
    print('CLICK200', material, json.dumps(dict(detected=found, false=false, worst_gap_rms_dbfs=max(errors))))
    assert found >= 190 and false <= 5 and max(errors) <= -30


@pytest.mark.xfail(strict=True, reason='Dense crackle removal below 80%; declick remains unpublished.')
def test_crackle_dense_removal_and_clean_samples():
    sr = 16000
    x = tones(sr, 1.2)
    z = x.copy()
    positions = np.arange(1600, 17600, 80)
    for i, a in enumerate(positions):
        z[a] += (-1)**i*.01
    y = render('declick', z, sr, C.resolve_kind_params({'kind': 'crackle', 'protect_transients': 0})).audio
    original = z-x
    residual = y-x
    efficiency = 1-np.sum(residual[positions]**2)/np.sum(original[positions]**2)
    clean = np.ones(len(x), bool)
    clean[positions] = False
    change = H.rms_dbfs((y-x)[clean])
    print('CRACKLE', efficiency, change)
    assert efficiency >= .8 and change <= -50


@pytest.mark.xfail(strict=True, reason='Mouth repair error exceeds -30 dBFS; declick remains unpublished.')
def test_mouth_band_clicks_and_silence_gating():
    sr = 16000
    x = np.r_[np.zeros((sr//2, 1)), H.vowel(sr=sr, seconds=4.3), np.zeros((sr//2, 1))]
    z = x.copy()
    positions = np.round((.7+np.arange(200)*.02)*sr).astype(int)
    for i, a in enumerate(positions):
        n = round((2+i%5)*sr/1000)
        u = np.arange(n)/sr
        z[a:a+n, 0] += .3*np.sin(2*np.pi*(2200+i%8*700)*u)*np.hanning(n)
    z[1600:1664, 0] += .3*np.sin(2*np.pi*4000*np.arange(64)/sr)*np.hanning(64)
    p = C.resolve_kind_params({'kind': 'mouth'})
    y = render('declick', z, sr, p).audio
    changed = np.any(z != y, axis=1)
    detected = sum(changed[a:a+round(.006*sr)].any() for a in positions)
    errors = [H.rms_dbfs(y[a:a+round(.006*sr)]-x[a:a+round(.006*sr)]) for a in positions]
    print('MOUTH200', detected, max(errors))
    assert y[:3200].tobytes() == z[:3200].tobytes()
    assert detected >= 190 and max(errors) <= -30


def test_declick_transients_and_long_event():
    sr = 16000
    x = np.tile(H.tone_burst(sr=sr, seconds=.15), (4, 1))
    y = render('declick', x, sr).audio
    for a in range(0, len(x), 2400):
        gain = H.peak_dbfs(y[a:a+160])-H.peak_dbfs(x[a:a+160])
        assert abs(gain) <= .5
    z = tones(sr, .3)
    z[1600:1920] += .7  # twenty milliseconds, exceeding the default maximum
    y = render('declick', z, sr).audio
    assert y[1600:1920].tobytes() == z[1600:1920].tobytes()


@pytest.mark.parametrize('material', ['tones', 'vowel', 'mix'])
@pytest.mark.parametrize('depth', [-3, -6, -12])
def test_declip_sdr_levels_constraints(material, depth):
    sr = 8000
    x = tones(sr, .10)
    if material == 'vowel':
        x = H.vowel(sr=sr, seconds=.10)
    elif material == 'mix':
        x = x+H.vowel(f0=137, sr=sr, seconds=.10)*.2+H.tone_burst(freq=1700, sr=sr, seconds=.10)*.1
    level = np.max(abs(x))*10**(depth/20)
    z = np.clip(x, -level, level)
    result = render('declip', z, sr, {'headroom': 'none'})
    y = result.audio
    clipped = abs(z) >= level
    improvement = sdr(x[clipped], y[clipped])-sdr(x[clipped], z[clipped])
    assert np.all(y[clipped]*np.sign(z[clipped]) >= level-1e-12)
    stats = result.steps[0]['stats']
    for value in stats['clip_levels'][0].values():
        if value is not None:
            assert abs(20*np.log10(value/level)) <= .2
    print('DECLIP', material, depth, improvement)
    if depth == -6:
        assert improvement >= 6


@pytest.mark.parametrize('material', ['tones', 'pink', 'vowel', 'bursts'])
def test_declip_clean_rp4(material):
    sr = 8000
    x = {'tones': lambda: tones(sr, .3), 'pink': lambda: H.pink_noise(sr=sr, seconds=.3),
         'vowel': lambda: H.vowel(sr=sr, seconds=.3),
         'bursts': lambda: H.tone_burst(sr=sr, seconds=.3)}[material]()
    from mankomix.dspx.procs.declip import declip
    y, _, stats = declip(x, sr, P.validate_params('declip', {}))
    assert stats['event_count'] == 0 and stats['headroom_db'] == 0
    assert y.tobytes() == x.tobytes()


def test_declip_headroom_square_and_oversampling():
    sr = 8000
    x = 1.8*tones(sr, .1)/.27
    z = np.clip(x, -.6, .6)
    y = render('declip', z, sr).audio
    assert np.max(abs(y)) <= 1
    square = np.repeat([-.7, .7], 160)[:, None]
    assert render('declip', square, sr).audio.tobytes() == square.tobytes()
    for factor in (2, 4):
        y = render('declip', z, sr, {'oversample': factor, 'headroom': 'none'}).audio
        assert np.isfinite(y).all()
        assert np.all(y[z >= .6] >= .6) and np.all(y[z <= -.6] <= -.6)


@pytest.mark.parametrize('material', ['tones', 'vowel'])
@pytest.mark.parametrize('ms,limit', [(5, 20), (20, 12), (100, 6)])
def test_interpolation_tonal_sdr_and_seams(material, ms, limit):
    sr = 16000
    x = tones(sr, .5) if material == 'tones' else H.vowel(sr=sr, seconds=.5)
    a, b = 3200, 3200+round(ms*sr/1000)
    z = x.copy()
    z[a:b] = 0
    p = dict(t0_s=[a/sr], t1_s=[b/sr], method='ar')
    y = render('interpolate', z, sr, p).audio
    value = sdr(x[a:b], y[a:b])
    print('INTERPOLATE', material, ms, value)
    assert value >= limit
    assert z[:a].tobytes() == y[:a].tobytes() and z[b:].tobytes() == y[b:].tobytes()
    delta = render('interpolate', z, sr, {**p, 'delta': True}).audio
    assert H.null(y+delta, z)['rms_dbfs'] <= -120
    # Compare wideband first-difference energy at either join with the clean
    # material at that same join, avoiding unrelated envelope changes.
    for edge in (a, b):
        sl = slice(edge-16, edge+16)
        excess = H.rms_dbfs(np.diff(y[sl], axis=0))-H.rms_dbfs(np.diff(x[sl], axis=0))
        assert excess <= 3


@pytest.mark.parametrize('ms', [5, 20, 100])
def test_interpolation_noise_rms(ms):
    sr = 16000
    x = H.white_noise(sr=sr, seconds=.5, seed=32)
    a, b = 3200, 3200+round(ms*sr/1000)
    z = x.copy()
    z[a:b] = 0
    p = dict(t0_s=[a/sr], t1_s=[b/sr], method='ar')
    y = render('interpolate', z, sr, p).audio
    surrounding = np.r_[x[a-1600:a], x[b:b+1600]]
    delta = H.rms_dbfs(y[a:b])-H.rms_dbfs(surrounding)
    print('NOISE GAP', ms, delta)
    assert abs(delta) <= 3
    assert y.tobytes() == render('interpolate', z, sr, p).audio.tobytes()


@pytest.mark.parametrize('bad', [dict(t0_s=[0], t1_s=[]), dict(t0_s=[0], t1_s=[.501]),
    dict(t0_s=[.1], t1_s=[.1]), dict(t0_s=[.1, .15], t1_s=[.2, .3]),
    dict(t0_s=[0], t1_s=[.031]), dict(method='spectral')])
def test_invalid_gaps(bad):
    with pytest.raises(ParamError):
        P.validate_params('interpolate', bad)


def test_new_ar_apis_bounds_and_unchanged_existing_api():
    t = np.arange(2000)/8000
    x = .3*np.sin(2*np.pi*223*t)
    old = ar.burg(x, 8)
    estimate, info = ar.lsar_gap(x[:900], x[940:], 40, order=32, lower=-.1, upper=.1)
    assert info['iterations'] <= 8 and np.max(abs(estimate)) <= .1
    np.testing.assert_array_equal(old, ar.burg(x, 8))
    missing = np.zeros(len(x), bool)
    missing[900:940] = True
    model = ar.observed_model(x, missing, 32)
    assert len(model) >= 3 and np.isfinite(model).all()
    silence, ratio = ar.innovation_gap(np.zeros(20), np.zeros(20), 20)
    np.testing.assert_array_equal(silence, 0)
    assert ratio == 0


def test_interpolation_maximum_gap_implicit_solver():
    sr = 16000
    x = tones(sr, 1.2)
    z = x.copy()
    a, b = 4800, 12800
    z[a:b] = 0
    p = dict(t0_s=[a/sr], t1_s=[b/sr], method='ar', ar_order=16)
    y = render('interpolate', z, sr, p).audio
    assert np.isfinite(y).all() and sdr(x[a:b], y[a:b]) >= 6
    assert y[:a].tobytes() == z[:a].tobytes() and y[b:].tobytes() == z[b:].tobytes()


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('channels', [1, 2])
def test_interpolation_gap_time_at_declared_sample_rates(sr, channels):
    x = np.repeat(tones(sr, .08), channels, axis=1)
    a, b = round(.03*sr), round(.035*sr)
    z = x.copy()
    z[a:b] = 0
    y = render('interpolate', z, sr, dict(t0_s=[.03], t1_s=[.035], method='ar', ar_order=16, fade_ms=0)).audio
    assert y[:a].tobytes() == z[:a].tobytes() and y[b:].tobytes() == z[b:].tobytes()
    assert H.rms_dbfs((y-x)[a:b]) < -30


def test_event_cap_selects_strongest_and_keeps_count():
    x = np.zeros((6003, 1))
    y = x.copy()
    y[::2, 0] = np.arange(3002)+1
    _, _, stats = R.finish(x, y, 8000, {'delta': False})
    assert stats['event_count'] == 3002 and len(stats['events']) == 2000
    assert stats['events'][0]['start_s'] == 2004/8000
