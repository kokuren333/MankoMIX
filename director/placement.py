"""Shared signal measurements for placement, overlap axes and phrases (X-03/04/06).

Reuse: director.edit:_power/frame_levels (and its activity constants),
core.analysis.music:onset_envelope/_normalize_onset and scipy.signal:find_peaks
(the full-band form of director.refstudy:attack_times),
core.analysis.erb:mean_power_spectrum/band_matrix, core.config:load_knowledge,
and director.query:observe/_stereo for image_position and side_ratio.
Shared helpers do no I/O; placement reads existing project state and renders in
memory through StemSource, without regenerating caches or changing existing paths.
"""

from __future__ import annotations

import copy
import json
import math

import numpy as np
from scipy.signal import find_peaks

from mankomix.core.analysis.erb import band_matrix, mean_power_spectrum
from mankomix.core.analysis.music import _normalize_onset, onset_envelope
from mankomix.core.analysis.stems import P22_ORDER, _as_frames
from mankomix.core.config import load_knowledge
from mankomix.director import edit as E
from mankomix.director import query as Q
from mankomix.director import stemobs as S
from mankomix.director.refstudy import ATTACK_MIN_GAP_S, ATTACK_PEAK_MIN


def _signal(signal: np.ndarray) -> np.ndarray:
    """Validate using core.analysis.stems:_as_frames; retain channel power."""
    x = _as_frames(signal)
    if x.shape[1] == 0:
        raise ValueError("audio must have at least one channel")
    return x


def _rate(sr: int) -> int:
    if isinstance(sr, (bool, np.bool_)) or not np.isfinite(sr) or sr < 1 or int(sr) != sr:
        raise ValueError("sample rate must be a positive integer")
    return int(sr)


