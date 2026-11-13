"""Mix-stage planner (SPEC 6.5, 6.6.1, 6.8, 7.2; R-04..R-13, R-22, R-25, R-28, R-29, R-31).

Deterministic, no LLM (R-23). From a stem set it builds a proposal (R-31)
following the fixed order of SPEC 6.5.1, measuring after every step:

    1 static balance       levels / pan only, importance-aware, lead aimed at
                           the P-10 band of the genre prior (R-04, R-05, R-28)
    2 arrangement          suggestions only (range mute, level drop, band-owner
                           rotation, role check; remix operations of SPEC 9.3)
    3 subtractive EQ       HPF just below the lowest f0 + low-energy floor
                           monitor (R-07, R-29); low-band roles (R-08); lead
                           template stage 1; competitor cuts where the lead is
                           masked (R-05, <= 3 dB per move, R-06, octaves, R-12);
                           accompaniment yield 1-3 kHz (template stage 4)
    4 dynamics             two-stage lead compression, de-esser when the lead is
                           sibilant (R-13), bass levelling, kick -> bass ducking
                           as gain automation when P-02 time_axis asks; times in
                           note values (R-11)
    5 additive EQ/enhance  only with a stated purpose (lead saturation for small
                           speakers, bass harmonics when OF-5 check 4 fails)
    6 space                plate-like reverb FX bus with wet low/high cut, sends
                           ordered by depth (P-09)
    7 mix bus              light glue compression; low-band mono only when
                           S-03 / S-04 fail (R-09)

Every candidate is rendered with ``core.mixrender.render_mix`` on
representative excerpts (SPEC 7.2), measured with ``objectives.measure_for_objective``
with the stems (P-02 / P-09 / P-10 / P-13 / P-22 measured in the full-mix
context, R-02; level matched, R-01) and the OF-5 gate, and evaluated with
``objectives.evaluate`` plus the stage guard terms of knowledge/mix_rules.json.
A step's moves are kept only when they pass the acceptance rule; a problem solved
in an earlier step is protected (a later candidate that undoes it is rejected).

Separated or baked stems (R-22): balance-level operations only, recorded.

Public API:
    plan_mix(project, *, variant_id=None, objective=None, max_iter=4, excerpt=True) -> proposal
    apply_mix_plan(project, proposal, *, actor) -> None
    decisions_six_elements(proposal) -> {balance, pan, frequency, depth, dynamics, interest}
    save_mix_proposal(project, proposal, **fields) -> project-relative path
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy import signal as ss

from . import config
from . import mixrender as mr
from . import objectives as O
from .errors import InputError
from .hashing import canonical_hash

STAGE = "mix"
OWNER = "mixplan"
PROPOSAL_DIR = "cache/proposals"
STEP_IDS = ("static_balance", "arrangement", "subtractive_eq", "dynamics", "additive_eq", "space", "mix_bus")
TEXT_ELEMENTS = ("balance", "pan", "frequency", "depth", "dynamics", "interest")
_TEXT_TO_RECORD = {"balance": "balance", "pan": "panning", "frequency": "frequency", "depth": "depth",
                   "dynamics": "dynamics", "interest": "interest"}
EXTRA_METRICS = frozenset({"P-02", "P-07", "P-09", "P-10", "P-22"})
_EPS = 1e-20
_OPS = {"gain": "balance", "pan": "balance", "filter": "eq", "eq": "eq", "saturator": "eq",
        "compressor": "dynamics", "deesser": "dynamics", "dynamic_eq": "dynamics", "automation": "dynamics",
        "send": "spatial", "reverb": "spatial", "stereo": "spatial", "delay": "spatial"}


def T(ja: str, en: str) -> dict:
    return {"ja": ja, "en": en}


def mix_rules() -> dict:
    return config.load_knowledge("mix_rules")


def _json_safe(obj):
    from .measure.vector import json_safe
    return json_safe(obj)


def _r(v, nd: int = 2):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


def sone_ratio(db: float) -> float:
    """Perceived loudness ratio of a level change (R-25): +10 dB ~ 2x (sone)."""
    return 2.0 ** (float(db) / 10.0)


def db_text(db: float) -> dict:
    """dB change with its sone ratio (R-25)."""
    r = sone_ratio(db)
    return T(f"{db:+.1f} dB（知覚倍率 約{r:.2f}倍）", f"{db:+.1f} dB (about {r:.2f}x in sone)")


def _f(v, nd=1, unit=""):
    if v is None:
        return "n/a"
    return f"{float(v):.{nd}f}{unit}"


# --------------------------------------------------------------------------
# vocabulary (SPEC 6.8.1: words always paired with numbers)


def _vocab(term_id: str) -> dict:
    voc = {t["id"]: t for t in config.load_vocabulary().get("terms", [])}
    t = voc.get(term_id) or {}
    en_fb = (mix_rules().get("vocabulary_en") or {}).get(term_id, term_id)
    ja = (t.get("ja") or [term_id])[0]
    en = (t.get("en") or [en_fb])[0]
    return {"id": term_id, "ja": ja, "en": en}


# --------------------------------------------------------------------------
# roles and groups (SPEC 4.11)


def _group_of(role: str | None, is_lead: bool) -> str:
    if is_lead:
        return "lead_vocal"
    groups = config.load_genre_priors().get("importance_groups", {})
    for g, roles in groups.items():
        if role in roles:
            return "harmony" if g == "lead_vocal" else g
    return "pads_fx_ornaments"


# --------------------------------------------------------------------------
# signal helpers (analysis only; the rendering is core.mixrender)


def _frames2(x) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    return a[:, None] if a.ndim == 1 else a


def _spectrum(x, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Channel-averaged Welch power spectrum."""
    a = _frames2(x)
    n = a.shape[0]
    nper = int(min(8192, 2 ** int(math.floor(math.log2(max(n, 256))))))
    f, p = ss.welch(a, fs=sr, nperseg=nper, noverlap=nper // 2, detrend=False, axis=0)
    return f, np.asarray(p).mean(axis=1)


def _band_db(f: np.ndarray, p: np.ndarray, lo: float, hi: float) -> float | None:
    sel = (f >= lo) & (f < hi)
    s = float(p[sel].sum()) if sel.any() else 0.0
    return 10.0 * math.log10(s) if s > _EPS else None


def _smooth_oct(f: np.ndarray, p: np.ndarray, width_oct: float, grid: np.ndarray) -> np.ndarray:
    """Mean power in a window of ``width_oct`` octaves around each grid frequency, in dB."""
    cs = np.concatenate([[0.0], np.cumsum(p)])
    lo = np.searchsorted(f, grid * 2.0 ** (-width_oct / 2.0))
    hi = np.searchsorted(f, grid * 2.0 ** (width_oct / 2.0))
    hi = np.maximum(hi, lo + 1)
    hi = np.minimum(hi, f.size)
    lo = np.minimum(lo, hi - 1)
    m = (cs[hi] - cs[lo]) / (hi - lo)
    return 10.0 * np.log10(m + _EPS)


def _grid(sr: int, lo: float = 20.0) -> np.ndarray:
    return lo * 2.0 ** (np.arange(0, int(math.log2(0.45 * sr / lo) * 24)) / 24.0)


def _peak_freq(f, p, lo: float, hi: float, sr: int) -> float:
    g = _grid(sr)
    sel = (g >= lo) & (g < hi)
    if not sel.any():
        return math.sqrt(lo * hi)
    lv = _smooth_oct(f, p, 1.0 / 3.0, g[sel])
    return float(g[sel][int(np.argmax(lv))])


def _excess(f, p, lo: float, hi: float, sr: int) -> tuple[float | None, float | None]:
    """Largest (1/6-octave level - 1-octave smoothed level) inside [lo, hi): (excess dB, freq)."""
    g = _grid(sr)
    sel = (g >= lo) & (g < hi)
    if not sel.any():
        return None, None
    fine = _smooth_oct(f, p, 1.0 / 6.0, g[sel])
    broad = _smooth_oct(f, p, 1.0, g[sel])
    d = fine - broad
    i = int(np.argmax(d))
    return float(d[i]), float(g[sel][i])


def _floor_freq(f, p, fraction: float) -> float | None:
    sel = f >= 10.0
    if not sel.any():
        return None
    ff, pp = f[sel], p[sel]
    tot = float(pp.sum())
    if tot <= _EPS:
        return None
    c = np.cumsum(pp) / tot
    i = int(np.searchsorted(c, fraction))
    return float(ff[min(i, ff.size - 1)])


def _frame_power(x, frame: int) -> np.ndarray:
    a = _frames2(x)
    pw = (a * a).mean(axis=1)
    n = pw.size // frame
    if n == 0:
        return np.array([float(pw.sum())])
    return pw[:n * frame].reshape(n, frame).mean(axis=1)


def _active(levels_db: np.ndarray) -> np.ndarray:
    gate = config.load_knowledge("masking_model")["activity_gate"]
    ok = levels_db > -150.0
    if not ok.any():
        return ok
    ref = float(np.percentile(levels_db[ok], 95))
    return ok & (levels_db > float(gate["abs_dbfs"])) & (levels_db > ref - float(gate["rel_db_below_p95"]))


def _db10(v: float) -> float:
    return 10.0 * math.log10(max(float(v), _EPS))


def _gr_frames(x_in, x_out, sr: int, frame_s: float = 0.05) -> dict:
    """Gain reduction measured as in/out level per frame over the active frames of the input."""
    fr = max(16, int(frame_s * sr))
    pi, po = _frame_power(x_in, fr), _frame_power(x_out, fr)
    lev = 10.0 * np.log10(pi + _EPS)
    act = _active(lev)
    if not act.any():
        return {"median_db": 0.0, "p95_db": 0.0, "max_db": 0.0, "active_frames": 0}
    gr = 10.0 * np.log10((pi[act] + _EPS) / (po[act] + _EPS))
    return {"median_db": float(np.median(gr)), "p95_db": float(np.percentile(gr, 95)),
            "max_db": float(np.max(gr)), "active_frames": int(act.sum())}


def _active_level(x, sr: int) -> float | None:
    fr = max(16, int(0.05 * sr))
    p = _frame_power(x, fr)
    lev = 10.0 * np.log10(p + _EPS)
    act = _active(lev)
    return _db10(float(p[act].mean())) if act.any() else None


def _bandpass(x, sr: int, lo: float, hi: float, order: int = 4):
    hi = min(hi, 0.45 * sr)
    sos = ss.butter(order, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return ss.sosfilt(sos, _frames2(x), axis=0)


def _render_steps(x, sr: int, steps: list[dict]):
    from mankomix.dsp import engine
    return engine.render_chain(x, sr, mr.engine_chain(steps), stage="track")


def _yardstick(gr_db: float) -> dict:
    y = mix_rules()["compressor"]["gr_yardsticks_db"]
    if gr_db > y["excessive_above"]:
        return {"id": "excessive", **T("過剰（10 dB 超）", "excessive (above 10 dB)")}
    if gr_db >= y["moderate"][0]:
        return {"id": "moderate", **T("粒をそろえる（3〜6 dB）", "evens the grain (3-6 dB)")}
    return {"id": "light", **T("軽いまとまり（1〜2 dB）", "light glue (1-2 dB)")}


# --------------------------------------------------------------------------
# rendering / evaluation


class _View:
    """Project stand-in whose data is a candidate (used for rendering only)."""

    def __init__(self, project, data: dict):
        self._project = project
        self.data = data

    def __getattr__(self, name):
        return getattr(self._project, name)


def _concat(parts: list[np.ndarray], sr: int) -> np.ndarray:
    if len(parts) == 1:
        return parts[0]
    k = int(0.05 * sr)
    out = []
    for p in parts:
        p = p.copy()
        kk = min(k, p.shape[0] // 2)
        if kk > 0:
            r = np.linspace(0.0, 1.0, kk, endpoint=False)[:, None]
            p[:kk] *= r
            p[-kk:] *= r[::-1]
        out.append(p)
    return np.vstack(out)


class _Evaluator:
    def __init__(self, project, base_data: dict, mix_bus: str, excerpts: list[dict], resolved: dict,
                 sr: int, bpm: float | None, profile: dict | None, rules: dict):
        self.project = project
        self.base = base_data
        self.mix_bus = mix_bus
        self.excerpts = excerpts
        self.resolved = resolved
        self.sr = sr
        self.bpm = bpm
        self.profile = profile
        self.rules = rules
        self.cache: dict[str, dict] = {}
        self.signals: dict[str, tuple] = {}
        self.before = None
        self.renders = 0
        self.track_ids = [t["id"] for t in mr.stem_tracks(base_data)]

    # -- data ---------------------------------------------------------------
    def data_for(self, state: dict) -> dict:
        d = copy.deepcopy(self.base)
        for t in d.get("tracks") or []:
            s = state["tracks"].get(t.get("id"))
            if s is None:
                continue
            t["gain_db"] = float(s["gain_db"])
            t["pan"] = {**(t.get("pan") or {}), **s["pan"]}
            t["chain"] = copy.deepcopy(s["chain"])
            t["sends"] = copy.deepcopy(s["sends"])
            if s.get("automation"):
                t["automation"] = copy.deepcopy(s["automation"])
            else:
                t.pop("automation", None)
        d["buses"] = [b for b in d.get("buses") or [] if b.get("owner") != OWNER]
        for b in d["buses"]:
            if b.get("id") == self.mix_bus:
                b["chain"] = copy.deepcopy(state["mix_chain"])
        idx = next(i for i, b in enumerate(d["buses"]) if b.get("id") == self.mix_bus)
        d["buses"][idx:idx] = [copy.deepcopy(b) for b in state["buses"].values()]
        return d

    def view(self, state: dict) -> _View:
        return _View(self.project, self.data_for(state))

    # -- rendering ------------------------------------------------------------
    def render(self, state: dict) -> tuple[np.ndarray, dict]:
        key = canonical_hash(state)
        hit = self.signals.get(key)
        if hit is not None:
            return hit
        view = self.view(state)
        mixes, per = [], {}
        for e in self.excerpts:
            so: dict = {}
            if e["label"] == "full":
                y, _, _ = mr.render_mix(view, stems_out=so, measure=False)
            else:
                y, _, _ = mr.render_mix(view, start=e["start"], length=e["end"] - e["start"], stems_out=so,
                                        measure=False)
            mixes.append(y)
            for tid in self.track_ids:
                per.setdefault(tid, []).append(so.get(tid))
        self.renders += 1
        stems = {}
        for tid, parts in per.items():
            if all(p is None for p in parts):
                continue
            stems[tid] = _concat([p if p is not None else np.zeros_like(mixes[i]) for i, p in enumerate(parts)],
                                 self.sr)
        out = (_concat(mixes, self.sr), stems)
        if len(self.signals) > 3:
            self.signals.pop(next(iter(self.signals)))
        self.signals[key] = out
        return out

    def track_signal(self, state: dict, tid: str, *, apply_chain: bool = True) -> np.ndarray:
        """Pre-fader track signal (clips -> chain) over the excerpts."""
        view = self.view(state)
        parts = []
        for e in self.excerpts:
            if e["label"] == "full":
                y, _, _ = mr.render_track(view, tid, apply_chain=apply_chain, apply_fader=False)
            else:
                y, _, _ = mr.render_track(view, tid, start=e["start"], length=e["end"] - e["start"],
                                          apply_chain=apply_chain, apply_fader=False)
            parts.append(y)
        return _concat(parts, self.sr)

    # -- evaluation -----------------------------------------------------------
    def evaluate(self, state: dict, *, gate: bool = True) -> dict:
        key = canonical_hash(state)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        y, stems = self.render(state)
        meas = O.measure_for_objective(y, self.sr, self.resolved, before=self.before, stems=stems,
                                       profile=self.profile, gate=gate, bpm=self.bpm,
                                       extra_metrics=set(EXTRA_METRICS))
        ev = O.evaluate(meas, self.resolved)
        out = _summarize(meas, ev, self.rules)
        out["key"] = key
        self.cache[key] = out
        return out


def _summarize(meas: dict, ev: dict, rules: dict) -> dict:
    st = meas.get("stems") or {}
    p10 = st.get("P-10") or {}
    p02 = st.get("P-02") or {}
    vs = p02.get("vs_lead") or {}
    ta = p02.get("time_axis") or {}
    p22 = st.get("P-22") or {}
    p09 = st.get("P-09") or {}
    p08 = st.get("P-08") or {}
    gate = ev.get("gate") or meas.get("gate") or {}
    perc = meas.get("perceptual") or {}
    sec = (p22.get("sections") or [{}])[0]
    out = {
        "score": ev.get("score"),
        "rejected": bool(ev.get("rejected")),
        "constraints": ev.get("constraints") or {},
        "terms": [{k: t.get(k) for k in ("objective", "key", "status", "value", "target", "penalty", "contribution")}
                  for t in ev.get("terms") or []],
        "gate": {"status": gate.get("status"),
                 "checks": {c["id"]: c["status"] for c in gate.get("checks") or []},
                 "suggestions": gate.get("corrective_suggestions") or []},
        "p10": {k: p10.get(k) for k in ("value", "target_db", "target_source", "verdict", "penalty", "lead")},
        "vs_lead": {"value": vs.get("value"), "penalty": vs.get("penalty"),
                    "low_mid": (vs.get("low_mid") or {}).get("buried_db"),
                    "presence": (vs.get("presence") or {}).get("buried_db"),
                    "maskers": {r: (vs.get(r) or {}).get("top_maskers") or [] for r in ("low_mid", "presence")},
                    "bands_hz": {r: (vs.get(r) or {}).get("band_hz") for r in ("low_mid", "presence")}},
        "p02_overall": {"value": (p02.get("overall") or {}).get("value"),
                        "penalty": (p02.get("overall") or {}).get("penalty")},
        "importance": {t: v.get("importance") for t, v in (p02.get("per_target") or {}).items()},
        "time_axis": {k: ta.get(k) for k in ("available", "kick", "bass", "value", "penalty", "unmask_db",
                                              "kick_buried_after_ducking_db")}
                     | {"ducking": ta.get("ducking")},
        "p22": {"max_count": p22.get("max_count"), "penalty": p22.get("penalty"),
                "bands": {b: {"count": v.get("count"), "owners": [o["track"] for o in v.get("owners") or []]}
                          for b, v in (sec.get("bands") or {}).items()}},
        "p09": {"penalty": p09.get("penalty"), "order": p09.get("estimated_order_front_to_back"),
                "lead_rank": p09.get("lead_rank")},
        "p08": {"penalty": p08.get("penalty"), "track": p08.get("track")} if p08 else None,
        "p17_mix": (perc.get("P-17") or {}).get("penalty"),
        "p11_mix": (perc.get("P-11") or {}).get("ltas_prominence_db"),
        "low_ratio_db": O.band_ratio_db(meas.get("vector") or {}, 20.0, 250.0),
        "features": {t: {"f0": f.get("f0"), "stereo": f.get("stereo"), "level": f.get("level"),
                         "activity": f.get("activity")}
                     for t, f in (st.get("features") or {}).items()},
    }
    guard = rules["acceptance"]["guard_terms"]
    gpen = {"P-10": p10.get("penalty"), "P-02:vs_lead": vs.get("penalty"), "P-22": p22.get("penalty")}
    out["guard"] = {k: _r(v, 4) for k, v in gpen.items()}
    # the total uses the unconstrained score so that a mix which already fails an invariant at the start
    # can still be compared; only NEWLY failing invariants reject a candidate (see _Planner._accept)
    score = ev.get("score_unconstrained")
    out["score_unconstrained"] = score
    out["failed"] = sorted(k for k, v in (ev.get("constraints") or {}).items() if v == "fail")
    if score is None:
        out["total"] = math.inf
    else:
        out["total"] = float(score) + sum(float(guard.get(k, 0.0)) * float(v or 0.0) for k, v in gpen.items())
    return out


def _snapshot(c: dict) -> dict:
    return {"score": _r(c["score"], 4), "score_unconstrained": _r(c.get("score_unconstrained"), 4),
            "total": _r(c["total"], 4),
            "P-10": _r(c["p10"].get("value")), "P-10_verdict": c["p10"].get("verdict"),
            "P-02_vs_lead_db": _r(c["vs_lead"].get("value"), 3), "P-02_overall_db": _r(c["p02_overall"].get("value"), 3),
            "P-22_max_owners": c["p22"].get("max_count"), "P-09_penalty": _r(c["p09"].get("penalty"), 3),
            "low_ratio_db": _r(c["low_ratio_db"]), "gate": c["gate"].get("status"),
            "constraints_failed": sorted(k for k, v in c["constraints"].items() if v == "fail")}


# --------------------------------------------------------------------------
# processors


def _proc(pid: str, ptype: str, params: dict, rule: str, why: str) -> dict:
    return {"id": pid, "type": ptype, "params": params, "reason": f"{rule}: {why} (mixplan)", "owner": OWNER}


def _eq_at(chain: list[dict], f: float) -> float:
    """Approximate summed EQ gain (dB) of the chain's eq bands at f."""
    tot = 0.0
    for p in chain:
        if p.get("type") != "eq" or p.get("enabled") is False:
            continue
        q = p.get("params") or {}
        g, fc, bw = float(q.get("gain_db", 0.0)), float(q.get("freq_hz", 1000.0)), float(q.get("bw_oct", 1.0))
        shape = q.get("shape", "peak")
        d = math.log2(max(f, 1.0) / fc)
        if shape == "peak":
            tot += g * math.exp(-math.log(2.0) * (d / max(bw / 2.0, 0.01)) ** 2)
        elif shape == "low_shelf":
            tot += g / (1.0 + (f / fc) ** 2)
        elif shape == "high_shelf":
            tot += g / (1.0 + (fc / f) ** 2)
    return tot


def _limit_eq(chain: list[dict], f: float, g: float, rules: dict) -> float:
    """R-06: |g| <= max_move_db, and the summed response at f stays within max_cumulative_db."""
    e = rules["eq"]
    g = max(-e["max_move_db"], min(e["max_move_db"], g))
    have = _eq_at(chain, f)
    cap = float(e["max_cumulative_db"])
    if abs(have + g) > cap:
        g = math.copysign(cap, g) - have
        if g * math.copysign(1.0, g) <= 0:
            return 0.0
    return round(g, 2)


def _note_ms(note: str, bpm: float | None, fallback_ms: float) -> tuple[float, dict]:
    from mankomix.dsp.processors import note_ms
    if bpm and bpm > 0:
        ms = note_ms(note, bpm)
        return ms, {"note": note, "bpm": round(float(bpm), 3), "ms": round(ms, 2), "rule": "R-11"}
    return float(fallback_ms), {"note": None, "bpm": None, "ms": float(fallback_ms), "rule": "R-11",
                                "note_reason": "tempo unknown: milliseconds used"}


# --------------------------------------------------------------------------
# planner


class _Planner:
    def __init__(self, project, *, variant_id, objective, max_iter, excerpt):
        if max_iter is None or int(max_iter) < 0:
            raise InputError("max_iter must be >= 0")
        self.project = project
        self.variant_id = variant_id
        self.max_iter = int(max_iter)
        self.rules = mix_rules()
        data, _ = mr.effective_data(project, variant_id=variant_id)
        data = copy.deepcopy(data)
        data["buses"] = [b for b in data.get("buses") or [] if b.get("owner") != OWNER]
        mixes = [b.get("id") for b in data["buses"] if b.get("kind") == "mix"]
        if len(mixes) != 1:
            raise InputError(f"exactly one bus of kind 'mix' is required (found {len(mixes)})")
        self.mix_bus = mixes[0]
        tracks = [t for t in mr.stem_tracks(data) if not t.get("muted")]
        if not tracks:
            raise InputError("the mix stage needs stem tracks", details={"hint": "import stems first"})
        self.data = data
        self.tracks = {t["id"]: t for t in tracks}
        self.tids = [t["id"] for t in tracks]
        self.sr = mr.project_rate(data)
        self.resolved = O.resolve_objective(project, variant=variant_id, spec=objective)
        lead = (self.resolved.get("lead") or {}).get("stem")
        self.lead = lead if lead in self.tracks else None
        self.genre = (self.resolved.get("genre") or {}).get("id")
        self.profile_id = self._profile_id()
        self.profile = config.get_profile(self.profile_id)
        self.moves: list[dict] = []
        self.decisions: dict[str, list] = {k: [] for k in O.ELEMENTS}
        self.steps: list[dict] = []
        self.reorderings: list[dict] = []
        self.arrangement: list[dict] = []
        self.protected: dict[str, Any] = {}
        self.unresolved: list[dict] = []
        self.notes: list[dict] = []
        self.excerpt = bool(excerpt)

    def _profile_id(self) -> str:
        if self.variant_id is not None:
            v = next((v for v in self.data.get("variants") or [] if v.get("id") == self.variant_id), None)
            outs = (v or {}).get("outputs") or []
            if outs and outs[0].get("profile"):
                return outs[0]["profile"]
        return "streaming_universal"

    # -- state ----------------------------------------------------------------
    def _initial_state(self) -> dict:
        st: dict = {"tracks": {}, "buses": {}, "mix_chain": []}
        for tid, t in self.tracks.items():
            pos, width = mr.track_pan(t)
            auto = t.get("automation") if isinstance(t.get("automation"), dict) else None
            if auto and auto.get("owner") == OWNER:
                auto = None
            st["tracks"][tid] = {
                "gain_db": float(t.get("gain_db") or 0.0),
                "pan": {"position": float(pos), "width": float(width)},
                "chain": [p for p in t.get("chain") or [] if p.get("owner") != OWNER],
                "sends": [s for s in t.get("sends") or [] if s.get("owner") != OWNER],
                "automation": copy.deepcopy(auto) if auto else None,
            }
        mb = next(b for b in self.data["buses"] if b.get("id") == self.mix_bus)
        st["mix_chain"] = [p for p in mb.get("chain") or [] if p.get("owner") != OWNER]
        return st

    # -- restrictions (R-22) ----------------------------------------------------
    def _restrictions(self, start: dict) -> dict:
        cfg = self.rules["r22"]
        by_id = {a.get("id"): a for a in self.data.get("assets") or []}
        out = {}
        for tid, t in self.tracks.items():
            decl = (t.get("restrictions") or {}).get("operations")
            if decl:
                if "all" in decl:
                    continue
                out[tid] = {"operations": sorted(set(decl)), "rule": (t.get("restrictions") or {}).get("rule") or "R-22",
                            "source": "declared", "reason": T("トラックに宣言された操作制限", "operation limits declared on the track")}
                continue
            origins = {(by_id.get(c.get("asset")) or {}).get("origin") for c in t.get("clips") or []}
            if "separated" in origins:
                out[tid] = {"operations": list(cfg["allowed_operations"]), "rule": "R-22", "source": "separated",
                            "reason": T("分離ステム（他パートの漏れを含む）。外科手術でなくバランス調整にのみ使う",
                                        "separated stem (contains bleed from other parts): balance adjustments only")}
                continue
            lv = ((start["features"].get(tid) or {}).get("level") or {})
            peak, lufs = lv.get("peak_dbfs"), lv.get("lufs_integrated")
            bd = cfg["baked_detection"]
            if peak is not None and lufs is not None and peak >= bd["peak_dbfs_min"] and peak - lufs < bd["plr_max_db"]:
                out[tid] = {"operations": list(cfg["allowed_operations"]), "rule": "R-22", "source": "baked",
                            "measured": {"peak_dbfs": _r(peak), "plr_db": _r(peak - lufs)},
                            "reason": T(f"焼き付いたステム（ピーク {peak:.1f} dBFS、PLR {peak - lufs:.1f} dB でヘッドルームがない）",
                                        f"baked stem (peak {peak:.1f} dBFS, PLR {peak - lufs:.1f} dB: no headroom)")}
        return out

    def allowed(self, tid: str, op: str) -> bool:
        r = self.restrictions.get(tid)
        if r is None:
            return True
        cat = _OPS.get(op, op)
        if cat == "balance":
            if op == "pan" and r.get("source") in ("separated", "baked") and not self.rules["r22"]["allow_pan"]:
                return False
            return "balance" in r["operations"]
        return cat in r["operations"]

    # -- acceptance -------------------------------------------------------------
    def _accept(self, cand: dict, kind: str, target: Callable[[dict], float | None] | None = None,
                valve: Callable[[dict, dict], str | None] | None = None) -> tuple[bool, str, dict]:
        acc = self.rules["acceptance"]
        cur = self.cur
        info = {"total_before": _r(cur["total"], 4), "total_after": _r(cand["total"], 4),
                "score_before": _r(cur["score"], 4), "score_after": _r(cand["score"], 4)}
        newly_failed = sorted(set(cand["failed"]) - set(cur["failed"]))
        if newly_failed:
            return False, "constraint fail: " + ", ".join(newly_failed), info
        if not math.isfinite(cand["total"]):
            return False, "candidate could not be scored", info
        g0, g1 = cur["gate"]["checks"], cand["gate"]["checks"]
        newly = sorted(k for k, v in g1.items() if v == "fail" and g0.get(k) != "fail")
        if newly:
            return False, "OF-5 check would fail: " + ", ".join(newly), info
        if self.protected.get("p10_ok") and cand["p10"].get("verdict") not in (None, "ok"):
            return False, f"would undo P-10 solved in step {self.protected['p10_ok']} (verdict '{cand['p10'].get('verdict')}')", info
        if valve is not None:
            v = valve(cur, cand)
            if v:
                return False, v, info
        d = cur["total"] - cand["total"]
        if target is not None:
            t0, t1 = target(cur), target(cand)
            info["target_before"], info["target_after"] = _r(t0, 4), _r(t1, 4)
        if kind == "template":
            if cand["total"] <= cur["total"] + acc["template_tolerance"]:
                return True, ("improved" if d > 0 else "within tolerance (template default)"), info
            return False, f"worsened the total by {-d:.4f} (> {acc['template_tolerance']})", info
        if d >= acc["min_improvement"]:
            return True, "improved", info
        if target is not None and info.get("target_before") is not None and info.get("target_after") is not None \
                and t0 - t1 >= acc["min_target_gain"] and cand["total"] <= cur["total"] + acc["template_tolerance"]:
            return True, "target metric improved within tolerance", info
        return False, f"no improvement (total change {-d:+.4f})", info

    def _try(self, step: int, moves: list[dict], state: dict, *, kind: str, target=None, valve=None) -> bool:
        if not moves:
            return False
        cand = self.ev.evaluate(state)
        ok, why, info = self._accept(cand, kind, target, valve)
        for m in moves:
            m["status"] = "kept" if ok else "rejected"
            m["result"] = {"verdict": why, **info, "after": _snapshot(cand)}
            self.moves.append(m)
        if ok:
            self.state, self.cur = state, cand
        return ok

    def _move(self, step: int, kind: str, *, track: str | None = None, bus: str | None = None, rules: list[str],
              action: dict, measured: dict, alternatives: list[dict], expected: dict, **extra) -> dict:
        self._seq[step] = self._seq.get(step, 0) + 1
        mid = f"m{step}.{self._seq[step]:02d}"
        self._pending.append(mid)
        m = {"id": mid, "step": step, "step_id": STEP_IDS[step - 1], "kind": kind, "track": track, "bus": bus,
             "rules": rules, "action": action, "measured": measured, "alternatives": alternatives,
             "expected": expected, "status": "proposed"}
        m.update(extra)
        return m

    def _decide(self, element: str, step: int, rule: str, measured: dict, measured_text: dict, action: dict,
                alternatives: list[dict], result: dict | None, result_text: dict, vocab: str | None = None,
                moves: list[dict] | None = None, status: str | None = None) -> None:
        rec = {"stage": "mix", "step": step, "step_id": STEP_IDS[step - 1] if step else None, "rule": rule,
               "measured": measured, "measured_text": measured_text, "action": action,
               "alternatives": alternatives, "result": result, "result_text": result_text,
               "vocabulary": _vocab(vocab) if vocab else None,
               "moves": [m["id"] for m in moves or []]}
        if status:
            rec["status"] = status
        self.decisions[element].append(rec)

    def _end_step(self, step: int, status: str, note: dict | None = None) -> None:
        kept = [m["id"] for m in self.moves if m["step"] == step and m["status"] == "kept"]
        rejected = [m["id"] for m in self.moves if m["step"] == step and m["status"] == "rejected"]
        rec = {"n": step, "id": STEP_IDS[step - 1], "status": status, "kept": kept, "rejected": rejected,
               "measured_after": _snapshot(self.cur)}
        if note:
            rec["note"] = note
        self.steps.append(rec)
        self._pending = []
        # protect what this step solved (SPEC 6.5.1: later steps do not touch it)
        if "p10_ok" not in self.protected and self.lead and self.cur["p10"].get("verdict") == "ok":
            self.protected["p10_ok"] = step

    # -- run --------------------------------------------------------------------
    def run(self) -> dict:
        from .planner import choose_excerpts
        self._pending: list[str] = []
        self._seq: dict[int, int] = {}
        state0 = self._initial_state()
        # full-length starting render: excerpt choice, tempo and sections (SPEC 7.2)
        full = [{"label": "full", "start": 0, "end": mr.timeline_length(self.data, self.sr)}]
        ev_full = _Evaluator(self.project, self.data, self.mix_bus, full, self.resolved, self.sr, None,
                             self.profile, self.rules)
        y_full, stems_full = ev_full.render(state0)
        self.n_full = y_full.shape[0]
        self.music = self._music(y_full)
        self.bpm = self.music.get("bpm")
        if self.excerpt:
            lead_sig = stems_full.get(self.lead) if self.lead else None
            excerpts = choose_excerpts(y_full, self.sr, lead_signal=lead_sig)
        else:
            excerpts = full
        self.excerpts = excerpts
        self.ev = _Evaluator(self.project, self.data, self.mix_bus, excerpts, self.resolved, self.sr, self.bpm,
                             self.profile, self.rules)
        if excerpts[0]["label"] == "full":
            self.ev.signals[canonical_hash(state0)] = (y_full, stems_full)
        y0, _ = self.ev.render(state0)
        self.ev.before = y0
        self.state = state0
        self.cur = self.start = self.ev.evaluate(state0)
        self.restrictions = self._restrictions(self.start)
        self.balance_only = bool(self.restrictions) and all(
            not any(self.allowed(t, op) for op in ("eq", "compressor", "send")) for t in self.tids)
        self.importance = {t: float(self.start["importance"].get(t) or 0.5) for t in self.tids}

        self.step_static_balance()
        self.step_arrangement()
        if self.balance_only:
            for n in range(3, 8):
                self._skip_r22(n)
        else:
            self.step_subtractive_eq()
            self.step_dynamics()
            self.step_additive()
            self.step_space()
            self.step_mix_bus()
        self.refine()
        self.arrangement_review()
        return self._proposal()

    def _music(self, y: np.ndarray) -> dict:
        tb = self.data.get("timebase") or {}
        out: dict = {"bpm": None, "bpm_source": None, "sections": None}
        sections = self.data.get("sections") or []
        need = not tb.get("bpm") or not sections
        m = None
        if need:
            try:
                from .analysis.music import analyze_music
                m = analyze_music(y, self.sr)
            except Exception as exc:  # analysis is advisory here
                self.notes.append({"code": "music_analysis_failed", "text": str(exc)[:200]})
        if tb.get("bpm"):
            out["bpm"], out["bpm_source"] = float(tb["bpm"]), "timebase"
        elif m and m.get("bpm"):
            out["bpm"], out["bpm_source"] = float(m["bpm"]), "estimated"
            out["bpm_confidence"] = m.get("bpm_confidence")
        if sections:
            out["sections"] = [{"id": s["id"], "start_s": s["start"] / self.sr,
                                "end_s": (s["start"] + s["length"]) / self.sr, "label": s.get("label")}
                               for s in sections]
            out["sections_source"] = "project"
        elif m:
            out["sections"] = [{"id": f"sec{i + 1}", "start_s": s.get("start_s"), "end_s": s.get("end_s"),
                                "label": s.get("label")} for i, s in enumerate(m.get("sections") or [])]
            out["sections_source"] = "estimated"
        return out

    # ---------------------------------------------------------------- step 1
    def _clarity_energy(self, stems: dict) -> dict:
        sr = self.sr
        frame = max(16, int(round(0.046 * sr)))
        lp = _frame_power(stems[self.lead], frame)
        act = _active(10.0 * np.log10(lp + _EPS))
        out = {}
        for t, x in stems.items():
            b = _bandpass(x, sr, 300.0, 5000.0)
            pw = _frame_power(b, frame)
            m = min(pw.size, act.size)
            out[t] = float(pw[:m][act[:m]].sum()) if act[:m].any() else 0.0
        return out

    def step_static_balance(self) -> None:
        cfg = self.rules["static_balance"]
        step = 1
        p10 = self.cur["p10"]
        _, stems = self.ev.render(self.state)
        if not self.lead or p10.get("value") is None:
            self._decide("balance", step, "R-04", {"P-10": None},
                         T("主役（リード）が宣言されておらず、主役帯域レベル差 P-10 は測れない（0 件の測定）",
                           "no lead declared: the lead band difference P-10 cannot be measured (0 measurements)"),
                         T("静的バランスは変更しない", "static balance unchanged"), [], None,
                         T("主役を宣言すると P-10 の目標帯に合わせられる", "declare a lead to aim at a P-10 target band"),
                         status="not_evaluated")
            self._pan_step(stems)
            self._end_step(step, "no_lead")
            return
        lo, hi = p10["target_db"]
        v0 = float(p10["value"])
        aim = lo + cfg["p10_aim_fraction"] * (hi - lo) if v0 < lo else hi - cfg["p10_aim_fraction"] * (hi - lo)
        voc = "nukenai" if v0 < lo else "mae_oku"
        verdict_ja = {"buried": "埋もれている", "floating": "浮いている", "ok": "目標内"}.get(p10.get("verdict"), "-")
        mtext = T(f"主役の明瞭度帯域レベル差 P-10 = {v0:+.1f} dB（目標 {lo:+.1f}〜{hi:+.1f} dB、出典 {p10.get('target_source')}、判定: {verdict_ja}）",
                  f"lead clarity-band difference P-10 = {v0:+.1f} dB (target {lo:+.1f}..{hi:+.1f} dB from {p10.get('target_source')}, verdict: {p10.get('verdict')})")
        if lo <= v0 <= hi:
            self._decide("balance", step, "R-04", {"P-10": _r(v0), "target_db": [lo, hi]}, mtext,
                         T("レベルは変更しない（目標帯の内側）", "levels unchanged (inside the target band)"),
                         [T("伴奏を下げてさらに前に出す", "lower the accompaniment further")], {"P-10": _r(v0)},
                         T(f"P-10 = {v0:+.1f} dB のまま", f"P-10 stays at {v0:+.1f} dB"), vocab=voc)
            self._pan_step(stems)
            self._end_step(step, "no_change")
            return
        self._bb = copy.deepcopy(self.state)
        E = self._clarity_energy(stems)
        acc = [t for t in self.tids if t != self.lead and E.get(t, 0.0) > 0.0]
        imp_l = self.importance.get(self.lead, 1.0)
        w = {t: max(0.05, imp_l - self.importance[t] + cfg["importance_floor"]) for t in acc}
        wmax = max(w.values()) if w else 1.0
        w = {t: v / wmax for t, v in w.items()}
        r22max = self.rules["r22"]["max_gain_change_db"]
        cap = {t: (min(cfg["accompaniment_max_trim_db"], r22max) if t in self.restrictions else cfg["accompaniment_max_trim_db"])
               for t in acc}
        lead_up = min(cfg["lead_raise_max_db"], r22max) if self.lead in self.restrictions else cfg["lead_raise_max_db"]
        lead_dn = min(cfg["lead_cut_max_db"], r22max) if self.lead in self.restrictions else cfg["lead_cut_max_db"]
        el = E.get(self.lead, 0.0)

        def model(gains: dict) -> float:
            a = sum(E[t] * 10 ** (gains.get(t, 0.0) / 10.0) for t in acc)
            return _db10(el * 10 ** (gains.get(self.lead, 0.0) / 10.0)) - _db10(a)

        offset = v0 - model({})

        def gains_for(s: float, r: float) -> dict:
            g = {t: -min(s * w[t], cap[t]) for t in acc if self.allowed(t, "gain")}
            if self.allowed(self.lead, "gain"):
                g[self.lead] = r
            return g

        def solve(aim_v: float) -> dict:
            want = aim_v - offset
            if v0 < lo:
                smax = cfg["accompaniment_max_trim_db"]
                if model(gains_for(smax, 0.0)) >= want:
                    a, b = 0.0, smax
                    for _ in range(40):
                        m = 0.5 * (a + b)
                        a, b = (a, m) if model(gains_for(m, 0.0)) >= want else (m, b)
                    return gains_for(b, 0.0)
                a, b = 0.0, lead_up
                if model(gains_for(smax, lead_up)) < want:
                    return gains_for(smax, lead_up)
                for _ in range(40):
                    m = 0.5 * (a + b)
                    a, b = (a, m) if model(gains_for(smax, m)) >= want else (m, b)
                return gains_for(smax, b)
            # floating: the lead comes down (a cut, R-05)
            a, b = -lead_dn, 0.0
            if model(gains_for(0.0, -lead_dn)) > want:
                return gains_for(0.0, -lead_dn)
            for _ in range(40):
                m = 0.5 * (a + b)
                a, b = (m, b) if model(gains_for(0.0, m)) <= want else (a, m)
            return gains_for(0.0, a)

        def build(g: dict) -> tuple[dict, list[dict]]:
            st = copy.deepcopy(self._bb)
            moves = []
            for t, d in sorted(g.items()):
                d = round(d, 1)
                if abs(d) < 0.1:
                    continue
                old = st["tracks"][t]["gain_db"]
                st["tracks"][t]["gain_db"] = round(old + d, 2)
                lead = t == self.lead
                moves.append(self._move(
                    step, "gain", track=t, rules=["R-04", "R-05", "R-28"] + (["R-22"] if t in self.restrictions else []),
                    action=T(f"{t} のフェーダーを {db_text(d)['ja']}", f"{t} fader {db_text(d)['en']}"),
                    measured={"P-10": _r(v0), "target_db": [lo, hi], "aim_db": _r(aim),
                              "importance": _r(self.importance.get(t), 3), "clarity_energy_share_db":
                                  _r(_db10(E.get(t, 0.0)) - _db10(sum(E.values())))},
                    alternatives=[T("主役だけを上げる（R-05 により後回し）", "raise only the lead (deferred by R-05)"),
                                  T("先に EQ で解く（R-04 の順序に反する）", "solve with EQ first (against the R-04 order)")],
                    expected={"P-10_aim_db": _r(aim)}, change={"param": "gain_db", "from": old, "to": st["tracks"][t]["gain_db"],
                                                               "delta_db": d, "sone_ratio": _r(sone_ratio(d), 3)},
                    role="lead" if lead else "accompaniment"))
            return st, moves

        p10_dev = lambda c: abs(float(c["p10"]["value"]) - aim) if c["p10"].get("value") is not None else None
        g = solve(aim)
        st, moves = build(g)
        ok = self._try(step, moves, st, kind="corrective", target=p10_dev)
        it = 0
        while ok and it < self.max_iter:
            v = self.cur["p10"].get("value")
            if v is None or abs(v - aim) <= cfg["solve_tolerance_db"]:
                break
            it += 1
            offset += v - (model(g) + offset)  # secant on the measured residual
            g2 = solve(aim)
            if canonical_hash({k: round(x, 1) for k, x in g2.items()}) == canonical_hash({k: round(x, 1) for k, x in g.items()}):
                break
            st, moves = build(g2)
            if not self._try(step, moves, st, kind="corrective", target=p10_dev):
                break
            g = g2
        v1 = self.cur["p10"].get("value")
        kept = [m for m in self.moves if m["step"] == step and m["status"] == "kept" and m["kind"] == "gain"]
        latest = {}
        for m in kept:
            latest[m["track"]] = m
        changes = [(t, self.state["tracks"][t]["gain_db"] - self._bb["tracks"][t]["gain_db"]) for t in latest]
        acts_ja = "、".join(f"{t} {db_text(d)['ja']}" for t, d in changes) or "変更なし"
        acts_en = ", ".join(f"{t} {db_text(d)['en']}" for t, d in changes) or "no change"
        vfin = _r(v1)
        self._decide("balance", step, "R-04, R-05, R-28",
                     {"P-10": _r(v0), "target_db": [lo, hi], "aim_db": _r(aim), "importance": {t: _r(v, 3) for t, v in self.importance.items()}},
                     T(f"主役が「{_vocab(voc)['ja']}」状態: {mtext['ja']}", f"the lead is {_vocab(voc)['en']}: {mtext['en']}"),
                     T(f"重要度の低い伴奏から下げ（R-05、R-28）、不足分だけ主役を上げた: {acts_ja}",
                       f"lowered the less important accompaniment first (R-05, R-28), raised the lead only for the rest: {acts_en}"),
                     [T("主役だけを上げる", "raise only the lead"), T("EQ で先に解く", "solve with EQ first")],
                     {"P-10": vfin, "verdict": self.cur["p10"].get("verdict")},
                     T(f"P-10 = {_f(vfin)} dB（判定: {self.cur['p10'].get('verdict')}）", f"P-10 = {_f(vfin)} dB (verdict: {self.cur['p10'].get('verdict')})"),
                     vocab=voc, moves=kept)
        if self.cur["p10"].get("verdict") != "ok":
            self.unresolved.append({"code": "p10_off_target", "rule": "R-28", "value": vfin, "target": [lo, hi],
                                    "text": T("静的バランスの上限内では P-10 が目標帯に届かない。アレンジ（ステップ 2）で解く候補",
                                              "P-10 does not reach its band within the static-balance limits; arrangement (step 2) candidate")})
        _, stems = self.ev.render(self.state)
        self._pan_step(stems)
        self._end_step(step, "done")

    def _pan_step(self, stems: dict) -> None:
        cfg = self.rules["static_balance"]["pan"]
        step = 1
        feats = self.cur["features"]
        E = self._clarity_energy(stems) if self.lead else {t: 0.0 for t in self.tids}
        cands = []
        for t in self.tids:
            if t == self.lead or not self.allowed(t, "pan"):
                continue
            g = _group_of(self.tracks[t].get("role"), False)
            if g not in cfg["groups"]:
                continue
            stx = (feats.get(t) or {}).get("stereo") or {}
            if abs(float(stx.get("pan") or 0.0)) > cfg["centered_pan_max"] or \
                    float(stx.get("width_side_ratio") or 0.0) > cfg["mono_side_ratio_max"]:
                continue
            if abs(self.state["tracks"][t]["pan"]["position"]) > 1e-6:
                continue
            cands.append(t)
        cands.sort(key=lambda t: (-E.get(t, 0.0), t))
        measured = {t: {"pan": _r(((feats.get(t) or {}).get("stereo") or {}).get("pan"), 3),
                        "side_ratio": _r(((feats.get(t) or {}).get("stereo") or {}).get("width_side_ratio"), 3)}
                    for t in self.tids}
        if not cands:
            self._decide("panning", step, "R-04, R-09", {"stereo": measured},
                         T(f"伴奏のうち中央かつほぼモノのハーモニー系ステムは 0 件（パン位置と Side 比を {len(measured)} 本で測定）",
                           f"0 centred near-mono harmony stems among the accompaniment (pan and side ratio measured on {len(measured)} stems)"),
                         T("パンは変更しない。主役と低域は中央（R-09）", "pan unchanged; the lead and the low end stay centred (R-09)"),
                         [T("ハーモニーを左右に振る", "spread the harmony left / right")], None,
                         T("定位の変更 0 件", "0 pan changes"))
            return
        st = copy.deepcopy(self.state)
        moves = []
        for i, t in enumerate(cands):
            pos = cfg["positions"][i % len(cfg["positions"])]
            st["tracks"][t]["pan"]["position"] = pos
            moves.append(self._move(step, "pan", track=t, rules=["R-04"],
                                    action=T(f"{t} を {pos:+.2f} に定位", f"pan {t} to {pos:+.2f}"),
                                    measured=measured[t], alternatives=[T("中央のまま", "keep centred")],
                                    expected={"note": "spatial release from masking is not credited by P-02 (channel-averaged)"},
                                    change={"param": "pan.position", "from": 0.0, "to": pos}))
        ok = self._try(step, moves, st, kind="template")
        self._decide("panning", step, "R-04, R-09", {"stereo": {t: measured[t] for t in cands}},
                     T(f"中央かつほぼモノのハーモニー系ステム {len(cands)} 本（Side 比 {cfg['mono_side_ratio_max']} 以下）",
                       f"{len(cands)} centred near-mono harmony stems (side ratio <= {cfg['mono_side_ratio_max']})"),
                     T("主役の中央から外して左右に配置（低域と主役は中央）", "moved off the lead's centre (low end and lead stay centred)"),
                     [T("中央のまま", "keep centred")], {"kept": ok},
                     T("採用" if ok else "不採用（評価が悪化）", "kept" if ok else "rejected (evaluation worsened)"), moves=moves)

    # ---------------------------------------------------------------- step 2
    def _to_song_s(self, t_s: float) -> float:
        pos = 0.0
        for e in self.excerpts:
            ln = (e["end"] - e["start"]) / self.sr
            if t_s < pos + ln or e is self.excerpts[-1]:
                return e["start"] / self.sr + max(0.0, t_s - pos)
            pos += ln
        return t_s

    def step_arrangement(self) -> None:
        step = 2
        cfg = self.rules["arrangement"]
        cur = self.cur
        feats = cur["features"]
        if self.lead:
            for region in ("low_mid", "presence"):
                for mk in cur["vs_lead"]["maskers"].get(region) or []:
                    t = mk["track"]
                    if mk.get("buried_db", 0.0) < cfg["min_buried_db"]:
                        continue
                    la = ((feats.get(self.lead) or {}).get("activity") or {}).get("intervals_s") or []
                    ma = ((feats.get(t) or {}).get("activity") or {}).get("intervals_s") or []
                    ov = []
                    for a0, a1 in la:
                        for b0, b1 in ma:
                            s, e = max(a0, b0), min(a1, b1)
                            if e - s > 0.5:
                                ov.append([_r(self._to_song_s(s), 3), _r(self._to_song_s(e), 3)])
                    low_imp = self.importance.get(t, 0.5) < self.importance.get(self.lead, 1.0)
                    self.arrangement.append({
                        "id": f"arr{len(self.arrangement) + 1}", "kind": "range_mute" if ov and low_imp else "level_drop",
                        "rule": "R-28", "track": t, "region": region, "status": "conditional",
                        "measured": {"buried_db": _r(mk["buried_db"], 2), "importance": _r(self.importance.get(t), 2),
                                     "overlap_s": ov[:8]},
                        "operation": ({"name": "range_mute", "args": [{"track_id": t, "start": int(a * self.sr),
                                                                        "end": int(b * self.sr)} for a, b in ov[:8]]}
                                      if ov and low_imp else {"name": "gain", "args": {"track_id": t, "delta_db": -3.0}}),
                        "text": T(f"{t} が主役を {mk['buried_db']:.1f} dB 埋めている（{region}）。処理で解けなければ、重要度の低い側（{t}）を下げる／区間をミュートする",
                                  f"{t} buries the lead by {mk['buried_db']:.1f} dB ({region}); if processing cannot solve it, the lower-importance side ({t}) is lowered / range-muted")})
            # role check: a non-lead vocal stem much stronger than the lead in the clarity band
            for t in self.tids:
                if t == self.lead or self.tracks[t].get("role") not in ("vocals", "backing_vocals"):
                    continue
                lf = ((feats.get(t) or {}).get("level") or {}).get("active_rms_dbfs")
                ll = ((feats.get(self.lead) or {}).get("level") or {}).get("active_rms_dbfs")
                if lf is not None and ll is not None and lf - ll > cfg["role_swap_clarity_margin_db"]:
                    self.arrangement.append({
                        "id": f"arr{len(self.arrangement) + 1}", "kind": "role_check", "rule": "R-28", "track": t,
                        "status": "recommended", "measured": {"level_vs_lead_db": _r(lf - ll)},
                        "operation": {"name": "set_role", "args": {"track_id": t, "is_lead": True}},
                        "text": T(f"{t} は主役より {lf - ll:.1f} dB 大きい。主役の宣言を確認する",
                                  f"{t} is {lf - ll:.1f} dB louder than the lead: check the lead declaration")})
        # P-22 band-owner rotation per section (R-28, R-08)
        try:
            from .analysis.stems import band_density
            _, stems = self.ev.render(self.state)
            meta = {t: {"role": self.tracks[t].get("role"), "is_lead": t == self.lead,
                        "importance": self.importance.get(t)} for t in stems}
            secs = self._measure_sections()
            bd = band_density(stems, self.sr, meta, secs, genre=self.genre)
        except Exception as exc:
            bd = {"sections": []}
            self.notes.append({"code": "band_density_failed", "text": str(exc)[:200]})
        rot = 0
        for s in bd.get("sections") or []:
            for band, v in (s.get("bands") or {}).items():
                if (v.get("count") or 0) > cfg["p22_max_owners"]:
                    owners = sorted(v.get("owners") or [], key=lambda o: (-(o.get("importance") or 0.0), -o["share"]))
                    keep = [o["track"] for o in owners[:cfg["p22_max_owners"]]]
                    yld = [o["track"] for o in owners[cfg["p22_max_owners"]:]]
                    rot += 1
                    self.arrangement.append({
                        "id": f"arr{len(self.arrangement) + 1}", "kind": "band_owner_rotation", "rule": "R-28",
                        "section": s.get("id"), "band": band, "status": "recommended",
                        "measured": {"owners": v.get("count"), "start_s": _r(self._to_song_s(s.get("start_s", 0.0)), 2),
                                     "end_s": _r(self._to_song_s(max(s.get("end_s", 0.0) - 1e-6, 0.0)), 2)},
                        "keep": keep, "yield": yld,
                        "operation": {"name": "band_yield", "args": {"tracks": yld, "band": band,
                                                                      "how": ["eq_cut", "octave_change", "range_mute"]}},
                        "text": T(f"区間 {s.get('id')} の {band} 帯域に主役が {v.get('count')} 本。{', '.join(keep)} に主役を渡し、{', '.join(yld)} が譲る（EQ／オクターブ／区間ミュート）",
                                  f"section {s.get('id')}: {v.get('count')} owners in the {band} band; keep {', '.join(keep)}, {', '.join(yld)} yield (EQ / octave / range mute)")})
        n = len(self.arrangement)
        self._decide("balance", step, "R-04, R-28",
                     {"P-02_vs_lead_db": _r(cur["vs_lead"].get("value"), 2), "P-22_max_owners": cur["p22"].get("max_count")},
                     T(f"対主役の埋もれ P-02 = {_f(cur['vs_lead'].get('value'), 2)} dB、帯域あたりの主役数 P-22 最大 {cur['p22'].get('max_count')}",
                       f"lead masking P-02 = {_f(cur['vs_lead'].get('value'), 2)} dB, P-22 band owners up to {cur['p22'].get('max_count')}"),
                     T(f"アレンジの提案 {n} 件（自動適用しない。人間かエージェントが承認する）",
                       f"{n} arrangement suggestions (never applied automatically; a human or agent approves them)"),
                     [T("EQ で無理に解く（R-28 により重要度の高い側の極端な加工を避ける）",
                        "force it with EQ (R-28 avoids extreme processing of the more important side)")],
                     {"suggestions": n, "band_owner_rotations": rot},
                     T(f"提案 {n} 件（主役交代 {rot} 件）", f"{n} suggestions ({rot} band-owner rotations)"),
                     vocab="komori" if rot else None)
        self._end_step(step, "suggestions_only", T("提案のみ。適用はリミックス操作（SPEC 9.3）",
                                                   "suggestions only; applied through remix operations (SPEC 9.3)"))

    def _measure_sections(self) -> list[dict] | None:
        if len(self.excerpts) > 1:
            out, pos = [], 0
            for i, e in enumerate(self.excerpts):
                ln = e["end"] - e["start"]
                out.append({"id": f"{e['label']}", "start": pos, "length": ln})
                pos += ln
            return out
        secs = self.music.get("sections") or []
        if not secs:
            return None
        return [{"id": s["id"], "start_s": s["start_s"], "end_s": s["end_s"]} for s in secs if s.get("end_s")]

    def arrangement_review(self) -> None:
        cfg = self.rules["arrangement"]
        for a in self.arrangement:
            if a["status"] != "conditional":
                continue
            region = a.get("region")
            now = None
            for mk in self.cur["vs_lead"]["maskers"].get(region) or []:
                if mk["track"] == a["track"]:
                    now = mk.get("buried_db")
            a["measured"]["buried_db_after_processing"] = _r(now, 2)
            a["status"] = "recommended" if now is not None and now >= cfg["min_buried_db"] else "not_needed"

    # ---------------------------------------------------------------- step 3
    def _skip_r22(self, n: int) -> None:
        lim = {t: r["operations"] for t, r in self.restrictions.items()}
        el = {3: "frequency", 4: "dynamics", 5: "frequency", 6: "depth", 7: "dynamics"}[n]
        self._decide(el, n, "R-22", {"restricted_tracks": len(lim), "tracks": len(self.tids)},
                     T(f"全 {len(self.tids)} 本が分離／焼き付きステム（許可された操作: バランスのみ）",
                       f"all {len(self.tids)} stems are separated / baked (allowed: balance only)"),
                     T("このステップの処理は行わない", "no processing in this step"),
                     [T("処理を入れる（R-22 により不可。漏れとアーティファクトが増幅される）",
                        "process anyway (not allowed by R-22: bleed and artefacts would be amplified)")],
                     None, T("処理 0 件", "0 processors"), status="skipped_r22")
        self._end_step(n, "skipped_r22", T("R-22: バランス調整のみ", "R-22: balance only"))

    def _spectra(self, stems: dict) -> dict:
        return {t: _spectrum(x, self.sr) for t, x in stems.items()}

    def step_subtractive_eq(self) -> None:
        step = 3
        r = self.rules
        _, stems = self.ev.render(self.state)
        spec = self._spectra(stems)
        feats = self.cur["features"]
        # 3a: HPF below the lowest f0 (R-07) + low-band roles (R-08), with the low-energy floor (R-29)
        hcfg = r["hpf"]
        plan = {}
        for t in self.tids:
            if not self.allowed(t, "filter") or any(p.get("type") == "filter" and (p.get("params") or {}).get("kind") == "hpf"
                                                    for p in self.state["tracks"][t]["chain"]):
                continue
            role = self.tracks[t].get("role") or "other"
            rc = {**{"margin_ratio": hcfg["margin_ratio"], "slope_db_oct": hcfg["slope_db_oct"]},
                  **(hcfg["by_role"].get(role) or hcfg["by_role"]["other"])}
            f0 = (feats.get(t) or {}).get("f0") or {}
            f0_low, conf = f0.get("lowest_f0_hz"), float(f0.get("f0_confidence") or 0.0)
            f, p = spec[t]
            floor = _floor_freq(f, p, hcfg["spectral_floor_fraction"])
            cands = [rc["max_hz"]]
            basis = {"role_max_hz": rc["max_hz"]}
            if f0_low and conf >= hcfg["f0_confidence_min"]:
                cands.append(rc["margin_ratio"] * f0_low)
                basis["lowest_f0_hz"] = _r(f0_low, 1)
                basis["f0_confidence"] = _r(conf, 2)
            if floor:
                cands.append(rc["margin_ratio"] * floor)
                basis["energy_floor_hz"] = _r(floor, 1)
            fc = min(cands)
            if fc < hcfg["min_cutoff_hz"]:
                continue
            plan[t] = (round(fc, 1), int(rc["slope_db_oct"]), basis)
        low_moves = self._low_band_roles()

        def build(scale: float, with_roles: bool):
            st = copy.deepcopy(self.state)
            moves = []
            for t, (fc, slope, basis) in plan.items():
                fcs = max(hcfg["min_cutoff_hz"], round(fc * scale, 1))
                st["tracks"][t]["chain"].append(_proc(f"mx.{t}.hpf", "filter", {"kind": "hpf", "freq_hz": fcs, "slope_db_oct": slope},
                                                      "R-07", "HPF just below the lowest f0"))
                moves.append(self._move(step, "chain_add", track=t, rules=["R-07", "R-29", "R-12"],
                                        action=T(f"{t} に HPF {fcs:.0f} Hz（{slope} dB/oct、最小位相）",
                                                 f"{t}: HPF {fcs:.0f} Hz ({slope} dB/oct, minimum phase)"),
                                        measured=basis, alternatives=[T("低域カットなし", "no low cut"),
                                                                      T("シェルフで下げる", "lower with a shelf instead")],
                                        expected={"low_floor_max_drop_db": r["low_end"]["low_floor_max_drop_db"]},
                                        processor=st["tracks"][t]["chain"][-1]))
            if with_roles:
                for t, proc, basis in low_moves:
                    g = _limit_eq(st["tracks"][t]["chain"], proc["params"]["freq_hz"], proc["params"]["gain_db"], r)
                    if g == 0.0:
                        continue
                    proc = copy.deepcopy(proc)
                    proc["params"]["gain_db"] = g
                    st["tracks"][t]["chain"].append(proc)
                    moves.append(self._move(step, "chain_add", track=t, rules=["R-08", "R-28", "R-29"],
                                            action=T(f"{t} の低域を {db_text(g)['ja']}（シェルフ {proc['params']['freq_hz']:.0f} Hz）で譲る",
                                                     f"{t} yields the low band: shelf {proc['params']['freq_hz']:.0f} Hz {db_text(g)['en']}"),
                                            measured=basis, alternatives=[T("アレンジで役割を分ける", "split the roles by arrangement")],
                                            expected={"max_low_elements": r["low_end"]["max_elements"]}, processor=proc))
            return st, moves

        def low_valve(cur, cand):
            a, b = cur.get("low_ratio_db"), cand.get("low_ratio_db")
            if a is not None and b is not None and a - b > r["low_end"]["low_floor_max_drop_db"]:
                return f"R-29: low/rest would drop by {a - b:.2f} dB (> {r['low_end']['low_floor_max_drop_db']} dB)"
            return None

        lr0 = self.cur["low_ratio_db"]
        if plan or low_moves:
            st, moves = build(1.0, True)
            ok = self._try(step, moves, st, kind="template", valve=low_valve)
            if not ok:
                st, moves = build(0.7, False)
                ok = self._try(step, moves, st, kind="template", valve=low_valve)
                if ok:
                    self.reorderings.append({"step": step, "rule": "R-29", "text": T(
                        "低域の下限監視により HPF を 0.7 倍に緩め、低域の役割分担は見送った",
                        "the low-energy floor relaxed the HPFs to 0.7x and dropped the low-band role moves")})
            lr1 = self.cur["low_ratio_db"]
            kept = [m for m in self.moves if m["step"] == step and m["status"] == "kept"]
            self._decide("frequency", step, "R-07, R-08, R-29",
                         {"low_ratio_db_before": _r(lr0), "hpf_tracks": len(plan), "low_role_moves": len(low_moves)},
                         T(f"各ステムの最低基本周波数とエネルギー下限を測定（HPF 候補 {len(plan)} 本）。低域総量（20〜250 Hz 対 残り）= {_f(lr0)} dB。「{_vocab('sukasuka')['ja']}」にならない下限: 低下 {r['low_end']['low_floor_max_drop_db']} dB まで",
                           f"lowest f0 and energy floor measured per stem ({len(plan)} HPF candidates); low/rest (20-250 Hz) = {_f(lr0)} dB; floor against '{_vocab('sukasuka')['en']}': at most {r['low_end']['low_floor_max_drop_db']} dB drop"),
                         T(f"最低基本周波数の直下に HPF を置いた（{len([m for m in kept if 'HPF' in m['action']['en']])} 本）",
                           f"HPFs just below the lowest f0 ({len([m for m in kept if 'HPF' in m['action']['en']])} stems)"),
                         [T("HPF なし", "no HPF"), T("シェルフで下げる", "shelving instead")],
                         {"low_ratio_db_after": _r(lr1)},
                         T(f"低域総量 {_f(lr0)} -> {_f(lr1)} dB", f"low/rest {_f(lr0)} -> {_f(lr1)} dB"), vocab="sukasuka", moves=kept)
        self._pending = []
        if self.lead:
            self._lead_template_cuts(step)
            self._competitor_cuts(step)
        self._end_step(step, "done")

    def _low_band_roles(self) -> list:
        r = self.rules
        bands = self.cur["p22"]["bands"]
        out = []
        owners_low = set()
        for b in ("sub", "bass"):
            v = bands.get(b) or {}
            if (v.get("count") or 0) > r["low_end"]["max_elements"]:
                owners_low.update(v.get("owners") or [])
        if not owners_low:
            return out
        keep = {t for t in owners_low if self.tracks.get(t, {}).get("role") in ("bass", "drums") or t == self.lead}
        cfg = r["eq"]["low_band_role"]
        for t in sorted(owners_low - keep):
            if not self.allowed(t, "eq"):
                continue
            proc = _proc(f"mx.{t}.lowrole", "eq", {"shape": "low_shelf", "freq_hz": cfg["shelf_hz"], "gain_db": cfg["gain_db"],
                                                   "bw_oct": cfg["shelf_bw_oct"], "phase": "minimum"},
                         "R-08", "low-band role: not the low-end owner")
            out.append((t, proc, {"owners_low": sorted(owners_low), "kept_owners": sorted(keep)}))
        return out

    def _lead_template_cuts(self, step: int) -> None:
        """Template stage 1 (vocal subtractive) + stage 4 (accompaniment yield 1-3 kHz)."""
        r = self.rules
        _, stems = self.ev.render(self.state)
        spec = self._spectra(stems)
        st = copy.deepcopy(self.state)
        moves = []
        L = self.lead
        ls = r["eq"]["lead_subtractive"]
        fL, pL = spec[L]
        f0 = (self.cur["features"].get(L) or {}).get("f0") or {}
        core = None
        if f0.get("lowest_f0_hz") and f0.get("median_f0_hz"):
            core = (float(f0["lowest_f0_hz"]) * 2.0 ** (-ls["core_margin_oct"]),
                    float(f0["median_f0_hz"]) * 2.0 ** ls["core_upper_oct"])
        skipped_core = []
        if self.allowed(L, "eq"):
            for tag, band, mn, bw, voc in (("mud", ls["mud_band_hz"], ls["mud_min_excess_db"], ls["mud_bw_oct"], "komori"),
                                           ("res", ls["resonance_band_hz"], ls["resonance_min_excess_db"], ls["resonance_bw_oct"], "kinkin")):
                ex, fx = _excess(fL, pL, band[0], band[1], self.sr)
                if ex is None or ex < mn:
                    continue
                if core is not None and core[0] <= fx <= core[1]:
                    # R-29 / 6.8.1 'futoi': never cut the core (fundamental range) of the lead
                    skipped_core.append({"tag": tag, "freq_hz": _r(fx, 1), "excess_db": _r(ex),
                                         "core_hz": [_r(core[0], 1), _r(core[1], 1)]})
                    continue
                g = -min(ls["max_cut_db"], max(ls["min_cut_db"], ls["cut_fraction"] * ex))
                g = _limit_eq(st["tracks"][L]["chain"], fx, g, r)
                if g == 0.0:
                    continue
                proc = _proc(f"mx.{L}.{tag}", "eq", {"shape": "peak", "freq_hz": round(fx, 1), "gain_db": g, "bw_oct": bw,
                                                     "phase": "minimum"}, "R-06", f"lead {tag} cut (template stage 1)")
                st["tracks"][L]["chain"].append(proc)
                v = _vocab(voc)
                moves.append(self._move(step, "chain_add", track=L, rules=["R-06", "R-12"], template_stage=1,
                                        action=T(f"主役の「{v['ja']}」帯域 {fx:.0f} Hz を {db_text(g)['ja']}（幅 {bw} oct）",
                                                 f"lead '{v['en']}' band {fx:.0f} Hz {db_text(g)['en']} (width {bw} oct)"),
                                        measured={"excess_db": _r(ex), "freq_hz": _r(fx, 1)},
                                        alternatives=[T("カットしない", "no cut"), T("ダイナミック EQ（間欠的な場合、R-13）", "dynamic EQ if intermittent (R-13)")],
                                        expected={"excess_db_after": _r(ex + g)}, processor=proc, vocabulary=v))
        # stage 4: the accompaniment yields 1-3 kHz (R-05)
        ay = r["eq"]["accompaniment_yield"]
        p10 = self.cur["p10"]
        aim_low = p10.get("value") is not None and p10.get("target_db") and \
            p10["value"] < p10["target_db"][0] + r["static_balance"]["p10_aim_fraction"] * (p10["target_db"][1] - p10["target_db"][0])
        buried_pres = (self.cur["vs_lead"].get("presence") or 0.0) > 0.0 and (self.cur["vs_lead"].get("penalty") or 0.0) > 0.0
        gdef = ay["gain_db_if_buried"] if (aim_low or buried_pres) else ay["gain_db"]
        lead_band = _band_db(fL, pL, *ay["band_hz"])
        yielded = []
        for t in self.tids:
            if t == L or _group_of(self.tracks[t].get("role"), False) not in ay["groups"] or not self.allowed(t, "eq"):
                continue
            f, p = spec[t]
            lv = _band_db(f, p, *ay["band_hz"])
            if lv is None or lead_band is None or lv - lead_band < ay["min_level_vs_lead_db"]:
                continue
            g = _limit_eq(st["tracks"][t]["chain"], ay["freq_hz"], gdef, r)
            if g == 0.0:
                continue
            proc = _proc(f"mx.{t}.yield", "eq", {"shape": "peak", "freq_hz": ay["freq_hz"], "gain_db": g, "bw_oct": ay["bw_oct"],
                                                 "phase": "minimum"}, "R-05", "accompaniment yields 1-3 kHz (template stage 4)")
            st["tracks"][t]["chain"].append(proc)
            yielded.append(t)
            moves.append(self._move(step, "chain_add", track=t, rules=["R-05", "R-06", "R-12"], template_stage=4,
                                    action=T(f"{t} の 1〜3 kHz を {db_text(g)['ja']}（声の芯の居場所を作る）",
                                             f"{t}: 1-3 kHz {db_text(g)['en']} (room for the core of the voice)"),
                                    measured={"band_level_vs_lead_db": _r(lv - lead_band), "P-10": _r(p10.get("value"))},
                                    alternatives=[T("主役を上げる（R-05 により不採用）", "raise the lead (rejected by R-05)"),
                                                  T("伴奏のフェーダーを下げる", "lower the accompaniment fader")],
                                    expected={"P-10": "up", "P-02_vs_lead": "down"}, processor=proc, role="accompaniment_yield"))
        if skipped_core:
            v = _vocab("futoi")
            lo_c, hi_c = skipped_core[0]["core_hz"]
            ja_list = "、".join(f"{x['freq_hz']} Hz（突出 {x['excess_db']} dB）" for x in skipped_core)
            en_list = ", ".join(f"{x['freq_hz']} Hz (excess {x['excess_db']} dB)" for x in skipped_core)
            self._decide("frequency", step, "R-29", {"skipped": skipped_core},
                         T(f"主役の {ja_list} は基本音の範囲 {lo_c}〜{hi_c} Hz（「{v['ja']}」の芯）",
                           f"lead {en_list} lies in its fundamental range {lo_c}-{hi_c} Hz (the '{v['en']}' core)"),
                         T("雛形第1段のカットを見送った（芯の帯域を削らない）", "template stage-1 cut skipped (the core band is not cut)"),
                         [T("雛形どおり 2〜4 dB カット", "cut 2-4 dB as in the template")], None,
                         T(f"カット 0 件（見送り {len(skipped_core)} 件）", f"0 cuts ({len(skipped_core)} skipped)"),
                         vocab="futoi", status="valve")
        if not moves:
            return
        pres0 = self._acc_presence(stems)

        def valve(cur, cand):
            _, s1 = self.ev.render(st)
            d = pres0 - self._acc_presence(s1)
            if d > r["eq"]["accompaniment_presence_max_drop_db"]:
                return f"R-29: accompaniment presence would drop {d:.2f} dB (> {r['eq']['accompaniment_presence_max_drop_db']} dB)"
            return None

        v0 = self.cur["vs_lead"].get("value")
        ok = self._try(step, moves, st, kind="template", valve=valve)
        v1 = self.cur["vs_lead"].get("value")
        kept = [m for m in moves if m["status"] == "kept"]
        _, s_now = self.ev.render(self.state)
        pres1 = self._acc_presence(s_now)
        self._decide("frequency", step, "R-05, R-06, R-29",
                     {"P-02_vs_lead_db": _r(v0, 3), "P-10": _r(p10.get("value")), "accompaniment_presence_db": _r(pres0)},
                     T(f"「{_vocab('nukenai')['ja']}」対策: 対主役の埋もれ P-02 = {_f(v0, 2)} dB、P-10 = {_f(p10.get('value'))} dB。伴奏 {len(yielded)} 本が 1〜3 kHz で主役から {abs(ay['min_level_vs_lead_db']):.0f} dB 以内",
                       f"against '{_vocab('nukenai')['en']}': lead masking P-02 = {_f(v0, 2)} dB, P-10 = {_f(p10.get('value'))} dB; {len(yielded)} accompaniment stems within {abs(ay['min_level_vs_lead_db']):.0f} dB of the lead at 1-3 kHz"),
                     T(f"歌もの雛形の第1段（主役の引き算 EQ）と第4段（伴奏の 1〜3 kHz を {gdef:+.1f} dB）を測定に合わせて入れた（{len(kept)} 手）",
                       f"vocal template stage 1 (lead subtractive EQ) and stage 4 (accompaniment 1-3 kHz {gdef:+.1f} dB) adapted to the measurement ({len(kept)} moves)"),
                     [T("主役のフェーダーを上げる（伴奏の上に乗せただけになる）", "raise the lead fader (it would only sit on top of the accompaniment)")],
                     {"P-02_vs_lead_db": _r(v1, 3), "accompaniment_presence_db": _r(pres1)},
                     T(f"P-02 対主役 {_f(v0, 2)} -> {_f(v1, 2)} dB、伴奏のプレゼンス {_f(pres0)} -> {_f(pres1)} dB（下限: 低下 {r['eq']['accompaniment_presence_max_drop_db']} dB まで）",
                       f"P-02 vs lead {_f(v0, 2)} -> {_f(v1, 2)} dB, accompaniment presence {_f(pres0)} -> {_f(pres1)} dB (floor: at most {r['eq']['accompaniment_presence_max_drop_db']} dB drop)"),
                     vocab="nukenai", moves=kept, status=None if ok else "rejected")
        self._pending = []

    def _acc_presence(self, stems: dict) -> float:
        acc = [x for t, x in stems.items() if t != self.lead]
        if not acc:
            return -200.0
        s = np.sum(acc, axis=0)
        f, p = _spectrum(s, self.sr)
        return _band_db(f, p, 1000.0, 4000.0) or -200.0

    def _competitor_cuts(self, step: int) -> None:
        r = self.rules
        cc = r["eq"]["competitor_cut"]
        _, stems = self.ev.render(self.state)
        fL, pL = _spectrum(stems[self.lead], self.sr)
        st = copy.deepcopy(self.state)
        moves = []
        vs = self.cur["vs_lead"]
        for region in ("low_mid", "presence"):
            band = vs["bands_hz"].get(region) or ([200.0, 800.0] if region == "low_mid" else [2000.0, 5000.0])
            fpk = _peak_freq(fL, pL, band[0], band[1], self.sr)
            n = 0
            for mk in vs["maskers"].get(region) or []:
                t = mk["track"]
                if n >= cc["max_maskers_per_region"] or mk.get("buried_db", 0.0) < cc["min_masker_buried_db"] \
                        or not self.allowed(t, "eq") or t == self.lead:
                    continue
                g = -min(cc["max_cut_db"], max(cc["min_cut_db"], cc["db_per_buried_db"] * mk["buried_db"]))
                g = _limit_eq(st["tracks"][t]["chain"], fpk, g, r)
                if g == 0.0:
                    continue
                n += 1
                proc = _proc(f"mx.{t}.unmask_{region}", "eq", {"shape": "peak", "freq_hz": round(fpk, 1), "gain_db": g,
                                                              "bw_oct": cc["bw_oct"], "phase": "minimum"},
                             "R-05", f"competitor cut where the lead is masked ({region})")
                st["tracks"][t]["chain"].append(proc)
                voc = _vocab("komori" if region == "low_mid" else "nukenai")
                moves.append(self._move(step, "chain_add", track=t, rules=["R-05", "R-06", "R-12", "R-28"],
                                        action=T(f"{t} の {fpk:.0f} Hz を {db_text(g)['ja']}（主役の{region}帯域の競合を下げる）",
                                                 f"{t}: {fpk:.0f} Hz {db_text(g)['en']} (lower the competitor in the lead's {region} band)"),
                                        measured={"buried_db": _r(mk["buried_db"], 3), "region": region, "band_hz": band,
                                                  "lead_peak_hz": _r(fpk, 1), "masker_importance": _r(mk.get("importance"), 2)},
                                        alternatives=[T("主役を上げる（R-05 により不採用）", "raise the lead (rejected by R-05)"),
                                                      T("区間ミュート（R-28、ステップ 2 の提案）", "range mute (R-28, step-2 suggestion)")],
                                        expected={"P-02_vs_lead": "down"}, processor=proc, vocabulary=voc))
        if not moves:
            self._decide("frequency", step, "R-05", {"P-02_vs_lead_db": _r(vs.get("value"), 3)},
                         T(f"主役を {cc['min_masker_buried_db']} dB 以上埋める競合ステムは 0 本（P-02 対主役 = {_f(vs.get('value'), 2)} dB）",
                           f"0 competitors bury the lead by >= {cc['min_masker_buried_db']} dB (P-02 vs lead = {_f(vs.get('value'), 2)} dB)"),
                         T("競合側のカットなし", "no competitor cut"), [], None, T("変更 0 件", "0 changes"))
            return
        target = lambda c: c["vs_lead"].get("value")
        v0 = vs.get("value")
        ok = self._try(step, moves, st, kind="corrective", target=target)
        if not ok:
            # one fallback: half the depth
            st2 = copy.deepcopy(self.state)
            half = []
            for m in moves:
                p = copy.deepcopy(m["processor"])
                p["params"]["gain_db"] = round(p["params"]["gain_db"] / 2.0, 2)
                if abs(p["params"]["gain_db"]) < 0.5:
                    continue
                st2["tracks"][m["track"]]["chain"].append(p)
                half.append(self._move(step, "chain_add", track=m["track"], rules=m["rules"],
                                       action=T(m["action"]["ja"] + "（半分の量で再試行）", m["action"]["en"] + " (retried at half depth)"),
                                       measured=m["measured"], alternatives=m["alternatives"], expected=m["expected"],
                                       processor=p, vocabulary=m.get("vocabulary")))
            ok = self._try(step, half, st2, kind="corrective", target=target)
            moves = half or moves
        v1 = self.cur["vs_lead"].get("value")
        kept = [m for m in moves if m["status"] == "kept"]
        self._decide("frequency", step, "R-05, R-06, R-12",
                     {"P-02_vs_lead_db": _r(v0, 3), "candidates": len(moves)},
                     T(f"主役が競合に埋もれている（「{_vocab('nukenai')['ja']}」）: P-02 対主役 = {_f(v0, 2)} dB、競合候補 {len(moves)} 本",
                       f"the lead is masked by competitors ('{_vocab('nukenai')['en']}'): P-02 vs lead = {_f(v0, 2)} dB, {len(moves)} competitor candidates"),
                     T(f"主役を上げずに、競合側の同じ帯域を 1 手 3 dB 以内で下げた（採用 {len(kept)} 手、最小位相、幅はオクターブ）",
                       f"cut the competitors in the same band instead of raising the lead, <= 3 dB per move ({len(kept)} kept, minimum phase, widths in octaves)"),
                     [T("主役を上げる", "raise the lead"), T("区間ミュート（ステップ 2）", "range mute (step 2)")],
                     {"P-02_vs_lead_db": _r(v1, 3)},
                     T(f"P-02 対主役 {_f(v0, 2)} -> {_f(v1, 2)} dB", f"P-02 vs lead {_f(v0, 2)} -> {_f(v1, 2)} dB"),
                     vocab="nukenai", moves=kept, status=None if ok else "rejected")
        self._pending = []

    # ---------------------------------------------------------------- step 4
    def _design_comp(self, x, base: dict, *, stat: str, target: float) -> tuple[dict, dict, np.ndarray]:
        iters = int(self.rules["compressor"]["threshold_iterations"])
        p = dict(base)
        y = x
        gr = {"median_db": 0.0, "p95_db": 0.0}
        for _ in range(max(1, iters)):
            res = _render_steps(x, self.sr, [{"id": "probe", "type": "compressor", "params": p}])
            y = np.asarray(res.audio)
            gr = _gr_frames(x, y * 10 ** (-p.get("makeup_db", 0.0) / 20.0), self.sr)
            err = target - gr[stat]
            if abs(err) < 0.3:
                break
            slope = max(0.2, 1.0 - 1.0 / float(p["ratio"]))
            p["threshold_db"] = round(float(np.clip(p["threshold_db"] - err / slope, -60.0, 0.0)), 2)
        return p, gr, y

    def step_dynamics(self) -> None:
        step = 4
        r = self.rules
        cc = r["compressor"]
        st = copy.deepcopy(self.state)
        moves = []
        records = []
        if self.lead and self.allowed(self.lead, "compressor"):
            L = self.lead
            x = self.ev.track_signal(st, L)
            lvl0 = _active_level(x, self.sr)
            # stage A: fast peak control
            a = cc["lead_peak"]
            rel_a, rel_a_rec = _note_ms(a["release_note"], self.bpm, a["release_ms_without_bpm"])
            pk = np.max(np.abs(_frames2(x)), axis=1)
            fr = max(16, int(0.01 * self.sr))
            pkf = pk[:pk.size // fr * fr].reshape(-1, fr).max(axis=1) if pk.size >= fr else pk
            lev = 20.0 * np.log10(pkf + 1e-12)
            act = _active(lev)  # 20*log10(peak) is already a power-equivalent dB level
            thr0 = float(np.percentile(lev[act], 90)) - 3.0 if act.any() else -20.0
            pa = {"threshold_db": round(float(np.clip(thr0, -60, 0)), 2), "ratio": a["ratio"], "knee_db": a["knee_db"],
                  "attack_ms": a["attack_ms"], "release_ms": round(rel_a, 2), "detector": a["detector"], "makeup_db": 0.0}
            pa, gra, ya = self._design_comp(x, pa, stat="p95_db", target=a["target_gr_p95_db"])
            # stage B: slow levelling, 2-3 dB
            b = cc["lead_level"]
            rel_b, rel_b_rec = _note_ms(b["release_note"], self.bpm, b["release_ms_without_bpm"])
            lv_b = _active_level(ya, self.sr) or -30.0
            pb = {"threshold_db": round(float(np.clip(lv_b - 1.0, -60, 0)), 2), "ratio": b["ratio"], "knee_db": b["knee_db"],
                  "attack_ms": b["attack_ms"], "release_ms": round(rel_b, 2), "detector": b["detector"],
                  "rms_window_ms": b["rms_window_ms"], "makeup_db": 0.0}
            pb, grb, yb = self._design_comp(ya, pb, stat="median_db", target=b["target_gr_median_db"])
            lvl1 = _active_level(yb, self.sr)
            makeup = round(float(np.clip((lvl0 or 0.0) - (lvl1 or 0.0), 0.0, 12.0)), 2) if lvl0 is not None and lvl1 is not None else 0.0
            pb["makeup_db"] = makeup
            ca = _proc(f"mx.{L}.comp_peak", "compressor", pa, "R-11", "lead stage A: fast peak control (template stage 2)")
            cb = _proc(f"mx.{L}.comp_level", "compressor", pb, "R-11", "lead stage B: slow 2-3 dB levelling (template stage 2)")
            ca["note_values"] = {"release": rel_a_rec}
            cb["note_values"] = {"release": rel_b_rec}
            st["tracks"][L]["chain"] += [ca, cb]
            for proc, gr, rec, tag in ((ca, gra, rel_a_rec, "A"), (cb, grb, rel_b_rec, "B")):
                ysk = _yardstick(gr["median_db"] if tag == "B" else gr["p95_db"])
                moves.append(self._move(step, "chain_add", track=L, rules=["R-11", "R-13"], template_stage=2,
                                        action=T(f"主役のコンプ段{tag}: 閾値 {proc['params']['threshold_db']:.1f} dBFS、{proc['params']['ratio']}:1、リリース {rec.get('note') or ''} {rec['ms']:.0f} ms",
                                                 f"lead compressor stage {tag}: threshold {proc['params']['threshold_db']:.1f} dBFS, {proc['params']['ratio']}:1, release {rec.get('note') or ''} {rec['ms']:.0f} ms"),
                                        measured={"gr_median_db": _r(gr["median_db"]), "gr_p95_db": _r(gr["p95_db"]),
                                                  "yardstick": ysk["id"], "release": rec},
                                        alternatives=[T("1 段のみ", "single stage"), T("コンプなし", "no compression")],
                                        expected={"gr": ysk}, processor=proc))
            records.append(("lead", gra, grb, makeup, rel_a_rec, rel_b_rec))
            # de-esser when the lead is sibilant (P-17 on the lead, R-13)
            from .analysis.perceptual import sibilance
            s0 = sibilance(yb, self.sr)
            de = r["deesser"]
            if self.allowed(L, "deesser") and (s0.get("penalty") or 0.0) > de["min_penalty"]:
                band = _bandpass(yb, self.sr, 5000.0, 8000.0)
                fr5 = max(16, int(0.005 * self.sr))
                bp = _frame_power(band, fr5)
                lvb = 10.0 * np.log10(bp + _EPS)
                actb = _active(lvb)
                thr = float(np.percentile(lvb[actb], 95)) - de["threshold_below_p95_db"] if actb.any() else -40.0
                pd = {"freq_hz": de["freq_hz"], "bw_oct": de["bw_oct"], "threshold_db": round(float(np.clip(thr, -80, 0)), 2),
                      "range_db": de["range_db"], "attack_ms": de["attack_ms"], "release_ms": de["release_ms"]}
                drop = s1 = None
                for _ in range(4):
                    res = _render_steps(yb, self.sr, [{"id": "probe", "type": "deesser", "params": pd}])
                    yd = np.asarray(res.audio)
                    b1 = _bandpass(yd, self.sr, 5000.0, 8000.0)
                    drop = _db10(float((band * band).mean())) - _db10(float((b1 * b1).mean()))
                    if drop <= de["max_band_drop_db"]:
                        s1 = sibilance(yd, self.sr)
                        break
                    pd["threshold_db"] = round(min(0.0, pd["threshold_db"] + 2.0), 2)
                if s1 is not None:
                    cd = _proc(f"mx.{L}.deess", "deesser", pd, "R-13", "lead sibilance (P-17) is intermittent: dynamic control")
                    st["tracks"][L]["chain"].append(cd)
                    v = _vocab("sibilant")
                    moves.append(self._move(step, "chain_add", track=L, rules=["R-13", "R-29"],
                                            action=T(f"主役にディエッサー（{pd['freq_hz']:.0f} Hz、閾値 {pd['threshold_db']:.1f} dBFS、最大 {pd['range_db']:.0f} dB）",
                                                     f"lead de-esser ({pd['freq_hz']:.0f} Hz, threshold {pd['threshold_db']:.1f} dBFS, up to {pd['range_db']:.0f} dB)"),
                                            measured={"P-17_lead_penalty": _r(s0.get("penalty"), 3),
                                                      "p99_prominence_db": _r(s0.get("p99_prominence_db")),
                                                      "event_pct": _r(s0.get("event_pct"))},
                                            alternatives=[T("静的 EQ で 5〜8 kHz を下げる（常時の問題ではないので不採用、R-13）",
                                                            "static 5-8 kHz cut (not a constant problem: rejected by R-13)")],
                                            expected={"P-17_lead_penalty_after": _r(s1.get("penalty"), 3),
                                                      "band_drop_db": _r(drop), "consonant_floor_db": de["max_band_drop_db"]},
                                            processor=cd, vocabulary=v))
                    records.append(("deesser", s0, s1, drop))
        # bass levelling when its level spread is large
        bass = [t for t in self.tids if self.tracks[t].get("role") == "bass" and self.allowed(t, "compressor")]
        for t in bass[:1]:
            x = self.ev.track_signal(st, t)
            fr = max(16, int(0.1 * self.sr))
            lv = 10.0 * np.log10(_frame_power(x, fr) + _EPS)
            act = _active(lv)
            spread = float(np.percentile(lv[act], 90) - np.percentile(lv[act], 10)) if act.sum() > 3 else 0.0
            bc = cc["bass_level"]
            if spread <= bc["level_spread_db"]:
                records.append(("bass_skip", t, spread))
                continue
            rel, rel_rec = _note_ms(bc["release_note"], self.bpm, bc["release_ms_without_bpm"])
            l0 = _active_level(x, self.sr) or -30.0
            pbs = {"threshold_db": round(float(np.clip(l0, -60, 0)), 2), "ratio": bc["ratio"], "knee_db": bc["knee_db"],
                   "attack_ms": bc["attack_ms"], "release_ms": round(rel, 2), "detector": bc["detector"],
                   "rms_window_ms": bc["rms_window_ms"], "makeup_db": 0.0}
            pbs, grs, ys = self._design_comp(x, pbs, stat="median_db", target=bc["target_gr_median_db"])
            l1 = _active_level(ys, self.sr)
            pbs["makeup_db"] = round(float(np.clip(l0 - (l1 or l0), 0.0, 12.0)), 2)
            proc = _proc(f"mx.{t}.comp", "compressor", pbs, "R-11", "bass levelling")
            proc["note_values"] = {"release": rel_rec}
            st["tracks"][t]["chain"].append(proc)
            ysk = _yardstick(grs["median_db"])
            moves.append(self._move(step, "chain_add", track=t, rules=["R-11"],
                                    action=T(f"{t} を {pbs['ratio']}:1 でならす（GR 中央値 {grs['median_db']:.1f} dB）",
                                             f"{t}: levelling at {pbs['ratio']}:1 (median GR {grs['median_db']:.1f} dB)"),
                                    measured={"level_spread_db": _r(spread), "gr_median_db": _r(grs["median_db"]), "release": rel_rec},
                                    alternatives=[T("コンプなし", "no compression")], expected={"gr": ysk}, processor=proc))
            records.append(("bass", t, spread, grs))
        if moves:
            ok = self._try(step, moves, st, kind="template")
        else:
            ok = False
        kept = [m for m in moves if m["status"] == "kept"]
        for rec in records:
            if rec[0] == "lead":
                _, gra, grb, makeup, ra, rb = rec
                self._decide("dynamics", step, "R-11, R-13",
                             {"gr_stage_a_p95_db": _r(gra["p95_db"]), "gr_stage_b_median_db": _r(grb["median_db"]), "makeup_db": makeup},
                             T(f"主役のゲインリダクションを測定: 段A p95 {gra['p95_db']:.1f} dB、段B 中央値 {grb['median_db']:.1f} dB（「{_vocab('tsubure')['ja']}」の目安は 10 dB 超）",
                               f"lead gain reduction measured: stage A p95 {gra['p95_db']:.1f} dB, stage B median {grb['median_db']:.1f} dB ('{_vocab('tsubure')['en']}' above 10 dB)"),
                             T(f"2段階コンプ（速い検出でピーク、遅い検出で {grb['median_db']:.1f} dB のレベリング）。リリースは音価 {ra.get('note') or '-'} / {rb.get('note') or '-'}（R-11）。メイクアップ {makeup:+.1f} dB でステップ 1 のバランスを保持",
                               f"two-stage compression (fast peak control, slow {grb['median_db']:.1f} dB levelling); releases as note values {ra.get('note') or '-'} / {rb.get('note') or '-'} (R-11); makeup {makeup:+.1f} dB keeps the step-1 balance"),
                             [T("1 段のみ", "single stage"), T("コンプなし", "no compression")],
                             {"kept": ok, "yardstick_b": _yardstick(grb["median_db"])["id"]},
                             T(f"{_yardstick(grb['median_db'])['ja']}（{'採用' if ok else '不採用'}）",
                               f"{_yardstick(grb['median_db'])['en']} ({'kept' if ok else 'rejected'})"),
                             vocab="tsubure", moves=[m for m in kept if m["track"] == self.lead and m["processor"]["type"] == "compressor"])
            elif rec[0] == "deesser":
                _, s0, s1, drop = rec
                self._decide("dynamics", step, "R-13, R-29",
                             {"P-17_lead_before": _r(s0.get("penalty"), 3), "P-17_lead_after": _r(s1.get("penalty"), 3)},
                             T(f"主役が「{_vocab('sibilant')['ja']}」: 5〜8 kHz の突出 p99 {_f(s0.get('p99_prominence_db'))} dB、事象率 {_f(s0.get('event_pct'))}%（P-17 = {_f(s0.get('penalty'), 3)}）",
                               f"the lead is {_vocab('sibilant')['en']}: 5-8 kHz prominence p99 {_f(s0.get('p99_prominence_db'))} dB, event rate {_f(s0.get('event_pct'))}% (P-17 = {_f(s0.get('penalty'), 3)})"),
                             T("間欠的な問題なのでディエッサー（ダイナミック処理、R-13）", "intermittent problem: de-esser (dynamic, R-13)"),
                             [T("静的な 5〜8 kHz カット", "static 5-8 kHz cut")],
                             {"P-17_lead_after": _r(s1.get("penalty"), 3), "p99_prominence_db_after": _r(s1.get("p99_prominence_db")),
                              "event_pct_after": _r(s1.get("event_pct")), "band_drop_db": _r(drop)},
                             T(f"突出 p99 {_f(s0.get('p99_prominence_db'))} -> {_f(s1.get('p99_prominence_db'))} dB、事象率 {_f(s0.get('event_pct'))} -> {_f(s1.get('event_pct'))}%、P-17（主役）{_f(s0.get('penalty'), 3)} -> {_f(s1.get('penalty'), 3)}、5〜8 kHz の平均低下 {_f(drop)} dB（子音の下限 {r['deesser']['max_band_drop_db']} dB）",
                               f"prominence p99 {_f(s0.get('p99_prominence_db'))} -> {_f(s1.get('p99_prominence_db'))} dB, event rate {_f(s0.get('event_pct'))} -> {_f(s1.get('event_pct'))}%, P-17 (lead) {_f(s0.get('penalty'), 3)} -> {_f(s1.get('penalty'), 3)}, mean 5-8 kHz drop {_f(drop)} dB (consonant floor {r['deesser']['max_band_drop_db']} dB)"),
                             vocab="sibilant", moves=[m for m in kept if m["processor"]["type"] == "deesser"])
            elif rec[0] == "bass_skip":
                self._decide("dynamics", step, "R-11", {"level_spread_db": _r(rec[2])},
                             T(f"{rec[1]} の短時間レベルの幅 {rec[2]:.1f} dB（基準 {cc['bass_level']['level_spread_db']} dB 以下）",
                               f"{rec[1]} short-term level spread {rec[2]:.1f} dB (<= {cc['bass_level']['level_spread_db']} dB)"),
                             T("ベースのコンプなし", "no bass compression"), [T("軽くならす", "light levelling")], None,
                             T("変更 0 件", "0 changes"))
        self._pending = []
        self._ducking(step)
        self._end_step(step, "done")

    def _ducking(self, step: int) -> None:
        dk = self.rules["ducking"]
        ta = self.cur["time_axis"]
        if not ta.get("available"):
            self._decide("dynamics", step, "R-11", {"time_axis": None},
                         T("キックとベースのステムを特定できない（時間軸のマスキング 0 件測定）",
                           "kick and bass stems not identified (0 time-axis measurements)"),
                         T("サイドチェイン相当の処理なし", "no ducking"), [], None, T("変更 0 件", "0 changes"))
            return
        ok_max = config.load_knowledge("masking_model")["penalties"]["time_axis"]["ok_max_db"]
        val = ta.get("value") or 0.0
        wants = any(b["id"] in dk["time_axis_objectives"] for b in self.resolved.get("blend") or [])
        kick, bass = ta.get("kick"), ta.get("bass")
        mtext = T(f"キックがベースに {val:.2f} dB 埋もれている（許容 {ok_max} dB まで、P-02 時間軸版）",
                  f"the kick is buried by the bass by {val:.2f} dB (ok up to {ok_max} dB, P-02 time axis)")
        if val <= ok_max and not wants:
            self._decide("dynamics", step, "R-11", {"kick_buried_db": _r(val, 2), "ok_max_db": ok_max}, mtext,
                         T("ダッキングは入れない", "no ducking"),
                         [T(f"{bass} をキックでダッキング", f"duck {bass} with the kick")], None, T("変更 0 件", "0 changes"))
            return
        if not self.allowed(bass, "automation") or self.state["tracks"][bass].get("automation"):
            self._decide("dynamics", step, "R-11, R-22", {"kick_buried_db": _r(val, 2)}, mtext,
                         T("ベースに既存のオートメーションまたは操作制限があるため見送り", "skipped: the bass has automation or restrictions"),
                         [], None, T("変更 0 件", "0 changes"))
            return
        note = (ta.get("ducking") or {}).get("suggested_release_note") or dk["release_note_default"]
        rel_ms, rel_rec = _note_ms(note, self.bpm, dk["release_ms_without_bpm"])
        st = copy.deepcopy(self.state)
        view = self.ev.view(st)
        xk, _, _ = mr.render_track(view, kick, apply_chain=False, apply_fader=False)
        band = _bandpass(xk, self.sr, 40.0, 120.0)
        hop = max(1, int(0.005 * self.sr))
        env = 10.0 * np.log10(_frame_power(band, hop) + _EPS)
        act = env > -150
        if not act.any():
            return
        ref = float(np.percentile(env[act], 95)) - dk["trigger_db_below_p95"]
        above = env > ref
        onsets = np.flatnonzero(above & ~np.concatenate([[False], above[:-1]])) * hop
        mi = int(dk["min_interval_ms"] * 1e-3 * self.sr)
        keep = []
        for o in onsets:
            if not keep or o - keep[-1] >= mi:
                keep.append(int(o))
        att = int(dk["attack_ms"] * 1e-3 * self.sr)
        rel = int(rel_ms * 1e-3 * self.sr)
        pts: list[list] = []
        for i, o in enumerate(keep):
            nxt = keep[i + 1] - att if i + 1 < len(keep) else None
            a0 = max(0, o - att)
            if pts and a0 <= pts[-1][0]:
                a0 = pts[-1][0] + 1
            end = o + rel if nxt is None else min(o + rel, max(o + 1, nxt - 1))
            if o <= a0:
                o = a0 + 1
            if end <= o:
                end = o + 1
            pts += [[a0, 0.0], [o, -float(dk["depth_db"])], [end, 0.0]]
        st["tracks"][bass]["automation"] = {"gain_db": pts, "owner": OWNER,
                                            "reason": f"R-11: kick -> bass ducking (time-axis unmasking), release {note} (mixplan)"}
        mv = self._move(step, "automation", track=bass, rules=["R-11", "R-13"],
                        action=T(f"{bass} をキックの {len(keep)} 打で {dk['depth_db']:.1f} dB ダッキング（リリース {note} = {rel_ms:.0f} ms）",
                                 f"duck {bass} by {dk['depth_db']:.1f} dB on {len(keep)} kick hits (release {note} = {rel_ms:.0f} ms)"),
                        measured={"kick_buried_db": _r(val, 2), "ok_max_db": ok_max, "release": rel_rec},
                        alternatives=[T("ベースの EQ で 40〜120 Hz を下げる（常時の処理になる）", "static bass EQ at 40-120 Hz (constant)")],
                        expected={"kick_buried_after_ducking_db": _r(ta.get("kick_buried_after_ducking_db"), 2)},
                        automation={"points": len(pts), "hits": len(keep)})
        ok = self._try(step, [mv], st, kind="corrective", target=lambda c: c["time_axis"].get("value"))
        self._decide("dynamics", step, "R-11, R-13", {"kick_buried_db": _r(val, 2)}, mtext, mv["action"],
                     mv["alternatives"], {"kick_buried_db_after": _r(self.cur["time_axis"].get("value"), 2)},
                     T(f"キックの埋もれ {val:.2f} -> {_f(self.cur['time_axis'].get('value'), 2)} dB（{'採用' if ok else '不採用'}）",
                       f"kick buried {val:.2f} -> {_f(self.cur['time_axis'].get('value'), 2)} dB ({'kept' if ok else 'rejected'})"),
                     moves=[mv] if ok else [])
        self._pending = []

    # ---------------------------------------------------------------- step 5
    def step_additive(self) -> None:
        step = 5
        r = self.rules["saturation"]
        if self.lead and self.allowed(self.lead, "saturator"):
            L = self.lead
            st = copy.deepcopy(self.state)
            c = r["lead"]
            x = self.ev.track_signal(st, L)
            p = {"drive_db": c["drive_db"], "mode": c["mode"], "mix": c["mix"], "oversample": c["oversample"], "output_db": 0.0}
            res = _render_steps(x, self.sr, [{"id": "probe", "type": "saturator", "params": p}])
            y = np.asarray(res.audio)
            f0_, p0_ = _spectrum(x, self.sr)
            f1_, p1_ = _spectrum(y, self.sr)
            lo, hi = c["band_hz"]
            sh0 = (_band_db(f0_, p0_, lo, hi) or 0.0) - _db10(float(p0_.sum()))
            sh1 = (_band_db(f1_, p1_, lo, hi) or 0.0) - _db10(float(p1_.sum()))
            l0, l1 = _active_level(x, self.sr), _active_level(y, self.sr)
            if l0 is not None and l1 is not None:
                p["output_db"] = round(float(np.clip(l0 - l1, -6.0, 6.0)), 2)
            proc = _proc(f"mx.{L}.sat", "saturator", p, "R-06", "lead harmonics in 1-5 kHz for small speakers (template stage 3)")
            st["tracks"][L]["chain"].append(proc)
            mv = self._move(step, "chain_add", track=L, rules=["R-06"], template_stage=3,
                            action=T(f"主役に薄いサチュレーション（ドライブ {p['drive_db']:.0f} dB、ミックス {p['mix']:.2f}）",
                                     f"light lead saturation (drive {p['drive_db']:.0f} dB, mix {p['mix']:.2f})"),
                            measured={"share_1_5k_db_before": _r(sh0), "share_1_5k_db_after": _r(sh1)},
                            purpose=T("小口径スピーカーでも声の存在感を保つ（OF-5 の帯域制限チェック）",
                                      "keep the voice present on small speakers (OF-5 band-limited check)"),
                            alternatives=[T("足し算をしない", "no enhancement"), T("1〜5 kHz の EQ ブースト（R-05 によりカット優先）", "1-5 kHz EQ boost (R-05 prefers cuts)")],
                            expected={"share_change_db": _r(sh1 - sh0)}, processor=proc)
            ok = self._try(step, [mv], st, kind="template")
            v = _vocab("nuke_nobi")
            self._decide("frequency", step, "R-06",
                         {"share_1_5k_db_before": _r(sh0), "share_1_5k_db_after": _r(sh1)},
                         T(f"目的: 小口径でも「{v['ja']}」声を保つ。主役の 1〜5 kHz の比率 {sh0:.1f} dB",
                           f"purpose: keep the voice '{v['en']}' on small speakers; lead 1-5 kHz share {sh0:.1f} dB"),
                         mv["action"], mv["alternatives"], {"kept": ok},
                         T(f"1〜5 kHz の比率 {sh0:.1f} -> {sh1:.1f} dB（{'採用' if ok else '不採用'}）",
                           f"1-5 kHz share {sh0:.1f} -> {sh1:.1f} dB ({'kept' if ok else 'rejected'})"),
                         vocab="nuke_nobi", moves=[mv] if ok else [])
            self._pending = []
        # bass harmonics only when OF-5 check 4 fails or P-08 is poor
        b = r["bass_enhance"]
        chk = self.cur["gate"]["checks"].get("pitch_preserved_without_fundamental")
        p08 = (self.cur.get("p08") or {})
        bt = p08.get("track") or next((t for t in self.tids if self.tracks[t].get("role") == "bass"), None)
        p08_pen = p08.get("penalty")
        # P-08 says whether harmonics are missing; a check-4 failure with healthy harmonics has another cause
        need = (p08_pen is not None and p08_pen >= b["p08_penalty_min"]) or (chk == "fail" and p08_pen is None)
        if bt and chk == "fail" and not need:
            v = _vocab("futoi")
            self._decide("frequency", step, "R-16", {"gate_pitch_check": chk, "P-08_penalty": _r(p08_pen, 3)},
                         T(f"OF-5 チェック 4 = {chk}、ただし倍音補完 P-08 = {_f(p08_pen, 3)}（倍音は足りている。「{v['ja']}」さは保たれている）",
                           f"OF-5 check 4 = {chk}, but harmonic completion P-08 = {_f(p08_pen, 3)} (harmonics are present; the '{v['en']}' quality holds)"),
                         T("倍音付加は入れない（目的が説明できない）", "no harmonic enhancement (no purpose can be stated)"),
                         [T("ベースに倍音付加", "bass harmonic enhancement")], None,
                         T("変更 0 件。チェック 4 の不合格は未解決として残す", "0 changes; the check-4 failure stays unresolved"),
                         vocab="futoi")
        if bt and need and self.allowed(bt, "saturator"):
            st = copy.deepcopy(self.state)
            p = {"drive_db": b["drive_db"], "mode": b["mode"], "asymmetry": b["asymmetry"], "mix": b["mix"],
                 "oversample": b["oversample"], "output_db": 0.0}
            x = self.ev.track_signal(st, bt)
            y = np.asarray(_render_steps(x, self.sr, [{"id": "probe", "type": "saturator", "params": p}]).audio)
            l0, l1 = _active_level(x, self.sr), _active_level(y, self.sr)
            if l0 is not None and l1 is not None:
                p["output_db"] = round(float(np.clip(l0 - l1, -6.0, 6.0)), 2)
            proc = _proc(f"mx.{bt}.harm", "saturator", p, "R-06", "bass harmonics so the pitch survives without the fundamental (OF-5 check 4)")
            st["tracks"][bt]["chain"].append(proc)
            mv = self._move(step, "chain_add", track=bt, rules=["R-06", "R-16"],
                            action=T(f"{bt} に倍音付加（ドライブ {p['drive_db']:.0f} dB、ミックス {p['mix']:.2f}）",
                                     f"{bt}: harmonic enhancement (drive {p['drive_db']:.0f} dB, mix {p['mix']:.2f})"),
                            measured={"gate_pitch_check": chk, "P-08_penalty": _r(p08.get("penalty"), 3)},
                            purpose=T("基本音が出ない再生系でも低音の音高を保つ（OF-5 チェック 4、P-08）",
                                      "keep the bass pitch audible without the fundamental (OF-5 check 4, P-08)"),
                            alternatives=[T("足し算をしない", "no enhancement")], expected={"gate_pitch_check": "pass"},
                            processor=proc)

            def tgt(c):
                return (0.0 if c["gate"]["checks"].get("pitch_preserved_without_fundamental") != "fail" else 1.0) + \
                    float(((c.get("p08") or {}).get("penalty")) or 0.0)

            ok = self._try(step, [mv], st, kind="corrective", target=tgt)
            v = _vocab("futoi")
            self._decide("frequency", step, "R-06, R-16",
                         {"gate_pitch_check": chk, "P-08_penalty": _r(p08.get("penalty"), 3)},
                         T(f"目的: 「{v['ja']}」低音を小型スピーカーでも保つ。OF-5 チェック 4 = {chk}、P-08 = {_f(p08.get('penalty'), 3)}",
                           f"purpose: keep a '{v['en']}' bass on small speakers; OF-5 check 4 = {chk}, P-08 = {_f(p08.get('penalty'), 3)}"),
                         mv["action"], mv["alternatives"],
                         {"gate_pitch_check": self.cur["gate"]["checks"].get("pitch_preserved_without_fundamental"),
                          "P-08_penalty": _r((self.cur.get("p08") or {}).get("penalty"), 3)},
                         T(f"チェック 4 = {self.cur['gate']['checks'].get('pitch_preserved_without_fundamental')}、P-08 = {_f((self.cur.get('p08') or {}).get('penalty'), 3)}（{'採用' if ok else '不採用'}）",
                           f"check 4 = {self.cur['gate']['checks'].get('pitch_preserved_without_fundamental')}, P-08 = {_f((self.cur.get('p08') or {}).get('penalty'), 3)} ({'kept' if ok else 'rejected'})"),
                         vocab="futoi", moves=[mv] if ok else [])
            self._pending = []
        self._end_step(step, "done", T("足し算は目的が説明できるものだけ", "additive moves only with a stated purpose"))

    # ---------------------------------------------------------------- step 6
    def step_space(self) -> None:
        step = 6
        rv = self.rules["reverb"]
        senders = [t for t in self.tids if self.allowed(t, "send")
                   and _group_of(self.tracks[t].get("role"), t == self.lead) not in rv["no_send_groups"]]
        if not senders:
            self._decide("depth", step, "R-10", {"senders": 0},
                         T("リバーブを送る対象 0 本", "0 stems to send to a reverb"), T("空間処理なし", "no spatial processing"),
                         [], None, T("変更 0 件", "0 changes"))
            self._end_step(step, "no_change")
            return
        bus_id = rv["bus_id"]
        if any(b.get("id") == bus_id for b in self.data["buses"]):
            bus_id = bus_id + "_mx"
        pre_ms, pre_rec = _note_ms(rv["predelay_note"], self.bpm, rv["predelay_ms_without_bpm"])
        params = dict(rv["params"])
        if self.genre in rv["short_reverb_genres"]:
            params["rt60_s"] = rv["short_rt60_s"]
        params["predelay_ms"] = round(min(250.0, pre_ms), 2)
        params["bpm"] = round(float(self.bpm), 3) if self.bpm else 0.0
        bus = {"id": bus_id, "kind": "fx", "name": "plate-like reverb (mixplan)", "output": self.mix_bus, "owner": OWNER,
               "chain": [_proc(f"mx.{bus_id}.plate", "reverb", params, "R-10",
                               "plate-like reverb, wet low-cut 600 Hz / high-cut 6 kHz keep only the tail (template stage 5)")]}
        bus["chain"][0]["note_values"] = {"predelay": pre_rec}
        declared = [t for t in (self.data.get("mix") or {}).get("declared_depth_order") or [] if t in self.tracks]
        st = copy.deepcopy(self.state)
        st["buses"][bus_id] = bus
        moves = [self._move(step, "bus_add", bus=bus_id, rules=["R-10", "R-11"], template_stage=5,
                            action=T(f"FX バス {bus_id}: プレート系リバーブ RT60 {params['rt60_s']:.1f} s、プリディレイ {pre_rec.get('note') or ''} {params['predelay_ms']:.0f} ms、返りの低域 {params['lowcut_hz']:.0f} Hz／高域 {params['highcut_hz']:.0f} Hz カット",
                                     f"FX bus {bus_id}: plate-like reverb RT60 {params['rt60_s']:.1f} s, pre-delay {pre_rec.get('note') or ''} {params['predelay_ms']:.0f} ms, return low-cut {params['lowcut_hz']:.0f} Hz / high-cut {params['highcut_hz']:.0f} Hz"),
                            measured={"genre": self.genre, "bpm": self.bpm, "predelay": pre_rec},
                            alternatives=[T("ホール系の長い残響", "longer hall"), T("ディレイ（音価で、R-11）", "a note-value delay (R-11)")],
                            expected={"depth": "lead front, harmony behind"}, bus_def=bus)]
        sends = {}
        for t in senders:
            g = _group_of(self.tracks[t].get("role"), t == self.lead)
            if declared and t in declared:
                lvl = rv["sends_db"]["lead_vocal"] + rv["declared_order_step_db"] * declared.index(t)
            else:
                lvl = rv["sends_db"].get(g, rv["sends_db"]["harmony"])
            lvl = round(min(rv["max_send_db"], lvl), 1)
            sends[t] = lvl
            st["tracks"][t]["sends"].append({"bus": bus_id, "level_db": lvl, "pre_fader": False, "owner": OWNER})
            moves.append(self._move(step, "send", track=t, rules=["R-10", "R-28"],
                                    action=T(f"{t} -> {bus_id} に {lvl:.1f} dB 送る", f"send {t} -> {bus_id} at {lvl:.1f} dB"),
                                    measured={"group": g, "declared_rank": declared.index(t) if t in declared else None},
                                    alternatives=[T("送らない（乾いた音は手前）", "no send (dry is front)")],
                                    expected={"depth_rank": "lead least"}, send={"bus": bus_id, "level_db": lvl}))
        p09_0 = self.cur["p09"].get("penalty")
        ok = self._try(step, moves, st, kind="template")
        v = _vocab("mae_oku")
        self._decide("depth", step, "R-10, R-11",
                     {"P-09_penalty_before": _r(p09_0, 3), "sends_db": sends, "declared_order": declared or None},
                     T(f"奥行き P-09 = {_f(p09_0, 3)}（主役が先頭なら 0）。「{v['ja']}」: 乾いた音は手前、残響の多い音は奥。送り {len(sends)} 本",
                       f"depth P-09 = {_f(p09_0, 3)} (0 when the lead is in front); '{v['en']}': dry is front, reverberant is back; {len(sends)} sends"),
                     T(f"プレート系リバーブを FX バスに置き、主役の送りを最小（{sends.get(self.lead, 'なし')} dB）、ハーモニーと装飾を多めに送った",
                       f"plate-like reverb on an FX bus; the lead gets the smallest send ({sends.get(self.lead, 'none')} dB), harmony and ornaments more"),
                     [T("主役に多く送る（奥に引っ込む）", "send the lead more (it moves back)"), T("ディレイで奥行き", "depth by delay")],
                     {"kept": ok, "P-09_penalty_after": _r(self.cur["p09"].get("penalty"), 3)},
                     T(f"P-09 {_f(p09_0, 3)} -> {_f(self.cur['p09'].get('penalty'), 3)}（送りの残響はステム単体の D/R に現れないため P-09 は乾いた信号で測っている）",
                       f"P-09 {_f(p09_0, 3)} -> {_f(self.cur['p09'].get('penalty'), 3)} (send returns are not part of the dry stems, so P-09 is measured on the dry signals)"),
                     vocab="mae_oku", moves=[m for m in moves if m["status"] == "kept"])
        self._decide("panning", step, "R-10", {"width_processing": 0},
                     T("全帯域ワイドナーは既定にしない（0 件）", "no full-band widener by default (0)"),
                     T("幅の処理なし", "no width processing"), [T("帯域別の幅（stereo）", "band-wise width (stereo)")], None,
                     T("変更 0 件（前提: スピーカー 60 度、ヘッドホン、モノ）", "0 changes (assumed: speakers at 60 deg, headphones, mono)"))
        self._pending = []
        self._end_step(step, "done")

    # ---------------------------------------------------------------- step 7
    def step_mix_bus(self) -> None:
        step = 7
        if self.variant_id is not None:
            self._decide("dynamics", step, "R-04", {"variant": self.variant_id},
                         T("バリアントはバスの差分を持てない（track_overrides のみ）", "a variant cannot hold bus differences (track_overrides only)"),
                         T("ミックスバス処理は見送り", "mix-bus processing skipped"), [], None,
                         T("変更 0 件（必要なスキーマ: variants[].bus_overrides）", "0 changes (schema needed: variants[].bus_overrides)"),
                         status="skipped_variant")
            self._end_step(step, "skipped_variant")
            return
        bc = self.rules["compressor"]["bus"]
        y, _ = self.ev.render(self.state)
        rel, rel_rec = _note_ms(bc["release_note"], self.bpm, bc["release_ms_without_bpm"])
        l = _active_level(y, self.sr) or -20.0
        p = {"threshold_db": round(float(np.clip(l + 3.0, -60, 0)), 2), "ratio": bc["ratio"], "knee_db": bc["knee_db"],
             "attack_ms": bc["attack_ms"], "release_ms": round(rel, 2), "detector": bc["detector"],
             "rms_window_ms": bc["rms_window_ms"], "makeup_db": 0.0}
        p, gr, _ = self._design_comp(y, p, stat="p95_db", target=bc["target_gr_p95_db"])
        st = copy.deepcopy(self.state)
        proc = _proc(f"mx.{self.mix_bus}.glue", "compressor", p, "R-11", "light mix-bus glue (1-2 dB)")
        proc["note_values"] = {"release": rel_rec}
        st["mix_chain"].append(proc)
        moves = [self._move(step, "bus_chain_add", bus=self.mix_bus, rules=["R-11", "R-27"],
                            action=T(f"ミックスバスに軽いコンプ（{p['ratio']}:1、GR p95 {gr['p95_db']:.1f} dB、リリース {rel_rec.get('note') or ''} {rel:.0f} ms）",
                                     f"light mix-bus compression ({p['ratio']}:1, GR p95 {gr['p95_db']:.1f} dB, release {rel_rec.get('note') or ''} {rel:.0f} ms)"),
                            measured={"gr_p95_db": _r(gr["p95_db"]), "gr_median_db": _r(gr["median_db"]), "release": rel_rec},
                            alternatives=[T("バス処理なし", "no bus processing")], expected={"gr": _yardstick(gr["p95_db"])},
                            processor=proc)]
        ok = self._try(step, moves, st, kind="template")
        self._mono_low(step)
        v = _vocab("tsubure")
        self._decide("dynamics", step, "R-11, R-27",
                     {"gr_p95_db": _r(gr["p95_db"]), "yardstick": _yardstick(gr["p95_db"])["id"]},
                     T(f"ミックスバスの GR p95 {gr['p95_db']:.1f} dB（目安: 1〜2 dB は軽いまとまり、10 dB 超は「{v['ja']}」）",
                       f"mix-bus GR p95 {gr['p95_db']:.1f} dB (1-2 dB light glue, above 10 dB '{v['en']}')"),
                     moves[0]["action"], moves[0]["alternatives"], {"kept": ok},
                     T(f"{_yardstick(gr['p95_db'])['ja']}（{'採用' if ok else '不採用'}）", f"{_yardstick(gr['p95_db'])['en']} ({'kept' if ok else 'rejected'})"),
                     vocab="tsubure", moves=[m for m in moves if m["status"] == "kept"])
        self._pending = []
        self._end_step(step, "done")

    def _mono_low(self, step: int) -> None:
        """R-09: low-band mono only when S-03 / S-04 fail on the measured mix (corrective)."""
        cons = self.cur["constraints"]
        if cons.get("S-03") != "fail" and cons.get("S-04") != "fail":
            return
        hz = self.rules["mix_bus"]["mono_below_hz"]
        st = copy.deepcopy(self.state)
        mono = _proc(f"mx.{self.mix_bus}.monolow", "stereo", {"mono_below_hz": hz, "width": 1.0, "crossovers_hz": [], "widths": []},
                     "R-09", "low-band mono because S-03 / S-04 failed on the measured mix")
        glue = [i for i, p in enumerate(st["mix_chain"]) if p.get("id") == f"mx.{self.mix_bus}.glue"]
        st["mix_chain"].insert(glue[0] if glue else len(st["mix_chain"]), mono)
        before = list(self.cur["failed"])
        mv = self._move(step, "bus_chain_add", bus=self.mix_bus, rules=["R-09"],
                        action=T(f"ミックスバスの {hz:.0f} Hz 以下をモノに", f"mix bus mono below {hz:.0f} Hz"),
                        measured={"S-03": cons.get("S-03"), "S-04": cons.get("S-04")},
                        alternatives=[T("原因のステム（幅の広い低域）を直す", "fix the stem with the wide low end")],
                        expected={"S-03": "pass", "S-04": "pass"}, processor=mono)
        ok = self._try(step, [mv], st, kind="corrective", target=lambda c: float(len(c["failed"])))
        self._decide("panning", step, "R-09", {"failed_before": before},
                     T(f"モノ合算の検査で不合格 {len(before)} 件（{', '.join(before)}）。前提: モノ再生",
                       f"{len(before)} mono-fold invariants failed ({', '.join(before)}); assumed playback: mono"),
                     mv["action"], mv["alternatives"], {"failed_after": self.cur["failed"]},
                     T(f"不合格 {len(before)} → {len(self.cur['failed'])} 件（{'採用' if ok else '不採用'}）".replace("→", "->"),
                       f"failures {len(before)} -> {len(self.cur['failed'])} ({'kept' if ok else 'rejected'})"),
                     moves=[mv] if ok else [])
        self._pending = []

    # ---------------------------------------------------------------- refine
    def refine(self) -> None:
        """If a later step moved P-10 out of its band, retouch the lead fader (recorded reordering)."""
        if not self.lead or self.cur["p10"].get("value") is None or self.cur["p10"].get("verdict") == "ok":
            return
        lo, hi = self.cur["p10"]["target_db"]
        aim = lo + self.rules["static_balance"]["p10_aim_fraction"] * (hi - lo)
        for i in range(self.max_iter):
            v = self.cur["p10"].get("value")
            if v is None or lo <= v <= hi or not self.allowed(self.lead, "gain"):
                break
            cap = self.rules["static_balance"]["lead_raise_max_db"]
            d = float(np.clip(aim - v, -cap, cap))
            st = copy.deepcopy(self.state)
            old = st["tracks"][self.lead]["gain_db"]
            st["tracks"][self.lead]["gain_db"] = round(old + d, 2)
            mv = self._move(1, "gain", track=self.lead, rules=["R-04", "R-25"],
                            action=T(f"主役のフェーダーを {db_text(d)['ja']}（再調整）", f"lead fader {db_text(d)['en']} (retouch)"),
                            measured={"P-10": _r(v), "target_db": [lo, hi]}, alternatives=[T("このまま", "leave as is")],
                            expected={"P-10_aim_db": _r(aim)},
                            change={"param": "gain_db", "from": old, "to": st["tracks"][self.lead]["gain_db"], "delta_db": round(d, 2),
                                    "sone_ratio": _r(sone_ratio(d), 3)}, refine_iteration=i + 1)
            saved = self.protected.pop("p10_ok", None)
            ok = self._try(1, [mv], st, kind="corrective",
                           target=lambda c: abs(c["p10"]["value"] - aim) if c["p10"].get("value") is not None else None)
            if saved:
                self.protected["p10_ok"] = saved
            self._pending = []
            self.reorderings.append({"step": 1, "after_step": 7, "rule": "R-04", "iteration": i + 1, "kept": ok,
                                     "text": T(f"後段の処理で P-10 が {v:+.1f} dB に動いたため、静的バランス（ステップ 1）に戻って主役を {d:+.1f} dB 調整",
                                               f"later steps moved P-10 to {v:+.1f} dB, so the static balance (step 1) was retouched: lead {d:+.1f} dB")})
            if not ok:
                break

    # ---------------------------------------------------------------- output
    def _interest(self) -> None:
        try:
            from .analysis.perceptual import section_contrast
            y0, _ = self.ev.render(self._initial_ref)
            y1, _ = self.ev.render(self.state)
            c0 = section_contrast(y0, self.sr)
            c1 = section_contrast(y1, self.sr, c0.get("sections"))
            a, b = c0.get("contrast_db"), c1.get("contrast_db")
        except Exception:
            a = b = None
        cfl = self.rules["interest"]["contrast_max_drop_db"]
        if a is not None and b is not None and a - b > cfl:
            self.unresolved.append({"code": "contrast_flattened", "rule": "R-26", "before_db": _r(a), "after_db": _r(b),
                                    "text": T(f"展開のコントラストが {a - b:.1f} dB 減った（目安 {cfl} dB）。人の耳で静と動の差を確認する",
                                              f"section contrast dropped by {a - b:.1f} dB (yardstick {cfl} dB): check the quiet / loud difference by ear")})
        self._decide("interest", 0, "R-26",
                     {"P-20_contrast_db_before": _r(a), "P-20_contrast_db_after": _r(b)},
                     T(f"展開のコントラスト（静と動の Short-term 差）{_f(a)} dB", f"section contrast (quiet vs loud short-term) {_f(a)} dB"),
                     T("「仕掛け」は自動化が最も難しい軸で、人間の指示とリファレンスに依存する。プランナーは展開を平坦にしないことだけを監視した",
                       "Interest is the hardest axis to automate and depends on human direction and references; the planner only watched that the arrangement contrast is not flattened"),
                     [T("ディレイの投げ（音価で）、オートメーション、区間ごとの演出は人間の指示で", "delay throws (note values), automation and per-section effects on human direction")],
                     {"P-20_contrast_db_after": _r(b)},
                     T(f"コントラスト {_f(a)} -> {_f(b)} dB（R-26）", f"contrast {_f(a)} -> {_f(b)} dB (R-26)"),
                     status="depends_on_humans_and_references")

    def _route(self) -> dict:
        origins = set()
        by_id = {a.get("id"): a for a in self.data.get("assets") or []}
        for t in self.tracks.values():
            for c in t.get("clips") or []:
                origins.add((by_id.get(c.get("asset")) or {}).get("origin") or "native_stem")
        need = self.start["p10"].get("verdict") not in (None, "ok") or (self.start["vs_lead"].get("penalty") or 0.0) > 0.0 \
            or (self.start["p22"].get("max_count") or 0) > self.rules["arrangement"]["p22_max_owners"]
        if origins and origins <= {"separated"}:
            if need:
                return {"route": "stem_mix", "rule": "R-21", "rebalance_needed": True, "origins": sorted(origins),
                        "reason": T("分離ステムのみだが、測定が再バランスの必要を示した（P-10 / P-02 / P-22）。ステムミックス経路を提案する",
                                    "only separated stems, but the measurement shows a rebalance is needed (P-10 / P-02 / P-22): the stem-mix route is proposed")}
            return {"route": "full_mix", "rule": "R-21", "rebalance_needed": False, "origins": sorted(origins),
                    "reason": T("分離ステムのみで再バランスの必要が測定されない。フルミックス経路のままが既定",
                                "only separated stems and no measured need to rebalance: the full-mix route stays the default")}
        return {"route": "stem_mix", "rule": "R-21", "rebalance_needed": need, "origins": sorted(origins),
                "reason": T("ステムがあり、ミックス段の結果をマスター入力にする", "stems exist: the mix-stage result is the master input")}

    def _proposal(self) -> dict:
        self._initial_ref = self._initial_state()
        self._interest()
        final = self.cur
        scope = "preview"
        if len(self.excerpts) > 1:
            full = [{"label": "full", "start": 0, "end": self.n_full}]
            fe = _Evaluator(self.project, self.data, self.mix_bus, full, self.resolved, self.sr, self.bpm, self.profile, self.rules)
            yb, _ = fe.render(self._initial_ref)
            fe.before = yb
            final = fe.evaluate(self.state)
            scope = "full_length"
        elif self.excerpts[0]["label"] == "full":
            scope = "full_length"
        changes = self._changes()
        v = final["p10"]
        if v.get("verdict") == "ok":
            self.unresolved = [u for u in self.unresolved if u.get("code") != "p10_off_target"]
        if self.lead and v.get("verdict") not in (None, "ok") and not any(u["code"] == "p10_off_target" for u in self.unresolved):
            self.unresolved.append({"code": "p10_off_target", "value": _r(v.get("value")), "target": v.get("target_db")})
        if (final["vs_lead"].get("penalty") or 0.0) > 0.0:
            self.unresolved.append({"code": "lead_masked", "rule": "R-28", "value": _r(final["vs_lead"].get("value"), 3)})
        if (final["p22"].get("max_count") or 0) > self.rules["arrangement"]["p22_max_owners"]:
            self.unresolved.append({"code": "band_density", "rule": "R-28", "max_owners": final["p22"].get("max_count"),
                                    "see": [a["id"] for a in self.arrangement if a["kind"] == "band_owner_rotation"]})
        if final["gate"].get("status") == "fail":
            self.unresolved.append({"code": "gate_fail", "spec_id": "OF-5",
                                    "failed": sorted(k for k, v in final["gate"]["checks"].items() if v == "fail")})
        failed = sorted(k for k, v in final["constraints"].items() if v == "fail")
        if failed:
            self.unresolved.append({"code": "constraint_fail", "failed": failed})
        schema_needs = [{"field": "mix.decisions / mix.applied", "status": "stored (mix allows additional properties) but not declared in schemas/project.schema.json"},
                        {"field": "variants[].mix", "status": "stored for variant plans (additional properties) but not declared"}]
        if self.variant_id is not None:
            schema_needs.append({"field": "variants[].bus_overrides", "status": "missing: a variant cannot change buses (mix-bus processing skipped)"})
        prop = {
            "stage": STAGE, "variant": self.variant_id, "project_id": self.data.get("id"),
            "lead": self.lead, "genre": self.genre, "profile": self.profile_id,
            "tempo": {"bpm": _r(self.bpm, 3), "source": self.music.get("bpm_source")},
            "sections": self.music.get("sections"),
            "excerpts": [{"label": e["label"], "start_s": _r(e["start"] / self.sr, 3), "end_s": _r(e["end"] / self.sr, 3)}
                         for e in self.excerpts],
            "route": self._route(),
            "restrictions": self.restrictions,
            "balance_only": self.balance_only,
            "order": self.steps,
            "reorderings": self.reorderings,
            "moves": self.moves,
            "changes": changes,
            "arrangement": self.arrangement,
            "measurements": {"start": _snapshot(self.start), "final": _snapshot(final)},
            "objective_evaluation": {"score": final["score"], "total_with_guard": _r(final["total"], 4),
                                     "guard": final["guard"], "terms": final["terms"], "constraints": final["constraints"],
                                     "gate": final["gate"], "scope": scope},
            "decisions": self.decisions,
            "unresolved": self.unresolved,
            "notes": self.notes,
            "objective_resolved": O.summarize_resolved(self.resolved),
            "preview": {"renders": self.ev.renders, "evaluations": len(self.ev.cache), "level_matched": True, "rule": "R-01"},
            "definitions": {"mix_rules": canonical_hash(self.rules), "masking_model": canonical_hash(config.load_knowledge("masking_model"))},
            "schema_needs": schema_needs,
            "operations": ["approve_and_apply", "reject_and_request_alternative"],
            "max_iter": self.max_iter,
        }
        prop["proposal_id"] = "mxp_" + canonical_hash({"variant": self.variant_id, "project": self.data.get("id"),
                                                       "changes": changes, "arr": [a["id"] for a in self.arrangement]})[:12]
        prop["decision_texts"] = decisions_six_elements(prop)
        return _json_safe(prop)

    def _changes(self) -> dict:
        s0 = self._initial_state()
        out: dict = {"tracks": {}, "buses": list(copy.deepcopy(self.state["buses"]).values()),
                     "mix_bus": self.mix_bus, "mix_chain": copy.deepcopy(self.state["mix_chain"])}
        for t in self.tids:
            a, b = s0["tracks"][t], self.state["tracks"][t]
            d: dict = {}
            for k in ("gain_db", "pan", "chain", "sends", "automation"):
                if canonical_hash(a.get(k)) != canonical_hash(b.get(k)):
                    d[k] = copy.deepcopy(b.get(k))
            if d:
                out["tracks"][t] = d
        out["mix_chain_changed"] = canonical_hash(s0["mix_chain"]) != canonical_hash(self.state["mix_chain"])
        return out


# --------------------------------------------------------------------------
# public API


def plan_mix(project, *, variant_id: str | None = None, objective=None, max_iter: int = 4, excerpt: bool = True) -> dict:
    """Mix-stage proposal (R-31) in the fixed order of SPEC 6.5.1.

    Returns {stage: "mix", proposal_id, variant, lead, route (R-21), restrictions (R-22),
    order[7 steps with measured_after], reorderings, moves[{id, step, kind, track/bus, rules,
    action, measured, alternatives, expected, status, result}], changes{tracks, buses, mix_chain},
    arrangement[suggestions], measurements{start, final}, objective_evaluation, decisions
    (six elements, structured), decision_texts (ja/en), unresolved, operations}.
    Nothing is written to the project.
    """
    return _Planner(project, variant_id=variant_id, objective=objective, max_iter=max_iter, excerpt=excerpt).run()


def save_mix_proposal(project, proposal: dict, **fields) -> str:
    """Write the proposal (plus ``fields``) to cache/proposals/<proposal_id>.json; returns the relative path."""
    pid = proposal.get("proposal_id")
    if not isinstance(pid, str) or not pid:
        raise InputError("the proposal has no proposal_id")
    path = Path(project.root) / PROPOSAL_DIR / f"{pid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = dict(proposal)
    stored.update(fields)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_json_safe(stored), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return PROPOSAL_DIR + f"/{pid}.json"


def _strip_owned(items: list) -> list:
    return [x for x in items if not (isinstance(x, dict) and x.get("owner") == OWNER)]


def _restriction_record(r: dict) -> dict:
    return {"operations": list(r["operations"]), "rule": r.get("rule") or "R-22",
            "reason": (r.get("reason") or {}).get("en", "") if isinstance(r.get("reason"), dict) else str(r.get("reason") or "")}


def apply_mix_plan(project, proposal: dict, *, actor: str) -> None:
    """Approve and apply a mix proposal (R-31): one journaled patch (op ``mix_apply``).

    Without a variant: track gains / pans / chains / sends / automation, the
    planner's FX bus and the mix-bus chain are written to the project; R-22
    restrictions are recorded on the tracks; ``mix.applied`` / ``mix.decisions``
    / ``mix.evaluation`` keep the decision record. With a variant: the track
    changes go to ``variants[].track_overrides`` (SPEC 9.4), the FX bus is added
    at project level (only the variant's sends reach it) and the record goes to
    ``variants[].mix``. The proposal file under cache/proposals/ is updated.
    """
    from . import jsonpatch
    if not isinstance(proposal, dict) or proposal.get("stage") != STAGE:
        raise InputError("not a mix-stage proposal")
    ch = proposal.get("changes") or {}
    data = copy.deepcopy(project.data)
    vid = proposal.get("variant")
    tracks = {t.get("id"): t for t in data.get("tracks") or []}
    for tid in (ch.get("tracks") or {}):
        if tid not in tracks:
            raise InputError(f"the proposal changes unknown track '{tid}'", details={"valid": sorted(tracks)})
    buses = [b for b in data.get("buses") or [] if b.get("owner") != OWNER]
    known = {b.get("id") for b in buses}
    for b in ch.get("buses") or []:
        if b.get("id") in known:
            raise InputError(f"bus id '{b.get('id')}' already exists in the project")
    mix_id = ch.get("mix_bus")
    idx = next((i for i, b in enumerate(buses) if b.get("id") == mix_id), None)
    if idx is None:
        raise InputError(f"mix bus '{mix_id}' not found")
    buses[idx:idx] = copy.deepcopy(ch.get("buses") or [])
    data["buses"] = buses
    record = {"stage": STAGE, "proposal_id": proposal.get("proposal_id"), "lead": proposal.get("lead"),
              "steps": [{"n": s["n"], "id": s["id"], "status": s["status"], "kept": s.get("kept", [])}
                        for s in proposal.get("order") or []],
              "reorderings": proposal.get("reorderings") or [],
              "arrangement_suggestions": [{"id": a["id"], "kind": a["kind"], "status": a["status"]}
                                          for a in proposal.get("arrangement") or []],
              "route": proposal.get("route"), "restrictions": proposal.get("restrictions") or {}}
    ev = proposal.get("objective_evaluation") or {}
    evaluation = {"proposal_id": proposal.get("proposal_id"), "score": ev.get("score"),
                  "total_with_guard": ev.get("total_with_guard"), "guard": ev.get("guard"), "terms": ev.get("terms"),
                  "constraints": ev.get("constraints"), "gate": ev.get("gate"), "scope": ev.get("scope"),
                  "measurements": proposal.get("measurements")}
    if vid is None:
        # earlier planner-owned items are replaced by this proposal (the plan started without them)
        for t in tracks.values():
            if t.get("chain"):
                t["chain"] = _strip_owned(t["chain"])
            if t.get("sends"):
                t["sends"] = _strip_owned(t["sends"])
            if isinstance(t.get("automation"), dict) and t["automation"].get("owner") == OWNER:
                t.pop("automation")
        mbus = next(b for b in data["buses"] if b.get("id") == mix_id)
        mbus["chain"] = _strip_owned(mbus.get("chain") or [])
        for tid, d in (ch.get("tracks") or {}).items():
            t = tracks[tid]
            for k, v in d.items():
                if k == "automation" and not v:
                    t.pop("automation", None)
                elif k == "pan":
                    t["pan"] = {**(t.get("pan") or {}), **v}
                else:
                    t[k] = copy.deepcopy(v)
        mbus["chain"] = copy.deepcopy(ch.get("mix_chain") or [])  # the full final chain (user steps kept)
        for tid, r in (proposal.get("restrictions") or {}).items():
            if tid in tracks and not tracks[tid].get("restrictions") and r.get("source") in ("separated", "baked"):
                tracks[tid]["restrictions"] = _restriction_record(r)
        mix = data.setdefault("mix", {"pan_law_center_db": -3.0})
        mix["applied"] = record
        mix["decisions"] = copy.deepcopy(proposal.get("decisions") or {})
        mix["evaluation"] = evaluation
    else:
        v = next((v for v in data.get("variants") or [] if v.get("id") == vid), None)
        if v is None:
            raise InputError(f"unknown variant '{vid}'")
        tov = v.setdefault("track_overrides", {})
        for o in tov.values():
            for k in ("chain", "sends"):
                if isinstance(o.get(k), list):
                    o[k] = _strip_owned(o[k])
            if isinstance(o.get("automation"), dict) and o["automation"].get("owner") == OWNER:
                o["automation"] = None
        for tid, d in (ch.get("tracks") or {}).items():
            o = tov.setdefault(tid, {})
            for k, val in d.items():
                o[k] = copy.deepcopy(val) if (val or k != "automation") else None
        v["mix"] = {"applied": record, "decisions": copy.deepcopy(proposal.get("decisions") or {}),
                    "evaluation": evaluation}
    ops = jsonpatch.diff(project.data, data)
    if ops:
        project.apply_patch(ops, actor=actor, reason=f"mix plan {proposal.get('proposal_id')}", op="mix_apply")
    try:
        from . import journal
        seq = journal.last_seq(project.root)
    except Exception:
        seq = None
    save_mix_proposal(project, proposal, status="applied", applied={"actor": actor, "journal_seq": seq})


# --------------------------------------------------------------------------
# decision texts (SPEC 6.8 section 4; 6.8.1)


def _alts(alts: list[dict], lang: str) -> str:
    return "; ".join(a.get(lang, "") for a in alts or []) or ("なし" if lang == "ja" else "none")


def decisions_six_elements(proposal: dict) -> dict:
    """Decision texts per Mix Report element, in ja and en.

    Returns {balance, pan, frequency, depth, dynamics, interest}, each
    {"ja": [lines], "en": [lines]}. Every line reads
    "measured -> rule -> action -> alternatives -> result"; level changes carry
    their sone ratio (R-25); vocabulary words come with the measured numbers
    (SPEC 6.8.1). "interest" states that it depends on human direction and
    references.
    """
    dec = proposal.get("decisions") or {}
    out: dict = {}
    lab = {"ja": ("測定", "規則", "操作", "代替案", "結果"), "en": ("measured", "rule", "action", "alternatives", "result")}
    for el in TEXT_ELEMENTS:
        recs = dec.get(_TEXT_TO_RECORD[el]) or []
        lines = {"ja": [], "en": []}
        for r in recs:
            for lang in ("ja", "en"):
                m, ru, ac, al, re_ = lab[lang]
                mt = (r.get("measured_text") or {}).get(lang) or json.dumps(r.get("measured"), ensure_ascii=False)
                rt = (r.get("result_text") or {}).get(lang) or json.dumps(r.get("result"), ensure_ascii=False)
                parts = [mt, r.get("rule") or "-", (r.get("action") or {}).get(lang, ""),
                         _alts(r.get("alternatives"), lang), rt]
                mt, rule, act, alts, rt = (str(x).replace("→", "->") for x in parts)  # the arrow is the separator
                lines[lang].append(f"{m}: {mt} → {ru}: {rule} → {ac}: {act} → {al}: {alts} → {re_}: {rt}")
        if el == "interest" and not lines["ja"]:
            lines = {"ja": ["測定: 0 件 → 規則: R-26 → 操作: 「仕掛け」は人間の指示とリファレンスに依存する → 代替案: なし → 結果: 0 件"],
                     "en": ["measured: 0 items → rule: R-26 → action: interest depends on human direction and references → alternatives: none → result: 0 items"]}
        if not lines["ja"]:
            lines = {"ja": [f"測定: 0 件 → 規則: R-04 → 操作: 変更なし → 代替案: なし → 結果: 0 件"],
                     "en": [f"measured: 0 items → rule: R-04 → action: no change → alternatives: none → result: 0 items"]}
        out[el] = lines
    return out


__all__ = ["plan_mix", "apply_mix_plan", "decisions_six_elements", "save_mix_proposal", "mix_rules",
           "sone_ratio", "db_text", "STAGE", "STEP_IDS"]
