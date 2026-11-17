"""BB-07: frequency-sampled FIRs and deterministic FFT convolution.

Public API (all audio and coefficients are float64):
``resolution_taps(sr, resolution)`` returns an odd, sample-rate-scaled length.
``design_linear_fir(magnitude, sr, taps, beta=8)`` samples a callable at a
power-of-two grid of at least 4*taps, then centres, windows and symmetrises.
``minimum_phase(h)`` folds the real log-magnitude cepstrum, preserving gain.
``curve_magnitude(f, curve, amount=1)`` interpolates dB on log Hz; endpoints
are held, including DC. Empty curves return unity.
``fft_convolve(x, h, mode='full')`` performs one FFT convolution.
``partitioned_convolve(x, h, partition_size=1024, mode='full')`` uses uniform
IR partitions. ``PartitionedConvolver(h, input_channels, partition_size)``
offers ``process(x)`` and one final ``flush()``. Process buffers partial
partitions and returns only completed partitions; flush returns the remainder
and the tail. External chunk sizes never change arithmetic or output bits.
Kernels may be (taps,), (taps, channels) for diagonal paths, or
(taps, input_channels, output_channels) for MIMO. Audio is (frames, channels).
Mode 'same' means the first input-length samples of the causal convolution.
``apply_fir(x, h, sr, linear=True, neutral=False)`` returns offline compensated
audio and latency/pre-ringing statistics. Neutral bypasses convolution exactly.

Algorithms are independently expressed from the frequency sampling/window
method and real-cepstrum lifter in standard discrete-time signal theory.
Formula reference: J. O. Smith, Spectral Audio Signal Processing,
https://dsprelated.com/freebooks/SASP/Minimum_Phase_Causal_Cepstra.html
(textbook derivation only, no implementation code copied).
"""
from __future__ import annotations

import numpy as np
from scipy import fft

RESOLUTIONS = {"low": 2049, "mid": 8193, "high": 32769, "max": 65537}


def resolution_taps(sr, resolution="mid"):
    if sr <= 0:
        raise ValueError("sample rate must be positive")
    return 2 * max(1, int(round((RESOLUTIONS[resolution] - 1) * sr / 96000))) + 1


def curve_magnitude(f, curve, amount=1.0):
    f = np.asarray(f, dtype=np.float64)
    if not curve:
        return np.ones_like(f)
    points = np.asarray(curve, dtype=np.float64)
    db = np.interp(np.log(np.maximum(f, np.finfo(float).tiny)),
                   np.log(points[:, 0]), points[:, 1])
    return 10.0 ** (db * amount / 20.0)


