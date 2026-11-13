"""Stem-level and inter-stem proxy metrics (SPEC 4.2, 4.11, 6.3, 8.1).

Proxies implemented here (all [model]/[practice] unless noted; constants live
in knowledge/masking_model.json and are calibration targets):

- ``stem_features``          per-stem level, centroid, lowest f0, harmonic
                             ratio, crest, activity, pan/width, blind D/R
- P-02 ``masking_matrix``    ERB-band excitation with a level-dependent
                             two-slope Bark spreading function; "buried dB"
                             per band / target; vs_lead, overall
                             (importance-weighted, 4.11), low_to_mid,
                             time_axis (kick vs bass, sidechain simulation)
- P-08 ``harmonic_completion`` / ``missing_fundamental_check``
- P-09 ``depth_order``       depth score and Kendall tau vs a declared order
- P-10 ``lead_band_difference``
- P-12 ``transient_retention``
- P-13 ``low_tuning``        kick/bass cents (standard formula), tonic band
- P-15 ``reverb_metrics``    blind D/R and band RT60 (rough)
- P-22 ``band_density``      owners per band and section
- ``measure_stem_context``   bundles everything

Input conventions: stems are ``{track_id: float array [frames, channels]}``
(1-D = mono) at one sample rate and head-aligned; shorter stems are treated as
zero-padded at the end. ``meta`` is ``{track_id: {role, is_lead, importance}}``
where importance is a number or the project form ``{"value", "by_section"}``.
Sections are ``{"id", "start", "length"}`` in samples (project form) or
``{"id", "start_s", "end_s"}`` in seconds.

Every public function returns a JSON-safe dict (no NaN / inf; numpy types
converted). Implemented with numpy/scipy only (no librosa).
"""

from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
from scipy import fft as sfft
from scipy import signal as ss
from scipy.stats import kendalltau

from ..config import load_genre_priors, load_knowledge
from ..errors import InputError
from . import erb as _erb

try:  # shared penalty shape (written by the perceptual module)
    from .perceptual import range_penalty as _shared_range_penalty  # type: ignore
except Exception:  # pragma: no cover - module not present yet
    _shared_range_penalty = None

_EPS = 1e-20
_DB_FLOOR = -200.0

P22_ORDER = ("sub", "bass", "lowmid", "mid", "highmid", "air")


# --------------------------------------------------------------------------
# Small helpers


def _model() -> dict:
    return load_knowledge("masking_model")


def _range_penalty(value, lo, hi, scale) -> float | None:
    """0 inside [lo, hi]; outside 1 - exp(-(d / scale)^2) (same shape as perceptual.range_penalty)."""
    if value is None or not np.isfinite(value):
        return None
    if _shared_range_penalty is not None:
        try:
            p = float(_shared_range_penalty(float(value), lo, hi, scale))
            if math.isfinite(p):
                return min(1.0, max(0.0, p))
        except Exception:
            pass
    v = float(value)
    if v < lo:
        d = lo - v
    elif v > hi:
        d = v - hi
    else:
        return 0.0
    return float(1.0 - math.exp(-(d / max(float(scale), 1e-12)) ** 2))


