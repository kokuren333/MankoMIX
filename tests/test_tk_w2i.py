"""W2i analysis primitives and processor acceptance, with measured diagnostics."""
import json
import math
import numpy as np
import pytest
from scipy import signal, fft
from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb import stft, ar, onsets, meters, crossover as C
from mankomix.dspx.procs import mb_limiter as ML, mb_transient as MT, deplosive as DP
from mankomix.core.measure import loudness as L
from mankomix.core.measure.vector import health
from mankomix.core.measure.bands import Spectrum
from mankomix.core.measure.stereo import band_stereo
from tests import toolimpl_harness as H

TYPES = ('deplosive', 'mb_transient', 'mb_limiter')


def render(kind, x, p=None, sr=48000):
    return H.render(kind, x, sr, p or {}, stage='track').audio


def dbgain(x, y):
    return H.rms_dbfs(y)-H.rms_dbfs(x)


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_stft_grid_fft_cola_and_empty(sr):
    x = H.white_noise(sr=sr, seconds=.04, channels=2)
    st = stft.analyze(x, sr)
    assert st.spectra.dtype == np.complex128
    np.testing.assert_array_equal(st.samples, np.arange(0, len(x), 256))
    np.testing.assert_allclose(stft.cola_weights(st.window, 256), 2, atol=1e-14)
    padded = np.pad(x, ((512, 1024), (0, 0)))
    for k in (0, len(st.samples)-1):
        expected = fft.rfft(padded[st.samples[k]:st.samples[k]+1024]*st.window[:, None], axis=0, workers=1)
        np.testing.assert_array_equal(st.spectra[k], expected)
    assert stft.analyze(np.empty((0, 2)), sr).spectra.shape == (0, 513, 2)
    assert stft.analyze(np.ones(12), sr, window=17, hop=3).spectra.shape == (4, 9, 1)


def test_ar_model_residual_lsar_bounds_and_clean_samples():
    rng = np.random.Generator(np.random.PCG64(4))
    noise = rng.standard_normal(12000)
    v = signal.lfilter([1], [1, -1.5, .7], noise)
    model = ar.burg(v, 2)
    np.testing.assert_allclose(model, [1, -1.5, .7], atol=.015)
    assert ar.robust_scale(ar.residual(v, model)[100:]) == pytest.approx(1, abs=.04)
    sr = 48000
    t = np.arange(3000)/sr
    x = .3*np.sin(2*np.pi*440*t)+.1*np.sin(2*np.pi*900*t)
    bad = np.zeros(len(x), dtype=bool)
    bad[1200:1250] = True
    bad[2000:2020] = True
    damaged = x.copy()
    damaged[bad] = 0
    y = ar.interpolate(damaged, bad, order=12, context=500)
    np.testing.assert_array_equal(y[~bad], x[~bad])
    error = H.rms_dbfs((y-x)[bad])
    assert error < -55
    blend = ar.bidirectional(x[700:1200], x[1250:1750], 50, order=12)
    assert H.rms_dbfs(blend-x[1200:1250]) < -50
    bounded = ar.interpolate(damaged, bad, order=12, lower=-.05, upper=.05)
    assert np.max(abs(bounded[bad])) <= .05
    np.testing.assert_array_equal(bounded[~bad], x[~bad])
    stereo = np.column_stack([damaged, damaged*.5])
    fixed = ar.interpolate(stereo, bad, order=12)
    assert H.rms_dbfs(fixed[bad, 0]-x[bad]) < -50
    assert np.isfinite(ar.interpolate(np.zeros(12), np.ones(12, bool))).all()
    print('AR', json.dumps({'gap_rms_error_dbfs': error}))


