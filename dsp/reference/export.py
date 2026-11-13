"""resample and dither (reference backend; export module only).

resample: scipy.signal.resample_poly with a rational ratio (48000 -> 44100 =
147/160) and a Kaiser-window FIR designed for ~120 dB stopband with a narrow
transition just below the lower Nyquist frequency. (No soxr / librosa.)

dither: TPDF (+-1 LSB peak, sum of two independent uniform variables), no
noise shaping, from numpy's PCG64 generator seeded with an integer the caller
derives from the project (SPEC 9.6), then quantised to the target word
length. The result holds exactly representable values k / 2^(bits-1).
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy import signal

STOPBAND_DB = 120.0
PASSBAND_FRACTION = 0.94   # passband edge as a fraction of the lower Nyquist
CUTOFF_FRACTION = 0.97     # -6 dB point as a fraction of the lower Nyquist


@lru_cache(maxsize=16)
def resample_filter(sr_in: int, sr_out: int) -> tuple[int, int, np.ndarray]:
    g = math.gcd(sr_in, sr_out)
    up, down = sr_out // g, sr_in // g
    fs_up = float(sr_in) * up
    nyq_low = min(sr_in, sr_out) / 2.0
    tw = 2.0 * (CUTOFF_FRACTION - PASSBAND_FRACTION) * nyq_low
    numtaps, beta = signal.kaiserord(STOPBAND_DB, tw / (fs_up / 2.0))
    numtaps |= 1
    h = signal.firwin(numtaps, CUTOFF_FRACTION * nyq_low, window=("kaiser", beta), fs=fs_up)
    h.setflags(write=False)
    return up, down, h  # resample_poly applies the gain of ``up`` itself (on a copy we pass)


def resample_poly_hq(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x.copy()
    up, down, h = resample_filter(int(sr_in), int(sr_out))
    return signal.resample_poly(x, up, down, axis=0, window=h.copy())


def resample(x: np.ndarray, sr: int, p: dict, **_):
    target = int(p["target_sr"])
    if target == sr:
        return x.copy(), sr, {"resampled": False, "from_sr": sr, "to_sr": sr}
    up, down, h = resample_filter(int(sr), target)
    y = signal.resample_poly(x, up, down, axis=0, window=h.copy())
    return y, target, {"resampled": True, "from_sr": sr, "to_sr": target, "ratio": f"{up}/{down}",
                       "method": "resample_poly", "window": "kaiser", "fir_taps": int(len(h)),
                       "stopband_db": STOPBAND_DB,
                       "passband_hz": round(PASSBAND_FRACTION * min(sr, target) / 2.0, 1)}


def tpdf_dither(x: np.ndarray, bits: int, seed: int) -> tuple[np.ndarray, dict]:
    q = 2.0 ** -(bits - 1)
    rng = np.random.Generator(np.random.PCG64(int(seed)))
    noise = (rng.random(x.shape) - rng.random(x.shape)) * q
    k = np.rint((x + noise) / q)
    kmax = 2 ** (bits - 1) - 1
    kmin = -(2 ** (bits - 1))
    clipped = int(np.count_nonzero((k > kmax) | (k < kmin)))
    k = np.clip(k, kmin, kmax)
    return k * q, {"clipped_samples": clipped, "lsb": q}


def dither(x: np.ndarray, sr: int, p: dict, *, seed: int = 0, **_):
    bits = int(p["bit_depth"])
    y, st = tpdf_dither(x, bits, seed)
    return y, sr, {"type": p["type"], "bit_depth": bits, "seed": int(seed), "rng": "numpy.PCG64",
                   "noise_shaping": "none", **st}


def to_pcm_int(y: np.ndarray, bits: int) -> np.ndarray:
    """Exact conversion of quantised floats (k / 2^(bits-1)) to integers for the file writer.

    16 bit -> int16; 24 bit -> int32 holding the 24-bit word in the top bits
    (libsndfile writes the upper 24 bits for PCM_24).
    """
    scale = 2.0 ** (bits - 1)
    k = np.rint(y * scale)
    k = np.clip(k, -scale, scale - 1)
    if bits == 16:
        return k.astype(np.int16)
    if bits == 24:
        return (k.astype(np.int64) << 8).astype(np.int32)
    raise ValueError(f"unsupported bit depth {bits}")
