"""Generic passive three-capacitor tone circuit and asymmetric stage.

No circuit values from a product are used. Independent nodal derivation;
SciPy 1.18.1 public signal APIs, BSD-3-Clause, no source port.
tone_transfer(p) returns analog numerator/denominator in descending powers.
tone_coefficients(sr,p) bilinear-transforms that transfer to digital SOS.
triode(x,k) is normalized biased tanh with a smooth positive grid shunt.
reference_makeup(sr,stages=2) returns a fixed central-circuit 1 kHz
recovery gain derived from the analog/digital filter transfer functions.
alignment_samples(...) returns the circuit-derived integer peak delay.
"""
import numpy as np
from scipy import signal
from functools import lru_cache


def tone_transfer(p):
    # Input--Cb--B--Rb--ground; input--Rt--T--Ct--ground;
    # B--Rm--T and B--Cm--ground. Output is T. Three capacitors.
    ratios = {'scoop': (1., 1., 1.), 'flat': (.7, 1.8, .7),
              'mid_forward': (.5, 3., .5)}[p['tonestack']]
    cb, cm, ct = 22e-9*ratios[0], 2.2e-9*ratios[1], 470e-12*ratios[2]
    rb = 22000+470000*p['bass']
    rt = 22000+220000*(1-p['treble'])
    rm = 10000+100000*(1-p['mid'])
    gb, gt, gm = 1/rb, 1/rt, 1/rm
    ab, at = np.array([cb+cm, gb+gm]), np.array([ct, gt+gm])
    den = np.polymul(ab, at)
    den[-1] -= gm*gm
    num = np.array([0., gm*cb+gt*(cb+cm), gt*(gb+gm)])
    return num, den


def tone_coefficients(sr, p):
    b, a = tone_transfer(p)
    return signal.tf2sos(*signal.bilinear(b, a, fs=sr))


def triode(x, strength):
    bias = .12
    u = strength*x
    # The positive grid-current shunt starts smoothly, with zero derivative
    # at the origin. The curve remains bounded and has unit initial slope.
    u = u-.08*np.maximum(u, 0)**2/(1+np.maximum(u, 0))
    return (np.tanh(u+bias)-np.tanh(bias))/(strength*(1-np.tanh(bias)**2))


def reference_makeup(sr, stages=2):
    """Fixed circuit-derived 1 kHz recovery gain for the central tone knobs.

    Independent of input audio and drive. The actual knob response is not
    normalized: only the central reference circuit supplies the fixed gain.
    Coupling HP and interstage LP losses are included analytically.
    """
    reference = dict(bass=.5, mid=.5, treble=.5, tonestack='scoop')
    _, tone = signal.sosfreqz(tone_coefficients(sr, reference), worN=[1000.], fs=sr)
    hp = signal.butter(1,12,'highpass',fs=sr,output='sos')
    lp = signal.butter(1,14000,'lowpass',fs=sr,output='sos')
    _, h1 = signal.sosfreqz(hp,worN=[1000.],fs=sr)
    _, h2 = signal.sosfreqz(lp,worN=[1000.],fs=sr)
    return float(1/abs(tone[0]*(h1[0]*h2[0])**stages))


@lru_cache(maxsize=128)
def alignment_samples(sr, factor, stages, bright, bass, mid, treble, tonestack, presence_db):
    """Integer peak delay of the linearized circuit, independent of audio.

    Keep the causal circuit phase and advance its wet output offline by
    this delay. The compensated resampler is included in the reference
    impulse, so rounding is performed only at the input sample rate.
    """
    from mankomix.dspx.bb import nonlinear as N
    rate = sr*factor
    p = dict(bass=bass, mid=mid, treble=treble, tonestack=tonestack)
    def linear(u):
        wet = u.copy()
        if bright:
            low = N.filter_audio(wet, rate, 1600, order=1)
            wet = low+1.6*(wet-low)
        for _ in range(stages):
            wet = N.filter_audio(wet, rate, 12, 'highpass', 1)
            wet = N.filter_audio(wet, rate, 14000, order=1)
        return signal.sosfilt(tone_coefficients(rate, p), wet, axis=0)
    pulse = np.zeros((2048, 1)); pulse[512] = 1.
    response = N.precision_oversampled(pulse, factor, linear)
    if presence_db:
        from mankomix.dsp.reference.filters import rbj_biquad
        response = signal.sosfilt(rbj_biquad('high_shelf', 3000, presence_db, 1, sr), response, axis=0)
    response = N.filter_audio(response, sr, 20, 'highpass', 2)
    response -= np.mean(response, axis=0)
    return int(np.argmax(abs(response[:, 0])))-512
