"""W2g2 acceptance: causal repeats, recorded random events and six curve targets."""
import json
import numpy as np
import pytest
from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain
from mankomix.dsp.errors import ParamError
from tests import toolimpl_harness as H

TYPES = ('stutter', 'glitch', 'curve_shaper')
TARGETS = ('filter', 'pan', 'width', 'drive', 'crush', 'time')
ENDS = dict(filter=(200, 8000), pan=(-1, 1), width=(0, 1),
            drive=(0, 18), crush=(2000, 48000), time=(0, 1))


@pytest.fixture(autouse=True)
def candidates(monkeypatch):
    # The pending target-default contract bridge keeps this candidate private.
    monkeypatch.setitem(P.PROCESSORS['curve_shaper'], 'implemented', True)


def render(name, x, sr, p=None, *, seed=17, item='w2g2', stage='bus'):
    return render_chain(x, sr, [dict(id=item, type=name, params=p or {})], stage=stage, seed=seed)


def gridp(**p):
    return dict(step_note='none', **p)


def curvep(target, **p):
    lo, hi = ENDS[target]
    return dict(target=target, note='none', lo=lo, hi=hi, **p)


def metric(name, **values):
    print('MEASURE '+name+' '+json.dumps(values, sort_keys=True))


def test_metadata():
    from mankomix.dspx.registry import time_varying_types
    for name in TYPES:
        d = P.describe(name)
        assert d['stages'] == ['track', 'bus'] and d['master_slot'] is None
        assert d['realtime'] == dict(block_ok=False, latency_samples=0, allocates=True)
        assert d['backends'] == ['reference'] and not d['offline_only']
        assert name in time_varying_types()


def test_declared_defaults_match_spec():
    grid = dict(step_note='1/16', bpm=0, step_ms=125, steps=16,
                origin_s=0, swing=0, active=[])
    expected = {
        'stutter': dict(grid, repeat=[], gate=[], level_db=[], pitch_semitones=[],
                        reverse=[], pan=[], decay_db=0, hold_source='step', fade_ms=2, mix=1),
        'glitch': dict(grid, chance=0, w_repeat=1, w_reverse=.5, w_gate=.5, w_stop=.3,
                       w_crush=.3, w_shift=.3, w_shuffle=.5, intensity=.5,
                       chance_pattern=[], length_max=1, fade_ms=2, mix=1, seed=0),
        'curve_shaper': dict(shape=[[0, 0], [.25, 1], [1, 1]], note='1/4', bpm=0,
            period_ms=500, origin_s=0, phase=0, smooth_ms=2, band_lo_hz=0,
            band_hi_hz=0, interp='linear', target='filter', amount=0, lo=200, hi=8000,
            one_shot=[], filter_type='lowpass', resonance_db=6, mix=1)}
    for name in TYPES:
        assert {s['id']: s['default'] for s in P.describe(name)['params']} == expected[name]


def test_pattern_array_endpoints_are_rendered():
    x = np.random.Generator(np.random.PCG64(12)).normal(0, .1, (3200, 2))
    p = gridp(steps=2, repeat=[4, 4], step_ms=100)
    for name, values in dict(repeat=[0, 1, 2, 3, 4, 6, 8, 12, 16, 32], gate=[0, 1],
        level_db=[-60, 6], pitch_semitones=[-24, 24], reverse=[0, 1], pan=[-1, 1]).items():
        for value in values:
            out = render('stutter', x, 8000, dict(p, **{name: [value, value]})).audio
            assert np.isfinite(out).all()
    for name in ('stutter', 'glitch'):
        key = 'repeat' if name == 'stutter' else 'chance_pattern'
        long = dict(steps=64, **{key: [1]*64})
        render(name, x, 8000, gridp(**long))
        with pytest.raises(ParamError):
            P.validate_params(name, gridp(**{key: [0]*65}))


def test_mono_pan_and_partial_active():
    sr = 8000
    x = H.sine(sr=sr, seconds=.2)
    mono = render('stutter', x, sr, gridp(steps=1, repeat=[4], pan=[1])).audio
    assert mono.shape == (len(x), 2)
    assert np.max(np.abs(mono[:, 0])) == 0
    bypass = render('stutter', x, sr, gridp(steps=1, repeat=[4], pan=[1], active=[[0, 0]])).audio
    assert bypass.tobytes() == x.tobytes()
    for name, values in (('stutter', dict(steps=1, repeat=[4])), ('glitch', dict(chance=1))):
        out = render(name, x, sr, gridp(active=[[0, 0], [.05, 1], [.1, 0]], **values)).audio
        assert out[:400].tobytes() == x[:400].tobytes()
        assert out[800:].tobytes() == x[800:].tobytes()


