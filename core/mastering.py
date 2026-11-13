"""Mastering planner (SPEC 6.6, R-14, R-15, R-18, R-30, R-31).

``plan_master`` measures the master input, builds a chain in the fixed order
of S-06 / SPEC 6.6.2 and returns a *proposal* (R-31): processors with their
reasons, the rationale for every stage (measured -> rule -> action ->
alternatives -> expected), the expected result, warnings and an optional
send-back to the mix stage. Nothing is written until ``apply_master_plan``.

The limiter is a ceiling, not a loudness device (R-14): the chain is
simulated on the actual input and the limiter's gain-reduction statistics
(P-18) decide whether the target is reachable.

The noise-return guard (S-08, a hard constraint) is planned the same way: the
simulated master is checked against the baseline verify will use (the
route's master input, cleaned where cleanup applies; same frames, same gain
compensation). On a failure the planner first reduces any HF boost of the
chain, then lowers the loudness target within the profile window
(non-normalized media) or keeps the target and changes how the limiter is
driven (normalized media: release time, clipper share). The tolerance is
never relaxed; if nothing inside the window passes, the least-failing
candidate is kept and the master is sent back (rule S-08).
"""

from __future__ import annotations

import copy
import math
import re

import numpy as np

from . import config
from . import master_analysis as ma
from .errors import InputError, ValidationError
from .hashing import canonical_hash
from .measure import loudness as ld
from .routes import SCHEMA_ROUTE, load_master_input, route_warnings, select_route, stem_tracks

NON_NORMALIZED_PROFILES = ("club", "cd", "sns_hot", "soundcloud")

# Fixed master-stage order (S-06, SPEC 6.6.2). Slots come from dsp/processors.py
# (master_slot); ``gain`` is neutral (allowed anywhere before the limiter).
STAGE_NAMES = {1: "corrective_eq", 2: "dynamics", 3: "enhance", 4: "stereo", 5: "loudness", 6: "true_peak_limiter"}


# --------------------------------------------------------------------------
# data helpers


def thresholds() -> dict:
    """knowledge/thresholds.json (initial, calibratable values)."""
    return config.load_knowledge("thresholds")


def tv(th: dict, *path, default=None):
    """Value of a threshold entry ({value: ...} or plain) at a path."""
    cur = th
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    if isinstance(cur, dict) and "value" in cur:
        return cur["value"]
    return cur


_WHEN_RE = re.compile(r"^\s*lufs_i\s*(>=|<=|>|<|==)\s*(-?\d+(?:\.\d+)?)\s*$")


def _when(cond: str, lufs_i: float | None) -> bool:
    m = _WHEN_RE.match(cond or "")
    if not m or lufs_i is None:
        return False
    op, v = m.group(1), float(m.group(2))
    return {">": lufs_i > v, ">=": lufs_i >= v, "<": lufs_i < v, "<=": lufs_i <= v, "==": lufs_i == v}[op]


def conditional_threshold(profile: dict) -> tuple[str, float] | None:
    """(op, value) of the first lufs_i condition of the profile's conditional ceiling."""
    for c in (profile.get("true_peak") or {}).get("conditional") or []:
        m = _WHEN_RE.match(c.get("when", ""))
        if m:
            return m.group(1), float(m.group(2))
    return None


def effective_ceiling(profile: dict, lufs_i: float | None, override: float | None = None) -> float:
    """Profile TP ceiling with conditional rules (e.g. Spotify -2.0 when louder than -14)."""
    tp = profile.get("true_peak") or {}
    ceiling = float(tp.get("ceiling_dbtp", -1.0))
    for c in tp.get("conditional") or []:
        if _when(c.get("when", ""), lufs_i):
            ceiling = min(ceiling, float(c["ceiling_dbtp"]))
    if override is not None:
        ceiling = min(ceiling, float(override))
    return ceiling


def codec_after_ceiling(profile: dict, th: dict | None = None) -> float:
    tp = profile.get("true_peak") or {}
    if tp.get("codec_after_ceiling_dbtp") is not None:
        return float(tp["codec_after_ceiling_dbtp"])
    return float(tv(th or thresholds(), "s02_codec", "codec_after_ceiling_dbtp", default=-0.1))


def loudness_window(profile: dict) -> list[float] | None:
    w = (profile.get("loudness") or {}).get("window_lufs_i")
    return [float(w[0]), float(w[1])] if w else None


def is_normalized(profile: dict) -> bool:
    lo = profile.get("loudness") or {}
    return profile["id"] not in NON_NORMALIZED_PROFILES and lo.get("policy") == "gate"


def definition_hashes(profile: dict | None = None, delivery: dict | None = None,
                      objective_ids: list[str] | None = None) -> dict:
    out = {"thresholds": canonical_hash(thresholds())}
    if profile is not None:
        out["profile"] = {"id": profile["id"], "sha256": canonical_hash(profile)}
    if delivery is not None:
        out["delivery"] = {"id": delivery["id"], "sha256": canonical_hash(delivery)}
    if objective_ids:
        objs = []
        for oid in objective_ids:
            try:
                objs.append({"id": oid, "sha256": canonical_hash(config.get_objective(oid))})
            except Exception:  # unknown objective ids are reported, not fatal here
                objs.append({"id": oid, "sha256": None})
        out["objectives"] = objs
    return out


def objective_spec(project, objective=None) -> dict:
    """Normalized objective ({blend, intensity, ...}) from an argument or the project."""
    if objective is None:
        obj = copy.deepcopy(project.data.get("objective") or {"blend": [{"id": "comfort", "weight": 1.0}], "intensity": 0.5})
    elif isinstance(objective, str):
        obj = {"blend": [], "intensity": 0.5}
        for part in objective.split("+"):
            name, _, w = part.partition(":")
            obj["blend"].append({"id": name.strip(), "weight": float(w) if w else 1.0})
        if len(obj["blend"]) == 1 and objective.count(":") == 1:
            obj["intensity"] = obj["blend"][0]["weight"]
            obj["blend"][0]["weight"] = 1.0
    else:
        obj = copy.deepcopy(objective)
    for b in obj.get("blend", []):
        config.get_objective(b["id"])  # raises InputError on unknown ids
    return obj


def objective_ids(obj: dict | None) -> list[str]:
    return [b["id"] for b in (obj or {}).get("blend", [])]


# --------------------------------------------------------------------------
# chain order (S-06)


def _master_slot(ptype: str | None) -> int:
    """Master slot (1..6) of a processor type; 0 if neutral or not a master processor."""
    from mankomix.dsp import processors as _p
    d = _p.PROCESSORS.get(ptype or "")
    if d is None or "master" not in d.get("stages", []):
        return 0
    return int(d.get("master_slot") or 0)


def check_chain_order(chain: list[dict]) -> dict:
    """S-06: master chain in the fixed order, limiter last. Returns {status, issues}."""
    issues = []
    last_rank = 0
    enabled = [p for p in chain or [] if p.get("enabled", True) and not p.get("bypass", False)]
    for i, p in enumerate(enabled):
        rank = _master_slot(p.get("type"))
        if rank == 0:
            if p.get("type") == "gain":
                continue
            issues.append({"step": p.get("id"), "type": p.get("type"), "problem": "not allowed in the master stage"})
            continue
        if rank < last_rank:
            issues.append({"step": p.get("id"), "type": p.get("type"),
                           "problem": f"{STAGE_NAMES[rank]} after {STAGE_NAMES[last_rank]}"})
        last_rank = max(last_rank, rank)
        if p.get("type") == "limiter" and i != len(enabled) - 1:
            issues.append({"step": p.get("id"), "type": "limiter", "problem": "limiter is not the last stage"})
    lim = [p for p in enabled if p.get("type") == "limiter"]
    if len(lim) > 1:
        issues.append({"problem": "more than one limiter"})
    return {"status": "pass" if not issues else "fail", "issues": issues, "rule": "S-06"}


