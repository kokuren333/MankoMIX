"""Perceptual frequency scales and ERB-band spectra (SPEC 4.1, 4.2 P-01, R-01, R-02).

- ERB-number scale and ERB bandwidth after Glasberg & Moore (1990):
  ERB-number(f) = 21.4 * log10(1 + 0.00437 f), ERB(f) = 24.7 * (0.00437 f + 1).
- Bark: Traunmueller (1990) and Zwicker & Terhardt (1980) approximations.
- Equal-loudness contours from the ISO 226:2003 formula; the parameter table
  is stored in knowledge/iso226.json.
- ``ltas_erb``: long-term average spectrum summed into ERB bands, level-matched
  to a reference integrated loudness before any comparison (R-01).

Signals are float arrays shaped [frames, channels] (1-D = mono).
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from ..errors import InputError

ERB_A = 21.4
ERB_B = 0.00437
DEFAULT_PHON = 80.0
DEFAULT_TARGET_LUFS = -23.0


# --------------------------------------------------------------------------
# Scales


def hz_to_erb_number(f):
    """ERB-number (Cams) of frequency f in Hz (Glasberg & Moore 1990)."""
    f = np.asarray(f, dtype=np.float64)
    return ERB_A * np.log10(1.0 + ERB_B * f)


def erb_number_to_hz(e):
    """Inverse of hz_to_erb_number."""
    e = np.asarray(e, dtype=np.float64)
    return (10.0 ** (e / ERB_A) - 1.0) / ERB_B


def erb_bandwidth(f):
    """Equivalent rectangular bandwidth in Hz at centre frequency f."""
    f = np.asarray(f, dtype=np.float64)
    return 24.7 * (ERB_B * f + 1.0)


def hz_to_bark(f, method: str = "traunmuller"):
    """Critical-band rate in Bark ('traunmuller' or 'zwicker')."""
    f = np.asarray(f, dtype=np.float64)
    if method == "traunmuller":
        return 26.81 * f / (1960.0 + f) - 0.53
    if method == "zwicker":
        return 13.0 * np.arctan(0.00076 * f) + 3.5 * np.arctan((f / 7500.0) ** 2)
    raise InputError(f"unknown Bark method '{method}'")


def bark_to_hz(z):
    """Inverse of the Traunmueller Bark formula."""
    z = np.asarray(z, dtype=np.float64)
    return 1960.0 * (z + 0.53) / (26.28 - z)


# --------------------------------------------------------------------------
# ERB band layout


def erb_band_edges(sr: float, n_fft: int | None = None, *, fmin: float = 20.0,
                   fmax: float | None = None, step: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Band edges and centres (Hz) spaced `step` ERB-numbers apart.

    fmax defaults to min(20 kHz, 0.475 * sr). When n_fft is given, bands
    narrower than one FFT bin are merged with their upper neighbour so every
    band holds at least one bin of energy. Centres are the ERB-number midpoints.
    """
    if step <= 0:
        raise InputError("step must be > 0")
    nyq = float(sr) / 2.0
    fmax = min(20000.0, 0.95 * nyq) if fmax is None else min(float(fmax), nyq)
    if not 0 < fmin < fmax:
        raise InputError(f"invalid band range {fmin}..{fmax} Hz")
    e0, e1 = float(hz_to_erb_number(fmin)), float(hz_to_erb_number(fmax))
    n = max(1, int(math.floor((e1 - e0) / step + 1e-9)))
    e_edges = e0 + step * np.arange(n + 1)
    edges = erb_number_to_hz(e_edges)
    edges[-1] = min(edges[-1], fmax)
    if n_fft is not None:
        df = float(sr) / int(n_fft)
        keep = [edges[0]]
        for hi in edges[1:]:
            if hi - keep[-1] >= df:
                keep.append(hi)
        if len(keep) == 1:
            keep.append(edges[-1])
        elif keep[-1] != edges[-1]:
            keep[-1] = edges[-1]
        edges = np.asarray(keep, dtype=np.float64)
    centers = erb_number_to_hz(0.5 * (hz_to_erb_number(edges[:-1]) + hz_to_erb_number(edges[1:])))
    return edges, centers


