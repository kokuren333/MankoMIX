"""Sample-varying trapezoidal SVF equalizer, derived from two integrators.

equalize(x, sr, centers_hz, shape, gain_db=0, bw_oct=.5) returns float64
audio, retaining the analog low/band/high state-variable outputs. Controls
are scalar or one per sample; frequencies are capped at .45*sr. No source
code is copied. Existing BB SVF functions are unchanged.
"""
import numpy as np
from mankomix.dsp.errors import ParamError


def equalize(x, sr, centers_hz, shape='peak', gain_db=0, bw_oct=.5):
    """Zero-state TPT peak/notch/shelves/highpass, octave bandwidth -> Q."""
    n = len(x)
    f = np.broadcast_to(np.asarray(centers_hz, dtype=float), (n,))
    db = np.broadcast_to(np.asarray(gain_db, dtype=float), (n,))
    if (shape not in ('peak', 'notch', 'low_shelf', 'high_shelf', 'hpf') or np.any(f <= 0)
            or not np.isfinite(f).all() or not np.isfinite(db).all() or not np.isfinite(bw_oct)
            or bw_oct <= 0 or sr <= 0):
        raise ParamError('invalid equalizer shape or center')
    q = 1/(2*np.sinh(np.log(2)*bw_oct/2))
    a = 10**(db/40)
    g = np.tan(np.pi*np.minimum(f, .45*sr)/sr)
    k = np.full(n, 1/q)
    m0, m1, m2 = np.ones(n), np.zeros(n), np.zeros(n)
    if shape == 'peak':
        k /= a
        m1 = k*(a*a-1)
    elif shape == 'notch':
        m1 = -k
    elif shape == 'hpf':
        m1, m2 = -k, -np.ones(n)
    elif shape == 'low_shelf':
        g /= np.sqrt(a)
        m1, m2 = k*(a-1), a*a-1
    else:
        g *= np.sqrt(a)
        m0, m1, m2 = a*a, k*(1-a)*a, 1-a*a
    a1 = 1/(1+g*(g+k))
    a2, a3 = g*a1, g*g*a1
    s1, s2 = np.zeros(x.shape[1]), np.zeros(x.shape[1])
    y = np.empty_like(x)
    for i, v in enumerate(x):
        v3 = v-s2
        bp = a1[i]*s1+a2[i]*v3
        lp = s2+a2[i]*s1+a3[i]*v3
        s1, s2 = 2*bp-s1, 2*lp-s2
        y[i] = m0[i]*v+m1[i]*bp+m2[i]*lp
    return y