_ENGINE_KEYS = ("id", "type", "params", "backend", "bypass", "note")


def engine_chain(chain: list[dict]) -> list[dict]:
    """Project-file processors -> engine steps (drops 'reason'; enabled=false -> bypass)."""
    out = []
    for p in chain or []:
        step = {k: copy.deepcopy(p[k]) for k in _ENGINE_KEYS if k in p and p[k] is not None}
        if p.get("enabled") is False:
            step["bypass"] = True
        out.append(step)
    return out


def validate_master_chain(chain: list[dict]) -> None:
    """Raise ValidationError if the chain breaks S-06 or processor params are invalid."""
    res = check_chain_order(chain)
    if res["status"] != "pass":
        raise ValidationError("master chain violates the fixed order (S-06)", details=res)
    from mankomix.dsp import engine
    try:
        engine.validate_chain(engine_chain(chain), "master")
    except ValueError as exc:
        raise ValidationError(f"invalid master chain: {exc}",
                              details={"rule": getattr(exc, "rule", None), "step": getattr(exc, "step", None)}) from None


# --------------------------------------------------------------------------
# processor builders (parameter ids follow dsp/processors.py)


def _proc(pid: str, ptype: str, params: dict, reason: str) -> dict:
    return {"id": pid, "type": ptype, "params": params, "reason": reason}


def eq_proc(pid: str, shape: str, freq_hz: float, gain_db: float, bw_oct: float, reason: str) -> dict:
    """One parametric EQ band (minimum phase, bandwidth in octaves, R-12)."""
    return _proc(pid, "eq", {"shape": shape, "freq_hz": round(float(freq_hz), 1),
                             "gain_db": round(float(gain_db), 2), "bw_oct": round(float(bw_oct), 2),
                             "phase": "minimum"}, reason)


def compressor_proc(threshold_db: float, ratio: float, reason: str) -> dict:
    return _proc("mst_comp", "compressor", {"threshold_db": round(float(threshold_db), 2), "ratio": float(ratio),
                                            "knee_db": 6.0, "attack_ms": 30.0, "release_ms": 250.0,
                                            "detector": "rms", "rms_window_ms": 10.0}, reason)


def stereo_mono_bass_proc(boundary_hz: float, reason: str) -> dict:
    return _proc("mst_stereo", "stereo", {"mono_below_hz": float(boundary_hz)}, reason)


def gain_proc(gain_db: float, reason: str) -> dict:
    """Loudness reach (slot 5): limiter drive."""
    return _proc("mst_loudness", "loudness_gain", {"gain_db": round(float(gain_db), 3)}, reason)


DEFAULT_RELEASE_MS = 100.0


def limiter_proc(ceiling_dbtp: float, reason: str, release_ms: float = DEFAULT_RELEASE_MS) -> dict:
    return _proc("mst_limiter", "limiter", {"ceiling_dbtp": round(float(ceiling_dbtp), 3),
                                            "lookahead_ms": 3.0, "release_ms": float(release_ms), "oversample": 4},
                 reason)


def clipper_proc(ceiling_db: float, reason: str) -> dict:
    """Soft clipper before the limiter (slot 5): takes the peaks above its ceiling so the
    limiter's gain envelope moves less (clipper share)."""
    return _proc("mst_clipper", "clipper", {"mode": "soft", "ceiling_db": round(min(0.0, float(ceiling_db)), 3),
                                            "drive_db": 0.0, "softness": 0.3, "oversample": 4}, reason)


def drive_tail(gain_db: float, ceiling: float, style: dict | None = None, *,
               reasons: tuple[str, str] = ("R-18", "R-14,S-01")) -> list[dict]:
    """Loudness reach and limiter (slots 5-6): gain, optional clipper, true-peak limiter.

    ``style`` = {"release_ms": float, "clipper_headroom_db": float}; the clipper ceiling
    sits ``clipper_headroom_db`` above the limiter ceiling (at most 0 dBFS)."""
    style = style or {}
    tail = [gain_proc(gain_db, reasons[0])]
    if style.get("clipper_headroom_db") is not None:
        tail.append(clipper_proc(ceiling + float(style["clipper_headroom_db"]), "S-08,R-14"))
    tail.append(limiter_proc(ceiling, reasons[1], release_ms=float(style.get("release_ms") or DEFAULT_RELEASE_MS)))
    return tail


def limiter_ceiling(chain: list[dict]) -> float | None:
    for p in chain:
        if p.get("type") == "limiter":
            return float(p["params"].get("ceiling_dbtp"))
    return None


def with_limiter_ceiling(chain: list[dict], ceiling: float) -> list[dict]:
    out = copy.deepcopy(chain)
    for p in out:
        if p.get("type") == "limiter":
            p["params"]["ceiling_dbtp"] = round(float(ceiling), 3)
    return out


# --------------------------------------------------------------------------
# simulation


def _render(x: np.ndarray, sr: int, chain: list[dict]):
    from mankomix.dsp import engine
    return engine.render_chain(x, sr, engine_chain(chain), stage="master", seed=0)


def limiter_stats(result) -> dict:
    """GR statistics of the limiter step of a RenderResult (P-18)."""
    for st in getattr(result, "steps", []) or []:
        if st.get("type") == "limiter":
            s = st.get("stats") or {}
            g = s.get("gain_reduction") or s

            def val(*keys):
                for k in keys:
                    if g.get(k) is not None:
                        return ma.finite_or_none(g[k]) or 0.0
                return 0.0
            return {"gr_median_db": val("median_db", "gr_median_db"),
                    "gr_p95_db": val("p95_db", "gr_p95_db"),
                    "gr_fraction_gt_1db": val("frac_over_1db", "fraction_gt_1db"),
                    "gr_max_db": val("max_db", "gr_max_db")}
    return {"gr_median_db": 0.0, "gr_p95_db": 0.0, "gr_fraction_gt_1db": 0.0, "gr_max_db": 0.0}


def _limiter_out_tp(result, sr: int) -> float:
    for st in getattr(result, "steps", []) or []:
        if st.get("type") == "limiter":
            v = (st.get("stats") or {}).get("out_true_peak_dbtp")
            if v is not None:
                return float(v)
    return float(ld.true_peak_dbtp(result.audio, sr))


GAIN_RANGE_DB = (-60.0, 40.0)  # loudness_gain parameter range (dsp/processors.py)


def _clipper_stats(result) -> dict | None:
    for st in getattr(result, "steps", []) or []:
        if st.get("type") == "clipper":
            s = st.get("stats") or {}
            return {"frac_samples_over_ceiling_in": s.get("frac_samples_over_ceiling_in")}
    return None


