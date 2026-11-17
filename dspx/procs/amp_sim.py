"""T07-13: BYOW NAM inference with explicit, recorded amplifier substitution."""
import numpy as np

from mankomix.dsp.errors import ParamError, NumericError
from mankomix.dspx.params import _f, _e


def validate(p):
    from mankomix.dspx.bb.nam import capture_entry
    # Empty is an internal declaration sentinel, never a default capture.
    if p['model']:
        try:
            capture_entry(p['model'])
        except LookupError:
            raise ParamError('amp_sim requires a registered BYOW amp_capture') from None


def amp_sim(x, sr, p, *, seed=0):
    from mankomix.dsp import processors as P
    from mankomix.dspx.bb import ml, nam
    from mankomix.dspx.procs.amp_basic import amp_basic
    validate(p)
    if not p['model']:
        raise ParamError('amp_sim requires an explicit model ID; no capture is bundled or selected by default')
    entry = nam.capture_entry(p['model'])
    record = dict(model_id=p['model'], license=ml.registry.license_record(entry),
        caveats=list(entry['license']['caveats']), fallback_used=False,
        model_sha256=ml.registry.model_sha256(entry), code_revision=nam.VERSION,
        latency_samples=0, latency_compensated=True)
    a = np.asarray(x, dtype=np.float64)*10**(p['input_db']/20)
    try:
        resolved = ml.resolve_for_run(p['model'], 'amp_capture')
        wet, run = nam.infer(a, sr, resolved)
        record.update(run)
    except ml.ModelUnavailable as exc:
        if p['fallback'] == 'error':
            raise
        fp = P.validate_params('amp_basic', {})
        wet, _, stats = amp_basic(a, sr, fp, seed=seed)
        record.update(provider='reference', fallback_used=True,
            fallback=dict(type='amp_basic', params=fp, reason=str(exc),
                          mapping='default generic amplifier after input gain; does not reproduce the capture'),
            fallback_stats=stats)
    y = wet*10**(p['output_db']/20)
    if y.shape != np.shape(x) or not np.all(np.isfinite(y)):
        raise NumericError('invalid amp_sim output')
    def measure(v):
        return dict(peak=float(np.max(np.abs(v), initial=0)),
                    rms=float(np.sqrt(np.mean(v*v))) if v.size else 0.)
    record.update(before=measure(np.asarray(x)), after=measure(y))
    return y, sr, record


def patch_schema(schema):
    schema.setdefault('required', []).append('model')
    schema['properties']['model'].pop('default', None)
    schema['properties']['model']['minLength'] = 1


SPECS = [dict(type='amp_sim', implemented=False,
    description='Offline user-owned NAM capture; requires an explicit registered model.',
    stages=['track'], master_slot=None, offline_only=True, backends=['model'],
    fallback=dict(type='amp_basic', default='error', mapping='explicit generic amplifier substitution; different sound'),
    realtime=dict(block_ok=False, latency_samples=0, allocates=True,
                  latency_rule='No adapter lookahead; capture phase/response retained; resampling aligned offline.'),
    params=[dict(id='model', type='asset', registry='models', unit=None, default='', allow_empty=True,
                 description='Required BYOW amp_capture ID; empty fails at execution. No bundled/default capture.'),
            _f('input_db', 'dB', -24, 24, 0, 'Gain before the capture or explicit substitute.'),
            _f('output_db', 'dB', -36, 12, 0, 'Gain after inference or explicit substitute.'),
            _e('fallback', ['amp_basic', 'error'], 'error', 'Missing local capture action; substitution has a different sound.')])]
IMPLS = {'amp_sim': amp_sim}
CROSS_VALIDATE = {'amp_sim': validate}
SCHEMA_PATCH = {'amp_sim': patch_schema}
