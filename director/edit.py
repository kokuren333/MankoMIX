"""The edit (declutter) stage of a direction: ``edit_trim`` / ``edit_gate`` (UPGRADE2 §1, U-19 to U-21).

A director may choose to silence the parts of a stem that are not the song (noise after the playing
has ended, leakage between phrases) before the chain and sends amplify them. Nothing here is a floor
default: this module is imported only when a direction carries an edit op, or by ``direction edit``.

- detection and the safeguards read the raw asset (the track's ``cleanup`` removed, in memory) through
  the clip layout, before the chain and the fader (``render_track(apply_chain=False, apply_fader=False)``);
  a ``cleanup_override`` therefore never changes what is found
- the safeguards EG-1 to EG-5 are fixed constants; no direction parameter loosens them
- the cut is the core's range mute (clips split at the edges, the inside muted; journaled) plus fades
  inside the kept clips (one ``patch``); the raw asset, the cleaned cache and the timeline length are
  untouched and no audio file is written
- every planned region, accepted or refused, goes to ``directions/dir_<id>.edits.json`` (the ledger);
  ``revert`` restores the muted flags and fades from it (one ``patch``), which renders bit-identically
  to the state before the edit (split points without fades are sample-exact)
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

EDIT_OPS = ("edit_trim", "edit_gate")

# detection (U-19 / §1.3; fixed)
FRAME_MS = 50.0
HOP_MS = 10.0
ACTIVE_FLOOR_DBFS = -70.0      # frames above this define the activity level
ACTIVE_PERCENTILE = 95.0
HEAD_GUARD_MS = 20.0           # edit_trim head: stop this long before the first content frame
TRIM_MIN_MS = 100.0            # edit_trim: shorter candidates are dropped
_EPS = 1e-20                   # -200 dBFS floor of a frame level

# safeguards (U-20; fixed, not writable from a direction)
GUARDS = {"EG-1": -36.0, "EG-2": -40.0, "EG-3": 0.10, "EG-4": -40.0, "EG-5": 48}
EG3_MIN_DBFS = -60.0           # EG-3 applies to regions whose loudest frame exceeds this
EG3_MIN_SAMPLES = 4096
EG3_BAND_HZ = (200.0, 8000.0)

# parameters: id -> (ops, low, high, default); "side" is an enumeration
PARAMS: dict[str, tuple] = {
    "threshold_db": (EDIT_OPS, -72.0, -36.0, -60.0),
    "hold_ms": (EDIT_OPS, 50.0, 2000.0, 400.0),
    "fade_ms": (EDIT_OPS, 2.0, 200.0, 20.0),
    "lead_ms": (("edit_gate",), 0.0, 100.0, 10.0),
    "min_gap_ms": (("edit_gate",), 200.0, 10000.0, 1000.0),
}
SIDES = ("tail", "head", "both")
LEDGER_SUFFIX = ".edits.json"


class EditError(ValueError):
    pass


# ---------------------------------------------------------------------------
# parameters
# ---------------------------------------------------------------------------

def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check_params(op: str, params: dict, where: str, err) -> None:
    """Shape and ranges of an edit move's params (``err(where, code, message)`` per problem)."""
    if not isinstance(params, dict):
        err(where, "bad_value", f"{op}: params must be an object")
        return
    for k, v in params.items():
        if k == "side":
            if op != "edit_trim":
                err(where, "bad_value", f"{op}: unknown parameter 'side' (edit_trim only)")
            elif v not in SIDES:
                err(where, "bad_value", f"side must be one of {', '.join(SIDES)}")
            continue
        spec = PARAMS.get(k)
        if spec is None or op not in spec[0]:
            err(where, "bad_value", f"{op}: unknown parameter '{k}'")
            continue
        _, lo, hi, _ = spec
        vals = v if (isinstance(v, list) and len(v) == 2) else [v]
        if not all(_num(x) for x in vals):
            err(where, "bad_value", f"{k} must be a number or a range [low, high]")
            continue
        for x in vals:
            if not lo <= float(x) <= hi:
                err(where, "param_range", f"{k} {x} outside [{lo:g}, {hi:g}]")
                break


