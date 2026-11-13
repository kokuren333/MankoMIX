"""Cleanup stage orchestration (SPEC 6.4): plan (R-31 proposal) and run.

``plan_cleanup`` diagnoses the input and proposes run / light / skip per step
with parameters, reasons and alternatives. ``run_cleanup`` applies a plan:

1. click repair (time domain, local),
2. detection-based spectral reduction with the protection caps,
3. optional deterministic HF completion,
4. low-band splice: the removed component is high-passed at the crossover
   (gain exactly 0 at and below it), so the output equals the input there
   (S-07, verified by a null test),
5. verification: delta (input - output), removed energy per band, P-16
   before/after, P-21 side effects, S-07 residual, over-suppression check
   (correlation of the removed 5-8 kHz envelope with the input's sibilant
   envelope; if suspicious the strength is reduced and the run repeated
   once automatically), and the S-08 noise baseline.

Works on any mono or multichannel [frames, channels] array; stem-wise use is
the caller's job. Deterministic: same input and plan give bit-identical
output.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field

import numpy as np

from ..errors import InputError
from . import clicks as _clicks
from . import complete as _complete
from . import spectral as _spectral
from ._util import (EPS, as_2d, band_energies, crossover_highpass, dct_lowpass, db10, db20,
                    load_policy, mid_side, restore_shape, rnd, stft, stft_freqs,
                    stft_params, v)
from .diagnose import decide, noise_shimmer_metrics
from .guard import noise_baseline, side_effects
from .protect import Protector, detect_events

STEPS = ("click_repair", "spectral_reduction", "protection", "completion")
ACTIONS = ("run", "light", "skip")
PLAN_VERSION = 1


@dataclass
class CleanupResult:
    audio: np.ndarray
    delta: np.ndarray
    report: dict = field(default_factory=dict)


def _fingerprint(x2d: np.ndarray) -> dict:
    h = hashlib.sha256(np.ascontiguousarray(x2d, dtype=np.float64).tobytes()).hexdigest()
    return {"frames": int(x2d.shape[0]), "channels": int(x2d.shape[1]), "sha256": h}


def _alternatives(step: str, action: str) -> list[dict]:
    effects = {
        "click_repair": {"run": "repair every detected click", "light": "repair head clicks only",
                         "skip": "leave clicks in place"},
        "spectral_reduction": {"run": "full strength, all passes", "light": "half strength, fewer passes",
                               "skip": "no spectral reduction (shimmer stays)"},
        "protection": {"run": "cap reduction on sibilant/breath/cymbal events",
                       "light": "same as run", "skip": "no protection caps (risk of dull consonants)"},
        "completion": {"run": "deterministic DSP HF completion above the ceiling",
                       "light": "same as run", "skip": "leave the HF ceiling as is"},
    }[step]
    return [{"action": a, "effect": effects[a]} for a in ACTIONS if a != action
            and not (step in ("protection", "completion") and a == "light")]


def _step_params(step: str, action: str, policy: dict, metrics: dict) -> dict:
    if step == "click_repair":
        return {"head_only": action == "light", "head_s": float(v(policy["clicks"]["head_s"]))}
    if step == "spectral_reduction":
        key = "light" if action == "light" else "run"
        return {"strength": float(v(policy["strength"][key])), "passes": int(v(policy["passes"][key])),
                "ceiling_hz": metrics.get("hf_ceiling_hz"),
                "crossover_hz": float(v(policy["crossover"]["frequency_hz"]))}
    if step == "protection":
        return {"sibilant_cap_db": float(v(policy["protection"]["sibilant"]["cap_db"])),
                "noise_event_cap_db": float(v(policy["protection"]["noise_event"]["cap_db"]))}
    return {"method": str(v(policy["completion"]["method"])), "ceiling_hz": metrics.get("hf_ceiling_hz"),
            "enabled": False, "model": None}


def plan_cleanup(x, sr: float, *, overrides: dict | None = None) -> dict:
    """Diagnose and propose a cleanup plan (R-31 proposal).

    ``overrides``: {"policy": {...deep-merged into the policy...},
    "<step>": "run"|"light"|"skip" or {"action": ..., <param>: ...}}.
    """
    x2d, _ = as_2d(x)
    overrides = copy.deepcopy(overrides or {})
    policy = load_policy(overrides.pop("policy", None))
    metrics = noise_shimmer_metrics(x2d, sr, policy=policy)
    actions, reasons = decide(metrics, policy)
    steps: dict = {}
    for step in STEPS:
        action = actions[step]
        steps[step] = {"action": action, "proposed": action, "params": _step_params(step, action, policy, metrics),
                       "reasons": list(reasons[step]), "overridden": False}
    for step, ov in overrides.items():
        if step not in STEPS:
            raise InputError(f"unknown cleanup step '{step}'", details={"valid": list(STEPS)})
        ov = {"action": ov} if isinstance(ov, str) else dict(ov)
        act = ov.pop("action", steps[step]["action"])
        if act not in ACTIONS:
            raise InputError(f"invalid action '{act}' for {step}", details={"valid": list(ACTIONS)})
        if act != steps[step]["action"]:
            steps[step]["params"] = _step_params(step, act, policy, metrics)
        steps[step]["action"] = act
        steps[step]["params"].update(ov)
        steps[step]["overridden"] = True
        steps[step]["reasons"].append(f"overridden to '{act}' by the caller")
    if steps["completion"]["action"] != "skip" and metrics.get("hf_ceiling_hz") is None:
        steps["completion"]["reasons"].append("no HF ceiling detected: completion has nothing to do")
    for step in STEPS:
        steps[step]["alternatives"] = _alternatives(step, steps[step]["action"])
    skip_all = all(s["action"] == "skip" for s in steps.values())
    overall = (["nothing detected: the whole cleanup stage is skipped (SPEC 6.4.2 step 1)"]
               if skip_all and not any(s["overridden"] for s in steps.values()) else [])
    return {"kind": "cleanup_plan", "version": PLAN_VERSION, "sr": int(sr),
            "input": _fingerprint(x2d), "diagnosis": {"metrics": metrics},
            "steps": steps, "skip_all": skip_all, "reasons": overall, "policy": policy,
            "ops": ["approve", "reject"]}


# --- execution ------------------------------------------------------------------

def _process(x2d: np.ndarray, sr: float, plan: dict, policy: dict, strength_scale: float,
             record: dict) -> np.ndarray:
    steps = plan["steps"]
    metrics = plan["diagnosis"]["metrics"]
    y = x2d
    # 1. clicks
    st = steps["click_repair"]
    if st["action"] != "skip":
        found = _clicks.detect_clicks(x2d, sr, policy=policy)
        if st["params"].get("head_only"):
            head = float(st["params"].get("head_s", v(policy["clicks"]["head_s"])))
            found = [c for c in found if c["peak"] < head * sr]
        y = _clicks.repair_clicks(x2d, sr, found, policy=policy) if found else x2d
        record["click_repair"] = {"action": st["action"], "repaired": found, "count": len(found)}
    else:
        record["click_repair"] = {"action": "skip"}
    # 2./3. spectral reduction with protection
    st = steps["spectral_reduction"]
    if st["action"] != "skip":
        p = st["params"]
        prot = Protector(policy) if steps["protection"]["action"] != "skip" else None
        strength = float(p.get("strength", 1.0)) * strength_scale
        removed, info = _spectral.reduce(y, sr, policy, strength=strength,
                                         passes=int(p.get("passes", 3)),
                                         ceiling_hz=p.get("ceiling_hz", metrics.get("hf_ceiling_hz")),
                                         caps_fn=prot)
        y = y - removed
        record["spectral_reduction"] = {"action": st["action"], **info}
        record["protection"] = ({"action": steps["protection"]["action"], **prot.info}
                                if prot is not None else {"action": "skip"})
    else:
        record["spectral_reduction"] = {"action": "skip"}
        record["protection"] = {"action": "skip"}
    # 4. completion
    st = steps["completion"]
    fc = st["params"].get("ceiling_hz") or metrics.get("hf_ceiling_hz")
    if st["action"] != "skip":
        method = st["params"].get("method", _complete.METHOD_DSP)
        if method == _complete.METHOD_NEURAL:
            _complete.neural_completion(y, sr, enabled=bool(st["params"].get("enabled")),
                                        model=st["params"].get("model"))
        if fc is None:
            record["completion"] = {"action": st["action"], "skipped": "no HF ceiling"}
        else:
            added, crec = _complete.complete_hf(y, sr, float(fc), policy)
            y = y + added
            record["completion"] = {"action": st["action"], **crec}
    else:
        record["completion"] = {"action": "skip"}
    # 5. low-band splice (S-07): the removed component never reaches below the crossover
    raw = x2d - y
    xover = float(v(policy["crossover"]["frequency_hz"]))
    trans = float(v(policy["crossover"]["transition_hz"]))
    removed = crossover_highpass(raw, sr, xover, trans) if np.any(raw) else raw
    return x2d - removed


def null_test_residual_dbfs(x, y, sr: float, crossover_hz: float = 1000.0, *,
                            method: str = "dct") -> float:
    """S-07 null test: peak of (y - x) after a brick-wall low-pass at the
    crossover, in dBFS (floor -300).

    ``method="dct"`` (default) low-passes in the DCT-II domain (even-symmetric
    extension, so a change at the very first sample does not leak into the
    low band through the file edge); ``"fir"`` uses a linear-phase Kaiser FIR
    low-pass (passband to 0.9 x crossover, -120 dB at the crossover) as an
    independent cross-check of the interior."""
    a, _ = as_2d(x)
    b, _ = as_2d(y)
    diff = b - a
    if not np.any(diff):
        return -300.0
    if method == "fir":
        from scipy.signal import firwin, kaiserord, oaconvolve
        ntaps, beta = kaiserord(120.0, 0.1 * crossover_hz / (sr / 2.0))
        taps = firwin(ntaps | 1, 0.95 * crossover_hz, window=("kaiser", beta), fs=sr)
        lp = np.stack([oaconvolve(diff[:, c], taps, mode="same") for c in range(diff.shape[1])], axis=1)
    else:
        lp = dct_lowpass(diff, sr, crossover_hz)
    return db20(float(np.max(np.abs(lp))))


def _oversuppression(x2d: np.ndarray, delta2d: np.ndarray, sr: float, policy: dict) -> dict:
    op = policy["oversuppression"]
    n_fft, hop = stft_params(sr, policy)
    freqs = stft_freqs(sr, n_fft)
    mid, _ = mid_side(x2d)
    dmid, _ = mid_side(delta2d)
    sx = stft(mid, n_fft, hop)
    px = (sx.real ** 2 + sx.imag ** 2).astype(np.float32)
    del sx
    sd = stft(dmid, n_fft, hop)
    pd = (sd.real ** 2 + sd.imag ** 2).astype(np.float32)
    del sd
    lo, hi = v(policy["protection"]["sibilant"]["band_hz"])
    sel = (freqs >= lo) & (freqs < hi)
    ex = px[:, sel].sum(axis=1).astype(np.float64)
    ed = pd[:, sel].sum(axis=1).astype(np.float64)
    ev = detect_events(px, freqs, sr / hop, policy)
    sib = ev["sibilant"] | ev["noise_event"]
    frames = sib if np.any(sib) else ex > 0
    removed_db = db10(float(np.sum(ed[frames])) / (float(np.sum(ex[frames])) + EPS)) if np.any(frames) else -300.0
    corr = None
    if np.std(ex) > 0 and np.std(ed) > 0:
        corr = float(np.corrcoef(ex, ed)[0, 1])
    flagged = (corr is not None and corr >= float(v(op["corr_threshold"]))
               and removed_db >= float(v(op["min_removed_db"])))
    return {"corr_5_8k": rnd(corr, 4), "removed_5_8k_on_events_db": rnd(removed_db),
            "event_seconds": rnd(float(np.sum(sib)) * hop / sr),
            "corr_threshold": float(v(op["corr_threshold"])),
            "min_removed_db": float(v(op["min_removed_db"])), "flagged": bool(flagged)}


def _removed_by_band(x2d: np.ndarray, delta2d: np.ndarray, sr: float, policy: dict,
                     ceiling_hz: float | None) -> dict:
    xover = float(v(policy["crossover"]["frequency_hz"]))
    nyq = sr / 2.0 + 1.0
    bands = [("low", 0.0, xover), ("presence", xover, 5000.0), ("sibilance", 5000.0, 8000.0),
             ("upper_presence", 8000.0, 10000.0), ("shimmer", 10000.0, 14000.0)]
    if ceiling_hz is not None and ceiling_hz > 14000.0:
        bands += [("air", 14000.0, ceiling_hz), ("above_ceiling", ceiling_hz, nyq)]
    else:
        bands += [("air", 14000.0, nyq)]
    bands = [b for b in bands if b[1] < sr / 2.0]
    ei = band_energies(x2d, sr, bands)
    ed = band_energies(delta2d, sr, bands)
    n = max(1, x2d.shape[0] * x2d.shape[1])
    out = {}
    for name, lo, hi in bands:
        out[name] = {"range_hz": [lo, min(hi, sr / 2.0)],
                     "removed_rel_db": rnd(db10(ed[name] / ei[name]) if ei[name] > 0 and ed[name] > 0 else None),
                     "removed_dbfs": rnd(db10(ed[name] / n) if ed[name] > 0 else None)}
    return out


def run_cleanup(x, sr: float, plan: dict | None = None) -> CleanupResult:
    """Apply a cleanup plan (``plan_cleanup`` output; computed if None)."""
    x2d, was_1d = as_2d(x)
    if plan is None:
        plan = plan_cleanup(x2d, sr)
    if int(plan.get("sr", sr)) != int(sr):
        raise InputError(f"plan was made for {plan.get('sr')} Hz, signal is {sr} Hz")
    policy = plan.get("policy") or load_policy()
    warnings = []
    fp = _fingerprint(x2d)
    if plan.get("input") and plan["input"].get("sha256") != fp["sha256"]:
        warnings.append("plan was made for a different input; diagnosis metrics re-measured")
        plan = copy.deepcopy(plan)
        plan["diagnosis"] = {"metrics": noise_shimmer_metrics(x2d, sr, policy=policy)}
    before = plan["diagnosis"]["metrics"]
    xover = float(v(policy["crossover"]["frequency_hz"]))
    s07_limit = float(v(policy["s07"]["residual_limit_dbfs"]))
    report: dict = {"kind": "cleanup_report", "plan_version": plan.get("version"),
                    "input": fp, "warnings": warnings,
                    "steps_planned": {k: s["action"] for k, s in plan["steps"].items()}}
    if plan.get("skip_all"):
        out = x2d.copy()
        delta = x2d - out
        report.update({
            "skipped": True,
            "reasons": plan.get("reasons") or ["all steps skipped"],
            "steps": {k: {"action": "skip"} for k in STEPS},
            "p16_before": before, "p16_after": before,
            "s07": {"residual_dbfs": -300.0, "limit_dbfs": s07_limit, "crossover_hz": xover, "pass": True},
            "noise_baseline": noise_baseline(out, sr, policy=policy, metrics=before),
        })
        return CleanupResult(restore_shape(out, was_1d), restore_shape(delta, was_1d), report)

    record: dict = {}
    out = _process(x2d, sr, plan, policy, 1.0, record)
    delta = x2d - out
    over = _oversuppression(x2d, delta, sr, policy)
    rerun = None
    if over["flagged"] and plan["steps"]["spectral_reduction"]["action"] != "skip":
        factor = float(v(policy["oversuppression"]["strength_factor"]))
        record2: dict = {}
        out2 = _process(x2d, sr, plan, policy, factor, record2)
        delta2 = x2d - out2
        over2 = _oversuppression(x2d, delta2, sr, policy)
        rerun = {"reason": "removed component correlates with the input's sibilant/breath envelope",
                 "strength_factor": factor, "first_check": over, "second_check": over2}
        out, delta, record, over = out2, delta2, record2, over2
    after = noise_shimmer_metrics(out, sr, policy=policy)
    resid = null_test_residual_dbfs(x2d, out, sr, xover)
    report.update({
        "skipped": False,
        "steps": record,
        "removed_energy": _removed_by_band(x2d, delta, sr, policy, before.get("hf_ceiling_hz")),
        "p16_before": before,
        "p16_after": after,
        "p21": side_effects(x2d, out, sr, policy=policy),
        "s07": {"residual_dbfs": rnd(resid), "limit_dbfs": s07_limit, "crossover_hz": xover,
                "method": "peak of (output - input) after a brick-wall DCT-domain low-pass at the crossover",
                "pass": bool(resid <= s07_limit)},
        "oversuppression": {**over, "rerun": rerun is not None, "rerun_detail": rerun},
        "recheck": {
            "peak_before_dbfs": rnd(db20(float(np.max(np.abs(x2d))))),
            "peak_after_dbfs": rnd(db20(float(np.max(np.abs(out))))),
            "shimmer_index_change_db": (rnd(after["shimmer_index_db"] - before["shimmer_index_db"])
                                        if after.get("shimmer_index_db") is not None
                                        and before.get("shimmer_index_db") is not None else None),
            "hf_ceiling_after_hz": after.get("hf_ceiling_hz"),
        },
        "noise_baseline": noise_baseline(out, sr, policy=policy, metrics=after),
        "neural_completion_used": False,
    })
    return CleanupResult(restore_shape(out, was_1d), restore_shape(delta, was_1d), report)

