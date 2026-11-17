"""W1d curve/pitch building blocks and restoration/mastering acceptance."""
import numpy as np
import pytest

from mankomix.dsp import processors as P, engine
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb import curves as C
from mankomix.dspx.bb.pitch import detect_pitch, sample_pitch
from mankomix.dspx.procs import dc_remove as DC, dehum as DH, fade as F
from tests import toolimpl_harness as H


def run(kind, x, sr, params=None):
    p = P.validate_params(kind, params)
    return {'dehum': DH.dehum, 'dc_remove': DC.dc_remove, 'fade': F.fade}[kind](x, sr, p)


def amplitude(x, sr, frequencies):
    t = np.arange(len(x))/sr
    columns = [np.ones(len(x))]
    for f in frequencies:
        columns.extend([np.sin(2*np.pi*f*t), np.cos(2*np.pi*f*t)])
    fit = np.linalg.lstsq(np.array(columns).T, x, rcond=None)[0][1:].reshape(-1, 2, x.shape[1])
    return np.sqrt(np.sum(fit*fit, axis=1))


def hum(sr, seconds, base=50.07, orders=8, amp=.015):
    t = np.arange(round(sr*seconds))/sr
    return sum(amp*np.sin(2*np.pi*base*k*t + .2*k) for k in range(1, orders+1))[:, None]


def test_curve_db_line_grid_rounding_and_later_wins():
    points = [[0, -20], [.10001, -10], [.10004, -6], [.2, 0]]
    y = C.sample_curve(points, 201, 1000)
    assert y[50] == -13
    assert y[100] == -6
    assert np.allclose(C.evaluate_curve([[0, -24], [1, 0]], [.25, .5, .75]), [-18, -12, -6])
    # Python ties-to-even, shared with director/curve.py.
    assert C.sample_curve([[0, 0], [.0005, 1], [.0025, 2]], 4, 1000).tolist() == [1, 1.5, 2, 2]


@pytest.mark.parametrize('points', [
    [[0, 0], [.1, 1], [.8, 1.01], [1, 1.02]],
    [[0, 3], [.2, 1], [.4, 1], [1, -8]],
    [[0, 0], [.2, 1], [.6, -2], [1, 0]],
])
def test_cubic_monotone_no_overshoot(points):
    assert np.allclose(C.evaluate_curve(points, np.array(points)[:, 0], 'smooth'), np.array(points)[:, 1])
    for (a, y0), (b, y1) in zip(points, points[1:]):
        y = C.evaluate_curve(points, np.linspace(a, b, 201), 'smooth')
        assert np.min(y) >= min(y0, y1)-1e-14
        assert np.max(y) <= max(y0, y1)+1e-14
        assert np.all(np.diff(y)*(y1-y0) >= -1e-14)


def test_periodic_clock_note_values_and_thousand_cycle_drift():
    for note in P.NOTE_VALUES[1:]:
        assert C.period_ms(note=note, bpm=123) == P.note_ms(note, 123)
    sr, bpm = 44100, 137
    period = P.note_ms('1/8d', bpm)*sr/1000
    for cycle in (1, 10, 1000):
        n = round(cycle*period)
        phase = C.phase_positions(1, sr, start_sample=n, note='1/8d', bpm=bpm, wrap=False)[0]
        assert abs(phase-cycle)*period <= .5+1e-7
    whole = C.periodic_curve([[0, -24], [.2, 0], [1, -24]], 8000, sr,
                             period_ms=37.3, origin_s=.02, phase=.17)
    for size in (64, 1024):
        blocks = [C.periodic_curve([[0, -24], [.2, 0], [1, -24]], min(size, 8000-i), sr,
                                   start_sample=i, period_ms=37.3, origin_s=.02, phase=.17)
                  for i in range(0, 8000, size)]
        assert np.array_equal(whole, np.concatenate(blocks))


@pytest.mark.parametrize('shape', ['sine', 'triangle', 'square', 'saw_up', 'saw_down',
                                    'sample_hold', 'random', 'random_walk'])
def test_lfo_absolute_clock_and_seed(shape):
    opts = dict(shape=shape, rate_hz=17.3, origin_s=.2, phase=.123, seed=71)
    y = C.lfo(7000, 8000, **opts)
    assert y.dtype == np.float64 and np.max(np.abs(y)) <= 1
    for size in (64, 1024):
        b = np.concatenate([C.lfo(min(size, len(y)-i), 8000, start_sample=i, **opts)
                            for i in range(0, len(y), size)])
        assert y.tobytes() == b.tobytes()
    if shape in ('sample_hold', 'random', 'random_walk'):
        assert not np.array_equal(y, C.lfo(7000, 8000, **{**opts, 'seed': 72}))
    else:
        assert np.array_equal(y, C.lfo(7000, 8000, **{**opts, 'seed': 72}))


