"""Calibration of a direction's quantities inside its declared ranges (closed loop).

A move may give a parameter as a range ``[lo, hi]`` with a ``select`` (mid / min /
max). v0 ``apply`` resolved every range to its ``select`` without looking at what
came out, so a claim could stay short while the direction still had room inside
its own ranges (and every direction in v0 delegates "範囲内の量の選択" to this
layer). This module closes that loop and nothing more:

- it only chooses values **inside the declared ranges** (the ``select`` value is
  the starting point; a parameter without a range is never changed);
- the claims are predicted at the mix stage: the project with the moves is
  rendered (``render_mix``, in memory, nothing is written) and every observation
  is compared with the floor mix after integrated-loudness matching, exactly as
  ``direction check`` does on the master. The master stage of a delivery profile
  is a loudness gain and a true-peak limiter; ``check`` measures the real master
  afterwards, so a prediction error can only show up there, never be hidden;
- a candidate is acceptable only if no measurable claim or safeguard gets worse:
  a met one stays met (with ``MARGIN``), an unmet one does not move away from
  its target; among acceptable candidates the one meeting the most primary
  claims (then claims, then safeguards, then the smallest primary shortfall)
  wins, and the step from ``select`` is then shortened as far as the same claims
  stay met (the direction's ``select`` stays the anchor);
- gates, thresholds, profiles and the master chain are not read or written here.

Knobs and the "stronger" end of a range: a move pushes its quantity further the
further its parameter is from the no-op value (gain 0 dB, width 1, position 0,
a quieter send, a lower high-pass / higher low-pass, less drive / mix /
feedback). Parameters without such an order (an EQ centre frequency, a delay
time) keep their ``select`` value. A move whose own safeguard fails is moved
toward its no-op end; moves that ``expect`` an unmet claim (first) or all other
moves (second candidate) are moved toward their stronger end.
"""

from __future__ import annotations

import copy
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import query as Q

MARGIN = 0.02          # dB (or coefficient) kept between a predicted value and its threshold
WORSE_EPS = 0.01       # an unmet item may not move further from its target than this
STRONG_HI = ("level_db", "drive_db", "mix", "feedback")


def _is_range(v: Any) -> bool:
    return (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                         for x in v))


def strong_end(op: str, ptype: str | None, key: str, lo: float, hi: float, params: dict) -> float | None:
    """The end of [lo, hi] where the move acts most; None when the parameter has no such order."""
    if op == "duck":
        # a deeper duck acts more; its other parameters (times, trigger) have no such order
        return hi if key == "depth_db" else None
    if key == "delta_db" or (key == "gain_db" and op != "gain"):
        return lo if abs(lo) > abs(hi) else (hi if abs(hi) > abs(lo) else None)
    if key == "width":
        return lo if abs(lo - 1.0) > abs(hi - 1.0) else (hi if abs(hi - 1.0) > abs(lo - 1.0) else None)
    if key == "position":
        return lo if abs(lo) > abs(hi) else (hi if abs(hi) > abs(lo) else None)
    if key in STRONG_HI:
        return hi
    if key == "freq_hz" and ptype == "filter":
        kind = params.get("kind")
        return hi if kind == "hpf" else (lo if kind == "lpf" else None)
    return None


