"""BB-06 float64 analysis and WOLA synthesis; periodic sqrt-Hann, one-worker FFT.

analyze(x, sr, window=1024, hop=None) returns STFTAnalysis. Frame centers
are 0, hop, ... strictly before the input end; zero padding is explicit.
Spectra have shape (time, frequency, channel), with unnormalized rFFT.
The original analyze/sqrt_hann/cola_weights functions retain their behavior.
synthesize/apply_gains reconstruct the centered grid, with an explicit
one-window uncompensated delay; smooth_gains smooths time/frequency in dB.
"""
from dataclasses import dataclass
import numpy as np
from scipy import fft
from mankomix.dsp.errors import ParamError


def sqrt_hann(length):
    """Periodic square-root Hann, including an exact zero at index zero."""
    if isinstance(length, bool) or not isinstance(length, (int, np.integer)) or length < 4:
        raise ParamError('window length must be an integer >= 4')
    return np.sqrt(.5 - .5*np.cos(2*np.pi*np.arange(length)/length))


def cola_weights(window, hop):
    """Sum squared window values by hop phase; a constant means WOLA COLA."""
    w = np.asarray(window, dtype=np.float64)
    if w.ndim != 1 or not np.isfinite(w).all() or not isinstance(hop, (int, np.integer)) or not 1 <= hop <= len(w):
        raise ParamError('invalid window or hop')
    return np.bincount(np.arange(len(w)) % hop, weights=w*w, minlength=hop)


@dataclass(frozen=True)
class STFTAnalysis:
    spectra: np.ndarray
    samples: np.ndarray
    frequencies_hz: np.ndarray
    window: np.ndarray
    hop_samples: int
    sr: int
    frames: int


