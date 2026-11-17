"""Independent tape elements; no external implementation source consulted.

Jiles-Atherton ODE: Chowdhury, DAFx-19, equations (18), (22), (23)-(24),
https://dafx.de/paper-archive/2019/DAFx2019_paper_3.pdf .
Only the paper was read. Dimensionless control mappings are our own.
SciPy 1.18.1 public signal APIs (BSD-3-Clause) are used, not copied.

API: magnetize(x, saturation=.5, bias=.5, hysteresis=True) runs fixed RK4
over linearly interpolated field samples, initial M=H=0, float64 (n,ch).
The caller supplies 8x oversampling. No adaptive step or Newton solver.
loss_fir(sr, speed=15, gap_loss=.5, bias=.5) returns a symmetric FIR.
head_bump_sos(sr, speed, gain_db) returns a generic speed-scaled peak.
emphasis(x, sr, speed, inverse=False) is the original generic shelf.
recording_eq(sr, speed) supplies an IEC-time-constant shelf pair for tape:
3.75 ips: 3180/90 us, 7.5: infinity/70, 15: infinity/35,
30: infinity/17.5. A 2 Hz zero and an ultrasonic pole regularize the
DC/Nyquist singularities. Time constants: Pretto et al., Audio Mostly
2021, Table 1, doi:10.1145/3478384.3478409 (paper only).
"""
import math
import numpy as np
from scipy import signal
from functools import lru_cache


def _langevin(q):
    if abs(q) < .01:
        q2 = q*q
        return q*(1/3-q2/45+2*q2*q2/945), 1/3-q2/15+2*q2*q2/189
    t = math.tanh(q)
    return 1/t-1/q, 1/(q*q)-1/(t*t)+1


def magnetize(x, saturation=.5, bias=.5, hysteresis=True):
    x = np.asarray(x, dtype=np.float64)
    # Dimensionless field calibration keeps the entire public drive range
    # resolved at the fixed 8x RK4 rate, rather than driving into a nearly
    # discontinuous magnetic transition. No input-dependent gain fitting.
    strength = .006+.12*saturation
    # Low bias creates a smooth dead-zone, without a discontinuous sign step.
    dead = max(0., .5-bias)*.8
    field = strength*x
    field = field-dead*np.tanh(field)
    if not hysteresis:
        slope = strength*(1-dead)
        return np.tanh(field)/slope
    # Bounded recording field and a broad pinning interval keep the fixed
    # 8x RK4 steps stable even for full-scale near-Nyquist excitation.
    field = 4*np.tanh(field/4)
    a, alpha = 1., .001
    c, k = .96-.05*max(0., .5-bias), 4.+.5*max(0., .5-bias)
    slope = c/(3*a-c*alpha)*strength*(1-dead)
    out = np.empty_like(x)

    def derivative(h, m, direction):
        ll, lp = _langevin((h+alpha*m)/a)
        delta = ll-m
        irreversible = 0.
        if direction*delta > 0:
            irreversible = (1-c)*delta/((1-c)*direction*k-alpha*delta)
        return (irreversible+c*lp/a)/(1-c*alpha*lp/a)

    for ch in range(x.shape[1]):
        m, previous = 0., 0.
        for n, value in enumerate(field[:, ch]):
            dh = float(value)-previous
            if dh:
                direction = 1. if dh > 0 else -1.
                middle = previous+.5*dh
                k1 = dh*derivative(previous, m, direction)
                k2 = dh*derivative(middle, m+.5*k1, direction)
                k3 = dh*derivative(middle, m+.5*k2, direction)
                k4 = dh*derivative(float(value), m+k3, direction)
                m += (k1+2*k2+2*k3+k4)/6
            out[n, ch] = m/slope
            previous = float(value)
    return out


@lru_cache(maxsize=96)
def loss_fir(sr, speed=15, gap_loss=.5, bias=.5):
    from mankomix.dspx.bb.fir import design_linear_fir
    taps = 2*round(sr*.008)+1
    velocity = .0254*speed
    gap, spacing, thickness = 4e-6, 1.2e-6, 2e-6
    def magnitude(f):
        wave = 2*np.pi*f/velocity
        thick = np.ones_like(f)
        np.divide(-np.expm1(-wave*thickness), wave*thickness,
                  out=thick, where=wave != 0)
        loss = np.abs(np.sinc(f*gap/velocity))*np.exp(-wave*spacing)*thick
        loss *= np.exp(-max(0., bias-.5)*f/(1200*speed))
        return (1-gap_loss)+gap_loss*loss
    h = design_linear_fir(magnitude, sr, taps, beta=12)
    h.setflags(write=False)
    return h


def head_bump_sos(sr, speed, gain_db):
    from mankomix.dsp.reference.filters import rbj_biquad
    return rbj_biquad('peak', 60*speed/15, gain_db, 1., sr)


def emphasis(x, sr, speed, inverse=False):
    tau = {3.75: 120e-6, 7.5: 90e-6, 15: 50e-6, 30: 35e-6}[speed]
    b, a = signal.bilinear([tau, 1.], [tau*.5, 1.], fs=sr)
    return signal.lfilter(a if inverse else b, b if inverse else a, x, axis=0)


def recording_eq(sr, speed):
    """Stable reciprocal recording/playback coefficients, unity at 1 kHz.

    H(s) = (1+s*tau_hi)/(1+s*tau_ultrasonic), with an additional
    (s+w_2Hz)/(s+1/tau_low) for the finite LF constant at 3.75 ips.
    Both regularizers are model choices, not extra IEC time constants.
    The analog map is bilinear at the supplied operating sample rate.
    """
    low, high = {3.75: (3180e-6, 90e-6), 7.5: (None, 70e-6),
                 15: (None, 35e-6), 30: (None, 17.5e-6)}[speed]
    b, a = np.array([high, 1.]), np.array([1/(2*np.pi*.45*sr), 1.])
    if low is not None:
        b = np.polymul(b, [1., 2*np.pi*2])
        a = np.polymul(a, [1., 1/low])
    b, a = signal.bilinear(b, a, fs=sr)
    _, h = signal.freqz(b, a, worN=[1000.], fs=sr)
    return b/abs(h[0]), a


def playback_makeup(sr, speed, gap_loss, bias, head_bump_db):
    """Fixed 1 kHz loss/bump/DC recovery derived from filter coefficients."""
    _, loss = signal.freqz(loss_fir(sr, speed, gap_loss, bias), worN=[1000.], fs=sr)
    _, bump = signal.sosfreqz(head_bump_sos(sr, speed, head_bump_db), worN=[1000.], fs=sr)
    _, dc = signal.sosfreqz(signal.butter(1, 5, 'highpass', fs=sr, output='sos'),
                           worN=[1000.], fs=sr)
    return float(1/abs(loss[0]*bump[0]*dc[0]))
