"""BB-13: shared nonlinear primitives, float64, frames by channels.

oversampled(x, factor, fn) duplicates dsp/reference/nonlinear.py verbatim in
its numerical path; both polyphase FIR delays are compensated (net zero).
oversampling_info(factor) declares the uncompensated 64-sample round trip.
ADAA1(curve, primitive).process(x) is stateful first-order antiderivative
antialiasing, with a half sample delay at its operating rate. Call reset()
between streams. adaa1 is the stateless convenience wrapper.
hard_clip, hard_clip_primitive, fold, fold_primitive, rectify_primitive and
loudness_curve/loudness_primitive are analytic curve/antiderivative pairs.
compand(x, mu=255, inverse=False) is an exactly paired logarithmic compander.
ClockFilter(sr, ratio=.45, order=2).process(x, clock_hz) is a stateful cascade
of clock-tracking one poles; clock_hz may be scalar or one value per frame.
filter_audio and dc_block are whole-context offline helpers, not streaming
adapters. nl_params/specification supply fresh registration dictionaries.

ADAA equations: Parker et al., DAFx-16, sections 2/4; Bilbao et al., IEEE SPL
2017, doi:10.1109/LSP.2017.2675541, eqs. (5)-(7). Independent
implementation from the papers, no external source code ported. scipy.signal
public API (BSD-3-Clause, installed version) is used for filters/resampling.
"""
from __future__ import annotations

from functools import lru_cache
import numpy as np
from scipy import signal

from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e, _b


@lru_cache(maxsize=8)
def _os_filter(factor: int) -> np.ndarray:
    h = signal.firwin(64 * factor + 1, 1.0 / factor, window=("kaiser", 10.0))
    h.setflags(write=False)
    return h


def oversampled(x: np.ndarray, factor: int, fn) -> np.ndarray:
    """Whole-context compensated resampling; preserve the existing arithmetic."""
    if factor not in (1, 2, 4, 8):
        raise ParamError('oversample must be 1, 2, 4 or 8')
    if not len(x):
        return np.asarray(x, dtype=np.float64).copy()
    if factor <= 1:
        return fn(x)
    h = _os_filter(factor)
    up = signal.resample_poly(x, factor, 1, axis=0, window=h.copy())
    up = fn(up)
    return signal.resample_poly(up, 1, factor, axis=0, window=h.copy())[: x.shape[0]]


_oversampled = oversampled


def oversampling_info(factor):
    if factor not in (1, 2, 4, 8):
        raise ParamError('oversample must be 1, 2, 4 or 8')
    return dict(oversample=int(factor), latency_samples=0,
                uncompensated_latency_samples=64 if factor > 1 else 0,
                latency_compensated=True)


class ADAA1:
    """Causal first divided difference, zero initial previous input per channel.

    Equal/nearly equal arguments use curve(midpoint); the relative threshold
    is 1e-7. State persists across arbitrary input block boundaries. This
    averages a linear function over adjacent samples; it is NOT zero delay.
    """
    def __init__(self, curve, primitive):
        self.curve, self.primitive = curve, primitive
        self.reset()

    def reset(self):
        self.previous = None

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        if x.ndim != 2:
            raise ParamError('ADAA audio must have shape (frames, channels)')
        if not len(x):
            return x.copy()
        if self.previous is None:
            self.previous = np.zeros(x.shape[1])
        if self.previous.shape != x.shape[1:]:
            raise ParamError('ADAA channel count changed')
        prev = np.concatenate([self.previous[None], x[:-1]], axis=0)
        delta = x - prev
        stable = np.abs(delta) > 1e-7 * np.maximum(1, np.maximum(np.abs(x), np.abs(prev)))
        y = np.asarray(self.curve((x + prev) * .5), dtype=np.float64).copy()
        np.divide(self.primitive(x) - self.primitive(prev), delta, out=y, where=stable)
        self.previous = x[-1].copy()
        return y


def adaa1(x, curve, primitive):
    return ADAA1(curve, primitive).process(x)


def hard_clip(x):
    return np.clip(x, -1, 1)


def tanh_primitive(x):
    """Stable log(cosh(x)), the antiderivative of tanh with F(0)=0."""
    return np.logaddexp(x, -x)-np.log(2.0)


def hard_clip_primitive(x):
    a = np.abs(x)
    return np.where(a <= 1, .5 * x*x, a - .5)


def fold(x):
    return 1 - np.abs(np.remainder(x + 1, 4) - 2)


def fold_primitive(x):
    r = np.remainder(x + 1, 4)
    return np.where(r < 2, .5*r*r-r, 3*r-.5*r*r-4)


def rectify_primitive(x):
    return .5 * x * np.abs(x)