def knobs(doc: dict, proj=None) -> list[dict]:
    """Every range parameter of the direction: id, move, key, range, select value, strong / weak end."""
    from .direction import _array_param_ids, EDIT_OPS, resolve_params
    out = []
    items = proj.floor_items() if proj is not None else {}
    tracks = proj.tracks() if proj is not None else {}
    buses = proj.buses() if proj is not None else {}

    def add(m: dict, params: dict, ptype: str | None, prefix: str):
        start, _ = resolve_params(m, params, ptype=ptype)
        for k, v in params.items():
            if not _is_range(v):
                continue
            if k in _array_param_ids(ptype):   # declared list/curve values are never ranges
                continue
            lo, hi = float(min(v)), float(max(v))
            st = strong_end(m.get("op"), ptype, k, lo, hi, {**params, **start})
            sel = m.get("select")
            sel = sel.get(k, "mid") if isinstance(sel, dict) else (sel or "mid")
            out.append({"id": f"{prefix}.{k}", "move": m["id"], "key": k, "range": [lo, hi], "select": sel,
                        "start": float(start[k]), "strong": st,
                        "weak": None if st is None else (hi if st == lo else lo)})

    for m in doc["block"].get("moves") or []:
        op = m.get("op")
        params = m.get("params") or {}
        if op in EDIT_OPS:   # edit parameters are never calibration knobs (§1.3)
            continue
        if op == "place":    # place parameters keep their select value (FBREVIEW FR-5)
            continue
        if op == "bus_add":
            for i, c in enumerate(params.get("chain") or []):
                add(m, c.get("params") or {}, c.get("type") or c.get("processor"), f"{m['id']}.chain{i}")
            continue
        ptype = m.get("processor")
        if op == "chain_param" and m.get("replaces") in items:
            kind, hid = items[m["replaces"]]
            holder = (tracks if kind == "track" else buses).get(hid) or {}
            it = next((x for x in holder.get("chain") or [] if x.get("id") == m["replaces"]), None)
            if it is not None:
                ptype = it.get("type")
                params = {**{k: v for k, v in (it.get("params") or {}).items() if k not in params}, **params}
        add(m, params, ptype, m["id"])
    return out


def data_with_changes(data: dict, changes: dict) -> dict:
    """Project data with a mix proposal's changes, as ``apply_mix_plan`` writes them (no variant), in memory."""
    from mankomix.core import mixplan
    out = copy.deepcopy(data)
    tracks = {t.get("id"): t for t in out.get("tracks") or []}
    buses = [b for b in out.get("buses") or [] if b.get("owner") != mixplan.OWNER]
    mix_id = changes.get("mix_bus")
    idx = next(i for i, b in enumerate(buses) if b.get("id") == mix_id)
    buses[idx:idx] = copy.deepcopy(changes.get("buses") or [])
    out["buses"] = buses
    for t in tracks.values():
        if t.get("chain"):
            t["chain"] = mixplan._strip_owned(t["chain"])
        if t.get("sends"):
            t["sends"] = mixplan._strip_owned(t["sends"])
        if isinstance(t.get("automation"), dict) and t["automation"].get("owner") == mixplan.OWNER:
            t.pop("automation")
    mbus = next(b for b in out["buses"] if b.get("id") == mix_id)
    for tid, d in (changes.get("tracks") or {}).items():
        t = tracks[tid]
        for k, v in d.items():
            if k == "automation" and not v:
                t.pop("automation", None)
            elif k == "pan":
                t["pan"] = {**(t.get("pan") or {}), **v}
            else:
                t[k] = copy.deepcopy(v)
    mbus["chain"] = copy.deepcopy(changes.get("mix_chain") or [])
    return out


def _slack(q: dict, delta: float | None) -> float | None:
    """>= 0: the item is met by that much; < 0: short by that much (same unit as the quantity)."""
    if delta is None:
        return None
    d = q.get("direction")
    if d == "up":
        return delta - float(q.get("min_delta", 0.0))
    if d == "down":
        return -delta - float(q.get("min_delta", 0.0))
    tol = float(q.get("tolerance", 0.0))
    if q.get("worse") == "up":
        return tol - delta
    if q.get("worse") == "down":
        return tol + delta
    return tol - abs(delta)


def _scale(q: dict) -> float:
    v = float(q.get("min_delta", q.get("tolerance", 0.0)) or 0.0)
    return abs(v) if abs(v) > 1e-9 else 1.0


class _Predictor:
    def __init__(self, root: Path, doc: dict, progress: Callable[[str], None]):
        from mankomix.core.project import Project
        from .direction import _Project
        self.root, self.doc, self.progress = root, doc, progress
        self.proj = _Project(root)
        self.pobj = Project.open(root)
        self.vid = (self.proj.variant() or {}).get("id")
        self.sections = self.proj.sections()
        b = doc["block"]
        self.obs = [o for o in b.get("observations") or []
                    if o.get("target", "master") == "master" and o.get("primitive") in Q.PRIMITIVES]
        self.renders = 0
        x, self.sr = self._render(self.pobj.data, "floor")
        self.floor_lufs = Q.integrated_lufs(x, self.sr)
        self.floor_vals = {o["id"]: Q.observe(x, self.sr, o, sections=self.sections)["value"] for o in self.obs}

    def _render(self, data: dict, label: str) -> tuple[np.ndarray, int]:
        from mankomix.core import mixrender
        t0 = time.time()
        p = copy.copy(self.pobj)
        p.data = data
        x, sr, _ = mixrender.render_mix(p, variant_id=self.vid, measure=False)
        self.renders += 1
        self.progress(f"calibrate: render {self.renders} ({label}) {time.time() - t0:.1f} s")
        return x, sr

    def deltas(self, sel: dict, label: str) -> dict:
        from .direction import build_proposal
        prop, _, _ = build_proposal(self.proj, self.doc, sel=sel)
        x, _ = self._render(data_with_changes(self.proj.data, prop["changes"]), label)
        g = self.floor_lufs - Q.integrated_lufs(x, self.sr)
        return {o["id"]: round(Q.observe(x, self.sr, o, sections=self.sections, gain_db=g)["value"]
                               - self.floor_vals[o["id"]], 4) for o in self.obs}


