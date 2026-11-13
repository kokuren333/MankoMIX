"""OF-5 translation gate (SPEC 4.5, 5.2 playback_assumptions).

A pass/fail check placed after every score objective. A failing gate makes a
candidate a correction target regardless of its score (4.1 item 3).

Checks (ids follow objectives/catalog.json, "translation".checks):

1. band_limited_lead_preserved      small-speaker preview (high-pass ~150 Hz,
   low-pass ~8 kHz): the lead keeps its relation to the accompaniment and its
   own level does not collapse. Needs stems.
2. mono_fold_loss_within_limit      P-06 per band on the mono fold within the
   S-04 limits of knowledge/thresholds.json (stricter low band when the
   profile asks for mono_fold_strict); no band cancels. With stems the lead
   stem's own clarity-band mono loss is checked too.
3. low_level_balance_preserved      the lead/accompaniment relation weighted
   with the ISO 226 contour at a low listening level (60 phon) stays within a
   tolerance of the relation at the reference level (80 phon). Needs stems.
4. pitch_preserved_without_fundamental  missing-fundamental check (P-08): after
   a high-pass at 120 Hz the bass pitch is still detected. Uses the bass stem,
   or the low-passed 2mix as a proxy.

Statuses: "pass", "fail", "not_evaluated". A check the profile does not ask
for is "not_evaluated" with required=False. A lead check on a 2mix without
stems is "not_evaluated" with reason "not_evaluable_without_stems": it is not
a pass. Overall status: "fail" if any required check fails, "pass" if every
required check passed, else "incomplete"; ``pass`` is True only for "pass".
"""

from __future__ import annotations

import math

import numpy as np
from scipy import fft as sfft
from scipy import signal as ss

from . import config

CHECK_IDS = ("band_limited_lead_preserved", "mono_fold_loss_within_limit",
             "low_level_balance_preserved", "pitch_preserved_without_fundamental")
_EPS = 1e-20


def _cfg() -> dict:
    return config.load_knowledge("objective_metrics")["gate"]


def _th() -> dict:
    return config.load_knowledge("thresholds")


def _tv(th: dict, *path, default=None):
    cur = th
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    if isinstance(cur, dict) and "value" in cur:
        return cur["value"]
    return cur


def _frames(x) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    return a


def _db10(v: float) -> float | None:
    return 10.0 * math.log10(v) if v > _EPS else None


def _check(cid: str, status: str, *, required: bool = True, values: dict | None = None,
           threshold: dict | None = None, reason: str | None = None) -> dict:
    out = {"id": cid, "status": status, "required": required, "values": values or {},
           "threshold": threshold or {}}
    if reason:
        out["reason"] = reason
    return out


# --------------------------------------------------------------------------
# stems helpers


def _pad_to(a: np.ndarray, n: int) -> np.ndarray:
    if a.shape[0] >= n:
        return a[:n]
    return np.vstack([a, np.zeros((n - a.shape[0], a.shape[1]))])


def _lead_and_acc(stems: dict, lead: str):
    arrs = {k: _frames(v) for k, v in stems.items()}
    n = max(a.shape[0] for a in arrs.values())
    ch = max(a.shape[1] for a in arrs.values())
    arrs = {k: _pad_to(np.repeat(a, ch, axis=1) if a.shape[1] == 1 and ch > 1 else a, n) for k, a in arrs.items()}
    lead_x = arrs[lead]
    acc = np.zeros_like(lead_x)
    for k, a in arrs.items():
        if k != lead:
            acc += a
    return lead_x, acc


