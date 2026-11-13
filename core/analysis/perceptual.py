"""Mix-level perceptual proxy metrics on the 2mix (SPEC 4.2: P-01, P-11, P-17, P-19, P-20).

Every metric returns a JSON-safe dict with the measured value(s), the target
or range that was used, and `penalty` in [0, 1] when a target range applies
(0 inside the range, smooth rise towards 1 outside; see `range_penalty`).

Rules applied here:
- R-01: spectra are compared after normalising to a common integrated
  loudness; ratio-type metrics (P-11, P-17, P-19) are level-invariant.
- R-02: band evaluation on the ERB scale with ISO 226:2003 weights (erb.py).
- R-17: without a reference the P-01 target is a broad generic prior (pink-like
  tilt, wide tolerance), never the Harman curve; flagged `generic_prior`.
- R-26: section contrast is monitored for preservation (contrast_change).

Thresholds and ranges are initial values in knowledge/thresholds_m3.json.
"""

from __future__ import annotations

import math

import numpy as np

from . import erb as _erb
from . import music as _music

ANALYZER = "mankomix.analysis.perceptual/1"


def _cfg() -> dict:
    return _music.thresholds()


def _json_safe(obj):
    from ..measure.vector import json_safe
    return json_safe(obj)


# --------------------------------------------------------------------------
# Penalty shape


def range_penalty(value, lo=None, hi=None, scale: float = 1.0):
    """Penalty in [0, 1] for `value` against the range [lo, hi].

    0 inside the range (a None bound is open); outside, with d the distance to
    the nearest bound, 1 - exp(-(d / scale)^2): flat at the bound, about 0.63
    at one `scale` away, about 0.98 at two. Returns None for a missing or
    non-finite value. Works element-wise on arrays (then returns an array with
    nan for missing values).
    """
    if scale is None or not np.all(np.asarray(scale, dtype=np.float64) > 0):
        raise ValueError("scale must be > 0")
    if isinstance(value, (list, tuple, np.ndarray)):
        v = np.asarray(value, dtype=np.float64)
        lo_a = np.full_like(v, -np.inf) if lo is None else np.broadcast_to(np.asarray(lo, float), v.shape)
        hi_a = np.full_like(v, np.inf) if hi is None else np.broadcast_to(np.asarray(hi, float), v.shape)
        sc = np.broadcast_to(np.asarray(scale, float), v.shape)
        d = np.maximum(np.maximum(lo_a - v, v - hi_a), 0.0)
        return np.where(np.isfinite(v), 1.0 - np.exp(-(d / sc) ** 2), np.nan)
    if value is None:
        return None
    v = float(value)
    if not math.isfinite(v):
        return None
    d = 0.0
    if lo is not None and v < lo:
        d = lo - v
    elif hi is not None and v > hi:
        d = v - hi
    return float(1.0 - math.exp(-(d / scale) ** 2))


# --------------------------------------------------------------------------
# Shared analysis context


