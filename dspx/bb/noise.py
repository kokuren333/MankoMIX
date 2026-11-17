"""BB-20 noise profiles, minimum statistics and decision-directed suppression.

API: region_profile -> NoiseProfile(mean_power, variance_power, frame_count);
minimum_statistics -> time/bin/ch noise power; suppression_gains -> gains;
transient_weights -> time/ch opening weights; floor_bands -> 1/3-oct records.
tonal_weights protects persistent peaks; auto_confidence is the conservative
automatic-mode broadband/stationarity gate.
All power uses the unnormalized BB-06 rFFT convention. Phase is untouched.

Formula references: Ephraim & Malah (1985) log-spectral estimator,
Martin (2001) minimum statistics, Boll (1979) power subtraction.
This is an independently written fixed-smoothing minimum-statistics variant,
not a reproduction of Martin's optimal-smoothing/bias tables. The bias model
and conservative automatic confidence gate are documented in the unit report.
SciPy public special/ndimage/signal APIs only; no external code is copied.
"""
from dataclasses import dataclass
import numpy as np
from scipy import ndimage, special, signal
from mankomix.dsp.errors import ParamError


@dataclass(frozen=True)
class NoiseProfile:
    mean_power: np.ndarray
    variance_power: np.ndarray
    frame_count: int


