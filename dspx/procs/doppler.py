"""Moving point source with retarded-time propagation and cubic delay reads.

Retarded time e solves t=e+(r(e)-r_min)/c. Differentiation gives exactly
f_out=f_in*c/(c+dr/de), unlike evaluating distance on the receiver clock.
The fixed minimum propagation time is removed, declared latency is zero.
"""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f


def check_runtime(p, sr=None):
    """Reject reversed intervals, nonmonotone paths and radial speeds >= .9c."""
    if p['end_s'] <= p['start_s']:
        raise ParamError('end_s must exceed start_s')
    a = np.asarray(p['path'])
    if not len(a):
        raise ParamError('path must be nonempty')
    if np.any(np.diff(a[:, 1]) < 0):
        raise ParamError('path must be monotone nondecreasing')
    if len(a) == 1:
        return
    xx = p['x0_m']+(p['x1_m']-p['x0_m'])*a[:, 1]
    velocity = np.diff(xx)/(np.diff(a[:, 0])*(p['end_s']-p['start_s']))
    radial = np.abs(velocity[:, None]*np.column_stack((xx[:-1], xx[1:])) /
                    np.hypot(np.column_stack((xx[:-1], xx[1:])), p['y_m']))
    if np.any(radial >= .9*p['speed_of_sound']):
        raise ParamError('radial speed must remain below 0.9 * speed_of_sound')


def trajectory(times, p):
    """Return x, range, radial velocity at absolute emission times."""
    a = np.asarray(p['path'])
    u = (np.asarray(times)-p['start_s'])/(p['end_s']-p['start_s'])
    value = np.interp(u, a[:, 0], a[:, 1])
    xx = p['x0_m']+(p['x1_m']-p['x0_m'])*value
    if len(a) == 1:
        distance = np.hypot(xx, p['y_m'])
        return xx, distance, np.zeros_like(xx)
    index = np.clip(np.searchsorted(a[:, 0], u, side='right')-1, 0, len(a)-2)
    velocity = (p['x1_m']-p['x0_m'])*np.diff(a[:, 1])[index]/np.diff(a[:, 0])[index]/(p['end_s']-p['start_s'])
    velocity = np.where((u > a[0, 0]) & (u < a[-1, 0]), velocity, 0)
    distance = np.hypot(xx, p['y_m'])
    return xx, distance, xx*velocity/distance


def propagation(frames, sr, p, *, start_sample=0):
    """Return absolute emission seconds, pan positions, range and gain."""
    check_runtime(p, sr)
    t = np.arange(start_sample, start_sample+frames, dtype=np.int64)/sr
    endpoints = p['x0_m']+(p['x1_m']-p['x0_m'])*np.asarray(p['path'])[[0,-1], 1]
    closest_x = np.clip(0, endpoints.min(), endpoints.max())
    minimum = np.hypot(closest_x, p['y_m'])
    # Monotonic arrival map; bracketed bisection avoids Newton jumps at knots.
    maximum = float(np.max(np.hypot(endpoints, p['y_m'])))
    lo = t-p['pitch_amount']*(maximum-minimum)/p['speed_of_sound']
    hi = t.copy()
    for _ in range(50):
        e = (lo+hi)/2
        arrival = e+p['pitch_amount']*(trajectory(e, p)[1]-minimum)/p['speed_of_sound']
        lo, hi = np.where(arrival < t, e, lo), np.where(arrival >= t, e, hi)
    e = t if p['pitch_amount'] == 0 else (lo+hi)/2
    xx, distance, _ = trajectory(e, p)
    pan = p['pan_amount']*np.arctan2(xx, p['y_m'])/(np.pi/2)
    gain = np.minimum(p['gain_ref_m']/distance, 10**(p['max_gain_db']/20))
    return e, pan, distance, gain


def doppler(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.motion import pan_audio
    from mankomix.dspx.bb.delayline import read_samples, spatial_stats
    check_runtime(p, sr)
    if not p['mix']:
        return x.copy(), sr, spatial_stats(x, sr)
    e, position, distance, gain = propagation(len(x), sr, p)
    wet = x.copy() if not p['pitch_amount'] else read_samples(x, e*sr, 'lagrange3')
    if p['air']:
        cutoff = np.minimum(.45*sr, 20000/(1+p['air']*distance/10))
        a = np.exp(-2*np.pi*cutoff/sr)
        state = np.zeros(x.shape[1])
        for n in range(len(x)):
            state = (1-a[n])*wet[n]+a[n]*state
            wet[n] = state
    wet = pan_audio(wet*gain[:, None], position)
    dry = pan_audio(x, np.zeros(len(x))) if x.shape[1] == 1 else x
    y = wet if p['mix'] == 1 else (1-p['mix'])*dry+p['mix']*wet
    stats = spatial_stats(y, sr)
    stats.update(propagation='retarded emission time; minimum propagation removed',
                 range_min_m=float(distance.min()) if len(x) else None,
                 range_max_m=float(distance.max()) if len(x) else None)
    return y, sr, stats


def _params():
    from mankomix.dspx.bb.motion import curve_param
    return [_f('start_s', 's', 0, 36000, 0, 'Pass start time.'),
            _f('end_s', 's', 0, 36000, 4, 'Pass end time.'),
            _f('x0_m', 'm', -500, 500, -30, 'Initial lateral position.'),
            _f('x1_m', 'm', -500, 500, 30, 'Final lateral position.'),
            _f('y_m', 'm', .5, 200, 5, 'Forward distance.'),
            curve_param('path', 'phase', 0, 1, 0, 1, 64, [[0, 0], [1, 1]]),
            _f('speed_of_sound', 'm/s', 300, 360, 343, 'Propagation speed.'),
            _f('gain_ref_m', 'm', .5, 50, 5, 'Unity gain reference distance.'),
            _f('max_gain_db', 'dB', 0, 12, 0, 'Maximum distance gain.'),
            _f('air', None, 0, 1, .5, 'Distance-dependent air absorption.'),
            _f('pan_amount', None, 0, 1, 1, 'Geometric pan amount.'),
            _f('pitch_amount', None, 0, 1, 1, 'Propagation modulation amount.'),
            _f('mix', None, 0, 1, 1, 'Wet proportion.')]


SPECS = [dict(type='doppler', implemented=True, description='Point-source propagation, distance gain and geometric pan.',
              params=_params(), stages=['track', 'bus'], master_slot=None, channel_ok=False,
              offline_only=False, backends=['reference'],
              realtime=dict(block_ok=False, allocates=True, latency_samples=0))]
IMPLS = {'doppler': doppler}
TIME_VARYING = {'doppler'}
CROSS_VALIDATE = {'doppler': check_runtime}
