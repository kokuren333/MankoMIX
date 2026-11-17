"""Three second-order state-variable bands with relative musical delays.

The critically damped SVF low/high transfer functions are bilinear mapped.
The middle output has negative polarity for flat allpass recombination when
delays and equalization are zero. Independent band delays can cause combing;
the public candidate remains unavailable until the specified limits pass.
"""
import numpy as np
from mankomix.dspx.params import _f, _b


def svf_bands(x, sr, lo, hi):
    """Return low, unsigned middle, high from two damped SVF integrator pairs."""
    from scipy import signal
    def split(u, f):
        g = np.tan(np.pi*f/sr)
        a = np.array([(1+g)**2, 2*(g*g-1), (1-g)**2])
        lp = signal.lfilter(g*g*np.array([1, 2, 1]), a, u, axis=0)
        hp = signal.lfilter(np.array([1, -2, 1]), a, u, axis=0)
        return lp, hp
    low, upper = split(x, lo)
    ll, lh = split(low, hi)
    middle, high = split(upper, hi)
    return ll-lh, middle, high


def phase_enhancer(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.delayline import fractional_delay
    from mankomix.dspx.bb.lowend import amplitude_envelope
    if p['hi_xover_hz'] >= .49*sr:
        from mankomix.dsp.errors import ParamError
        raise ParamError('hi_xover_hz must be below 0.49*sr')
    info = dict(latency_samples=0, musical_delays_ms=[p['amount']*p['lo_delay_ms'],
                p['amount']*p['mid_delay_ms'], 0])
    if not p['amount'] or not len(x):
        return x.copy(), sr, info
    low, mid, high = svf_bands(x, sr, p['lo_xover_hz'], p['hi_xover_hz'])
    low = fractional_delay(low, p['amount']*p['lo_delay_ms']*sr/1000, 'sinc256')
    mid = fractional_delay(mid, p['amount']*p['mid_delay_ms']*sr/1000, 'sinc256')
    env = amplitude_envelope(mid, sr, 10, 120)
    level = 20*np.log10(np.maximum(env, 1e-12))
    quiet = np.clip((-level-10)/30, 0, 1)
    hi_db = p['amount']*p['hi_process_db']*((1-p['hi_dynamic'])+p['hi_dynamic']*quiet)
    y = low*10**(p['amount']*p['lo_contour_db']/20)
    y += (-mid if p['mid_invert'] else mid)+high*10**(hi_db/20)
    return y, sr, info


def _spec():
    from mankomix.dspx.bb.lowend import definition
    return definition('phase_enhancer', [
        _f('amount', '0..1', 0, 1, 0, 'Zero bypasses all processing.'),
        _f('lo_xover_hz', 'Hz', 80, 400, 150, 'Low crossover.'),
        _f('hi_xover_hz', 'Hz', 1200, 5000, 2400, 'High crossover.'),
        _f('lo_delay_ms', 'ms', 0, 5, 2.5, 'Low delay at amount one.'),
        _f('mid_delay_ms', 'ms', 0, 2, .5, 'Middle delay at amount one.'),
        _f('lo_contour_db', 'dB', 0, 12, 0, 'Low contour.'),
        _f('hi_process_db', 'dB', 0, 12, 4, 'Maximum high enhancement.'),
        _f('hi_dynamic', '0..1', 0, 1, .5, 'Quiet-middle high boost.'),
        _b('mid_invert', True, 'Invert middle for allpass recombination.')],
        'Three SVF bands, relative delays and level-dependent high enhancement.')


SPECS = [_spec()]
IMPLS = {'phase_enhancer': phase_enhancer}
TIME_VARYING = {'phase_enhancer'}