def _converge(pre: np.ndarray, sr: int, target: float, ceiling: float, pre_lufs: float,
              tol: float = 0.05, max_iter: int = 6, warm: dict | None = None,
              style: dict | None = None) -> dict:
    """Find the limiter drive that lands the limited output on target (secant search).

    Limiting compresses the gain -> loudness slope, so a plain step undershoots;
    the secant uses the measured slope. Returns the closest simulation; its
    rendered audio is kept under ``_audio`` (in-memory only, for the S-08 check).
    """
    lo_g, hi_g = GAIN_RANGE_DB
    if warm and warm.get("ceiling") == ceiling and math.isfinite(warm.get("lufs_i", math.nan)):
        # warm start from a previous simulation on the same signal (slope of the limited curve)
        slope0 = min(1.0, max(0.05, float(warm.get("slope", 1.0))))
        gain = warm["gain_db"] + (target - warm["lufs_i"]) / slope0
    else:
        slope0 = 1.0
        gain = target - pre_lufs
    gain = min(hi_g, max(lo_g, gain))
    pts: list[tuple[float, float]] = []
    best = None
    for _ in range(max_iter):
        res = _render(pre, sr, drive_tail(gain, ceiling, style))
        out_l = float(ld.integrated(res.audio, sr))
        sim = {"gain_db": round(gain, 3), "lufs_i": out_l, "true_peak": _limiter_out_tp(res, sr),
               "limiter": limiter_stats(res), "target": target, "ceiling": ceiling, "reached": True,
               "style": dict(style or {}), "_audio": res.audio}
        clip = _clipper_stats(res)
        if clip is not None:
            sim["clipper"] = clip
        if best is None or abs(target - out_l) < abs(target - best["lufs_i"]):
            best = sim
        err = target - out_l
        if not math.isfinite(err) or abs(err) <= tol:
            break
        pts.append((gain, out_l))
        if len(pts) >= 2 and abs(pts[-1][1] - pts[-2][1]) > 1e-3:
            slope = (pts[-1][1] - pts[-2][1]) / (pts[-1][0] - pts[-2][0]) if pts[-1][0] != pts[-2][0] else 1.0
            slope = min(1.0, max(0.05, slope))
        else:
            slope = slope0
        new_gain = min(hi_g, max(lo_g, gain + err / slope))
        if abs(new_gain - gain) < 1e-4:
            break  # clamped at the parameter limit
        gain = new_gain
    if abs(target - best["lufs_i"]) > 0.5 and best["lufs_i"] < target:
        best["reached"] = False
    if len(pts) >= 2 and pts[-1][0] != pts[-2][0]:
        best["slope"] = (pts[-1][1] - pts[-2][1]) / (pts[-1][0] - pts[-2][0])
    else:
        best["slope"] = slope0
    return best


# --------------------------------------------------------------------------
# planner stages


def _plan_eq(x, sr, th, stems_exist: bool) -> tuple[list | None, dict, dict | None, list]:
    prior = th.get("generic_tonal_prior", {})
    bands = prior.get("bands", [])
    ratios = ma.band_energy_ratios(x, sr, bands)
    max_gain = float(tv(th, "master_eq", "max_abs_gain_db", default=2.0))
    act_db = float(tv(th, "master_eq", "min_deviation_to_act_db", default=3.0))
    frac = float(tv(th, "master_eq", "correction_fraction", default=0.5))
    moves, deviations, warnings = [], {}, []
    needs_more = False
    for b in bands:
        r = ratios.get(b["id"])
        if r is None:
            continue
        lo, hi = b["ratio_range"]
        if r < lo:
            dev = 10 * math.log10(max(r, 1e-12) / lo)
        elif r > hi:
            dev = 10 * math.log10(r / hi)
        else:
            dev = 0.0
        deviations[b["id"]] = {"ratio": round(r, 5), "prior_range": [lo, hi], "deviation_db": round(dev, 2)}
        if abs(dev) < act_db:
            continue
        want = -dev * frac
        if abs(want) > max_gain:
            needs_more = True
        g = max(-max_gain, min(max_gain, want))
        f_lo, f_hi = b["range_hz"]
        fc = math.sqrt(f_lo * f_hi)
        kind = "low_shelf" if b["id"] == "sub" else "high_shelf" if b["id"] == "air" else "peak"
        moves.append({"kind": kind, "freq_hz": round(f_hi if kind == "low_shelf" else f_lo if kind == "high_shelf" else fc, 1),
                      "gain_db": round(g, 2), "width_oct": round(max(1.0, math.log2(f_hi / f_lo)), 2),
                      "band": b["id"], "wanted_db": round(want, 2)})
    send_back = None
    measured = {"band_ratios_vs_generic_prior": deviations}
    if not moves:
        rat = {"stage": "corrective_eq", "measured": measured, "rule": "R-06",
               "action": {"ja": "明確な帯域の問題が測定されなかったため、EQ は入れない（0 dB）",
                          "en": "No clear band issue was measured, so no EQ is applied (0 dB)"},
               "alternatives": [{"ja": "汎用 prior に寄せる小さな補正", "en": "small moves toward the generic prior"}],
               "expected": {"eq_moves": 0}}
        return None, rat, None, warnings
    if needs_more and stems_exist:
        send_back = {"reason": {"ja": "マスター EQ の上限（約 2 dB）を超える補正が必要。ミックスの問題として差し戻す",
                                "en": "Correction beyond the master EQ limit (about 2 dB) is needed; sent back as a mix problem"},
                     "rule": "R-15", "measured": deviations}
    elif needs_more:
        warnings.append({"code": "eq_clamped", "rule": "R-15",
                         "message": {"ja": "必要な補正量が 2 dB を超えるが、ステムがないため 2 dB に制限して適用した",
                                     "en": "Needed correction exceeds 2 dB; no stems exist, so it was limited to 2 dB"}})
    proc = [eq_proc(f"mst_eq{i + 1}", m["kind"], m["freq_hz"], m["gain_db"], m["width_oct"], "R-06,R-15")
            for i, m in enumerate(moves)]
    rat = {"stage": "corrective_eq", "measured": measured, "rule": "R-06",
           "action": {"ja": "汎用 prior から大きく外れた帯域だけを ±2 dB 以内で補正",
                      "en": "Correct only bands far outside the generic prior, within +/-2 dB"},
           "moves": moves,
           "alternatives": [{"ja": "補正しない（ミックス段で直す）", "en": "no correction (fix at the mix stage)"},
                            {"ja": "マルチバンド処理（R-30 により既定では使わない）", "en": "multiband processing (not default, R-30)"}],
           "expected": {"eq_moves": len(moves)}}
    return proc, rat, send_back, warnings


def _plan_stereo(x, sr, th, profile) -> tuple[dict | None, dict]:
    boundary = float((profile.get("playback_assumptions") or {}).get("mono_low_band_hz")
                     or tv(th, "s03_low_band_phase", "boundary_hz", default=120.0))
    loss = ma.mono_loss_db(x, sr, 20.0, boundary)
    win = float(tv(th, "s03_low_band_phase", "window_s", default=0.4))
    pers = ma.negative_persistence(ma.windowed_correlation(x, sr, 20.0, boundary, win), win)
    trig = float(tv(th, "s04_mono_loss", "planner_mono_bass_trigger_db", default=1.0))
    max_run = float(tv(th, "s03_low_band_phase", "max_persistence_s", default=1.0))
    max_frac = float(tv(th, "s03_low_band_phase", "max_negative_fraction", default=0.1))
    measured = {"low_band_hz": boundary, "low_band_mono_loss_db": None if loss is None else round(loss, 2),
                "low_band_negative_corr": pers}
    problem = (loss is not None and loss > trig) or pers["longest_run_s"] > max_run or pers["negative_fraction"] > max_frac
    if not problem:
        return None, {"stage": "stereo", "measured": measured, "rule": "R-09",
                      "action": {"ja": "低域のモノ損失と逆相は許容内。ステレオ処理は入れない",
                                 "en": "Low-band mono loss and anti-phase are within limits; no stereo processing"},
                      "alternatives": [{"ja": f"{boundary:.0f} Hz 以下のモノ化", "en": f"mono below {boundary:.0f} Hz"}],
                      "expected": {}}
    return stereo_mono_bass_proc(boundary, "R-09,S-03,S-04"), {
        "stage": "stereo", "measured": measured, "rule": "R-09",
        "action": {"ja": f"{boundary:.0f} Hz 以下をモノにする（低域の逆相・モノ損失が測定されたため）",
                   "en": f"Mono below {boundary:.0f} Hz (low-band anti-phase / mono loss was measured)"},
        "alternatives": [{"ja": "ミックス段で原因のステムを直す", "en": "fix the offending stem at the mix stage"}],
        "expected": {"low_band_mono_loss_db": 0.0}}