def activity(signal: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (active mask, frame-start seconds, unrounded frame dBFS).

    Reuses director.edit:_power/frame_levels and the activity definition in
    director.edit:plan_signal: p95 of frames > ACTIVE_FLOOR_DBFS, then content
    >= p95 + the existing default PARAMS['threshold_db'] (-60 dB).
    No frames above the absolute floor means an all-false mask. Windows,
    including the last partial window, are exactly the edit stage's windows.
    """
    sr = _rate(sr)
    levels, hop, _ = E.frame_levels(E._power(_signal(signal)), sr)
    times = np.arange(levels.size, dtype=np.float64) * hop / sr
    eligible = levels > E.ACTIVE_FLOOR_DBFS
    mask = np.zeros(levels.size, dtype=bool)
    if eligible.any():
        active_db = float(np.percentile(levels[eligible], E.ACTIVE_PERCENTILE))
        mask = levels >= active_db + E.PARAMS["threshold_db"][3]
    return mask, times, levels


def onsets(signal: np.ndarray, sr: int) -> list[float]:
    """Full-band form of director.refstudy:attack_times, in seconds.

    Reuses core.analysis.music:onset_envelope/_normalize_onset and
    scipy.signal:find_peaks with refstudy's ATTACK_PEAK_MIN/ATTACK_MIN_GAP_S.
    _normalize_onset implements the same 0.4 s local mean and whole-song
    standard-deviation normalization as attack_times. Only band filtering and
    cross-band exclusion are omitted; the mono sum and detector are unchanged.
    Peaks outside the input are discarded (short-input convolution padding).
    """
    sr = _rate(sr)
    mono = Q._stereo(_signal(signal)).mean(axis=1)
    if not mono.size:
        return []
    flux, _, fr = onset_envelope(mono, float(sr))
    if not flux.size:
        return []
    strength = _normalize_onset(flux, fr)
    peaks, _ = find_peaks(strength, height=ATTACK_PEAK_MIN,
                         distance=max(1, int(math.ceil(ATTACK_MIN_GAP_S * fr))))
    return [round(float(k / fr), 3) for k in peaks if k / fr < mono.size / sr]


def runs(mask: np.ndarray, frame_times: np.ndarray) -> list[tuple[float, float]]:
    """Consecutive true frames as [start, end) seconds, without gap merging.

    frame_times are the starts returned by activity. As in
    director.edit:plan_signal, the end includes the last frame's 50 ms window,
    not just its hop. No minimum length, hold or fade is added. The caller must
    clip the end to the source duration for a final partial window. No detector
    is used here; only mask transitions and director.edit:FRAME_MS are used.
    """
    mask = np.asarray(mask, dtype=bool)
    times = np.asarray(frame_times, dtype=np.float64)
    if mask.ndim != 1 or times.ndim != 1 or mask.size != times.size:
        raise ValueError("mask and frame_times must be one-dimensional and equal in length")
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("frame_times must be finite and strictly increasing")
    edges = np.diff(np.r_[0, mask.astype(np.int8), 0])
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return [(round(float(times[a]), 3), round(float(times[b - 1] + E.FRAME_MS / 1000), 3))
            for a, b in zip(starts, ends)]


def band_shares(signal: np.ndarray, sr: int) -> dict:
    """Return {'bands': six shares, 'occupied_hz': [p05, p95]}.

    Reuses core.config:load_knowledge for masking_model.p22.bands_hz and its
    analysis grid, core.analysis.stems:P22_ORDER, and
    core.analysis.erb:mean_power_spectrum/band_matrix. The Hann/Parseval spectrum
    averages channel powers, preserving anti-phase energy. Pad the last frame
    as core.analysis.stems:_Ctx._band_power does. Shares normalize the summed
    energy of the six P-22 bands (20 Hz--20 kHz, clipped at Nyquist); occupied
    frequencies use the full spectrum's cumulative energy, without interpolation.
    Empty/silent inputs return zero shares and [0, 0]. Values round to 3 decimals.
    """
    sr = _rate(sr)
    x = _signal(signal)
    bands = dict.fromkeys(P22_ORDER, 0.0)
    out = {"bands": bands, "occupied_hz": [0.0, 0.0]}
    if not x.size or not np.any(x):
        return out
    model = load_knowledge("masking_model")
    nfft = max(2, int(2 ** round(math.log2(model["analysis"]["frame_s"] * sr))))
    hop = max(1, int(nfft * model["analysis"]["hop_fraction"]))
    nframes = 1 + max(0, math.ceil((len(x) - nfft) / hop))
    need = (nframes - 1) * hop + nfft
    spectrum = np.zeros(nfft // 2 + 1)
    for channel in x.T:
        padded = np.pad(channel, (0, max(0, need - len(channel))))
        spectrum += mean_power_spectrum(padded, nfft, hop) / x.shape[1]
    energy = []
    for name in P22_ORDER:
        lo, hi = model["p22"]["bands_hz"][name]
        energy.append(float(band_matrix(sr, nfft, [lo, min(hi, sr / 2)])[0] @ spectrum)
                      if lo < sr / 2 else 0.0)
    total = sum(energy)
    if total > 0:
        bands.update((name, round(value / total, 3)) for name, value in zip(P22_ORDER, energy))
    cumulative = np.cumsum(spectrum)
    if cumulative[-1] > 0:
        bins = np.searchsorted(cumulative, cumulative[-1] * np.array([0.05, 0.95]))
        out["occupied_hz"] = [round(float(k * sr / nfft), 3) for k in bins]
    return out


def image(signal: np.ndarray) -> tuple[float | None, float | None]:
    """Return (image_position, side_ratio_db) via director.query:observe.

    Both primitives are full-band and sample-rate independent. A virtual rate
    of 1 Hz lets observe accept even a single sample under its section-duration
    rule; no resampling, filter or signal modification occurs. Its range metadata
    is discarded. Empty/silent input returns (None, None), matching null cells.
    Values round to 3 decimals; observe's existing dB floor is retained.
    """
    x = Q._stereo(_signal(signal))
    if not x.size:
        return None, None
    position = Q.observe(x, 1, {"primitive": "image_position"})
    if position["status"] != "ok":
        return None, None
    side = Q.observe(x, 1, {"primitive": "side_ratio"})
    return round(position["value"], 3), round(side["value"], 3)


NOTE = ("値は関係と配置の記述で、良し悪しを言わない。役割は機械が決めない。"
        "鳴り始めは密な素材で当てにならない。読みは指揮者の〔推定〕")
RELIABILITY = {"bands": "high", "active_ratio": "high", "onset": "medium",
               "sustain": "medium", "roles": "not_decided"}


class PlacementInputError(S.StemObsError):
    """Placement inputs cannot be read without changing the project."""


def _grid_step(proj) -> float | None:
    """Read core.remix:project_music's existing cache, without computing/writing.

    Reuse its static-sum asset/hash key and cache version. The floor proposal
    retains BPM but drops confidence, so it cannot establish the 0.5 threshold.
    """
    from mankomix.core import mixrender as MR
    from mankomix.core.hashing import canonical_hash
    from mankomix.core.remix import ANALYSIS_CACHE_VERSION, _cache_path

    ids = []
    fullmix = MR.fullmix_asset_id(proj.data)
    for track in MR.stem_tracks(proj.data):
        for clip in track.get("clips") or []:
            aid = clip.get("asset")
            if aid not in ids and aid != fullmix:
                ids.append(aid)
    assets = {a["id"]: a for a in proj.data.get("assets") or []}
    key = canonical_hash({"static_sum": [[aid, assets[aid].get("sha256")] for aid in ids]})[:24]
    path = _cache_path(proj, key)
    if not path.is_file():
        return None
    stored = json.loads(path.read_text(encoding="utf-8"))
    if stored.get("version") != ANALYSIS_CACHE_VERSION:
        return None
    music = stored.get("music") or {}
    bpm, confidence = music.get("bpm"), music.get("bpm_confidence")
    if (isinstance(bpm, (int, float)) and not isinstance(bpm, bool)
            and math.isfinite(bpm) and bpm > 0
            and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
            and math.isfinite(confidence) and confidence >= 0.5):
        return 60.0 / bpm / 4.0
    return None


def _declared(rows, section):
    """Copy matching source rows, without inferring roles or merging declarations.

    String sections match by ID. Time ranges match every floor section with
    positive overlap (touching endpoints do not match). Preserve source order,
    keys, lead, roles and duplicates, including other tracks' declarations.
    """
    matched = []
    for row in rows:
        ref = row.get("section")
        match = ref == section["id"] if isinstance(ref, str) else (
            isinstance(ref, dict) and
            max(float(ref["t0_s"]), section["t0_s"]) <
            min(float(ref["t1_s"]), section["t1_s"]))
        if match:
            matched.append(copy.deepcopy(row))
    return matched or None


def placement(project, *, variant=None, direction=None) -> dict:
    """Describe each audible dry track in the floor proposal's sections (X-03).

    Frame activity is measured within each section using the shared edit-stage
    definition. Active energy is the sum of active frame mean-square powers;
    level_active_db is the dB of their arithmetic mean, never a mean of dB.
    Onsets and runs use the shared detectors within each section. Grid offsets
    are signed milliseconds against the nearest sixteenth from project time 0.
    """
    from mankomix.core.errors import MankoError
    from .direction import DirectionError, _Project, parse_document
    from .relate import _source

    try:
        proj = _Project(project)
        pv = proj.variant(variant)
        if variant is not None and pv is None:
            raise PlacementInputError(f"unknown variant '{variant}'")
        role_rows = []
        if direction is not None:
            frame = parse_document(direction)["block"].get("frame") or {}
            role_rows = frame.get("section_roles") or []
            for row in role_rows:
                refs = list(row.get("roles") or {})
                if row.get("lead") is not None:
                    refs.append(row["lead"])
                for tid in refs:
                    if tid not in proj.tracks():
                        raise PlacementInputError(f"unknown track '{tid}'")
        src = _source(project, (pv or {}).get("id"))
        if not src._audible:
            raise PlacementInputError("no audible stem tracks")
        stems, sr = src.dry()
        if not stems:
            raise PlacementInputError("no audible stem tracks")
        duration = max(len(x) for x in stems.values()) / sr
        floor = proj.sections() or [{"id": "all", "start_s": 0.0, "end_s": duration}]
        sections, spans = [], []
        for sec in floor:
            t0, t1 = max(0.0, float(sec["start_s"])), min(duration, float(sec["end_s"]))
            if not math.isfinite(t0) or not math.isfinite(t1) or t1 <= t0:
                raise PlacementInputError(f"invalid floor section '{sec['id']}'")
            sections.append({"id": sec["id"], "t0_s": round(t0, 3), "t1_s": round(t1, 3)})
            spans.append((int(round(t0 * sr)), int(round(t1 * sr))))
        ids = sorted(stems)
        grid_step = _grid_step(proj)
        cells = {tid: {} for tid in ids}
        for sec, (i0, i1) in zip(sections, spans):
            energies = {}
            for tid in ids:
                cut = stems[tid][i0:i1]
                mask, frame_times, levels = activity(cut, sr)
                cell = None
                if mask.any():
                    # Undo the edit-stage log floor before summing physical power.
                    powers = np.maximum(10.0 ** (levels[mask] / 10.0) - E._EPS, 0.0)
                    energy = float(powers.sum())
                    energies[tid] = energy
                    position, side = image(cut)
                    attacks = onsets(cut, sr)
                    seconds = (i1 - i0) / sr
                    offset = None
                    if grid_step is not None and attacks:
                        absolute = np.asarray(attacks) + i0 / sr
                        offsets = absolute - np.floor(absolute / grid_step + 0.5) * grid_step
                        offset = round(float(np.median(offsets)) * 1000.0, 3)
                    lengths = [max(0.0, min(end, len(cut) / sr) - start) * 1000.0
                               for start, end in runs(mask, frame_times)]
                    cell = {"active_ratio": round(float(mask.mean()), 3),
                            "level_active_db": round(10.0 * math.log10(float(powers.mean())), 3),
                            "activity_share": None, **band_shares(cut, sr),
                            "onset": {"count": len(attacks),
                                      "per_s": round(len(attacks) / seconds, 3),
                                      "grid_offset_ms_median": offset},
                            "sustain": {"run_ms_median": round(float(np.median(lengths)), 3)},
                            "image_position": position, "side_ratio_db": side,
                            "declared_roles": _declared(role_rows, sec)}
                cells[tid][sec["id"]] = cell
            total = sum(energies.values())
            for tid, energy in energies.items():
                cells[tid][sec["id"]]["activity_share"] = round(energy / total, 3)
        return {"kind": "direction_stem_placement", "signal": "mix_stage_dry",
                "sections": sections, "tracks": ids, "cells": cells,
                "reliability": dict(RELIABILITY), "note": NOTE}
    except (DirectionError, S.StemObsError, Q.QueryError, MankoError, OSError,
            ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PlacementInputError(str(exc)) from exc
