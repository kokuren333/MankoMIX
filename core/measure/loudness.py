"""Loudness and peak measurement (SPEC 4.2 P-03 / P-14, 4.3 S-01).

Implemented from the standards, not from third-party code:

- ITU-R BS.1770-4: K-weighting (pre-filter shelf + RLB high-pass), mean-square
  per channel, channel weights, 400 ms gating blocks with 75 % overlap,
  absolute gate -70 LUFS, relative gate -10 LU.
- EBU Tech 3341: momentary (400 ms) and short-term (3 s) loudness, here
  evaluated on a 100 ms hop.
- EBU Tech 3342: loudness range from short-term values (absolute gate
  -70 LUFS, relative gate -20 LU, 10th to 95th percentile).
- ITU-R BS.1770-4 Annex 2: true peak by oversampling (>= 4x) with a
  polyphase FIR interpolator.

All signals are float arrays shaped [frames, channels] (1-D = mono).
Values that do not exist (silence, too short) are returned as -inf or nan;
callers that need JSON should map them to null (see vector.py).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import resample_poly, sosfilt

from ..errors import InputError

ABS_GATE_LUFS = -70.0
REL_GATE_LU = -10.0
LRA_REL_GATE_LU = -20.0
MOMENTARY_S = 0.4
SHORT_TERM_S = 3.0
HOP_S = 0.1
TP_MIN_OVERSAMPLE = 4
TP_TARGET_RATE = 192000
TP_TAPS_PER_PHASE = 32
TP_KAISER_BETA = 8.0

# Analog-prototype parameters of the BS.1770 K-weighting filters. With the
# bilinear transform (tan prewarping at f0) these reproduce the coefficient
# tables published in BS.1770-4 for 48 kHz to ~1e-8 and give the same
# response at any other rate.
_SHELF_F0 = 1681.974450955533
_SHELF_GAIN_DB = 3.999843853973347
_SHELF_Q = 0.7071752369554196
_SHELF_VB_EXP = 0.4996667741545416
_HP_F0 = 38.13547087602444
_HP_Q = 0.5003270373238773


def as_frames(x) -> np.ndarray:
    """Return x as float64 [frames, channels]. 1-D input is treated as mono."""
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    if a.ndim != 2:
        raise InputError(f"audio must be 1-D or 2-D [frames, channels], got shape {a.shape}")
    if a.shape[1] > 64 and a.shape[0] <= 64:
        raise InputError(f"audio looks like [channels, frames] (shape {a.shape}); expected [frames, channels]")
    return a


def channel_weights(n_channels: int) -> np.ndarray:
    """BS.1770 channel weights G_i.

    1 ch: mono (one channel, weight 1). 2 ch: L R. 3 ch: L R C.
    5 ch: L R C Ls Rs (surrounds 1.41). 6 ch: L R C LFE Ls Rs (LFE excluded).
    Other layouts: all 1.0.
    """
    if n_channels == 5:
        return np.array([1.0, 1.0, 1.0, 1.41, 1.41])
    if n_channels == 6:
        return np.array([1.0, 1.0, 1.0, 0.0, 1.41, 1.41])
    return np.ones(n_channels)


def k_weighting_sos(sr: float) -> np.ndarray:
    """K-weighting as second-order sections [2, 6] for sample rate sr."""
    sr = float(sr)
    if sr <= 2 * _SHELF_F0:
        raise InputError(f"sample rate too low for K-weighting: {sr}")
    # Stage 1: high-frequency shelf (head acoustics).
    k = math.tan(math.pi * _SHELF_F0 / sr)
    vh = 10.0 ** (_SHELF_GAIN_DB / 20.0)
    vb = vh ** _SHELF_VB_EXP
    a0 = 1.0 + k / _SHELF_Q + k * k
    b_shelf = [(vh + vb * k / _SHELF_Q + k * k) / a0,
               2.0 * (k * k - vh) / a0,
               (vh - vb * k / _SHELF_Q + k * k) / a0]
    a_shelf = [1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / _SHELF_Q + k * k) / a0]
    # Stage 2: RLB high-pass. Numerator fixed to [1, -2, 1] as in BS.1770.
    k = math.tan(math.pi * _HP_F0 / sr)
    a0 = 1.0 + k / _HP_Q + k * k
    b_hp = [1.0, -2.0, 1.0]
    a_hp = [1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / _HP_Q + k * k) / a0]
    return np.array([b_shelf + a_shelf, b_hp + a_hp], dtype=np.float64)


def _kfilter(a: np.ndarray, sr: float) -> np.ndarray:
    """K-weighting filter that stays fast on sparse/near-silent material.

    IIR tails decaying into subnormal numbers slow sosfilt down by an order of
    magnitude. A tiny alternating offset keeps the filter state normal; since
    the filter is linear, its own response is subtracted again, so silence
    stays exactly zero and results are unchanged beyond rounding.
    """
    sos = k_weighting_sos(sr)
    guard = np.empty((a.shape[0], 1))
    guard[0::2] = 1e-20
    guard[1::2] = -1e-20
    return sosfilt(sos, a + guard, axis=0) - sosfilt(sos, guard, axis=0)


def k_weight(x, sr: float) -> np.ndarray:
    """Apply K-weighting per channel (filter starts from rest)."""
    a = as_frames(x)
    return _kfilter(a, sr)


# --------------------------------------------------------------------------
# Block energies


def _segment_sums(y: np.ndarray, sr: float) -> tuple[np.ndarray, np.ndarray]:
    """Sum of squares per 100 ms segment and channel, plus segment lengths.

    Segment boundaries are round(k * sr * 0.1); only complete segments are
    kept. Summing per segment (instead of differencing a running cumsum)
    keeps silent stretches exactly zero.
    """
    n = y.shape[0]
    hop = sr * HOP_S
    n_seg = int(math.floor(n / hop + 1e-9))
    if n_seg <= 0:
        return np.zeros((0, y.shape[1])), np.zeros(0)
    bounds = np.round(np.arange(n_seg + 1) * hop).astype(np.int64)
    bounds[-1] = min(bounds[-1], n)
    sq = y * y
    sums = np.add.reduceat(sq, bounds[:-1], axis=0)
    # reduceat's last segment runs to the end of the array; trim it.
    sums[-1] = sq[bounds[-2]:bounds[-1]].sum(axis=0)
    return sums, np.diff(bounds).astype(np.float64)


def _block_mean_squares(seg: np.ndarray, seg_len: np.ndarray, n_seg_per_block: int) -> np.ndarray:
    """Mean square per channel for blocks of n consecutive segments, 1-segment hop."""
    if seg.shape[0] < n_seg_per_block:
        return np.zeros((0, seg.shape[1]))
    win = np.lib.stride_tricks.sliding_window_view(seg, n_seg_per_block, axis=0).sum(axis=-1)
    lens = np.lib.stride_tricks.sliding_window_view(seg_len, n_seg_per_block).sum(axis=-1)
    return win / lens[:, None]


def _loudness_from_ms(ms: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """LUFS per block from per-channel mean squares [blocks, ch]."""
    z = ms @ weights
    with np.errstate(divide="ignore"):
        return -0.691 + 10.0 * np.log10(z)


class _Blocks:
    """K-weighted 100 ms segment energies, shared by all loudness measures."""

    def __init__(self, x, sr: float, weights=None):
        a = as_frames(x)
        self.sr = float(sr)
        self.weights = channel_weights(a.shape[1]) if weights is None else np.asarray(weights, float)
        if self.weights.shape != (a.shape[1],):
            raise InputError("channel weights do not match channel count")
        y = _kfilter(a, sr)
        self.seg, self.seg_len = _segment_sums(y, self.sr)

    def ms(self, window_s: float) -> np.ndarray:
        return _block_mean_squares(self.seg, self.seg_len, int(round(window_s / HOP_S)))

    def lufs(self, window_s: float) -> np.ndarray:
        return _loudness_from_ms(self.ms(window_s), self.weights)

    def integrated(self) -> float:
        ms = self.ms(MOMENTARY_S)
        if ms.shape[0] == 0:
            return float("-inf")
        lk = _loudness_from_ms(ms, self.weights)
        gated = lk > ABS_GATE_LUFS
        if not np.any(gated):
            return float("-inf")
        rel = _loudness_from_ms(ms[gated].mean(axis=0, keepdims=True), self.weights)[0] + REL_GATE_LU
        keep = gated & (lk > rel)
        if not np.any(keep):
            return float("-inf")
        return float(_loudness_from_ms(ms[keep].mean(axis=0, keepdims=True), self.weights)[0])

    def lra(self) -> float:
        st = self.lufs(SHORT_TERM_S)
        return _lra_from_short_term(st)


def _lra_from_short_term(st: np.ndarray) -> float:
    st = st[st > ABS_GATE_LUFS]
    if st.size == 0:
        return float("nan")
    # Relative gate: -20 LU below the power mean of the absolute-gated values.
    mean_power = np.mean(10.0 ** (st / 10.0))
    rel = 10.0 * math.log10(mean_power) + LRA_REL_GATE_LU
    st = st[st > rel]
    if st.size == 0:
        return float("nan")
    lo, hi = np.percentile(st, [10.0, 95.0])
    return float(hi - lo)


# --------------------------------------------------------------------------
# Public loudness API


def momentary(x, sr: float) -> np.ndarray:
    """Momentary loudness (LUFS) of 400 ms blocks every 100 ms.

    Element k covers [k*0.1 s, k*0.1 s + 0.4 s). Only complete blocks are
    returned; silent blocks are -inf.
    """
    return _Blocks(x, sr).lufs(MOMENTARY_S)


def short_term(x, sr: float) -> np.ndarray:
    """Short-term loudness (LUFS) of 3 s windows every 100 ms (Tech 3341)."""
    return _Blocks(x, sr).lufs(SHORT_TERM_S)


def integrated(x, sr: float, *, weights=None) -> float:
    """Gated integrated loudness (BS.1770-4). -inf for silence or < 400 ms."""
    return _Blocks(x, sr, weights).integrated()


def loudness_range(x, sr: float) -> float:
    """Loudness range in LU (EBU Tech 3342). nan if nothing passes the gates."""
    return _Blocks(x, sr).lra()


# --------------------------------------------------------------------------
# Peaks


def _db(v: float) -> float:
    return 20.0 * math.log10(v) if v > 0 else float("-inf")


def sample_peak_dbfs(x) -> float:
    """Highest absolute sample value in dBFS (non-finite samples ignored)."""
    a = np.abs(as_frames(x))
    a = a[np.isfinite(a)]
    return _db(float(a.max())) if a.size else float("-inf")


def tp_oversample_factor(sr: float) -> int:
    """Oversampling factor: >= 4 and effective rate >= 192 kHz."""
    return max(TP_MIN_OVERSAMPLE, int(math.ceil(TP_TARGET_RATE / float(sr) - 1e-9)))


def _interp_filter(up: int) -> np.ndarray:
    """Kaiser-windowed sinc interpolator (cutoff at the input Nyquist).

    It is a Nyquist filter: the zero phase passes the input samples unchanged,
    the other phases interpolate between them.
    """
    half = up * TP_TAPS_PER_PHASE // 2
    n = np.arange(-half, half + 1)
    h = np.sinc(n / up) * np.kaiser(2 * half + 1, TP_KAISER_BETA)
    h[(n % up == 0) & (n != 0)] = 0.0
    return h / up  # resample_poly multiplies by up


def true_peak_per_channel(x, sr: float, oversample: int | None = None,
                          *, chunk: int = 1 << 18) -> list[float]:
    """True peak per channel in dBTP.

    The signal is upsampled by `oversample` (default tp_oversample_factor)
    with a polyphase FIR and the maximum absolute value is taken. The result
    is never below the sample peak. Processing is chunked with overlap so
    memory stays bounded for long files.
    """
    a = as_frames(x)
    up = tp_oversample_factor(sr) if oversample is None else int(oversample)
    if up < 1:
        raise InputError("oversample must be >= 1")
    a = np.where(np.isfinite(a), a, 0.0)
    n = a.shape[0]
    out = []
    if n == 0:
        return [float("-inf")] * a.shape[1]
    if up == 1:
        return [_db(float(np.max(np.abs(a[:, c])))) for c in range(a.shape[1])]
    h = _interp_filter(up)
    pad = TP_TAPS_PER_PHASE + 2
    for c in range(a.shape[1]):
        col = a[:, c]
        peak = float(np.max(np.abs(col)))
        for start in range(0, n, chunk):
            s0 = max(0, start - pad)
            s1 = min(n, start + chunk + pad)
            y = resample_poly(col[s0:s1], up, 1, window=h)
            off = (start - s0) * up
            keep = y[off:off + (min(n, start + chunk) - start) * up]
            if keep.size:
                peak = max(peak, float(np.max(np.abs(keep))))
        out.append(_db(peak))
    return out


def true_peak_dbtp(x, sr: float, oversample: int | None = None) -> float:
    """Maximum true peak over all channels in dBTP."""
    return float(max(true_peak_per_channel(x, sr, oversample)))


# --------------------------------------------------------------------------
# Summary (P-03)


def loudness_summary(x, sr: float, *, true_peak: float | None = None) -> dict:
    """P-03 loudness/dynamics group. Floats; missing values are -inf/nan.

    Short-term percentiles use the short-term values above the absolute gate
    (-70 LUFS) so silence does not drag them to -inf.
    `true_peak` may be passed in when the caller has already measured it.
    """
    a = as_frames(x)
    blocks = _Blocks(a, sr)
    il = blocks.integrated()
    st = blocks.lufs(SHORT_TERM_S)
    mom = blocks.lufs(MOMENTARY_S)
    st_g = st[st > ABS_GATE_LUFS]
    if st_g.size:
        p10, p50, p95 = (float(v) for v in np.percentile(st_g, [10.0, 50.0, 95.0]))
    else:
        p10 = p50 = p95 = float("nan")
    st_max = float(st.max()) if st.size else float("-inf")
    m_max = float(mom.max()) if mom.size else float("-inf")
    tp = true_peak_dbtp(a, sr) if true_peak is None else float(true_peak)
    nan = float("nan")
    return {
        "integrated_lufs": il,
        "short_term_max_lufs": st_max,
        "short_term_p10": p10,
        "short_term_p50": p50,
        "short_term_p95": p95,
        "momentary_max_lufs": m_max,
        "lra_lu": _lra_from_short_term(st),
        "true_peak_dbtp": tp,
        "sample_peak_dbfs": sample_peak_dbfs(a),
        "plr_db": tp - il if math.isfinite(tp) and math.isfinite(il) else nan,
        "psr_db": tp - st_max if math.isfinite(tp) and math.isfinite(st_max) else nan,
    }
