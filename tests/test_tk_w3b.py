"""BB-11 / W3b: independent PT measurements, contracts and open limitations.

Strict xfails retain original acceptance numbers for reproducible limitations;
enabling a processor in a test fixture never changes its public declaration.
"""
import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb import pitchtime as B
from mankomix.dspx.procs import pitch_shift as PS, pitch_curve as PC
from mankomix.dspx.procs import harmonizer as HA, micro_pitch as MP
from tests import toolimpl_harness as H

KINDS = ('pitch_shift', 'pitch_curve', 'harmonizer', 'micro_pitch')
MODULES = dict(zip(KINDS, (PS, PC, HA, MP)))
QUALITY = ('fast', 'standard', 'high')


@pytest.fixture
def enabled(monkeypatch):
    for kind in KINDS:
        monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)


def direct(kind, x, p=None, sr=16000):
    return MODULES[kind].IMPLS[kind](x, sr, P.validate_params(kind, p or {}), seed=19)[0]


def render(kind, x, p=None, sr=16000):
    return E.render_chain(x, sr, [{'type': kind, 'params': p or {}}], stage='track').audio


def frequency(x, sr, target):
    return H.fundamental_frequency(x, sr, low_hz=max(10, target*.8), high_hz=min(sr*.49, target*1.2))


def cents(x, sr, target):
    return 1200*np.log2(frequency(x, sr, target)/target)


def ripple(x, sr, guard=.25):
    env = np.abs(signal.hilbert(x[:, 0]))[round(guard*sr):-round(guard*sr)]
    return float(20*np.log10(env.max()/max(env.min(), 1e-30)))


def width90(x):
    energy = np.asarray(x)**2
    cumulative = np.r_[0., np.cumsum(energy)]
    ends = np.searchsorted(cumulative, cumulative[:-1]+.9*cumulative[-1])
    starts = np.arange(len(energy))
    valid = ends <= len(energy)
    return int(np.min(ends[valid]-starts[valid]))


@pytest.mark.parametrize('quality', QUALITY)
def test_pt1_neutral_exact(quality):
    x = H.white_noise(-12, sr=16000, seconds=.21, channels=2)
    for options in ({}, dict(formant=True, formant_cents=1200), dict(mix=.5)):
        y = direct('pitch_shift', x, dict(quality=quality, **options))
        assert H.null(x, y)['bit_identical']
    for fn in (B.wsola, B.phase_vocoder):
        assert H.null(x, fn(x, 16000, 1))['peak_dbfs'] <= -120


@pytest.mark.parametrize('quality', QUALITY)
@pytest.mark.parametrize('freq', [100, 440, 1000, 3000])
def test_pt2_pt3_stationary(quality, freq):
    x = H.sine(freq, -12, sr=16000, seconds=1.5, channels=1)
    y = direct('pitch_shift', x, dict(semitones=7, quality=quality))
    error = float(cents(y[4000:-4000], 16000, freq*2**(7/12)))
    am = ripple(y, 16000)
    print('PT2/PT3', quality, freq, 'cents', error, 'ripple_db', am)
    assert abs(error) <= (10 if quality == 'fast' else 3)
    assert am <= {'fast': 1, 'standard': .5, 'high': .2}[quality]


@pytest.mark.parametrize('quality', QUALITY)
@pytest.mark.parametrize('semitones', [-24, -12, 5, 12, 24])
def test_pt4_same_length(quality, semitones):
    x = H.sine(440, -12, sr=16000, seconds=.123, channels=2)
    y = direct('pitch_shift', x, dict(semitones=semitones, quality=quality))
    assert y.shape == x.shape and y.dtype == np.float64 and np.isfinite(y).all()


