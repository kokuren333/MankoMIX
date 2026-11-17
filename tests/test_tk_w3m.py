"""W3m independent acoustic acceptance, RP/PT/CT and unresolved limits."""
import json
import numpy as np
import pytest
from scipy import fft, signal
from mankomix.dsp import processors as P, engine as E
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb import stft, dereverberation as D, partials as B
from mankomix.dspx.procs import dereverb as DR, poly_retune as PR
from tests import toolimpl_harness as H

MODULES = dict(dereverb=DR, poly_retune=PR)


def emit(name, value):
    print(name+': '+json.dumps(value, sort_keys=True, ensure_ascii=True))


@pytest.fixture
def enabled(monkeypatch):
    for kind in MODULES:
        monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)


def direct(kind, x, p=None, sr=12000, **kwargs):
    return MODULES[kind].IMPLS[kind](x, sr, P.validate_params(kind, p or {}), **kwargs)


def render(kind, x, p=None, sr=12000):
    return E.render_chain(x, sr, [dict(type=kind, params=p or {})], stage='track').audio


def mapping(note=4, shift=-1):
    m = [0]*12
    m[note] = shift
    return m


def relative_removed(x, y):
    return H.db(H.rms(x-y)/max(H.rms(x), 1e-30))


def chord(sr=12000, seconds=3):
    roots = 440*2**((np.array([60, 64, 67])-69)/12)
    t = np.arange(round(sr*seconds))/sr
    x = sum(.15/h*np.sin(2*np.pi*f*h*t+.13*h) for f in roots for h in range(1, 7))
    return x[:, None], roots


def component_levels(x, sr, frequencies):
    t = np.arange(len(x))/sr
    matrix = np.column_stack([fn(2*np.pi*f*t) for f in frequencies for fn in (np.sin, np.cos)])
    beta = np.linalg.lstsq(matrix, x[:, 0], rcond=None)[0].reshape(-1, 2)
    return np.sqrt(np.sum(beta**2, axis=1))


def room_material(rt, material, sr=8000, channels=1):
    seconds = 4.
    dry = np.zeros((round(sr*seconds), channels))
    for onset, f0 in ((.25, 100), (2., 140)):
        count = round(sr*.15)
        if material == 'vowel':
            source = H.vowel(f0, sr=sr, seconds=.15, channels=channels)
        else:
            source = H.white_noise(sr=sr, seconds=.15, channels=channels, seed=33)
        source = source*signal.windows.tukey(count, .2)[:, None]
        start = round(onset*sr)
        dry[start:start+count] = source
    rng = np.random.Generator(np.random.PCG64(57))
    t = np.arange(round(sr*max(2., 2*rt)))/sr
    ir = rng.normal(size=(len(t), channels))*np.exp(-3*np.log(10)*t[:, None]/rt)
    ir[:round(.05*sr)] = 0
    ir *= np.sqrt(.5/np.maximum(np.sum(ir**2, axis=0), 1e-30))
    ir[0] = 1
    wet = np.column_stack([signal.fftconvolve(dry[:, c], ir[:, c])[:len(dry)] for c in range(channels)])
    return dry, wet, ir


def drr(dry, wet):
    gain = float(np.sum(dry*wet)/np.sum(dry*dry))
    return H.db(H.rms(gain*dry)/max(H.rms(wet-gain*dry), 1e-30))


@pytest.mark.parametrize('method', ['spectral', 'wpe'])
def test_rp_neutral_delta_region_events_and_determinism(enabled, method):
    x = room_material(1., 'burst')[1]
    p = dict(method=method, rt60_s=1., start_s=.6, end_s=1.7, amount=1)
    normal, _, stats = direct('dereverb', x, p, sr=8000)
    delta = direct('dereverb', x, dict(p, delta=True), sr=8000)[0]
    assert H.null(x, normal+delta)['peak_dbfs'] <= -120
    assert normal[:4800].tobytes() == x[:4800].tobytes()
    assert normal[13600:].tobytes() == x[13600:].tobytes()
    changed = np.any(normal != x, axis=1)
    covered = np.zeros(len(x), bool)
    for event in stats['events']:
        left = round(event['start_s']*8000)
        right = left+round(event['duration_s']*8000)
        covered[left:right] = True
    assert np.array_equal(covered, changed)
    assert stats['event_count'] == len(stats['events']) > 0
    assert stats['before']['sample_peak_dbfs'] is not None
    assert stats['removed_energy_bands'] and stats['removed_energy_rel_db'] < 0
    assert render('dereverb', x, p, 8000).tobytes() == normal.tobytes()
    assert render('dereverb', x, p, 8000).tobytes() == normal.tobytes()
    for delta_on in (False, True):
        neutral = direct('dereverb', x, dict(p, amount=0, delta=delta_on), sr=8000)[0]
        assert neutral.tobytes() == x.tobytes()


