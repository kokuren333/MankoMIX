"""T10-02: explicit speech-model suppression and recorded spectral fallback."""
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e


def validate(p):
    from mankomix.dspx.bb.ml import model_entry
    from mankomix.dspx.bb.restoration import validate_region
    validate_region(p)
    try:
        model_entry(p['model'], 'denoise')
    except LookupError:
        raise ParamError('denoise_ml requires a registered denoise model') from None


def denoise_ml(x, sr, p, *, seed=0):
    from mankomix.dsp import processors as P
    from mankomix.dspx.bb import ml, restoration
    from mankomix.dspx.procs.denoise import denoise
    validate(p)
    entry = ml.model_entry(p['model'], 'denoise')
    record = dict(model_id=p['model'], caveats=list(entry['license']['caveats']),
                  license=ml.registry.license_record(entry), fallback_used=False,
                  provider=None, latency_samples=0, latency_compensated=True)
    if not p['amount'] or not p['reduction_db'] or restoration.region(len(x), sr, p)[0] == restoration.region(len(x), sr, p)[1]:
        return restoration.finish(x, x.copy(), sr, p, **record, inference_skipped=True)
    try:
        resolved = ml.resolve_for_run(p['model'], 'denoise')
        wet, run = ml.infer(x, sr, resolved)
        record.update(run)
        wet = x+(1-10**(-p['reduction_db']/20))*(wet-x)
        y = restoration.region_mix(x, wet, sr, p)
    except ml.ModelUnavailable as exc:
        if p['fallback'] == 'error':
            raise
        fp = P.validate_params('denoise', dict(profile='auto', amount=p['amount'],
                  delta=False, start_s=p['start_s'], end_s=p['end_s'],
                  reduction_db=min(p['reduction_db'], 40)))
        y, _, fallback_stats = denoise(x, sr, fp, seed=seed)
        record.update(fallback_used=True, fallback=dict(type='denoise', params=fp,
                      reason=str(exc), mapping='automatic_profile_maximum_40_db'),
                      fallback_stats=fallback_stats, provider='reference')
    return restoration.finish(x, y, sr, p, **record)


def patch_schema(schema):
    schema.setdefault('required', []).append('model')
    schema['properties']['model'].pop('default', None)


from mankomix.dspx.bb.restoration import rp_params

SPECS = [dict(type='denoise_ml', implemented=False,
    description='Offline speech denoising; singing and instruments are unsuitable.',
    stages=['track'], master_slot=None, offline_only=True, backends=['model'],
    fallback=dict(type='denoise', mapping='auto profile; reduction capped at 40 dB'),
    realtime=dict(block_ok=False, latency_samples=0, allocates=True),
    params=[dict(id='model', type='asset', registry='models', unit=None, default='',
                 description='Required registered denoise model ID; weights are never fetched during render.'),
            _f('reduction_db', 'dB', 0, 60, 18, 'Maximum model correction blend.'),
            _e('fallback', ['denoise', 'error'], 'denoise', 'Action when local model/runtime is unavailable.'),
            *rp_params()])]
IMPLS = {'denoise_ml': denoise_ml}
CROSS_VALIDATE = {'denoise_ml': validate}
SCHEMA_PATCH = {'denoise_ml': patch_schema}
