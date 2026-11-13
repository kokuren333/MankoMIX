"""Mastering planner (SPEC 6.6, R-14, R-15, R-18, R-30, R-31).

``plan_master`` measures the master input, builds a chain in the fixed order
of S-06 / SPEC 6.6.2 and returns a *proposal* (R-31): processors with their
reasons, the rationale for every stage (measured -> rule -> action ->
alternatives -> expected), the expected result, warnings and an optional
send-back to the mix stage. Nothing is written until ``apply_master_plan``.

The limiter is a ceiling, not a loudness device (R-14): the chain is
simulated on the actual input and the limiter's gain-reduction statistics
(P-18) decide whether the target is reachable.
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


def limiter_proc(ceiling_dbtp: float, reason: str) -> dict:
    return _proc("mst_limiter", "limiter", {"ceiling_dbtp": round(float(ceiling_dbtp), 3),
                                            "lookahead_ms": 3.0, "release_ms": 100.0, "oversample": 4},
                 reason)


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


def _converge(pre: np.ndarray, sr: int, target: float, ceiling: float, pre_lufs: float,
              tol: float = 0.05, max_iter: int = 6, warm: dict | None = None) -> dict:
    """Find the limiter drive that lands the limited output on target (secant search).

    Limiting compresses the gain -> loudness slope, so a plain step undershoots;
    the secant uses the measured slope. Returns the closest simulation.
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
        res = _render(pre, sr, [gain_proc(gain, "R-18"), limiter_proc(ceiling, "R-14")])
        out_l = float(ld.integrated(res.audio, sr))
        sim = {"gain_db": round(gain, 3), "lufs_i": out_l, "true_peak": _limiter_out_tp(res, sr),
               "limiter": limiter_stats(res), "target": target, "ceiling": ceiling, "reached": True}
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
    x, sr = load_master_input(project, route["route"])
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

    lim = sim["limiter"]
    final_target = sim["target"]
    ceiling = sim["ceiling"]
    chain = list(pre_chain)
    chain.append(gain_proc(sim["gain_db"], "R-18"))
    chain.append(limiter_proc(ceiling, "R-14,S-01"))

    loud_rat = {"stage": "loudness",
                "measured": {"input_lufs_i": round(in_lufs, 2), "pre_limiter_lufs_i": round(pre_lufs, 2),
                             "profile_target_lufs_i": target, "window_lufs_i": window, "tried": tried},
                "rule": "R-18",
                "action": ({"ja": f"正規化される媒体のため目標 {final_target:.1f} LUFS に合わせる（配送条件として扱う）",
                            "en": f"Normalized medium: match {final_target:.1f} LUFS (a delivery gate, not a goal)"}
                           if normalized else
                           {"ja": f"正規化されない媒体のため、レンジ内でリミッター依存度の制約下で到達できる {final_target:.1f} LUFS を取る",
                            "en": f"Non-normalized medium: {final_target:.1f} LUFS, reachable within the window under the P-18 limit"}),
                "alternatives": [{"ja": "より大きい目標（リミッター依存度が上がる）", "en": "a louder target (more limiter dependency)"}],
                "expected": {"lufs_i": round(sim["lufs_i"], 2), "gain_db": sim["gain_db"]}}
    rationale.append(loud_rat)
    lim_rat = {"stage": "true_peak_limiter", "measured": {"limiter_gr": {k: round(v, 2) for k, v in lim.items()}},
               "rule": "R-14",
               "action": {"ja": f"最終段に True Peak リミッター（天井 {ceiling:.1f} dBTP）",
                          "en": f"True-peak limiter last (ceiling {ceiling:.1f} dBTP)"},
               "alternatives": [{"ja": "クリッパーの併用（既定では使わない）", "en": "add a clipper (not default)"}],
               "expected": {"true_peak": round(sim["true_peak"], 2)}}
    rationale.append(lim_rat)

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
    if target is not None and final_target < target:
        warnings.append({"code": "target_lowered", "rule": "R-14",
                         "message": {"ja": f"リミッター依存度のため目標を {target:.1f} から {final_target:.1f} LUFS に下げた",
                                     "en": f"Target lowered from {target:.1f} to {final_target:.1f} LUFS because of limiter dependency"}})

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
                     "limiter_gr": {k: round(v, 2) for k, v in lim.items()}},
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