@pytest.mark.parametrize('material', ['tones', 'pink', 'vowel', 'bursts',
    pytest.param('percussion', marks=pytest.mark.xfail(strict=True,
        reason='A dry decaying snare is misidentified as a reverberant tail; RP4 -40 dB remains unmet.'))])
def test_dereverb_rp4_clean(material):
    sr = 8000
    if material == 'tones':
        x = sum(H.sine(f, sr=sr, seconds=2.5) for f in (137, 443, 997))
    elif material == 'pink':
        x = H.pink_noise(sr=sr, seconds=2.5)
    elif material == 'vowel':
        x = H.vowel(sr=sr, seconds=2.5)
    else:
        x = np.zeros((sr*3, 1))
        burst = (H.tone_burst(700, sr=sr, seconds=1, decay_ms=160) if material == 'bursts'
                 else H.drum('snare', sr=sr, seconds=1))
        x[:sr] = burst
        x[sr*2:] = burst
    y, _, stats = direct('dereverb', x, sr=sr)
    value = relative_removed(x, y)
    emit('rp4_'+material, dict(removed_db=value, rt60_s=stats['rt60_s']))
    assert value <= -40


@pytest.mark.parametrize('rt', [.5, 1., 2.])
@pytest.mark.parametrize('material', ['vowel', 'burst'])
def test_rt60_automatic_estimation(rt, material):
    _, wet, _ = room_material(rt, material)
    estimate, records = D.estimate_rt60(wet, 8000)
    emit('rt_estimate', dict(material=material, truth=rt, estimate=estimate, regions=len(records)))
    assert estimate is not None and abs(estimate/rt-1) <= .25


@pytest.mark.parametrize('method', ['spectral', 'wpe'])
@pytest.mark.parametrize('rt', [.5, 1., 2.])
@pytest.mark.parametrize('material', ['vowel', 'burst'])
@pytest.mark.xfail(strict=True, reason='Original T20 shortening / DRR criteria remain unmet by both late models.')
def test_dereverb_t20_drr_and_direct(method, rt, material):
    sr = 8000
    dry, x, _ = room_material(rt, material)
    y, _, _ = direct('dereverb', x, dict(method=method, rt60_s=rt, amount=1), sr=sr)
    before, after = [], []
    for f in (250, 500, 1000, 2000):
        before.append(H.rt60(x[round(.4*sr):round(1.9*sr)], sr, band_hz=f))
        after.append(H.rt60(y[round(.4*sr):round(1.9*sr)], sr, band_hz=f))
    early = slice(round(.25*sr), round(.3*sr))
    early_db = H.db(H.rms(y[early])/H.rms(x[early]))
    improvement = drr(dry, y)-drr(dry, x)
    emit('dereverb_acoustic', dict(method=method, material=material, rt=rt,
        t20_before=before, t20_after=after, drr_gain_db=improvement, early_db=early_db))
    assert abs(early_db) <= 1
    assert improvement >= 3
    assert all(a is not None and b is not None and b <= .7*a for a, b in zip(before, after))


def test_delayed_power_formula_and_tilt():
    sr = 12000
    a = stft.analyze(H.white_noise(sr=sr, seconds=.4), sr, window=256)
    p = abs(a.spectra)**2
    step = int(np.ceil(.05*sr/a.hop_samples))
    alpha = np.exp(-a.hop_samples/(sr*.02))
    sm = signal.lfilter([1-alpha], [1, -alpha], p, axis=0)
    result = D.late_power(a, 1., 50)
    assert not np.any(result[:step])
    np.testing.assert_allclose(result[step:], sm[:-step]*np.exp(-6*np.log(10)*step*a.hop_samples/sr), rtol=1e-14)
    tilt = D.late_power(a, 1., 50, 3)
    assert np.mean(tilt[:, a.frequencies_hz > 2000]) < np.mean(result[:, a.frequencies_hz > 2000])
    assert D.estimate_rt60(np.zeros((10, 1)), sr) == (None, [])


