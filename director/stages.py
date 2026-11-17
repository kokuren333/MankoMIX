"""Read-only band energy at the track, mix and rendered master stages (X-05)."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from mankomix.core import audio_io
from mankomix.core.errors import MankoError
from . import query as Q
from . import stemobs as S
from .relate import _source, _sections

NOTE = "値は各段の帯域エネルギーの記述で、良し悪しを言わない。読みは指揮者の〔推定〕"
RELIABILITY = {"band_energy": "high", "interpretation": "not_provided"}
LARGE_BOOSTS_NOTE = "読む材料。拒否も警告もしない"


class StagesInputError(S.StemObsError):
    """The requested stage signals cannot be read without changing the project."""


def _large_boosts(direction, project):
    """Describe EQ boosts using the existing range selection and R-06 data."""
    from mankomix.core import config
    from .direction import parse_document, resolve_params

    limit = config.load_knowledge("mix_rules")["eq"]["max_move_db"]
    rows = []
    for move in parse_document(direction)["block"].get("moves", []):
        op = move.get("op")
        processors = []
        if op == "chain_add":
            processors = [move]
        elif op == "bus_add":
            processors = (move.get("params") or {}).get("chain") or []
        elif op == "chain_param":
            holder = {**project.tracks(), **project.buses()}.get(move.get("target")) or {}
            item = next((p for p in holder.get("chain") or [] if p.get("id") == move.get("replaces")), None)
            if item is not None:
                processors = [{"type": item.get("type"),
                               "params": {**(item.get("params") or {}), **(move.get("params") or {})}}]
        for proc in processors:
            kind = proc.get("processor", proc.get("type"))
            key = {"eq": "gain_db", "dynamic_eq": "range_db"}.get(kind)
            if key is None:
                continue
            params, _ = resolve_params(move, proc.get("params"))
            gain = params.get(key, 0.0)
            # A notch ignores gain_db and cannot boost.
            if kind == "eq" and params.get("shape") == "notch":
                continue
            if gain > limit:
                rows.append({"move": move.get("id"), "target": move.get("target"),
                             "freq_hz": round(float(params.get("freq_hz", 1000.0)), 3),
                             "gain_db": round(float(gain), 3), "rule": "R-06"})
    return rows


def stages(project, *, variant=None, band, section=None, direction=None) -> dict:
    """Measure audible dry tracks and the mix in memory, plus an existing native master.

    ``direction`` adds reference-only context about EQ boosts above R-06.
    No cache is regenerated and no file is written. Master matching uses full
    programme integrated loudness, before selecting the measurement section.
    """
    from .direction import DirectionError, _Project, _render_file

    if not S._band_ok(band):
        raise StagesInputError("bad_value: band must be [lo, hi] in Hz with 0 <= lo < hi")
    try:
        root = Path(project)
        proj = _Project(root)
        pv = proj.variant(variant)
        if variant is not None and pv is None:
            raise StagesInputError(f"unknown variant '{variant}'")
        vid = (pv or {}).get("id")
        src = _source(root, vid)
        dry, sr = src.dry()
        if not dry:
            raise StagesInputError("no audible stem tracks")
        mix, _ = src.mix()
        sections = _sections(root)
        t0, t1 = Q.section_range(section, sections, len(mix) / sr)
        spec = {"primitive": "band_energy", "band_hz": list(band),
                "section": {"t0_s": t0, "t1_s": t1}}

        def energy(x, rate, gain=0.0):
            return float(Q.observe(x, rate, spec, gain_db=gain)["value"])

        rows = {}
        powers = []
        summed = np.zeros_like(mix)
        for tid, x in dry.items():
            pre, pre_sr = src.pre_chain(tid, length=len(mix))
            a, b = energy(pre, pre_sr), energy(x, sr)
            rows[tid] = {"pre_chain_db": round(a, 3), "dry_db": round(b, 3),
                         "chain_delta_db": round(b - a, 3)}
            powers.append(10.0 ** (b / 10.0))
            summed += x
        sum_db, mix_db = energy(summed, sr), energy(mix, sr)
        out = {"kind": "direction_stem_stages", "variant": vid,
               "band_hz": [round(float(v), 3) for v in band],
               "range_s": [round(t0, 3), round(t1, 3)], "tracks": rows,
               "sum_of_dry_db": round(sum_db, 3),
               "cancellation_db": round(sum_db - Q._db(sum(powers)), 3),
               "mix_db": round(mix_db, 3), "master_db": None,
               "master_minus_mix_matched_db": None}
        # The archive is native float, before delivery resampling/dither. A native
        # delivery is the existing fallback used by direction.check / refsheet.
        master = root / "renders" / str(vid) / "master__archive_f32.wav"
        if not master.is_file():
            master = _render_file(root, vid) if vid else None
        if master is None:
            out["master_reason"] = "その変種の描画済みマスターが無い"
        else:
            x, msr = audio_io.read(master)
            out["master_db"] = round(energy(x, msr), 3)
            lm, lx = Q.integrated_lufs(mix, sr), Q.integrated_lufs(x, msr)
            if math.isfinite(lm) and math.isfinite(lx):
                out["master_minus_mix_matched_db"] = round(energy(x, msr, lm - lx) - mix_db, 3)
            else:
                out["master_match_reason"] = "積分ラウドネスが測れない"
        out.update(note=NOTE, reliability=dict(RELIABILITY))
        if direction is not None:
            out.update(large_boosts=_large_boosts(direction, proj), large_boosts_note=LARGE_BOOSTS_NOTE)
        return out
    except (DirectionError, S.StemObsError, Q.QueryError, MankoError, OSError, ValueError) as exc:
        raise StagesInputError(str(exc)) from exc
