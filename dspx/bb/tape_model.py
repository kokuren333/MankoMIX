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
emphasis(x, sr, speed, inverse=False) is an exactly paired first-order shelf;
its chosen time constants are generic, not a verified IEC implementation.
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
    strength = .12+2.8*saturation
    # Low bias creates a smooth dead-zone, without a discontinuous sign step.
    dead = max(0., .5-bias)*.8
    field = strength*(x-dead*.015*np.tanh(x/.015))
    if not hysteresis:
        slope = strength*(1-dead)
        return np.tanh(field)/slope
    # Bounded recording field and a broad pinning interval keep the fixed
    # 8x RK4 steps stable even for full-scale near-Nyquist excitation.
    field = 4*np.tanh(field/4)
    a, alpha = 1., .001
    c, k = .96-.5*max(0., .5-bias), 4.+.5*max(0., .5-bias)
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
