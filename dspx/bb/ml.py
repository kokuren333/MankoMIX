"""BB-16: offline model registry and deterministic CPU ONNX inference.

API: model_entry(id, kind=None) resolves metadata without loading weights;
resolve_for_run(id, kind=None) re-hashes local files and never downloads;
pull(id) explicitly delegates acquisition to core.registry.model_pull;
session(bytes_or_path) fixes all ONNX CPU execution options;
infer(x, sr, resolved) returns (same-length float64 audio, reproducibility).
infer_blocks(blocks, sr, resolved) replays full offline context independently
of transport boundaries. Kinds are denoise, amp_capture and separate; legacy
task=separation maps to separate. BYOW stays in core's local registrations.

The spectral adapter is independently written against the published model
interface and equations, checked against DeepFilterNet libDF/src/lib.rs and
DeepFilterNet/df/deepfilternet3.py (MIT OR Apache-2.0), revision
7b14b895fe7fc42cab72b4a4c1e49c982bd6404b, upstream:
https://github.com/Rikorose/DeepFilterNet . No upstream code is bundled.
"""
from __future__ import annotations

import copy
import hashlib
import io
import tarfile

import numpy as np
from scipy import fft

from mankomix.core import registry
from mankomix.core.errors import EnvironmentProblem, InputError, ValidationError
from mankomix.dsp.errors import ParamError, NumericError

VERSION = 'bb16-1'
KINDS = frozenset(('denoise', 'amp_capture', 'separate'))
SPEECH_CAVEAT = ('These candidates are all trained on conversational speech; singing, instruments and mixes '
                 'are unsuitable and musical content may be removed as noise. Use only for narration, '
                 'dialogue or raw vocal recordings.')


class ModelUnavailable(EnvironmentProblem):
    """Only absence of local weights/runtime permits a declared fallback."""


def model_entry(model_id, kind=None):
    if kind is not None and kind not in KINDS:
        raise ParamError('unknown model kind')
    try:
        entry = registry.model_show(model_id)['entry']
    except InputError:
        raise LookupError(model_id) from None
    actual = entry.get('kind', entry.get('task'))
    actual = 'separate' if actual == 'separation' else actual
    if actual not in KINDS or (kind is not None and actual != kind):
        raise ParamError('model kind does not match the requested task')
    entry = copy.deepcopy(entry)
    entry['kind'] = actual
    if actual == 'denoise':
        caveats = entry['license'].setdefault('caveats', [])
        if SPEECH_CAVEAT not in caveats:
            caveats.append(SPEECH_CAVEAT)
    return entry


def resolve_for_run(model_id, kind=None):
    entry = model_entry(model_id, kind)
    # Always re-hash, even if size and mtime still match core's cache.
    verification = registry.model_verify(model_id)
    if any(f['state'] == 'sha256_mismatch' for f in verification['files']):
        raise ValidationError('model weights do not match their pinned sha256')
    if not verification['files'] or any(f['state'] == 'missing' for f in verification['files']):
        raise ModelUnavailable('model weights unavailable locally; use an explicit model pull or BYOW registration')
    resolved = registry.resolve_for_run(model_id)
    resolved['entry'] = entry
    for name, path in resolved['paths'].items():
        expected = next(f.get('size_bytes') for f in verification['files'] if f['name'] == name)
        declared = registry._declared_files(entry)
        pinned = next(f.get('size_bytes') for f in declared if f['name'] == name)
        if pinned is not None and (expected != pinned or path.stat().st_size != pinned):
            raise ValidationError('model weights do not match their pinned size')
    return resolved


def pull(model_id):
    """Explicit user operation; never called by validation or inference."""
    model_entry(model_id)
    return registry.model_pull(model_id)


def session(model):
    """Create an isolated CPU session; optional dependency is imported lazily."""
    try:
        import onnxruntime as ort
    except ImportError:
        raise ModelUnavailable('ONNX Runtime is not installed (existing separation extra)') from None
    if 'CPUExecutionProvider' not in ort.get_available_providers():
        raise ModelUnavailable('ONNX CPUExecutionProvider is unavailable')
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = 1
    opt.inter_op_num_threads = 1
    opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opt.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    opt.add_session_config_entry('session.use_deterministic_compute', '1')
    return ort.InferenceSession(model if isinstance(model, bytes) else str(model), sess_options=opt,
                                providers=['CPUExecutionProvider'])


