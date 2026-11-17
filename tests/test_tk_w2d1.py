"""U-06b acceptance and C3 closure of short feedback and weighted tape motion."""
import importlib
import hashlib
import json

import numpy as np
import pytest
from scipy import signal
from scipy.fft import rfft, rfftfreq

from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain, validate_chain
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb.curves import phase_positions
from mankomix.dspx.bb.modulation import mod_lfo, pitch_delay, pitch_latency, bandlimited_walk
from mankomix.dspx.bb.delayline import fractional_delay
from mankomix.dspx.bb.wobble import wobble, wobble_from_params, base_latency
from mankomix.dspx.procs.flanger import flanger, raw_flanger, delay_samples, latency_samples
from mankomix.dspx.procs.phaser import phaser, corner_frequencies
from mankomix.dspx.procs.vibrato import vibrato, raw_vibrato, onset_envelope
from mankomix.dspx.procs.adt import adt, voice_motion
from mankomix.dspx.procs.wow_flutter import wow_flutter, raw_wow_flutter, weighting_sos, weighted_measurement
from tests import toolimpl_harness as H

KINDS = ('flanger', 'phaser', 'vibrato', 'adt', 'wow_flutter')
FUNCTIONS = dict(zip(KINDS, (flanger, phaser, vibrato, adt, wow_flutter)))
DEFAULTS = {
    'flanger': dict(rate_hz=.25, note='none', bpm=0, depth=.7, lfo_shape='sine', stereo_phase=0,
                    origin_s=0, phase=0, mix=.5, seed=0, delay_ms=2, min_delay_ms=.2,
                    feedback=.5, through_zero=False, invert=False, sweep='log', highcut_hz=0),
    'phaser': dict(rate_hz=.4, note='none', bpm=0, depth=.7, lfo_shape='sine', stereo_phase=.1,
                   origin_s=0, phase=0, mix=.5, seed=0, stages=4, center_hz=800, range_oct=3,
                   feedback=.3, spread=0, invert=False),
    'vibrato': dict(rate_hz=5, note='none', bpm=0, depth=.5, lfo_shape='sine', stereo_phase=0,
                    origin_s=0, phase=0, seed=0, depth_cents=20, onset_ms=0),
    'adt': dict(delay_ms=30, wander_ms=4, wander_rate_hz=.4, wander_shape='random',
                level_wander_db=.5, voices=1, spread=.7, double_db=-3, highcut_hz=0, seed=0),
    'wow_flutter': dict(wow_depth=.2, wow_rate_hz=.6, flutter_depth=.05, flutter_rate_hz=9,
                        drift=.3, scrape=0, stereo_link=1, seed=0),
}


def p(kind, **params):
    return P.validate_params(kind, params)


def run(kind, x, sr=48000, **params):
    return render_chain(x, sr, [{'id': 'motion', 'type': kind, 'params': params}],
                        stage='track', seed=197)


def tone(sr=48000, seconds=1, hz=1000, channels=1):
    return np.repeat((.1*np.sin(2*np.pi*hz*np.arange(round(seconds*sr))/sr))[:, None], channels, axis=1)


def measurement(label, values):
    print(label + ': ' + json.dumps(values, sort_keys=True, allow_nan=False))


@pytest.mark.parametrize('kind', KINDS)
def test_declarations_defaults_and_valid_endpoints(kind):
    spec = P.describe(kind)
    assert p(kind) == DEFAULTS[kind]
    assert spec['stages'] == ['track', 'bus'] and spec['master_slot'] is None
    assert spec['backends'] == ['reference'] and not spec['offline_only']
    assert spec['realtime']['allocates'] and not spec['realtime']['block_ok']
    from mankomix.dspx.registry import time_varying_types
    assert kind in time_varying_types()
    assert spec.get('channel_ok') == (kind != 'adt')
    x = tone(seconds=.012)
    for entry in spec['params']:
        values = []
        if entry['type'] in ('float', 'int'):
            values = [entry['min'], entry['max']]
        elif entry['type'] == 'enum':
            values = entry['choices']
        elif entry['type'] == 'bool':
            values = [False, True]
        for value in values:
            extra = {'bpm': 120} if entry['id'] == 'note' and value != 'none' else {}
            if kind == 'flanger' and entry['id'] == 'min_delay_ms':
                extra['delay_ms'] = max(2, value)
            if kind == 'flanger' and entry['id'] == 'delay_ms':
                extra['min_delay_ms'] = min(.2, value)
            params = p(kind, **{**extra, entry['id']: value})
            y, sr_out, _ = FUNCTIONS[kind](x, 48000, params, seed=197)
            assert sr_out == 48000 and len(y) == len(x) and np.isfinite(y).all(), (kind, entry, value)


