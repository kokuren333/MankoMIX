"""Cubic modulated comb, signed feedback, and compensated through-zero dry path."""
import numpy as np

from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _b, _e
from mankomix.dspx.bb.modulation import mod_params, mod_lfo, mod_rate, modulation_definition
from mankomix.dspx.bb.delayline import DelayLine, LoopFilter, fractional_delay, spatial_stats


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
        # BB-09's centred four-point kernel needs two samples of causal reserve.
        delays = np.maximum(delays, 3.)
        filt = LoopFilter(sr, x.shape[1], highcut=p['highcut_hz'])
        wet = DelayLine(max(3., float(np.max(delays, initial=3))), x.shape[1], 'lagrange3').process(
            x, delays, feedback=abs(p['feedback']), loop=filt,
            matrix=np.eye(x.shape[1])*np.sign(p['feedback']))
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
    latency_rule='round(delay_ms * sr / 2000) if through_zero and mix > 0 else 0; compensated offline')]
TIME_VARYING = {'flanger'}
IMPLS = {'flanger': flanger}
CROSS_VALIDATE = {'flanger': cross_validate}
