"""W3a WOLA/noise primitives, processor contracts and acoustic acceptance.

Known specification misses are strict xfails, with the original numerical
thresholds intact. Enabling an unaccepted processor is confined to a fixture.
"""
import json
import numpy as np
import pytest
from scipy import fft, signal, stats
from mankomix.dsp import processors as P, engine as E
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb import stft as S, noise as N
from mankomix.dspx.procs import denoise as DN, spectral_fx as FX, spectral_freeze as FZ
from tests import toolimpl_harness as H

MODULES = dict(denoise=DN, spectral_fx=FX, spectral_freeze=FZ)
OPS = ['blur', 'gate', 'shift', 'scale', 'scramble', 'contrast', 'phase', 'smear_freq']


@pytest.fixture
def enabled(monkeypatch):
    # False remains externally visible; only acceptance tests may render it.
    for kind in MODULES:
        if not P.PROCESSORS[kind]['implemented']:
            monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)


def direct(kind, x, p=None, sr=16000, **kw):
    return MODULES[kind].IMPLS[kind](x, sr, P.validate_params(kind, p or {}), **kw)


def render(kind, x, p=None, sr=16000, seed=0, item='effect'):
    return E.render_chain(x, sr, [dict(id=item, type=kind, params=p or {})], stage='track', seed=seed).audio


def change(x, y):
    return H.rms_dbfs(y)-H.rms_dbfs(x)


