"""T10-09: experimental offline late-reverberation attenuation, RP records."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _i, _e, _b


def validate(p):
    if 0 < p['rt60_s'] < .1:
        raise ParamError('dereverb: rt60_s must be zero or at least 0.1 s')
    if (p['start_s'] or p['end_s']) and p['end_s'] <= p['start_s']:
        raise ParamError('dereverb: end_s must exceed start_s')


def latency_samples(sr, p):
    from mankomix.dspx.bb.stft import window_samples
    return window_samples(p['window'], sr)


def dereverb(x, sr, p, *, seed=0, compensate=True):
    from mankomix.dspx.bb import stft, noise, dereverberation as D
    from mankomix.dspx.procs.dehum import _region
    from mankomix.dspx.procs.denoise import _account
    validate(p)
    left, right = _region(len(x), sr, p)
    n = latency_samples(sr, p)
    y = x.copy()
    extra = dict(method=p['method'], rt60_s=None, rt60_source='not_estimated',
                 decay_regions=[], latency_samples=n, latency_compensated=compensate)
    if p['amount'] and p['reduction_db'] and right > left and np.any(x):
        rt, regions = D.estimate_rt60(x, sr) if p['rt60_s'] == 0 else (p['rt60_s'], [])
        extra.update(rt60_s=rt, rt60_source='automatic' if p['rt60_s'] == 0 else 'parameter',
                     decay_regions=regions)
        a = stft.analyze(x, sr, window=n)
        if p['method'] == 'wpe':
            wet, info = D.wpe(a.spectra, p['wpe_taps'], p['wpe_delay'], p['wpe_iter'])
            extra.update(info)
            # Limit the complex removal vector; do not replace WPE with a mask.
            removed = a.spectra-wet
            limit = (1-10**(-p['reduction_db']/20))*abs(a.spectra)
            removed *= np.minimum(1., limit/np.maximum(abs(removed), 1e-30))
            correction = stft.synthesize(a, -removed)
        elif rt is not None:
            late = D.late_power(a, rt, p['early_ms'], p['band_tilt'])
            gains = noise.suppression_gains(abs(a.spectra)**2, late, sr, a.hop_samples,
                a.frequencies_hz, method='wiener', reduction_db=p['reduction_db'],
                time_smooth_ms=p['time_smooth_ms'], freq_smooth_oct=.1,
                transient_protect=1, decision_alpha=.98)
            gains[late == 0] = 1
            correction = stft.synthesize(a, a.spectra*(gains-1))
            extra.update(gain_min=float(gains.min()), gain_max=float(gains.max()))
        else:
            correction = np.zeros_like(x)
        correction *= D.early_envelope(x, sr, p['early_ms'])[:, None]
        blend = np.full(right-left, p['amount'])
        ramp = min(round(.01*sr), (right-left)//2)
        if ramp:
            if left:
                blend[:ramp] *= np.linspace(0, 1, ramp)
            if right < len(x):
                blend[-ramp:] *= np.linspace(1, 0, ramp)
        y[left:right] += correction[left:right]*blend[:, None]
    stats = {**_account(x, y, sr), **extra}
    out = x-y if p['delta'] and p['amount'] else y
    if not compensate:
        out = stft.delay_output(out, n)
    return out, sr, stats


SPECS = [dict(type='dereverb', implemented=False,
    description='Experimental offline delayed-power or weighted-prediction dereverberation.',
    stages=['track'], master_slot=None, offline_only=True, backends=['reference'],
    realtime=dict(block_ok=False, latency_samples='window_scaled', allocates=True),
    params=[
        _f('amount', None, 0, 1, .5, 'Removal fraction; zero bypasses.'),
        _b('delta', False, 'Audition removed signal.'),
        _f('start_s', 's', 0, 36000, 0, 'Start; both zero selects full clip.'),
        _f('end_s', 's', 0, 36000, 0, 'End of processing region.'),
        _e('method', ['spectral', 'wpe'], 'spectral', 'Late-reverberation model.'),
        _f('rt60_s', 's', 0, 10, 0, 'Zero estimates automatically; otherwise at least 0.1 s.'),
        _f('reduction_db', 'dB', 0, 30, 9, 'Maximum spectral attenuation/removal radius.'),
        _f('early_ms', 'ms', 10, 150, 50, 'Protected early interval.'),
        _f('time_smooth_ms', 'ms', 0, 300, 60, 'Spectral gain smoothing tau.'),
        _f('band_tilt', 'dB/oct', -3, 3, 0, 'Positive values shorten high-band RT.'),
        _i('wpe_taps', None, 4, 40, 12, 'Delayed prediction taps per channel.'),
        _i('wpe_delay', 'frames', 1, 6, 3, 'First prediction lag.'),
        _i('wpe_iter', None, 1, 5, 3, 'Fixed variance updates.'),
        _e('window', [1024, 2048], 1024, '48 kHz analysis window.')])]
IMPLS = {'dereverb': dereverb}
CROSS_VALIDATE = {'dereverb': validate}
