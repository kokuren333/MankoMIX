"""Two-path dispersive waveguide, synthesized IR and optional input drive."""
from mankomix.dspx.params import _f, _i


def reverb_spring(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.spring import render_spring_ir
    from mankomix.dspx.bb.fir import fft_convolve
    from mankomix.dspx.bb.reverb import finish, validate_rv
    from mankomix.dspx.bb import nonlinear as N
    import numpy as np
    validate_rv(p)
    if p['mix'] == 0 or not len(x):
        return x.copy(), sr, {'latency_samples': 0}
    h, stats = render_spring_ir(sr, p, seed)
    excitation = x
    if p['drive_db']:
        strength = 10**(p['drive_db']/20)
        excitation = N.precision_oversampled(x, 4, lambda u: np.tanh(strength*u)/strength)
    stereo = np.repeat(excitation, 2, axis=1) if x.shape[1] == 1 else excitation
    wet = fft_convolve(stereo, h, mode='same')
    if x.shape[1] == 1:
        wet = wet.mean(axis=1, keepdims=True)
    return finish(x, wet, sr, p, stats)


def _spec():
    from mankomix.dspx.bb.reverb import definition, rv_params
    params = rv_params(.5, 6, 2.5, predelay=0)
    for v in params:
        if v['id'] == 'lowcut_hz': v['default'] = 100
        if v['id'] == 'highcut_hz': v['default'] = 6000
    return definition('reverb_spring', params+[
        _i('springs',None,1,3,2,'Parallel springs.'),
        _f('delay_ms','ms',20,80,45,'Seeded round-trip delay.'),
        _f('chirp_hz','Hz',2000,8000,4300,'Dispersion transition.'),
        _f('dispersion',None,0,1,.7,'Allpass dispersion.'),
        _f('damping_hz','Hz',1000,12000,5000,'Excitation/output damping.'),
        _f('drive_db','dB',0,12,0,'Input saturation; zero bypasses.')], implemented=True)


SPECS = [_spec()]
IMPLS = {'reverb_spring': reverb_spring}
