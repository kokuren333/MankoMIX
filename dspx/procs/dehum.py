"""Offline harmonic hum suppression and conservative stable-line detection.

Original algorithms using public scipy FFT/filter/optimization APIs
(BSD-3-Clause, scipy 1.18.1). No third-party source is copied.
Notch depth is finite; forward/backward transfer has the requested center
gain and -3 dB width. Subtraction fits all harmonics jointly in 1 s windows
with 50% overlap. Measurements reuse the existing loudness/peak functions.
"""
from __future__ import annotations

import math
import numpy as np
from scipy import fft, optimize, signal
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _b, _e, _f, _i

SPECS = [{
    'type': 'dehum', 'implemented': True,
    'description': 'Offline stable harmonic hum suppression with residual audition.',
    'params': [_f('amount', None, 0, 1, 1, 'Removal amount; zero bypasses.'),
               _b('delta', False, 'Output only the removed signal.'),
               _f('start_s', 's', 0, 36000, 0, 'Region start; both zero means full.'),
               _f('end_s', 's', 0, 36000, 0, 'Region end; both zero means full.'),
               _f('base_hz', 'Hz', 0, 70, 0, 'Zero auto, otherwise 40..70 Hz.'),
               _i('harmonics', None, 1, 40, 8, 'Number of harmonic orders.'),
               _b('odd_only', False, 'Use odd harmonic orders only.'),
               _f('depth_db', 'dB', 3, 60, 30, 'Suppression at each notch center.'),
               _f('width_hz', 'Hz', 0.2, 10, 1, 'Zero-phase notch -3 dB width.'),
               _f('slope', 'dB/order', 0, 6, 0, 'Reduction in depth per harmonic order.'),
               _b('track', False, 'Follow slow base-frequency drift with 10 s windows.'),
               _e('mode', ['notch', 'subtract'], 'notch', 'Harmonic suppression method.')],
    'stages': ['track', 'bus'], 'master_slot': None, 'offline_only': True,
    'realtime': {'block_ok': False, 'latency_samples': 0, 'allocates': True},
    'backends': ['reference'],
}]


