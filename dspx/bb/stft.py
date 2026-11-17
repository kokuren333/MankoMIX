"""BB-06 analysis half: float64 frames, periodic sqrt-Hann, one-worker FFT.

analyze(x, sr, window=1024, hop=None) returns STFTAnalysis. Frame centers
are 0, hop, ... strictly before the input end; zero padding is explicit.
Spectra have shape (time, frequency, channel), with unnormalized rFFT.
sqrt_hann and cola_weights expose the future WOLA window convention.
Synthesis and gain processing belong to the later BB-06 implementation.
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
