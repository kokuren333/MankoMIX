"""C8b window-aware spectral effects and dynamics closure measurements."""
import json
import numpy as np
import pytest
from scipy import signal
from mankomix.dsp import engine as E, processors as P
from mankomix.dspx.bb import stft as S, spectral_components as C
from mankomix.dspx.procs import spectral_fx as FX, spectral_dynamics as D
from tests import toolimpl_harness as H


def emit(name, **values):
    print(name, json.dumps(values, sort_keys=True))


def direct(kind, x, sr, params):
    module = FX if kind == 'spectral_fx' else D
    return module.IMPLS[kind](x, sr, P.validate_params(kind, params))[0]


def ripple(y, sr, interval=(.6, 1.4)):
    envelope = abs(signal.hilbert(y[:, 0]))[round(interval[0]*sr):round(interval[1]*sr)]
    return float(20*np.log10(envelope.max()/envelope.min()))


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('window', [1024, 2048, 4096])
def test_effect_s4_all_windows_rates_and_nonzero_amounts(sr, window):
    # Integer-Hz stationary signals avoid artificial Hilbert crop edges.
    # The off-bin position differs across sr/window; no neutral rendering.
    x = H.sine(997, -28, sr=sr, seconds=1)
    for op, extra in [('contrast', {'exponent': .25}), ('contrast', {'exponent': 4}),
                      ('smear_freq', {'width_oct': .05}), ('smear_freq', {'width_oct': 2}),
                      ('phase', {'phase_mode': 'random'})]:
        for amount in (.4, 1):
            params = dict(window=window, op=op, amount=amount, **extra)
            y = direct('spectral_fx', x, sr, params)
            value = ripple(y, sr, (.3, .7))
            emit('C8B_FX_S4', sr=sr, window=window, params=params, ripple_db=value)
            assert value <= .05
            assert H.rms_dbfs(y[round(.3*sr):round(.7*sr)]) > -60


@pytest.mark.parametrize('freq', [250, 3000])
@pytest.mark.parametrize('window', [1024, 2048, 4096])
def test_additional_s4_frequencies(freq, window):
    sr = 48000
    x = H.sine(freq, -28, sr=sr, seconds=2)
    for kind, params in [('spectral_fx', dict(op='contrast', amount=1, exponent=4)),
                         ('spectral_fx', dict(op='smear_freq', amount=1, width_oct=2)),
                         ('spectral_fx', dict(op='phase', amount=1, phase_mode='random')),
                         ('spectral_dynamics', {})]:
        y = direct(kind, x, sr, dict(window=window, **params))
        value = ripple(y, sr)
        emit('C8B_OTHER_S4', frequency_hz=freq, window=window, kind=kind, params=params, ripple_db=value)
        assert value <= .05


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('window', [1024, 2048, 4096])
def test_dynamics_off_bin_static_curves_and_smoothing_endpoints(sr, window):
    for smooth in (0, .1, 1):
        for mode, level, expected in [('compress', -28, 8), ('expand', -46, 12)]:
            x = H.sine(997, level, sr=sr, seconds=1.2)
            params = dict(window=window, mode=mode, smooth_oct=smooth,
                          threshold_tilt_db_oct=0, knee_db=0)
            y = direct('spectral_dynamics', x, sr, params)
            sl = slice(round(.4*sr), round(.8*sr))
            gr = H.rms_dbfs(x[sl])-H.rms_dbfs(y[sl])
            value = ripple(y, sr, (.4, .8))
            emit('C8B_DYNAMICS', sr=sr, window=window, mode=mode, smooth_oct=smooth,
                 gr_db=gr, expected_gr_db=expected, ripple_db=value)
            assert abs(gr-expected) <= .5
            assert value <= .05


