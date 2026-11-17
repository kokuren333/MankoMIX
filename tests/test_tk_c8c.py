"""C8c closure: public formant shifting and the permitted hum domain."""
import json

import numpy as np
import pytest

from mankomix.dsp import processors as P, engine as E
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb import psola as B, stft as S
from mankomix.dspx.procs.guitar_denoise import expand
from tests import toolimpl_harness as H
from tests.test_tk_w3k import envelope_peaks, periodic_ripple, pitch_error


def measure(label, **values):
    print(label, json.dumps(values, sort_keys=True))


def render(kind, x, sr, params, stage='track'):
    return E.render_chain(x, sr, [dict(id='closure', type=kind, params=params)], stage=stage)


@pytest.mark.parametrize('kind', ['formant_shift', 'guitar_denoise'])
def test_public_closure(kind):
    assert P.describe(kind)['implemented'] is True


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('method', ['cepstrum', 'true_env', 'lpc'])
def test_active_formants_at_supported_rates(sr, method):
    targets = np.array([700, 1200, 2600])*2**.25
    x = H.vowel(150, formants_hz=(700, 1200, 2600), sr=sr, seconds=1.)
    result = render('formant_shift', x, sr, dict(shift_cents=300, envelope=method), stage='bus')
    peaks = envelope_peaks(result.audio, sr, targets)
    error = float(np.max(abs(peaks/targets-1)))
    cents = pitch_error(result.audio[sr//4:3*sr//4], sr, 150)
    measure('formants', sr=sr, method=method, peaks_hz=peaks.tolist(), relative_error=error, cents=cents)
    assert error <= .03
    assert abs(cents) <= 1
    assert result.audio.shape == x.shape and result.audio.dtype == np.float64


@pytest.mark.parametrize('sr', [16000, 44100, 48000, 96000])
@pytest.mark.parametrize('window', [1024, 2048, 4096])
def test_active_s4_all_windows_and_rates(sr, window):
    x = H.sine(997, -12, sr=sr, seconds=1., channels=2)
    rows = {}
    for method in ['cepstrum', 'true_env', 'lpc']:
        y = render('formant_shift', x, sr, dict(shift_cents=300, envelope=method, window=window)).audio
        ripple = periodic_ripple(y, sr, 997)
        rows[method] = ripple
        assert ripple <= .05, (sr, window, method, ripple)
        assert np.array_equal(y[:, 0], y[:, 1])
    measure('s4', sr=sr, window=window, ripple_db=rows)


def test_resolved_envelope_scaling_and_opt_in(monkeypatch):
    sr, n = 16000, 684
    m = np.abs(np.fft.rfft(np.hanning(n)))+1e-6
    for method in ['cepstrum', 'true_env', 'lpc']:
        env = B.resolved_spectral_envelope(m, sr, method, window=n)
        scaled = B.resolved_spectral_envelope(.1*m, sr, method, window=n)
        np.testing.assert_allclose(scaled, .1*env, rtol=1e-6)
    def forbidden(*args, **kwargs):
        raise AssertionError('legacy path entered the opt-in estimator')
    monkeypatch.setattr(B, 'resolved_spectral_envelope', forbidden)
    x = H.vowel(150, sr=sr, seconds=.1)
    y, delay = B.shift_envelope(x, sr, 300)
    explicit, _ = B.shift_envelope(x, sr, 300, resolved=False)
    assert np.array_equal(y, explicit) and delay == S.window_samples(2048, sr)


@pytest.mark.parametrize('hum', [0., .05, np.nextafter(.05, 1), .5, 1.])
def test_permitted_hum_exact_child_depth_and_public_render(hum):
    p = P.validate_params('guitar_denoise', dict(hum=hum, amp_noise=0, squeak=0, pick=0))
    children = expand(p)
    x = H.sine(50, -18, sr=16000, seconds=.1)
    result = render('guitar_denoise', x, 16000, p)
    assert np.isfinite(result.audio).all()
    if hum == 0:
        assert children == [] and result.audio.tobytes() == x.tobytes()
    else:
        assert children == [dict(type='dehum', params=dict(depth_db=60*hum, harmonics=16, base_hz=0.))]
        assert P.validate_params('dehum', children[0]['params'])['depth_db'] == 60*hum
        manual = E.render_chain(x, 16000, [dict(id='closure.1', **children[0])], stage='track')
        assert result.audio.tobytes() == manual.audio.tobytes()
        assert result.steps[0]['composite_of']['type'] == 'guitar_denoise'
    measure('hum', hum=hum, depth_db=60*hum, children=len(children))


@pytest.mark.parametrize('hum', [np.nextafter(0., 1), .001, .025, np.nextafter(.05, 0)])
def test_forbidden_hum_rejected_before_expansion(hum):
    with pytest.raises(ParamError, match='hum must be zero or 0.05'):
        P.validate_params('guitar_denoise', dict(hum=hum))
    p = P.validate_params('guitar_denoise', {})
    with pytest.raises(ParamError, match='hum must be zero or 0.05'):
        expand({**p, 'hum': hum})


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('stage', ['track', 'bus'])
def test_guitar_all_stages_rates_children_and_empty(sr, stage):
    x = H.white_noise(-18, sr=sr, seconds=.04, channels=2)
    p = dict(hum=.05, hum_hz=50, amp_noise=1, gate_threshold_db=-80, squeak=1, pick=1)
    result = render('guitar_denoise', x, sr, p, stage)
    repeat = render('guitar_denoise', x, sr, p, stage)
    assert result.audio.shape == x.shape and np.isfinite(result.audio).all()
    assert result.audio.tobytes() == repeat.audio.tobytes()
    assert [s['type'] for s in result.steps] == ['dehum', 'denoise', 'gate', 'resonance_suppressor', 'transient_shaper']
    zero = dict(hum=0, amp_noise=0, squeak=0, pick=0)
    assert render('guitar_denoise', x, sr, zero, stage).audio.tobytes() == x.tobytes()
