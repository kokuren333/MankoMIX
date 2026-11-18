"""OQ_B: real model/fallback rendering, bilingual reports and legacy bytes."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
from types import ModuleType

import numpy as np
import pytest

from mankomix.core import config, mastering, mixrender as mr, registry, render, report, routes
from mankomix.core.errors import ValidationError
from mankomix.dsp import processors as P
from mankomix.dspx.bb import ml
from tests.test_mixrender import _project
from tests.test_render_cache import proj as cache_project
from tests.test_tk_w5b import register as register_nam


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('MANKOMIX_RENDER_CACHE_MB', '64')
    monkeypatch.setattr(registry, '_open_url', lambda *a: pytest.fail('implicit network'))
    config.clear_cache()
    mr.clear_track_cache()
    yield
    config.clear_cache()
    mr.clear_track_cache()


def _varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])


def _field(number, value):
    if isinstance(value, int):
        return _varint(number * 8) + _varint(value)
    if isinstance(value, str):
        value = value.encode()
    return _varint(number * 8 + 2) + _varint(len(value)) + value


def _half_onnx():
    # A self-authored ONNX protobuf: one Mul with one scalar float weight.
    # Encoding this tiny graph directly avoids adding the onnx authoring dependency.
    def info(name):
        shape = b''.join(_field(1, _field(1, d)) for d in (1, 1, 128))
        tensor = _field(1, 1) + _field(2, shape)
        return _field(1, name) + _field(2, _field(1, tensor))
    weight = _field(2, 1) + _field(4, struct.pack('<f', .5)) + _field(8, 'weight')
    node = _field(1, 'x') + _field(1, 'weight') + _field(2, 'y') + _field(4, 'Mul')
    graph = (_field(1, node) + _field(2, 'oq_b_half') + _field(5, weight)
             + _field(11, info('x')) + _field(12, info('y')))
    return _field(1, 8) + _field(7, graph) + _field(8, _field(2, 13))


def _register(tmp_path, kind):
    if kind == 'amp_sim':
        return register_nam(tmp_path, mid='oq_b_model')
    import onnxruntime as ort
    path = tmp_path / 'half.onnx'
    path.write_bytes(_half_onnx())
    registry.model_register(path, id='oq_b_model', task='denoise', license_weights='unknown',
        runtime=dict(backend='onnxruntime', adapter='waveform_onnx_v1', sample_rate=48000,
                     code_revision='oq-b-self-authored-1', onnxruntime_version=ort.__version__,
                     config=dict(chunk_samples=128, overlap_samples=64)))
    return path


def _project_with_chain(tmp_path, kind, missing=False):
    path = _register(tmp_path, kind)
    x = np.random.Generator(np.random.PCG64(21)).normal(0, .02, (24000, 2))
    project = _project(tmp_path, {'vocals.wav': (x, 48000)})
    params = dict(model='oq_b_model', fallback='denoise' if kind == 'denoise_ml' else 'amp_basic')
    project.data['tracks'][0]['chain'] = [dict(id='oq_b_step', type=kind, params=params, reason='OQ_B')]
    project.save(actor='human', op='patch', reason='OQ_B model chain')
    if missing:
        path.unlink()
    return project, path


def _master(project):
    plan = mastering.plan_master(project, profile_id='cd', delivery_id='cd_redbook', variant_id='var_oq_b')
    mastering.apply_master_plan(project, plan, actor='planner')


def _artifacts(project, renderer=render, reporter=report):
    result = renderer.render_variant(project, 'var_oq_b')
    manifests = [(project.root / item['manifest']).read_bytes()
                 for item in [result['archive'], *result['outputs']]]
    paths = reporter.write_report(project, 'var_oq_b')
    reports = [(project.root / paths[key]).read_bytes() for key in ('json', 'md_ja', 'md_en')]
    source = json.loads(reports[0])
    return manifests, reports, source


@pytest.mark.parametrize('kind', ['denoise_ml', 'amp_sim'])
@pytest.mark.parametrize('missing', [True, False], ids=['fallback', 'inference'])
def test_model_render_reaches_manifest_source_and_bilingual_report(tmp_path, monkeypatch, kind, missing):
    # Status is gated separately; no DSP, inference, audio or report is substituted.
    monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)
    project, path = _project_with_chain(tmp_path, kind, missing)
    expected_sha = registry.model_sha256(ml.model_entry('oq_b_model'))
    if not missing:
        assert expected_sha == hashlib.sha256(path.read_bytes()).hexdigest()
    _master(project)
    manifests, reports, source = _artifacts(project)
    facts = source['reproducibility']
    for payload in manifests:
        manifest = json.loads(payload)
        step = next(s for s in manifest['steps'] if s['id'] == 'oq_b_step')
        assert step['track_id'] == project.data['tracks'][0]['id']
        assert step['stats']['fallback_used'] == missing
        assert manifest['model_records'][0]['model_id'] == 'oq_b_model'
        if missing:
            assert step['fallback']['type'] == ('denoise' if kind == 'denoise_ml' else 'amp_basic')
            assert any('rendered with fallback' in w for w in manifest['render_warnings'])
            assert manifest['models'] == []
        else:
            assert len(manifest['models']) == 1
            model = manifest['models'][0]
            assert model['model_sha256'] == expected_sha
            assert model['code_revision'] and model['runtime_version'] and model['provider']
            assert model['before'] and model['after']
    assert facts['model_records'][0]['model_id'] == 'oq_b_model'
    for payload in reports:
        text = payload.decode('utf-8')
        assert 'oq_b_model' in text
        if missing:
            assert 'rendered with fallback' in text and facts['fallback_steps']
        else:
            assert expected_sha in text and len(facts['models']) == 1
    if not missing:
        again = _artifacts(project)
        assert (manifests, reports) == again[:2]
        if kind == 'denoise_ml':
            resolved = ml.resolve_for_run('oq_b_model', 'denoise')
            x = np.ones((257, 1), dtype=np.float64) * .25
            wet, _ = ml.infer(x, 48000, resolved)
            assert np.max(abs(wet - .125)) < 1e-15


@pytest.mark.parametrize('kind', ['denoise_ml', 'amp_sim'])
def test_model_tracks_revalidate_missing_and_same_stamp_tamper(tmp_path, monkeypatch, kind):
    monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)
    project, path = _project_with_chain(tmp_path, kind)
    tid = project.data['tracks'][0]['id']
    before = mr.render_track(project, tid)
    assert mr.track_cache_info()['entries'] == 0
    payload, stamp = path.read_bytes(), path.stat()
    path.unlink()
    missing = mr.render_track(project, tid)
    assert missing[2]['chain'][0]['stats']['fallback_used']
    assert missing[0].tobytes() != before[0].tobytes()
    path.write_bytes(payload)
    restored = mr.render_track(project, tid)
    assert restored[0].tobytes() == before[0].tobytes()
    bad = bytearray(payload)
    bad[-1] ^= 1
    path.write_bytes(bad)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert path.stat().st_size == stamp.st_size and path.stat().st_mtime_ns == stamp.st_mtime_ns
    with pytest.raises(ValidationError, match='sha256'):
        mr.render_track(project, tid)
    assert mr.track_cache_info()['hits'] == 0


def _legacy(name):
    # Compare against the exact pre-OQ source (these four files matched e967b0a).
    root = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(['git', 'show', f'e967b0a:core/{name}.py'], cwd=root)
    module = ModuleType(f'mankomix.core._oq_b_legacy_{name}')
    module.__package__ = 'mankomix.core'
    exec(compile(source, f'<pre-OQ core/{name}.py>', 'exec'), module.__dict__)
    return module


def test_existing_project_cache_manifest_and_full_report_bytes_unchanged(cache_project):
    legacy_mr, legacy_routes, legacy_render, legacy_report = [_legacy(n) for n in
                                                            ('mixrender', 'routes', 'render', 'report')]
    legacy_render.load_master_input = legacy_routes.load_master_input
    legacy_report.load_master_input = legacy_routes.load_master_input
    for track in cache_project.data['tracks']:
        ctx = mr._Ctx(cache_project, cache_project.data, 0)
        assert mr._track_key(ctx, track, 0, ctx.total, track['chain']) == legacy_mr._track_key(
            ctx, track, 0, ctx.total, track['chain'])
    _master(cache_project)
    before = _artifacts(cache_project, legacy_render, legacy_report)
    mr.clear_track_cache()
    after = _artifacts(cache_project)
    assert before == after
    for category, payloads in zip(('manifest', 'report-json-ja-en'), after[:2]):
        print(category, [hashlib.sha256(payload).hexdigest() for payload in payloads])


def test_unspecified_denoise_fallback_and_stale_route_records(tmp_path, monkeypatch):
    monkeypatch.setitem(P.PROCESSORS['denoise_ml'], 'implemented', True)
    monkeypatch.setattr(registry, 'default_model', lambda mode: None)
    x = np.random.Generator(np.random.PCG64(22)).normal(0, .02, (24000, 2))
    project = _project(tmp_path, {'vocals.wav': (x, 48000)})
    project.data['tracks'][0]['chain'] = [dict(id='default', type='denoise_ml', params={}, reason='OQ_B')]
    _master(project)
    _, reports, source = _artifacts(project)
    assert source['reproducibility']['fallback_steps'][0]['fallback']['type'] == 'denoise'
    assert all('rendered with fallback' in payload.decode('utf-8') for payload in reports)
    routes.load_master_input(project, 'stem_sum')
    assert project._mix_render_record is None