def design_linear_fir(magnitude, sr, taps, beta=8.0):
    if taps < 3 or taps % 2 != 1 or sr <= 0:
        raise ValueError("FIR length must be odd and >= 3; sr must be positive")
    nfft = 1 << (4 * int(taps) - 1).bit_length()
    f = fft.rfftfreq(nfft, 1.0 / sr)
    mag = np.asarray(magnitude(f), dtype=np.float64)
    if mag.shape != f.shape or not np.isfinite(mag).all() or np.any(mag < 0):
        raise ValueError("magnitude must return finite nonnegative grid values")
    h = np.roll(fft.irfft(mag, nfft, workers=1), taps // 2)[:taps]
    h *= np.kaiser(taps, beta)
    # Make symmetry exact rather than depending on FFT rounding.
    return (h + h[::-1]) * 0.5


def minimum_phase(h):
    """Full-length spectral factor; no square-root magnitude or gain rescaling."""
    h = np.asarray(h, dtype=np.float64)
    if h.ndim != 1 or not len(h) or not np.isfinite(h).all():
        raise ValueError("expected a finite nonempty FIR vector")
    if not np.any(h):
        return h.copy()
    nfft = 1 << (32 * len(h) - 1).bit_length()
    mag = np.abs(fft.rfft(h, nfft, workers=1))
    c = fft.irfft(np.log(np.maximum(mag, np.max(mag) * 1e-15)), nfft, workers=1)
    lifted = np.zeros(nfft)
    lifted[0] = c[0]
    lifted[1:nfft // 2] = 2 * c[1:nfft // 2]
    lifted[nfft // 2] = c[nfft // 2]
    return fft.irfft(np.exp(fft.rfft(lifted, workers=1)), nfft, workers=1)[:len(h)].copy()


def _kernel(h, channels):
    h = np.asarray(h, dtype=np.float64)
    if h.ndim == 1:
        h = h[:, None, None] * np.eye(channels)[None, :, :]
    elif h.ndim == 2:
        if h.shape[1] != channels:
            raise ValueError("diagonal kernel channel mismatch")
        h = h[:, :, None] * np.eye(channels)[None, :, :]
    if h.ndim != 3 or not len(h) or h.shape[1] != channels or h.shape[2] < 1:
        raise ValueError("invalid convolution kernel shape")
    if not np.isfinite(h).all():
        raise ValueError("kernel must be finite")
    return h


def _audio(x, channels=None):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] < 1 or (channels is not None and x.shape[1] != channels):
        raise ValueError("audio must have shape (frames, channels)")
    if not np.isfinite(x).all():
        raise ValueError("audio must be finite")
    return x


def _mode(y, n, mode):
    if mode not in ("full", "same"):
        raise ValueError("mode must be full or same (causal)")
    return y if mode == "full" else y[:n]


def fft_convolve(x, h, mode="full"):
    x = _audio(x)
    h = _kernel(h, x.shape[1])
    n = len(x)
    if not n:
        return _mode(np.zeros((0, h.shape[2])), n, mode)
    length = n + len(h) - 1
    nfft = fft.next_fast_len(length, real=True)
    X = fft.rfft(x, nfft, axis=0, workers=1)
    H = fft.rfft(h, nfft, axis=0, workers=1)
    Y = np.zeros((len(X), h.shape[2]), dtype=np.complex128)
    for i in range(x.shape[1]):
        Y += X[:, i, None] * H[:, i, :]
    return _mode(fft.irfft(Y, nfft, axis=0, workers=1)[:length], n, mode)


class PartitionedConvolver:
    """Uniform frequency-domain delay line with a fixed internal partition grid."""

    def __init__(self, h, input_channels=1, partition_size=1024):
        if isinstance(partition_size, bool) or int(partition_size) != partition_size or partition_size < 1:
            raise ValueError("partition_size must be a positive integer")
        self.size = int(partition_size)
        self.h = _kernel(h, input_channels).copy()
        self.ci, self.co = self.h.shape[1:]
        self.count = (len(self.h) + self.size - 1) // self.size
        self.H = []
        for k in range(self.count):
            self.H.append(fft.rfft(self.h[k*self.size:(k+1)*self.size], 2*self.size,
                                   axis=0, workers=1))
        self.history = np.zeros((self.count, self.size + 1, self.ci), dtype=np.complex128)
        self.overlap = np.zeros((self.size, self.co))
        self.pending = np.zeros((0, self.ci))
        self.index = self.frames = self.emitted = 0
        self.closed = False

    def _block(self, x):
        b = self.size
        self.history[self.index % self.count] = fft.rfft(x, 2*b, axis=0, workers=1)
        Y = np.zeros((b + 1, self.co), dtype=np.complex128)
        for k in range(min(self.count, self.index + 1)):
            X = self.history[(self.index - k) % self.count]
            for i in range(self.ci):
                Y += X[:, i, None] * self.H[k][:, i, :]
        y = fft.irfft(Y, 2*b, axis=0, workers=1)
        out = y[:b] + self.overlap
        self.overlap = y[b:].copy()
        self.index += 1
        return out

    def process(self, x):
        if self.closed:
            raise ValueError("convolver is already flushed")
        x = _audio(x, self.ci)
        self.frames += len(x)
        self.pending = np.concatenate((self.pending, x))
        blocks = []
        offset = 0
        while len(self.pending) - offset >= self.size:
            blocks.append(self._block(self.pending[offset:offset+self.size]))
            offset += self.size
        self.pending = self.pending[offset:].copy()
        self.emitted += offset
        return np.concatenate(blocks) if blocks else np.zeros((0, self.co))

    def flush(self):
        if self.closed:
            raise ValueError("convolver is already flushed")
        self.closed = True
        remaining = self.frames + len(self.h) - 1 - self.emitted if self.frames else 0
        blocks = []
        first = np.zeros((self.size, self.ci))
        first[:len(self.pending)] = self.pending
        while len(blocks) * self.size < remaining:
            blocks.append(self._block(first))
            first = np.zeros_like(first)
        return np.concatenate(blocks)[:remaining] if blocks else np.zeros((0, self.co))


def partitioned_convolve(x, h, partition_size=1024, mode="full"):
    x = _audio(x)
    conv = PartitionedConvolver(h, x.shape[1], partition_size)
    y = np.concatenate((conv.process(x), conv.flush()))
    return _mode(y, len(x), mode)


def apply_fir(x, h, sr, *, linear=True, neutral=False):
    """Compensate linear group delay offline; report causal delay separately."""
    d = (len(h) - 1) // 2 if linear else 0
    pre = h[:d]
    total = float(np.sum(h*h))
    energy = float(np.sum(pre*pre))
    above = np.flatnonzero(np.abs(pre) > np.max(np.abs(h)) * 1e-3)
    stats = {"fir_taps": len(h), "latency_samples": d, "latency_compensated": True,
             "phase_cost": {"phase_type": "linear" if linear else "minimum"},
             "pre_ringing": {"energy_ratio_db": round(10*np.log10(energy/total), 6) if energy else None,
                             "duration_ms_above_-60db": round((d-above[0])*1000/sr, 6) if len(above) else 0.0}}
    y = x.copy() if neutral else fft_convolve(x, h)[d:d+len(x)]
    return y, stats
