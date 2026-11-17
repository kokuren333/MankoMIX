"""C1 additions: opt-in DSP contracts and specification contradictions."""
import importlib
import math

import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import processors as P
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb import nonlinear as N
from mankomix.dspx.procs.fuzz import fuzz_curve, hard_fuzz_primitive, gated_fuzz_primitive
from tests.test_tk_w2a1 import tone, alias_db, render, db, amplitude


@pytest.mark.parametrize('factor', [1, 2, 4, 8, 16, 32, 64, 128, 256])
def test_precision_resampler_latency_and_contract(factor):
    x = np.zeros((1024, 2)); x[512] = 1
    seen = []
    def identity(u):
        seen.append(u.shape)
        return u
    y = N.precision_oversampled(x, factor, identity)
    assert seen == [(len(x)*factor, 2)]
    assert y.shape == x.shape and np.argmax(abs(y[:, 0])) == 512
    assert N.precision_oversampled(x, factor, identity).tobytes() == y.tobytes()
    assert N.precision_oversampled(x[:0], factor, identity).shape == (0, 2)
    info = N.precision_oversampling_info(factor)
    assert info['latency_samples'] == 0
    assert info['uncompensated_latency_samples'] == (352 if factor > 2 else 320 if factor == 2 else 0)
    if factor > 1:
        h = N._precision_os_filter(factor)
        raw = signal.upfirdn(h*factor, x, up=factor, axis=0)
        if factor > 2:
            raw = signal.upfirdn(N._precision_os_filter(factor//2), raw, down=factor//2, axis=0)
        raw = signal.upfirdn(N._precision_final_filter(), raw, down=2, axis=0)
        assert np.argmax(abs(raw[:, 0]))-512 == info['uncompensated_latency_samples']


@pytest.mark.parametrize('factor', [0, 3, 512])
def test_precision_rejects_invalid_factor(factor):
    with pytest.raises(ParamError):
        N.precision_oversampled(np.zeros((2, 1)), factor, np.tanh)
    with pytest.raises(ParamError):
        N.precision_oversampling_info(factor)


@pytest.mark.parametrize('bias', [-1, -.5, 0, .2, .5, 1])
@pytest.mark.parametrize('shape', ['hard', 'octave'])
def test_fuzz_analytic_integral(bias, shape):
    x = np.linspace(-1, 1, 20003)[:, None]
    h = 1e-7
    derivative = (hard_fuzz_primitive(x+h, 30, bias, shape)
                  -hard_fuzz_primitive(x-h, 30, bias, shape))/(2*h)
    assert np.max(abs(derivative-fuzz_curve(x, 30, bias, 0, shape))) < 1e-7


@pytest.mark.parametrize('gate', [.2, 1])
@pytest.mark.parametrize('shape', ['hard', 'octave'])
def test_gate_aware_fuzz_integral(gate, shape):
    edge = .02*gate**4
    x = np.linspace(-3*edge, 3*edge, 10003)[:, None]
    h = edge*1e-5
    primitive = gated_fuzz_primitive(30, .2, gate, shape)
    derivative = (primitive(x+h)-primitive(x-h))/(2*h)
    assert np.max(abs(derivative-fuzz_curve(x, 30, .2, gate, shape))) < 1e-6


def test_fuzz_default_gate_small_signal_and_full_gate(monkeypatch):
    monkeypatch.setitem(P.PROCESSORS['fuzz'], 'implemented', True)
    x = tone(db=-60)
    # The default dead zone lies below the -60 dBFS probe, while full
    # gate must still remove a -50 dBFS signal before input drive.
    assert np.max(abs(render('fuzz', tone(db=-50), dict(gate=1)))) == 0
    current = render('fuzz', x)
    gain = db(amplitude(current, 1000)/amplitude(x, 1000))
    print('C1_FUZZ_DEFAULT_GAIN', gain)
    assert abs(gain) <= .05



def test_loudness_finite_amplitude_contradiction():
    # Exact fundamental of f(A sin(t)), before reconstruction filtering.
    a, c, amplitude_in = 1, .5, .1
    gain_zero = 1+a*(1-c/2)
    gain_finite = gain_zero-a*(1-c)*8*amplitude_in/(3*math.pi)-3*a*c*amplitude_in**2/8
    error = 20*math.log10(gain_finite/gain_zero)
    peak = 10**(-1/20)
    mapped = float(N.loudness_curve(np.array([peak]), a, c)[0])
    print('C1_LOUDNESS_EXACT', dict(finite_gain_error_db=error, input_peak=peak, mapped_peak=mapped))
    assert abs(error) > .05 and mapped > peak


@pytest.mark.parametrize('mode', ['tanh', 'asymmetric'])
def test_original_saturator_compatibility_conflict(mode):
    from mankomix.dsp.reference import nonlinear as original
    x = tone(5000)
    p = P.validate_params('saturator', dict(drive_db=12, mode=mode))
    y = original.saturator(x, 48000, p)[0]
    measured = alias_db(y, 5000)
    # NT2 needs -80 dBc; even a -120 dBFS RMS null cannot remove the
    # existing alias component of this frozen reference implementation.
    carrier_rms = amplitude(y, 5000)/math.sqrt(2)
    correction_rms = carrier_rms*(10**(measured/20)-10**(-80/20))
    print('C1_ORIGINAL_ALIAS', mode, measured, 'MIN_CORRECTION_DBFS', db(correction_rms))
    assert measured > -80
    assert db(correction_rms) > -120


def test_original_saturator_dc_compatibility_conflict():
    from mankomix.dsp.reference import nonlinear as original
    x = tone()
    p = P.validate_params('saturator', dict(drive_db=12, mode='asymmetric'))
    y = original.saturator(x, 48000, p)[0]
    dc = abs(float(np.mean(y)))
    print('C1_ORIGINAL_DC_DBFS', db(dc), 'MIN_CORRECTION_DBFS', db(dc-1e-4))
    assert dc > 1e-4 and dc-1e-4 > 1e-6


@pytest.mark.parametrize('curve', ['hard', 'fold'])
def test_clipping_band_normalized_small_signal(monkeypatch, curve):
    monkeypatch.setitem(P.PROCESSORS['mb_distortion'], 'implemented', True)
    x = tone(db=-60, seconds=.15)
    y = render('mb_distortion', x,
               dict(crossovers_hz=[], kind_1=curve, drive_db=[24]))
    assert abs(db(amplitude(y, 1000)/amplitude(x, 1000))) <= .05


@pytest.mark.parametrize('kind,params,limit', [
    ('exciter', dict(amount_db=-6, drive_db=36, dynamic=1), -80),
    ('fuzz', dict(drive_db=60), -60),
    ('mb_distortion', dict(crossovers_hz=[], kind_1='fold', drive_db=[48]), -60),
])
def test_maximum_drive_aliasing(monkeypatch, kind, params, limit):
    monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)
    values = {f: alias_db(render(kind, tone(f, seconds=1.5), params), f)
              for f in (5000, 10000, 15000)}
    print('C1_MAX_DRIVE_ALIAS', kind, values)
    assert max(values.values()) <= limit


def test_c1_public_flags():
    for kind in ('exciter', 'fuzz', 'mb_distortion', 'loudness_shaper', 'mb_saturator'):
        spec = importlib.import_module('mankomix.dspx.procs.'+kind).SPECS[0]
        assert spec['implemented'] is (kind in ('exciter', 'fuzz', 'mb_distortion'))
