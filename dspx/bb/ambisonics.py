"""File-conversion mathematics, independent of the mono/stereo mix graph.

ACN/SN3D without Condon-Shortley phase, following Nachbar et al., AmbiX
(2011), https://ambisonics.iem.at/xchange/fileformat/2011_nachbarzottersontacchideleflie_ambix.pdf
Original solid-harmonic polynomial recurrence and spherical-moment rotation;
no third-party implementation is used. Orders one through three only.
Axes: x front, y left, z up. Positive azimuth points left. Active rotations
are Rz(yaw) Ry(pitch) Rx(roll), i.e. roll, then pitch, then yaw.
"""
from __future__ import annotations

from functools import lru_cache
from math import factorial, isqrt, sqrt

import numpy as np


def order_for_channels(channels):
    order = isqrt(channels) - 1
    if order not in (1, 2, 3) or (order + 1)**2 != channels:
        raise ValueError("Ambisonic input requires (N+1)^2 channels, N=1..3 (4, 9 or 16)")
    return order


def _add(*terms):
    result = {}
    for scale, poly in terms:
        for key, value in poly.items():
            result[key] = result.get(key, 0) + scale*value
    return result


def _mul(a, b):
    result = {}
    for ka, va in a.items():
        for kb, vb in b.items():
            key = tuple(x+y for x, y in zip(ka, kb))
            result[key] = result.get(key, 0) + va*vb
    return result


def _harmonics(order, axes):
    """Recursively lift Cartesian coordinates to real solid harmonics.

    Q[m,m]=(2m-1)(x+iy)Q[m-1,m-1]; Q[m+1,m]=(2m+1)zQ[m,m].
    Q[l,m]=((2l-1)zQ[l-1,m]-(l+m-1)r^2 Q[l-2,m])/(l-m).
    Substituting rotated axes builds higher-order rotations from the 3x3
    rotation, without sampled fitting, Euler singularities or SVD repair.
    """
    x, y, z = axes
    r2 = _add(*[(1, _mul(a, a)) for a in axes])
    q = {}
    for m in range(order+1):
        q[m, m] = ({(0, 0, 0): 1} if m == 0 else
                   _add((2*m-1, _mul(_add((1, x), (1j, y)), q[m-1, m-1]))))
        if m < order:
            q[m+1, m] = _add((2*m+1, _mul(z, q[m, m])))
        for n in range(m+2, order+1):
            q[n, m] = _add(((2*n-1)/(n-m), _mul(z, q[n-1, m])),
                           (-(n+m-1)/(n-m), _mul(r2, q[n-2, m])))
    result = []
    for n in range(order+1):
        for m in range(-n, n+1):
            k = abs(m)
            scale = sqrt((2 if k else 1)*factorial(n-k)/factorial(n+k))
            result.append({key: float(scale*(complex(v).imag if m < 0 else complex(v).real))
                           for key, v in q[n, k].items()})
    return result


_AXES = ({(1, 0, 0): 1}, {(0, 1, 0): 1}, {(0, 0, 1): 1})


@lru_cache(maxsize=3)
def _basis(order):
    if order not in (1, 2, 3):
        raise ValueError("order must be 1, 2 or 3")
    return _harmonics(order, _AXES)


def harmonics(order, azimuth, elevation):
    az, el = np.radians(azimuth), np.radians(elevation)
    xyz = np.stack(np.broadcast_arrays(np.cos(el)*np.cos(az),
                                       np.cos(el)*np.sin(az), np.sin(el)), axis=-1)
    return np.stack([sum(v*np.prod(xyz**np.array(k), axis=-1) for k, v in p.items())
                     for p in _basis(order)], axis=-1)


def _double_factorial(n):
    result = 1
    while n > 0:
        result *= n
        n -= 2
    return result


def _moment(key):
    if any(k % 2 for k in key):
        return 0.
    return np.prod([_double_factorial(k-1) for k in key]) / _double_factorial(sum(key)+1)


