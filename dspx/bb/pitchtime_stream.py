"""Stateful companion to BB-11a, using its tap geometry and period estimator.

FastShift(sr, channels, ratio, grain_ms=80, reverse=False).process(x) keeps
zero-state history and the absolute handover clock across arbitrary blocks.
The two Hann taps use BB-09 sinc8 reads and BB-11's causal period-spacing
estimator. Each read is divided by its kernel L1 norm: the interpolator and
the convex crossfade are peak contractions. No existing BB-11 API is changed.
Reverse uses negative read velocity inside each grain, retaining causal taps.
The pitch effect's wet delay is intentional, with no dry-path compensation.
"""
import numpy as np


class FastShift:
    """Persistent, bounded dual-tap shift; ratio=1 bypasses exactly."""

    def __init__(self, sr, channels, ratio, grain_ms=80, reverse=False):
        from mankomix.dspx.bb.pitchtime import _positive
        self.sr = _positive(sr, 'sr')
        self.grain = _positive(grain_ms, 'grain_ms')*sr/1000
        self.ratio = _positive(ratio, 'ratio')
        self.velocity = -ratio if reverse else ratio
        self.delta = 1-self.velocity
        self.channels = channels
        self.keep = int(np.ceil(max(self.grain+16, .06*sr)))
        self.history = np.zeros((self.keep, channels))
        self.position = 0
        self.start = min(.04*sr, self.grain/(4*abs(self.delta))) if self.delta else 0
        self.finish = self.start
        self.spacing = None

    def process(self, x):
        from mankomix.dspx.bb.pitchtime import _audio, _period_spacing
        from mankomix.dspx.bb.delayline import _kernel
        x = _audio(x)
        if x.shape[1] != self.channels:
            raise ValueError('channel count changed')
        if not self.delta or not len(x):
            self.position += len(x)
            return x.copy()
        source = np.concatenate((self.history, x))
        origin = self.position-self.keep
        clock = self.position+np.arange(len(x), dtype=float)
        d1, d2, weight = np.empty(len(x)), np.empty(len(x)), np.zeros(len(x))
        a = 0
        while a < len(x):
            now = clock[a]
            if now < self.start:
                b = min(len(x), max(a+1, int(np.ceil(self.start-self.position))))
                d1[a:b] = 4+self.grain/2+self.delta*(clock[a:b]-self.start)
                d2[a:b] = d1[a:b]
            else:
                if self.spacing is None or now >= self.finish:
                    if self.spacing is not None:
                        self.start = self.finish
                    end = max(0, int(np.floor(self.start))-4-int(origin))
                    self.spacing = _period_spacing(source, end, self.sr, self.grain/2)
                    self.finish = self.start+self.spacing/abs(self.delta)
                b = min(len(x), max(a+1, int(np.ceil(self.finish-self.position))))
                d1[a:b] = 4+self.grain/2+self.delta*(clock[a:b]-self.start)
                d2[a:b] = d1[a:b]-np.copysign(self.spacing, self.delta)
                weight[a:b] = .5-.5*np.cos(np.pi*(clock[a:b]-self.start)/(self.finish-self.start))
            a = b
        wet = np.zeros_like(x)
        for delay, gain in ((d1, 1-weight), (d2, weight)):
            pos = clock-delay
            # BB-09's centred sinc support is strictly behind the write head.
            indices, kernel = _kernel(pos, 'sinc8')
            norm = np.maximum(1., np.sum(np.abs(kernel), axis=-1))
            voice = np.zeros_like(x)
            for j in range(kernel.shape[1]):
                ix = indices[:, j]-origin
                values = source[np.clip(ix, 0, len(source)-1)]
                voice += np.where(((ix >= 0) & (ix < len(source)))[:, None], values, 0)*kernel[:, j, None]
            wet += voice*(gain/norm)[:, None]
        self.history = source[-self.keep:].copy()
        self.position += len(x)
        return wet
