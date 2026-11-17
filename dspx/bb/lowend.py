"""Whole-context low-frequency helpers built on BB-03 and BB-07.

band_fir(x, sr, lo=0, hi=0, tilt=0) returns (audio, metadata). Edges are
half-amplitude frequencies of a Kaiser-windowed, frequency-sampled linear
FIR. tilt is a nonnegative power-law rolloff above lo. All FIR delays are
compensated. amplitude_envelope(x, sr, attack_ms, release_ms) uses an
offline analytic amplitude followed by BB-03's zero-state amplitude follower.
definition creates fresh reference declarations; no existing BB is replaced.
"""
from functools import lru_cache
import numpy as np
from scipy import fft


def definition(name, params, description, *, offline=False, stages=None):
    return dict(type=name, implemented=False, description=description,
                params=params, stages=stages or ['track', 'bus', 'master'],
                master_slot=3, offline_only=offline, backends=['reference'],
                channel_ok=True, realtime=dict(block_ok=False, allocates=True,
                latency_samples=0, latency_rule='Whole-context processing; FIR delays compensated offline.'))


@lru_cache(maxsize=32)
def _kernel(sr, lo, hi, tilt):
    from mankomix.dspx.bb.fir import design_linear_fir
    edge = min(f for f in (lo, hi) if f > 0)
    taps = 2*int(np.ceil(20*sr/edge))+1
    def magnitude(f):
        m = np.ones_like(f)
        if lo:
            m *= (f >= lo)
        if hi:
            m *= (f <= hi)
        if tilt and lo:
            m *= np.maximum(f/lo, 1)**(-tilt)
        return m
    h = design_linear_fir(magnitude, sr, taps, beta=14)
    h.setflags(write=False)
    return h


def band_fir(x, sr, lo=0, hi=0, tilt=0):
    """Return delay-compensated FIR audio and its uncompensated delay metadata."""
    from mankomix.dspx.bb.fir import fft_convolve
    from mankomix.dsp.errors import ParamError
    if not 0 <= lo < sr/2 or not 0 <= hi < sr/2 or (lo and hi and lo >= hi):
        raise ParamError('invalid low-frequency FIR edges')
    if not lo and not hi:
        return x.copy(), dict(fir_taps=0, uncompensated_latency_samples=0, latency_samples=0)
    h = _kernel(sr, float(lo), float(hi), float(tilt))
    delay = len(h)//2
    wet = fft_convolve(x, h)[delay:delay+len(x)] if len(x) else x.copy()
    return wet, dict(fir_taps=len(h), uncompensated_latency_samples=delay,
                     latency_samples=0, latency_compensated=True)


def amplitude_envelope(x, sr, attack_ms, release_ms):
    """Analytic peak amplitude, zero padded, then BB-03 amplitude ballistics."""
    from mankomix.dspx.bb.dynamics import envelope
    if not len(x):
        return x.copy()
    n = fft.next_fast_len(2*len(x))
    spectrum = fft.fft(x, n, axis=0, workers=1)
    h = np.zeros(n)
    h[0] = 1
    h[1:(n+1)//2] = 2
    if n % 2 == 0:
        h[n//2] = 1
    a = abs(fft.ifft(spectrum*h[:, None], axis=0, workers=1)[:len(x)])
    return envelope(a, sr, attack_ms, release_ms)