def full_params(op: str, resolved: dict) -> dict:
    """Resolved params (ranges already reduced to one value) with the defaults filled in."""
    out: dict = {}
    for k, (ops, _, _, d) in PARAMS.items():
        if op in ops:
            out[k] = float(resolved.get(k, d))
    if op == "edit_trim":
        out["side"] = str(resolved.get("side", "tail"))
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------
# the raw signal and its frames
# ---------------------------------------------------------------------------

class _RawView:
    """Project stand-in whose data is a copy (rendering only)."""

    def __init__(self, project, data: dict):
        self._project = project
        self.data = data

    def __getattr__(self, name):
        return getattr(self._project, name)


def raw_track(root: str | Path, track_id: str) -> tuple[np.ndarray, int, dict]:
    """(signal, rate, data) of a track's clip layout over the raw asset: cleanup removed (in memory),
    no chain, no fader. ``data`` is the project data as read (not the copy)."""
    from mankomix.core import mixrender as mr
    from mankomix.core.project import Project
    proj = Project.open(Path(root))
    data = copy.deepcopy(proj.data)
    track = next((t for t in data.get("tracks") or [] if t.get("id") == track_id), None)
    if track is None:
        raise EditError(f"unknown track '{track_id}'")
    track.pop("cleanup", None)
    x, sr, _ = mr.render_track(_RawView(proj, data), track_id, apply_chain=False, apply_fader=False)
    return x, int(sr), proj.data


