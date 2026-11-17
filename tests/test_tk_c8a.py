"""C8a: moving partials, analysis windows and opt-in BB compatibility."""
import numpy as np
import pytest
from scipy import signal

from mankomix.dspx.bb import pitchtime as B
from tests.test_tk_w3b import direct


def instantaneous_error(y, sr, target, times, stop):
    measured = np.diff(np.unwrap(np.angle(signal.hilbert(y[:, 0]))))*sr/(2*np.pi)
    valid = (times[:-1] > .3) & (times[:-1] < stop) & (target < sr*.4)
    errors = 1200*np.log2(np.maximum(measured[valid], 1e-20)/target[valid])
    return float(np.max(np.abs(errors))), float(np.percentile(np.abs(errors), 95))


@pytest.mark.parametrize('method,f0,f1', [('linear', 300, 2400), ('logarithmic', 3200, 200)])
@pytest.mark.parametrize('quality', ['fast', 'standard', 'high'])
@pytest.mark.parametrize('semitones', [-12, 12])
def test_other_glide_directions_and_rate(method, f0, f1, quality, semitones):
    sr, seconds = 32000, 3.2
    t = np.arange(round(sr*seconds))/sr
    x = .2*signal.chirp(t, f0, seconds, f1, method=method)[:, None]
    y = direct('pitch_shift', x, dict(quality=quality, semitones=semitones), sr)
    frequency = (f0+(f1-f0)*t[:-1]/seconds if method == 'linear'
                 else f0*(f1/f0)**(t[:-1]/seconds))
    maximum, p95 = instantaneous_error(y, sr, frequency*2**(semitones/12), t, seconds-.5)
    print('C8a_glide', method, quality, semitones, 'max_cents', maximum, 'p95', p95)
    assert maximum <= 5


@pytest.mark.parametrize('window', [1024, 8192])
@pytest.mark.parametrize('transients', [0, 1])
@pytest.mark.parametrize('semitones', [-12, 12])
def test_high_window_and_transient_endpoints(window, transients, semitones):
    sr, seconds = 24000, 4
    t = np.arange(sr*seconds)/sr
    x = .2*signal.chirp(t, 100, seconds, 8000, method='logarithmic')[:, None]
    y = direct('pitch_shift', x, dict(semitones=semitones, window=window,
                                    transients=transients), sr)
    target = 100*80**(t[:-1]/seconds)*2**(semitones/12)
    maximum, p95 = instantaneous_error(y, sr, target, t, 3.5)
    print('C8a_window', window, transients, semitones, 'max_cents', maximum, 'p95', p95)
    assert maximum <= 5


@pytest.mark.parametrize('quality', ['fast', 'standard', 'high'])
@pytest.mark.parametrize('formant', [False, True])
def test_shared_shift_default_equals_explicit_legacy(quality, formant):
    x = np.random.Generator(np.random.PCG64(83)).normal(0, .05, (1600, 2))
    options = dict(quality=quality, formant=formant, window=1024)
    assert np.array_equal(B.shift(x, 16000, 5, **options),
                          B.shift(x, 16000, 5, track_glides=False, **options))


@pytest.mark.parametrize('stereo_link', [False, True])
@pytest.mark.parametrize('stretch', [.83, 1.5])
def test_shared_vocoder_default_equals_explicit_legacy(stereo_link, stretch):
    x = np.random.Generator(np.random.PCG64(84)).normal(0, .05, (1600, 2))
    options = dict(window=1024, stereo_link=stereo_link)
    assert np.array_equal(B.phase_vocoder(x, 16000, stretch, **options),
                          B.phase_vocoder(x, 16000, stretch, track_glides=False, **options))


@pytest.mark.parametrize('kind', ['stationary', 'noise', 'chord', 'cancelled_side', 'silence'])
def test_fast_clock_rejects_ambiguous_or_stationary_input(kind):
    sr = 16000
    t = np.arange(sr)/sr
    tone = .2*np.sin(2*np.pi*440*t)
    if kind == 'stationary':
        x = tone[:, None]
    elif kind == 'noise':
        x = np.random.Generator(np.random.PCG64(85)).normal(0, .1, (sr, 1))
    elif kind == 'chord':
        x = (tone+.2*np.sin(2*np.pi*713*t))[:, None]
    elif kind == 'cancelled_side':
        glide = .2*signal.chirp(t, 300, 1, 1000, method='linear')
        x = np.column_stack([glide+tone, glide-tone])
    else:
        x = np.zeros((sr, 1))
    assert B._glide_taps(x, sr, 2, 40) is None


@pytest.mark.parametrize('frames', [0, 1, 7, 800, 801])
def test_fast_short_context_and_guard_boundary(frames):
    x = .2*np.sin(2*np.pi*100*np.arange(frames)/8000)[:, None]
    y = direct('pitch_shift', x, dict(quality='fast', semitones=12), 8000)
    assert y.shape == x.shape and np.isfinite(y).all()