@pytest.mark.parametrize('kind', KINDS)
def test_default_engine_repeat_and_excerpt(kind):
    x = tone(seconds=.18, channels=2)
    result = H.render(kind, x, 48000, stage='track', seed=197)
    a = result.audio
    assert a.tobytes() == H.render(kind, x, 48000, stage='track', seed=197).audio.tobytes()
    excerpt = H.render_excerpt(kind, x, 48000, 1007, len(x), stage='track', seed=197)
    # Both full render and excerpt use H's item id, hence the same engine seed.
    assert a[1007:].tobytes() == excerpt.tobytes()
    assert 'mono' in result.steps[0]['stats']


@pytest.mark.parametrize('kind', ['flanger', 'phaser'])
def test_mix_zero_bits_even_through_zero(kind):
    x = np.random.Generator(np.random.PCG64(4)).normal(size=(2048, 2))
    x[3] = -0.
    extra = {'through_zero': True} if kind == 'flanger' else {}
    assert run(kind, x, mix=0, **extra).audio.tobytes() == x.tobytes()


@pytest.mark.parametrize('kind', ['flanger', 'phaser', 'vibrato'])
def test_mod_clock_period_excerpt_phase_and_tempo(kind):
    params = p(kind, rate_hz=7.3, stereo_phase=.5, origin_s=.013, phase=.12)
    wave = mod_lfo(5000, 8000, params, 2)
    np.testing.assert_allclose(wave[:, 0], -wave[:, 1], atol=2e-15)
    assert wave[1234:3567].tobytes() == mod_lfo(2333, 8000, params, 2, start_sample=1234).tobytes()
    start = round((.013 + (1000-.12)/7.3)*8000)
    phase = phase_positions(1, 8000, start_sample=start, period_ms=1000/7.3,
                            origin_s=.013, phase=.12, wrap=False)[0]
    assert abs((phase-1000)*8000/7.3) <= 1
    peaks = signal.find_peaks(wave[:, 0])[0]
    assert abs(np.mean(np.diff(peaks))-8000/7.3) <= 1
    a = p(kind, note='1/4', bpm=120, stereo_phase=0)
    a['origin_s'] = 0
    expected = np.sin(2*np.pi*np.remainder(np.arange(4000)/4000, 1))
    np.testing.assert_allclose(mod_lfo(4000, 8000, a)[:, 0], expected, atol=2e-15)
    for bad in ({'note': '1/4', 'bpm': 0}, {'bpm': 10}):
        with pytest.raises(ParamError):
            run(kind, tone(seconds=.01), **bad)


def test_bandlimited_walk_and_absolute_grid():
    wave = bandlimited_walk(6000, 100, 2, seed=17)
    frequencies = rfftfreq(len(wave), .01)
    assert np.max(abs(rfft(wave)[frequencies > 2])) < 1e-10
    assert wave[1033:3077].tobytes() == bandlimited_walk(2044, 100, 2, seed=17, start_sample=1033).tobytes()
    assert wave.tobytes() != bandlimited_walk(6000, 100, 2, seed=18).tobytes()
    assert np.max(abs(wave)) <= 1
    opposite = bandlimited_walk(6000, 100, 2, seed=17, phase=.5)
    np.testing.assert_allclose(wave, -opposite, atol=2e-15)


@pytest.mark.parametrize('invert', [False, True])
def test_flanger_fixed_comb_noise_notches(invert):
    sr, n, delay = 16000, 65536, 32
    rng = np.random.Generator(np.random.PCG64(8))
    x = rng.normal(size=(n, 1))*.03
    y = run('flanger', x, sr, delay_ms=2, depth=0, feedback=0, invert=invert).audio
    expected = .5*x + (-.5 if invert else .5)*fractional_delay(x, delay, 'lagrange3')
    assert H.null(y, expected)['rms_dbfs'] <= -100
    f, transfer = signal.freqz([.5]+[0.]*(delay-1)+[-.5 if invert else .5], worN=65536, fs=sr)
    notches = signal.find_peaks(-abs(transfer))[0]
    spacing = np.diff(f[notches[:8]])
    assert np.max(abs(spacing-sr/delay))/(sr/delay) < .02
    # Independent white-noise cross-spectrum at alternating theoretical extrema.
    f, cross = signal.csd(x[:, 0], y[:, 0], fs=sr, nperseg=8192)
    _, power = signal.welch(x[:, 0], fs=sr, nperseg=8192)
    response = abs(cross/power)
    near = lambda hz: response[np.argmin(abs(f-hz))]
    assert (near(250) > near(500)) if invert else (near(500) > near(250))
    measurement('flanger_comb', {'invert': invert, 'spacing_hz': float(spacing.mean())})


