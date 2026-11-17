"""Oversampled ideal/diode ring modulation with absolute carrier integration.

The four rectifier branches follow Parker, DAFx-11, section 3, independently
implemented from https://www.dafx.de/paper-archive/2011/Papers/66_e.pdf .
Diode thresholds are normalized design choices (.2/.4), not measured hardware.
"""
import numpy as np
from mankomix.dspx.params import _f, _e


def carrier_phase(frames, sr, p, *, seed=0, start_sample=0):
    """Carrier cycles; log-linear curve segments are integrated analytically.

    With LFO FM, its log-frequency is sampled on a fixed absolute 2560 Hz
    control grid (at least 128 points per fastest LFO cycle), then integrated
    as log-linear segments. Endpoint/grid knots do not depend on excerpt size.
    """
    from mankomix.dspx.bb.motion import curve_integral
    from mankomix.dspx.bb.curves import evaluate_curve
    from mankomix.dspx.bb.modulation import mod_lfo
    t = np.arange(start_sample, start_sample+frames, dtype=np.int64)/sr
    points = p['freq_curve'] or [[0, p['freq_hz']]]
    if p['lfo_depth_oct'] and len(t):
        last = int(np.ceil(t[-1]*2560))+1
        grid = np.arange(last+1)/2560
        knots = np.unique(np.r_[grid, np.asarray(points)[:, 0]])
        # Evaluate the absolute LFO at the fixed control clock, not the audio clock.
        wave = mod_lfo(len(grid), 2560, dict(p, depth=1, stereo_phase=0, phase=0),
                       seed=seed)[:, 0]
        base = np.exp(evaluate_curve([[a, np.log(b)] for a, b in points], knots))
        freq = base*2**(p['lfo_depth_oct']*np.interp(knots, grid, wave))
        points = np.column_stack((knots, freq))
    return curve_integral(points, t, logarithmic=True)


def carrier_wave(cycles, frequency, sr, shape='sine'):
    """Additive odd harmonics with instantaneous cutoff at .45*base sr."""
    angle = 2*np.pi*np.remainder(cycles, 1)
    if shape == 'sine':
        return np.sin(angle)
    out = np.zeros_like(angle)
    max_harmonic = int(.45*sr/max(.1, float(np.min(frequency)))) if len(angle) else 0
    # At very low carrier frequencies an additive square may need many terms.
    for harmonic in range(1, max_harmonic+1, 2):
        weight = 4/(np.pi*harmonic) if shape == 'square' else 8/np.pi**2*(-1)**((harmonic-1)//2)/harmonic**2
        out += np.where(harmonic*frequency <= .45*sr, weight*np.sin(harmonic*angle), 0)
    return out


def diode_transfer(v):
    """C1 piecewise diode: zero, quadratic knee, then slope-one affine."""
    u = np.maximum(v-.2, 0)
    return np.where(u <= .2, u*u/.4, u-.1)


def diode_ring(x, c):
    a, b = c+x/2, c-x/2
    return diode_transfer(a)+diode_transfer(-a)-diode_transfer(b)-diode_transfer(-b)


def ring_mod(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.nonlinear import oversampled
    from mankomix.dspx.bb.delayline import spatial_stats
    from mankomix.dspx.bb.curves import evaluate_curve
    from mankomix.dspx.bb.modulation import validate_mod
    validate_mod(p)
    if not p['mix']:
        return x.copy(), sr, spatial_stats(x, sr)
    factor = p['oversample']
    def process(up):
        cycles = carrier_phase(len(up), sr*factor, p, seed=seed)
        times = np.arange(len(up))/(sr*factor)
        points = p['freq_curve'] or [[0, p['freq_hz']]]
        freq = np.exp(evaluate_curve([[a, np.log(b)] for a, b in points], times))
        if p['lfo_depth_oct']:
            from mankomix.dspx.bb.modulation import mod_lfo
            freq *= 2**(p['lfo_depth_oct']*mod_lfo(len(up), sr*factor,
                         dict(p, depth=1, stereo_phase=0, phase=0), seed=seed)[:, 0])
        c = carrier_wave(cycles, freq, sr, p['carrier'])[:, None]
        wet = up*c
        if p['diode']:
            wet = (1-p['diode'])*wet+p['diode']*diode_ring(up, c)
        return (1-p['am'])*wet+p['am']*(up+wet)/2
    wet = oversampled(x, factor, process)
    y = wet if p['mix'] == 1 else (1-p['mix'])*x+p['mix']*wet
    stats = spatial_stats(y, sr)
    stats.update(oversample=factor, carrier_harmonic_limit_hz=.45*sr,
                 fm_control_hz=2560, carrier_phase='analytic log-linear integral')
    return y, sr, stats


def _params():
    from mankomix.dspx.bb.motion import curve_param
    from mankomix.dspx.bb.modulation import mod_params
    common = [v for v in mod_params(1, 0, 0, 1) if v['id'] in
              ('rate_hz', 'note', 'bpm', 'lfo_shape', 'origin_s', 'mix', 'seed')]
    return [_f('freq_hz', 'Hz', .1, 10000, 440, 'Carrier frequency.'),
            _e('carrier', ['sine', 'triangle', 'square'], 'sine', 'Bandlimited carrier.'),
            curve_param('freq_curve', 's', 0, 36000, .1, 10000, 1024, []),
            _f('lfo_depth_oct', 'oct', 0, 4, 0, 'Log-frequency modulation.'),
            _f('am', None, 0, 1, 0, 'Blend toward unipolar 100 percent AM.'),
            _f('diode', None, 0, 1, 0, 'Blend toward a four-diode piecewise ring.'),
            _e('oversample', [1, 2, 4], 2, 'Multiplication oversampling.', unit='x')] + common


SPECS = [dict(type='ring_mod', implemented=True, description='Bandlimited ideal or four-diode ring modulation.',
              params=_params(), stages=['track', 'bus'], master_slot=None, channel_ok=True,
              offline_only=False, backends=['reference'],
              realtime=dict(block_ok=False, allocates=True, latency_samples=0))]
IMPLS = {'ring_mod': ring_mod}
TIME_VARYING = {'ring_mod'}


def validate(p):
    from mankomix.dspx.bb.modulation import validate_mod
    validate_mod(p)


CROSS_VALIDATE = {'ring_mod': validate}
