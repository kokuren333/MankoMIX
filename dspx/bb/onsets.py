"""BB-22 offline log-spectral/complex flux and refined onset positions.

onset_features(x,sr,kind='percussive') -> OnsetFeatures on a fixed grid.
detect_onsets(x,sr,kind='percussive',band='full',threshold=.3,
min_interval_ms=30) -> chronological JSON-safe event dictionaries. Stable
IDs are o_<sample>. Ratios use power in <200, 200..2500, >=2500 Hz.
No project mutation, warning or quality verdict is performed.
"""
from dataclasses import dataclass
import numpy as np
from scipy import ndimage, signal
from mankomix.dsp.errors import ParamError
from .stft import analyze


@dataclass(frozen=True)
class OnsetFeatures:
    samples: np.ndarray
    flux: dict
    power: np.ndarray
    hop_samples: int
    window_samples: int


def onset_features(x, sr, *, kind='percussive'):
    if kind not in ('percussive', 'soft'):
        raise ParamError('kind must be percussive or soft')
    size = max(16, int(round(1024*sr/48000)))
    hop = max(1, int(round(256*sr/48000)))
    st = analyze(x, sr, window=size, hop=hop)
    mag = np.sqrt(np.mean(np.abs(st.spectra)**2, axis=2))
    log = np.log1p(100*mag/size)
    diff = np.maximum(0, np.diff(log, axis=0, prepend=log[:1]))
    if kind == 'soft' and len(log) >= 3:
        phase = np.angle(st.spectra)
        predicted = 2*phase[1:-1]-phase[:-2]
        deviation = np.abs(np.exp(1j*phase[2:])-np.exp(1j*predicted))
        complex_flux = np.mean(deviation, axis=2)*log[2:]
        diff[2:] += .5*complex_flux
    masks = {'low': st.frequencies_hz < 200,
             'mid': (st.frequencies_hz >= 200) & (st.frequencies_hz < 2500),
             'high': st.frequencies_hz >= 2500,
             'full': np.ones(len(st.frequencies_hz), dtype=bool)}
    flux = {k: np.sum(diff[:, mask], axis=1) for k, mask in masks.items()}
    power = np.column_stack([np.sum(mag[:, masks[k]]**2, axis=1) for k in ('low', 'mid', 'high')])
    return OnsetFeatures(st.samples, flux, power, hop, size)


def detect_onsets(x, sr, *, kind='percussive', band='full', threshold=.3, min_interval_ms=30):
    if band not in ('full', 'low', 'mid', 'high') or not 0 <= threshold <= 1 or not 5 <= min_interval_ms <= 500:
        raise ParamError('invalid onset band, threshold or interval')
    a = np.asarray(x, dtype=np.float64)
    a = a[:, None] if a.ndim == 1 else a
    features = onset_features(a, sr, kind=kind)
    flux = features.flux[band]
    if len(flux) < 3 or not np.any(flux):
        return []
    width = max(3, int(round(.15*sr/features.hop_samples)) | 1)
    med = ndimage.median_filter(flux, size=width, mode='nearest')
    mean = ndimage.uniform_filter1d(flux, size=width, mode='nearest')
    floor = med+(0.3+threshold*1.5)*mean
    peaks, _ = signal.find_peaks(flux, height=floor+np.max(flux)*.005,
                                distance=max(1, int(round(min_interval_ms*sr/1000/features.hop_samples))))
    # Sub-millisecond RMS envelope avoids choosing carrier zero crossings.
    smooth = max(1, int(round(.00075*sr)))
    env = np.sqrt(np.maximum(0, ndimage.uniform_filter1d(np.mean(a*a, axis=1), smooth, mode='nearest')))
    slope = ndimage.uniform_filter1d(np.gradient(env), max(1, round(.0005*sr)), mode='nearest')
    events = []
    for k in peaks:
        center = int(features.samples[k])
        lo = max(0, center-features.window_samples)
        hi = min(len(a), center+features.hop_samples)
        if hi <= lo:
            continue
        j = lo+int(np.argmax(slope[lo:hi]))
        base = float(np.percentile(env[max(0, j-round(.025*sr)):max(1, j-round(.003*sr))], 20))
        top = float(np.max(env[j:min(len(a), j+round(.015*sr)+1)]))
        rise = float(slope[j])
        pre = env[max(0, j-round(.015*sr)):max(1, j-round(.003*sr))]
        post = env[j:min(len(a), j+round(.012*sr)+1)]
        if len(pre) and np.mean(post**2) <= 1.5*np.mean(pre**2):
            continue
        # Reject steady carriers/noise and fades slower than 30 ms. Local
        # contrast is relative, so three velocity levels share a threshold.
        if rise <= 0 or top <= max(1e-9, base*1.8) or rise*sr/max(top-base, 1e-20) < 35:
            continue
        sample = int(np.clip(round(j-(env[j]-base)/rise), lo, j))
        if sample < smooth and env[0] > top*.3:
            continue
        if events and sample-events[-1]['sample'] < round(min_interval_ms*sr/1000):
            continue
        energy = features.power[k]
        ratios = energy/max(float(energy.sum()), 1e-30)
        peak = float(np.max(np.abs(a[sample:min(len(a), sample+round(.03*sr)+1)])))
        events.append({'id': f'o_{sample}', 'sample': sample, 'time_s': sample/sr,
                       'strength': float(np.clip(flux[k]/np.max(flux), 0, 1)),
                       'peak_dbfs': float(20*np.log10(peak)) if peak else None,
                       'band_ratios': dict(zip(('low', 'mid', 'high'), map(float, ratios))),
                       'confidence': float(np.clip((flux[k]-floor[k])/max(flux[k], 1e-30), 0, 1))})
    return events
