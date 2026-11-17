"""Self-contained speed inference and inverse-time mapping for restoration.

estimate_speed(x, sr, p) -> (samples, fractional_speed, component_count).
Spectral peaks select isolated analytic bands, differentiated unwrapped
phase yields IF, and a consensus median extracts common relative motion.
inverse_positions(speed) -> same-length monotone inverse clock. Speed is
fractional (not percent); zero-mean displacement fixes the integration
constant. resample_inverse(x, speed) uses the existing BB-09 sinc256 reader
in bounded chunks. The caller decides whether a measured curve is reliable.

Independent implementation of spec T10-17; the 2007 JAES paper discusses
hum/bias tracking, not this median estimator. Filter widths, consensus and
thresholds are explicit engineering choices documented in the unit report.
"""
import numpy as np
from scipy import fft, signal
from mankomix.dsp.errors import ParamError


def _rate_band(values, rate, low, high):
    if len(values) < 4:
        return np.zeros_like(values)
    # Reflect context; cosine shoulders avoid a sharp spectral truncation.
    pad = len(values)
    source = np.pad(values, (pad, pad), mode='reflect')
    f = fft.rfftfreq(len(source), 1/rate)
    gain = np.clip((f-low*.5)/(low*.5), 0, 1)
    gain = .5-.5*np.cos(np.pi*gain)
    upper = np.clip((high*1.25-f)/(high*.25), 0, 1)
    gain *= .5-.5*np.cos(np.pi*upper)
    return fft.irfft(fft.rfft(source, workers=1)*gain, len(source), workers=1)[pad:pad+len(values)]


