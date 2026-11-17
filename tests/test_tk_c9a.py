"""C9a: decay boundaries, release clock, band accuracy and send monotonicity."""
import json
from pathlib import Path

import numpy as np
import pytest

from mankomix.dsp import processors as P, engine as E
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb import reverb as R
from mankomix.dspx.bb.vintage import VintageTank
from tests import toolimpl_harness as H

METRICS = {}


@pytest.fixture(scope='module', autouse=True)
def save_measurements():
    yield
    Path('_private/tool_impl/logs/C9a_measurements.json').write_text(
        json.dumps(METRICS, indent=2, sort_keys=True)+'\n', encoding='utf8', newline='\n')


@pytest.mark.parametrize('kind,valid,invalid', [
    ('reverb_freeze', dict(rt60_s=24), dict(rt60_s=24.000001)),
    ('reverb_vintage', dict(rt60_s=12, bass_mult=2), dict(rt60_s=12.000001, bass_mult=2)),
    ('reverb_vintage', dict(rt60_s=20, bass_mult=1.2), dict(rt60_s=20, bass_mult=2)),
    ('reverb_vintage', dict(rt60_s=20, bass_mult=.5), dict(rt60_s=20, bass_mult=1.200001)),
])
def test_decay_relationships_at_both_entry_points(kind, valid, invalid):
    from importlib import import_module
    fn = import_module('mankomix.dspx.procs.'+kind).IMPLS[kind]
    p = P.validate_params(kind, valid)
    assert fn(np.zeros((8, 1)), 4000, dict(p, mix=0))[0].shape == (8, 1)
    with pytest.raises(ParamError, match='24 s'):
        P.validate_params(kind, invalid)
    with pytest.raises(ParamError, match='24 s'):
        fn(np.zeros((8, 1)), 4000, dict(p, **invalid, mix=0))


@pytest.mark.parametrize('kind', ['reverb_freeze', 'reverb_vintage'])
def test_old_maximum_is_measured_and_rejected(kind):
    sr = 4000
    p = P.validate_params(kind, {})
    p.update(rt60_s=60 if kind.endswith('freeze') else 20,
             mix=1, lowcut_hz=20, highcut_hz=20000, mod_depth=0)
    p.update(size_m=60) if kind.endswith('freeze') else p.update(bass_mult=2)
    x = np.zeros((61*sr, 2))
    x[:sr] = np.random.Generator(np.random.PCG64(7)).choice([-1., 1.], (sr, 2))
    cls = R.FreezeFDN if kind.endswith('freeze') else R.VintageTank
    y = cls(sr, p, seed=17).process(x)
    peak = H.peak_dbfs(y[-sr:])
    METRICS[kind+'_old_maximum_dbfs'] = peak
    assert peak >= -120
    with pytest.raises(ParamError):
        P.validate_params(kind, p)


@pytest.mark.parametrize('rt,bass', [(.3, .5), (.3, 1.2), (2.5, 1.2), (12, 2), (20, 1.2)])
def test_vintage_band_decay_at_defaults_and_boundaries(rt, bass):
    sr = 24000
    p = P.validate_params('reverb_vintage', dict(rt60_s=rt, bass_mult=bass, mod_depth=0))
    x = np.zeros((round(max(2, rt*max(1, bass)*1.3)*sr), 2)); x[0] = 1
    y = VintageTank(sr, p, seed=17).process(x)
    times = H.octave_rt60(y, sr, centers_hz=(125, 1000, 8000))
    targets = {125: rt*bass, 1000: rt, 8000: rt}
    METRICS['vintage_rt_'+str(rt)+'_bass_'+str(bass)] = dict(measured=times, targets=targets)
    for band, target in targets.items():
        assert times[band] is not None and abs(times[band]/target-1) <= .15, (band, times, targets)


@pytest.mark.parametrize('channels', [1, 2])
def test_shimmer_monotonic_control_grid(channels):
    from tests.test_tk_w3l import burst
    from mankomix.dspx.bb.shimmer import _wet, _normalization
    sr = 8000
    x = np.repeat(burst(sr, seconds=1, length=.15), 2, axis=1)
    p = P.validate_params('reverb_shimmer', dict(rt60_s=2, mix=1, mod_depth=0,
        damping_hz=3500, lowcut_hz=20, highcut_hz=3500))
    late, early = _normalization(sr, 2, p['diffusion'], 3500, p['seed'], 19)
    rows = []
    for amount in (.05, .15, .25, .35, .5, .65, .8, 1):
        wet, _ = _wet(x, sr, dict(p, shimmer=amount), 19, late, early)
        if channels == 1:
            wet = wet.mean(axis=1, keepdims=True)
        row = []
        for start, end in ((.2, .35), (.55, .75)):
            segment = wet[round(start*sr):round(end*sr)]
            a = H.band_level(segment, sr, 420, 460)['rms']
            b = H.band_level(segment, sr, 860, 900)['rms']
            row.append(float(20*np.log10(b/a)))
        rows.append(row)
    METRICS['shimmer_grid_'+str(channels)] = rows
    assert np.all(np.diff(rows, axis=0) > 0)
    assert np.all(np.diff(rows, axis=1) > 0)


def test_vintage_engine_uses_distributed_absorption():
    x = H.impulse(sr=4000, seconds=.4, channels=2)
    result = E.render_chain(x, 4000, [dict(type='reverb_vintage', id='tank',
        params=dict(rt60_s=.3, mix=1))], stage='bus', seed=17)
    assert result.steps[0]['stats']['absorption'] == 'distributed_delay'


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_vintage_decay_uses_seconds_at_physical_sample_rates(sr):
    p = P.validate_params('reverb_vintage', dict(rt60_s=.3, bass_mult=1.2, mod_depth=0))
    x = np.zeros((sr, 2)); x[0] = 1
    y = VintageTank(sr, p, seed=17).process(x)
    measured = H.octave_rt60(y, sr, centers_hz=(125, 1000, 8000))
    METRICS['vintage_sr_'+str(sr)] = measured
    for band, target in ((125, .36), (1000, .3), (8000, .3)):
        assert abs(measured[band]/target-1) <= .15
