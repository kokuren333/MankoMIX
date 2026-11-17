"""Shared tape speed generator: analytic integration, never a cumulative clock.

API: wobble(frames, sr, *, channels=1, start_sample=0, seed=0,
wow_depth=.2, wow_rate_hz=.6, flutter_depth=.05, flutter_rate_hz=9,
drift=.3, scrape=0, stereo_link=1) returns (displacement_samples,
speed_deviation_fraction). Both arrays are float64, frames x channels.
wobble_from_params(frames, sr, p, **clock) accepts the processor dictionary.
base_latency(sr, p) returns the conservative integer base latency.

Random motion is a band-limited periodic random walk: PCG64 values on an
absolute 60-second grid, Fourier interpolation with a 1/f displacement
spectrum, and an analytic derivative. No DC or integrated random bias.
The grid's periodic extension is intentional and independent of render length.
The deterministic sinusoids retain their requested frequencies. No copied code.
"""
import numpy as np
from scipy.fft import rfft, rfftfreq

from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb.curves import _clock
from mankomix.dspx.bb.modulation import combined_seed


def _random_motion(samples, sr, rate, seed, phase=0.):
    count = max(8, int(np.ceil(120*rate))+2)
    rng = np.random.Generator(np.random.PCG64(int(seed)))
    grid = rng.uniform(-1, 1, count)
    coeff = rfft(grid, workers=1)[1:]
    hz = rfftfreq(count, 60/count)[1:]
    valid = hz <= rate
    hz, coeff = hz[valid], coeff[valid]
    if len(hz) > 24:
        # A fixed logarithmic harmonic grid bounds CPU cost independently of
        # the requested excerpt. All selected bins remain <= rate_hz.
        indices = np.unique(np.rint(np.geomspace(1, len(hz), 24)).astype(int)-1)
        hz, coeff = hz[indices], coeff[indices]
    if not len(hz):
        return np.zeros(len(samples)), np.zeros(len(samples)), 0.
    omega = 2*np.pi*hz
    # 1/f displacement = integrated band-limited white velocity.
    a = coeff / omega
    norm = float(np.sum(np.abs(coeff)))
    a /= norm
    a *= np.exp(2j*np.pi*phase)
    displacement, velocity = np.zeros(len(samples)), np.zeros(len(samples))
    # Absolute modulo samples gives bit-identical random access at any offset.
    t = np.remainder(samples, 60*sr)/sr
    for w, value in zip(omega, a):
        phase = w*t
        displacement += value.real*np.cos(phase) - value.imag*np.sin(phase)
        velocity += -w*(value.real*np.sin(phase) + value.imag*np.cos(phase))
    return displacement, velocity, float(np.sum(np.abs(a)))


def wobble(frames, sr, *, channels=1, start_sample=0, seed=0, wow_depth=.2,
           wow_rate_hz=.6, flutter_depth=.05, flutter_rate_hz=9, drift=.3,
           scrape=0, stereo_link=1):
    """Integrate fractional speed deviations; d(displacement_seconds)/dt = -v."""
    samples = _clock(frames, sr, start_sample)
    values = (wow_depth, wow_rate_hz, flutter_depth, flutter_rate_hz, drift, scrape, stereo_link)
    if (not np.isfinite(values).all() or wow_depth < 0 or flutter_depth < 0 or
            wow_rate_hz <= 0 or flutter_rate_hz <= 0 or channels < 1 or
            any(not 0 <= v <= 1 for v in (drift, scrape, stereo_link))):
        raise ParamError('invalid speed generator controls')
    displacement, speed = np.zeros((frames, channels)), np.zeros((frames, channels))
    for c in range(channels):
        for depth, rate, salt in ((wow_depth, wow_rate_hz, 0), (flutter_depth, flutter_rate_hz, 1009)):
            if not depth:
                continue
            t = samples.astype(np.float64)/sr
            phase = 2*np.pi*np.remainder(t*rate, 1.)
            v = np.sin(phase)
            integral = -np.cos(phase)/(2*np.pi*rate)
            if drift:
                d0, v0, _ = _random_motion(samples, sr, rate, seed+salt)
                if c and stereo_link < 1:
                    dc, vc, _ = _random_motion(samples, sr, rate, seed+salt+65537*c)
                    d0 = stereo_link*d0 + (1-stereo_link)*dc
                    v0 = stereo_link*v0 + (1-stereo_link)*vc
                integral = (1-drift)*integral + drift*d0
                v = (1-drift)*v + drift*v0
            # Unlinked deterministic motion also receives independent phases.
            if c and stereo_link < 1 and not drift:
                theta = 2*np.pi*.371*c
                integral = stereo_link*integral - (1-stereo_link)*np.cos(phase+theta)/(2*np.pi*rate)
                v = stereo_link*v + (1-stereo_link)*np.sin(phase+theta)
            displacement[:, c] -= depth*.01*integral*sr
            speed[:, c] += depth*.01*v
        if scrape:
            rng = np.random.Generator(np.random.PCG64(int(seed)+2003))
            phases = rng.uniform(0, 2*np.pi, 8)
            for f, phase in zip(np.linspace(min(2000, sr*.2), min(3500, sr*.4), 8), phases):
                if c:
                    phase += (1-stereo_link)*c*.713
                w = 2*np.pi*f
                arg = w*(samples.astype(float)/sr)+phase
                amp = scrape*1e-5/8
                speed[:, c] += amp*np.sin(arg)
                displacement[:, c] += sr*amp*np.cos(arg)/w
    return displacement, speed


def wobble_from_params(frames, sr, p, *, channels=1, start_sample=0, seed=0):
    keys = ('wow_depth', 'wow_rate_hz', 'flutter_depth', 'flutter_rate_hz', 'drift', 'scrape', 'stereo_link')
    controls = {k: p[k] for k in keys if k in p}
    return wobble(frames, sr, channels=channels, start_sample=start_sample,
                  seed=combined_seed(seed, p), **controls)


def base_latency(sr, p):
    # A 60-second random component can contain a 1/60 Hz term.
    drift = p.get('drift', .3)
    span = .03*((1-drift)/(2*np.pi*p['wow_rate_hz']) + drift*60/(2*np.pi))
    span += .01*((1-drift)/(2*np.pi*p['flutter_rate_hz']) + drift*60/(2*np.pi))
    return int(np.ceil(sr*span)) + 2