def _power(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        return x * x
    return np.mean(x * x, axis=1)


def frame_levels(pw: np.ndarray, sr: int) -> tuple[np.ndarray, int, int]:
    """(level dBFS per frame, hop, window) in samples; frame k covers [k*hop, k*hop + window)."""
    hop = max(1, int(round(HOP_MS * 1e-3 * sr)))
    win = max(1, int(round(FRAME_MS * 1e-3 * sr)))
    n = pw.shape[0]
    if n == 0:
        return np.zeros(0), hop, win
    c = np.concatenate([[0.0], np.cumsum(pw)])
    k = 1 + max(0, -(-(n - win) // hop))
    s = np.arange(k) * hop
    e = np.minimum(s + win, n)
    mean = (c[e] - c[s]) / np.maximum(e - s, 1)
    return 10.0 * np.log10(np.maximum(mean, 0.0) + _EPS), hop, win


def _merge(iv: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _intersect(iv: list[tuple[int, int]], cover: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out = []
    for a, b in iv:
        for c, d in cover:
            lo, hi = max(a, c), min(b, d)
            if lo < hi:
                out.append((lo, hi))
    return sorted(out)


def _clip_cover(data: dict, track_id: str, rate: int) -> list[tuple[int, int]]:
    """Timeline spans of the track's unmuted clips (merged)."""
    from mankomix.core import mixrender as mr
    track = next((t for t in data.get("tracks") or [] if t.get("id") == track_id), {})
    iv = []
    for c in track.get("clips") or []:
        if c.get("muted"):
            continue
        ts = int(c.get("timeline_start", 0) or 0)
        ln = int(mr.clip_length(data, c, rate))
        if ln > 0:
            iv.append((ts, ts + ln))
    return _merge(iv)


def _flatness(seg: np.ndarray, sr: int) -> float:
    """Spectral flatness (geometric / arithmetic mean) of the mono sum's averaged power spectrum
    (Welch, the method of ``refstudy._welch``) between 200 Hz and 8 kHz."""
    from scipy.signal import welch
    mono = seg.mean(axis=1) if seg.ndim == 2 else seg
    f, p = welch(mono, fs=sr, nperseg=min(8192, mono.size))
    m = (f >= EG3_BAND_HZ[0]) & (f <= min(EG3_BAND_HZ[1], sr / 2.0))
    p = np.asarray(p[m], dtype=np.float64)
    am = float(np.mean(p)) if p.size else 0.0
    if am <= 0.0:
        return 0.0
    gm = float(np.exp(np.mean(np.log(np.maximum(p, am * 1e-30)))))
    return gm / am


def _r(v: float | None, nd: int = 2) -> float | None:
    if v is None or not math.isfinite(v):
        return None
    return round(float(v), nd)


def _db(ratio: float) -> float:
    return 10.0 * math.log10(max(ratio, 1e-30))


# ---------------------------------------------------------------------------
# planning (shared by scan and apply)
# ---------------------------------------------------------------------------

def _max_level(lv: np.ndarray, hop: int, win: int, n: int, a: int, b: int) -> float:
    """Loudest frame of the samples [a, b) (a region with its fade margins): the frames whose window
    lies inside [a, b). A frame that only overlaps the edge would read the neighbouring phrase (the
    window is longer than lead + fade), so it is not taken; when no whole frame fits, the frames that
    overlap are used."""
    k = np.arange(lv.shape[0])
    s = k * hop
    e = np.minimum(s + win, n)
    inside = (s >= a) & (e <= b)
    if not inside.any():
        inside = (s < b) & (e > a)
    return float(np.max(lv[inside])) if inside.any() else -200.0


def plan_signal(x: np.ndarray, sr: int, op: str, params: dict, *, window: tuple[int, int] | None = None,
                cover: list[tuple[int, int]] | None = None) -> dict:
    """Candidate regions of ``op`` on signal ``x`` and the safeguard verdicts. ``params``: full params
    (``full_params``); ``window``: the section range in samples; ``cover``: the unmuted clip spans
    (regions outside them are already silent and are not planned)."""
    if op not in EDIT_OPS:
        raise EditError(f"unknown edit op '{op}'")
    pw = _power(x)
    n = int(pw.shape[0])
    lv, hop, win = frame_levels(pw, sr)
    ms = lambda v: int(round(float(v) * 1e-3 * sr))  # noqa: E731
    total_e = float(np.sum(pw))
    plan: dict = {"active_db": None, "track_energy_db": _r(_db(total_e / max(n, 1))) if total_e > 0 else None,
                  "regions": [], "refused": [], "removed_energy_rel_db": None, "status": "no_regions"}
    act = lv > ACTIVE_FLOOR_DBFS
    if not act.any():
        plan["note"] = f"silent track (no frame above {ACTIVE_FLOOR_DBFS:g} dBFS): no region"
        return plan
    active = float(np.percentile(lv[act], ACTIVE_PERCENTILE))
    plan["active_db"] = _r(active)
    content = np.flatnonzero(lv >= active + float(params["threshold_db"]))
    fade = ms(params["fade_ms"])
    # candidates
    cand: list[tuple[int, int]] = []
    if op == "edit_gate":
        runs = []
        start = prev = int(content[0])
        for k in content[1:]:
            k = int(k)
            if k != prev + 1:
                runs.append((start, prev))
                start = k
            prev = k
        runs.append((start, prev))
        lead, hold = ms(params["lead_ms"]), ms(params["hold_ms"])
        keep = _merge([(max(0, a * hop - lead), min(n, b * hop + win + hold)) for a, b in runs])
        pos = 0
        for a, b in keep + [(n, n)]:
            if a > pos:
                cand.append((pos, a))
            pos = max(pos, b)
        min_len = ms(params["min_gap_ms"])
    else:
        side = params.get("side", "tail")
        if side in ("tail", "both"):
            e = min(n, int(content[-1]) * hop + win + ms(params["hold_ms"]))
            if e < n:
                cand.append((e, n))
        if side in ("head", "both"):
            s = int(content[0]) * hop - ms(HEAD_GUARD_MS)
            if s > 0:
                cand.append((0, s))
        min_len = ms(TRIM_MIN_MS)
    cand = [c for c in sorted(cand) if c[1] - c[0] >= min_len]
    if window is not None:
        cand = [c for c in _intersect(cand, [window]) if c[1] - c[0] >= min_len]
    if cover is not None:
        cand = [c for c in _intersect(cand, cover) if c[1] - c[0] >= min_len]
    # safeguards EG-1 to EG-3, region by region
    accepted, refused = [], []
    for s, e in cand:
        a, b = max(0, s - fade), min(n, e + fade)
        mx = _max_level(lv, hop, win, n, a, b)
        rel = mx - active
        energy = float(np.sum(pw[s:e]))
        row = {"start": int(s), "end": int(e), "t0_s": round(s / sr, 3), "t1_s": round(e / sr, 3),
               "max_frame_dbfs": _r(mx), "rel_active_db": _r(rel),
               "energy_rel_track_db": _r(_db(energy / total_e)) if energy > 0 else None, "flatness": None}
        hit = None
        if rel > GUARDS["EG-1"]:
            hit = ("EG-1", _r(rel), GUARDS["EG-1"])
        elif mx > GUARDS["EG-2"]:
            hit = ("EG-2", _r(mx), GUARDS["EG-2"])
        elif mx > EG3_MIN_DBFS:
            if b - a < EG3_MIN_SAMPLES:
                hit = ("EG-3", None, GUARDS["EG-3"])
                row["note"] = f"shorter than {EG3_MIN_SAMPLES} samples above {EG3_MIN_DBFS:g} dBFS"
            else:
                fl = _flatness(x[a:b], sr)
                row["flatness"] = round(fl, 4)
                if fl < GUARDS["EG-3"]:
                    hit = ("EG-3", round(fl, 4), GUARDS["EG-3"])
        if hit is None:
            accepted.append((row, energy))
        else:
            refused.append({**row, "guard": hit[0], "value": hit[1], "limit": hit[2]})
    # EG-4: the total removed energy; withdraw the largest regions first
    while accepted and _db(sum(en for _, en in accepted) / total_e) > GUARDS["EG-4"]:
        tot = _db(sum(en for _, en in accepted) / total_e)
        i = max(range(len(accepted)), key=lambda j: (accepted[j][1], -accepted[j][0]["start"]))
        row, _ = accepted.pop(i)
        refused.append({**row, "guard": "EG-4", "value": _r(tot), "limit": GUARDS["EG-4"]})
    # EG-5: fragmentation; the whole move is withheld
    if len(accepted) > GUARDS["EG-5"]:
        cnt = len(accepted)
        refused += [{**row, "guard": "EG-5", "value": cnt, "limit": GUARDS["EG-5"]} for row, _ in accepted]
        accepted = []
        plan["status"] = "too_many_regions"
    elif accepted:
        plan["status"] = "ok"
        plan["removed_energy_rel_db"] = _r(_db(sum(en for _, en in accepted) / total_e))
    for i, (row, _) in enumerate(accepted, 1):
        plan["regions"].append({"n": i, **row})
    plan["refused"] = sorted(refused, key=lambda r: (r["start"], r["end"]))
    return plan


def _section_window(root: Path, section: Any, rate: int, n: int) -> tuple[int, int] | None:
    if section in (None, "all"):
        return None
    from . import query as Q
    from .direction import _Project
    sections = _Project(root).sections()
    try:
        t0, t1 = Q.section_range(section, sections, n / rate)
    except Q.QueryError as e:
        raise EditError(str(e)) from None
    return int(round(t0 * rate)), int(round(t1 * rate))


def plan_track(root: str | Path, track_id: str, op: str, params: dict, section: Any = None) -> dict:
    """Plan one edit move on the project's current state (read-only)."""
    root = Path(root)
    from mankomix.core import mixrender as mr
    x, sr, data = raw_track(root, track_id)
    rate = mr.project_rate(data)
    window = _section_window(root, section, rate, x.shape[0])
    return plan_signal(x, sr, op, params, window=window, cover=_clip_cover(data, track_id, rate))


def measure_record() -> dict:
    return {"source": "raw_asset_pre_clean", "frame_ms": FRAME_MS, "hop_ms": HOP_MS,
            "guards": dict(GUARDS)}


def _move_params(move: dict) -> dict:
    from .direction import resolve_params
    resolved, _ = resolve_params(move, move.get("params") or {})
    return full_params(move["op"], resolved)


def scan(root: str | Path, track_id: str, op: str, params: dict | None = None, section: Any = None) -> dict:
    """``direction edit scan``: what an edit move would cut and refuse, with the same functions as apply.
    Writes nothing."""
    if op not in EDIT_OPS:
        raise EditError(f"--op must be one of {', '.join(EDIT_OPS)}")
    errs: list[str] = []
    check_params(op, params or {}, "params", lambda w, c, m: errs.append(m))
    if errs:
        raise EditError("; ".join(errs))
    full = _move_params({"id": "scan", "op": op, "params": params or {}})
    plan = plan_track(root, track_id, op, full, section)
    return {"kind": "direction_edit_scan", "track": track_id, "op": op, "params": full,
            "section": section, "measure": measure_record(), **plan}


# ---------------------------------------------------------------------------
# apply / revert
# ---------------------------------------------------------------------------

def ledger_path(root: str | Path, dir_id: str) -> Path:
    from .direction import DIRECTIONS_DIR
    return Path(root) / DIRECTIONS_DIR / f"{dir_id}{LEDGER_SUFFIX}"


def _clip_index(data: dict) -> dict[str, tuple[int, int, dict]]:
    out = {}
    for ti, t in enumerate(data.get("tracks") or []):
        for ci, c in enumerate(t.get("clips") or []):
            out[c.get("id")] = (ti, ci, c)
    return out


def _fade_ops(root: Path, track_id: str, regions: list[dict], fade: int) -> tuple[list[dict], list[dict]]:
    """Patch ops and the ledger rows for the fades at the cut edges (inside the kept clips; never at
    the ends of the timeline; an existing longer fade is kept)."""
    from mankomix.core import mixrender as mr
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    rate = mr.project_rate(data)
    total = int(mr.timeline_length(data, rate))
    ti = next(i for i, t in enumerate(data.get("tracks") or []) if t.get("id") == track_id)
    clips = data["tracks"][ti].get("clips") or []
    ops, rows = [], []
    for r in regions:
        for ci, c in enumerate(clips):
            if c.get("muted"):
                continue
            ts = int(c.get("timeline_start", 0) or 0)
            ln = int(mr.clip_length(data, c, rate))
            for field, edge, ok in (("fade_out", ts + ln, r["start"] > 0), ("fade_in", ts, r["end"] < total)):
                if not ok or edge != (r["start"] if field == "fade_out" else r["end"]):
                    continue
                before = int(c.get(field, 0) or 0)
                after = min(fade, ln)
                if after <= before:
                    continue
                ops.append({"op": "replace", "path": f"/tracks/{ti}/clips/{ci}/{field}", "value": after})
                rows.append({"clip": c.get("id"), "field": field, "before": before, "after": after})
    return ops, rows


def _live_foreign_edit(root: Path, dir_id: str, tracks: set[str]) -> tuple[str, str, list[str]] | None:
    """The first (ledger file name order, move order) other direction whose applied edit moves on one of
    ``tracks`` are still in the project: a muted clip of theirs is still muted, or a fade row of theirs
    no longer holds its ``before`` value. Returns (other direction id, track, move ids) or None."""
    from .direction import DIRECTIONS_DIR
    ddir = root / DIRECTIONS_DIR
    if not ddir.is_dir():
        return None
    data = None
    for lp in sorted(ddir.glob(f"*{LEDGER_SUFFIX}"), key=lambda q: q.name):
        try:
            led = json.loads(lp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(led, dict) or led.get("kind") != "direction_edits" or led.get("direction") == dir_id:
            continue
        hits: dict[str, list[str]] = {}
        for mid, e in (led.get("moves") or {}).items():
            if not isinstance(e, dict) or e.get("status") != "applied" or e.get("track") not in tracks:
                continue
            if data is None:
                data = json.loads((root / "project.json").read_text(encoding="utf-8"))
                idx = _clip_index(data)
            live = any(cid in idx and idx[cid][2].get("muted")
                       for r in e.get("regions") or [] for cid in r.get("muted_clips") or [])
            live = live or any(f.get("clip") in idx
                               and int(idx[f["clip"]][2].get(f.get("field"), 0) or 0) != int(f.get("before", 0) or 0)
                               for f in e.get("fades") or [])
            if live:
                hits.setdefault(e["track"], []).append(mid)
        if hits:
            track = next(iter(hits))
            return str(led.get("direction")), track, hits[track]
    return None


def apply_moves(root: str | Path, doc: dict, moves: list[dict], *, actor: str = "agent") -> dict:
    """Run the edit stage of a direction (before every other move); write the ledger.

    Returns {"record": {move id: apply-record entry}, "summary": {...}, "ledger": relative path}."""
    from mankomix.core import api
    from mankomix.core import journal
    from mankomix.core.errors import MankoError
    from .direction import DIRECTIONS_DIR, DirectionError
    root = Path(root)
    dir_id = doc["id"]
    lp = ledger_path(root, dir_id)
    if lp.is_file():
        raise DirectionError(f"{dir_id}: the edit ledger already exists in this project")
    # Another direction's edits still in the project on a track this one cuts: a range mute here would
    # split their clips and copy their fades onto fragments their ledger does not know (UPGRADE2 §17).
    live = _live_foreign_edit(root, dir_id, {m["target"] for m in moves})
    if live is not None:
        other_id, track, mids = live
        raise DirectionError(f"{dir_id}: track '{track}' still holds the edits of {other_id} (move(s) "
                             f"{', '.join(mids)}); revert them (direction edit revert --direction {other_id}) "
                             f"or apply to a fresh copy of the floor")
    rel = f"{DIRECTIONS_DIR}/{lp.name}"
    ledger: dict = {"kind": "direction_edits", "schema_version": 1, "direction": dir_id,
                    "journal_seq_before": journal.last_seq(root), "measure": measure_record(), "moves": {},
                    "reverted": False}
    record: dict = {}
    # The cut-edge fades of a track wait until the last edit move on that track has muted: a later
    # range mute would otherwise split a clip carrying an earlier move's fade and copy the fade onto a
    # new fragment the ledger does not know (revert would then leave it behind).
    last_on_track = {m["target"]: m["id"] for m in moves}
    pending: dict[str, list[tuple[str, dict, dict]]] = {}
    for m in moves:
        mid, op, track = m["id"], m["op"], m["target"]
        params = _move_params(m)
        plan = plan_track(root, track, op, params, m.get("section"))
        entry: dict = {"op": op, "track": track, "params": params, "section": m.get("section"),
                       "active_db": plan["active_db"], "track_energy_db": plan["track_energy_db"],
                       "regions": [], "refused": plan["refused"], "fades": [], "fades_journal_seq": None,
                       "removed_energy_rel_db": plan["removed_energy_rel_db"]}
        if plan.get("note"):
            entry["note"] = plan["note"]
        for r in plan["regions"]:
            try:
                res = api.stem_mute(str(root), track, r["start"], r["end"],
                                    reason=f"direction {dir_id} move {mid} region {r['n']}", actor=actor)
            except MankoError as e:
                raise DirectionError(f"{mid}: range mute failed: {e}") from None
            entry["regions"].append({**r, "muted_clips": list(res.get("muted_clips") or []),
                                     "journal_seq": res.get("journal_seq")})
        if entry["regions"]:
            pending.setdefault(track, []).append((mid, entry, params))
        if last_on_track[track] == mid:
            for fmid, fentry, fparams in pending.pop(track, []):
                ops, rows = _fade_ops(root, track, fentry["regions"],
                                      int(round(fparams["fade_ms"] * 1e-3 * _rate(root))))
                if ops:
                    api.patch(str(root), ops, actor=actor, reason=f"direction {dir_id} move {fmid}: edit fades")
                    fentry["fades"] = rows
                    fentry["fades_journal_seq"] = journal.last_seq(root)
        entry["status"] = {"ok": "applied", "too_many_regions": "too_many_regions"}.get(plan["status"],
                                                                                     "no_regions")
        ledger["moves"][mid] = entry
        record[mid] = {"op": op, "track": track, "regions": len(entry["regions"]),
                       "refused": len(entry["refused"]), "removed_energy_rel_db": entry["removed_energy_rel_db"],
                       "status": entry["status"], "ledger": rel}
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"moves": len(record), "regions": sum(r["regions"] for r in record.values()),
               "refused": sum(r["refused"] for r in record.values()), "ledger": rel}
    return {"record": record, "summary": summary, "ledger": rel}


def _rate(root: Path) -> int:
    from mankomix.core import mixrender as mr
    return int(mr.project_rate(json.loads((root / "project.json").read_text(encoding="utf-8"))))


def revert(root: str | Path, dir_id: str, move: str | None = None, *, actor: str = "human") -> dict:
    """``direction edit revert``: unmute the ledger's clips and restore its fades (one patch)."""
    from mankomix.core import api
    from mankomix.core import journal
    root = Path(root)
    lp = ledger_path(root, dir_id)
    if not lp.is_file():
        raise EditError(f"no edit ledger for {dir_id} in this project")
    ledger = json.loads(lp.read_text(encoding="utf-8"))
    extension_rows = {**ledger.get('derived', {}), **ledger.get('clip_edits', {}), **ledger.get('derived_groups', {})}
    resource_moves = []
    if ledger.get('nodes') or ledger.get('controls'):
        from .xops import _resources
        try:
            resource_moves = _resources.revert(root, dir_id, move, actor=actor)
        except ValueError as exc:
            raise EditError(str(exc)) from exc
        known = move in ledger.get('nodes', {}) or any(
            row.get('move_ref') == f'{dir_id}/{move}' for row in ledger.get('controls', {}).values())
        if move is not None and known or move is None and not ordered_edits(ledger):
            current = json.loads(lp.read_text(encoding='utf-8'))
            return {'kind': 'direction_edit_revert', 'direction': dir_id, 'move': move,
                    'reverted_moves': resource_moves, 'ledger': f'directions/{lp.name}',
                    'journal_seq': journal.last_seq(root), 'ledger_reverted': current.get('reverted', False)}
        ledger = json.loads(lp.read_text(encoding='utf-8'))
    ordered = ledger.get('xop_order') or []
    if ordered and (move in ordered or move is None and (not ledger.get('moves') or any(
            extension_rows[mid].get('status') == 'applied' for mid in ordered))):
        from . import xops
        try:
            result = xops.revert_edits(root, dir_id, move, actor=actor)
        except ValueError as exc:
            raise EditError(str(exc)) from exc
        if move is not None or not ledger.get('moves'):
            if resource_moves:
                result['resource_reverted_moves'] = resource_moves
            return result
        legacy = revert(root, dir_id, actor=actor)
        legacy['derived_reverted_moves'] = [mid for mid in result['reverted_moves']
                                            if extension_rows[mid]['kind'] == 'derived']
        legacy['extension_reverted_moves'] = result['reverted_moves']
        if resource_moves:
            legacy['resource_reverted_moves'] = resource_moves
        return legacy
    if move in (ledger.get('moves') or {}) and any(
            row.get('status') == 'applied' and row.get('track') == ledger['moves'][move].get('track')
            for row in extension_rows.values()):
        raise EditError('revert later extension edits on this track first')
    # BB-18 layouts must be restored before the older mute/fade edits they contain.
    derived_rows = ledger.get('derived') or {}
    if derived_rows and (move in derived_rows or move is None and (
            not ledger.get('moves') or any(row.get('status') == 'applied' for row in derived_rows.values()))):
        from . import derived
        try:
            result = derived.revert(root, dir_id, move, actor=actor)
        except derived.DerivedError as exc:
            raise EditError(str(exc)) from exc
        if move is not None or not ledger.get('moves'):
            return result
        legacy = revert(root, dir_id, actor=actor) if any(
            row.get('status') == 'applied' for row in ledger['moves'].values()) else None
        if legacy is None:
            return result
        legacy['derived_reverted_moves'] = result['reverted_moves']
        return legacy
    moves = ledger.get("moves") or {}
    if move is not None and move not in moves:
        raise EditError(f"{dir_id} has no edit move '{move}'")
    if move is not None and moves[move].get("status") == "applied":
        others = [mid for mid, e in moves.items() if mid != move and e.get("status") == "applied"
                  and e.get("track") == moves[move].get("track")]
        if others:
            raise EditError(f"{move}: the applied edit move(s) {', '.join(others)} share track "
                            f"'{moves[move].get('track')}'; reverting one move alone cannot restore the "
                            f"cut-edge fades - use the whole-direction revert or checkout "
                            f"{ledger.get('journal_seq_before')}")
    targets = [mid for mid in moves if (move is None or mid == move) and moves[mid].get("status") == "applied"]
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    idx = _clip_index(data)
    ops, seen = [], set()
    for mid in targets:
        e = moves[mid]
        for r in e.get("regions") or []:
            for cid in r.get("muted_clips") or []:
                if cid not in idx:
                    raise EditError(f"{mid}: clip '{cid}' is no longer in the project (use checkout "
                                    f"{ledger.get('journal_seq_before')})")
                ti, ci, _ = idx[cid]
                ops.append({"op": "replace", "path": f"/tracks/{ti}/clips/{ci}/muted", "value": False})
        for f in e.get("fades") or []:
            if f.get("clip") not in idx:
                raise EditError(f"{mid}: clip '{f.get('clip')}' is no longer in the project")
            ti, ci, _ = idx[f["clip"]]
            path = f"/tracks/{ti}/clips/{ci}/{f['field']}"
            if path in seen:          # an earlier move's row holds the value from before the edit
                continue
            seen.add(path)
            ops.append({"op": "replace", "path": path, "value": f["before"]})
    seq = None
    if ops:
        api.patch(str(root), ops, actor=actor, reason=f"direction {dir_id}: revert edits"
                                                      + (f" of {move}" if move else ""))
        seq = journal.last_seq(root)
    for mid in targets:
        moves[mid]["status"] = "reverted"
        moves[mid]["reverted_journal_seq"] = seq
    if all(x.get("status") != "applied" for x in moves.values()) and not any(
            x.get('status') == 'applied' for x in extension_rows.values()):
        ledger["reverted"] = True
        ledger["reverted_journal_seq"] = seq
    lp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from .direction import DIRECTIONS_DIR
    return {"kind": "direction_edit_revert", "direction": dir_id, "move": move, "reverted_moves": targets,
            "journal_seq": seq, "ledger_reverted": bool(ledger.get("reverted")),
            "ledger": f"{DIRECTIONS_DIR}/{lp.name}"}


def ordered_edits(ledger):
    """Whether native/extension clip edits remain to dispatch after mix resources."""
    return any(row.get('status') == 'applied'
               for kind in ('moves', 'derived', 'clip_edits', 'derived_groups')
               for row in ledger.get(kind, {}).values())
