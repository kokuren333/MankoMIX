"""W3l: independent acceptance measurements for shimmer and pitch delay."""
import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import processors as P, engine as E
from mankomix.dsp.errors import ParamError
from mankomix.dspx.procs import pitch_delay as D, reverb_shimmer as S
from mankomix.dspx.bb.pitchtime_stream import FastShift
from mankomix.dspx.bb.shiftloop import LoopShift
from mankomix.dspx.bb.shimmer import ShimmerFDN, hall_params
from tests import toolimpl_harness as H

KINDS = ('pitch_delay', 'reverb_shimmer')
MODULES = dict(zip(KINDS, (D, S)))


def direct(kind, x, params=None, sr=16000, seed=19):
    p = P.validate_params(kind, params or {})
    return MODULES[kind].IMPLS[kind](x, sr, p, seed=seed)


def burst(sr, seconds=4., hz=440, length=.2):
    x = np.zeros((round(sr*seconds), 1))
    n = round(length*sr)
    x[:n, 0] = .25*np.sin(2*np.pi*hz*np.arange(n)/sr)*signal.windows.tukey(n, .15)
    return x


def freq(x, sr, target):
    return H.fundamental_frequency(x, sr, low_hz=max(10, target*.85), high_hz=min(.49*sr, target*1.15))


def tone_level(x, sr, hz):
    t = np.arange(len(x))/sr
    basis = np.column_stack((np.sin(2*np.pi*hz*t), np.cos(2*np.pi*hz*t), np.ones(len(x))))
    coef = np.linalg.lstsq(basis, np.mean(x, axis=1), rcond=None)[0]
    return float(np.hypot(*coef[:2]))


@pytest.mark.parametrize('ratio,reverse', [(1, False), (2, False), (.5, False), (4, False), (2, True)])
def test_bb11_state_survives_arbitrary_blocks(ratio, reverse):
    x = H.sine(440, -12, sr=16000, seconds=.24, channels=2)
    whole = FastShift(16000, 2, ratio, 80, reverse).process(x)
    for size in (64, 1024):
        proc = FastShift(16000, 2, ratio, 80, reverse)
        actual = np.concatenate([proc.process(x[a:a+size]) for a in range(0, len(x), size)])
        assert H.null(whole, actual)['bit_identical']
    assert np.max(np.abs(whole)) <= np.max(np.abs(x))+1e-14
    if ratio == 1 and not reverse:
        assert H.null(x, whole)['bit_identical']


def test_fast_orthogonal_route_and_default_delayline_contract():
    from mankomix.dspx.bb.shimmer import hadamard_route, _normalization
    from mankomix.dspx.bb.delayline import DelayLine
    from mankomix.dspx.bb.reverb import orthogonal_matrix, render_ir
    x = H.white_noise(-12, sr=2000, seconds=.12, channels=16)
    matrix = orthogonal_matrix(16)
    expected = x @ matrix.T
    assert np.max(np.abs(expected-hadamard_route(x))) < 1e-14
    legacy = DelayLine(32, 16, 'integer').process(x, 32, .6, matrix=matrix)
    routed = DelayLine(32, 16, 'integer').process(x, 32, .6, route=hadamard_route)
    assert H.null(legacy, routed)['peak_dbfs'] <= -120
    for size in (64, 1024):
        line = DelayLine(32, 16, 'integer')
        actual = np.concatenate([line.process(x[a:a+size], 32, .6, route=hadamard_route)
                                 for a in range(0, len(x), size)])
        assert H.null(routed, actual)['bit_identical']
    with pytest.raises(ValueError, match='preserve shape'):
        DelayLine(32, 16).process(x, 32, .5, route=lambda block: block[:, :1])
    p = P.validate_params('reverb_shimmer', dict(rt60_s=.5))
    _, late, early = render_ir(2000, hall_params(p), seed=19, return_scales=True, absorption_order=4)
    actual = _normalization(2000, .5, p['diffusion'], p['damping_hz'], p['seed'], 19)
    assert np.allclose(actual, (late, early), rtol=1e-12, atol=1e-12)


