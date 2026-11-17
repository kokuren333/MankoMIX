"""W1a BB-02/03 acceptance and all four single-band dynamics contracts."""
import math
import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dsp.reference import dynamics as original
from mankomix.dsp.reference import ballistics
from mankomix.dsp.reference.stereo import _taps_for
from mankomix.dspx.bb import crossover as C, dynamics as D
from mankomix.dspx.procs.gate import raw_gate
from tests import toolimpl_harness as H

TYPES = ('gate', 'transient_shaper', 'upward_compressor', 'leveler')


def render(kind, x, p=None, sr=16000, stage='track'):
    return E.render_chain(x, sr, [{'type': kind, 'params': p or {}}], stage=stage).audio


def constant(db, sr=16000, seconds=2):
    return (10**(db/20) * np.where(np.arange(round(sr*seconds)) % 2, -1., 1.))[:, None]


def gain(x, y):
    return H.rms_dbfs(y)-H.rms_dbfs(x)


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('edges', [[], [150], [150, 2500], [40, 150, 1000, 5000, 15000]])
def test_linear_reconstruction_and_original_fir(sr, edges):
    x = H.white_noise(-12, sr=sr, seconds=.08, channels=2)
    bands, meta = C.split_bands(x, sr, edges, 'linear')
    assert H.null(x, C.recombine_bands(bands))['peak_dbfs'] <= -120
    if edges:
        taps = _taps_for(min(edges), sr)
        assert taps == meta['fir_taps']
        h = signal.firwin(taps, edges[0], window=('kaiser', signal.kaiser_beta(90)), fs=sr)
        expected = np.column_stack([signal.oaconvolve(c, h)[(taps-1)//2:][:len(x)] for c in x.T])
        np.testing.assert_allclose(bands[0], expected, atol=1e-14, rtol=0)
        d = meta['latency_samples']
        raw, _ = C.split_bands(np.pad(x, ((0, d), (0, 0))), sr, edges, 'linear', compensate=False)
        assert H.null(x, C.recombine_bands(raw)[d:d+len(x)])['peak_dbfs'] <= -120


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('order', [4, 8])
@pytest.mark.parametrize('edges', [[150], [150, 2500], [40, 150, 1000, 5000, 15000]])
def test_minimum_tree_allpass(sr, order, edges):
    # Long impulse includes the entire low-frequency IIR tail. Dense FFT tests
    # DC, crossover neighborhoods and Nyquist, not only a few band centers.
    x = H.impulse(sr=sr, seconds=.5, channels=2)
    bands, _ = C.split_bands(x, sr, edges, order=order)
    y = C.recombine_bands(bands)
    response = np.fft.rfft(y[:, 0])
    error = np.max(np.abs(20*np.log10(np.abs(response))))
    assert error <= .01
    expected = x
    for f in edges:
        lo, hi = C.lr_sos(f, sr, order)
        expected = signal.sosfilt(lo, expected, axis=0) + signal.sosfilt(hi, expected, axis=0)
    assert H.null(expected, y)['peak_dbfs'] <= -120


def test_mb_block_validation_and_scalar_defaults():
    assert C.mb_params()[0]['default'] == [150, 2500]
    assert C.expand_band_params({'crossovers_hz': [150, 2500], 'ratio': []}, {'ratio': 2}) == {'ratio': [2., 2., 2.]}
    assert C.expand_band_params({'crossovers_hz': [], 'ratio': [3]}, {'ratio': 2}) == {'ratio': [3]}
    for p in ({'crossovers_hz': [150, 150]}, {'crossovers_hz': [300, 150]},
              {'crossovers_hz': [19]}, {'crossovers_hz': [20001]},
              {'crossovers_hz': [100]*6}, {'crossovers_hz': [True]}, {'phase': 'other'}):
        with pytest.raises(ParamError):
            C.validate_mb(p)
    with pytest.raises(ParamError):
        C.validate_mb({'crossovers_hz': [7840]}, 16000)
    for v in ([1, 2], [math.nan], 2):
        with pytest.raises(ParamError):
            C.expand_band_params({'crossovers_hz': [], 'ratio': v}, {'ratio': 2})


def test_detector_and_compressor_compatibility():
    x = H.white_noise(-14, sr=16000, seconds=.2, channels=2)
    for linked in (False, True):
        for mode in ('peak', 'rms'):
            p = P.validate_params('compressor', {'stereo_link': linked, 'detector': mode})
            gr = D.compressor_gain(x, 16000, p)
            actual = D.apply_gain(x, -gr, p['makeup_db'])
            expected = original.compressor(x, 16000, p, ballistics_impl='python')[0]
            assert H.null(actual, expected)['peak_dbfs'] <= -120
    assert np.array_equal(D.detector(x, 16000, 'peak', stereo_link=False), np.abs(x))
    assert np.array_equal(D.detector(x, 16000, 'rms', 10, False), original.rms_detector(x, 16000, 10))


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_ballistics_tau_and_stateful_partition(sr):
    target = np.r_[np.full(round(.08*sr), 6.), np.zeros(round(.15*sr))]
    actual = D.smooth_gain(target, sr, 5, 15)
    expected = ballistics.smooth_python(target, ballistics.coef(5, sr), ballistics.coef(15, sr))
    assert actual.tobytes() == expected.tobytes()
    for size in (64, 1024):
        smoother = D.GainSmoother(sr, 5, 15)
        split = np.concatenate([smoother.process(target[i:i+size]) for i in range(0, len(target), size)])
        assert split.tobytes() == actual.tobytes()
    assert abs(actual[round(.005*sr)-1] / 6 - (1-math.exp(-1))) < .002
    end = round(.08*sr)
    assert abs(actual[end+round(.015*sr)-1] / actual[end-1] - math.exp(-1)) < .002
    follower = D.envelope(target, sr, 5, 15)
    assert np.array_equal(follower, actual)
    fast, slow, release = D.dual_envelope(target, sr, 5, 15, 50)
    assert fast[round(.005*sr)-1] > slow[round(.005*sr)-1]
    assert release[-1] > fast[-1]


def test_program_release_and_gate_partition():
    sr = 16000
    targets = np.r_[np.full(1600, 12.), np.zeros(3200)]
    adaptive = D.GainSmoother(sr, 1, 50, program_release=(10, 200, 12))
    y = adaptive.process(targets)
    fast = D.smooth_gain(targets, sr, 1, 10)
    slow = D.smooth_gain(targets, sr, 1, 200)
    assert fast[2000] < y[2000] < slow[2000]
    other = D.GainSmoother(sr, 1, 50, program_release=(10, 200, 12))
    assert np.array_equal(y, np.concatenate([other.process(targets[i:i+64]) for i in range(0, len(targets), 64)]))
    p = P.validate_params('gate', {})
    levels = np.r_[np.full(300, -60), np.full(300, -30), np.full(2000, -60)][:, None]
    full = D.GateState(sr, p).process(levels)
    for size in (64, 1024):
        state = D.GateState(sr, p)
        chunks = [state.process(levels[i:i+size]) for i in range(0, len(levels), size)]
        for index in (0, 1):
            assert np.array_equal(np.concatenate([v[index] for v in chunks]), full[index])


def test_static_computers_independent_expected_values():
    levels = np.array([-84., -66., -60., -48., -36., -30., -24., -12., 0.])
    up = D.upward_gain_db(levels, -30, 2, 6, -60, 0)
    np.testing.assert_allclose(up, [0, 3, 6, 6, 3, 0, 0, 0, 0])
    np.testing.assert_allclose(D.downward_gain_db(levels, -24, 4),
                               np.minimum(0, (-24-levels)*.75))
    np.testing.assert_allclose(D.expander_gain_db(levels, -30, 4, -40, 0),
                               np.maximum(-40, np.minimum(0, (levels+30)*3)))
    knee = D.upward_gain_db(np.array([-33., -30., -27.]), -30, 2, 24, -60, 6)
    np.testing.assert_allclose(knee, [1.5, .375, 0])


@pytest.mark.parametrize('kind', TYPES)
def test_declarations_defaults_and_all_numeric_endpoints(kind):
    definition = P.describe(kind)
    assert definition['implemented'] and definition['master_slot'] == 2
    assert definition['stages'] == ['track', 'bus', 'master']
    assert definition['backends'] == ['reference'] and not definition['offline_only']
    defaults = {s['id']: s['default'] for s in definition['params']}
    assert P.validate_params(kind, {}) == defaults
    x = constant(-30, seconds=.03)
    assert np.isfinite(render(kind, x)).all()
    for spec in definition['params']:
        values = [spec['min'], spec['max']] if spec['type'] == 'float' else spec.get('choices', [False, True])
        for value in values:
            p = {spec['id']: value}
            if kind == 'leveler' and spec['id'] == 'high_threshold_db':
                p['low_threshold_db'] = min(-34, value-3)
            if kind == 'leveler' and spec['id'] == 'low_threshold_db':
                if value > -3:
                    with pytest.raises(ParamError):
                        render(kind, x, p)
                    continue
                p['high_threshold_db'] = max(-14, value+3)
            if spec['id'] == 'key_hi_hz' and value == 20000:
                assert np.isfinite(render(kind, x, p, sr=48000)).all()
            else:
                assert np.isfinite(render(kind, x, p)).all()


@pytest.mark.parametrize('kind', TYPES)
def test_common_ct1_through_ct8(kind):
    neutrals = {'gate': {'ratio': 1}, 'transient_shaper': {'attack_db': 0, 'sustain_db': 0},
                'upward_compressor': {'ratio': 1}, 'leveler': {'up_ratio': 1, 'down_ratio': 1}}
    def sr_probe(x, y, sr, params):
        # Default -20 dBFS peak tone lies in each neutral static region.
        # Measure settled unity plus frequency, rather than only finiteness.
        start = round(.08*sr)
        measured = gain(x[start:], y[start:])
        f = H.fundamental_frequency(y[start:], sr, low_hz=900, high_hz=1100)
        return {'passed': abs(measured) < .1 and abs(f-1000) < 1,
                'gain_db': measured, 'frequency_hz': f}
    extra = {}
    if kind == 'gate':
        extra = {'latency_params': {'ratio': 1, 'lookahead_ms': 5},
                 'declared_latency': lambda sr, p: round(sr*p['lookahead_ms']/1000),
                 'latency_probe': lambda x, sr, p, **kw: raw_gate(x, sr, p)[0]}
    if kind == 'leveler':
        extra['invalid_params'] = [{'low_threshold_db': -15, 'high_threshold_db': -14}]
    result = H.assert_common_tests(kind, neutral=neutrals[kind], seconds=.15, sr_probe=sr_probe, **extra)
    assert all(r['passed'] for r in result.values())


@pytest.mark.parametrize('kind', ['upward_compressor', 'leveler', 'gate'])
def test_rendered_static_characteristics(kind):
    for level in (-84, -66, -60, -48, -46, -45, -44, -40, -36, -34, -32, -30, -28, -24, -17, -14, -11, -6):
        x = constant(level)
        p = {'detector': 'peak'} if kind == 'upward_compressor' else {}
        y = render(kind, x, p)
        measured = gain(x[-1600:], y[-1600:])
        if kind == 'gate':
            below = -45-level
            demand = below if below >= 1.5 else ((below+1.5)**2/6 if below > -1.5 else 0)
            expected = max(-40, -3*demand)
        elif kind == 'upward_compressor':
            b = -30-level
            demand = b if b >= 3 else ((b+3)**2/12 if b > -3 else 0)
            f = np.clip((level+72)/12, 0, 1)
            expected = min(6, .5*demand)*f*f*(3-2*f)
        else:
            b = -34-level
            up = b if b >= 3 else ((b+3)**2/12 if b > -3 else 0)
            f = np.clip((level+72)/12, 0, 1)
            over = level+14
            down = over if over >= 3 else ((over+3)**2/12 if over > -3 else 0)
            expected = min(6, .5*up)*f*f*(3-2*f) - (2/3)*down
        assert measured == pytest.approx(expected, abs=.3), (kind, level, measured, expected)


def test_exact_neutral_regions_and_noise_floor():
    sr = 16000
    for kind, db in [('gate', -30), ('upward_compressor', -18), ('leveler', -22)]:
        x = H.sine(1000, db, sr=sr, seconds=.3)
        y = render(kind, x)
        assert x[-1600:].tobytes() == y[-1600:].tobytes()
    x = H.white_noise(-84, sr=sr, seconds=.5)
    assert abs(gain(x, render('upward_compressor', x))) <= .1
    for kind, p in [('gate', {'ratio': 1}), ('transient_shaper', {}),
                    ('upward_compressor', {'ratio': 1}), ('leveler', {'up_ratio': 1, 'down_ratio': 1})]:
        assert x.tobytes() == render(kind, x, p).tobytes()


def test_gate_hysteresis_hold_release_lookahead_and_keys():
    sr = 16000
    p = P.validate_params('gate', {})
    levels = np.r_[np.full(100, -50), np.tile(np.r_[np.full(100, -44), np.full(100, -46)], 10)][:, None]
    _, states = D.GateState(sr, p).process(levels)
    assert np.count_nonzero(np.diff(states[:, 0] > 0)) == 1
    x = np.concatenate([constant(-30, seconds=.1), constant(-70, seconds=.8)])
    y = render('gate', x)
    trace = 20*np.log10(np.abs(y[:, 0]/x[:, 0]))
    boundary = 1600
    first = np.flatnonzero(trace[boundary:] < -1e-10)[0]
    assert first/sr*1000 == pytest.approx(50, abs=5)
    tau = np.flatnonzero(trace[boundary+first:] <= -40*(1-math.exp(-1)))[0]/sr*1000
    assert tau == pytest.approx(150, rel=.1)
    burst = np.r_[np.zeros(1600), np.full(1600, .1), np.zeros(1600)][:, None]
    ahead = render('gate', burst, {'lookahead_ms': 5})
    assert gain(burst[1600:1680], ahead[1600:1680]) >= -.1
    for bad in ({'key_lo_hz': 1000, 'key_hi_hz': 500}, {'key_hi_hz': 8000}):
        with pytest.raises(ParamError):
            render('gate', burst, bad)
    # A low-frequency key below a highpass must close the gate.
    low = H.sine(50, -20, sr=sr, seconds=1.5)
    assert gain(low[-1600:], render('gate', low, {'key_lo_hz': 1500})[-1600:]) < -30


def test_transient_burst_attack_sustain_and_level_independence():
    sr = 16000
    x = H.tone_burst(sr=sr, seconds=.6)
    for params in ({'attack_db': 6}, {'sustain_db': 6}, {'sustain_db': -6}):
        y = render('transient_shaper', x, params)
        attack = H.peak_dbfs(y[:160])-H.peak_dbfs(x[:160])
        sustain = gain(x[1600:4800], y[1600:4800])
        if 'attack_db' in params:
            assert attack == pytest.approx(6, abs=1)
            assert abs(gain(x[3200:], y[3200:])) <= .5
        else:
            assert sustain == pytest.approx(params['sustain_db'], abs=1.5)
            assert abs(attack) <= .5
        quiet = render('transient_shaper', x*.1, params)
        assert gain(x*.1, quiet) == pytest.approx(gain(x, y), abs=.3)
        assert H.peak_dbfs(quiet[:160])-H.peak_dbfs(x[:160]*.1) == pytest.approx(attack, abs=.3)
    tone = H.sine(1000, -12, sr=sr, seconds=.5)
    for params in ({'attack_db': 6}, {'sustain_db': 6}, {'sustain_db': -6}):
        assert abs(gain(tone[3200:], render('transient_shaper', tone, params)[3200:])) <= .1


def test_master_slot_order_and_tv_registration():
    from mankomix.dspx.registry import time_varying_types
    assert set(TYPES) <= time_varying_types()
    for kind in TYPES:
        E.validate_chain([{'type': 'eq'}, {'type': kind}, {'type': 'limiter'}], stage='master')
        with pytest.raises(ChainError):
            E.validate_chain([{'type': 'limiter'}, {'type': kind}], stage='master')


@pytest.mark.parametrize('freq', [50, 100, 250, 440, 1000, 3000])
def test_transient_steady_carrier_is_not_a_transient(freq):
    x = H.sine(freq, -12, sr=16000, seconds=1)
    for p in ({'attack_db': 6}, {'sustain_db': 6}, {'sustain_db': -6}):
        y = render('transient_shaper', x, p)
        assert abs(gain(x[8000:], y[8000:])) <= .1


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('kind', ['upward_compressor', 'leveler'])
def test_processor_gain_time_constants(sr, kind):
    first = round(.05*sr)
    second = round(.3*sr)
    if kind == 'upward_compressor':
        levels, params, attack_ms, release_ms = [-100, -50, -36], {'detector': 'peak'}, 20, 200
        high, low = 6., 3.
    else:
        levels, params, attack_ms, release_ms = [-24, -6, -10], {'rms_window_ms': 1}, 15, 250
        high, low = -16/3, -8/3
    x = np.concatenate([constant(levels[0], sr, first/sr),
                        constant(levels[1], sr, (second-first)/sr), constant(levels[2], sr, .8)])
    y = render(kind, x, params, sr)
    trace = 20*np.log10(np.abs(y[:, 0]/x[:, 0]))
    a = trace[first+round(attack_ms/1000*sr)-1]
    assert a/high == pytest.approx(1-math.exp(-1), abs=.04)
    before = trace[second-1]
    released = trace[second+round(release_ms/1000*sr)-1]
    assert (released-low)/(before-low) == pytest.approx(math.exp(-1), abs=.03)
    reached = np.flatnonzero(trace[first:second]/high >= 1-math.exp(-1))[0]
    measured_attack = (reached+1)/sr*1000
    reached = np.flatnonzero((trace[second:]-low)/(before-low) <= math.exp(-1))[0]
    measured_release = (reached+1)/sr*1000
    assert measured_attack == pytest.approx(attack_ms, rel=.1)
    assert measured_release == pytest.approx(release_ms, rel=.1)


def test_literal_spec_parameter_tables():
    tables = {
        'gate': [('threshold_db', -80, 0, -45), ('ratio', 1, 100, 4), ('range_db', -90, 0, -40),
                 ('hysteresis_db', 0, 12, 3), ('knee_db', 0, 24, 3), ('attack_ms', .05, 100, 1),
                 ('hold_ms', 0, 2000, 50), ('release_ms', 5, 3000, 150), ('lookahead_ms', 0, 20, 0),
                 ('key_lo_hz', 0, 2000, 0), ('key_hi_hz', 0, 20000, 0)],
        'transient_shaper': [('attack_db', -12, 12, 0), ('sustain_db', -12, 12, 0),
                 ('fast_ms', .1, 10, 1), ('slow_ms', 5, 100, 20), ('sustain_release_ms', 50, 2000, 300),
                 ('max_gain_db', 0, 18, 12), ('output_db', -24, 12, 0)],
        'upward_compressor': [('threshold_db', -80, 0, -30), ('ratio', 1, 10, 2), ('max_gain_db', 0, 24, 6),
                 ('floor_db', -120, -30, -60), ('knee_db', 0, 24, 6), ('attack_ms', .05, 300, 20),
                 ('release_ms', 5, 3000, 200), ('rms_window_ms', 1, 300, 20), ('mix', 0, 1, 1)],
        'leveler': [('high_threshold_db', -60, 0, -14), ('down_ratio', 1, 30, 3),
                 ('low_threshold_db', -80, 0, -34), ('up_ratio', 1, 10, 2), ('max_gain_db', 0, 24, 6),
                 ('floor_db', -120, -30, -60), ('knee_db', 0, 24, 6), ('attack_ms', .05, 300, 15),
                 ('release_ms', 5, 3000, 250), ('rms_window_ms', 1, 300, 30), ('output_db', -24, 12, 0)],
    }
    for kind, expected in tables.items():
        specs = P.describe(kind)['params']
        assert [(p['id'], p['min'], p['max'], p['default']) for p in specs if p['type'] == 'float'] == expected
        assert [p['default'] for p in specs if p['id'] == 'stereo_link'] == [True]
    det = next(p for p in P.describe('upward_compressor')['params'] if p['id'] == 'detector')
    assert det['choices'] == ['peak', 'rms'] and det['default'] == 'rms'


def test_stereo_link_unlinked_mix_and_output_gain():
    x = np.column_stack([constant(-50)[:, 0], constant(-20)[:, 0]])
    linked = render('upward_compressor', x)
    separate = render('upward_compressor', x, {'stereo_link': False})
    assert np.array_equal(linked[-1600:], x[-1600:])
    assert gain(x[-1600:, :1], separate[-1600:, :1]) == pytest.approx(6, abs=.01)
    assert np.array_equal(separate[-1600:, 1:], x[-1600:, 1:])
    half = render('upward_compressor', x, {'stereo_link': False, 'mix': .5})
    np.testing.assert_allclose(half, x+.5*(separate-x), atol=0, rtol=0)
    for kind, params in [('transient_shaper', {}), ('leveler', {'up_ratio': 1, 'down_ratio': 1})]:
        assert gain(x, render(kind, x, {**params, 'output_db': -6})) == pytest.approx(-6, abs=1e-10)


def test_transient_burst_train_retains_envelope_context():
    sr = 16000
    hit = H.tone_burst(sr=sr, seconds=.6)
    cell = np.concatenate([hit, np.zeros((round(.4*sr), 1))])
    x = np.tile(cell, (3, 1))
    for p in ({'attack_db': 6}, {'sustain_db': 6}, {'sustain_db': -6}):
        y = render('transient_shaper', x, p)
        for start in range(0, len(x), len(cell)):
            lead = slice(start, start+160)
            tail = slice(start+1600, start+4800)
            attack = H.peak_dbfs(y[lead])-H.peak_dbfs(x[lead])
            if 'attack_db' in p:
                assert attack == pytest.approx(6, abs=1)
                late = slice(start+3200, start+len(hit))
                assert abs(gain(x[late], y[late])) <= .5
            else:
                assert abs(attack) <= .5
                assert gain(x[tail], y[tail]) == pytest.approx(p['sustain_db'], abs=1.5)
