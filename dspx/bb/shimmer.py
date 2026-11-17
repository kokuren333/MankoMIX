"""BB-10 TV / BB-11a connection without altering existing FDN behavior.

hall_params(p): equivalent hall-kernel parameters for the shimmer-zero null.
ShimmerFDN(sr, p, seed=0).process(stereo): BB-10 FDN with parallel BB-11a
feedback, a <=.98 total feedback cap, and tanh loop protection. The computed
cap also reserves 60-second decay margin for the pitch buffer's history.
process_shimmer(x, sr, p, seed=0): whole-context TV rendering, SD, and R-10
measurements from a modulation-stopped, small-signal MIMO impulse response.
Stateful pitch and IIR filters retain their histories inside FDN callbacks.
"""
from functools import lru_cache
import math
import numpy as np
from mankomix.dspx.bb.reverb import FDN
from mankomix.dspx.bb.delayline import DelayLine


def hadamard_route(block):
    """Normalised Sylvester routing, fixed butterfly order, without BLAS."""
    channels = block.shape[1]
    if channels not in (8, 16):
        raise ValueError('8 or 16 FDN lines required')
    out = block.copy()
    width = 1
    while width < channels:
        groups = out.reshape(len(out), channels//(2*width), 2, width)
        left, right = groups[:, :, 0].copy(), groups[:, :, 1].copy()
        groups[:, :, 0], groups[:, :, 1] = left+right, left-right
        width *= 2
    return out/math.sqrt(channels)


class _FDNLine(DelayLine):
    def process(self, x, delays, feedback=0., loop=None, matrix=None, block_size=1024):
        return super().process(x, delays, feedback, loop, block_size=block_size, route=hadamard_route)


def hall_params(p):
    """Return the fixed hall geometry and absorption used by this type."""
    return dict(p, size_m=25., er_late_db=0., rt60_low_mult=1., rt60_high_mult=.6,
                low_xover_hz=250., high_xover_hz=p['damping_hz'], width=1., mod_rate_hz=.5)


class ShimmerFDN(FDN):
    def __init__(self, sr, p, *, seed=0):
        from mankomix.dspx.bb.shiftloop import LoopShift
        super().__init__(sr, hall_params(p), seed=seed, absorption_order=4, mod_interpolation='lagrange3')
        self.line = _FDNLine(self.line.max_delay, self.lines, self.line.method)
        self.amount = p['shimmer'] if p['shift_semitones'] else 0.
        self.shifter = LoopShift(sr, self.lines, semitones=p['shift_semitones'],
                                 grain_ms=p['grain_ms'], highcut_hz=p['damping_hz'])
        # Absolute cap specified by T03-06, plus a conservative history-aware
        # cap: <=18 s nominal T60 for the longest FDN+pitch-buffer traversal.
        # The requested RT60 still controls absorption below that safety cap.
        history = float(max(self.delays))/sr+p['grain_ms']/1000+.01
        self.feedback_cap = min(.98, math.exp(-math.log(1000)*history/18))
        if self.amount:
            from mankomix.dspx.bb.reverb import rt60_gain
            gains = rt60_gain(self.delays, sr, p['rt60_s'])
            for sos, gain in zip(self.sos, gains):
                sos[0, :3] *= min(1., self.feedback_cap/gain)

    def _absorb(self, block):
        if not self.amount:
            return super()._absorb(block)
        shifted = self.shifter.process(block)
        # Parallel send: original + shimmer * shifted. Normalise by the sum
        # of the branch gains before applying the bounded FDN absorption.
        parallel = (block+self.amount*shifted)/(1+self.amount)
        return np.tanh(super()._absorb(parallel))


def _wet(stereo, sr, p, seed, late_gain, er_gain):
    from mankomix.dspx.bb import reverb as R
    from mankomix.dspx.bb.curves import modulation_seed
    from mankomix.dspx.bb.fir import fft_convolve
    from mankomix.dspx.bb.delayline import fractional_delay
    tank = ShimmerFDN(sr, p, seed=seed)
    wet = tank.process(stereo, offline_diffusion=True)*late_gain
    er = R.early_reflections(sr, max(1, round(.2*sr)), 25., modulation_seed(seed, 'er', p['seed']))
    wet += fft_convolve(stereo, er, 'same')*er_gain
    wet = fractional_delay(wet, round(p['predelay_ms']*sr/1000), 'integer')
    return R._wet_filter(wet, sr, p), tank.feedback_cap if tank.amount else None


@lru_cache(maxsize=32)
def _normalization(sr, rt, diffusion, damping, parameter_seed, seed):
    from mankomix.dspx.bb import reverb as R
    from mankomix.dspx.bb.curves import modulation_seed
    p = dict(rt60_s=rt, diffusion=diffusion, damping_hz=damping, seed=parameter_seed,
             predelay_ms=0, lowcut_hz=20, highcut_hz=20000, mod_depth=0,
             shimmer=0, shift_semitones=0, grain_ms=80)
    n = max(1, math.ceil((rt*140/60+.15)*sr))
    energy = 0.
    for channel in range(2):
        pulse = np.zeros((n, 2))
        pulse[0, channel] = 1.
        h = ShimmerFDN(sr, p, seed=seed).process(pulse, offline_diffusion=True)
        energy += float(np.sum(h*h))/2
    er = R.early_reflections(sr, max(1, round(.2*sr)), 25., modulation_seed(seed, 'er', parameter_seed))
    er_energy = float(np.sum(er*er))/2
    return 1/math.sqrt(2*energy), math.sqrt(.5/er_energy)


@lru_cache(maxsize=64)
def _design(sr, items, seed):
    from mankomix.dspx.bb import reverb as R
    p = dict(items)
    late, early = _normalization(sr, p['rt60_s'], p['diffusion'], p['damping_hz'], p['seed'], seed)
    # Fifty dB of nominal decay keeps the T20 fitting interval well above
    # the finite-context floor. The actual history-aware cap decays faster.
    n = max(1, math.ceil((p['rt60_s']*50/60+.3)*sr))
    h = np.zeros((n, 2, 2))
    for channel in range(2):
        pulse = np.zeros((n, 2))
        pulse[0, channel] = 1e-4
        h[:, channel], _ = _wet(pulse, sr, dict(p, mod_depth=0.), seed, late, early)
    h /= 1e-4
    vector = R.measure_ir(h, sr, dict(p, mix=1), modulation_stopped=True)
    return vector, late, early


def process_shimmer(x, sr, p, *, seed=0):
    from mankomix.dspx.bb import reverb as R
    R.validate_rv(p)
    if not p['mix'] or not len(x):
        return x.copy(), sr, dict(latency_samples=0, bypass=True)
    items = tuple(sorted((k, v) for k, v in p.items() if k not in {'mix', 'bpm', 'mod_depth'} and not k.startswith('duck_')))
    # Measurement parameters are independent of dry/wet and self-duck state.
    vector, late, early = _design(sr, items, seed)
    wet, cap = _wet(R._stereo(x), sr, p, seed, late, early)
    if x.shape[1] == 1:
        wet = wet.mean(axis=1, keepdims=True)
    from copy import deepcopy
    stats = deepcopy(vector)
    if 0 < p['mix'] < 1 and stats['wet_energy_db'] is not None:
        stats['dr_db_white'] = 20*math.log10((1-p['mix'])/p['mix'])-stats['wet_energy_db']
    stats.update(execution='tv', fdn_lines=16, measurement_small_signal=1e-4,
                 measurement_shift_enabled=bool(p['shimmer'] and p['shift_semitones']), feedback_cap=cap,
                 shifter_gain_bound=1., group_delay_compensated=False)
    return R.finish(x, wet, sr, p, stats)