@pytest.mark.parametrize('fn', [B.wsola, B.phase_vocoder])
@pytest.mark.parametrize('ratio', [.5, .83, 1, 1.5, 2])
def test_pt4_stretch_length_and_pitch(fn, ratio):
    x = H.sine(440, -12, sr=16000, seconds=.75, channels=1)
    y = fn(x, 16000, ratio)
    assert len(y) == round(len(x)*ratio)
    assert abs(cents(y[len(y)//4:3*len(y)//4], 16000, 440)) <= 3


@pytest.mark.parametrize('quality', ['standard', 'high'])
@pytest.mark.parametrize('operation', ['shift', 'stretch'])
def test_pt5_clicks(quality, operation):
    sr = 16000
    x = np.zeros((sr, 1))
    positions = np.arange(1600, 15000, 1600)
    x[positions] = .5
    ratio = 1.35
    if operation == 'shift':
        y = direct('pitch_shift', x, dict(semitones=5, quality=quality))
        expected = positions
    else:
        fn = B.wsola if quality == 'standard' else B.phase_vocoder
        y = fn(x, sr, ratio)
        expected = np.rint(positions*ratio).astype(int)
    widths, offsets = [], []
    for pos in expected:
        block = y[pos-700:pos+700, 0]
        widths.append(width90(block)*1000/sr)
        offsets.append((np.argmax(np.abs(block))-700)*1000/sr)
    print('PT5', quality, operation, 'width_ms', widths, 'offset_ms', offsets)
    assert max(widths) <= (5 if quality == 'standard' else 10)
    assert max(np.abs(offsets)) <= 5


def envelope_peaks(x, sr, targets):
    """Independent power-envelope measurement, 120 Hz Gaussian smoothing.

    Wider than a harmonic step of the test's 100/133 Hz F0; local maxima are
    searched in +/-15% regions. This does not use the implementation lifter.
    """
    n = 65536
    v = x[sr//3:-sr//3, 0]
    spectrum = np.abs(np.fft.rfft(v*np.hanning(len(v)), n))**2
    f = np.fft.rfftfreq(n, 1/sr)
    sigma = 120*n/sr
    smooth = signal.convolve(spectrum, signal.windows.gaussian(round(sigma)*8+1, sigma), mode='same')
    peaks = []
    for target in targets:
        indices = np.flatnonzero((f > target*.85) & (f < target*1.15))
        peaks.append(f[indices[np.argmax(smooth[indices])]])
    return np.array(peaks)


@pytest.mark.parametrize('quality', ['standard', 'high'])
@pytest.mark.parametrize('preserve', [False, True])
def test_pt6_vowel(quality, preserve):
    x = H.vowel(sr=16000, seconds=1.5, f0=100)
    y = direct('pitch_shift', x, dict(semitones=5, quality=quality, formant=preserve))
    original = envelope_peaks(x, 16000, [700, 1200, 2500])
    target = original*(1 if preserve else 2**(5/12))
    measured = envelope_peaks(y, 16000, target)
    error = np.abs(measured/target-1)
    print('PT6', quality, preserve, 'input', original, 'output', measured, 'relative_error', error)
    assert max(error) <= .03


def test_high_stereo_identity_and_anticancelled_mid():
    x = H.sine(440, -12, sr=16000, seconds=.6, channels=2)
    for sign in (1, -1):
        x[:, 1] = sign*x[:, 0]
        y = direct('pitch_shift', x, dict(semitones=7))
        if sign == 1:
            assert np.array_equal(y[:, 0], y[:, 1])
        else:
            assert np.max(np.abs(y[:, 0]+y[:, 1])) < 1e-12


def test_linked_stereo_correlation():
    sr = 16000
    t = np.arange(sr)/sr
    common = np.sin(2*np.pi*440*t)
    x = .15*np.column_stack([common+.3*np.sin(2*np.pi*713*t), common+.3*np.sin(2*np.pi*1137*t)])
    y = direct('pitch_shift', x, dict(semitones=7))
    a, b = np.corrcoef(x.T)[0, 1], np.corrcoef(y[4000:-4000].T)[0, 1]
    print('stereo_correlation', a, b, 'change', b-a)
    assert abs(b-a) <= .05


@pytest.mark.parametrize('quality', QUALITY)
@pytest.mark.parametrize('semitones', [-12, 12])
def test_sweep_acceptance(quality, semitones, request):
    if quality != 'high' or semitones != 12:
        request.node.add_marker(pytest.mark.xfail(strict=True,
            reason='Log sweep instantaneous frequency exceeds +/-5 cents'))
    sr, seconds = 24000, 4
    t = np.arange(sr*seconds)/sr
    x = .2*signal.chirp(t, 100, seconds, 8000, method='logarithmic')[:, None]
    y = direct('pitch_shift', x, dict(semitones=semitones, quality=quality), sr)
    actual = np.diff(np.unwrap(np.angle(signal.hilbert(y[:, 0]))))*sr/(2*np.pi)
    target = 100*80**(t[:-1]/seconds)*2**(semitones/12)
    valid = (t[:-1] > .3) & (t[:-1] < 3.5) & (target < sr*.4)
    errors = 1200*np.log2(np.maximum(actual[valid], 1e-20)/target[valid])
    print('sweep', quality, semitones, 'max_abs_cents', np.max(np.abs(errors)), 'p95', np.percentile(np.abs(errors), 95))
    assert np.max(np.abs(errors)) <= 5


@pytest.mark.parametrize('quality', QUALITY)
def test_upshift_alias_rejection(quality):
    sr = 48000
    x = H.sine(15000, -12, sr=sr, seconds=.5, channels=1)
    y = direct('pitch_shift', x, dict(semitones=12, quality=quality), sr)
    alias_db = H.rms_dbfs(y[6000:-6000])-H.rms_dbfs(x[6000:-6000])
    print('alias', quality, 'relative_db', alias_db)
    assert alias_db <= -70


def test_bend_neutral_and_context(enabled):
    x = H.white_noise(-18, sr=16000, seconds=1, channels=2)
    for interp in ('linear', 'smooth', 'step'):
        p = dict(bend=[[0, 0], [.2, 0], [.3, 7], [.5, 0], [.7, 0], [.8, -5]], interp=interp)
        y = render('pitch_curve', x, p)
        assert np.array_equal(y[9000:10500], x[9000:10500])
        part = H.render_excerpt('pitch_curve', x, 16000, 8000, 12000, p)
        assert H.null(y[8000:12000], part)['bit_identical']
    assert H.null(x, render('pitch_curve', x))['bit_identical']
    p = dict(bend=[[0, 0], [.2, 7], [.5, 0], [.8, -5]], interp='step', glide_ms=50)
    y = render('pitch_curve', x, p)
    assert H.null(x[10400:11200], y[10400:11200])['bit_identical']


@pytest.mark.parametrize('quality', ['fast', 'standard'])
def test_bend_ramp(quality):
    sr = 16000
    x = H.sine(1000, -12, sr=sr, seconds=1.5, channels=1)
    y = direct('pitch_curve', x, dict(bend=[[0, 0], [1, 12]], quality=quality))
    hz = np.diff(np.unwrap(np.angle(signal.hilbert(y[:, 0]))))*sr/(2*np.pi)
    t = np.arange(len(hz))/sr
    valid = (t > .1) & (t < .9)
    errors = 1200*np.log2(np.maximum(hz[valid], 1e-20)/(1000*2**t[valid]))
    print('bend', quality, 'max_abs_cents', np.max(np.abs(errors)))
    assert max(np.abs(errors)) <= 15


def test_bend_interpolation_and_glide():
    points = [[0, 0], [.2, 12], [.4, 0]]
    linear = B.bend_values(points, 8000, 16000)
    smooth = B.bend_values(points, 8000, 16000, 'smooth')
    step = B.bend_values(points, 8000, 16000, 'step', 10)
    assert linear[1600] == 6 and smooth[1600] != 6
    assert step[3199] == 0
    assert step[3359] == 12
    assert abs(step[3279]-6) < 1e-12
    assert np.all(step[6560:] == 0)
    assert np.max(smooth) <= 12 and np.min(smooth) >= 0


@pytest.mark.parametrize('quality', ['fast', 'standard'])
def test_bend_constant_pt2_pt3(quality):
    sr = 16000
    x = H.sine(440, -12, sr=sr, seconds=1.5, channels=1)
    y = direct('pitch_curve', x, dict(bend=[[0, 7]], quality=quality), sr)
    error = float(cents(y[4000:-4000], sr, 440*2**(7/12)))
    am = ripple(y, sr)
    print('bend_constant', quality, 'cents', error, 'ripple_db', am)
    assert abs(error) <= (10 if quality == 'fast' else 3)
    assert am <= (1 if quality == 'fast' else .5)


@pytest.mark.parametrize('count', [0, 1, 2, 4])
def test_harmonizer_dry_and_mute(count):
    x = H.white_noise(-12, sr=16000, seconds=.1, channels=2)
    p = dict(semitones=[7]*count, level_db=[-60]*count)
    assert H.null(x, direct('harmonizer', x, p))['bit_identical']


@pytest.mark.parametrize('quality', QUALITY)
def test_harmonizer_voice_frequency_pan_delay(quality):
    sr = 16000
    x = H.sine(440, -12, sr=sr, seconds=1.25, channels=2)
    p = dict(semitones=[7], level_db=[-6], pan=[1], delay_ms=[50], dry_db=-90, quality=quality)
    y = direct('harmonizer', x, p)
    expected = 440*2**(7/12)
    error = float(cents(y[4000:-4000, 1], sr, expected))
    print('harmonizer', quality, 'cents', error)
    assert np.max(np.abs(y[:, 0]-x[:, 0]*10**(-90/20))) < 1e-15
    assert abs(error) <= 3
    # Removing the musical delay uses the same compensated voice samples.
    z = direct('harmonizer', x, {**p, 'delay_ms': [0]})
    dry = x*10**(-90/20)
    assert H.null((z-dry)[:-800], (y-dry)[800:])['peak_dbfs'] < -120


def test_harmonizer_feedback_octaves():
    sr = 8000
    # A gated tone separates repeats without confusing the fast grain delay.
    x = np.zeros((sr*2, 1))
    x[400:880, 0] = .2*np.sin(2*np.pi*800*np.arange(480)/sr)*signal.windows.tukey(480, .25)
    y = direct('harmonizer', x, dict(semitones=[-12], level_db=[0], delay_ms=[250],
        feedback=[.5], dry_db=-90), sr)
    measurements = []
    for repeat in (1, 2, 3):
        start = round((.05+repeat*.25)*sr)
        z = y[start:start+1500]
        target = 800*2**(-repeat)
        measurements.append((frequency(z, sr, target), H.peak_dbfs(z)))
    print('feedback_repeats_hz_dbfs', measurements)
    for repeat, (hz, _) in enumerate(measurements, 1):
        assert abs(1200*np.log2(hz/(800*2**(-repeat)))) <= 10
    levels = [v[1] for v in measurements]
    assert max(np.abs(np.diff(levels)+20*np.log10(2))) <= .5


@pytest.mark.parametrize('quality', ['standard', 'high'])
def test_harmonizer_feedback_refused(quality):
    with pytest.raises(ParamError):
        P.validate_params('harmonizer', dict(feedback=[.1], quality=quality))


@pytest.mark.parametrize('key', ['cents', 'level_db', 'pan', 'delay_ms', 'feedback'])
def test_parallel_arrays(key):
    with pytest.raises(ParamError):
        P.validate_params('harmonizer', {key: [0, 0]})


def test_harmonizer_explicit_defaults():
    x = H.white_noise(-12, sr=16000, seconds=.1, channels=2)
    a = direct('harmonizer', x)
    b = direct('harmonizer', x, dict(cents=[0], level_db=[-6], pan=[0], delay_ms=[0], feedback=[0]))
    assert H.null(a, b)['bit_identical']


def test_micro_frequency_ripple_delay_and_mono_record():
    sr = 48000
    x = H.sine(1000, -12, sr=sr, seconds=7, channels=2)
    y, _, stats = MP.micro_pitch(x, sr, P.validate_params('micro_pitch', dict(mix=1)))
    for channel, detune in enumerate((-9, 9)):
        error = cents(y[sr//4:-sr//4, channel], sr, 1000*2**(detune/1200))
        am = ripple(y[:, channel:channel+1], sr)
        print('micro', channel, 'cents', error, 'ripple_db', am)
        assert abs(error) <= .5 and am <= .5
    assert 'mono' in stats and 'mono_worst_third_octave_db' in stats
    print('micro_mono', stats['mono'])
    z = direct('micro_pitch', x, dict(left_cents=0, right_cents=0, mix=1), sr)
    expected = np.zeros_like(x)
    expected[480:, 0] = x[:-480, 0]
    expected[720:, 1] = x[:-720, 1]
    assert H.null(z, expected)['peak_dbfs'] <= -80
    assert H.null(x, direct('micro_pitch', x, dict(mix=0), sr))['bit_identical']


def test_micro_noncommensurate_tone():
    x = H.sine(440, -12, sr=48000, seconds=7, channels=2)
    y = direct('micro_pitch', x, dict(mix=1), 48000)
    am = ripple(y[:, :1], 48000)
    print('micro_440_ripple_db', am)
    assert am <= .5


@pytest.mark.parametrize('kind', KINDS)
def test_common_tests(enabled, kind):
    neutral = {'pitch_shift': dict(semitones=0), 'pitch_curve': dict(bend=[]),
               'harmonizer': dict(level_db=[-60], dry_db=0), 'micro_pitch': dict(mix=0)}[kind]
    params = {'pitch_shift': dict(semitones=7, quality='high'),
              'pitch_curve': dict(bend=[[0, 7]]),
              'harmonizer': dict(semitones=[7], dry_db=-90), 'micro_pitch': dict(mix=0)}[kind]
    def probe(x, y, sr, p):
        if kind == 'micro_pitch':
            z = direct(kind, x, dict(mix=1), sr)
            errors = [float(cents(z[len(z)//3:2*len(z)//3, c], sr, 1000*2**(v/1200)))
                      for c, v in enumerate((-9, 9))]
        else:
            errors = [float(cents(y[len(y)//3:2*len(y)//3], sr, 1000*2**(7/12)))]
        return {'passed': max(np.abs(errors)) <= (1 if kind == 'micro_pitch' else 10), 'cents': errors}
    H.assert_common_tests(kind, params=params, neutral=neutral, seconds=.6, sr_probe=probe,
        latency_params=neutral)


# Independent specification table: min/max/default, not derived from SPECS.
NUMERIC = {
 'pitch_shift': {'semitones': (-24,24,0), 'cents':(-100,100,0),
    'formant_cents':(-1200,1200,0), 'transients':(0,1,.7), 'mix':(0,1,1)},
 'pitch_curve': {'glide_ms':(0,500,0), 'grain_ms':(10,200,40), 'harmony_db':(-90,6,-90)},
 'harmonizer': {'semitones':(-24,24,[7]), 'cents':(-100,100,[]), 'level_db':(-60,6,[]),
    'pan':(-1,1,[]), 'delay_ms':(0,1000,[]), 'feedback':(0,.9,[]),
    'grain_ms':(10,200,40), 'dry_db':(-90,6,0)},
 'micro_pitch': {'left_cents':(-50,50,-9), 'right_cents':(-50,50,9),
    'left_delay_ms':(0,100,10), 'right_delay_ms':(0,100,15), 'grain_ms':(10,80,30),
    'feedback':(0,.5,0), 'highcut_hz':(0,20000,0), 'mix':(0,1,.3)}}

OTHER_DEFAULTS = {
 'pitch_shift': dict(quality='high', formant=False, window=4096, stereo_link=True),
 'pitch_curve': dict(bend=[], interp='linear', quality='fast', formant=False),
 'harmonizer': dict(quality='fast', formant=False),
 'micro_pitch': dict(input='mono_sum')}


@pytest.mark.parametrize('kind', KINDS)
def test_parameter_defaults_and_bounds(enabled, kind):
    definition = P.describe(kind)
    specs = {s['id']: s for s in definition['params']}
    assert definition['backends'] == ['reference']
    assert definition['master_slot'] is None and definition['stages'] == ['track', 'bus']
    assert definition['offline_only'] is False
    x = H.sine(440, -12, sr=8000, seconds=.025, channels=2)
    base = P.validate_params(kind, {})
    assert set(base) == set(NUMERIC[kind]) | set(OTHER_DEFAULTS[kind])
    for key, value in OTHER_DEFAULTS[kind].items():
        assert base[key] == value
    assert H.null(direct(kind, x, sr=8000), direct(kind, x, base, 8000))['bit_identical']
    active = {'pitch_shift': dict(semitones=5, formant=True),
              'pitch_curve': dict(bend=[[0, 5]], interp='step'),
              'harmonizer': {}, 'micro_pitch': {}}[kind]
    for key, (lo, hi, default) in NUMERIC[kind].items():
        s = specs[key]
        assert (s['min'], s['max'], s['default']) == (lo, hi, default)
        for value in (lo, hi):
            p = {**active, key: [value] if s['type'] == 'float_array' else value}
            y = render(kind, x, p, 8000)
            assert np.isfinite(y).all()
        for value in (lo-1, hi+1):
            with pytest.raises(ParamError):
                P.validate_params(kind, {key: [value] if s['type'] == 'float_array' else value})
    for s in specs.values():
        if s['type'] in ('enum', 'bool'):
            for v in s.get('choices', [False, True]):
                assert np.isfinite(render(kind, x, {**active, s['id']: v}, 8000)).all()
    with pytest.raises(ParamError):
        P.validate_params(kind, {'unknown': 1})


@pytest.mark.parametrize('kind', KINDS)
def test_public_acceptance_status(kind):
    if kind == 'pitch_shift':
        assert P.describe(kind)['implemented'] is False
        with pytest.raises(ChainError):
            render(kind, np.zeros((32, 1)))
    else:
        assert P.describe(kind)['implemented'] is True
        assert np.isfinite(render(kind, np.zeros((32, 1)))).all()


@pytest.mark.parametrize('kind', ['micro_pitch', 'harmonizer'])
def test_feedback_maximum_decays(kind):
    sr = 2000
    x = np.zeros((sr*61, 2))
    x[:sr] = np.random.Generator(np.random.PCG64(19)).choice([-1., 1.], (sr, 2))
    if kind == 'micro_pitch':
        p = dict(feedback=.5, mix=1, left_delay_ms=100, right_delay_ms=100, grain_ms=80)
    else:
        p = dict(semitones=[7], feedback=[.9], delay_ms=[250], grain_ms=40, dry_db=-90)
    y = direct(kind, x, p, sr)
    tail = H.peak_dbfs(y[-sr:])
    print('CT8_feedback', kind, 'tail_dbfs', tail, 'peak_dbfs', H.peak_dbfs(y))
    assert np.isfinite(y).all()
    assert tail < -120


def test_unsafe_feedback_time_combination_refused():
    with pytest.raises(ParamError, match='CT-8'):
        P.validate_params('harmonizer', dict(feedback=[.9], delay_ms=[1000], grain_ms=200))


def test_four_active_voices():
    x = H.sine(440, -12, sr=8000, seconds=.2, channels=2)
    y = direct('harmonizer', x, dict(semitones=[-24, -12, 12, 24], cents=[-100, 0, 0, 100],
        pan=[-1, 0, .5, 1], level_db=[-6, -12, -12, -6], delay_ms=[0, 5, 10, 15]), 8000)
    assert y.shape == x.shape and np.isfinite(y).all()


def test_bb_invalid_and_short_inputs():
    for frames in (0, 1, 7):
        x = np.zeros((frames, 2))
        for q in QUALITY:
            y = B.shift(x, 16000, 5, quality=q)
            assert y.shape == x.shape and np.isfinite(y).all()
    x = np.zeros((32, 1))
    for value in (0, -1, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            B.fast_shift(x, 16000, value)
        for fn in (B.wsola, B.phase_vocoder):
            with pytest.raises(ValueError):
                fn(x, 16000, value)
    with pytest.raises(ValueError):
        B.wsola(x, 16000, 1, source_positions=[1, 0])
    with pytest.raises(ValueError):
        B.shift(x, 16000, 5, quality='unknown')


def test_bend_curve_contract(enabled):
    assert P.validate_params('pitch_curve', {'bend': []})['bend'] == []
    for bend in ([[0, 25]], [[0, -25]], [[1, 0], [0, 0]], [[0, 0], [0, 1]],
                 [[float('nan'), 0]], [[i, 0] for i in range(4097)]):
        with pytest.raises(ParamError):
            P.validate_params('pitch_curve', {'bend': bend})
    assert PC.TIME_VARYING == {'pitch_curve'}


def test_latency_declarations_and_nonzero_measurements():
    for sr in (44100, 48000, 96000):
        assert B.latency_samples(sr, 'fast') == 0
        assert B.latency_samples(sr, 'standard') == round(sr*.04)
        for window in (1024, 2048, 4096, 8192):
            assert B.latency_samples(sr, 'high', window) == round(window*sr/48000)
    x = H.impulse(at_s=.1, sr=16000, seconds=.5, channels=1)
    for quality in ('standard', 'high'):
        params = P.validate_params('pitch_shift', dict(semitones=5, quality=quality))
        y = PS.pitch_shift(x, 16000, params)[0]
        raw = PS.raw_pitch_shift(x, 16000, params)[0]
        declared = B.latency_samples(16000, quality)
        assert H.latency(raw)-1600 == declared
        assert np.array_equal(raw[declared:], y[:-declared])
        delay = H.latency(y)-1600
        print('nonneutral_impulse', quality, 'offset_samples', delay)
        assert delay == 0
