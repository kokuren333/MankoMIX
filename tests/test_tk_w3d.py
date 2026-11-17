"""W3d: adaptive release, composite wiring and T12-01 master invariants."""
import copy
import itertools
import json

import numpy as np
import pytest
from scipy import ndimage

from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ChainError, ParamError
from mankomix.dsp.reference import truepeak as TP
from mankomix.dspx.bb import dynamics as D
from mankomix.dspx.procs import adaptive_limiter as A, limiter_chain as L
from tests import toolimpl_harness as H


def params(**kw):
    return P.validate_params('adaptive_limiter', kw)


def render(x, sr=48000, **kw):
    return E.render_chain(x, sr, [{'type': 'adaptive_limiter', 'params': kw}], stage='track')


def fixed_reference(x, sr, p, release_ms=None):
    """Independent fixed-release recurrence and explicit order-statistics path.

    release_ms=600 is a comparison reference, not an out-of-range public
    release_min_ms setting. No adaptive state/helper is used here.
    """
    release = p['release_min_ms'] if release_ms is None else release_ms
    a = np.exp(-1/(release*.001*sr))
    x = x.copy() if p['drive_db'] == 0 else x*10**(p['drive_db']/20)
    ceiling = 10**(p['ceiling_db']/20)

    def detector(y):
        peak = np.column_stack([TP.peak_per_sample(y[:, c:c+1], p['oversample']) for c in range(y.shape[1])])
        return peak+p['stereo_link']*(np.max(peak, axis=1, keepdims=True)-peak)

    def smooth(required):
        r = round(p['lookahead_ms']*sr/1000)//2
        low = ndimage.minimum_filter1d(required, size=2*r+1, axis=0, mode='constant', cval=1.)
        w = np.hanning(2*r+3)[1:-1]
        w /= np.sum(w)
        return np.minimum(required, 1-ndimage.convolve1d(1-low, w, axis=0, mode='constant', cval=0.))

    demand = np.maximum(0, 20*np.log10(np.maximum(detector(x), 1e-30)/ceiling))
    slow, previous = np.empty_like(demand), np.zeros(x.shape[1])
    for i, row in enumerate(demand):
        previous = np.maximum(row*(1-p['transient']), previous*a)
        slow[i] = previous
    slow_gain = 10**(-slow/20)
    required = np.minimum(1, 10**(-demand/20)/slow_gain)
    held, previous = np.empty_like(required), np.zeros(x.shape[1])
    for i, row in enumerate(1-required):
        # Existing smooth_python is a one-pole toward demand, not a peak hold.
        previous = np.where(row > previous, row, a*previous+(1-a)*row)
        held[i] = previous
    y = x*slow_gain*smooth(1-held)
    for _ in range(2):
        y *= smooth(np.minimum(1, ceiling/np.maximum(detector(y), 1e-30)))
    return y


@pytest.mark.parametrize('factor', [1, 2, 4, 8])
@pytest.mark.parametrize('link', [0, .35, 1])
def test_fixed_release_reference(factor, link):
    rng = np.random.Generator(np.random.PCG64(11))
    x = rng.normal(0, .7, (2400, 2))
    p = params(adapt=0, oversample=factor, stereo_link=link)
    y = A.adaptive_limiter(x, 48000, p)[0]
    ref = fixed_reference(x, 48000, p)
    assert np.max(np.abs(y-ref)) < 2e-13


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_low_frequency_distortion_and_fixed_comparison(sr):
    t = np.arange(round(1.2*sr))/sr
    x = (10**(5/20)*np.sin(2*np.pi*50*t))[:, None]
    p = params()
    y, _, st = A.adaptive_limiter(x, sr, p)
    steady = slice(round(.6*sr), round(1.1*sr))
    metric = H.thd(y[steady], sr, 50)['thd_db']
    fixed = H.thd(fixed_reference(x, sr, p)[steady], sr, 50)['thd_db']
    # Exclude zero crossings when recovering gain from the audio.
    active = np.abs(x[steady, 0]) > .1
    gr = 20*np.log10(np.abs(x[steady, 0][active]/y[steady, 0][active]))
    ripple = float(np.ptp(gr))
    assert metric <= -50 and ripple <= .5
    assert metric < fixed
    assert abs(float(np.max(gr))-6) < .1
    assert st['release_ms_max'] <= 600
    print(json.dumps({'sr': sr, 'adaptive_thd_db': metric, 'fixed_30_thd_db': fixed,
                      'gr_ripple_db': ripple, 'detector_peak_dbfs': st['detector_peak_dbfs']}, sort_keys=True))


