"""W1e acceptance: MB dynamics, band balance and absolute-clock tremolo."""
import math
import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb import crossover as C
from mankomix.dspx.procs import mb_compressor as MC, mb_expander as ME
from mankomix.dspx.procs import parallel_comp as PC, band_pan as BP, tremolo as TR
from tests import toolimpl_harness as H

KINDS = ('mb_compressor', 'mb_expander', 'parallel_comp', 'band_pan', 'tremolo')
MODULES = dict(zip(KINDS, (MC, ME, PC, BP, TR)))


@pytest.fixture
def enabled():
    # Acceptance runs through normal public registration, without overriding it.
    for kind in KINDS:
        assert P.PROCESSORS[kind]['implemented']


def render(kind, x, p=None, sr=16000, stage='track'):
    return E.render_chain(x, sr, [{'type': kind, 'params': p or {}}], stage=stage).audio


def direct(kind, x, p=None, sr=16000, **kwargs):
    return MODULES[kind].IMPLS[kind](x, sr, P.validate_params(kind, p or {}), **kwargs)[0]


def dbgain(x, y):
    return H.rms_dbfs(y)-H.rms_dbfs(x)


@pytest.mark.parametrize('kind', ['mb_compressor', 'mb_expander'])
@pytest.mark.parametrize('phase', ['linear', 'minimum'])
@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_mb_neutral_reconstruction(enabled, kind, phase, sr):
    x = H.impulse(sr=sr, seconds=.5, channels=2)
    p = dict(phase=phase, ratio=[1, 1, 1])
    y = render(kind, x, p, sr)
    if phase == 'linear':
        assert H.null(x, y)['peak_dbfs'] <= -120
    else:
        assert np.max(np.abs(20*np.log10(np.abs(np.fft.rfft(y[:, 0]))))) < .01
        expected = x
        for f in [150, 2500]:
            lo, hi = C.lr_sos(f, sr)
            expected = signal.sosfilt(lo, expected, axis=0)+signal.sosfilt(hi, expected, axis=0)
        assert H.null(y, expected)['peak_dbfs'] <= -120


@pytest.mark.parametrize('linked', [True, False])
@pytest.mark.parametrize('detector', ['peak', 'rms'])
def test_single_band_matches_existing_compressor(enabled, linked, detector):
    x = H.white_noise(-10, seconds=.2, sr=16000, channels=2)
    cp = dict(threshold_db=-24, ratio=2, attack_ms=10, release_ms=150,
              makeup_db=0, knee_db=6, detector=detector, rms_window_ms=10, stereo_link=linked)
    p = dict(crossovers_hz=[], **{k: [v] if k in MC.DEFAULTS else v for k, v in cp.items()})
    y = render('mb_compressor', x, p)
    old = render('compressor', x, cp)
    assert H.null(y, old)['peak_dbfs'] <= -120


@pytest.mark.parametrize('kind', ['mb_compressor', 'mb_expander'])
@pytest.mark.parametrize('band,freq', [(0, 50), (1, 500), (2, 6000)])
def test_bandwise_level_staircase(enabled, kind, band, freq):
    # Independent renders of each stair avoid carrying preceding stair state.
    for db in [-60, -45, -30, -15]:
        x = H.sine(freq, db, seconds=.6, sr=16000)
        threshold = -30 if kind == 'mb_compressor' else -45
        p = dict(phase='linear', threshold_db=[threshold]*3, ratio=[2]*3,
                 attack_ms=[.05]*3, release_ms=[5]*3, knee_db=0)
        if kind == 'mb_expander':
            p['hold_ms'] = [0]*3
        y = render(kind, x, p)
        # Compressor RMS detector: sine RMS is peak minus 3.0103 dB.
        level = db-10*math.log10(2) if kind == 'mb_compressor' else db
        expected = -max(level-threshold, 0)/2 if kind == 'mb_compressor' else max(min(level-threshold, 0), -24)
        if kind == 'mb_expander':
            # Use band center samples near carrier peaks to measure the peak
            # detector static curve independently of its intra-cycle ripple.
            idx = np.flatnonzero(np.abs(x[:, 0]) > .999*10**(db/20))
            idx = idx[(idx > 4000) & (idx < len(x)-1000)]
            actual = np.median(20*np.log10(np.abs(y[idx, 0]/x[idx, 0])))
        else:
            actual = dbgain(x[4000:-1000], y[4000:-1000])
        # Expander peak detector is samplewise; fast attack with closing tau
        # causes carrier-cycle averaging. Static acceptance also uses constant
        # levels below, so do not confuse that ripple with a static dB error.
        if kind == 'mb_compressor':
            assert actual == pytest.approx(expected, abs=.3)
        else:
            assert actual == pytest.approx(expected, abs=.3)


