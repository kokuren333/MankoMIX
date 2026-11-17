"""Two-rotor propagation with analytic acceleration and angular directivity.

Delay-line/directivity principle: Smith et al., DAFx-02,
https://dafx.de/paper-archive/2002/DAFX02_Smith_Serafin_Abel_Berners_doppler_leslie.pdf .
No measured device responses are used. Radii (.25/.18 m), normalized
directivity and angular cutoff below are explicitly chosen model constants.
Only one horn aperture radiates (one modulation cycle per revolution).
"""
import numpy as np
from mankomix.dspx.params import _f, _e, _i


def rotor_angles(frames, sr, p, rotor='horn', *, start_sample=0):
    """Return radians and Hz from the exact integrated piecewise-linear ODE."""
    from mankomix.dspx.bb.motion import rotor_motion
    curve = p['speed_curve'] or [[0, {'stop': 0, 'slow': 1, 'fast': 2}[p['speed']]]]
    a = np.asarray(curve, dtype=np.float64)
    knots = a[:, 0].tolist()
    for j in range(len(a)-1):
        if min(a[j, 1], a[j+1, 1]) < 1 < max(a[j, 1], a[j+1, 1]):
            knots.append(a[j, 0]+(1-a[j, 1])/(a[j+1, 1]-a[j, 1])*(a[j+1, 0]-a[j, 0]))
    knots = np.array(sorted(set(knots)))
    speed = np.interp(knots, a[:, 0], a[:, 1])
    target = np.interp(speed, [0, 1, 2], [0, p[rotor+'_slow_hz'], p[rotor+'_fast_hz']])
    t = np.arange(start_sample, start_sample+frames, dtype=np.int64)/sr
    cycles, hz = rotor_motion(t, np.column_stack((knots, target)), p[rotor+'_accel_s'])
    return 2*np.pi*cycles, hz


def _rotor(x, sr, theta, depth, p, radius, horn):
    from mankomix.dspx.bb.delayline import read_samples
    phases = theta[:, None]+np.array([-1, 1])*np.deg2rad(p['mic_angle_deg'])/2
    facing = np.cos(phases)
    delay = sr*radius/343*depth*(1-facing)
    mono = np.repeat(np.mean(x, axis=1)[:, None], 2, axis=1)
    wet = read_samples(mono, np.arange(len(x))[:, None]-delay, 'lagrange3')
    amount = depth*(.15+.65*(1-p['mic_distance']))
    wet *= 1-amount*(1-facing)/2
    cutoff = (2500+15500*(1+facing)/2) if horn else (1400+2600*(1+facing)/2)
    cutoff = (1-depth)*(.45*sr)+depth*np.minimum(cutoff, .45*sr)
    coef = np.exp(-2*np.pi*cutoff/sr)
    state = [0., 0.]
    out = []
    for values, coefficients in zip(wet.tolist(), coef.tolist()):
        for ch in range(2):
            state[ch] = (1-coefficients[ch])*values[ch]+coefficients[ch]*state[ch]
        out.append(state.copy())
    return np.asarray(out).reshape((-1, 2))


def rotary(x, sr, p, *, seed=0):
    from mankomix.dsp.errors import ParamError
    from mankomix.dspx.bb.crossover import split_bands
    from mankomix.dspx.bb.nonlinear import oversampled
    from mankomix.dspx.bb.delayline import spatial_stats
    if p['crossover_hz'] >= .98*sr/2:
        raise ParamError('crossover_hz must be below 0.98 * Nyquist')
    if not p['mix']:
        return x.copy(), sr, spatial_stats(x, sr)
    source = x
    if p['drive_db']:
        drive = 10**(p['drive_db']/20)
        source = oversampled(x, 4, lambda v: np.tanh(drive*v)/drive)
    bands, _ = split_bands(source, sr, [p['crossover_hz']], 'minimum')
    horn, _ = rotor_angles(len(x), sr, p, 'horn')
    drum, _ = rotor_angles(len(x), sr, p, 'drum')
    high = _rotor(bands[1], sr, horn, p['horn_depth'], p, .25, True)
    low = _rotor(bands[0], sr, drum, p['drum_depth'], p, .18, False)
    wet = high*min(1, 1+p['balance'])+low*min(1, 1-p['balance'])
    dry = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x
    y = wet if p['mix'] == 1 else (1-p['mix'])*dry+p['mix']*wet
    return y, sr, spatial_stats(y, sr)


def _params():
    from mankomix.dspx.bb.motion import curve_param
    out = [_e('speed', ['slow', 'fast', 'stop'], 'slow', 'Steady target speed.'),
           curve_param('speed_curve', 's', 0, 36000, 0, 2, 256, [])]
    for rotor, slow, fast, tau, depth in [('horn', .8, 6.8, 1, .7), ('drum', .7, 5.9, 4.5, .4)]:
        out += [_f(rotor+'_slow_hz', 'Hz', .3, 2, slow, 'Slow rotation frequency.'),
                _f(rotor+'_fast_hz', 'Hz', 4, 10, fast, 'Fast rotation frequency.'),
                _f(rotor+'_accel_s', 's', .1, 10, tau, 'Velocity time constant.'),
                _f(rotor+'_depth', None, 0, 1, depth, 'Doppler and amplitude depth.')]
    return out + [_f('crossover_hz', 'Hz', 400, 1600, 800, 'LR4 crossover.'),
                  _f('mic_angle_deg', 'degree', 0, 180, 90, 'Virtual microphone opening.'),
                  _f('mic_distance', None, 0, 1, .5, 'Normalized microphone distance.'),
                  _f('drive_db', 'dB', 0, 24, 0, 'Front-end saturation.'),
                  _f('balance', None, -1, 1, 0, 'Horn versus drum balance.'),
                  _f('mix', None, 0, 1, 1, 'Wet proportion.'),
                  _i('seed', None, 0, 65535, 0, 'Reserved deterministic seed.')]


SPECS = [dict(type='rotary', implemented=True, description='Two accelerating rotors with cubic Doppler and angular radiation.',
              params=_params(), stages=['track', 'bus'], master_slot=None, channel_ok=False,
              offline_only=False, backends=['reference'],
              realtime=dict(block_ok=False, allocates=True, latency_samples=0))]
IMPLS = {'rotary': rotary}
TIME_VARYING = {'rotary'}