def analyze(x, sr, *, window=1024, hop=None):
    """Analyze mono or frames/ch audio on a centered fixed integer grid."""
    w = sqrt_hann(window)
    hop = window//4 if hop is None else hop
    cola_weights(w, hop)
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    if a.ndim != 2 or a.shape[1] < 1 or not np.isfinite(a).all() or sr <= 0:
        raise ParamError('finite audio and positive sample rate required')
    centers = np.arange(0, len(a), hop, dtype=np.int64)
    padded = np.pad(a, ((window//2, window), (0, 0)))
    if len(centers):
        frames = np.lib.stride_tricks.sliding_window_view(padded, window, axis=0)[centers]
        spectra = fft.rfft(frames*w, axis=-1, workers=1).transpose(0, 2, 1)
    else:
        spectra = np.empty((0, window//2+1, a.shape[1]), dtype=np.complex128)
    return STFTAnalysis(spectra, centers, fft.rfftfreq(window, 1/sr), w, int(hop), int(sr), len(a))


def check_cola(window, hop, *, atol=1e-12):
    """Return the positive WOLA constant, or raise ParamError.

    Formula reference: Smith, Spectral Audio Signal Processing, Weighted
    Overlap Add. No third-party implementation is copied.
    """
    weights = cola_weights(window, hop)
    if np.min(weights) <= 0 or not np.allclose(weights, weights[0], rtol=0, atol=atol):
        raise ParamError('window and hop do not satisfy WOLA COLA')
    return float(weights[0])


def window_samples(window, sr):
    """Scale a 48 kHz window to sr, rounding to a multiple of four."""
    if sr <= 0 or window < 4:
        raise ParamError('positive sample rate and window >= 4 required')
    return max(4, 4*int(round(float(window)*sr/48000/4)))


def latency_samples(window, sr=None):
    """Declared buffered WOLA delay: one actual window, before compensation."""
    return int(window) if sr is None else window_samples(window, sr)


def delay_output(x, delay):
    """Expose the uncompensated buffered output, retaining input length."""
    if delay < 0 or int(delay) != delay:
        raise ParamError('delay must be a nonnegative integer')
    y = np.zeros_like(x)
    if delay == 0:
        return x.copy()
    if delay < len(x):
        y[delay:] = x[:-delay]
    return y


def synthesize(analysis, spectra=None, *, compensate=True):
    """Inverse WOLA to (frames, ch); spectra defaults to the analysis data.

    The original centered analysis grid is unchanged. At finite boundaries
    the sum of *present* window products is used, including the truncated
    final overlap. Unit gains therefore reconstruct even one-sample clips.
    compensate=False exposes the declared one-window buffered delay.
    """
    a = analysis
    check_cola(a.window, a.hop_samples)
    z = a.spectra if spectra is None else np.asarray(spectra, dtype=np.complex128)
    if z.shape != a.spectra.shape or not np.isfinite(z).all():
        raise ParamError('finite spectra matching analysis shape required')
    n = len(a.window)
    y = np.zeros((a.frames, z.shape[2]), dtype=np.float64)
    weights = np.zeros(a.frames, dtype=np.float64)
    # Chunk FFT work to avoid a second full-length time-domain allocation.
    for first in range(0, len(z), 128):
        blocks = fft.irfft(z[first:first+128], n=n, axis=1, workers=1)
        for j, block in enumerate(blocks):
            start = int(a.samples[first+j])-n//2
            left, right = max(0, start), min(a.frames, start+n)
            w = a.window[left-start:right-start]
            y[left:right] += block[left-start:right-start]*w[:, None]
            weights[left:right] += w*w
    if a.frames and np.any(weights <= 0):
        raise ParamError('analysis grid leaves uncovered samples')
    if a.frames:
        y /= weights[:, None]
    return y if compensate else delay_output(y, n)


def smooth_frequency(values, frequencies_hz, width_oct):
    """Box average along bin axis 1 over a constant-octave bandwidth.

    Shape is (time, bin, ...); zero width is an exact copy. Prefix sums
    implement nonuniform neighborhoods without a dense bin-by-bin matrix.
    """
    v = np.asarray(values, dtype=np.float64)
    f = np.asarray(frequencies_hz, dtype=np.float64)
    if v.ndim < 2 or v.shape[1] != len(f) or width_oct < 0 or not np.isfinite(v).all():
        raise ParamError('invalid frequency smoothing data')
    if width_oct == 0 or not v.size:
        return v.copy()
    lo = np.searchsorted(f, f*2**(-width_oct/2), side='left')
    hi = np.searchsorted(f, f*2**(width_oct/2), side='right')
    hi = np.maximum(hi, lo+1)
    sums = np.concatenate([np.zeros_like(v[:, :1]), np.cumsum(v, axis=1)], axis=1)
    shape = (1, len(f))+(1,)*(v.ndim-2)
    return (sums[:, hi]-sums[:, lo])/(hi-lo).reshape(shape)


def smooth_gains(gains, sr, hop, frequencies_hz, *, time_ms=0, freq_oct=0):
    """Smooth nonnegative linear per-bin gains in dB, frequency then time.

    Time uses a causal one-pole with exp(-hop/(sr*tau)), initialized to the
    first target (no artificial fade-in); tau=0 bypasses that dimension.
    """
    from scipy.signal import lfilter
    g = np.asarray(gains, dtype=np.float64)
    if np.any(g < 0) or not np.isfinite(g).all() or time_ms < 0 or sr <= 0 or hop <= 0:
        raise ParamError('invalid gains or smoothing clock')
    if not g.size or (time_ms == 0 and freq_oct == 0):
        return g.copy()
    db = smooth_frequency(20*np.log10(np.maximum(g, 1e-15)), frequencies_hz, freq_oct)
    if time_ms > 0:
        alpha = np.exp(-hop/(sr*time_ms*.001))
        db, _ = lfilter([1-alpha], [1, -alpha], db, axis=0, zi=alpha*db[:1])
    return 10**(db/20)


def apply_gains(analysis, gains, *, time_ms=0, freq_oct=0, compensate=True):
    """Broadcast gains to spectra, smooth, and return (audio, applied_gains)."""
    try:
        g = np.broadcast_to(np.asarray(gains, dtype=np.float64), analysis.spectra.shape)
    except ValueError as exc:
        raise ParamError('gains do not broadcast to spectra') from exc
    g = smooth_gains(g, analysis.sr, analysis.hop_samples, analysis.frequencies_hz,
                     time_ms=time_ms, freq_oct=freq_oct)
    return synthesize(analysis, analysis.spectra*g, compensate=compensate), g


def band_weights(frequencies_hz, lo_hz, hi_hz):
    """Unity inside the band with inward 1/3-octave cosine edge tapers."""
    if not 0 < lo_hz < hi_hz:
        raise ParamError('lo_hz must be positive and below hi_hz')
    f = np.maximum(np.asarray(frequencies_hz), np.finfo(float).tiny)
    logf = np.log2(f)
    low = np.clip(3*(logf-np.log2(lo_hz)), 0, 1)
    high = np.clip(3*(np.log2(hi_hz)-logf), 0, 1)
    return .5*(1-np.cos(np.pi*low)) * .5*(1-np.cos(np.pi*high))
