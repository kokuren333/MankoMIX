"""W5b NAM contracts with generated weights only; real captures are opt-in BYOW."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from mankomix.core import config, registry
from mankomix.core.errors import ValidationError
from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ParamError, NumericError, ChainError
from mankomix.dspx.bb import ml, nam
from tests.toolimpl_harness import assert_common_tests, fundamental_frequency


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path/'settings'))
    config.clear_cache()
    monkeypatch.setattr(registry, '_open_url', lambda *a: pytest.fail('implicit network request'))
    yield
    config.clear_cache()


@pytest.fixture
def enabled(monkeypatch):
    # Standard Mix Report/cache integration requires changes in forbidden core.
    # Exercise the engine in isolation while public implementation stays False.
    monkeypatch.setitem(P.PROCESSORS['amp_sim'], 'implemented', True)


def wave_doc(*, gated=False, head=False, bias=0., arrays=1):
    layer = dict(input_size=1, condition_size=1, head_size=1, channels=1,
                 kernel_size=2, dilations=[1, 3], activation='Tanh', gated=gated, head_bias=True)
    weights = []
    for _ in range(arrays):
        weights += [1.]  # Input rechannel.
        for _ in layer['dilations']:
            weights += [.2, .4]*(2 if gated else 1)  # Oldest -> current kernel taps.
            weights += [bias]*(2 if gated else 1)
            weights += [.1]*(2 if gated else 1)  # Raw-input conditioning.
            weights += [.3, bias]  # Residual projection.
        weights += [.7, bias]  # Skip/head rechannel.
    hc = None
    if head:
        hc = dict(channels=1, activation='Tanh', num_layers=2, out_channels=1)
        weights += [.8, bias, .9, bias]
    weights += [.5]  # Serialized head scale.
    return dict(version='0.5.2', architecture='WaveNet', sample_rate=48000,
                config=dict(layers=[copy.deepcopy(layer) for _ in range(arrays)], head=hc, head_scale=.5),
                weights=weights)


def lstm_doc(*, layers=1, initial=True):
    weights = []
    for _ in range(layers):
        # H=1: rows i/f/g/o, input then previous hidden, summed gate biases, h0/c0.
        weights += [.3, .1, -.2, .15, .7, .2, .4, -.1]
        weights += [.1, -.2, .03, .2]
        weights += [.12, -.08] if initial else [0., 0.]
    weights += [.8, .01 if initial else 0.]
    return dict(version='0.5.1', architecture='LSTM', sample_rate=48000,
                config=dict(input_size=1, hidden_size=1, num_layers=layers), weights=weights)


def encode(doc):
    return json.dumps(doc, sort_keys=True, separators=(',', ':')).encode()


def register(tmp_path, doc=None, mid='capture'):
    path = tmp_path/(mid+'.nam')
    path.write_bytes(encode(wave_doc() if doc is None else doc))
    nam.register(path, id=mid, source_url='https://example.invalid/user-capture.nam',
                 license_weights='unknown', evidence_url='https://example.invalid/user-declaration')
    return path


def render(x, sr=48000, **kw):
    return E.render_chain(x, sr, [dict(id='capture', type='amp_sim', params={'model': 'capture', **kw})], stage='track')


@pytest.mark.parametrize('gated,head,arrays,bias', [(False, False, 1, 0.), (True, False, 1, .03),
    (False, True, 2, .02), (True, True, 2, -.01)])
def test_wavenet_matches_independent_scalar_equations(gated, head, arrays, bias):
    doc = wave_doc(gated=gated, head=head, arrays=arrays, bias=bias)
    model = nam.load(encode(doc))
    x = np.random.Generator(np.random.PCG64(3)).normal(0, .2, 77)
    # Independent full valid convolutions on raw zero-left-padded audio.
    raw = np.r_[np.zeros(model.network.receptive_field-1), x]
    residual, skip = raw.copy(), None
    for _ in range(arrays):
        terms = []
        for dilation in (1, 3):
            z = .2*residual[:-dilation]+.4*residual[dilation:]+bias+.1*raw[-(len(residual)-dilation):]
            a = np.tanh(z)
            if gated:
                a *= 1/(1+np.exp(-z))
            residual = residual[dilation:]+(.3*a+bias)
            terms.append(a)
        count = len(residual)
        s = sum(a[-count:] for a in terms)
        if skip is not None:
            s += skip[-count:]
        skip = .7*s+bias
    expected = skip*.5
    if head:
        expected = .9*np.tanh(.8*np.tanh(expected)+bias)+bias
    actual = model.process(x[:, None], model.state(1))[:, 0]
    assert np.max(abs(actual-expected)) < 2e-16


@pytest.mark.parametrize('layers', [1, 2])
def test_lstm_gate_order_and_exported_states(layers):
    model = nam.load(encode(lstm_doc(layers=layers)))
    x = np.linspace(-.7, .8, 121)
    cells = [[.12, -.08] for _ in range(layers)]
    expected = []
    for value in x:
        for cell in cells:
            h, c = cell
            i, f, g, o = [.3*value+.1*h+.1, -.2*value+.15*h-.2,
                          .7*value+.2*h+.03, .4*value-.1*h+.2]
            sig = lambda z: 1/(1+math.exp(-z))
            c = sig(f)*c+sig(i)*math.tanh(g)
            h = sig(o)*math.tanh(c)
            cell[:] = [h, c]
            value = h
        expected.append(.8*h+.01)
    y = model.process(x[:, None], model.state(1))[:, 0]
    # Scalar math and numpy transcendental functions can differ by a few ULPs.
    assert np.max(abs(y-expected)) < 4e-16


@pytest.mark.parametrize('architecture', ['WaveNet', 'LSTM'])
@pytest.mark.parametrize('block', [1, 64, 1024])
def test_true_stateful_chunks_and_channel_independence(architecture, block):
    doc = wave_doc(gated=True, arrays=2, bias=.01) if architecture == 'WaveNet' else lstm_doc(layers=2)
    model = nam.load(encode(doc))
    x = np.random.Generator(np.random.PCG64(7)).normal(0, .1, (2063, 2))
    full = model.process(x, model.state(2))
    state = model.state(2)
    split = np.concatenate([model.process(x[i:i+block], state) for i in range(0, len(x), block)])
    assert full.tobytes() == split.tobytes()
    assert full[:, :1].tobytes() == model.process(x[:, :1], model.state(1)).tobytes()


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(version='0.7.0'), lambda d: d.update(architecture='Linear'),
    lambda d: d.update(sample_rate=None), lambda d: d.update(sample_rate=True),
    lambda d: d['weights'].pop(), lambda d: d['weights'].append(1.),
    lambda d: d['weights'].__setitem__(0, float('nan')),
    lambda d: d['config']['layers'][0].update(dilations=[0]),
    lambda d: d['config']['layers'][0].update(activation='unknown'),
    lambda d: d['config']['layers'][0].update(gated='true'),
    lambda d: d['config']['layers'][0].update(head_size=2),
    lambda d: d['config'].update(condition_dsp={}),
    lambda d: d['config']['layers'][0].update(groups_input=2),
])
def test_bad_format_is_explicit_error(mutation):
    doc = wave_doc()
    mutation(doc)
    with pytest.raises(ParamError):
        nam.load(encode(doc))


def test_invalid_json_duplicate_keys_and_nonfinite_audio():
    for payload in (b'{}', b'[]', b'{', b'{"version":"0.5.2","version":"0.5.1"}', b'null'):
        with pytest.raises(ParamError):
            nam.load(payload)
    model = nam.load(encode(lstm_doc()))
    with pytest.raises(ParamError):
        model.process(np.array([[np.nan]]), model.state(1))
    with pytest.raises(ParamError):
        model.process(np.zeros((1, 2)), model.state(1))


def test_pinning_licenses_no_official_capture_or_copy(tmp_path):
    path = register(tmp_path)
    entry = nam.capture_entry('capture')
    assert entry['tier'] == 'byow' and entry['task'] == 'amp_capture'
    assert entry['weights']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert entry['weights']['size_bytes'] == path.stat().st_size
    assert entry['weights']['source_url'] == entry['runtime']['source_url']
    assert entry['runtime']['code_revision'] == nam.VERSION
    assert entry['license']['code'] == 'Apache-2.0' and entry['license']['weights'] == 'unknown'
    assert nam.CAVEAT in entry['license']['caveats']
    assert all(e in entry['license']['evidence'] for e in nam.REFERENCES)
    assert not [e for e in registry.load_catalog()['models'] if e.get('task') == 'amp_capture']
    assert not list(registry.models_dir().rglob('*.nam'))
    with pytest.raises(Exception, match='BYOW'):
        ml.pull('capture')


def test_parameter_schema_required_empty_sentinel_and_kind(tmp_path, enabled):
    d = P.describe('amp_sim')
    assert d['stages'] == ['track'] and d['backends'] == ['model'] and d['offline_only']
    assert P.validate_params('amp_sim', {}) == dict(model='', input_db=0., output_db=0., fallback='error')
    for model in ('', 'unknown'):
        with pytest.raises(ParamError):
            render(np.zeros((5, 1)), model=model)
    with pytest.raises(ParamError):
        P.validate_params('amp_sim', dict(model='speech_df3_48k'))
    branch = next(b for b in P.graph_schema()['items']['oneOf'] if b['properties']['type']['const'] == 'amp_sim')
    assert 'model' in branch['properties']['params']['required']
    assert 'default' not in branch['properties']['params']['properties']['model']
    assert branch['properties']['params']['properties']['model']['minLength'] == 1
    register(tmp_path)
    with pytest.raises(ChainError):
        E.render_chain(np.zeros((5, 1)), 48000, [dict(type='amp_sim', params=dict(model='capture'))], stage='bus')


@pytest.mark.parametrize('kw', [dict(input_db=-24.01), dict(input_db=24.01),
    dict(output_db=-36.01), dict(output_db=12.01), dict(fallback='pass'), dict(unknown=1)])
def test_parameter_ranges(tmp_path, kw):
    register(tmp_path)
    with pytest.raises(ParamError):
        P.validate_params('amp_sim', dict(model='capture', **kw))


@pytest.mark.parametrize('input_db,output_db', [(-24, -36), (0, 0), (24, 12)])
def test_gain_endpoints_and_records(tmp_path, enabled, input_db, output_db):
    register(tmp_path)
    x = np.linspace(-.2, .2, 1031)[:, None]
    result = render(x, input_db=input_db, output_db=output_db)
    model = nam.load(encode(wave_doc()))
    expected = model.process(x*10**(input_db/20), model.state(1))*10**(output_db/20)
    assert result.audio.tobytes() == expected.tobytes()
    assert result.audio.dtype == np.float64
    record = result.steps[0]['stats']
    assert record['provider'] == 'numpy_cpu' and not record['fallback_used']
    assert record['model_sha256'] and record['before'] and record['after']
    assert record['geometry']['chunk_samples'] == 1024
    assert ml.report_records(result.to_dict())[0]['model_id'] == 'capture'
    assert result.steps == render(x, input_db=input_db, output_db=output_db).steps


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('channels', [1, 2])
def test_resampling_alignment_lengths_and_offline_boundaries(tmp_path, sr, channels):
    register(tmp_path)
    resolved = ml.resolve_for_run('capture', 'amp_capture')
    for length in (0, 1, 3077):
        x = np.zeros((length, channels))
        if length > 500:
            x[500] = .2
        y, record = nam.infer(x, sr, resolved)
        assert y.shape == x.shape and y.dtype == np.float64
        if length > 500:
            assert np.argmax(abs(y[:, 0])) == 500
            for size in (64, 1024, 4096):
                split, _ = nam.infer_blocks([x[i:i+size] for i in range(0, len(x), size)], sr, resolved)
                assert y.tobytes() == split.tobytes()
        assert record['latency_samples'] == 0 and record['model_sample_rate'] == 48000


def test_explicit_fallback_missing_hash_and_size_errors(tmp_path, monkeypatch, enabled):
    path = register(tmp_path)
    payload, stat = path.read_bytes(), path.stat()
    x = np.linspace(-.1, .1, 177)[:, None]
    path.write_bytes(b'X'*len(payload))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    for fallback in ('error', 'amp_basic'):
        with pytest.raises(ValidationError):
            render(x, fallback=fallback)
    path.write_bytes(payload)
    doc = registry.load_byow()
    doc['models'][0]['weights']['size_bytes'] += 1
    with monkeypatch.context() as patch:
        patch.setattr(registry, 'load_byow', lambda: copy.deepcopy(doc))
        with pytest.raises(ValidationError):
            render(x, fallback='amp_basic')
    path.unlink()
    with pytest.raises(ml.ModelUnavailable):
        render(x)
    a = render(x, fallback='amp_basic', input_db=6, output_db=-3)
    from mankomix.dspx.procs.amp_basic import amp_basic
    fp = P.validate_params('amp_basic', {})
    expected = amp_basic(x*10**(6/20), 48000, fp)[0]*10**(-3/20)
    assert a.audio.tobytes() == expected.tobytes()
    assert a.steps[0]['fallback']['type'] == 'amp_basic'
    assert a.steps[0]['stats']['fallback_used']
    assert 'does not reproduce' in a.steps[0]['fallback']['mapping']
    assert ml.report_records(a.to_dict())[0]['fallback_used']


def test_corrupt_config_runtime_output_and_race_never_fallback(tmp_path, enabled, monkeypatch):
    path = register(tmp_path)
    resolved = ml.resolve_for_run('capture', 'amp_capture')
    path.write_bytes(b'changed')
    with pytest.raises(ValidationError):
        nam.infer(np.zeros((1, 1)), 48000, resolved)
    path = register(tmp_path, mid='other')
    resolved = ml.resolve_for_run('other', 'amp_capture')
    for key in ('source_url', 'format_version', 'sample_rate'):
        bad = copy.deepcopy(resolved)
        bad['entry']['runtime'].pop(key)
        with pytest.raises(ParamError):
            nam.infer(np.zeros((1, 1)), 48000, bad)
    resolved['entry']['runtime']['code_revision'] = 'different'
    with pytest.raises(ParamError):
        nam.infer(np.zeros((1, 1)), 48000, resolved)
    monkeypatch.setattr(ml, 'resolve_for_run', lambda *a: resolved)
    with pytest.raises(ParamError):
        render(np.zeros((1, 1)), model='other', fallback='amp_basic')
    doc = wave_doc()
    doc['weights'][-3] = 1e308
    doc['weights'][-1] = 1e308
    model = nam.load(encode(doc))
    with pytest.raises(NumericError):
        model.process(np.ones((5, 1))*.1, model.state(1))


@pytest.mark.parametrize('version', ['0.5.1', '0.5.2', '0.5.3'])
def test_supported_versions_and_lstm_engine(tmp_path, enabled, version):
    doc = lstm_doc(layers=2)
    doc['version'] = version
    doc['sample_rate'] = 48000.0  # Valid exporter JSON uses either integer or double.
    register(tmp_path, doc)
    x = np.linspace(-1., 1., 1081)[:, None]
    model = nam.load(encode(doc))
    y = render(x)
    assert y.audio.tobytes() == model.process(x, model.state(1)).tobytes()
    assert y.steps[0]['stats']['geometry']['state'] == 'exported_h0_c0'
    assert y.steps == render(x).steps


def test_common_contracts_generated_capture(tmp_path, enabled):
    register(tmp_path)
    def probe(x, y, sr, p):
        f = fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
        return dict(frequency_hz=f, passed=abs(f-1000) < 1)
    result = assert_common_tests('amp_sim', params=dict(model='capture'), seconds=.025,
        neutral=None, invalid_params=[dict(model='missing')], sr_probe=probe)
    assert not result['CT-4']['applicable']  # Captures do not have a neutral parameter.


def test_optional_external_capture(tmp_path, enabled):
    source = os.environ.get('MANKOMIX_W5B_MODEL')
    if not source:
        pytest.skip('set MANKOMIX_W5B_MODEL and independently pinned SHA256/output hash; no download')
    expected_weights = os.environ.get('MANKOMIX_W5B_MODEL_SHA256')
    expected_output = os.environ.get('MANKOMIX_W5B_EXPECTED_HASH')
    assert expected_weights and expected_output, 'external capture requires independent known-answer hashes'
    payload = Path(source).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == expected_weights
    # Only the user-supplied file is registered; never copy it into the repo/cache.
    nam.register(source, id='capture', source_url=os.environ['MANKOMIX_W5B_SOURCE_URL'],
                 license_weights=os.environ['MANKOMIX_W5B_LICENSE_WEIGHTS'],
                 evidence_url=os.environ.get('MANKOMIX_W5B_LICENSE_URL'))
    rate = nam.load(payload).rate
    t = np.arange(rate//4+127)/rate
    x = (.1*np.sin(2*np.pi*220*t)+.03*np.sin(2*np.pi*440*t))[:, None]
    a, b = render(x, rate), render(x, rate)
    assert a.audio.tobytes() == b.audio.tobytes() and a.steps == b.steps
    assert ml.output_hash(a.audio) == expected_output
    print('external_capture_hash', ml.output_hash(a.audio))
