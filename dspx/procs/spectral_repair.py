"""T10-10 numeric spectral rectangles (GUI belongs to W4)."""
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _b, _e, _f


def validate(p):
    if len({len(p[k]) for k in ('t0_s','t1_s','lo_hz','hi_hz')}) != 1:
        raise ParamError('all rectangle arrays must have equal lengths')
    for t0, t1, lo, hi in zip(p['t0_s'],p['t1_s'],p['lo_hz'],p['hi_hz']):
        if t1 <= t0 or t1-t0 > 2.000000000001 or hi <= lo:
            raise ParamError('rectangles require t1>t0, duration<=2 s and hi>lo')


def spectral_repair(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.spectral_repair import repair_audio
    from mankomix.dspx.bb.restoration import finish
    validate(p)
    rectangles = list(zip(p['t0_s'],p['t1_s'],p['lo_hz'],p['hi_hz']))
    y = repair_audio(x,sr,rectangles,**{k:p[k] for k in ('window','mode','attenuate_db','context_ms','feather_ms','feather_oct')}) if rectangles else x.copy()
    return finish(x,y,sr,p,rectangle_count=len(rectangles))


SPECS = [dict(type='spectral_repair',implemented=True,description='Explicit spectral rectangle repair.',
    stages=['track','bus'],master_slot=None,offline_only=True,backends=['reference'],
    realtime=dict(block_ok=False,latency_samples=0,allocates=True),
    params=[_b('delta',False,'Residual audition.'),
        _a('t0_s','s',0,36000,64,[],'Rectangle starts.'),_a('t1_s','s',0,36000,64,[],'Ends, at most 2 s later.'),
        _a('lo_hz','Hz',0,24000,64,[],'Lower edges.'),_a('hi_hz','Hz',0,24000,64,[],'Upper edges.'),
        _e('mode',['attenuate','replace_time','replace_freq','pattern'],'replace_time','Repair method.'),
        _f('attenuate_db','dB',0,60,12,'Maximum attenuation.'),_f('context_ms','ms',20,2000,200,'Clean context.'),
        _f('feather_ms','ms',0,100,10,'Time feather.'),_f('feather_oct','oct',0,.5,.05,'Frequency feather.'),
        _e('window',[1024,2048,4096],2048,'48 kHz window.')])]
IMPLS = {'spectral_repair':spectral_repair}
CROSS_VALIDATE = {'spectral_repair':validate}
