"""D-16 closure: analytic gain, frozen compatibility and audio transfer checks."""
import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain
from mankomix.dsp.reference import basic, nonlinear
from tests import toolimpl_harness as H
from tests.test_tk_w2a1 import tone, amplitude, db


def render(kind, x, sr=48000, **params):
    return render_chain(x, sr, [dict(id='closure', type=kind, params=params)],
                        stage='track', seed=16).audio


@pytest.mark.parametrize('effect', [0, .5, 1])
@pytest.mark.parametrize('curve', [0, .5, 1])
def test_polynomial_finite_gain_across_family(effect, curve):
    # 統括の判断 D-16 による: G(A), retaining the +/-0.05 dB tolerance.
    A = .1
    gain = 1+effect*(1-curve/2)-8*effect*(1-curve)*A/(3*np.pi)-3*effect*curve*A*A/8
    x = tone(db=-20, seconds=.3)
    y = render('loudness_shaper', x, effect=effect, curve=curve)
    assert abs(db(amplitude(y, 1000)/amplitude(x, 1000))-db(gain)) <= .05


@pytest.mark.parametrize('mode', ['tanh', 'asymmetric'])
@pytest.mark.parametrize('factor', [1, 2, 4, 8])
def test_singleband_reference_null_across_drive_and_resampling(mode, factor):
    x = np.random.Generator(np.random.PCG64(16)).uniform(-1, 1, (2048, 2))
    for drive in (6, 12, 24):
        y = render('mb_saturator', x, crossovers_hz=[], drive_db=[drive],
                   level_db=[6], mix=[.5], output_db=-9, mode=mode, oversample=factor)
        params = P.validate_params('saturator', dict(drive_db=drive, mode=mode,
                                                   mix=.5, output_db=-3, oversample=factor))
        expected = nonlinear.saturator(x, 48000, params)[0]
        assert H.null(y, expected)['rms_dbfs'] <= -120


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_pan_static_bits_and_mirror_across_positions(sr):
    # 統括の判断 D-16 による: legacy bits and mirror <= -240 dBFS.
    x = np.random.Generator(np.random.PCG64(16)).uniform(-1, 1, (257, 2))
    worst = 0.
    for center in np.linspace(-1, 1, 17):
        a = render('autopan', x, sr, depth=0, center=float(center))
        b = render('autopan', x[:, ::-1].copy(), sr, depth=0, center=float(-center))
        expected = basic.pan(x, sr, dict(position=float(center), center_db=-3))[0]
        assert a.tobytes() == expected.tobytes()
        worst = max(worst, float(np.max(abs(a[:, ::-1]-b))))
    print('C4_AUTOPAN_MIRROR_DBFS', sr, db(worst))
    assert db(worst) <= -240


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_vibe_audio_transfer_and_vibrato_flatness(sr):
    # Compare the rendered impulse spectrum with the independently derived
    # transfer function, including DC, Nyquist and the very low first notch.
    n = 1 << int(np.ceil(np.log2(4*sr)))
    x = np.zeros((n, 1)); x[0] = 1
    f = np.fft.rfftfreq(n, 1/sr)
    corners = 12000/np.array([1., 15., 220., 4700.])
    k = (np.tan(np.pi*corners/sr)-1)/(np.tan(np.pi*corners/sr)+1)
    sos = [[v, 1, 0, 1, v, 0] for v in k]
    expected = signal.sosfreqz(sos, worN=f, fs=sr)[1]
    wet = np.fft.rfft(render('vibe', x, sr, depth=0, mode='vibrato')[:, 0])
    chorus = np.fft.rfft(render('vibe', x, sr, depth=0, mode='chorus')[:, 0])
    assert np.max(abs(wet-expected)) < 1e-10
    assert np.max(abs(chorus-(.55+.45*expected))) < 1e-10
    ripple = float(np.max(abs(20*np.log10(abs(wet)))))
    assert ripple <= .05
    assert abs(chorus).min() >= .1-1e-10
    assert len(signal.find_peaks(-abs(chorus))[0]) <= 2
    print('C4_VIBE_RESPONSE', sr, dict(vibrato_max_error_db=ripple,
                                     chorus_min_db=db(abs(chorus).min())))


def test_four_public_flags_and_unpatched_engine():
    for kind in ('loudness_shaper', 'mb_saturator', 'autopan', 'vibe'):
        assert P.PROCESSORS[kind]['implemented'] is True
        assert np.isfinite(render(kind, tone(seconds=.01))).all()
