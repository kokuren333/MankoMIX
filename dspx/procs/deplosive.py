"""T10-13 conservative offline low-frequency burst suppression (RP).

Low-band onset candidates must coincide with a local low/mid energy-ratio
outlier above the active-track median. A zero-phase fourth-order low band
is subtracted only in recorded event spans. The control has a short cosine
attack and a release_ms cosine return; outside the spans samples are exact.
"""
import math
import numpy as np
from scipy import signal, ndimage, fft
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _b, _f
from mankomix.dspx.bb.onsets import detect_onsets
from mankomix.dspx.procs.dehum import _region, _measure

SPECS = [{
    'type': 'deplosive', 'implemented': True,
    'description': 'Offline onset-and-ratio-gated low-frequency burst suppression.',
    'stages': ['track', 'bus'], 'master_slot': None, 'offline_only': True,
    'backends': ['reference'],
    'realtime': {'block_ok': False, 'latency_samples': 0, 'allocates': True},
    'params': [
        _f('amount', None, 0, 1, 1, 'Removal amount; zero bypasses.'),
        _b('delta', False, 'Audition the removed signal.'),
        _f('start_s', 's', 0, 36000, 0, 'Region start; both zero means full.'),
        _f('end_s', 's', 0, 36000, 0, 'Region end; both zero means full.'),
        _f('freq_hz', 'Hz', 60, 300, 150, 'Upper edge of the suppressed low band.'),
        _f('threshold_db', 'dB', 0, 24, 8, 'Low/mid energy-ratio excess above median.'),
        _f('max_reduce_db', 'dB', 3, 36, 18, 'Maximum low-band attenuation.'),
        _f('min_ms', 'ms', 5, 50, 10, 'Minimum detected event duration.'),
        _f('max_ms', 'ms', 30, 300, 150, 'Maximum detected event duration.'),
        _f('lookahead_ms', 'ms', 0, 20, 5, 'Pre-onset control ramp.'),
        _f('release_ms', 'ms', 10, 300, 60, 'Cosine return to unity.')]}]


def deplosive(x, sr, p, *, seed=0):
    if p['min_ms'] > p['max_ms'] or p['freq_hz'] >= .49*sr:
        raise ParamError('invalid event duration or frequency for sample rate')
    left, right = _region(len(x), sr, p)
    y = x.copy()
    candidates = []
    baseline = None
    if p['amount'] and len(x) >= 16 and np.any(x) and left < right:
        sos = signal.butter(4, p['freq_hz'], fs=sr, output='sos')
        low = signal.sosfiltfilt(sos, x, axis=0, padlen=min(len(x)-1, round(.1*sr)))
        mid = signal.sosfiltfilt(signal.butter(4, [max(300, p['freq_hz']*1.5), min(2500, sr*.45)],
                                             btype='bandpass', fs=sr, output='sos'), x, axis=0,
                                 padlen=min(len(x)-1, round(.1*sr)))
        size = max(1, round(.01*sr))
        lp = ndimage.uniform_filter1d(np.mean(low*low, axis=1), size, mode='nearest')
        mp = ndimage.uniform_filter1d(np.mean(mid*mid, axis=1), size, mode='nearest')
        power = lp+mp
        ratio = 10*np.log10(np.maximum(lp, 1e-30)/np.maximum(mp, max(float(np.max(mp))*1e-8, 1e-30)))
        active = power > max(float(np.max(power))*1e-4, 1e-20)
        baseline = float(np.median(ratio[active])) if active.any() else 0.
        # A track with essentially no mid-band carrier (bass/kick only) has
        # no useful low/mid reference. Suppression requires a carrier.
        hot = (ratio > baseline+p['threshold_db']) & active & (baseline < 20)
        onsets = detect_onsets(low, sr, band='full', threshold=.15,
                               min_interval_ms=max(5, min(500, p['min_ms'])))
        envelope = np.zeros(len(x))
        last_end = -1
        for onset in onsets:
            n = onset['sample']
            if n < last_end:
                continue
            search = slice(max(left, n), min(right, n+round(.025*sr)))
            choices = np.flatnonzero(hot[search])
            if not len(choices):
                continue
            a = search.start+int(choices[0])
            b = a
            while b < right and hot[b]:
                b += 1
            duration = (b-a)*1000/sr
            if not p['min_ms'] <= duration <= p['max_ms']:
                continue
            a = max(left, min(a, n)-round(p['lookahead_ms']*sr/1000))
            end = min(right, b+round(p['release_ms']*sr/1000))
            control = np.ones(end-a)
            ramp = min(b-a, max(1, round(max(1, p['lookahead_ms'])*sr/1000)))
            control[:ramp] = .5-.5*np.cos(np.linspace(0, np.pi, ramp))
            if end > b:
                control[b-a:] = .5+.5*np.cos(np.linspace(0, np.pi, end-b))
            envelope[a:end] = np.maximum(envelope[a:end], control)
            candidates.append(onset['sample'])
            last_end = b
        # RP region boundary crossfades, retaining exact out-of-region samples.
        ramp = min(round(.01*sr), (right-left)//2)
        if ramp and left:
            envelope[left:left+ramp] *= np.linspace(0, 1, ramp)
        if ramp and right < len(x):
            envelope[right-ramp:right] *= np.linspace(1, 0, ramp)
        gain = 1-p['amount']*(1-10**(-p['max_reduce_db']/20))*envelope
        idx = envelope != 0
        y[idx] = x[idx]+(gain[idx, None]-1)*low[idx]
    removed = x-y
    changed = np.any(removed != 0, axis=1)
    edges = np.diff(np.r_[False, changed, False].astype(np.int8))
    events = []
    for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        strength = float(np.sqrt(np.mean(removed[a:b]**2)))
        events.append({'start_s': int(a)/sr, 'length_s': int(b-a)/sr,
                       'strength_dbfs': 20*math.log10(strength) if strength else None})
    def relative(num, den):
        return 10*math.log10(num/den) if num and den else None
    bands = []
    if len(x):
        fx, fr = fft.rfft(x, axis=0, workers=1), fft.rfft(removed, axis=0, workers=1)
        freq = fft.rfftfreq(len(x), 1/sr)
        for lo, hi in ((0, p['freq_hz']), (p['freq_hz'], 300), (300, 2500), (2500, sr/2+1)):
            if hi <= lo or lo >= sr/2:
                continue
            mask = (freq >= lo) & (freq < hi)
            bands.append({'lo_hz': lo, 'hi_hz': min(hi, sr/2),
                          'removed_energy_rel_db': relative(float(np.sum(abs(fr[mask])**2)), float(np.sum(abs(fx[mask])**2)))})
    top = sorted(events, key=lambda e: (-e['strength_dbfs'], e['start_s']))[:2000]
    stats = {'latency_samples': 0, 'event_count': len(events),
             'events': sorted(top, key=lambda e: e['start_s']),
             'onset_samples': candidates[:2000], 'ratio_median_db': baseline,
             'removed_energy_rel_db': relative(float(np.sum(removed*removed)), float(np.sum(x*x))),
             'removed_energy_bands': bands, 'before': _measure(x, sr), 'after': _measure(y, sr)}
    return (removed if p['delta'] and p['amount'] else y), sr, stats


IMPLS = {'deplosive': deplosive}


def _validate(p):
    if p['min_ms'] > p['max_ms'] or (p['start_s'] != 0 or p['end_s'] != 0) and p['end_s'] <= p['start_s']:
        raise ParamError('invalid event duration or RP region')


CROSS_VALIDATE = {'deplosive': _validate}