def _clean(o: Any) -> Any:
    """Recursively convert to JSON-safe builtins (NaN / inf -> None)."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return round(f, 4) if math.isfinite(f) else None
    return o


def _as_frames(x) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    if a.ndim != 2:
        raise InputError(f"audio must be 1-D or 2-D [frames, channels], got shape {a.shape}")
    if a.shape[1] > 64 and a.shape[0] <= 64:
        raise InputError(f"audio looks like [channels, frames] (shape {a.shape}); expected [frames, channels]")
    if a.size and not np.isfinite(a).all():
        raise InputError("audio contains NaN or infinite samples")
    return a


def _db(p) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(np.asarray(p, dtype=np.float64), _EPS))


def _dbs(p) -> float | None:
    """Scalar power -> dB, None for silence."""
    if p is None or not np.isfinite(p) or p <= _EPS:
        return None
    return float(10.0 * math.log10(p))


def _pmap(fn, items: list) -> list:
    """Order-preserving map over stems; numpy/scipy FFT and filters release the GIL."""
    items = list(items)
    workers = min(len(items), max(1, (os.cpu_count() or 2) - 1), 8)
    if workers <= 1:
        return [fn(i) for i in items]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def _decimate(x: np.ndarray, sr: float, target: float) -> tuple[np.ndarray, float]:
    q = max(1, int(sr // target))
    if q == 1:
        return x, float(sr)
    return ss.resample_poly(x, 1, q), float(sr) / q


def _gate(levels_db: np.ndarray, valid: np.ndarray, abs_db: float, rel_db: float) -> np.ndarray:
    """Activity gate: above abs_db and above (p95 - rel_db)."""
    v = levels_db[valid & (levels_db > _DB_FLOOR + 1)]
    if v.size == 0:
        return np.zeros_like(levels_db, dtype=bool)
    thr = max(abs_db, float(np.percentile(v, 95)) - rel_db)
    return valid & (levels_db >= thr)


def _intervals(mask: np.ndarray, hop_s: float, frame_s: float, merge_gap_s: float,
               min_len_s: float, max_n: int = 200) -> list[list[float]]:
    out: list[list[float]] = []
    if not mask.any():
        return out
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    for s, e in zip(starts, ends):
        t0, t1 = s * hop_s, (e - 1) * hop_s + frame_s
        if out and t0 - out[-1][1] <= merge_gap_s:
            out[-1][1] = t1
        else:
            out.append([t0, t1])
    out = [iv for iv in out if iv[1] - iv[0] >= min_len_s]
    return [[round(a, 3), round(b, 3)] for a, b in out[:max_n]]


def _parse_sections(sections, sr: float, n: int) -> list[dict]:
    if not sections:
        return [{"id": "all", "start": 0, "end": n}]
    out = []
    for i, s in enumerate(sections):
        if isinstance(s, dict):
            sid = str(s.get("id", f"section_{i}"))
            if "start" in s and "length" in s:
                a, b = int(s["start"]), int(s["start"]) + int(s["length"])
            elif "start_s" in s and "end_s" in s:
                a, b = int(round(float(s["start_s"]) * sr)), int(round(float(s["end_s"]) * sr))
            else:
                raise InputError(f"section {sid} needs start/length (samples) or start_s/end_s")
        elif isinstance(s, (list, tuple)) and len(s) == 2:
            sid = f"section_{i}"
            a, b = int(round(float(s[0]) * sr)), int(round(float(s[1]) * sr))
        else:
            raise InputError(f"cannot parse section {s!r}")
        a, b = max(0, a), min(n, b)
        if b > a:
            out.append({"id": sid, "start": a, "end": b})
    return out or [{"id": "all", "start": 0, "end": n}]


def _frame_power_series(p: np.ndarray, frame: int, hop: int, n_frames: int) -> np.ndarray:
    """Mean of a per-sample power series over frames [k*hop, k*hop+frame)."""
    cs = np.concatenate([[0.0], np.cumsum(p)])
    st = np.arange(n_frames) * hop
    a = np.minimum(st, p.size)
    b = np.minimum(st + frame, p.size)
    return (cs[b] - cs[a]) / frame


# --------------------------------------------------------------------------
# Periodicity (YIN) on a decimated, low-passed mono signal


def _yin(x: np.ndarray, sr: float, *, fmin: float = 25.0, fmax: float = 1000.0,
         thresh: float = 0.15, voiced_max: float = 0.35, hop_s: float = 0.025,
         gate_abs_db: float = -60.0, gate_rel_db: float = 40.0) -> dict:
    """YIN (de Cheveigne & Kawahara 2002) with parabolic refinement.

    The signal is decimated to ~4 kHz first (anti-alias low-pass ~1.8 kHz),
    which is the 'low-passed signal' used for the lowest-f0 estimate.
    """
    xd, srd = _decimate(np.asarray(x, dtype=np.float64), sr, 4000.0)
    tau_max = int(math.ceil(srd / fmin))
    tau_min = max(2, int(math.floor(srd / fmax)))
    W = int(round(srd * 2.0 / fmin))
    N = W + tau_max + 2
    hop = max(1, int(round(srd * hop_s)))
    if xd.size < N:
        xd = np.pad(xd, (0, N - xd.size))
    n_fr = 1 + (xd.size - N) // hop
    fr = np.lib.stride_tricks.sliding_window_view(xd, N)[::hop][:n_fr]
    M = sfft.next_fast_len(N + W)
    taus = np.arange(tau_max + 2)
    f0 = np.full(n_fr, np.nan)
    aper = np.ones(n_fr)
    e0_all = np.zeros(n_fr)
    chunk = 512
    for c0 in range(0, n_fr, chunk):
        f = fr[c0:c0 + chunk]
        A = sfft.rfft(f[:, :W], M, axis=1)
        B = sfft.rfft(f, M, axis=1)
        cc = sfft.irfft(np.conj(A) * B, M, axis=1)[:, :tau_max + 2]
        cs = np.concatenate([np.zeros((f.shape[0], 1)), np.cumsum(f * f, axis=1)], axis=1)
        e0 = cs[:, W]
        et = cs[:, taus + W] - cs[:, taus]
        d = np.maximum(e0[:, None] + et - 2.0 * cc, 0.0)
        d[:, 0] = 0.0
        cum = np.cumsum(d[:, 1:], axis=1)
        dp = np.ones_like(d)
        dp[:, 1:] = d[:, 1:] * taus[1:][None, :] / np.maximum(cum, _EPS)
        seg = dp[:, tau_min:tau_max + 1]
        below = seg < thresh
        has = below.any(axis=1)
        idx = np.where(has, np.argmax(below, axis=1), np.argmin(seg, axis=1)) + tau_min
        rows = np.arange(f.shape[0])
        for _ in range(tau_max):
            nxt = np.minimum(idx + 1, tau_max)
            move = (nxt > idx) & (dp[rows, nxt] < dp[rows, idx])
            if not move.any():
                break
            idx = np.where(move, nxt, idx)
        y0 = dp[rows, np.maximum(idx - 1, 1)]
        y1 = dp[rows, idx]
        y2 = dp[rows, np.minimum(idx + 1, tau_max + 1)]
        den = y0 - 2.0 * y1 + y2
        shift = np.where(den > 1e-12, 0.5 * (y0 - y2) / np.where(den > 1e-12, den, 1.0), 0.0)
        shift = np.clip(shift, -1.0, 1.0)
        tau_f = idx + shift
        ymin = np.clip(y1 - 0.25 * (y0 - y2) * shift, 0.0, 1.0)
        f0[c0:c0 + chunk] = srd / tau_f
        aper[c0:c0 + chunk] = ymin
        e0_all[c0:c0 + chunk] = e0 / W
    lev = _db(e0_all)
    active = _gate(lev, np.ones(n_fr, dtype=bool), gate_abs_db, gate_rel_db)
    voiced = active & (aper < voiced_max) & (f0 >= fmin * 0.98) & (f0 <= fmax * 1.02)
    f0v = np.where(voiced, f0, np.nan)
    t = (np.arange(n_fr) * hop + W / 2.0) / srd
    return {"t": t, "f0": f0v, "f0_raw": f0, "aper": aper, "active": active, "voiced": voiced,
            "level_db": lev, "xd": xd, "srd": srd, "hop": hop, "W": W}


def _f0_summary(y: dict) -> dict:
    v = y["f0"][y["voiced"]]
    n_act = int(y["active"].sum())
    if v.size == 0 or n_act == 0:
        return {"lowest_f0_hz": None, "median_f0_hz": None, "f0_confidence": 0.0,
                "voiced_fraction": 0.0}
    clarity = 1.0 - y["aper"][y["voiced"]]
    vf = v.size / n_act
    return {
        "lowest_f0_hz": float(np.percentile(v, 5)),
        "median_f0_hz": float(np.median(v)),
        "f0_confidence": float(np.clip(vf * float(np.mean(clarity)), 0.0, 1.0)),
        "voiced_fraction": float(vf),
    }


# --------------------------------------------------------------------------
# Envelope-based blind D/R and pre-delay proxy


def _envelope(p: np.ndarray, sr: float, block_s: float) -> np.ndarray:
    blk = max(1, int(round(sr * block_s)))
    nb = p.size // blk
    if nb == 0:
        return np.zeros(1)
    return p[:nb * blk].reshape(nb, blk).mean(axis=1)


def _dr_estimate(p: np.ndarray, sr: float, model: dict) -> dict:
    """Blind direct-to-reverberant estimate from an energy envelope.

    For each prominent envelope peak (onset), early energy = [-10 ms, +early]
    and late energy = [+early, min(next onset, +late)]. D/R = median of
    10*log10(early / late). Sustained notes count as 'late': sustained
    instruments read as reverberant (caveat). The pre-delay proxy is the time
    after the peak where the dB decay flattens (knee between the direct decay
    and the tail); it is very rough.
    """
    cfg = model["p09"]
    blk_s = 0.005
    env = _envelope(p, sr, blk_s)
    env_db = _db(env)
    valid = env > _EPS
    if valid.sum() < 10:
        return {"dr_db": None, "pre_delay_ms": None, "n_events": 0}
    thr = max(model["activity_gate"]["abs_dbfs"], float(np.percentile(env_db[valid], 95)) - 30.0)
    peaks, _ = ss.find_peaks(env_db, prominence=10.0, distance=int(0.1 / blk_s), height=thr)
    e_n = int(cfg["early_window_ms"] / 1000 / blk_s)
    l_n = int(cfg["late_window_ms"] / 1000 / blk_s)
    min_l = int(cfg["min_late_window_ms"] / 1000 / blk_s)
    smooth = np.convolve(env_db, np.ones(3) / 3.0, mode="same")
    drs, knees = [], []
    for i, pk in enumerate(peaks):
        nxt = peaks[i + 1] if i + 1 < len(peaks) else env.size
        a = max(0, pk - 2)
        b = pk + e_n
        c = min(nxt - 2, pk + l_n, env.size)
        if c - b < min_l:
            continue
        early = env[a:b].sum()
        late = env[b:c].sum()
        if early > _EPS and late > _EPS:
            drs.append(10.0 * math.log10(early / late))
        # knee: slope (dB per 10 ms) drops below 30 % of the steepest early slope
        seg = smooth[pk:min(pk + 30, c)]
        if seg.size >= 8:
            sl = seg[2:] - seg[:-2]
            steep = float(np.min(sl[:6]))
            if steep < -1.0:
                k = np.flatnonzero(sl[2:] > 0.3 * steep)
                if k.size:
                    knees.append((k[0] + 2) * blk_s * 1000.0)
    if len(drs) < int(cfg["min_events"]):
        return {"dr_db": None, "pre_delay_ms": None, "n_events": len(drs)}
    return {"dr_db": float(np.median(drs)),
            "pre_delay_ms": float(np.median(knees)) if knees else None,
            "n_events": len(drs)}


# --------------------------------------------------------------------------
# stem_features


def _features_full(x, sr: float, model: dict) -> tuple[dict, dict]:
    a = _as_frames(x)
    sr = float(sr)
    n, nch = a.shape
    m = a.mean(axis=1)
    p = (a * a).mean(axis=1)
    an = model["analysis"]
    gate = model["activity_gate"]
    frame = max(16, int(round(an["frame_s"] * sr)))
    hop = max(1, int(round(frame * an["hop_fraction"])))
    n_fr = max(1, int(math.ceil(max(n - frame, 0) / hop)) + 1)
    fp = _frame_power_series(p, frame, hop, n_fr)
    lev = _db(fp)
    active = _gate(lev, np.ones(n_fr, dtype=bool), gate["abs_dbfs"], gate["rel_db_below_p95"])
    peak = float(np.max(np.abs(a))) if a.size else 0.0
    rms_all = float(p.mean()) if p.size else 0.0
    rms_act = float(fp[active].mean()) if active.any() else 0.0
    lufs = None
    try:
        from ..measure.loudness import integrated as _integrated
        v = float(_integrated(a, sr))
        lufs = v if math.isfinite(v) else None
    except Exception:
        lufs = None
    # spectrum: centroid and high-frequency ratio
    centroid = hf_ratio = None
    if n >= 256 and rms_all > _EPS:
        nper = min(4096, 1 << int(math.floor(math.log2(n))))
        f, pxx = ss.welch(m, fs=sr, nperseg=nper, noverlap=0, detrend=False)
        tot = float(pxx.sum())
        if tot > _EPS:
            centroid = float((f * pxx).sum() / tot)
            hf_ratio = float(pxx[f >= model["regions_hz"]["hf_ratio_above"]].sum() / tot)
    # periodicity
    y = _yin(m, sr, gate_abs_db=gate["abs_dbfs"])
    f0s = _f0_summary(y)
    harm = float(np.mean(1.0 - y["aper"][y["active"]])) if y["active"].any() else None
    # pan / width
    if nch >= 2:
        L, R = a[:, 0], a[:, 1]
        el, er = float(L @ L), float(R @ R)
        mid, side = 0.5 * (L + R), 0.5 * (L - R)
        em, es = float(mid @ mid), float(side @ side)
        pan = (er - el) / (er + el) if er + el > _EPS else 0.0
        corr = float(L @ R) / math.sqrt(el * er) if el > _EPS and er > _EPS else None
        width = es / (em + es) if em + es > _EPS else 0.0
        pan_db = 10 * math.log10(er / el) if el > _EPS and er > _EPS else None
    else:
        pan, corr, width, pan_db = 0.0, 1.0, 0.0, 0.0
    dr = _dr_estimate(p, sr, model)
    peak_db = 20 * math.log10(peak) if peak > 0 else None
    act_db = _dbs(rms_act)
    feats = {
        "duration_s": n / sr,
        "channels": nch,
        "level": {
            "lufs_integrated": lufs,
            "rms_dbfs": _dbs(rms_all),
            "active_rms_dbfs": act_db,
            "peak_dbfs": peak_db,
        },
        "spectral_centroid_hz": centroid,
        "hf_ratio": hf_ratio,
        "f0": f0s,
        "harmonic_ratio": harm,
        "crest_db": (peak_db - act_db) if peak_db is not None and act_db is not None else None,
        "activity": {
            "ratio": float(active.mean()) if n_fr else 0.0,
            "intervals_s": _intervals(active, hop / sr, frame / sr, gate["merge_gap_s"],
                                      gate["min_interval_s"]),
        },
        "stereo": {"pan": pan, "pan_db": pan_db, "correlation": corr, "width_side_ratio": width},
        "dr": {"dr_db": dr["dr_db"], "pre_delay_ms": dr["pre_delay_ms"], "n_events": dr["n_events"],
               "caveat": "blind estimate from envelope decay; sustained notes read as reverberant"},
    }
    return feats, {"yin": y, "mono": m}


def stem_features(x, sr) -> dict:
    """Per-stem features (SPEC 6.3 'stem-level').

    Keys: duration_s, channels, level{lufs_integrated, rms_dbfs,
    active_rms_dbfs, peak_dbfs}, spectral_centroid_hz, hf_ratio,
    f0{lowest_f0_hz, median_f0_hz, f0_confidence, voiced_fraction},
    harmonic_ratio, crest_db, activity{ratio, intervals_s},
    stereo{pan, pan_db, correlation, width_side_ratio},
    dr{dr_db, pre_delay_ms, n_events, caveat}.
    """
    feats, _ = _features_full(x, sr, _model())
    return _clean(feats)


# --------------------------------------------------------------------------
# Roles, importance, lead / kick / bass resolution


def _genre_prior(genre: str | None) -> tuple[dict | None, str | None]:
    if not genre:
        return None, None
    for g in load_genre_priors().get("genres", []):
        if g.get("id") == genre:
            return g, None
    return None, f"unknown genre '{genre}': generic values used"


def _role_group(role: str, is_lead: bool, priors: dict, lead_declared: bool) -> str:
    if is_lead:
        return "lead_vocal"
    groups = priors.get("importance_groups", {})
    for g, roles in groups.items():
        if role in roles:
            if g == "lead_vocal" and lead_declared:
                return "harmony"
            return g
    return "pads_fx_ornaments"


def _importances(meta: dict, ids: list[str], genre: str | None, model: dict,
                 section_id: str | None = None) -> dict[str, dict]:
    priors = load_genre_priors()
    gp, _ = _genre_prior(genre)
    order = list((gp or {}).get("stem_importance_order") or priors.get("default_stem_importance_order", []))
    ladder = model["importance_defaults"]["values_by_rank"]
    lead_declared = any(bool((meta.get(t) or {}).get("is_lead")) for t in ids)
    out = {}
    for t in ids:
        md = meta.get(t) or {}
        imp = md.get("importance")
        val, src = None, None
        if isinstance(imp, dict):
            if section_id is not None and isinstance(imp.get("by_section"), dict) \
                    and section_id in imp["by_section"]:
                val, src = float(imp["by_section"][section_id]), "by_section"
            elif imp.get("value") is not None:
                val, src = float(imp["value"]), str(imp.get("source", "declared"))
        elif isinstance(imp, (int, float)) and not isinstance(imp, bool):
            val, src = float(imp), "declared"
        if val is None:
            grp = _role_group(str(md.get("role", "other")), bool(md.get("is_lead")), priors, lead_declared)
            rank = order.index(grp) if grp in order else len(order) - 1
            val = float(ladder[min(rank, len(ladder) - 1)])
            src = "genre_prior" if gp and gp.get("stem_importance_order") else "default"
        out[t] = {"value": max(0.0, val), "source": src}
    return out


def _name(t: str, md: dict) -> str:
    return f"{t} {md.get('name', '')}".lower()


def _resolve_lead(meta: dict, ids: list[str], energy: dict[str, float] | None = None) -> tuple[str | None, str | None]:
    leads = [t for t in ids if (meta.get(t) or {}).get("is_lead")]
    if leads:
        return leads[0], "declared"
    voc = [t for t in ids if (meta.get(t) or {}).get("role") == "vocals"]
    if voc:
        if energy:
            voc.sort(key=lambda t: -energy.get(t, 0.0))
        return voc[0], "estimated_from_role"
    return None, None


def _resolve_kick_bass(meta: dict, ids: list[str], kick_energy: dict, bass_energy: dict):
    kick = [t for t in ids if (meta.get(t) or {}).get("is_kick") or "kick" in _name(t, meta.get(t) or {})]
    ksrc = "declared_or_named"
    if not kick:
        kick = [t for t in ids if (meta.get(t) or {}).get("role") == "drums"]
        ksrc = "estimated_from_drums_role"
    bass = [t for t in ids if (meta.get(t) or {}).get("role") == "bass"
            or "808" in _name(t, meta.get(t) or {})]
    bass = [t for t in bass if t not in kick[:1]] if kick else bass
    k = max(kick, key=lambda t: kick_energy.get(t, 0.0)) if kick else None
    bass = [t for t in bass if t != k]
    b = max(bass, key=lambda t: bass_energy.get(t, 0.0)) if bass else None
    return (k, ksrc if k else None), (b, "role" if b else None)


# --------------------------------------------------------------------------
# Shared band analysis context


class _Ctx:
    """Band powers of every stem on a common frame grid (+ lazy excitation)."""

    def __init__(self, stems: dict, sr: float, meta: dict | None, model: dict,
                 genre: str | None = None):
        if not stems:
            raise InputError("no stems given")
        self.model = model
        self.sr = float(sr)
        self.meta = {t: dict((meta or {}).get(t) or {}) for t in stems}
        self.ids = [str(t) for t in stems]
        self.arr = {str(t): _as_frames(v) for t, v in stems.items()}
        self.genre = genre
        self.n = max(a.shape[0] for a in self.arr.values())
        an = model["analysis"]
        self.nfft = int(2 ** round(math.log2(an["frame_s"] * self.sr)))
        self.hop = max(1, int(self.nfft * an["hop_fraction"]))
        self.n_fr = max(1, int(math.ceil(max(self.n - self.nfft, 0) / self.hop)) + 1)
        self.frame_t = (np.arange(self.n_fr) * self.hop + self.nfft / 2) / self.sr
        # ERB bands
        edges, centers = _erb.erb_band_edges(self.sr, self.nfft, fmin=an["band_lo_hz"],
                                             fmax=min(an["band_hi_hz"], 0.475 * self.sr),
                                             step=an["band_step_erb"])
        self.edges, self.fc = edges, centers
        self.z = _erb.hz_to_bark(centers)
        khz = centers / 1000.0
        self.ath = 3.64 * khz ** -0.8 - 6.5 * np.exp(-0.6 * (khz - 3.3) ** 2) + 1e-3 * khz ** 4
        Werb = _erb.band_matrix(self.sr, self.nfft, edges)                 # [bands, bins]
        p22 = model["p22"]["bands_hz"]
        nyq = self.sr / 2.0
        rows = []
        self.p22_names = []
        for name in P22_ORDER:
            lo, hi = p22[name]
            if lo >= nyq:
                continue
            rows.append(_erb.band_matrix(self.sr, self.nfft, [lo, min(hi, nyq)])[0])
            self.p22_names.append(name)
        clo, chi = model["regions_hz"]["clarity_band"]
        rows.append(_erb.band_matrix(self.sr, self.nfft, [clo, min(chi, nyq)])[0])
        rows.append(np.ones(self.nfft // 2 + 1))                            # total
        self.W = np.vstack([Werb, np.vstack(rows)]).T                       # [bins, cols]
        nb = Werb.shape[0]
        n22 = len(self.p22_names)
        raw = dict(zip(self.ids, _pmap(lambda t: self._band_power(self.arr[t]), self.ids)))
        tot_raw = {t: raw[t][:, -1] for t in self.ids}
        # activity on the un-normalized level
        gate = model["activity_gate"]
        self.active = {}
        for t in self.ids:
            lev = _db(tot_raw[t])
            self.active[t] = _gate(lev, np.ones(self.n_fr, dtype=bool), gate["abs_dbfs"],
                                   gate["rel_db_below_p95"])
        # level match: one common gain so that the (power-summed) mix sits at the reference
        mix = sum(tot_raw.values())
        mix_db = _db(mix)
        sel = mix_db > -70.0
        mix_ms = float(mix[sel].mean()) if sel.any() else 0.0
        self.gain_db = (an["mix_reference_rms_dbfs"] - 10 * math.log10(mix_ms)) if mix_ms > _EPS else 0.0
        g = 10 ** (self.gain_db / 10.0)
        self.bp = {t: raw[t][:, :nb] * g for t in self.ids}
        self.p22 = {t: raw[t][:, nb:nb + n22] * g for t in self.ids}
        self.clar = {t: raw[t][:, nb + n22] * g for t in self.ids}
        self.tot = {t: raw[t][:, -1] * g for t in self.ids}
        self.spl_off = float(an["full_scale_spl_db"])
        self.w = {}
        for t in self.ids:
            audible = (_db(self.bp[t]) + self.spl_off) > self.ath[None, :]
            self.w[t] = self.bp[t] * audible
        self._E: dict | None = None
        self._Elow: dict | None = None
        rg = model["regions_hz"]
        self.low_src = self.fc < rg["low_source_below"]

    # -- band power -------------------------------------------------------
    def _band_power(self, a: np.ndarray) -> np.ndarray:
        nfft, hop, n_fr = self.nfft, self.hop, self.n_fr
        win = ss.get_window("hann", nfft, fftbins=True)
        scale = np.full(nfft // 2 + 1, 2.0)
        scale[0] = 1.0
        scale[-1] = 1.0
        scale /= nfft * float(np.sum(win * win))
        out = np.zeros((n_fr, self.W.shape[1]))
        need = (n_fr - 1) * hop + nfft
        nch = a.shape[1]
        for ch in range(nch):
            x = a[:, ch]
            if x.size < need:
                x = np.pad(x, (0, need - x.size))
            fr = np.lib.stride_tricks.sliding_window_view(x[:need], nfft)[::hop][:n_fr]
            for c0 in range(0, n_fr, 512):
                X = sfft.rfft(fr[c0:c0 + 512] * win, axis=1)
                pw = (X.real ** 2 + X.imag ** 2) * scale
                out[c0:c0 + 512] += pw @ self.W
        return out / nch

    # -- spreading --------------------------------------------------------
    def _spread(self, P: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        sp = self.model["spreading"]
        dz = self.z[None, :] - self.z[:, None]               # [j, i] = z_i - z_j
        up = dz >= 0
        low_att = np.where(up, 0.0, sp["lower_slope_db_per_bark"] * (-dz))
        E = np.empty_like(P)
        El = np.empty_like(P)
        lowmask = self.low_src.astype(np.float64)
        ln = math.log(10.0) / 10.0
        for c0 in range(0, P.shape[0], 256):
            Pc = P[c0:c0 + 256]
            L = _db(Pc) + self.spl_off
            su = np.clip(sp["upper_slope_base_db_per_bark"] + sp["upper_slope_freq_term_hz"] / self.fc[None, :]
                         - sp["upper_slope_level_coeff_db_per_bark_per_db"] * L,
                         sp["upper_slope_min_db_per_bark"], sp["upper_slope_max_db_per_bark"])
            att = np.where(up[None], su[:, :, None] * dz[None], low_att[None])
            A = np.exp(-ln * att)                                 # [f, j, i]
            E[c0:c0 + 256] = np.matmul(Pc[:, None, :], A)[:, 0, :]
            El[c0:c0 + 256] = np.matmul((Pc * lowmask)[:, None, :], A)[:, 0, :]
        return E, El

    def excitation(self) -> tuple[dict, dict]:
        if self._E is None:
            self._E, self._Elow = {}, {}
            for t in self.ids:
                self._E[t], self._Elow[t] = self._spread(self.bp[t])
        return self._E, self._Elow  # type: ignore[return-value]

    # -- masking helpers ----------------------------------------------------
    def buried(self, t: str, masker_exc: np.ndarray) -> np.ndarray:
        mk = self.model["masking"]
        thr = masker_exc * 10 ** (mk["threshold_offset_db"] / 10.0)
        b = 10.0 * np.log10((thr + _EPS) / (self.bp[t] + _EPS))
        return np.clip(b, 0.0, mk["buried_cap_db"])

    def others(self, t: str, E: dict) -> np.ndarray:
        acc = np.zeros((self.n_fr, self.fc.size))
        for s in self.ids:
            if s != t:
                acc += E[s]
        return acc

    def region(self, lo: float, hi: float) -> np.ndarray:
        return (self.fc >= lo) & (self.fc < hi)

    def frames_in(self, a: int, b: int) -> np.ndarray:
        st = np.arange(self.n_fr) * self.hop
        c = st + self.nfft // 2
        return (c >= a) & (c < b)

    def agg(self, t: str, b: np.ndarray, band_sel=None, frame_sel=None):
        """(value_db, per_band_db) for target t; None when t has no audible energy there."""
        w = self.w[t]
        if band_sel is not None:
            w = w[:, band_sel]
            b = b[:, band_sel]
        fm = self.active[t].copy()
        if frame_sel is not None:
            fm &= frame_sel
        rp = w.sum(axis=1)
        ok = fm & (rp > 0)
        if not ok.any():
            return None, None
        ref = float(np.percentile(rp[ok], 95))
        ok &= rp >= ref * 10 ** (-self.model["activity_gate"]["rel_db_below_p95"] / 10.0)
        if not ok.any():
            return None, None
        wo, bo = w[ok], b[ok]
        per_frame = (wo * bo).sum(axis=1) / wo.sum(axis=1)
        wb = wo.sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            per_band = np.where(wb > 0, (wo * bo).sum(axis=0) / np.where(wb > 0, wb, 1.0), np.nan)
        return float(per_frame.mean()), per_band


# --------------------------------------------------------------------------
# P-02 masking


def _note_values(bpm: float | None) -> dict | None:
    if not bpm or bpm <= 0:
        return None
    beat = 60.0 / float(bpm)
    return {"1/4": beat, "1/8": beat / 2, "1/16": beat / 4}


def _time_axis(ctx: _Ctx, bpm: float | None) -> dict:
    model = ctx.model
    rg = model["regions_hz"]
    kb = ctx.region(*rg["kick_band"])
    kick_e = {t: float(ctx.bp[t][:, kb].sum()) for t in ctx.ids}
    bass_e = {t: float(ctx.p22[t][:, ctx.p22_names.index("bass")].sum()) if "bass" in ctx.p22_names else 0.0
              for t in ctx.ids}
    (k, ksrc), (b, bsrc) = _resolve_kick_bass(ctx.meta, ctx.ids, kick_e, bass_e)
    pen_cfg = model["penalties"]["time_axis"]
    if k is None or b is None or not kb.any():
        return {"available": False, "reason": "kick or bass stem not identified",
                "kick": k, "bass": b, "value": None, "penalty": None}
    E, _ = ctx.excitation()
    sc = model["sidechain_sim"]
    env = ctx.bp[k][:, kb].sum(axis=1)
    env_db = _db(env)
    pos = env > _EPS
    if not pos.any():
        return {"available": False, "reason": "kick stem has no kick-band energy",
                "kick": k, "bass": b, "value": None, "penalty": None}
    ref = float(np.percentile(env_db[pos], 95))
    rng = float(sc["trigger_range_db"])
    trig = np.clip((env_db - (ref - rng)) / rng, 0.0, 1.0)
    hits = trig > 0.5
    hop_s = ctx.hop / ctx.sr
    notes = _note_values(bpm)
    rel_s = notes[sc["release_note"]] if notes and sc["release_note"] in notes else sc["release_ms_without_bpm"] / 1000.0
    tau = rel_s / math.log(10.0)
    dec = math.exp(-hop_s / max(tau, 1e-6))
    gr = np.zeros(ctx.n_fr)
    prev = 0.0
    depth = float(sc["depth_db"])
    for i in range(ctx.n_fr):
        prev = max(depth * trig[i], prev * dec)
        gr[i] = prev
    k_bur_before = ctx.buried(k, E[b])
    k_bur_after = ctx.buried(k, E[b] * (10 ** (-gr / 10.0))[:, None])
    v_before, _ = ctx.agg(k, k_bur_before, kb, hits)
    v_after, _ = ctx.agg(k, k_bur_after, kb, hits)
    b_bur, _ = ctx.agg(b, ctx.buried(b, E[k]), kb)
    # kick decay time and inter-kick interval
    peaks, _ = ss.find_peaks(env_db, prominence=6.0, distance=max(1, int(0.08 / hop_s)),
                             height=ref - rng)
    decays = []
    for i, pk in enumerate(peaks):
        end = peaks[i + 1] if i + 1 < len(peaks) else ctx.n_fr
        below = np.flatnonzero(env_db[pk:end] < env_db[pk] - sc["kick_decay_db"])
        if below.size:
            decays.append(below[0] * hop_s)
    decay_s = float(np.median(decays)) if decays else None
    ioi = float(np.median(np.diff(peaks))) * hop_s if len(peaks) > 1 else None
    recovery = {"release_s": rel_s, "release_from": "bpm_note_value" if notes else "default_ms",
                "kick_decay_s": decay_s, "kick_interval_s": ioi}
    if notes:
        recovery["note_values_s"] = notes
        if decay_s is not None:
            fit = [nm for nm, v in sorted(notes.items(), key=lambda kv: kv[1]) if v >= decay_s]
            recovery["suggested_release_note"] = fit[0] if fit else "1/4"
    if ioi is not None:
        recovery["release_recovers_before_next_kick"] = bool(rel_s < ioi)
    value = v_before
    return {
        "available": True,
        "kick": k, "kick_source": ksrc, "bass": b, "bass_source": bsrc,
        "kick_band_hz": rg["kick_band"],
        "kick_buried_by_bass_db": v_before,
        "kick_buried_after_ducking_db": v_after,
        "unmask_db": (v_before - v_after) if v_before is not None and v_after is not None else None,
        "bass_buried_by_kick_db": b_bur,
        "kick_hit_fraction": float(hits.mean()),
        "ducking": {"depth_db": depth, **recovery},
        "value": value,
        "penalty": _range_penalty(value, 0.0, pen_cfg["ok_max_db"], pen_cfg["scale_db"]) if value is not None else None,
    }


def _p02(ctx: _Ctx, sections=None, bpm=None) -> dict:
    model = ctx.model
    E, El = ctx.excitation()
    rg = model["regions_hz"]
    pen = model["penalties"]
    imps = _importances(ctx.meta, ctx.ids, ctx.genre, model)
    per_target: dict[str, dict] = {}
    full_b: dict[str, np.ndarray] = {}
    for t in ctx.ids:
        bt = ctx.buried(t, ctx.others(t, E))
        full_b[t] = bt
        v, pb = ctx.agg(t, bt)
        per_target[t] = {
            "role": ctx.meta[t].get("role"),
            "importance": imps[t]["value"],
            "importance_source": imps[t]["source"],
            "buried_db": v,
            "buried_db_by_band": pb,
        }
    # pairwise matrix (target row, masker column), full band
    matrix: dict[str, dict] = {}
    for t in ctx.ids:
        row = {}
        for m in ctx.ids:
            if m == t:
                continue
            v, _ = ctx.agg(t, ctx.buried(t, E[m]))
            row[m] = v
        matrix[t] = row

    def _overall(values: dict[str, float | None], weights: dict[str, float]):
        num = den = 0.0
        for t, v in values.items():
            if v is None:
                continue
            num += weights[t] * v
            den += weights[t]
        return (num / den if den > 0 else None), num

    ov, ov_sum = _overall({t: per_target[t]["buried_db"] for t in ctx.ids},
                          {t: imps[t]["value"] for t in ctx.ids})
    overall = {"value": ov, "weighted_sum": ov_sum,
               "penalty": _range_penalty(ov, 0.0, pen["overall"]["ok_max_db"], pen["overall"]["scale_db"])
               if ov is not None else None}
    # vs_lead
    energy = {t: float(ctx.clar[t].sum()) for t in ctx.ids}
    lead, lsrc = _resolve_lead(ctx.meta, ctx.ids, energy)
    if lead is None:
        vs_lead = {"available": False, "reason": "no lead declared and no vocals role", "lead": None,
                   "value": None, "penalty": None}
    else:
        res = {}
        pvals = []
        for key, cfgkey in (("low_mid", "lead_low_mid"), ("presence", "lead_presence")):
            lo, hi = rg[cfgkey]
            sel = ctx.region(lo, hi)
            v, _ = ctx.agg(lead, full_b[lead], sel) if sel.any() else (None, None)
            maskers = []
            for m in ctx.ids:
                if m == lead:
                    continue
                mv, _ = ctx.agg(lead, ctx.buried(lead, E[m]), sel) if sel.any() else (None, None)
                if mv is not None and mv > 0:
                    maskers.append({"track": m, "buried_db": mv, "importance": imps[m]["value"]})
            maskers.sort(key=lambda d: -d["buried_db"])
            p = _range_penalty(v, 0.0, pen["vs_lead"]["ok_max_db"], pen["vs_lead"]["scale_db"]) if v is not None else None
            if p is not None:
                pvals.append(p)
            res[key] = {"band_hz": [lo, hi], "buried_db": v, "penalty": p, "top_maskers": maskers[:3]}
        vals = [res[k]["buried_db"] for k in res if res[k]["buried_db"] is not None]
        vs_lead = {"available": True, "lead": lead, "lead_source": lsrc, **res,
                   "value": float(np.mean(vals)) if vals else None,
                   "penalty": float(np.mean(pvals)) if pvals else None,
                   "combine": pen["vs_lead"].get("combine", "mean")}
    # low_to_mid: masking caused by energy below low_source_below onto 200-800 Hz
    lo, hi = rg["low_to_mid_target"]
    sel = ctx.region(lo, hi)
    l2m_vals = {}
    for t in ctx.ids:
        acc = np.zeros((ctx.n_fr, ctx.fc.size))
        for s in ctx.ids:
            if s != t:
                acc += El[s]
        v, _ = ctx.agg(t, ctx.buried(t, acc), sel) if sel.any() else (None, None)
        l2m_vals[t] = v
    l2m, _ = _overall(l2m_vals, {t: imps[t]["value"] for t in ctx.ids})
    spill_num = sum(El[s][:, sel].sum() for s in ctx.ids)
    spill_den = sum(ctx.bp[s][:, sel].sum() for s in ctx.ids)
    low_to_mid = {
        "source_below_hz": rg["low_source_below"], "target_band_hz": [lo, hi],
        "value": l2m, "by_target": l2m_vals,
        "spill_db": _dbs(spill_num / spill_den) if spill_den > _EPS and spill_num > _EPS else None,
        "penalty": _range_penalty(l2m, 0.0, pen["low_to_mid"]["ok_max_db"], pen["low_to_mid"]["scale_db"])
        if l2m is not None else None,
    }
    out = {
        "bands_hz": ctx.fc,
        "level_match_gain_db": ctx.gain_db,
        "per_target": per_target,
        "matrix": matrix,
        "vs_lead": vs_lead,
        "overall": overall,
        "low_to_mid": low_to_mid,
        "time_axis": _time_axis(ctx, bpm),
        "model": "two-slope Bark spreading, level-dependent upper slope (knowledge/masking_model.json)",
    }
    if sections:
        secs = _parse_sections(sections, ctx.sr, ctx.n)
        by_sec = []
        for s in secs:
            fs = ctx.frames_in(s["start"], s["end"])
            simps = _importances(ctx.meta, ctx.ids, ctx.genre, model, section_id=s["id"])
            vals = {t: ctx.agg(t, full_b[t], None, fs)[0] for t in ctx.ids}
            sov, _ = _overall(vals, {t: simps[t]["value"] for t in ctx.ids})
            entry = {"id": s["id"], "start_s": s["start"] / ctx.sr, "end_s": s["end"] / ctx.sr,
                     "overall_db": sov,
                     "overall_penalty": _range_penalty(sov, 0.0, pen["overall"]["ok_max_db"],
                                                       pen["overall"]["scale_db"]) if sov is not None else None}
            if lead is not None:
                for key, cfgkey in (("vs_lead_low_mid_db", "lead_low_mid"), ("vs_lead_presence_db", "lead_presence")):
                    rsel = ctx.region(*rg[cfgkey])
                    entry[key] = ctx.agg(lead, full_b[lead], rsel, fs)[0] if rsel.any() else None
            by_sec.append(entry)
        out["by_section"] = by_sec
    return out


def masking_matrix(stems: dict, sr: float, meta: dict, *, sections=None, genre: str | None = None,
                   bpm: float | None = None) -> dict:
    """P-02 masking risk.

    Keys: bands_hz, level_match_gain_db, per_target{id: {role, importance,
    importance_source, buried_db, buried_db_by_band}}, matrix{target:
    {masker: buried_db}}, vs_lead{lead, lead_source, low_mid{band_hz,
    buried_db, penalty, top_maskers}, presence{...}, value, penalty},
    overall{value, weighted_sum, penalty}, low_to_mid{value, by_target,
    spill_db, penalty}, time_axis{kick, bass, kick_buried_by_bass_db,
    kick_buried_after_ducking_db, unmask_db, bass_buried_by_kick_db,
    ducking{...}, value, penalty}, by_section (when sections are given).
    """
    model = _model()
    return _clean(_p02(_Ctx(stems, sr, meta, model, genre), sections, bpm))


# --------------------------------------------------------------------------
# P-08 harmonic completion


def _harmonic_index(y: dict, f0_fixed: float | None, model: dict) -> dict:
    cfg = model["p08"]
    xd, srd = y["xd"], y["srd"]
    hw = float(cfg["harmonic_band_halfwidth_f0"])
    nwin = int(round(0.4 * srd))
    nfft = sfft.next_fast_len(max(4096, 2 * nwin))
    win = ss.get_window("hann", nwin)
    df = srd / nfft
    if f0_fixed is not None:
        frames = np.flatnonzero(y["active"])
        f0s = np.full(frames.size, float(f0_fixed))
    else:
        frames = np.flatnonzero(y["voiced"])
        f0s = y["f0"][frames]
    if frames.size == 0:
        return {"f0_hz": f0_fixed, "index_db": None, "h2_db": None, "h3_db": None, "n_frames": 0}
    centres = (frames * y["hop"] + y["W"] // 2).astype(int)
    xp = np.pad(xd, (nwin, nwin))
    segs = np.lib.stride_tricks.sliding_window_view(xp, nwin)[centres + nwin - nwin // 2]
    E = np.zeros(3)
    fk = np.arange(nfft // 2 + 1) * df
    for c0 in range(0, segs.shape[0], 256):
        S = sfft.rfft(segs[c0:c0 + 256] * win, nfft, axis=1)
        P = S.real ** 2 + S.imag ** 2
        f0c = f0s[c0:c0 + 256][:, None]
        for h in (1, 2, 3):
            m = (fk[None, :] >= (h - hw) * f0c) & (fk[None, :] < (h + hw) * f0c)
            E[h - 1] += float((P * m).sum())
    if E[0] <= _EPS:
        return {"f0_hz": float(np.median(f0s)), "index_db": None, "h2_db": None, "h3_db": None,
                "n_frames": int(frames.size)}
    idx = 10 * math.log10(max(E[1] + E[2], _EPS) / E[0])
    return {"f0_hz": float(np.median(f0s)), "index_db": idx,
            "h2_db": 10 * math.log10(max(E[1], _EPS) / E[0]),
            "h3_db": 10 * math.log10(max(E[2], _EPS) / E[0]),
            "n_frames": int(frames.size)}


def _p08(x, sr, f0=None, model=None, y=None) -> dict:
    model = model or _model()
    cfg = model["p08"]
    if y is None:
        a = _as_frames(x)
        y = _yin(a.mean(axis=1), float(sr), gate_abs_db=model["activity_gate"]["abs_dbfs"])
    r = _harmonic_index(y, f0, model)
    r["f0_source"] = "given" if f0 is not None else "estimated"
    r["target_index_db_min"] = cfg["target_index_db_min"]
    r["penalty"] = _range_penalty(r["index_db"], cfg["target_index_db_min"], math.inf, cfg["scale_db"]) \
        if r["index_db"] is not None else None
    return r


def harmonic_completion(x_bass, sr, f0=None) -> dict:
    """P-08: energy at 2nd/3rd harmonic bands relative to the fundamental band.

    Keys: f0_hz, f0_source, index_db (10*log10((E2+E3)/E1)), h2_db, h3_db,
    n_frames, target_index_db_min, penalty. With f0=None the per-frame YIN
    pitch is used (melodic bass lines); a given f0 is applied to all active frames.
    """
    return _clean(_p08(x_bass, sr, f0))


def _missing_fundamental(x, sr, f0=None, hp_hz=None, model=None, y=None) -> dict:
    model = model or _model()
    cfg = model["p08"]
    hp = float(hp_hz if hp_hz is not None else cfg["missing_fundamental_hp_hz"])
    a = _as_frames(x)
    m = a.mean(axis=1)
    if y is None:
        y = _yin(m, float(sr), gate_abs_db=model["activity_gate"]["abs_dbfs"])
    sos = ss.butter(8, hp, btype="highpass", fs=float(sr), output="sos")
    mh = ss.sosfiltfilt(sos, m) if m.size > 64 else m
    yh = _yin(mh, float(sr), gate_abs_db=model["activity_gate"]["abs_dbfs"] - 30.0)
    ref_f0 = float(f0) if f0 is not None else (float(np.median(y["f0"][y["voiced"]])) if y["voiced"].any() else None)
    if ref_f0 is None:
        return {"available": False, "reason": "no pitch detected in the original", "hp_hz": hp,
                "f0_hz": None, "agreement_ratio": None, "preserved": None}
    n = min(y["f0"].size, yh["f0"].size)
    base = y["voiced"][:n] if f0 is None else y["active"][:n]
    f_orig = y["f0"][:n] if f0 is None else np.full(n, ref_f0)
    ok = base & yh["voiced"][:n]
    agree = np.zeros(n, dtype=bool)
    with np.errstate(invalid="ignore", divide="ignore"):
        cents = 1200 * np.abs(np.log2(yh["f0"][:n] / f_orig))
    agree[ok] = cents[ok] < cfg["pitch_agree_cents"]
    nb = int(base.sum())
    ratio = float(agree.sum() / nb) if nb else None
    return {
        "available": True,
        "hp_hz": hp,
        "f0_hz": ref_f0,
        "fundamental_below_cutoff": bool(ref_f0 < hp),
        "pitch_detected_after_hp": bool(yh["voiced"].any()),
        "median_f0_after_hp_hz": float(np.median(yh["f0"][yh["voiced"]])) if yh["voiced"].any() else None,
        "agreement_ratio": ratio,
        "preserved": bool(ratio is not None and ratio >= cfg["min_agreement"]),
        "caveat": "periodicity-pitch proxy (YIN); not a listening test",
    }


def missing_fundamental_check(x_bass, sr, f0=None, hp_hz=None) -> dict:
    """OF-5 check 4 / P-08: high-pass (default 120 Hz) and test whether the pitch survives.

    Keys: available, hp_hz, f0_hz, fundamental_below_cutoff,
    pitch_detected_after_hp, median_f0_after_hp_hz, agreement_ratio, preserved, caveat.
    """
    return _clean(_missing_fundamental(x_bass, sr, f0, hp_hz))


# --------------------------------------------------------------------------
# P-09 depth order


def _p09(feats: dict[str, dict], meta: dict, ids: list[str], declared_order, model: dict) -> dict:
    cfg = model["p09"]
    w = cfg["weights"]

    def col(get):
        v = np.array([np.nan if get(feats[t]) is None else float(get(feats[t])) for t in ids])
        fin = np.isfinite(v)
        z = np.zeros(len(ids))
        if fin.sum() >= 2:
            mu, sd = float(v[fin].mean()), float(v[fin].std())
            if sd > 1e-9:
                z[fin] = (v[fin] - mu) / sd
        return v, z

    lv, zl = col(lambda f: f["level"]["active_rms_dbfs"])
    dv, zd = col(lambda f: f["dr"]["dr_db"])
    hv, zh = col(lambda f: f["hf_ratio"])
    pv, zp = col(lambda f: f["dr"]["pre_delay_ms"])
    close = w["level"] * zl + w["dr"] * zd + w["hf_ratio"] * zh + w["pre_delay"] * zp
    order = [ids[i] for i in np.argsort(-close, kind="stable")]
    per = {t: {"closeness": float(close[i]), "depth": float(-close[i]),
               "level_db": lv[i], "dr_db": dv[i], "hf_ratio": hv[i], "pre_delay_ms": pv[i]}
           for i, t in enumerate(ids)}
    out: dict[str, Any] = {"per_stem": per, "estimated_order_front_to_back": order,
                           "weights": w, "declared_order": None, "kendall_tau": None, "penalty": None}
    if declared_order:
        dec = [str(t) for t in declared_order if str(t) in ids]
        out["declared_order"] = dec
        out["declared_order_source"] = "declared"
        if len(dec) >= 2:
            est_rank = {t: i for i, t in enumerate(order)}
            tau = kendalltau(np.arange(len(dec)), [est_rank[t] for t in dec]).statistic
            tau = float(tau) if tau is not None and np.isfinite(tau) else 0.0
            out["kendall_tau"] = tau
            out["penalty"] = (1.0 - tau) / 2.0
    else:
        lead, lsrc = _resolve_lead(meta, ids)
        if lead is not None and len(ids) >= 2:
            r = order.index(lead)
            out["declared_order_source"] = f"lead_front_default ({lsrc})"
            out["lead"] = lead
            out["lead_rank"] = r
            out["penalty"] = r / (len(ids) - 1)
    out["caveat"] = "D/R and pre-delay are blind envelope estimates; z-scores are relative to this stem set"
    return out


def depth_order(stems: dict, sr: float, meta: dict, declared_order=None) -> dict:
    """P-09: depth score per stem and order consistency with a declared front-to-back order.

    Keys: per_stem{id: {closeness, depth, level_db, dr_db, hf_ratio,
    pre_delay_ms}}, estimated_order_front_to_back, weights, declared_order,
    declared_order_source, kendall_tau, penalty ((1 - tau) / 2; without a
    declared order: lead rank / (n - 1)), caveat.
    """
    model = _model()
    ids = [str(t) for t in stems]
    feats = {t: _features_full(stems[t], sr, model)[0] for t in ids}
    return _clean(_p09(feats, meta or {}, ids, declared_order, model))


# --------------------------------------------------------------------------
# P-10 lead band difference


def _p10_target(genre: str | None, model: dict) -> tuple[list[float], str, str | None]:
    cfg = model["p10"]
    gp, note = _genre_prior(genre)
    if gp is not None:
        t = gp.get("p10_target_db") or {}
        rng = t.get("range")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            return [float(rng[0]), float(rng[1])], f"genre_prior:{genre}", note
        rel = t.get("relative")
        if rel in cfg["relative_targets_db"]:
            return list(map(float, cfg["relative_targets_db"][rel])), f"genre_prior:{genre}:relative_{rel}", note
    return list(map(float, cfg["generic_target_db"])), "generic", note


def _p10(ctx: _Ctx, sections=None) -> dict:
    model = ctx.model
    cfg = model["p10"]
    energy = {t: float(ctx.clar[t].sum()) for t in ctx.ids}
    lead, lsrc = _resolve_lead(ctx.meta, ctx.ids, energy)
    target, tsrc, note = _p10_target(ctx.genre, model)
    base = {"band_hz": model["regions_hz"]["clarity_band"], "target_db": target, "target_source": tsrc,
            "provisional": True}
    if note:
        base["note"] = note
    if lead is None:
        return {**base, "available": False, "reason": "no lead declared and no vocals role",
                "lead": None, "value": None, "verdict": None, "penalty": None}
    acc = sum(ctx.clar[t] for t in ctx.ids if t != lead)

    def diff(frames):
        fm = ctx.active[lead] & frames
        if not fm.any() or not isinstance(acc, np.ndarray):
            return None
        a = float(acc[fm].sum())
        lval = float(ctx.clar[lead][fm].sum())
        if a <= _EPS or lval <= _EPS:
            return None
        return 10 * math.log10(lval / a)

    def verdict(v):
        if v is None:
            return None
        return "buried" if v < target[0] else ("floating" if v > target[1] else "ok")

    v = diff(np.ones(ctx.n_fr, dtype=bool))
    out = {**base, "available": v is not None, "lead": lead, "lead_source": lsrc,
           "lead_is_estimate": lsrc != "declared",
           "value": v, "verdict": verdict(v),
           "penalty": _range_penalty(v, target[0], target[1], cfg["scale_db"]) if v is not None else None,
           "level_matched": True,
           "method": "lead minus power-summed accompaniment, frames where the lead is active"}
    if v is None:
        out["reason"] = "no accompaniment energy in the band or lead inactive"
    if sections:
        out["by_section"] = []
        for s in _parse_sections(sections, ctx.sr, ctx.n):
            sv = diff(ctx.frames_in(s["start"], s["end"]))
            out["by_section"].append({"id": s["id"], "value": sv, "verdict": verdict(sv)})
    return out


def lead_band_difference(stems: dict, sr: float, meta: dict, genre: str | None = None, *, sections=None) -> dict:
    """P-10: lead clarity-band (300 Hz - 5 kHz) level minus the accompaniment.

    Keys: band_hz, target_db, target_source, provisional, available, lead,
    lead_source ('declared' | 'estimated_from_role'), lead_is_estimate, value
    (dB), verdict ('buried' | 'floating' | 'ok'), penalty, by_section.
    """
    model = _model()
    return _clean(_p10(_Ctx(stems, sr, meta, model, genre), sections))


# --------------------------------------------------------------------------
# P-12 transient retention


def _bandpass_sos(lo: float, hi: float, sr: float):
    nyq = sr / 2.0
    if lo >= 0.45 * sr:
        return None
    if hi >= 0.45 * sr:
        return ss.butter(4, lo, btype="highpass", fs=sr, output="sos")
    return ss.butter(4, [lo, min(hi, 0.95 * nyq)], btype="bandpass", fs=sr, output="sos")


def _attack_ratio(env: np.ndarray, onsets: np.ndarray, blk_s: float, cfg: dict) -> float | None:
    a_n = max(1, int(cfg["attack_ms"] / 1000 / blk_s))
    b_n = max(a_n + 1, int(cfg["body_ms"] / 1000 / blk_s))
    pre = max(1, int(0.01 / blk_s))
    vals = []
    for o in onsets:
        s0 = max(0, o - pre)
        s1 = o - pre + a_n
        s2 = o + b_n
        if s2 > env.size or s1 <= s0:
            continue
        at = env[s0:s1].sum()
        bd = env[s1:s2].sum()
        if at > _EPS and bd > _EPS:
            vals.append(10 * math.log10(at / bd))
    return float(np.median(vals)) if vals else None


def _p12(before, after, sr: float, model: dict) -> dict:
    cfg = model["p12"]
    b = _as_frames(before).mean(axis=1)
    a = _as_frames(after).mean(axis=1)
    n = min(b.size, a.size)
    b, a = b[:n], a[:n]
    sr = float(sr)
    frame = max(16, int(round(model["analysis"]["frame_s"] * sr)))
    hop = max(1, frame // 2)
    n_fr = max(1, int(math.ceil(max(n - frame, 0) / hop)) + 1)
    gate = model["activity_gate"]
    act = _gate(_db(_frame_power_series(b * b, frame, hop, n_fr)), np.ones(n_fr, dtype=bool),
                gate["abs_dbfs"], gate["rel_db_below_p95"])
    smask = np.zeros(n, dtype=bool)
    for i in np.flatnonzero(act):
        smask[i * hop:min(n, i * hop + frame)] = True
    bands = {}
    losses = []
    for name in P22_ORDER:
        lo, hi = model["p22"]["bands_hz"][name]
        sos = _bandpass_sos(lo, hi, sr)
        if sos is None or not smask.any():
            continue
        cr = []
        for sig in (b, a):
            y = ss.sosfilt(sos, sig)
            ys = y[smask]
            ms = float(np.mean(ys * ys))
            pk = float(np.max(np.abs(ys)))
            cr.append(20 * math.log10(pk) - 10 * math.log10(ms) if ms > _EPS and pk > 0 else None)
        d = cr[1] - cr[0] if cr[0] is not None and cr[1] is not None else None
        bands[name] = {"crest_before_db": cr[0], "crest_after_db": cr[1], "delta_db": d}
        if d is not None:
            losses.append(max(0.0, -d))
    blk_s = 0.005
    eb = _envelope(b * b, sr, blk_s)
    ea = _envelope(a * a, sr, blk_s)
    eb_db = _db(eb)
    valid = eb > _EPS
    onsets = np.array([], dtype=int)
    if valid.any():
        thr = max(gate["abs_dbfs"], float(np.percentile(eb_db[valid], 95)) - 30.0)
        onsets, _ = ss.find_peaks(eb_db, prominence=6.0, distance=int(0.05 / blk_s), height=thr)
    ar_b = _attack_ratio(eb, onsets, blk_s, cfg)
    ar_a = _attack_ratio(ea, onsets, blk_s, cfg)
    ar_d = ar_a - ar_b if ar_a is not None and ar_b is not None else None
    crest_loss = float(np.mean(losses)) if losses else None
    att_loss = max(0.0, -ar_d) if ar_d is not None else None
    ps = [p for p in (
        _range_penalty(crest_loss, -math.inf, cfg["crest_loss_ok_db"], cfg["crest_scale_db"]) if crest_loss is not None else None,
        _range_penalty(att_loss, -math.inf, cfg["attack_loss_ok_db"], cfg["attack_scale_db"]) if att_loss is not None else None,
    ) if p is not None]
    return {
        "bands": bands,
        "mean_crest_loss_db": crest_loss,
        "attack_ratio_before_db": ar_b,
        "attack_ratio_after_db": ar_a,
        "attack_ratio_delta_db": ar_d,
        "n_onsets": int(len(onsets)),
        "penalty": float(np.mean(ps)) if ps else None,
    }


def transient_retention(before, after, sr) -> dict:
    """P-12: band crest change and attack-section energy ratio, before vs after processing.

    Keys: bands{name: {crest_before_db, crest_after_db, delta_db}},
    mean_crest_loss_db, attack_ratio_before_db, attack_ratio_after_db,
    attack_ratio_delta_db, n_onsets, penalty. Crest and ratios are
    level-independent, so no level match is needed.
    """
    return _clean(_p12(before, after, sr, _model()))


# --------------------------------------------------------------------------
# P-13 low tuning


def _kick_f0(y: dict, model: dict) -> float | None:
    lo, hi = model["p13"]["kick_search_hz"]
    xd, srd = y["xd"], y["srd"]
    if xd.size < 64 or not np.any(xd):
        return None
    nper = min(xd.size, 1 << int(math.floor(math.log2(max(64, min(xd.size, int(srd)))))))
    nfft = max(nper, 16384)
    f, pxx = ss.welch(xd, fs=srd, nperseg=nper, nfft=nfft)
    sel = np.flatnonzero((f >= lo) & (f <= hi))
    if sel.size < 3 or pxx[sel].max() <= 0:
        return None
    i = sel[np.argmax(pxx[sel])]
    if 0 < i < f.size - 1:
        l0, l1, l2 = _db(pxx[i - 1:i + 2])
        den = l0 - 2 * l1 + l2
        sh = 0.5 * (l0 - l2) / den if den < 0 else 0.0
        return float(f[i] + np.clip(sh, -1, 1) * (f[1] - f[0]))
    return float(f[i])


def _cents_risk(c: float, cfg: dict) -> float:
    a = abs(c)
    t0, (r0, r1), s = cfg["in_tune_cents"], cfg["risk_full_cents"], cfg["separate_cents"]
    if a <= t0 or a >= s:
        return 0.0
    if a < r0:
        return (a - t0) / (r0 - t0)
    if a <= r1:
        return 1.0
    return (s - a) / (s - r1)


def _tonic_info(tonic: float, cfg: dict) -> dict:
    lo, hi = cfg["tonic_fold_hz"]
    f = float(tonic)
    while f >= hi:
        f /= 2.0
    while f < lo:
        f *= 2.0
    octs = []
    g = f
    while g / 2 >= 20.0:
        g /= 2
    while g <= 250.0:
        band = "sub" if g < cfg["sub_band_hz"][1] else "bass"
        octs.append({"hz": g, "band": band})
        g *= 2
    return {"tonic_hz": float(tonic), "folded_hz": f,
            "in_sub_band": bool(cfg["sub_band_hz"][0] <= f < cfg["sub_band_hz"][1]),
            "octaves_20_250_hz": octs,
            "policy_hint": "use_fundamental" if f >= cfg["use_fundamental_min_hz"] else "harmonic_completion",
            "rule": "R-16"}


def _fold_cents(f: float, ref: float) -> float:
    c = 1200 * math.log2(f / ref)
    return c - 1200 * round(c / 1200)


def _p13(ctx: _Ctx, yins: dict, key_tonic_hz, model: dict) -> dict:
    cfg = model["p13"]
    rg = model["regions_hz"]
    kb = ctx.region(*rg["kick_band"])
    kick_e = {t: float(ctx.bp[t][:, kb].sum()) for t in ctx.ids}
    bi = ctx.p22_names.index("bass") if "bass" in ctx.p22_names else None
    bass_e = {t: float(ctx.p22[t][:, bi].sum()) if bi is not None else 0.0 for t in ctx.ids}
    (k, ksrc), (b, bsrc) = _resolve_kick_bass(ctx.meta, ctx.ids, kick_e, bass_e)
    out: dict[str, Any] = {"kick": k, "kick_source": ksrc, "bass": b, "bass_source": bsrc,
                           "kick_f0_hz": None, "bass_f0_hz": None, "cents_difference": None,
                           "cents_folded": None, "beat_hz": None, "beating_risk": None,
                           "risk_frame_fraction": None, "penalty": None}
    fk = _kick_f0(yins[k], model) if k is not None else None
    fb = None
    if b is not None:
        yb = yins[b]
        if yb["voiced"].any():
            fb = float(np.median(yb["f0"][yb["voiced"]]))
    out["kick_f0_hz"], out["bass_f0_hz"] = fk, fb
    if fk and fb:
        c = 1200 * math.log2(fb / fk)
        out["cents_difference"] = c
        out["cents_folded"] = _fold_cents(fb, fk)
        out["beat_hz"] = abs(fb - fk)
        risk = _cents_risk(c, cfg)
        out["beating_risk"] = risk
        yb = yins[b]
        v = yb["f0"][yb["voiced"]]
        if v.size:
            cc = 1200 * np.log2(v / fk)
            out["risk_frame_fraction"] = float(np.mean([_cents_risk(x, cfg) > 0.5 for x in cc]))
        out["penalty"] = risk
    if key_tonic_hz:
        ti = _tonic_info(float(key_tonic_hz), cfg)
        if fk:
            ti["kick_vs_tonic_cents"] = _fold_cents(fk, float(key_tonic_hz))
        if fb:
            ti["bass_vs_tonic_cents"] = _fold_cents(fb, float(key_tonic_hz))
        out["tonic"] = ti
    else:
        out["tonic"] = None
    return out


def low_tuning(stems: dict, sr: float, meta: dict, key_tonic_hz=None) -> dict:
    """P-13: kick vs bass fundamental difference (cents) and tonic sub-band membership (R-16).

    Keys: kick, kick_source, bass, bass_source, kick_f0_hz (spectral peak in
    30-150 Hz), bass_f0_hz (median YIN), cents_difference (1200*log2(fb/fk)),
    cents_folded, beat_hz, beating_risk, risk_frame_fraction, penalty,
    tonic{tonic_hz, folded_hz, in_sub_band, octaves_20_250_hz, policy_hint,
    kick_vs_tonic_cents, bass_vs_tonic_cents} or None.
    """
    model = _model()
    ctx = _Ctx(stems, sr, meta, model)
    yins = {}
    for t in ctx.ids:
        yins[t] = _yin(ctx.arr[t].mean(axis=1), ctx.sr, gate_abs_db=model["activity_gate"]["abs_dbfs"])
    return _clean(_p13(ctx, yins, key_tonic_hz, model))


# --------------------------------------------------------------------------
# P-15 reverb metrics


def _rt60_bands(m: np.ndarray, sr: float, model: dict) -> dict:
    cfg = model["p15"]
    xd, srd = _decimate(m, sr, 16000.0)
    blk_s = 0.01
    res = {}
    total_segments = 0
    for fc in cfg["octave_centres_hz"]:
        lo, hi = fc / math.sqrt(2), fc * math.sqrt(2)
        if hi >= 0.45 * srd or xd.size < 1024:
            continue
        sos = ss.butter(3, [lo, hi], btype="bandpass", fs=srd, output="sos")
        y = ss.sosfilt(sos, xd)
        env = _envelope(y * y, srd, blk_s)
        env_db = _db(env)
        valid = env > _EPS
        if valid.sum() < 20:
            res[str(int(fc))] = {"rt60_s": None, "n_segments": 0}
            continue
        floor = float(np.percentile(env_db[valid], 5))
        top = float(np.percentile(env_db[valid], 95))
        peaks, _ = ss.find_peaks(env_db, prominence=10.0, distance=10, height=top - 30.0)
        rts = []
        for i, pk in enumerate(peaks):
            end = peaks[i + 1] if i + 1 < len(peaks) else env.size
            seg = env_db[pk:end]
            ref = seg[0]
            lim = max(floor + 5.0, ref - cfg["decay_end_db"])
            i0 = np.flatnonzero(seg <= ref - cfg["decay_start_db"])
            if not i0.size:
                continue
            i0 = int(i0[0])
            i1 = np.flatnonzero(seg <= lim)
            if not i1.size:
                continue
            i1 = int(i1[0])
            span = seg[i0] - seg[i1]
            if span < cfg["min_decay_span_db"] - cfg["decay_start_db"] or i1 - i0 < 4:
                continue
            tt = np.arange(i0, i1 + 1) * blk_s
            yy = seg[i0:i1 + 1]
            A = np.vstack([tt, np.ones_like(tt)]).T
            coef, *_ = np.linalg.lstsq(A, yy, rcond=None)
            pred = A @ coef
            ssr = float(((yy - pred) ** 2).sum())
            sst = float(((yy - yy.mean()) ** 2).sum())
            r2 = 1 - ssr / sst if sst > 0 else 0.0
            if coef[0] < 0 and r2 >= cfg["min_fit_r2"]:
                rts.append(float(np.clip(-60.0 / coef[0], 0.05, 10.0)))
        total_segments += len(rts)
        res[str(int(fc))] = {"rt60_s": float(np.median(rts)) if rts else None, "n_segments": len(rts)}
    mids = [res[k]["rt60_s"] for k in ("500", "1000") if k in res and res[k]["rt60_s"] is not None]
    return {"by_band": res, "rt60_mid_s": float(np.mean(mids)) if mids else None,
            "n_segments": total_segments}


def _p15(x, sr, model: dict, feats: dict | None = None) -> dict:
    a = _as_frames(x)
    m = a.mean(axis=1)
    cfg = model["p15"]
    if feats is None:
        dr = _dr_estimate((a * a).mean(axis=1), float(sr), model)
    else:
        dr = feats["dr"]
    rt = _rt60_bands(m, float(sr), model)
    d = dr["dr_db"]
    return {
        "dr_db": d,
        "pre_delay_ms": dr.get("pre_delay_ms"),
        "n_events": dr.get("n_events"),
        "rt60_s_by_band": {k: v["rt60_s"] for k, v in rt["by_band"].items()},
        "rt60_segments_by_band": {k: v["n_segments"] for k, v in rt["by_band"].items()},
        "rt60_mid_s": rt["rt60_mid_s"],
        "rough": True,
        "caveat": "blind decay-slope estimates on music, not a room measurement; sustained notes read as reverberant",
        "dr_db_min": cfg["dr_db_min"],
        "penalty": _range_penalty(d, cfg["dr_db_min"], math.inf, cfg["dr_scale_db"]) if d is not None else None,
    }


def reverb_metrics(x, sr) -> dict:
    """P-15: blind D/R and octave-band RT60 (125 Hz - 4 kHz), marked rough.

    Keys: dr_db, pre_delay_ms, n_events, rt60_s_by_band{'125'..'4000'},
    rt60_segments_by_band, rt60_mid_s, rough, caveat, dr_db_min, penalty.
    """
    return _clean(_p15(x, sr, _model()))


# --------------------------------------------------------------------------
# P-22 band density


def _p22(ctx: _Ctx, sections=None) -> dict:
    cfg = ctx.model["p22"]
    imps = _importances(ctx.meta, ctx.ids, ctx.genre, ctx.model)
    lo_t, hi_t = cfg["target_owners"]
    out_secs = []
    pens = []
    max_count = 0
    for s in _parse_sections(sections, ctx.sr, ctx.n):
        fs = ctx.frames_in(s["start"], s["end"])
        en = {t: ctx.p22[t][fs].sum(axis=0) for t in ctx.ids}
        mix_total = float(sum(v.sum() for v in en.values()))
        bands = {}
        for j, name in enumerate(ctx.p22_names):
            vals = {t: float(en[t][j]) for t in ctx.ids}
            tot = sum(vals.values())
            if mix_total <= _EPS or tot <= mix_total * 10 ** (-cfg["band_floor_db_below_mix"] / 10):
                bands[name] = {"empty": True, "count": 0, "owners": [], "penalty": None}
                continue
            loud = max(vals.values())
            owners = []
            for t, v in vals.items():
                if v <= _EPS:
                    continue
                rel = 10 * math.log10(v / loud)
                share = v / tot
                if rel >= -cfg["within_db"] and share >= cfg["min_share"]:
                    owners.append({"track": t, "share": share, "rel_db": rel,
                                   "importance": imps[t]["value"], "role": ctx.meta[t].get("role")})
            owners.sort(key=lambda d: -d["share"])
            cnt = len(owners)
            max_count = max(max_count, cnt)
            p = _range_penalty(cnt, lo_t, hi_t, cfg["scale_owners"])
            pens.append(p)
            bands[name] = {"empty": False, "count": cnt, "owners": owners, "penalty": p,
                           "band_hz": cfg["bands_hz"][name]}
        out_secs.append({"id": s["id"], "start_s": s["start"] / ctx.sr, "end_s": s["end"] / ctx.sr,
                         "bands": bands})
    return {
        "rule": {"kind": cfg["rule"], "within_db": cfg["within_db"], "min_share": cfg["min_share"]},
        "target_owners": [lo_t, hi_t],
        "sections": out_secs,
        "max_count": max_count,
        "penalty": float(np.mean(pens)) if pens else None,
    }


def band_density(stems: dict, sr: float, meta: dict, sections=None, *, genre: str | None = None) -> dict:
    """P-22: per section and band (sub/bass/lowmid/mid/highmid/air), the stems owning the band.

    Keys: rule{kind, within_db, min_share}, target_owners, sections[{id,
    start_s, end_s, bands{name: {empty, count, owners[{track, share, rel_db,
    importance, role}], penalty, band_hz}}}], max_count, penalty.
    """
    model = _model()
    return _clean(_p22(_Ctx(stems, sr, meta, model, genre), sections))


# --------------------------------------------------------------------------
# Bundle


def measure_stem_context(stems: dict, sr: float, meta: dict, *, genre: str | None = None,
                         declared_order=None, sections=None, key_tonic_hz=None, bpm=None,
                         before=None, after=None) -> dict:
    """All stem-context proxies.

    Keys: features{id: stem_features}, P-02, P-08 (bass stem or null), P-09,
    P-10, P-12 (null unless before/after given; dicts of stems give a per-track
    result), P-13, P-15{per_stem, lead, penalty}, P-22, notes.
    """
    model = _model()
    ctx = _Ctx(stems, sr, meta, model, genre)
    feats, internals = {}, {}
    for t, (f, i) in zip(ctx.ids, _pmap(lambda t: _features_full(ctx.arr[t], ctx.sr, model), ctx.ids)):
        feats[t], internals[t] = f, i
    yins = {t: internals[t]["yin"] for t in ctx.ids}
    notes = []
    _, gnote = _genre_prior(genre)
    if gnote:
        notes.append(gnote)
    if not genre:
        notes.append("genre not declared: generic initial values used")
    out: dict[str, Any] = {"features": feats}
    out["P-02"] = _p02(ctx, sections, bpm)
    # P-08 on the bass stem
    bi = ctx.p22_names.index("bass") if "bass" in ctx.p22_names else None
    bass_e = {t: float(ctx.p22[t][:, bi].sum()) if bi is not None else 0.0 for t in ctx.ids}
    kb = ctx.region(*model["regions_hz"]["kick_band"])
    kick_e = {t: float(ctx.bp[t][:, kb].sum()) for t in ctx.ids}
    _, (b, _) = _resolve_kick_bass(ctx.meta, ctx.ids, kick_e, bass_e)
    if b is not None:
        p08 = _p08(ctx.arr[b], ctx.sr, None, model, yins[b])
        p08["track"] = b
        p08["missing_fundamental"] = _missing_fundamental(ctx.arr[b], ctx.sr, None, None, model, yins[b])
        out["P-08"] = p08
    else:
        out["P-08"] = None
    out["P-09"] = _p09(feats, ctx.meta, ctx.ids, declared_order, model)
    out["P-10"] = _p10(ctx, sections)
    if before is not None and after is not None:
        if isinstance(before, dict) and isinstance(after, dict):
            per = {str(t): _p12(before[t], after[t], ctx.sr, model) for t in before if t in after}
            ps = [v["penalty"] for v in per.values() if v["penalty"] is not None]
            out["P-12"] = {"per_track": per, "penalty": float(np.mean(ps)) if ps else None}
        else:
            out["P-12"] = _p12(before, after, ctx.sr, model)
    else:
        out["P-12"] = None
    out["P-13"] = _p13(ctx, yins, key_tonic_hz, model)
    per15 = dict(zip(ctx.ids, _pmap(lambda t: _p15(ctx.arr[t], ctx.sr, model, feats[t]), ctx.ids)))
    lead, lsrc = _resolve_lead(ctx.meta, ctx.ids, {t: float(ctx.clar[t].sum()) for t in ctx.ids})
    out["P-15"] = {"per_stem": per15, "lead": lead, "lead_source": lsrc,
                   "penalty": per15[lead]["penalty"] if lead is not None else None}
    out["P-22"] = _p22(ctx, sections)
    out["notes"] = notes
    return _clean(out)


__all__ = [
    "stem_features", "masking_matrix", "harmonic_completion", "missing_fundamental_check",
    "depth_order", "lead_band_difference", "transient_retention", "low_tuning",
    "reverb_metrics", "band_density", "measure_stem_context",
]
