"""T10-11 conservative deterministic high-band estimation."""
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e, _i
from mankomix.dspx.bb.restoration import definition, rp_params, validate_region


def validate(p):
    validate_region(p)
    if 0 < p['cutoff_hz'] < 2000:
        raise ParamError('cutoff_hz must be zero or 2000..20000')
    if p['cutoff_hz'] and p['top_hz'] <= p['cutoff_hz']:
        raise ParamError('top_hz must exceed cutoff_hz')


def hf_restore(x,sr,p,*,seed=0):
    from mankomix.dspx.bb.bandwidth_extension import extend
    from mankomix.dspx.bb.restoration import region_mix, finish
    validate(p)
    if p['amount'] and len(x):
        addition, info = extend(x,sr,p,seed=seed)
        y = region_mix(x,x+addition,sr,p) if info['detected'] else x.copy()
    else:
        y, info = x.copy(), dict(detected=False,cutoff_hz=None,cliff_depth_db=0.,
            caveat='Generated high frequencies are an estimate, not restoration of original content.')
    return finish(x,y,sr,p,**info)


SPECS = [definition('hf_restore',rp_params(.7)+[
    _f('cutoff_hz','Hz',0,20000,0,'Zero auto; otherwise >=2000 Hz.'),_f('top_hz','Hz',4000,22000,16000,'Extension top.'),
    _e('source',['copy_up','harmonic'],'copy_up','High-band generator.'),
    _f('slope_db_oct','dB/oct',-24,0,0,'Zero extrapolates observed slope.'),_f('level_db','dB',-12,6,0,'Generated level offset.'),
    _f('noise_mix',None,0,1,.3,'Noise power proportion.'),_f('transient_follow',None,0,1,.7,'Observed-envelope following.'),
    _i('seed',None,0,65535,0,'Parameter random seed.')])]
SPECS[0]['description'] = 'Estimated high-band extension with conservative cliff detection.'
SPECS[0]['implemented'] = True
IMPLS = {'hf_restore':hf_restore}
CROSS_VALIDATE = {'hf_restore':validate}
