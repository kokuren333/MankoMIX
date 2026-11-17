"""Bounded loop composition for pitch delay and shimmer.

LoopShift(sr, channels, mode='pitch', semitones=12, cents=0, hz=50,
grain_ms=80, reverse=False, highcut_hz=0).process(x) retains filter, BB-11a
tap, and BB-Hilbert states. Zero shift bypasses all safety filters exactly.
Upward safety filters precede translation; their stop edge maps to highcut
(default .45 sr). SSB has a conservative .5 gain bound from the triangle
inequality for its two allpass branches. Signed shifts fold across DC.
"""
import numpy as np
from scipy import signal


class LoopShift:
    def __init__(self, sr, channels, *, mode='pitch', semitones=12, cents=0,
                 hz=50, grain_ms=80, reverse=False, highcut_hz=0):
        from mankomix.dspx.bb.pitchtime_stream import FastShift
        from mankomix.dspx.bb.hilbert import HilbertPair
        self.sr, self.position, self.mode, self.hz = sr, 0, mode, hz
        self.ratio = 2**((semitones+cents/100)/12)
        self.neutral = ((self.ratio == 1 and not reverse) if mode == 'pitch' else hz == 0)
        self.pitch = FastShift(sr, channels, self.ratio, grain_ms, reverse)
        self.pair = HilbertPair(channels)
        edge = min(highcut_hz or .45*sr, .49*sr)
        stop = edge/self.ratio if mode == 'pitch' else edge-max(0, hz)
        self.muted = stop <= 0
        self.sos = None
        if not self.neutral and not self.muted:
            stop = min(stop, .49*sr)
            order, corner = signal.ellipord(.9*stop, stop, .01, 100, fs=sr)
            self.sos = signal.ellip(order, .01, 100, corner, fs=sr, output='sos')
            self.zi = np.zeros((len(self.sos), 2, channels))

    def process(self, x):
        if self.neutral or not len(x):
            self.position += len(x)
            return x.copy()
        if self.muted:
            self.position += len(x)
            return np.zeros_like(x)
        v, self.zi = signal.sosfilt(self.sos, x, axis=0, zi=self.zi)
        if self.mode == 'pitch':
            wet = self.pitch.process(v)
        else:
            real, imag = self.pair.process(v)
            angle = 2*np.pi*np.remainder((self.position+np.arange(len(x)))*self.hz/self.sr, 1)
            wet = .5*(real*np.cos(angle[:, None])-imag*np.sin(angle[:, None]))
        self.position += len(x)
        return wet
