"""Fixed creative rack mappings; see dspx/COMPOSITES.md."""
from mankomix.dspx.params import _f, _e, _i

# wow, flutter, drive, lost bits, minimum clock, HP, LP, noise channels
STYLES = {
    'tape': (1.5,.4,12,12,12000,30,10000,('hiss',)),
    'vinyl': (.8,.2,9,10,16000,40,12000,('crackle','rumble')),
    'digital': (.3,.08,18,20,4000,20,18000,('hiss',)),
    'radio': (.2,.05,15,16,8000,300,3500,('hiss','hum')),
}


def expand(p):
    """Expand resolved controls using the documented fixed table."""
    wow, flutter, drive, bits, rate, low, high, noises = STYLES[p['style']]
    result = []
    w,d,c,t,n,s = (p[k] for k in ('wobble','dirt','crunch','tone','noise','space'))
    if w:
        result.append(dict(type='wow_flutter', params=dict(wow_depth=wow*w, flutter_depth=flutter*w, seed=p['seed'])))
    if d:
        result.append(dict(type='saturator', params=dict(drive_db=drive*d, mode='tanh')))
    if c:
        result.append(dict(type='bitcrush', params=dict(bits=24-bits*c,
            rate_hz=192000*(rate/192000)**c, antialias=False, seed=p['seed'])))
    if t:
        # One cut_filter has one edge: the band requires two ordinary children.
        result.extend([dict(type='cut_filter', params=dict(kind='hpf', freq_hz=low*t)),
                       dict(type='cut_filter', params=dict(kind='lpf', freq_hz=20000*(high/20000)**t))])
        result[-2]['params']['freq_hz'] = max(10, low*t)
    if n:
        noise = dict(seed=p['seed'])
        for name in noises:
            peak = {'hiss':-45, 'crackle':-35, 'rumble':-45, 'hum':-50}[name]
            noise[name+'_db'] = -120+(120+peak)*n
        if p['style'] == 'digital':
            noise['hiss_color'] = 'white'
        result.append(dict(type='noise_bed', params=noise))
    if s:
        result.append(dict(type='reverb', params=dict(rt60_s=.3, predelay_ms=0, mix=.25*s)))
    return result


SPECS = [dict(type='lofi', implemented=True, composite=True, description='Fixed creative degradation rack.',
    stages=['track','bus'], master_slot=None, offline_only=False, backends=['reference'], channel_ok=False,
    realtime=dict(block_ok=False, allocates=True, latency_samples='variable',
                  latency_rule='Expanded children declare and compensate their latency.'),
    params=[_e('style',['tape','vinyl','digital','radio'],'tape','Fixed component map.'),
        _f('wobble',None,0,1,.3,'Motion.'), _f('dirt',None,0,1,.3,'Drive.'),
        _f('crunch',None,0,1,0,'Quantization.'), _f('tone',None,0,1,.5,'Band restriction.'),
        _f('noise',None,0,1,.3,'Noise.'), _f('space',None,0,1,0,'Short room.'),
        _i('seed',None,0,65535,0,'Child seed.')])]
IMPLS = {}
COMPOSITES = {'lofi': expand}
TIME_VARYING = {'lofi'}
