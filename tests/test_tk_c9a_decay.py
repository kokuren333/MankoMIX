"""C9a: uninterrupted CT-8 boundary and final-release decay measurements."""
import json
from pathlib import Path

import numpy as np
import pytest

from mankomix.dsp import processors as P
from mankomix.dspx.bb import reverb as R
from mankomix.dspx.bb.vintage import VintageTank
from tests import toolimpl_harness as H

METRICS = {}


@pytest.fixture(scope='module', autouse=True)
def save_measurements():
    yield
    Path('_private/tool_impl/logs/C9a_decay_measurements.json').write_text(
        json.dumps(METRICS, indent=2, sort_keys=True)+'\n', encoding='utf8', newline='\n')


@pytest.mark.parametrize('kind,options', [
    ('reverb_freeze', dict(rt60_s=24, size_m=60, diffusion=1, damping_hz=20000, mod_depth=1)),
    ('reverb_vintage', dict(rt60_s=12, bass_mult=2, input_diffusion=1,
        tank_diffusion=1, damping_hz=20000, bandwidth_hz=20000, mod_depth=1, mod_rate_hz=3)),
    ('reverb_vintage', dict(rt60_s=20, bass_mult=1.2, damping_hz=20000, mod_depth=0)),
])
def test_ct8_boundary_full_minute_and_untruncated_tail(kind, options):
    sr = 2000
    p = P.validate_params(kind, dict(options, mix=1, lowcut_hz=20, highcut_hz=20000, predelay_ms=250))
    x = np.zeros((120*sr, 2))
    x[:60*sr] = np.random.Generator(np.random.PCG64(15)).choice([-1., 1.], (60*sr, 2))
    cls = R.FreezeFDN if kind.endswith('freeze') else VintageTank
    wet = cls(sr, p, seed=17).process(x)
    # The uninterrupted state is measured both before and after wet shaping.
    raw_peak = H.peak_dbfs(wet[-sr:])
    y = R._tv_wet_shape(x, wet, sr, p)
    peak = H.peak_dbfs(y[-sr:])
    METRICS[kind+'_boundary_'+str(options['rt60_s'])] = dict(raw_dbfs=raw_peak, wet_dbfs=peak)
    assert np.isfinite(y).all() and raw_peak < -120 and peak < -120


@pytest.mark.parametrize('mode', ['mute', 'pass'])
def test_ct8_clock_starts_after_final_freeze_release(mode):
    sr = 2000
    p = P.validate_params('reverb_freeze', dict(rt60_s=24, size_m=60,
        freeze_start_s=[.7, 5], freeze_end_s=[3, 65], freeze_fade_ms=2000,
        freeze_input=mode, mix=1, lowcut_hz=20, highcut_hz=20000))
    # The second hold extends past 60 seconds after input stops. The decay
    # clock starts at the later of input stop and the final release ramp end.
    x = np.zeros((127*sr, 2))
    x[:sr] = np.random.Generator(np.random.PCG64(15)).choice([-1., 1.], (sr, 2))
    y = R.FreezeFDN(sr, p, seed=17).process(x)
    during = H.peak_dbfs(y[64*sr:65*sr])
    released = H.peak_dbfs(y[-sr:])
    METRICS['freeze_release_'+mode] = dict(held_dbfs=during, after_60s_dbfs=released)
    assert during > -120 and released < -120 and np.isfinite(y).all()

