"""C11: unspecified model contract and evidence for the blocked report path."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from mankomix.core import config, registry, mixrender, render, report, routes
from mankomix.core.errors import ValidationError
from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb import ml
from mankomix.dspx.procs.denoise_ml import denoise_ml


@pytest.fixture(autouse=True)
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path / 'home'))
    config.clear_cache()
    monkeypatch.setattr(registry, '_open_url', lambda *a: pytest.fail('implicit network'))
    yield
    config.clear_cache()


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('channels', [1, 2])
def test_defaults_validate_and_run_spectral_fallback(sr, channels, monkeypatch):
    monkeypatch.setattr(registry, 'default_model', lambda mode: None)
    monkeypatch.setattr(ml, 'resolve_for_run', lambda *a: pytest.fail('no model selected'))
    p = P.validate_params('denoise_ml', {})
    assert p['model'] == ''
    assert P.validate_params('denoise_ml', {'model': ''}) == p
    x = np.random.Generator(np.random.PCG64(11)).normal(0, .03, (2048, channels))
    y, rsr, stats = denoise_ml(x, sr, p, seed=1)
    assert y.shape == x.shape and y.dtype == np.float64 and rsr == sr
    assert stats['fallback_used'] and stats['fallback']['type'] == 'denoise'
    assert stats['fallback']['params']['profile'] == 'auto'
    assert 'no registered default' in stats['fallback']['reason']
    expected = E.render_chain(x, sr, [dict(type='denoise', params=stats['fallback']['params'])], stage='track')
    assert y.tobytes() == expected.audio.tobytes()
    assert y.tobytes() == denoise_ml(x, sr, p, seed=1)[0].tobytes()


def test_unspecified_model_error_policy_and_neutral_path(monkeypatch):
    monkeypatch.setattr(registry, 'default_model', lambda mode: None)
    x = np.ones((100, 1)) * .01
    p = P.validate_params('denoise_ml', {'fallback': 'error'})
    with pytest.raises(ml.ModelUnavailable, match='no registered default'):
        denoise_ml(x, 48000, p)
    for neutral in ({'amount': 0}, {'reduction_db': 0}):
        p = P.validate_params('denoise_ml', dict(fallback='error', **neutral))
        y, _, stats = denoise_ml(x, 48000, p)
        assert y.tobytes() == x.tobytes()
        assert stats['inference_skipped'] and not stats['fallback_used']


def test_registered_default_is_used_and_explicit_id_wins(monkeypatch):
    modes, selected = [], []
    def default(mode):
        modes.append(mode)
        return 'speech_df3_48k'
    monkeypatch.setattr(registry, 'default_model', default)
    def resolve(mid, kind):
        selected.append((mid, kind))
        return {}
    monkeypatch.setattr(ml, 'resolve_for_run', resolve)
    monkeypatch.setattr(ml, 'infer', lambda x, sr, r: (x * .5, {'fallback_used': False}))
    p = P.validate_params('denoise_ml', {})
    _, _, stats = denoise_ml(np.ones((100, 1)) * .01, 48000, p)
    assert selected == [('speech_df3_48k', 'denoise')]
    assert modes and set(modes) == {'denoise'}
    assert stats['model_id'] == 'speech_df3_48k' and not stats['fallback_used']
    monkeypatch.setattr(registry, 'default_model', lambda mode: pytest.fail('explicit ID must win'))
    P.validate_params('denoise_ml', {'model': 'speech_df3_48k'})


@pytest.mark.parametrize('model', ['missing', 'scnet_4stem', None, 0])
def test_unknown_wrong_kind_and_non_string_still_fail(model):
    with pytest.raises(ParamError):
        P.validate_params('denoise_ml', {'model': model})


@pytest.fixture
def engine_fallback(monkeypatch):
    # Probe the existing engine contract in isolation. The public processor
    # remains unimplemented because the report path below loses its warning.
    monkeypatch.setitem(P.PROCESSORS['denoise_ml'], 'implemented', True)
    backends = E._backends()
    backends['model'] = {}
    monkeypatch.setattr(E, '_backends', lambda: backends)
    fp = P.validate_params('denoise', {'profile': 'auto'})
    chain = [dict(id='speech', type='denoise_ml',
                  fallback=dict(type='denoise', params=fp))]
    x = np.random.Generator(np.random.PCG64(11)).normal(0, .03, (2048, 2))
    res = E.render_chain(x, 48000, chain, stage='track')
    warning = next(w for w in res.warnings if 'rendered with fallback' in w)
    assert '(approximation)' in warning
    assert res.steps[0]['fallback']['type'] == 'denoise'
    expected = E.render_chain(x, 48000, [dict(type='denoise', params=fp)], stage='track')
    assert res.audio.tobytes() == expected.audio.tobytes()
    return x, chain, res, warning


def test_core_keeps_mix_warning_but_discards_step_fallback(engine_fallback, monkeypatch):
    x, chain, res, warning = engine_fallback
    data = dict(timebase=dict(sample_rate=48000, length_samples=len(x)))
    project = SimpleNamespace(data=data)
    ctx = mixrender._Ctx(project, data, 0)
    assert mixrender.engine_chain(chain)[0]['fallback'] == chain[0]['fallback']
    actual, actual_steps = ctx.run_chain(x, chain, 'track')
    assert actual.tobytes() == res.audio.tobytes() and actual_steps[0]['fallback'] == res.steps[0]['fallback']
    # Supply the real engine result to inspect downstream serialization even
    # though engine_chain has already discarded the fallback declaration.
    monkeypatch.setattr(E, 'render_chain', lambda *a, **kw: res)
    _, steps = ctx.run_chain(x, chain, 'track')
    assert warning in ctx.warnings
    assert steps[0]['fallback'] == res.steps[0]['fallback']
    assert render._step_backends(res.steps)[0]['fallback'] == res.steps[0]['fallback']
    # The mastering/report input API returns audio/rate and drops mix metadata.
    monkeypatch.setattr(mixrender, 'render_mix', lambda *a, **kw: (res.audio, res.sr, {'warnings': ctx.warnings}))
    loaded = routes.load_master_input(project, 'stem_mix')
    assert len(loaded) == 2 and loaded[0] is res.audio
    assert warning in project._mix_render_record['warnings']


def test_c4_manifest_warning_reaches_mix_report_source(engine_fallback, monkeypatch):
    _, _, res, warning = engine_fallback
    manifest = dict(steps=render._step_backends(res.steps), render_warnings=res.warnings)
    assert warning in manifest['render_warnings']
    monkeypatch.setattr(report, 'load_manifest', lambda *a: manifest)
    source = report._reproducibility(SimpleNamespace(), 'v', [])
    assert warning in json.dumps(source, ensure_ascii=False)