def band_matrix(sr: float, n_fft: int, edges) -> np.ndarray:
    """[bands, bins] matrix summing rfft-bin powers into bands.

    Each bin covers [f - df/2, f + df/2); its weight in a band is the fraction
    of that interval inside the band, so energy is conserved across bands.
    """
    edges = np.asarray(edges, dtype=np.float64)
    df = float(sr) / int(n_fft)
    f = np.arange(int(n_fft) // 2 + 1) * df
    lo_bin, hi_bin = f - df / 2.0, f + df / 2.0
    lo = np.maximum(lo_bin[None, :], edges[:-1, None])
    hi = np.minimum(hi_bin[None, :], edges[1:, None])
    return np.clip(hi - lo, 0.0, None) / df


# --------------------------------------------------------------------------
# ISO 226:2003


@lru_cache(maxsize=1)
def _iso226_table() -> dict:
    from ..config import load_knowledge
    doc = load_knowledge("iso226")
    return {k: np.asarray(doc[k], dtype=np.float64)
            for k in ("frequency_hz", "alpha_f", "L_U_db", "T_f_db")}


def iso226_spl(phon: float, freqs=None) -> tuple[np.ndarray, np.ndarray]:
    """Equal-loudness contour: (freqs_hz, SPL dB) at loudness level `phon`.

    With freqs=None the 29 table frequencies are returned; otherwise the
    contour is interpolated linearly on log-frequency and held constant
    outside 20 Hz .. 12.5 kHz.
    """
    t = _iso226_table()
    ln = float(phon)
    af, lu, tf = t["alpha_f"], t["L_U_db"], t["T_f_db"]
    a_f = 4.47e-3 * (10.0 ** (0.025 * ln) - 1.15) + (0.4 * 10.0 ** ((tf + lu) / 10.0 - 9.0)) ** af
    lp = (10.0 / af) * np.log10(a_f) - lu + 94.0
    if freqs is None:
        return t["frequency_hz"].copy(), lp
    f = np.asarray(freqs, dtype=np.float64)
    lf = np.log10(np.clip(f, 1e-3, None))
    return f, np.interp(lf, np.log10(t["frequency_hz"]), lp)


def equal_loudness_weight_db(freqs, phon: float = DEFAULT_PHON) -> np.ndarray:
    """Relative ear sensitivity in dB: SPL(1 kHz) - SPL(f) on the `phon` contour.

    0 dB at 1 kHz, negative where the ear is less sensitive (low and very
    high frequencies), positive around 2-5 kHz.
    """
    _, spl = iso226_spl(phon, np.atleast_1d(freqs))
    _, ref = iso226_spl(phon, [1000.0])
    return ref[0] - spl


def perceptual_band_weights(centers_hz, phon: float = DEFAULT_PHON, *, floor: float = 0.1) -> dict:
    """Per-band ISO 226 weights.

    weight_db: relative sensitivity (equal_loudness_weight_db). importance:
    10^(weight_db/20), floored at `floor`, normalised to mean 1; used to weight
    band deviations in aggregates (SPEC 4.1 (a): more weight where the ear is
    more sensitive).
    """
    w_db = equal_loudness_weight_db(centers_hz, phon)
    imp = np.maximum(10.0 ** (w_db / 20.0), floor)
    imp = imp / imp.mean()
    return {"phon": float(phon), "weight_db": w_db, "importance": imp}


# --------------------------------------------------------------------------
# Spectra


def as_frames(x) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    if a.ndim != 2:
        raise InputError(f"audio must be 1-D or 2-D [frames, channels], got shape {a.shape}")
    if a.shape[1] > 64 and a.shape[0] <= 64:
        raise InputError(f"audio looks like [channels, frames] (shape {a.shape}); expected [frames, channels]")
    if not np.isfinite(a).all():
        a = np.where(np.isfinite(a), a, 0.0)
    return a


def mono(x) -> np.ndarray:
    """Mono sum (mean of channels)."""
    return as_frames(x).mean(axis=1)


def _frame_starts(n: int, n_fft: int, hop: int) -> np.ndarray:
    if n <= n_fft:
        return np.zeros(1, dtype=np.int64)
    return np.arange(0, n - n_fft + 1, hop, dtype=np.int64)


def stft_power_frames(y: np.ndarray, n_fft: int, hop: int, *, chunk: int = 256,
                      reducer=None) -> np.ndarray:
    """Power spectra |X|^2 of Hann-windowed frames of mono y, processed in chunks.

    Power is scaled so that summing the one-sided bins of a frame gives the
    window-weighted mean square of that frame (Parseval). If `reducer` is given
    it is applied to each chunk ([frames, bins] -> [frames, k]) and the reduced
    rows are returned, which keeps memory bounded for long files.
    """
    y = np.asarray(y, dtype=np.float64)
    if y.size < n_fft:
        y = np.concatenate([y, np.zeros(n_fft - y.size)])
    win = np.hanning(n_fft + 1)[:-1]  # periodic Hann
    scale = np.full(n_fft // 2 + 1, 2.0 / (n_fft * np.sum(win ** 2)))
    scale[0] *= 0.5
    if n_fft % 2 == 0:
        scale[-1] *= 0.5
    starts = _frame_starts(y.size, n_fft, hop)
    idx = np.arange(n_fft)
    out = []
    for c in range(0, starts.size, chunk):
        s = starts[c:c + chunk]
        frames = y[s[:, None] + idx[None, :]] * win
        p = np.abs(np.fft.rfft(frames, axis=1)) ** 2 * scale
        out.append(reducer(p) if reducer is not None else p)
    return np.concatenate(out, axis=0)


def mean_power_spectrum(y: np.ndarray, n_fft: int, hop: int | None = None) -> np.ndarray:
    """Welch-style mean power spectrum (Parseval-scaled) of mono y."""
    hop = n_fft // 2 if hop is None else hop
    sums = stft_power_frames(y, n_fft, hop, reducer=lambda p: p.sum(axis=0, keepdims=True))
    n_frames = _frame_starts(max(y.size, n_fft), n_fft, hop).size
    return sums.sum(axis=0) / max(n_frames, 1)


def _db(p, floor: float = 1e-20) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(np.asarray(p, dtype=np.float64), floor))


def loudness_arrays(x, sr: float) -> dict:
    """{"momentary", "short_term", "integrated"} from mankomix.core.measure.loudness.

    Momentary (400 ms) and short-term (3 s) LUFS every 100 ms; integrated
    loudness is derived from the momentary blocks with the BS.1770-4 gates
    (the channel-weighted sum is linear, so this equals the direct measure).
    """
    from ..measure.loudness import momentary, short_term
    a = as_frames(x)
    mom = momentary(a, sr)
    return {"momentary": mom, "short_term": short_term(a, sr),
            "integrated": integrated_from_momentary(mom)}


def integrated_from_momentary(mom) -> float:
    """BS.1770-4 gated integrated loudness from momentary block loudness values."""
    lk = np.asarray(mom, dtype=np.float64)
    lk = lk[np.isfinite(lk) & (lk > -70.0)]
    if lk.size == 0:
        return float("-inf")
    z = 10.0 ** ((lk + 0.691) / 10.0)
    rel = -0.691 + 10.0 * math.log10(z.mean()) - 10.0
    keep = z[lk > rel]
    if keep.size == 0:
        return float("-inf")
    return float(-0.691 + 10.0 * math.log10(keep.mean()))


def loudness_gain_db(x, sr: float, target_lufs: float = DEFAULT_TARGET_LUFS, *,
                     integrated_lufs: float | None = None) -> tuple[float, float | None]:
    """(gain_db, integrated_lufs) that brings x to target_lufs; gain 0 for silence."""
    if integrated_lufs is None:
        from ..measure.loudness import integrated
        integrated_lufs = integrated(as_frames(x), sr)
    il = float(integrated_lufs)
    if not math.isfinite(il):
        return 0.0, None
    return float(target_lufs - il), il


def ltas_erb(x, sr: float, *, n_fft: int = 8192, fmin: float = 20.0, fmax: float | None = None,
             step: float = 1.0, per_channel: bool = False, level_match: bool = True,
             target_lufs: float = DEFAULT_TARGET_LUFS, gain_db: float | None = None) -> dict:
    """Long-term average spectrum in ERB bands (dB, Parseval-scaled band power).

    The mono sum is analysed; per_channel adds one level vector per channel.
    With level_match the signal is first normalised to `target_lufs` integrated
    loudness (R-01) so two LTAS can be compared directly; `gain_db` may be
    passed when the caller has already measured it.
    Returns numpy arrays (use perceptual.json_safe for JSON).
    """
    a = as_frames(x)
    sr = float(sr)
    il = None
    if level_match and gain_db is None:
        gain_db, il = loudness_gain_db(a, sr, target_lufs)
    g = 0.0 if (not level_match or gain_db is None) else float(gain_db)
    edges, centers = erb_band_edges(sr, n_fft, fmin=fmin, fmax=fmax, step=step)
    m = band_matrix(sr, n_fft, edges)
    lin = 10.0 ** (g / 10.0)
    out = {
        "centers_hz": centers,
        "edges_hz": edges,
        "level_db": _db(m @ mean_power_spectrum(a.mean(axis=1), n_fft) * lin),
        "downmix": "mono_sum",
        "normalization": {
            "level_matched": bool(level_match),
            "target_lufs": float(target_lufs) if level_match else None,
            "integrated_lufs": il,
            "gain_db": g,
        },
        "n_fft": int(n_fft),
        "erb_step": float(step),
    }
    if per_channel:
        out["per_channel_db"] = [_db(m @ mean_power_spectrum(a[:, c], n_fft) * lin)
                                 for c in range(a.shape[1])]
    return out
