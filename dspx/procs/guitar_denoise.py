"""T10-16 exact fixed composite mapping; zero controls omit their stages."""
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f


def validate(p):
    if 0 < p['hum_hz'] < 40:
        raise ParamError('hum_hz must be zero or 40..70')


def expand(p):
    """Resolved controls -> ordinary child chain, in the specified order."""
    validate(p)
    out = []
    if p['hum']:
        out.append(dict(type='dehum',params=dict(depth_db=60*p['hum'],harmonics=16,base_hz=p['hum_hz'])))
    if p['amp_noise']:
        out.extend([dict(type='denoise',params=dict(profile='auto',reduction_db=30*p['amp_noise'])),
                    dict(type='gate',params=dict(range_db=-30*p['amp_noise'],threshold_db=p['gate_threshold_db']))])
    if p['squeak']:
        out.append(dict(type='resonance_suppressor',params=dict(depth_db=24*p['squeak'],lo_hz=2000,hi_hz=8000)))
    if p['pick']:
        out.append(dict(type='transient_shaper',params=dict(attack_db=-9*p['pick'])))
    return out


SPECS = [dict(type='guitar_denoise',implemented=False,composite=True,
    description='Fixed hum/noise/gate/string-noise/pick composite.',stages=['track','bus'],master_slot=None,
    offline_only=True,backends=['reference'],realtime=dict(block_ok=False,allocates=True,latency_samples='variable',
        latency_rule='Expanded children compensate their declared latency.'),params=[
    _f('hum',None,0,1,.5,'Hum amount.'),_f('hum_hz','Hz',0,70,0,'Zero auto, otherwise 40..70.'),
    _f('amp_noise',None,0,1,.3,'Amplifier noise amount.'),_f('gate_threshold_db','dBFS',-80,0,-55,'Gate threshold.'),
    _f('squeak',None,0,1,0,'String-noise amount.'),_f('pick',None,0,1,0,'Pick attenuation.')])]
IMPLS = {}
COMPOSITES = {'guitar_denoise':expand}
CROSS_VALIDATE = {'guitar_denoise':validate}