def _target_and_window(profile, target_override):
    lo = profile.get("loudness") or {}
    window = loudness_window(profile)
    target = lo.get("target_lufs_i")
    if target_override is not None:
        target = float(target_override)
        if window and not (window[0] <= target <= window[1]):
            raise InputError(f"target {target} LUFS is outside the profile window {window}",
                             details={"window": window})
    return (None if target is None else float(target)), window


# --------------------------------------------------------------------------
# S-08 noise-return guard at planning time


_S08_DEFAULT_VARIANTS = [{"release_ms": 50.0}, {"release_ms": 30.0}, {"release_ms": 250.0},
                         {"clipper_headroom_db": 1.0}, {"release_ms": 30.0, "clipper_headroom_db": 1.0}]

_S08_LABEL = {"shimmer_index_db": "shimmer index", "side_shimmer_index_db": "side shimmer index",
              "noise_floor_dbfs": "noise floor", "noise_floor_hf_dbfs": "HF noise floor",
              "above_ceiling_level_db": "above-ceiling level"}


def s08_planning_config(th: dict | None = None) -> dict:
    th = th or thresholds()
    return {"margin_db": float(tv(th, "s08_planning", "plan_margin_db", default=0.2)),
            "hf_boost_min_hz": float(tv(th, "s08_planning", "hf_boost_min_hz", default=4000.0)),
            "hf_boost_factors": [float(f) for f in tv(th, "s08_planning", "hf_boost_reduction_factors",
                                                      default=[0.5, 0.0])],
            "normalized_variants": list(tv(th, "s08_planning", "normalized_limiter_variants",
                                           default=_S08_DEFAULT_VARIANTS))}


def s08_evaluate(baseline_info: dict, reference: dict, audio: np.ndarray, sr: int, lufs: float | None,
                 margin_db: float) -> dict:
    """S-08 on a simulated master (same baseline, frames and gain compensation as verify).

    The planner requires every delta to stay ``margin_db`` inside the tolerance (render-time
    resampling / dither / S-02 ceiling changes move the result a little); the tolerance itself
    is the verify one and is never relaxed. ``worst_excess_db`` = max(delta - (tol - margin))."""
    from .cleanstage import s08_check
    r = s08_check(baseline_info, audio, sr, lufs if (lufs is not None and math.isfinite(lufs)) else None,
                  reference=reference)
    return s08_reduce(r, margin_db)


def s08_reduce(r: dict, margin_db: float) -> dict:
    """Planner view of an S-08 check result (``s08_check`` or ``cleanup.noise_return_check``)."""
    deltas, failing, excess = {}, [], None
    for k, c in (r.get("deltas") or {}).items():
        if c.get("pass") is None or c.get("delta_db") is None:
            continue
        d, t = float(c["delta_db"]), float(c["tolerance_db"])
        deltas[k] = {"delta_db": round(d, 2), "tolerance_db": t}
        e = d - (t - margin_db)
        excess = e if excess is None else max(excess, e)
        if e > 1e-9:
            failing.append(k)
    status = "not_run" if excess is None else ("pass" if excess <= 1e-9 else "fail")
    vstat = r.get("status") or (None if "pass" not in r else ("pass" if r["pass"] else "fail"))
    return {"status": status, "verify_tolerance_status": vstat, "margin_db": margin_db,
            "worst_excess_db": None if excess is None else round(excess, 2), "deltas": deltas,
            "failing": failing, "gain_db": r.get("gain_db"), "frame_selection": r.get("frame_selection"),
            "suggestions": r.get("suggestions") or []}


def _hf_boost_ids(chain: list[dict], hf_min_hz: float) -> list[str]:
    """EQ steps that boost the high frequencies (any high-shelf boost, or a boost centred >= hf_min_hz)."""
    out = []
    for p in chain:
        if p.get("type") != "eq":
            continue
        pr = p.get("params") or {}
        if float(pr.get("gain_db") or 0.0) <= 0.0:
            continue
        if pr.get("shape") == "high_shelf" or float(pr.get("freq_hz") or 0.0) >= hf_min_hz:
            out.append(p["id"])
    return out


def _deltas_text(ev: dict, lang: str) -> str:
    parts = []
    for k, d in (ev.get("deltas") or {}).items():
        if ev.get("failing") and k not in ev["failing"]:
            continue
        name = _S08_LABEL.get(k, k)
        tol = (f"（許容 {d['tolerance_db']:.1f} dB）" if lang == "ja" else f" (tolerance {d['tolerance_db']:.1f} dB)")
        parts.append(f"{name} {d['delta_db']:+.1f} dB{tol}")
    return ", ".join(parts) if parts else "-"


def _s08_summary(ev: dict) -> dict:
    return {k: ev.get(k) for k in ("status", "verify_tolerance_status", "worst_excess_db", "margin_db",
                                   "deltas", "failing", "gain_db", "frame_selection")}


def _state_result(st: dict, ev: dict) -> dict:
    sim = st["sim"]
    out = {"s08": _s08_summary(ev), "target_lufs_i": sim["target"], "lufs_i": round(sim["lufs_i"], 2),
           "gain_db": sim["gain_db"], "limiter_gr_p95_db": round(sim["limiter"]["gr_p95_db"], 2)}
    if sim.get("style"):
        out["limiter_style"] = sim["style"]
    return out


def _style_text(style: dict) -> dict:
    ja, en = [], []
    if style.get("release_ms") is not None:
        ja.append(f"リリース {style['release_ms']:.0f} ms")
        en.append(f"release {style['release_ms']:.0f} ms")
    if style.get("clipper_headroom_db") is not None:
        ja.append(f"ソフトクリッパー（リミッター天井の {style['clipper_headroom_db']:.1f} dB 上）")
        en.append(f"soft clipper {style['clipper_headroom_db']:.1f} dB above the limiter ceiling")
    return {"ja": "、".join(ja), "en": ", ".join(en)}


