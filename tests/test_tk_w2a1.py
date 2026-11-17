"""W2a1 acceptance, explicit unmet criteria, and measured harmonic vectors."""
import importlib
import json
import math
import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dsp.reference import nonlinear as original
from mankomix.dsp.reference.truepeak import true_peak_dbtp
from mankomix.core.measure.loudness import integrated
from mankomix.dspx.bb import nonlinear as N
from tests import toolimpl_harness as H

TYPES = ('exciter', 'loudness_shaper', 'fuzz', 'bitcrush', 'mb_saturator', 'mb_distortion')
ACTIVE = dict(exciter=dict(amount_db=-6, dynamic=0), loudness_shaper=dict(effect=1),
              fuzz=dict(drive_db=30, bias=0, gate=0, lowcut_hz=0, tone_hz=20000),
              bitcrush=dict(bits=8), mb_saturator=dict(drive_db=[12]*3),
              mb_distortion=dict(kind_2='tanh', drive_db=[0, 12, 0]))
NEUTRAL = dict(exciter=dict(amount_db=-60), loudness_shaper=dict(effect=0),
               fuzz=dict(drive_db=0), bitcrush=dict(bits=24, rate_hz=192000),
               mb_saturator=dict(drive_db=[]),
               mb_distortion=dict(kind_1='off', kind_2='off', kind_3='off', kind_4='off'))


@pytest.fixture(autouse=True)
def enable_candidates_only_during_acceptance(monkeypatch):
    # The public flag remains False until all acceptance criteria pass.
    # Exercise candidates through the real engine without exposing them to users.
    for kind in TYPES:
        monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)


def render(kind, x, p=None, sr=48000, seed=0, stage='track'):
    return E.render_chain(x, sr, [{'type': kind, 'params': p or {}}], stage=stage, seed=seed).audio


def tone(f=1000, db=-6, sr=48000, seconds=.6):
    return (10**(db/20)*np.sin(2*np.pi*f*np.arange(round(sr*seconds))/sr))[:, None]


def db(v):
    return float(20*np.log10(max(float(v), 1e-300)))


