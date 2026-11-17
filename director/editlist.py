"""Reference-only time-varying moves on floor/result dry track signals.

Imported by check only with --edit-list. No verdict or calibration reads this
block. Signals are measured at mix-stage gain, without master level matching.
"""

from __future__ import annotations

import json

import numpy as np

from . import duck as K
from . import query as Q
from . import stemobs as S

NOTE = "参考値。どの判定にも入らない"
MAX_ROWS = 512
WINDOW_S = 0.010
EPS = 1e-20


def _round(value):
    if isinstance(value, float):
        return round(value, 3) if np.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


def _level(x: np.ndarray, sr: int, t0: float, t1: float) -> float | None:
    a, b = max(0, int(round(t0 * sr))), min(len(x), int(round(t1 * sr)))
    if b <= a:
        return None
    return float(10 * np.log10(max(float(np.mean(x[a:b] ** 2)), EPS)))


def _interval(move, t0, t1, amount, why):
    return {"move": move.get("id"), "track": move.get("target"),
            "t0_s": t0, "t1_s": t1, "amount_db": amount, "why": why,
            "before_db": None, "after_db": None}


def _local_levels(x: np.ndarray, sr: int, times: np.ndarray) -> np.ndarray:
    """2 ms power windows, using only the local hit span and one cumulative sum."""
    a = np.clip(np.rint((times - .001) * sr).astype(int), 0, len(x))
    b = np.clip(np.rint((times + .001) * sr).astype(int), 0, len(x))
    start, end = int(a.min()), int(b.max())
    pw = x[start:end] ** 2
    if pw.ndim > 1:
        pw = pw.mean(axis=1)
    c = np.concatenate(([0.0], np.cumsum(pw)))
    power = (c[b - start] - c[a - start]) / np.maximum(b - a, 1)
    return np.where(b > a, 10 * np.log10(np.maximum(power, EPS)), np.nan)


def _duck(move, params, record, floor, result, bpm):
    p = K.full_params(params)
    release = record.get("release") or K.release(params, bpm)[1]
    row = {"move": move.get("id"), "track": move.get("target"), "key": p["key"],
           "hits": record.get("hits"),
           "planned": {"depth_db": record.get("depth_db", p["depth_db"]),
                       "lead_ms": record.get("attack_ms", p["attack_ms"]), "release": release},
           "measured": {"band_drop_db_median": None, "bottom_minus_onset_ms_median": None}}
    try:
        # Use the same pre-chain key and onset detector as the applied envelope.
        # Validate cleanup caches before key_hits can invoke the core renderer.
        floor.tracks()
        fs, sr = floor.dry()
        rs, rsr = result.dry()
        hits, hsr = K.key_hits(floor.root, p["key"], p)
        row["hits"] = len(hits)
        band = record.get("key_band_hz") or [p["key_lo_hz"], p["key_hi_hz"]]
        f = Q._bandpass(fs[row["track"]], sr, band)
        r = Q._bandpass(rs[row["track"]], rsr, band)
        drops, offsets = [], []
        for hit in hits:
            t = hit / hsr
            fl = _level(f, sr, t - WINDOW_S, t + WINDOW_S)
            rl = _level(r, rsr, t - WINDOW_S, t + WINDOW_S)
            if fl is None or rl is None or fl <= -199:
                continue
            drops.append(fl - rl)
            # A 2 ms moving power window suppresses waveform zero crossings.
            # The minimum result/floor band-power ratio locates the attenuation
            # bottom, independently of the key's own amplitude envelope.
            times = np.arange(int(round((t - WINDOW_S) * sr)),
                              int(round((t + WINDOW_S) * sr)) + 1) / sr
            flevels = _local_levels(f, sr, times)
            rlevels = _local_levels(r, rsr, times)
            valid = [(rv - fv, abs(tt - t), tt) for tt, fv, rv in zip(times, flevels, rlevels)
                     if np.isfinite(fv) and np.isfinite(rv) and fv > -199]
            if valid:
                offsets.append((min(valid)[2] - t) * 1000)
        if drops:
            row["measured"]["band_drop_db_median"] = float(np.median(drops))
        if offsets:
            row["measured"]["bottom_minus_onset_ms_median"] = float(np.median(offsets))
    except (S.StemObsError, Q.QueryError, KeyError, ValueError) as exc:
        row["measurement_error"] = str(exc)
    return row


