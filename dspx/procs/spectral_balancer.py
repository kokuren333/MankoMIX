"""T02-06 coarse ERB excitation balance, relative to a 1/f reference.

An original single-input control rule, not a reproduction of the multitrack
algorithm of Hafezi & Reiss (JAES 63(5), 2015). P-02 spreading is reused:
search and validation using P-02 therefore share a measuring model. Scores
here omit P-02 mix matching/aggregation and are not independent evidence of
perceptual improvement. The 3 dB dead zone and 100 ms power averaging are
explicit conservative design choices, not constants from a publication.
"""
import numpy as np
from scipy import signal
from mankomix.dspx.params import _f, _e, _b


def validate(p):
    from mankomix.dspx.bb.spectral_control import validate_band
    validate_band(p)


def latency_samples(sr, p):
    from mankomix.dspx.bb.spectral_control import latency_samples as resolve
    return resolve(sr, p)


def control(analysis, p):
    """Return (bin gain dB, band gain dB, band centres), before edge taper.

    Negative SMR departure from a level-matched pink reference controls
    recover. Positive exported-excitation departure controls tame, so broad
    dominant regions do not cancel themselves in the self/external ratio.
    Loudness hold solves a clipped, tapered K-weighted power constraint for
    each frame before time smoothing. No full-band post gain is introduced.
    """
    from mankomix.dspx.bb import auditory as A, stft
    from mankomix.dspx.bb.spectral_control import frame_smooth
    from mankomix.core.measure.loudness import k_weighting_sos
    a = analysis
    power, edges, fc = A.band_powers(a)
    if p['stereo_link']:
        power = np.mean(power, axis=2, keepdims=True)
    alpha = np.exp(-a.hop_samples/(a.sr*.1))
    power = signal.lfilter([1-alpha], [1, -alpha], power, axis=0)
    pink = A.pink_reference(a, edges)
    base = pink[None, :, None] * (np.sum(power, axis=1, keepdims=True)/np.sum(pink))
    # Auditory routines use band as the final axis; processors keep channels last.
    def external(v, exported=False):
        return A.excitation(v.transpose(0, 2, 1), fc, spl_offset_db=96.,
                            exclude_self=True, exported=exported).transpose(0, 2, 1)
    smr = A.signal_to_mask_db(power, external(power))
    ref_smr = A.signal_to_mask_db(base, external(base))
    departure = smr-ref_smr
    export = 10*np.log10((external(power, True)+1e-30)/(external(base, True)+1e-30))
    band_db = p['recover']*np.maximum(-departure-3, 0)-p['tame']*np.maximum(export-3, 0)
    band_db += p['tilt_db_oct']*np.log2(fc[None, :, None]/1000)
    band_db = np.clip(band_db, -p['max_change_db'], p['max_change_db'])
    db = A.interpolate_gains(band_db, fc, a.frequencies_hz)
    if p['loudness_hold']:
        # This holds a BS.1770 spectral-energy proxy, not ISO sones.
        _, h = signal.sosfreqz(k_weighting_sos(a.sr), worN=a.frequencies_hz, fs=a.sr)
        pw = A.bin_powers(a)*abs(h[None, :, None])**2
        if p['stereo_link']:
            pw = np.sum(pw, axis=2, keepdims=True)
        taper = stft.band_weights(a.frequencies_hz, p['lo_hz'], p['hi_hz'])[None, :, None]
        original = np.sum(pw, axis=1, keepdims=True)
        low, high = np.full_like(original, -2*p['max_change_db']), np.full_like(original, 2*p['max_change_db'])
        for _ in range(32):
            mid = .5*(low+high)
            proposed = np.clip(db+mid, -p['max_change_db'], p['max_change_db'])
            energy = np.sum(pw*10**(proposed*taper/10), axis=1, keepdims=True)
            high = np.where(energy > original, mid, high)
            low = np.where(energy > original, low, mid)
        db = np.clip(db+.5*(low+high), -p['max_change_db'], p['max_change_db'])
    db = frame_smooth(db, a.sr, a.hop_samples, p['time_ms'], p['time_ms'])
    return db, band_db, fc


def spectral_balancer(x, sr, p, *, seed=0, compensate=True):
    from mankomix.dspx.bb import stft
    from mankomix.dspx.bb.spectral_control import finish
    validate(p)
    a, db = None, np.empty((0, 0, 1))
    active = p['recover'] or p['tame'] or p['tilt_db_oct']
    if active and p['max_change_db'] and p['mix'] and len(x) and np.any(x):
        a = stft.analyze(x, sr, window=latency_samples(sr, p))
        db, _, _ = control(a, p)
    return finish(x, sr, p, a, db, compensate=compensate)


SPECS = [dict(type='spectral_balancer', implemented=True,
    description='Conservative ERB excitation balance relative to pink noise.',
    stages=['track', 'bus', 'master'], master_slot=3, offline_only=False, backends=['reference'],
    realtime=dict(block_ok=False, latency_samples='window_scaled', allocates=True),
    params=[_e('window', [1024, 2048, 4096], 2048, '48 kHz analysis size.'),
        _f('lo_hz', 'Hz', 20, 20000, 20, 'Lower effect edge.'),
        _f('hi_hz', 'Hz', 20, 24000, 20000, 'Upper effect edge.'),
        _f('mix', None, 0, 1, 1, 'Processed fraction.'), _b('delta', False, 'Removed signal.'),
        _b('stereo_link', True, 'Common per-bin gain across channels.'),
        _f('recover', None, 0, 1, .3, 'Masked-band recovery strength.'),
        _f('tame', None, 0, 1, .3, 'Dominant-band attenuation strength.'),
        _f('tilt_db_oct', 'dB/oct', -3, 3, 0, 'Target balance tilt about 1 kHz.'),
        _f('max_change_db', 'dB', 0, 12, 6, 'Absolute gain ceiling.'),
        _f('time_ms', 'ms', 20, 2000, 150, 'Gain time constant.'),
        _b('loudness_hold', True, 'Hold frame K-weighted power before gain smoothing.')])]
IMPLS = {'spectral_balancer': spectral_balancer}
TIME_VARYING = set(IMPLS)
CROSS_VALIDATE = {'spectral_balancer': validate}