def _run(sess, inputs):
    outputs = sess.run(None, {k: np.ascontiguousarray(v, dtype=np.float32) for k, v in inputs.items()})
    if any(not np.all(np.isfinite(a)) for a in outputs):
        raise NumericError('non-finite ONNX output')
    return dict(zip((o.name for o in sess.get_outputs()), outputs))


def erb_widths():
    """Pinned 48 kHz/960-point/32-band ERB partition, minimum two bins."""
    boundaries = np.floor((24.7*9.265*np.expm1(np.arange(1, 33)*np.log1p(24000/(24.7*9.265))/32))/50+.5).astype(int)
    widths, prev, debt = [], 0, 0
    for boundary in boundaries:
        width = int(boundary)-prev-debt
        debt = max(0, 2-width)
        widths.append(max(2, width))
        prev = int(boundary)
    widths[-1] += 481-sum(widths)
    return np.array(widths)


def _analysis(x):
    hop, n = 480, 960
    window = np.sin(.5*np.pi*np.sin(np.pi*(np.arange(n)+.5)/n)**2)
    frames = (len(x)+hop-1)//hop+1
    padded = np.pad(x, (hop, frames*hop-len(x)))
    spec = np.stack([fft.rfft(padded[t*hop:t*hop+n]*window, workers=1)/n for t in range(frames)])
    return spec, window


def _features(spec):
    widths = erb_widths()
    power = abs(spec)**2
    bands = np.stack([np.mean(power[:, a:a+w], axis=1)
                      for a, w in zip(np.r_[0, np.cumsum(widths)[:-1]], widths)], axis=1)
    bands = 10*np.log10(bands+1e-10)
    mean, unit = np.linspace(-60, -90, 32), np.linspace(.001, .0001, 96)
    erb, cplx = np.empty_like(bands), np.empty_like(spec[:, :96])
    alpha = np.exp(-.01)
    for t in range(len(spec)):
        mean = alpha*mean+(1-alpha)*bands[t]
        unit = alpha*unit+(1-alpha)*abs(spec[t, :96])
        erb[t] = (bands[t]-mean)/40
        cplx[t] = spec[t, :96]/np.sqrt(unit)
    # The exported networks omit the forward model's two-frame lookahead.
    erb = np.pad(erb[2:], ((0, min(2, len(erb))), (0, 0)))
    cplx = np.pad(cplx[2:], ((0, min(2, len(cplx))), (0, 0)))
    return erb, cplx


def _graphs(payload):
    # Read selected archive members in memory. Never extract paths to disk.
    wanted = {'enc.onnx', 'erb_dec.onnx', 'df_dec.onnx', 'config.ini'}
    blobs = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        for member in archive:
            name = member.name.rsplit('/', 1)[-1]
            if name in wanted:
                if name in blobs or not member.isfile() or member.size > 32*1024*1024:
                    raise ParamError('invalid model archive member')
                blobs[name] = archive.extractfile(member).read()
    if set(blobs) != wanted:
        raise ParamError('model archive is missing required graphs/config')
    import configparser
    config = configparser.ConfigParser()
    config.read_string(blobs['config.ini'].decode('utf-8'))
    expected = {'sr': 48000, 'fft_size': 960, 'hop_size': 480, 'nb_erb': 32,
                'nb_df': 96, 'df_order': 5, 'df_lookahead': 2, 'min_nb_erb_freqs': 2}
    if any(config.getint('df', k) != v for k, v in expected.items()) or config.getint('deepfilternet', 'conv_lookahead') != 2:
        raise ParamError('unsupported spectral model configuration')
    return {name: session(blobs[name+'.onnx']) for name in ('enc', 'erb_dec', 'df_dec')}