def test_lfo_known_phases_and_hold():
    assert np.allclose(C.lfo(4, 4), [0, 1, 0, -1], atol=1e-15)
    assert np.array_equal(C.lfo(4, 4, shape='triangle'), [-1, 0, 1, 0])
    assert np.array_equal(C.lfo(4, 4, shape='square'), [1, 1, -1, -1])
    hold = C.lfo(40, 10, shape='sample_hold', seed=71)
    expected = np.random.Generator(np.random.PCG64(71)).uniform(-1, 1, 4)
    assert np.array_equal(hold, np.repeat(expected, 10))
    mixed = C.lfo(40, 10, shape='sample_hold', seed=71, item_id='mod1', parameter_seed=3)
    assert np.array_equal(mixed, C.lfo(40, 10, shape='sample_hold',
                                     seed=C.modulation_seed(71, 'mod1', 3)))
    assert not np.array_equal(mixed, C.lfo(40, 10, shape='sample_hold', seed=71,
                                          item_id='mod2', parameter_seed=3))


@pytest.mark.parametrize('bad', [{'note': '1/7'}, {'note': '1/4'}, {'bpm': 10}, {'period_ms': 0}])
def test_curve_tempo_invalid(bad):
    with pytest.raises(ParamError):
        C.period_ms(**bad)


