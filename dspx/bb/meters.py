"""BB-25 read-only measurement timelines using existing verification meters.

measure(x,sr) returns unrounded integrated/sample/true peak, health and stereo.
timeline(x,sr,hop_ms=100,window_ms=400) returns fixed-start complete level windows;
sample/true peaks cover each hop interval so downsampling cannot hide peaks.
decimate(values,factor,peak=False) averages consecutive bins or preserves max.
stereo_bands delegates to existing Spectrum/band_stereo. spectrogram uses
BB-06 and returns raw window-energy-normalized one-sided bin power (not PSD).
Nonfinite silence measures remain IEEE values, just like the existing APIs.
Callers writing JSON can use core.measure.vector.json_safe.
"""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.core.measure import loudness as L
from mankomix.core.measure.vector import health
from mankomix.core.measure.bands import Spectrum, BANDS_P22
from mankomix.core.measure.stereo import band_stereo
from .stft import analyze


def stereo_bands(x, sr, bands=BANDS_P22):
    return band_stereo(Spectrum(x, sr), bands)


def measure(x, sr):
    return {'lufs_i': L.integrated(x, sr) if len(x) else -np.inf, 'sample_peak_dbfs': L.sample_peak_dbfs(x),
            'true_peak_dbtp': L.true_peak_dbtp(x, sr), 'health': health(x),
            'stereo': stereo_bands(x, sr)}


def decimate(values, factor, *, peak=False):
    v = np.asarray(values, dtype=np.float64)
    if not isinstance(factor, (int, np.integer)) or factor < 1 or v.ndim < 1:
        raise ParamError('positive integer decimation factor required')
    if not len(v):
        return v.copy()
    return np.stack([(np.max if peak else np.mean)(v[i:i+factor], axis=0) for i in range(0, len(v), factor)])


def timeline(x, sr, *, hop_ms=100, window_ms=400):
    if sr <= 0 or not np.isfinite([hop_ms, window_ms]).all() or min(hop_ms, window_ms) <= 0:
        raise ParamError('positive finite rate/window/hop required')
    a = L.as_frames(x)
    hop, window = max(1, round(hop_ms*sr/1000)), max(1, round(window_ms*sr/1000))
    starts = np.arange(0, len(a), hop, dtype=np.int64)
    # TP windows overlap by one hop on either side to retain boundary context.
    # Their explicit support is returned, so callers need not infer it.
    peaks = [L.sample_peak_dbfs(a[i:min(len(a), i+hop)]) for i in starts]
    true_peaks = [L.true_peak_dbtp(a[max(0, i-hop):min(len(a), i+2*hop)], sr) for i in starts]
    complete = starts[starts+window <= len(a)]
    return {'samples': starts, 'times_s': starts/sr,
            'hop_samples': int(hop), 'window_samples': int(window),
            'true_peak_start_samples': np.maximum(0, starts-hop),
            'true_peak_end_samples': np.minimum(len(a), starts+2*hop),
            'sample_peak_dbfs': np.asarray(peaks), 'true_peak_dbtp': np.asarray(true_peaks),
            'level_samples': complete,
            'lufs_i_window': np.asarray([L.integrated(a[i:i+window], sr) for i in complete]),
            'momentary': L.momentary(a, sr) if len(a) else np.empty(0),
            'short_term': L.short_term(a, sr) if len(a) else np.empty(0),
            'loudness_hop_samples': int(round(.1*sr)),
            'stereo': [stereo_bands(a[i:i+window], sr) for i in complete]}


def spectrogram(x, sr, *, window=1024, hop=None):
    st = analyze(x, sr, window=window, hop=hop)
    power = np.abs(st.spectra)**2/(window*np.sum(st.window**2))
    if window % 2 == 0:
        power[:, 1:-1] *= 2
    else:
        power[:, 1:] *= 2
    return {'samples': st.samples, 'times_s': st.samples/sr,
            'frequencies_hz': st.frequencies_hz, 'power': power,
            'hop_samples': st.hop_samples, 'window_samples': len(st.window)}
