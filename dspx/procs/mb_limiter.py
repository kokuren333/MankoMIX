"""T01-12 sample-peak limiting with bounded control-window smoothing.

The release follower never falls below instantaneous attenuation demand.
Dilation by r samples followed by a nonnegative, unit-sum window of radius
r makes every averaged gain <= the instantaneous required gain. Two stages
each require 2*r samples of lookahead. Offline output is compensated; raw
output is a delayed copy of that same complete-context result.
"""
import numpy as np
from scipy import ndimage
from mankomix.dspx.bb import crossover as C, dynamics as D
from mankomix.dspx.params import _a, _b, _f

_mb = C.mb_params()
_mb[1]['default'] = 'linear'
SPECS = [{
    'type': 'mb_limiter', 'implemented': True,
    'description': 'Multiband and broadband sample-peak limiter; true peak is measured only.',
    'stages': ['track', 'bus', 'master'], 'master_slot': 5,
    'offline_only': False, 'backends': ['reference'],
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0,
                 'latency_rule': 'linear crossover delay plus 4*floor(round(lookahead_ms*sr/1000)/2); compensated offline'},
    'params': _mb+[
        _a('threshold_db', 'dBFS', -24, 0, 6, [], 'Per-band ceiling; empty means -3.'),
        _a('release_ms', 'ms', 5, 2000, 6, [], 'Per-band release; empty means 100.'),
        _f('lookahead_ms', 'ms', .5, 10, 2, 'Lookahead per limiting stage.'),
        _b('stereo_link', True, 'Maximum-linked peak detector.'),
        _f('out_ceiling_db', 'dBFS', -24, 0, -.3, 'Final broadband sample ceiling.')]}]
TIME_VARYING = {'mb_limiter'}


def latency_samples(sr, p):
    fir = (C.taps_for(min(p['crossovers_hz']), sr)-1)//2 if p['phase'] == 'linear' and p['crossovers_hz'] else 0
    return fir+4*(int(round(p['lookahead_ms']*sr/1000))//2)


def limit_band(x, sr, ceiling_db, release_ms, lookahead_ms, stereo_link=True):
    """Return (limited audio, gain array); gain guarantees sample ceiling."""
    if not len(x):
        return x.copy(), np.ones_like(x)
    peak = D.detector(x, sr, 'peak', stereo_link=stereo_link)
    ceiling = np.nextafter(10**(ceiling_db/20), 0.)
    required = np.minimum(1., ceiling/np.maximum(peak, np.finfo(float).tiny))
    # D.envelope with a zero attack coefficient is expressed through the
    # shared original smoother, avoiding an epsilon attack approximation.
    attenuation = 1-required
    held = np.column_stack([D.smooth_python(c, 0., D.coef(release_ms, sr)) for c in attenuation.T])
    radius = int(round(lookahead_ms*sr/1000))//2
    control = ndimage.minimum_filter1d(1-held, size=2*radius+1, axis=0, mode='constant', cval=1.)
    w = np.hanning(2*radius+3)[1:-1]
    w /= np.sum(w)
    gain = ndimage.convolve1d(control, w, axis=0, mode='constant', cval=1.)
    # Guard floating summation at equality, without changing the audio shape.
    gain = np.minimum(gain, required)
    return x*gain, gain


def mb_limiter(x, sr, p, *, seed=0, compensate=True):
    from mankomix.core.measure.loudness import true_peak_dbtp
    C.validate_mb(p, sr)
    bp = C.expand_band_params(p, {'threshold_db': -3, 'release_ms': 100})
    bands, info = C.split_mb(x, sr, p)
    peaks = []
    for i, band in enumerate(bands):
        bands[i], _ = limit_band(band, sr, bp['threshold_db'][i], bp['release_ms'][i], p['lookahead_ms'], p['stereo_link'])
        v = float(np.max(np.abs(bands[i]))) if len(x) else 0.
        peaks.append(20*float(np.log10(v)) if v else None)
    y, _ = limit_band(C.recombine_bands(bands), sr, p['out_ceiling_db'], max(bp['release_ms']), p['lookahead_ms'], p['stereo_link'])
    delay = latency_samples(sr, p)
    tp = true_peak_dbtp(y, sr)
    stats = dict(info, latency_samples=delay, latency_compensated=compensate,
                 band_sample_peaks_dbfs=peaks, true_peak_dbtp=float(tp) if np.isfinite(tp) else None,
                 true_peak_guaranteed=False)
    return (y if compensate else D.delay_audio(y, delay)), sr, stats


IMPLS = {'mb_limiter': mb_limiter}


def _validate(p):
    C.validate_mb(p)
    C.expand_band_params(p, {'threshold_db': -3, 'release_ms': 100})


CROSS_VALIDATE = {'mb_limiter': _validate}