def _items(doc: dict) -> list[dict]:
    """Every measurable claim and safeguard (obs: quantities on the master)."""
    b = doc["block"]
    # track targets and the context primitives (stemobs) are not read: master signals only
    obs = {o.get("id"): o for o in b.get("observations") or []
           if o.get("target", "master") == "master" and o.get("primitive") in Q.PRIMITIVES}
    out = []
    for c in b.get("claims") or []:
        qty = str(c.get("quantity", ""))
        if qty.startswith("obs:") and qty[4:] in obs:
            out.append({"key": f"claim:{c.get('id')}", "kind": "claim", "primary": bool(c.get("primary")),
                        "obs": qty[4:], "q": c})
    for m in b.get("moves") or []:
        for i, q in enumerate(m.get("safeguard") or []):
            qty = str(q.get("quantity", ""))
            if qty.startswith("obs:") and qty[4:] in obs:
                out.append({"key": f"safeguard:{m.get('id')}:{i}", "kind": "safeguard", "move": m.get("id"),
                            "primary": False, "obs": qty[4:], "q": q})
    return out


def _judge(items: list[dict], deltas: dict) -> dict:
    return {it["key"]: _slack(it["q"], deltas.get(it["obs"])) for it in items}


def _met(s: float | None) -> bool:
    return s is not None and s >= MARGIN


def _score(items: list[dict], sl: dict) -> tuple:
    prim = [it for it in items if it["kind"] == "claim" and it["primary"]]
    claims = [it for it in items if it["kind"] == "claim"]
    safe = [it for it in items if it["kind"] == "safeguard"]
    short = sum(min(sl[it["key"]] - MARGIN, 0.0) / _scale(it["q"]) for it in prim if sl[it["key"]] is not None)
    return (sum(_met(sl[i["key"]]) for i in prim), sum(_met(sl[i["key"]]) for i in claims),
            sum(_met(sl[i["key"]]) for i in safe), round(short, 6))


def _feasible(items: list[dict], s0: dict, s1: dict) -> list[str]:
    """Items that got worse (empty: acceptable)."""
    bad = []
    for it in items:
        a, b = s0[it["key"]], s1[it["key"]]
        if a is None or b is None:
            continue
        if _met(a) and not _met(b):
            bad.append(it["key"])
        elif not _met(a) and b < a - WORSE_EPS:
            bad.append(it["key"])
    return bad


def _blend(ks: list[dict], start: dict, target: dict, t: float) -> dict:
    out = {}
    for k in ks:
        a, b = start[k["id"]], target[k["id"]]
        v = a + t * (b - a)
        lo, hi = k["range"]
        out[k["id"]] = round(min(hi, max(lo, v)), 4)
    return out