@pytest.mark.parametrize('kind', ['mb_compressor', 'mb_expander'])
def test_other_band_isolation(enabled, kind):
    for active in range(3):
        ratio = [1]*3
        ratio[active] = 8
        p = dict(phase='linear', ratio=ratio, threshold_db=[-30]*3,
                 attack_ms=[1]*3, release_ms=[5]*3)
        for band, f in enumerate([50, 600, 6500]):
            if band == active:
                continue
            x = H.sine(f, -12 if kind == 'mb_compressor' else -48, sr=16000, seconds=.4)
            y = render(kind, x, p)
            assert abs(dbgain(x[2000:-2000], y[2000:-2000])) <= .1


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_compressor_time_constants(enabled, sr):
    n = round(.06*sr)
    x = np.r_[np.full(n, .001), np.full(round(.2*sr), .5), np.full(round(.3*sr), .001)][:, None]
    p = dict(crossovers_hz=[], detector='peak', knee_db=0, threshold_db=[-24],
             ratio=[2], attack_ms=[5], release_ms=[15])
    y = render('mb_compressor', x, p, sr)
    gr = -20*np.log10(y[:, 0]/x[:, 0])
    target = (20*np.log10(.5)+24)/2
    attack = gr[n+round(.005*sr)-1]/target
    end = n+round(.2*sr)
    release = gr[end+round(.015*sr)-1]/gr[end-1]
    assert attack == pytest.approx(1-math.exp(-1), rel=.01)
    assert release == pytest.approx(math.exp(-1), rel=.01)
    print('compressor_tau', sr, attack, release)


def test_expander_static_hold_and_upward(enabled):
    for db in [-80, -60, -50, -45, -39, -20]:
        x = np.full((32000, 1), 10**(db/20))
        y = render('mb_expander', x, dict(crossovers_hz=[], knee_db=0, hold_ms=[0]))
        assert dbgain(x[-1000:], y[-1000:]) == pytest.approx(max(min(db+45, 0), -24), abs=.3)
        if db >= -39:
            assert y.tobytes() == x.tobytes()
    sr = 16000
    x = np.r_[np.full(800, .1), np.full(8000, .001)][:, None]
    p = dict(crossovers_hz=[], threshold_db=[-40], range_db=[-24], hold_ms=[20], release_ms=[50], knee_db=0)
    y = render('mb_expander', x, p, sr)
    g = 20*np.log10(y[:, 0]/x[:, 0])
    assert np.all(g[800:1120] == 0)
    assert g[1120+800-1] == pytest.approx(-20*(1-math.exp(-1)), abs=.04)
    z = render('mb_expander', np.full((8000, 1), .1), dict(crossovers_hz=[], up_gain_db=[6], knee_db=0))
    assert dbgain(np.full((1000, 1), .1), z[-1000:]) == pytest.approx(6, abs=.01)


def test_compressor_upward_floor_plateau_range(enabled):
    for db, expected in [(-100, 0), (-48, 6), (-36, 3), (-27, 0), (-6, -4)]:
        x = np.full((8000, 1), 10**(db/20))
        p = dict(crossovers_hz=[], up_threshold_db=[-30], threshold_db=[-24],
                 knee_db=0, detector='peak', attack_ms=[1], release_ms=[5], range_db=[4])
        y = render('mb_compressor', x, p)
        assert dbgain(x[-1000:], y[-1000:]) == pytest.approx(expected, abs=.01)