def test_isolated_click_recovery_and_fixed_600_loss():
    sr = 48000
    x = (.02*np.sin(2*np.pi*1000*np.arange(round(.4*sr))/sr))[:, None]
    at = round(.1*sr)
    x[at] = 10**(5/20)
    y = A.adaptive_limiter(x, sr, params())[0]
    fixed = fixed_reference(x, sr, params(), release_ms=600)
    # Recovery is 95% decay of the initial 6 dB GR: residual <=0.3 dB.
    active = np.abs(x[:, 0]) > .005
    gr = np.zeros(len(x))
    gr[active] = 20*np.log10(np.abs(x[active, 0]/y[active, 0]))
    last = np.flatnonzero((np.arange(len(x)) >= at) & (gr > .3))[-1]
    recovery = (last-at)/sr*1000
    window = slice(at+1, at+round(.1*sr))
    loss = 20*np.log10(np.linalg.norm(x[window])/np.linalg.norm(y[window]))
    fixed_loss = 20*np.log10(np.linalg.norm(x[window])/np.linalg.norm(fixed[window]))
    assert recovery <= 30*3
    assert loss < fixed_loss
    print(json.dumps({'click_recovery_ms': recovery, 'click_loss_100ms_db': loss,
                      'fixed_600_loss_100ms_db': fixed_loss}, sort_keys=True))


@pytest.mark.parametrize('factor', [1, 2, 4, 8])
def test_detection_ceiling_property(factor):
    rng = np.random.Generator(np.random.PCG64(9))
    worst = -np.inf
    for i in range(8):
        sr = [44100, 48000, 96000][i % 3]
        n = 1400
        noise = rng.normal(0, .7, (n, 1+i % 2))
        tone = np.sin(2*np.pi*.245*np.arange(n)+.7)[:, None]
        x = noise+tone
        x[0] = 3
        x[-1] = -3
        mn = rng.uniform(5, 200)
        p = params(oversample=factor, ceiling_db=float(rng.uniform(-24, 0)),
                   drive_db=float(rng.uniform(0, 24)), lookahead_ms=float(rng.uniform(1, 10)),
                   release_min_ms=mn, release_max_ms=float(rng.uniform(max(100, mn), 3000)),
                   adapt=float(rng.uniform()), transient=float(rng.uniform()), stereo_link=float(rng.uniform()))
        y, _, st = A.adaptive_limiter(x, sr, p)
        excess = TP.true_peak_dbtp(y, factor=factor)-p['ceiling_db']
        worst = max(worst, excess)
        assert excess <= .1
        assert np.isfinite(y).all() and y.shape == x.shape
        assert st['true_peak_dbtp'] == TP.true_peak_dbtp(y, sr)
        assert st['true_peak_guaranteed'] is False
    print(json.dumps({'factor': factor, 'worst_ceiling_excess_db': worst}, sort_keys=True))


@pytest.mark.parametrize('factor', [1, 2, 4, 8])
def test_below_ceiling_is_bit_identical(factor):
    rng = np.random.Generator(np.random.PCG64(7))
    x = rng.normal(0, .01, (2400, 2))
    x[0, 0] = -0.
    out = render(x, oversample=factor)
    assert out.audio.tobytes() == x.tobytes()


@pytest.mark.parametrize('block', [64, 1024, 4019])
def test_causal_state_block_invariance(block):
    rng = np.random.Generator(np.random.PCG64(22))
    peak = np.abs(rng.normal(size=(4019, 2)))
    demand = np.maximum(0., 20*np.log10(np.maximum(peak, 1e-30)))
    whole = D.AdaptiveReleaseState(48000).process(demand, peak)
    state = D.AdaptiveReleaseState(48000)
    parts = [state.process(demand[i:i+block], peak[i:i+block]) for i in range(0, len(peak), block)]
    for j in range(3):
        assert whole[j].tobytes() == np.concatenate([part[j] for part in parts]).tobytes()