@pytest.mark.parametrize('mode', ['pitch', 'freq'])
def test_delay_repetition_frequencies(mode):
    sr = 16000
    x = burst(sr)
    y, _, stats = direct('pitch_delay', x, dict(mode=mode, time_ms=600, feedback=.6, mix=1), sr)
    values = []
    for n in (1, 2, 3):
        target = 440*2**n if mode == 'pitch' else 440+50*n
        segment = y[round((n*.6+.07)*sr):round((n*.6+.19)*sr)]
        measured = freq(segment, sr, target)
        error = 1200*np.log2(measured/target) if mode == 'pitch' else measured-target
        values.append((n, measured, error))
        assert abs(error) <= (15 if mode == 'pitch' else 1)
    print('DT repetitions', mode, values)
    assert stats['shifter_gain_bound'] <= 1 and 'haas' in stats


@pytest.mark.parametrize('mode', ['pitch', 'freq'])
def test_shift_outside_loop_is_once(mode):
    sr = 16000
    x = burst(sr)
    y = direct('pitch_delay', x, dict(mode=mode, time_ms=600, feedback=.6, mix=1, shift_in_loop=False), sr)[0]
    target = 880 if mode == 'pitch' else 490
    measurements = []
    for n in (1, 2, 3):
        f = freq(y[round((n*.6+.07)*sr):round((n*.6+.19)*sr)], sr, target)
        measurements.append(f)
        assert abs(1200*np.log2(f/target)) <= 15 if mode == 'pitch' else abs(f-target) <= 1
    print('DT shift once', mode, measurements)


@pytest.mark.parametrize('mode', ['pitch', 'freq'])
@pytest.mark.parametrize('delay', [25., 25.125])
def test_zero_shift_simple_delay_null_and_decay(mode, delay):
    from mankomix.dspx.bb.delayfx import feedback_audio
    x = H.white_noise(-12, sr=8000, seconds=.7, channels=2)
    p = dict(mode=mode, time_ms=delay, feedback=.6, mix=1, shift_semitones=0, shift_cents=0, shift_hz=0)
    y = direct('pitch_delay', x, p, 8000)[0]
    ref = feedback_audio(x, delay*8, .6, method='sinc8')
    null = H.null(ref, y)
    print('DT zero null', mode, delay, null)
    assert null['peak_dbfs'] <= (-60 if mode == 'pitch' else -80)
    pulse = H.impulse(sr=8000, seconds=.8)
    y = direct('pitch_delay', pulse, dict(p, time_ms=25.), 8000)[0]
    peaks = np.flatnonzero(np.abs(y[:, 0]) > 1e-8)
    assert np.array_equal(peaks[:8], 200*np.arange(1, 9))
    attenuation = 20*np.log10(np.abs(y[peaks[1:8], 0]/y[peaks[:7], 0]))
    assert np.max(np.abs(attenuation-20*np.log10(.6))) <= .2


@pytest.mark.parametrize('hz', [100, 200, 440, 1000, 3000, 6000, 10000])
@pytest.mark.parametrize('shift', [-50, 50])
def test_frequency_sideband_suppression(hz, shift):
    sr = 48000
    x = H.sine(hz, -12, sr=sr, seconds=.6)
    y = direct('pitch_delay', x, dict(mode='freq', shift_hz=shift, feedback=0, time_ms=10, mix=1), sr)[0]
    segment = y[round(.2*sr):round(.5*sr)]
    wanted = tone_level(segment, sr, hz+shift)
    image = tone_level(segment, sr, hz-shift)
    rejection = 20*np.log10(wanted/max(image, 1e-30))
    print('SSB', hz, shift, rejection)
    assert rejection >= 40
    assert abs(freq(segment, sr, hz+shift)-(hz+shift)) <= 1


