"""Absolute-clock helpers for spatial and modulation reference processors.

curve_integral(points, times, logarithmic=False) returns the analytic integral
from zero, with constant endpoint extension. rotor_motion(times, points, tau)
returns (cycles, Hz) for a piecewise-linear target passed through a one-pole;
the initial speed is the first target, and angle starts at zero.
allpass_cascade(x, sr, corners) evaluates zero-state first-order TPT sections;
corners has shape (1 or frames, channels, sections). pan_audio(x, positions)
uses the existing -3 dB pan law, with symmetric vector arithmetic.
No third-party implementation is copied.
"""
import math
import numpy as np
from scipy import signal


def curve_integral(points, times, logarithmic=False):
    a = np.asarray(points, dtype=np.float64)
    t = np.asarray(times, dtype=np.float64)
    knots, values = a.T
    result = (np.minimum(t, knots[0])-0)*values[0]
    for j in range(len(knots)-1):
        width = knots[j+1]-knots[j]
        u = np.clip(t-knots[j], 0, width)
        if logarithmic:
            slope = np.log(values[j+1]/values[j])/width
            result += values[j]*u if abs(slope) < 1e-14 else values[j]*np.expm1(slope*u)/slope
        else:
            result += values[j]*u + (values[j+1]-values[j])*u*u/(2*width)
    result += np.maximum(t-knots[-1], 0)*values[-1]
    return result


def rotor_motion(times, points, tau):
    t = np.asarray(times, dtype=np.float64)
    a = np.asarray(points, dtype=np.float64)
    # Include the constant target before the first supplied knot.
    if a[0, 0] > 0:
        a = np.vstack(([0., a[0, 1]], a))
    angle = np.zeros_like(t)
    speed = np.full_like(t, a[0, 1])
    initial, integral = a[0, 1], 0.
    for j in range(len(a)):
        start, target = a[j]
        end = a[j+1, 0] if j+1 < len(a) else np.inf
        slope = (a[j+1, 1]-target)/(end-start) if np.isfinite(end) else 0.
        mask = (t >= start) & (t < end)
        u = t[mask]-start
        delta = initial-target+slope*tau
        speed[mask] = target+slope*(u-tau)+delta*np.exp(-u/tau)
        angle[mask] = integral+target*u+slope*(u*u/2-tau*u)-delta*tau*np.expm1(-u/tau)
        if np.isfinite(end):
            u = end-start
            integral += target*u+slope*(u*u/2-tau*u)-delta*tau*np.expm1(-u/tau)
            initial = target+slope*(u-tau)+delta*np.exp(-u/tau)
    return angle, speed


def allpass_cascade(x, sr, corners):
    f = np.asarray(corners)
    wet = np.empty_like(x)
    for ch in range(x.shape[1]):
        if len(f) == 1:
            k = (np.tan(np.pi*f[0, ch]/sr)-1)/(np.tan(np.pi*f[0, ch]/sr)+1)
            wet[:, ch] = signal.sosfilt([[v, 1, 0, 1, v, 0] for v in k], x[:, ch])
        else:
            g = np.tan(np.pi*f[:, ch]/sr)
            g /= 1+g
            state = [0.]*f.shape[2]
            out = []
            for value, row in zip(x[:, ch].tolist(), g.tolist()):
                for j, coefficient in enumerate(row):
                    v = (value-state[j])*coefficient
                    low = v+state[j]
                    state[j] = low+v
                    value = 2*low-value
                out.append(value)
            wet[:, ch] = out
    return wet


def pan_audio(x, positions):
    p = np.asarray(positions, dtype=np.float64)
    exponent = -3/(20*math.log10(math.cos(math.pi/4)))
    # Mirrored positions use exactly the same transcendental operations.
    far_angle = (np.abs(p)+1)*np.pi/4
    far = np.cos(far_angle)
    far = np.where(far <= 1e-15, 0., far**exponent)
    near = np.sin(far_angle)**exponent
    gl, gr = np.where(p > 0, far, near), np.where(p > 0, near, far)
    center = math.cos(math.pi/4)**exponent
    gl, gr = np.where(p == 0, center, gl), np.where(p == 0, center, gr)
    if x.shape[1] == 1:
        return x*np.column_stack((gl, gr))
    return x*np.column_stack((np.minimum(1, gl/center), np.minimum(1, gr/center)))


def curve_param(pid, xunit, xmin, xmax, ymin, ymax, maximum, default):
    return dict(id=pid, type='curve', unit=None, x_unit=xunit, x_min=xmin,
                x_max=xmax, y_min=ymin, y_max=ymax, max_points=maximum,
                default=default, description='Absolute control curve with constant endpoint extension.')