def test_bounded_context_and_prefix_replay():
    rng = np.random.Generator(np.random.PCG64(30))
    x = rng.normal(0, .8, (9000, 2))
    p = params()
    full = A.adaptive_limiter(x, 48000, p)[0]
    end = 6000
    prefix = A.adaptive_limiter(x[:end], 48000, p)[0]
    margin = A.latency_samples(48000, p)
    assert full[:end-margin].tobytes() == prefix[:end-margin].tobytes()
    other = x.copy()
    other[end:] *= 10
    assert full[:end-margin].tobytes() == A.adaptive_limiter(other, 48000, p)[0][:end-margin].tobytes()


def test_stereo_link_and_symmetry():
    rng = np.random.Generator(np.random.PCG64(6))
    x = rng.normal(0, .7, (2400, 2))*[1, .03]
    linked = render(x).audio
    unlinked = render(x, stereo_link=0).audio
    assert unlinked[:, 1].tobytes() == x[:, 1].tobytes()
    assert np.linalg.norm(linked[:, 1]) < np.linalg.norm(unlinked[:, 1])
    assert render(x[:, ::-1]).audio[:, ::-1].tobytes() == linked.tobytes()


def manual_children(p):
    steps = []
    if p['comp_on']:
        steps.append({'type': 'compressor', 'params': {'threshold_db': p['comp_threshold_db'],
            'ratio': 2, 'knee_db': 6, 'attack_ms': 30, 'release_ms': 200}})
    if p['clip_on']:
        steps.append({'type': 'clipper', 'params': {'mode': 'soft', 'softness': .3,
            'ceiling_db': p['clip_ceiling_db'], 'drive_db': p['clip_drive_db']}})
    if p['hf_on']:
        steps.append({'type': 'dynamic_eq', 'params': {'shape': 'high_shelf',
            'freq_hz': p['hf_freq_hz'], 'threshold_db': p['hf_threshold_db'], 'range_db': p['hf_range_db']}})
    if p['peak_on']:
        steps.append({'type': 'adaptive_limiter', 'params': {'ceiling_db': p['peak_ceiling_db'],
            'release_min_ms': p['peak_release_ms']}})
    return steps


@pytest.mark.parametrize('on', list(itertools.product([False, True], repeat=4)))
def test_composite_manual_equivalence_and_records(on):
    overrides = dict(zip(('comp_on', 'clip_on', 'hf_on', 'peak_on'), on))
    p = P.validate_params('limiter_chain', overrides)
    source = {'type': 'limiter_chain', 'id': 'stack', 'params': overrides}
    x = np.random.Generator(np.random.PCG64(3)).normal(0, .7, (1800, 2))
    out = E.render_chain(x, 48000, [source], stage='bus')
    manual = E.render_chain(x, 48000, manual_children(p), stage='bus')
    assert out.audio.tobytes() == manual.audio.tobytes()
    if any(on):
        assert [s['type'] for s in out.steps] == [s['type'] for s in manual.steps]
        assert len(out.steps) == sum(on)
    else:
        assert out.audio.tobytes() == x.tobytes()
    assert all(s['composite_of'] == source for s in out.steps)
    assert [s['id'] for s in out.steps] == [f'stack.{i+1}' for i in range(len(out.steps))]


@pytest.mark.parametrize('child_index,bad', [(0, {'ratio': 31}), (1, {'softness': 2}),
                                           (2, {'freq_hz': 30000}), (3, {'release_min_ms': 201})])