@pytest.mark.parametrize('mode', ['pitch', 'freq'])
def test_upward_antialias_before_nyquist(mode):
    sr = 48000
    hz = 15000 if mode == 'pitch' else 23000
    x = H.sine(hz, -6, sr=sr, seconds=.6)
    p = dict(mode=mode, shift_hz=2000, feedback=0, time_ms=10, mix=1)
    y = direct('pitch_delay', x, p, sr)[0]
    suppression = H.rms_dbfs(y[12000:-4000])-H.rms_dbfs(x[12000:-4000])
    print('antialias', mode, suppression)
    assert suppression <= -60


@pytest.mark.parametrize('mode', ['pitch', 'freq'])
def test_highcut_kills_repeated_upward_shifts(mode):
    sr = 16000
    x = burst(sr, seconds=3.)
    p = dict(mode=mode, shift_hz=1000, time_ms=500, feedback=.8, highcut_hz=3000, mix=1)
    y = direct('pitch_delay', x, p, sr)[0]
    # At traversal three, 3520 Hz / 3440 Hz already exceeds the safety edge.
    reference = H.rms(x[:3200])
    measured = H.rms(y[round(1.6*sr):round(1.7*sr)])
    rejection = 20*np.log10(max(measured, 1e-30)/reference)
    print('highcut repeated', mode, rejection)
    assert rejection <= -60


def test_reverse_grains_reverse_asymmetric_envelope():
    sr = 8000
    x = H.white_noise(-12, sr=sr, seconds=.8)
    normal = FastShift(sr, 1, 1, 80).process(x)
    reverse = FastShift(sr, 1, 1, 80, True).process(x)
    assert not np.array_equal(normal, reverse)
    # During a single-tap segment the read velocity is -1, independently
    # confirmed by an increasing ramp becoming a decreasing output ramp.
    ramp = np.arange(4000, dtype=float)[:, None]/4000
    y = FastShift(sr, 1, 1, 80, True).process(ramp)
    assert np.all(np.diff(y[130:150, 0]) < 0)


def test_shimmer_zero_matches_hall_kernel():
    from mankomix.dspx.bb.reverb import process_reverb
    sr = 8000
    x = H.white_noise(-12, sr=sr, seconds=.4, channels=2)
    p = P.validate_params('reverb_shimmer', dict(rt60_s=.5, shimmer=0, mix=1, mod_depth=.2))
    actual = S.reverb_shimmer(x, sr, p, seed=19)[0]
    expected = process_reverb(x, sr, hall_params(p), seed=19, execution='tv', absorption_order=4, mod_interpolation='lagrange3')[0]
    null = H.null(expected, actual)
    print('shimmer zero hall null', null)
    assert null['peak_dbfs'] <= -100


def test_shimmer_octave_grows_with_time_and_amount():
    sr = 8000
    x = burst(sr, seconds=2., length=.15)
    values = []
    for amount in (.15, .35, .65, 1.):
        y, _, stats = direct('reverb_shimmer', x, dict(rt60_s=2., shimmer=amount, mod_depth=0, mix=1,
                                                        lowcut_hz=20, highcut_hz=3500, damping_hz=3500), sr)
        row = []
        for start, end in ((.2, .35), (.55, .75)):
            segment = y[round(start*sr):round(end*sr)]
            # Narrow-band energy, independently measured around each octave.
            a = H.band_level(segment, sr, 420, 460)['rms']
            b = H.band_level(segment, sr, 860, 900)['rms']
            row.append(20*np.log10(max(b, 1e-30)/max(a, 1e-30)))
        values.append(row)
        assert row[1] > row[0]
        assert stats['measurement_shift_enabled'] and stats['feedback_cap'] <= .98
    print('shimmer octave ratios dB', values)
    assert np.all(np.diff(np.array(values), axis=0) > 0)


@pytest.mark.parametrize('semitones', [-12, 7, 12, 24])
def test_shimmer_bb11_shift_precision(semitones):
    sr = 16000
    x = H.sine(440, -12, sr=sr, seconds=.7)
    y = LoopShift(sr, 1, semitones=semitones, grain_ms=80).process(x)
    target = 440*2**(semitones/12)
    measured = freq(y[4000:9000], sr, target)
    error = 1200*np.log2(measured/target)
    print('shimmer shifter cents', semitones, error)
    assert abs(error) <= 10


