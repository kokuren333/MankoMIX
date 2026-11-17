"""C7e closure: compensated BBD clock, correlated voices, generic contracts."""
import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain
from mankomix.dsp.errors import ParamError
from mankomix.dspx import registry


def measure(label, **values):
    print(label+': '+json.dumps(values, sort_keys=True))


def render(kind, x, sr, **params):
    return render_chain(x, sr, [dict(type=kind, params=params)], stage='track').audio


def test_bbd_dispersion_correction_from_independent_continuous_cascade():
    from mankomix.dspx.procs.bbd_delay import compensated_delay
    # Independently convolve the analog impulse on a fine normalized time grid.
    # The continuous limit isolates DC delay and the dispersive residual;
    # the finite-clock correction is independently checked by DT2 below.
    b, a = signal.butter(5, 1, analog=True)
    r, poles, _ = signal.residue(b, a)
    step = .001
    t = np.arange(0, 65, step)
    impulse = np.real(np.exp(t[:, None]*poles).dot(r))
    traversal = signal.fftconvolve(impulse, impulse)*step
    response = np.zeros_like(t); response[0] = 1/step
    modes = []
    for _ in range(5):
        response = signal.fftconvolve(response, traversal)[:len(t)]*step
        i = int(np.argmax(response))
        offset = .5*(response[i-1]-response[i+1])/(response[i-1]-2*response[i]+response[i+1])
        modes.append((i+offset)*step)
    mean_phase = (modes[-1]-modes[0])/4
    dc_phase = float(2*np.real(np.sum(-1/poles)))
    d = float(compensated_delay(40, 8000, 1024, .5))
    cutoff = min(.18*1024*8000/(2*d), .18*8000)
    dc_samples = dc_phase*8000/(2*np.pi*cutoff)
    residual_samples = (mean_phase-dc_phase)*8000/(2*np.pi*cutoff)
    assert dc_samples > 5 and residual_samples > .2
    assert abs(d+dc_samples+residual_samples-40) < 1e-6
    measure('bbd_analog_clock_derivation', peak_modes=modes, dc_phase=dc_phase,
            mean_phase=mean_phase, dc_samples=dc_samples, residual_samples=residual_samples)


@pytest.mark.parametrize('tone', [0, .5, 1])
def test_unit_clock_filter_compensation_against_independent_event_lattice(tone):
    from mankomix.dspx.bb.bbd import BBDPlan
    from mankomix.dspx.procs.bbd_delay import repeat_filter_delay
    period = 128
    transport = 16*period
    x = np.zeros((10*transport, 1)); x[0] = 1
    plan = BBDPlan(len(x), period, transport, stages=32, tone=tone)
    peaks = []
    for _ in range(5):
        x = plan.process(x)
        i = int(np.argmax(x[:, 0]))
        y = x[:, 0]
        offset = .5*(y[i-1]-y[i+1])/(y[i-1]-2*y[i]+y[i+1])
        peaks.append((i+offset)/period)
    measured = (peaks[-1]-peaks[0])/4-16
    analytic = repeat_filter_delay(.12+.12*tone)
    assert abs(measured-analytic) < 1e-5
    measure('bbd_unit_clock', tone=tone, event_cycles=measured, analytic_cycles=analytic)


@pytest.mark.parametrize('sr', [8000, 44100, 48000, 96000])
def test_bbd_dt2_five_repeat_mean_at_rates_and_duration_endpoints(sr):
    rows = []
    for ms in (5, 100, 300, 1200):
        target = ms*sr/1000
        x = np.zeros((int(6*target+100), 1)); x[0] = 1
        y = render('bbd_delay', x, sr, time_ms=ms, stages=1024,
                   compander=False, feedback=.5, mix=1)[:, 0]
        peaks = signal.find_peaks(abs(y), height=np.max(abs(y))*1e-4,
                                  distance=int(.75*target))[0][:5]
        # 統括の判断 D-21(a): DC group-delay compensation in the clock,
        # then the mean spacing of the first five repeats, target +/-1 sample.
        assert len(peaks) == 5
        mean = float(np.mean(np.diff(peaks)))
        assert abs(mean-target) <= 1, (sr, ms, peaks, mean)
        rows.append(dict(time_ms=ms, peaks=peaks.tolist(), mean_samples=mean, target_samples=target))
    measure('bbd_DT2', sr=sr, rows=rows)


@pytest.mark.parametrize('stages', [1024, 2048, 4096, 8192])
@pytest.mark.parametrize('tone', [0, .5, 1])
@pytest.mark.parametrize('sr', [8000, 96000])
def test_bbd_clock_stage_tone_endpoints(stages, tone, sr):
    from mankomix.dspx.bb.bbd import BBDPlan
    from mankomix.dspx.procs.bbd_delay import compensated_delay
    rows = []
    for ms in (5, 1200):
        target = ms*sr/1000
        delay = compensated_delay(target, sr, stages, tone)
        x = np.zeros((int(6*target+100), 1)); x[0] = 1
        plan = BBDPlan(len(x), sr, delay, stages, tone)
        # Exercise the actual event model on both sides of the cutoff cap.
        peaks = []
        for _ in range(5):
            x = plan.process(x)
            peaks.append(int(np.argmax(abs(x))))
        # 統括の判断 D-21(a).
        mean = float(np.mean(np.diff(peaks)))
        assert abs(mean-target) <= 1
        rows.append(dict(time_ms=ms, mean_samples=mean, target_samples=target))
    measure('bbd_clock_endpoints', sr=sr, stages=stages, tone=tone, rows=rows)


