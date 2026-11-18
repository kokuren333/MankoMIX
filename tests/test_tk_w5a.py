"""W5a contracts: no implicit network or weights, optional pinned real model."""
import copy
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mankomix.core import config, registry
from mankomix.core.errors import ValidationError
from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ParamError, NumericError
from mankomix.dspx.bb import ml
from mankomix.dspx.procs.denoise_ml import denoise_ml
from tests.toolimpl_harness import assert_common_tests

MODEL = 'speech_df3_48k'


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path/'home'))
    config.clear_cache()
    monkeypatch.setattr(registry, '_open_url', lambda *a: pytest.fail('implicit network request'))
    yield
    config.clear_cache()


@pytest.fixture
def enabled(monkeypatch):
    # Final public status stays False until the forbidden core report surface
    # supplies an extension hook. Exercise the complete engine path in isolation.
    monkeypatch.setitem(P.PROCESSORS['denoise_ml'], 'implemented', True)


def params(**kw):
    return P.validate_params('denoise_ml', {'model': MODEL, **kw})


def render(x, sr=48000, **kw):
    return E.render_chain(x, sr, [dict(id='speech', type='denoise_ml', params=dict(model=MODEL, **kw))], stage='track')


def test_catalog_and_kind_contracts():
    entry = ml.model_entry(MODEL, 'denoise')
    assert not registry.catalog_issues(registry.load_catalog())
    assert entry['weights']['size_bytes'] == 7983136
    assert entry['license']['weights'] == entry['license']['code'] == 'MIT OR Apache-2.0'
    assert ml.SPEECH_CAVEAT in entry['license']['caveats']
    assert ml.model_entry('scnet_4stem', 'separate')['kind'] == 'separate'
    with pytest.raises(ParamError):
        ml.model_entry(MODEL, 'amp_capture')
    with pytest.raises(ParamError):
        params(model='scnet_4stem')
    assert P.describe('denoise_ml')['offline_only']
    assert P.describe('denoise_ml')['backends'] == ['model']
    assert P.describe('denoise_ml')['implemented']


@pytest.mark.parametrize('kw', [dict(reduction_db=-.01), dict(reduction_db=60.01),
    dict(amount=-.01), dict(amount=1.01), dict(start_s=-1), dict(end_s=36001),
    dict(start_s=2, end_s=1), dict(fallback='pass'), dict(unknown=0)])
def test_invalid_parameters(kw):
    with pytest.raises(ParamError):
        params(**kw)


def test_unspecified_and_unknown_model():
    assert P.validate_params('denoise_ml', {})['model'] == ''
    assert P.validate_params('denoise_ml', {'model': ''})['model'] == ''
    for p in ({'model': 'missing'}, {'model': None}):
        with pytest.raises(ParamError):
            P.validate_params('denoise_ml', p)
    graph = P.graph_schema()
    branch = next(b for b in graph['items']['oneOf'] if b['properties']['type']['const'] == 'denoise_ml')
    assert 'model' not in branch['properties']['params'].get('required', [])
    assert branch['properties']['params']['properties']['model']['default'] == ''


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('channels', [1, 2])
def test_missing_fallback_shape_and_records(enabled, sr, channels):
    x = np.random.Generator(np.random.PCG64(20)).normal(0, .03, (2048, channels))
    result = render(x, sr)
    stats = result.steps[0]['stats']
    assert result.audio.shape == x.shape and result.audio.dtype == np.float64
    assert result.steps[0]['backend'] == 'model'
    assert stats['fallback_used'] and stats['fallback']['type'] == 'denoise'
    assert stats['fallback']['params']['profile'] == 'auto'
    assert stats['caveats'] and stats['before'] and stats['after']
    assert ml.report_records(result.to_dict())[0]['fallback_used']
    assert ml.report_records({'steps': []}) == []
    assert np.array_equal(result.audio, render(x, sr).audio)


def test_fallback_error_and_limit(enabled):
    x = np.ones((100, 1))*.01
    with pytest.raises(ml.ModelUnavailable):
        render(x, fallback='error')
    result = render(x, reduction_db=60)
    assert result.steps[0]['stats']['fallback']['params']['reduction_db'] == 40