@pytest.mark.parametrize('name', TYPES)
def test_bounds_defaults_and_rejection(name):
    x, sr = H.sine(sr=48000, seconds=.008), 48000
    base = curvep('filter') if name == 'curve_shaper' else gridp()
    render(name, x, sr, base)
    for s in P.describe(name)['params']:
        if s['id'] in ('lo', 'hi'):
            continue  # Target-dependent endpoints are tested independently below.
        values = [s['min'], s['max']] if s['type'] in ('int', 'float') else s.get('choices', [])
        for value in values:
            p = dict(base, **{s['id']: value})
            if s['id'] in ('note', 'step_note') and value != 'none':
                p['bpm'] = 120
            if s['id'] == 'bpm' and value == 0:
                p['note' if name == 'curve_shaper' else 'step_note'] = 'none'
            if s['id'] in ('band_lo_hz', 'band_hi_hz') and value:
                p.update(band_lo_hz=20000, band_hi_hz=24000)
                rate = 96000
            else:
                rate = sr
            if s['id'] == 'target':
                p.update(zip(('lo', 'hi'), ENDS[value]))
            y = render(name, x, rate, p).audio
            assert len(y) == len(x) and np.isfinite(y).all()
    for bad in ({'unknown': 1}, {'bpm': 10}, {'mix': 2}):
        with pytest.raises(ParamError):
            P.validate_params(name, dict(base, **bad))
    with pytest.raises(ParamError):
        render(name, x, sr, {})


@pytest.mark.parametrize('name', ('stutter', 'glitch'))
def test_grid_active_and_patterns(name):
    for bad in (dict(active=[[0, .5]]), dict(steps=2, **({'repeat': [4]} if name == 'stutter' else {'chance_pattern': [1]}))):
        with pytest.raises(ParamError):
            P.validate_params(name, gridp(**bad))
    if name == 'stutter':
        for bad in ({'steps': 1, 'repeat': [5]}, {'steps': 1, 'reverse': [.5]}):
            with pytest.raises(ParamError):
                P.validate_params(name, gridp(**bad))
    else:
        from mankomix.dspx.procs.glitch import KINDS
        with pytest.raises(ParamError):
            P.validate_params(name, gridp(**{'w_'+k: 0 for k in KINDS}))
    x = np.random.Generator(np.random.PCG64(1)).normal(0, .1, (2400, 2))
    active = gridp(steps=1, **({'repeat': [4]} if name == 'stutter' else {'chance': 1}))
    for neutral in ({'mix': 0}, {'active': [[0, 0]]}):
        assert render(name, x, 8000, dict(active, **neutral)).audio.tobytes() == x.tobytes()