def test_composite_children_revalidated(monkeypatch, child_index, bad):
    from mankomix.dspx import registry
    original = registry.composites
    def expansions():
        table = original()
        def corrupt(p):
            children = L.expand(p)
            children[child_index]['params'].update(bad)
            return children
        table['limiter_chain'] = corrupt
        return table
    monkeypatch.setattr(registry, 'composites', expansions)
    with pytest.raises(ParamError):
        E.validate_chain([{'type': 'limiter_chain', 'params': {'hf_on': True}}], 'bus')


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_t12_master_final_limiter_and_transparency(sr):
    rng = np.random.Generator(np.random.PCG64(19))
    final = {'id': 'final', 'type': 'limiter', 'params': {'ceiling_dbtp': -1}}
    adaptive = {'id': 'adaptive', 'type': 'adaptive_limiter'}
    quiet = rng.normal(0, .015, (3000, 2))
    a = E.render_chain(quiet, sr, [final], stage='master')
    b = E.render_chain(quiet, sr, [adaptive, final], stage='master')
    assert a.audio.tobytes() == b.audio.tobytes()
    loud = quiet*50+np.sin(2*np.pi*.24*np.arange(len(quiet)))[:, None]
    for chain in ([final], [{**adaptive, 'params': {'drive_db': 12}}, final]):
        out = E.render_chain(loud, sr, chain, stage='master')
        assert out.steps[-1]['type'] == 'limiter'
        assert TP.true_peak_dbtp(out.audio, sr) <= -1+.05
        assert out.steps[-1]['stats']['out_true_peak_dbtp'] <= -1
    with pytest.raises(ChainError, match='S-06'):
        E.validate_chain([final, adaptive], 'master')


def test_master_slots_and_chain_restriction():
    from mankomix.dspx.registry import time_varying_types
    assert 'adaptive_limiter' in time_varying_types()
    for kind in ('adaptive_limiter', 'limiter_chain'):
        assert P.describe(kind)['implemented'] is True
        assert P.describe(kind)['backends'] == ['reference']
        assert P.describe(kind)['offline_only'] is False
    assert P.describe('adaptive_limiter')['master_slot'] == 5
    assert P.describe('limiter_chain')['master_slot'] == 5
    with pytest.raises((ParamError, ChainError)):
        E.validate_chain([{'type': 'limiter_chain'}], 'master')
    with pytest.raises(ChainError, match='S-06'):
        E.validate_chain(manual_children(P.validate_params('limiter_chain', {'hf_on': True})), 'master')


def acoustic_probe(x, y, sr, p):
    frequency = H.fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
    # Measure the declared fixed-release tau independently at every CT rate.
    d = np.concatenate([np.full(round(.01*sr), 6.), np.zeros(round(.04*sr))])[:, None]
    state = D.AdaptiveReleaseState(sr, 30, 600, 0, 0)
    trace = state.process(d, np.ones_like(d))[0]
    at = round(.01*sr)
    actual = float(trace[at+round(.03*sr)-1, 0]/trace[at-1, 0])
    return {'frequency_hz': frequency, 'release_30ms_remaining': actual,
            'passed': abs(frequency-1000) <= 1 and abs(actual-np.exp(-1)) < .001}


def test_adaptive_common_contract():
    H.assert_common_tests('adaptive_limiter', neutral={'ceiling_db': 0}, seconds=.05,
        sr_probe=acoustic_probe, declared_latency=A.latency_samples,
        latency_probe=lambda x, sr, p, **kw: A.adaptive_limiter(x, sr, p, compensate=False)[0],
        invalid_params=[{'release_min_ms': 200, 'release_max_ms': 100}])


def test_composite_common_contract():
    off = {'comp_on': False, 'clip_on': False, 'hf_on': False, 'peak_on': False}
    p = P.validate_params('limiter_chain', {})
    def raw(x, sr, unused, **kw):
        y = E.render_chain(x, sr, L.expand(p), stage='track').audio
        return D.delay_audio(y, A.latency_samples(sr, params()))
    H.assert_common_tests('limiter_chain', neutral=off, seconds=.05,
        sr_probe=acoustic_probe, declared_latency=lambda sr, p: A.latency_samples(sr, params()),
        latency_probe=raw)


ADAPTIVE_FLOATS = {
    'ceiling_db': (-24, 0, -1), 'drive_db': (0, 24, 0), 'lookahead_ms': (1, 10, 4),
    'release_min_ms': (5, 200, 30), 'release_max_ms': (100, 3000, 600),
    'adapt': (0, 1, .7), 'transient': (0, 1, .3), 'stereo_link': (0, 1, 1)}
CHAIN_FLOATS = {
    'comp_threshold_db': (-60, 0, -12), 'clip_ceiling_db': (-24, 0, -1.5),
    'clip_drive_db': (0, 24, 0), 'hf_freq_hz': (2000, 16000, 8000),
    'hf_threshold_db': (-80, 0, -24), 'hf_range_db': (-24, 0, -4),
    'peak_ceiling_db': (-24, 0, -1), 'peak_release_ms': (5, 200, 30)}


