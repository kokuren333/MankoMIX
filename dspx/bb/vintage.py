"""Crossed multitap tank with absorption distributed over every delay.

The graph and delay geometry come from BB-10 VintageTank. Each pure delay
is replaced by an attenuating delay, including the delays inside allpasses.
For flat absorption this is exactly the substitution z^-1 -> r*z^-1:
all modes decay at r per sample, independently of diffusion coefficients.
Frequency-dependent absorption uses the existing four-pole shelf designer.
No legacy BB-10 class or function is modified.

Formula source (no implementation copied): J. O. Smith, Physical Audio
Signal Processing, equations (4.5)-(4.8),
https://www.dsprelated.com/freebooks/pasp/Achieving_Desired_Reverberation_Times.html
"""
from functools import lru_cache
import math
import numpy as np
from scipy import signal

from mankomix.dspx.bb import reverb as R


class _Absorption:
    def __init__(self, delay, sr, p):
        # Damping controls the transition into a gently shorter high-band
        # decay, rather than adding an RT-independent loss on every circuit.
        high = .95 if p['damping_hz'] < .45*sr else 1.
        self.sos = R.absorption_sos(delay, sr,
            (p['rt60_s']*p['bass_mult'], p['rt60_s'], high*p['rt60_s']),
            250, p['damping_hz'], order=4)
        self.zi = np.zeros((len(self.sos), 2))

    def __call__(self, x):
        y, self.zi = signal.sosfilt(self.sos, np.asarray(x), zi=self.zi)
        return y


class _Memory(R._TapMemory):
    def __init__(self, capacity, sr, p):
        super().__init__(capacity)
        self.sr, self.p, self.filters = sr, p, {}

    def read(self, start, frames, delay):
        if delay not in self.filters:
            self.filters[delay] = _Absorption(delay, self.sr, self.p)
        return self.filters[delay](super().read(start, frames, delay))


class _Allpass(R.TankAllpass):
    def __init__(self, delay, gain, excursion, sr, p):
        super().__init__(delay, gain, excursion)
        self.absorb = _Absorption(delay, sr, p)
        self.output_absorb = _Absorption(delay, sr, p)
        self.tap_filters, self.sr, self.p = {}, sr, p

    def process(self, x, delays=None):
        # Identical filters see the same read history in the feedback and
        # output paths. Keeping separate state avoids depending on callback
        # subdivision, and preserves arbitrary process-block boundaries.
        delayed = self.line.process(x, self.delay if delays is None else delays,
            1., lambda v: self.gain*self.absorb(v[:, 0])[:, None])
        return -self.gain*x+(1-self.gain**2)*self.output_absorb(delayed[:, 0])[:, None]

    def tap(self, start, frames, offset):
        if offset not in self.tap_filters:
            self.tap_filters[offset] = _Absorption(offset, self.sr, self.p)
        return self.tap_filters[offset](super().tap(start, frames, offset))


class _InputAllpass(R._SignedInputAllpass):
    def __init__(self, delay, gain, sr, p):
        self.original_gain = gain
        self.attenuation = float(R.rt60_gain(delay, sr, p['rt60_s']))
        super().__init__(delay, gain*self.attenuation)

    def process(self, x):
        y = super().process(x)
        delayed = (y+self.gain*x)/(1-self.gain**2)
        return (-self.original_gain*x + (1-self.original_gain**2)*self.attenuation*delayed)


class VintageTank(R.VintageTank):
    """Stateful, RT-scaled version of the existing figure-eight topology."""
    def __init__(self, sr, p, *, seed=0):
        super().__init__(sr, p, seed=seed)
        # A subsecond requested decay cannot be measured reliably on a tank
        # whose first full traversal already lasts about 0.7 s. Compress the
        # same geometry for short rooms, keeping all delay ratios and signs.
        self.scale *= min(1., p['rt60_s']/1.5)
        self.inputs = [_InputAllpass(self.length(d), ap.gain, sr, p)
            for d, ap in zip((142, 107, 379, 277), self.inputs)]
        self.gain = 1.
        self.damp = [lambda x: x, lambda x: x]
        self.bass_sos = np.array([[1., 0., 0., 1., 0., 0.]])
        self.bass_zi = [np.zeros((1, 2)) for _ in range(2)]
        self.first = [_Allpass(self.length(d), ap.gain,
            self.excursion if p['mod_depth'] else 0, sr, p)
            for d, ap in zip((672, 908), self.first)]
        self.second = [_Allpass(self.length(d), ap.gain, 0, sr, p)
            for d, ap in zip((1800, 2656), self.second)]
        self.long_d = [self.length(d) for d in (4453, 4217)]
        self.end_d = [self.length(d) for d in (3720, 3163)]
        self.long = [_Memory(d+max(self.end_d), sr, p) for d in self.long_d]
        self.end = [_Memory(d+max(self.end_d), sr, p) for d in self.end_d]


@lru_cache(maxsize=4)
def _measurement_ir(sr, items, seed):
    p = dict(items)
    n = max(1, math.ceil((p['rt60_s']*max(1, p['bass_mult'])*1.3+.25)*sr))
    pulse = np.zeros((n, 2)); pulse[0] = 1
    h = R._tv_wet_shape(pulse, VintageTank(sr, p, seed=seed).process(pulse), sr, p)
    h.setflags(write=False)
    return h


def process_vintage(x, sr, p, *, seed=0):
    """Render the dedicated tank and measure the same unmodulated graph."""
    R.validate_rv(p)
    if not p['mix']:
        return x.copy(), sr, dict(latency_samples=0, bypass=True)
    measured = {k: v for k, v in p.items() if k not in {'mix', 'bpm'} and not k.startswith('duck_')}
    measured.update(mod_depth=0, bits='0')
    h = _measurement_ir(sr, tuple(sorted(measured.items())), seed)
    wet = R._tv_wet_shape(x, VintageTank(sr, p, seed=seed).process(R._stereo(x)), sr, p)
    stats = R.measure_ir(h, sr, p, modulation_stopped=True)
    stats.update(execution='tv', measurement_quantization_disabled=True,
        internal_bits=int(p['bits']), quantization='subtractive_tpdf_zero_gate',
        absorption='distributed_delay')
    return R.finish(x, wet, sr, p, stats)
