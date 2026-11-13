"""Deterministic planner loop (SPEC 7.2, 7.3; R-01, R-06, R-15, R-23, R-29, R-31).

No LLM is involved (R-23): the planner measures, proposes small moves, renders
previews, evaluates them against the resolved objective and keeps the best.

    measure -> candidate chains -> render preview (representative excerpts)
      -> evaluate (level matched, R-01) -> keep the best -> repeat
    stop at the iteration cap or when the improvement falls below a threshold;
    the final chain is rendered full length and evaluated once more.

The starting point is the mastering planner's proposal (core/mastering.py
plan_master). Candidate moves stay at the master stage: corrective EQ in
small steps within the master EQ limit (R-06, R-15), optional enhancement,
stereo width / low-band mono, light single-band compression (R-30). Every
cut direction carries its opposite safety valve (R-29): low-end cuts may not
push the low/rest ratio below a floor; presence cuts may not push the
presence below a floor.

Output is always a proposal (R-31): parameters, rationale with rule ids and
the alternatives considered; ``apply`` writes it through the stage's apply
function. Decisions are recorded per Mix Report element (balance, panning,
frequency, depth, dynamics, interest).
"""

from __future__ import annotations

import copy
import math

import numpy as np

from . import config
from . import objectives as O
from .errors import InputError
from .hashing import canonical_hash

STAGES = ("master", "mix", "clean")


def _json_safe(obj):
    from .measure.vector import json_safe
    return json_safe(obj)


def _pcfg() -> dict:
    return O.metric_table()["planner"]


def _tv(th: dict, *path, default=None):
    return O._tv(th, *path, default=default)


def T(ja: str, en: str) -> dict:
    return {"ja": ja, "en": en}


# --------------------------------------------------------------------------
# excerpts (SPEC 7.2: loudest, quietest, lead-present; full length only for the final)


def _window_levels(x: np.ndarray, sr: int, win: int, hop: int, weight=None) -> np.ndarray:
    from .measure.loudness import k_weight
    y = k_weight(x, sr) if weight is None else weight
    p = np.mean(y * y, axis=1)
    cs = np.concatenate([[0.0], np.cumsum(p)])
    starts = np.arange(0, max(1, x.shape[0] - win + 1), hop)
    e = (cs[np.minimum(starts + win, len(cs) - 1)] - cs[starts]) / win
    return starts, 10.0 * np.log10(e + 1e-20)


def choose_excerpts(x, sr: int, *, lead_signal=None, excerpt_s: float | None = None) -> list[dict]:
    """Representative excerpts: loudest, quietest (not silent) and lead-present windows.

    Returns [{label, start, end}] in samples, sorted by start; a single
    {"label": "full"} entry when the signal is short.
    """
    cfg = _pcfg()
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    n = a.shape[0]
    ex = float(excerpt_s or cfg["excerpt_s"])
    if n / sr < float(cfg["full_length_below_s"]) or n / sr < 3 * ex + 1.0:
        return [{"label": "full", "start": 0, "end": n}]
    win, hop = int(ex * sr), int(0.25 * sr)
    starts, lev = _window_levels(a, sr, win, hop)
    chosen: list[dict] = []

    def free(s):
        return all(s + win <= c["start"] or s >= c["end"] for c in chosen)

    order = np.argsort(-lev, kind="stable")
    for i in order:
        if free(starts[i]):
            chosen.append({"label": "loudest", "start": int(starts[i]), "end": int(starts[i] + win)})
            break
    top = float(lev.max())
    for i in np.argsort(lev, kind="stable"):
        if lev[i] > top - 25.0 and free(starts[i]):
            chosen.append({"label": "quietest", "start": int(starts[i]), "end": int(starts[i] + win)})
            break
    if lead_signal is not None:
        ls = np.asarray(lead_signal, dtype=np.float64)
        ls = ls[:, None] if ls.ndim == 1 else ls
        _, ll = _window_levels(ls[:n], sr, win, hop, weight=ls[:n])
        score = ll
        label = "lead_present"
    else:
        # 2mix proxy: share of the clarity band (300 Hz - 5 kHz) in the window
        from scipy.signal import butter, sosfilt
        sos = butter(2, [300.0, 5000.0], btype="bandpass", fs=sr, output="sos")
        cb = sosfilt(sos, a, axis=0)
        _, lc = _window_levels(a, sr, win, hop, weight=cb)
        score = lc - lev
        label = "lead_present_proxy"
    for i in np.argsort(-score, kind="stable"):
        if free(starts[i]):
            chosen.append({"label": label, "start": int(starts[i]), "end": int(starts[i] + win)})
            break
    return sorted(chosen, key=lambda c: c["start"])