def _spectral(spec, erb, cplx, graphs):
    """Canonical 256-frame chunks, 128 overlap, 100-frame recurrent warmup.

    Chunks are anchored to clip zero, never to caller/transport boundaries.
    Raised-cosine OLA is normalized, including the first/last frame.
    """
    count = len(spec)
    accum, norm = np.zeros_like(spec), np.zeros(count)
    taper = np.sin(np.pi*(np.arange(256)+.5)/256)**2
    for start in range(-128, count, 128):
        lo, hi = max(0, start), min(count, start+256)
        context = max(0, lo-100)
        e = erb[context:hi]
        c = cplx[context:hi]
        enc = _run(graphs['enc'], {'feat_erb': e[None, None],
                                 'feat_spec': np.stack((c.real, c.imag))[None]})
        mask = _run(graphs['erb_dec'], {k: enc[k] for k in ('emb', 'e3', 'e2', 'e1', 'e0')})['m'][0, 0]
        coefs = _run(graphs['df_dec'], {k: enc[k] for k in ('emb', 'c0')})['coefs'][0]
        if mask.shape != (hi-context, 32) or coefs.shape != (hi-context, 96, 10):
            raise ParamError('unexpected spectral ONNX output shape')
        wet = spec[lo:hi]*np.repeat(mask[lo-context:], erb_widths(), axis=1)
        low = np.zeros((hi-lo, 96), dtype=np.complex128)
        cf = coefs[lo-context:].reshape(hi-lo, 96, 5, 2)
        for tap in range(5):
            ids = np.arange(lo, hi)+tap-2
            valid = (ids >= 0) & (ids < count)
            low[valid] += spec[ids[valid], :96]*(cf[valid, :, tap, 0]+1j*cf[valid, :, tap, 1])
        wet[:, :96] = low
        weight = taper[lo-start:hi-start]
        accum[lo:hi] += wet*weight[:, None]
        norm[lo:hi] += weight
    return accum/norm[:, None]


def _synthesis(spec, window, length):
    out = np.zeros((len(spec)+1)*480)
    for t, row in enumerate(spec):
        out[t*480:t*480+960] += fft.irfft(row, n=960, workers=1)*960*window
    return out[480:480+length]


def waveform(x, sess, *, chunk_samples, overlap_samples):
    """Reusable mono [1,1,N] waveform ONNX adapter for subsequent BB-16 users.

    Sessions have one float input/output. Channels run independently. Chunk
    geometry is supplied by the pinned entry, with zero padding and sine^2
    normalized overlap-add; invalid outputs raise instead of passing through.
    """
    n, overlap = chunk_samples, overlap_samples
    if isinstance(n, bool) or not isinstance(n, int) or n < 2 or isinstance(overlap, bool) or not isinstance(overlap, int) or not 0 <= overlap < n:
        raise ParamError('invalid pinned waveform chunk geometry')
    if len(sess.get_inputs()) != 1 or len(sess.get_outputs()) != 1:
        raise ParamError('waveform adapter requires one input and one output')
    hop = n-overlap
    result, norm = np.zeros_like(x), np.zeros(len(x))
    window = np.sin(np.pi*(np.arange(n)+.5)/n)**2 if overlap else np.ones(n)
    for start in range(-overlap, len(x), hop):
        lo, hi = max(0, start), min(len(x), start+n)
        if hi <= lo:
            continue
        for ch in range(x.shape[1]):
            block = np.zeros((1, 1, n), dtype=np.float32)
            block[0, 0, lo-start:hi-start] = x[lo:hi, ch]
            y = next(iter(_run(sess, {sess.get_inputs()[0].name: block}).values()))
            if y.shape != block.shape:
                raise ParamError('waveform ONNX output shape differs from its input')
            result[lo:hi, ch] += y[0, 0, lo-start:hi-start]*window[lo-start:hi-start]
        norm[lo:hi] += window[lo-start:hi-start]
    return result/norm[:, None] if len(x) else result


