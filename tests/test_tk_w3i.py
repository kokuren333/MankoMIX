"""W3i auditory model and spectral processor acoustic/contract acceptance."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from scipy import fft, signal
from mankomix.dsp import processors as P, engine as E
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb import auditory as A, stft as S, spectral_control as C
from mankomix.dspx.procs import resonance_suppressor as R, spectral_dynamics as D, spectral_balancer as B
from tests import toolimpl_harness as H

MODULES = dict(resonance_suppressor=R, spectral_dynamics=D, spectral_balancer=B)
NEUTRAL = dict(resonance_suppressor=dict(depth_db=0), spectral_dynamics=dict(ratio=1),
               spectral_balancer=dict(recover=0, tame=0, tilt_db_oct=0))


@pytest.fixture
def enabled(monkeypatch):
    for kind in MODULES:
        monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)


def direct(kind, x, p=None, sr=16000, **kw):
    return MODULES[kind].IMPLS[kind](x, sr, P.validate_params(kind, p or {}), **kw)


def emit(name, value):
    print(name, json.dumps(value, sort_keys=True))


def change(x, y):
    return H.rms_dbfs(y)-H.rms_dbfs(x)


def band_changes(x, y, sr, centers, width=1/3, trim=.5):
    skip = round(trim*sr)
    x, y = x[skip:-skip], y[skip:-skip]
    f = fft.rfftfreq(len(x), 1/sr)
    px, py = abs(fft.rfft(x, axis=0, workers=1))**2, abs(fft.rfft(y, axis=0, workers=1))**2
    out = []
    for fc in centers:
        use = (f >= fc*2**(-width/2)) & (f < fc*2**(width/2))
        out.append(float(10*np.log10(np.sum(py[use])/np.sum(px[use]))))
    return np.array(out)


def sculpt(x, sr, center, width, db, *, on_off=False):
    f = fft.rfftfreq(len(x), 1/sr)
    use = (f >= center*2**(-width/2)) & (f < center*2**(width/2))
    delta = fft.irfft(fft.rfft(x, axis=0, workers=1)*(10**(use[:, None]*db/20)-1),
                      n=len(x), axis=0, workers=1)
    if on_off:
        delta *= ((np.arange(len(x))//round(.5*sr)) % 2)[:, None]
    return x+delta


def test_auditory_floor_duplicate_and_independent_spreading():
    from mankomix.core.analysis import erb, stems
    from mankomix.core.config import load_knowledge
    for sr in (44100, 48000, 96000):
        old = erb.erb_band_edges(sr, 2048)
        new = A.erb_band_edges(sr, 2048)
        for a, b in zip(old, new):
            np.testing.assert_array_equal(a, b)
        np.testing.assert_array_equal(A.band_matrix(sr, 2048, new[0]), erb.band_matrix(sr, 2048, old[0]))
    fc = np.array([250., 1000., 4000.])
    p = np.array([[1e-4, 1e-3, 1e-5], [1e-2, 1e-7, 0.]])
    ctx = SimpleNamespace(model=load_knowledge('masking_model'), fc=fc, z=erb.hz_to_bark(fc),
                          spl_off=96., low_src=np.array([True, False, False]))
    original, _ = stems._Ctx._spread(ctx, p)
    np.testing.assert_allclose(A.excitation(p, fc, spl_offset_db=96), original, atol=1e-18, rtol=1e-14)
    external = A.excitation(p, fc, spl_offset_db=96, exclude_self=True)
    np.testing.assert_allclose(external+p, original, atol=1e-18)
    exports = A.excitation(p, fc, spl_offset_db=96, exclude_self=True, exported=True)
    np.testing.assert_allclose(exports.sum(axis=-1), external.sum(axis=-1), atol=1e-18)
    # Independent one-masker attenuation, with equal SPL convention.
    dz = float(erb.hz_to_bark(4000)-erb.hz_to_bark(1000))
    expected = 1e-3*10**(-(24+.23-.2*66)*dz/10)
    assert A.excitation([[0, 1e-3, 0]], fc, spl_offset_db=96)[0, 2] == pytest.approx(expected)
    threshold = A.masking_threshold(external)
    np.testing.assert_allclose(threshold, external*10**(-6/10))
    np.testing.assert_allclose(A.signal_to_mask_db(p, external), 10*np.log10((p+1e-20)/(threshold+1e-20)))
    assert np.all(A.quiet_threshold(fc, spl_offset_db=96) > 0)
    with pytest.raises(ParamError):
        A.excitation(-p, fc, spl_offset_db=96)


def test_iso_copy_ast_calibration_and_reference_levels():
    from mankomix.core.analysis import iso532_1 as old
    from mankomix.dspx.bb import _auditory_iso532 as clone
    from tests.test_iso532_1 import TEST_SIGNAL_1
    # The entire independent implementation, including all tables, is equal.
    assert ast.dump(ast.parse(Path(old.__file__).read_text(encoding='utf8'))) == ast.dump(ast.parse(Path(clone.__file__).read_text(encoding='utf8')))
    result = A.iso_levels(TEST_SIGNAL_1)
    assert result == old.loudness_from_third_octave_levels(TEST_SIGNAL_1)
    assert abs(result['N_sone']-83.296) <= .1
    with pytest.raises(TypeError):
        A.iso_loudness(np.zeros(48000), 48000)
    x = H.sine(1000, dbfs=-40, sr=48000, seconds=.6)
    for method in ('stationary', 'time_varying'):
        result = A.iso_loudness(x, 48000, calibration_db_spl=100, method=method)
        assert result == old.loudness_zwicker(x, 48000, calibration_db_spl=100, method=method)
        json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_parseval_and_erb_aggregation(sr):
    x = H.white_noise(-20, sr=sr, seconds=.15, channels=2, seed=2)
    a = S.analyze(x, sr, window=S.window_samples(2048, sr))
    p = A.bin_powers(a)
    i = len(a.samples)//2
    start = a.samples[i]-len(a.window)//2
    expected = np.sum((x[start:start+len(a.window)]*a.window[:, None])**2, axis=0)/np.sum(a.window**2)
    np.testing.assert_allclose(p[i].sum(axis=0), expected, rtol=1e-13)
    bands, edges, fc = A.band_powers(a)
    assert bands.shape == (len(a.samples), len(fc), 2)
    np.testing.assert_allclose(bands, np.einsum('tfc,bf->tbc', p, A.band_matrix(sr, len(a.window), edges)))


def test_envelope_research_three_candidates():
    sr = 48000
    x = H.pink_noise(-25, sr=sr, seconds=.2, seed=1)
    x = sculpt(x, sr, 3000, .05, 12)
    a = S.analyze(x, sr, window=2048)
    i = np.argmin(abs(a.frequencies_hz-3000))
    db = 10*np.log10(np.maximum(abs(a.spectra)**2, 1e-30))
    result = {}
    for method in ('log_mean', 'cepstral', 'true_envelope'):
        env = C.spectral_envelope(abs(a.spectra)**2, a.frequencies_hz, .5, method=method)
        assert env.shape == db.shape and np.isfinite(env).all()
        result[method] = float(np.median(db[3:-3, i]-env[3:-3, i]))
    emit('ENVELOPE_CANDIDATES_EXCESS_DB', result)
    assert result['log_mean'] > result['true_envelope']


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('window', [1024, 2048, 4096])
def test_frame_clock_tau_across_rates(sr, window):
    n = S.window_samples(window, sr)
    hop = n//4
    clock = sr/hop
    step = np.r_[np.zeros(10), np.full(100, -6.), np.zeros(150)][:, None, None]
    out = C.frame_smooth(step, sr, hop, 20, 80)[:, 0, 0]
    attack = (np.flatnonzero(out[10:110] <= -6*(1-np.exp(-1)))[0]+1)/clock
    release = (np.flatnonzero(abs(out[110:]) <= abs(out[109])*np.exp(-1))[0]+1)/clock
    assert abs(attack-.02) <= 1/clock and abs(release-.08) <= 1/clock
    emit('RATE_TAU', dict(sr=sr, window=window, actual_samples=n,
                         attack_s=attack, release_s=release))


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('window', [pytest.param(1024, marks=pytest.mark.xfail(strict=True,
    reason='Short-window acoustic GR is 6.36 dB instead of 8 +/-0.5; type remains False')), 2048, 4096])
def test_dynamics_acoustics_across_rates(sr, window):
    n = S.window_samples(window, sr)
    freq = round(1000*n/sr)*sr/n
    x = H.sine(freq, dbfs=-28, sr=sr, seconds=.6, channels=2)
    y = direct('spectral_dynamics', x, dict(window=window, threshold_tilt_db_oct=0), sr)[0]
    gr = -change(x[round(.3*sr):-round(.1*sr)], y[round(.3*sr):-round(.1*sr)])
    emit('RATE_MEASUREMENT', dict(sr=sr, window=window, actual_samples=n, gr_db=gr))
    assert gr == pytest.approx(8, abs=.5)


@pytest.mark.parametrize('kind', ['resonance_suppressor', 'spectral_balancer'])
@pytest.mark.parametrize('freq', [250, 3000])
@pytest.mark.parametrize('window', [1024, 2048, 4096])
def test_s4_other_frequencies(kind, freq, window):
    sr = 48000
    x = H.sine(freq, dbfs=-28, sr=sr, seconds=2)
    y = direct(kind, x, dict(window=window), sr)[0]
    envelope = abs(signal.hilbert(y[:, 0]))[36000:60000]
    ripple = float(20*np.log10(envelope.max()/envelope.min()))
    emit('S4_OTHER', dict(kind=kind, frequency_hz=freq, window=window, ripple_db=ripple))
    assert ripple <= .05


@pytest.mark.parametrize('kind', list(MODULES))
@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('window', [1024, 2048, 4096])
def test_s1_bypass_and_unity_wola(kind, sr, window):
    x = H.white_noise(-12, sr=sr, seconds=.035, channels=2, seed=3)
    y = direct(kind, x, {**NEUTRAL[kind], 'window':window}, sr)[0]
    np.testing.assert_array_equal(y, x)
    a = S.analyze(x, sr, window=S.window_samples(window, sr))
    assert H.null(x, S.synthesize(a))['peak_dbfs'] <= -120


@pytest.mark.parametrize('kind', list(MODULES))
@pytest.mark.parametrize('compensate', [False, True])
def test_s2_delta_and_latency(kind, compensate):
    sr = 16000
    x = H.white_noise(-18, sr=sr, seconds=.3, channels=2, seed=4)
    y, _, stats = direct(kind, x, sr=sr, compensate=compensate)
    delta = direct(kind, x, dict(delta=True), sr, compensate=compensate)[0]
    expected = x if compensate else S.delay_output(x, stats['latency_samples'])
    assert H.null(expected, y+delta)['peak_dbfs'] <= -120
    assert stats['latency_compensated'] == compensate


@pytest.mark.parametrize('kind', list(MODULES))
@pytest.mark.parametrize('freq', [250, 10000])
def test_s3_outside_band(kind, freq):
    sr = 48000
    x = H.sine(freq, dbfs=-20, sr=sr, seconds=.7)
    p = dict(lo_hz=1000, hi_hz=4000)
    y = direct(kind, x, p, sr)[0]
    assert abs(change(x[sr//5:-sr//5], y[sr//5:-sr//5])) <= .1


@pytest.mark.parametrize('kind,window', [
    pytest.param(kind, window, marks=pytest.mark.xfail(strict=True,
        reason='S4 exceeds 0.05 dB at an allowed window; type remains False'))
    if kind == 'spectral_dynamics' and window in (1024, 4096) else (kind, window)
    for kind in MODULES for window in (1024, 2048, 4096)])
def test_s4_stationary_sine_frame_ripple(kind, window):
    sr = 48000
    x = H.sine(1000, dbfs=-28, sr=sr, seconds=2)
    y = direct(kind, x, dict(window=window), sr)[0]
    envelope = abs(signal.hilbert(y[:, 0]))[round(.75*sr):round(1.25*sr)]
    ripple = float(20*np.log10(envelope.max()/envelope.min()))
    emit('S4', dict(kind=kind, window=window, ripple_db=ripple))
    assert ripple <= .05


def test_resonance_injected_peak_and_remote_third_octaves():
    sr = 16000
    x = sculpt(H.pink_noise(-22, sr=sr, seconds=3, seed=12), sr, 3000, .05, 12)
    y = direct('resonance_suppressor', x, dict(excess_db=6), sr=sr)[0]
    attenuation = -float(band_changes(x, y, sr, [3000], .05)[0])
    remote = band_changes(x, y, sr, [250, 500, 750, 1000])
    emit('RESONANCE', dict(attenuation_db=attenuation, remote_db=remote.tolist()))
    assert attenuation == pytest.approx(min(6, 12-6), abs=2)
    assert np.max(abs(remote)) <= .5


def test_resonance_pink_harmlessness_all_third_octaves():
    sr = 48000
    x = H.pink_noise(-22, sr=sr, seconds=3, seed=12)
    y = direct('resonance_suppressor', x, sr=sr)[0]
    centers = 1000*2**(np.arange(-15, 13)/3)
    changes = band_changes(x, y, sr, centers)
    emit('RESONANCE_PINK', dict(centers_hz=centers.tolist(), change_db=changes.tolist()))
    assert np.max(abs(changes)) <= .5


@pytest.mark.parametrize('sr', [44100, 96000])
def test_resonance_calibrated_default_at_other_rates(sr):
    x = sculpt(H.pink_noise(-22, sr=sr, seconds=2.5, channels=2, seed=12), sr, 3000, .05, 12)
    y = direct('resonance_suppressor', x, sr=sr)[0]
    reduction = -band_changes(x, y, sr, [3000], .05)[0]
    # The revised excess default changes the formula's expected GR, not its tolerance.
    assert reduction == pytest.approx(min(6, 12-8), abs=2)
    emit('RESONANCE_DEFAULT_RATE', dict(sr=sr, reduction_db=float(reduction)))


def test_resonance_intermittent_off_harmlessness():
    sr = 16000
    base = H.pink_noise(-22, sr=sr, seconds=4, seed=12)
    x = sculpt(base, sr, 3000, .05, 12, on_off=True)
    y = direct('resonance_suppressor', x, sr=sr)[0]
    changes = []
    for sec in (1., 2., 3.):
        left, right = round((sec+.25)*sr), round((sec+.45)*sr)
        changes.extend(band_changes(x[left:right], y[left:right], sr, [250, 500, 1000, 2000, 4000], trim=.02).tolist())
    emit('RESONANCE_OFF', changes)
    assert np.max(np.abs(changes)) <= .3


def test_resonance_sweep_limit_and_time_constants():
    sr = 16000
    x = H.sweep(200, 6000, dbfs=-12, sr=sr, seconds=1)
    p = P.validate_params('resonance_suppressor', {})
    a = S.analyze(x, sr, window=R.latency_samples(sr, p))
    gain, target = R.control(a, p)
    assert gain.min() >= -p['depth_db']-1e-12 and gain.max() <= 0
    aa = np.exp(-a.hop_samples/(sr*p['attack_ms']*.001))
    ar = np.exp(-a.hop_samples/(sr*p['release_ms']*.001))
    prev = np.concatenate([np.zeros_like(gain[:1]), gain[:-1]])
    bound = np.where(abs(-target) > abs(prev), (1-aa), (1-ar))*abs(-target-prev)
    assert np.max(abs(gain-prev)-bound) < 1e-12
    # Step and decay of the reused frame smoother: independent 63% crossing.
    clock = sr/a.hop_samples
    demand = np.r_[np.zeros(20), np.full(150, -6.), np.zeros(200)][:, None, None]
    out = C.frame_smooth(demand, sr, a.hop_samples, 20, 80)[:, 0, 0]
    attack = (np.flatnonzero(out[20:170] <= -6*(1-np.exp(-1)))[0]+1)/clock
    release = (np.flatnonzero(abs(out[170:]) <= abs(out[169])*np.exp(-1))[0]+1)/clock
    emit('FRAME_TAU', dict(attack_s=attack, release_s=release, frame_s=1/clock))
    assert abs(attack-.02) <= 1/clock and abs(release-.08) <= 1/clock


@pytest.mark.parametrize('window', [1024, 2048, 4096])
def test_dynamics_full_scale_bin_normalization(window):
    sr = 48000
    frequency = round(1000*window/sr)*sr/window
    a = S.analyze(H.sine(frequency, dbfs=0, sr=sr, seconds=.5), sr, window=window)
    level = float(np.median(C.bin_levels(a)[10:-10, round(frequency*window/sr), 0]))
    emit('BIN_DBFS', dict(window=window, level_dbfs=level))
    assert abs(level) <= .2


@pytest.mark.parametrize('mode', ['compress', 'expand'])
def test_dynamics_static_curve_and_independent_subthreshold_tone(mode):
    sr = 48000
    x = H.sine(1500, dbfs=-28 if mode == 'compress' else -46, sr=sr, seconds=1.2)
    if mode == 'compress':
        x += H.sine(3000, dbfs=-52, sr=sr, seconds=1.2)
    p = dict(threshold_tilt_db_oct=0, mode=mode, knee_db=0)
    y = direct('spectral_dynamics', x, p, sr)[0]
    gr = -band_changes(x, y, sr, [1500], .1, trim=.4)[0]
    expected = 12*(1-1/3) if mode == 'compress' else 6*(3-1)
    emit('DYNAMICS_STATIC', dict(mode=mode, gr_db=float(gr), expected_db=expected))
    assert gr == pytest.approx(expected, abs=.5)
    if mode == 'compress':
        assert abs(band_changes(x, y, sr, [3000], .1, trim=.4)[0]) <= .2


def test_balancer_pink_all_erb_bands():
    sr = 48000
    x = H.pink_noise(-22, sr=sr, seconds=3, seed=12)
    y = direct('spectral_balancer', x, sr=sr)[0]
    a = S.analyze(x[sr:-sr], sr, window=2048)
    b = S.analyze(y[sr:-sr], sr, window=2048)
    px, _, fc = A.band_powers(a)
    py, _, _ = A.band_powers(b)
    changes = 10*np.log10(np.sum(py, axis=(0, 2))/np.sum(px, axis=(0, 2)))
    emit('BALANCER_PINK', dict(centers_hz=fc.tolist(), change_db=changes.tolist()))
    assert np.max(abs(changes)) <= .5


@pytest.mark.parametrize('kind', ['resonance_suppressor', 'spectral_balancer'])
@pytest.mark.parametrize('seed', [3, 71])
def test_pink_preservation_independent_seeds(kind, seed):
    sr = 48000
    x = H.pink_noise(-22, sr=sr, seconds=2, seed=seed)
    y = direct(kind, x, sr=sr)[0]
    if kind == 'resonance_suppressor':
        changes = band_changes(x, y, sr, 1000*2**(np.arange(-15, 13)/3))
    else:
        px, _, _ = A.band_powers(S.analyze(x[sr//2:-sr//2], sr, window=2048))
        py, _, _ = A.band_powers(S.analyze(y[sr//2:-sr//2], sr, window=2048))
        changes = 10*np.log10(np.sum(py, axis=(0, 2))/np.sum(px, axis=(0, 2)))
    emit('PINK_SEED', dict(kind=kind, seed=seed, max_abs_change_db=float(np.max(abs(changes)))))
    assert np.max(abs(changes)) <= .5


@pytest.mark.parametrize('parameter,db', [('tame', 15), ('recover', -10)])
def test_balancer_injected_band_monotonicity_bounds_and_loudness(parameter, db):
    from mankomix.core.measure.loudness import integrated
    sr = 16000
    x = sculpt(H.pink_noise(-22, sr=sr, seconds=3, seed=12), sr, 2000, 1/3, db)
    changes, loudness = [], []
    for strength in (0., .3, .6, 1.):
        p = {'recover':0, 'tame':0, parameter:strength}
        y, _, stats = direct('spectral_balancer', x, p, sr)
        changes.append(float(band_changes(x, y, sr, [2000])[0]))
        loudness.append(float(integrated(y, sr)-integrated(x, sr)))
        assert max(abs(stats['gain_min_db']), abs(stats['gain_max_db'])) <= 6+1e-12
    emit('BALANCER_BAND', dict(parameter=parameter, changes_db=changes, loudness_lu=loudness))
    if parameter == 'tame':
        assert changes[-1] <= -2 and np.all(np.diff(changes) <= 0)
    else:
        assert changes[-1] > 0 and np.all(np.diff(changes) >= 0)
    assert max(abs(np.array(changes))) <= 6
    assert max(abs(np.array(loudness))) <= .5


def test_balancer_gain_time_bound():
    sr = 16000
    x = H.white_noise(-20, sr=sr, seconds=.6, channels=2, seed=2)
    p = P.validate_params('spectral_balancer', {})
    a = S.analyze(x, sr, window=B.latency_samples(sr, p))
    db, bands, fc = B.control(a, p)
    alpha = np.exp(-a.hop_samples/(sr*p['time_ms']*.001))
    delta = abs(np.diff(np.concatenate([np.zeros_like(db[:1]), db]), axis=0))
    assert np.max(delta) <= 2*p['max_change_db']*(1-alpha)+1e-12
    assert np.max(abs(db)) <= p['max_change_db']+1e-12
    emit('BALANCER_SLEW', dict(max_delta_db=float(delta.max()), bound_db=float(12*(1-alpha))))


@pytest.mark.parametrize('kind', list(MODULES))
def test_common_ct(enabled, kind):
    neutral = NEUTRAL[kind]
    # Active range with a declared band excluding 1 kHz for independent CT-7.
    params = dict(lo_hz=3000, hi_hz=12000)
    module = MODULES[kind]
    def probe(x, y, sr, p):
        freq = H.fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
        gain = change(x[round(.03*sr):-round(.03*sr)], y[round(.03*sr):-round(.03*sr)])
        return dict(passed=abs(freq-1000) < 1 and abs(gain) < .1, frequency_hz=freq, gain_db=gain)
    result = H.assert_common_tests(kind, neutral=neutral, params=params, seconds=.12,
        sr_probe=probe, declared_latency=module.latency_samples,
        latency_probe=lambda x, sr, p, **kw: module.IMPLS[kind](x, sr, p, compensate=False)[0],
        latency_params=neutral, invalid_params=[dict(lo_hz=1000, hi_hz=500)])
    assert all(result[f'CT-{i}']['passed'] for i in range(1, 9))


@pytest.mark.parametrize('kind', list(MODULES))
def test_spec_ranges_defaults_and_parameter_endpoints(kind):
    common = dict(lo_hz=(20, 20000, 20), hi_hz=(20, 24000, 20000), mix=(0, 1, 1))
    expected = {
        'resonance_suppressor':{**common, 'lo_hz':(20, 20000, 200), 'hi_hz':(20, 24000, 16000),
            # PM_PLAN 9.3 calibrated default: original 6 -> 8; range unchanged.
            'depth_db':(0, 24, 6), 'excess_db':(0, 24, 8), 'envelope_oct':(.1, 2, .5),
            'notch_oct':(.02, .5, .1), 'attack_ms':(0, 200, 5), 'release_ms':(5, 2000, 80), 'tilt_db_oct':(-6, 6, 0)},
        'spectral_dynamics':{**common, 'threshold_db':(-100, 0, -40), 'threshold_tilt_db_oct':(-6, 6, -3),
            'ratio':(1, 20, 3), 'knee_db':(0, 24, 6), 'range_db':(0, 36, 12), 'smooth_oct':(0, 1, .1),
            'attack_ms':(0, 200, 10), 'release_ms':(5, 2000, 100)},
        'spectral_balancer':{**common, 'recover':(0, 1, .3), 'tame':(0, 1, .3), 'tilt_db_oct':(-3, 3, 0),
            'max_change_db':(0, 12, 6), 'time_ms':(20, 2000, 150)}}[kind]
    spec = P.describe(kind)
    nums = {d['id']:(d['min'], d['max'], d['default']) for d in spec['params'] if d['type'] == 'float'}
    assert nums == expected
    assert spec['stages'] == ['track', 'bus', 'master']
    assert spec['master_slot'] == (3 if kind == 'spectral_balancer' else 2)
    assert spec['backends'] == ['reference'] and spec['offline_only'] is False
    assert spec['realtime'] == dict(block_ok=False, latency_samples='window_scaled', allocates=True)
    defaults = P.validate_params(kind, {})
    assert defaults['window'] == 2048 and defaults['delta'] is False and defaults['stereo_link'] is True
    if kind == 'spectral_dynamics':
        assert defaults['mode'] == 'compress'
    if kind == 'spectral_balancer':
        assert defaults['loudness_hold'] is True
    x = H.sine(1000, sr=48000, seconds=.03, channels=2)
    for d in spec['params']:
        values = [d['min'], d['max']] if d['type'] == 'float' else ([False, True] if d['type'] == 'bool' else d['choices'])
        for v in values:
            p = {d['id']:v}
            if d['id'] == 'lo_hz':
                p['hi_hz'] = max(v+1, defaults['hi_hz'])
            if d['id'] == 'hi_hz' and v == 20:
                with pytest.raises(ParamError):
                    P.validate_params(kind, p)
                continue
            y = direct(kind, x, p, 48000)[0]
            assert y.shape == x.shape and np.isfinite(y).all()
    with pytest.raises(ParamError):
        P.validate_params(kind, dict(window=512))


@pytest.mark.parametrize('kind', list(MODULES))
def test_stereo_link_empty_one_sample_and_registration(enabled, kind):
    from mankomix.dspx.registry import time_varying_types
    assert kind in time_varying_types()
    for length in (0, 1):
        x = np.ones((length, 2))*.1
        y = direct(kind, x)[0]
        assert y.shape == x.shape and np.isfinite(y).all()
    sr = 16000
    mono = H.sine(1000, sr=sr, seconds=.3)
    x = np.c_[mono, mono*.2]
    linked = direct(kind, x)[0]
    assert H.null(linked[:, :1]*.2, linked[:, 1:])['peak_dbfs'] <= -120
    independent = np.column_stack([direct(kind, x[:, c:c+1], dict(stereo_link=False))[0][:, 0] for c in (0, 1)])
    assert H.null(independent, direct(kind, x, dict(stereo_link=False))[0])['peak_dbfs'] <= -120
    # Master slot 2/3 ordering is enforced by the existing engine.
    chain = [dict(id='process', type=kind, params=NEUTRAL[kind]), dict(id='limit', type='limiter', params={})]
    E.render_chain(x, sr, chain, stage='master')
    with pytest.raises(ChainError):
        E.render_chain(x, sr, list(reversed(chain)), stage='master')


def test_implementation_registration_honesty():
    for kind, module in MODULES.items():
        assert P.describe(kind)['implemented'] == module.SPECS[0]['implemented']
        if not module.SPECS[0]['implemented']:
            with pytest.raises(ChainError, match='not implemented'):
                E.render_chain(np.zeros((64, 1)), 48000, [dict(id='p', type=kind, params={})], stage='track')