@pytest.mark.parametrize('kind', KINDS)
def test_common_tests(kind):
    params = (dict(rt60_s=.5, shimmer=0) if kind == 'reverb_shimmer'
              else dict(time_ms=25, feedback=.5, shift_semitones=12))
    def probe(x, y, sr, p):
        # An independent active measurement at the tested physical sample rate.
        if kind == 'pitch_delay':
            q = dict(p, feedback=0, time_ms=10, mix=1, shift_semitones=12)
            out = direct(kind, H.sine(1000, -20, sr=sr, seconds=.3), q, sr)[0]
            f = freq(out[round(.1*sr):round(.25*sr)], sr, 2000)
            return dict(passed=abs(1200*np.log2(f/2000)) <= 15, measured_hz=f)
        # BB-10 delay geometry and physical units scale with sr.
        p0 = P.validate_params(kind, dict(rt60_s=.5, shimmer=0, mix=1, predelay_ms=20, mod_depth=0))
        impulse = H.impulse(sr=sr, seconds=.1, channels=2)
        wet = direct(kind, impulse, p0, sr)[0]
        first = np.flatnonzero(np.max(np.abs(wet), axis=1) > 1e-12)[0]
        return dict(passed=first >= round(.02*sr) and first <= round(.03*sr), first_sample=int(first))
    result = H.assert_common_tests(kind, params=params, neutral={'mix': 0},
                                   latency_params={'mix': 0}, seconds=.08, feedback=False,
                                   sr_probe=probe, srs=(8000,))
    print('CT', kind, {k: v['passed'] for k, v in result.items()})


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('channels', [1, 2])
def test_ct7_active_physical_sample_rates(sr, channels):
    from mankomix.dspx.bb.shimmer import _wet
    tone = H.sine(1000, -20, sr=sr, seconds=.25, channels=channels)
    y = direct('pitch_delay', tone, dict(feedback=0, time_ms=10, mix=1), sr)[0]
    frequency = freq(y[round(.1*sr):round(.2*sr)], sr, 2000)
    assert abs(1200*np.log2(frequency/2000)) <= 15
    pulse = H.impulse(sr=sr, seconds=.08, channels=2)
    p = P.validate_params('reverb_shimmer', dict(rt60_s=.5, shimmer=.5, mod_depth=0, mix=1))
    wet, cap = _wet(pulse, sr, p, 19, 1., 1.)
    if channels == 1:
        wet = wet.mean(axis=1, keepdims=True)
    first = np.flatnonzero(np.max(np.abs(wet), axis=1) > 1e-12)[0]
    expected = round(.02*sr)+round(25/343*.08*sr)
    assert first == expected and cap <= .98 and wet.shape[1] == channels
    print('CT7', sr, channels, 'pitch_hz', frequency, 'RV onset', first)


@pytest.mark.parametrize('mode', ['pitch', 'freq'])
def test_ct8_delay_60_second_decay(mode):
    sr = 2000
    x = np.zeros((61*sr, 2))
    x[:sr] = np.where(H.white_noise(0, sr=sr, seconds=1, channels=2) >= 0, 1., -1.)
    y = direct('pitch_delay', x, dict(mode=mode, time_ms=100, feedback=.8 if mode == 'pitch' else .95,
                                    grain_ms=500, mix=1), sr)[0]
    peak = H.peak_dbfs(y[-sr:])
    print('CT8 delay', mode, peak, 'peak', H.peak_dbfs(y))
    assert np.isfinite(y).all() and peak < -120