def _plan_noise_return(project, route: dict, x: np.ndarray, sr: int, th: dict, profile: dict,
                       normalized: bool, candidates: list[float], rationale: list[dict], state0: dict) -> dict:
    """S-08 at planning time (see module docstring). Returns {state, tried, rationale, expected, send_back}.

    ``state`` = {sim, pre_chain, pre, pre_lufs}. The check runs on the simulated chain over the
    full input (the same signal the R-14 loop simulates). Each corrective step is recorded as
    measured -> rule -> action -> alternatives -> result.
    """
    from .cleanstage import route_baseline
    from .cleanup import reference_selection
    cfg = s08_planning_config(th)
    margin = cfg["margin_db"]
    base_info = route_baseline(project, route["route"], x, sr)
    ref = reference_selection(x, sr)

    def evaluate(st):
        return s08_evaluate(base_info, ref, st["sim"]["_audio"], sr, st["sim"]["lufs_i"], margin)

    def converge(st, target, ceiling, style, warm):
        return _converge(st["pre"], sr, target, ceiling, st["pre_lufs"], warm=warm, style=style)

    cur = dict(state0)
    ev = evaluate(cur)
    first = ev
    evaluated = [(ev, cur)]
    steps: list[dict] = []
    tried: list[dict] = []

    def record(action: dict, alternatives: list[dict], prev_ev: dict, st: dict, new_ev: dict, kind: str):
        steps.append({"step": len(steps) + 1, "kind": kind, "measured": {"s08": _s08_summary(prev_ev)},
                      "rule": "S-08", "action": action, "alternatives": alternatives,
                      "result": _state_result(st, new_ev)})
        sim_ = st["sim"]
        tried.append({"target": sim_["target"], "lufs_i": round(sim_["lufs_i"], 2),
                      "gr_p95_db": round(sim_["limiter"]["gr_p95_db"], 2), "s08": new_ev["status"],
                      "s08_worst_excess_db": new_ev["worst_excess_db"], "by": kind,
                      **({"limiter_style": sim_["style"]} if sim_.get("style") else {})})

    # step 1: reduce any HF boost of the chain (SPEC 6.7 corrective action)
    if ev["status"] == "fail":
        hf_ids = _hf_boost_ids(cur["pre_chain"], cfg["hf_boost_min_hz"])
        if not hf_ids:
            steps.append({"step": len(steps) + 1, "kind": "hf_boost", "measured": {"s08": _s08_summary(ev)},
                          "rule": "S-08",
                          "action": {"ja": "チェーンに高域のブーストがないため、高域ブーストの低減は該当しない",
                                     "en": "The chain has no HF boost, so reducing it does not apply"},
                          "alternatives": [], "result": None})
        orig = {p["id"]: float(p["params"]["gain_db"]) for p in cur["pre_chain"] if p["id"] in hf_ids}
        for f in (cfg["hf_boost_factors"] if hf_ids else []):
            chain2 = []
            for p in cur["pre_chain"]:
                if p["id"] in orig:
                    g = round(orig[p["id"]] * f, 2)
                    if abs(g) < 0.05:
                        continue  # boost removed
                    p = copy.deepcopy(p)
                    p["params"]["gain_db"] = g
                    p["reason"] = (p.get("reason") or "") + ",S-08"
                chain2.append(p)
            pre2 = _render(x, sr, chain2).audio if chain2 else x
            st = {"pre_chain": chain2, "pre": pre2, "pre_lufs": float(ld.integrated(pre2, sr))}
            st["sim"] = converge(st, cur["sim"]["target"], cur["sim"]["ceiling"], cur["sim"].get("style"), None)
            ev2 = evaluate(st)
            record({"ja": f"高域のブースト（{', '.join(sorted(orig))}）を {int(round(f * 100))}% に下げた",
                    "en": f"HF boost ({', '.join(sorted(orig))}) reduced to {int(round(f * 100))}%"},
                   [{"ja": "目標ラウドネスを下げる", "en": "lower the loudness target"},
                    {"ja": "ミックス段で高域を整える", "en": "fix the top end at the mix stage"}], ev, st, ev2, "hf_boost")
            evaluated.append((ev2, st))
            if (ev2["worst_excess_db"] is not None and ev["worst_excess_db"] is not None
                    and ev2["worst_excess_db"] <= ev["worst_excess_db"] + 1e-9):
                cur, ev = st, ev2  # keep the reduction: it helped (or passed)
            if ev["status"] != "fail":
                break
        if hf_ids:
            eq_rat = next((r for r in rationale if r.get("stage") == "corrective_eq"), None)
            kept = {p["id"]: float(p["params"]["gain_db"]) for p in cur["pre_chain"] if p.get("type") == "eq"}
            for i, m in enumerate((eq_rat or {}).get("moves") or []):
                pid = f"mst_eq{i + 1}"
                if pid in orig and kept.get(pid, 0.0) != orig[pid]:
                    m["s08_reduced_from_db"] = orig[pid]
                    m["gain_db"] = kept.get(pid, 0.0)

    # step 2: lower the target (non-normalized) or change the limiter drive (normalized)
    if ev["status"] == "fail":
        if not normalized:
            for t in [c for c in candidates if c < cur["sim"]["target"] - 1e-9]:
                st = {k: cur[k] for k in ("pre_chain", "pre", "pre_lufs")}
                st["sim"] = converge(st, t, effective_ceiling(profile, t), cur["sim"].get("style"), cur["sim"])
                ev2 = evaluate(st)
                record({"ja": f"目標ラウドネスを {cur['sim']['target']:.1f} から {t:.1f} LUFS に下げた（リミッターの駆動を下げる。レンジ内）",
                        "en": f"Loudness target lowered from {cur['sim']['target']:.1f} to {t:.1f} LUFS (less limiter drive, inside the window)"},
                       [{"ja": "リリース時間やクリッパーの分担を変える（リミッター依存度を隠すため、正規化されない媒体では自動では選ばない。R-14）",
                         "en": "change the release / clipper share (not chosen automatically for non-normalized media: it hides limiter dependency, R-14)"},
                        {"ja": "ミックス段へ差し戻す", "en": "send back to the mix stage"}], ev, st, ev2, "target")
                evaluated.append((ev2, st))
                cur, ev = st, ev2
                if ev["status"] != "fail":
                    break
        else:
            base_style = dict(cur["sim"].get("style") or {})
            for var in cfg["normalized_variants"]:
                style = {**base_style, **{k: float(val) for k, val in var.items()}}
                st = {k: cur[k] for k in ("pre_chain", "pre", "pre_lufs")}
                st["sim"] = converge(st, cur["sim"]["target"], cur["sim"]["ceiling"], style, cur["sim"])
                ev2 = evaluate(st)
                record({"ja": f"正規化される媒体のため目標 {cur['sim']['target']:.1f} LUFS を保ち、リミッターの駆動のしかたを変えた（{_style_text(style)['ja']}）",
                        "en": f"Normalized medium: kept the {cur['sim']['target']:.1f} LUFS target and changed how the limiter is driven ({_style_text(style)['en']})"},
                       [{"ja": "目標を下げる（正規化される媒体では配送条件なので下げない）",
                         "en": "lower the target (not for a normalized medium: the target is the delivery gate)"},
                        {"ja": "ミックス段へ差し戻す", "en": "send back to the mix stage"}], ev, st, ev2, "limiter_style")
                evaluated.append((ev2, st))
                if ev2["status"] != "fail":
                    cur, ev = st, ev2
                    break

    send_back = None
    if ev["status"] == "fail":
        # least-failing candidate (the earlier one on ties: less change)
        best_i = min(range(len(evaluated)),
                     key=lambda i: (evaluated[i][0]["worst_excess_db"] if evaluated[i][0]["worst_excess_db"] is not None
                                    else math.inf, i))
        ev, cur = evaluated[best_i]
        sim_ = cur["sim"]
        sugg = [{"action": "reduce_limiter_drive",
                 "text": {"ja": "ミックス段でピーク（キックやスネアのトランジェント）とリミッターの負担を減らし、マスターを薄い駆動で仕上げられるようにする",
                          "en": "reduce peaks (kick / snare transients) and limiter load at the mix stage so the master needs less drive"}},
                {"action": "clean_first",
                 "text": {"ja": "整音段（clean plan）でノイズとシマーを先に処理し、基準のノイズ床を下げる（R-20）",
                          "en": "treat noise and shimmer in the cleanup stage first (clean plan) to lower the baseline noise (R-20)"}}]
        if _hf_boost_ids(cur["pre_chain"], cfg["hf_boost_min_hz"]):
            sugg.insert(0, {"action": "reduce_hf_boost",
                            "text": {"ja": "マスター EQ の高域ブーストをさらに下げる", "en": "reduce the master EQ's HF boost further"}})
        if not normalized:
            sugg.append({"action": "limiter_style",
                         "text": {"ja": "人の判断で、リリースを短くするかクリッパーに一部を受け持たせて再検証する（リミッター依存度が見えにくくなる点に注意。R-14）",
                                  "en": "by human decision, try a faster release or a clipper share and verify again (it hides limiter dependency, R-14)"}})
        st_txt = _style_text(sim_.get("style") or {}) if sim_.get("style") else None
        where_en = f"{sim_['target']:.1f} LUFS" + (f", {st_txt['en']}" if st_txt else "")
        where_ja = f"{sim_['target']:.1f} LUFS" + (f"、{st_txt['ja']}" if st_txt else "")
        scope_ja = "プロファイルのレンジ内で目標を下げても" if not normalized else "目標を保ったままリミッターの駆動のしかたを変えても"
        scope_en = ("even with the target lowered within the profile window" if not normalized
                    else "even with the target kept and the limiter drive changed")
        send_back = {"rule": "S-08",
                     "reason": {"ja": f"ノイズ戻り監視（S-08）が{scope_ja}合格しない。最も悪化の小さい候補（{where_ja}）でも {_deltas_text(ev, 'ja')}。許容幅は緩めない。ミックス段（または整音段）へ差し戻す",
                                "en": f"The noise-return guard (S-08) does not pass {scope_en}. The least-failing candidate ({where_en}) still has {_deltas_text(ev, 'en')}. The tolerance is not relaxed; sent back to the mix (or cleanup) stage"},
                     "measured": {"s08": _s08_summary(ev), "target_lufs_i": sim_["target"],
                                  "lufs_i": round(sim_["lufs_i"], 2),
                                  "limiter_gr": {k: round(val, 2) for k, val in sim_["limiter"].items()}},
                     "suggestions": sugg}

    if first["status"] == "pass":
        action = {"ja": "シミュレーションしたマスターはノイズ戻り監視に合格（是正は不要）",
                  "en": "The simulated master passes the noise-return guard (no correction needed)"}
    elif first["status"] == "not_run":
        action = {"ja": "P-16 を測定できず、ノイズ戻り監視は計画時に評価できなかった（検証で再評価する）",
                  "en": "P-16 could not be measured; the guard was not evaluated at planning time (verify re-evaluates it)"}
    elif ev["status"] == "pass":
        action = {"ja": "ノイズ戻りの悪化を測定したため、是正（下の手順）を行い合格させた",
                  "en": "Noise return was measured; corrected (steps below) until the guard passes"}
    else:
        action = {"ja": "是正しても合格しないため、最も悪化の小さい候補を残してミックス段へ差し戻す",
                  "en": "Corrections did not pass; the least-failing candidate is kept and the master is sent back"}
    rat = {"stage": "noise_return_guard",
           "measured": {"s08": _s08_summary(first),
                        "baseline": {k: base_info.get(k) for k in ("source", "cleaned", "path")
                                     if base_info.get(k) is not None},
                        "scope": "full input, simulated chain", "frame_selection": "baseline frames, time aligned"},
           "rule": "S-08",
           "action": action,
           "alternatives": [{"ja": "許容幅を緩める（ハード制約なので行わない。SPEC 4.3）",
                             "en": "relax the tolerance (never: hard constraint, SPEC 4.3)"},
                            {"ja": "マルチバンド処理でノイズを抑える（R-30 により既定では使わない）",
                             "en": "suppress the noise with multiband processing (not default, R-30)"}],
           "expected": {"s08": _s08_summary(ev)},
           "steps": steps}
    return {"state": cur, "tried": tried, "rationale": rat, "send_back": send_back,
            "expected": {**_s08_summary(ev), "baseline_source": base_info.get("source"),
                         "corrective_steps": len([st for st in steps if st.get("result") is not None])}}