@pytest.mark.parametrize('method', ['yin', 'pyin'])
def test_pitch_vowel_curve_and_unvoiced(method):
    sr, seconds = 8000, 1.6
    t = np.arange(round(sr*seconds))/sr
    f0 = 125 + 15*t/seconds
    x = H.vowel(f0, sr=sr, seconds=seconds)
    q = detect_pitch(x, sr, method=method, fmin=70, fmax=350, hop_ms=10)
    keep = (q.times_s > .15) & (q.times_s < 1.45)
    error = np.abs(q.f0_hz[keep]/(125+15*q.times_s[keep]/seconds)-1)
    assert q.voiced[keep].all()
    assert np.max(error) < .01
    assert np.array_equal(q.samples, np.arange(0, len(x), 80))
    assert q.samples.dtype == np.int64 and q.f0_hz.dtype == np.float64
    # Silence and aperiodic white noise must not acquire a pitch.
    noise = H.white_noise(-25, sr=sr, seconds=.5)
    composite = np.concatenate([x[:sr//2], np.zeros((sr//2, 1)), noise])
    z = detect_pitch(composite, sr, method=method, fmin=70, fmax=350)
    silent = (z.times_s > .65) & (z.times_s < .85)
    noisy = (z.times_s > 1.15) & (z.times_s < 1.35)
    assert not z.voiced[silent | noisy].any()
    assert np.isnan(z.f0_hz[silent | noisy]).all()
    sampled = sample_pitch(z, z.samples)[0]
    assert np.array_equal(sampled, z.f0_hz, equal_nan=True)
    again = detect_pitch(x, sr, method=method, fmin=70, fmax=350)
    assert q.f0_hz.tobytes() == again.f0_hz.tobytes()
    print('pitch', method, 'max_relative_error', float(error.max()))


def test_pitch_stereo_antiphase_empty_and_validation():
    x = H.vowel(137, sr=8000, seconds=.5)
    q = detect_pitch(np.c_[x, -x], 8000, method='yin', fmin=70, fmax=350)
    assert abs(np.nanmedian(q.f0_hz)-137) < 1
    for a in (np.empty((0, 1)), np.zeros((1, 1)), np.zeros((800, 1))):
        r = detect_pitch(a, 8000)
        assert not r.voiced.any() and np.isnan(r.f0_hz).all()
    for kw in ({'fmin': 0}, {'fmax': 5000}, {'hop_ms': 0}, {'method': 'other'}, {'frame_length': 10}):
        with pytest.raises(ParamError):
            detect_pitch(x, 8000, **kw)


@pytest.mark.parametrize('shape,mid', [('linear', .5), ('equal_power', 2**-.5),
                                     ('s_curve', .5), ('exp', .001), ('log', .999)])
def test_fade_shapes_endpoints_midpoint_and_monotone(shape, mid):
    y = C.fade_shape(np.linspace(0, 1, 1001), shape)
    assert y[0] == 0 and y[-1] == 1
    assert np.all(np.diff(y) >= 0)
    assert abs(y[500]-mid) < 1e-14


@pytest.mark.parametrize('shape', F.SHAPES)
def test_fade_envelope_and_excerpt(shape):
    sr = 8000
    x = H.sine(311, sr=sr, seconds=.7, channels=2)
    p = P.validate_params('fade', {'in_end_s': .1, 'out_start_s': .3, 'out_ms': 200,
                                 'shape_in': shape, 'shape_out': shape})
    y, _, _ = F.fade(x, sr, p)
    # Independent shape definitions for +/-0.01 dB acceptance.
    u = np.arange(1, 800)/800
    expected = {'linear': u, 'equal_power': np.sin(np.pi*u/2),
                's_curve': (1-np.cos(np.pi*u))/2,
                'exp': 10**(-120*(1-u)/20), 'log': 1-10**(-120*u/20)}[shape]
    g = F.fade_envelope(len(x), sr, p)
    assert np.max(np.abs(20*np.log10(g[1:800]/expected))) < .01
    assert y[800:2400].tobytes() == x[800:2400].tobytes()
    assert np.all(y[4000:] == 0)
    for size in (64, 1024):
        joined = np.concatenate([F.fade(x[i:i+size], sr, p, start_sample=i)[0]
                                 for i in range(0, len(x), size)])
        assert joined.tobytes() == y.tobytes()
    assert run('fade', x, sr)[0].tobytes() == x.tobytes()


def test_dc_mean_off_threshold_and_channels():
    sr = 8000
    sine = H.sine(1000, sr=sr, seconds=1)
    x = np.c_[sine + 10**(-30/20), sine - .02]
    assert run('dc_remove', x, sr)[0].tobytes() == x.tobytes()
    y, _, stats = run('dc_remove', x, sr, {'mode': 'mean'})
    assert np.max(np.abs(np.mean(y, axis=0))) <= 1e-7
    assert np.max(np.ptp(x-y, axis=0)) < 1e-15
    assert H.null(y, np.c_[sine, sine])['rms_dbfs'] < -140
    quiet = np.c_[sine+1e-6, sine+1e-6]
    assert run('dc_remove', quiet, sr, {'mode': 'mean'})[0].tobytes() == quiet.tobytes()
    common = run('dc_remove', x, sr, {'mode': 'mean', 'per_channel': False})[0]
    assert np.max(np.abs((common[:, 0]-common[:, 1])-(x[:, 0]-x[:, 1]))) < 1e-15
    assert 'peak_after_dbfs' in stats


def test_dc_highpass_zero_phase_response_and_minimum_latency():
    sr = 4000
    x = H.sine(20, -12, sr=sr, seconds=10) + 10**(-30/20)
    y, _, stats = run('dc_remove', x, sr, {'mode': 'highpass'})
    gain = 20*np.log10(amplitude(y[2*sr:-2*sr], sr, [20])[0, 0]/10**(-12/20))
    assert gain >= -.5
    assert abs(np.mean(y)) <= 1e-5
    pulse = H.impulse(at_s=5, sr=sr, seconds=10)
    z = run('dc_remove', pulse, sr, {'mode': 'highpass'})[0][:, 0]
    assert np.max(np.abs(z[5*sr-2*sr:5*sr]-z[5*sr+1:5*sr+2*sr+1][::-1])) < 1e-12
    causal = run('dc_remove', pulse, sr, {'mode': 'highpass', 'phase': 'minimum'})[0]
    assert H.latency(causal) == 5*sr
    assert np.count_nonzero(causal[:5*sr]) == 0
    print('dc gain_db', gain, 'dc_dbfs', H.db(abs(np.mean(y))))


def test_dehum_auto_eight_harmonics_and_between_tones():
    sr, seconds = 4000, 10
    vowel = H.vowel(137, sr=sr, seconds=seconds, formants_hz=(600, 1000, 1500))
    tones = H.sine(75, -26, sr=sr, seconds=seconds)+H.sine(125, -26, sr=sr, seconds=seconds)
    x = vowel+hum(sr, seconds)+tones
    y, _, stats = run('dehum', x, sr)
    assert abs(stats['base_hz']-50.07) <= .02
    frequencies = [50.07*k for k in range(1, 9)] + [75, 125]
    a = amplitude(x[2*sr:-2*sr], sr, frequencies)[:, 0]
    b = amplitude(y[2*sr:-2*sr], sr, frequencies)[:, 0]
    change = 20*np.log10(b/a)
    assert np.max(np.abs(change[:8]+30)) <= 3
    assert np.max(np.abs(change[8:])) <= .2
    print('dehum base', stats['base_hz'], 'harmonic_db', change[:8].tolist(), 'between_db', change[8:].tolist())


def test_dehum_subtraction_burst_protection():
    sr, seconds = 4000, 5
    clean = np.zeros((sr*seconds, 1))
    burst = H.tone_burst(50.07, -6, rise_ms=2, decay_ms=15, sr=sr, seconds=.1)
    clean[2*sr:2*sr+len(burst)] = burst
    x = clean+hum(sr, seconds)
    p = {'base_hz': 50.07, 'mode': 'subtract', 'depth_db': 60}
    y, _, _ = run('dehum', x, sr, p)
    # Away from the transient, compare to the fitted hum itself.
    outside = np.r_[y[:sr], y[-sr:]]
    suppression = H.rms_dbfs(outside)-H.rms_dbfs(hum(sr, 2))
    assert suppression <= -40
    active = slice(2*sr, 2*sr+len(burst))
    level = H.rms_dbfs(y[active])-H.rms_dbfs(clean[active])
    assert abs(level) <= 1
    print('subtract suppression_db', suppression, 'burst_change_db', level)


@pytest.mark.parametrize('mode', ['notch', 'subtract'])
def test_dehum_track_twenty_seconds(mode):
    sr, seconds = 2000, 20
    t = np.arange(sr*seconds)/sr
    cycles = 49.8*t + .01*t*t
    x = sum(.02*np.sin(2*np.pi*k*cycles+.3*k) for k in range(1, 9))[:, None]
    y, _, stats = run('dehum', x, sr, {'base_hz': 50, 'track': True, 'mode': mode})
    change = H.rms_dbfs(y[sr:-sr])-H.rms_dbfs(x[sr:-sr])
    assert change <= -25
    print('track', mode, 'suppression_db', change, 'grid', stats['tracking'])


@pytest.mark.parametrize('material', ['tones', 'pink', 'vowel', 'bursts'])
def test_dehum_rp4_no_hum_bit_identical(material):
    sr, seconds = 8000, 2
    if material == 'tones':
        x = sum(H.sine(f, sr=sr, seconds=seconds) for f in (219, 443, 997))
    elif material == 'pink':
        x = H.pink_noise(sr=sr, seconds=seconds)
    elif material == 'vowel':
        x = H.vowel(137, sr=sr, seconds=seconds)
    else:
        x = np.zeros((sr*seconds, 1))
        for at in (0, 4000, 8000, 12000):
            b = H.tone_burst(311, sr=sr, seconds=.2)
            x[at:at+len(b)] += b
    y, _, stats = run('dehum', x, sr)
    assert not stats['detected']
    assert y.tobytes() == x.tobytes()
    assert stats['event_count'] == 0 and stats['removed_energy_rel_db'] is None


def test_dehum_rp_delta_region_events_repeat_and_zero_phase():
    sr = 4000
    x = hum(sr, 5)
    p = {'base_hz': 50.07, 'start_s': 1, 'end_s': 4, 'amount': .7}
    y, _, stats = run('dehum', x, sr, p)
    delta = run('dehum', x, sr, {**p, 'delta': True})[0]
    assert H.null(y+delta, x)['rms_dbfs'] <= -120
    assert x[:sr].tobytes() == y[:sr].tobytes()
    assert x[4*sr:].tobytes() == y[4*sr:].tobytes()
    changed = np.any(y != x, axis=1)
    events = np.zeros(len(x), bool)
    for event in stats['events']:
        a = round(event['start_s']*sr)
        events[a:a+round(event['length_s']*sr)] = True
    assert np.array_equal(changed, events)
    assert run('dehum', x, sr, p)[0].tobytes() == y.tobytes()
    assert run('dehum', x, sr, {**p, 'amount': 0, 'delta': True})[0].tobytes() == x.tobytes()
    pulse = H.impulse(sr=sr, seconds=20, at_s=10)
    response = run('dehum', pulse, sr, {'base_hz': 50, 'harmonics': 1})[0][:, 0]
    assert np.max(np.abs(response[8*sr:10*sr]-response[10*sr+1:12*sr+1][::-1])) < 1e-12
    assert stats['before']['lufs_i'] == DH._measure(x, sr)['lufs_i']


def test_dehum_odd_slope_width_and_parameter_extremes():
    sr, seconds = 4000, 12
    x = hum(sr, seconds, base=50, orders=4)
    y = run('dehum', x, sr, {'base_hz': 50, 'harmonics': 4, 'odd_only': True,
                            'depth_db': 30, 'slope': 2})[0]
    change = 20*np.log10(amplitude(y[3*sr:-3*sr], sr, [50, 100, 150, 200])[:, 0]/.015)
    assert np.allclose(change, [-30, 0, -26, 0], atol=.15)
    near = sum(H.sine(f, -20, sr=sr, seconds=seconds) for f in (49.5, 50.5))
    out = run('dehum', near, sr, {'base_hz': 50, 'harmonics': 1})[0]
    width_db = 20*np.log10(amplitude(out[3*sr:-3*sr], sr, [49.5, 50.5])[:, 0]/.1)
    assert np.allclose(width_db, -3.0103, atol=.08)
    for param in P.describe('dehum')['params']:
        if param['type'] in ('float', 'int'):
            for bound in ('min', 'max'):
                value = param[bound]
                if param['id'] == 'end_s':
                    options = {'start_s': 0, 'end_s': value}
                elif param['id'] == 'start_s':
                    options = {'start_s': value, 'end_s': min(36000, value+1)} if value < 36000 else {'start_s': 0, 'end_s': value}
                else:
                    options = {param['id']: value}
                # base_hz min is the valid auto sentinel, 1..39.99 is not valid.
                output = run('dehum', x[:sr], sr, {'base_hz': 50, **options})[0]
                assert np.isfinite(output).all()
    print('odd_slope_db', change.tolist(), 'width_db', width_db.tolist())


def test_registration_master_order_and_defaults():
    assert P.describe('dc_remove')['stages'] == ['track', 'bus']
    with pytest.raises(ChainError):
        engine.validate_chain([{'type': 'dc_remove'}], 'master')
    engine.validate_chain([{'type': 'eq'}, {'type': 'fade'}, {'type': 'limiter'}], 'master')
    with pytest.raises(ChainError):
        engine.validate_chain([{'type': 'fade'}, {'type': 'eq'}], 'master')
    with pytest.raises(ChainError):
        engine.validate_chain([{'type': 'limiter'}, {'type': 'fade'}], 'master')
    from mankomix.dspx.registry import time_varying_types
    assert 'fade' in time_varying_types() and 'dehum' not in time_varying_types()
    for kind in ('fade', 'dc_remove', 'dehum'):
        p = P.validate_params(kind, {})
        for spec in P.describe(kind)['params']:
            assert p[spec['id']] == spec['default']
        assert P.describe(kind)['realtime']['latency_samples'] == 0


def _sr_probe(kind):
    def probe(x, y, sr, p):
        if kind == 'fade':
            n = round(.025*sr)
            ratio = y[n, 0]/x[n, 0] if abs(x[n, 0]) > 1e-10 else y[n+1, 0]/x[n+1, 0]
            index = n if abs(x[n, 0]) > 1e-10 else n+1
            expected = index/round(.05*sr)
            return {'passed': abs(ratio-expected) < 1e-12, 'midpoint_amplitude': ratio}
        # Physical frequency/level at a band far from DC and hum.
        freq = H.fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
        gain = H.rms_dbfs(y)-H.rms_dbfs(x)
        return {'passed': abs(freq-1000) < 1 and abs(gain) < .01,
                'frequency_hz': freq, 'gain_db': gain}
    return probe


@pytest.mark.parametrize('kind,params,neutral', [
    ('fade', {'in_end_s': .05, 'shape_in': 'linear'}, {'in_end_s': 0, 'out_start_s': 0}),
    ('dc_remove', {'mode': 'highpass', 'phase': 'minimum'}, {'mode': 'off'}),
    ('dehum', {'base_hz': 50, 'harmonics': 1}, {'amount': 0}),
])
def test_common_ct1_to_ct8(kind, params, neutral):
    invalid = [{'base_hz': 20}, {'start_s': 2, 'end_s': 1}] if kind == 'dehum' else []
    latency = {'in_end_s': 0, 'out_start_s': 0} if kind == 'fade' else None
    result = H.assert_common_tests(kind, params=params, neutral=neutral, seconds=.12,
                                   sr_probe=_sr_probe(kind), invalid_params=invalid,
                                   latency_params=latency)
    assert all(v['passed'] for v in result.values())


@pytest.mark.parametrize('kind', ['dc_remove', 'fade'])
def test_numeric_endpoints_and_default_outputs(kind):
    sr = 8000
    x = H.sine(311, sr=sr, seconds=.15, channels=2)
    assert run(kind, x, sr)[0].tobytes() == x.tobytes()
    for spec in P.describe(kind)['params']:
        values = [spec['min'], spec['max']] if spec['type'] in ('int', 'float') else spec.get('choices', [True, False])
        for value in values:
            y = run(kind, x, sr, {spec['id']: value})[0]
            assert np.isfinite(y).all() and y.shape == x.shape