def test_ct8_shimmer_all_maximum_60_seconds_then_decay():
    sr = 2000
    p = dict(rt60_s=30, predelay_ms=250, mix=1, lowcut_hz=20, highcut_hz=20000,
             shift_semitones=24, shimmer=1, grain_ms=200, diffusion=1, damping_hz=20000, mod_depth=1)
    # Full-scale excitation for a full minute, followed by a full minute of
    # silence in the same state. Lowcut=20 retains more energy than max=2000.
    x = np.zeros((120*sr, 2))
    x[:60*sr] = np.where(H.white_noise(0, sr=sr, seconds=60, channels=2) >= 0, 1., -1.)
    y, _, stats = direct('reverb_shimmer', x, p, sr)
    peak = H.peak_dbfs(y[-sr:])
    print('CT8 shimmer max', peak, 'peak', H.peak_dbfs(y), 'cap', stats['feedback_cap'])
    assert np.isfinite(y).all() and peak < -120


@pytest.mark.parametrize('kind', KINDS)
def test_defaults_ranges_and_active_endpoints(kind):
    expected = dict(mix=(0, 1, .2), bpm=(0, 400, 0), seed=(0, 65535, 0),
                    duck_db=(0, 24, 0), duck_threshold_db=(-80, 0, -40),
                    duck_attack_ms=(.1, 200, 10), duck_release_ms=(5, 3000, 250))
    if kind == 'pitch_delay':
        expected.update(time_ms=(.1, 4000, 250), feedback=(0, .95, .3),
                        lowcut_hz=(0, 2000, 0), highcut_hz=(0, 24000, 0),
                        shift_semitones=(-24, 24, 12), shift_cents=(-100, 100, 0),
                        shift_hz=(-2000, 2000, 50), grain_ms=(10, 500, 100))
    else:
        expected.update(rt60_s=(.5, 30, 6), predelay_ms=(0, 250, 20), lowcut_hz=(20, 2000, 300),
                        highcut_hz=(1000, 20000, 8000), shift_semitones=(-12, 24, 12),
                        shimmer=(0, 1, .5), grain_ms=(20, 200, 80), diffusion=(0, 1, .8),
                        damping_hz=(1000, 20000, 7000), mod_depth=(0, 1, .2))
    spec = P.describe(kind)
    actual = {s['id']: (s['min'], s['max'], s['default']) for s in spec['params'] if s['type'] in ('float', 'int')}
    assert actual == expected
    assert spec['stages'] == ['track', 'bus'] and spec['master_slot'] is None
    assert spec['realtime'] == dict(block_ok=False, allocates=True, latency_samples=0)
    assert spec['backends'] == ['reference'] and not spec['offline_only'] and not spec['channel_ok']
    sr = 4800
    x = H.sine(440, -12, sr=sr, seconds=.035, channels=2)
    base = dict(rt60_s=.5, mix=1) if kind == 'reverb_shimmer' else dict(time_ms=20, feedback=0, mix=1)
    def endpoint(options):
        if kind == 'pitch_delay':
            return direct(kind, x, options, sr)[0]
        # Exercise the actual TV wet kernel and RV/SD finish, without generating
        # a new two-input R-10 IR for every endpoint. R-10 is tested separately.
        from mankomix.dspx.bb.shimmer import _wet
        from mankomix.dspx.bb.reverb import finish, validate_rv
        p = P.validate_params(kind, options)
        validate_rv(p)
        wet, _ = _wet(x, sr, p, 19, 1., 1.)
        return finish(x, wet, sr, p, {})[0]
    # Restrict changes to the tested endpoint; no bypass is used for endpoints.
    for pid, (lo, hi, default) in expected.items():
        for value in (lo, hi):
            params = dict(base, **{pid: value})
            if pid == 'lowcut_hz' and value >= sr/2:
                continue
            y = endpoint(params)
            assert y.shape == x.shape and y.dtype == np.float64 and np.isfinite(y).all(), (pid, value)
    for s in spec['params']:
        values = s['choices'] if s['type'] == 'enum' else [False, True] if s['type'] == 'bool' else []
        for value in values:
            options = dict(base, **{s['id']: value})
            if s['id'] == 'note' and value != 'none':
                options['bpm'] = 120
                if value == '1/1d':
                    options['bpm'] = 240
            y = endpoint(options)
            assert np.isfinite(y).all()


