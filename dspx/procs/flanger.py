"""Cubic modulated comb, signed feedback, and compensated through-zero dry path."""
import numpy as np

from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _b, _e
from mankomix.dspx.bb.modulation import mod_params, mod_lfo, mod_rate, modulation_definition
from mankomix.dspx.bb.delayline import DelayLine, LoopFilter, fractional_delay, spatial_stats


def _short_feedback(x, delays, sr, feedback, highcut):
    """Solve the centred cubic loop, including its current/future coefficients.

    D is BB-09's unmodified four-point interpolator with zero extension.
    For loop EQ F=B/A and stored signal u=x+feedback*F*D*u, solve
    (A-feedback*B*D)u=A*x. This full-context reference solve needs no
    minimum-delay clamp or extra sample in the loop. No streaming API.
    """
    from scipy import sparse
    from scipy.sparse.linalg import spsolve
    from mankomix.dspx.bb.delayline import _kernel

    n, channels = x.shape
    wet = np.zeros_like(x)
    if not n:
        return wet
    sos = LoopFilter(sr, channels, highcut=highcut).sos
    b, a = (np.array([1.]), np.array([1.])) if sos is None else (sos[0, :3], sos[0, 3:])
    def polynomial(coeff):
        return sparse.diags([np.full(n-k, value) for k, value in enumerate(coeff) if k < n],
                            -np.arange(min(n, len(coeff))), shape=(n, n), format='csc')
    numerator, denominator = polynomial(b), polynomial(a)
    rows = np.repeat(np.arange(n), 4)
    for c in range(channels):
        indices, weights = _kernel(np.arange(n)-delays[:, c], 'lagrange3')
        columns, values = indices.ravel(), weights.ravel()
        valid = (columns >= 0) & (columns < n) & (values != 0)
        reader = sparse.csc_matrix((values[valid], (rows[valid], columns[valid])), shape=(n, n))
        system = denominator - feedback * (numerator @ reader)
        stored = spsolve(system, denominator @ x[:, c], permc_spec='NATURAL', use_umfpack=False)
        wet[:, c] = reader @ stored
    return wet


def cross_validate(p):
    mod_rate(p)
    if p['min_delay_ms'] > p['delay_ms']:
        raise ParamError('min_delay_ms must not exceed delay_ms')


def latency_samples(sr, p):
    return round(p['delay_ms'] * sr / 2000) if p['through_zero'] and p['mix'] else 0


def delay_samples(frames, sr, p, channels=1, *, start_sample=0, seed=0):
    """Absolute sweep, depth zero at delay_ms."""
    cross_validate(p)
    wave = mod_lfo(frames, sr, p, channels, start_sample=start_sample, seed=seed)
    lo, hi = p['min_delay_ms'], p['delay_ms']
    u = (wave + 1) / 2
    if p['sweep'] == 'linear':
        sweep = lo + (hi-lo)*u
    else:
        # log1p supplies a finite, continuous logarithmic sweep through zero.
        scale = .01
        sweep = scale*np.expm1(np.log1p(lo/scale) + u*(np.log1p(hi/scale)-np.log1p(lo/scale)))
    return sr/1000 * (p['delay_ms'] + p['depth']*(sweep-p['delay_ms']))


def raw_flanger(x, sr, p, *, seed=0):
    mod_rate(p)
    latency = latency_samples(sr, p)
    if not p['mix']:
        return x.copy(), sr, {'latency_samples': 0, 'latency_compensated': False}
    delays = delay_samples(len(x), sr, p, x.shape[1], seed=seed)
    if p['feedback']:
        if np.any(delays < 3):
            # Cubic interpolation can reach one sample ahead. Continue the
            # zero-input tail so that this is feedback history, not a forced
            # zero stored value at the right edge. The 64-sample continuation
            # is verified against a longer continuation in the short-loop tests.
            tail = 64
            extended = np.pad(x, ((0, tail), (0, 0)))
            future = delay_samples(tail, sr, p, x.shape[1], start_sample=len(x), seed=seed)
            wet = _short_feedback(extended, np.concatenate((delays, future)), sr,
                                  p['feedback'], p['highcut_hz'])[:len(x)]
        else:
            filt = LoopFilter(sr, x.shape[1], highcut=p['highcut_hz'])
            wet = DelayLine(float(np.max(delays, initial=3)), x.shape[1], 'lagrange3').process(
                x, delays, feedback=abs(p['feedback']), loop=filt,
                matrix=np.eye(x.shape[1])*np.sign(p['feedback']))
        # Keep the specified +26 dB resonance ceiling even at mix=1:
        # 1/(1-.95) is +26.0206 dB without this tiny endpoint trim.
        wet *= min(1., (1-abs(p['feedback']))*10**(26/20))
    else:
        wet = fractional_delay(x, delays, 'lagrange3')
        wet = LoopFilter(sr, x.shape[1], highcut=p['highcut_hz'])(wet)
    dry = fractional_delay(x, latency, 'lagrange3')
    y = (1-p['mix'])*dry + p['mix']*(-wet if p['invert'] else wet)
    return y, sr, {'latency_samples': latency, 'latency_compensated': False,
                   'delay_min_samples': float(np.min(delays, initial=np.inf)) if len(x) else None,
                   'delay_max_samples': float(np.max(delays, initial=0))}


def flanger(x, sr, p, *, seed=0):
    latency = latency_samples(sr, p)
    padded = np.pad(x, ((0, latency), (0, 0))) if latency else x
    y, _, stats = raw_flanger(padded, sr, p, seed=seed)
    y = y[latency:latency+len(x)]
    stats.update(spatial_stats(y, sr))
    stats.update(latency_samples=latency, latency_compensated=True)
    return y, sr, stats


SPECS = [modulation_definition('flanger', mod_params(.25, .7, 0, .5) + [
    _f('delay_ms', 'ms', .1, 15, 2, 'Upper sweep delay.'),
    _f('min_delay_ms', 'ms', 0, 5, .2, 'Lower sweep delay.'),
    _f('feedback', None, -.95, .95, .5, 'Signed feedback.'),
    _b('through_zero', False, 'Delay dry by half the upper delay.'),
    _b('invert', False, 'Invert wet polarity.'),
    _e('sweep', ['linear', 'log'], 'log', 'Delay sweep scale.'),
    _f('highcut_hz', 'Hz', 0, 20000, 0, 'Unity-bounded loop lowpass; zero bypasses.')],
    latency_rule='round(delay_ms * sr / 2000) if through_zero and mix > 0 else 0; compensated offline',
    implemented=True)]
TIME_VARYING = {'flanger'}
IMPLS = {'flanger': flanger}
CROSS_VALIDATE = {'flanger': cross_validate}