def test_bbd_compensated_clock_tempo_stats_and_short_sample_rate_rejection():
    from mankomix.dspx.procs.bbd_delay import compensated_delay
    x = np.zeros((8000, 1)); x[0] = 1
    p = dict(time_ms=125, feedback=.5, mix=1, compander=False)
    a = render_chain(x, 8000, [dict(type='bbd_delay', params=p)], stage='track')
    assert a.audio.tobytes() == render('bbd_delay', x, 8000, **dict(p, note='1/16', bpm=120)).tobytes()
    assert float(compensated_delay(1000, 8000, 4096, .5)) < 1000
    stats = a.steps[0]['stats']
    assert stats['clock_hz'] == 4096*8000/(2*stats['transport_delay_samples'])
    with pytest.raises(ParamError, match='filter delay'):
        render('bbd_delay', x[:20], 1000, time_ms=5, feedback=0, mix=1)


@pytest.mark.parametrize('model', ['clean', 'bbd', 'dual', 'tri', 'ensemble'])
def test_chorus_coincident_voices_null_against_single_voice_all_widths(model):
    sr = 8000
    x = np.random.Generator(np.random.PCG64(34)).normal(0, .1, (1600, 2))
    reference = render('chorus', x, sr, model=model, voices=1, depth=0, mix=1)
    errors = []
    for width in (0, .5, 1):
        for count in range(1, 5):
            y = render('chorus', x, sr, model=model, voices=count, depth=0, mix=1, width=width)
            error = float(np.max(abs(y-reference)))
            assert error < 1e-12
            errors.append(error)
    measure('chorus_coincident_null', model=model, max_error=max(errors))


def test_chorus_uncorrelated_modulated_voice_rms():
    sr = 8000
    x = np.random.Generator(np.random.PCG64(42)).normal(0, .1, (16000, 2))
    rows = []
    for width in (0, 1):
        levels = []
        for count in range(1, 5):
            y = render('chorus', x, sr, voices=count, depth=1, depth_ms=10, delay_ms=20,
                       width=width, mix=1)
            levels.append(float(10*np.log10(np.mean(y[4000:]**2))))
        assert max(levels)-min(levels) <= 1
        rows.append(dict(width=width, rms_dbfs=levels))
    measure('chorus_modulated_voice_rms', rows=rows)


def test_chorus_correlated_normalization_is_causal_bounded_and_scale_invariant():
    from mankomix.dspx.procs.chorus import mix_voices
    x = np.random.Generator(np.random.PCG64(19)).normal(0, .1, (2000, 2))
    voices = [x, .7*x+np.roll(x, 30, axis=0), np.roll(x, 60, axis=0)]
    routing = np.array([[1, 0], [1, 1], [0, 1.]])
    y = mix_voices(voices, routing, 8000)
    assert np.isfinite(y).all()
    assert np.array_equal(mix_voices([v[:1000] for v in voices], routing, 8000), y[:1000])
    assert np.max(abs(mix_voices([v*1e-4 for v in voices], routing, 8000)-y*1e-4)) < 1e-15
    assert not np.any(mix_voices([np.zeros_like(x)]*3, routing, 8000))
    assert mix_voices([x[:0]]*3, routing, 8000).shape == (0, 2)
    # Opposed voices cancel without an inverse-correlation gain singularity.
    assert not np.any(mix_voices([x, -x], np.ones((2, 2)), 8000))


def test_chorus_normalization_replayed_history_multivoice_feedback():
    from mankomix.dspx.bb.delayfx import render_with_history
    from mankomix.dspx.procs.chorus import chorus
    x = np.random.Generator(np.random.PCG64(26)).normal(0, .1, (1200, 2))
    for model in ('clean', 'bbd'):
        for feedback in (-.5, .5):
            p = P.validate_params('chorus', dict(model=model, voices=4, width=.4,
                                                feedback=feedback, mix=1))
            y = chorus(x, 8000, p)[0]
            excerpt = render_with_history(chorus, x[700:], 8000, p, history=x[:700])[0]
            assert excerpt.tobytes() == y[700:].tobytes()
            assert np.isfinite(y).all()


def mock_modules(tmp_path, monkeypatch, modules):
    directory = tmp_path/'procs'; directory.mkdir()
    for name in reversed(list(modules)):
        (directory/(name+'.py')).touch()
    monkeypatch.setattr(registry, '__file__', str(tmp_path/'registry.py'))
    monkeypatch.setattr(registry, '_TABLES', None)
    calls = []
    def load(name):
        calls.append(name.rsplit('.', 1)[-1])
        return modules[calls[-1]]
    monkeypatch.setattr(registry.importlib, 'import_module', load)
    return calls


