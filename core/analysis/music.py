"""Music-information analysis (SPEC 6.3): tempo, beats, key, tonic, sections.

Everything is implemented here with numpy/scipy (no librosa, Essentia, aubio
or madmom):

- Onset strength: log-compressed spectral flux of a decimated mono signal.
- Tempo: autocorrelation of the onset envelope, harmonic-sum scoring with a
  log-normal tempo prior, refined on a multiple of the period.
- Beats: dynamic-programming beat tracker (Ellis 2007 formulation).
- Key: tuning-compensated chroma correlated with the Krumhansl-Kessler
  profiles (Krumhansl 1990), 24 keys.
- Tonic: frequency of the key tonic in the lowest octave >= 20 Hz, plus the
  octave where the tonic is strongest in the low end (R-16).
- Sections: optimal piecewise-constant segmentation of smoothed momentary
  loudness, labelled quiet / mid / loud from short-term loudness means.
- Note values in ms from the tempo (R-11).

Every estimate carries a confidence in 0..1 (6.3). Values are JSON-safe.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import resample_poly

from . import erb as _erb

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Krumhansl-Kessler key profiles (index 0 = tonic).
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

ANALYSIS_SR = 12000.0
ONSET_NFFT_S = 0.0213   # ~256 samples at 12 kHz
ONSET_HOP_S = 0.00533   # ~64 samples at 12 kHz


@lru_cache(maxsize=1)
def thresholds() -> dict:
    from ..config import load_knowledge
    return load_knowledge("thresholds_m3")


def _clip01(v: float) -> float:
    return float(min(1.0, max(0.0, v))) if math.isfinite(v) else 0.0


def _pow2(n: float) -> int:
    return int(2 ** max(4, round(math.log2(max(n, 16.0)))))


def _decimated_mono(x, sr: float) -> tuple[np.ndarray, float]:
    y = _erb.mono(x)
    k = max(1, int(round(float(sr) / ANALYSIS_SR)))
    if k > 1:
        y = resample_poly(y, 1, k)
    return y, float(sr) / k


# --------------------------------------------------------------------------
# Onset envelope and tempo


def onset_envelope(y: np.ndarray, sr: float) -> tuple[np.ndarray, np.ndarray, float]:
    """(onset strength, low-band onset strength, frame rate) for mono y.

    Frame n is centred on n * hop (front padding of n_fft / 2).
    """
    n_fft = _pow2(sr * ONSET_NFFT_S)
    hop = max(1, int(round(sr * ONSET_HOP_S)))
    yp = np.concatenate([np.zeros(n_fft // 2), y, np.zeros(n_fft // 2)])
    p = _erb.stft_power_frames(yp, n_fft, hop)
    mag = np.sqrt(p)
    ref = float(np.max(mag)) if mag.size else 0.0
    if ref <= 0:
        z = np.zeros(mag.shape[0])
        return z, z.copy(), sr / hop
    lg = np.log1p(100.0 * mag / ref)
    d = np.diff(lg, axis=0, prepend=lg[:1])
    d = np.maximum(d, 0.0)
    flux = d.sum(axis=1)
    low_bins = max(1, int(round(200.0 * n_fft / sr)))
    flux_low = d[:, 1:low_bins + 1].sum(axis=1)
    return flux, flux_low, sr / hop


def _normalize_onset(flux: np.ndarray, fr: float) -> np.ndarray:
    if flux.size == 0:
        return flux
    w = max(3, int(round(0.4 * fr)) | 1)
    local = np.convolve(flux, np.ones(w) / w, mode="same")
    o = np.maximum(flux - local, 0.0)
    s = float(np.std(o))
    return o / s if s > 0 else o


def _acf(o: np.ndarray) -> np.ndarray:
    n = o.size
    z = o - o.mean()
    nfft = 1 << int(math.ceil(math.log2(max(2 * n, 2))))
    spec = np.fft.rfft(z, nfft)
    ac = np.fft.irfft(np.abs(spec) ** 2, nfft)[:n]
    return ac / ac[0] if ac[0] > 0 else np.zeros(n)


def _interp(a: np.ndarray, pos: float) -> float:
    if pos < 0 or pos > a.size - 1:
        return 0.0
    i = int(math.floor(pos))
    f = pos - i
    if i + 1 >= a.size:
        return float(a[i])
    return float(a[i] * (1 - f) + a[i + 1] * f)


def _peak_near(a: np.ndarray, center: float, radius: float) -> tuple[float, float]:
    """(position, height) of the parabolic-interpolated maximum of a near center."""
    lo = max(1, int(math.floor(center - radius)))
    hi = min(a.size - 2, int(math.ceil(center + radius)))
    if hi < lo:
        return center, _interp(a, center)
    i = lo + int(np.argmax(a[lo:hi + 1]))
    y0, y1, y2 = a[i - 1], a[i], a[i + 1]
    den = y0 - 2 * y1 + y2
    off = 0.5 * (y0 - y2) / den if den < 0 else 0.0
    off = max(-0.5, min(0.5, off))
    return i + off, float(y1 - 0.25 * (y0 - y2) * off)


def estimate_tempo(o: np.ndarray, fr: float, cfg: dict | None = None) -> dict:
    """Tempo from the onset-envelope autocorrelation. Returns bpm, confidence, alternatives."""
    cfg = cfg or thresholds()["music"]
    bmin, bmax = cfg["bpm_range"]
    center, octs = cfg["bpm_prior_center"], cfg["bpm_prior_octaves"]
    n = o.size
    empty = {"bpm": None, "confidence": 0.0, "alternatives": []}
    if n < 8 or not np.any(o > 0):
        return empty
    ac = _acf(o)
    lag_min = max(2, int(math.floor(60.0 * fr / bmax)))
    lag_max = min(int(math.ceil(60.0 * fr / bmin)), (n - 1) // 2)
    if lag_max <= lag_min:
        return empty
    lags = np.arange(lag_min, lag_max + 1, dtype=np.float64)
    # Harmonic sum: a true period also correlates at its multiples.
    score = np.zeros_like(lags)
    for m in (1, 2, 3, 4):
        pos = lags * m
        ok = pos <= n - 1
        score[ok] += np.interp(pos[ok], np.arange(n), np.maximum(ac, 0.0)) / m
    bpms = 60.0 * fr / lags
    prior = np.exp(-0.5 * (np.log2(bpms / center) / octs) ** 2)
    weighted = score * prior
    best = int(np.argmax(weighted))
    lag0 = lags[best]
    # Sub-frame refinement on the longest multiple that still has a clear peak.
    _, h1 = _peak_near(ac, lag0, 1.5)
    lag = lag0
    for m in (8, 4, 2, 1):
        if m * lag0 + m >= n - 1:
            continue
        pos, h = _peak_near(ac, m * lag0, max(1.5, 0.5 * m))
        if m == 1 or h >= 0.5 * h1:
            lag = pos / m
            break
    bpm = 60.0 * fr / lag
    # Confidence: periodicity strength x margin over the best non-matching candidate.
    base = float(np.median(np.maximum(ac[lag_min:lag_max + 1], 0.0)))
    strength = _clip01((h1 - base) / max(1e-9, 1.0 - base))
    far = np.abs(np.log2(bpms / bpm)) > 0.07
    second = float(np.max(weighted[far])) if np.any(far) else 0.0
    margin = 1.0 - second / weighted[best] if weighted[best] > 0 else 0.0
    conf = strength * (0.5 + 0.5 * _clip01(margin / 0.3))
    alts = []
    order = np.argsort(-weighted)
    for i in order:
        b = float(bpms[i])
        if all(abs(math.log2(b / a["bpm"])) > 0.07 for a in alts) and abs(math.log2(b / bpm)) > 0.07:
            alts.append({"bpm": round(b, 2), "relative_score": float(weighted[i] / weighted[best])})
        if len(alts) >= 3:
            break
    return {"bpm": float(bpm), "confidence": _clip01(conf), "alternatives": alts,
            "periodicity": strength}


def track_beats(o: np.ndarray, fr: float, bpm: float, tightness: float = 100.0) -> np.ndarray:
    """Beat frame indices by dynamic programming (Ellis 2007)."""
    n = o.size
    if n == 0 or not bpm:
        return np.zeros(0, dtype=np.int64)
    period = 60.0 * fr / bpm
    lo_off = max(1, int(round(period / 2)))
    hi_off = max(lo_off + 1, int(round(2 * period)))
    # pen_rev[k] is the transition penalty for a predecessor hi_off - k frames back.
    pen_rev = (-tightness * np.log(np.arange(hi_off, lo_off - 1, -1) / period) ** 2)
    score = o.astype(np.float64).copy()
    back = np.full(n, -1, dtype=np.int64)
    for t in range(lo_off, n):
        s0 = t - hi_off
        if s0 >= 0:
            c = score[s0:t - lo_off + 1] + pen_rev
        else:
            c = score[0:t - lo_off + 1] + pen_rev[-s0:]
            s0 = 0
        j = int(c.argmax())
        if c[j] > 0:
            score[t] += c[j]
            back[t] = s0 + j
    # Start the backtrace at the best local maximum in the last period.
    tail = max(0, n - int(round(period)) - 1)
    t = tail + int(np.argmax(score[tail:]))
    beats = [t]
    while back[t] >= 0:
        t = int(back[t])
        beats.append(t)
    beats = np.array(beats[::-1], dtype=np.int64)
    # Drop beats outside the region that actually has onsets.
    strong = np.flatnonzero(o > 0.3 * np.percentile(o, 99)) if np.any(o > 0) else np.zeros(0, int)
    if strong.size:
        keep = (beats >= strong[0] - period / 2) & (beats <= strong[-1] + period / 2)
        beats = beats[keep]
    return beats


# --------------------------------------------------------------------------
# Key, tuning and tonic


def _chroma(y: np.ndarray, sr: float) -> tuple[np.ndarray, float, int]:
    """(12-bin chroma C..B, tuning in semitones, number of frames used)."""
    n_fft = _pow2(sr * 0.68)
    p = _erb.stft_power_frames(y, n_fft, n_fft // 2)
    mag = np.sqrt(p)
    f = np.arange(mag.shape[1]) * sr / n_fft
    sel = (f >= 55.0) & (f <= 2000.0)
    mag, f = mag[:, sel], f[sel]
    if mag.size == 0:
        return np.zeros(12), 0.0, 0
    midi = 69.0 + 12.0 * np.log2(f / 440.0)
    fe = mag.sum(axis=1)
    active = fe > (np.max(fe) * 1e-3 if fe.size else 0)
    m = mag[active]
    if m.shape[0] == 0:
        return np.zeros(12), 0.0, 0
    # Tuning: circular mean of the fractional pitch of spectral peaks.
    pk = (m[:, 1:-1] > m[:, :-2]) & (m[:, 1:-1] >= m[:, 2:]) & (m[:, 1:-1] > 0.05 * m.max(axis=1, keepdims=True))
    w = np.where(pk, m[:, 1:-1], 0.0).sum(axis=0)
    frac = midi[1:-1] - np.round(midi[1:-1])
    zc = np.sum(w * np.exp(2j * np.pi * frac))
    tuning = float(np.angle(zc) / (2 * np.pi)) if abs(zc) > 0 else 0.0
    adj = midi - tuning
    near = np.round(adj)
    wgt = np.exp(-0.5 * ((adj - near) / 0.25) ** 2)
    pc = (near.astype(np.int64)) % 12
    proj = np.zeros((m.shape[1], 12))
    proj[np.arange(m.shape[1]), pc] = wgt
    ch = m @ proj
    norms = np.linalg.norm(ch, axis=1, keepdims=True)
    ch = ch / np.maximum(norms, 1e-12)
    return ch.sum(axis=0), tuning, int(m.shape[0])


def estimate_key(chroma: np.ndarray) -> dict:
    """Krumhansl-Schmuckler key estimate from a 12-bin chroma (C..B)."""
    if not np.any(chroma > 0) or np.std(chroma) == 0:
        return {"key": None, "tonic_pc": None, "mode": None, "confidence": 0.0, "alternatives": []}
    scores = []
    for mode, prof in (("major", KK_MAJOR), ("minor", KK_MINOR)):
        for tonic in range(12):
            r = float(np.corrcoef(chroma, np.roll(prof, tonic))[0, 1])
            scores.append((r, tonic, mode))
    scores.sort(key=lambda s: -s[0])
    r1, tonic, mode = scores[0]
    r2 = scores[1][0]
    conf = _clip01(r1) * min(1.0, math.sqrt(max(0.0, r1 - r2) / 0.1))
    alts = [{"key": f"{PITCH_NAMES[t]} {m}", "correlation": float(r)} for r, t, m in scores[1:4]]
    return {"key": f"{PITCH_NAMES[tonic]} {mode}", "tonic_pc": tonic, "mode": mode,
            "confidence": _clip01(conf), "correlation": float(r1), "alternatives": alts}


def _tonic_bass(y: np.ndarray, sr: float, f1: float) -> tuple[float, str, list]:
    """Octave of the tonic where it stands out most below 200 Hz.

    Candidates f1 * 2^k below 200 Hz; prominence = level within +-0.5 semitone
    minus the mean level 1-3 semitones away. Falls back to the 40-80 Hz octave
    (typical bass register) when nothing stands out by 3 dB.
    """
    n_fft = _pow2(sr * 1.36)
    ps = _erb.mean_power_spectrum(y, n_fft)
    f = np.arange(ps.size) * sr / n_fft
    cands = []
    k = 0
    while f1 * 2 ** k < 200.0:
        fc = f1 * 2 ** k
        st = 12.0 * np.log2(np.maximum(f, 1e-6) / fc)
        core = np.abs(st) <= 0.5
        ring = (np.abs(st) >= 1.0) & (np.abs(st) <= 3.0)
        if core.any() and ring.any():
            lvl = 10 * math.log10(max(float(ps[core].sum()), 1e-30))
            ring_lvl = 10 * math.log10(max(float(ps[ring].mean() * core.sum()), 1e-30))
            cands.append({"hz": float(fc), "prominence_db": float(lvl - ring_lvl), "level_db": float(lvl)})
        k += 1
    good = [c for c in cands if c["prominence_db"] >= 3.0]
    if good:
        best = max(good, key=lambda c: c["level_db"])
        return best["hz"], "spectral_peak", cands
    fb = f1 * 2 if f1 * 2 < 80.0 else f1
    while fb < 40.0:
        fb *= 2
    return float(fb), "default_register", cands


# --------------------------------------------------------------------------
# Sections


def _min_section_s(duration: float, cfg: dict) -> float:
    lo = min(cfg["min_section_s"], duration / 3.0)
    return float(max(lo, min(duration * cfg["min_section_fraction_of_length"], cfg["max_min_section_s"])))


def _segment(y: np.ndarray, min_len: int, beta: float) -> list[int]:
    """Optimal piecewise-constant segmentation (least squares + beta per segment).

    Returns segment start indices (first is 0).
    """
    n = y.size
    if n < 2 * min_len:
        return [0]
    s1 = np.concatenate([[0.0], np.cumsum(y)])
    s2 = np.concatenate([[0.0], np.cumsum(y * y)])
    best = np.full(n + 1, np.inf)
    best[0] = 0.0
    arg = np.zeros(n + 1, dtype=np.int64)
    for j in range(min_len, n + 1):
        i = np.arange(0, j - min_len + 1)
        i = i[(i == 0) | (i >= min_len)]
        ln = j - i
        cost = (s2[j] - s2[i]) - (s1[j] - s1[i]) ** 2 / ln
        tot = best[i] + cost + beta
        k = int(np.argmin(tot))
        best[j], arg[j] = tot[k], i[k]
    starts = []
    j = n
    while j > 0:
        starts.append(int(arg[j]))
        j = int(arg[j])
    return sorted(starts)


def _floor_lufs(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    fin = v[np.isfinite(v)]
    top = float(fin.max()) if fin.size else -70.0
    floor = max(-70.0, top - 60.0)
    return np.where(np.isfinite(v), np.maximum(v, floor), floor)


def _mean_gated(v: np.ndarray) -> float | None:
    v = v[np.isfinite(v) & (v > -70.0)]
    return float(v.mean()) if v.size else None


def label_sections(sections: list[dict], cfg: dict | None = None) -> list[dict]:
    """Assign quiet / mid / loud from short_term_lufs_mean (in place, also returned)."""
    cfg = cfg or thresholds()["sections"]
    vals = [s["short_term_lufs_mean"] for s in sections if s.get("short_term_lufs_mean") is not None]
    if not vals:
        for s in sections:
            s["label"] = "mid"
        return sections
    lo, hi = min(vals), max(vals)
    q, l = cfg["label_split"]
    for s in sections:
        v = s.get("short_term_lufs_mean")
        if v is None:
            s["label"] = "quiet"
        elif hi - lo < cfg["min_change_db"]:
            s["label"] = "mid"
        else:
            pos = (v - lo) / (hi - lo)
            s["label"] = "quiet" if pos <= q else ("loud" if pos >= l else "mid")
    return sections


def section_levels(st: np.ndarray, sections: list[dict]) -> None:
    """Fill short_term_lufs_mean from a short-term loudness array (centres at 0.1 k + 1.5 s)."""
    centers = np.arange(st.size) * 0.1 + 1.5
    for s in sections:
        sel = (centers >= s["start_s"]) & (centers < s["end_s"])
        if not np.any(sel) and st.size:
            mid = 0.5 * (s["start_s"] + s["end_s"])
            sel = np.zeros(st.size, bool)
            sel[int(np.argmin(np.abs(centers - mid)))] = True
        s["short_term_lufs_mean"] = _mean_gated(st[sel]) if st.size else None


def detect_sections(x, sr: float, cfg: dict | None = None, *, loudness: dict | None = None) -> list[dict]:
    """Loudness sections [{start_s, end_s, label, short_term_lufs_mean}].

    `loudness` may carry precomputed {"momentary": array, "short_term": array}
    from mankomix.core.measure.loudness to avoid filtering the signal again.
    """
    cfg = cfg or thresholds()["sections"]
    a = _erb.as_frames(x)
    duration = a.shape[0] / float(sr)
    if duration <= 0:
        return []
    lz = loudness if loudness is not None else _erb.loudness_arrays(a, sr)
    mom, st = lz["momentary"], lz["short_term"]
    starts_s = [0.0]
    if mom.size >= 4:
        mom_f = _floor_lufs(mom)
        w = max(1, int(round(cfg["median_smoothing_s"] / 0.1))) | 1
        sm = median_filter(mom_f, size=w, mode="nearest")
        step = max(1, int(round(cfg["grid_s"] / 0.1)))
        g = sm[::step]
        gt = np.arange(g.size) * 0.1 * step + 0.2
        # 0.75: window edges eat part of a section of exactly the minimum length.
        min_len = max(1, int(0.75 * _min_section_s(duration, cfg) / (0.1 * step)))
        delta = cfg["min_change_db"]
        idx = _segment(g, min_len, beta=min_len * delta ** 2 / 4.0)
        # Merge neighbours whose levels differ by less than half the minimum change.
        bounds = idx + [g.size]
        means = [float(g[bounds[i]:bounds[i + 1]].mean()) for i in range(len(idx))]
        merged = [0]
        mvals = [means[0]]
        mlen = [bounds[1] - bounds[0]]
        for i in range(1, len(idx)):
            if abs(means[i] - mvals[-1]) < delta / 2.0:
                ln = bounds[i + 1] - bounds[i]
                mvals[-1] = (mvals[-1] * mlen[-1] + means[i] * ln) / (mlen[-1] + ln)
                mlen[-1] += ln
            else:
                merged.append(idx[i])
                mvals.append(means[i])
                mlen.append(bounds[i + 1] - bounds[i])
        starts_s = [0.0] + [float(0.5 * (gt[i - 1] + gt[i])) for i in merged[1:]]
    ends_s = starts_s[1:] + [duration]
    sections = [{"start_s": round(s0, 3), "end_s": round(s1, 3)} for s0, s1 in zip(starts_s, ends_s)]
    section_levels(st, sections)
    label_sections(sections, cfg)
    return [{"start_s": s["start_s"], "end_s": s["end_s"], "label": s["label"],
             "short_term_lufs_mean": s["short_term_lufs_mean"]} for s in sections]


# --------------------------------------------------------------------------
# Public entry point


def note_values_ms(bpm: float | None, beats_per_bar: int = 4) -> dict | None:
    """Note lengths in ms for a quarter-note tempo (R-11)."""
    if not bpm:
        return None
    q = 60000.0 / bpm
    return {
        "1bar": q * beats_per_bar, "1/2": q * 2, "1/4": q, "1/8": q / 2, "1/16": q / 4,
        "1/4.": q * 1.5, "1/8.": q * 0.75, "1/4T": q * 2 / 3, "1/8T": q / 3,
    }


def analyze_music(x, sr: float, *, loudness: dict | None = None) -> dict:
    """BPM, beats, key, tonic frequency, loudness sections and note values (SPEC 6.3).

    x: float array [frames, channels] (1-D = mono). Confidences are 0..1;
    `low_confidence` lists the estimates below the reporting threshold.
    `loudness`: optional precomputed {"momentary", "short_term"} LUFS arrays.
    """
    cfg = thresholds()
    mcfg = cfg["music"]
    a = _erb.as_frames(x)
    sr = float(sr)
    y, sra = _decimated_mono(a, sr)

    flux, flux_low, fr = onset_envelope(y, sra)
    o = _normalize_onset(flux, fr)
    tempo = estimate_tempo(o, fr, mcfg)
    bpm = tempo["bpm"]
    beat_frames = track_beats(o, fr, bpm) if bpm else np.zeros(0, dtype=np.int64)
    beats_s = [round(float(b) / fr, 4) for b in beat_frames]

    downbeats, db_conf = [], 0.0
    if beat_frames.size >= 8:
        lowo = _normalize_onset(flux_low, fr)
        acc = o + lowo
        strength = np.array([acc[max(0, b - 2):b + 3].max() for b in beat_frames])
        phase = [float(strength[p::4].mean()) for p in range(4)]
        order = np.argsort(phase)[::-1]
        bp = int(order[0])
        downbeats = beats_s[bp::4]
        if phase[bp] > 0:
            db_conf = _clip01((phase[bp] - phase[int(order[1])]) / phase[bp] / 0.3)
        db_conf *= tempo["confidence"]

    chroma, tuning, n_chroma = _chroma(y, sra)
    key = estimate_key(chroma)
    tonic = None
    if key["tonic_pc"] is not None:
        f1 = 440.0 * 2.0 ** ((key["tonic_pc"] - 9 + tuning) / 12.0)
        while f1 >= 40.0:
            f1 /= 2.0
        while f1 < 20.0:
            f1 *= 2.0
        fb, src, cands = _tonic_bass(y, sra, f1)
        sub_lo, sub_hi = mcfg["sub_band_hz"]
        tonic = {
            "tonic_hz": f1,
            "tonic_octave_above_hz": 2.0 * f1,
            "tonic_bass_hz": fb,
            "tonic_bass_source": src,
            "tonic_bass_candidates": cands,
            "tonic_in_sub_band": bool(sub_lo <= fb <= sub_hi),
            "small_speaker_loss": bool(fb < mcfg["small_speaker_loss_below_hz"]),
        }

    sections = detect_sections(a, sr, cfg["sections"], loudness=loudness)

    low_thr = mcfg["low_confidence_below"]
    low_conf = [name for name, c in (("bpm", tempo["confidence"]), ("key", key["confidence"]))
                if c < low_thr]
    out = {
        "bpm": bpm,
        "bpm_confidence": tempo["confidence"],
        "bpm_alternatives": tempo["alternatives"],
        "beats_s": beats_s,
        "downbeats_s": downbeats,
        "downbeat_confidence": db_conf,
        "meter_assumed": "4/4",
        "key": key["key"],
        "key_confidence": key["confidence"],
        "key_alternatives": key["alternatives"],
        "tuning_cents": round(100.0 * tuning, 1),
        "chroma": [float(v) for v in (chroma / chroma.max() if chroma.max() > 0 else chroma)],
        "tonic_hz": tonic["tonic_hz"] if tonic else None,
        "tonic_octave_above_hz": tonic["tonic_octave_above_hz"] if tonic else None,
        "tonic_bass_hz": tonic["tonic_bass_hz"] if tonic else None,
        "tonic_bass_source": tonic["tonic_bass_source"] if tonic else None,
        "tonic_in_sub_band": tonic["tonic_in_sub_band"] if tonic else None,
        "small_speaker_loss": tonic["small_speaker_loss"] if tonic else None,
        "sections": sections,
        "note_values": note_values_ms(bpm),
        "low_confidence": low_conf,
        "duration_s": a.shape[0] / sr,
        "analysis_sr": sra,
    }
    from ..measure.vector import json_safe
    return json_safe(out)