class _Ctx:
    """Caches the expensive intermediate results shared by the metrics."""

    def __init__(self, x, sr: float, loudness: dict | None = None):
        self.a = _erb.as_frames(x)
        self.sr = float(sr)
        self.y = self.a.mean(axis=1)
        self._lz = loudness
        self._frames = None
        self._ltas = None

    @property
    def lz(self) -> dict:
        if self._lz is None:
            self._lz = _erb.loudness_arrays(self.a, self.sr)
        if "integrated" not in self._lz:
            self._lz["integrated"] = _erb.integrated_from_momentary(self._lz["momentary"])
        return self._lz

    def level_match(self) -> dict:
        target = _cfg()["level_match"]["target_lufs"]
        gain, il = _erb.loudness_gain_db(self.a, self.sr, target, integrated_lufs=self.lz["integrated"])
        return {"target_lufs": target, "integrated_lufs": il, "gain_db": gain}

    def frames(self) -> dict:
        """Short-time ERB band powers (500 Hz .. 12 kHz) plus total and >4 kHz power."""
        if self._frames is None:
            sr = self.sr
            n_fft = 1 << int(round(math.log2(sr * 0.0427)))
            hop = n_fft // 2
            fmax = min(12000.0, 0.95 * sr / 2)
            edges, centers = _erb.erb_band_edges(sr, n_fft, fmin=500.0, fmax=fmax)
            m = _erb.band_matrix(sr, n_fft, edges)
            f = np.arange(n_fft // 2 + 1) * sr / n_fft
            hi_bins = f >= _cfg()["p20_contrast"]["high_band_hz"]

            def reduce(p):
                return np.column_stack([p @ m.T, p.sum(axis=1), p[:, hi_bins].sum(axis=1)])

            r = _erb.stft_power_frames(self.y, n_fft, hop, reducer=reduce)
            nb = centers.size
            times = (np.arange(r.shape[0]) * hop + n_fft / 2) / sr
            self._frames = {"bands": r[:, :nb], "total": r[:, nb], "high": r[:, nb + 1],
                            "centers": centers, "times": times, "n_fft": n_fft, "hop": hop}
        return self._frames

    def ltas(self) -> dict:
        if self._ltas is None:
            lm = self.level_match()
            step = _cfg()["erb"]["step_erb"]
            self._ltas = _erb.ltas_erb(self.a, self.sr, step=step, target_lufs=lm["target_lufs"],
                                       gain_db=lm["gain_db"])
            self._ltas["normalization"]["integrated_lufs"] = lm["integrated_lufs"]
        return self._ltas


def _db(p) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(np.asarray(p, dtype=np.float64), 1e-20))


def _active(power: np.ndarray, gate_db: float = 40.0) -> np.ndarray:
    if power.size == 0:
        return np.zeros(0, bool)
    top = float(np.percentile(power, 99))
    if top <= 0:
        return np.zeros(power.shape, bool)
    return power > max(top * 10.0 ** (-gate_db / 10.0), 1e-14)


def _band_mean_db(levels_db: np.ndarray, centers: np.ndarray, lo: float, hi: float) -> np.ndarray:
    sel = (centers >= lo) & (centers < hi)
    if not np.any(sel):
        sel = np.zeros(centers.shape, bool)
        sel[int(np.argmin(np.abs(np.log(centers / math.sqrt(lo * hi)))))] = True
    return levels_db[..., sel].mean(axis=-1)


# --------------------------------------------------------------------------
# P-01 LTAS deviation