@pytest.mark.parametrize('channels', [1, 2])
@pytest.mark.parametrize('iterations', [1, 3, 5])
def test_wpe_loaded_rank_deficiency_and_fixed_iterations(channels, iterations):
    # Identical channels, pure tone, and almost-zero bins are ill conditioned.
    rng = np.random.Generator(np.random.PCG64(8))
    z = rng.normal(size=(45, 5, 1))+1j*rng.normal(size=(45, 5, 1))
    z[:, 1] = z[0, 1]
    z[:, 2] = 1e-25
    z[:, 3] = 0
    z = np.repeat(z, channels, axis=2)
    a, info = D.wpe(z, 40, 1, iterations)
    b, _ = D.wpe(z, 40, 1, iterations)
    assert a.tobytes() == b.tobytes() and np.isfinite(a).all()
    assert info == dict(iterations=iterations, loaded_solves=5*iterations)
    assert np.array_equal(a[:1], z[:1])
    assert not np.any(a[:, 3])


def test_harmonic_ownership_and_ambiguous_overlap():
    roots = 440*2**((np.array([60, 64, 67])-69)/12)
    freqs = np.sort(np.ravel(roots[:, None]*np.arange(1, 7)))
    amplitudes = np.array([.15/round(f/roots[np.argmin(abs(f/roots-np.rint(f/roots)))]) for f in freqs])
    bases, owner, ambiguous = B.harmonic_groups(freqs, amplitudes, 1.)
    emit('ownership', dict(roots=bases.tolist(), ambiguous=ambiguous))
    for i, f in enumerate(freqs):
        if abs(f-roots[1]*5) < .01:
            assert abs(bases[owner[i]]-roots[1]) < .1
    # Shared octave/fifth components receive a deterministic owner, not separation.
    b1, o1, count = B.harmonic_groups(np.array([100., 150., 200., 300., 400., 450., 600.]), np.ones(7), 1)
    b2, o2, _ = B.harmonic_groups(np.array([100., 150., 200., 300., 400., 450., 600.]), np.ones(7), 1)
    assert b1.tobytes() == b2.tobytes() and o1.tobytes() == o2.tobytes() and count > 0


@pytest.mark.parametrize('window', [4096, 8192, 16384])
def test_triad_harmonic_frequencies_and_unchanged_levels(window):
    sr = 12000
    x, roots = chord(sr, 4)
    y, _, info = direct('poly_retune', x, dict(map=mapping(), window=window), sr=sr)
    targets = roots.copy()
    targets[1] *= 2**(-1/12)
    errors = []
    for root in targets:
        for h in range(1, 7):
            target = root*h
            frequency = H.fundamental_frequency(y[sr:-sr], sr, low_hz=target*2**(-12/1200), high_hz=target*2**(12/1200))
            errors.append(float(1200*np.log2(frequency/target)))
    original = np.ravel(roots[:, None]*np.arange(1, 7))
    moved = targets[1]*np.arange(1, 7)
    levels_in = component_levels(x[sr:-sr], sr, original)
    levels_out = component_levels(y[sr:-sr], sr, np.r_[original, moved])[:18]
    untouched = np.r_[np.arange(6), np.arange(12, 18)]
    change = 20*np.log10(levels_out[untouched]/levels_in[untouched])
    emit('triad', dict(window=window, errors_cents=errors, unchanged_db=change.tolist(), **info))
    assert max(abs(np.array(errors))) <= 10
    assert max(abs(change)) <= 1


def test_e_fifth_moves_with_its_fundamental():
    sr = 12000
    x, roots = chord(sr, 4)
    y = direct('poly_retune', x, dict(map=mapping()), sr=sr)[0]
    target = roots[1]*5*2**(-1/12)
    measured = H.fundamental_frequency(y[sr:-sr], sr, low_hz=target-8, high_hz=target+8)
    error = 1200*np.log2(measured/target)
    emit('e_fifth', dict(frequency_hz=measured, error_cents=error))
    assert abs(error) <= 10
    old = component_levels(y[sr:-sr], sr, [roots[1]*5, target])
    assert H.db(old[0]/old[1]) < -20


