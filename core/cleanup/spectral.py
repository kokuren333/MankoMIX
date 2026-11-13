"""Detection-based spectral reduction (SPEC 6.4.2 step 3, band policy 6.4.1).

Model of the artifact: AI-generated audio carries signal-correlated noise in
the high band that *flickers* -- time-frequency cells light up for a few tens
of milliseconds above the steady level of their neighbourhood ("shimmer",
"birdies", swirl). Music in the same band is either tonal (tracked partials),
transient (onsets followed by smooth decays) or steady noise (air, breath).

Detector (per pooled frequency group and STFT frame):

* power pooled into ~94 Hz groups and smoothed over 3 groups,
* steady reference = low percentile of ~120 ms windows just before and
  just after the frame; excess = level above the larger of the two (dB), so
  attacks and decays are not mistaken for flicker,
* transient-onset release control: frames at and just after a broadband
  onset (2-9 kHz energy jump) are not reduced, with a linear release,
* melody/harmonic protection: bins on a spectral peak that continues for
  several frames (a tracked partial) are never reduced.

Reduction: excess above the band threshold, limited per pass (3-6 dB in the
shimmer band), several passes with re-detection on the reduced spectrum,
smoothed over time and frequency (anti musical noise), capped in total and by
the protection stage. Bins below the crossover get a gain of exactly 1.
STFT: Hann analysis and synthesis, fixed window and hop (75 % overlap).
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np
from scipy import ndimage
from scipy.signal import butter, sosfilt

from ._util import EPS, bin_range, istft, stft, stft_freqs, stft_params, v


# --- band policy as per-bin vectors ------------------------------------------

def band_vectors(freqs: np.ndarray, policy: dict, ceiling_hz: float | None,
                 nyquist: float) -> dict:
    """Per-bin threshold, per-pass cap, total cap and minimum reduction (dB),
    plus a band-id index per bin. Bins of the untouched low band get zeros."""
    k = freqs.shape[0]
    thr = np.full(k, np.inf, dtype=np.float32)
    per_pass = np.zeros(k, dtype=np.float32)
    total = np.zeros(k, dtype=np.float32)
    min_red = np.zeros(k, dtype=np.float32)
    band_idx = np.full(k, -1, dtype=np.int16)
    xover = float(v(policy["crossover"]["frequency_hz"]))
    for i, b in enumerate(policy["bands"]):
        lo, hi = b["range_hz"]
        if lo == "ceiling":
            if ceiling_hz is None:
                continue
            lo = ceiling_hz
        if hi is None:
            hi = nyquist + 1.0
        lo = float(lo)
        hi = float(hi)
        if b["id"] != "above_ceiling" and ceiling_hz is not None:
            hi = min(hi, ceiling_hz)
        sel = (freqs >= max(lo, xover)) & (freqs < hi)
        if b.get("threshold_db") is None or not np.any(sel):
            continue
        thr[sel] = float(b["threshold_db"])
        per_pass[sel] = float(b["per_pass_max_db"])
        total[sel] = float(b["total_max_db"])
        min_red[sel] = float(b.get("min_reduction_db") or 0.0)
        band_idx[sel] = i
    # never touch the protected low band
    low = freqs <= xover
    thr[low] = np.inf
    per_pass[low] = 0.0
    total[low] = 0.0
    min_red[low] = 0.0
    return {"thr": thr, "per_pass": per_pass, "total": total, "min_red": min_red,
            "band_idx": band_idx}


# --- detectors ----------------------------------------------------------------

def _two_sided_ref(pg: np.ndarray, win: int, pct: float) -> np.ndarray:
    """Steady reference per cell: the larger of the low percentiles of the
    windows just before and just after the frame (axis 0 = time).

    A flicker peak exceeds both, a decay only the later window and an attack
    only the earlier one, so only flicker shows an excess over this."""
    cen = ndimage.percentile_filter(pg, pct, size=(win,) + (1,) * (pg.ndim - 1), mode="nearest")
    sh = win // 2 + 1
    t = pg.shape[0]
    if t <= sh:
        return cen
    past = np.empty_like(cen)
    fut = np.empty_like(cen)
    past[sh:] = cen[:-sh]
    past[:sh] = cen[:1]
    fut[:-sh] = cen[sh:]
    fut[-sh:] = cen[-1:]
    return np.maximum(past, fut)


def attack_frames(sig1d: np.ndarray, sr: float, n_fft: int, hop: int, n_frames: int,
                  policy: dict) -> np.ndarray:
    """Boolean per STFT frame: a sharp attack in the high band (hi-hat,
    cymbal, consonant onset) -- the high-passed RMS rises by >= rise_db within
    a few ms *to* a level near its local maximum. Slow tremolo-like flicker
    does not qualify. Frame t covers input samples [t*hop - n_fft, t*hop)."""
    det = policy["detector"]["attack"]
    out = np.zeros(n_frames, bool)
    fc = min(float(v(det["highpass_hz"])), 0.45 * sr)
    blk = max(4, int(round(float(v(det["block_ms"])) * 1e-3 * sr)))
    n = sig1d.shape[0]
    nb = n // blk
    if nb < 16:
        return out
    sos = butter(4, fc, btype="highpass", fs=sr, output="sos")
    hp = sosfilt(sos, sig1d)
    e = np.sqrt(np.mean(hp[:nb * blk].reshape(nb, blk) ** 2, axis=1)) + 1e-12
    look0 = max(1, int(round(float(v(det["lookback_ms"])[0]) / float(v(det["block_ms"])))))
    look1 = max(look0, int(round(float(v(det["lookback_ms"])[1]) / float(v(det["block_ms"])))))
    before = np.full(nb, np.inf)
    for off in range(look0, look1 + 1):
        sh = np.full(nb, np.inf)
        sh[off:] = e[:-off]
        before = np.minimum(before, sh)
    lw = max(3, int(round(float(v(det["local_ms"])) / float(v(det["block_ms"])))) | 1)
    lmax = ndimage.maximum_filter1d(e, lw, mode="nearest")
    rise = 20.0 * np.log10(e / np.where(np.isfinite(before), before, e))
    near = 20.0 * np.log10(e / lmax)
    att = (rise >= float(v(det["rise_db"]))) & (near >= -float(v(det["near_max_db"])))
    att &= e > float(v(det["min_level"]))
    idx = np.flatnonzero(att)
    if idx.size:
        centre = idx * blk + blk // 2
        t = np.clip(np.round((centre + n_fft / 2.0) / hop).astype(int), 0, n_frames - 1)
        out[t] = True
    return out


def onset_gate(power: np.ndarray, freqs: np.ndarray, frame_rate: float, policy: dict,
               attacks: np.ndarray | None = None) -> np.ndarray:
    """Per-frame protection weight in [0, 1] (1 = fully protected).

    Transient-onset release control: an energy jump in the onset band (below
    the shimmer band) opens the gate, which holds and then releases linearly.
    Co-modulation: when the onset band itself shows a short event (excess
    over its own two-sided steady reference), the high band is following the
    music (hi-hat, snare, consonant) and is protected in proportion."""
    det = policy["detector"]["onset"]
    lo, hi = v(det["band_hz"])
    sl = bin_range(freqs, lo, hi)
    e = power[:, sl].sum(axis=1).astype(np.float64) + EPS
    t = e.shape[0]
    gate = np.zeros(t, dtype=np.float32)
    if t < 3:
        return gate
    look = max(1, int(v(det["lookback_frames"])))
    prev = np.full(t, np.inf)
    for i in range(1, look + 1):
        shifted = np.full(t, np.inf)
        shifted[i:] = e[:-i]
        prev = np.minimum(prev, shifted)
    jump = 10.0 * np.log10(e / np.where(np.isfinite(prev), prev, e))
    floor = np.percentile(e, 10.0)
    onset = (jump >= float(v(det["jump_db"]))) & (e > floor * 4.0)
    if attacks is not None:
        onset = onset | attacks
    hold = max(0, int(round(float(v(det["hold_s"])) * frame_rate)))
    rel = max(1, int(round(float(v(det["release_s"])) * frame_rate)))
    pre = max(0, int(v(det["pre_frames"])))
    on = onset.astype(np.float32)
    for i in range(hold + rel + 1):
        wgt = 1.0 if i <= hold else 1.0 - (i - hold) / (rel + 1.0)
        if i == 0:
            gate = np.maximum(gate, on)
        else:
            gate[i:] = np.maximum(gate[i:], on[:t - i] * wgt)
    for i in range(1, pre + 1):
        gate[:-i] = np.maximum(gate[:-i], on[i:])
    # co-modulation with the onset band
    win = max(3, int(round(float(v(policy["detector"]["ref_window_s"])) * frame_rate)) | 1)
    ref = _two_sided_ref(e, win, float(v(policy["detector"]["ref_percentile"])))
    ex = 10.0 * np.log10(e / (ref + EPS))
    c0, c1 = v(det["comod_db"])
    co = np.clip((ex - c0) / max(c1 - c0, 1e-6), 0.0, 1.0).astype(np.float32)
    co = ndimage.maximum_filter1d(co, 3)
    return np.maximum(gate, co)


def tonal_protection(power: np.ndarray, policy: dict) -> np.ndarray:
    """Boolean [frames, bins]: bins on tracked partials (persistent peaks)."""
    det = policy["detector"]["tonal"]
    prom = 10.0 ** (float(v(det["prominence_db"])) / 10.0)
    nb = int(v(det["neighborhood_bins"]))
    cont = int(v(det["continuity_frames"]))
    p = power
    local = ndimage.uniform_filter1d(p, nb, axis=1, mode="nearest")
    left = np.empty_like(p)
    right = np.empty_like(p)
    left[:, 1:] = p[:, :-1]
    left[:, 0] = np.inf
    right[:, :-1] = p[:, 1:]
    right[:, -1] = np.inf
    peak = (p >= left) & (p >= right) & (p > prom * local) & (p > 0)
    peak = ndimage.maximum_filter1d(peak, 3, axis=1)
    pf = peak.astype(np.float32)
    half = cont // 2
    thr = 1.0 - 0.5 / cont
    centered = ndimage.uniform_filter1d(pf, cont, axis=0, mode="constant") >= thr
    fwd = ndimage.uniform_filter1d(pf, cont, axis=0, mode="constant", origin=-half) >= thr
    bwd = ndimage.uniform_filter1d(pf, cont, axis=0, mode="constant", origin=half) >= thr
    prot = (centered | fwd | bwd) & peak
    return ndimage.maximum_filter1d(prot, 3, axis=1)


class GroupGrid:
    """Pooling of STFT bins (from k0 upward) into fixed-width groups."""

    def __init__(self, freqs: np.ndarray, k0: int, group_bins: int):
        self.k0 = k0
        self.g = max(1, group_bins)
        self.k = freqs.shape[0]
        n = self.k - k0
        self.n_groups = int(math.ceil(n / self.g)) if n > 0 else 0
        self.pad = self.n_groups * self.g - n

    def pool(self, p: np.ndarray) -> np.ndarray:
        sub = p[:, self.k0:]
        if self.pad:
            sub = np.concatenate([sub, np.repeat(sub[:, -1:], self.pad, axis=1)], axis=1)
        return sub.reshape(sub.shape[0], self.n_groups, self.g).mean(axis=2)

    def expand(self, gvals: np.ndarray) -> np.ndarray:
        full = np.zeros((gvals.shape[0], self.k), dtype=np.float32)
        rep = np.repeat(gvals, self.g, axis=1)[:, :self.k - self.k0]
        full[:, self.k0:] = rep
        return full

    def group_mean(self, vec: np.ndarray) -> np.ndarray:
        sub = vec[self.k0:]
        if self.pad:
            sub = np.concatenate([sub, np.repeat(sub[-1:], self.pad)])
        return sub.reshape(self.n_groups, self.g).mean(axis=1)


def excess_db(power: np.ndarray, grid: GroupGrid, frame_rate: float, policy: dict) -> np.ndarray:
    """Flicker excess (dB above the steady temporal reference) per group."""
    det = policy["detector"]
    pg = grid.pool(power)
    fs = int(v(det["freq_smooth_groups"]))
    if fs > 1:
        pg = ndimage.uniform_filter1d(pg, fs, axis=1, mode="nearest")
    win = max(3, int(round(float(v(det["ref_window_s"])) * frame_rate)) | 1)
    ref = _two_sided_ref(pg, win, float(v(det["ref_percentile"])))
    return (10.0 * np.log10((pg + EPS) / (ref + EPS))).astype(np.float32)


def flicker_excess_power(power: np.ndarray, freqs: np.ndarray, frame_rate: float,
                         policy: dict, lo: float, hi: float, *, threshold_db: float = 3.0,
                         gate: np.ndarray | None = None,
                         flatness_weight: bool = True) -> float:
    """Diagnostic: energy of the flicker component inside [lo, hi) in the
    same (unnormalised) units as ``power`` summed over cells. Onset frames
    and tracked partials are excluded; with ``flatness_weight`` each cell is
    weighted by the spectral flatness of its ~1 kHz neighbourhood, so the
    index measures noise-like flicker (band flatness over time x modulation)."""
    sl = bin_range(freqs, lo, hi)
    if sl.stop - sl.start < 2 or power.shape[0] < 3:
        return 0.0
    sub = np.ascontiguousarray(power[:, sl])
    df = freqs[1] - freqs[0]
    gbins = max(1, int(round(float(v(policy["detector"]["group_hz"])) / df)))
    grid = GroupGrid(freqs[sl], 0, gbins)
    ex = excess_db(sub, grid, frame_rate, policy)
    prot = tonal_protection(sub, policy)
    pool = grid.pool(np.where(prot, 0.0, sub).astype(np.float32))
    ratio = 10.0 ** (-ex / 10.0)  # ref / power
    thr = 10.0 ** (-threshold_db / 10.0)
    frac = np.clip(1.0 - ratio / thr, 0.0, 1.0)  # share of the cell above thr x ref
    if gate is not None:
        frac = frac * (1.0 - gate[:, None])
    if flatness_weight:
        # noise-likeness of each ~1 kHz chunk per frame (Gaussian noise
        # periodogram flatness ~0.56 -> weight 1; tonal content -> ~0)
        chunk = max(2, int(round(1000.0 / df)))
        lp = np.log(sub.astype(np.float64) + EPS)
        nchunk = max(1, sub.shape[1] // chunk)
        wts = np.zeros(pool.shape, dtype=np.float32)
        gcent = (np.arange(grid.n_groups) * grid.g + 0.5 * grid.g) // chunk
        for c in range(nchunk):
            k0, k1 = c * chunk, (sub.shape[1] if c == nchunk - 1 else (c + 1) * chunk)
            gm = np.exp(lp[:, k0:k1].mean(axis=1))
            am = sub[:, k0:k1].mean(axis=1) + EPS
            w = np.clip((gm / am) / 0.5, 0.0, 1.0).astype(np.float32)
            sel = np.clip(gcent, 0, nchunk - 1) == c
            wts[:, sel] = w[:, None]
        frac = frac * wts
    return float(np.sum(pool * frac) * grid.g)


# --- reduction ----------------------------------------------------------------

def reduction_db(power: np.ndarray, freqs: np.ndarray, frame_rate: float, policy: dict, *,
                 vectors: dict, strength: float, passes: int,
                 caps: np.ndarray | None = None,
                 gate: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """Total reduction in dB [frames, bins] after all passes (>= 0)."""
    det = policy["detector"]
    t, k = power.shape
    df = freqs[1] - freqs[0]
    k0 = int(np.argmax(np.isfinite(vectors["thr"]))) if np.any(np.isfinite(vectors["thr"])) else k
    total = np.zeros((t, k), dtype=np.float32)
    info = {"passes": [], "tonal_protected_fraction": 0.0, "onset_frames": 0}
    if k0 >= k or t < 3 or strength <= 0.0 or passes <= 0:
        return total, info
    gbins = max(1, int(round(float(v(det["group_hz"])) / df)))
    grid = GroupGrid(freqs, k0, gbins)
    thr_g = grid.group_mean(np.where(np.isfinite(vectors["thr"]), vectors["thr"], 1e3)).astype(np.float32)
    pp_g = grid.group_mean(vectors["per_pass"]).astype(np.float32)
    mr_g = grid.group_mean(vectors["min_red"]).astype(np.float32)
    slope = float(v(det["slope"]))
    sm_t = int(v(det["gain_smooth_frames"]))
    sm_g = int(v(det["gain_smooth_groups"]))
    if gate is None:
        gate = onset_gate(power, freqs, frame_rate, policy)
    open_ = (1.0 - gate)[:, None].astype(np.float32)
    info["onset_frames"] = int(np.sum(gate >= 0.999))
    prot = tonal_protection(power, policy)
    info["tonal_protected_fraction"] = float(np.mean(prot[:, k0:])) if k > k0 else 0.0
    total_cap = vectors["total"][None, :]
    if caps is not None:
        total_cap = np.minimum(total_cap, caps)
    for pi in range(passes):
        cur = power * (10.0 ** (-total / 10.0))
        ex = excess_db(cur, grid, frame_rate, policy)
        r = np.clip((ex - thr_g[None, :]) * slope, 0.0, None)
        r = np.minimum(r, pp_g[None, :])
        fired = r > 0.0
        r = np.where(fired, np.maximum(r, np.minimum(mr_g[None, :], pp_g[None, :])), 0.0)
        r = r * strength * open_
        if sm_t > 1 or sm_g > 1:
            r = ndimage.uniform_filter(r, size=(max(1, sm_t), max(1, sm_g)), mode="nearest")
        rb = grid.expand(r.astype(np.float32))
        if gbins > 1:
            rb[:, k0:] = ndimage.uniform_filter1d(rb[:, k0:], gbins, axis=1, mode="nearest")
        rb[prot] = 0.0
        new_total = np.minimum(total + rb, total_cap)
        new_total[:, :k0] = 0.0
        added = new_total - total
        total = new_total.astype(np.float32)
        info["passes"].append({
            "pass": pi + 1,
            "fired_fraction": float(np.mean(fired)),
            "mean_added_db": float(np.mean(added[:, k0:])),
            "max_added_db": float(np.max(added)) if added.size else 0.0,
        })
    return total, info


def reduce(x2d: np.ndarray, sr: float, policy: dict, *, strength: float = 1.0,
           passes: int = 3, ceiling_hz: float | None = None,
           caps_fn: Callable[[np.ndarray, np.ndarray, float], np.ndarray] | None = None) -> tuple[np.ndarray, dict]:
    """Detection-based spectral reduction of a [frames, channels] signal.

    Stereo is processed as mid/side (each with its own detection, onset gate
    from the mid); other layouts per channel. Returns (removed component
    [frames, channels], info). ``caps_fn(power_mid, freqs, frame_rate)`` may
    return a [frames, bins] cap in dB from the protection stage.
    """
    n, nch = x2d.shape
    n_fft, hop = stft_params(sr, policy)
    freqs = stft_freqs(sr, n_fft)
    frame_rate = sr / hop
    vectors = band_vectors(freqs, policy, ceiling_hz, sr / 2.0)
    if nch == 2:
        sigs = [0.5 * (x2d[:, 0] + x2d[:, 1]), 0.5 * (x2d[:, 0] - x2d[:, 1])]
        names = ["mid", "side"]
    else:
        sigs = [x2d[:, c] for c in range(nch)]
        names = [f"ch{c}" for c in range(nch)]
    specs = [stft(s, n_fft, hop) for s in sigs]
    p0 = (specs[0].real ** 2 + specs[0].imag ** 2).astype(np.float32)
    att = attack_frames(sigs[0], sr, n_fft, hop, p0.shape[0], policy)
    gate = onset_gate(p0, freqs, frame_rate, policy, attacks=att)
    caps = caps_fn(p0, freqs, frame_rate) if caps_fn is not None else None
    removed = []
    info: dict = {"n_fft": n_fft, "hop": hop, "window": "hann", "strength": strength,
                  "passes": passes, "ceiling_hz": ceiling_hz, "channels": {}}
    for name, s, spec in zip(names, sigs, specs):
        if not np.any(s):
            removed.append(np.zeros(n))
            info["channels"][name] = {"skipped": "silent"}
            continue
        pw = p0 if name in ("mid", "ch0") else (spec.real ** 2 + spec.imag ** 2).astype(np.float32)
        tot, cinfo = reduction_db(pw, freqs, frame_rate, policy, vectors=vectors,
                                  strength=strength, passes=passes, caps=caps, gate=gate)
        g = 10.0 ** (-tot / 20.0)
        rem_spec = spec * (1.0 - g).astype(np.float32)
        removed.append(istft(rem_spec, n_fft, hop, n))
        cinfo["mean_reduction_db_by_band"] = _band_mean_reduction(tot, freqs, policy, ceiling_hz, sr)
        cinfo["max_reduction_db"] = float(np.max(tot)) if tot.size else 0.0
        info["channels"][name] = cinfo
    if nch == 2:
        m, sd = removed
        out = np.stack([m + sd, m - sd], axis=1)
    else:
        out = np.stack(removed, axis=1)
    return out, info


def _band_mean_reduction(tot: np.ndarray, freqs: np.ndarray, policy: dict,
                         ceiling_hz: float | None, sr: float) -> dict:
    out = {}
    for b in policy["bands"]:
        lo, hi = b["range_hz"]
        if lo == "ceiling":
            if ceiling_hz is None:
                continue
            lo = ceiling_hz
        hi = sr / 2.0 + 1.0 if hi is None else float(hi)
        if b["id"] != "above_ceiling" and ceiling_hz is not None:
            hi = min(hi, ceiling_hz)
        sl = bin_range(freqs, float(lo), hi)
        if sl.stop > sl.start:
            out[b["id"]] = round(float(np.mean(tot[:, sl])), 3)
    return out