def test_window_response_against_direct_sum_and_off_bin_calibration():
    n, sr = 1024, 48000
    offsets = np.array([-.5, -.37, 0, .13, .5])
    expected = abs(np.sum(S.sqrt_hann(n)[None, :]
                   *np.exp(-2j*np.pi*offsets[:, None]*np.arange(n)/n), axis=1))
    np.testing.assert_allclose(C.window_response(offsets, n), expected, atol=1e-11)
    for hz in (937.5, 997, 1007, 1031.25):
        a = S.analyze(H.sine(hz, -12, sr=sr, seconds=.5), sr, window=n)
        ids, amplitude = C.lobes(a)
        k = round(hz*n/sr)
        measured = float(np.median(20*np.log10(amplitude[5:-5, k, 0])))
        emit('C8B_CALIBRATION', frequency_hz=hz, measured_dbfs=measured)
        assert abs(measured+12) <= .02
        # All sidelobes of an isolated component receive its same detector.
        assert np.ptp(amplitude[10, :, 0]) < 1e-12
        assert np.unique(ids[10, :, 0]).size == 1


def test_contrast_and_smear_remain_active_on_resolved_spectral_envelope():
    sr = 48000
    x = H.sine(1500, -12, sr=sr, seconds=2)+H.sine(2250, -32, sr=sr, seconds=2)
    sl = slice(sr//2, -sr//2)
    def difference(y):
        return H.band_level(y[sl], sr, 1400, 1600)['dbfs']-H.band_level(y[sl], sr, 2150, 2350)['dbfs']
    for exponent in (.25, 1, 2, 4):
        y = direct('spectral_fx', x, sr, dict(op='contrast', amount=1, exponent=exponent))
        value = difference(y)
        emit('C8B_CONTRAST', exponent=exponent, difference_db=value)
        assert abs(value-20*exponent) <= 1
    smeared = direct('spectral_fx', x, sr, dict(op='smear_freq', amount=1, width_oct=2))
    value = difference(smeared)
    emit('C8B_SMEAR', original_difference_db=difference(x), difference_db=value)
    assert 0 < value < 15
    assert H.null(x, smeared)['rms_dbfs'] > -60


def test_random_phase_lobe_coherence_magnitude_seed_and_nontrivial_output():
    sr = 16000
    x = H.white_noise(-20, sr=sr, seconds=.7, channels=2, seed=17)
    params = dict(op='phase', phase_mode='random', amount=1)
    p = P.validate_params('spectral_fx', params)
    a = S.analyze(x, sr, window=S.window_samples(p['window'], sr))
    z = FX.transform(a, p, seed=5)
    interior = (a.frequencies_hz > 100) & (a.frequencies_hz < 7000)
    np.testing.assert_allclose(abs(z[:, interior]), abs(a.spectra[:, interior]), atol=1e-12)
    ids, _ = C.lobes(a)
    for t in (3, 12, 30):
        for ch in (0, 1):
            for k in np.unique(ids[t, :, ch]):
                bins = (ids[t, :, ch] == k) & interior
                ratios = z[t, bins, ch]/a.spectra[t, bins, ch]
                if len(ratios):
                    np.testing.assert_allclose(ratios, ratios[0], atol=1e-12)
    def render(seed, item='effect'):
        return E.render_chain(x, sr, [dict(id=item, type='spectral_fx', params=params)],
                              stage='track', seed=seed).audio
    y = render(3)
    np.testing.assert_array_equal(y, render(3))
    assert H.null(x, y)['rms_dbfs'] > -60
    assert not np.array_equal(y, render(4))
    assert not np.array_equal(y, render(3, 'other'))


def test_dynamics_audio_time_response_range_and_independent_quiet_component():
    sr = 48000
    # Flat threshold and hard knee make the independent static curve exact.
    x = np.r_[H.sine(1500, -70, sr=sr, seconds=.3),
              H.sine(1500, -28, sr=sr, seconds=.6),
              H.sine(1500, -70, sr=sr, seconds=.6)]
    p = P.validate_params('spectral_dynamics', dict(window=1024, knee_db=0,
        threshold_tilt_db_oct=0, attack_ms=30, release_ms=80))
    a = S.analyze(x, sr, window=1024)
    gain, target = D.control(a, p)
    prev = np.concatenate([np.zeros_like(gain[:1]), gain[:-1]])
    tau = np.where(abs(target) > abs(prev), .03, .08)
    expected = target+(prev-target)*np.exp(-a.hop_samples/(sr*tau))
    np.testing.assert_allclose(gain, expected, atol=1e-12)
    assert gain.min() >= -p['range_db']-1e-12 and gain.max() <= 0
    y = D.spectral_dynamics(x, sr, p)[0]
    # Independent coherent 10 ms amplitude projections, away from onset.
    fitted = []
    for t in (.35, .4, .5, .7, 1.0, 1.1, 1.3):
        sl = slice(round(t*sr), round((t+.01)*sr))
        fitted.append(float(20*np.log10(H._tone_fit(y[sl], sr, [1500])[0][0, 0]
                       /H._tone_fit(x[sl], sr, [1500])[0][0, 0])))
    emit('C8B_AUDIO_TIME', time_s=[.35, .4, .5, .7, 1., 1.1, 1.3], gain_db=fitted)
    assert fitted[0] > fitted[1] > fitted[2] > fitted[3]
    assert fitted[4] < fitted[5] < fitted[6]
    assert abs(fitted[3]+8) < .1 and abs(fitted[-1]) < .2


def test_public_registration_and_defaults():
    for kind in ('spectral_fx', 'spectral_dynamics'):
        x = H.sine(997, -28, sr=48000, seconds=.2)
        chain = [dict(id='effect', type=kind, params={})]
        assert P.describe(kind)['implemented'] is True
        y = E.render_chain(x, 48000, chain, stage='track').audio
        assert y.shape == x.shape and np.isfinite(y).all()
        if kind == 'spectral_fx':
            np.testing.assert_array_equal(y, x)
            params = dict(op='phase', phase_mode='hold', amount=1)
            chain[0]['params'] = params
            active = E.render_chain(x, 48000, chain, stage='track').audio
            np.testing.assert_array_equal(active, direct(kind, x, 48000, params))


def test_literal_hold_phase_magnitude_and_hop_periodicity():
    # 統括の判断 D-25(a): test the fixed phase/magnitude and hop period;
    # the resulting envelope ripple is an intended effect, exempt from S4.
    sr, window = 48000, 2048
    # A hop-harmonic input has constant magnitudes. A frozen phase then
    # forces an H-periodic output; verify the literal operation independently.
    x = H.sine(750, sr=sr, seconds=3)
    a = S.analyze(x, sr, window=window)
    p = P.validate_params('spectral_fx', dict(op='phase', phase_mode='hold', amount=1))
    z = FX.transform(a, p)
    use = (a.frequencies_hz > 100) & (a.frequencies_hz < 5000)
    np.testing.assert_allclose(abs(z[:, use]), abs(a.spectra[:, use]), atol=1e-12)
    np.testing.assert_allclose(np.exp(1j*np.angle(z[:, use])),
        np.broadcast_to(np.exp(1j*np.angle(a.spectra[:1, use])), z[:, use].shape), atol=1e-12)
    y = S.synthesize(a, z)
    hop = a.hop_samples
    period_null = H.null(y[sr:2*sr-hop], y[sr+hop:2*sr])['rms_dbfs']
    envelope = abs(signal.hilbert(y[:, 0]))[sr:2*sr]
    value = float(20*np.log10(envelope.max()/envelope.min()))
    emit('C8B_HOLD_LITERAL', frequency_hz=750, ripple_db=value, hop_null_dbfs=period_null)
    assert period_null <= -120


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_active_endpoint_combinations_full_scale_stereo(sr):
    x = np.sign(H.white_noise(sr=sr, seconds=.08, channels=2, seed=43))
    for window in (1024, 2048, 4096):
        for op, extra in [('contrast', {'exponent': .25}), ('contrast', {'exponent': 4}),
                          ('smear_freq', {'width_oct': .05}), ('smear_freq', {'width_oct': 2}),
                          ('phase', {'phase_mode': 'hold'}), ('phase', {'phase_mode': 'random'})]:
            y = direct('spectral_fx', x, sr, dict(window=window, amount=1, op=op, **extra))
            assert y.shape == x.shape and np.isfinite(y).all()
        for mode in ('compress', 'expand'):
            for linked in (False, True):
                y = direct('spectral_dynamics', x, sr, dict(window=window, mode=mode,
                    stereo_link=linked, ratio=20, range_db=36, threshold_db=-100,
                    threshold_tilt_db_oct=6, smooth_oct=1, attack_ms=0, release_ms=5))
                assert y.shape == x.shape and np.isfinite(y).all()
