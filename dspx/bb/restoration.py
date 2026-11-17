"""Offline restoration support (independent implementation; SciPy BSD API).

rp_params(amount=1), definition(name, params) declare the RP contract.
region(frames,sr,p), region_mix(x,wet,sr,p) keep out-of-region bytes intact.
runs(mask) yields half-open intervals. finish(x,y,sr,p,**extra) returns the
normal/delta signal and JSON-safe measurements of actual changed intervals.
band(x,sr,lo,hi) uses a zero-phase Butterworth detector; zero edges are open.
"""
import math
import numpy as np
from scipy import fft, signal
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _b


def rp_params(amount=1):
    return [_f('amount', None, 0, 1, amount, 'Repair amount; zero bypasses.'),
            _b('delta', False, 'Output the removed signal.'),
            _f('start_s', 's', 0, 36000, 0, 'Region start; both zero means full.'),
            _f('end_s', 's', 0, 36000, 0, 'Region end; both zero means full.')]


def definition(name, params):
    return {'type': name, 'implemented': False, 'description': 'Offline AR restoration with residual audition.',
            'stages': ['track', 'bus'], 'master_slot': None, 'offline_only': True,
            'backends': ['reference'],
            'realtime': {'block_ok': False, 'latency_samples': 0, 'allocates': True}, 'params': params}


def validate_region(p):
    if (p['start_s'] or p['end_s']) and p['end_s'] <= p['start_s']:
        raise ParamError('end_s must exceed start_s, or both must be zero')


def region(frames, sr, p):
    validate_region(p)
    if p['start_s'] == p['end_s'] == 0:
        return 0, frames
    return min(frames, round(p['start_s']*sr)), min(frames, round(p['end_s']*sr))


def region_mix(x, wet, sr, p):
    y = x.copy()
    lo, hi = region(len(x), sr, p)
    if not p['amount'] or hi <= lo:
        return y
    w = np.full(hi-lo, p['amount'])
    ramp = min(round(.01*sr), (hi-lo)//2)
    if ramp and lo:
        w[:ramp] *= np.linspace(0, 1, ramp)
    if ramp and hi < len(x):
        w[-ramp:] *= np.linspace(1, 0, ramp)
    changed = np.any(wet[lo:hi] != x[lo:hi], axis=1) & (w != 0)
    ids = np.flatnonzero(changed)+lo
    y[ids] = x[ids]+w[changed, None]*(wet[ids]-x[ids])
    return y


def runs(mask):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    return list(zip(map(int, np.flatnonzero(edges == 1)), map(int, np.flatnonzero(edges == -1))))


def band(x, sr, lo=0, hi=0):
    if lo and hi and lo >= hi:
        raise ParamError('detector band must be ascending')
    if lo >= sr/2:
        raise ParamError('detector low edge must be below Nyquist')
    if not lo and (not hi or hi >= sr/2):
        return x.copy()
    edges = [lo, min(hi, sr*.49)] if lo and hi and hi < sr/2 else lo or hi
    kind = 'bandpass' if isinstance(edges, list) else ('highpass' if lo else 'lowpass')
    sos = signal.butter(4, edges, btype=kind, fs=sr, output='sos')
    return signal.sosfiltfilt(sos, x, axis=0, padlen=min(len(x)-1, round(.02*sr))) if len(x) > 1 else x.copy()


def finish(x, y, sr, p, **extra):
    from mankomix.dspx.procs.dehum import _measure
    removed = x-y
    def rel(num, den):
        return 10*math.log10(num/den) if num > 0 and den > 0 else None
    events = []
    for a, b in runs(np.any(removed != 0, axis=1)):
        strength = float(np.mean(removed[a:b]**2))
        events.append({'start_s': a/sr, 'length_s': (b-a)/sr,
                       'strength_dbfs': 10*math.log10(strength)})
    top = sorted(events, key=lambda e: (-e['strength_dbfs'], e['start_s']))[:2000]
    bands = []
    if len(x):
        fx, fd = fft.rfft(x, axis=0, workers=1), fft.rfft(removed, axis=0, workers=1)
        f = fft.rfftfreq(len(x), 1/sr)
        for lo, hi in ((0, 120), (120, 500), (500, 2000), (2000, 8000), (8000, sr/2+1)):
            if lo >= sr/2:
                continue
            k = (f >= lo) & (f < hi)
            # Doubling interior bins preserves Parseval weighting at DC/Nyquist.
            weight = np.full(len(f), 2.)
            weight[0] = 1
            if len(x) % 2 == 0:
                weight[-1] = 1
            num = float(np.sum(abs(fd[k])**2*weight[k, None]))
            den = float(np.sum(abs(fx[k])**2*weight[k, None]))
            bands.append({'lo_hz': lo, 'hi_hz': min(hi, sr/2), 'removed_energy_rel_db': rel(num, den)})
    stats = {'latency_samples': 0, 'event_count': len(events),
             'events': sorted(top, key=lambda e: e['start_s']),
             'removed_energy_rel_db': rel(float(np.sum(removed**2)), float(np.sum(x**2))),
             'removed_energy_bands': bands, 'before': _measure(x, sr), 'after': _measure(y, sr), **extra}
    return (removed if p.get('delta') and p.get('amount', 1) else y), sr, stats