def _active_mask(lead_mono: np.ndarray, sr: float) -> np.ndarray:
    """Sample mask of frames (~46 ms) where the lead is active (same gate idea as stems.py)."""
    model = config.load_knowledge("masking_model")["activity_gate"]
    frame = max(16, int(round(0.046 * sr)))
    n = lead_mono.size
    k = max(1, n // frame)
    blk = lead_mono[: k * frame].reshape(k, frame)
    lev = 10.0 * np.log10(np.mean(blk * blk, axis=1) + _EPS)
    top = float(np.percentile(lev, 95)) if lev.size else -400.0
    act = (lev > model["abs_dbfs"]) & (lev > top - model["rel_db_below_p95"])
    mask = np.zeros(n, dtype=bool)
    for i in np.flatnonzero(act):
        mask[i * frame:(i + 1) * frame] = True
    return mask


def _power_spectrum(x: np.ndarray, sr: float) -> tuple[np.ndarray, np.ndarray]:
    """Channel-averaged power per rfft bin (Parseval-scaled) and the bin frequencies."""
    n = x.shape[0]
    nfft = sfft.next_fast_len(max(n, 16), real=True)
    X = sfft.rfft(x, n=nfft, axis=0)
    p = (X.real ** 2 + X.imag ** 2).mean(axis=1) / (nfft * max(n, 1))
    f = sfft.rfftfreq(nfft, 1.0 / sr)
    return p, f


def _bandlimit_gain(f: np.ndarray, sr: float, hp: float, lp: float, order: int) -> np.ndarray:
    """|H|^2 of a Butterworth high-pass + low-pass (small-speaker model)."""
    sos_h = ss.butter(order, hp, btype="highpass", fs=sr, output="sos")
    _, hh = ss.sosfreqz(sos_h, worN=f, fs=sr)
    g = np.abs(hh) ** 2
    if lp < 0.5 * sr:
        sos_l = ss.butter(order, lp, btype="lowpass", fs=sr, output="sos")
        _, hl = ss.sosfreqz(sos_l, worN=f, fs=sr)
        g = g * np.abs(hl) ** 2
    return g


# --------------------------------------------------------------------------
# checks


def _check_band_limited(lead_p, acc_p, f, sr, cfg) -> dict:
    c = cfg["small_speaker"]
    g = _bandlimit_gain(f, sr, c["highpass_hz"], c["lowpass_hz"], int(c["order"]))
    el, ea = float(lead_p.sum()), float(acc_p.sum())
    elb, eab = float((lead_p * g).sum()), float((acc_p * g).sum())
    d_full = _db10(el / ea) if ea > _EPS and el > _EPS else None
    d_bl = _db10(elb / eab) if eab > _EPS and elb > _EPS else None
    retained = _db10(elb / el) if el > _EPS and elb > _EPS else None
    thr = {"lead_drop_tolerance_db": c["lead_drop_tolerance_db"], "lead_retained_min_db": c["lead_retained_min_db"],
           "preview_hz": [c["highpass_hz"], c["lowpass_hz"]]}
    vals = {"lead_vs_acc_full_db": d_full, "lead_vs_acc_band_limited_db": d_bl, "lead_retained_db": retained}
    if d_full is None or d_bl is None or retained is None:
        return _check(CHECK_IDS[0], "not_evaluated", values=vals, threshold=thr,
                      reason="lead or accompaniment silent in the preview band")
    ok = d_bl >= d_full - c["lead_drop_tolerance_db"] and retained >= c["lead_retained_min_db"]
    return _check(CHECK_IDS[0], "pass" if ok else "fail", values=vals, threshold=thr)


def _check_low_level(lead_p, acc_p, f, cfg) -> dict:
    from .analysis.erb import equal_loudness_weight_db
    c = cfg["low_level"]
    ff = np.maximum(f, 20.0)
    w_ref = 10.0 ** (equal_loudness_weight_db(ff, c["phon_reference"]) / 10.0)
    w_low = 10.0 ** (equal_loudness_weight_db(ff, c["phon_low"]) / 10.0)
    band = (f >= 20.0) & (f <= 20000.0)
    w_ref, w_low = w_ref * band, w_low * band

    def rel(w):
        a, b = float((lead_p * w).sum()), float((acc_p * w).sum())
        return _db10(a / b) if a > _EPS and b > _EPS else None

    d_ref, d_low = rel(w_ref), rel(w_low)
    thr = {"tolerance_db": c["tolerance_db"], "phon_low": c["phon_low"], "phon_reference": c["phon_reference"]}
    vals = {"lead_vs_acc_reference_level_db": d_ref, "lead_vs_acc_low_level_db": d_low,
            "change_db": None if d_ref is None or d_low is None else d_low - d_ref}
    if vals["change_db"] is None:
        return _check(CHECK_IDS[2], "not_evaluated", values=vals, threshold=thr, reason="lead or accompaniment silent")
    ok = abs(vals["change_db"]) <= c["tolerance_db"]
    return _check(CHECK_IDS[2], "pass" if ok else "fail", values=vals, threshold=thr)


def _check_mono(x, sr, cfg, boundary, strict, required, lead_x=None) -> dict:
    from . import master_analysis as ma
    from .measure.bands import BANDS_P22, Spectrum
    from .measure.stereo import band_stereo
    th = _th()
    low_max = float(_tv(th, "s04_mono_loss", "low_band_max_db", default=1.5))
    if strict:
        low_max = min(low_max, float(cfg["mono_fold"]["strict_low_band_max_db"]))
    band = _tv(th, "s04_mono_loss", "lead_clarity_band_hz", default=[300, 5000])
    clar_max = float(_tv(th, "s04_mono_loss", "lead_clarity_max_db", default=3.0))
    any_max = float(cfg["mono_fold"]["any_band_max_db"])
    thr = {"low_band_max_db": low_max, "low_band_hz": [20.0, boundary], "lead_clarity_band_hz": band,
           "lead_clarity_max_db": clar_max, "any_band_max_db": any_max, "strict": bool(strict),
           "source": "knowledge/thresholds.json S-04 (+ gate values)"}
    a = _frames(x)
    if a.shape[1] < 2:
        return _check(CHECK_IDS[1], "pass", required=required, values={"note": "mono signal"}, threshold=thr)
    low = ma.mono_loss_db(a, sr, 20.0, boundary)
    clar = ma.mono_loss_db(a, sr, float(band[0]), float(band[1]))
    st = band_stereo(Spectrum(a, sr), BANDS_P22) or {"bands": {}}
    per = {k: {"mono_loss_db": v.get("mono_loss_db"), "cancelled": v.get("cancelled")}
           for k, v in st["bands"].items() if not v.get("silent")}
    problems = []
    if low is not None and low > low_max:
        problems.append(f"low band (< {boundary:.0f} Hz) loses {low:.1f} dB in mono")
    if clar is not None and clar > clar_max:
        problems.append(f"clarity band loses {clar:.1f} dB in mono")
    for k, v in per.items():
        if v["cancelled"]:
            problems.append(f"band '{k}' cancels in mono")
        elif v["mono_loss_db"] is not None and v["mono_loss_db"] > any_max:
            problems.append(f"band '{k}' loses {v['mono_loss_db']:.1f} dB in mono")
    vals = {"low_band_mono_loss_db": low, "clarity_band_mono_loss_db": clar, "bands": per}
    if lead_x is not None and _frames(lead_x).shape[1] >= 2:
        ll = ma.mono_loss_db(_frames(lead_x), sr, float(band[0]), float(band[1]))
        vals["lead_stem_clarity_mono_loss_db"] = ll
        thr["lead_stem_clarity_max_db"] = cfg["mono_fold"]["lead_stem_clarity_max_db"]
        if ll is not None and ll > cfg["mono_fold"]["lead_stem_clarity_max_db"]:
            problems.append(f"lead stem loses {ll:.1f} dB in mono")
    vals["problems"] = problems
    return _check(CHECK_IDS[1], "fail" if problems else "pass", required=required, values=vals, threshold=thr)


def _check_pitch(src, sr, cfg, required, proxy: str | None) -> dict:
    from .analysis.stems import harmonic_completion, missing_fundamental_check
    mf = missing_fundamental_check(src, sr)
    hc = harmonic_completion(src, sr)
    model = config.load_knowledge("masking_model")["p08"]
    thr = {"hp_hz": mf.get("hp_hz"), "min_agreement": model["min_agreement"],
           "pitch_agree_cents": model["pitch_agree_cents"]}
    vals = {"f0_hz": mf.get("f0_hz"), "agreement_ratio": mf.get("agreement_ratio"),
            "fundamental_below_cutoff": mf.get("fundamental_below_cutoff"),
            "median_f0_after_hp_hz": mf.get("median_f0_after_hp_hz"),
            "harmonic_index_db": hc.get("index_db"), "source": proxy or "bass stem",
            "caveat": mf.get("caveat")}
    if not mf.get("available"):
        return _check(CHECK_IDS[3], "not_evaluated", required=required, values=vals, threshold=thr,
                      reason=mf.get("reason") or "no bass pitch detected")
    if not mf.get("fundamental_below_cutoff"):
        vals["note"] = "the fundamental is above the high-pass; nothing is removed"
        return _check(CHECK_IDS[3], "pass", required=required, values=vals, threshold=thr)
    return _check(CHECK_IDS[3], "pass" if mf.get("preserved") else "fail", required=required,
                  values=vals, threshold=thr)


def _bass_stem(stems: dict, meta: dict | None) -> str | None:
    meta = meta or {}
    cands = [k for k in stems if (meta.get(k) or {}).get("role") == "bass" or "808" in str(k).lower()
             or "bass" in str(k).lower()]
    return cands[0] if cands else None


def _suggestions(checks: list[dict]) -> list[dict]:
    out = []
    for c in checks:
        if c["status"] != "fail":
            continue
        if c["id"] == CHECK_IDS[0]:
            out.append({"check": c["id"], "rule": "R-28",
                        "text": "the lead loses its place on small speakers: lower competing accompaniment in "
                                "300 Hz - 5 kHz rather than boosting the lead's low end"})
        elif c["id"] == CHECK_IDS[1]:
            out.append({"check": c["id"], "rule": "R-09",
                        "text": "mono fold loses level: mono the low band below the boundary (stereo "
                                "mono_below_hz) or fix the anti-phase source at the mix stage; reduce Haas-style width (R-10)"})
        elif c["id"] == CHECK_IDS[2]:
            out.append({"check": c["id"], "rule": "R-03",
                        "text": "the lead/accompaniment relation shifts at low listening level: the lead relies on "
                                "low or very high frequencies; move its weight towards 1-4 kHz or lower the accompaniment"})
        elif c["id"] == CHECK_IDS[3]:
            out.append({"check": c["id"], "rule": "R-16",
                        "text": "the bass pitch disappears without its fundamental: add upper harmonics "
                                "(saturation on the bass, P-08) so small speakers still convey the bass line"})
    return out


def evaluate_gate(x, sr: int, *, stems: dict | None = None, meta: dict | None = None,
                  profile: dict | str | None = None, lead: str | None = None, bass: str | None = None,
                  strict_mono: bool = False) -> dict:
    """Run the OF-5 checks on a (rendered) signal.

    x: the full mix [frames, channels]; stems: {track_id: array} for the lead
    checks (lead = declared lead track id; without it a 'vocals' stem from
    meta is used); profile: media profile (dict or id) whose
    playback_assumptions decide which checks apply and how strict.
    Returns {pass, status, checks[], corrective_suggestions[], profile, notes}.
    """
    if isinstance(profile, str):
        profile = config.get_profile(profile)
    pa = (profile or {}).get("playback_assumptions") or {}
    small = bool(pa.get("small_speaker_check", True))
    mono_req = bool(pa.get("mono_fold_check", True))
    low_req = bool(pa.get("low_level_check", True))
    strict = bool(pa.get("mono_fold_strict", False)) or bool(strict_mono)
    boundary = float(pa.get("mono_low_band_hz") or _tv(_th(), "s03_low_band_phase", "boundary_hz", default=120.0))
    cfg = _cfg()
    sr = int(sr)
    a = _frames(x)
    notes = []

    if stems and lead is None:
        voc = [k for k in stems if ((meta or {}).get(k) or {}).get("role") == "vocals"]
        if voc:
            lead = voc[0]
            notes.append("lead estimated from the 'vocals' role")
    lead_x = acc = None
    if stems and lead in stems and len(stems) >= 2:
        lead_x, acc = _lead_and_acc(stems, lead)

    checks: list[dict] = []
    # 1 + 3: lead checks
    if lead_x is not None:
        mask = _active_mask(lead_x.mean(axis=1), sr)
        if not mask.any():
            lp = ap = f = None
        else:
            lp, f = _power_spectrum(lead_x * mask[:, None], sr)
            ap, _ = _power_spectrum(acc * mask[:, None], sr)
    reason_no_stems = "not_evaluable_without_stems"
    if not small:
        checks.append(_check(CHECK_IDS[0], "not_evaluated", required=False, reason="not_required_by_profile"))
    elif lead_x is None:
        checks.append(_check(CHECK_IDS[0], "not_evaluated", reason=reason_no_stems))
    elif lp is None:
        checks.append(_check(CHECK_IDS[0], "not_evaluated", reason="lead never active"))
    else:
        checks.append(_check_band_limited(lp, ap, f, sr, cfg))
    # 2: mono fold
    if not mono_req:
        checks.append(_check(CHECK_IDS[1], "not_evaluated", required=False, reason="not_required_by_profile"))
    else:
        checks.append(_check_mono(a, sr, cfg, boundary, strict, True, lead_x))
    # 3
    if not low_req:
        checks.append(_check(CHECK_IDS[2], "not_evaluated", required=False, reason="not_required_by_profile"))
    elif lead_x is None:
        checks.append(_check(CHECK_IDS[2], "not_evaluated", reason=reason_no_stems))
    elif lp is None:
        checks.append(_check(CHECK_IDS[2], "not_evaluated", reason="lead never active"))
    else:
        checks.append(_check_low_level(lp, ap, f, cfg))
    # 4: fundamental removed (small-speaker condition)
    if not small:
        checks.append(_check(CHECK_IDS[3], "not_evaluated", required=False, reason="not_required_by_profile"))
    else:
        b = bass if (stems and bass in stems) else (_bass_stem(stems, meta) if stems else None)
        if b is not None:
            checks.append(_check_pitch(_frames(stems[b]), sr, cfg, True, None))
        else:
            from scipy.signal import butter, sosfiltfilt
            sos = butter(6, cfg["pitch"]["mix_lowpass_hz"], btype="lowpass", fs=sr, output="sos")
            src = sosfiltfilt(sos, a, axis=0)
            checks.append(_check_pitch(src, sr, cfg, True,
                                       f"2mix low-passed at {cfg['pitch']['mix_lowpass_hz']:.0f} Hz (proxy, no bass stem)"))

    req = [c for c in checks if c["required"]]
    if any(c["status"] == "fail" for c in req):
        status = "fail"
    elif req and all(c["status"] == "pass" for c in req):
        status = "pass"
    else:
        status = "incomplete"
    if not stems:
        notes.append("2mix only: lead checks are not evaluable without stems and are not counted as passes")
    from .measure.vector import json_safe
    return json_safe({
        "objective": "translation", "spec_id": "OF-5",
        "pass": status == "pass", "failed": status == "fail", "status": status,
        "checks": checks, "corrective_suggestions": _suggestions(checks),
        "profile": (profile or {}).get("id"),
        "playback_assumptions": {"small_speaker_check": small, "mono_fold_check": mono_req,
                                 "mono_fold_strict": strict, "low_level_check": low_req,
                                 "mono_low_band_hz": boundary},
        "lead": lead, "notes": notes,
    })


__all__ = ["CHECK_IDS", "evaluate_gate"]
