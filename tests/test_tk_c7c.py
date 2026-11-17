"""C7c: closure regressions beyond the original measured W3c acceptance."""
import numpy as np
import pytest

from mankomix.dsp import processors as P
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb import ar
from mankomix.dspx.bb.restoration import runs
from mankomix.dspx.procs import declick as C
from tests import toolimpl_harness as H


@pytest.mark.parametrize('kind', C.KIND_DEFAULTS)
def test_kind_defaults_preserve_all_explicit_overrides(kind):
    raw = {'kind': kind, **C.KIND_DEFAULTS['click']}
    before = dict(raw)
    resolved = P.validate_params('declick', raw)
    assert raw == before
    for pid, value in C.KIND_DEFAULTS['click'].items():
        assert resolved[pid] == value
    omitted = P.validate_params('declick', {'kind': kind})
    for pid, value in C.KIND_DEFAULTS[kind].items():
        assert omitted[pid] == value


def test_conditional_defaults_are_exposed_in_schema():
    variants = P.graph_schema()['items']['oneOf']
    params = next(v['properties']['params'] for v in variants
                  if v['properties']['type']['const'] == 'declick')
    assert 'default' not in params['properties']['threshold']
    for branch in params['allOf'][:3]:
        kind = branch['if']['properties']['kind']['const']
        assert {pid: spec['default'] for pid, spec in branch['then']['properties'].items()} == C.KIND_DEFAULTS[kind]


@pytest.mark.parametrize('kind', [[], {}, None, True])
def test_invalid_kind_uses_the_public_parameter_error(kind):
    with pytest.raises(ParamError):
        P.validate_params('declick', {'kind': kind})


def test_min_run_default_change_has_a_measured_upper_bound():
    x = H.vowel(sr=8000, seconds=.1)[:, 0]
    level = max(abs(x))*10**(-6/20)
    z = np.clip(x, -level, level)
    error = (x-z)**2
    ceilings = {}
    for minimum in (2, 3):
        oracle = z.copy()
        for a, b in runs(abs(z) >= level):
            if b-a >= minimum:
                oracle[a:b] = x[a:b]
        ceilings[minimum] = 10*np.log10(sum(error)/sum((x-oracle)**2))
    assert ceilings[3] < 6 < ceilings[2]
    assert P.validate_params('declip', {})['min_run'] == 2


def test_joint_lsar_recovers_neighboring_holes_without_changing_observations():
    omega = 2*np.pi*700/8000
    x = .3*np.sin(omega*np.arange(240))
    missing = abs(x) > .17
    z = np.clip(x, -.17, .17)
    model = np.array([1., -2*np.cos(omega), 1.])
    y, info = ar.joint_lsar(z, missing, models=[model, model],
                             lower=np.where(z > 0, .17, -np.inf),
                             upper=np.where(z < 0, -.17, np.inf))
    assert H.rms_dbfs((y-x)[missing]) < -100
    assert y[~missing].tobytes() == z[~missing].tobytes()
    assert np.all(y[missing]*np.sign(z[missing]) >= .17)
    assert 1 <= info['iterations'] <= 8


def test_observed_model_ignores_values_inside_holes():
    x = H.vowel(sr=8000, seconds=.1)[:, 0]
    mask = abs(x) > .12
    damaged = x.copy()
    damaged[mask] = 100*np.arange(mask.sum())
    a = ar.robust_observed_model(x, mask, 16)
    b = ar.robust_observed_model(damaged, mask, 16)
    np.testing.assert_array_equal(a, b)


@pytest.mark.parametrize('bad', [0, 9])
def test_joint_lsar_rejects_invalid_iteration_limits(bad):
    with pytest.raises(ParamError):
        ar.joint_lsar(np.zeros(8), np.ones(8, bool), models=[np.ones(1)]*2, iterations=bad)


def test_periodic_repair_uses_observed_period_with_another_pitch():
    sr = 16000
    x = H.vowel(f0=125, sr=sr, seconds=.4)
    z = x.copy()
    positions = [1760, 2521, 3397, 4702]
    for index, a in enumerate(positions):
        z[a:a+7+index*3] += (-1)**index*.2
    p = P.validate_params('declick', {})
    y, _, stats = C.declick(z, sr, p)
    assert H.rms_dbfs(y-x) < -60
    assert stats['detected_event_count'] >= len(positions)
    assert y.tobytes() == C.declick(z, sr, p)[0].tobytes()


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('channels', [1, 2])
def test_actual_repair_at_declared_sample_rates(sr, channels):
    t = np.arange(round(.06*sr))/sr
    x = np.repeat((.15*np.sin(2*np.pi*223*t)+.08*np.sin(2*np.pi*503*t)+
                   .04*np.sin(2*np.pi*997*t))[:, None], channels, axis=1)
    a, b = round(.03*sr), round(.031*sr)
    damaged = x.copy()
    damaged[a:b] += .5
    y, _, _ = C.declick(damaged, sr, P.validate_params('declick', {'protect_transients': 0}))
    assert H.rms_dbfs((y-x)[a:b]) < -30
    from mankomix.dspx.procs.declip import declip
    level = np.max(abs(x))*10**(-6/20)
    clipped = np.clip(x, -level, level)
    repaired, _, stats = declip(clipped, sr, P.validate_params('declip', {'headroom': 'none'}))
    selected = abs(clipped) >= level
    improvement = 10*np.log10(np.sum((clipped-x)[selected]**2)/np.sum((repaired-x)[selected]**2))
    assert improvement >= 6
    assert stats['clipped_sample_fraction'] > 0
    assert repaired[~selected].tobytes() == clipped[~selected].tobytes()
