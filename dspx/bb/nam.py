"""NAM JSON reference inference, independently implemented with numpy float64.

Format/weight-order references (MIT; no upstream code is bundled):
https://github.com/sdatkinson/neural-amp-modeler/tree/102333bf1c2c9f4255d73b8712ad3ecb0d8af275
nam/models/wavenet.py and nam/models/recurrent.py (v0.9.0).
https://github.com/sdatkinson/NeuralAmpModelerCore/tree/d3189ed482ded880c128bf312941266c4fa5ceec
NAM/lstm.cpp and docs/nam_file_version.rst. Licenses checked 2026-11-17.

API: register(path, ...) pins a user-owned capture via BB-16's registry;
load(payload) validates classic mono WaveNet/LSTM NAM 0.5.1..0.5.3;
model.state(channels) and model.process(audio, state) preserve causal state;
infer(audio, sr, resolved) / infer_blocks(blocks, sr, resolved) provide full
offline context, fixed 1024-sample internal chunks, and BB-16 run records.
No downloading, ONNX conversion, training, BLAS matmul, or global state.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

import numpy as np

from mankomix.dsp.errors import ParamError, NumericError

VERSION = 'nam-numpy-1'
ADAPTER = 'nam_numpy_v1'
CAVEAT = '実機メーカーとの関係なし (No affiliation with equipment manufacturers). Capture rights and training-data terms are the user\'s responsibility.'
TRAINER_REV = '102333bf1c2c9f4255d73b8712ad3ecb0d8af275'
CORE_REV = 'd3189ed482ded880c128bf312941266c4fa5ceec'
REFERENCES = [
    dict(url=f'https://raw.githubusercontent.com/sdatkinson/neural-amp-modeler/{TRAINER_REV}/LICENSE',
         checked_on='2026-11-17', kind='license_file', note='MIT format reference; not a license for individual captures.'),
    dict(url=f'https://raw.githubusercontent.com/sdatkinson/NeuralAmpModelerCore/{CORE_REV}/LICENSE',
         checked_on='2026-11-17', kind='license_file', note='MIT inference reference; not a license for individual captures.')]


def _int(value, lo=1, hi=128):
    if type(value) is not int or not lo <= value <= hi:
        raise ParamError('unsupported NAM dimension or sample rate')
    return value


def _rate(value):
    # The NAM exporter also writes integral-valued doubles, e.g. 48000.0.
    if type(value) not in (int, float) or not np.isfinite(value) or value != int(value):
        raise ParamError('NAM sample rate must be an explicit integral frequency')
    return _int(int(value), 8000, 384000)


def _keys(obj, required, optional=()):
    if not isinstance(obj, dict) or set(obj)-set(required)-set(optional) or set(required)-set(obj):
        raise ParamError('unsupported or missing NAM configuration fields')


def _sigmoid(x):
    # Stable for arbitrarily large, finite gate values.
    return np.exp(-np.logaddexp(0., -x))


def _mv(w, x):
    # Explicit fixed-order reduction avoids a threaded BLAS implementation.
    return np.sum(w*x[None, :], axis=1)


def _activation(name, x):
    if name == 'Tanh':
        return np.tanh(x)
    if name == 'ReLU':
        return np.maximum(x, 0.)
    if name == 'Sigmoid':
        return _sigmoid(x)
    raise ParamError('unsupported NAM activation')


class _Weights:
    def __init__(self, values):
        if not isinstance(values, list) or len(values) > 4_000_000 or any(type(v) not in (int, float) for v in values):
            raise ParamError('NAM weights must be a bounded flat numeric array')
        self.values = np.asarray(values, dtype=np.float64)
        if not np.all(np.isfinite(self.values)):
            raise ParamError('NAM weights must be finite')
        self.offset = 0

    def take(self, *shape):
        count = int(np.prod(shape))
        end = self.offset+count
        if end > len(self.values):
            raise ParamError('truncated NAM weights')
        result = self.values[self.offset:end].reshape(shape).copy()
        self.offset = end
        return result

    def finish(self):
        if self.offset != len(self.values):
            raise ParamError('trailing NAM weights')


class _LSTM:
    def __init__(self, cfg, weights):
        _keys(cfg, ('input_size', 'hidden_size', 'num_layers'), ('in_channels', 'out_channels'))
        if any(_int(cfg.get(k, 1)) != 1 for k in ('input_size', 'in_channels', 'out_channels')):
            raise ParamError('only mono NAM captures are supported; audio channels run independently')
        h = _int(cfg['hidden_size'])
        n = _int(cfg['num_layers'], hi=8)
        self.layers = []
        for i in range(n):
            self.layers.append((weights.take(4*h, (1 if i == 0 else h)+h),
                                weights.take(4*h), weights.take(h), weights.take(h)))
        self.head, self.bias = weights.take(1, h), weights.take(1)
        self.receptive_field = None
        self.warmup = 0

    def state(self):
        # NAM serializes h0/c0 after a training-side zero-input burn-in.
        return [[h.copy(), c.copy()] for _, _, h, c in self.layers]

    def sample(self, value, state):
        x = np.array([value])
        for (w, b, _, _), cell in zip(self.layers, state):
            h, c = cell
            i, f, g, o = np.split(_mv(w, np.concatenate((x, h)))+b, 4)
            c = _sigmoid(f)*c+_sigmoid(i)*np.tanh(g)
            h = _sigmoid(o)*np.tanh(c)
            cell[:] = [h, c]
            x = h
        return float((_mv(self.head, x)+self.bias)[0])


class _WaveNet:
    def __init__(self, cfg, weights):
        _keys(cfg, ('layers', 'head', 'head_scale'))
        configs = cfg['layers']
        if not isinstance(configs, list) or not 1 <= len(configs) <= 8:
            raise ParamError('unsupported NAM layer arrays')
        self.arrays, rf, previous, previous_head = [], 1, 1, None
        for cfg_layer in configs:
            _keys(cfg_layer, ('input_size', 'condition_size', 'head_size', 'channels',
                              'kernel_size', 'dilations', 'activation', 'gated', 'head_bias'))
            cin, channels, head = (_int(cfg_layer[k]) for k in ('input_size', 'channels', 'head_size'))
            kernel = _int(cfg_layer['kernel_size'], hi=16)
            ds = cfg_layer['dilations']
            if cin != previous or _int(cfg_layer['condition_size']) != 1 or (previous_head is not None and previous_head != channels):
                raise ParamError('incompatible NAM layer-array channels')
            if not isinstance(ds, list) or not 1 <= len(ds) <= 32:
                raise ParamError('unsupported NAM dilation list')
            ds = [_int(d, hi=65536) for d in ds]
            rf += (kernel-1)*sum(ds)
            if rf > 262144:
                raise ParamError('unsupported NAM receptive field')
            if type(cfg_layer['gated']) is not bool or type(cfg_layer['head_bias']) is not bool:
                raise ParamError('NAM gate and bias flags must be boolean')
            activation = cfg_layer['activation']
            _activation(activation, np.zeros(1))
            gated = cfg_layer['gated']
            rechannel = weights.take(channels, cin)
            layers = []
            for d in ds:
                mid = channels*(2 if gated else 1)
                layers.append((weights.take(mid, channels, kernel), weights.take(mid),
                               weights.take(mid, 1), weights.take(channels, channels), weights.take(channels), d))
            out = weights.take(head, channels)
            bias = weights.take(head) if cfg_layer['head_bias'] else np.zeros(head)
            self.arrays.append((rechannel, layers, out, bias, activation, gated))
            previous, previous_head = channels, head
        self.head = []
        if cfg['head'] is not None:
            hc = cfg['head']
            _keys(hc, ('channels', 'activation', 'num_layers', 'out_channels'), ('in_channels',))
            if _int(hc.get('in_channels', previous_head)) != previous_head or _int(hc['out_channels']) != 1:
                raise ParamError('unsupported NAM output head channels')
            _activation(hc['activation'], np.zeros(1))
            for i in range(_int(hc['num_layers'], hi=8)):
                cout = 1 if i == hc['num_layers']-1 else _int(hc['channels'])
                self.head.append((weights.take(cout, previous_head), weights.take(cout), hc['activation']))
                previous_head = cout
        if previous_head != 1:
            raise ParamError('NAM capture must have one output')
        if type(cfg['head_scale']) not in (int, float) or not np.isfinite(cfg['head_scale']):
            raise ParamError('invalid NAM head scale')
        # The serialized tail is authoritative, as in the Core loader.
        self.scale = float(weights.take(1)[0])
        self.receptive_field, self.warmup = rf, rf-1

    def state(self):
        rings = [[np.zeros(((w.shape[2]-1)*d+1, w.shape[1])) for w, _, _, _, _, d in layers]
                 for _, layers, _, _, _, _ in self.arrays]
        state = [0, rings]
        # Equivalent to left-padding the raw input by receptive_field-1;
        # biases in deeper layers must propagate through the padding too.
        for _ in range(self.warmup):
            self.sample(0., state)
        return state

    def sample(self, value, state):
        t, rings = state
        x, head = np.array([value]), None
        for (rechannel, layers, out, bias, activation, gated), array_rings in zip(self.arrays, rings):
            x = _mv(rechannel, x)
            for (w, b, mix, residual, rb, dilation), ring in zip(layers, array_rings):
                ring[t % len(ring)] = x
                z = b.copy()
                for k in range(w.shape[2]):
                    lag = (w.shape[2]-1-k)*dilation
                    z += _mv(w[:, :, k], ring[(t-lag) % len(ring)])
                z += mix[:, 0]*value
                c = len(x)
                a = _activation(activation, z[:c])
                if gated:
                    a *= _sigmoid(z[c:])
                x = x+_mv(residual, a)+rb
                head = a.copy() if head is None else head+a
            head = _mv(out, head)+bias
        y = head*self.scale
        for w, b, activation in self.head:
            y = _mv(w, _activation(activation, y))+b
        state[0] += 1
        return float(y[0])


class NamModel:
    def __init__(self, document):
        if not isinstance(document, dict) or document.get('version') not in ('0.5.1', '0.5.2', '0.5.3'):
            raise ParamError('supported NAM versions are 0.5.1, 0.5.2 and 0.5.3')
        self.version = document['version']
        self.rate = _rate(document.get('sample_rate'))
        self.architecture = document.get('architecture')
        weights = _Weights(document.get('weights'))
        cls = {'LSTM': _LSTM, 'WaveNet': _WaveNet}.get(self.architecture)
        if cls is None:
            raise ParamError('unsupported NAM architecture')
        self.network = cls(document.get('config'), weights)
        weights.finish()

    def state(self, channels):
        return [self.network.state() for _ in range(_int(channels, hi=64))]

    def process(self, audio, state):
        a = np.asarray(audio, dtype=np.float64)
        if a.ndim != 2 or a.shape[1] != len(state) or not np.all(np.isfinite(a)):
            raise ParamError('NAM audio must be finite (frames, channels) matching its state')
        y = np.empty_like(a)
        with np.errstate(over='ignore', invalid='ignore'):
            for ch, s in enumerate(state):
                for t in range(len(a)):
                    y[t, ch] = self.network.sample(a[t, ch], s)
        if not np.all(np.isfinite(y)):
            raise NumericError('non-finite NAM inference output')
        return y


def load(payload):
    """Read a bounded JSON document; reject ambiguity and unsupported variants."""
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ParamError('duplicate NAM JSON key')
            out[k] = v
        return out
    if len(payload) > 256*1024*1024:
        raise ParamError('NAM file exceeds the reference size limit')
    try:
        doc = json.loads(payload, object_pairs_hook=pairs)
        return NamModel(doc)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        if isinstance(exc, ParamError):
            raise
        raise ParamError('invalid NAM JSON/configuration') from None


def register(path, *, id, source_url, license_weights, evidence_url=None, usage_restrictions='unknown', replace=False):
    """Explicit local BYOW registration. Never copies or downloads a capture."""
    from pathlib import Path
    from mankomix.dspx.bb import ml
    if not isinstance(source_url, str) or not re.fullmatch(r'https?://\S+', source_url):
        raise ParamError('BYOW NAM registration requires the original distribution URL')
    payload = Path(path).read_bytes()
    model = load(payload)
    rt = dict(backend='numpy', adapter=ADAPTER, sample_rate=model.rate, code_revision=VERSION,
              source_url=source_url, format_version=model.version, reference_trainer_revision=TRAINER_REV,
              reference_core_revision=CORE_REV, config=dict(chunk_samples=1024))
    result = ml.registry.model_register(path, id=id, task='amp_capture', architecture=model.architecture,
        runtime=rt, license_code='Apache-2.0', license_weights=license_weights,
        evidence_url=evidence_url, usage_restrictions=usage_restrictions, replace=replace,
        note='Capture license is a user declaration; MIT reference licenses do not cover captures.')
    doc = ml.registry.load_byow()
    entry = next(e for e in doc['models'] if e['id'] == id)
    entry['weights']['source_url'] = source_url
    entry['license']['caveats'].append(CAVEAT)
    entry['license']['evidence'].extend(copy.deepcopy(REFERENCES))
    ml.registry._save_byow(doc)
    result['license'] = ml.registry.license_record(entry)
    return result


def capture_entry(model_id):
    from mankomix.dspx.bb import ml
    entry = ml.model_entry(model_id, 'amp_capture')
    if entry.get('tier') != 'byow':
        raise ParamError('amp_sim accepts only user-owned BYOW captures')
    _runtime(entry)
    if CAVEAT not in entry['license'].setdefault('caveats', []):
        entry['license']['caveats'].append(CAVEAT)
    return entry


def _runtime(entry):
    rt = entry.get('runtime', {})
    if not isinstance(rt, dict) or rt.get('backend') != 'numpy' or rt.get('adapter') != ADAPTER or rt.get('code_revision') != VERSION or rt.get('config') != dict(chunk_samples=1024):
        raise ParamError('NAM runtime differs from the pinned reference adapter')
    source = rt.get('source_url')
    weights = entry.get('weights', {})
    if (not isinstance(source, str) or not re.fullmatch(r'https?://\S+', source)
            or weights.get('source_url') != source or type(weights.get('size_bytes')) is not int
            or weights['size_bytes'] <= 0):
        raise ParamError('NAM registration must pin its original source URL and size')
    if entry.get('architecture') not in ('WaveNet', 'LSTM') or rt.get('format_version') not in ('0.5.1', '0.5.2', '0.5.3'):
        raise ParamError('unsupported registered NAM architecture or format version')
    _rate(rt.get('sample_rate'))
    return rt


def infer(x, sr, resolved):
    from mankomix.dspx.bb import ml
    from mankomix.core.errors import ValidationError
    from mankomix.dsp.reference.export import resample_poly_hq
    entry = copy.deepcopy(resolved['entry'])
    if entry.get('kind', entry.get('task')) != 'amp_capture' or entry.get('tier') != 'byow':
        raise ParamError('NAM inference requires a BYOW amp_capture')
    rt = _runtime(entry)
    if len(resolved['paths']) != 1:
        raise ParamError('NAM requires one pinned capture file')
    name, path = next(iter(resolved['paths'].items()))
    try:
        payload = path.read_bytes()
    except OSError:
        raise ml.ModelUnavailable('NAM capture unavailable locally') from None
    pinned = next(f for f in ml.registry._declared_files(entry) if f['name'] == name)
    if hashlib.sha256(payload).hexdigest() != pinned['sha256'] or len(payload) != pinned.get('size_bytes'):
        raise ValidationError('NAM capture changed before inference')
    model = load(payload)
    if rt.get('sample_rate') != model.rate or entry.get('architecture') != model.architecture or rt.get('format_version') != model.version:
        raise ParamError('NAM contents differ from the pinned registry architecture/rate/version')
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2 or not 1 <= a.shape[1] <= 64 or not np.all(np.isfinite(a)):
        raise ParamError('NAM input must be finite (frames, channels)')
    _int(sr, 8000, 384000)
    audio = resample_poly_hq(a, sr, model.rate) if len(a) else a.copy()
    state, wet = model.state(a.shape[1]), np.empty_like(audio)
    for start in range(0, len(audio), 1024):
        wet[start:start+1024] = model.process(audio[start:start+1024], state)
    wet = resample_poly_hq(wet, model.rate, sr)[:len(a)] if len(a) else wet
    if wet.shape != a.shape or not np.all(np.isfinite(wet)):
        raise NumericError('invalid NAM output shape or values')
    if CAVEAT not in entry['license'].setdefault('caveats', []):
        entry['license']['caveats'].append(CAVEAT)
    record = dict(model_id=entry['id'], model_sha256=resolved['model_sha256'], runtime_version=VERSION,
        code_revision=VERSION, provider='numpy_cpu', numpy_version=np.__version__, architecture=model.architecture,
        model_format_version=model.version, model_sample_rate=model.rate, fallback_used=False,
        geometry=dict(chunk_samples=1024, overlap_samples=0, window='none', padding='causal_zero',
                      state='exported_h0_c0' if model.architecture == 'LSTM' else 'zero_input_left_padding',
                      warmup_samples=model.network.warmup, receptive_field=model.network.receptive_field),
        latency_samples=0, latency_compensated=True,
        license=ml.registry.license_record(entry), caveats=list(entry['license']['caveats']),
        warnings=list(resolved['warnings']))
    return wet, record


def infer_blocks(blocks, sr, resolved):
    """Offline resampling replays full context; raw model.process is stateful."""
    return infer(np.concatenate(list(blocks), axis=0), sr, resolved)