def test_poly_neutral_and_determinism(enabled):
    x, _ = chord(seconds=1)
    for p in ({}, dict(map=mapping(), strength=0)):
        assert render('poly_retune', x, p).tobytes() == x.tobytes()
    p = dict(map=mapping())
    y = render('poly_retune', x, p)
    assert render('poly_retune', x, p).tobytes() == y.tobytes()
    assert H.render_excerpt('poly_retune', x, 12000, 1100, 4700, p, stage='track').tobytes() == y[1100:4700].tobytes()


def test_poly_outside_band_and_below_threshold():
    sr = 12000
    # Shift E4, keep 35 Hz / 4 kHz outside and a separate -80 dB partial inside.
    t = np.arange(sr*3)/sr
    x = (.2*np.sin(2*np.pi*329.6275569*t)+.1*np.sin(2*np.pi*35*t)
         +.05*np.sin(2*np.pi*4000*t)+1e-5*np.sin(2*np.pi*440*t))[:, None]
    a = stft.analyze(x, sr, window=2048)
    m = mapping()
    m[9] = 1
    delta, _ = B.retune_regions(a, m, lo_hz=60, hi_hz=2000, min_peak_db=-60)
    assert not np.any(delta[:, (a.frequencies_hz < 60) | (a.frequencies_hz > 2000)])
    y = direct('poly_retune', x, dict(map=m, hi_hz=2000), sr=sr)[0]
    residual = x[sr:-sr]-y[sr:-sr]
    # Hann analysis excludes rectangular-crop leakage of the legitimate shifted tone.
    win = signal.windows.hann(len(residual), sym=False)
    tapered = residual*win[:, None]/np.sqrt(np.mean(win**2))
    outside = max(H.band_level(tapered, sr, 20, 40)['rms'], H.band_level(tapered, sr, 3900, 4100)['rms'])
    # Compare actual protected residual, not just the internal mask.
    weak = component_levels(residual, sr, [440])[0]
    emit('protected', dict(outside_dbfs=H.db(outside), weak_residual_dbfs=H.db(weak)))
    assert H.db(outside) <= -60 and H.db(weak) <= -60


@pytest.mark.parametrize('transients', [.7, 1])
def test_poly_pt5_click_positions_and_width(transients):
    sr = 12000
    x = np.zeros((sr, 1))
    centers = np.arange(1, 10)*1200
    x[centers] = 1
    y = direct('poly_retune', x, dict(map=mapping(), transients=transients), sr=sr)[0]
    for center in centers:
        seg = y[center-500:center+500, 0]
        assert abs(np.argmax(abs(seg))-500) <= .005*sr
        c = np.r_[0., np.cumsum(seg**2)]
        ends = np.searchsorted(c, c[:-1]+.9*c[-1])
        valid = ends <= len(seg)
        width = np.min(ends[valid]-np.arange(len(seg))[valid])/sr
        assert width <= .01


@pytest.mark.parametrize('sr', [12000, 44100, 48000, 96000])
def test_poly_pt2_pt3_active_sr(sr):
    x = H.sine(440, sr=sr, seconds=1.5)
    target = 440*2**(1/12)
    y = direct('poly_retune', x, dict(map=mapping(9, 1)), sr=sr)[0]
    body = y[round(.4*sr):-round(.4*sr)]
    freq = H.fundamental_frequency(body, sr, low_hz=target-5, high_hz=target+5)
    # Hilbert is computed on full context before cropping its boundary error.
    env = abs(signal.hilbert(y[:, 0]))[round(.4*sr):-round(.4*sr)]
    ripple = H.db(env.max()/env.min())
    cent = 1200*np.log2(freq/target)
    emit('poly_stationary', dict(sr=sr, error_cents=cent, ripple_db=ripple))
    assert abs(cent) <= 3 and ripple <= .2 and y.shape == x.shape


