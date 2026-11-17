"""C7b phase continuity, off-grid freeze and rolling spectral stability."""
import json
import numpy as np
import pytest
from scipy import signal
from mankomix.dsp import processors as P
from mankomix.dspx.bb import stft as S
from mankomix.dspx.procs import spectral_fx as FX, spectral_freeze as FZ
from tests import toolimpl_harness as H


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('op,extra,target', [
    ('blur', {}, 1000), ('shift', {'shift_hz': -400}, 600),
    ('shift', {'shift_hz': 400}, 1400),
    ('scale', {'ratio': .25}, 250), ('scale', {'ratio': 4}, 4000)])
def test_translation_continuity_and_scale_endpoints(sr, op, extra, target):
    x = H.sine(1000, sr=sr, seconds=3)
    p = P.validate_params('spectral_fx', dict(op=op, amount=1, **extra))
    y = FX.spectral_fx(x, sr, p)[0]
    # Form the analytic signal before cropping, to exclude FFT cut artifacts.
    envelope = abs(signal.hilbert(y[:, 0]))[sr:-sr]
    ripple = float(20*np.log10(envelope.max()/envelope.min()))
    frequency = H.fundamental_frequency(y[sr:-sr], sr,
                                        low_hz=target*.8, high_hz=target*1.2)
    print('C7B_FX', json.dumps(dict(sr=sr, op=op, extra=extra,
                                  ripple_db=ripple, frequency_hz=frequency), sort_keys=True))
    assert ripple <= .05
    assert abs(frequency-target) <= (sr/S.window_samples(p['window'], sr))/2


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('frequency', [997.3, 1000.1])
def test_freeze_advance_off_grid(sr, frequency):
    x = H.sine(frequency, sr=sr, seconds=3)
    p = P.validate_params('spectral_freeze', dict(freeze_start_s=[.5], freeze_end_s=[2.9],
                         phase_mode='advance', input_during='mute'))
    y = FZ.spectral_freeze(x, sr, p)[0]
    measured = H.fundamental_frequency(y[sr:2*sr], sr,
                                       low_hz=frequency-30, high_hz=frequency+30)
    print('C7B_ADVANCE', json.dumps(dict(sr=sr, input_hz=frequency, output_hz=measured), sort_keys=True))
    assert abs(measured-frequency) <= 1


def test_random_30s_rolling_stability_and_gain():
    sr = 8000
    x = H.pink_noise(-20, sr=sr, seconds=31, seed=7)
    p = P.validate_params('spectral_freeze', dict(freeze_start_s=[.5], freeze_end_s=[30.9],
                         capture_ms=500, input_during='mute', freeze_db=6))
    y = FZ.spectral_freeze(x, sr, p, seed=7)[0]
    centers = [125, 250, 500, 1000, 2000]
    original = np.array([H.band_level(x[sr//2:sr], sr, f*2**(-1/6), f*2**(1/6))['dbfs']
                         for f in centers])+6
    for offset in [0, .125, .25, .5, .75]:
        levels = np.array([[H.band_level(y[round((t+offset)*sr):round((t+offset+1)*sr)], sr,
                           f*2**(-1/6), f*2**(1/6))['dbfs'] for f in centers] for t in range(1, 29)])
        variation = np.ptp(levels, axis=0)
        error = levels.mean(axis=0)-original
        print('C7B_RANDOM', json.dumps(dict(offset_s=offset, variation_db=variation.tolist(),
                                           capture_error_db=error.tolist()), sort_keys=True))
        assert max(variation) <= .5
        assert max(abs(error)) <= 1
    v = y[sr:3*sr, 0]
    correlation = signal.fftconvolve(v, v[::-1], mode='full')[len(v)-1:]/np.sum(v*v)
    hop = S.window_samples(p['window'], sr)//4
    lags = np.arange(round(.02*sr), sr)
    outside = np.minimum(lags % hop, hop-lags % hop) > 2
    assert max(abs(correlation[lags[outside]])) < .2


def test_random_phase_balancing_retains_held_magnitudes():
    sr = 8000
    x = H.white_noise(-20, sr=sr, seconds=4, seed=19)
    a = S.analyze(x, sr, window=S.window_samples(4096, sr))
    magnitude = np.sqrt(np.mean(abs(a.spectra[20:40])**2, axis=0))
    frames = np.arange(len(a.samples))
    rng = np.random.Generator(np.random.PCG64(3))
    z = magnitude[None]*np.exp(1j*rng.uniform(-np.pi, np.pi, a.spectra.shape))
    z[:, 0] = z[:, 0].real
    z[:, -1] = z[:, -1].real
    held = abs(z).copy()
    initial = z.copy()
    result = FZ._balance_random_phases(a, z, frames, x[:sr//2], 0, len(x))
    np.testing.assert_allclose(abs(result), held, atol=1e-12, rtol=1e-12)
    assert np.isfinite(S.synthesize(a, result)).all()
    repeated = FZ._balance_random_phases(a, initial, frames, x[:sr//2], 0, len(x))
    np.testing.assert_array_equal(result, repeated)


def test_phase_zero_semantics_and_periodicity():
    sr = 48000
    x = H.sine(750, sr=sr, seconds=3)
    a = S.analyze(x, sr, window=2048)
    p = P.validate_params('spectral_fx', dict(op='phase', phase_mode='zero', amount=1))
    z = FX.transform(a, p)
    interior = (a.frequencies_hz > 100) & (a.frequencies_hz < 5000)
    np.testing.assert_allclose(abs(z[:, interior]), abs(a.spectra[:, interior]), atol=1e-12)
    np.testing.assert_allclose(np.angle(z[:, interior]), 0, atol=1e-12)
    y = S.synthesize(a, z)
    hop = a.hop_samples
    assert H.null(y[sr:2*sr-hop], y[sr+hop:2*sr])['rms_dbfs'] <= -60
    envelope = abs(signal.hilbert(y[sr:-sr, 0]))
    print('C7B_PHASE_ZERO', json.dumps(dict(ripple_db=float(20*np.log10(envelope.max()/envelope.min()))),
                                      sort_keys=True))


def test_random_default_single_frame_capture_30s():
    sr = 8000
    x = H.pink_noise(-20, sr=sr, seconds=31, seed=23)
    p = P.validate_params('spectral_freeze', dict(freeze_start_s=[.5], freeze_end_s=[30.9],
                                                input_during='mute'))
    y = FZ.spectral_freeze(x, sr, p, seed=23)[0]
    a = S.analyze(x, sr, window=S.window_samples(p['window'], sr))
    capture = np.argmin(abs(a.samples-sr//2))
    power = abs(a.spectra[capture, :, 0])**2/(len(a.window)*np.sum(a.window*a.window))
    power[1:-1] *= 2
    for f in [125, 250, 500, 1000, 2000]:
        lo, hi = f*2**(-1/6), f*2**(1/6)
        target = 10*np.log10(np.sum(power[(a.frequencies_hz >= lo) & (a.frequencies_hz < hi)]))
        levels = [H.band_level(y[t*sr:(t+1)*sr], sr, lo, hi)['dbfs'] for t in range(1, 30)]
        print('C7B_SINGLE_CAPTURE', json.dumps(dict(center_hz=f, variation_db=float(np.ptp(levels)),
                                             capture_error_db=float(np.mean(levels)-target)), sort_keys=True))
        assert np.ptp(levels) <= .5
        assert abs(np.mean(levels)-target) <= 1
