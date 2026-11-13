"""Band definitions and deterministic band-splitting helpers.

Everything here works on one full-length real FFT per channel (`Spectrum`).
That gives a frequency resolution of 1/duration, exact energy bookkeeping
(Parseval) and zero-phase band signals, with no state and no randomness.

- Energies, cross-energies (correlation, side ratio, mono loss) and LTAS are
  summed over FFT bins with brick-wall band membership [lo, hi). Contiguous
  bands therefore partition the energy exactly.
- Time-domain band signals (for peaks/crest) use smooth, amplitude-
  complementary raised-cosine edges on a log-frequency axis (1/6 octave on
  each side of an edge) to avoid brick-wall ringing. Contiguous band signals
  sum back to the (band-limited) input.

Bands above Nyquist are omitted; a band whose upper edge exceeds Nyquist is
clipped to Nyquist.
"""

from __future__ import annotations

import math
from typing import Iterable, NamedTuple

import numpy as np
from scipy import fft as sfft


class Band(NamedTuple):
    name: str
    lo_hz: float
    hi_hz: float


# P-22: six contiguous density bands.
BANDS_P22: tuple[Band, ...] = (
    Band("sub", 20.0, 60.0),
    Band("bass", 60.0, 250.0),
    Band("lowmid", 250.0, 500.0),
    Band("mid", 500.0, 2000.0),
    Band("highmid", 2000.0, 6000.0),
    Band("air", 6000.0, 20000.0),
)

# P-07: energy-ratio bands named in SPEC 4.2 (sub, bass, lowmid 200-800 Hz),
# completed upward. lowmid deliberately overlaps bass (SPEC definition), so
# these fractions do not sum to 1; use BANDS_P22 for a partition.
BANDS_P07: tuple[Band, ...] = (
    Band("sub", 20.0, 60.0),
    Band("bass", 60.0, 250.0),
    Band("lowmid", 200.0, 800.0),
    Band("mid", 800.0, 2000.0),
    Band("highmid", 2000.0, 6000.0),
    Band("air", 6000.0, 20000.0),
)

AUDIBLE_RANGE_HZ = (20.0, 20000.0)
EDGE_HALF_WIDTH_OCT = 1.0 / 6.0


def clip_bands(bands: Iterable, sr: float) -> list[Band]:
    """Drop bands starting at/above Nyquist and clip upper edges to Nyquist."""
    nyq = sr / 2.0
    out = []
    for b in bands:
        b = Band(*b)
        if b.lo_hz >= nyq:
            continue
        out.append(Band(b.name, float(b.lo_hz), float(min(b.hi_hz, nyq))))
    return out


def erb_number(f_hz):
    """ERB-rate (Glasberg & Moore 1990): 21.4 * log10(1 + 0.00437 f)."""
    return 21.4 * np.log10(1.0 + 0.00437 * np.asarray(f_hz, dtype=float))


def erb_number_to_hz(e):
    return (10.0 ** (np.asarray(e, dtype=float) / 21.4) - 1.0) / 0.00437


def erb_grid(sr: float, lo_hz: float = 20.0, hi_hz: float = 20000.0, step: float = 1.0) -> list[Band]:
    """Contiguous bands of `step` ERB-number width from lo_hz to min(hi_hz, Nyquist)."""
    hi = min(hi_hz, sr / 2.0)
    e0, e1 = float(erb_number(lo_hz)), float(erb_number(hi))
    n = max(1, int(math.ceil((e1 - e0) / step - 1e-9)))
    edges = erb_number_to_hz(np.minimum(e0 + step * np.arange(n + 1), e1))
    edges[0], edges[-1] = lo_hz, hi
    return [Band(f"erb{i:02d}", float(edges[i]), float(edges[i + 1])) for i in range(n)]