def plan_master(project, *, variant_id: str | None = None, profile_id: str,
                delivery_id: str | None = None, objective=None, target_lufs: float | None = None) -> dict:
    """Propose a master chain for one variant/profile (R-31 proposal form)."""
    profile = config.get_profile(profile_id)
    pid = profile["id"]
    delivery = config.get_delivery(delivery_id or profile.get("default_delivery") or "hires_native")
    th = thresholds()
    obj = objective_spec(project, objective)
    vid = variant_id or f"var_{pid}"

    route = select_route(project)
    x, sr = load_master_input(project, route["route"], variant_id=vid)
    stems_exist = bool(stem_tracks(project.data))
    warnings = list(route_warnings(route["route"]))
    rationale = []
    chain = []

    in_sum = ld.loudness_summary(x, sr)
    in_lufs = in_sum["integrated_lufs"]
    if not math.isfinite(in_lufs):
        raise InputError("master input is silent; nothing to master")

    # (1) corrective EQ
    eq, rat, send_back, w = _plan_eq(x, sr, th, stems_exist)
    rationale.append(rat)
    warnings += w
    if eq:
        chain.extend(eq)

    # (2) dynamics: off by default, single band only (R-30); may be enabled below
    dyn_rat = {"stage": "dynamics", "measured": {"plr_db": ma.finite_or_none(in_sum["plr_db"]),
                                                  "lra_lu": ma.finite_or_none(in_sum["lra_lu"])},
               "rule": "R-30",
               "action": {"ja": "既定でダイナミクス処理なし（マルチバンドは使わない）",
                          "en": "No dynamics processing by default (no multiband)"},
               "alternatives": [{"ja": "軽いシングルバンド・コンプ（1〜2 dB）", "en": "light single-band compression (1-2 dB)"},
                                {"ja": "マルチバンド（ミックスへ差し戻す代替としてのみ）", "en": "multiband (only as an alternative to a send-back)"}],
               "expected": {}}
    rationale.append(dyn_rat)

    # (3) enhance: off in M2
    rationale.append({"stage": "enhance", "measured": {}, "rule": "R-06",
                      "action": {"ja": "エンハンスは既定で使わない", "en": "No enhancement by default"},
                      "alternatives": [{"ja": "倍音付加（目的が説明できる場合のみ）", "en": "harmonic enhancement (only with a stated purpose)"}],
                      "expected": {}})

    # (4) stereo
    st, rat = _plan_stereo(x, sr, th, profile)
    rationale.append(rat)
    if st is not None:
        chain.append(st)

    pre_chain = list(chain)
    pre = _render(x, sr, pre_chain).audio if pre_chain else x
    pre_lufs = float(ld.integrated(pre, sr))

    # (5) loudness and (6) limiter
    target, window = _target_and_window(profile, target_lufs)
    normalized = is_normalized(profile)
    warn_p95 = float(tv(th, "p18_limiter_dependency", "gr_p95_warn_db", default=4.0))
    sb_p95 = float(tv(th, "p18_limiter_dependency", "gr_p95_send_back_db", default=5.0))
    step = float(tv(th, "loudness", "nonnormalized_step_lu", default=1.0))

    if target is None:  # objective-driven (soundcloud): loudest level with acceptable limiting
        candidates = [-11.0 - k * step for k in range(int(6 / step) + 1)]
    else:
        # the lowest candidate keeps a margin above the window floor: the S-02 loop may
        # still lower the ceiling (and the loudness) a little at render time
        margin = float(tv(th, "loudness", "window_floor_margin_lu", default=0.3))
        candidates = [target]
        floor = (window[0] + margin) if window else target
        t = target
        while t - step >= floor - 1e-9:
            t = round(t - step, 3)
            candidates.append(t)
        if window and candidates[-1] > floor + 1e-9:
            candidates.append(round(floor, 3))

    tried = []
    sim = None
    comp_added = False
    for t in candidates:
        ceiling = effective_ceiling(profile, t)
        sim = _converge(pre, sr, t, ceiling, pre_lufs, warm=sim)
        # avoid triggering a stricter conditional ceiling by landing just above a threshold
        cond = conditional_threshold(profile)
        if cond and effective_ceiling(profile, sim["lufs_i"]) < ceiling and target_lufs is None:
            t2 = cond[1] - 0.1 if cond[0] in (">", ">=") else t
            if window is None or window[0] <= t2:
                sim = _converge(pre, sr, t2, ceiling, pre_lufs, warm=sim)
        tried.append({"target": t, "lufs_i": round(sim["lufs_i"], 2), "gr_p95_db": round(sim["limiter"]["gr_p95_db"], 2)})
        p95 = sim["limiter"]["gr_p95_db"]
        if p95 > warn_p95 and not comp_added and t == candidates[0]:
            # gentle single-band compression before giving up loudness (R-30)
            comp_added = True
            thr = pre_lufs + 6.0
            comp = compressor_proc(thr, 1.5, "R-30,R-14")
            chain_c = pre_chain + [comp]
            pre_c = _render(x, sr, chain_c).audio
            pre_c_l = float(ld.integrated(pre_c, sr))
            sim_c = _converge(pre_c, sr, t, ceiling, pre_c_l)
            if sim_c["limiter"]["gr_p95_db"] < p95 - 0.5:
                pre_chain, pre, pre_lufs, sim = chain_c, pre_c, pre_c_l, sim_c
                p95 = sim["limiter"]["gr_p95_db"]
                dyn_rat["action"] = {"ja": "リミッターの負担を減らすため、軽いシングルバンド・コンプ（1.5:1）を入れた",
                                     "en": "Light single-band compression (1.5:1) to reduce limiter load"}
                dyn_rat["rule"] = "R-30"
                tried[-1]["with_compressor"] = round(p95, 2)
        if p95 <= sb_p95:
            break

    r14_target = sim["target"]

    # (S-08) noise-return guard on the simulated master, against the baseline verify uses
    s08 = _plan_noise_return(project, route, x, sr, th, profile, normalized, candidates, rationale,
                             {"sim": sim, "pre_chain": pre_chain, "pre": pre, "pre_lufs": pre_lufs})
    sim, pre_chain, pre_lufs = s08["state"]["sim"], s08["state"]["pre_chain"], s08["state"]["pre_lufs"]
    tried += s08["tried"]
    style = sim.get("style") or {}

    lim = sim["limiter"]
    final_target = sim["target"]
    ceiling = sim["ceiling"]
    chain = list(pre_chain)
    chain += drive_tail(sim["gain_db"], ceiling, style,
                        reasons=("R-18" + (",S-08" if final_target < r14_target else ""),
                                 "R-14,S-01" + (",S-08" if style else "")))

    loud_rat = {"stage": "loudness",
                "measured": {"input_lufs_i": round(in_lufs, 2), "pre_limiter_lufs_i": round(pre_lufs, 2),
                             "profile_target_lufs_i": target, "window_lufs_i": window, "tried": tried},
                "rule": "R-18",
                "action": ({"ja": f"正規化される媒体のため目標 {final_target:.1f} LUFS に合わせる（配送条件として扱う）",
                            "en": f"Normalized medium: match {final_target:.1f} LUFS (a delivery gate, not a goal)"}
                           if normalized else
                           {"ja": f"正規化されない媒体のため、レンジ内でリミッター依存度（P-18）とノイズ戻り（S-08）の制約下で到達できる {final_target:.1f} LUFS を取る",
                            "en": f"Non-normalized medium: {final_target:.1f} LUFS, reachable within the window under the P-18 limit and the S-08 guard"}),
                "alternatives": [{"ja": "より大きい目標（リミッター依存度とノイズ戻りが増える）",
                                  "en": "a louder target (more limiter dependency and noise return)"}],
                "expected": {"lufs_i": round(sim["lufs_i"], 2), "gain_db": sim["gain_db"]}}
    rationale.append(loud_rat)
    release = float(style.get("release_ms") or DEFAULT_RELEASE_MS)
    lim_action = {"ja": f"最終段に True Peak リミッター（天井 {ceiling:.1f} dBTP、リリース {release:.0f} ms）",
                  "en": f"True-peak limiter last (ceiling {ceiling:.1f} dBTP, release {release:.0f} ms)"}
    if style.get("clipper_headroom_db") is not None:
        lim_action = {"ja": lim_action["ja"] + f"。その手前にソフトクリッパー（リミッター天井の {style['clipper_headroom_db']:.1f} dB 上）を置き、ピークの一部を受け持たせる（S-08）",
                      "en": lim_action["en"] + f"; a soft clipper {style['clipper_headroom_db']:.1f} dB above the limiter ceiling takes part of the peaks (S-08)"}
    lim_rat = {"stage": "true_peak_limiter", "measured": {"limiter_gr": {k: round(v, 2) for k, v in lim.items()}},
               "rule": "R-14" + (",S-08" if style else ""),
               "action": lim_action,
               "alternatives": [{"ja": "クリッパーの併用（既定では使わない）", "en": "add a clipper (not default)"},
                                {"ja": "リリース時間の変更（ポンピングとノイズの持ち上がりが変わる）",
                                 "en": "a different release time (changes pumping and noise lift)"}],
               "expected": {"true_peak": round(sim["true_peak"], 2), **({"clipper": sim["clipper"]} if sim.get("clipper") else {})}}
    rationale.append(lim_rat)
    rationale.append(s08["rationale"])

    if lim["gr_p95_db"] > warn_p95:
        warnings.append({"code": "limiter_dependency", "rule": "P-18",
                         "message": {"ja": f"リミッターのゲインリダクション（95 パーセンタイル {lim['gr_p95_db']:.1f} dB）が大きい",
                                     "en": f"Limiter gain reduction is high (p95 {lim['gr_p95_db']:.1f} dB)"},
                         "values": lim})
    if not sim.get("reached", True):
        send_back = {"reason": {"ja": f"リミッターの駆動量の上限でも目標 {final_target:.1f} LUFS に届かない（{sim['lufs_i']:.1f} LUFS）。ミックス側の問題として差し戻す",
                                "en": f"Target {final_target:.1f} LUFS is not reachable even at the maximum limiter drive ({sim['lufs_i']:.1f} LUFS). Sent back as a mix-side problem"},
                     "rule": "R-14", "measured": lim}
    if lim["gr_p95_db"] > sb_p95:
        send_back = {"reason": {"ja": f"目標をレンジの下限近くまで下げても、リミッターのゲインリダクションが {lim['gr_p95_db']:.1f} dB（95 パーセンタイル）で、上限 {sb_p95:.1f} dB を超える。ミックス側の問題として差し戻す",
                                "en": f"Even near the bottom of the window, limiter GR is {lim['gr_p95_db']:.1f} dB (p95), above the {sb_p95:.1f} dB limit. Sent back as a mix-side problem"},
                     "rule": "R-14", "measured": lim}
    if target is not None and r14_target < target:
        warnings.append({"code": "target_lowered", "rule": "R-14",
                         "message": {"ja": f"リミッター依存度のため目標を {target:.1f} から {r14_target:.1f} LUFS に下げた",
                                     "en": f"Target lowered from {target:.1f} to {r14_target:.1f} LUFS because of limiter dependency"}})
    if final_target < r14_target:
        warnings.append({"code": "target_lowered_s08", "rule": "S-08",
                         "message": {"ja": f"ノイズ戻り監視（S-08）のため目標を {r14_target:.1f} から {final_target:.1f} LUFS に下げた",
                                     "en": f"Target lowered from {r14_target:.1f} to {final_target:.1f} LUFS for the noise-return guard (S-08)"}})
    if style:
        warnings.append({"code": "limiter_style_s08", "rule": "S-08",
                         "message": {"ja": "ノイズ戻り監視（S-08）のため、目標を保ったままリミッターの駆動のしかた（リリース時間／クリッパーの分担）を変えた。低域の歪みとアタックを耳で確認する",
                                     "en": "For the noise-return guard (S-08) the target was kept and the way the limiter is driven (release / clipper share) was changed; check low-end distortion and attacks by ear"},
                         "values": style})
    if s08["send_back"] is not None:
        if send_back is None:
            send_back = s08["send_back"]
        else:
            send_back = dict(send_back)
            send_back["also"] = list(send_back.get("also") or []) + [s08["send_back"]]
    if send_back is not None:
        send_back["rules"] = [send_back["rule"]] + [a.get("rule") for a in send_back.get("also") or []]

    obj_ids = objective_ids(obj)
    proposal = {
        "stage": "master",
        "variant": vid,
        "profile": pid,
        "delivery": delivery["id"],
        "objective": obj,
        "route": route,
        "chain": chain,
        "rationale": rationale,
        "expected": {"lufs_i": round(sim["lufs_i"], 2), "true_peak": round(sim["true_peak"], 2),
                     "target_lufs_i": final_target, "ceiling_dbtp": ceiling,
                     "codec_after_ceiling_dbtp": codec_after_ceiling(profile, th),
                     "limiter_gr": {k: round(v, 2) for k, v in lim.items()},
                     "s08": s08["expected"]},
        "input": {"lufs_i": round(in_lufs, 2), "true_peak": ma.finite_or_none(in_sum["true_peak_dbtp"]),
                  "frames": int(x.shape[0]), "sample_rate": int(sr)},
        "warnings": warnings,
        "send_back": send_back,
        "definitions": definition_hashes(profile, delivery, obj_ids),
    }
    proposal["proposal_id"] = "mpl_" + canonical_hash({k: proposal[k] for k in ("variant", "profile", "delivery", "chain")})[:12]
    return proposal


