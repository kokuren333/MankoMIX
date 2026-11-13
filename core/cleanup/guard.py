"""Noise-return guard (S-08, SPEC 6.7) and cleanup side effects (P-21).

The P-16 metrics of the cleaned signal are stored as the "noise baseline".
After mastering, the same metrics are measured again; level metrics are
compared after removing the master's overall gain change, ratio metrics
(the shimmer index) are gain-invariant by construction.
"""

from __future__ import annotations

import numpy as np
from scipy import fft as sfft

from ._util import as_2d, db10, load_policy, rnd, v
from .diagnose import noise_shimmer_metrics

BASELINE_KEYS = ("noise_floor_dbfs", "noise_floor_hf_dbfs", "shimmer_index_db",
                 "side_shimmer_index_db", "hf_ceiling_hz", "above_ceiling_level_db")


def _integrated(x2d: np.ndarray, sr: float) -> float | None:
    try:
        from ..measure.loudness import integrated
        val = float(integrated(x2d, sr))
        return val if np.isfinite(val) else None
    except Exception:  # pragma: no cover - measurement module unavailable
        return None


def noise_baseline(x_clean, sr: float, *, policy: dict | None = None,
                   metrics: dict | None = None) -> dict:
    """P-16 after cleanup, kept as the S-08 reference."""
    policy = policy or load_policy()
    x2d, _ = as_2d(x_clean)
    m = metrics or noise_shimmer_metrics(x2d, sr, policy=policy, with_clicks=False)
    base = {k: m.get(k) for k in BASELINE_KEYS}
    base["integrated_lufs"] = rnd(_integrated(x2d, sr))
    base["sr"] = int(sr)
    base["kind"] = "cleanup_noise_baseline"
    return base


def noise_return_check(baseline: dict, x_master, sr: float, gain_db: float | None = None, *,
                       policy: dict | None = None) -> dict:
    """S-08: compare P-16 of the master with the cleanup baseline.

    ``gain_db`` is the master's overall gain change relative to the cleaned
    signal; if None it is estimated from the integrated loudness difference.
    Level metrics are compensated by it before comparison.
    """
    policy = policy or load_policy()
    tol = policy["s08"]
    x2d, _ = as_2d(x_master)
    m = noise_shimmer_metrics(x2d, sr, policy=policy, with_clicks=False)
    gain_source = "given"
    if gain_db is None:
        lm = _integrated(x2d, sr)
        lb = baseline.get("integrated_lufs")
        gain_db = (lm - lb) if (lm is not None and lb is not None) else 0.0
        gain_source = "integrated_loudness" if (lm is not None and lb is not None) else "assumed_zero"
    g = float(gain_db)
    checks = {}

    def _cmp(key: str, tol_key: str, compensate: bool):
        b = baseline.get(key)
        a = m.get(key)
        if a is None or b is None:
            checks[key] = {"before": b, "after": a, "delta_db": None, "tolerance_db": None,
                           "pass": None, "note": "not measurable"}
            return
        d = float(a) - (g if compensate else 0.0) - float(b)
        t = float(v(tol[tol_key]))
        checks[key] = {"before": b, "after": a, "gain_compensated": compensate,
                       "delta_db": rnd(d), "tolerance_db": t, "pass": bool(d <= t)}

    _cmp("shimmer_index_db", "shimmer_index_tol_db", False)
    _cmp("side_shimmer_index_db", "shimmer_index_tol_db", False)
    _cmp("noise_floor_dbfs", "noise_floor_tol_db", True)
    _cmp("noise_floor_hf_dbfs", "noise_floor_hf_tol_db", True)
    _cmp("above_ceiling_level_db", "above_ceiling_tol_db", False)
    judged = [c["pass"] for c in checks.values() if c["pass"] is not None]
    ok = all(judged) if judged else True
    suggestions = []
    if not ok:
        hf_fail = any(checks[k]["pass"] is False for k in
                      ("shimmer_index_db", "side_shimmer_index_db", "noise_floor_hf_dbfs",
                       "above_ceiling_level_db") if k in checks)
        nf_fail = checks.get("noise_floor_dbfs", {}).get("pass") is False
        if hf_fail:
            suggestions.append({"action": "reduce_hf_boost",
                                "text": "reduce the high-shelf / air boost of the master EQ "
                                        "(shimmer or HF noise rose above the cleanup baseline)"})
        if nf_fail or hf_fail:
            suggestions.append({"action": "reduce_limiter_drive",
                                "text": "reduce limiter drive / loudness target: quiet passages "
                                        "were lifted relative to the music"})
    return {"check": "S-08", "pass": bool(ok), "gain_db": rnd(g), "gain_source": gain_source,
            "deltas": checks, "suggestions": suggestions,
            "note": "tolerances are initial values (knowledge/cleanup_policy.json s08)"}


