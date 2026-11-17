"""T10-02: explicit speech-model suppression and recorded spectral fallback."""
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e


def _model_entry(model):
    """Resolve metadata without loading weights or accessing the network."""
    from mankomix.dspx.bb.ml import model_entry
    from mankomix.core import registry
    model = model or registry.default_model('denoise')
    if not model:
        return None
    try:
        return model_entry(model, 'denoise')
    except LookupError:
        raise ParamError('denoise_ml requires a registered denoise model') from None


def validate(p):
    from mankomix.dspx.bb.restoration import validate_region
    validate_region(p)
    _model_entry(p['model'])


def denoise_ml(x, sr, p, *, seed=0):
    from mankomix.dsp import processors as P
    from mankomix.dspx.bb import ml, restoration
    from mankomix.dspx.procs.denoise import denoise
    validate(p)
    entry = _model_entry(p['model'])
    record = dict(model_id=entry['id'] if entry else '',
                  caveats=list(entry['license']['caveats']) if entry else [ml.SPEECH_CAVEAT],
                  license=ml.registry.license_record(entry) if entry else None, fallback_used=False,
                  provider=None, latency_samples=0, latency_compensated=True)
    if not p['amount'] or not p['reduction_db'] or restoration.region(len(x), sr, p)[0] == restoration.region(len(x), sr, p)[1]:
        return restoration.finish(x, x.copy(), sr, p, **record, inference_skipped=True)
    try:
        if entry is None:
            raise ml.ModelUnavailable('no registered default denoise model; specify a model ID')
        resolved = ml.resolve_for_run(entry['id'], 'denoise')
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


from mankomix.dspx.bb.restoration import rp_params

SPECS = [dict(type='denoise_ml', implemented=False,
    description='Offline speech denoising; singing and instruments are unsuitable.',
    stages=['track'], master_slot=None, offline_only=True, backends=['model'],
    fallback=dict(type='denoise', mapping='auto profile; reduction capped at 40 dB'),
    realtime=dict(block_ok=False, latency_samples=0, allocates=True),
    params=[dict(id='model', type='asset', registry='models', unit=None, default='', allow_empty=True,
                 description='Registered denoise model ID; empty uses the registered denoise default or fallback. Weights are never fetched during render.'),
            _f('reduction_db', 'dB', 0, 60, 18, 'Maximum model correction blend.'),
            _e('fallback', ['denoise', 'error'], 'denoise', 'Action when local model/runtime is unavailable.'),
            *rp_params()])]
IMPLS = {'denoise_ml': denoise_ml}
CROSS_VALIDATE = {'denoise_ml': validate}