# --------------------------------------------------------------------------
# apply


def find_variant(data: dict, variant_id: str) -> dict | None:
    for v in data.get("variants", []) or []:
        if v.get("id") == variant_id:
            return v
    return None


_TERM_KEYS = ("objective", "metric", "variant", "key", "sense", "weight", "effective_weight", "value", "target",
              "target_source", "penalty", "contribution", "status", "reason", "unit")
_GATE_CHECK_KEYS = ("id", "status", "required", "reason", "values")


def stored_evaluation(proposal: dict, chain: list[dict]) -> dict | None:
    """Compact copy of a proposal's objective evaluation for ``variants[].evaluation``.

    Keeps the score, the per-metric breakdown, constraints and the gate; ``chain_hash``
    ties it to the chain it was computed for (the Mix Report ignores a stale one).
    """
    ev = proposal.get("objective_evaluation")
    if not isinstance(ev, dict):
        return None
    gate = ev.get("gate") if isinstance(ev.get("gate"), dict) else None
    if gate is not None:
        gate = {**{k: gate.get(k) for k in ("status", "pass", "profile", "playback_assumptions", "lead", "notes",
                                            "corrective_suggestions") if k in gate},
                "checks": [{k: c.get(k) for k in _GATE_CHECK_KEYS if k in c} for c in gate.get("checks") or []]}
    resolved = proposal.get("objective_resolved") or {}
    return copy.deepcopy({
        "proposal_id": proposal.get("proposal_id"),
        "chain_hash": canonical_hash(chain),
        "scope": ev.get("scope"),
        "score": ev.get("score"),
        "terms": [{k: t.get(k) for k in _TERM_KEYS if k in t} for t in ev.get("terms") or []],
        "constraints": ev.get("constraints") or {},
        "gate": gate,
        "redistribution": ev.get("redistribution") or [],
        "objective": {k: resolved.get(k) for k in ("blend", "intensity", "lead", "genre", "reference", "notes")
                      if k in resolved},
        "level_matched": True,
        "rule": "R-01",
    })