@pytest.mark.parametrize('kind', list(MODULES))
def test_common_ct(enabled, kind):
    module = MODULES[kind]
    # Active frequency, full-scale and stereo checks are measured separately.
    params = dict(method='spectral') if kind == 'dereverb' else dict(map=[0]*12)
    neutral = dict(amount=0) if kind == 'dereverb' else dict(map=[0]*12)
    def probe(x, y, sr, p):
        target = 1000
        body = y[round(.04*sr):-round(.04*sr)]
        freq = H.fundamental_frequency(body, sr, low_hz=target-5, high_hz=target+5)
        error = 1200*np.log2(freq/target)
        gain = H.db(H.rms(body)/H.rms(x[round(.04*sr):-round(.04*sr)]))
        return dict(passed=abs(error) <= 3 and abs(gain) <= 1, frequency_hz=freq, error_cents=error, gain_db=gain)
    report = H.assert_common_tests(kind, params=params, neutral=neutral, seconds=.24,
        sr_probe=probe, declared_latency=module.latency_samples, latency_params=neutral,
        latency_probe=lambda x, sr, p, **kw: module.IMPLS[kind](x, sr, p, compensate=False)[0],
        invalid_params=[dict(map=[0]*11)] if kind == 'poly_retune' else [dict(rt60_s=.05), dict(start_s=2, end_s=1)])
    assert all(report[f'CT-{i}']['passed'] for i in range(1, 9))


@pytest.mark.parametrize('kind', list(MODULES))
def test_independent_spec_ranges_defaults_and_metadata(kind):
    expected = dict(
        dereverb=dict(amount=(0, 1, .5), delta=(False,), start_s=(0, 36000, 0), end_s=(0, 36000, 0),
            method=(['spectral', 'wpe'], 'spectral'), rt60_s=(0, 10, 0), reduction_db=(0, 30, 9),
            early_ms=(10, 150, 50), time_smooth_ms=(0, 300, 60), band_tilt=(-3, 3, 0),
            wpe_taps=(4, 40, 12), wpe_delay=(1, 6, 3), wpe_iter=(1, 5, 3), window=([1024, 2048], 1024)),
        poly_retune=dict(map=(-6, 6, [0]*12), a4_hz=(400, 480, 440), strength=(0, 1, 1),
            window=([4096, 8192, 16384], 8192), lo_hz=(20, 500, 60), hi_hz=(1000, 20000, 12000),
            min_peak_db=(-90, -30, -60), transients=(0, 1, .7)))
    spec = P.describe(kind)
    assert set(expected[kind]) == {d['id'] for d in spec['params']}
    assert spec['stages'] == (['track'] if kind == 'dereverb' else ['track', 'bus'])
    assert spec['offline_only'] and spec['master_slot'] is None and spec['backends'] == ['reference']
    assert spec['realtime']['block_ok'] is False
    for d in spec['params']:
        table = expected[kind][d['id']]
        if d['type'] in ('float', 'int', 'float_array'):
            assert (d['min'], d['max'], d['default']) == table
        elif d['type'] == 'enum':
            assert (d['choices'], d['default']) == table
        else:
            assert (d['default'],) == table
    assert P.validate_params(kind, {}) == {d['id']: d['default'] for d in spec['params']}
    from mankomix.director.direction import TIME_VARYING
    assert (kind in TIME_VARYING) == (kind == 'poly_retune')


@pytest.mark.parametrize('kind', list(MODULES))
def test_parameter_endpoints_active_and_empty(kind):
    sr = 12000
    x = H.sine(440, sr=sr, seconds=.08, channels=2)
    for d in P.describe(kind)['params']:
        if d['type'] in ('float', 'int', 'float_array'):
            values = [d['min'], d['max']]
        elif d['type'] == 'enum':
            values = d['choices']
        else:
            values = [False, True]
        for value in values:
            p = dict(map=mapping(9, 1)) if kind == 'poly_retune' else dict(method='wpe')
            p[d['id']] = [value]*12 if d['id'] == 'map' else value
            if d['id'] == 'start_s' and value:
                p['end_s'] = 36000
                # start=36000 cannot have end>start in the declared domain.
                with pytest.raises(ParamError):
                    P.validate_params(kind, p)
                p['start_s'] = 35999
            if d['id'] == 'end_s' and value == 0:
                p['start_s'] = 0
            y = direct(kind, x, p, sr=sr)[0]
            assert y.shape == x.shape and y.dtype == np.float64 and np.isfinite(y).all()
    if kind == 'dereverb':
        direct(kind, x, dict(rt60_s=.1), sr=sr)
    assert direct(kind, np.zeros((0, 1)), sr=sr)[0].shape == (0, 1)
    assert np.isfinite(direct(kind, np.ones((1, 2)), sr=sr)[0]).all()


