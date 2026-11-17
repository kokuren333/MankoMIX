"""C2: measured RT60 boundaries with backward-compatible BB-10 defaults."""
import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import processors as P, engine as E
from mankomix.dspx.bb import reverb as R
from tests import toolimpl_harness as H


@pytest.mark.parametrize("kind,rt", [("reverb_hall",20),("reverb_chamber",8),
                                   ("reverb_hall",6),("reverb_chamber",6)])
def test_longest_band_boundary_preserves_declared_rt60(kind,rt):
    sr=24000
    p=P.validate_params(kind,dict(rt60_s=rt,rt60_low_mult=24/rt,rt60_high_mult=24/rt,
                                 mix=1,lowcut_hz=20,highcut_hz=20000))
    # Twenty-four seconds contains 60 dB of the longest decay; T20 fits only
    # -5..-25 dB, well before this finite measurement window ends.
    h=R.render_ir(sr,p,chamber=kind.endswith("chamber"),frames=24*sr,absorption_order=4)
    measured=H.octave_rt60(h.sum(axis=1),sr,centers_hz=(125,1000,8000))
    targets={125:24,1000:rt,8000:24}
    print(kind,"base RT60",rt,"boundary T20",measured,"targets",targets)
    assert set(measured) == set(targets)
    for band, target in targets.items():
        assert abs(measured[band]/target-1) <= .1


@pytest.mark.parametrize("kind", ["reverb_hall","reverb_chamber"])
def test_default_rt_vector(kind):
    p=P.validate_params(kind,{})
    h=R.render_ir(32000,p,chamber=kind.endswith("chamber"),absorption_order=4)
    measured=H.octave_rt60(h.sum(axis=1),32000,centers_hz=(125,1000,8000))
    targets={125:p["rt60_s"]*p["rt60_low_mult"],1000:p["rt60_s"],
             8000:p["rt60_s"]*p["rt60_high_mult"]}
    print(kind,"default T20",measured,"targets",targets)
    assert set(measured) == set(targets)
    for band, target in targets.items():
        assert abs(measured[band]/target-1) <= .1


@pytest.mark.parametrize("kind,rt,depth", [("reverb_hall",20,0),("reverb_hall",20,1),
                                         ("reverb_chamber",8,0)])
def test_maximum_decay_engine_ct8(kind,rt,depth):
    # Complement W2b's untruncated core measurement with the full processor:
    # normalization, wet filtering and the engine/item seed path.
    sr=4000
    p=dict(rt60_s=rt,rt60_low_mult=24/rt,rt60_high_mult=24/rt,
           lowcut_hz=20,highcut_hz=20000,mix=1)
    if kind == "reverb_hall":
        p.update(mod_depth=depth,mod_rate_hz=.05)
    x=np.zeros((61*sr,2))
    x[:sr]=np.random.Generator(np.random.PCG64(15)).choice([-1.,1.],(sr,2))
    y=E.render_chain(x,sr,[{"id":"maximum_room","type":kind,"params":p}],stage="bus",seed=15).audio
    tail=H.peak_dbfs(y[-sr:])
    print(kind,"mod depth",depth,"maximum decay CT8 engine tail dBFS",tail)
    assert np.isfinite(y).all() and tail < -120


def test_hall_feedback_interpolation_has_no_gain_above_unity():
    x=np.zeros((64,1)); x[8]=1
    for fraction in np.linspace(0,1,129):
        h=R.fractional_delay(x,3+fraction,"lagrange3")[:,0]
        gain=abs(signal.freqz(h,worN=2048)[1])
        assert gain.max() <= 1+1e-12
