"""Shared T02-03/04 control nucleus, using BB-06 and BB-03 unchanged.

API: common_params, validate_band, latency_samples, frame_smooth,
spectral_envelope, widen_notches, bin_levels, finish.
Envelope candidates are log-axis power box mean, cepstral low-pass, and iterative
true envelope (Roebel & Rodet, DAFx-05, iterative ceiling/lifter principle).
The study cutoff, iteration cap and stop tolerance below are local choices;
the paper's optimized implementation is not reproduced. The processor selects
the log-axis mean specified in T02-03; candidates remain callable for study.
"""
import numpy as np
from scipy import fft
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e, _b


def common_params(lo=20, hi=20000):
    return [_e('window', [1024, 2048, 4096], 2048, '48 kHz analysis size.'),
            _f('lo_hz', 'Hz', 20, 20000, lo, 'Lower effect edge.'),
            _f('hi_hz', 'Hz', 20, 24000, hi, 'Upper effect edge.'),
            _f('mix', None, 0, 1, 1, 'Processed fraction.'),
            _b('delta', False, 'Output the removed signal.'),
            _b('stereo_link', True, 'Use the same gain for all channels.')]


def validate_band(p):
    if p['lo_hz'] >= p['hi_hz']:
        raise ParamError('lo_hz must be below hi_hz')


def latency_samples(sr, p):
    from .stft import window_samples
    return window_samples(p['window'], sr)


def frame_smooth(target_db, sr, hop, attack_ms, release_ms):
    """BB-03 signed dB smoother at the frame rate, zero initial state.

    Zero attack uses exp(-infinity)=0 via a numerically exact tiny tau.
    The final dimensions are independent bins/channels, flattened for BB-03.
    """
    from .dynamics import smooth_gain
    t = np.asarray(target_db, dtype=np.float64)
    if not len(t):
        return t.copy()
    return smooth_gain(t.reshape(len(t), -1), sr/hop,
                       max(attack_ms, 1e-12), max(release_ms, 1e-12)).reshape(t.shape)


def spectral_envelope(power, frequencies_hz, width_oct, *, method='log_mean'):
    """Return dB envelope. Alternatives are study-only, never auto-selected."""
    from .stft import smooth_frequency
    db = 10*np.log10(np.maximum(power, 1e-30))
    if method == 'log_mean':
        # Smooth power on a log-frequency neighborhood, then convert to dB.
        # Averaging dB instead biases stochastic power downward by ~2.5 dB.
        return 10*np.log10(np.maximum(smooth_frequency(power, frequencies_hz, width_oct), 1e-30))
    n = 2*(len(frequencies_hz)-1)
    positive = frequencies_hz[frequencies_hz > 0]
    pivot = np.median(positive)
    cutoff = max(1, min(n//2, round(n*(frequencies_hz[1]-frequencies_hz[0])/(pivot*width_oct))))
    def lifter(v):
        cep = fft.irfft(v, n=n, axis=1, workers=1)
        cep[:, cutoff+1:n-cutoff] = 0
        return fft.rfft(cep, axis=1, workers=1).real
    env = lifter(db)
    if method == 'cepstral':
        return env
    if method != 'true_envelope':
        raise ParamError('unknown envelope study method')
    for _ in range(32):
        env = lifter(np.maximum(db, env))
        if np.max(db-env, initial=0) < .1:
            break
    return env


def widen_notches(demand_db, frequencies_hz, width_oct):
    """Log-frequency maximum followed by BB-06 equal-width box average."""
    from .stft import smooth_frequency
    f = np.asarray(frequencies_hz)
    lo = np.searchsorted(f, f*2**(-width_oct/2), side='left')
    hi = np.maximum(lo+1, np.searchsorted(f, f*2**(width_oct/2), side='right'))
    wide = np.empty_like(demand_db)
    for k, (left, right) in enumerate(zip(lo, hi)):
        wide[:, k] = np.max(demand_db[:, left:right], axis=1)
    return smooth_frequency(wide, f, width_oct)


def bin_levels(analysis, smooth_oct=0):
    """Coherent peak dBFS (full-scale bin-centred sine=0); optional power mean.

    Frequency smoothing is calibrated against the sqrt-Hann lobe, so it
    does not silently move the threshold for a bin-centred isolated sine.
    DC/Nyquist use a one-sided amplitude factor of one.
    """
    from .stft import smooth_frequency
    a = analysis
    p = abs(a.spectra)**2
    n = len(a.window)
    factor = np.full(len(a.frequencies_hz), 2./np.sum(a.window))
    factor[[0, -1]] *= .5
    if smooth_oct:
        f = a.frequencies_hz
        lo = np.searchsorted(f, f*2**(-smooth_oct/2), side='left')
        hi = np.maximum(lo+1, np.searchsorted(f, f*2**(smooth_oct/2), side='right'))
        lobe = abs(fft.fft(a.window, workers=1))**2/np.sum(a.window)**2
        calibration = np.array([np.mean(lobe[(np.arange(left, right)-k) % n])
                                for k, (left, right) in enumerate(zip(lo, hi))])
        p = smooth_frequency(p, f, smooth_oct)/calibration[None, :, None]
    return 10*np.log10(np.maximum(p*factor[None, :, None]**2, 1e-30))


def finish(x, sr, p, analysis, gain_db, *, compensate=True):
    """Apply tapered real gains with WOLA; exact bypass and delta accounting."""
    from . import stft
    n = latency_samples(sr, p)
    stats = dict(latency_samples=n, latency_compensated=bool(compensate),
                 gain_min_db=0., gain_max_db=0., max_frame_delta_db=0.)
    y = x.copy()
    if analysis is not None and gain_db.size:
        weights = stft.band_weights(analysis.frequencies_hz, p['lo_hz'], p['hi_hz'])
        db = gain_db*weights[None, :, None]
        gains = 10**(db/20)
        y += p['mix']*stft.synthesize(analysis, analysis.spectra*(gains-1))
        stats.update(gain_min_db=float(np.min(db)), gain_max_db=float(np.max(db)),
                     max_frame_delta_db=float(np.max(abs(np.diff(db, axis=0)), initial=0)))
    out = x-y if p['delta'] else y
    return (out if compensate else stft.delay_output(out, n)), sr, stats