def drum_sequence(sr, count=200):
    # Three velocities, three spectra, seeded overlapping broadband noise.
    positions = np.round((.12+np.arange(count)*.16)*sr).astype(int)
    x = H.white_noise(-54, sr=sr, seconds=(positions[-1]/sr+.3), seed=11)
    for i, n in enumerate(positions):
        hit = H.drum(('kick', 'snare', 'hat')[i%3], dbfs=(-8, -14, -20)[(i//3)%3],
                     sr=sr, seconds=.14, seed=i)
        x[n:n+len(hit)] += hit
    return x, positions


def match_events(found, truth, tolerance):
    unused = list(map(int, found))
    errors = []
    for n in truth:
        if not unused:
            break
        j = int(np.argmin(np.abs(np.asarray(unused)-n)))
        if abs(unused[j]-n) <= tolerance:
            errors.append(unused.pop(j)-n)
    f = 2*len(errors)/max(1, len(found)+len(truth))
    return f, np.asarray(errors)


def test_onsets_200_drum_hits():
    sr = 48000
    x, truth = drum_sequence(sr)
    events = onsets.detect_onsets(x, sr)
    found = [e['sample'] for e in events]
    f, err = match_events(found, truth, sr*.01)
    median = np.median(abs(err))/sr*1000 if len(err) else math.inf
    print('ONSETS_DRUM', json.dumps({'count': len(events), 'f_score': f, 'median_error_ms': median}))
    assert f >= .95
    assert median <= 2
    assert events == onsets.detect_onsets(x, sr)
    assert all(e['id'] == f"o_{e['sample']}" and 0 <= e['strength'] <= 1 and
               sum(e['band_ratios'].values()) == pytest.approx(1) for e in events)


def test_onsets_soft_vowels_and_stationary_fades():
    sr = 48000
    truth = np.round((.1+np.arange(16)*.35)*sr).astype(int)
    x = np.zeros((truth[-1]+round(.3*sr), 1))
    for i, n in enumerate(truth):
        v = H.vowel(f0=150+i%3*20, sr=sr, seconds=.25)
        ramp = round(.015*sr)
        v[:ramp] *= np.linspace(0, 1, ramp)[:, None]
        v[-ramp:] *= np.linspace(1, 0, ramp)[:, None]
        x[n:n+len(v)] += v
    found = [e['sample'] for e in onsets.detect_onsets(x, sr, kind='soft')]
    f, err = match_events(found, truth, sr*.03)
    print('ONSETS_SOFT', json.dumps({'count': len(found), 'f_score': f, 'median_error_ms': float(np.median(abs(err))/sr*1000) if len(err) else None}))
    assert f >= .85
    for kind in ('soft', 'percussive'):
        for freq in (80, 1000):
            tone = H.sine(freq, sr=sr, seconds=1.2)
            assert onsets.detect_onsets(tone, sr, kind=kind) == []
            assert onsets.detect_onsets(tone*np.linspace(0, 1, len(tone))[:, None], sr, kind=kind) == []


def test_onsets_sample_rate_invariance_and_band_features():
    times = []
    for sr in (44100, 48000, 96000):
        x, truth = drum_sequence(sr, 12)
        events = onsets.detect_onsets(x, sr)
        f, err = match_events([e['sample'] for e in events], truth, sr*.01)
        assert f == 1
        times.append(np.array([e['sample']/sr for e in events]))
        feat = onsets.onset_features(x, sr)
        assert feat.window_samples == round(1024*sr/48000)
        assert feat.hop_samples == round(256*sr/48000)
        np.testing.assert_allclose(feat.flux['full'], feat.flux['low']+feat.flux['mid']+feat.flux['high'], atol=1e-12)
        for band in ('low', 'mid', 'high'):
            assert isinstance(onsets.detect_onsets(x, sr, band=band), list)
    assert np.max(abs(times[0]-times[1])) <= .001
    assert np.max(abs(times[2]-times[1])) <= .001
    print('ONSETS_SR', json.dumps({'max_44100_48000_ms': float(np.max(abs(times[0]-times[1]))*1000),
                                  'max_96000_48000_ms': float(np.max(abs(times[2]-times[1]))*1000)}))


def test_meters_existing_values_timelines_decimation_spectrogram():
    sr = 48000
    x = H.white_noise(-14, sr=sr, seconds=.8, channels=2)
    x[4800] = .9
    result = meters.measure(x, sr)
    assert result['lufs_i'] == L.integrated(x, sr)
    assert result['sample_peak_dbfs'] == L.sample_peak_dbfs(x)
    assert result['true_peak_dbtp'] == L.true_peak_dbtp(x, sr)
    assert result['health'] == health(x)
    assert result['stereo'] == band_stereo(Spectrum(x, sr))
    tl = meters.timeline(x, sr)
    np.testing.assert_array_equal(tl['momentary'], L.momentary(x, sr))
    np.testing.assert_array_equal(tl['short_term'], L.short_term(x, sr))
    for i, n in enumerate(tl['samples']):
        assert tl['sample_peak_dbfs'][i] == L.sample_peak_dbfs(x[n:n+4800])
        assert tl['true_peak_dbtp'][i] == L.true_peak_dbtp(x[tl['true_peak_start_samples'][i]:tl['true_peak_end_samples'][i]], sr)
    assert np.max(meters.decimate(tl['sample_peak_dbfs'], 3, peak=True)) == L.sample_peak_dbfs(x)
    np.testing.assert_array_equal(meters.decimate([1, 2, 9, 4, 3], 2, peak=True), [2, 9, 3])
    spec = meters.spectrogram(x, sr)
    st = stft.analyze(x, sr)
    k = 4
    n = st.samples[k]
    expected = np.sum((x[n-512:n+512]*st.window[:, None])**2, axis=0)/np.sum(st.window**2)
    np.testing.assert_allclose(spec['power'][k].sum(axis=0), expected, atol=1e-14)
    assert meters.stereo_bands(x[:, :1], sr) is None
    assert meters.timeline(np.empty((0, 1)), sr)['samples'].size == 0


@pytest.mark.parametrize('phase', ['linear', 'minimum'])
def test_mb_transient_neutral_reconstruction(phase):
    sr = 48000
    x = H.impulse(sr=sr, seconds=.6)
    p = P.validate_params('mb_transient', {'phase': phase})
    y = render('mb_transient', x, p)
    expected = C.recombine_bands(C.split_mb(x, sr, p)[0])
    np.testing.assert_array_equal(y, expected)
    if phase == 'linear':
        assert H.null(x, y)['peak_dbfs'] <= -120
    else:
        assert np.max(abs(20*np.log10(abs(fft.rfft(y[:, 0]))))) <= .01


@pytest.mark.parametrize('band,freq', [(0, 80), (1, 1000), (2, 7000)])
def test_mb_transient_attack_sustain_each_band(band, freq):
    sr = 48000
    x = H.tone_burst(freq=freq, sr=sr, seconds=.65)
    neutral = render('mb_transient', x, {'phase': 'linear'})
    for attack, sustain in ((6, 0), (0, 6), (0, -6)):
        a, s = [0]*3, [0]*3
        a[band], s[band] = attack, sustain
        p = {'phase': 'linear', 'attack_db': a, 'sustain_db': s}
        y = render('mb_transient', x, p)
        head = H.peak_dbfs(y[:round(.01*sr)])-H.peak_dbfs(neutral[:round(.01*sr)])
        tail = dbgain(neutral[round(.1*sr):round(.3*sr)], y[round(.1*sr):round(.3*sr)])
        print('TRANSIENT', band, attack, sustain, head, tail)
        if attack:
            assert head == pytest.approx(6, abs=1)
            assert abs(dbgain(neutral[round(.2*sr):], y[round(.2*sr):])) <= .5
        else:
            assert tail == pytest.approx(sustain, abs=1.5)
            assert abs(head) <= .5


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_limiter_random_ceiling_neutral_thd_latency(sr):
    rng = np.random.Generator(np.random.PCG64(18))
    for i in range(8):
        edges = [150, 2500] if i%2 else []
        p = P.validate_params('mb_limiter', {'crossovers_hz': edges, 'phase': ('linear', 'minimum')[i%3 == 0],
             'threshold_db': rng.uniform(-24, 0, len(edges)+1).tolist(),
             'release_ms': rng.uniform(5, 2000, len(edges)+1).tolist(),
             'lookahead_ms': float(rng.uniform(.5, 10)), 'stereo_link': bool(i%2),
             'out_ceiling_db': float(rng.uniform(-24, 0))})
        x = rng.standard_normal((round(.025*sr), 2))*rng.uniform(.1, 5)
        y, _, stats = ML.mb_limiter(x, sr, p)
        assert np.max(abs(y)) <= 10**(p['out_ceiling_db']/20)
        assert all(v is None or v <= ceiling+.05 for v, ceiling in zip(stats['band_sample_peaks_dbfs'], p['threshold_db']))
        assert stats['true_peak_dbtp'] == L.true_peak_dbtp(y, sr)
    x = H.sine(1000, -6, sr=sr, seconds=.2)
    p = P.validate_params('mb_limiter', {'threshold_db': [0]*3, 'out_ceiling_db': 0})
    assert H.null(x, ML.mb_limiter(x, sr, p)[0])['peak_dbfs'] <= -120
    pulse = H.impulse(at_s=.02, sr=sr, seconds=.4, dbfs=-6)
    delay = ML.latency_samples(sr, p)
    raw = ML.mb_limiter(pulse, sr, p, compensate=False)[0]
    assert H.latency(raw)-round(.02*sr) == delay
    assert H.latency(ML.mb_limiter(pulse, sr, p)[0])-round(.02*sr) == 0
    x = H.sine(1000, 0, sr=sr, seconds=.3)
    y = render('mb_limiter', x, {'crossovers_hz': [], 'threshold_db': [-3], 'out_ceiling_db': 0}, sr)
    thd = H.thd(y[round(.1*sr):], sr, 1000)['thd_db']
    print('LIMITER', sr, 'thd_db', thd)
    assert thd <= -60


def damaged_vowel(sr=16000, count=30):
    truth = np.round((.3+np.arange(count)*.3)*sr).astype(int)
    x = H.vowel(f0=180, sr=sr, seconds=truth[-1]/sr+.4, dbfs=-20)
    for i, n in enumerate(truth):
        t = np.arange(round(.06*sr))/sr
        burst = .6*np.sin(2*np.pi*(40+(i%5)*20)*t)*np.exp(-t/.025)
        x[n:n+len(t), 0] += burst
    return x, truth


def test_deplosive_30_bursts_ratio_bass_and_exact_event_exterior():
    sr = 16000
    x, truth = damaged_vowel(sr)
    p = P.validate_params('deplosive', {})
    y, _, stats = DP.deplosive(x, sr, p)
    detected = stats['onset_samples']
    f, errors = match_events(detected, truth, sr*.03)
    low_changes, high_changes = [], []
    for n in truth:
        a, b = n, n+round(.06*sr)
        low_changes.append(H.band_level(y[a:b], sr, 20, 150)['dbfs']-H.band_level(x[a:b], sr, 20, 150)['dbfs'])
        high_changes.append(H.band_level(y[a:b], sr, 300, 7000)['dbfs']-H.band_level(x[a:b], sr, 300, 7000)['dbfs'])
    print('DEPLOSIVE', json.dumps({'count': len(detected), 'recall': len(errors)/len(truth),
          'low_db_max': max(low_changes), 'high_db_max_abs': max(abs(np.asarray(high_changes))),
          'median_ratio_db': stats['ratio_median_db']}))
    assert len(errors)/len(truth) >= .9
    assert max(low_changes) <= -10
    assert max(abs(np.asarray(high_changes))) <= .5
    spans = np.zeros(len(x), bool)
    for e in stats['events']:
        a = round(e['start_s']*sr)
        b = a+round(e['length_s']*sr)
        spans[a:b] = True
    np.testing.assert_array_equal(y[~spans], x[~spans])
    np.testing.assert_array_equal(np.any(x != y, axis=1), spans)
    bass = H.sine(80, sr=sr, seconds=1)
    out, _, stats = DP.deplosive(bass, sr, p)
    np.testing.assert_array_equal(out, bass)
    assert stats['event_count'] == 0


def test_deplosive_rp_contract_and_four_clean_materials():
    sr = 16000
    x, _ = damaged_vowel(sr, 4)
    assert np.array_equal(render('deplosive', x, {'amount': 0, 'delta': True}, sr), x)
    y = render('deplosive', x, sr=sr)
    delta = render('deplosive', x, {'delta': True}, sr)
    assert H.null(y+delta, x)['peak_dbfs'] <= -120
    region = render('deplosive', x, {'start_s': .4, 'end_s': 1}, sr)
    np.testing.assert_array_equal(region[:round(.4*sr)], x[:round(.4*sr)])
    np.testing.assert_array_equal(region[sr:], x[sr:])
    clean = [H.sine(430, sr=sr)+H.sine(900, sr=sr), H.pink_noise(sr=sr),
             H.vowel(sr=sr), H.kick_train(sr=sr)]
    for a in clean:
        y, _, stats = DP.deplosive(a, sr, P.validate_params('deplosive', {}))
        value = stats['removed_energy_rel_db']
        assert value is None or value <= -60
        print('RP_CLEAN', value, stats['event_count'])


@pytest.mark.parametrize('kind', TYPES)
def test_parameter_defaults_ranges_and_common_ct(kind):
    modules = {'deplosive': DP, 'mb_transient': MT, 'mb_limiter': ML}
    module = modules[kind]
    definition = P.describe(kind)
    default = P.validate_params(kind, {})
    assert default == {d['id']: d['default'] for d in definition['params']}
    # Exercise every numeric endpoint and every enum/bool value. Crossovers
    # are tested at 96k, where the declared 20 kHz maximum is legal.
    x = H.sine(1000, sr=96000, seconds=.015)
    for d in definition['params']:
        if d['type'] in ('float', 'int', 'float_array'):
            vals = [d['min'], d['max']]
            if d['id'] == 'crossovers_hz':
                vals = [[d['min']], [d['max']]]
            elif d['type'] == 'float_array':
                vals = [[v]*3 for v in vals]
        elif d['type'] == 'bool':
            vals = [False, True]
        else:
            vals = d['choices']
        for value in vals:
            change = {d['id']: value}
            if d['id'] == 'crossovers_hz':
                change.update({k: [] for k in ('attack_db', 'sustain_db', 'threshold_db', 'release_ms') if k in default})
            if kind == 'deplosive' and d['id'] in ('start_s', 'end_s'):
                change.update(start_s=0, end_s=value)
            if kind == 'deplosive' and d['id'] == 'min_ms':
                change['max_ms'] = max(default['max_ms'], value)
            p = P.validate_params(kind, change)
            out = getattr(module, kind)(x, 96000, p)[0]
            assert out.shape == x.shape and np.isfinite(out).all()
    def probe(a, y, sr, p):
        # Probe a declared physical quantity: unity steady tone, including
        # crossover phase and compensation, at each specified rate/layout.
        measured = H.fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
        delta = dbgain(a[round(.03*sr):], y[round(.03*sr):])
        return {'frequency_hz': measured, 'gain_db': delta,
                'passed': abs(measured-1000) < 1 and abs(delta) < .1}
    neutral = {'deplosive': {'amount': 0}, 'mb_transient': {'phase': 'linear'},
               'mb_limiter': {'threshold_db': [0]*3, 'out_ceiling_db': 0}}[kind]
    extra = {}
    if kind in ('mb_transient', 'mb_limiter'):
        extra = {'declared_latency': module.latency_samples,
                 'latency_probe': lambda x, sr, p, **kw: getattr(module, kind)(x, sr, p, compensate=False)[0],
                 'invalid_params': [{'crossovers_hz': [300, 150]},
                                    {('attack_db' if kind == 'mb_transient' else 'threshold_db'): [1, 2]}]}
    H.assert_common_tests(kind, neutral=neutral, params={'phase': 'linear'} if kind == 'mb_transient' else {},
                          seconds=.1, sr_probe=probe, **extra)


def test_master_slots_tv_and_invalid_cross_relations():
    from mankomix.dspx.registry import time_varying_types
    assert {'mb_transient', 'mb_limiter'} <= time_varying_types()
    assert 'deplosive' not in time_varying_types()
    assert P.describe('mb_limiter')['master_slot'] == 5
    assert P.describe('mb_transient')['master_slot'] == 2
    E.validate_chain([{'type': 'mb_limiter'}, {'type': 'limiter'}], 'master')
    with pytest.raises(ChainError):
        E.validate_chain([{'type': 'limiter'}, {'type': 'mb_limiter'}], 'master')
    with pytest.raises(ParamError):
        P.validate_params('deplosive', {'min_ms': 50, 'max_ms': 30})
    with pytest.raises(ParamError):
        P.validate_params('deplosive', {'start_s': 2, 'end_s': 1})


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_nonzero_transient_and_deplosive_controls_across_rates(sr):
    x = H.tone_burst(freq=1000, sr=sr, seconds=.6, channels=2)
    p = {'phase': 'linear', 'attack_db': [0, 6, 0]}
    y = render('mb_transient', x, p, sr)
    head = H.peak_dbfs(y[:round(.01*sr)])-H.peak_dbfs(x[:round(.01*sr)])
    assert head == pytest.approx(6, abs=1)
    quieter = render('mb_transient', x*.1, p, sr)
    assert dbgain(x, y) == pytest.approx(dbgain(x*.1, quieter), abs=.3)
    # An independent channel remains unchanged when stereo linking is off.
    mono = render('mb_transient', x[:, :1], dict(p, stereo_link=False), sr)
    np.testing.assert_array_equal(render('mb_transient', x, dict(p, stereo_link=False), sr)[:, :1], mono)
    damaged, truth = damaged_vowel(sr, 3)
    repaired, _, stats = DP.deplosive(damaged, sr, P.validate_params('deplosive', {}))
    _, err = match_events(stats['onset_samples'], truth, sr*.03)
    assert len(err) == 3
    assert np.isfinite(repaired).all()


def test_ar_one_sided_constraints_and_primitive_validation():
    t = np.arange(600)/48000
    x = .4*np.cos(2*np.pi*440*t)
    mask = np.zeros(len(x), bool)
    mask[300:310] = True
    damaged = x.copy()
    damaged[mask] = 0
    lower = np.full(len(x), -np.inf)
    lower[mask] = .2
    y = ar.interpolate(damaged, mask, lower=lower, order=4)
    assert (y[mask] >= .2).all()
    np.testing.assert_array_equal(y[~mask], x[~mask])
    for mask in (np.arange(len(x)), np.zeros((10, 2), bool)):
        with pytest.raises(ParamError):
            ar.interpolate(x, mask)
    with pytest.raises(ParamError):
        ar.interpolate(x, np.zeros(len(x), bool), lower=1, upper=0)
    for kwargs in ({'window': 3}, {'hop': 0}, {'hop': 1025}):
        with pytest.raises(ParamError):
            stft.analyze(x, 48000, **kwargs)
    for kwargs in ({'kind': 'unknown'}, {'threshold': 2}, {'band': 'unknown'}, {'min_interval_ms': 0}):
        with pytest.raises(ParamError):
            onsets.detect_onsets(x, 48000, **kwargs)


def test_ar_long_gap_regularization():
    x = .3*np.sin(2*np.pi*440*np.arange(5000)/48000)
    mask = np.zeros(len(x), bool)
    mask[1600:2800] = True
    damaged = x.copy()
    damaged[mask] = 0
    y = ar.interpolate(damaged, mask, order=12)
    np.testing.assert_array_equal(y[~mask], x[~mask])
    assert np.isfinite(y).all()
    error = H.rms_dbfs(y[mask]-x[mask])
    print('AR_LONG', error)
    # A long gap is underdetermined by the short local model. Require an
    # actual improvement over missing (zero) audio, and record fidelity.
    assert error <= H.rms_dbfs(x[mask])-6