def _estimate(x, sr, lo=45.0, hi=65.0):
    """Strongest narrow stable low-frequency line, rounded to 0.01 Hz."""
    if len(x) < sr or not np.any(x):
        return None
    mono = x[:, int(np.argmax(np.mean(x*x, axis=0)))]
    ratio = max(1, int(sr//400))
    a = signal.resample_poly(mono, 1, ratio)
    rate = sr/ratio
    w = np.hanning(len(a))
    nfft = fft.next_fast_len(max(len(a), int(rate*100)))
    spectrum = np.abs(fft.rfft(a*w, nfft, workers=1))
    freqs = fft.rfftfreq(nfft, 1/rate)
    band = (freqs >= lo) & (freqs <= hi)
    k = np.flatnonzero(band)[int(np.argmax(spectrum[band]))]
    candidate = freqs[k]
    # Reject broad/noisy peaks. A line's Hann main lobe is excluded.
    background = (np.abs(freqs-candidate) > max(0.6, 3*rate/len(a))) & (np.abs(freqs-candidate) < 8)
    if spectrum[k] < 15*max(float(np.median(spectrum[background])), 1e-20):
        return None
    t = np.arange(len(a))/rate

    def score(f):
        z = np.exp(-2j*np.pi*f*t)
        return -abs(np.dot(a*w, z))**2

    fit = optimize.minimize_scalar(score, bounds=(max(lo, candidate-.05), min(hi, candidate+.05)),
                                   method='bounded', options={'xatol': 1e-8})
    f = float(fit.x)
    # Stable line must persist in both halves; isolated bursts are not hum.
    amps = []
    for chunk in np.array_split(a, 2):
        tt = np.arange(len(chunk))/rate
        amps.append(abs(np.dot(chunk*np.hanning(len(chunk)), np.exp(-2j*np.pi*f*tt)))/len(chunk))
    if min(amps) < 0.5*max(amps) or min(amps) < max(1e-7, .001*np.sqrt(np.mean(mono*mono))):
        return None
    return round(f, 2)


def _tracking(x, sr, base):
    centers = np.unique(np.r_[0, np.arange(5*sr, len(x), 5*sr), len(x)-1]).astype(int)
    values = []
    for c in centers:
        left = max(0, c-5*sr)
        right = min(len(x), c+5*sr)
        found = _estimate(x[left:right], sr, max(40, base-.5), min(70, base+.5))
        values.append(base if found is None else found)
    # The endpoint windows are one-sided; linear extrapolation of interior
    # centers avoids flattening a true slow ramp at the beginning and end.
    if len(centers) >= 4:
        values[0] = values[1] - (values[2]-values[1])*(centers[1]-centers[0])/(centers[2]-centers[1])
        values[-1] = values[-2] + (values[-2]-values[-3])*(centers[-1]-centers[-2])/(centers[-2]-centers[-3])
    return centers, np.clip(values, base-.5, base+.5)


def _notch(x, sr, base, orders, p):
    sections = []
    target = 2**-.5
    for order in orders:
        depth = max(0.0, p['depth_db']-p['slope']*(order-1))
        if depth == 0:
            continue
        gain = 10**(-depth/20)
        # At depths <=3.0103 dB a -3 dB crossing need not exist; keep the
        # underlying deep-notch width instead of introducing a singular Q.
        factor = math.sqrt((1-target)/(target-gain)) if gain < target else math.sqrt(math.sqrt(2)-1)
        width = p['width_hz']*factor
        b, a = signal.iirnotch(base*order, base*order/width, fs=sr)
        b = math.sqrt(gain)*a + (1-math.sqrt(gain))*b
        sections.append(np.r_[b, a])
    if not sections:
        return x.copy()
    pad = min(len(x)-1, int(math.ceil(12*sr/(np.pi*p['width_hz']*.64))))
    return signal.sosfiltfilt(np.asarray(sections), x, axis=0, padlen=pad)


def _phase(samples, sr, centers, frequencies):
    """Analytic integral of a piecewise linear frequency curve in cycles."""
    times = centers/sr
    areas = np.r_[0.0, np.cumsum(np.diff(times)*(frequencies[:-1]+frequencies[1:])/2)]
    index = np.clip(np.searchsorted(centers, samples, side='right')-1, 0, len(centers)-2)
    dt = (samples-centers[index])/sr
    slopes = np.diff(frequencies)/np.diff(times)
    return areas[index] + frequencies[index]*dt + slopes[index]*dt*dt/2


def _notch_tracked(x, sr, orders, p, tracking):
    """Two-pass biquads with sample-varying centers, rather than frozen blocks.

    A single state trajectory covers the whole input. Coefficients are derived
    from absolute positions of the 10 s analysis grid. Mirrored frequency and
    audio context initialize the passes without block seams.
    """
    pad = min(len(x)-1, int(math.ceil(12*sr/(np.pi*p['width_hz']*.64))))
    frequencies = np.interp(np.arange(len(x)), *tracking)
    frequencies = np.pad(frequencies, (pad, pad), mode='reflect')
    y = np.pad(x, ((pad, pad), (0, 0)), mode='reflect', reflect_type='odd')
    for order in orders:
        depth = max(0.0, p['depth_db']-p['slope']*(order-1))
        if depth == 0:
            continue
        gain = 10**(-depth/20)
        target = 2**-.5
        factor = math.sqrt((1-target)/(target-gain)) if gain < target else math.sqrt(math.sqrt(2)-1)
        beta = math.tan(np.pi*p['width_hz']*factor/sr)
        g, root = 1/(1+beta), math.sqrt(gain)
        a1 = -2*g*np.cos(2*np.pi*frequencies*order/sr)
        a2 = 2*g-1
        b0 = root + (1-root)*g
        b2 = root*a2 + (1-root)*g
        # b1 == a1 for the finite-depth numerator blend.
        for reverse in (False, True):
            source = y[::-1] if reverse else y
            coeff = a1[::-1] if reverse else a1
            out = np.empty_like(source)
            for channel in range(source.shape[1]):
                s1 = s2 = 0.0
                for i in range(len(source)):
                    v = source[i, channel]
                    z = b0*v+s1
                    s1 = coeff[i]*(v-z)+s2
                    s2 = b2*v-a2*z
                    out[i, channel] = z
            y = out[::-1] if reverse else out
    return y[pad:pad+len(x)]


def _subtract(x, sr, base, orders, p, tracking=None):
    size, hop = sr, max(1, sr//2)
    result, weight = np.zeros_like(x), np.zeros(len(x))
    n = np.arange(len(x))
    phase = base*n/sr if tracking is None else _phase(n, sr, *tracking)
    gains = np.repeat([1-10**(-max(0, p['depth_db']-p['slope']*(o-1))/20) for o in orders], 2)
    for start in range(-hop, len(x), hop):
        left, right = max(0, start), min(len(x), start+size)
        if right <= left:
            continue
        w = np.sin(np.pi*(np.arange(left, right)-start+.5)/size)**2
        angle = 2*np.pi*phase[left:right, None]*np.asarray(orders)[None, :]
        design = np.stack([np.sin(angle), np.cos(angle)], axis=2).reshape(right-left, -1)
        root = np.sqrt(w)
        coeff = np.linalg.lstsq(design*root[:, None], x[left:right]*root[:, None], rcond=None)[0]
        result[left:right] += (design @ (coeff*gains[:, None]))*w[:, None]
        weight[left:right] += w
    return x-result/weight[:, None]


def _region(length, sr, p):
    if p['start_s'] == p['end_s'] == 0:
        return 0, length
    if p['end_s'] <= p['start_s']:
        raise ParamError('dehum: end_s must exceed start_s (or both zero)')
    return min(length, int(round(p['start_s']*sr))), min(length, int(round(p['end_s']*sr)))


def _measure(x, sr):
    from mankomix.core.measure import loudness
    from mankomix.core.errors import InputError
    def finite(v):
        return float(v) if math.isfinite(v) else None
    try:
        lufs = finite(loudness.integrated(x, sr))
    except InputError:
        lufs = None  # Existing K-weighting does not support very low sr.
    return {'lufs_i': lufs,
            'sample_peak_dbfs': finite(loudness.sample_peak_dbfs(x)),
            'true_peak_dbtp': finite(loudness.true_peak_dbtp(x, sr))}


def dehum(x, sr, p, *, seed=0):
    if p['base_hz'] != 0 and not 40 <= p['base_hz'] <= 70:
        raise ParamError('dehum: base_hz must be 0 or 40..70 Hz')
    left, right = _region(len(x), sr, p)
    base, tracking = None, None
    y = x.copy()
    if p['amount'] != 0 and right > left and np.any(x[left:right]):
        base = p['base_hz'] or _estimate(x[left:right], sr)
        if base is not None:
            orders = [i for i in range(1, p['harmonics']+1)
                      if (not p['odd_only'] or i % 2) and base*i < sr*.49]
            if p['track'] and len(x) > sr:
                tracking = _tracking(x, sr, base)
            if not orders:
                wet = x.copy()
            elif p['mode'] == 'subtract':
                wet = _subtract(x, sr, base, orders, p, tracking)
            elif tracking is None:
                wet = _notch(x, sr, base, orders, p)
            else:
                wet = _notch_tracked(x, sr, orders, p, tracking)
            blend = np.ones(right-left)*p['amount']
            ramp = min(int(round(.01*sr)), (right-left)//2)
            if ramp and (left or right < len(x)):
                if left:
                    blend[:ramp] *= np.linspace(0, 1, ramp)
                if right < len(x):
                    blend[-ramp:] *= np.linspace(1, 0, ramp)
            y[left:right] = x[left:right] + blend[:, None]*(wet[left:right]-x[left:right])
    removed = x-y
    changed = np.any(removed != 0, axis=1)
    edges = np.diff(np.r_[False, changed, False].astype(np.int8))
    events = []
    for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        strength = float(np.sqrt(np.mean(removed[a:b]**2)))
        events.append({'start_s': a/sr, 'length_s': (b-a)/sr,
                       'strength_dbfs': 20*math.log10(strength) if strength else None})
    power = float(np.sum(x*x))
    rel = float(np.sum(removed*removed))/power if power else 0.0
    bands = []
    if len(x):
        fx, fr = fft.rfft(x, axis=0, workers=1), fft.rfft(removed, axis=0, workers=1)
        frequencies = fft.rfftfreq(len(x), 1/sr)
        for lo, hi in ((0, 120), (120, 500), (500, 2000), (2000, 8000), (8000, sr/2+1)):
            if lo >= sr/2:
                continue
            mask = (frequencies >= lo) & (frequencies < hi)
            den = float(np.sum(np.abs(fx[mask])**2))
            num = float(np.sum(np.abs(fr[mask])**2))
            bands.append({'lo_hz': lo, 'hi_hz': min(hi, sr/2),
                          'removed_energy_rel_db': 10*math.log10(num/den) if num and den else None})
    top = sorted(events, key=lambda e: (-(e['strength_dbfs'] if e['strength_dbfs'] is not None
                                        else -math.inf), e['start_s']))[:2000]
    stats = {'detected': base is not None, 'base_hz': base,
             'event_count': len(events), 'events': sorted(top, key=lambda e: e['start_s']),
             'removed_energy_rel_db': 10*math.log10(rel) if rel else None,
             'removed_energy_bands': bands, 'before': _measure(x, sr), 'after': _measure(y, sr)}
    if tracking is not None:
        stats['tracking'] = [[int(n)/sr, round(float(f), 6)] for n, f in zip(*tracking)]
    # amount=0 bypass has priority over residual audition (RP1).
    return (removed if p['delta'] and p['amount'] != 0 else y), sr, stats


IMPLS = {'dehum': dehum}