def rotation_matrix(order, yaw=0., pitch=0., roll=0.):
    """Exact polynomial projection using analytic unit-sphere moments."""
    basis = _basis(order)
    angles = np.asarray([yaw, pitch, roll], dtype=np.float64)
    if not np.isfinite(angles).all():
        raise ValueError("rotation angles must be finite")
    if np.all(angles == 0):
        return np.eye((order+1)**2)
    a, b, c = np.radians(angles % 360)
    rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    rx = np.array([[1, 0, 0], [0, np.cos(c), -np.sin(c)], [0, np.sin(c), np.cos(c)]])
    cartesian = rz @ ry @ rx
    axes = [{key: cartesian[i, j] for j, axis in enumerate(_AXES) for key in axis}
            for i in range(3)]
    rotated = _harmonics(order, axes)
    result = np.zeros(((order+1)**2, (order+1)**2))
    result[0, 0] = 1
    # First degree is the Cartesian 3x3 matrix in ACN order Y,Z,X.
    result[1:4, 1:4] = cartesian[np.ix_([1, 2, 0], [1, 2, 0])]
    for n in range(2, order+1):
        for i in range(n*n, (n+1)**2):
            for j in range(n*n, (n+1)**2):
                result[i, j] = (2*n+1)*sum(
                    va*vb*_moment(tuple(a+b for a, b in zip(ka, kb)))
                    for ka, va in rotated[i].items() for kb, vb in basis[j].items())
    return result


def encode(x, order=1, azimuth=0., elevation=0.):
    """Treat stereo as one point source using its arithmetic mono sum."""
    if x.shape[1] not in (1, 2):
        raise ValueError("encode requires mono or stereo input")
    if not np.isfinite([azimuth, elevation]).all() or not -180 <= azimuth <= 180 or not -90 <= elevation <= 90:
        raise ValueError("azimuth must be -180..180 and elevation -90..90 degrees")
    return np.mean(x, axis=1, keepdims=True)*harmonics(order, azimuth, elevation)


def stereo(x, angle=90.):
    order_for_channels(x.shape[1])
    if not np.isfinite(angle) or not 0 <= angle <= 180:
        raise ValueError("angle must be 0..180 degrees")
    # An actual first-degree cardioid has no higher-degree terms.
    weights = .5*harmonics(1, np.array([angle, -angle]), 0.)
    return x[:, :4] @ weights.T


def convert(x, source, target):
    if x.shape[1] != 4:
        raise ValueError("FuMa conversion requires exactly four channels (first order)")
    if source not in ("fuma", "ambix") or target not in ("fuma", "ambix"):
        raise ValueError("formats must be fuma or ambix")
    if source == target:
        return x.copy()
    if source == "fuma":
        y = x[:, [0, 2, 3, 1]].copy()
        y[:, 0] *= sqrt(2)
    else:
        y = x[:, [0, 3, 1, 2]].copy()
        y[:, 0] /= sqrt(2)
    return y


def speaker_directions():
    """Icosahedron vertices and face centres (dual dodecahedron): 32 rays."""
    phi = (1+sqrt(5))/2
    ico, dual = [], []
    for a in (-1., 1.):
        for b in (-1., 1.):
            ico.extend([(0, a, b*phi), (a, b*phi, 0), (b*phi, 0, a)])
            dual.extend([(0, a*phi, b/phi), (a*phi, b/phi, 0), (b/phi, 0, a*phi)])
            for c in (-1., 1.):
                dual.append((a, b, c))
    xyz = np.array(ico+dual)
    xyz /= np.linalg.norm(xyz, axis=1, keepdims=True)
    return np.degrees(np.arctan2(xyz[:, 1], xyz[:, 0])), np.degrees(np.arcsin(xyz[:, 2]))


def speaker_weights():
    """Sphere quadrature through degree seven, sufficient for third order.

    Each polyhedron integrates degree <=5. For x^6 their averages are 2/15
    and 4/27; group weights 5/14 and 9/14 give the sphere moment 1/7.
    Icosahedral symmetry fixes the other degree-six moments; odd ones vanish.
    """
    return np.r_[np.full(12, 5/168), np.full(20, 9/280)]


def binaural(x, sr, hrtf="model_sphere"):
    from .hrtf import load_hrtf
    from .fir import fft_convolve
    order = order_for_channels(x.shape[1])
    dataset, provenance = load_hrtf(hrtf, sr)
    az, el = speaker_directions()
    degrees = np.array([isqrt(k) for k in range(x.shape[1])])
    decoder = harmonics(order, az, el)*(2*degrees+1)*speaker_weights()[:, None]
    # HRTF uses positive-right azimuth, AmbiX uses positive-left.
    kernels = [dataset.kernel(float(-a), float(e), sr) for a, e in zip(az, el)]
    h = np.zeros((max(map(len, kernels)), x.shape[1], 2))
    for row, kernel in zip(decoder, kernels):
        h[:len(kernel)] += kernel[:, None, :]*row[None, :, None]
    return fft_convolve(x, h, "same"), {
        "hrtf": hrtf, "source_sha256": provenance["source_sha256"],
        "asset": provenance["asset"], "warnings": provenance["warnings"],
        "virtual_speakers": len(az), "tail": "trimmed to input length",
        "note": "Headphones only; individual localization is not guaranteed."}