def test_relationship_rejections():
    x = np.zeros((64, 1))
    for options in (dict(bpm=10), dict(note='1/4'), dict(note='1/1', bpm=20),
                    dict(time_ms=4000, feedback=.95), dict(time_ms=.1, feedback=.3)):
        with pytest.raises(ParamError):
            direct('pitch_delay', x, options, 16000)
    with pytest.raises(ParamError):
        direct('reverb_shimmer', x, dict(bpm=10), 16000)


def test_shimmer_seed_engine_id_and_decay():
    sr = 8000
    x = H.impulse(sr=sr, seconds=1.4, channels=2)
    p = dict(rt60_s=.5, shimmer=.4, mod_depth=0, mix=1)
    def render(seed, identifier, parameter_seed=0):
        chain = [dict(type='reverb_shimmer', id=identifier, params=dict(p, seed=parameter_seed))]
        return E.render_chain(x, sr, chain, stage='bus', seed=seed).audio
    a = render(5, 'a')
    assert H.null(a, render(5, 'a'))['bit_identical']
    assert not np.array_equal(a, render(6, 'a'))
    assert not np.array_equal(a, render(5, 'b'))
    assert not np.array_equal(a, render(5, 'a', 1))
    times = [H.rt60(render(seed, 'a'), sr, band_hz=1000) for seed in (5, 6)]
    print('RT4 shimmer seeds T20', times)
    assert abs(times[0]/times[1]-1) <= .05


@pytest.mark.parametrize('kind', KINDS)
def test_sd_wet_only(kind):
    sr = 8000
    x = H.sine(440, -6, sr=sr, seconds=.6, channels=2)
    p = dict(rt60_s=.5, mix=1, shimmer=.4) if kind == 'reverb_shimmer' else dict(time_ms=20, feedback=.3, mix=1)
    plain = direct(kind, x, p, sr)[0]
    disabled = direct(kind, x, dict(p, duck_db=0), sr)[0]
    ducked = direct(kind, x, dict(p, duck_db=12, duck_threshold_db=-40, duck_attack_ms=.1), sr)[0]
    assert H.null(plain, disabled)['bit_identical']
    attenuation = H.rms_dbfs(ducked[2000:])-H.rms_dbfs(plain[2000:])
    print('SD', kind, attenuation)
    assert abs(attenuation+12) <= 1


def test_normal_registration_matches_acceptance():
    # The final declaration is checked explicitly after all acceptance probes.
    assert P.describe('pitch_delay')['implemented']
    assert P.describe('reverb_shimmer')['implemented']


def test_active_default_measurement_and_context_excerpt():
    sr = 4800
    x = burst(sr, seconds=.35)
    x = np.repeat(x, 2, axis=1)
    for kind in KINDS:
        result = H.render(kind, x, sr, stage='bus', seed=7)
        y = result.audio
        excerpt = H.render_excerpt(kind, x, sr, 200, len(x), stage='bus', seed=7)
        assert H.null(y[200:], excerpt)['bit_identical']
        assert y.shape == x.shape and np.isfinite(y).all()
        if kind == 'reverb_shimmer':
            stats = direct(kind, x, sr=sr)[2]
            assert stats['measurement_modulation_stopped']
            assert stats['measurement_shift_enabled']
            assert stats['rt60_measured_s']['1000'] is not None
            print('default shimmer R10', stats)


def test_true_neutral_ct8_at_long_rt():
    sr = 2000
    x = np.zeros((61*sr, 1))
    x[:sr, 0] = np.sin(2*np.pi*440*np.arange(sr)/sr)
    y = direct('reverb_shimmer', x, dict(rt60_s=30, shimmer=0, mod_depth=0, lowcut_hz=20, mix=1), sr)[0]
    peak = H.peak_dbfs(y[-sr:])
    print('shimmer zero RT30 CT8', peak)
    assert peak < -120
