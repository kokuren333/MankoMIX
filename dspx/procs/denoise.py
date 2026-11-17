"""T10-01 offline stationary-noise suppression with RP accounting.

Automatic mode conservatively protects tonal/nonstationary material. Pink
noise itself is indistinguishable from unwanted noise and is deliberately
excluded from the automatic RP4 harmlessness claim (spec/10 exception).
"""
import numpy as np
from scipy import fft
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e, _b


def validate(p):
    if p['lo_hz'] >= p['hi_hz']:
        raise ParamError('denoise: lo_hz must be below hi_hz')
    if (p['start_s'] or p['end_s']) and p['end_s'] <= p['start_s']:
        raise ParamError('denoise: end_s must exceed start_s')
    if p['profile'] == 'region' and p['profile_end_s']-p['profile_start_s'] < .2-1e-12:
        raise ParamError('denoise: region profile needs at least 0.2 s')


def latency_samples(sr, p):
    from mankomix.dspx.bb.stft import window_samples
    return window_samples(p['window'], sr)


def _account(x, y, sr):
    """RP records of actual changed spans, total/band residual and meters."""
    from mankomix.dspx.procs.dehum import _measure
    residual = x-y
    changed = np.any(residual != 0, axis=1)
    edges = np.diff(np.r_[False, changed, False].astype(int))
    events = []
    for left, right in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        strength = float(np.mean(residual[left:right]**2))
        events.append(dict(start_s=float(left/sr), duration_s=float((right-left)/sr),
                           strength_dbfs=float(10*np.log10(strength)) if strength else None))
    total = float(np.sum(x*x))
    removed = float(np.sum(residual*residual))
    bands = []
    if len(x):
        fx = fft.rfft(x, axis=0, workers=1)
        fr = fft.rfft(residual, axis=0, workers=1)
        freqs = fft.rfftfreq(len(x), 1/sr)
        for lo, hi in ((0, 120), (120, 500), (500, 2000), (2000, 8000), (8000, sr/2+1)):
            if lo >= sr/2:
                continue
            use = (freqs >= lo) & (freqs < hi)
            den, num = float(np.sum(abs(fx[use])**2)), float(np.sum(abs(fr[use])**2))
            bands.append(dict(lo_hz=lo, hi_hz=min(hi, sr/2),
                              removed_energy_rel_db=float(10*np.log10(num/den)) if num and den else None))
    top = sorted(events, key=lambda e: (-(e['strength_dbfs'] if e['strength_dbfs'] is not None
                                        else -np.inf), e['start_s']))[:2000]
    empty_meter = dict(lufs_i=None, sample_peak_dbfs=None, true_peak_dbtp=None)
    return dict(event_count=len(events), events=sorted(top, key=lambda e: e['start_s']),
                removed_energy_rel_db=float(10*np.log10(removed/total)) if removed and total else None,
                removed_energy_bands=bands, before=_measure(x, sr) if len(x) else empty_meter.copy(),
                after=_measure(y, sr) if len(y) else empty_meter.copy())


def denoise(x, sr, p, *, seed=0, compensate=True):
    from mankomix.dspx.bb import stft, noise
    from mankomix.dspx.procs.dehum import _region
    validate(p)
    left, right = _region(len(x), sr, p)
    n = latency_samples(sr, p)
    y = x.copy()
    extra = dict(profile_source=p['profile'], noise_floor_third_oct=[],
                 latency_samples=n, latency_compensated=True)
    if p['amount'] and p['reduction_db'] and right > left and np.any(x):
        a = stft.analyze(x, sr, window=n)
        power = abs(a.spectra)**2
        if p['profile'] == 'region':
            profile = noise.region_profile(a, p['profile_start_s'], p['profile_end_s'])
            floor = profile.mean_power
            extra['profile_frame_count'] = profile.frame_count
            extra['profile_variance_mean'] = float(np.mean(profile.variance_power))
        else:
            floor = noise.minimum_statistics(power, sr, a.hop_samples)
        gains = noise.suppression_gains(power, floor, sr, a.hop_samples, a.frequencies_hz,
                    method=p['method'], reduction_db=p['reduction_db'], sensitivity=p['sensitivity'],
                    time_smooth_ms=p['time_smooth_ms'], freq_smooth_oct=p['freq_smooth_oct'],
                    transient_protect=p['transient_protect'])
        if p['profile'] == 'auto':
            confidence = noise.auto_confidence(power, floor, sr, a.hop_samples)
            gains = 1+(gains-1)*confidence
        else:
            protect = noise.tonal_weights(power, floor*10**(p['sensitivity']/10), sr, a.hop_samples)
            gains = gains+(1-gains)*protect
        band = stft.band_weights(a.frequencies_hz, p['lo_hz'], p['hi_hz'])
        gains = 1+(gains-1)*band[None, :, None]
        # Delta synthesis avoids rounding changes when a frame is untouched.
        correction = stft.synthesize(a, a.spectra*(gains-1))
        blend = np.full(right-left, p['amount'])
        ramp = min(round(.01*sr), (right-left)//2)
        if ramp:
            if left:
                blend[:ramp] *= np.linspace(0, 1, ramp)
            if right < len(x):
                blend[-ramp:] *= np.linspace(1, 0, ramp)
        y[left:right] += correction[left:right]*blend[:, None]
        extra['noise_floor_third_oct'] = noise.floor_bands(floor, a)
        extra['gain_min'] = float(np.min(gains))
        extra['gain_max'] = float(np.max(gains))
    stats = {**_account(x, y, sr), **extra}
    output = x-y if p['delta'] and p['amount'] else y
    if not compensate:
        output = stft.delay_output(output, n)
        stats['latency_compensated'] = False
    return output, sr, stats


SPECS = [dict(type='denoise', implemented=True,
    description='Conservative offline spectral stationary-noise suppression.',
    stages=['track', 'bus'], master_slot=None, offline_only=True, backends=['reference'],
    realtime=dict(block_ok=False, latency_samples='window_scaled', allocates=True),
    params=[
        _f('amount', None, 0, 1, 1, 'Removal fraction; zero bypasses before analysis.'),
        _b('delta', False, 'Audition the removed signal.'),
        _f('start_s', 's', 0, 36000, 0, 'Processing start; both zero means full clip.'),
        _f('end_s', 's', 0, 36000, 0, 'Processing end.'),
        _e('profile', ['region', 'auto'], 'auto', 'Noise profile source.'),
        _f('profile_start_s', 's', 0, 36000, 0, 'Noise-only profile start.'),
        _f('profile_end_s', 's', 0, 36000, 0, 'Noise-only profile end, at least 0.2 s later.'),
        _f('reduction_db', 'dB', 0, 40, 12, 'Maximum per-bin attenuation.'),
        _f('sensitivity', 'dB', -12, 12, 0, 'Noise power margin.'),
        _e('method', ['wiener', 'log_mmse', 'subtract'], 'log_mmse', 'Suppression estimator.'),
        _f('time_smooth_ms', 'ms', 0, 500, 80, 'Causal dB-gain smoothing tau.'),
        _f('freq_smooth_oct', 'oct', 0, 1, .1, 'Gain smoothing width.'),
        _f('transient_protect', None, 0, 1, .5, 'Broadband attack opening.'),
        _e('window', [1024, 2048, 4096], 2048, '48 kHz analysis size.'),
        _f('lo_hz', 'Hz', 20, 20000, 20, 'Lower effect edge.'),
        _f('hi_hz', 'Hz', 20, 24000, 20000, 'Upper effect edge.')])]
IMPLS = {'denoise': denoise}
CROSS_VALIDATE = {'denoise': validate}
