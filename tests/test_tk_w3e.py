"""W3e: delay/polarity, stereo azimuth and conservative inverse speed clocks."""
import json
import numpy as np
import pytest
from scipy import fft, signal
from mankomix.dsp import processors as P, engine as E
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb.align import estimate_delay, estimate_segments, align_pair, solve_delays
from mankomix.dspx.bb.delayline import fractional_delay, read_samples
from mankomix.dspx.bb.dewow import inverse_positions
from mankomix.dspx.bb.wobble import wobble
from mankomix.dspx.procs import azimuth_fix as AZ, dewow as DW
from mankomix.dspx.procs.wow_flutter import weighted_measurement
from tests import toolimpl_harness as H

MODULES = {'dewow': DW, 'azimuth_fix': AZ}


def emit(label, value):
    print(label, json.dumps(value, sort_keys=True, allow_nan=False))


def direct(kind, x, sr, **params):
    return MODULES[kind].IMPLS[kind](x, sr, P.validate_params(kind, params))


def noise(sr, seconds, seed=15):
    return H.white_noise(sr=sr, seconds=seconds, seed=seed)[:, 0]


@pytest.mark.parametrize('method', ['gcc_phat', 'correlation'])
@pytest.mark.parametrize('delay', [-64.371, 0., 193.113])
@pytest.mark.parametrize('polarity', [-1, 1])
def test_bb17_fractional_sign_and_polarity(method, delay, polarity):
    sr = 16000
    source = noise(sr, .3)
    a = fractional_delay(source[:, None], max(0, -delay), 'sinc256')[:, 0]
    b = fractional_delay(source[:, None], max(0, delay), 'sinc256')[:, 0]*polarity
    result = estimate_delay(a, b, sr, method=method, max_delay_ms=20, band_hz=(40, 7000))
    assert abs(result['delay_samples']-delay) < .04
    assert result['polarity'] == polarity and result['confidence'] == 'high'
    left, right = align_pair(a, b, result['delay_samples'], result['polarity'])
    assert np.corrcoef(left[400:-400], right[400:-400])[0, 1] > .999


def test_bb17_w4_three_tracks_noisy_colored_segments_and_graph():
    sr = 16000
    source = noise(sr, 1.2)
    rng = np.random.Generator(np.random.PCG64(27))
    delays = np.array([0, 1.37, 4.02])*sr/1000
    tracks = []
    for i, delay in enumerate(delays):
        a = fractional_delay(source[:, None], delay, 'sinc256')[:, 0]
        a = signal.lfilter([1., .03*i], [1], a)
        a += rng.normal(0, H.rms(a)*.1, len(a))
        tracks.append(a*(-1 if i == 1 else 1))
    pairs = []
    for i, j in ((0, 1), (1, 2), (0, 2)):
        result = estimate_segments(tracks[i], tracks[j], sr, segment_s=.4,
                                   max_delay_ms=10, band_hz=(40, 7000))
        assert abs(result['delay_ms']-(delays[j]-delays[i])/sr*1000) <= .02
        assert result['polarity'] == (-1 if 1 in (i, j) else 1)
        pairs.append((i, j, result['delay_samples']))
    fit = solve_delays(3, pairs)
    aligned = [fractional_delay(a[:, None], d, 'sinc256')[:, 0]*(-1 if i == 1 else 1)
               for i, (a, d) in enumerate(zip(tracks, fit['delay_samples']))]
    level = H.band_level(sum(aligned)[400:-400], sr, 100, 4000)['dbfs']
    baseline = H.band_level((3*source)[400:-400], sr, 100, 4000)['dbfs']
    assert abs(level-baseline) <= .5
    emit('bb17_three_tracks', dict(pairs=pairs, fit=fit, sum_level_error_db=level-baseline))