def test_rp_bypass_delta_region(enabled, monkeypatch):
    x = np.random.Generator(np.random.PCG64(4)).normal(0, .1, (4800, 2))
    monkeypatch.setattr(ml, 'resolve_for_run', lambda *a: pytest.fail('neutral path loads weights'))
    for kw in (dict(amount=0), dict(reduction_db=0), dict(amount=0, delta=True)):
        assert render(x, **kw).audio.tobytes() == x.tobytes()
    monkeypatch.setattr(ml, 'resolve_for_run', lambda *a: {})
    monkeypatch.setattr(ml, 'infer', lambda x, sr, r: (x*.5, dict(fallback_used=False)))
    y = render(x, start_s=.02, end_s=.08).audio
    delta = render(x, start_s=.02, end_s=.08, delta=True).audio
    assert np.max(abs(y+delta-x)) < 1e-15
    assert y[:960].tobytes() == x[:960].tobytes()
    assert y[3840:].tobytes() == x[3840:].tobytes()
    assert np.isclose(y[2000, 0]/x[2000, 0], 1-.5*(1-10**(-18/20)))
    changed = render(x, start_s=.02, end_s=.08).steps[0]['stats']
    assert changed['event_count'] == 1
    assert .02 <= changed['events'][0]['start_s'] < .021


def test_explicit_pull_hash_and_tamper(tmp_path, monkeypatch, enabled):
    payload = b'not a real model'
    doc = registry.load_catalog()
    entry = next(e for e in doc['models'] if e['id'] == MODEL)
    entry['weights'].update(sha256=ml.output_hash(np.zeros((1, 1))), size_bytes=len(payload))
    import hashlib
    entry['weights']['sha256'] = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(registry, 'load_catalog', lambda: copy.deepcopy(doc))
    calls = []
    def source(url):
        calls.append(url)
        return io.BytesIO(payload)
    monkeypatch.setattr(registry, '_open_url', source)
    assert ml.pull(MODEL)['files'][0]['action'] == 'downloaded'
    assert len(calls) == 1
    resolved = ml.resolve_for_run(MODEL, 'denoise')
    path = next(iter(resolved['paths'].values()))
    stamp = path.stat()
    path.write_bytes(b'X'*len(payload))
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises(ValidationError):
        render(np.zeros((20, 1)))
    path.unlink()
    monkeypatch.setattr(registry, '_open_url', lambda _: io.BytesIO(b'wrong'))
    with pytest.raises(ValidationError):
        ml.pull(MODEL)
    assert not path.exists() and not path.with_name(path.name+'.part').exists()


def test_byow_kinds_and_no_download(tmp_path):
    path = tmp_path/'user.onnx'
    path.write_bytes(b'user-supplied')
    registry.model_register(path, id='capture', task='amp_capture', license_weights='unknown',
        runtime={'backend': 'onnxruntime', 'adapter': 'waveform_onnx_v1', 'sample_rate': 48000,
                 'config': {'chunk_samples': 128, 'overlap_samples': 64}})
    resolved = ml.resolve_for_run('capture', 'amp_capture')
    assert resolved['entry']['tier'] == 'byow' and resolved['warnings']
    assert path.read_bytes() == b'user-supplied'
    with pytest.raises(Exception, match='BYOW'):
        ml.pull('capture')


class Identity:
    def get_inputs(self):
        return [SimpleNamespace(name='audio')]
    def get_outputs(self):
        return [SimpleNamespace(name='output')]
    def run(self, _, feed):
        return [feed['audio']]


@pytest.mark.parametrize('length', [0, 1, 127, 128, 129, 1025])
@pytest.mark.parametrize('overlap', [0, 64])
def test_waveform_chunk_ola(length, overlap):
    x = np.random.Generator(np.random.PCG64(4)).normal(0, .1, (length, 2)).astype('float32').astype('float64')
    y = ml.waveform(x, Identity(), chunk_samples=128, overlap_samples=overlap)
    assert y.shape == x.shape
    assert np.max(abs(y-x), initial=0) < 1e-15