def test_parallel_identity_alignment_and_saturator(enabled):
    x = H.impulse(at_s=.05, sr=16000, seconds=.2, channels=2)
    assert render('parallel_comp', x, dict(wet_db=-90, dry_db=0)).tobytes() == x.tobytes()
    noise = H.white_noise(-12, sr=16000, seconds=.15, channels=2)
    p = dict(dry_db=-90, wet_db=-6, wet_makeup_db=12, attack_ms=1, detector='rms')
    y = render('parallel_comp', noise, p)
    cp = dict(threshold_db=-30, ratio=10, knee_db=3, attack_ms=1, release_ms=80,
              detector='rms', rms_window_ms=5, makeup_db=12)
    assert H.null(y, render('compressor', noise, cp)*10**(-6/20))['peak_dbfs'] <= -120
    for drive in [0, 12, 24]:
        dry = render('parallel_comp', x, dict(wet_db=-90, wet_drive_db=drive))
        wet = render('parallel_comp', x, dict(dry_db=-90, wet_db=0, wet_drive_db=drive, ratio=1))
        assert H.latency(wet, dry, method='correlation') == 0
    from mankomix.dsp.reference.nonlinear import saturator
    wet = render('parallel_comp', noise, dict(dry_db=-90, wet_db=0, wet_makeup_db=0, ratio=1, wet_drive_db=12))
    expected = saturator(noise, 16000, dict(mode='tanh', drive_db=12, oversample=4, mix=1, output_db=0))[0]
    assert H.null(wet, expected)['peak_dbfs'] <= -120


@pytest.mark.parametrize('sr', [16000, 44100, 48000, 96000])
def test_parallel_spec_default_burst(enabled, sr):
    x = H.tone_burst(sr=sr, seconds=.6)
    y = render('parallel_comp', x, sr=sr)
    peak = H.peak_dbfs(y[:round(.01*sr)])-H.peak_dbfs(x[:round(.01*sr)])
    tail = dbgain(x[round(.1*sr):round(.3*sr)], y[round(.1*sr):round(.3*sr)])
    assert peak <= 1
    assert tail >= 3
    print('parallel_default_burst', sr, dict(peak_db=peak, tail_db=tail))


def test_band_pan_neutral_protection_width_and_balance(enabled):
    x = H.white_noise(-18, seconds=.2, sr=16000, channels=2)
    assert H.null(x, render('band_pan', x))['peak_dbfs'] <= -120
    p = dict(crossovers_hz=[80, 2000], pan=[1, 0, 0], width=[0, 1, 1])
    result = E.render_chain(x, 16000, [{'type': 'band_pan', 'params': p}], stage='track')
    assert H.null(result.audio, x)['peak_dbfs'] <= -120
    assert result.steps[0]['stats']['ignored_pan_width_bands'] == [0]
    mono = render('band_pan', x, dict(crossovers_hz=[], width=[0], lo_protect_hz=0))
    assert H.null(mono[:, 0], mono[:, 1])['peak_dbfs'] <= -120
    with pytest.raises(ParamError):
        render('band_pan', x[:, :1])
    with pytest.raises(ParamError):
        E.render_chain(x, 16000, [{'type': 'band_pan', 'channel': 'side'}], stage='track')
    for band, f in enumerate([50, 600, 6500]):
        tone = H.sine(f, -18, sr=16000, seconds=.6, channels=2)
        y = render('band_pan', tone, dict(pan=[0, 1, 0], lo_protect_hz=0))
        if band == 1:
            assert H.peak_dbfs(y[3000:-3000, :1]) <= -120
        else:
            assert abs(dbgain(y[3000:-3000, :1], y[3000:-3000, 1:])) <= .1


def test_band_pan_swap_and_measurements(enabled):
    from mankomix.dsp.reference.space import mono_fold
    x = H.white_noise(-18, seconds=.2, sr=16000, channels=2)
    p = dict(pan=[-.7, .4, .9], width=[0, 1.3, 2], level_db=[-1, 2, 0], lo_protect_hz=0)
    y = render('band_pan', x, p)
    swap = render('band_pan', x[:, ::-1], dict(p, pan=[-v for v in p['pan']]))
    assert y[:, ::-1].tobytes() == swap.tobytes()
    result = E.render_chain(x, 16000, [{'type': 'band_pan', 'params': p}], stage='track')
    assert result.steps[0]['stats']['mono'] == mono_fold(y[:, 0], y[:, 1])


