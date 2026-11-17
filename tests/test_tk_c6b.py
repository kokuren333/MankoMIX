"""C6b: normal contract wiring, BBD continuous limit and closure evidence."""
import json
import numpy as np
import pytest
from jsonschema import Draft202012Validator
from scipy import signal

from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain
from mankomix.dsp.errors import ParamError


ENDPOINTS = {'filter': (200, 8000), 'pan': (-1, 1), 'width': (0, 1),
             'drive': (0, 18), 'crush': (2000, 48000), 'time': (0, 1)}


def measure(label, **values):
    print(label+': '+json.dumps(values, sort_keys=True))


@pytest.mark.parametrize('target', ENDPOINTS)
def test_normal_engine_target_defaults_partial_endpoints_and_schema(target):
    from mankomix.dspx.procs.curve_shaper import TARGETS
    assert P.describe('curve_shaper')['implemented']
    raw = dict(target=target, note='none', amount=1)
    lo, hi = ENDPOINTS[target]
    resolved = P.validate_params('curve_shaper', raw)
    assert (resolved['lo'], resolved['hi']) == (lo, hi)
    assert raw == dict(target=target, note='none', amount=1)
    lower, upper = TARGETS[target][:2]
    assert P.validate_params('curve_shaper', dict(raw, lo=upper))['hi'] == hi
    assert P.validate_params('curve_shaper', dict(raw, hi=lower))['lo'] == lo
    x = np.random.Generator(np.random.PCG64(91)).normal(0, .01, (1000, 2))
    def render(params):
        return render_chain(x, 48000, [dict(type='curve_shaper', params=params)], stage='track').audio
    assert render(raw).tobytes() == render(dict(raw, lo=lo, hi=hi)).tobytes()
    validator = Draft202012Validator(P.graph_schema())
    validator.validate([dict(type='curve_shaper', params=raw)])
    validator.validate([dict(type='curve_shaper', params=resolved)])
    for key, value in (('lo', lower-1), ('hi', upper+1)):
        invalid = dict(raw, **{key: value})
        assert not validator.is_valid([dict(type='curve_shaper', params=invalid)])
        with pytest.raises(ParamError):
            P.validate_params('curve_shaper', invalid)
    measure('target_defaults', target=target, lo=resolved['lo'], hi=resolved['hi'])


def test_cross_validate_cannot_recover_omission_after_scalar_defaults():
    from mankomix.dspx.registry import cross_validators
    from mankomix.dspx.procs.curve_shaper import validate
    # W1f's validator remains the relationship checker. The legacy scalar
    # resolver has already lost the information needed for target defaults.
    raw = dict(target='crush', note='none')
    explicit = dict(raw, lo=200, hi=8000)
    assert P._validate_params_base('curve_shaper', raw) == P._validate_params_base('curve_shaper', explicit)
    assert cross_validators()['curve_shaper'] is validate
    assert P.validate_params('curve_shaper', explicit)['lo'] == 200
    assert P.validate_params('curve_shaper', explicit)['hi'] == 8000
    assert P.validate_params('curve_shaper', raw)['lo'] == 2000
    with pytest.raises(ParamError, match='selected target range'):
        P.validate_params('curve_shaper', dict(target='width', hi=3))


@pytest.mark.parametrize('target', [[], {}, 'unknown', 1, None])
def test_bad_target_still_raises_param_error(target):
    with pytest.raises(ParamError):
        P.validate_params('curve_shaper', dict(target=target))


def test_default_filter_schema_and_explicit_invalid_endpoints():
    validator = Draft202012Validator(P.graph_schema())
    for item in (dict(type='curve_shaper'), dict(type='curve_shaper', params={})):
        validator.validate([item])
    assert P.validate_params('curve_shaper', {})['lo'] == 200
    for p in (dict(lo=0, hi=1), dict(target='pan', lo=200, hi=8000)):
        assert not validator.is_valid([dict(type='curve_shaper', params=p)])
        with pytest.raises(ParamError):
            P.validate_params('curve_shaper', p)