def test_bad_model_output():
    class Broken(Identity):
        def run(self, _, feed):
            return [np.full((1, 1, 128), np.nan)]
    with pytest.raises(NumericError):
        ml.waveform(np.ones((256, 1)), Broken(), chunk_samples=128, overlap_samples=64)


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_model_resampling_length_alignment(tmp_path, monkeypatch, sr):
    import sys
    monkeypatch.setitem(sys.modules, 'onnxruntime', SimpleNamespace(__version__='unit-test'))
    monkeypatch.setattr(ml, 'session', lambda _: Identity())
    path = tmp_path/'identity.onnx'
    path.write_bytes(b'identity')
    registry.model_register(path, id='identity', task='denoise', license_weights='unknown',
        runtime={'backend': 'onnxruntime', 'adapter': 'waveform_onnx_v1', 'sample_rate': 48000,
                 'config': {'chunk_samples': 128, 'overlap_samples': 64}})
    resolved = ml.resolve_for_run('identity', 'denoise')
    x = np.zeros((4097, 2))
    x[500] = [.5, .25]
    y, record = ml.infer(x, sr, resolved)
    assert y.shape == x.shape and y.dtype == np.float64
    assert np.argmax(abs(y[:, 0])) == 500
    assert y.tobytes() == ml.infer_blocks([x[:777], x[777:1001], x[1001:]], sr, resolved)[0].tobytes()
    assert record['model_sample_rate'] == 48000


def test_missing_runtime_falls_back(enabled, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'onnxruntime', None)
    monkeypatch.setattr(ml, 'resolve_for_run', lambda *a: dict(entry=ml.model_entry(MODEL)))
    stats = render(np.ones((100, 1))*.01).steps[0]['stats']
    assert stats['fallback_used'] and 'Runtime is not installed' in stats['fallback']['reason']


def test_spectral_frontend_reconstruction():
    widths = ml.erb_widths()
    assert sum(widths) == 481 and min(widths) == 2
    for length in (1, 479, 480, 481, 4991):
        x = np.random.Generator(np.random.PCG64(10)).normal(0, .1, length)
        spec, window = ml._analysis(x)
        y = ml._synthesis(spec, window, length)
        assert np.max(abs(x-y)) < 1e-15
        erb, cplx = ml._features(spec)
        assert erb.shape == (len(spec), 32) and cplx.shape == (len(spec), 96)


def test_session_options(monkeypatch):
    ort = pytest.importorskip('onnxruntime')
    seen = {}
    def constructor(model, *, sess_options, providers):
        seen.update(options=sess_options, providers=providers)
        return Identity()
    monkeypatch.setattr(ort, 'InferenceSession', constructor)
    ml.session(b'unit-test')
    opt = seen['options']
    assert opt.intra_op_num_threads == opt.inter_op_num_threads == 1
    assert opt.execution_mode == ort.ExecutionMode.ORT_SEQUENTIAL
    assert opt.graph_optimization_level == ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    assert seen['providers'] == ['CPUExecutionProvider']


def test_common_fallback(enabled):
    def probe(x, y, sr, p):
        from tests.toolimpl_harness import fundamental_frequency
        frequency = fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
        return dict(frequency_hz=frequency, passed=abs(frequency-1000) < 1)
    assert_common_tests('denoise_ml', params={'model': MODEL}, neutral={'amount': 0},
                        seconds=.045, invalid_params=[{'model': 'unknown'}], sr_probe=probe)