def test_registry_collects_generic_hooks_deterministically_and_returns_copies(tmp_path, monkeypatch):
    from mankomix.dspx.procs.curve_shaper import resolve_target_params, patch_schema
    assert registry.param_resolvers()['curve_shaper'] is resolve_target_params
    assert registry.schema_patches()['curve_shaper'] is patch_schema
    fn = lambda p: p
    modules = {name: SimpleNamespace(SPECS=[dict(type='c7e_'+name)], IMPLS={},
               RESOLVE_PARAMS={'c7e_'+name: fn}, SCHEMA_PATCH={'c7e_'+name: fn}) for name in ('z', 'a')}
    calls = mock_modules(tmp_path, monkeypatch, modules)
    resolvers, patches = registry.param_resolvers(), registry.schema_patches()
    assert calls == ['a', 'z']
    assert list(resolvers) == list(patches) == ['c7e_a', 'c7e_z']
    resolvers.clear(); patches.clear()
    assert len(registry.param_resolvers()) == len(registry.schema_patches()) == 2


@pytest.mark.parametrize('hook', ['RESOLVE_PARAMS', 'SCHEMA_PATCH'])
@pytest.mark.parametrize('case', ['duplicate', 'undeclared', 'noncallable'])
def test_registry_rejects_invalid_generic_hooks(tmp_path, monkeypatch, hook, case):
    fn = lambda p: p
    a = SimpleNamespace(SPECS=[dict(type='c7e_a')], IMPLS={})
    b = SimpleNamespace(SPECS=[dict(type='c7e_b')], IMPLS={})
    if case == 'duplicate':
        setattr(a, hook, {'c7e_a': fn}); setattr(b, hook, {'c7e_a': fn})
    else:
        setattr(a, hook, {'unknown' if case == 'undeclared' else 'c7e_a': fn if case == 'undeclared' else None})
    mock_modules(tmp_path, monkeypatch, dict(a=a, b=b))
    with pytest.raises(ImportError):
        registry.specs()


def test_contracts_dispatch_unknown_type_hooks_in_order_without_mutating_input(monkeypatch):
    from mankomix.dspx.params import _f
    kind = 'c7e_generic'
    spec = P.describe('gain')
    spec.update(type=kind, params=[_f('value', None, 0, 10, 1, 'Test value.')])
    monkeypatch.setitem(P.PROCESSORS, kind, spec)
    calls = []
    def resolve(p):
        calls.append(('resolve', copy.deepcopy(p)))
        return dict({'value': 3}, **(p or {}))
    def validate(p):
        calls.append(('validate', copy.deepcopy(p)))
    def patch(p):
        calls.append(('schema', p['properties']['value']['default']))
        p['properties']['value']['default'] = 3
    monkeypatch.setattr(registry, 'param_resolvers', lambda: {kind: resolve})
    monkeypatch.setattr(registry, 'schema_patches', lambda: {kind: patch})
    monkeypatch.setattr(registry, 'cross_validators', lambda: {kind: validate})
    raw = {}
    assert P.validate_params(kind, raw) == {'value': 3}
    assert raw == {} and calls == [('resolve', {}), ('validate', {'value': 3.})]
    assert P.validate_params(kind, {'value': 4}) == {'value': 4}
    assert P.validate_params(kind, None) == {'value': 3}
    before = len(calls)
    with pytest.raises(ParamError):
        P.validate_params(kind, {'value': 11})
    assert len(calls) == before+1 and calls[-1][0] == 'resolve'
    schema = P.graph_schema()
    variant = next(v for v in schema['items']['oneOf'] if v['properties']['type']['const'] == kind)
    assert variant['properties']['params']['properties']['value']['default'] == 3
    assert spec['params'][0]['default'] == 1
    before = len(calls)
    P.validate_params('gain', {})
    assert len(calls) == before


def test_curve_shaper_schema_and_raw_resolution_match_prior_contract():
    # Reconstruct C6b's former contract dispatch over the legacy schema and
    # compare the whole graph. Other units may declare their own new hooks.
    from mankomix.dspx.procs.curve_shaper import resolve_target_params, target_schema
    expected = P._graph_schema_base()
    other_patches = registry.schema_patches()
    for variant in expected['items']['oneOf']:
        variant['properties']['channel'] = {'enum': ['stereo', 'mid', 'side', 'left', 'right']}
        if variant['properties']['type']['const'] == 'curve_shaper':
            params = variant['properties']['params']
            params['allOf'] = target_schema()
            for endpoint in ('lo', 'hi'):
                params['properties'][endpoint].pop('default', None)
        elif variant['properties']['type']['const'] in other_patches:
            other_patches[variant['properties']['type']['const']](variant['properties']['params'])
    assert P.graph_schema() == expected
    for target in ('filter', 'pan', 'width', 'drive', 'crush', 'time'):
        for endpoints in ({}, {'lo': 200, 'hi': 8000} if target in ('filter', 'crush') else {'lo': 0}):
            raw = dict(target=target, **endpoints)
            prior = P._validate_params_base('curve_shaper', resolve_target_params(raw))
            assert P.validate_params('curve_shaper', raw) == prior