def test_default_sync_clock_still_requires_explicit_tempo():
    x = np.random.Generator(np.random.PCG64(12)).normal(0, .1, (512, 2))
    for target in ENDPOINTS:
        for raw in (dict(target=target), dict(target=target, amount=1, mix=0)):
            with pytest.raises(ParamError, match='bpm'):
                render_chain(x, 48000, [dict(type='curve_shaper', params=raw)], stage='track')
            y = render_chain(x, 48000, [dict(type='curve_shaper', params=dict(raw, bpm=120))], stage='track').audio
            assert y.tobytes() == x.tobytes()
        # An active synchronized clock still requires an explicit tempo.
        with pytest.raises(ParamError, match='bpm'):
            render_chain(x, 48000, [dict(type='curve_shaper', params=dict(target=target, amount=1))], stage='track')
        y = render_chain(x, 48000, [dict(type='curve_shaper', params=dict(target=target, amount=1, bpm=120))], stage='track').audio
        assert np.isfinite(y).all()
    for source in (x, x[:, :1]):
        with pytest.raises(ParamError, match='bpm'):
            render_chain(source, 48000, [dict(type='curve_shaper')], stage='track')
        y = render_chain(source, 48000, [dict(type='curve_shaper', params=dict(bpm=120))], stage='track').audio
        assert y.tobytes() == source.tobytes()


def test_bbd_zero_limit_against_independent_continuous_state_space():
    from mankomix.dspx.procs.chorus import BBDVoice
    from mankomix.dspx.bb.bbd import envelope_compand
    sr = 8000
    x = np.zeros((256, 1)); x[20] = .1
    plan = BBDVoice(len(x), sr, 0)
    # scipy integrates a tenth-order continuous state-space impulse response;
    # it does not use the implementation's modal repeated-pole recurrence.
    b, a = signal.butter(5, 1, analog=True)
    rate = 2*np.pi*.18
    _, impulse = signal.impulse((np.polymul(b, b), np.polymul(a, a)),
                               T=np.arange(len(x))*rate)
    source = envelope_compand(x, sr)
    expected = signal.lfilter(impulse*rate, [1], source, axis=0)
    expected = envelope_compand(expected, sr, inverse=True)
    actual = plan.process(x)
    error = float(np.max(np.abs(actual-expected)))
    assert error < 1e-11
    assert np.array_equal(plan.process(np.zeros_like(x)), np.zeros_like(x))
    assert plan.process(np.empty((0, 1))).shape == (0, 1)
    measure('bbd_zero_limit', max_error=error, peak=float(np.max(np.abs(actual))))


def test_bbd_high_clock_transition_convergence_and_unchanged_event_path():
    from mankomix.dspx.procs.chorus import BBDVoice
    from mankomix.dspx.bb.bbd import bbd_audio
    sr = 8000
    x = (.1*np.sin(2*np.pi*731*np.arange(256)/sr))[:, None]
    for delay in (16, 32, 64):
        actual = BBDVoice(len(x), sr, delay).process(x)
        assert actual.tobytes() == bbd_audio(x, sr, delay, stages=1024).tobytes()
    exact_errors = []
    for delay in (.25, 1, 4, 8, 15.999):
        actual = BBDVoice(len(x), sr, delay).process(x)
        expected = bbd_audio(x, sr, delay, stages=1024)
        exact_errors.append(float(np.max(np.abs(actual-expected))))
    # A numerical diagnostic bound for the newly added asymptotic branch,
    # not a replacement for any spec acceptance number.
    assert max(exact_errors) < 1e-3
    zero = BBDVoice(len(x), sr, 0).process(x)
    errors = [float(np.max(np.abs(BBDVoice(len(x), sr, delay).process(x)-zero)))
              for delay in (.01, .001, .0001)]
    assert errors[2] < errors[1] < errors[0]
    assert errors[-1] < 2e-5
    boundary = [BBDVoice(len(x), sr, delay).process(x) for delay in (16-1e-7, 16, 16+1e-7)]
    assert max(np.max(np.abs(y-boundary[1])) for y in boundary) < 1e-7
    measure('bbd_high_clock', event_peak_errors=exact_errors, zero_peak_errors=errors)


