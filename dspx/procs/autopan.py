"""Absolute-clock pan modulation; stereo uses the existing balance law."""
import numpy as np
from mankomix.dspx.params import _f, _e, _i


def _params():
    from mankomix.dspx.bb.motion import curve_param
    from mankomix.dspx.bb.modulation import mod_params
    common = mod_params(1, .5, 0, None)
    common = [v for v in common if v['id'] != 'stereo_phase']
    next(v for v in common if v['id'] == 'lfo_shape')['choices'].insert(2, 'square')
    return common + [
        _e('source', ['lfo', 'shape', 'envelope'], 'lfo', 'Pan control source.'),
        _f('center', None, -1, 1, 0, 'Central pan position.'),
        curve_param('shape', 'phase', 0, 1, -1, 1, 64, [[0, -1], [.5, 1], [1, -1]]),
        _f('env_attack_ms', 'ms', 1, 500, 20, 'Envelope rise time constant.'),
        _f('env_release_ms', 'ms', 10, 3000, 300, 'Envelope fall time constant.'),
        _f('env_threshold_db', 'dBFS', -80, 0, -40, 'Unity envelope reference.'),
        _f('smooth_ms', 'ms', 0, 50, 5, 'Pan smoothing time constant.')]


def validate(p):
    from mankomix.dsp.errors import ParamError
    from mankomix.dspx.bb.modulation import validate_mod
    validate_mod(p)
    if p['source'] == 'shape' and not p['shape']:
        raise ParamError('shape source requires nonempty shape')


def pan_positions(x, sr, p, *, seed=0, start_sample=0):
    """Pan positions; stateful sources/smoothing require input history from zero."""
    from mankomix.dspx.bb import curves as Q, dynamics as D
    from mankomix.dspx.bb.modulation import mod_lfo
    if p['source'] == 'envelope':
        level = np.max(np.abs(x), axis=1)/10**(p['env_threshold_db']/20)
        m = np.clip(D.smooth_python(level, D.coef(p['env_attack_ms'], sr),
                                   D.coef(p['env_release_ms'], sr)), 0, 1)
    elif p['source'] == 'shape':
        m = Q.periodic_curve(p['shape'], len(x), sr, period_ms=1000/p['rate_hz'],
                             note=p['note'], bpm=p['bpm'], origin_s=p['origin_s'],
                             phase=p['phase'], start_sample=start_sample)
    else:
        m = mod_lfo(len(x), sr, dict(p, stereo_phase=0), 1,
                    seed=seed, start_sample=start_sample)[:, 0]
    position = np.clip(p['center']+p['depth']*m, -1, 1)
    if p['smooth_ms']:
        position = D.envelope_signed(position, sr, p['smooth_ms'])
    return position


def autopan(x, sr, p, *, seed=0):
    from mankomix.dsp.reference.basic import pan
    from mankomix.dspx.bb.motion import pan_audio
    from mankomix.dspx.bb.delayline import spatial_stats
    validate(p)
    if p['depth'] == 0:
        y, _, _ = pan(x, sr, dict(position=p['center'], center_db=-3))
    else:
        y = pan_audio(x, pan_positions(x, sr, p, seed=seed))
    return y, sr, spatial_stats(y, sr)


SPECS = [dict(type='autopan', implemented=False, description='Absolute-clock equal-power autopan and stereo balance.',
              params=_params(), stages=['track', 'bus'], master_slot=None, channel_ok=False,
              offline_only=False, backends=['reference'],
              realtime=dict(block_ok=False, allocates=True, latency_samples=0))]
IMPLS = {'autopan': autopan}
TIME_VARYING = {'autopan'}
CROSS_VALIDATE = {'autopan': validate}