@pytest.mark.parametrize('kind,expected', [('adaptive_limiter', ADAPTIVE_FLOATS), ('limiter_chain', CHAIN_FLOATS)])
def test_declared_defaults_bounds_and_actual_endpoints(kind, expected):
    definition = P.describe(kind)
    definitions = {d['id']: d for d in definition['params']}
    p = P.validate_params(kind, {})
    x = np.random.Generator(np.random.PCG64(4)).normal(0, 1, (600, 2))
    assert E.render_chain(x, 48000, [{'type': kind}], stage='bus').audio.tobytes() == E.render_chain(
        x, 48000, [{'type': kind, 'params': p}], stage='bus').audio.tobytes()
    for pid, (lo, hi, default) in expected.items():
        d = definitions[pid]
        assert (d['min'], d['max'], d['default']) == (lo, hi, default)
        for value in (lo, hi):
            pp = {pid: value}
            if kind == 'limiter_chain':
                pp['hf_on'] = True
            out = E.render_chain(x, 48000, [{'type': kind, 'params': pp}], stage='bus')
            assert np.isfinite(out.audio).all()
        for value in (lo-1, hi+1):
            with pytest.raises(ParamError):
                E.validate_chain([{'type': kind, 'params': {pid: value}}], 'bus')
    if kind == 'adaptive_limiter':
        assert p == dict({k: v[2] for k, v in ADAPTIVE_FLOATS.items()}, oversample=4)
        for value in [1, 2, 4, 8]:
            assert np.isfinite(render(x, oversample=value).audio).all()
    else:
        assert p == dict({k: v[2] for k, v in CHAIN_FLOATS.items()}, comp_on=True,
                         clip_on=True, hf_on=False, peak_on=True)


def test_control_validation_and_empty_audio():
    for kw in ({'release_min_ms': 201}, {'adapt': 2}, {'transient': -1}):
        with pytest.raises(ParamError):
            params(**kw)
    with pytest.raises(ParamError):
        params(release_min_ms=200, release_max_ms=100)
    with pytest.raises(ParamError):
        D.AdaptiveReleaseState(48000).process(np.ones((2, 1)), np.ones((3, 1)))
    y, _, st = A.adaptive_limiter(np.empty((0, 2)), 48000, params())
    assert y.shape == (0, 2) and st['true_peak_dbtp'] is None


def test_control_safety_and_zero_state():
    rng = np.random.Generator(np.random.PCG64(52))
    required = rng.uniform(0, 1, (2000, 2))
    for ms in (0, 1, 4, 10):
        g = D.bounded_lookahead_gain(required, 48000, ms)
        assert np.all(g >= 0) and np.all(g <= required)
        ones = np.ones_like(required)
        assert D.bounded_lookahead_gain(ones, 48000, ms).tobytes() == ones.tobytes()
        assert not np.any(D.bounded_lookahead_gain(np.zeros_like(required), 48000, ms))
    for bad in (np.array([[1.1]]), np.array([[-.1]]), np.array([[np.nan]]), np.ones(3)):
        with pytest.raises(ParamError):
            D.bounded_lookahead_gain(bad, 48000, 4)
    d = np.zeros((1000, 2))
    slow, tau, persist = D.AdaptiveReleaseState(48000).process(d, d)
    assert not np.any(slow) and not np.any(persist) and np.all(tau == 30)


def test_measurements_reuse_existing_function_and_no_mutation(monkeypatch):
    calls = []
    original = TP.true_peak_dbtp
    def observed(x, sr=None, factor=None):
        calls.append((sr, factor))
        return original(x, sr, factor)
    monkeypatch.setattr(TP, 'true_peak_dbtp', observed)
    x = np.random.Generator(np.random.PCG64(10)).normal(0, .8, (1800, 2))
    before, p = x.tobytes(), params(drive_db=3)
    source = copy.deepcopy(p)
    y, _, st = A.adaptive_limiter(x, 48000, p)
    second = A.adaptive_limiter(x, 48000, p)
    assert st['true_peak_dbtp'] == original(y, 48000)
    assert st['detector_peak_dbfs'] == original(y, factor=4)
    assert (48000, None) in calls and (None, 4) in calls
    assert second[0].tobytes() == y.tobytes() and second[2] == st
    assert x.tobytes() == before and p == source