def third_octave_grid(sr: float, lo_hz: float = 20.0, hi_hz: float = 20000.0) -> list[Band]:
    """Base-10 1/3-octave bands (IEC 61260 nominal centres 25 Hz ... 20 kHz)."""
    out = []
    for k in range(14, 44):  # 10**(k/10): 25.1 Hz ... 19.95 kHz
        fc = 10.0 ** (k / 10.0)
        lo, hi = fc * 10 ** (-0.05), fc * 10 ** 0.05
        if hi < lo_hz or lo > hi_hz:
            continue
        out.append(Band(f"{fc:.0f}", lo, hi))
    return clip_bands(out, sr)


def _hp_edge(f: np.ndarray, edge: float, half_oct: float) -> np.ndarray:
    """Smooth high-pass weight: 0 below edge*2^-h, 1 above edge*2^h.

    f must be sorted ascending (FFT bin frequencies); only the transition
    region is evaluated.
    """
    if edge <= 0:
        return np.ones_like(f)
    i0 = int(np.searchsorted(f, edge * 2.0 ** -half_oct, side="left"))
    i1 = int(np.searchsorted(f, edge * 2.0 ** half_oct, side="right"))
    w = np.zeros_like(f)
    w[i1:] = 1.0
    ft = f[i0:i1]
    if ft.size:
        t = (np.log2(np.maximum(ft, 1e-12) / edge) + half_oct) / (2.0 * half_oct)
        w[i0:i1] = 0.5 - 0.5 * np.cos(np.pi * np.clip(t, 0.0, 1.0))
    return w


