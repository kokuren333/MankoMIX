"""C7d closure: public registration, tape limits and active amp alignment."""
import itertools
import json

import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import engine as E, processors as P
from tests import toolimpl_harness as H


def render(name, x, p=None, sr=48000):
    return E.render_chain(x, sr, [dict(id='closure', type=name, params=p or {})], stage='track')


def spectrum(y, f=1000, sr=48000):
    # A coherent 100 ms window, with 150 ms of settling and 50 ms end guard.
    z = y[round(.15*sr):round(.25*sr), 0]
    sp = 2*abs(np.fft.rfft(z))/len(z)
    k = round(f*.1)
    allowed = np.zeros(len(sp), dtype=bool)
    allowed[0] = True
    allowed[k::k] = True
    return H.db(np.linalg.norm(sp[~allowed])/sp[k]), H.db(sp[k])


def test_public_closure_registration():
    for name in ['tape', 'cassette', 'lofi', 'amp_basic']:
        assert P.describe(name)['implemented'] is True
        assert np.isfinite(render(name, H.sine(1000, -12, seconds=.02, channels=2)).audio).all()


@pytest.mark.parametrize('memory', [False, True])
def test_tape_nt2_at_drive_and_magnetic_endpoints(memory):
    rows = []
    for saturation, bias, f in itertools.product([0, 1], [0, 1], [5000, 10000, 15000]):
        x = H.sine(f, -6, seconds=.3)
        p = dict(hysteresis=memory, drive_db=24, saturation=saturation, bias=bias)
        result = render('tape', x, p)
        alias, _ = spectrum(result.audio, f)
        rows.append([saturation, bias, f, alias])
        assert alias <= -70, rows[-1]
        assert result.steps[0]['stats']['internal_oversample'] == 8
    print('C7D_TAPE_NT2', memory, json.dumps(rows))


@pytest.mark.parametrize('memory', [False, True])
def test_tape_nt4_across_speed_and_drive(memory):
    rows = []
    for speed, drive in itertools.product([3.75, 7.5, 15, 30], [0, 6, 12, 18, 24]):
        p = dict(hysteresis=memory, speed=speed, drive_db=drive)
        _, gain = spectrum(render('tape', H.sine(1000, -60, seconds=.3), p).audio)
        rows.append([speed, drive, gain+60])
        assert abs(gain+60) <= .05, rows[-1]
    print('C7D_TAPE_NT4', memory, json.dumps(rows))


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_iec_time_constants_and_exact_reciprocal(sr):
    from mankomix.dspx.bb.tape_model import recording_eq
    rows = []
    rate = 8*sr
    f = np.array([20., 100., 1000., 10000.])
    s = 2j*rate*np.tan(np.pi*f/rate)
    for speed, low, high in [(3.75, .003180, .000090), (7.5, None, .000070),
                             (15, None, .000035), (30, None, .0000175)]:
        b, a = recording_eq(rate, speed)
        _, response = signal.freqz(b, a, worN=f, fs=rate)
        expected = (1+s*high)/(1+s/(2*np.pi*.45*rate))
        if low is not None:
            expected *= (s+2*np.pi*2)/(s+1/low)
        expected /= abs(expected[2])
        np.testing.assert_allclose(response, expected, rtol=1e-8, atol=1e-8)
        x = H.white_noise(seconds=.01, sr=rate, seed=13)
        y = signal.lfilter(a, b, signal.lfilter(b, a, x, axis=0), axis=0)
        assert H.null(x, y)['rms_dbfs'] <= -120
        rows.append([speed, low, high, (20*np.log10(abs(response))).tolist()])
    print('C7D_EQ', sr, json.dumps(rows))


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_amp_nt6_active_mixed_and_control_endpoints(sr):
    rows = []
    x = np.zeros((3000, 2)); x[1500] = [.1, -.1]
    for stages, controls in itertools.product([1, 2, 4], [dict(),
        dict(bright=True, bass=0, mid=1, treble=1, presence_db=6),
        dict(bass=1, mid=0, treble=0, presence_db=-6)]):
        p = dict(stages=stages, **controls)
        result = render('amp_basic', x, p, sr)
        wet = result.audio
        half = render('amp_basic', x, dict(p, mix=.5), sr).audio
        assert H.latency(wet, reference=x, method='correlation') == 0
        assert H.latency(half, reference=x, method='correlation') == 0
        assert H.null(half, .5*(x+wet))['rms_dbfs'] <= -120
        rows.append([stages, controls, result.steps[0]['stats']['circuit_delay_samples']])
    print('C7D_AMP_NT6', sr, json.dumps(rows))


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_nonlinear_active_alignment_at_operating_rates(sr):
    x = np.zeros((2048, 1)); x[1024] = .1
    for memory, speed in itertools.product([False, True], [3.75, 7.5, 15, 30]):
        p = dict(hysteresis=memory, speed=speed, drive_db=24)
        wet = render('tape', x, p, sr).audio
        assert H.latency(wet, reference=x, method='correlation') == 0
    for factor, stages in itertools.product([1, 2, 4, 8], [1, 4]):
        p = dict(oversample=factor, stages=stages)
        wet = render('amp_basic', x, p, sr).audio
        assert H.latency(wet, reference=x, method='correlation') == 0


@pytest.mark.parametrize('name,drive', [('tape', 0), ('tape', 24), ('amp_basic', 24), ('amp_basic', 60)])
def test_nt5_long_stationary_dc(name, drive):
    x = H.sine(1000, -6, seconds=2)
    y = render(name, x, dict(drive_db=drive)).audio
    dc = H.db(float(np.max(abs(np.mean(y[48000:90000], axis=0)))))
    assert dc <= -80
    assert np.count_nonzero(render(name, np.zeros((512, 2)), dict(drive_db=drive)).audio) == 0
    print('C7D_NT5', name, drive, dc)


@pytest.mark.parametrize('name', ['cassette', 'lofi'])
def test_empty_composite_identity_record_and_order(name):
    p = dict(wobble=0, saturation=0, age=0, hiss_db=-120, narrow=0) if name == 'cassette' else dict.fromkeys(
        ['wobble', 'dirt', 'crunch', 'tone', 'noise', 'space'], 0)
    source = dict(id='empty', type=name, params=p)
    x = H.white_noise(seconds=.02, channels=2, seed=61)
    x[0] = [-0., 0.]
    result = E.render_chain(x, 48000, [source], stage='track')
    assert result.audio.tobytes() == x.tobytes()
    assert len(result.steps) == 1
    assert result.steps[0]['id'] == 'empty'
    assert result.steps[0]['composite_of'] == source
    assert result.steps[0]['expansion'] == []
    before, after = dict(type='gain', params=dict(gain_db=-3)), dict(type='gain', params=dict(gain_db=1))
    a = E.render_chain(x, 48000, [before, source, after], stage='track')
    b = E.render_chain(x, 48000, [before, after], stage='track')
    assert a.audio.tobytes() == b.audio.tobytes()