def _spectra(x2d: np.ndarray) -> dict:
    """One-sided power spectra (Parseval-weighted) of the channel sum and,
    for stereo, of mid and side, from one FFT per channel."""
    n = x2d.shape[0]
    nfft = sfft.next_fast_len(max(n, 1), real=True)
    w = np.full(nfft // 2 + 1, 2.0 / nfft)
    w[0] = 1.0 / nfft
    if nfft % 2 == 0:
        w[-1] = 1.0 / nfft
    specs = [sfft.rfft(x2d[:, c], nfft) for c in range(x2d.shape[1])]
    total = sum((s.real ** 2 + s.imag ** 2) for s in specs) * w
    out = {"total": total, "f": lambda sr: np.arange(nfft // 2 + 1) * (sr / nfft)}
    if len(specs) == 2:
        m = 0.5 * (specs[0] + specs[1])
        sd = 0.5 * (specs[0] - specs[1])
        out["mid"] = (m.real ** 2 + m.imag ** 2) * w
        out["side"] = (sd.real ** 2 + sd.imag ** 2) * w
    return out


def _band_sum(p: np.ndarray, f: np.ndarray, lo: float, hi: float) -> float:
    return float(np.sum(p[(f >= lo) & (f < hi)]))


def side_effects(before, after, sr: float, *, policy: dict | None = None) -> dict:
    """P-21: per-band stereo width change and 250-500 Hz energy change."""
    policy = policy or load_policy()
    pp = policy["p21"]
    b2d, _ = as_2d(before)
    a2d, _ = as_2d(after)
    bands = [(name, float(lo), float(hi)) for name, (lo, hi)
             in zip(v(pp["band_names"]), v(pp["bands_hz"])) if lo < sr / 2.0]
    min_e = 10.0 ** (float(v(pp["min_band_energy_db"])) / 10.0) * b2d.shape[0]
    width_tol = float(v(pp["width_tol_db"]))
    lm_tol = float(v(pp["lowmid_tol_db"]))
    sb = _spectra(b2d)
    sa = _spectra(a2d)
    eb = _band_sum(sb["total"], sb["f"](sr), 250.0, 500.0)
    ea = _band_sum(sa["total"], sa["f"](sr), 250.0, 500.0)
    lm = db10(ea) - db10(eb) if (eb > 0 and ea > 0) else (0.0 if eb == ea else None)
    lm_pass = None if lm is None else bool(abs(lm) <= lm_tol)
    width: dict | None = None
    width_pass = None
    if b2d.shape[1] == 2 and a2d.shape[1] == 2:
        width = {}
        width_pass = True
        fb, fa = sb["f"](sr), sa["f"](sr)
        for name, lo, hi in bands:
            mb, sbs = _band_sum(sb["mid"], fb, lo, hi), _band_sum(sb["side"], fb, lo, hi)
            ma, sas = _band_sum(sa["mid"], fa, lo, hi), _band_sum(sa["side"], fa, lo, hi)
            tb, ta = mb + sbs, ma + sas
            if tb <= min_e or ta <= min_e:
                width[name] = {"side_ratio_before": None, "side_ratio_after": None,
                               "change_db": None, "pass": None}
                continue
            rb = sbs / tb
            ra = sas / ta
            ch = 0.0 if (rb <= 1e-12 and ra <= 1e-12) else db10(ra) - db10(rb)
            ok = bool(ch >= -width_tol)
            width_pass = width_pass and ok
            width[name] = {"side_ratio_before": rnd(rb, 5), "side_ratio_after": rnd(ra, 5),
                           "change_db": rnd(ch), "pass": ok}
    judged = [p for p in (lm_pass, width_pass) if p is not None]
    return {"check": "P-21", "width_change": width,
            "lowmid_250_500_change_db": rnd(lm),
            "width_tolerance_db": width_tol, "lowmid_tolerance_db": lm_tol,
            "pass": bool(all(judged)) if judged else True}
