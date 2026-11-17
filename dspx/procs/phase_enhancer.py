"""Joint allpass delay equalization with state-variable tone/detector bands.

Absolute band delays are calibrated together as stable second-order
allpasses, preserving unity magnitude at every frequency. The critically
damped SVF branches control contour, polarity and dynamic high enhancement.
"""
from functools import lru_cache
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


@lru_cache(maxsize=128)
def delay_sos(sr, lo, hi, low_ms, mid_ms):
    """Joint allpass calibration: absolute delay without crossover combing.

    Two damped second-order continuous-time allpasses are bilinear mapped.
    Their group delays are analytic positive Lorentzian pairs. Center offsets
    are solved at the low and middle band centers; damping is kept broad
    except when one requested delay is zero. No inverse audio filter is used.
    """
    from scipy import signal, optimize
    centers = np.array([lo/3.75, np.sqrt(lo*hi)])
    target = np.array([low_ms, mid_ms])
    use = np.flatnonzero(target > 0)
    if not len(use):
        return np.empty((0, 6))
    w = 2*sr*np.tan(np.pi*centers/sr)
    damping = np.minimum(np.array([.4, .25])*w, 1000/np.maximum(target, 1e-30))
    # Near-zero adjacent delays require a more selective phase transition.
    for i in range(2):
        damping[i] *= min(1., max(.01, 5*target[1-i]/max(target[i], 1e-30)))
    damping *= np.minimum(1., target)
    damping = np.maximum(damping[use], 1.)
    def delays(z):
        pole_hz = np.exp(z)
        a = damping[:, None]
        g = np.sum(2*a/(a*a+(w-pole_hz[:, None])**2)
                   + 2*a/(a*a+(w+pole_hz[:, None])**2), axis=0)
        return g/np.cos(np.pi*centers/sr)**2*1000
    scale = np.maximum(.005, target*.05)
    best = None
    for ratio in (1.4, .8, 2.):
        result = optimize.least_squares(lambda z: (delays(z)-target)/scale,
            np.log(w[use]*ratio), bounds=(np.log(np.ones(len(use))),
            np.log(np.full(len(use), 100*sr))), max_nfev=120)
        if best is None or result.cost < best.cost:
            best = result
    sos = []
    for a, b in zip(damping, np.exp(best.x)):
        # Stable poles -a +/- j*b, reflected zeros +a +/- j*b.
        bd, ad = signal.bilinear([1., -2*a, a*a+b*b],
                                [1., 2*a, a*a+b*b], fs=sr)
        sos.extend(signal.tf2sos(bd, ad))
    return np.asarray(sos)


def phase_enhancer(x, sr, p, *, seed=0):
    from scipy import signal
    from mankomix.dspx.bb.lowend import amplitude_envelope
    if p['hi_xover_hz'] >= .49*sr:
        from mankomix.dsp.errors import ParamError
        raise ParamError('hi_xover_hz must be below 0.49*sr')
    low_ms, mid_ms = p['amount']*p['lo_delay_ms'], p['amount']*p['mid_delay_ms']
    info = dict(latency_samples=0, musical_delays_ms=[low_ms, mid_ms, 0],
                phase_network='joint_second_order_allpass')
    if not p['amount'] or not len(x):
        return x.copy(), sr, info
    sos = delay_sos(sr, p['lo_xover_hz'], p['hi_xover_hz'], low_ms, mid_ms)
    base = signal.sosfilt(sos, x, axis=0) if len(sos) else x.copy()
    # SVF bands remain the tone/detector branches. The jointly calibrated
    # allpass replaces independently delayed summation, which creates notches.
    low, mid, high = svf_bands(base, sr, p['lo_xover_hz'], p['hi_xover_hz'])
    env = amplitude_envelope(mid, sr, 10, 120)
    level = 20*np.log10(np.maximum(env, 1e-12))
    quiet = np.clip((-level-10)/30, 0, 1)
    hi_db = p['amount']*p['hi_process_db']*((1-p['hi_dynamic'])+p['hi_dynamic']*quiet)
    y = base+low*np.expm1(p['amount']*p['lo_contour_db']*np.log(10)/20)
    y += high*np.expm1(hi_db*np.log(10)/20)
    if not p['mid_invert']:
        y += 2*mid
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
SPECS[0]['implemented'] = True
IMPLS = {'phase_enhancer': phase_enhancer}
TIME_VARYING = {'phase_enhancer'}