def _fade(seg: np.ndarray, k: int) -> np.ndarray:
    seg = seg.copy()
    k = min(k, seg.shape[0] // 2)
    if k > 0:
        r = np.linspace(0.0, 1.0, k, endpoint=False)[:, None]
        seg[:k] *= r
        seg[-k:] *= r[::-1]
    return seg


def _concat(parts: list[np.ndarray], sr: int, fade: bool) -> np.ndarray:
    if len(parts) == 1:
        return parts[0]
    k = int(_pcfg()["excerpt_fade_s"] * sr)
    return np.vstack([_fade(p, k) if fade else p for p in parts])


# --------------------------------------------------------------------------
# chains


def _eq_specs() -> dict:
    return {b["id"]: b for b in _pcfg()["eq_bands"]}


def _initial_state(base_chain: list[dict], base_rationale: list[dict]) -> dict:
    """Planner state from plan_master's chain: EQ gain per band, enhance, stereo, compressor."""
    band_of = {}
    for r in base_rationale or []:
        if r.get("stage") == "corrective_eq":
            for i, m in enumerate(r.get("moves") or []):
                band_of[f"mst_eq{i + 1}"] = m.get("band")
    eq = {}
    for p in base_chain:
        if p.get("type") == "eq" and band_of.get(p["id"]):
            eq[band_of[p["id"]]] = float(p["params"]["gain_db"])
    return {"eq": eq, "enhance": None, "width": None, "mono_below_hz": None, "compressor": None}


def build_chain(base_chain: list[dict], state: dict, base_rationale: list[dict]) -> list[dict]:
    """Master chain in the fixed order (S-06) from plan_master's chain plus the planner state."""
    from .mastering import compressor_proc, eq_proc
    band_of = {}
    for r in base_rationale or []:
        if r.get("stage") == "corrective_eq":
            for i, m in enumerate(r.get("moves") or []):
                band_of[f"mst_eq{i + 1}"] = m.get("band")
    specs = _eq_specs()
    eqs, dyn, enh, st, tail = [], [], [], [], []
    seen_bands = set()
    for p in base_chain:
        p = copy.deepcopy(p)
        t = p.get("type")
        if t in ("eq", "filter"):
            b = band_of.get(p["id"])
            if b in state["eq"]:
                seen_bands.add(b)
                p["params"]["gain_db"] = round(state["eq"][b], 2)
                if abs(state["eq"][b]) < 1e-9:
                    continue
            eqs.append(p)
        elif t in ("compressor", "dynamic_eq", "deesser"):
            dyn.append(p)
        elif t == "saturator":
            enh.append(p)
        elif t == "stereo":
            st.append(p)
        else:
            tail.append(p)
    for b in sorted(state["eq"], key=lambda k: list(specs).index(k) if k in specs else 99):
        g = state["eq"][b]
        if b in seen_bands or abs(g) < 1e-9 or b not in specs:
            continue
        s = specs[b]
        eqs.append(eq_proc(f"pln_eq_{b}", s["shape"], s["freq_hz"], g, s["bw_oct"], "R-06,R-01,planner"))
    if state.get("compressor") and not dyn:
        c = state["compressor"]
        dyn.append(compressor_proc(c["threshold_db"], c["ratio"], "R-30,planner"))
    if state.get("enhance") and not enh:
        e = state["enhance"]
        enh.append({"id": "pln_enhance", "type": "saturator",
                    "params": {"drive_db": e["drive_db"], "mode": "tanh", "mix": e["mix"], "oversample": 4},
                    "reason": "P-08,R-16,planner"})
    if state.get("width") is not None or state.get("mono_below_hz") is not None:
        if st:
            p = st[0]
        else:
            p = {"id": "pln_stereo", "type": "stereo", "params": {}, "reason": "R-09,R-10,planner"}
            st = [p]
        if state.get("width") is not None:
            p["params"]["width"] = round(float(state["width"]), 3)
        if state.get("mono_below_hz") is not None:
            p["params"]["mono_below_hz"] = float(state["mono_below_hz"])
    return eqs + dyn + enh + st + tail


_TAIL_TYPES = ("loudness_gain", "clipper", "limiter")


def _split_tail(chain: list[dict]) -> tuple[list[dict], list[dict]]:
    """(pre-limiter processing, [loudness_gain, (clipper), limiter]). A clipper belongs to the
    limiter drive (slot 5, after the drive gain)."""
    pre = [p for p in chain if p.get("type") not in _TAIL_TYPES]
    tail = [p for p in chain if p.get("type") in _TAIL_TYPES]
    return pre, tail


def _render(x: np.ndarray, sr: int, chain: list[dict]):
    from mankomix.dsp import engine
    from .mastering import engine_chain
    return engine.render_chain(x, sr, engine_chain(chain), stage="master", seed=0)


# --------------------------------------------------------------------------
# evaluation of one chain on the preview


class _Evaluator:
    def __init__(self, resolved, profile, ceiling, parts, sr, before, before_p20, sections, stems_parts):
        self.resolved = resolved
        self.profile = profile
        self.ceiling = ceiling
        self.parts = parts
        self.sr = sr
        self.before = before
        self.before_p20 = before_p20
        self.sections = sections
        self.stems_parts = stems_parts
        self.cache: dict = {}
        self.base_pre_lufs = None
        self.renders = 0
        self._s08_ref = None

    def s08(self, y) -> dict | None:
        """S-08 on the preview: the output is measured on the frames of the unprocessed preview
        (time aligned), gain compensated by the integrated loudness difference (as verify does)."""
        from .cleanup import noise_return_check, reference_selection
        from .mastering import s08_planning_config, s08_reduce
        try:
            if self._s08_ref is None:
                self._s08_ref = reference_selection(self.before, self.sr)
            ref = self._s08_ref
            r = noise_return_check(ref["metrics"], y, self.sr, reference=ref)
            return s08_reduce(r, s08_planning_config()["margin_db"])
        except Exception as exc:  # informative for the loop; verify is the final judge
            return {"status": "not_run", "reason": str(exc)}

    def _pre_lufs(self, chain):
        from .measure.loudness import integrated
        pre, _ = _split_tail(chain)
        ys = [_render(p, self.sr, pre).audio if pre else p for p in self.parts]
        y = _concat(ys, self.sr, fade=False)
        return float(integrated(y, self.sr)), ys

    def render(self, chain):
        """Render chain on every excerpt with loudness compensation (constant limiter drive)."""
        from .mastering import limiter_stats
        pre, tail = _split_tail(chain)
        lufs, ys = self._pre_lufs(chain)
        if self.base_pre_lufs is None:
            self.base_pre_lufs = lufs
        comp = (self.base_pre_lufs - lufs) if (math.isfinite(lufs) and math.isfinite(self.base_pre_lufs)) else 0.0
        tail = copy.deepcopy(tail)
        for p in tail:
            if p.get("type") == "loudness_gain":
                p["params"]["gain_db"] = round(float(p["params"]["gain_db"]) + comp, 3)
        outs, stats = [], []
        for y in ys:
            res = _render(y, self.sr, tail) if tail else None
            outs.append(res.audio if res is not None else y)
            if res is not None:
                stats.append(limiter_stats(res))
        self.renders += 1
        lim = None
        if stats:
            lim = {k: float(max(s[k] for s in stats)) for k in stats[0]}
        final_chain = pre + tail
        return _concat(outs, self.sr, fade=len(outs) > 1), lim, final_chain, comp

    def evaluate(self, chain, *, gate: bool = False) -> dict:
        key = canonical_hash(chain)
        hit = self.cache.get(key)
        if hit is not None and (not gate or hit.get("gate_done")):
            return hit
        y, lim, final_chain, comp = self.render(chain)
        stems = None
        meas = O.measure_for_objective(
            y, self.sr, self.resolved, before=self.before, before_p20=self.before_p20, sections=self.sections,
            stems=stems, profile=self.profile, ceiling_dbtp=self.ceiling, limiter=lim, chain=final_chain,
            gate=gate, extra_metrics={"P-11"})
        ev = O.evaluate(meas, self.resolved)
        vec = meas["vector"]
        out = {"chain": final_chain, "evaluation": ev, "limiter": lim, "loudness_compensation_db": comp,
               "low_ratio_db": O.band_ratio_db(vec, 20.0, 250.0),
               "presence_db": ((meas.get("perceptual") or {}).get("P-11") or {}).get("ltas_prominence_db"),
               "lufs_i": (vec.get("P-03") or {}).get("integrated_lufs"),
               "true_peak": (vec.get("P-14") or {}).get("true_peak_dbtp"),
               "s08": self.s08(y),
               "gate_done": gate}
        self.cache[key] = out
        return out


# --------------------------------------------------------------------------
# candidate moves


def _band_for_freq(f: float) -> str:
    specs = _pcfg()["eq_bands"]
    return min(specs, key=lambda s: abs(math.log2(max(f, 1.0) / s["freq_hz"])))["id"]


def _moves(state: dict, ev: dict, resolved: dict, base_ok: dict) -> tuple[list[dict], list[dict]]:
    """Candidate single moves from the current evaluation. Returns (moves, blocked)."""
    cfg = _pcfg()
    th = config.load_knowledge("thresholds")
    max_g = float(_tv(th, "master_eq", "max_abs_gain_db", default=2.0))
    step = float(cfg["eq_step_db"])
    terms = {t["key"]: t for t in ev["terms"] if t["status"] == "measured"}
    wants: list[tuple[float, dict]] = []

    def eq(band, direction, why, rule, priority):
        wants.append((priority, {"kind": "eq", "band": band, "delta_db": direction * step,
                                 "why": why, "rule": rule}))

    for t in ev["terms"]:
        if t["status"] != "measured" or not t.get("penalty"):
            continue
        prio = float(t.get("contribution") or 0.0)
        m, v = t["metric"], t.get("variant")
        if m == "P-01":
            bands_done: set = set()
            for d in t.get("largest_deviations") or []:
                band = _band_for_freq(d["center_hz"])
                if band in bands_done or len(bands_done) >= 3:
                    continue
                bands_done.add(band)
                eq(band, -1.0 if d["deviation_db"] > 0 else 1.0,
                   f"P-01: {d['center_hz']:.0f} Hz deviates {d['deviation_db']:+.1f} dB from the target", "R-06",
                   prio * (1.0 + d.get("importance", 1.0)))
        elif m == "P-11" and v == "two_sided":
            tgt = t.get("target") or [None, None]
            val = t.get("value")
            if val is not None and tgt[0] is not None and val < tgt[0]:
                eq("high_mid", 1.0, "P-11: presence deficit", "R-06", prio)
            else:
                eq("high_mid", -1.0, "P-11: presence excess", "R-06", prio)
        elif m == "P-11":
            eq("high_mid", -1.0, "P-11: 2-5 kHz prominence (harshness)", "R-05,R-06", prio)
        elif m == "P-17":
            eq("air", -1.0, "P-17: 5-8 kHz sibilance (no de-esser at the master stage yet)", "R-13,R-06", prio)
        elif m == "P-07":
            tgt = t.get("target") or [None, None]
            val = t.get("value")
            up = val is not None and tgt[0] is not None and val < tgt[0]
            for b in (("sub", "bass") if (v in (None, "sub+bass")) else (("sub",) if v == "sub" else ("bass",))):
                eq(b, 1.0 if up else -1.0, f"P-07: low/rest {val:+.1f} dB vs target {tgt}", "R-06,R-07", prio)
        elif m == "P-08" and state.get("enhance") is None:
            wants.append((prio, {"kind": "enhance", "drive_db": 6.0, "mix": 0.25,
                                 "why": "P-08: add upper harmonics so the bass survives small speakers",
                                 "rule": "R-16"}))
        elif m == "P-05":
            w = state.get("width") if state.get("width") is not None else 1.0
            if w - 0.1 >= 0.5:
                wants.append((prio, {"kind": "width", "width": round(w - 0.1, 3),
                                     "why": "P-05: width restraint", "rule": "R-10"}))
        elif m == "P-03" and v in (None, "plr", "lra") and state.get("compressor") is None:
            val = t.get("value")
            plr = val.get("plr_db") if isinstance(val, dict) else (val if v == "plr" else None)
            tgt = t.get("target") or {}
            hi = (tgt.get("plr_db") or [None, None])[1] if isinstance(tgt, dict) else (tgt[1] if tgt else None)
            if plr is not None and hi is not None and plr > hi:
                wants.append((prio, {"kind": "compressor", "ratio": 1.5,
                                     "why": "P-03: PLR above the range (very dynamic for the medium)",
                                     "rule": "R-30"}))
    cons = ev.get("constraints") or {}
    if (cons.get("S-03") == "fail" or cons.get("S-04") == "fail") and state.get("mono_below_hz") is None:
        wants.append((10.0, {"kind": "mono_bass", "why": "S-03/S-04: low-band anti-phase / mono loss",
                             "rule": "R-09"}))

    wants.sort(key=lambda w: -w[0])
    out, blocked, seen = [], [], set()
    for _, mv in wants:
        k = (mv["kind"], mv.get("band"), mv.get("delta_db"))
        if k in seen:
            continue
        seen.add(k)
        if mv["kind"] == "eq":
            g = state["eq"].get(mv["band"], 0.0) + mv["delta_db"]
            if abs(g) > max_g + 1e-9:
                blocked.append({**mv, "rule": "R-15", "reason": f"master EQ limit ({max_g:.1f} dB) reached on '{mv['band']}'"})
                continue
            # a direct reversal of the last kept move is not a new idea
            if base_ok.get("last") == (mv["band"], -mv["delta_db"]):
                continue
        out.append(mv)
        if len(out) >= int(cfg["max_candidates_per_iteration"]):
            break
    return out, blocked


def _apply_move(state: dict, mv: dict, boundary: float) -> dict:
    s = copy.deepcopy(state)
    if mv["kind"] == "eq":
        s["eq"][mv["band"]] = round(s["eq"].get(mv["band"], 0.0) + mv["delta_db"], 3)
    elif mv["kind"] == "enhance":
        s["enhance"] = {"drive_db": mv["drive_db"], "mix": mv["mix"]}
    elif mv["kind"] == "width":
        s["width"] = mv["width"]
    elif mv["kind"] == "compressor":
        s["compressor"] = {"threshold_db": -20.0, "ratio": mv["ratio"]}
    elif mv["kind"] == "mono_bass":
        s["mono_below_hz"] = boundary
    return s


def _s08_worse(cand: dict, cur: dict, slack_db: float = 0.1) -> bool:
    """S-08 (hard constraint) for a candidate move: it may not make the noise-return guard
    fail, nor make an already failing guard worse."""
    a, b = cand.get("s08") or {}, cur.get("s08") or {}
    if a.get("status") != "fail":
        return False
    if b.get("status") != "fail":
        return True
    return (a.get("worst_excess_db") or 0.0) > (b.get("worst_excess_db") or 0.0) + slack_db


def _valve(mv: dict, cand: dict, cur: dict) -> str | None:
    """R-29 safety valves. Returns a reason when the candidate trips one."""
    v = _pcfg()["safety_valves"]
    if mv["kind"] == "eq" and mv["delta_db"] < 0:
        if mv["band"] in ("sub", "bass", "low_mid"):
            lo = float(v["low_end_min_db"])
            c, b = cand.get("low_ratio_db"), cur.get("low_ratio_db")
            if c is not None and c < lo and (b is None or b >= lo or c < b):
                return f"R-29: low/rest would fall to {c:.1f} dB (floor {lo:.1f} dB)"
        if mv["band"] in ("high_mid", "air"):
            lo = float(v["presence_min_db"])
            c, b = cand.get("presence_db"), cur.get("presence_db")
            if c is not None and c < lo and (b is None or b >= lo or c < b):
                return f"R-29: presence would fall to {c:.1f} dB (floor {lo:.1f} dB)"
    return None


def _move_text(mv: dict) -> dict:
    if mv["kind"] == "eq":
        return T(f"{mv['band']} 帯域を {mv['delta_db']:+.1f} dB", f"{mv['band']} band {mv['delta_db']:+.1f} dB")
    if mv["kind"] == "enhance":
        return T("倍音付加（サチュレーター、薄く）", "light harmonic enhancement (saturator)")
    if mv["kind"] == "width":
        return T(f"ステレオ幅を {mv['width']:.2f} に", f"stereo width to {mv['width']:.2f}")
    if mv["kind"] == "compressor":
        return T("軽いシングルバンド・コンプ（1.5:1）", "light single-band compression (1.5:1)")
    if mv["kind"] == "mono_bass":
        return T("低域のモノ化", "mono below the low-band boundary")
    return T(mv["kind"], mv["kind"])


def _iter_record(i: int, cand: dict, move: dict | None, improvement: float | None, extra: dict | None = None) -> dict:
    ev = cand["evaluation"]
    rec = {"i": i, "chain": cand["chain"], "score": ev["score"], "score_by_objective": ev["score_by_objective"],
           "terms": [{k: t.get(k) for k in ("objective", "key", "status", "value", "target", "penalty",
                                            "weight", "effective_weight", "contribution", "reason")}
                     for t in ev["terms"]],
           "constraints": ev["constraints"], "rejected": ev["rejected"],
           "gate": _gate_summary(ev.get("gate")), "move": move, "improvement": improvement,
           "limiter": cand.get("limiter"), "loudness_compensation_db": cand.get("loudness_compensation_db")}
    if extra:
        rec.update(extra)
    return rec


def _gate_summary(g: dict | None) -> dict | None:
    if not g:
        return None
    return {"status": g.get("status"), "pass": g.get("pass"),
            "checks": [{"id": c["id"], "status": c["status"], "reason": c.get("reason")} for c in g.get("checks", [])],
            "corrective_suggestions": g.get("corrective_suggestions", [])}


# --------------------------------------------------------------------------
# decisions (Mix Report, 6 elements)


def _decisions(kept_moves: list[dict], first: dict, final: dict, resolved: dict, stems: bool,
               blocked: list[dict], valves: list[dict]) -> dict:
    out = {k: [] for k in O.ELEMENTS}
    t0 = {t["key"]: t for t in first["evaluation"]["terms"]}
    t1 = {t["key"]: t for t in final["evaluation"]["terms"]}

    def measured(keys):
        return {k: {"before": (t0.get(k) or {}).get("value"), "after": (t1.get(k) or {}).get("value"),
                    "penalty_before": (t0.get(k) or {}).get("penalty"), "penalty_after": (t1.get(k) or {}).get("penalty")}
                for k in keys if k in t0 or k in t1}

    for mv in kept_moves:
        el = {"eq": "frequency", "enhance": "frequency", "width": "panning", "mono_bass": "panning",
              "compressor": "dynamics"}[mv["kind"]]
        out[el].append({"stage": "planner", "measured": mv.get("why"), "rule": mv.get("rule"),
                        "action": _move_text(mv),
                        "alternatives": [T("この手を入れない", "leave as is"),
                                         T("ミックス段で原因を直す（R-15）", "fix the cause at the mix stage (R-15)")],
                        "result": {"score_after": mv.get("score_after"), "improvement": mv.get("improvement")}})
    for b in blocked:
        out["frequency" if b["kind"] == "eq" else "dynamics"].append(
            {"stage": "planner", "measured": b.get("why"), "rule": "R-15", "action": T(
                "マスター EQ の上限に達したため、これ以上動かさない（ミックスの問題として差し戻し候補）",
                "Master EQ limit reached; not moved further (candidate for a mix-stage send-back)"),
             "alternatives": [], "result": None, "status": "blocked"})
    for v in valves:
        out["frequency"].append({"stage": "planner", "measured": v.get("why"), "rule": "R-29",
                                 "action": T("逆向きの安全弁により見送り", "skipped by the opposite safety valve"),
                                 "alternatives": [], "result": v.get("reason"), "status": "valve"})
    if not out["frequency"]:
        out["frequency"].append({"stage": "planner", "measured": measured(["P-01", "P-11", "P-19"]), "rule": "R-06",
                                 "action": T("周波数の追加補正なし", "no further frequency correction"),
                                 "alternatives": [], "result": None})
    else:
        out["frequency"].insert(0, {"stage": "planner", "measured": measured(["P-01", "P-11", "P-17", "P-19", "P-07:sub+bass"]),
                                    "rule": "R-01", "action": T("レベルマッチ後の測定で判断した", "decided on level-matched measurements"),
                                    "alternatives": [], "result": None})
    if not out["panning"]:
        out["panning"].append({"stage": "planner", "measured": {"S-03": final["evaluation"]["constraints"].get("S-03"),
                                                                "S-04": final["evaluation"]["constraints"].get("S-04")},
                               "rule": "R-09", "action": T("定位・幅は変更なし", "no panning / width change"),
                               "alternatives": [], "result": None})
    out["dynamics"].append({"stage": "planner", "measured": measured(["P-03", "P-12", "P-18"]),
                            "rule": "R-14", "action": T("リミッターは天井として扱い、駆動量はレベル補償で一定に保った",
                                                        "the limiter is a ceiling; its drive was kept constant by loudness compensation"),
                            "alternatives": [], "result": final.get("limiter")})
    na = T("ステムがないためマスター段では扱わない（ミックス段、M4）",
           "not handled at the master stage without stems (mix stage, M4)")
    if not stems:
        out["balance"].append({"stage": "planner", "measured": None, "rule": "R-04", "action": na,
                               "alternatives": [], "result": None, "status": "not_evaluated"})
        out["depth"].append({"stage": "planner", "measured": measured(["P-09", "P-15"]), "rule": None, "action": na,
                             "alternatives": [], "result": None, "status": "not_evaluated"})
    else:
        out["balance"].append({"stage": "planner", "measured": measured(["P-02", "P-10", "P-22"]), "rule": "R-28",
                               "action": T("バランスはミックス段で扱う", "balance is handled at the mix stage"),
                               "alternatives": [], "result": None})
        out["depth"].append({"stage": "planner", "measured": measured(["P-09", "P-15"]), "rule": None,
                             "action": T("奥行きはミックス段で扱う", "depth is handled at the mix stage"),
                             "alternatives": [], "result": None})
    out["interest"].append({"stage": "planner", "measured": measured(["P-20"]), "rule": "R-26",
                            "action": T("「仕掛け」は自動化が最も難しい軸で、人間の指示とリファレンスに依存する。プランナーは展開のコントラストを平坦にしないことだけを監視する",
                                        "Interest is the hardest axis to automate and depends on human direction and references; the planner only watches that section contrast is not flattened"),
                            "alternatives": [], "result": None, "status": "depends_on_humans_and_references"})
    return out


# --------------------------------------------------------------------------
# loop


def run_loop(project, *, variant_id: str | None = None, profile_id: str | None = None,
             delivery_id: str | None = None, max_iter: int = 6, min_improvement: float = 0.005,
             objective=None, base_proposal: dict | None = None, final_full_length: bool = True) -> dict:
    """Deterministic planner loop for the master stage (SPEC 7.2).

    Returns {iterations[{i, chain, score, terms, constraints, gate, move, improvement}],
    best{chain, score, evaluation}, final (full-length evaluation), converged,
    reason, unresolved[], decisions{6 elements}, excerpts, base_proposal, resolved}.
    """
    from . import mastering, routes
    if profile_id is None:
        profile_id = "streaming_universal"
    profile = config.get_profile(profile_id)
    max_iter = int(max_iter if max_iter is not None else 6)
    if max_iter < 0:
        raise InputError("max_iter must be >= 0")
    resolved = O.resolve_objective(project, variant=variant_id, spec=objective)
    if objective is None and str(resolved.get("spec_source", "")).startswith("variant:"):
        objective = resolved["spec"]  # the variant's own objective override (9.4)
    base = base_proposal or mastering.plan_master(project, variant_id=variant_id, profile_id=profile_id,
                                                  delivery_id=delivery_id, objective=objective)
    route = (base.get("route") or {}).get("route")
    x, sr = routes.load_master_input(project, route)
    ceiling = float((base.get("expected") or {}).get("ceiling_dbtp", -1.0))
    pa = profile.get("playback_assumptions") or {}
    boundary = float(pa.get("mono_low_band_hz") or 120.0)

    # excerpts (7.2): representative windows, full length only for the final render
    excerpts = choose_excerpts(x, sr)
    parts = [x[e["start"]:e["end"]] for e in excerpts]
    before = _concat(parts, sr, fade=len(parts) > 1)
    sections = None
    if len(excerpts) > 1:
        sections, pos = [], 0
        for e, p in zip(excerpts, parts):
            lab = {"loudest": "loud", "quietest": "quiet"}.get(e["label"], "mid")
            sections.append({"start_s": pos / sr, "end_s": (pos + p.shape[0]) / sr, "label": lab})
            pos += p.shape[0]
    before_p20 = None
    if "P-20" in O.needed_metrics(resolved):
        from .analysis.perceptual import section_contrast
        before_p20 = section_contrast(before, sr, sections)
        sections = before_p20.get("sections")
    evr = _Evaluator(resolved, profile, ceiling, parts, sr, before, before_p20, sections, None)

    state = _initial_state(base["chain"], base.get("rationale"))
    chain0 = build_chain(base["chain"], state, base.get("rationale"))
    cur = evr.evaluate(chain0, gate=True)
    iterations = [_iter_record(0, cur, None, None, {"note": "starting point: mastering.plan_master proposal"})]
    kept_moves: list[dict] = []
    blocked_all: list[dict] = []
    valves_all: list[dict] = []
    rejected_log: list[dict] = []
    converged, reason = False, None
    base_ok = {"last": None}
    first = cur
    if cur["evaluation"]["rejected"]:
        rejected_log.append({"i": 0, "constraints": cur["evaluation"]["constraints"],
                             "note": "the starting chain fails a safety invariant"})

    for i in range(1, max_iter + 1):
        cur_score = cur["evaluation"]["score"]
        if cur_score is None:
            cur_score = math.inf
        moves, blocked = _moves(state, cur["evaluation"], resolved, base_ok)
        for b in blocked:
            if not any(b.get("band") == x_.get("band") and b.get("kind") == x_.get("kind") for x_ in blocked_all):
                blocked_all.append(b)
        if not moves:
            converged, reason = True, "no applicable move left (all proposals blocked or nothing to improve)"
            break
        cands = []
        for mv in moves:
            st = _apply_move(state, mv, boundary)
            chain = build_chain(base["chain"], st, base.get("rationale"))
            c = evr.evaluate(chain)
            ev = c["evaluation"]
            if ev["rejected"]:
                rejected_log.append({"i": i, "move": mv, "constraints": {k: v for k, v in ev["constraints"].items()
                                                                          if v == "fail"}})
                continue
            if _s08_worse(c, cur):
                rejected_log.append({"i": i, "move": mv, "constraints": {"S-08": "fail"},
                                     "s08": {k: (c.get("s08") or {}).get(k)
                                             for k in ("status", "worst_excess_db", "deltas")},
                                     "note": "the move would make the noise-return guard fail or worse (S-08)"})
                continue
            vr = _valve(mv, c, cur)
            if vr:
                valves_all.append({**mv, "reason": vr})
                continue
            cands.append((ev["score"], moves.index(mv), mv, st, c))
        cands.sort(key=lambda r: (r[0], r[1]))
        chosen = None
        for score, _, mv, st, c in cands:
            if cur_score - score < min_improvement:
                break
            cg = evr.evaluate(build_chain(base["chain"], st, base.get("rationale")), gate=True)
            g_new = (cg["evaluation"].get("gate") or {}).get("status")
            g_cur = (cur["evaluation"].get("gate") or {}).get("status")
            if g_new == "fail" and g_cur != "fail":
                rejected_log.append({"i": i, "move": mv, "gate": "fail", "note": "OF-5 gate would fail"})
                continue
            chosen = (score, mv, st, cg)
            break
        if chosen is None:
            converged = True
            best_cand = cands[0][0] if cands else None
            reason = (f"converged: best improvement {cur_score - best_cand:.4f} < {min_improvement}"
                      if best_cand is not None and math.isfinite(cur_score)
                      else "converged: no admissible candidate improved the score")
            break
        score, mv, st, cg = chosen
        improvement = cur_score - score
        mv = {**mv, "score_after": score, "improvement": improvement}
        kept_moves.append(mv)
        state, cur = st, cg
        base_ok["last"] = (mv.get("band"), mv.get("delta_db")) if mv["kind"] == "eq" else None
        iterations.append(_iter_record(i, cur, {k: mv[k] for k in mv if k not in ("score_after",)}, improvement,
                                       {"candidates_evaluated": len(moves)}))
    else:
        reason = f"iteration cap reached ({max_iter})"
        converged = False
    if max_iter == 0:
        reason, converged = "iteration cap is 0: starting point only", False

    best = cur
    # final: full-length render and evaluation (7.2)
    final = None
    if final_full_length:
        if len(excerpts) == 1 and excerpts[0]["label"] == "full":
            final = best
        else:
            fe = _Evaluator(resolved, profile, ceiling, [x], sr, x, None, None, None)
            fe.base_pre_lufs = None
            final = fe.evaluate(best["chain"], gate=True)
            # S-08 is a hard constraint: if the refined chain fails it on the full length while the
            # starting chain passes, keep the starting chain (plan_master's S-08-aware proposal)
            if kept_moves and (final.get("s08") or {}).get("status") == "fail":
                # fresh evaluator: the starting chain keeps its own drive (no loudness compensation)
                fs = _Evaluator(resolved, profile, ceiling, [x], sr, x, None, None, None)
                start = fs.evaluate(first["chain"], gate=True)
                if (start.get("s08") or {}).get("status") != "fail":
                    rejected_log.append({"i": len(iterations), "constraints": {"S-08": "fail"},
                                         "s08": {k: final["s08"].get(k) for k in ("status", "worst_excess_db", "deltas")},
                                         "note": "full-length S-08 fails for the refined chain; reverted to the starting chain"})
                    best, final = first, start
                    reason = (reason or "") + "; reverted to the starting chain (S-08 on the full length)"
                    kept_moves = []

    unresolved = _unresolved(final or best, blocked_all, valves_all, base, resolved)
    decisions = _decisions(kept_moves, first, final or best, resolved, bool(resolved.get("stems")),
                           blocked_all, valves_all)
    return _json_safe({
        "stage": "master", "variant": base.get("variant"), "profile": base.get("profile"),
        "delivery": base.get("delivery"),
        "iterations": iterations,
        "best": {"chain": best["chain"], "score": best["evaluation"]["score"],
                 "evaluation": best["evaluation"], "limiter": best.get("limiter")},
        "final": None if final is None else {"scope": "full_length", "score": final["evaluation"]["score"],
                                             "evaluation": final["evaluation"], "lufs_i": final.get("lufs_i"),
                                             "true_peak": final.get("true_peak"), "limiter": final.get("limiter"),
                                             "s08": final.get("s08")},
        "converged": converged, "reason": reason,
        "max_iter": max_iter, "min_improvement": min_improvement,
        "unresolved": unresolved, "decisions": decisions,
        "rejected": rejected_log, "blocked": blocked_all, "valves": valves_all,
        "excerpts": [{"label": e["label"], "start_s": e["start"] / sr, "end_s": e["end"] / sr} for e in excerpts],
        "preview": {"renders": evr.renders, "level_matched": True, "rule": "R-01"},
        "base_proposal": base,
        "resolved": O.summarize_resolved(resolved),
        "resolved_notes": resolved.get("notes"),
    })


def _unresolved(final: dict, blocked, valves, base, resolved) -> list[dict]:
    out = []
    ev = final["evaluation"]
    for t in ev["terms"]:
        if t["status"] == "measured" and (t.get("penalty") or 0.0) > 0.25:
            out.append({"code": "term_off_target", "objective": t["objective"], "metric": t["key"],
                        "value": t.get("value"), "target": t.get("target"), "penalty": t.get("penalty")})
        elif t["status"] != "measured":
            out.append({"code": "not_measured", "objective": t["objective"], "metric": t["key"],
                        "reason": t.get("reason")})
    for b in blocked:
        out.append({"code": "master_eq_limit", "rule": "R-15", "band": b.get("band"), "why": b.get("why"),
                    "text": "needed correction exceeds the master EQ limit: a mix-stage problem"})
    for v in valves:
        out.append({"code": "safety_valve", "rule": "R-29", "move": v.get("band") or v.get("kind"),
                    "reason": v.get("reason")})
    g = ev.get("gate") or {}
    if g.get("status") == "fail":
        out.append({"code": "gate_fail", "spec_id": "OF-5",
                    "failed": [c["id"] for c in g.get("checks", []) if c["status"] == "fail"],
                    "suggestions": g.get("corrective_suggestions", [])})
    elif g.get("status") == "incomplete":
        out.append({"code": "gate_incomplete", "spec_id": "OF-5",
                    "not_evaluated": [{"id": c["id"], "reason": c.get("reason")} for c in g.get("checks", [])
                                      if c["status"] == "not_evaluated" and c.get("required")]})
    if any(v == "fail" for v in ev["constraints"].values()):
        out.append({"code": "constraint_fail", "failed": [k for k, v in ev["constraints"].items() if v == "fail"]})
    if base.get("send_back"):
        out.append({"code": "send_back", **base["send_back"]})
    return out


# --------------------------------------------------------------------------
# proposals (R-31)


def propose(project, stage: str = "master", *, variant_id: str | None = None, profile_id: str | None = None,
            delivery_id: str | None = None, max_iter: int | None = None, min_improvement: float = 0.005,
            objective=None, targets=None, overrides=None, excerpt: bool = True) -> dict:
    """Stage proposal (R-31): parameters, rationale with rule ids, alternatives.

    stage "master": mastering.plan_master refined by run_loop. "mix":
    mixplan.plan_mix (fixed order of SPEC 6.5.1; ``max_iter`` default 4).
    "clean": cleanstage.plan_clean (``targets`` / ``overrides``).
    """
    if stage not in STAGES:
        raise InputError(f"unknown stage '{stage}'", details={"valid": list(STAGES)})
    if stage == "mix":
        from .mixplan import plan_mix
        return plan_mix(project, variant_id=variant_id, objective=objective,
                        max_iter=4 if max_iter is None else max_iter, excerpt=excerpt)
    if stage == "clean":
        from .cleanstage import plan_clean
        return plan_clean(project, targets=targets, overrides=overrides)
    if profile_id is None and variant_id is not None:
        v = next((v for v in project.data.get("variants") or [] if v.get("id") == variant_id), None)
        outs = (v or {}).get("outputs") or []
        if outs:
            profile_id = outs[0].get("profile")
            delivery_id = delivery_id or outs[0].get("delivery")
    loop = run_loop(project, variant_id=variant_id, profile_id=profile_id, delivery_id=delivery_id,
                    max_iter=6 if max_iter is None else max_iter, min_improvement=min_improvement,
                    objective=objective)
    base = copy.deepcopy(loop["base_proposal"])
    final = loop.get("final") or {}
    prop = base
    prop["chain"] = loop["best"]["chain"]
    rationale = list(base.get("rationale") or [])
    rationale.append({
        "stage": "planner_loop", "rule": "R-01,R-06,R-15,R-29",
        "measured": {"score_start": loop["iterations"][0]["score"], "score_best": loop["best"]["score"],
                     "iterations": len(loop["iterations"]) - 1},
        "action": T("目的関数の内訳に沿って小さな手を試し、レベルマッチ後の測定で最良の候補を残した",
                    "small moves were tried along the objective breakdown; the best level-matched candidate was kept"),
        "moves": [it["move"] for it in loop["iterations"][1:] if it.get("move")],
        "alternatives": [T("plan_master の提案をそのまま使う", "use the plan_master proposal unchanged")]
                        + [_move_text(b) for b in loop["blocked"][:3]],
        "expected": {"score": loop["best"]["score"], "converged": loop["converged"], "reason": loop["reason"],
                     "s08": ({k: (final.get("s08") or {}).get(k) for k in ("status", "worst_excess_db", "deltas")}
                             if final.get("s08") else None)},
    })
    prop["rationale"] = rationale
    exp = dict(prop.get("expected") or {})
    if final.get("lufs_i") is not None:
        exp["lufs_i"] = round(final["lufs_i"], 2)
    if final.get("true_peak") is not None:
        exp["true_peak"] = round(final["true_peak"], 2)
    if final.get("limiter"):
        exp["limiter_gr"] = {k: round(v, 2) for k, v in final["limiter"].items()}
    exp["objective_score"] = final.get("score", loop["best"]["score"])
    prop["expected"] = exp
    prop["objective_evaluation"] = {
        "score": final.get("score", loop["best"]["score"]),
        "terms": (final.get("evaluation") or loop["best"]["evaluation"])["terms"],
        "constraints": (final.get("evaluation") or loop["best"]["evaluation"])["constraints"],
        "gate": (final.get("evaluation") or loop["best"]["evaluation"]).get("gate"),
        "redistribution": (final.get("evaluation") or loop["best"]["evaluation"])["redistribution"],
        "scope": "full_length" if final else "preview",
    }
    prop["planner"] = {k: loop[k] for k in ("iterations", "converged", "reason", "unresolved", "excerpts",
                                            "rejected", "blocked", "valves", "preview", "max_iter",
                                            "min_improvement")}
    prop["decisions"] = loop["decisions"]
    prop["objective_resolved"] = loop["resolved"]
    prop["alternatives"] = [{"chain": base_chain_summary(loop["base_proposal"]["chain"]),
                             "score": loop["iterations"][0]["score"],
                             "label": T("plan_master の初期提案", "initial plan_master proposal")}]
    prop["operations"] = ["approve_and_apply", "reject_and_request_alternative"]
    prop["proposal_id"] = "mpl_" + canonical_hash({k: prop[k] for k in ("variant", "profile", "delivery", "chain")})[:12]
    return _json_safe(prop)


def base_chain_summary(chain: list[dict]) -> list[dict]:
    return [{"id": p.get("id"), "type": p.get("type"), "params": p.get("params")} for p in chain]


def apply(project, proposal: dict, *, actor: str = "planner") -> dict:
    """Approve and apply a stage proposal (R-31)."""
    stage = proposal.get("stage")
    if stage == "master":
        from .mastering import apply_master_plan
        apply_master_plan(project, proposal, actor=actor)
        return {"applied": True, "stage": "master", "variant": proposal.get("variant"),
                "proposal_id": proposal.get("proposal_id")}
    if stage == "mix":
        from .mixplan import apply_mix_plan
        apply_mix_plan(project, proposal, actor=actor)
        return {"applied": True, "stage": "mix", "variant": proposal.get("variant"),
                "proposal_id": proposal.get("proposal_id")}
    if stage in ("clean", "cleanup"):
        from .cleanstage import apply_clean
        return apply_clean(project, proposal, actor=actor)
    raise InputError(f"cannot apply a '{stage}' proposal", details={"stage": stage, "valid": list(STAGES)})


__all__ = ["STAGES", "choose_excerpts", "build_chain", "run_loop", "propose", "apply"]