def region_profile(analysis, start_s, end_s):
    """Average and population variance of fully contained profile frames.

    Profile intervals must be >= 0.2 s and lie entirely in the supplied clip.
    Excluding boundary windows prevents signal leakage from adjacent content.
    """
    a = analysis
    if start_s < 0 or end_s-start_s < .2-1e-12 or end_s > a.frames/a.sr+1e-12:
        raise ParamError('noise profile needs an in-bounds interval >= 0.2 s')
    left, right = round(start_s*a.sr), round(end_s*a.sr)
    use = (a.samples-len(a.window)//2 >= left) & (a.samples+(len(a.window)+1)//2 <= right)
    if not np.any(use):
        raise ParamError('noise profile interval contains no complete analysis window')
    power = abs(a.spectra[use])**2
    return NoiseProfile(np.mean(power, axis=0), np.var(power, axis=0), int(np.sum(use)))


def minimum_statistics(power, sr, hop, *, history_s=1.5, smooth_ms=80):
    """Past-only 1.5 s minimum of recursively smoothed periodograms.

    Bias is the reciprocal lower gamma quantile for an effective number of
    independent minima. Shape accounts for overlap using 2.5-hop correlation;
    this is an explicit approximation, verified on stationary Gaussian noise.
    """
    p = np.asarray(power, dtype=np.float64)
    if p.ndim != 3 or np.any(p < 0) or not np.isfinite(p).all() or sr <= 0 or hop <= 0 or history_s <= 0 or smooth_ms <= 0:
        raise ParamError('invalid minimum-statistics input')
    if not len(p):
        return p.copy()
    dt = hop/sr
    alpha = np.exp(-dt/(smooth_ms*.001))
    sm, _ = signal.lfilter([1-alpha], [1, -alpha], p, axis=0, zi=alpha*p[:1])
    count = max(1, round(history_s/dt))
    past = ndimage.minimum_filter1d(sm, count, axis=0, origin=(count-1)//2, mode='nearest')
    shape = max(1., (1+alpha)/(1-alpha)/2.5)
    independent = max(1., history_s/(2*smooth_ms*.001))
    probability = 1/(independent+1)
    bias = shape/max(float(special.gammaincinv(shape, probability)), 1e-12)
    return past*bias


def transient_weights(power, sr, hop):
    """Broadband energy rise opening, dilated to cover WOLA attack context."""
    p = np.asarray(power, dtype=np.float64)
    if not len(p):
        return np.empty((0, p.shape[-1]))
    energy = np.sum(p, axis=1)
    before = ndimage.minimum_filter1d(energy, max(3, round(.04*sr/hop)), axis=0,
                                     origin=(max(3, round(.04*sr/hop))-1)//2, mode='nearest')
    rise = 10*np.log10((energy+1e-30)/(before+1e-30))
    opening = np.clip((rise-3)/6, 0, 1)
    return ndimage.maximum_filter1d(opening, 5, axis=0, mode='nearest')


def suppression_gains(power, noise_power, sr, hop, frequencies_hz, *, method='log_mmse',
                      reduction_db=12, sensitivity=0, time_smooth_ms=80,
                      freq_smooth_oct=.1, transient_protect=.5, decision_alpha=.98):
    """Decision-directed prior SNR and Wiener/log-MMSE/power-subtraction gain.

    xi[t] = alpha*previous_clean_power/noise[t] + (1-alpha)*max(gamma-1,0).
    log-MMSE gain = xi/(1+xi)*exp(E1(gamma*xi/(1+xi))/2).
    Power subtraction uses a fixed oversubtraction factor of two to avoid
    isolated surviving noise peaks (the factor is independent of sensitivity).
    Gains are limited to [10**(-reduction_db/20),1] before/after smoothing.
    Attack opening follows smoothing so an onset need not wait one time tau.
    """
    from mankomix.dspx.bb.stft import smooth_gains
    p = np.asarray(power, dtype=np.float64)
    try:
        noise = np.broadcast_to(np.asarray(noise_power, dtype=np.float64), p.shape)*10**(sensitivity/10)
    except ValueError as exc:
        raise ParamError('noise power shape does not match power') from exc
    if (p.ndim != 3 or np.any(p < 0) or np.any(noise < 0) or not np.isfinite(p).all()
            or not np.isfinite(noise).all() or method not in ('wiener', 'log_mmse', 'subtract')
            or not 0 <= decision_alpha < 1 or not 0 <= transient_protect <= 1 or reduction_db < 0):
        raise ParamError('invalid suppression input')
    floor = 10**(-reduction_db/20)
    gains = np.ones_like(p)
    previous = np.zeros(p.shape[1:])
    for t in range(len(p)):
        den = np.maximum(noise[t], 1e-30)
        gamma = np.minimum(p[t]/den, 1e30)
        xi = decision_alpha*previous/den+(1-decision_alpha)*np.maximum(gamma-1, 0)
        wiener = xi/(1+xi)
        if method == 'wiener':
            g = wiener
        elif method == 'subtract':
            g = np.sqrt(np.maximum(1-2/np.maximum(gamma, 1e-30), 0))
        else:
            v = np.maximum(gamma*wiener, 1e-30)
            g = wiener*np.exp(np.minimum(.5*special.exp1(v), 50))
        gains[t] = np.clip(g, floor, 1)
        previous = gains[t]**2*p[t]
    gains = smooth_gains(gains, sr, hop, frequencies_hz,
                         time_ms=time_smooth_ms, freq_oct=freq_smooth_oct)
    opening = np.minimum(1., 2*transient_protect*transient_weights(p, sr, hop))
    return np.clip(gains+(1-gains)*opening[:, None, :], floor, 1)


def auto_confidence(power, noise_power, sr, hop):
    """Conservative automatic removal: stationary broadband content only.

    A noise-only region remains the explicit way to suppress a known floor
    under tonal material. Automatic mode cannot identify semantic 'noise'.
    """
    p = np.asarray(power)
    if not len(p):
        return np.empty((0, 1, p.shape[-1]))
    flatness = np.exp(np.mean(np.log(p[:, 1:]+1e-30), axis=1))/(np.mean(p[:, 1:], axis=1)+1e-30)
    broadband = np.clip((flatness-.15)/.2, 0, 1)
    energy = np.sum(p, axis=1)
    floor = np.sum(noise_power, axis=1)
    stationary = np.clip((floor/(energy+1e-30)-.1)/.4, 0, 1)
    confidence = broadband*stationary
    confidence[:int(np.ceil(1.5*sr/hop))] = 0
    return confidence[:, None, :]


def tonal_weights(power, noise_power, sr, hop):
    """Offline persistent local spectral peaks above a known noise template.

    A 320 ms mean must exceed three times the template, be a five-bin local
    maximum and exceed its local mean by 20%. At least 60% of the nearby
    periodograms must also exceed three times the template. Protect its
    three-bin main region. Persistence rejects random periodogram peaks,
    while opening after
    gain smoothing prevents that smoothing from eroding persistent partials.
    """
    p = np.asarray(power, dtype=np.float64)
    if not len(p):
        return np.zeros_like(p)
    size = max(1, round(.32*sr/hop))
    sm = ndimage.uniform_filter1d(p, size, axis=0, mode='nearest')
    peak = ((sm >= ndimage.maximum_filter1d(sm, 5, axis=1, mode='nearest'))
            & (sm > 1.2*ndimage.uniform_filter1d(sm, 5, axis=1, mode='nearest'))
            & (sm > 3*np.asarray(noise_power)))
    weights = ndimage.maximum_filter1d(peak.astype(np.float64), 3, axis=1, mode='nearest')
    persistence = ndimage.uniform_filter1d((p > 3*np.asarray(noise_power)).astype(float),
                                          size, axis=0, mode='nearest')
    return weights*(ndimage.maximum_filter1d(persistence, 3, axis=1, mode='nearest') >= .6)


def floor_bands(noise_power, analysis):
    """1/3-octave integrated noise energy in dBFS, per channel.

    One-sided factors and N*sum(window**2) give Parseval mean-square units.
    Empty bins are omitted; exact zero is represented by None for JSON.
    """
    p = np.asarray(noise_power, dtype=np.float64)
    if p.ndim == 3:
        p = np.mean(p, axis=0) if len(p) else np.zeros(p.shape[1:])
    n = len(analysis.window)
    factor = np.full(len(analysis.frequencies_hz), 2.)
    factor[0] = 1
    if n % 2 == 0:
        factor[-1] = 1
    normalized = p*factor[:, None]/(n*np.sum(analysis.window**2))
    out = []
    for k in range(-18, 21):
        center = 1000*2**(k/3)
        use = (analysis.frequencies_hz >= center*2**(-1/6)) & (analysis.frequencies_hz < center*2**(1/6))
        if np.any(use):
            e = np.sum(normalized[use], axis=0)
            out.append(dict(center_hz=float(center), power_dbfs=[float(10*np.log10(v)) if v else None for v in e]))
    return out