@pytest.mark.parametrize('sr', (44100, 48000, 96000))
def test_stutter_repeat_gate_pitch_fade(sr):
    length = int(sr*.4)
    x = H.sine(sr=sr, seconds=.8, freq=200, dbfs=-12)
    p = gridp(steps=1, step_ms=400, repeat=[4], fade_ms=2)
    y = render('stutter', x, sr, p).audio
    bounds = np.rint(np.arange(5)*length/4).astype(int)
    # Exact comparisons use matching sample lengths (44.1k is also divisible by 4 here).
    f = round(.003*sr)
    for a in bounds[1:-1]:
        assert np.array_equal(y[a+f:a+bounds[1]-f], y[f:bounds[1]-f])
    gated = render('stutter', x, sr, dict(p, gate=[.5])).audio
    for a, b in zip(bounds, bounds[1:]):
        assert np.max(np.abs(gated[a+(b-a)//2:b]), initial=0) == 0
    pitched = render('stutter', x, sr, dict(p, pitch_semitones=[12])).audio
    a, b = bounds[1:3]
    freq = H.fundamental_frequency(pitched[a+f:a+(b-a)//2-f], sr, low_hz=350, high_hz=450)
    assert abs(freq-400) < 1
    assert np.max(np.abs(pitched[a+(b-a)//2:b]), initial=0) == 0
    dc = np.ones((length, 1))
    fade = render('stutter', dc, sr, p).audio[:, 0]
    rise = np.flatnonzero(fade[:bounds[1]] >= 1)[0]
    assert abs(rise/sr-.002) <= 1/sr
    metric('stutter', sr=sr, pitch_hz=freq, fade_rise_s=rise/sr)


def test_stutter_reverse_pattern_decay_causality():
    sr, n = 8000, 800
    x = np.arange(n*4, dtype=float)[:, None]/(n*10)
    p = gridp(steps=2, repeat=[4, 4], reverse=[1, 1], step_ms=100, fade_ms=.2)
    result = render('stutter', x, sr, p)
    y = result.audio
    assert np.array_equal(y[5:195], x[5:195])
    assert np.array_equal(y[205:395], x[:200][::-1][5:195])
    assert 'pass two' in result.steps[0]['stats']['first_pass']
    hold = render('stutter', x, sr, dict(p, hold_source='pattern', reverse=[0, 0])).audio
    assert np.array_equal(hold[805:995], hold[5:195])
    decayed = render('stutter', x, sr, dict(p, decay_db=6)).audio
    assert np.allclose(decayed[205:395], y[205:395]*10**(-6/20), atol=0, rtol=1e-15)
    changed = x.copy()
    changed[1177:] = 100
    assert np.array_equal(render('stutter', changed, sr, p).audio[:1177], y[:1177])
    neutral = render('stutter', x, sr, dict(p, repeat=[0, 0], gate=[0, 0])).audio
    assert neutral.tobytes() == x.tobytes()


def test_absolute_grid_10000_and_swing():
    from mankomix.dspx.bb.time_creative import grid
    p = P.validate_params('stutter', gridp(step_ms=5.1234, swing=.3))
    k, a, b = grid(51300, 1000, p)
    for step in (0, 1, 2, 9999, 10000):
        ids = np.flatnonzero(k == step)
        assert len(ids)
        assert a[ids[0]] == round((step+(step % 2)*.3)*5.1234)
    metric('grid', boundary_10000=int(a[np.flatnonzero(k == 10000)[0]]))


def test_glitch_statistics_and_random_access():
    from mankomix.dspx.procs.glitch import events, KINDS, WEIGHTS
    p = P.validate_params('glitch', gridp(chance=.4))
    records = events(0, 10000, p, seed=21)
    rate = len(records)/10000
    ratios = [sum(e['effect'] == k for e in records)/len(records) for k in KINDS]
    assert abs(rate-.4) <= .02
    assert np.max(np.abs(np.array(ratios)-np.array(WEIGHTS)/sum(WEIGHTS))) <= .03
    assert events(3900, 4100, p, seed=21) == [e for e in records if 3900 <= e['step'] < 4100]
    metric('glitch_statistics', rate=rate, type_ratios=ratios)


def test_glitch_engine_seed_log_pattern_and_continuation():
    from mankomix.dspx.procs.glitch import events
    x = np.random.Generator(np.random.PCG64(4)).normal(0, .1, (16000, 2))
    p = gridp(chance=.7, step_ms=10, steps=4, chance_pattern=[0, 1, 1, 1], length_max=3)
    r = render('glitch', x, 8000, p)
    records = r.steps[0]['stats']['events']
    assert all(e['step'] % 4 != 0 for e in records)
    affected = np.zeros(len(x), dtype=bool)
    for e in records:
        affected[e['start_sample']:e['end_sample']] = True
    assert r.audio[~affected].tobytes() == x[~affected].tobytes()
    assert render('glitch', x, 8000, p).audio.tobytes() == r.audio.tobytes()
    for seed, item, extra in ((18, 'w2g2', {}), (17, 'other', {}), (17, 'w2g2', {'seed': 1})):
        assert render('glitch', x, 8000, dict(p, **extra), seed=seed, item=item).audio.tobytes() != r.audio.tobytes()
    resolved = P.validate_params('glitch', p)
    assert events(70, 90, resolved, seed=42) == [e for e in events(0, 90, resolved, seed=42) if e['step'] >= 70]


def test_glitch_log_is_the_executed_effect():
    from mankomix.dspx.procs.glitch import apply_event
    x = np.random.Generator(np.random.PCG64(2)).normal(0, .1, (1600, 2))
    p = gridp(chance=.8, step_ms=10, length_max=3)
    result = render('glitch', x, 8000, p)
    resolved = P.validate_params('glitch', p)
    for record in result.steps[0]['stats']['events']:
        step, a, b = record['step'], record['start_sample'], record['end_sample']
        expected = apply_event(x, 8000, a, b, lambda back: ((step-back)*80, (step-back+1)*80),
                               record, resolved)
        assert expected.tobytes() == result.audio[a:b].tobytes()


@pytest.mark.parametrize('effect', ('repeat', 'reverse', 'gate', 'stop', 'crush', 'shift', 'shuffle'))
def test_glitch_single_effect(effect):
    from mankomix.dspx.procs.glitch import KINDS
    from mankomix.dspx.bb.time_creative import seam_gain, causal_read
    sr, size = 8000, 800
    x = H.sine(sr=sr, seconds=.4, freq=100, dbfs=-9)
    p = gridp(chance=1, intensity=1, step_ms=100, fade_ms=.2,
              **{'w_'+k: int(k == effect) for k in KINDS})
    r = render('glitch', x, sr, p)
    records = r.steps[0]['stats']['events']
    assert all(e['effect'] == effect for e in records)
    e = records[1]
    s = e['strength']
    fade = seam_gain(np.arange(size), size, .0002*sr)[:, None]
    if effect == 'repeat':
        from mankomix.dspx.bb.creative_rack import repeat_step
        expected = repeat_step(x, sr, size, 2*size, (2, 3, 4, 6, 8, 12, 16, 32)[min(7, int(s*8))], fade_ms=.2)
    elif effect == 'gate':
        expected = np.zeros((size, 1))
    elif effect == 'reverse':
        expected = x[:size][::-1]*fade
    elif effect == 'crush':
        expected = render('bitcrush', x[size:2*size], sr,
            dict(bits=24-23*s, rate_hz=max(100, sr*(1-.98*s)))).audio*fade
    elif effect == 'stop':
        expected = render('tape_stop', x[size:2*size], sr,
            dict(stop_s=[0], stop_ms=100, curve=4-3.75*s, fade_ms=.2)).audio*fade
    elif effect == 'shift':
        pos = np.arange(size)*2**(2*s-p['intensity'])
        use = pos < size
        expected = np.zeros((size, 1))
        expected[use] = causal_read(x[:size], pos[use], size+np.arange(size)[use])
        expected *= fade
    else:
        back = 1+min(3, int(s*4))
        expected = x[:size]*fade if back == 1 else np.zeros((size, 1))
    assert np.array_equal(r.audio[size:2*size], expected)


def test_fixed_draw_count_even_at_zero_chance(monkeypatch):
    from mankomix.dspx.procs import glitch as G
    original = G.step_draws
    calls = []
    def draws(step, seed=0, parameter_seed=0):
        calls.append(step)
        return original(step, seed, parameter_seed)
    monkeypatch.setattr(G, 'step_draws', draws)
    x = H.sine(sr=8000, seconds=.1)
    y = render('glitch', x, 8000, gridp(chance=0, step_ms=10)).audio
    assert calls == list(range(10))
    assert y.tobytes() == x.tobytes()


@pytest.mark.parametrize('target', TARGETS)
def test_curve_neutral_fixed_core_and_history(target):
    from mankomix.dspx.procs.curve_shaper import render_with_history
    sr = 48000
    x = H.sine(sr=sr, seconds=.25, channels=2, freq=220, dbfs=-12)
    x[:, 1] *= -.5
    p = curvep(target, amount=1, smooth_ms=0, shape=[[0, .5], [1, .5]], period_ms=500)
    resolved = P.validate_params('curve_shaper', p)
    control = np.sqrt(p['lo']*p['hi']) if target in ('filter', 'crush') else sum(ENDS[target])/2
    y = render('curve_shaper', x, sr, p).audio
    if target == 'filter':
        from mankomix.dspx.bb.svf import svf
        expected = svf(x, sr, control, 6)
    elif target == 'pan':
        expected = render('pan', x, sr, dict(position=control)).audio
    elif target == 'width':
        expected = render('stereo', x, sr, dict(width=control, crossovers_hz=[], mono_below_hz=0)).audio
    elif target == 'drive':
        expected = render('saturator', x, sr, dict(drive_db=control, mode='tanh', oversample=4)).audio
    elif target == 'crush':
        expected = render('bitcrush', x, sr, dict(rate_hz=control)).audio
    else:
        from mankomix.dspx.bb.time_creative import causal_read
        expected = causal_read(x, np.arange(len(x))*.5, np.arange(len(x)))
    db = H.rms_dbfs(y-expected)
    assert db <= -100
    for neutral in ({'amount': 0}, {'mix': 0}):
        assert render('curve_shaper', x, sr, dict(p, **neutral)).audio.tobytes() == x.tobytes()
    # Full-context replay includes future FIR support for drive and band splits.
    full = render_with_history(x[4000:], sr, resolved, history=x[:4000])[0]
    assert full.tobytes() == y[4000:].tobytes()
    metric('curve_fixed', target=target, null_dbfs=db)


@pytest.mark.parametrize('target', TARGETS)
@pytest.mark.parametrize('sr', (44100, 48000, 96000))
def test_curve_period_phase_shots_and_band(target, sr):
    from mankomix.dspx.procs.curve_shaper import modulation
    p = P.validate_params('curve_shaper', curvep(target, amount=1, smooth_ms=0,
        period_ms=100, shape=[[0, 0], [1, 1]], phase=.25))
    shape, _ = modulation(sr//2, sr, p)
    assert np.allclose(shape[:sr//10], shape[sr//10:sr//5], atol=2e-15)
    assert abs(shape[0]-.25) < 1e-15
    assert modulation(400, sr, p, start_sample=301)[0].tobytes() == shape[301:701].tobytes()
    shot = dict(p, phase=0, one_shot=[.1, .3])
    values, _ = modulation(sr//2, sr, shot)
    assert np.all(values[:round(.1*sr)] == 1)
    assert values[round(.1*sr)] == 0
    assert abs(values[round(.15*sr)]-.5) < 1/sr*10
    assert np.all(values[round(.2*sr):round(.3*sr)] == 1)
    x = H.sine(sr=sr, seconds=.18, channels=2, freq=200, dbfs=-18)
    y = render('curve_shaper', x, sr, dict(p, band_lo_hz=2000, band_hi_hz=5000)).audio
    gain = H.rms_dbfs(y[round(.04*sr):-round(.04*sr)])-H.rms_dbfs(x[round(.04*sr):-round(.04*sr)])
    assert abs(gain) <= .2


@pytest.mark.parametrize('target', TARGETS)
def test_curve_bounds_and_invalid(target):
    ranges = dict(filter=(20, 20000), pan=(-1, 1), width=(0, 2), drive=(0, 36), crush=(200, 48000), time=(0, 1))
    x = H.sine(sr=96000, seconds=.005, channels=2)
    for lo in ranges[target]:
        for hi in ranges[target]:
            y = render('curve_shaper', x, 96000, dict(curvep(target), lo=lo, hi=hi, amount=1)).audio
            assert np.isfinite(y).all()
    for bad in ({'lo': ranges[target][0]-1}, {'hi': ranges[target][1]+1},
                {'shape': []}, {'one_shot': [1, .5]}, {'band_lo_hz': 100, 'band_hi_hz': 0}):
        with pytest.raises(ParamError):
            P.validate_params('curve_shaper', dict(curvep(target), **bad))


@pytest.mark.parametrize('target', TARGETS)
def test_curve_dynamic_history_fullscale_and_mono(target):
    from mankomix.dspx.procs.curve_shaper import render_with_history
    x = np.random.Generator(np.random.PCG64(4)).choice([-1., 1.], (2400, 2))
    p = P.validate_params('curve_shaper', curvep(target, amount=1, period_ms=100,
        shape=[[0, 0], [.3, 1], [.7, .1], [1, .5]], smooth_ms=2))
    full = render('curve_shaper', x, 8000, p).audio
    excerpt = render_with_history(x[377:], 8000, p, history=x[:377])[0]
    assert full[377:].tobytes() == excerpt.tobytes()
    mono = render('curve_shaper', x[:, :1], 8000, p).audio
    assert mono.shape == (len(x), 2 if target == 'pan' else 1)
    assert np.isfinite(mono).all() and np.isfinite(full).all()


def test_curve_smoothing_tempo_and_long_clock():
    from mankomix.dspx.procs.curve_shaper import modulation
    from mankomix.dspx.procs.volume_shaper import modulation as volume_modulation
    for interp in ('linear', 'smooth'):
        p = P.validate_params('curve_shaper', curvep('width', interp=interp, smooth_ms=2))
        values = modulation(3000, 8000, p)[0]
        assert np.array_equal(values, 1+volume_modulation(3000, 8000, dict(p, depth_db=1)))
        assert modulation(307, 8000, p, start_sample=137)[0].tobytes() == values[137:444].tobytes()
    p = P.validate_params('curve_shaper', curvep('width', one_shot=[.1], period_ms=100,
        shape=[[0, 0], [1, .6]], smooth_ms=50))
    values = modulation(2400, 8000, p)[0]
    assert np.all(values[:800] == .6) and np.all(values[1600:] == .6)
    for note in P.NOTE_VALUES[1:]:
        p = P.validate_params('curve_shaper', dict(curvep('width'), note=note, bpm=120))
        assert np.isfinite(modulation(100, 8000, p)[0]).all()
    p = P.validate_params('curve_shaper', curvep('time', period_ms=13.37, smooth_ms=0,
        shape=[[0, 0], [1, 1]], phase=.17))
    at = round(1000*13.37*8)
    value, resets = modulation(1, 8000, p, start_sample=at)
    duration = 13.37*8
    phase = ((at/duration)+.17) % 1
    # T01-09 rounds the shape's endpoint to a sample, retaining fractional
    # cycle duration in the clock. This is a fixed anchor offset, not drift.
    expected = phase*duration/round(duration)
    assert abs(value[0]-expected) < 1e-15
    metric('curve_long_clock', sample=at, phase=float(value[0]), reset=int(resets[0]))


@pytest.mark.parametrize('target', TARGETS)
def test_target_default_resolver_and_proposed_schema(target):
    from mankomix.dspx.procs.curve_shaper import resolve_target_params, target_schema, TARGETS as limits
    from jsonschema import Draft202012Validator
    raw = dict(target=target, note='none')
    resolved = resolve_target_params(raw)
    assert (resolved['lo'], resolved['hi']) == ENDS[target]
    assert raw == dict(target=target, note='none')
    # Validate and render the proposed normalizer's actual output before the
    # shared contract hook is authorized. No defaults are guessed from values.
    y = render('curve_shaper', H.sine(sr=48000, seconds=.005), 48000, dict(resolved, amount=1)).audio
    assert np.isfinite(y).all()
    explicit = resolve_target_params(dict(target='crush', lo=200, hi=8000))
    assert explicit['lo'] == 200 and explicit['hi'] == 8000
    schema = dict(type='object', properties={
        'target': dict(enum=list(TARGETS)), 'lo': dict(type='number'), 'hi': dict(type='number')},
        allOf=target_schema())
    Draft202012Validator(schema).validate(resolved)
    lower, upper = limits[target][:2]
    for key, bad in (('lo', lower-1), ('hi', upper+1)):
        assert not Draft202012Validator(schema).is_valid(dict(resolved, **{key: bad}))
    assert not Draft202012Validator(schema).is_valid(dict(lo=0, hi=1))


@pytest.mark.parametrize('name,target', [('stutter', None), ('glitch', None)]+
                         [('curve_shaper', t) for t in TARGETS])
def test_common(name, target, monkeypatch):
    p = curvep(target, amount=1) if name == 'curve_shaper' else gridp()
    if target == 'pan':
        original_sine = H.sine
        # The harness assumes shape preservation; pan's active mono expansion
        # is independently tested, so use stereo for its frequency probe.
        monkeypatch.setattr(H, 'sine', lambda *a, **kw: original_sine(*a, **dict(kw, channels=2)))
    if name == 'stutter':
        p.update(steps=1, repeat=[4])
    elif name == 'glitch':
        p.update(chance=1)
    neutral = dict(amount=0) if name == 'curve_shaper' else dict(mix=0)
    def probe(x, y, sr, vp):
        tone = H.sine(sr=sr, seconds=.1, channels=x.shape[1])
        out = render(name, tone, sr, dict(p, **neutral)).audio
        freq = H.fundamental_frequency(out, sr, low_hz=900, high_hz=1100)
        return dict(passed=abs(freq-1000) < 1 and abs(H.rms_dbfs(out)-H.rms_dbfs(tone)) < .01,
                    frequency_hz=freq)
    H.assert_common_tests(name, params=p, neutral=neutral, latency_params=dict(p, **neutral),
                          seconds=.025, sr_probe=probe)