def test_real_model_optional(monkeypatch, tmp_path, enabled):
    source = os.environ.get('MANKOMIX_W5A_MODEL')
    if not source:
        pytest.skip('set MANKOMIX_W5A_MODEL to the pinned official ONNX archive; never downloads')
    import hashlib
    entry = ml.model_entry(MODEL)
    payload = Path(source).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == entry['weights']['sha256']
    dest = registry.models_dir()/MODEL/entry['weights']['filename']
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    sr = 48000
    t = np.arange(48000*3+127)/sr
    x = (.1*np.sin(2*np.pi*220*t)+.03*np.sin(2*np.pi*440*t))[:, None]
    a, b = render(x), render(x)
    assert a.audio.tobytes() == b.audio.tobytes()
    assert a.steps == b.steps
    resolved = ml.resolve_for_run(MODEL, 'denoise')
    wet, record = ml.infer(x, sr, resolved)
    for size in (64, 1024, 30001):
        blocks = [x[i:i+size] for i in range(0, len(x), size)]
        assert ml.infer_blocks(blocks, sr, resolved)[0].tobytes() == wet.tobytes()
    # Captured for the pinned weights, adapter v1, CPU ORT 1.30.0 in the
    # reference Windows environment. Other environments may supply their
    # independently reviewed known-answer value; it is never auto-accepted.
    golden = os.environ.get('MANKOMIX_W5A_EXPECTED_HASH',
                            'e4461665f679480e1dda5e83fc82c1ed00274d48a6179a925af5ce992cd6d0e1')
    assert ml.output_hash(a.audio) == golden
    assert record['provider'] == 'CPUExecutionProvider'
    print('real_model_hash', ml.output_hash(a.audio))
    # T10-01 style observations, deliberately not quality acceptance gates.
    from tests.toolimpl_harness import vowel
    clean = vowel(sr=48000, seconds=1, channels=1)
    clean[:12000] = 0
    noise = np.random.Generator(np.random.PCG64(70)).normal(size=clean.shape)
    noise *= np.sqrt(np.mean(clean**2)/10/np.mean(noise**2))
    noisy = clean+noise
    enhanced = render(noisy).audio
    noise_change = 10*np.log10(np.sum(enhanced[:10000]**2)/np.sum(noisy[:10000]**2))
    before, after = [], []
    for lo in range(14400, 48000-960, 960):
        ref = clean[lo:lo+960]
        before.append(10*np.log10(np.sum(ref**2)/np.sum((noisy[lo:lo+960]-ref)**2)))
        after.append(10*np.log10(np.sum(ref**2)/np.sum((enhanced[lo:lo+960]-ref)**2)))
    harmonic_changes = []
    times = np.arange(24000, 48000)/48000
    for hz in (100, 700, 1200, 2500):
        basis = np.exp(-2j*np.pi*hz*times)
        a_ref = abs(np.sum(clean[24000:, 0]*basis))
        a_out = abs(np.sum(enhanced[24000:, 0]*basis))
        harmonic_changes.append(dict(hz=hz, change_db=float(20*np.log10(a_out/a_ref))))
    print('quality_observations', json.dumps(dict(noise_only_change_db=float(noise_change),
          segment_snr_input_db=float(np.mean(before)), segment_snr_output_db=float(np.mean(after)),
          segment_snr_improvement_db=float(np.mean(after)-np.mean(before)),
          harmonic_changes=harmonic_changes)))


def test_spectral_chunk_seams_without_weights(monkeypatch):
    spec, window = ml._analysis(np.random.Generator(np.random.PCG64(44)).normal(0, .1, 480*600+71))
    erb, cplx = ml._features(spec)
    def fake(graph, feed):
        if graph == 'enc':
            n = feed['feat_erb'].shape[2]
            return {k: np.zeros((1, n, 1)) for k in ('e0', 'e1', 'e2', 'e3', 'emb', 'c0')}
        n = feed['emb'].shape[1]
        if graph == 'erb_dec':
            return {'m': np.ones((1, 1, n, 32))}
        coefs = np.zeros((1, n, 96, 10))
        coefs[..., 4] = 1
        return {'coefs': coefs}
    monkeypatch.setattr(ml, '_run', fake)
    y = ml._spectral(spec, erb, cplx, {k: k for k in ('enc', 'erb_dec', 'df_dec')})
    assert np.max(abs(y-spec)) < 1e-15
    # Inspect every fixed chunk join, including first/last partial chunks.
    for seam in range(128, len(spec), 128):
        assert np.max(abs(y[seam-2:seam+2]-spec[seam-2:seam+2])) < 1e-15