@pytest.mark.parametrize('sr', [8000, 44100, 48000, 96000])
@pytest.mark.parametrize('feedback', [-.5, 0, .5])
def test_chorus_crosses_zero_with_feedback_and_replayed_history(sr, feedback):
    from mankomix.dspx.bb.delayfx import render_with_history
    kind = 'chorus'
    p = P.validate_params(kind, dict(model='bbd', delay_ms=2, depth_ms=10,
        depth=1, phase=.74, stereo_phase=.25, voices=1, mix=1, feedback=feedback))
    x = np.random.Generator(np.random.PCG64(13)).choice([-.1, .1], (round(.025*sr), 2))
    from mankomix.dspx.procs.chorus import voice_motion, chorus
    delays = voice_motion(len(x), sr, p)
    assert np.any(delays == 0) and np.any(delays > 0)
    # Chorus remains private because of the separate contradictory RMS spec.
    y, _, _ = chorus(x, sr, p)
    repeat, _, _ = chorus(x, sr, p)
    assert y.tobytes() == repeat.tobytes()
    assert np.isfinite(y).all() and np.max(np.abs(y)) < 10
    cut = len(x)//2
    excerpt, _, _ = render_with_history(chorus, x[cut:], sr, p, history=x[:cut])
    assert excerpt.tobytes() == y[cut:].tobytes()
    silence, _, _ = chorus(np.zeros_like(x), sr, p)
    assert not np.any(silence)


def test_bbd_filter_dispersion_evidence_without_changing_clock_or_threshold():
    from mankomix.dspx.bb.bbd import BBDPlan
    rows = []
    for ms in (5, 100, 300, 1200):
        sr = 8000; delay = round(ms*sr/1000)
        x = np.zeros((7*delay+400, 1)); x[0] = 1
        plan = BBDPlan(len(x), sr, delay, stages=1024)
        assert np.all(plan.clock == 1024/(2*ms/1000))
        peaks = []
        wet = x
        for _ in range(5):
            wet = plan.process(wet)
            peaks.append(int(np.argmax(np.abs(wet))))
        intervals = np.diff(peaks)
        rows.append(dict(time_ms=ms, expected_samples=delay, peaks=peaks,
                         intervals=intervals.tolist()))
    # A per-traversal scalar advance translates every interval equally. The
    # longest setting has >2 samples of dispersion, so no such advance can
    # put all intervals inside the unchanged +/-1 sample acceptance window.
    assert np.ptp(rows[-1]['intervals']) > 2
    measure('bbd_filter_dispersion', rows=rows)


@pytest.mark.parametrize('feedback', [-.5, .5])
def test_infinite_clock_limit_full_scale_sixty_second_tail(feedback):
    from mankomix.dspx.procs.chorus import BBDVoice
    from mankomix.dspx.bb.bbd import envelope_compand
    sr = 1000
    x = np.zeros((61*sr, 1))
    x[:sr, 0] = np.random.Generator(np.random.PCG64(15)).choice([-1., 1.], sr)
    source = envelope_compand(x, sr)
    plan = BBDVoice(len(x), sr, 0)
    wet = plan.process(source, compander=False)
    for _ in range(128):
        update = plan.process(source+feedback*wet, compander=False)
        delta = np.max(np.abs(update-wet))
        wet = update
        if delta < 128*np.finfo(np.float64).eps*max(1., np.max(np.abs(wet))):
            break
    else:
        pytest.fail('infinite-clock feedback did not converge')
    y = envelope_compand(wet, sr, inverse=True)
    tail = float(np.max(np.abs(y[-sr:])))
    assert np.isfinite(y).all() and tail < 1e-6
    measure('bbd_zero_limit_tail', feedback=feedback, peak=float(np.max(np.abs(y))), tail=tail)


def test_coherent_voice_rms_conflict_matches_closed_form():
    from mankomix.dspx.procs.chorus import chorus
    x = np.random.Generator(np.random.PCG64(4)).normal(0, .1, (16000, 2))
    outputs = []
    for voices in range(1, 5):
        p = P.validate_params('chorus', dict(voices=voices, depth=0, width=0, mix=1))
        outputs.append(chorus(x, 8000, p)[0])
    ratios = [float(np.sqrt(np.mean(y*y)/np.mean(outputs[0]**2))) for y in outputs]
    assert np.allclose(ratios, np.sqrt(np.arange(1, 5)), atol=1e-14)
    assert not P.describe('chorus')['implemented']
    assert not P.describe('bbd_delay')['implemented']
    measure('coherent_voice_conflict', gain_db=(20*np.log10(ratios)).tolist())