class Spectrum:
    """Full-length real FFT of a [frames, channels] signal.

    The signal is zero-padded by `pad_s` seconds (to keep band-filter
    responses from wrapping around) and to a fast FFT length.
    `bin_power(c)` returns per-bin contributions to the channel's mean square
    over the original length, so `bin_power(c)[mask].sum()` is the band's
    mean square (dB re 1.0; a full-scale sine reads -3.01 dB).
    """

    def __init__(self, x: np.ndarray, sr: float, pad_s: float = 0.5):
        a = np.asarray(x, dtype=np.float64)
        if a.ndim == 1:
            a = a[:, None]
        self.sr = float(sr)
        self.n = a.shape[0]
        self.channels = a.shape[1]
        self.nfft = sfft.next_fast_len(self.n + int(round(pad_s * sr)) + 1, real=True)
        self.X = sfft.rfft(a, n=self.nfft, axis=0)
        self.freqs = sfft.rfftfreq(self.nfft, 1.0 / self.sr)
        w = np.full(self.freqs.shape, 2.0)
        w[0] = 1.0
        if self.nfft % 2 == 0:
            w[-1] = 1.0
        self._scale = w / (float(self.nfft) * max(self.n, 1))
        self._pow: dict = {}

    def index_range(self, lo_hz: float, hi_hz: float) -> tuple[int, int]:
        """Bin index range [i0, i1) of frequencies in [lo_hz, hi_hz)."""
        nb = self.freqs.shape[0]
        i0 = int(np.searchsorted(self.freqs, lo_hz, side="left"))
        i1 = int(np.searchsorted(self.freqs, hi_hz, side="left"))
        return min(i0, nb), min(max(i1, i0), nb)

    def mask(self, lo_hz: float, hi_hz: float) -> np.ndarray:
        return (self.freqs >= lo_hz) & (self.freqs < hi_hz)

    def bin_power(self, c: int) -> np.ndarray:
        if c not in self._pow:
            xc = self.X[:, c]
            self._pow[c] = self._scale * (xc.real ** 2 + xc.imag ** 2)
        return self._pow[c]

    def mean_bin_power(self) -> np.ndarray:
        """Per-bin mean-square contributions averaged over channels."""
        if "mean" not in self._pow:
            acc = np.zeros_like(self._scale)
            for c in range(self.channels):
                acc += self.bin_power(c)
            self._pow["mean"] = acc / self.channels
        return self._pow["mean"]

    def bin_cross(self, c0: int, c1: int) -> np.ndarray:
        """Per-bin contributions to mean(x_c0 * x_c1)."""
        key = ("x", c0, c1)
        if key not in self._pow:
            self._pow[key] = self._scale * (self.X[:, c0] * np.conj(self.X[:, c1])).real
        return self._pow[key]

    def band_sum(self, per_bin: np.ndarray, lo_hz: float, hi_hz: float) -> float:
        i0, i1 = self.index_range(lo_hz, hi_hz)
        return float(per_bin[i0:i1].sum())

    def has_bins(self, lo_hz: float, hi_hz: float) -> bool:
        i0, i1 = self.index_range(lo_hz, hi_hz)
        return i1 > i0

    def band_power(self, lo_hz: float, hi_hz: float, c: int) -> float:
        return self.band_sum(self.bin_power(c), lo_hz, hi_hz)

    def mean_power(self, lo_hz: float, hi_hz: float) -> float:
        """Band mean square averaged over channels."""
        return self.band_sum(self.mean_bin_power(), lo_hz, hi_hz)

    def band_weights(self, lo_hz: float, hi_hz: float,
                     half_oct: float = EDGE_HALF_WIDTH_OCT) -> np.ndarray:
        """Smooth zero-phase band response on the FFT bins.

        Edges at or above Nyquist (and lo <= 0) are left open.
        """
        f = self.freqs
        w = _hp_edge(f, lo_hz, half_oct)
        if hi_hz < self.sr / 2.0:
            w = w * (1.0 - _hp_edge(f, hi_hz, half_oct))
        return w

    def band_signal(self, lo_hz: float, hi_hz: float,
                    half_oct: float = EDGE_HALF_WIDTH_OCT) -> np.ndarray:
        """Zero-phase band-passed signal [frames, channels] at the full rate."""
        w = self.band_weights(lo_hz, hi_hz, half_oct)
        y = sfft.irfft(self.X * w[:, None], n=self.nfft, axis=0)
        return y[: self.n]

    def band_signal_reduced(self, lo_hz: float, hi_hz: float,
                            half_oct: float = EDGE_HALF_WIDTH_OCT,
                            oversample: float = 16.0,
                            weights: np.ndarray | None = None) -> tuple[np.ndarray, float]:
        """Band signal synthesised at a reduced rate, returns (y, rate).

        The rate is at least `oversample` times the band's highest non-zero
        frequency (or the full rate if that is not lower), so peaks read
        from it are within 20*log10(cos(pi/oversample)) dB (0.17 dB at 16x)
        of the full-rate peak. Mean squares are preserved. `weights` may pass
        a precomputed band_weights(lo_hz, hi_hz, half_oct).
        """
        w = self.band_weights(lo_hz, hi_hz, half_oct) if weights is None else weights
        top = hi_hz * 2.0 ** half_oct if hi_hz < self.sr / 2.0 else self.sr / 2.0
        n_r = sfft.next_fast_len(int(math.ceil(self.nfft * min(1.0, oversample * top / self.sr))) + 2,
                                 real=True)
        if n_r >= self.nfft:
            return sfft.irfft(self.X * w[:, None], n=self.nfft, axis=0)[: self.n], self.sr
        nb = n_r // 2 + 1
        spec = self.X[:nb] * w[:nb, None]
        # The band response is zero well below the reduced Nyquist, so no bin folds.
        y = sfft.irfft(spec, n=n_r, axis=0) * (n_r / self.nfft)
        rate = self.sr * n_r / self.nfft
        return y[: int(math.ceil(self.n * n_r / self.nfft))], rate


def split_bands(x: np.ndarray, sr: float, bands: Iterable = BANDS_P22):
    """Yield (Band, band_signal[frames, channels]) one band at a time."""
    spec = Spectrum(x, sr)
    for b in clip_bands(bands, sr):
        yield b, spec.band_signal(b.lo_hz, b.hi_hz)
