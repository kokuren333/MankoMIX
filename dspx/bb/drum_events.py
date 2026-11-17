"""BB-22 drum events with pinned raw-onset IDs and detector-band evidence.

drum_events(x,sr,params) returns every onset, including rejected events.
Band energies are zero-phase Butterworth measurements in the first 30 ms;
the underlying BB-22 position and ID are never changed by detector settings.
SciPy signal public APIs (BSD-3-Clause); no third-party code copied.
"""
import numpy as np
from scipy import signal
from mankomix.dsp.errors import ParamError

DETECT = {'threshold_db': (-80, 0, -30), 'detect_lo_hz': (20, 20000, 40),
          'detect_hi_hz': (20, 20000, 200), 'reject_lo_hz': (0, 20000, 0),
          'reject_hi_hz': (0, 20000, 0), 'reject_ratio_db': (-12, 24, 6),
          'min_interval_ms': (5, 500, 30)}


def check_bands(p):
    if p['detect_lo_hz'] >= p['detect_hi_hz']:
        raise ParamError('detect_lo_hz must be below detect_hi_hz')
    lo, hi = p['reject_lo_hz'], p['reject_hi_hz']
    if (lo == 0) != (hi == 0) or (hi and lo >= hi):
        raise ParamError('reject band requires both zero or 0 < lo < hi')


def band_audio(x, sr, lo, hi):
    hi = min(hi, .49*sr)
    if lo >= hi:
        raise ParamError('detector band must intersect frequencies below Nyquist')
    sos = signal.butter(3, [lo, hi], btype='bandpass', fs=sr, output='sos')
    return signal.sosfiltfilt(sos, x, axis=0, padlen=min(21, max(0, len(x)-1))) if len(x) else x.copy()


def drum_onsets(x, sr, *, min_interval_ms=30):
    """BB-22 events plus flux candidates missed by its full-band rise veto.

    Existing events keep their exact IDs and positions. Additional candidates
    use the same BB-22 spectral features/adaptive threshold and tangent rule,
    with a shorter envelope window for short clicks and low drum carriers.
    A quiet lead-in permits exact sample refinement. No envelope-only trigger
    is introduced: every candidate must be a spectral-flux peak.
    """
    from .onsets import detect_onsets, onset_features
    from scipy import ndimage
    primary = [r for r in detect_onsets(x, sr, min_interval_ms=min_interval_ms)
               if r['sample'] >= round(.001*sr)]
    features = onset_features(x, sr)
    if len(x) < 8 or not np.any(features.flux['full']):
        return primary
    width = max(3, round(.15*sr/features.hop_samples) | 1)
    candidates = {}
    spacing = max(1, round(min_interval_ms*sr/1000/features.hop_samples))
    for flux in features.flux.values():
        med = ndimage.median_filter(flux, size=width, mode='nearest')
        mean = ndimage.uniform_filter1d(flux, size=width, mode='nearest')
        floor = med+.75*mean
        peaks, _ = signal.find_peaks(flux, height=floor+np.max(flux)*.005, distance=spacing)
        for k in peaks:
            candidates[k] = max(candidates.get(k, 0.), float((flux[k]-floor[k])/max(flux[k], 1e-30)))
    power = np.mean(x*x, axis=1)
    env = np.sqrt(np.maximum(0, ndimage.uniform_filter1d(power, max(1, round(.0003*sr)), mode='nearest')))
    slope = ndimage.uniform_filter1d(np.gradient(env), max(1, round(.0002*sr)), mode='nearest')
    added = []
    for k, confidence in sorted(candidates.items()):
        center = int(features.samples[k])
        lo, hi = max(0, center-features.window_samples), min(len(x), center+features.window_samples//2)
        if hi <= lo or lo == 0:
            # Supplemental candidates require a complete preceding context;
            # the ordinary BB-22 detector remains authoritative at file head.
            continue
        j = lo+int(np.argmax(slope[lo:hi]))
        pre = env[max(0, j-round(.015*sr)):max(1, j-round(.003*sr))]
        post = env[j:min(len(x), j+round(.012*sr)+1)]
        base = float(np.percentile(pre, 20)) if len(pre) else 0.
        top = float(np.max(post, initial=0))
        rise = float(slope[j])
        if (rise <= 0 or top <= max(1e-9, base*1.8) or
                rise*sr/max(top-base, 1e-30) < 35 or
                (len(pre) and np.mean(post**2) <= 1.3*np.mean(pre**2))):
            continue
        sample = int(np.clip(round(j-(env[j]-base)/rise), lo, j))
        if sample < round(.001*sr):
            continue  # No preceding context for a supplemental attack at file head.
        # Preserve the standard meter's ID for an already measured hit.
        if any(abs(r['sample']-sample) < min_interval_ms*sr/1000 for r in primary+added):
            continue
        if sample < round(.001*sr) and env[0] > top*.3:
            continue
        peak = float(np.max(abs(x[sample:min(len(x), sample+round(.03*sr)+1)]), initial=0))
        energy = features.power[k]
        ratios = energy/max(float(energy.sum()), 1e-30)
        added.append({'id': f'o_{sample}', 'sample': sample, 'time_s': sample/sr,
                      'strength': float(features.flux['full'][k]/max(np.max(features.flux['full']), 1e-30)),
                      'peak_dbfs': float(20*np.log10(max(peak, 1e-15))),
                      'band_ratios': dict(zip(('low', 'mid', 'high'), map(float, ratios))),
                      'confidence': float(np.clip(confidence, 0, 1)), 'refinement': 'short_envelope_flux_peak'})
    return sorted(primary+added, key=lambda r: r['sample'])


def drum_events(x, sr, params):
    p = {k: params.get(k, v[2]) for k, v in DETECT.items()}
    check_bands(p)
    x = np.asarray(x, dtype=np.float64)
    detect = band_audio(x, sr, p['detect_lo_hz'], p['detect_hi_hz'])
    reject = band_audio(x, sr, p['reject_lo_hz'], p['reject_hi_hz']) if p['reject_hi_hz'] else None
    rows = drum_onsets(x, sr, min_interval_ms=p['min_interval_ms'])
    for row in rows:
        a, b = row['sample'], min(len(x), row['sample']+round(.03*sr))
        peak = float(np.max(np.abs(detect[a:b]), initial=0))
        energy = float(np.mean(detect[a:b]**2)) if b > a else 0.
        ratio = (10*np.log10(max(float(np.mean(reject[a:b]**2)), 1e-30)/max(energy, 1e-30))
                 if reject is not None else None)
        level = float(20*np.log10(max(peak, 1e-15)))
        reason = ('below_threshold' if level < p['threshold_db'] else
                  'reject_band' if ratio is not None and ratio >= p['reject_ratio_db'] else 'opened')
        row.update(detect_peak_dbfs=level, reject_ratio_db=ratio, opened=reason == 'opened', reason=reason)
    return rows, detect


def velocities(rows):
    """Flux and peak amplitude composite, normalized across accepted hits."""
    values = np.array([np.sqrt(max(0, r['strength'])*10**((r['peak_dbfs'] if r['peak_dbfs'] is not None else -300)/20)) for r in rows])
    return values/max(float(np.max(values, initial=0)), 1e-30)