def test_flanger_through_zero_cancellation_and_latency():
    sr = 48000
    x = tone(sr, 1)
    params = p('flanger', delay_ms=2, min_delay_ms=0, depth=1, sweep='linear',
               through_zero=True, invert=True, feedback=0, rate_hz=1)
    raw, _, stats = raw_flanger(x, sr, params)
    # At phase .5, wet and delayed dry both read exactly n - 48.
    assert abs(raw[sr//2, 0]) < 1e-12
    assert stats['latency_samples'] == 48
    q = {**params, 'depth': 0, 'invert': False, 'mix': 0.01}
    impulse = np.zeros((1000, 1)); impulse[100] = 1
    assert np.argmax(abs(raw_flanger(impulse, sr, q)[0][:, 0]))-100 == 48
    assert np.argmax(abs(flanger(impulse, sr, q)[0][:, 0]))-100 == 0


@pytest.mark.parametrize('feedback', [-.95, .95])
def test_feedback_bound_and_sixty_second_tail(feedback):
    sr = 8000
    x = np.zeros((60*sr+400, 2)); x[:400] = 1
    for kind in ('flanger', 'phaser'):
        params = p(kind, depth=0, feedback=feedback)
        if kind == 'phaser':
            params['stages'] = 12
        y, _, _ = FUNCTIONS[kind](x, sr, params)
        assert np.isfinite(y).all()
        assert np.max(abs(y)) <= 10**(26/20)
        assert H.peak_dbfs(y[-sr:]) < -120
        measurement('feedback_tail', {'type': kind, 'feedback': feedback,
                                     'peak': float(np.max(abs(y))), 'tail_peak': float(np.max(abs(y[-sr:])))})


@pytest.mark.parametrize('stages', [2, 4, 6, 8, 12])
@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_phaser_notch_count_theory_and_allpass(stages, sr):
    n = 32768
    x = np.zeros((n, 1)); x[0] = 1
    params = p('phaser', depth=0, feedback=0, stages=stages)
    wet = phaser(x, sr, {**params, 'mix': 1})[0][:, 0]
    magnitude = abs(rfft(wet))
    assert np.max(abs(20*np.log10(magnitude))) < .01
    y = phaser(x, sr, params)[0][:, 0]
    freq = rfftfreq(n, 1/sr)
    minima = signal.find_peaks(-abs(rfft(y)))[0]
    assert len(minima) == stages//2
    theory = sr/np.pi*np.arctan(np.tan(np.pi*800/sr)*np.tan(np.pi/(2*stages)))
    assert abs(freq[minima[0]]/theory-1) < .03
    measurement('phaser_notch', {'stages': stages, 'sr': sr, 'first_hz': float(freq[minima[0]]),
                                'theory_hz': float(theory), 'allpass_error_db': float(np.max(abs(20*np.log10(magnitude))))})


def test_phaser_sweep_endpoints():
    params = p('phaser', depth=1, rate_hz=1)
    corners = corner_frequencies(8000, 8000, params)
    np.testing.assert_allclose([corners.min(), corners.max()], 800*2.**np.array([-1.5, 1.5]), rtol=.03)
    params['stereo_phase'] = 0
    y = run('phaser', tone(seconds=.2, channels=2), stereo_phase=0).audio
    assert y[:, 0].tobytes() == y[:, 1].tobytes()


@pytest.mark.parametrize('cents', [20, 200])
def test_vibrato_pitch_and_envelope(cents):
    sr = 48000
    x = tone(sr, 4)
    params = p('vibrato', depth=1, depth_cents=cents, rate_hz=5)
    y, _, _ = vibrato(x, sr, params)
    analytic = signal.hilbert(y[:, 0])
    frequency = np.diff(np.unwrap(np.angle(analytic)))*sr/(2*np.pi)
    frequency = frequency[sr//2:-sr//2]
    pitch = 1200*np.log2(frequency/1000)
    extrema = [float(pitch.min()), float(pitch.max())]
    assert abs(extrema[0]+cents) <= .05*cents and abs(extrema[1]-cents) <= .05*cents
    average = float(1200*np.log2(frequency.mean()/1000))
    assert abs(average) < .5
    env = abs(analytic)[sr//2:-sr//2]
    ripple = float(20*np.log10(env.max()/env.min()))
    assert ripple <= .05
    measurement('vibrato', {'depth_cents': cents, 'extrema_cents': extrema,
                            'mean_cents': average, 'envelope_ripple_db': ripple})


def test_vibrato_zero_latency_and_onset():
    sr = 48000
    x = tone(sr, .5)
    assert run('vibrato', x, depth_cents=0).audio.tobytes() == x.tobytes()
    params = p('vibrato', depth_cents=0)
    raw = raw_vibrato(x, sr, params)[0]
    latency = pitch_latency(sr, params)
    assert H.null(raw[latency:], x[:-latency])['rms_dbfs'] <= -120
    envelope = onset_envelope(x, sr, 100)
    first = np.flatnonzero(envelope > 0)[0]
    assert abs(first/sr-.1) < .01
    assert np.all(envelope[:first] == 0) and np.max(envelope) == 1


@pytest.mark.parametrize('kind', ['vibrato', 'wow_flutter'])
def test_raw_active_latency_compensation_matches_offline(kind):
    params = p(kind)
    x = tone(seconds=.3, channels=2)
    latency = pitch_latency(48000, params) if kind == 'vibrato' else base_latency(48000, params)
    raw_fn = raw_vibrato if kind == 'vibrato' else raw_wow_flutter
    padded = np.pad(x, ((0, latency), (0, 0)))
    raw = raw_fn(padded, 48000, params, seed=8)[0]
    offline = FUNCTIONS[kind](x, 48000, params, seed=8)[0]
    assert raw[latency:latency+len(x)].tobytes() == offline.tobytes()


@pytest.mark.parametrize('kind', ['flanger', 'phaser', 'vibrato'])
@pytest.mark.parametrize('shape', ['sine', 'triangle', 'random'])
def test_control_generators_excerpt_and_link(kind, shape):
    params = p(kind, lfo_shape=shape, stereo_phase=0, origin_s=.037, phase=.13)
    maker = {'flanger': delay_samples, 'phaser': corner_frequencies, 'vibrato': pitch_delay}[kind]
    a = maker(6001, 8000, params, 2, seed=7)
    b = maker(2123, 8000, params, 2, start_sample=1701, seed=7)
    assert a[1701:3824].tobytes() == b.tobytes()
    assert a[:, 0].tobytes() == a[:, 1].tobytes()


@pytest.mark.parametrize('voices', [1, 2])
def test_adt_fixed_structure_and_pan(voices):
    sr = 48000
    x = tone(sr, .3, channels=2)
    params = p('adt', wander_ms=0, level_wander_db=0, spread=0, voices=voices)
    y, _, stats = adt(x, sr, params)
    expected = x + np.sqrt(voices)*10**(-3/20)*fractional_delay(x, 1440, 'lagrange3')
    assert H.null(y, expected)['rms_dbfs'] <= -100
    assert stats['first_notch_hz'] == 1000/60
    assert 'mono' in stats
    if voices == 1:
        y = adt(x, sr, {**params, 'spread': 1})[0]
        assert y[:, 0].tobytes() == x[:, 0].tobytes()
        np.testing.assert_allclose(y[:, 1], expected[:, 1]-x[:, 1], atol=1e-16)
    measurement('adt_mono', {k: stats[k] for k in ('mono', 'first_notch_hz')})


def test_adt_motion_range_seed_and_excerpt():
    params = p('adt', wander_shape='sine', wander_rate_hz=1)
    d, _ = voice_motion(8000, 8000, params)
    np.testing.assert_allclose([d.min(), d.max()], np.array([26, 34])*8, rtol=.05)
    params['wander_shape'] = 'random'
    a = voice_motion(8000, 8000, params, seed=3)
    b = voice_motion(8000, 8000, params, seed=3)
    c = voice_motion(8000, 8000, params, seed=4)
    assert all(u.tobytes() == v.tobytes() for u, v in zip(a, b))
    assert a[0].tobytes() != c[0].tobytes()
    excerpt = voice_motion(1221, 8000, params, start_sample=971, seed=3)
    assert all(u[971:2192].tobytes() == v.tobytes() for u, v in zip(a, excerpt))


@pytest.mark.parametrize('kind', KINDS)
def test_seed_changes_random_output(kind):
    extra = {'lfo_shape': 'random'} if kind in ('flanger', 'phaser', 'vibrato') else {}
    x = tone(seconds=.25, channels=2)
    assert run(kind, x, seed=17, **extra).audio.tobytes() != run(kind, x, seed=18, **extra).audio.tobytes()


def test_wobble_speed_integral_and_random_absolute_clock():
    sr = 8000
    params = dict(wow_depth=.2, flutter_depth=.05, drift=.3, scrape=.7, stereo_link=1)
    d, v = wobble(16000, sr, channels=2, seed=8, **params)
    assert d[:, 0].tobytes() == d[:, 1].tobytes()
    assert v[:, 0].tobytes() == v[:, 1].tobytes()
    short = wobble(1703, sr, channels=2, start_sample=2931, seed=8, **params)
    assert all(a[2931:4634].tobytes() == b.tobytes() for a, b in zip((d, v), short))
    assert d.tobytes() != wobble(16000, sr, channels=2, seed=9, **params)[0].tobytes()
    # Remove scrape for the finite-difference derivative test at this sr.
    d, v = wobble(16000, sr, seed=8, wow_depth=.2, flutter_depth=.05, drift=.3)
    np.testing.assert_allclose(-np.gradient(d[:, 0]), v[:, 0], atol=3e-6)
    unlinked = wobble(1000, sr, channels=2, stereo_link=0, seed=8)[0]
    assert unlinked[:, 0].tobytes() != unlinked[:, 1].tobytes()


@pytest.mark.parametrize('band,depth,rate', [('wow', .2, .6), ('flutter', .05, 9)])
def test_wow_flutter_3150_hz_excursion(band, depth, rate):
    sr = 48000
    params = p('wow_flutter', wow_depth=depth if band == 'wow' else 0,
               flutter_depth=depth if band == 'flutter' else 0, drift=0)
    x = tone(sr, 5, 3150, 2)
    y, _, stats = wow_flutter(x, sr, params)
    freq = np.diff(np.unwrap(np.angle(signal.hilbert(y[:, 0]))))*sr/(2*np.pi)
    deviation = 100*(freq[sr:-sr]/3150-1)
    assert abs(deviation.max()/depth-1) < .1
    assert abs(deviation.min()/depth+1) < .1
    assert y[:, 0].tobytes() == y[:, 1].tobytes()
    measurement('wow_flutter_tone', {'band': band, 'min_percent': float(deviation.min()),
                                    'max_percent': float(deviation.max()), 'rate_hz': rate})


def test_wow_flutter_neutral_sixty_seconds_and_link():
    x = tone(seconds=.2, channels=2)
    y = run('wow_flutter', x, wow_depth=0, flutter_depth=0, scrape=0).audio
    assert y.tobytes() == x.tobytes()
    sr = 8000
    d, v = wobble(60*sr+1, sr, channels=2, seed=19)
    offset = float(np.max(abs(d[-1]-d[0])))
    mean = float(np.max(abs(np.mean(v[:-1], axis=0)))*100)
    assert offset <= 1 and mean <= .001
    assert d[:, 0].tobytes() == d[:, 1].tobytes()
    measurement('wow_flutter_60s', {'end_offset_samples': offset, 'mean_speed_percent': mean})


def test_wobble_arbitrary_rate_end_offset():
    d, v = wobble(60*8000+1, 8000, wow_rate_hz=.137, wow_depth=3, flutter_depth=0, drift=0,
                  close_60s=True)
    offset = float(abs(d[-1, 0]-d[0, 0]))
    measurement('closed_wobble_60s_noninteger_cycles', {'end_offset_samples': offset})
    assert offset <= 1
    assert abs(np.mean(v[:-1]))*100 <= .001


@pytest.mark.parametrize('kind', ['flanger', 'phaser', 'vibrato', 'wow_flutter'])
def test_common_contracts(kind):
    params, neutral, lp = {}, None, {}
    if kind in ('flanger', 'phaser'):
        params = {'depth': 0, 'feedback': 0}
        neutral = {'mix': 0}
    if kind == 'vibrato':
        neutral = {'depth_cents': 0}
        lp = neutral
    if kind == 'wow_flutter':
        neutral = {'wow_depth': 0, 'flutter_depth': 0, 'scrape': 0}
        lp = neutral

    def sr_probe(x, y, sr, validated):
        frequency = H.fundamental_frequency(y[sr//20:], sr, low_hz=850, high_hz=1150)
        return {'passed': abs(frequency-1000) < 2, 'frequency_hz': frequency}

    raw = None
    resolver = 0
    if kind == 'flanger':
        # Through-zero latency also checked with a dominant dry impulse.
        lp = {'through_zero': True, 'mix': .01, 'depth': 0}
        resolver = latency_samples
        raw = lambda x, sr, p, **kw: raw_flanger(x, sr, p, seed=kw['seed'])[0]
    elif kind == 'vibrato':
        resolver = pitch_latency
        raw = lambda x, sr, p, **kw: raw_vibrato(x, sr, p, seed=kw['seed'])[0]
    elif kind == 'wow_flutter':
        resolver = base_latency
        raw = lambda x, sr, p, **kw: raw_wow_flutter(x, sr, p, seed=kw['seed'])[0]
    result = H.assert_common_tests(kind, params=params, neutral=neutral, latency_params=lp,
                                   declared_latency=resolver, latency_probe=raw,
                                   sr_probe=sr_probe, seconds=.25)
    measurement('common_'+kind, {k: v['passed'] for k, v in result.items()})


def test_adt_common_contracts_with_stereo_fixture_adapter(monkeypatch):
    # BB-01 assumes invariant channel count in CT-7. ADT explicitly creates
    # stereo, so run its generic fixture in stereo and test mono creation below.
    original = H.sine
    monkeypatch.setattr(H, 'sine', lambda *a, **kw: original(*a, **{**kw, 'channels': 2}))
    params = {'wander_ms': 0, 'level_wander_db': 0}

    def probe(x, y, sr, validated):
        f = H.fundamental_frequency(y[sr//10:], sr, low_hz=900, high_hz=1100)
        return {'passed': abs(f-1000) < 1, 'frequency_hz': f}

    result = H.assert_common_tests('adt', params=params, sr_probe=probe, seconds=.25,
                                   latency_params={'spread': 1})
    measurement('common_adt', {k: v['passed'] for k, v in result.items()})
    for sr in (44100, 48000, 96000):
        mono = tone(sr, .3)
        y = run('adt', mono, sr, **params).audio
        assert y.shape == (len(mono), 2)
        assert abs(H.fundamental_frequency(y[sr//10:], sr, low_hz=900, high_hz=1100)-1000) < 1


def test_channel_selection_and_master_rejection():
    x = tone(seconds=.15, channels=2)
    for kind in KINDS:
        with pytest.raises(ChainError):
            validate_chain([{'type': kind}], 'master')
        if kind == 'adt':
            with pytest.raises(ParamError):
                render_chain(x, 48000, [{'type': kind, 'channel': 'left'}], stage='track')
        else:
            y = render_chain(x, 48000, [{'type': kind, 'channel': 'left'}], stage='track').audio
            assert x[:, 1].tobytes() == y[:, 1].tobytes()


def test_honest_implementation_flags():
    for kind in KINDS:
        module = importlib.import_module('mankomix.dspx.procs.'+kind)
        assert module.SPECS[0]['implemented'] is True


def test_flanger_subsample_feedback_sweep():
    params = p('flanger', depth=1, delay_ms=.1, min_delay_ms=0, sweep='linear', rate_hz=20)
    x = tone(48000, .1)
    _, _, stats = raw_flanger(x, 48000, params)
    requested = delay_samples(len(x), 48000, params)
    assert abs(stats['delay_min_samples']-float(requested.min())) <= .01


def test_iec_weighted_measurement():
    _, _, stats = wow_flutter(tone(seconds=.1), 48000, p('wow_flutter'))
    assert stats['iec_60386_weighted_percent'] is not None
    assert 'self_contained_spec_fallback' in stats['weighting_status']
    assert not stats['weighting_minimum_5s']


@pytest.mark.parametrize('feedback', [-.95, .95])
@pytest.mark.parametrize('delay', [0., .125, .9, 1.25, 2.75])
@pytest.mark.parametrize('highcut', [0, 1700])
def test_flanger_short_loop_equation_and_continuation(feedback, delay, highcut):
    from mankomix.dspx.procs.flanger import _short_feedback
    sr = 8000
    x = np.random.Generator(np.random.PCG64(71)).normal(size=(127, 2))*.03
    delays = np.full_like(x, delay)
    wet = _short_feedback(x, delays, sr, feedback, highcut)
    filtered = wet if not highcut else signal.sosfilt(
        signal.butter(2, highcut, fs=sr, output='sos'), wet, axis=0)
    # Independent BB-09 read verifies the actual equation, not delay stats.
    expected = fractional_delay(x+feedback*filtered, delays, 'lagrange3')
    assert np.max(abs(wet-expected)) < 2e-13
    params = p('flanger', delay_ms=.1, min_delay_ms=0, depth=1, phase=.75,
               sweep='linear', rate_hz=20, mix=1, feedback=feedback, highcut_hz=highcut)
    a = raw_flanger(x, sr, params)[0]
    b = raw_flanger(np.pad(x, ((0, 128), (0, 0))), sr, params)[0][:len(x)]
    np.testing.assert_allclose(a, b, rtol=0, atol=2e-13)


@pytest.mark.parametrize('feedback', [-.95, .95])
def test_flanger_short_loop_resonance_and_sixty_second_tail(feedback):
    sr = 1000
    params = p('flanger', delay_ms=.1, min_delay_ms=0, depth=0, feedback=feedback, mix=1)
    x = np.zeros((sr*60+100, 1)); x[:100] = 1
    y = flanger(x, sr, params)[0]
    assert np.isfinite(y).all()
    # The +26 dB criterion describes resonance, not cubic step overshoot.
    resonance_db = float(20*np.log10(np.max(abs(y[60:80]))))
    assert resonance_db <= 26+1e-12
    assert H.peak_dbfs(y[-sr:]) < -120
    measurement('flanger_short_tail', {'feedback': feedback, 'peak': float(np.max(abs(y))),
                                       'resonance_db': resonance_db,
                                       'tail_peak': float(np.max(abs(y[-sr:])))})


@pytest.mark.parametrize('feedback', [-.95, .95])
@pytest.mark.parametrize('delay', [.125, .9, 1.25, 2.75])
def test_flanger_short_loop_tone_resonance(feedback, delay):
    sr = 1000
    params = p('flanger', delay_ms=delay, min_delay_ms=0, depth=0, feedback=feedback, mix=1)
    largest = 0.
    for hz in (0, 100, 250, 400, 499):
        angle = 2*np.pi*hz*np.arange(4096)/sr
        x = np.column_stack([np.cos(angle), np.sin(angle)])
        y = flanger(x, sr, params)[0][2048:3072]
        gain = float(np.max(np.sqrt(np.sum(y*y, axis=1))))
        largest = max(largest, gain)
        assert 20*np.log10(gain) <= 26+1e-8
    measurement('short_tone_resonance', {'feedback': feedback, 'delay_samples': delay,
                                        'largest_db': float(20*np.log10(largest))})


def test_short_flanger_raw_compensation():
    sr = 48000
    params = p('flanger', delay_ms=.1, min_delay_ms=0, depth=1, through_zero=True,
               feedback=.95, rate_hz=20)
    x = tone(sr, .1, channels=2)
    latency = latency_samples(sr, params)
    raw = raw_flanger(np.pad(x, ((0, latency), (0, 0))), sr, params)[0]
    assert raw[latency:latency+len(x)].tobytes() == flanger(x, sr, params)[0].tobytes()


@pytest.mark.parametrize('controls,digest', [
    ({}, '9e64d15c82a247521cacf4d0db2ce182de36d611a7bfa7de21c2d16b7c3c23de'),
    ({'wow_rate_hz': .137, 'drift': 0, 'scrape': .8, 'stereo_link': 0},
     'f73528fbb87a0b6229eb405223d31a75cbcc4f435a1ea47840a903ca10ca0a29'),
    ({'drift': 1, 'stereo_link': .3}, 'd44fbf6026011d5d26e8449ad0d07dde0a6bf5c5d915b2d5aba1217f6c506f30')])
def test_shared_wobble_original_default_bytes(controls, digest):
    # Captured from W2d1's original shared implementation before C3 edits.
    arrays = wobble(1027, 8000, channels=2, start_sample=371, seed=19, **controls)
    assert hashlib.sha256(b''.join(a.tobytes() for a in arrays)).hexdigest() == digest


@pytest.mark.parametrize('rate,flutter', [(.1, 4), (.137, 7.123), (4, 50)])
@pytest.mark.parametrize('drift,link', [(0, 0), (.3, .4), (1, 1)])
def test_wobble_closed_motion_endpoints_excerpt_and_derivative(rate, flutter, drift, link):
    sr = 8000
    controls = dict(wow_depth=3, flutter_depth=1, wow_rate_hz=rate, flutter_rate_hz=flutter,
                    drift=drift, stereo_link=link, scrape=1, close_60s=True)
    # Endpoints need no full-length audio or 60 s allocation.
    start = wobble(1, sr, channels=2, seed=31, **controls)[0]
    end = wobble(1, sr, channels=2, start_sample=60*sr, seed=31, **controls)[0]
    assert np.max(abs(start-end)) <= 1
    d, v = wobble(6001, sr, channels=2, seed=31, **controls)
    excerpt = wobble(1703, sr, channels=2, start_sample=1931, seed=31, **controls)
    assert all(a[1931:3634].tobytes() == b.tobytes() for a, b in zip((d, v), excerpt))
    # Analytic d/dt tested without high-frequency scrape finite-difference error.
    controls['scrape'] = 0
    d, v = wobble(6001, sr, channels=2, seed=31, **controls)
    np.testing.assert_allclose(-np.gradient(d, axis=0)[1:-1], v[1:-1], atol=3e-6)
    _, speed = wobble(60*200, 200, channels=2, seed=31, **controls)
    mean = float(np.max(abs(np.mean(speed, axis=0)))*100)
    assert mean <= .001
    measurement('closed_motion', {'rate_hz': rate, 'flutter_hz': flutter, 'drift': drift,
                                  'link': link, 'end_samples': float(np.max(abs(start-end))),
                                  'mean_percent': mean})


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_weighting_frequency_response_and_calibrated_detector(sr):
    hz = np.array([.05, .1, .5, .6, 1., 4., 9., 40., 100.])
    _, response = signal.sosfreqz(weighting_sos(sr), worN=hz, fs=sr)
    # Independently evaluate the declared analogue formula at bilinear frequencies.
    omega = 2*sr*np.tan(np.pi*hz/sr)
    def analogue(w):
        return (1j*w)**2/((1j*w+2*np.pi*.5)*(1j*w+2*np.pi*4)**2)
    norm = abs(analogue(2*sr*np.tan(np.pi*4/sr)))
    np.testing.assert_allclose(abs(response), abs(analogue(omega))/norm, rtol=2e-6)
    # Measure at a low control rate: the filter operates on speed, not the carrier.
    control_sr = 400
    time = np.arange(60*control_sr)/control_sr
    speed = np.column_stack([.001*np.sin(2*np.pi*4*time), .002*np.sin(2*np.pi*4*time)])
    result = weighted_measurement(speed, control_sr)
    np.testing.assert_allclose(result['weighted_percent_by_channel'], np.sqrt(2)*np.array([.1, .2]), rtol=.01)
    assert result['weighting_minimum_5s'] and result['iec_60386_weighted_percent'] == max(result['weighted_percent_by_channel'])
    measurement('weighting_response', {'sr': sr, 'hz': hz.tolist(), 'magnitude': abs(response).tolist(),
                                        'calibration_percent': result['weighted_percent_by_channel']})


def test_weighted_3150_hz_audio_demodulation_and_item_seed():
    sr = 16000
    params = p('wow_flutter', wow_depth=.2, wow_rate_hz=4, flutter_depth=0, drift=0)
    x = tone(sr, 8, 3150, 2)
    rendered = H.render('wow_flutter', x, sr, params, stage='track', seed=31)
    y = rendered.audio
    phase = np.unwrap(np.angle(signal.hilbert(y[:, 0])))
    demodulated = np.diff(phase)*sr/(2*np.pi*3150)-1
    # Exclude Hilbert boundary transients and filter startup in both paths.
    actual = signal.sosfilt(weighting_sos(sr), demodulated)
    _, speed = wobble_from_params(len(x), sr, params, close_60s=True)
    reference = signal.sosfilt(weighting_sos(sr), speed[:, 0])
    measured = 200*np.std(actual[sr:-sr])
    expected = 200*np.std(reference[sr:-sr])
    assert abs(measured/expected-1) < .1
    random_params = {'drift': 1}
    a = render_chain(x[:2000], sr, [{'id': 'a', 'type': 'wow_flutter', 'params': random_params}], stage='track', seed=31)
    b = render_chain(x[:2000], sr, [{'id': 'b', 'type': 'wow_flutter', 'params': random_params}], stage='track', seed=31)
    assert a.audio.tobytes() != b.audio.tobytes()
    measurement('weighted_audio', {'demodulated_percent': measured, 'generator_percent': expected,
                                   'stats_percent': rendered.steps[0]['stats']['iec_60386_weighted_percent']})