@pytest.mark.parametrize('shape', ['sine', 'triangle', 'square', 'random'])
def test_tremolo_absolute_blocks_and_seed(enabled, shape):
    p = P.validate_params('tremolo', dict(lfo_shape=shape, stereo_phase=.5, origin_s=.031, seed=4, bias=.2))
    x = np.ones((12000, 2))*.1
    full = TR.tremolo(x, 16000, p, seed=23)[0]
    for size in [64, 1024]:
        y = np.concatenate([TR.tremolo(x[i:i+size], 16000, p, seed=23, start_sample=i)[0]
                            for i in range(0, len(x), size)])
        assert full.tobytes() == y.tobytes()
    assert full[1733:].tobytes() == TR.tremolo(x[1733:], 16000, p, seed=23, start_sample=1733)[0].tobytes()
    if shape == 'random':
        assert full.tobytes() != TR.tremolo(x, 16000, p, seed=24)[0].tobytes()


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_tremolo_valleys_phase_period_and_square(enabled, sr):
    x = np.full((sr, 2), .1)
    p = P.validate_params('tremolo', dict(depth=1, depth_db=12, stereo_phase=.5))
    y = TR.tremolo(x, sr, p)[0]
    gains = 20*np.log10(y/x)
    assert np.min(gains[:, 0]) == pytest.approx(-12, abs=.1)
    assert np.max(gains[:, 0]) == pytest.approx(0, abs=.1)
    assert np.corrcoef(gains.T)[0, 1] == pytest.approx(-1, abs=1e-8)
    np.testing.assert_allclose(gains[:, 0]+gains[:, 1], -12, atol=1e-12)
    q = dict(p, stereo_phase=0)
    assert np.array_equal(TR.tremolo(x, sr, q)[0][:, 0], TR.tremolo(x, sr, q)[0][:, 1])
    # Probe each note after 1000 periods without allocating the full timeline.
    for note in P.NOTE_VALUES[1:]:
        q = dict(p, note=note, bpm=137, depth_db=6)
        period = P.note_ms(note, 137)*sr/1000
        for cycle in [1, 1000]:
            target = (cycle+.25)*period
            begin = round(target)-2
            m = TR.modulation(5, sr, q, channels=1, start_sample=begin)[:, 0]
            assert abs(begin+np.argmax(m)-target) <= 1
    q = dict(p, lfo_shape='square', stereo_phase=0, square_smooth_ms=3)
    m = TR.modulation(sr//2, sr, q, channels=1)[:, 0]
    edge = round(.1*sr)
    reached = np.flatnonzero(m[edge:] <= -1+2/math.e)[0]+1
    assert reached/sr*1000 == pytest.approx(3, rel=.2)
    assert render('tremolo', x, dict(depth=0, mode='harmonic'), sr).tobytes() == x.tobytes()


def test_harmonic_opposed_envelopes_and_pink_rms(enabled):
    sr = 16000
    phases = []
    for freq in [200, 3200]:
        x = H.sine(freq, -18, sr=sr, seconds=2)
        y = render('tremolo', x, dict(mode='harmonic'))
        # Analytic amplitude away from the endpoints; 5 Hz phasor is robust
        # against carrier residuals and LR4 allpass phase.
        env = np.abs(signal.hilbert(y[:, 0]))
        n = np.arange(8000, 24000)
        phases.append(np.angle(np.sum(env[n]*np.exp(-2j*np.pi*5*n/sr))))
    difference = abs(np.angle(np.exp(1j*(phases[0]-phases[1]))))*180/np.pi
    assert difference == pytest.approx(180, abs=5)
    x = H.pink_noise(-18, seconds=5, sr=sr)
    y = render('tremolo', x, dict(mode='harmonic'))
    # Fold 20 complete cycles into 25 ms phase bins. Measure the repeatable
    # RMS modulation without mistaking pink-noise randomness for tremolo.
    gains = []
    for phase in range(8):
        indices = np.concatenate([np.arange(cycle*3200+phase*400, cycle*3200+(phase+1)*400)
                                  for cycle in range(4, 24)])
        gains.append(dbgain(x[indices], y[indices]))
    variation = max(gains)-min(gains)
    assert variation <= 1.5
    print('harmonic', dict(phase_difference_deg=difference, rms_variation_db=variation))


@pytest.mark.parametrize('kind', KINDS)
def test_literal_tables_and_rendered_bounds(enabled, kind):
    # Independently list every numeric declaration, including array defaults.
    tables = {
        'mb_compressor': [('threshold_db', -60, 0, []), ('ratio', 1, 30, []), ('attack_ms', .05, 300, []),
            ('release_ms', 5, 3000, []), ('makeup_db', -12, 24, []), ('range_db', 0, 48, []),
            ('up_threshold_db', -80, 0, []), ('up_ratio', 1, 10, []), ('up_max_gain_db', 0, 24, []),
            ('knee_db', 0, 24, 6), ('rms_window_ms', 1, 300, 10)],
        'mb_expander': [('threshold_db', -80, 0, []), ('ratio', 1, 100, []), ('range_db', -90, 0, []),
            ('attack_ms', .05, 300, []), ('hold_ms', 0, 2000, []), ('release_ms', 5, 3000, []),
            ('up_gain_db', 0, 12, []), ('knee_db', 0, 24, 6)],
        'parallel_comp': [('threshold_db', -60, 0, -30), ('ratio', 1, 30, 10), ('knee_db', 0, 24, 3),
            ('attack_ms', .05, 300, .1), ('release_ms', 5, 3000, 80), ('rms_window_ms', 1, 300, 5),
            ('wet_makeup_db', -12, 36, 17), ('wet_hpf_hz', 0, 1000, 0), ('wet_drive_db', 0, 24, 0),
            ('dry_db', -90, 12, -6), ('wet_db', -90, 12, -6)],
        'band_pan': [('pan', -1, 1, []), ('width', 0, 2, []), ('level_db', -12, 12, []), ('lo_protect_hz', 0, 300, 120)],
        'tremolo': [('rate_hz', .01, 20, 5), ('bpm', 0, 400, 0), ('depth', 0, 1, .5),
            ('stereo_phase', 0, 1, 0), ('origin_s', 0, 36000, 0), ('phase', 0, 1, 0), ('seed', 0, 65535, 0),
            ('depth_db', 0, 48, 6), ('square_smooth_ms', .5, 20, 3), ('crossover_hz', 200, 4000, 800), ('bias', 0, 1, 0)],
    }
    params = P.describe(kind)['params']
    numbers = [(v['id'], v['min'], v['max'], v['default']) for v in params if v['type'] in ('float', 'int', 'float_array')]
    mb = [('crossovers_hz', 20, 20000, [200, 2000] if kind == 'band_pan' else [150, 2500])] if kind in ('mb_compressor', 'mb_expander', 'band_pan') else []
    assert numbers == mb+tables[kind]
    x = H.white_noise(-20, seconds=.008, sr=96000, channels=2)
    assert np.array_equal(direct(kind, x, sr=96000), direct(kind, x, P.validate_params(kind, {}), sr=96000))
    for item in params:
        pid = item['id']
        if item['type'] in ('float', 'int', 'float_array'):
            for v in [item['min'], item['max']]:
                p = {pid: v}
                if item['type'] == 'float_array':
                    p[pid] = [v] if pid == 'crossovers_hz' else [v]*3
                if kind == 'mb_compressor' and pid == 'up_threshold_db':
                    p['threshold_db'] = [0]*3
                y = direct(kind, x, p, 96000)
                assert np.isfinite(y).all(), (kind, pid, v)
        elif item['type'] in ('enum', 'bool'):
            for v in item.get('choices', [True, False]):
                p = {pid: v}
                if pid == 'note' and v != 'none':
                    p['bpm'] = 120
                assert np.isfinite(direct(kind, x, p, 96000)).all()


@pytest.mark.parametrize('kind', ['mb_compressor', 'mb_expander', 'band_pan'])
def test_mb_runtime_validation(enabled, kind):
    x = np.zeros((64, 2))
    key = 'pan' if kind == 'band_pan' else 'threshold_db'
    for p in [dict(crossovers_hz=[150, 150]), dict(crossovers_hz=[300, 150]),
              dict(crossovers_hz=[7900]), {key: [1, 2]}, {key: [math.nan]*3}]:
        with pytest.raises(ParamError):
            render(kind, x, p)
    if kind == 'mb_compressor':
        with pytest.raises(ParamError):
            render(kind, x, dict(up_threshold_db=[-10]*3))


@pytest.mark.parametrize('kind', KINDS)
def test_registration_stages_time_varying(enabled, kind):
    from mankomix.dspx.registry import time_varying_types
    spec = P.describe(kind)
    assert spec['backends'] == ['reference']
    assert not spec['offline_only'] and spec['realtime']['allocates']
    assert (kind in time_varying_types()) == (kind != 'band_pan')
    if kind in ('mb_compressor', 'mb_expander', 'parallel_comp'):
        assert spec['master_slot'] == 2
        E.validate_chain([{'type': 'eq'}, {'type': kind}, {'type': 'limiter'}], stage='master')
        with pytest.raises(ChainError):
            E.validate_chain([{'type': 'limiter'}, {'type': kind}], stage='master')
    else:
        assert spec['stages'] == ['track', 'bus'] and spec['master_slot'] is None
    assert 'mix' not in P.validate_params('tremolo', {})


@pytest.mark.parametrize('kind', KINDS)
def test_common_contracts(enabled, monkeypatch, kind):
    params, neutral, extra = {}, {}, {}
    if kind in ('mb_compressor', 'mb_expander'):
        params = dict(phase='linear', ratio=[1]*3)
        neutral = params
        extra['declared_latency'] = MC.latency_samples
        extra['latency_probe'] = lambda x, sr, p, **kw: MODULES[kind].IMPLS[kind](x, sr, p, compensate=False)[0]
    elif kind == 'parallel_comp':
        params = neutral = dict(wet_db=-90, dry_db=0)
    elif kind == 'band_pan':
        # This type explicitly rejects mono, so run the shared acoustic probes
        # with stereo generators; mono rejection is independently asserted.
        for name in ('impulse', 'sine'):
            original = getattr(H, name)
            def stereo(*args, _original=original, **kw):
                kw['channels'] = 2
                return _original(*args, **kw)
            monkeypatch.setattr(H, name, stereo)
        extra['declared_latency'] = MC.latency_samples
        extra['latency_probe'] = lambda x, sr, p, **kw: BP.band_pan(x, sr, p, compensate=False)[0]
    else:
        params = neutral = dict(depth=0)
    def probe(x, y, sr, p):
        # Neutral path: measure carrier and gain, not just shape/finiteness.
        freq = H.fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
        change = dbgain(x, y)
        return dict(passed=abs(freq-1000)<1 and abs(change)<.01, frequency_hz=freq, gain_db=change)
    result = H.assert_common_tests(kind, params=params, neutral=neutral, seconds=.03,
                                   sr_probe=probe, **extra)
    assert all(result[f'CT-{i}']['passed'] for i in range(1, 9))


def test_tempo_runtime_rejection(enabled):
    for p in [dict(note='1/4'), dict(bpm=10), dict(mode='harmonic', crossover_hz=4000)]:
        with pytest.raises(ParamError):
            render('tremolo', np.zeros((64, 2)), p, sr=8000)


@pytest.mark.parametrize('kind', ['parallel_comp', 'tremolo'])
def test_completed_acceptance_is_advertised(kind):
    assert P.PROCESSORS[kind]['implemented'] is True
    assert MODULES[kind].SPECS[0]['implemented'] is True
    E.validate_chain([{'type': kind}], stage='track')


def test_random_lfo_limits_and_direct_item_seed(enabled):
    p = P.validate_params('tremolo', dict(lfo_shape='random', rate_hz=1))
    a = TR.modulation(100000, 1000, p, channels=1, seed=12, item_id='a')[:, 0]
    b = TR.modulation(100000, 1000, p, channels=1, seed=12, item_id='b')[:, 0]
    assert a.tobytes() != b.tobytes()
    assert a[1001:2001].tobytes() == TR.modulation(1000, 1000, p, channels=1,
                                                seed=12, item_id='a', start_sample=1001)[:, 0].tobytes()
    # Same 100 s / 1 kHz / Hann probe as W1e, now requiring <= -100 dB.
    spectrum = np.abs(np.fft.rfft((a-np.mean(a))*np.hanning(len(a))))**2
    freq = np.fft.rfftfreq(len(a), 1/1000)
    leakage = 10*np.log10(np.sum(spectrum[freq > 1])/np.sum(spectrum))
    assert leakage <= -100
    x = np.full((32000, 1), .1)
    def item(identifier):
        return E.render_chain(x, 16000, [{'id': identifier, 'type': 'tremolo', 'params': p}],
                              stage='track', seed=12).audio
    assert item('a').tobytes() != item('b').tobytes()
    assert TR.SPECS[0]['implemented']
    print('random_bandwidth_above_rate_db', leakage)


@pytest.mark.parametrize('kind', ['mb_compressor', 'mb_expander', 'band_pan'])
def test_all_band_arrays_and_maximum_band_count(enabled, kind):
    x = H.white_noise(-20, sr=48000, seconds=.04, channels=2)
    arrays = [v for v in P.describe(kind)['params'] if v['type'] == 'float_array' and v['id'] != 'crossovers_hz']
    for count, edges in [(1, []), (6, [40, 150, 1000, 5000, 15000])]:
        p = dict(crossovers_hz=edges, phase='linear')
        if kind != 'band_pan':
            p['ratio'] = [1]*count
        y = render(kind, x, p, sr=48000)
        assert H.null(x, y)['peak_dbfs'] <= -120
        for arr in arrays:
            bad = dict(p, **{arr['id']: [arr['min']]*(count+1)})
            with pytest.raises(ParamError):
                render(kind, x, bad, sr=48000)


def test_tremolo_and_band_pan_spatial_records(enabled):
    from mankomix.dspx.bb.delayline import spatial_stats
    x = H.white_noise(-20, sr=16000, seconds=.2, channels=2)
    for kind, params in [('band_pan', dict(pan=[.5, 0, -.3])),
                         ('tremolo', dict(stereo_phase=.5)), ('tremolo', dict(mode='harmonic'))]:
        result = E.render_chain(x, 16000, [{'type': kind, 'params': params}], stage='track')
        expected = spatial_stats(result.audio, 16000)
        for key, value in expected.items():
            if key == 'latency_samples':
                continue  # band_pan also reports its compensated FIR delay.
            assert result.steps[0]['stats'][key] == value


@pytest.mark.parametrize('kind', ['mb_compressor', 'mb_expander', 'parallel_comp', 'tremolo'])
def test_active_common_contracts(enabled, kind):
    # Run CT-1/2/3/6/8 with the actual dynamic defaults as well as the neutral
    # shared tests. Isolate the processing delay with a neutral latency probe.
    if kind in ('mb_compressor', 'mb_expander'):
        neutral = dict(phase='linear', ratio=[1]*3)
        lp = dict(crossovers_hz=[], ratio=[1])
    elif kind == 'parallel_comp':
        neutral = lp = dict(wet_db=-90, dry_db=0)
    else:
        neutral = lp = dict(depth=0)
    def probe(x, y, sr, p):
        # Carrier frequency is independent of the gain/modulation clock. Tau,
        # valley depth and synchronized frequency have separate acoustic tests.
        freq = H.fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
        return dict(passed=abs(freq-1000)<1, carrier_hz=freq)
    H.assert_common_tests(kind, neutral=neutral, latency_params=lp,
                          seconds=.06, sr_probe=probe)


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_expander_attack_hold_release_across_rates(enabled, sr):
    cell = round(.2*sr)
    x = np.r_[np.full(cell, .001), np.full(cell, .1), np.full(cell, .001)][:, None]
    p = dict(crossovers_hz=[], threshold_db=[-40], range_db=[-24], ratio=[2],
             knee_db=0, attack_ms=[5], hold_ms=[10], release_ms=[15])
    y = render('mb_expander', x, p, sr)
    g = 20*np.log10(y[:, 0]/x[:, 0])
    attack = g[cell+round(.005*sr)-1]/g[cell-1]
    end, hold = 2*cell, round(.01*sr)
    assert np.max(np.abs(g[end:end+hold])) < 1e-9
    release = g[end+hold+round(.015*sr)-1]/-20
    assert attack == pytest.approx(math.exp(-1), rel=.01)
    assert release == pytest.approx(1-math.exp(-1), rel=.01)
    print('expander_tau', sr, attack, release)


@pytest.mark.parametrize('kind,values', [
    ('mb_compressor', dict(threshold_db=-24, ratio=2, attack_ms=10, release_ms=150,
                           makeup_db=0, range_db=48, up_ratio=2, up_max_gain_db=6)),
    ('mb_expander', dict(threshold_db=-45, ratio=2, range_db=-24, attack_ms=2,
                         hold_ms=20, release_ms=150, up_gain_db=0)),
    ('band_pan', dict(pan=0, width=1, level_db=0)),
])
def test_empty_arrays_render_as_literal_spec_defaults(enabled, kind, values):
    x = H.white_noise(-20, seconds=.08, sr=16000, channels=2)
    explicit = {key: [value]*3 for key, value in values.items()}
    assert render(kind, x).tobytes() == render(kind, x, explicit).tobytes()