@pytest.mark.parametrize('kind', list(MODULES))
def test_processor_acceptance_registration(kind):
    accepted = kind == 'poly_retune'
    assert MODULES[kind].SPECS[0]['implemented'] is accepted
    assert P.describe(kind)['implemented'] is accepted
    if accepted:
        x = np.zeros((20, 1))
        assert render(kind, x).tobytes() == x.tobytes()
    else:
        with pytest.raises(ChainError, match='not implemented|not_implemented'):
            render(kind, np.zeros((20, 1)))


def test_bb_rejects_invalid_inputs():
    for p in (dict(map=[]), dict(map=[0]*13), dict(map=[7]*12)):
        with pytest.raises(ParamError):
            P.validate_params('poly_retune', p)
    for p in (dict(rt60_s=.01), dict(start_s=2, end_s=1)):
        with pytest.raises(ParamError):
            P.validate_params('dereverb', p)
    for z, tap, delay, iterations in ((np.zeros((2, 2)), 4, 1, 1), (np.zeros((2, 2, 1)), 3, 1, 1),
                                     (np.zeros((2, 2, 1)), 4, 0, 1), (np.zeros((2, 2, 1)), 4, 1, 0)):
        with pytest.raises(ParamError):
            D.wpe(z, tap, delay, iterations)
    with pytest.raises(ParamError):
        B.harmonic_groups([200, 100], [1, 1], 1)


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_wpe_active_rate_and_early_interval(sr):
    x = H.sine(1000, sr=sr, seconds=.3, channels=2)
    y = direct('dereverb', x, dict(method='wpe', amount=1), sr=sr)[0]
    body = slice(round(.12*sr), round(.26*sr))
    frequency = H.fundamental_frequency(y[body], sr, low_hz=995, high_hz=1005)
    gain = H.db(H.rms(y[body])/H.rms(x[body]))
    emit('wpe_stationary', dict(sr=sr, frequency_hz=frequency, gain_db=gain))
    assert abs(frequency-1000) < 1 and abs(gain+9) < .5
    enveloped = np.zeros((round(.3*sr), 1))
    onset = round(.1*sr)
    enveloped[onset:] = .1
    weight = D.early_envelope(enveloped, sr, 50)
    assert not np.any(weight[onset:onset+round(.05*sr)])
    assert weight[onset+round(.065*sr)] == 1
    a = stft.analyze(x, sr, window=stft.window_samples(1024, sr))
    late = D.late_power(a, 1., 50)
    first = np.flatnonzero(np.any(late != 0, axis=(1, 2)))[0]
    actual = first*a.hop_samples/sr
    assert .05 <= actual < .05+a.hop_samples/sr+1e-12


def test_poly_stereo_and_antiphase_preservation():
    x = H.sine(440, sr=12000, seconds=.8)
    p = dict(map=mapping(9, 1))
    for polarity in (1, -1):
        stereo = np.column_stack([x[:, 0], polarity*x[:, 0]])
        y = direct('poly_retune', stereo, p)[0]
        assert np.max(abs(y[:, 0]-polarity*y[:, 1])) < 1e-12
        assert y.shape == stereo.shape


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_active_poly_fullscale(enabled, sr):
    rng = np.random.Generator(np.random.PCG64(33))
    x = np.where(rng.normal(size=(round(.06*sr), 2)) >= 0, 1., -1.)
    y = render('poly_retune', x, dict(map=mapping(11, 1)), sr=sr)
    assert y.shape == x.shape and y.dtype == np.float64 and np.isfinite(y).all()


def test_serial_loaded_solver_against_independent_residual():
    rng = np.random.Generator(np.random.PCG64(11))
    z = rng.normal(size=(30, 14))+1j*rng.normal(size=(30, 14))
    rhs = rng.normal(size=(14, 2))+1j*rng.normal(size=(14, 2))
    normal = np.einsum('ti,tj->ij', z.conj(), z, optimize=False)+np.eye(14)*1e-6
    answer = D._loaded_solve(normal, rhs)
    residual = np.einsum('ij,jc->ic', normal, answer, optimize=False)-rhs
    assert np.max(abs(residual)) < 1e-12