def apply_master_plan(project, proposal: dict, *, actor: str = "planner") -> None:
    """Write the proposal's chain into its variant and save (op master_apply)."""
    if proposal.get("stage") != "master":
        raise InputError("not a master-stage proposal")
    chain = copy.deepcopy(proposal["chain"])
    validate_master_chain(chain)
    data = project.data
    vid = proposal["variant"]
    variant = find_variant(data, vid)
    if variant is None:
        variant = {"id": vid, "objective": None, "master": {}, "outputs": []}
        data.setdefault("variants", []).append(variant)
    route = proposal.get("route") or {}
    rname = route.get("route", "full_mix")
    exp = proposal.get("expected") or {}
    variant["master"] = {
        "route": SCHEMA_ROUTE.get(rname, "fullmix"),
        "route_detail": rname,
        "chain": chain,
        "profile": proposal.get("profile"),
        "proposal_id": proposal.get("proposal_id"),
        "plan": {
            "rationale": proposal.get("rationale", []),
            "expected": exp,
            "warnings": proposal.get("warnings", []),
            "send_back": proposal.get("send_back"),
            "route_reason": route.get("reason"),
            "input": proposal.get("input"),
            "definitions": proposal.get("definitions"),
        },
    }
    # objective evaluation and decisions travel with the chain they describe (Mix Report 4-6);
    # a proposal without them (plain plan_master) drops stale ones from an earlier proposal
    ev = stored_evaluation(proposal, chain)
    if ev is not None:
        variant["evaluation"] = ev
    else:
        variant.pop("evaluation", None)
    if isinstance(proposal.get("decisions"), dict):
        variant["decisions"] = copy.deepcopy(proposal["decisions"])
    else:
        variant.pop("decisions", None)
    obj = proposal.get("objective")
    if obj is not None and obj != data.get("objective"):
        variant["objective"] = obj
    out = {"profile": proposal["profile"], "delivery": proposal["delivery"]}
    outputs = variant.setdefault("outputs", [])
    existing = next((o for o in outputs if o.get("profile") == out["profile"] and o.get("delivery") == out["delivery"]), None)
    if existing is None:
        existing = dict(out)
        outputs.append(existing)
    existing["target_lufs_i"] = exp.get("target_lufs_i")
    reason = (f"master plan {proposal.get('proposal_id')} for {proposal['profile']}"
              + (f"; send back ({proposal['send_back']['rule']})" if proposal.get("send_back") else ""))
    project.save(actor=actor, op="master_apply", reason=reason)