def calibrate(root: str | Path, doc: dict, *, progress: Callable[[str], None] | None = None) -> dict:
    """Choose the range values of ``doc`` for the floor project at ``root`` (before apply). See the module doc."""
    root = Path(root)
    progress = progress or (lambda s: print(s, file=sys.stderr, flush=True))
    from .direction import _Project
    ks = knobs(doc, _Project(root))
    items = _items(doc)
    rec: dict = {"method": "closed-loop selection inside the declared ranges; prediction = mix bus rendered in "
                           "memory, integrated-loudness matched to the floor mix (direction check then measures "
                           "the real master)",
                 "margin": MARGIN, "knobs": ks, "items": [it["key"] for it in items], "evaluations": []}
    start = {k["id"]: k["start"] for k in ks}
    if not ks or not items:
        rec.update({"selection": start, "chosen": "select", "renders": 0,
                    "reason": "no range parameter" if not ks else "no measurable claim or safeguard"})
        return rec
    if any(m.get("op") == "cleanup_override" for m in doc["block"].get("moves") or []):
        rec.update({"selection": start, "chosen": "select", "renders": 0,
                    "reason": "cleanup_override present: the prediction would need the cleanup stage (not calibrated)"})
        return rec
    pr = _Predictor(root, doc, progress)
    evals: dict[str, dict] = {}

    def evaluate(label: str, sel: dict) -> dict:
        d = pr.deltas(sel, label)
        sl = _judge(items, d)
        e = {"label": label, "selection": sel, "deltas": d, "slack": sl, "score": _score(items, sl)}
        evals[label] = e
        rec["evaluations"].append(e)
        return e

    e0 = evaluate("select", start)
    s0 = e0["slack"]
    b = doc["block"]
    unmet_q = {}   # quantity -> direction, for unmet up/down claims
    for it in items:
        if it["kind"] == "claim" and not _met(s0[it["key"]]) and it["q"].get("direction") in ("up", "down"):
            unmet_q[it["q"]["quantity"]] = it["q"]["direction"]
    shrink = {it["move"] for it in items if it["kind"] == "safeguard" and s0[it["key"]] is not None
              and not _met(s0[it["key"]])}
    expect_moves = set()
    for m in b.get("moves") or []:
        if m.get("id") in shrink:
            continue
        if any(unmet_q.get(q.get("quantity")) == q.get("direction") for q in m.get("expect") or []):
            expect_moves.add(m.get("id"))
    others = {m.get("id") for m in b.get("moves") or []} - shrink
    movable = [k for k in ks if k["strong"] is not None]

    def target(strong_moves: set, weak_moves: set) -> dict:
        t = dict(start)
        for k in movable:
            if k["move"] in weak_moves:
                t[k["id"]] = k["weak"]
            elif k["move"] in strong_moves:
                t[k["id"]] = k["strong"]
        return t

    cands = []
    if unmet_q and expect_moves:
        cands.append(("expect_strong", target(expect_moves, shrink)))
    if unmet_q:
        cands.append(("all_strong", target(others, shrink)))
    if shrink:
        cands.append(("safeguard_shrink", target(set(), shrink)))
    seen = {tuple(sorted(start.items()))}
    for label, sel in cands:
        key = tuple(sorted(sel.items()))
        if key in seen:
            continue
        seen.add(key)
        e = evaluate(label, sel)
        e["worse"] = _feasible(items, s0, e["slack"])
    best = e0
    for e in rec["evaluations"][1:]:
        if not e.get("worse") and e["score"] > best["score"]:
            best = e
    chosen = best
    if best is not e0:
        # shorten the step from select as long as the score does not drop (the same items stay met
        # and no primary claim falls further short); an unreached claim keeps the full step
        lo_t, hi_t = 0.0, 1.0
        for _ in range(2):
            t = round((lo_t + hi_t) / 2.0, 4)
            sel = _blend(ks, start, best["selection"], t)
            e = evaluate(f"{best['label']}@{t}", sel)
            e["worse"] = _feasible(items, s0, e["slack"])
            if not e["worse"] and e["score"] >= best["score"]:
                chosen, hi_t = e, t
            else:
                lo_t = t
    unreached = []
    for it in items:
        if it["kind"] == "claim" and not _met(chosen["slack"][it["key"]]):
            unreached.append({"claim": it["key"].split(":", 1)[1], "predicted_delta": chosen["deltas"][it["obs"]],
                              "slack": chosen["slack"][it["key"]]})
    rec.update({"selection": chosen["selection"], "chosen": chosen["label"], "renders": pr.renders,
                "candidates": {"expect_moves": sorted(expect_moves), "shrink_moves": sorted(shrink)},
                "unreached_in_ranges": unreached,
                "changed": {k["id"]: {"select": k["start"], "chosen": chosen["selection"][k["id"]], "range": k["range"]}
                            for k in ks if abs(chosen["selection"][k["id"]] - k["start"]) > 1e-9}})
    for e in rec["evaluations"]:
        e["score"] = list(e["score"])
    return rec