def loudness_curve(x, effect=1, curve=.5, clip=True):
    u = np.clip(x, -1, 1)
    y = u + effect*((1-curve)*(u-u*np.abs(u)) + .5*curve*(u-u**3))
    return y if clip else y + (x-u)


def loudness_primitive(x, effect=1, curve=.5, clip=True):
    a = np.abs(x)
    v = np.minimum(a, 1)
    y = .5*v*v + effect*((1-curve)*(.5*v*v-v**3/3) +
                         .5*curve*(.5*v*v-v**4/4))
    return y + np.maximum(a-1, 0) + (0 if clip else .5*np.maximum(a-1, 0)**2)


def compand(x, mu=255, *, inverse=False):
    """Signed log1p compression / expm1 expansion, no clipping at full scale."""
    if not np.isfinite(mu) or mu <= 0:
        raise ParamError('mu must be positive and finite')
    x = np.asarray(x, dtype=np.float64)
    if inverse:
        return np.sign(x)*np.expm1(np.abs(x)*np.log1p(mu))/mu
    return np.sign(x)*np.log1p(mu*np.abs(x))/np.log1p(mu)


class ClockFilter:
    """Clock-following matched-z lowpass; persistent order by channel state.

    Cutoff is min(ratio*clock_hz, .45*sr). Each pole has a=exp(-2*pi*fc/sr).
    Coefficients change each sample, without resetting history. This is a
    generic BBD element, not a complete BBD or a physical tape model.
    """
    def __init__(self, sr, ratio=.45, order=2):
        if sr <= 0 or not 0 < ratio <= .5 or order not in (1, 2, 3, 4):
            raise ParamError('invalid clock filter configuration')
        self.sr, self.ratio, self.order = sr, ratio, order
        self.state = None

    def process(self, x, clock_hz):
        x = np.asarray(x, dtype=np.float64)
        if x.ndim != 2:
            raise ParamError('clock filter audio must be frames by channels')
        clock = np.broadcast_to(np.asarray(clock_hz, dtype=np.float64), (len(x),))
        if np.any(~np.isfinite(clock)) or np.any(clock <= 0):
            raise ParamError('clock must be positive and finite')
        if self.state is None:
            self.state = np.zeros((self.order, x.shape[1]))
        if self.state.shape != (self.order, x.shape[1]):
            raise ParamError('clock filter channel count changed')
        a = np.exp(-2*np.pi*np.minimum(self.ratio*clock, .45*self.sr)/self.sr)
        y = np.empty_like(x)
        for i, row in enumerate(x):
            v = row
            for pole in range(self.order):
                self.state[pole] = (1-a[i])*v + a[i]*self.state[pole]
                v = self.state[pole]
            y[i] = v
        return y


def clock_following_filter(x, sr, clock_hz, *, ratio=.45, order=2):
    return ClockFilter(sr, ratio, order).process(x, clock_hz)


def filter_audio(x, sr, freq, kind='lowpass', order=2):
    """Causal Butterworth; highpass zero and lowpass >= Nyquist bypass."""
    if not len(x) or freq <= 0 or (kind == 'lowpass' and freq >= sr*.5):
        return x.copy()
    freq = min(freq, .49*sr)
    return signal.sosfilt(signal.butter(order, freq, kind, fs=sr, output='sos'), x, axis=0)


def dc_block(x, sr, freq=5):
    """5 Hz highpass plus offline residual-mean removal, exact silence in/out."""
    y = filter_audio(x, sr, freq, 'highpass', 1)
    return y - np.mean(y, axis=0) if len(y) else y


def nl_params(drive_max=36, drive_default=0, oversample_default=4):
    return [_f('drive_db', 'dB', 0, drive_max, drive_default, 'Nonlinear drive.'),
            _f('output_db', 'dB', -36, 12, 0, 'Output gain.'),
            _b('auto_gain', False, 'Subtract drive_db times the fixed coefficient 1.'),
            _f('mix', '0..1', 0, 1, 1, 'Aligned dry/wet mix.'),
            _e('oversample', [1, 2, 4, 8], oversample_default, 'Oversampling.', unit='x')]


def specification(name, params, description, *, slot=3, stages=None):
    return dict(type=name, implemented=False, description=description, params=params,
                stages=stages or ['track', 'bus', 'master'], master_slot=slot,
                offline_only=False, backends=['reference'], channel_ok=True,
                realtime=dict(block_ok=False, allocates=True, latency_samples=0,
                              latency_rule='Polyphase 64 samples round trip, compensated offline; factor 1: zero.'))


def mix_output(x, wet, mix=1, output_db=0):
    y = x.copy() if mix == 0 else wet if mix == 1 else mix*wet+(1-mix)*x
    return y if output_db == 0 else y*10**(output_db/20)
