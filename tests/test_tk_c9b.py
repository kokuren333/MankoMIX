"""C9b: close harmonics, legacy BB behavior, and active registered retuning."""
import numpy as np
import pytest
from mankomix.dspx.bb import partials, stft
from tests.test_tk_w3m import component_levels, direct, mapping, render, emit, H


@pytest.mark.parametrize('phase', [0., .7, 2.1])
def test_close_triad_with_independent_phases_and_levels(phase):
    sr = 12000
    roots = 440*2**((np.array([60, 64, 67])-69)/12)
    t = np.arange(3*sr)/sr
    x = sum((.1+.02*i)/h*np.sin(2*np.pi*f*h*t+phase*(i+1)*h)
            for i, f in enumerate(roots) for h in range(1, 7))[:, None]
    y = render('poly_retune', x, dict(map=mapping()), sr=sr)
    original = np.ravel(roots[:, None]*np.arange(1, 7))
    moved = roots[1]*2**(-1/12)*np.arange(1, 7)
    body = slice(sr, 2*sr)
    before = component_levels(x[body], sr, original)
    after = component_levels(y[body], sr, np.r_[original, moved])
    kept = np.r_[np.arange(6), np.arange(12, 18)]
    change = 20*np.log10(after[kept]/before[kept])
    emit('c9b_phases', dict(phase=phase, unchanged_db=change.tolist()))
    assert max(abs(change)) <= 1
    assert np.all(after[18:] > .5*before[6:12])
    assert render('poly_retune', x, dict(map=mapping()), sr=sr).tobytes() == y.tobytes()


def test_close_triad_joint_fit_preserves_stereo_polarity():
    sr = 12000
    t = np.arange(sr*2)/sr
    roots = 440*2**((np.array([60, 64, 67])-69)/12)
    mono = sum(.1/h*np.sin(2*np.pi*f*h*t) for f in roots for h in range(1, 7))
    for polarity in (1, -1):
        x = np.column_stack([mono, polarity*mono])
        y = direct('poly_retune', x, dict(map=mapping()), sr=sr)[0]
        assert np.max(abs(y[:, 1]-polarity*y[:, 0])) < 1e-12


def test_legacy_region_api_keeps_opt_in_default():
    sr = 12000
    t = np.arange(sr)/sr
    x = (.1*np.sin(2*np.pi*261.6255653*t)
         +.05*np.sin(2*np.pi*329.6275569*t))[:, None]
    a = stft.analyze(x, sr, window=2048)
    default, first = partials.retune_regions(a, mapping())
    legacy, second = partials.retune_regions(a, mapping(), resolve_close=False)
    assert default.tobytes() == legacy.tobytes()
    assert first == second


def test_predicted_close_harmonic_below_threshold_is_preserved():
    sr = 12000
    roots = 440*2**((np.array([60, 64, 67])-69)/12)
    t = np.arange(3*sr)/sr
    x = sum((1e-6 if i == 1 and h == 4 else .1/h)*np.sin(2*np.pi*f*h*t)
            for i, f in enumerate(roots) for h in range(1, 7))[:, None]
    y = direct('poly_retune', x, dict(map=mapping()), sr=sr)[0]
    frequencies = [roots[0]*5, roots[1]*4, roots[1]*4*2**(-1/12)]
    residual = component_levels((x-y)[sr:2*sr], sr, frequencies)[1]
    emit('c9b_hidden_weak', dict(residual_dbfs=H.db(residual)))
    assert H.db(residual) <= -60


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_active_close_harmonics_at_production_rates(sr):
    roots = 440*2**((np.array([60, 64, 67])-69)/12)
    t = np.arange(2*sr)/sr
    x = sum(.1/h*np.sin(2*np.pi*f*h*t+.13*h)
            for f in roots for h in range(1, 7))[:, None]
    y = render('poly_retune', x, dict(map=mapping()), sr=sr)
    original = np.ravel(roots[:, None]*np.arange(1, 7))
    moved = roots[1]*2**(-1/12)*np.arange(1, 7)
    body = slice(sr//2, 3*sr//2)
    before = component_levels(x[body], sr, original)
    after = component_levels(y[body], sr, np.r_[original, moved])
    kept = np.r_[np.arange(6), np.arange(12, 18)]
    change = 20*np.log10(after[kept]/before[kept])
    target = moved[4]
    frequency = H.fundamental_frequency(y[body], sr, low_hz=target-8, high_hz=target+8)
    error = 1200*np.log2(frequency/target)
    emit('c9b_active_rate', dict(sr=sr, unchanged_db=change.tolist(), e_fifth_error_cents=error))
    assert max(abs(change)) <= 1 and abs(error) <= 10