def block(doc: dict, project, floor_project, record: dict | None, *, result_source=None, floor_source=None,
          variant=None, floor_variant=None) -> dict:
    """Stable move/segment order; over 512 rows, one encompassing span per move.

    Edit rows add op/applied to the interval form. Mutes have no finite planned
    dB amount (null). Refused edit candidates are not applied regions.
    """
    from .direction import resolve_params

    b = doc["block"]
    recorded = (record or {}).get("record", {}).get("moves", {})
    selection = ((record or {}).get("calibration") or {}).get("selection")
    ledger_path = project.root / "directions" / f"{doc['id']}.edits.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else {}
    rows, moves = [], {}
    for move in b.get("moves") or []:
        op, mid = move.get("op"), move.get("id")
        if op not in ("gain", "gain_curve", "duck", "edit_trim", "edit_gate") \
                or (op == "gain" and move.get("section") in (None, "all")):
            continue
        rec = recorded.get(mid) or {}
        params, _ = resolve_params(move, move.get("params") or {}, selection)
        why = move.get("basis")
        moves[mid] = (move, params, rec)
        if op == "gain" and move.get("section") not in (None, "all"):
            sections = floor_project.sections()
            duration = max((float(s["end_s"]) for s in sections), default=1e9)
            t0, t1 = rec.get("range_s") or Q.section_range(move["section"], sections, duration)
            amount = rec.get("delta_db", params.get("delta_db"))
            if amount is None and "gain_db" in params:
                amount = params["gain_db"] - floor_project.tracks().get(move.get("target"), {}).get("gain_db", 0)
            rows.append(_interval(move, t0, t1, amount, (move.get("section") or {}).get("why", why)
                                  if isinstance(move.get("section"), dict) else why))
        elif op == "gain_curve":
            for seg in rec.get("segments", params.get("segments", [])):
                rows.append(_interval(move, seg["t0_s"], seg["t1_s"],
                                      0.0 if seg.get("hold") else seg["delta_db"], seg.get("why", why)))
        elif op == "duck":
            rows.append({"move": mid, "track": move.get("target"), "_duck": True})
        elif op in ("edit_trim", "edit_gate"):
            entry = (ledger.get("moves") or {}).get(mid) or {}
            for region in entry.get("regions") or []:
                rows.append({**_interval(move, region["t0_s"], region["t1_s"], None, region.get("why", why)),
                             "op": op, "applied": entry.get("status") == "applied"})
    count = len(rows)
    mode = "rows"
    if count > MAX_ROWS:
        mode = "summary"
        groups = {}
        for row in rows:
            groups.setdefault(row["move"], []).append(row)
        rows = []
        for mid, group in groups.items():
            if group[0].get("_duck"):
                rows.append(group[0])
                continue
            amounts = [r["amount_db"] for r in group if r["amount_db"] is not None]
            rows.append({"move": mid, "track": group[0]["track"], "op": moves[mid][0]["op"],
                         "rows": len(group), "t0_s": min(r["t0_s"] for r in group),
                         "t1_s": max(r["t1_s"] for r in group),
                         "amount_db_range": [min(amounts), max(amounts)] if amounts else None,
                         "why": moves[mid][0].get("basis"), "before_db": None, "after_db": None})
            if "applied" in group[0]:
                rows[-1]["applied"] = group[0]["applied"]
    if rows:
        result_source = result_source or S.StemSource(project.root, variant)
        floor_source = floor_source or S.StemSource(floor_project.root, floor_variant)
    signals = {}
    for row in rows:
        if row.pop("_duck", False):
            move, params, rec = moves[row["move"]]
            row.update(_duck(move, params, rec, floor_source, result_source, K.floor_bpm(floor_project.floor_mxp)))
            continue
        for name, source in (("before_db", floor_source), ("after_db", result_source)):
            try:
                if name not in signals:
                    signals[name] = source.dry()
                stems, sr = signals[name]
                row[name] = _level(stems[row["track"]], sr, row["t0_s"], row["t1_s"])
            except (S.StemObsError, KeyError) as exc:
                row.setdefault("measurement_errors", {})[name] = str(exc)
    return _round({"note": NOTE, "mode": mode, "row_count": count, "rows": rows})