def generic_prior(ltas: dict, sr: float) -> dict:
    """Broad generic P-01 prior on the same ERB bands as `ltas` (R-17: not Harman).

    Model power density: a -3 dB/octave tilt with gentle high-pass / low-pass
    band limits, integrated over each band. Median levels are shape-only (the
    caller removes the overall offset). Tolerance: iqr_db_mid inside the mid
    range, widening to iqr_db_edge towards the ends on the ERB scale.
    """
    c = _cfg()["p01_generic_prior"]
    n_fft = int(ltas["n_fft"])
    edges = np.asarray(ltas["edges_hz"], float)
    centers = np.asarray(ltas["centers_hz"], float)
    f = np.arange(n_fft // 2 + 1) * float(sr) / n_fft
    f = np.maximum(f, 1e-3)
    expo = c["tilt_db_per_octave"] / (10.0 * math.log10(2.0))
    psd = f ** expo
    psd = psd / (1.0 + (c["highpass_hz"] / f) ** (2 * c["highpass_order"]))
    psd = psd / (1.0 + (f / c["lowpass_hz"]) ** (2 * c["lowpass_order"]))
    med = _db(_erb.band_matrix(sr, n_fft, edges) @ psd)
    e = _erb.hz_to_erb_number(centers)
    e_lo, e_hi = _erb.hz_to_erb_number(np.asarray(c["mid_range_hz"], float))
    e_min, e_max = _erb.hz_to_erb_number(20.0), _erb.hz_to_erb_number(20000.0)
    t = np.where(e < e_lo, (e_lo - e) / max(e_lo - e_min, 1e-9),
                 np.where(e > e_hi, (e - e_hi) / max(e_max - e_hi, 1e-9), 0.0))
    iqr = c["iqr_db_mid"] + np.clip(t, 0.0, 1.0) * (c["iqr_db_edge"] - c["iqr_db_mid"])
    return {"centers_hz": centers, "median_db": med, "iqr_db": iqr, "source": "generic_prior",
            "shape_only": True}


def _align_reference(reference: dict, centers: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    med = np.asarray(reference["median_db"], dtype=np.float64)
    iqr = np.asarray(reference["iqr_db"], dtype=np.float64)
    rc = reference.get("centers_hz")
    if rc is not None:
        rc = np.asarray(rc, dtype=np.float64)
        if rc.shape != centers.shape or not np.allclose(rc, centers, rtol=1e-3):
            er, ec = _erb.hz_to_erb_number(rc), _erb.hz_to_erb_number(centers)
            med, iqr = np.interp(ec, er, med), np.interp(ec, er, iqr)
    if med.shape != centers.shape:
        raise ValueError(f"reference has {med.size} bands, LTAS has {centers.size}; "
                         "pass reference['centers_hz'] to interpolate")
    return med, iqr


def _ltas_deviation(ctx: _Ctx, reference: dict | None, phon: float | None) -> dict:
    cfg = _cfg()
    lt = ctx.ltas()
    centers = np.asarray(lt["centers_hz"])
    level = np.asarray(lt["level_db"])
    phon = cfg["erb"]["phon"] if phon is None else float(phon)
    w = _erb.perceptual_band_weights(centers, phon, floor=cfg["erb"]["importance_floor"])
    imp = w["importance"]
    generic = reference is None
    if generic:
        ref = generic_prior(lt, ctx.sr)
        med, iqr = ref["median_db"], ref["iqr_db"]
        shape_only = True
    else:
        med, iqr = _align_reference(reference, centers)
        shape_only = bool(reference.get("shape_only", False))
    raw = level - med
    if shape_only:
        lo, hi = cfg["p01_generic_prior"]["mid_range_hz"]
        mid = (centers >= lo) & (centers <= hi)
        offset = float(np.median(raw[mid] if np.any(mid) else raw))
    else:
        offset = 0.0
    dev = raw - offset
    half = np.maximum(iqr / 2.0, 0.0)
    scale = np.maximum(half, cfg["p01_generic_prior"]["penalty_scale_db_min"])
    band_pen = range_penalty(dev, -half, half, scale)
    band_pen = np.where(np.isfinite(band_pen), band_pen, 0.0)
    wsum = float(imp.sum())
    penalty = float(np.sum(imp * band_pen) / wsum)
    excess = np.maximum(np.abs(dev) - half, 0.0)
    order = np.argsort(-(imp * excess))
    largest = [{"center_hz": float(centers[i]), "deviation_db": float(dev[i]),
                "outside_by_db": float(excess[i]), "importance": float(imp[i])}
               for i in order[:5] if excess[i] > 0]
    return {
        "id": "P-01",
        "centers_hz": centers,
        "level_db": level,
        "reference": {"source": "generic_prior" if generic else reference.get("source", "reference"),
                      "median_db": med, "iqr_db": iqr, "shape_only": shape_only},
        "generic_prior": generic,
        "offset_db": offset,
        "deviation_db": dev,
        "band_penalty": band_pen,
        "weight_db": w["weight_db"],
        "importance": imp,
        "phon": phon,
        "weighted_rms_deviation_db": float(math.sqrt(np.sum(imp * dev ** 2) / wsum)),
        "weighted_excess_db": float(np.sum(imp * excess) / wsum),
        "largest_deviations": largest,
        "penalty": penalty,
        "level_match": lt["normalization"],
        "note": ("evaluated against a broad generic guide, not a genre target (SPEC 4.6)"
                 if generic else "evaluated against the given reference distribution"),
    }


def ltas_deviation(x, sr: float, reference: dict | None = None, *, phon: float | None = None) -> dict:
    """P-01: ERB-band LTAS deviation from a reference distribution, ISO 226 weighted.

    reference: {"median_db": [...], "iqr_db": [...], optional "centers_hz",
    "shape_only", "source"} measured with the same level match (ltas_erb at
    the thresholds' target_lufs). None uses the generic prior.
    """
    return _json_safe(_ltas_deviation(_Ctx(x, sr), reference, phon))


# --------------------------------------------------------------------------
# P-11 harshness / presence


def _harshness(ctx: _Ctx) -> dict:
    c = _cfg()["p11_harshness"]
    fr = ctx.frames()
    p, centers = fr["bands"], fr["centers"]
    act = _active(p.sum(axis=1))
    lo_r, h_r, up_r = c["lower_neighbour_hz"], c["band_hz"], c["upper_neighbour_hz"]
    gm = [math.sqrt(r[0] * r[1]) for r in (lo_r, h_r, up_r)]
    wt = math.log(gm[1] / gm[0]) / math.log(gm[2] / gm[0])

    def prominence(levels):
        lo = _band_mean_db(levels, centers, *lo_r)
        h = _band_mean_db(levels, centers, *h_r)
        up = _band_mean_db(levels, centers, *up_r)
        return h - (lo + wt * (up - lo))

    if not np.any(act):
        return {"id": "P-11", "active_frames": 0, "penalty": None,
                "presence": {"penalty": None}, "note": "no active signal"}
    prom_t = prominence(_db(p[act]))
    prom_ltas = float(prominence(_db(p[act].mean(axis=0))))
    pct = float(100.0 * np.mean(prom_t > c["frame_threshold_db"]))
    lo, hi = c["ltas_prominence_range_db"]
    pen_ltas = range_penalty(prom_ltas, lo, hi, c["ltas_penalty_scale_db"])
    plo, phi = c["peaky_frame_pct_range"]
    pen_peaky = range_penalty(pct, plo, phi, c["peaky_frame_pct_scale"])
    prl, prh = c["presence_range_db"]
    return {
        "id": "P-11",
        "band_hz": h_r,
        "neighbour_bands_hz": [lo_r, up_r],
        "ltas_prominence_db": prom_ltas,
        "frame_prominence_median_db": float(np.median(prom_t)),
        "frame_prominence_p95_db": float(np.percentile(prom_t, 95)),
        "peaky_frame_pct": pct,
        "frame_threshold_db": c["frame_threshold_db"],
        "range": {"ltas_prominence_db": [lo, hi], "peaky_frame_pct": [plo, phi]},
        "penalty_ltas": pen_ltas,
        "penalty_peaky": pen_peaky,
        "penalty": max(pen_ltas, pen_peaky),
        "presence": {
            "value_db": prom_ltas,
            "range_db": [prl, prh],
            "deficit_db": max(0.0, prl - prom_ltas),
            "excess_db": max(0.0, prom_ltas - prh),
            "penalty": range_penalty(prom_ltas, prl, prh, c["presence_penalty_scale_db"]),
        },
        "active_frames": int(act.sum()),
        "level_invariant": True,
    }


def harshness(x, sr: float) -> dict:
    """P-11: 2-5 kHz prominence over neighbouring bands (long-term and per frame).

    `penalty` = max(long-term excess, share of peaky frames); `presence` is the
    two-sided version (deficit and excess) used by OF-3.
    """
    return _json_safe(_harshness(_Ctx(x, sr)))


# --------------------------------------------------------------------------
# P-17 sibilance


def _sibilance(ctx: _Ctx) -> dict:
    c = _cfg()["p17_sibilance"]
    fr = ctx.frames()
    p, centers = fr["bands"], fr["centers"]
    sib_sel = (centers >= c["band_hz"][0]) & (centers < c["band_hz"][1])
    sib_pow = p[:, sib_sel].sum(axis=1) if np.any(sib_sel) else np.zeros(p.shape[0])
    act = _active(sib_pow, c["active_gate_db"]) & _active(p.sum(axis=1))
    if not np.any(act):
        return {"id": "P-17", "active_frames": 0, "penalty": None, "note": "no active signal"}
    lv = _db(p)
    r = _band_mean_db(lv, centers, *c["band_hz"]) - _band_mean_db(lv, centers, *c["reference_hz"])
    base = float(np.median(r[act]))
    exc = r - base
    ev = act & (exc > c["event_threshold_db"])
    d = np.diff(np.concatenate([[0], ev.astype(np.int8), [0]]))
    n_events = int(np.sum(d == 1))
    dur_min = (fr["times"][-1] + fr["n_fft"] / 2 / ctx.sr) / 60.0 if fr["times"].size else 0.0
    pct = float(100.0 * ev.sum() / act.sum())
    p99 = float(np.percentile(exc[act], 99))
    lo, hi = c["peak_prominence_range_db"]
    elo, ehi = c["event_pct_range"]
    pen_peak = range_penalty(p99, lo, hi, c["peak_prominence_scale_db"])
    pen_pct = range_penalty(pct, elo, ehi, c["event_pct_scale"])
    return {
        "id": "P-17",
        "band_hz": c["band_hz"],
        "reference_hz": c["reference_hz"],
        "baseline_ratio_db": base,
        "p99_prominence_db": p99,
        "max_prominence_db": float(np.max(exc[act])),
        "event_pct": pct,
        "events": n_events,
        "events_per_min": n_events / dur_min if dur_min > 0 else None,
        "event_threshold_db": c["event_threshold_db"],
        "range": {"p99_prominence_db": [lo, hi], "event_pct": [elo, ehi]},
        "penalty": max(pen_peak, pen_pct),
        "active_frames": int(act.sum()),
        "level_invariant": True,
        "note": "frame-level 5-8 kHz vs 1-4 kHz ratio on the full mix; cymbals can also trigger it",
    }


def sibilance(x, sr: float) -> dict:
    """P-17: prominence of 5-8 kHz sibilant events (frame band-ratio peaks)."""
    return _json_safe(_sibilance(_Ctx(x, sr)))


# --------------------------------------------------------------------------
# P-19 spectral smoothness


def _fractional_octave_levels(ps: np.ndarray, sr: float, n_fft: int, f_lo: float, f_hi: float,
                              per_octave: int) -> tuple[np.ndarray, np.ndarray]:
    k0 = int(math.ceil(per_octave * math.log2(f_lo / 1000.0)))
    k1 = int(math.floor(per_octave * math.log2(f_hi / 1000.0)))
    k = np.arange(k0, k1 + 1)
    centers = 1000.0 * 2.0 ** (k / per_octave)
    edges = 1000.0 * 2.0 ** ((np.arange(k0, k1 + 2) - 0.5) / per_octave)
    m = _erb.band_matrix(sr, n_fft, edges)
    return centers, m @ ps


def _smoothness(ctx: _Ctx) -> dict:
    c = _cfg()["p19_smoothness"]
    sr = ctx.sr
    n_fft = 1 << int(round(math.log2(sr * 0.68)))
    ps = _erb.mean_power_spectrum(ctx.y, n_fft)
    f_lo, f_hi = c["range_hz"]
    f_hi = min(f_hi, 0.45 * sr)
    per_oct = int(round(1.0 / c["fine_resolution_oct"]))
    centers, bp = _fractional_octave_levels(ps, sr, n_fft, f_lo, f_hi, per_oct)
    if centers.size < 8 or not np.any(bp > 0):
        return {"id": "P-19", "penalty": None, "note": "not enough signal or bandwidth"}
    # Smoothing over `smooth_resolution_oct` (mean of dB levels, half weights at the
    # ends). Averaging dB rather than power keeps a narrow peak from lifting its
    # own baseline.
    n_side = int(round(c["smooth_resolution_oct"] * per_oct / 2.0))
    ker = np.ones(2 * n_side + 1)
    ker[0] = ker[-1] = 0.5
    fine = _db(bp)
    smooth = np.convolve(fine, ker, mode="same") / np.convolve(np.ones_like(fine), ker, mode="same")
    dev = fine - smooth
    thr = c["resonance_threshold_db"]
    pk = np.flatnonzero((dev[1:-1] > dev[:-2]) & (dev[1:-1] >= dev[2:]) & (dev[1:-1] > thr)) + 1
    nt = np.flatnonzero((dev[1:-1] < dev[:-2]) & (dev[1:-1] <= dev[2:]) & (dev[1:-1] < -thr)) + 1
    res = sorted(({"freq_hz": float(centers[i]), "excess_db": float(dev[i])} for i in pk),
                 key=lambda d: -d["excess_db"])
    notches = sorted(({"freq_hz": float(centers[i]), "depth_db": float(-dev[i])} for i in nt),
                     key=lambda d: -d["depth_db"])
    rms = float(np.sqrt(np.mean(dev ** 2)))
    peak = float(np.max(dev))
    lo, hi = c["rms_dev_range_db"]
    plo, phi = c["max_peak_range_db"]
    pen_rms = range_penalty(rms, lo, hi, c["rms_dev_scale_db"])
    pen_peak = range_penalty(peak, plo, phi, c["max_peak_scale_db"])
    return {
        "id": "P-19",
        "range_hz": [f_lo, f_hi],
        "resolution_oct": {"fine": 1.0 / per_oct, "smooth": c["smooth_resolution_oct"]},
        "rms_deviation_db": rms,
        "max_peak_db": peak,
        "max_notch_db": float(-np.min(dev)),
        "resonance_threshold_db": thr,
        "resonance_count": len(res),
        "notch_count": len(notches),
        "resonances": res[:10],
        "notches": notches[:10],
        "range": {"rms_deviation_db": [lo, hi], "max_peak_db": [plo, phi]},
        "penalty_rms": pen_rms,
        "penalty_peak": pen_peak,
        "penalty": max(pen_rms, pen_peak),
        "level_invariant": True,
        "note": ("transferred from loudspeaker preference research (smoothness); "
                 "tonal music shows note peaks at semitone resolution"),
    }


def spectral_smoothness(x, sr: float) -> dict:
    """P-19: unevenness of the 1/12-octave LTAS around its 1/3-octave smoothed version."""
    return _json_safe(_smoothness(_Ctx(x, sr)))


# --------------------------------------------------------------------------
# P-20 section contrast


def _group_level(sections: list[dict], label: str) -> float | None:
    num = den = 0.0
    for s in sections:
        v = s.get("short_term_lufs_mean")
        if s.get("label") == label and v is not None:
            d = max(float(s["end_s"]) - float(s["start_s"]), 1e-6)
            num += v * d
            den += d
    return num / den if den > 0 else None


def _section_contrast(ctx: _Ctx, sections: list[dict] | None) -> dict:
    lz = ctx.lz
    st = np.asarray(lz["short_term"], dtype=np.float64)
    if sections is None:
        secs = _music.detect_sections(ctx.a, ctx.sr, loudness=lz)
        given = False
    else:
        secs = [{"start_s": float(s["start_s"]), "end_s": float(s["end_s"]), "label": s.get("label")}
                for s in sections]
        _music.section_levels(st, secs)
        if any(s["label"] is None for s in secs):
            _music.label_sections(secs)
        given = True
    loud, quiet = _group_level(secs, "loud"), _group_level(secs, "quiet")
    contrast = loud - quiet if loud is not None and quiet is not None else None

    fr = ctx.frames()
    t = fr["times"]

    def high_share(label):
        sel = np.zeros(t.shape, bool)
        for s in secs:
            if s["label"] == label:
                sel |= (t >= s["start_s"]) & (t < s["end_s"])
        tot = float(fr["total"][sel].sum())
        return 10.0 * math.log10(max(float(fr["high"][sel].sum()), 1e-30) / tot) if tot > 0 else None

    hs_loud, hs_quiet = high_share("loud"), high_share("quiet")
    opening = hs_loud - hs_quiet if hs_loud is not None and hs_quiet is not None else None
    stg = st[np.isfinite(st) & (st > -70.0)]
    spread = float(np.percentile(stg, 90) - np.percentile(stg, 10)) if stg.size else None
    return {
        "id": "P-20",
        "sections": secs,
        "sections_given": given,
        "loud_lufs": loud,
        "quiet_lufs": quiet,
        "contrast_db": contrast,
        "has_contrast": contrast is not None,
        "high_band_hz": _cfg()["p20_contrast"]["high_band_hz"],
        "high_share_db": {"loud": hs_loud, "quiet": hs_quiet},
        "opening_db": opening,
        "short_term_p90_p10_db": spread,
        "penalty": None,
        "note": "no absolute target; compare before/after with contrast_change (R-26)",
    }


def section_contrast(x, sr: float, sections: list[dict] | None = None) -> dict:
    """P-20: loud-vs-quiet short-term loudness difference and high-band opening.

    sections: [{start_s, end_s, label}] to measure on fixed boundaries (pass the
    `sections` of the before-measurement when measuring the processed signal);
    None detects them from short-term loudness.
    """
    return _json_safe(_section_contrast(_Ctx(x, sr), sections))


def contrast_change(before: dict, after: dict) -> dict:
    """Compare two P-20 results (before / after processing) for contrast loss (R-26).

    shrink_db > 0 means the loud-quiet difference got smaller. `warning` when
    it exceeds warn_shrink_db (knowledge/thresholds_m3.json). Measure `after`
    with the sections of `before` so both use the same boundaries.
    """
    c = _cfg()["p20_contrast"]
    b, a = before.get("contrast_db"), after.get("contrast_db")
    shrink = b - a if b is not None and a is not None else None
    ob, oa = before.get("opening_db"), after.get("opening_db")
    o_shrink = ob - oa if ob is not None and oa is not None else None

    def bounds(r):
        return [(round(float(s["start_s"]), 2), round(float(s["end_s"]), 2)) for s in r.get("sections", [])]

    out = {
        "id": "P-20",
        "contrast_before_db": b,
        "contrast_after_db": a,
        "shrink_db": shrink,
        "warn_shrink_db": c["warn_shrink_db"],
        "warning": bool(shrink is not None and shrink > c["warn_shrink_db"]),
        "opening_before_db": ob,
        "opening_after_db": oa,
        "opening_shrink_db": o_shrink,
        "opening_warning": bool(o_shrink is not None and o_shrink > c["warn_opening_shrink_db"]),
        "sections_match": bounds(before) == bounds(after),
        "penalty": range_penalty(shrink, None, c["penalty_free_shrink_db"], c["penalty_scale_db"]),
        "range": {"shrink_db": [None, c["penalty_free_shrink_db"]]},
    }
    return _json_safe(out)


# --------------------------------------------------------------------------
# Bundle


def measure_mix_perceptual(x, sr: float, *, reference: dict | None = None,
                           sections: list[dict] | None = None, phon: float | None = None) -> dict:
    """All 2mix perceptual proxies plus music information.

    Keys: "P-01", "P-11", "P-17", "P-19", "P-20", "music", "level_match", "analyzer".
    """
    ctx = _Ctx(x, sr)
    mus = _music.analyze_music(ctx.a, ctx.sr, loudness=ctx.lz)
    secs = sections if sections is not None else mus.get("sections")
    out = {
        "analyzer": ANALYZER,
        "level_match": ctx.level_match(),
        "P-01": _ltas_deviation(ctx, reference, phon),
        "P-11": _harshness(ctx),
        "P-17": _sibilance(ctx),
        "P-19": _smoothness(ctx),
        "P-20": _section_contrast(ctx, secs),
        "music": mus,
    }
    if sections is None:
        out["P-20"]["sections_given"] = False
    return _json_safe(out)