def test_bb17_low_confidence_and_invalid_inputs():
    result = estimate_delay(noise(16000, .4), noise(16000, .4, 42), 16000, max_delay_ms=5)
    assert result['confidence'] == 'low' and abs(result['correlation_after']) < .1
    assert estimate_delay(np.zeros(32), np.zeros(32), 48000)['confidence'] == 'low'
    for kwargs in ({'band_hz': (3000, 1000)}, {'max_delay_ms': -1}, {'oversample': 0}, {'method': 'other'}):
        with pytest.raises(ParamError):
            estimate_delay(np.zeros(32), np.zeros(32), 48000, **kwargs)
    with pytest.raises(ParamError):
        solve_delays(3, [(0, 1, 2)])
    fit = solve_delays(3, [(0, 1, 10), (1, 2, 20), (0, 2, 33)])
    np.testing.assert_allclose(fit['arrival_samples'], [0, 11, 32], atol=1e-12)
    assert abs(fit['residual_rms_samples']-1) < 1e-12


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_azimuth_37us_and_10khz_sum(sr):
    a = noise(sr, .4)
    b = fractional_delay(a[:, None], 37e-6*sr, 'sinc256')[:, 0]
    x = np.column_stack((a, b))
    y, _, stats = direct('azimuth_fix', x, sr)
    assert abs(stats['correction_us']+37) <= 2
    loss = H.band_level(np.mean(y[256:-256], axis=1), sr, 9500, 10500)['dbfs']-H.band_level(a[256:-256], sr, 9500, 10500)['dbfs']
    assert abs(loss) <= .1
    emit('azimuth_'+str(sr), dict(correction_us=stats['correction_us'], sum_10khz_loss_db=loss))


def test_azimuth_independent_stereo_manual_sign_tracking_and_mono():
    sr = 48000
    x = H.white_noise(sr=sr, seconds=.5, channels=2)
    y, _, stats = direct('azimuth_fix', x, sr)
    assert stats['confidence'] == 'low' and y.tobytes() == x.tobytes()
    with pytest.raises(ParamError, match='stereo'):
        direct('azimuth_fix', x[:, :1], sr)
    a = noise(sr, .5)
    a[::100] = -0.0
    x = np.column_stack((a, a))
    y, _, _ = direct('azimuth_fix', x, sr, mode='manual', delay_us=100)
    assert y[:, 0].tobytes() == x[:, 0].tobytes()
    assert abs(estimate_delay(y[:, 0], y[:, 1], sr, max_delay_ms=.2)['delay_samples']-4.8) < .05
    negative, _, _ = direct('azimuth_fix', x, sr, mode='manual', delay_us=-100)
    assert negative[:, 1].tobytes() == x[:, 1].tobytes()
    assert abs(estimate_delay(negative[:, 0], negative[:, 1], sr, max_delay_ms=.2)['delay_samples']+4.8) < .05
    a = noise(sr, 1)
    d = np.linspace(20, 100, len(a))*1e-6*sr
    b = read_samples(a[:, None], np.arange(len(a))-d, 'sinc256')[:, 0]
    y, _, stats = direct('azimuth_fix', np.column_stack((a, b)), sr, track_s=.2)
    assert len(stats['delay_estimates']) >= 8
    errors = [abs(estimate_delay(y[k:k+4800, 0], y[k:k+4800, 1], sr, max_delay_ms=.2)['delay_samples'])
              for k in (9600, 24000, 33600)]
    assert max(errors) < .15
    emit('azimuth_tracking', dict(max_residual_samples=max(errors)))


