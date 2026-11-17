"""Event-clock BBD and analytic input/output filter elements.

Reference principle: Holters & Parker, DAFx-18, sections 2/3, equations
(5)-(19), https://www.dafx.de/paper-archive/2018/papers/DAFx2018_paper_12.pdf .
Independent modal implementation, no circuit coefficients or source copied.
scipy.signal's public Butterworth/residue/lfilter APIs are BSD-3-Clause.

BBDPlan(frames,sr,delays,stages=4096,tone=.5).process(x) returns wet audio.
Delays are scalar or frames, in host samples; the event queue has stages/2
entries and alternates sample/hold half clocks. Filters are fifth-order
Butterworth with cutoff=(.12+.12*tone)*clock, capped at .18*host_sr.
The fixed-clock case integrates output steps analytically and evaluates the
input impulse-invariant filter at fractional event times. Varying clock uses
piecewise-constant poles on each host interval. No rounded event sampling.
envelope_compand(x,sr,inverse=False): RMS-controlled 2:1 / 1:2, 10ms key,
2ms attack / 40ms release. bbd_audio additionally adds deterministic noise.
These are full-context APIs; callers replay history for excerpts.
"""
import numpy as np
from scipy import signal


def envelope_compand(x, sr, *, inverse=False):
    from mankomix.dspx.bb.dynamics import detector, envelope
    if not len(x):
        return x.copy()
    rms = detector(x, sr, mode='rms', window_ms=10, stereo_link=False)
    level = envelope(rms, sr, 2, 40)
    return x*level if inverse else x/np.sqrt(np.maximum(level, 1e-12))


class BBDPlan:
    """Precomputed event lattice and modal filter factors, zero-state per call."""
    def __init__(self, frames, sr, delays, stages=4096, tone=.5):
        self.frames, self.sr = frames, sr
        d = np.broadcast_to(np.asarray(delays, dtype=np.float64).reshape(-1), (frames,))
        if np.any(d <= 0) or np.any(~np.isfinite(d)):
            raise ValueError('BBD delay must be positive')
        self.clock = stages*sr/(2*d)
        self.cutoff = np.minimum((.12+.12*tone)*self.clock, .18*sr)
        phase = np.r_[0., np.cumsum(self.clock/sr)]
        event = np.arange(int(np.ceil(phase[-1])))
        sample = np.interp(event, phase, np.arange(frames+1))
        output = np.interp(event+(stages-1)/2, phase, np.arange(frames+1), right=frames+1.)
        valid = (sample < frames) & (output < frames)
        self.sample, self.output = sample[valid], output[valid]
        b, a = signal.butter(5, 1., analog=True)
        self.residue, self.poles, _ = signal.residue(b, a)
        self.fixed = not frames or np.all(self.cutoff == self.cutoff[0])

    def process(self, x):
        n = self.frames
        if not n or not len(self.sample):
            return np.zeros_like(x)
        ix = np.floor(self.sample).astype(int)
        frac = self.sample-ix
        rate = 2*np.pi*self.cutoff/self.sr
        sampled = np.zeros((len(ix), x.shape[1]), dtype=np.complex128)
        # Input is represented by weighted impulses on the host grid. Each
        # analog pole is evaluated at the actual event time inside that interval.
        for residue, pole in zip(self.residue, self.poles):
            a = np.exp(pole*rate)
            if self.fixed:
                state = signal.lfilter([rate[0]*residue], [1, -a[0]], x, axis=0)
            else:
                state = np.empty_like(x, dtype=np.complex128)
                old = np.zeros(x.shape[1], dtype=np.complex128)
                for k in range(n):
                    old = a[k]*old+rate[k]*residue*x[k]
                    state[k] = old
            sampled += state[ix]*np.exp(pole*rate[ix]*frac)[:, None]
        sampled = sampled.real
        deltas = np.diff(sampled, axis=0, prepend=np.zeros((1, x.shape[1])))
        out_index = np.ceil(self.output).astype(int)
        valid = out_index < n
        out_index, deltas = out_index[valid], deltas[valid]
        fractions = out_index-self.output[valid]
        changes = np.zeros_like(x)
        np.add.at(changes, out_index, deltas)
        y = np.cumsum(changes, axis=0).astype(np.complex128)
        # Output is the exact continuous response to the queue's held steps,
        # not a nearest-neighbour reconstruction followed by a digital LPF.
        for residue, pole in zip(self.residue, self.poles):
            injection = np.zeros_like(x, dtype=np.complex128)
            np.add.at(injection, out_index,
                      deltas*(residue/pole)*np.exp(pole*rate[out_index]*fractions)[:, None])
            a = np.exp(pole*rate)
            if self.fixed:
                state = signal.lfilter([1.], [1, -a[0]], injection, axis=0)
            else:
                state = np.empty_like(injection)
                old = np.zeros(x.shape[1], dtype=np.complex128)
                for k in range(n):
                    old = a[k]*old+injection[k]
                    state[k] = old
            y += state
        return y.real


def bbd_audio(x, sr, delays, *, stages=4096, tone=.5, compander=True,
              noise_db=-120, seed=0):
    """Process one complete traversal; noise is inserted before the expander."""
    source = envelope_compand(x, sr) if compander else x
    wet = BBDPlan(len(x), sr, delays, stages, tone).process(source)
    if noise_db > -120:
        wet += np.random.Generator(np.random.PCG64(seed)).standard_normal(wet.shape)*10**(noise_db/20)
    return envelope_compand(wet, sr, inverse=True) if compander else wet