def estimate_speed(x, sr, p):
    n = len(x)
    analysis_rate = max(200., sr*.45*p['max_dev']*.01*4)
    hop = max(1, int(sr//analysis_rate))
    samples = np.unique(np.r_[np.arange(0, n, hop), max(0, n-1)]).astype(int)
    empty = (samples, np.zeros(len(samples)), 0)
    if n < max(32, sr//2) or not np.any(x):
        return empty
    mono = x[:, int(np.argmax(np.sum(x*x, axis=0)))]
    # Welch suppresses random narrow-bin maxima; one-quarter-second windows
    # retain separate harmonics while averaging note activity over the file.
    f, power = signal.welch(mono, sr, nperseg=min(n, max(32, sr//4)))
    if p['reference'] == 'pilot':
        centers = [p['pilot_hz']]
    else:
        peaks, _ = signal.find_peaks(power, distance=max(1, round(24/(f[1]-f[0]))))
        peaks = [k for k in peaks if 70 <= f[k] < sr*.45 and power[k] > np.max(power)*1e-4]
        peaks = sorted(peaks, key=lambda k: (-power[k], f[k]))
        centers = []
        for k in peaks:
            width = max(20., p['max_rate_hz']*1.5, f[k]*p['max_dev']*.02)
            background = power[(abs(f-f[k]) > width) & (abs(f-f[k]) < width*3)]
            if len(background) and power[k] < 30*max(np.median(background), 1e-300):
                continue
            if all(abs(f[k]-c) > 2*width for c in centers):
                centers.append(float(f[k]))
            if len(centers) == 24:
                break
    if not centers:
        return empty
    # Reflect to suppress analytic-band boundary discontinuities.
    pad = min(n-1, sr//2)
    padded = np.pad(mono, (pad, pad), mode='reflect')
    spectrum = fft.fft(padded, workers=1)
    frequencies = fft.fftfreq(len(padded), 1/sr)
    t = samples/sr
    tracks = []
    for center in centers:
        width = max(20., 2*p['max_rate_hz'], center*p['max_dev']*.02)
        distance = abs(frequencies-center)
        mask = np.clip((width*1.5-distance)/(width*.5), 0, 1)
        mask = .5-.5*np.cos(np.pi*mask)
        mask[frequencies <= 0] = 0
        z = fft.ifft(spectrum*mask, workers=1)[pad:pad+n]
        # Demodulate before decimation so high carriers cannot alias phase.
        baseband = z[samples]*np.exp(-2j*np.pi*center*t)
        phase = np.unwrap(np.angle(baseband))
        instantaneous = center+np.gradient(phase, t)/(2*np.pi)
        amplitude = abs(baseband)
        valid = amplitude > np.quantile(amplitude, .9)*.3
        edge = max(.12, 2/width)
        valid &= (t >= edge) & (t <= t[-1]-edge)
        if np.sum(valid) < 20:
            continue
        if p['reference'] == 'pilot':
            nominal = p['pilot_hz']
        else:
            # A single analysis band may cover neighboring notes at different
            # times. Cluster their stable IF plateaux before normalising; a
            # global median would place the nominal between two played notes.
            remaining = instantaneous[valid].copy()
            nominals = []
            span = center*p['max_dev']*.015
            while len(remaining) >= 20 and len(nominals) < 8:
                bins = np.arange(center-width*2, center+width*2+span/4, span/4)
                hist, edges = np.histogram(remaining, bins=bins)
                smoothed = np.convolve(hist, np.ones(5), 'same')
                k = int(np.argmax(smoothed))
                mode = (edges[k]+edges[k+1])/2
                group = abs(remaining-mode) <= span
                if np.sum(group) < 20:
                    break
                nominals.append(float(np.median(remaining[group])))
                remaining = remaining[~group]
            if not nominals:
                continue
            candidates = np.asarray(nominals)
            nominal = candidates[np.argmin(abs(instantaneous[:, None]-candidates), axis=1)]
        deviation = instantaneous/nominal-1
        valid &= abs(deviation) <= p['max_dev']*.015
        if np.sum(valid) < 20:
            continue
        # Fill only short gaps from this carrier; acceptance below still counts
        # observed components, not these interpolated missing observations.
        track = np.full(len(t), np.nan)
        track[valid] = deviation[valid]
        tracks.append(track)
    required = 1 if p['reference'] == 'pilot' else 3
    if len(tracks) < required:
        return empty
    tracks = np.array(tracks)
    valid = np.isfinite(tracks)
    # Avoid nanmedian warnings on unobserved cells.
    median = np.zeros(len(t))
    for k in range(len(t)):
        observed = tracks[valid[:, k], k]
        if len(observed) >= required:
            candidate = float(np.median(observed))
            tolerance = max(.0005, abs(candidate)*.3)
            if np.mean(abs(observed-candidate) <= tolerance) >= .7:
                median[k] = candidate
    usable = np.sum(valid, axis=0) >= required
    if np.sum(usable) < 20:
        return empty
    # Extrapolate observed interior values through analysis-only edge guards.
    first, last = np.flatnonzero(usable)[[0, -1]]
    median[:first] = median[first]
    median[last+1:] = median[last]
    rate = sr/hop
    filtered = _rate_band(median, rate, p['min_rate_hz'], p['max_rate_hz'])
    filtered = np.clip(filtered, -p['max_dev']*.01, p['max_dev']*.01)
    filtered -= np.mean(filtered)
    peak = np.max(abs(filtered), initial=0.)
    if peak > p['max_dev']*.01:
        filtered *= p['max_dev']*.01/peak
    if np.sqrt(np.mean(filtered**2))*100 <= .02:
        filtered[:] = 0
    return samples, filtered, len(tracks)


def inverse_positions(speed):
    v = np.asarray(speed, dtype=np.float64)
    if v.ndim != 1 or not np.isfinite(v).all() or np.any(abs(v) >= 1):
        raise ParamError('finite fractional speed below unity required')
    n = len(v)
    if n < 2:
        return np.arange(n, dtype=np.float64)
    velocity = 1+v
    velocity /= np.mean((velocity[:-1]+velocity[1:])/2)
    displacement = np.r_[0., np.cumsum((velocity[:-1]+velocity[1:])/2-1)]
    displacement -= np.mean(displacement)
    source = np.arange(n)+displacement
    positions = np.interp(np.arange(n), source, np.arange(n))
    left, right = np.arange(n) < source[0], np.arange(n) > source[-1]
    positions[left] = (np.arange(n)[left]-source[0])/velocity[0]
    positions[right] = n-1+(np.arange(n)[right]-source[-1])/velocity[-1]
    return positions


def resample_inverse(x, speed):
    from mankomix.dspx.bb.delayline import read_samples
    if len(speed) != len(x):
        raise ParamError('speed must have one value per input frame')
    if not np.any(speed):
        return x.copy()
    positions = inverse_positions(speed)
    out = np.empty_like(x)
    for start in range(0, len(x), 2048):
        out[start:start+2048] = read_samples(x, positions[start:start+2048], 'sinc256')
    return out
