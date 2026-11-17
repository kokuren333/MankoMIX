"""C7a fast-kernel closure: periodic tones, delay clock and causal history."""
import numpy as np
import pytest

from mankomix.dsp import processors as P
from mankomix.dspx.bb import pitchtime as B
from mankomix.dspx.bb.delayline import fractional_delay
from tests import toolimpl_harness as H
from tests.test_tk_w3b import direct, cents, ripple


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('semitones', [-24, -7, 7, 24])
def test_fast_stationary_rates_and_intervals(sr, semitones):
    x = H.sine(440, -12, sr=sr, seconds=1.5, channels=2)
    # A cancelled mid must not disable the common periodic tap clock.
    x[:, 1] *= -1
    y = direct('pitch_shift', x, dict(semitones=semitones, quality='fast'), sr)
    error = float(cents(y[sr//4:-sr//4, 0], sr, 440*2**(semitones/12)))
    am = ripple(y, sr)
    print('C7a_fast', sr, semitones, 'cents', error, 'ripple_db', am)
    assert abs(error) <= 10 and am <= 1
    assert np.max(np.abs(y[:, 0]+y[:, 1])) < 1e-12


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('freq', [100, 329.63, 440, 1337])
def test_micro_periods_across_complete_crossfades(sr, freq):
    # Seven seconds covers both +/-9 cent tap handovers at the default grain.
    x = H.sine(freq, -12, sr=sr, seconds=7, channels=1)
    y = direct('micro_pitch', x, dict(mix=1), sr)
    for channel, detune in enumerate((-9, 9)):
        error = float(cents(y[sr//4:-sr//4, channel], sr, freq*2**(detune/1200)))
        am = ripple(y[:, channel:channel+1], sr)
        print('C7a_micro', sr, freq, channel, 'cents', error, 'ripple_db', am)
        assert abs(error) <= .5 and am <= .5


@pytest.mark.parametrize('grain_ms', [10, 80])
@pytest.mark.parametrize('detune', [-50, 50])
def test_micro_grain_and_detune_endpoints(grain_ms, detune):
    sr = 48000
    x = H.sine(440, -12, sr=sr, seconds=7, channels=2)
    y = direct('micro_pitch', x, dict(left_cents=detune, right_cents=-detune,
                                    grain_ms=grain_ms, mix=1), sr)
    for channel, value in enumerate((detune, -detune)):
        error = float(cents(y[sr//4:-sr//4, channel], sr, 440*2**(value/1200)))
        am = ripple(y[:, channel:channel+1], sr)
        print('C7a_micro_endpoint', grain_ms, value, 'cents', error, 'ripple_db', am)
        assert abs(error) <= .5 and am <= .5


@pytest.mark.parametrize('delay', [0, .5, 1.5, 800, 800.25])
def test_musical_delay_follows_shifted_voice(delay):
    sr = 16000
    x = H.sine(440, -12, sr=sr, seconds=.8, channels=2)
    ratio = 2**(7/12)
    wet = B.fast_shift(x, sr, ratio)
    delayed = B.fast_shift(x, sr, ratio, delay_ms=1000*delay/sr)
    if delay == round(delay):
        assert np.array_equal(delayed, fractional_delay(wet, delay))
    else:
        # Measure the fundamental's delay independently by sine/cosine fitting.
        # Interpolating an already modulated voice would add another kernel's
        # sidebands, rather than provide an independent phase reference.
        theta = 2*np.pi*440*ratio*np.arange(4000, len(x)-4000)/sr
        basis = np.column_stack([np.sin(theta), np.cos(theta)])
        source = np.linalg.lstsq(basis, wet[4000:-4000, 0], rcond=None)[0]
        result = np.linalg.lstsq(basis, delayed[4000:-4000, 0], rcond=None)[0]
        phase = 2*np.pi*440*ratio*delay/sr
        sine, cosine = np.sin(phase), np.cos(phase)
        expected = [source[0]*cosine+source[1]*sine,
                    source[1]*cosine-source[0]*sine]
        difference = H.null(basis @ result, basis @ expected)
        print('C7a_fractional_delay', delay, difference['peak_dbfs'])
        assert difference['peak_dbfs'] <= -80


@pytest.mark.parametrize('ratio', [2**(-9/1200), 2**(7/12), 4.])
@pytest.mark.parametrize('delay', [0, .5, 800.25])
def test_period_selection_uses_no_future_audio(ratio, delay):
    sr, end = 16000, 3200
    x = H.sine(440, -12, sr=sr, seconds=.6, channels=2)
    other = x.copy()
    other[end:] = H.white_noise(-6, sr=sr, seconds=.4, channels=2)[:len(x)-end]
    params = dict(delay_ms=1000*delay/sr)
    a = B.fast_shift(x, sr, ratio, **params)
    b = B.fast_shift(other, sr, ratio, **params)
    assert np.array_equal(a[:end], b[:end])
    assert np.array_equal(a[:end], B.fast_shift(x[:end], sr, ratio, **params))


@pytest.mark.parametrize('kind', ['pitch_curve', 'harmonizer', 'micro_pitch'])
def test_closed_types_are_publicly_enabled(kind):
    assert P.describe(kind)['implemented'] is True
