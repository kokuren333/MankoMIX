"""Read-only measurements of the contents of stems (FR-6).

These are clues for a director, never restrictions on a direction or a gate.
All audio is measured after cleanup, before the track chain and fader.
"""
from __future__ import annotations

import json
import math
from itertools import combinations
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy import signal

from mankomix.core import config, mixrender as MR
from mankomix.core.analysis.stems import reverb_metrics
from mankomix.core.errors import MankoError
from mankomix.core.measure import loudness as L
from mankomix.core.project import Project
from . import stemobs


NOTE = ("共有成分は、線形に共通な成分が自分のエネルギーに占める割合の推定で、漏れの量そのものではない。"
        "同じ音を重ねて弾く別の楽器はほぼ数に入らず、残響で広がった漏れは低く出る。"
        "残響の値は粗い盲推定。読みは指揮者の〔推定〕")
SHARED_SR = 16000
SPECTRUM = {"fs": SHARED_SR, "window": "hann", "nperseg": 2048, "noverlap": 1024}


class PurityInputError(ValueError):
    """The requested project, tracks or existing cleanup inputs cannot be read."""


def _ordered(value):
    """Sort dictionary keys and round finite measurements once for JSON output."""
    if isinstance(value, dict):
        return {k: _ordered(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_ordered(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return round(float(value), 3) if math.isfinite(value) else None
    return value


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _floor_restrictions(project: Project) -> dict:
    """Use the applied floor proposal, with the same fallback as dossier._pick."""
    wanted = ((project.data.get("mix") or {}).get("applied") or {}).get("proposal_id")
    proposals = [_read_json(p) for p in sorted((project.root / "cache" / "proposals").glob("*.json"))]
    proposals = [p for p in proposals if p.get("stage") == "mix"]
    chosen = next((p for p in proposals if wanted and p.get("proposal_id") == wanted), None)
    if chosen is None:
        applied = [p for p in proposals if p.get("status") == "applied"]
        applied.sort(key=lambda p: (str(p.get("proposed_at") or ""), str(p.get("proposal_id") or "")))
        chosen = applied[-1] if applied else {}
    return chosen.get("restrictions") or {}


def _validate_cleanup(project: Project, tracks: list[dict]) -> None:
    """Use the shared check per clip to preserve the existing input-error details."""
    for track in tracks:
        for clip in track.get("clips") or []:
            aid = clip.get("asset")
            if stemobs.cleanup_cache_error(project, [{**track, "clips": [clip]}]):
                raise PurityInputError(f"cleanup cache is missing or stale for '{track['id']}' / '{aid}'; "
                                       "run clean apply/render first")


def _span(data: dict, track: dict, sr: int) -> tuple[int, int]:
    """Clip support on the project timeline, excluding render-time tail padding."""
    spans = [(int(c.get("timeline_start") or 0), MR.clip_length(data, c, sr))
             for c in track.get("clips") or []]
    spans = [(start, start + length) for start, length in spans if length > 0]
    return (min(s for s, _ in spans), max(e for _, e in spans)) if spans else (0, 0)


def _measure(x: np.ndarray, sr: int, detection: dict) -> dict:
    if not len(x):
        return {"baked_reverb": None, "baked_width": None,
                "baked_dynamics": {"peak_dbfs": None, "lufs_integrated": None,
                                   "plr_db": None, "crest_db": None}, "r22_baked": False}
    peak = float(L.sample_peak_dbfs(x))
    lufs = float(L.integrated(x, sr))
    # Match query.observe's full-band side ratio, correlation and crest.
    left, right = x[:, 0], x[:, 1]
    mid, side = (left + right) / 2.0, (left - right) / 2.0
    den = math.sqrt(float(np.sum(left * left)) * float(np.sum(right * right)))
    def db(p):
        return 10.0 * math.log10(max(float(p), 1e-20))

    rms = float(np.sqrt(np.mean(x * x)))
    crest = 20.0 * math.log10(max(float(np.max(np.abs(x))), 1e-12)) - \
        20.0 * math.log10(max(rms, 1e-12))
    reverb = reverb_metrics(x, sr)
    reverb = {k: reverb.get(k) for k in ("dr_db", "rt60_mid_s")}
    return {
        "baked_reverb": reverb if any(v is not None for v in reverb.values()) else None,
        "baked_width": {"correlation": float(np.sum(left * right)) / den if den > 0 else 0.0,
                        "side_ratio_db": db(np.mean(side * side)) - db(np.mean(mid * mid))},
        "baked_dynamics": {"peak_dbfs": peak, "lufs_integrated": lufs,
                           "plr_db": peak - lufs if math.isfinite(peak) and math.isfinite(lufs) else None,
                           "crest_db": crest},
        "r22_baked": bool(math.isfinite(peak) and math.isfinite(lufs) and
                          peak >= detection["peak_dbfs_min"] and peak - lufs < detection["plr_max_db"]),
    }


def _shared(audio: dict, spans: dict, sr: int) -> tuple[dict, set]:
    mono = {tid: MR.resample(x.mean(axis=1), sr, SHARED_SR) if len(x) else np.empty(0)
            for tid, x in audio.items()}
    shared = {tid: [] for tid in audio}
    too_short = {tid for tid, (s, e) in spans.items() if e - s < 10 * sr}
    long_pairs, short_pairs = set(), set()
    for a, b in combinations(sorted(audio), 2):
        start = max(spans[a][0], spans[b][0])
        end = min(spans[a][1], spans[b][1])
        if end - start < 10 * sr:
            short_pairs.update((a, b))
            continue
        long_pairs.update((a, b))
        lo, hi = round(start * SHARED_SR / sr), round(end * SHARED_SR / sr)
        x, y = mono[a][lo:hi], mono[b][lo:hi]
        if any(float(np.mean(v * v)) < 10 ** (-70.0 / 10.0) for v in (x, y)):
            continue
        f, c = signal.coherence(x, y, **SPECTRUM)
        _, px = signal.welch(x, **SPECTRUM)
        _, py = signal.welch(y, **SPECTRUM)
        band = (f >= 100.0) & (f <= 7000.0)
        c = np.nan_to_num(c[band], nan=0.0)
        powers = [p[band] for p in (px, py)]
        common = [float(np.sum(c * p)) for p in powers]
        louder = a if common[0] >= common[1] else b
        for tid, other, power, coherent in zip((a, b), (b, a), powers, common):
            total = float(np.sum(power))
            if total <= 0 or coherent <= 0:
                continue
            value = 10.0 * math.log10(coherent / total)
            if value >= -20.0:
                shared[tid].append({"track": other, "shared_power_db": value, "louder_in": louder})
    too_short.update(short_pairs - long_pairs)
    for rows in shared.values():
        rows.sort(key=lambda row: (-row["shared_power_db"], row["track"]))
        del rows[5:]
    return shared, too_short


def stem_purity(project_root: str | Path, tracks: Iterable[str] | None = None) -> dict:
    """Measure stem contents in memory, without changing any project file.

    Args:
        project_root: Project folder containing project.json.
        tracks: Track IDs to report (a single string is also accepted). None
            reports every audible stem, honoring track mute/solo. Explicit IDs
            may include muted stems. Shared components are compared against
            all audible stems as well as the explicitly requested stems.

    Returns:
        The FR-6 dictionary with kind="direction_stem_purity",
        signal="post_clean_pre_chain", tracks, mixture and the fixed note.
        Keys are sorted, finite measurements rounded to three decimals, and
        unavailable measurements represented by None (JSON null). Short clip
        spans/common overlaps produce shared=None and reason="too_short";
        silent pairs are omitted. No provenance or flag restricts an action.

    Raises:
        PurityInputError: The project/track input cannot be read, no tracks are
            selected, or an applied cleanup cache is missing or stale. Cleanup
            is never regenerated. Raw, disabled or skipped cleanup needs no
            cache, as in refsheet._project_stems.
    """
    try:
        project = Project.open(project_root)
        data, _ = MR.effective_data(project)
        by_id = {t["id"]: t for t in MR.stem_tracks(data)}
        solo = {tid for tid, t in by_id.items() if t.get("solo")}
        audible = {tid for tid, t in by_id.items() if not t.get("muted") and (not solo or tid in solo)}
        selected = audible if tracks is None else set([tracks] if isinstance(tracks, str) else tracks)
        unknown = selected - by_id.keys()
        if unknown:
            raise PurityInputError("unknown stem tracks: " + ", ".join(sorted(unknown)))
        if not selected:
            raise PurityInputError("no stem tracks selected")
        measured = sorted(audible | selected)
        _validate_cleanup(project, [by_id[tid] for tid in measured])
        sr = MR.project_rate(data)
        spans = {tid: _span(data, by_id[tid], sr) for tid in measured}
        audio = {tid: MR.render_track(project, tid, apply_chain=False, apply_fader=False,
                                      length=spans[tid][1])[0] if spans[tid][1] > 0 else np.empty((0, 2))
                 for tid in measured}
        shared, too_short = _shared(audio, spans, sr)
        detection = config.load_knowledge("mix_rules")["r22"]["baked_detection"]
        restricted = _floor_restrictions(project)
        assets = {a["id"]: a for a in data.get("assets") or []}
        result = {}
        for tid in sorted(selected):
            row = _measure(audio[tid], sr, detection)
            origins = sorted({assets[c["asset"]]["origin"] for c in by_id[tid].get("clips") or []
                              if assets.get(c.get("asset"), {}).get("origin") is not None})
            row["flags"] = {"origin": origins[0] if len(origins) == 1 else origins or None,
                            "r22_baked": row.pop("r22_baked"), "floor_restricted": tid in restricted}
            row["shared"] = None if tid in too_short else shared[tid]
            if tid in too_short:
                row["reason"] = "too_short"
            result[tid] = row
        check = next((c for c in (data.get("ingest") or {}).get("checks") or []
                      if c.get("check") == "stem_sum_consistency"), None)
        mixture = {k: (check.get("values") or {}).get(k) for k in
                   ("residual_db", "correlation", "residual_after_gain_fit_db")} if check else None
        return _ordered({"kind": "direction_stem_purity", "signal": "post_clean_pre_chain",
                         "tracks": result, "mixture": mixture, "note": NOTE})
    except (MankoError, OSError, ValueError) as exc:
        if isinstance(exc, PurityInputError):
            raise
        raise PurityInputError(str(exc)) from exc