def infer(x, sr, resolved):
    from mankomix.dsp.reference.export import resample_poly_hq
    entry = resolved['entry']
    rt = entry['runtime']
    try:
        import onnxruntime as ort
    except ImportError:
        raise ModelUnavailable('ONNX Runtime is not installed (existing separation extra)') from None
    if rt.get('onnxruntime_version') and ort.__version__ != rt['onnxruntime_version']:
        raise ParamError('ONNX Runtime version differs from the pinned model runtime')
    rate = int(rt['sample_rate'])
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] < 1 or not np.all(np.isfinite(a)) or sr <= 0 or rate <= 0:
        raise ParamError('model audio must be finite (frames, channels) with positive sr')
    if len(resolved['paths']) != 1:
        raise ParamError('this ONNX adapter requires one pinned file')
    name, path = next(iter(resolved['paths'].items()))
    try:
        payload = path.read_bytes()
    except OSError:
        raise ModelUnavailable('model weights unavailable locally') from None
    pinned = next(f for f in registry._declared_files(entry) if f['name'] == name)
    if hashlib.sha256(payload).hexdigest() != pinned['sha256'] or (
            pinned.get('size_bytes') is not None and len(payload) != pinned['size_bytes']):
        raise ValidationError('model weights changed before session creation')
    audio = resample_poly_hq(a, sr, rate) if len(a) else a.copy()
    adapter = rt.get('adapter')
    if adapter == 'deep_filter_onnx_v1':
        graphs = _graphs(payload)
        wet = np.zeros_like(audio)
        for ch in range(audio.shape[1]):
            if len(audio):
                spec, window = _analysis(audio[:, ch])
                erb, cplx = _features(spec)
                wet[:, ch] = _synthesis(_spectral(spec, erb, cplx, graphs), window, len(audio))
        geometry = dict(chunk_frames=256, overlap_frames=128, warmup_frames=100,
                        window='vorbis_960_sine2_chunk', padding='zero', hop_samples=480,
                        lookahead_frames=2, latency_samples=0, latency_compensated=True)
    elif adapter == 'waveform_onnx_v1':
        cfg = rt['config']
        wet = waveform(audio, session(payload),
                       chunk_samples=cfg['chunk_samples'], overlap_samples=cfg['overlap_samples'])
        geometry = dict(cfg, window='sine_squared', padding='zero', latency_samples=0)
    else:
        raise ParamError('unsupported ONNX model adapter')
    wet = resample_poly_hq(wet, rate, sr) if len(a) else wet
    wet = wet[:len(a)]
    if wet.shape != a.shape or not np.all(np.isfinite(wet)):
        raise NumericError('invalid model output shape or values')
    record = dict(model_id=entry['id'], model_sha256=resolved['model_sha256'], runtime_version=VERSION,
                  code_revision=rt.get('code_revision'), provider='CPUExecutionProvider',
                  onnxruntime=ort.__version__, intra_op=1, inter_op=1, optimization='ORT_DISABLE_ALL',
                  model_sample_rate=rate, geometry=geometry, license=registry.license_record(entry),
                  caveats=list(entry['license'].get('caveats', [])), warnings=list(resolved['warnings']),
                  fallback_used=False)
    return wet, record


def infer_blocks(blocks, sr, resolved):
    """Offline replay: caller chunk boundaries never reset models or resampling."""
    return infer(np.concatenate(list(blocks), axis=0), sr, resolved)


def output_hash(x):
    return hashlib.sha256(np.ascontiguousarray(x, dtype='<f8').tobytes()).hexdigest()


def model_backend():
    """Dispatchers remain available without weights so their fallback can run."""
    from mankomix.dspx import registry as extensions
    impls = extensions.implementations()
    # Use the immutable collected declarations, avoiding a deep copy of the
    # complete processor catalogue on every legacy engine render.
    return {s['type']: impls[s['type']] for s in extensions._tables()[0]
            if 'model' in s.get('backends', ()) and s['type'] in impls}


def report_records(render_records):
    """Collect model/fallback facts for report consumers, without rerendering.

    Accept engine steps or nested mix manifests. Return no section when no
    model was requested. Public core report integration is deliberately left
    to the owner of core/report.py; this helper does not patch core at import.
    """
    found = []
    def visit(value):
        if isinstance(value, dict):
            stats = value.get('stats')
            if isinstance(stats, dict) and stats.get('model_id'):
                found.append(dict(step_id=value.get('id'), type=value.get('type'),
                                  **copy.deepcopy(stats)))
            else:
                for key in sorted(value):
                    visit(value[key])
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(render_records)
    return found
