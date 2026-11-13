"""Measurement vector (SPEC 4.2, 6.3): one JSON-safe dict per signal.

Keys: analyzer_version, sample_rate, channels, frames, duration_s,
P-03, P-04, P-05, P-06, P-07, P-14, LTAS, health, notes.
Non-finite numbers (-inf for silence, nan) are replaced by None, so
json.dumps(vector, allow_nan=False) always works.

Non-finite input samples are counted in `health` and replaced by 0 before
any other measurement (health.sanitized = True).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .. import audio_io
from . import loudness as _ld
from .bands import BANDS_P07, BANDS_P22, Spectrum
from .spectral import band_crest, band_energy, ltas
from .stereo import MONO_CONVENTION, band_stereo, low_band_negative_persistence

ANALYZER_VERSION = "mankomix-measure/1.0.0"
CLIP_THRESHOLD = 1.0
CLIP_MIN_RUN = 3


def json_safe(obj):
    """Recursively convert numpy types to Python and non-finite floats to None."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [json_safe(v) for v in obj.tolist()]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    return obj


def _clip_runs(col: np.ndarray, min_run: int) -> tuple[int, int]:
    """(samples in runs of >= min_run consecutive |x| >= 1.0, number of such runs)."""
    hot = np.abs(col) >= CLIP_THRESHOLD
    if not hot.any():
        return 0, 0
    d = np.diff(np.concatenate(([0], hot.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    lens = ends - starts
    long = lens >= min_run
    return int(lens[long].sum()), int(long.sum())


def health(x: np.ndarray) -> dict:
    """S-09 input health: non-finite samples, DC offset, clipping."""
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    nan_c = np.isnan(a).sum(axis=0)
    inf_c = np.isinf(a).sum(axis=0)
    clean = np.where(np.isfinite(a), a, 0.0)
    dc = clean.mean(axis=0) if a.shape[0] else np.zeros(a.shape[1])
    clip = [_clip_runs(clean[:, c], CLIP_MIN_RUN) for c in range(a.shape[1])]
    peak = np.max(np.abs(clean), axis=0) if a.shape[0] else np.zeros(a.shape[1])
    return {
        "nan_count": int(nan_c.sum()),
        "inf_count": int(inf_c.sum()),
        "nan_count_per_channel": nan_c.tolist(),
        "inf_count_per_channel": inf_c.tolist(),
        "sanitized": bool(nan_c.sum() + inf_c.sum() > 0),
        "dc_offset": dc.tolist(),
        "dc_offset_db": [20.0 * math.log10(abs(v)) if v != 0 else None for v in dc],
        "clipped_samples": int(sum(c[0] for c in clip)),
        "clipped_samples_per_channel": [c[0] for c in clip],
        "clip_runs": int(sum(c[1] for c in clip)),
        "clip_rule": f"|x| >= {CLIP_THRESHOLD} in runs of >= {CLIP_MIN_RUN} samples",
        "over_full_scale_samples": int((np.abs(clean) > 1.0).sum()),
        "peak_abs": peak.tolist(),
        "silent": bool(not np.any(clean)),
    }


def measure_signal(x, sr: int, *, low_band_hz: float = 120.0) -> dict:
    """Measure a signal [frames, channels] (1-D = mono) and return the vector."""
    a = _ld.as_frames(x)
    sr = int(sr)
    h = health(a)
    if h["sanitized"]:
        a = np.where(np.isfinite(a), a, 0.0)
    n, ch = a.shape
    notes: list[str] = []

    tp_ch = _ld.true_peak_per_channel(a, sr)
    tp = float(max(tp_ch)) if tp_ch else float("-inf")
    p03 = _ld.loudness_summary(a, sr, true_peak=tp)
    if n < int(_ld.SHORT_TERM_S * sr):
        notes.append("shorter than 3 s: short-term loudness and LRA are null")

    spec = Spectrum(a, sr)
    p04 = band_crest(spec, BANDS_P22, x=a)
    p07 = band_energy(spec, BANDS_P07)
    p07["partition_bands"] = band_energy(spec, BANDS_P22)["bands"]
    p07["note"] = ("'bands' follow SPEC P-07 (lowmid 200-800 Hz overlaps bass, fractions do not sum "
                   "to 1); 'partition_bands' are the contiguous P-22 bands (fractions sum to 1)")

    st = band_stereo(spec, BANDS_P22)
    if st is None:
        note = "mono input: stereo measures are not applicable"
        notes.append("P-05/P-06: " + note)
        p05 = {"available": False, "note": note, "bands": None, "full_band": None,
               "low_band_persistence": None}
        p06 = {"available": False, "note": note, "convention": MONO_CONVENTION, "bands": None,
               "full_band": None, "worst_band": None}
    else:
        if ch > 2:
            notes.append(f"{ch} channels: P-05/P-06 use channels 0 (L) and 1 (R) only")
        keys05 = ("correlation", "side_ratio", "range_hz", "silent")
        keys06 = ("level_change_db", "mono_loss_db", "cancelled", "range_hz", "silent")
        p05 = {"available": True, "note": None,
               "bands": {k: {kk: v[kk] for kk in keys05} for k, v in st["bands"].items()},
               "full_band": {kk: st["full_band"][kk] for kk in keys05},
               "low_band_persistence": low_band_negative_persistence(a, sr, cutoff_hz=low_band_hz)}
        bands06 = {k: {kk: v[kk] for kk in keys06} for k, v in st["bands"].items()}
        worst, worst_loss = None, -math.inf
        for k, v in bands06.items():
            loss = math.inf if v["cancelled"] else (v["mono_loss_db"] if v["mono_loss_db"] is not None else -math.inf)
            if loss > worst_loss:
                worst, worst_loss = k, loss
        p06 = {"available": True, "note": None, "convention": MONO_CONVENTION, "bands": bands06,
               "full_band": {kk: st["full_band"][kk] for kk in keys06}, "worst_band": worst}

    vec = {
        "analyzer_version": ANALYZER_VERSION,
        "sample_rate": sr,
        "channels": ch,
        "frames": n,
        "duration_s": n / sr if sr else 0.0,
        "P-03": p03,
        "P-04": p04,
        "P-05": p05,
        "P-06": p06,
        "P-07": p07,
        "P-14": {"true_peak_dbtp": tp, "true_peak_per_channel_dbtp": tp_ch,
                 "oversample": _ld.tp_oversample_factor(sr), "codec": None},
        "LTAS": {"erb": ltas(spec, "erb"), "third_octave": ltas(spec, "third_octave")},
        "health": h,
        "notes": notes,
    }
    return json_safe(vec)


def measure_file(path: str | Path, *, low_band_hz: float = 120.0) -> dict:
    """Read a file through audio_io (never resampled) and measure it."""
    data, sr = audio_io.read(path)
    vec = measure_signal(data, sr, low_band_hz=low_band_hz)
    vec["source"] = {"file_name": Path(path).name}
    return vec
