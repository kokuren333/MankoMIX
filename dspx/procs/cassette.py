"""Fixed cassette component mapping; see dspx/COMPOSITES.md."""
from mankomix.dspx.params import _f, _e, _i

TAPE_TYPES = {'normal': (.45, .65, 10000), 'chrome': (.55, .45, 14000),
              'metal': (.6, .3, 16000)}


def expand(p):
    """Resolved controls -> ordinary chain items; zero amounts omit stages."""
    result = []
    seed = p['seed']
    w, s, age = p['wobble'], p['saturation'], p['age']
    bias, gap, cutoff = TAPE_TYPES[p['tape_type']]
    if w:
        result.append(dict(type='wow_flutter', params=dict(wow_depth=1.5*w, flutter_depth=.4*w, seed=seed)))
    if s or age:
        result.append(dict(type='tape', params=dict(speed=3.75, saturation=s, drive_db=6*s,
            bias=bias, gap_loss=min(1, gap+.35*age), seed=seed)))
    if age:
        result.append(dict(type='cut_filter', params=dict(kind='lpf', freq_hz=cutoff*(1-.5*age))))
    if p['hiss_db'] > -120 or age:
        result.append(dict(type='noise_bed', params=dict(hiss_db=p['hiss_db'], dropout=.3*age, seed=seed)))
    if p['narrow']:
        result.append(dict(type='stereo', params=dict(width=1-.5*p['narrow'])))
    return result


SPECS = [dict(type='cassette', implemented=True, composite=True,
    description='Fixed cassette degradation composite.', stages=['track','bus'], master_slot=None,
    offline_only=False, backends=['reference'], channel_ok=False,
    realtime=dict(block_ok=False, allocates=True, latency_samples='variable',
                  latency_rule='Expanded child processors declare and compensate latency.'),
    params=[_f('wobble',None,0,1,.3,'Motion amount.'), _f('saturation',None,0,1,.5,'Tape saturation.'),
        _e('tape_type',['normal','chrome','metal'],'normal','Fixed material map.'),
        _f('age',None,0,1,.3,'Loss and dropout amount.'),
        _f('hiss_db','dBFS',-120,-40,-66,'Hiss level; -120 disables.'),
        _f('narrow',None,0,1,.2,'Stereo narrowing.'), _i('seed',None,0,65535,0,'Child seed.')])]
IMPLS = {}
COMPOSITES = {'cassette': expand}
