"""Generic passive three-capacitor tone circuit and asymmetric stage.

No circuit values from a product are used. Independent nodal derivation;
SciPy 1.18.1 public signal APIs, BSD-3-Clause, no source port.
tone_transfer(p) returns analog numerator/denominator in descending powers.
tone_coefficients(sr,p) bilinear-transforms that transfer to digital SOS.
triode(x,k) is normalized biased tanh with a smooth positive grid shunt.
reference_makeup(sr,stages=2) returns a fixed central-circuit 1 kHz
recovery gain derived from the analog/digital filter transfer functions.
"""
import numpy as np
from scipy import signal


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