def emit(name, value):
    print(name, json.dumps(value, sort_keys=True))


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('nominal', [1024, 2048, 4096])
def test_wola_unity_boundaries_cola_and_latency(sr, nominal):
    n = S.window_samples(nominal, sr)
    for length in (0, 1, n//8+1, n+13):
        x = np.random.Generator(np.random.PCG64(1)).standard_normal((length, 2))*.1
        a = S.analyze(x, sr, window=n)
        assert S.check_cola(a.window, a.hop_samples) == pytest.approx(2, abs=1e-12)
        y, g = S.apply_gains(a, 1)
        assert y.shape == x.shape
        assert np.max(abs(y-x), initial=0) < 1e-12
        if length:
            assert H.null(x, y)['peak_dbfs'] <= -120
        np.testing.assert_array_equal(g, np.ones_like(g))
    pulse = H.impulse(at_s=.01, sr=sr, seconds=.3)
    a = S.analyze(pulse, sr, window=n)
    assert H.latency(S.synthesize(a, compensate=False))-round(.01*sr) == n
    assert H.latency(S.synthesize(a))-round(.01*sr) == 0
    emit('WOLA', dict(sr=sr, window=n, peak_null_dbfs=H.null(pulse, S.synthesize(a))['peak_dbfs']))


def test_wola_gain_smoothing_and_validation():
    sr, n = 48000, 2048
    f = fft.rfftfreq(n, 1/sr)
    g = np.ones((200, len(f), 2))
    g[10:] = .1
    sm = S.smooth_gains(g, sr, n//4, f, time_ms=80)
    tau = round(.08*sr/(n//4))
    expected = -20*(1-np.exp(-(tau+1)*n//4/(sr*.08)))
    assert 20*np.log10(sm[10+tau, 100, 0]) == pytest.approx(expected, abs=.01)
    spike = np.zeros((2, len(f), 1))
    spike[:, 80] = 1
    spread = S.smooth_frequency(spike, f, 1)
    assert np.count_nonzero(spread[0]) > 10
    np.testing.assert_array_equal(S.smooth_frequency(spike, f, 0), spike)
    with pytest.raises(ParamError):
        S.check_cola(S.sqrt_hann(1024), 300)
    with pytest.raises(ParamError):
        S.smooth_gains(-g, sr, 512, f)
    a = S.analyze(np.ones((100, 1)), sr)
    with pytest.raises(ParamError):
        S.apply_gains(a, np.ones((2, 7)))
    with pytest.raises(ParamError):
        S.synthesize(a, np.zeros((1, 2, 3)))


def test_noise_profile_formulas_and_past_only_minimum():
    sr, n = 16000, S.window_samples(2048, 16000)
    x = H.white_noise(-30, sr=sr, seconds=2, channels=2, seed=22)
    a = S.analyze(x, sr, window=n)
    profile = N.region_profile(a, .1, .8)
    use = (a.samples-n//2 >= .1*sr) & (a.samples+n//2 <= .8*sr)
    np.testing.assert_array_equal(profile.mean_power, np.mean(abs(a.spectra[use])**2, axis=0))
    np.testing.assert_array_equal(profile.variance_power, np.var(abs(a.spectra[use])**2, axis=0))
    for start, end in ((0, .1), (0, 3), (-.1, .4)):
        with pytest.raises(ParamError):
            N.region_profile(a, start, end)
    p = abs(a.spectra)**2
    short = N.minimum_statistics(p[:30], sr, a.hop_samples)
    full = N.minimum_statistics(p, sr, a.hop_samples)
    np.testing.assert_array_equal(short, full[:30])
    one = np.full((8, 3, 1), 10.)
    floor = np.ones((3, 1))
    for method in ('wiener', 'log_mmse', 'subtract'):
        g = N.suppression_gains(one, floor, sr, 100, [0, 100, 200], method=method,
                reduction_db=40, time_smooth_ms=0, freq_smooth_oct=0,
                transient_protect=0, decision_alpha=0)
        xi, gamma = 9., 10.
        if method == 'wiener':
            expected = xi/(1+xi)
        elif method == 'subtract':
            expected = np.sqrt(1-2/gamma)
        else:
            from scipy.special import exp1
            expected = xi/(1+xi)*np.exp(.5*exp1(gamma*xi/(1+xi)))
        np.testing.assert_allclose(g, expected, atol=1e-14)


def test_minimum_statistics_20_seconds_true_floor():
    sr = 8000
    x = H.white_noise(-30, sr=sr, seconds=20, channels=2, seed=4)
    a = S.analyze(x, sr, window=S.window_samples(2048, sr))
    p = abs(a.spectra)**2
    floor = N.minimum_statistics(p, sr, a.hop_samples)
    truth = np.mean(p[a.samples > 2*sr], axis=0)
    estimate = np.mean(floor[a.samples > 2*sr], axis=0)
    # Independent 1/3-oct aggregation, not the reporting helper.
    errors = []
    for center in (125, 250, 500, 1000, 2000, 3150):
        use = (a.frequencies_hz >= center*2**(-1/6)) & (a.frequencies_hz < center*2**(1/6))
        errors.extend((10*np.log10(np.sum(estimate[use], axis=0)/np.sum(truth[use], axis=0))).tolist())
    emit('MINSTAT_20S', dict(errors_db=errors, max_abs_db=max(abs(np.array(errors)))))
    assert max(abs(np.array(errors))) <= 2


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('method', ['wiener', 'log_mmse', 'subtract'])
def test_denoise_active_region_rates_and_methods(sr, method):
    noise = H.white_noise(-35, sr=sr, seconds=1.4, seed=6)
    x = noise.copy()
    x[round(.6*sr):] += H.sine(1000, -18, sr=sr, seconds=.8)
    y, _, record = direct('denoise', x, dict(profile='region', profile_start_s=.05,
                         profile_end_s=.5, method=method), sr)
    sl = slice(round(.15*sr), round(.45*sr))
    # Residual attenuation is measured inside lo/hi. At 96 kHz a full-band
    # white input includes 20..48 kHz which the effect must leave untouched.
    gain = H.band_level(y[sl], sr, 200, 10000)['dbfs']-H.band_level(x[sl], sr, 200, 10000)['dbfs']
    tone = slice(round(.9*sr), round(1.3*sr))
    amplitude = H._tone_fit(y[tone], sr, [1000])[0][0, 0]
    tone_gain = float(20*np.log10(amplitude/10**(-18/20)))
    emit('DENOISE_RATES', dict(sr=sr, method=method, noise_gain_db=gain, tone_gain_db=tone_gain))
    assert abs(gain+12) <= 2 and abs(tone_gain) <= 1
    assert record['gain_min'] >= 10**(-12/20)-1e-14


def test_shared_noise_transient_and_gain_bounds():
    sr, hop = 48000, 512
    f = fft.rfftfreq(2048, 1/sr)
    p = np.ones((100, len(f), 2))
    p[30:33] *= 100
    floor = np.ones(p.shape[1:])*2
    closed = N.suppression_gains(p, floor, sr, hop, f, transient_protect=0)
    opened = N.suppression_gains(p, floor, sr, hop, f, transient_protect=.5)
    assert np.mean(opened[29:34]) >= np.mean(closed[29:34])
    assert np.min(opened) >= 10**(-12/20) and np.max(opened) <= 1
    assert np.max(N.transient_weights(p, sr, hop)) == 1
    with pytest.raises(ParamError):
        N.suppression_gains(p, -floor, sr, hop, f)
    with pytest.raises(ParamError):
        N.minimum_statistics(-p, sr, hop)


def noisy_vowel(sr=16000):
    clean = np.zeros((4*sr, 1))
    clean[sr:] = H.vowel(f0=125, sr=sr, seconds=3, dbfs=-14)
    noise = H.white_noise(H.rms_dbfs(clean[sr:])-10, sr=sr, seconds=4, seed=81)
    return clean, noise, clean+noise


def region_params(**kw):
    return dict(profile='region', profile_start_s=.1, profile_end_s=.8) | kw


def test_denoise_region_residual_harmonics_snr_and_attack(enabled):
    sr = 16000
    clean, noise, x = noisy_vowel(sr)
    y = render('denoise', x, region_params(), sr)
    residual_gain = change(x[int(.25*sr):int(.75*sr)], y[int(.25*sr):int(.75*sr)])
    start, stop = int(1.3*sr), int(3.8*sr)
    errors = []
    # Independent coherent projection of actual signal harmonics.
    t = np.arange(stop-start)/sr
    for hz in (500, 625, 750, 1125, 1250, 2500):
        phasor = np.exp(-2j*np.pi*hz*t)
        ref = abs(np.sum(x[start:stop, 0]*phasor))
        got = abs(np.sum(y[start:stop, 0]*phasor))
        if ref > 1:
            errors.append(20*np.log10(got/ref))
    gains = []
    for at in np.arange(1.3, 3.7, .1):
        sl = slice(round(at*sr), round((at+.03)*sr))
        gains.append(10*np.log10(np.sum((x[sl]-clean[sl])**2)/np.sum((y[sl]-clean[sl])**2)))
    attack = change(x[sr:sr+round(.01*sr)], y[sr:sr+round(.01*sr)])
    emit('DENOISE_REGION', dict(noise_gain_db=residual_gain, harmonic_changes_db=errors,
                               segment_snr_improvement_db=float(np.mean(gains)), attack_db=attack))
    assert abs(residual_gain+12) <= 2
    assert max(abs(np.array(errors))) <= 1
    assert np.mean(gains) >= 6
    assert attack >= -1


def test_denoise_rp_and_s4(enabled):
    sr = 16000
    _, _, x = noisy_vowel(sr)
    np.testing.assert_array_equal(render('denoise', x, dict(amount=0, delta=True), sr), x)
    p = region_params(start_s=.3, end_s=2.5)
    y, _, record = direct('denoise', x, p, sr)
    d = direct('denoise', x, {**p, 'delta': True}, sr)[0]
    assert H.null(y+d, x)['peak_dbfs'] <= -120
    np.testing.assert_array_equal(y[:round(.3*sr)], x[:round(.3*sr)])
    np.testing.assert_array_equal(y[round(2.5*sr):], x[round(2.5*sr):])
    spans = np.zeros(len(x), bool)
    for event in record['events']:
        left = round(event['start_s']*sr)
        spans[left:left+round(event['duration_s']*sr)] = True
    np.testing.assert_array_equal(spans, np.any(x != y, axis=1))
    assert len(record['noise_floor_third_oct']) > 10
    assert record['before']['sample_peak_dbfs'] is not None
    tone = H.sine(1000, sr=sr, seconds=3)
    out = render('denoise', tone, sr=sr)
    envelope = abs(signal.hilbert(out[sr:-sr, 0]))
    ripple = 20*np.log10(max(envelope)/min(envelope))
    emit('DENOISE_S4', dict(ripple_db=ripple))
    assert ripple <= .05


@pytest.mark.parametrize('material', ['sines', 'vowel', 'bursts'])
def test_denoise_auto_rp4_clean(material):
    sr = 16000
    if material == 'sines':
        x = H.sine(430, sr=sr, seconds=4)+H.sine(900, sr=sr, seconds=4)
    elif material == 'vowel':
        x = H.vowel(sr=sr, seconds=4)
    else:
        x = H.kick_train(sr=sr, seconds=4)
    y, _, record = direct('denoise', x, sr=sr)
    value = record['removed_energy_rel_db']
    emit('RP4', dict(material=material, removed_db=value))
    assert value is None or value <= -45


def musical_kurtosis(audio, sr):
    a = S.analyze(audio, sr, window=S.window_samples(2048, sr))
    # Normalize each bin's mean before flattening time-frequency power.
    power = abs(a.spectra[3:-3, 5:-5])**2
    power /= np.maximum(np.mean(power, axis=0, keepdims=True), 1e-30)
    return float(stats.kurtosis(power.ravel(), fisher=False))


def test_denoise_musical_noise_smoothing(enabled):
    sr = 16000
    x = H.white_noise(-30, sr=sr, seconds=4, seed=32)
    smooth = render('denoise', x, region_params(transient_protect=0), sr)
    rough = render('denoise', x, region_params(time_smooth_ms=0, freq_smooth_oct=0, transient_protect=0), sr)
    original = musical_kurtosis(x[sr:-sr], sr)
    ratio = musical_kurtosis(smooth[sr:-sr], sr)/original
    unsmoothed = musical_kurtosis(rough[sr:-sr], sr)/original
    emit('MUSICAL_NOISE', dict(smoothed_ratio=ratio, unsmoothed_ratio=unsmoothed))
    assert ratio <= 1.5
    assert unsmoothed > 1.5


@pytest.mark.parametrize('op', OPS)
def test_fx_bounded_silence_neutral_and_band_immutability(enabled, op):
    sr = 16000
    x = H.white_noise(-12, sr=sr, seconds=.3, channels=2)
    p = dict(op=op, amount=1, lo_hz=400, hi_hz=3000)
    y = render('spectral_fx', x, p, sr)
    assert y.shape == x.shape and np.isfinite(y).all() and np.max(abs(y)) < 20
    np.testing.assert_array_equal(render('spectral_fx', x, {**p, 'amount': 0}, sr), x)
    a = S.analyze(x, sr, window=S.window_samples(2048, sr))
    z = FX.transform(a, P.validate_params('spectral_fx', p))
    outside = (a.frequencies_hz < 400) | (a.frequencies_hz > 3000)
    np.testing.assert_array_equal(z[:, outside], a.spectra[:, outside])
    outside_tone = H.sine(100, sr=sr, seconds=1)
    y = render('spectral_fx', outside_tone, p, sr)
    assert abs(change(outside_tone[sr//4:-sr//4], y[sr//4:-sr//4])) <= .1
    assert not np.any(render('spectral_fx', np.zeros_like(x), p, sr))


def test_fx_shift_gate_contrast_and_blur(enabled):
    sr = 48000
    x = H.sine(1000, sr=sr, seconds=2)
    for op, kwargs, target in [('shift', dict(shift_hz=400), 1400), ('scale', dict(ratio=1.5), 1500)]:
        y = render('spectral_fx', x, dict(op=op, amount=1, **kwargs), sr)
        f = H.fundamental_frequency(y[sr//2:-sr//2], sr, low_hz=1100, high_hz=1800)
        emit('FX_FREQUENCY', dict(op=op, measured_hz=f))
        assert abs(f-target) <= (sr/2048)/2
    x = H.sine(750, -10, sr=sr, seconds=2)+H.sine(3000, -50, sr=sr, seconds=2)
    y = render('spectral_fx', x, dict(op='gate', amount=1, threshold_db=-30), sr)
    sl = slice(sr//2, -sr//2)
    strong = H.band_level(y[sl], sr, 700, 800)['dbfs']-H.band_level(x[sl], sr, 700, 800)['dbfs']
    weak = H.band_level(y[sl], sr, 2950, 3050)['dbfs']-H.band_level(x[sl], sr, 2950, 3050)['dbfs']
    emit('FX_GATE', dict(strong_change=strong, weak_change=weak))
    assert abs(strong) <= .5 and weak <= -40
    a = S.analyze(H.sine(750, -10, sr=sr, seconds=1)+H.sine(3000, -30, sr=sr, seconds=1), sr, window=2048)
    z = FX.transform(a, P.validate_params('spectral_fx', dict(op='contrast', amount=1)))
    i, j = round(750*2048/sr), round(3000*2048/sr)
    difference = np.median(20*np.log10(abs(z[3:-3, i, 0])/abs(z[3:-3, j, 0])))
    original = np.median(20*np.log10(abs(a.spectra[3:-3, i, 0])/abs(a.spectra[3:-3, j, 0])))
    assert abs(difference-2*original) <= 1
    # Isolate the declared amplitude pole using spectra after a known step.
    a = S.analyze(np.zeros((48000, 1)), sr, window=2048)
    a.spectra[:5, 32] = 100
    p = P.validate_params('spectral_fx', dict(op='blur', amount=1, time_ms=200))
    z = FX.transform(a, p)
    frames = np.arange(7, 40)
    slope = np.polyfit(frames*a.hop_samples/sr, np.log(abs(z[frames, 32, 0])), 1)[0]
    measured = -1000/slope
    emit('FX_BLUR', dict(tau_ms=measured, contrast_difference_db=difference))
    assert abs(measured-200) <= 40


def test_random_engine_seed_and_roboticity(enabled):
    sr = 16000
    x = H.white_noise(sr=sr, seconds=1, channels=2)
    for kind, p in [('spectral_fx', dict(op='scramble', amount=1, rate_hz=7)),
                    ('spectral_fx', dict(op='phase', phase_mode='random', amount=1)),
                    ('spectral_freeze', dict(freeze_start_s=[.2], freeze_end_s=[.9], input_during='mute'))]:
        a = render(kind, x, p, sr, seed=10)
        np.testing.assert_array_equal(a, render(kind, x, p, sr, seed=10))
        assert not np.array_equal(a, render(kind, x, p, sr, seed=11))
        assert not np.array_equal(a, render(kind, x, p, sr, seed=10, item='other'))
        excerpt = H.render_excerpt(kind, x, sr, sr//3, sr, p, stage='track', seed=10)
        # Harness uses its own stable item id, so compare to its full render.
        full = H.render(kind, x, sr, p, stage='track', seed=10).audio
        np.testing.assert_array_equal(excerpt, full[sr//3:])
    stationary = H.sine(32*sr/S.window_samples(2048, sr), sr=sr, seconds=2)
    y = render('spectral_fx', stationary, dict(op='phase', phase_mode='zero', amount=1), sr)
    hop = S.window_samples(2048, sr)//4
    assert H.null(y[sr:len(y)-4*hop], y[sr+hop:len(y)-3*hop])['rms_dbfs'] <= -60


def test_freeze_interval_validation_and_exact_outside(enabled):
    x = H.white_noise(sr=16000, seconds=2)
    np.testing.assert_array_equal(render('spectral_freeze', x), x)
    p = dict(freeze_start_s=[.2, 1.2], freeze_end_s=[.9, 1.8], capture_ms=100, drift=.5,
             input_during='mute')
    y = render('spectral_freeze', x, p)
    mask = np.ones(len(x), bool)
    for a, b in zip(p['freeze_start_s'], p['freeze_end_s']):
        mask[round(a*16000):round(b*16000)] = False
    np.testing.assert_array_equal(y[mask], x[mask])
    for bad in [dict(freeze_start_s=[0]), dict(freeze_start_s=[1], freeze_end_s=[.5]),
                dict(freeze_start_s=[0, .5], freeze_end_s=[.6, 1])]:
        with pytest.raises(ParamError):
            P.validate_params('spectral_freeze', bad)


def test_freeze_advance_frequency(enabled):
    sr = 16000
    x = H.sine(1000, sr=sr, seconds=3)
    p = dict(freeze_start_s=[.5], freeze_end_s=[2.9], phase_mode='advance', input_during='mute')
    y = render('spectral_freeze', x, p, sr)
    f = H.fundamental_frequency(y[sr:2*sr], sr, low_hz=900, high_hz=1100)
    emit('FREEZE_ADVANCE', dict(input_hz=1000, output_hz=f, error_hz=abs(f-1000)))
    assert abs(f-1000) <= 1


def test_freeze_30s_spectrum_and_no_loop(enabled):
    sr = 8000
    x = H.pink_noise(-20, sr=sr, seconds=31, seed=14)
    p = dict(freeze_start_s=[.5], freeze_end_s=[30.9], input_during='mute', capture_ms=500)
    y = render('spectral_freeze', x, p, sr)
    centers = [125, 250, 500, 1000, 2000]
    # Independent full-second FFT band energy, over 30 seconds of freeze.
    levels = np.array([[H.band_level(y[int(s*sr):int((s+1)*sr)], sr, f*2**(-1/6), f*2**(1/6))['dbfs']
                        for f in centers] for s in range(1, 30)])
    capture = x[round(.5*sr):sr]
    original = np.array([H.band_level(capture, sr, f*2**(-1/6), f*2**(1/6))['dbfs'] for f in centers])
    variation = np.ptp(levels, axis=0)
    offset = np.mean(levels, axis=0)-original
    v = y[sr:3*sr, 0]
    corr = signal.fftconvolve(v, v[::-1], mode='full')[len(v)-1:]/np.sum(v*v)
    hop = S.window_samples(4096, sr)//4
    lags = np.arange(round(.02*sr), sr)
    outside_hop = np.minimum(lags % hop, hop-lags % hop) > 2
    peak = float(np.max(abs(corr[lags[outside_hop]])))
    emit('FREEZE_30S', dict(variation_db=variation.tolist(), capture_offset_db=offset.tolist(),
                           off_hop_correlation=peak))
    assert np.max(variation) <= .5
    assert np.max(abs(offset)) <= 1
    assert peak < .2


# 統括の判断 D-21(c): scramble permutes bins as its intended effect;
# stationary-sine envelope preservation is not an acceptance condition.
@pytest.mark.parametrize('op', [pytest.param(op, marks=pytest.mark.xfail(strict=True,
    reason='Remaining active-effect S4 miss; see C7b report.'))
    if op in ('contrast', 'phase', 'smear_freq') else op for op in OPS if op != 'scramble'])
def test_fx_s4_measured_ripple(enabled, op):
    sr = 48000
    x = H.sine(1000, sr=sr, seconds=3)
    y = render('spectral_fx', x, dict(op=op, amount=1), sr)
    envelope = abs(signal.hilbert(y[sr:-sr, 0]))
    ripple = float(20*np.log10(np.max(envelope)/np.min(envelope)))
    emit('FX_S4', dict(op=op, ripple_db=ripple))
    assert ripple <= .05


@pytest.mark.parametrize('kind', list(MODULES))
def test_common_ct(enabled, kind):
    module = MODULES[kind]
    p = {} if kind != 'spectral_fx' else dict(op='gate', amount=1)
    neutral = dict(amount=0) if kind != 'spectral_freeze' else dict(freeze_start_s=[], freeze_end_s=[])
    def probe(x, y, sr, p):
        freq = H.fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
        gain = change(x[round(.04*sr):-round(.04*sr)], y[round(.04*sr):-round(.04*sr)])
        return dict(passed=abs(freq-1000) < 1 and abs(gain) < .1, frequency_hz=freq, gain_db=gain)
    result = H.assert_common_tests(kind, params=p, neutral=neutral, seconds=.12,
        sr_probe=probe, declared_latency=module.latency_samples,
        latency_probe=lambda x, sr, p, **kw: module.IMPLS[kind](x, sr, p, compensate=False)[0],
        latency_params=neutral)
    assert all(result[f'CT-{i}']['passed'] for i in range(1, 9))


@pytest.mark.parametrize('kind', list(MODULES))
def test_declared_defaults_and_all_parameter_endpoints(kind):
    definition = P.describe(kind)
    defaults = P.validate_params(kind, {})
    assert defaults == {p['id']: p['default'] for p in definition['params']}
    assert definition['stages'] == ['track', 'bus'] and definition['master_slot'] is None
    assert definition['offline_only'] == (kind == 'denoise')
    sr = 96000
    x = H.sine(1000, sr=sr, seconds=.025, channels=2)
    for d in definition['params']:
        if d['type'] in ('float', 'int'):
            values = [d['min'], d['max']]
        elif d['type'] == 'float_array':
            # Relationship-valid interval endpoints, including max time/max count.
            values = [[], [d['min']], [d['max']]]
        elif d['type'] == 'bool':
            values = [False, True]
        else:
            values = d['choices']
        for v in values:
            p = {d['id']: v}
            if 'amount' in defaults:
                p['amount'] = 1 if d['id'] != 'amount' else v
            if d['id'] == 'lo_hz':
                p['hi_hz'] = max(v+1, defaults['hi_hz'])
            if d['id'] == 'hi_hz':
                p['lo_hz'] = min(v-1, defaults['lo_hz'])
                if p['lo_hz'] < 20:
                    # hi_hz=20 requires lo_hz<20, outside declared domain.
                    with pytest.raises(ParamError):
                        P.validate_params(kind, p)
                    continue
            if kind == 'denoise' and d['id'] == 'profile' and v == 'region':
                # Runtime bounds on profiles are separately tested on long audio.
                p.update(profile_start_s=.1, profile_end_s=.8)
                audio = H.white_noise(sr=sr, seconds=1)
            else:
                audio = x
            if d['id'] in ('start_s', 'end_s'):
                p.update(start_s=0, end_s=v)
            if d['id'] in ('freeze_start_s', 'freeze_end_s'):
                p.update(freeze_start_s=[0] if v else [], freeze_end_s=[36000] if v else [])
            y = direct(kind, audio, p, sr)[0]
            assert y.shape == audio.shape and np.isfinite(y).all()
    # Explicit maximum interval array count without overlap.
    if kind == 'spectral_freeze':
        direct(kind, x, dict(freeze_start_s=list(np.arange(32)*2.),
                            freeze_end_s=list(np.arange(32)*2.+1)), sr)


def test_registration_honesty():
    for kind, module in MODULES.items():
        assert P.describe(kind)['implemented'] == module.SPECS[0]['implemented']
        if not module.SPECS[0]['implemented']:
            with pytest.raises(ChainError, match='not implemented'):
                render(kind, np.zeros((64, 1)))


def test_spec_numeric_ranges_and_defaults_independently():
    # Independent literals from the specification, not generated from SPECS.
    common = dict(lo_hz=(20, 20000, 20), hi_hz=(20, 24000, 20000))
    expected = {
        'denoise': {**common, 'amount': (0, 1, 1), 'start_s': (0, 36000, 0),
            'end_s': (0, 36000, 0), 'profile_start_s': (0, 36000, 0),
            'profile_end_s': (0, 36000, 0), 'reduction_db': (0, 40, 12),
            'sensitivity': (-12, 12, 0), 'time_smooth_ms': (0, 500, 80),
            'freq_smooth_oct': (0, 1, .1), 'transient_protect': (0, 1, .5)},
        'spectral_fx': {**common, 'mix': (0, 1, 1), 'amount': (0, 1, 0),
            'seed': (0, 65535, 0), 'time_ms': (10, 5000, 200),
            'threshold_db': (-80, 0, -30), 'shift_hz': (-4000, 4000, 100),
            'ratio': (.25, 4, 1.5), 'block_hz': (20, 2000, 200),
            'rate_hz': (0, 50, 0), 'exponent': (.25, 4, 2), 'width_oct': (.05, 2, .3)},
        'spectral_freeze': {'capture_ms': (0, 500, 0), 'fade_in_ms': (0, 5000, 30),
            'fade_out_ms': (0, 5000, 500), 'drift': (0, 1, 0),
            'freeze_db': (-24, 12, 0), 'seed': (0, 65535, 0)}}
    enums = {
        'denoise': dict(window=([1024, 2048, 4096], 2048),
            profile=(['region', 'auto'], 'auto'), method=(['wiener', 'log_mmse', 'subtract'], 'log_mmse')),
        'spectral_fx': dict(window=([1024, 2048, 4096], 2048),
            op=(OPS, 'blur'), phase_mode=(['zero', 'random', 'hold'], 'zero')),
        'spectral_freeze': dict(window=([2048, 4096, 8192, 16384], 4096),
            phase_mode=(['advance', 'random'], 'random'), input_during=(['mute', 'pass'], 'pass'))}
    for kind, numbers in expected.items():
        ps = {p['id']: p for p in P.describe(kind)['params']}
        for key, values in numbers.items():
            assert tuple(ps[key][v] for v in ('min', 'max', 'default')) == values
        for key, (choices, default) in enums[kind].items():
            assert ps[key]['choices'] == choices and ps[key]['default'] == default
    for key in ('freeze_start_s', 'freeze_end_s'):
        p = {p['id']: p for p in P.describe('spectral_freeze')['params']}[key]
        assert (p['min'], p['max'], p['max_len'], p['default']) == (0, 36000, 32, [])


def test_empty_and_runtime_profile_bounds():
    for kind in MODULES:
        y = direct(kind, np.empty((0, 2)))[0]
        assert y.shape == (0, 2)
    with pytest.raises(ParamError):
        direct('denoise', np.ones((16000, 1)), region_params(profile_end_s=3))


def test_freeze_random_no_loop_independent_of_stability(enabled):
    sr = 8000
    x = H.white_noise(sr=sr, seconds=5)
    y = render('spectral_freeze', x, dict(freeze_start_s=[.2], freeze_end_s=[4.9],
                                        input_during='mute'), sr)
    v = y[sr:3*sr, 0]
    corr = signal.fftconvolve(v, v[::-1], mode='full')[len(v)-1:]/np.sum(v*v)
    hop = S.window_samples(4096, sr)//4
    lags = np.arange(round(.02*sr), sr)
    outside = np.minimum(lags % hop, hop-lags % hop) > 2
    peak = float(np.max(abs(corr[lags[outside]])))
    emit('FREEZE_NO_LOOP', dict(off_hop_correlation=peak))
    assert peak < .2


def test_phase_hold_gate_invert_and_active_freeze_full_scale(enabled):
    sr = 16000
    x = H.sine(1000, sr=sr, seconds=.5)+H.sine(2500, -60, sr=sr, seconds=.5)
    a = S.analyze(x, sr, window=S.window_samples(2048, sr))
    p = P.validate_params('spectral_fx', dict(op='phase', phase_mode='hold', amount=1))
    held = FX.transform(a, p)
    use = (a.frequencies_hz > 100) & (a.frequencies_hz < 5000)
    np.testing.assert_allclose(np.angle(held[:, use]), np.broadcast_to(np.angle(a.spectra[:1, use]), held[:, use].shape), atol=1e-12)
    out = render('spectral_fx', x, dict(op='gate', amount=1, invert=True), sr)
    assert (H.band_level(out[sr//4:], sr, 900, 1100)['dbfs']
            -H.band_level(x[sr//4:], sr, 900, 1100)['dbfs']) <= -40
    fullscale = np.sign(H.white_noise(sr=sr, seconds=.5, channels=2))
    for mode in ('advance', 'random'):
        y = render('spectral_freeze', fullscale,
            dict(freeze_start_s=[.1], freeze_end_s=[.45], phase_mode=mode,
                 input_during='mute', freeze_db=12, drift=1), sr)
        assert y.shape == fullscale.shape and np.isfinite(y).all()