def harmonic_melody(sr=12000, seconds=8):
    t = np.arange(round(seconds*sr))/sr
    # Distinct sustained notes; all partials share a known continuous clock.
    frequency = np.choose((t//2).astype(int) % 4, [200., 240., 300., 250.])
    phase = 2*np.pi*np.cumsum(frequency)/sr
    return sum(.07/k*np.sin(k*phase) for k in range(1, 7))[:, None]


def demodulated_speed(x, sr, center, width=40):
    # Independent audio-domain oracle for a stationary isolated test carrier.
    frequencies = fft.fftfreq(len(x), 1/sr)
    spectrum = fft.fft(x[:, 0], workers=1)
    spectrum[(frequencies < center-width) | (frequencies > center+width)] = 0
    phase = np.unwrap(np.angle(fft.ifft(spectrum, workers=1)))
    return np.gradient(phase)*sr/(2*np.pi*center)-1


def test_dewow_known_wobble_on_harmonic_melody():
    sr = 12000
    x = harmonic_melody(sr)
    clean, _, clean_stats = direct('dewow', x, sr)
    assert clean_stats['speed_rms_percent'] <= .02
    assert clean.tobytes() == x.tobytes()
    d, true = wobble(len(x), sr, wow_depth=.5, wow_rate_hz=.5,
                     flutter_depth=.1, flutter_rate_hz=8, drift=0, close_60s=True)
    warped = read_samples(x, np.arange(len(x))-d[:, 0], 'lagrange3')
    y, _, stats = direct('dewow', warped, sr)
    curve = np.array(stats['curve'])
    inferred = np.interp(np.arange(len(x))/sr, curve[:, 0], curve[:, 1])*.01
    corr = np.corrcoef(inferred[sr:-sr], true[sr:-sr, 0])[0, 1]
    assert corr >= .9
    assert len(y) == len(x)
    before = stats['speed_measurement_before']['iec_60386_weighted_percent']
    after = stats['speed_measurement_after']['iec_60386_weighted_percent']
    assert after <= before/3
    measured = []
    for k, fundamental in enumerate((200, 240, 300, 250)):
        left, right = k*2*sr, (k+1)*2*sr
        vb = demodulated_speed(warped[left:right], sr, fundamental*3)[sr//2:-sr//2]
        va = demodulated_speed(y[left:right], sr, fundamental*3)[sr//2:-sr//2]
        wb = weighted_measurement(vb[:, None], sr)['iec_60386_weighted_percent']
        wa = weighted_measurement(va[:, None], sr)['iec_60386_weighted_percent']
        assert wa <= wb/3
        measured.append(dict(note=k, weighted_before_percent=wb, weighted_after_percent=wa))
    emit('dewow_melody', dict(curve_correlation=corr, weighted_before_percent=before,
                              weighted_after_percent=after, components=stats['component_count'],
                              independent_audio_demodulation=measured))


@pytest.mark.parametrize('reference', ['partials', 'pilot'])
def test_dewow_independent_audio_demodulation(reference):
    sr = 12000
    t = np.arange(sr*6)/sr
    x = sum(.05*np.sin(2*np.pi*f*t) for f in (300, 600, 900, 1200, 1500))[:, None]
    d, true = wobble(len(x), sr, wow_depth=.5, wow_rate_hz=.5,
                     flutter_depth=.1, flutter_rate_hz=8, drift=0, close_60s=True)
    warped = read_samples(x, np.arange(len(x))-d[:, 0], 'lagrange3')
    params = {'reference': reference, **({'pilot_hz': 900} if reference == 'pilot' else {})}
    y, _, stats = direct('dewow', warped, sr, **params)
    before = demodulated_speed(warped, sr, 900)[sr:-sr]
    after = demodulated_speed(y, sr, 900)[sr:-sr]
    wb = weighted_measurement(before[:, None], sr)['iec_60386_weighted_percent']
    wa = weighted_measurement(after[:, None], sr)['iec_60386_weighted_percent']
    curve = np.array(stats['curve'])
    estimate = np.interp(t, curve[:, 0], curve[:, 1])*.01
    corr = np.corrcoef(estimate[sr:-sr], true[sr:-sr, 0])[0, 1]
    assert corr >= .9 and wa <= wb/3
    emit('dewow_demod_'+reference, dict(curve_correlation=corr, weighted_before_percent=wb,
                                       weighted_after_percent=wa))


def test_dewow_preserves_single_note_vibrato():
    sr = 12000
    t = np.arange(sr*6)/sr
    phase = 2*np.pi*300*t - 300*.004/6*np.cos(2*np.pi*6*t)
    x = (.07*np.sin(phase)+.07*np.sin(2*np.pi*650*t)+.07*np.sin(2*np.pi*1100*t))[:, None]
    y, _, _ = direct('dewow', x, sr)
    a = demodulated_speed(x, sr, 300)[sr:-sr]
    b = demodulated_speed(y, sr, 300)[sr:-sr]
    ratio = np.std(b)/np.std(a)
    assert ratio >= .8
    emit('single_note_vibrato', dict(retained_ratio=ratio))


def test_dewow_manual_wow_flutter_roundtrip():
    sr = 12000
    t = np.arange(sr*6)/sr
    x = (.12*np.sin(2*np.pi*200*t)+.04*np.sin(2*np.pi*400*t))[:, None]
    controls = dict(wow_depth=.5, wow_rate_hz=.5, flutter_depth=.1,
                    flutter_rate_hz=8, drift=0, scrape=0, stereo_link=1)
    warped = H.render('wow_flutter', x, sr, controls).audio
    _, speed = wobble(len(x), sr, **{k: v for k, v in controls.items() if k != 'scrape'}, close_60s=True)
    points = [[float(t[i]), float(speed[i, 0]*100)] for i in range(0, len(x), 4)]
    points.append([float(t[-1]), float(speed[-1, 0]*100)])
    y, _, stats = direct('dewow', warped, sr, curve=points)
    # The zero-mean integration constant agrees with the closed wobble clock.
    result = H.null(x[sr:-sr], y[sr:-sr])
    assert result['rms_dbfs'] <= -60
    assert y.shape == x.shape and stats['curve'] == points
    assert stats['speed_measurement_after'] is None
    emit('manual_roundtrip', dict(null_dbfs=result['rms_dbfs']))


def clean_fixtures(sr):
    t = np.arange(sr*2)/sr
    yield 'sines', sum(.04*np.sin(2*np.pi*f*t) for f in (193, 421, 733, 1201))[:, None]
    yield 'pink', H.pink_noise(sr=sr, seconds=2)
    yield 'vowel', H.vowel(sr=sr, seconds=2)
    yield 'bursts', H.kick_train(sr=sr, seconds=2)


@pytest.mark.parametrize('kind', MODULES)
def test_rp4_clean_four_materials(kind):
    measurements = {}
    for name, a in clean_fixtures(12000):
        x = np.repeat(a, 2, axis=1)
        y, _, stats = direct(kind, x, 12000)
        relative = 10*np.log10(max(float(np.sum((x-y)**2)/np.sum(x*x)), 1e-300))
        assert relative <= -60, (kind, name, relative)
        if kind == 'dewow':
            assert stats['speed_rms_percent'] <= .02 and y.tobytes() == x.tobytes()
        measurements[name] = relative
    emit('rp4_'+kind, measurements)


@pytest.mark.parametrize('kind', MODULES)
def test_rp1_2_3_5_6_and_context_replay(kind):
    sr = 12000
    x = H.white_noise(sr=sr, seconds=.5, channels=2)
    params = dict(mode='manual', delay_us=37) if kind == 'azimuth_fix' else dict(curve=[[0, .3], [1, -.3]])
    normal = H.render(kind, x, sr, params).audio
    delta = H.render(kind, x, sr, dict(params, delta=True)).audio
    assert H.null(x, normal+delta)['rms_dbfs'] <= -120
    assert H.render(kind, x, sr, dict(params, amount=0, delta=True)).audio.tobytes() == x.tobytes()
    y, _, stats = direct(kind, x, sr, **params, start_s=.1, end_s=.4)
    assert y[:1200].tobytes() == x[:1200].tobytes() and y[4800:].tobytes() == x[4800:].tobytes()
    actual = np.any(x != y, axis=1)
    recorded = np.zeros(len(x), bool)
    for event in stats['events']:
        a = round(event['start_s']*sr)
        recorded[a:a+round(event['length_s']*sr)] = True
    assert np.array_equal(actual, recorded)
    first = H.render(kind, x, sr, params)
    second = H.render(kind, x, sr, params)
    assert first.audio.tobytes() == second.audio.tobytes()
    assert first.steps == second.steps
    assert H.render_excerpt(kind, x, sr, 123, 1023, params).tobytes() == first.audio[123:1023].tobytes()


@pytest.mark.parametrize('kind', MODULES)
def test_defaults_declarations_and_all_parameter_endpoints(kind):
    defaults = dict(amount=1, delta=False, start_s=0, end_s=0)
    defaults.update(dict(reference='partials', pilot_hz=0, max_dev=1, min_rate_hz=.2, max_rate_hz=12, curve=[])
                    if kind == 'dewow' else dict(mode='auto', delay_us=0, band_lo_hz=3000, track_s=0, max_us=200))
    assert P.validate_params(kind, {}) == defaults
    spec = P.describe(kind)
    assert spec['implemented'] and MODULES[kind].SPECS[0]['implemented']
    assert spec['stages'] == ['track', 'bus'] and spec['master_slot'] is None
    assert spec['backends'] == ['reference'] and spec['offline_only'] and not spec['realtime']['block_ok']
    from mankomix.dspx.registry import time_varying_types
    assert kind not in time_varying_types()
    x = H.white_noise(sr=48000, seconds=.01, channels=2)
    for entry in spec['params']:
        values = ([entry['min'], entry['max']] if entry['type'] in ('float', 'int') else
                  entry['choices'] if entry['type'] == 'enum' else
                  [False, True] if entry['type'] == 'bool' else [])
        for value in values:
            extra = {}
            if entry['id'] == 'start_s':
                extra['end_s'] = 36000 if value < 36000 else 0
                if value == 36000:
                    # Upper endpoint is valid only with an empty region beyond EOF;
                    # start=end remains explicitly invalid, tested separately.
                    with pytest.raises(ParamError):
                        P.validate_params(kind, {'start_s': value, 'end_s': 36000})
                    continue
            if entry['id'] == 'reference' and value == 'pilot':
                extra['pilot_hz'] = 1000
            if entry['id'] == 'min_rate_hz' and value == 2:
                extra['max_rate_hz'] = 12
            p = P.validate_params(kind, {entry['id']: value, **extra})
            y, rate, _ = MODULES[kind].IMPLS[kind](x, 48000, p)
            assert y.shape == x.shape and rate == 48000 and np.isfinite(y).all()
    for bad in ({'start_s': .2, 'end_s': .1}, {'end_s': 0, 'start_s': .2}):
        with pytest.raises(ParamError):
            P.validate_params(kind, bad)


def test_dewow_curve_validation_and_inverse_clock():
    for params in ({'reference': 'pilot'}, {'pilot_hz': 10}, {'min_rate_hz': 2, 'max_rate_hz': 1},
                   {'curve': [[0, 6]]}, {'curve': [[1, 0], [0, 0]]},
                   {'curve': [[0, float('nan')]]}, {'curve': [[0, 0]]*65537}):
        with pytest.raises(ParamError):
            P.validate_params('dewow', params)
    with pytest.raises(ParamError, match='Nyquist'):
        direct('dewow', np.ones((100, 1)), 48000, reference='pilot', pilot_hz=24000)
    for carrier in (20, 24000):
        # The upper pilot endpoint needs a sample rate above 48 kHz.
        tone = H.sine(carrier, sr=96000, seconds=.6)
        y, _, _ = direct('dewow', tone, 96000, reference='pilot', pilot_hz=carrier)
        assert y.shape == tone.shape and np.isfinite(y).all()
    points = np.column_stack((np.linspace(0, 36000, 65536), np.linspace(-5, 5, 65536))).tolist()
    y, _, _ = direct('dewow', np.ones((64, 1)), 48000, curve=points, max_dev=5)
    assert y.shape == (64, 1)
    t = np.linspace(0, 4, 10000)
    pos = inverse_positions(.05*np.sin(2*np.pi*t))
    assert np.all(np.diff(pos) > 0) and len(pos) == len(t)


@pytest.mark.parametrize('kind', MODULES)
def test_scope_rejection_and_json_safe_stats(kind):
    with pytest.raises(ChainError):
        E.validate_chain([{'id': 'repair', 'type': kind}], stage='master')
    x = H.white_noise(sr=48000, seconds=.02, channels=2)
    for stage in ('track', 'bus'):
        result = H.render(kind, x, 48000, stage=stage)
        json.dumps(result.steps, allow_nan=False, sort_keys=True)


@pytest.mark.parametrize('kind', MODULES)
def test_common_ct1_to_ct8(kind, monkeypatch):
    if kind == 'azimuth_fix':
        original = H.sine
        original_impulse = H.impulse
        # CT-7's mono branch is an explicit rejection for this stereo-only type.
        monkeypatch.setattr(H, 'sine', lambda *a, **kw: original(*a, **{**kw, 'channels': 2}))
        monkeypatch.setattr(H, 'impulse', lambda *a, **kw: original_impulse(*a, **{**kw, 'channels': 2}))
    def probe(x, y, sr, p):
        f = H.fundamental_frequency(y[sr//20:], sr, low_hz=900, high_hz=1100)
        return {'frequency_hz': f, 'passed': abs(f-1000) < 1}
    extra = {}
    if kind == 'azimuth_fix':
        extra.update(declared_latency=AZ.latency_samples,
                     latency_probe=lambda x, sr, p, **kw: AZ.raw_azimuth_fix(x, sr, p)[0])
    result = H.assert_common_tests(kind, neutral={'amount': 0}, sr_probe=probe, seconds=.12, **extra)
    emit('common_'+kind, {k: v['passed'] for k, v in result.items()})