def amplitude(x, f, sr=48000):
    x = x[len(x)//3:2*len(x)//3, 0]
    return float(2*abs(np.dot(x, np.exp(-2j*np.pi*f*np.arange(len(x))/sr)))/len(x))


def harmonics(y, f=1000, sr=48000):
    amps = [amplitude(y, f*k, sr) for k in range(1, 8) if f*k < sr/2]
    return dict(thd_db=db(np.linalg.norm(amps[1:])/max(amps[0], 1e-300)),
                levels_db=[db(a/max(amps[0], 1e-300)) for a in amps[1:]])


def alias_db(y, f, sr=48000, reference_amplitude=None):
    y = y[len(y)//3:2*len(y)//3, 0]
    spectrum = abs(np.fft.rfft(y))/len(y)
    fund = spectrum[round(f*len(y)/sr)]
    if reference_amplitude is not None:
        fund = reference_amplitude/2
    for k in range(1, int((sr/2)//f)+1):
        i = round(k*f*len(y)/sr)
        spectrum[max(0, i-1):i+2] = 0
    spectrum[:2] = 0
    return db(np.linalg.norm(spectrum)/max(fund, 1e-300))


@pytest.mark.parametrize('factor', [1, 2, 4, 8])
def test_oversampler_is_exact_copy_and_alignment(factor):
    x = np.random.Generator(np.random.PCG64(3)).normal(size=(1003, 2))
    assert N.oversampled(x, factor, np.tanh).tobytes() == original._oversampled(x, factor, np.tanh).tobytes()
    pulse = np.zeros((2048, 1)); pulse[1024] = 1
    y = N.oversampled(pulse, factor, lambda u: u)
    assert np.argmax(abs(y[:, 0])) == 1024
    assert N.oversampling_info(factor)['uncompensated_latency_samples'] == (64 if factor > 1 else 0)
    if factor > 1:
        h = N._os_filter(factor)
        raw = signal.upfirdn(h, signal.upfirdn(h*factor, pulse, up=factor, axis=0), down=factor, axis=0)
        assert np.argmax(abs(raw[:, 0]))-1024 == 64
    assert N.oversampled(np.empty((0, 2)), factor, np.tanh).shape == (0, 2)


@pytest.mark.parametrize('curve,primitive', [(N.hard_clip, N.hard_clip_primitive),
    (np.tanh, N.tanh_primitive),
    (N.fold, N.fold_primitive), (np.abs, N.rectify_primitive),
    (N.loudness_curve, N.loudness_primitive)])
def test_adaa_integrals_and_block_invariance(curve, primitive):
    x = np.random.Generator(np.random.PCG64(4)).uniform(-5, 5, (2049, 2))
    derivative = (primitive(x+1e-6)-primitive(x-1e-6))/2e-6
    assert np.max(abs(derivative-curve(x))) < 1e-8
    full = N.adaa1(x, curve, primitive)
    for size in (1, 64, 1024):
        stream = N.ADAA1(curve, primitive)
        blocked = np.concatenate([stream.process(x[i:i+size]) for i in range(0, len(x), size)])
        assert full.tobytes() == blocked.tobytes()
    assert np.isfinite(N.adaa1(np.ones((32, 2)), curve, primitive)).all()


def test_compander_and_clock_filter():
    x = np.random.Generator(np.random.PCG64(7)).uniform(-2, 2, (1000, 2))
    np.testing.assert_allclose(N.compand(N.compand(x), inverse=True), x, atol=3e-15)
    clock = np.linspace(1000, 30000, len(x))
    full = N.clock_following_filter(x, 48000, clock)
    for size in (1, 64, 1024):
        filt = N.ClockFilter(48000)
        parts = [filt.process(x[i:i+size], clock[i:i+size]) for i in range(0, len(x), size)]
        assert np.concatenate(parts).tobytes() == full.tobytes()
    probe = tone(10000, -6, seconds=.3)
    low = N.clock_following_filter(probe, 48000, 2000)
    high = N.clock_following_filter(probe, 48000, 30000)
    assert np.linalg.norm(low) < np.linalg.norm(high)/10
    for invalid in (0, -1, np.nan):
        with pytest.raises(ParamError): N.clock_following_filter(x, 48000, invalid)


@pytest.mark.parametrize('kind', TYPES)
def test_neutral_and_registration(kind):
    spec = P.describe(kind)
    assert spec['backends'] == ['reference']
    assert spec['master_slot'] == (5 if kind == 'loudness_shaper' else None if kind in ('fuzz', 'bitcrush') else 3)
    x = np.random.Generator(np.random.PCG64(12)).normal(0, .1, (1000, 2))
    assert x.tobytes() == render(kind, x, NEUTRAL[kind]).tobytes()
    assert kind not in importlib.import_module('mankomix.dspx.registry').time_varying_types()


@pytest.mark.parametrize('kind', TYPES)
def test_common(kind):
    def probe(x, y, sr, p):
        f = H.fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
        return dict(frequency_hz=f, passed=abs(f-1000) <= 1)
    result = H.assert_common_tests(kind, params=ACTIVE[kind], neutral=NEUTRAL[kind],
                                   seconds=.06, sr_probe=probe, latency_params=NEUTRAL[kind])
    print('CT_RESULT', kind, json.dumps(dict(passed=[k for k,v in result.items() if v['passed']],
        ct2_mode=result['CT-2']['mode'],
        ct7_frequency_error_hz=max(abs(v['frequency_hz']-1000) for v in result['CT-7']['measurements']),
        ct5_offline_delays=sorted(set(v['offline_samples'] for v in result['CT-5']['measurements'])))))


@pytest.mark.parametrize('kind', TYPES)
def test_parameter_bounds_defaults_and_enums(kind):
    spec = P.describe(kind)
    assert P.validate_params(kind, {}) == {p['id']: p['default'] for p in spec['params']}
    x = tone(sr=96000, seconds=.01)
    for param in spec['params']:
        pid, typ = param['id'], param['type']
        values = param['choices'] if typ == 'enum' else [False, True] if typ == 'bool' else [param['min'], param['max']]
        for value in values:
            overrides = {**ACTIVE[kind], pid: value}
            if typ == 'float_array':
                count = len(P.validate_params(kind, {})['crossovers_hz'])+1
                overrides[pid] = [value]*count if pid != 'crossovers_hz' else [value]
                if pid == 'crossovers_hz':
                    overrides.update({p['id']: [] for p in spec['params'] if p['type'] == 'float_array' and p['id'] != pid})
            if pid.startswith('kind_') and int(pid[-1]) > 3 and value != 'off':
                with pytest.raises(ParamError): P.validate_params(kind, overrides)
                continue
            y = render(kind, x, overrides, sr=96000)
            assert y.shape == x.shape and np.isfinite(y).all(), (kind, pid, value)


def test_cross_validation_and_master_order():
    for kind, p in [('exciter', dict(out_lowcut_hz=100)),
                    ('mb_saturator', dict(drive_db=[2])),
                    ('mb_distortion', dict(crossovers_hz=[], kind_2='hard')),
                    ('mb_distortion', dict(crossovers_hz=[2000, 1000]))]:
        with pytest.raises(ParamError): P.validate_params(kind, p)
    E.validate_chain([{'type': 'loudness_shaper'}, {'type': 'limiter'}], stage='master')
    with pytest.raises(ChainError):
        E.validate_chain([{'type': 'limiter'}, {'type': 'loudness_shaper'}], stage='master')


@pytest.mark.parametrize('mode', ['tanh', 'asymmetric'])
def test_mb_saturator_singleband_original_null(mode):
    x = tone(db=-12, seconds=.2)
    p = dict(crossovers_hz=[], drive_db=[12], mix=[.5], level_db=[0], mode=mode)
    y = render('mb_saturator', x, p)
    z = original.saturator(x, 48000, P.validate_params('saturator', dict(drive_db=12, mode=mode, mix=.5)))[0]
    assert H.null(y, z)['rms_dbfs'] <= -120


@pytest.mark.parametrize('kind', ['mb_saturator', 'mb_distortion'])
@pytest.mark.parametrize('phase', ['linear', 'minimum'])
def test_mb_other_band_unchanged(kind, phase):
    p = dict(crossovers_hz=[1000], phase=phase, drive_db=[24, 0])
    if kind == 'mb_distortion': p.update(kind_1='hard')
    x = tone(6000, -12)
    y = render(kind, x, p)
    gain = db(amplitude(y, 6000)/amplitude(x, 6000))
    assert abs(gain) < .1
    assert harmonics(y, 6000)['thd_db'] < -100


@pytest.mark.parametrize('symmetry', ['even', 'odd'])
def test_exciter_symmetry_and_dynamic(symmetry):
    x = tone(4000, -12)
    p = dict(amount_db=0, harmonics=symmetry, dynamic=1)
    d = render('exciter', x, p)-x
    even, odd = amplitude(d, 8000), amplitude(d, 12000)
    assert db(even/odd) > 10 if symmetry == 'even' else db(odd/even) > 10
    quiet = x*.1
    dq = render('exciter', quiet, p)-quiet
    assert abs(db(np.linalg.norm(dq)/np.linalg.norm(quiet))-db(np.linalg.norm(d)/np.linalg.norm(x))) < 1.5


def test_fuzz_bias_gate_octave_dc():
    x = tone(1000, -10)
    base = dict(bias=0, gate=0, tone_hz=20000, lowcut_hz=0)
    symmetric = render('fuzz', x, base)
    asymmetric = render('fuzz', x, dict(base, bias=.5))
    assert db(amplitude(symmetric, 2000)/amplitude(symmetric, 1000)) < -60
    assert db(amplitude(asymmetric, 2000)/amplitude(asymmetric, 1000)) >= -30
    q = render('fuzz', tone(db=-50), dict(base, gate=1))
    assert H.rms_dbfs(q) < -90
    assert H.rms_dbfs(render('fuzz', x, dict(base, gate=1))) > -60
    octave = render('fuzz', x, dict(base, shape='octave'))
    assert amplitude(octave, 2000) > amplitude(octave, 1000)
    for wet in (symmetric, asymmetric, octave):
        assert db(abs(np.mean(wet))) <= -80
    assert np.array_equal(render('fuzz', np.zeros_like(x)), np.zeros_like(x))


@pytest.mark.parametrize('kind', ['tanh', 'hard', 'fold', 'rectify'])
def test_mb_kinds_symmetry_and_fold_bound(kind):
    y = render('mb_distortion', tone(db=-6), dict(crossovers_hz=[], kind_1=kind, drive_db=[24], tone_hz=[20000]))
    even = np.linalg.norm([amplitude(y, k*1000) for k in (2, 4, 6)])
    odd = np.linalg.norm([amplitude(y, k*1000) for k in (1, 3, 5, 7)])
    assert db(odd/even) < -60 if kind == 'rectify' else db(even/odd) < -60
    assert np.max(abs(N.fold(np.linspace(-100, 100, 10000)))) <= 1


def test_loudness_exact_curve_properties_and_loudness():
    x = np.sort(np.random.Generator(np.random.PCG64(1)).uniform(-1, 1, 100000))
    for c in (0, .5, 1):
        y = N.loudness_curve(x, 1, c)
        assert np.all(np.diff(y) >= 0) and np.max(abs(y)) <= 1
    x = H.pink_noise(-12, sr=48000, seconds=1, channels=2, seed=4)
    x *= 10**(-1/20)/np.max(abs(x))
    y = render('loudness_shaper', x, dict(effect=1))
    change = integrated(y, 48000)-integrated(x, 48000)
    print('LOUDNESS', json.dumps(dict(lu_change=change, input_peak=float(np.max(abs(x))),
        output_peak=float(np.max(abs(y))), true_peak_in=true_peak_dbtp(x), true_peak_out=true_peak_dbtp(y))))
    assert change >= 1


def test_bitcrush_grid_hold_antialias_random_and_excerpts():
    x = tone(1000, -1, seconds=.3)
    y = render('bitcrush', x, dict(bits=8))
    assert np.all(y*256 == np.rint(y*256))
    held = render('bitcrush', x, dict(rate_hz=12000))
    assert np.all(held.reshape(-1, 4) == held.reshape(-1, 4)[:, :1])
    high = tone(10000)
    raw = render('bitcrush', high, dict(rate_hz=12000))
    filtered = render('bitcrush', high, dict(rate_hz=12000, antialias=True))
    assert db(amplitude(raw, 2000)/amplitude(raw, 1000)) > 40
    assert db(amplitude(filtered, 2000)/amplitude(raw, 2000)) < -40
    from mankomix.dspx.procs.bitcrush import render_with_history
    p = P.validate_params('bitcrush', dict(bits=8, jitter=.5, dither=1, rate_hz=11025, hold='linear'))
    a = render('bitcrush', x, p, seed=7)
    assert a.tobytes() == render('bitcrush', x, p, seed=7).tobytes()
    assert a.tobytes() != render('bitcrush', x, p, seed=8).tobytes()
    # Engine seeds combine step IDs; direct replay tests use the same raw seed.
    full = render_with_history(x, 48000, p, seed=7)[0]
    for start in (511, 1001):
        part = render_with_history(x[start:], 48000, p, seed=7, history=x[:start])[0]
        assert full[start:].tobytes() == part.tobytes()
    assert not np.any(render('bitcrush', np.zeros_like(x), dict(bits=8)))
    assert np.all(render('bitcrush', np.zeros_like(x), dict(bits=8, quantizer='midrise')) == 1/256)


@pytest.mark.parametrize('kind', TYPES)
def test_record_five_point_harmonics_and_aliasing(kind):
    rows = []
    for drive in (0, 6, 12, 18, 24):
        p = dict(ACTIVE[kind])
        if kind in ('fuzz', 'exciter'): p['drive_db'] = drive
        elif kind.startswith('mb_'): p['drive_db'] = [drive]*3
        elif kind == 'loudness_shaper': p['effect'] = drive/24
        else: p['bits'] = 24-drive*23/24
        rows.append(dict(control=drive, **harmonics(render(kind, tone(), p))))
    aliases = {str(f): alias_db(render(kind, tone(f, seconds=1.5), ACTIVE[kind]), f) for f in (5000, 10000, 15000)}
    small = tone(db=-60)
    small_gain = db(amplitude(render(kind, small, ACTIVE[kind]), 1000)/amplitude(small, 1000))
    print('NT_VECTOR', json.dumps(dict(type=kind, harmonic_vector=rows, alias_dbc=aliases, small_signal_gain_db=small_gain)))
    assert len(rows) == 5 and all(np.isfinite(row['thd_db']) for row in rows)


def test_exciter_original_component_rejection():
    x = tone(4000, -6)
    delta = render('exciter', x, dict(amount_db=0))-x
    rejection = db(amplitude(delta, 4000)/max(amplitude(delta, 8000), amplitude(delta, 12000)))
    print('EXCITER_FUNDAMENTAL_DB', rejection)
    assert rejection <= -20


def test_exciter_one_octave_below():
    x = tone(1500, -6)
    delta = render('exciter', x, dict(amount_db=0))-x
    level = H.rms_dbfs(delta[len(delta)//3:2*len(delta)//3])
    print('EXCITER_BELOW_DBFS', level)
    assert level <= -80


@pytest.mark.xfail(strict=True, reason='T07-07 exact polynomial finite-amplitude gain differs from its derivative at zero.')
def test_loudness_minus20_gain():
    x = tone(db=-20)
    y = render('loudness_shaper', x, dict(effect=1, curve=.5))
    measured = db(amplitude(y, 1000)/amplitude(x, 1000))
    expected = 20*math.log10(1.75)
    print('LOUDNESS_MINUS20_DB', measured, 'EXPECTED', expected)
    assert abs(measured-expected) <= .05


@pytest.mark.xfail(strict=True, reason='T07-07 specified f(x)>x inside (0,1) increases the sample peak.')
def test_loudness_pink_sample_peak():
    x = H.pink_noise(-12, sr=48000, seconds=1, channels=2, seed=4)
    x *= 10**(-1/20)/np.max(abs(x))
    y = render('loudness_shaper', x, dict(effect=1))
    assert np.max(abs(y)) <= np.max(abs(x))


@pytest.mark.xfail(strict=True, reason='T07-07: both 19/20 kHz inputs remain in the same 2400 Hz high band.')
def test_loudness_band_split_difference_tone():
    x = tone(19000, -12)+tone(20000, -12)
    single = amplitude(render('loudness_shaper', x, dict(effect=1, band_split=False)), 1000)
    multi = amplitude(render('loudness_shaper', x, dict(effect=1, band_split=True)), 1000)
    difference = db(multi/single)
    print('LOUDNESS_SPLIT_DIFFERENCE_DB', difference)
    assert difference <= -10


def test_bitcrush_snr():
    # Full-scale, noncoherent with the quantizer grid; exact integer FFT cycles.
    x = tone(997, 0)
    y = render('bitcrush', x, dict(bits=8))
    snr = db(np.linalg.norm(x)/np.linalg.norm(y-x))
    print('BITCRUSH_SNR_DB', snr, 'EXPECTED', 6.02*8+1.76)
    assert abs(snr-(6.02*8+1.76)) <= 1


@pytest.mark.parametrize('kind,settings,limit', [
    ('exciter', dict(amount_db=-6), -80),
    ('loudness_shaper', dict(effect=1), -80),
    ('fuzz', {}, -60),
    pytest.param('mb_saturator', dict(drive_db=[12]*3), -80, marks=pytest.mark.xfail(strict=True, reason='NT2: original-compatible saturator/resampler exceeds -80 dBc.')),
    ('mb_distortion', dict(crossovers_hz=[], kind_1='hard', drive_db=[24]), -60),
    ('mb_distortion', dict(crossovers_hz=[], kind_1='fold', drive_db=[24]), -60)])
def test_nt2_active_alias_limit(kind, settings, limit):
    values = {f: alias_db(render(kind, tone(f, seconds=1.5), settings), f) for f in (5000, 10000, 15000)}
    print('NT2_ACCEPTANCE', kind, settings, values)
    assert max(values.values()) <= limit


@pytest.mark.parametrize('kind', ['exciter', 'fuzz', 'mb_saturator', 'mb_distortion'])
def test_nt4_small_signal(kind):
    x = tone(db=-60)
    y = render(kind, x, ACTIVE[kind])
    gain = db(amplitude(y, 1000)/amplitude(x, 1000))
    print('NT4_GAIN_DB', kind, gain)
    assert abs(gain) <= .05


@pytest.mark.parametrize('kind', ['fuzz', 'bitcrush', 'mb_saturator', 'mb_distortion'])
def test_nt6_aligned_mix(kind):
    x = tone(seconds=.1)
    wet = render(kind, x, ACTIVE[kind])
    p = dict(ACTIVE[kind])
    p['mix'] = [.5]*3 if kind.startswith('mb_') else .5
    y = render(kind, x, p)
    assert H.null(y, .5*x+.5*wet)['peak_dbfs'] <= -120


def test_spec_defaults_independently():
    expected = dict(
        exciter=dict(freq_hz=3000, amount_db=-60, harmonics='both', drive_db=12, dynamic=.5, out_lowcut_hz=0, oversample=4),
        loudness_shaper=dict(effect=0, curve=.5, input_db=0, clip=True, band_split=False, output_db=0, oversample=4),
        fuzz=dict(drive_db=30, output_db=0, auto_gain=False, mix=1, oversample=8, bias=.2, gate=.2,
                  shape='hard', tone_hz=3000, lowcut_hz=60, input_z=0),
        bitcrush=dict(bits=24, rate_hz=192000, antialias=False, hold='zoh', jitter=0, dither=0,
                      quantizer='midtread', mix=1, output_db=0, seed=0),
        mb_saturator=dict(crossovers_hz=[150, 2500], phase='linear', drive_db=[], level_db=[], mix=[], mode='tanh', oversample=4, output_db=0),
        mb_distortion=dict(crossovers_hz=[200, 2000], phase='linear', kind_1='off', kind_2='off', kind_3='off', kind_4='off',
                           drive_db=[], tone_hz=[], level_db=[], mix=[], oversample=8))
    for kind, defaults in expected.items():
        assert P.validate_params(kind, {}) == defaults


def test_public_implementation_flags():
    for kind in TYPES:
        module = importlib.import_module('mankomix.dspx.procs.'+kind)
        assert module.SPECS[0]['implemented'] is (kind in ('bitcrush', 'exciter', 'fuzz', 'mb_distortion'))


@pytest.mark.parametrize('kind', ['exciter', 'loudness_shaper',
    pytest.param('mb_saturator', marks=pytest.mark.xfail(strict=True,
        reason='NT5: matching original asymmetric saturator retains a finite-record startup DC residual.')),
    'mb_distortion'])
def test_output_dc(kind):
    p = dict(ACTIVE[kind])
    if kind == 'mb_saturator': p['mode'] = 'asymmetric'
    if kind == 'mb_distortion': p['kind_2'] = 'rectify'
    y = render(kind, tone(), p)
    dc = db(abs(np.mean(y)))
    print('NT5_DC_DBFS', kind, dc)
    assert dc <= -80


def test_fuzz_default_gate_small_signal():
    x = tone(db=-60)
    y = render('fuzz', x)
    gain = db(amplitude(y, 1000)/amplitude(x, 1000))
    print('FUZZ_DEFAULT_SMALL_SIGNAL_DB', gain)
    assert abs(gain) <= .05


@pytest.mark.parametrize('kind', ['tanh', 'rectify', 'fuzz', 'crush'])
def test_record_remaining_mb_kind_aliasing(kind):
    values = {f: alias_db(render('mb_distortion', tone(f, seconds=1.5), dict(crossovers_hz=[], kind_1=kind, drive_db=[24])), f,
                         reference_amplitude=10**(-6/20) if kind == 'rectify' else None)
              for f in (5000, 10000, 15000)}
    print('MB_KIND_ALIAS', kind, json.dumps(values))
    assert max(values.values()) <= -80


@pytest.mark.parametrize('drive', [0, 12, 24, 48])
def test_fold_audio_bound(drive):
    for level in (-20, -6, 0):
        y = render('mb_distortion', tone(1000, level, seconds=.15),
            dict(crossovers_hz=[], kind_1='fold', drive_db=[drive]))
        assert np.max(abs(y)) <= 1


@pytest.mark.parametrize('feature', ['jitter', 'dither'])
def test_each_random_feature_seed(feature):
    x = tone(seconds=.1)
    p = dict(bits=8, rate_hz=11025, **{feature: 1})
    a = render('bitcrush', x, p, seed=91)
    assert a.tobytes() == render('bitcrush', x, p, seed=91).tobytes()
    assert a.tobytes() != render('bitcrush', x, p, seed=92).tobytes()
    assert a.tobytes() != render('bitcrush', x, dict(p, seed=1), seed=91).tobytes()


def test_fuzz_fixed_auto_gain():
    x = tone(seconds=.1)
    p = dict(bias=0, gate=0, lowcut_hz=0, tone_hz=20000)
    a = render('fuzz', x, p)
    b = render('fuzz', x, dict(p, auto_gain=True, output_db=6))
    np.testing.assert_allclose(b, a*10**(-24/20), atol=1e-16)
    dry = render('fuzz', x, dict(p, mix=0, auto_gain=True, output_db=6))
    np.testing.assert_allclose(dry, x*10**(-24/20), atol=1e-16)


@pytest.mark.parametrize('kind', ['mb_saturator', 'mb_distortion'])
def test_generated_harmonics_leave_source_band(kind):
    p = dict(crossovers_hz=[1000], drive_db=[24, 0])
    if kind == 'mb_distortion': p['kind_1'] = 'tanh'
    x = tone(500, -6)
    y = render(kind, x, p)
    third = db(amplitude(y, 1500)/amplitude(y, 500))
    print('OUTSIDE_SOURCE_BAND_1500_DBC', kind, third)
    assert third > -40
