"""Absolute-block PCG64 noise, fixed FIR colours and Poisson shot noise.

API: noise_components(frames, sr, p, seed=0, start_sample=0) returns a dict
of stationary unit-RMS hiss/crackle/hum/rumble arrays and click sample times.
The fixed 4096-sample event grid and independently keyed components make
random access identical to slicing a full render. Colour FIR energy and
Poisson shot-noise variance set ensemble RMS, never per-render normalization.
Public scipy.signal/fft APIs (SciPy 1.18.1, BSD-3-Clause); no source port.
"""
from functools import lru_cache
import numpy as np
from mankomix.dspx.params import _f, _e, _i
from mankomix.dspx.bb.time_creative import definition, curve_param

BLOCK = 4096


def _rng(seed, knob, component, block):
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(
        [int(seed), int(knob), component, int(block)+2**40])))


def _white(first, last, channels, seed, knob, component):
    out = np.empty((last-first, channels))
    for block in range(first//BLOCK, (last-1)//BLOCK+1):
        values = _rng(seed, knob, component, block).standard_normal((BLOCK, channels))
        a, b = max(first, block*BLOCK), min(last, (block+1)*BLOCK)
        out[a-first:b-first] = values[a-block*BLOCK:b-block*BLOCK]
    return out


@lru_cache(maxsize=32)
def color_fir(sr, color, spectrum=()):
    """Return fixed, unit-energy colour FIR (the impulse is cached read-only)."""
    from mankomix.dspx.bb.fir import design_linear_fir, curve_magnitude
    if color == 'white' and not spectrum:
        h = np.ones(1)
    else:
        taps = 2*round(sr*.085)+1
        def magnitude(f):
            if spectrum:
                return curve_magnitude(f, list(spectrum))
            if color == 'pink':
                return np.maximum(f, 10)**(-.5)
            if color == 'rumble':
                return 1/np.sqrt(1+(f/15)**8)
            return np.sqrt(np.maximum(f, 20)/max(sr/2, 20))
        h = design_linear_fir(magnitude, sr, taps)
        h /= np.sqrt(np.sum(h*h))
    h.setflags(write=False)
    return h


def _colored(frames, start, sr, p, seed, component, color, channels, spectrum=()):
    from mankomix.dspx.bb.fir import fft_convolve
    h = color_fir(sr, color, spectrum)
    if not frames:
        return np.empty((0, channels))
    # Fixed blocks of output convolution keep arithmetic independent of excerpts.
    out = np.empty((frames, channels))
    for block in range(start//BLOCK, (start+frames-1)//BLOCK+1):
        a, b = block*BLOCK, (block+1)*BLOCK
        w = _white(a-len(h)+1, b, channels, seed, p['seed'], component)
        filtered = fft_convolve(w, h)[len(h)-1:len(h)-1+BLOCK]
        lo, hi = max(a, start), min(b, start+frames)
        out[lo-start:hi-start] = filtered[lo-a:hi-a]
    return out


def _clicks(frames, start, sr, p, seed, channels):
    length = max(1, round(sr*.003))
    h = np.exp(-np.arange(length)/(max(1, sr*.0005)))
    norm = np.sqrt(p['crackle_rate_hz']/sr*np.sum(h*h))
    out = np.zeros((frames, channels))
    arrivals = []
    for block in range((start-length)//BLOCK, (start+frames-1)//BLOCK+1):
        rng = _rng(seed, p['seed'], 2, block)
        count = rng.poisson(p['crackle_rate_hz']*BLOCK/sr)
        positions = block*BLOCK+rng.integers(0, BLOCK, count)
        amplitudes = rng.standard_normal((count, channels))
        for pos, amp in zip(positions, amplitudes):
            if start <= pos < start+frames:
                arrivals.append(int(pos))
            lo, hi = max(start, pos), min(start+frames, pos+length)
            if hi > lo:
                out[lo-start:hi-start] += h[lo-pos:hi-pos, None]*amp/norm
    return out, sorted(arrivals)


def noise_components(frames, sr, p, seed=0, start_sample=0, channels=2):
    spectrum = tuple(tuple(point) for point in p['spectrum'])
    result = {}
    if p['hiss_db'] > -120:
        result['hiss'] = _colored(frames, start_sample, sr, p, seed, 1, p['hiss_color'], channels, spectrum)
    if p['crackle_db'] > -120:
        result['crackle'], result['click_samples'] = _clicks(frames, start_sample, sr, p, seed, channels)
    if p['rumble_db'] > -120:
        result['rumble'] = _colored(frames, start_sample, sr, p, seed, 4, 'rumble', channels)
    if p['hum_db'] > -120:
        t = np.arange(start_sample, start_sample+frames)/sr
        orders = [k for k in (1, 3, 5, 7) if k*p['hum_hz'] < .45*sr]
        hum = sum(np.sin(2*np.pi*k*p['hum_hz']*t)/k for k in orders)
        hum /= np.sqrt(.5*sum(1/k**2 for k in orders))
        result['hum'] = np.repeat(hum[:, None], channels, axis=1)
    return result


def _dropout(frames, sr, p, seed):
    gain = np.ones(frames)
    for block in range(-1, (frames-1)//BLOCK+1):
        rng = _rng(seed, p['seed'], 5, block)
        count = rng.poisson(10*BLOCK/sr)
        # Fixed four draws per candidate, including disabled dropouts.
        for u, pos, length, depth in rng.random((count, 4)):
            at = block*BLOCK+int(pos*BLOCK)
            end = at+max(1, round((.005+.045*length)*sr))
            if u < p['dropout']:
                a, b = max(0, at), min(frames, end)
                if b > a:
                    gain[a:b] *= 1-p['dropout']*(.5+.5*depth)
    return gain


def noise_bed(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.dynamics import envelope
    if all(p[name] == -120 for name in ('hiss_db', 'crackle_db', 'hum_db', 'rumble_db')) and not p['dropout']:
        return x.copy(), sr, {'click_count': 0}
    parts = noise_components(len(x), sr, p, seed, channels=x.shape[1])
    added = np.zeros_like(x)
    for name in ('hiss', 'crackle', 'hum', 'rumble'):
        if name in parts:
            v = parts[name]
            if x.shape[1] == 2 and p['width'] < 1:
                # Equal power common/independent mix; width=0 is exactly mono.
                v = np.sqrt(1-p['width'])*v[:, :1]+np.sqrt(p['width'])*v
                normalizer = np.sqrt(1+2*np.sqrt(p['width']*(1-p['width'])))
                v = v/normalizer if name == 'hum' else v/np.array([[normalizer, 1]])
            added += v*10**(p[name+'_db']/20)
    if p['follow']:
        env = envelope(np.max(np.abs(x), axis=1), sr, 1, p['follow_release_ms'])
        added *= (1-p['follow']+p['follow']*np.clip(env, 0, 1))[:, None]
    gain = _dropout(len(x), sr, p, seed) if p['dropout'] else np.ones(len(x))
    return x*gain[:, None]+added, sr, {'click_count': len(parts.get('click_samples', [])),
                                    'click_samples': parts.get('click_samples', [])}


SPECS = [definition('noise_bed', [
    _f('hiss_db', 'dBFS', -120, -30, -120, 'Hiss ensemble RMS; -120 disables.'),
    _e('hiss_color', ['white', 'pink', 'tape'], 'tape', 'Fixed FIR colour.'),
    _f('crackle_db', 'dBFS', -120, -20, -120, 'Poisson crackle ensemble RMS.'),
    _f('crackle_rate_hz', 'Hz', .1, 100, 8, 'Poisson arrival rate.'),
    _f('hum_db', 'dBFS', -120, -30, -120, 'Fundamental plus three odd harmonics RMS.'),
    _e('hum_hz', [50, 60], 50, 'Hum fundamental.'),
    _f('rumble_db', 'dBFS', -120, -30, -120, 'Sub-20 Hz rumble ensemble RMS.'),
    curve_param('spectrum', 64, 1, 24000, -120, 24, 'Hz'),
    _f('follow', None, 0, 1, 0, 'Input-envelope proportion.'),
    _f('follow_release_ms', 'ms', 10, 2000, 300, 'Envelope release tau.'),
    _f('dropout', None, 0, 1, 0, 'Dropout probability and depth.'),
    _f('width', None, 0, 1, 1, 'Noise decorrelation.'),
    _i('seed', None, 0, 65535, 0, 'Noise seed.')], implemented=True)]
TIME_VARYING = {'noise_bed'}
IMPLS = {'noise_bed': noise_bed}
