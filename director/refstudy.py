"""Reference study (原液経路, refstudy): measurements and signs of a user-supplied reference.

``direction ref study`` measures a reference master (2-mix) and/or its stems and
writes a deterministic Markdown digest, ``<kb>/references/works/<slug>/refstudy.md``.
The tool stops at measurements and signs (〔測定〕〔兆候〕); what the work was
aiming at is the director's 〔推定〕 in the analysis memo.

Rules kept here (docs: ``_private/design/UPDATE_PROPOSAL.md`` §1.2, §1.3, §1.5, §3):

- Every quantity is an existing measurement, called, never redefined:
  ``core.reference.measure_reference`` (whole vector, LTAS on ERB bands level
  matched to -23 LUFS), ``core.master_analysis`` (band energy ratios, mono
  loss, windowed correlation, section times), ``director.query`` (loudness,
  crest, band ratio, side ratio, correlation), ``core.cleanup.diagnose`` (HF
  ceiling = roll-off, HF spectral flatness) and ``core.ingest.naming`` (stem
  roles from ``knowledge/ingest_patterns.json``). Nothing in ``core`` changes.
- The audio is read into memory only. No copy, no conversion product and no
  file name is kept: the document records the content SHA-256, the format
  (sample rate, bit depth, lossy or not) and the length.
- Granularity: time resolution stops at sections, frequency at band
  aggregates. No frame series, spectrogram, waveform or full LTAS bins.
- Confidence caps are attached mechanically: lossy source -> HF conclusions
  low; separated (pseudo stems) -> everything medium at most.
- Deterministic: same input bytes -> same document bytes (fixed rounding, no
  clock, sorted keys, no absolute paths).
- The raw-reference path never writes the project's ``references`` (the core
  yardstick) nor ``knowledge/`` (U-1). It only writes under the kb root.

The core never imports this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from mankomix import ENGINE_VERSION
from mankomix import repo_data_root
from mankomix.core import audio_io
from mankomix.core import master_analysis as MA
from mankomix.core.measure.bands import BANDS_P22

from . import kb as kbmod
from . import query as Q

REFSTUDY_VERSION = 1
DEFAULT_KB = "_private/kb"            # UD-1: third-party measurements default to the private kb
ABSENT_LUFS = -60.0                   # same presence rule as the song dossier §3
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

BANDS = [{"id": b.name, "range_hz": [b.lo_hz, b.hi_hz]} for b in BANDS_P22]
BAND_IDS = [b["id"] for b in BANDS]
# low bands for the mono boundary (upper edges); band aggregates only
MONO_EDGES_HZ = (20.0, 40.0, 60.0, 80.0, 100.0, 120.0, 160.0, 200.0, 250.0, 320.0, 400.0, 500.0)
TILT_FIT_HZ = (100.0, 10000.0)        # LTAS slope fit range (dB per octave)
NEG_CORR_BAND_HZ = (20.0, 120.0)      # low band for the negative-correlation persistence
NEG_CORR_WINDOW_S = 0.4

MIN_SECTION_S = 1.0
MAX_SECTIONS = 23                     # the per-section stem table is 1 + sections columns (kb lint: <= 24)

# --- sign rules: thresholds (rule constants, not new measurement definitions) ---
LIMIT_RULE = {"plr_db_max": 9.0, "crest_db_max": 10.0, "near_peak_fraction_min": 0.005, "short_range_lu_max": 5.0}
NEAR_PEAK_DB = 1.0                    # "near the peak" = within 1 dB of the sample peak (head-flattening rate)
MONO_SIDE_DB_MAX = -20.0              # a low band counts as mono when side/mid is below this
CONTRAST_RULE = {"lufs_lu_min": 3.0, "width_db_min": 3.0, "band_db_min": 3.0}
LOSSY_HF_HZ = 16000.0                 # lossy codecs: conclusions about roughly >= 16 kHz are low
RESIDUAL_UNRELIABLE_DB = -6.0         # sum vs master residual above this -> the difference is unreliable
ALIGN_MAX_LAG_S = 0.5
ALIGN_WINDOW_S = 30.0

CONF_ORDER = ("low", "medium", "high")

STEM_NOTE = ("配布ステムは通常「処理済みの書き出し」で、見えるのは要素ごとの結果であり、処理そのもの"
             "（個別トラックの処理・使用機材・編集の経緯）ではない。")


class RefStudyError(ValueError):
    """Bad input for the raw-reference path (maps to an input error in the CLI)."""


class SeparationUnavailable(RuntimeError):
    """``--separate`` asked for but no usable separation model in this environment."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _f(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _r(v: Any, d: int = 2) -> float | None:
    f = _f(v)
    if f is None:
        return None
    out = round(f, d)
    return 0.0 if out == 0 else out


def _db10(v: float) -> float | None:
    return 10.0 * math.log10(v) if v and v > 0 else None


def _num(v: Any, d: int = 2, sign: bool = False) -> str:
    f = _f(v)
    if f is None:
        return "—"
    if abs(f) < 0.5 * 10.0 ** (-d):
        f = 0.0
    return f"{f:+.{d}f}" if sign else f"{f:.{d}f}"


SM_FLOOR_DB = -60.0


def _sm(v: Any) -> str:
    """Side/mid ratio for display: a centred (mono) source reads '<-60' instead of a huge negative number."""
    f = _f(v)
    if f is None:
        return "—"
    return f"<{SM_FLOOR_DB:g}" if f < SM_FLOOR_DB else _num(f, 1)


def _cell(v: Any) -> str:
    s = "—" if v is None or v == "" else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def _table(head: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        out.append("| " + " | ".join(_cell(c) for c in r) + " |")
    return out


def _stereo(x) -> np.ndarray:
    return MA.as_stereo(x)


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def cap_confidence(conf: str, cap: str | None) -> str:
    if cap is None or conf not in CONF_ORDER or cap not in CONF_ORDER:
        return conf
    return CONF_ORDER[min(CONF_ORDER.index(conf), CONF_ORDER.index(cap))]


def check_slug(slug: str, what: str = "work") -> str:
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        raise RefStudyError(f"bad {what} slug '{slug}': use lowercase letters, digits, '-' and '_' (max 64)")
    return slug


# ---------------------------------------------------------------------------
# material (no audio kept)
# ---------------------------------------------------------------------------

def _bit_depth(subtype: str) -> str:
    s = (subtype or "").upper()
    m = re.match(r"PCM_(?:S|U)?(\d+)", s)
    if m:
        return m.group(1)
    if s == "FLOAT":
        return "32f"
    if s == "DOUBLE":
        return "64f"
    return "—"


def _rate_text(sr: int) -> str:
    k = sr / 1000.0
    return f"{k:g}k"


def material_info(path: Path) -> dict:
    """Content hash, format and length of one audio file (the file name is not recorded)."""
    inf = audio_io.info(path)
    return {"sha256": _sha256_file(path), "sample_rate": int(inf.sample_rate),
            "bit_depth": _bit_depth(inf.subtype), "lossy": bool(inf.lossy),
            "format": f"{_rate_text(int(inf.sample_rate))}/{_bit_depth(inf.subtype)}",
            "channels": int(inf.channels), "duration_s": _r(inf.duration_s, 3)}


def read_audio(path: Path) -> tuple[np.ndarray, int]:
    x, sr = audio_io.read(path)
    return np.asarray(x, dtype=np.float64), int(sr)


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------

def load_sections(spec: Any, duration_s: float) -> list[dict]:
    """User sections: a JSON list of {id, start_s, end_s} (or {"sections": [...]})."""
    if isinstance(spec, dict):
        spec = spec.get("sections")
    if not isinstance(spec, list) or not spec:
        raise RefStudyError("--sections must be a non-empty JSON list of {id, start_s, end_s}")
    if len(spec) > MAX_SECTIONS:
        raise RefStudyError(f"--sections: at most {MAX_SECTIONS} sections (granularity stops at sections)")
    out, seen = [], set()
    for i, s in enumerate(spec):
        if not isinstance(s, dict):
            raise RefStudyError(f"--sections[{i}] must be an object")
        sid = str(s.get("id") or f"s{i + 1}")
        if sid in seen:
            raise RefStudyError(f"--sections: duplicate id '{sid}'")
        seen.add(sid)
        a, b = _f(s.get("start_s")), _f(s.get("end_s"))
        if a is None or b is None:
            raise RefStudyError(f"--sections[{i}] needs numeric start_s and end_s")
        a, b = max(0.0, a), min(float(duration_s), b)
        if b - a < MIN_SECTION_S:
            raise RefStudyError(f"--sections: '{sid}' is shorter than {MIN_SECTION_S:g} s (inside the audio)")
        out.append({"id": sid, "start_s": _r(a, 3), "end_s": _r(b, 3), "label": s.get("label")})
    return out


def auto_sections(x: np.ndarray, sr: int) -> list[dict]:
    """``master_analysis.section_times``: the loudest and the quietest 3 s regions."""
    st = MA.section_times(x, sr)
    dur = float(st["duration_s"])
    out = []
    for sid, key in (("loudest", "loudest_start_s"), ("quietest", "quietest_start_s")):
        t0 = _f(st.get(key))
        if t0 is None:
            continue
        t1 = min(dur, t0 + 3.0)
        if t1 - t0 >= MIN_SECTION_S:
            out.append({"id": sid, "start_s": _r(t0, 3), "end_s": _r(t1, 3), "label": None})
    return out


# ---------------------------------------------------------------------------
# measurements (all existing definitions)
# ---------------------------------------------------------------------------

def _obs(x: np.ndarray, sr: int, prim: str, rng: tuple[float, float] | None = None, **kw) -> float | None:
    o = {"primitive": prim, **kw}
    if rng is not None:
        o["section"] = {"t0_s": rng[0], "t1_s": rng[1]}
    try:
        r = Q.observe(x, sr, o)
    except Q.QueryError:
        return None
    return _f(r.get("value")) if r.get("status") == "ok" else None


def _seg(x: np.ndarray, sr: int, rng: tuple[float, float] | None) -> np.ndarray:
    if rng is None:
        return x
    return x[int(round(rng[0] * sr)):int(round(rng[1] * sr))]


def band_fractions(x: np.ndarray, sr: int) -> dict:
    """Band energy ratios (fractions of the mid power) on the P-22 partition bands."""
    r = MA.band_energy_ratios(x, sr, BANDS)
    return {k: _r(v, 5) for k, v in r.items()}


def segment_measure(x: np.ndarray, sr: int, rng: tuple[float, float] | None = None) -> dict:
    """Loudness, crest, width and band distribution of the whole signal or one section."""
    seg = _seg(x, sr, rng)
    out = {
        "lufs_i": _r(_obs(x, sr, "loudness", rng, stat="integrated"), 2),
        "short_max": _r(_obs(x, sr, "loudness", rng, stat="short_max"), 2),
        "crest_db": _r(_obs(x, sr, "crest", rng), 2),
        "side_ratio_db": _r(_obs(x, sr, "side_ratio", rng), 2),
        "correlation": _r(_obs(x, sr, "correlation", rng), 3),
        "bands": band_fractions(seg, sr),
    }
    return out


def _tilt(ltas: dict | None) -> float | None:
    """Slope (dB per octave) of the level-matched ERB LTAS fitted over TILT_FIT_HZ."""
    if not ltas:
        return None
    c = np.asarray([_f(v) if _f(v) is not None else np.nan for v in ltas.get("centers_hz") or []], float)
    lv = np.asarray([_f(v) if _f(v) is not None else np.nan for v in ltas.get("level_db") or []], float)
    if c.size == 0 or c.size != lv.size:
        return None
    m = np.isfinite(c) & np.isfinite(lv) & (c >= TILT_FIT_HZ[0]) & (c <= TILT_FIT_HZ[1]) & (lv > -150.0)
    if m.sum() < 4:
        return None
    slope = np.polyfit(np.log2(c[m]), lv[m], 1)[0]
    return float(slope)


def _ltas_band_means(ltas: dict | None) -> dict:
    """Mean ERB LTAS level (dB) inside each P-22 band (aggregate only)."""
    out = {}
    if not ltas:
        return {b: None for b in BAND_IDS}
    c = np.asarray([_f(v) if _f(v) is not None else np.nan for v in ltas.get("centers_hz") or []], float)
    lv = np.asarray([_f(v) if _f(v) is not None else np.nan for v in ltas.get("level_db") or []], float)
    for b in BANDS:
        lo, hi = b["range_hz"]
        m = np.isfinite(c) & np.isfinite(lv) & (c >= lo) & (c < hi)
        out[b["id"]] = float(np.mean(lv[m])) if m.any() else None
    return out


def near_peak_fraction(x: np.ndarray) -> float | None:
    """Fraction of samples within NEAR_PEAK_DB of the sample peak (head-flattening rate)."""
    a = np.abs(_stereo(x))
    peak = float(a.max()) if a.size else 0.0
    if peak <= 0:
        return None
    thr = peak * 10.0 ** (-NEAR_PEAK_DB / 20.0)
    return float(np.mean(a >= thr))


def hf_metrics(x: np.ndarray, sr: int) -> dict:
    """Roll-off (HF ceiling) and HF noisiness (spectral flatness) from the cleanup diagnosis (P-16)."""
    from mankomix.core.cleanup.diagnose import noise_shimmer_metrics
    m = noise_shimmer_metrics(_stereo(x), sr, with_clicks=False)
    return {"rolloff_hz": _r(m.get("hf_ceiling_hz"), 0), "rolloff_drop_db": _r(m.get("hf_ceiling_drop_db"), 1),
            "flatness": _r(m.get("shimmer_flatness"), 4), "shimmer_index_db": _r(m.get("shimmer_index_db"), 2)}


def spatial_measure(x: np.ndarray, sr: int) -> dict:
    a = _stereo(x)
    bands = {}
    for b in BANDS:
        lo, hi = b["range_hz"]
        if lo >= sr / 2.0:
            continue
        bands[b["id"]] = {
            "side_ratio_db": _r(_obs(a, sr, "side_ratio", None, band_hz=[lo, hi]), 2),
            "correlation": _r(_obs(a, sr, "correlation", None, band_hz=[lo, hi]), 3),
            "mono_loss_db": _r(MA.mono_loss_db(a, sr, lo, hi), 2),
        }
    low = []
    for lo, hi in zip(MONO_EDGES_HZ[:-1], MONO_EDGES_HZ[1:]):
        low.append({"band_hz": [lo, hi], "side_ratio_db": _r(_obs(a, sr, "side_ratio", None, band_hz=[lo, hi]), 2)})
    corr = MA.windowed_correlation(a, sr, NEG_CORR_BAND_HZ[0], NEG_CORR_BAND_HZ[1], NEG_CORR_WINDOW_S)
    neg = MA.negative_persistence(corr, NEG_CORR_WINDOW_S)
    return {"bands": bands, "low_side": low,
            "negative": {"longest_run_s": _r(neg.get("longest_run_s"), 2),
                         "negative_fraction": _r(neg.get("negative_fraction"), 4),
                         "min_corr": _r(neg.get("min_corr"), 3)}}


def mono_boundary_hz(low_side: list[dict]) -> float | None:
    """Upper edge of the contiguous run of low bands (from the bottom) whose side/mid is below the threshold."""
    edge = None
    for row in low_side:
        v = _f(row.get("side_ratio_db"))
        if v is None or v >= MONO_SIDE_DB_MAX:
            break
        edge = float(row["band_hz"][1])
    return edge


def master_measure(x: np.ndarray, sr: int, sections: list[dict]) -> dict:
    """Everything §1.2 lists for a 2-mix (whole, bands, space, HF, sections)."""
    from mankomix.core.reference import measure_reference
    x = _stereo(x)
    vec = measure_reference(x, sr)
    p03 = (vec.get("measure") or {}).get("P-03") or {}
    p04 = ((vec.get("measure") or {}).get("P-04") or {}).get("bands") or {}
    whole = segment_measure(x, sr, None)
    st_p10, st_p95 = _f(p03.get("short_term_p10")), _f(p03.get("short_term_p95"))
    dyn = {
        "lufs_i": _r(p03.get("integrated_lufs"), 2),
        "short_p50": _r(p03.get("short_term_p50"), 2),
        "short_p95": _r(st_p95, 2),
        "short_max": _r(p03.get("short_term_max_lufs"), 2),
        "short_range_lu": _r(st_p95 - st_p10, 2) if st_p95 is not None and st_p10 is not None else None,
        "lra_lu": _r(p03.get("lra_lu"), 2),
        "true_peak_dbtp": _r(p03.get("true_peak_dbtp"), 2),
        "plr_db": _r(p03.get("plr_db"), 2),
        "psr_db": _r(p03.get("psr_db"), 2),
        "crest_db": whole["crest_db"],
        "near_peak_fraction": _r(near_peak_fraction(x), 5),
    }
    ltas = vec.get("ltas_erb") or {}
    band_crest = {b: _r((p04.get(b) or {}).get("crest_db"), 2) for b in BAND_IDS}
    spatial = spatial_measure(x, sr)
    hf = hf_metrics(x, sr)
    secs = []
    for s in sections:
        m = segment_measure(x, sr, (float(s["start_s"]), float(s["end_s"])))
        secs.append({"id": s["id"], "start_s": s["start_s"], "end_s": s["end_s"], **m})
    perc = vec.get("perceptual") or {}
    music = vec.get("music") or {}
    return {
        "duration_s": _r(vec.get("duration_s"), 3),
        "dynamics": dyn,
        "bands": whole["bands"],
        "band_crest_db": band_crest,
        "ltas_band_db": {k: _r(v, 2) for k, v in _ltas_band_means(ltas).items()},
        "tilt_db_per_oct": _r(_tilt(ltas), 3),
        "level_match": {"target_lufs": _r((vec.get("level_match") or {}).get("target_lufs"), 1),
                        "gain_db": _r((vec.get("level_match") or {}).get("gain_db"), 2)},
        "width": {"side_ratio_db": whole["side_ratio_db"], "correlation": whole["correlation"]},
        "spatial": spatial,
        "mono_boundary_hz": mono_boundary_hz(spatial["low_side"]),
        "hf": {**hf, "air_fraction": whole["bands"].get("air")},
        "vector": {
            "P-11": _r((perc.get("P-11") or {}).get("ltas_prominence_db"), 2),
            "P-17": _r((perc.get("P-17") or {}).get("p99_prominence_db"), 2),
            "P-19": _r((perc.get("P-19") or {}).get("rms_deviation_db"), 2),
            "P-20": _r((perc.get("P-20") or {}).get("contrast_db"), 2),
            "bpm": _r(music.get("bpm"), 1), "bpm_confidence": _r(music.get("bpm_confidence"), 2),
            "key": music.get("key"), "key_confidence": _r(music.get("key_confidence"), 2),
        },
        "sections": secs,
        "ltas_raw": ltas,       # kept in memory for the sum/master difference; never rendered
    }


def section_summary(secs: list[dict]) -> dict:
    usable = [s for s in secs if _f(s.get("lufs_i")) is not None]
    if not usable:
        return {"max": None, "min": None}
    mx = max(usable, key=lambda s: (float(s["lufs_i"]), s["id"]))
    mn = min(usable, key=lambda s: (float(s["lufs_i"]), s["id"]))
    return {"max": mx["id"], "min": mn["id"]}


# ---------------------------------------------------------------------------
# stems
# ---------------------------------------------------------------------------

def _role_vocabulary() -> list[str]:
    data = json.loads((repo_data_root() / "knowledge" / "ingest_patterns.json").read_text(encoding="utf-8"))
    return list(data.get("role_vocabulary") or [])


def assign_roles(names: list[str], overrides: dict | None = None) -> list[dict]:
    """Roles of the files of a stem folder (ingest naming rules; unassigned -> 'other'; --roles wins).

    Full mixes and derived sums are excluded (they would add the same sound twice)."""
    from mankomix.core.ingest import naming
    vocab = set(_role_vocabulary())
    overrides = dict(overrides or {})
    for k, v in overrides.items():
        if v not in vocab or v == "fullmix":
            raise RefStudyError(f"--roles: '{v}' is not a stem role of the vocabulary")
    if len(names) > 1:
        entries = naming.classify(names)["entries"]
    else:   # a lone file would be read as a full mix by classify(); a stem folder means stems
        role, src = naming.keyword_role(naming.stem_of(names[0]))
        entries = [{"original_name": names[0], "role": role, "role_source": src, "derived_sum": False}]
    out = []
    for e in entries:
        name = e["original_name"]
        key = naming.stem_of(name)
        role, src = e.get("role") or "other", e.get("role_source") or "default"
        excluded = None
        if name in overrides or key in overrides:
            role, src = overrides.get(name, overrides.get(key)), "user"
        elif e.get("derived_sum"):
            excluded = "derived_sum"
        elif role == "fullmix":
            excluded = "fullmix"
        if role not in vocab:
            role = "other"
        out.append({"name": name, "role": role, "role_source": src, "excluded": excluded})
    unknown = sorted(set(overrides) - {o["name"] for o in out} - {naming.stem_of(o["name"]) for o in out})
    if unknown:
        raise RefStudyError("--roles names files that are not in the stem folder")
    return out


def _sum(arrs: list[np.ndarray]) -> np.ndarray:
    n = max(a.shape[0] for a in arrs)
    out = np.zeros((n, 2))
    for a in arrs:
        out[: a.shape[0]] += _stereo(a)
    return out


def _lufs(x: np.ndarray, sr: int) -> float | None:
    if x.shape[0] < int(0.4 * sr):
        return None
    return _f(Q.integrated_lufs(x, sr))


def _lr_diff_db(x: np.ndarray) -> float | None:
    a = _stereo(x)
    el, er = float(np.mean(a[:, 0] ** 2)), float(np.mean(a[:, 1] ** 2))
    if el <= 1e-20 and er <= 1e-20:
        return None
    return 10.0 * math.log10(max(el, 1e-20) / max(er, 1e-20))


def _p22_params() -> dict:
    data = json.loads((repo_data_root() / "knowledge" / "masking_model.json").read_text(encoding="utf-8"))
    return data.get("p22") or {}


def _welch(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray] | None:
    from scipy.signal import welch
    mid = _stereo(x).mean(axis=1)
    if mid.size < 256:
        return None
    return welch(mid, fs=sr, nperseg=min(8192, mid.size))


def _band_power(spec: tuple | None, sr: int, lo: float, hi: float) -> float:
    """Band power of the mid channel (same Welch estimate as ``master_analysis.band_energy_ratios``)."""
    if spec is None:
        return 0.0
    f, p = spec
    m = (f >= lo) & (f < min(hi, sr / 2.0))
    return float(np.sum(p[m]))


def stem_relations(by_role: dict[str, np.ndarray], sr: int, sections: list[dict]) -> dict:
    """Relations between stems with the song dossier §5 definitions (lead vs the rest, the low end
    shared by drums and bass, band owners with the P-22 rule of knowledge/masking_model.json)."""
    roles = sorted(by_role)
    spec = {r: _welch(by_role[r], sr) for r in roles}
    rel: dict[str, Any] = {}
    lead = "vocals" if "vocals" in by_role else None
    if lead and len(roles) > 1:
        rest = _sum([by_role[r] for r in roles if r != lead])
        vals = {"all": None}
        lv, rv = _lufs(by_role[lead], sr), _lufs(rest, sr)
        vals["all"] = _r(lv - rv, 2) if lv is not None and rv is not None else None
        for s in sections:
            a, b = int(round(float(s["start_s"]) * sr)), int(round(float(s["end_s"]) * sr))
            lv, rv = _lufs(by_role[lead][a:b], sr), _lufs(rest[a:b], sr)
            vals[s["id"]] = _r(lv - rv, 2) if lv is not None and rv is not None and lv >= ABSENT_LUFS else None
        rel["lead_vs_rest_lu"] = {"lead": lead, "values": vals}
    else:
        rel["lead_vs_rest_lu"] = None
    if "drums" in by_role and "bass" in by_role:
        low = {}
        for name, (lo, hi) in (("sub", (20.0, 60.0)), ("bass", (60.0, 250.0))):
            pd, pb = _band_power(spec["drums"], sr, lo, hi), _band_power(spec["bass"], sr, lo, hi)
            low[name] = {"drums_db": _r(_db10(pd), 2), "bass_db": _r(_db10(pb), 2),
                         "drums_share": _r(pd / (pd + pb), 3) if pd + pb > 0 else None}
        rel["low_share"] = low
    else:
        rel["low_share"] = None
    p22 = _p22_params()
    within = float(p22.get("within_db", 6.0))
    min_share = float(p22.get("min_share", 0.05))
    owners = {}
    for bid, (lo, hi) in (p22.get("bands_hz") or {}).items():
        pw = {r: _band_power(spec[r], sr, float(lo), float(hi)) for r in roles}
        tot = sum(pw.values())
        top = max(pw.values()) if pw else 0.0
        if tot <= 0 or top <= 0:
            owners[bid] = []
            continue
        owners[bid] = [r for r in roles if pw[r] > 0 and 10.0 * math.log10(pw[r] / top) >= -within
                       and pw[r] / tot >= min_share]
    rel["band_owners"] = owners
    rel["band_owner_rule"] = {"within_db": within, "min_share": min_share}
    return rel


def _band_crest(x: np.ndarray, sr: int) -> dict:
    """P-04 band crest (the measurement vector's definition, without the rest of the vector)."""
    from mankomix.core.measure.bands import Spectrum
    from mankomix.core.measure.spectral import band_crest
    a = _stereo(x)
    return (band_crest(Spectrum(a, sr), BANDS_P22, x=a) or {}).get("bands") or {}


def stems_measure(by_role: dict[str, np.ndarray], sr: int, sections: list[dict]) -> dict:
    """Per-role quantities (§1.3) and the relations between the stems."""
    roles = sorted(by_role)
    total = _sum([by_role[r] for r in roles])
    sum_lufs = _lufs(total, sr)
    sec_sum = []
    for s in sections:
        a, b = int(round(float(s["start_s"]) * sr)), int(round(float(s["end_s"]) * sr))
        sec_sum.append(_lufs(total[a:b], sr))
    rows = {}
    for r in roles:
        x = _stereo(by_role[r])
        lu = _lufs(x, sr)
        p04 = _band_crest(x, sr)
        per_sec = []
        for s, ssum in zip(sections, sec_sum):
            a, b = int(round(float(s["start_s"]) * sr)), int(round(float(s["end_s"]) * sr))
            v = _lufs(x[a:b], sr)
            present = v is not None and v >= ABSENT_LUFS
            per_sec.append({"id": s["id"], "present": present,
                            "rel_lu": _r(v - ssum, 2) if present and ssum is not None else None})
        rows[r] = {
            "lufs_i": _r(lu, 2),
            "rel_lu": _r(lu - sum_lufs, 2) if lu is not None and sum_lufs is not None else None,
            "lr_diff_db": _r(_lr_diff_db(x), 2),
            "side_ratio_db": _r(_obs(x, sr, "side_ratio"), 2),
            "correlation": _r(_obs(x, sr, "correlation"), 3),
            "crest_db": _r(_obs(x, sr, "crest"), 2),
            "band_crest_db": {b: _r((p04.get(b) or {}).get("crest_db"), 2) for b in BAND_IDS},
            "bands": band_fractions(x, sr),
            "sections": per_sec,
            "present_fraction": _r(sum(1 for p in per_sec if p["present"]) / len(per_sec), 3) if per_sec else None,
        }
    return {"sum_lufs": _r(sum_lufs, 2), "roles": rows, "relations": stem_relations(by_role, sr, sections)}


# ---------------------------------------------------------------------------
# sum vs master (T-6)
# ---------------------------------------------------------------------------

def align_lag(master: np.ndarray, total: np.ndarray, sr: int) -> int:
    """Lag (samples) that best aligns the stem sum to the master (positive: the sum is late)."""
    from scipy.signal import fftconvolve
    n = min(master.shape[0], total.shape[0], int(ALIGN_WINDOW_S * sr))
    if n < int(0.5 * sr):
        return 0
    a = _stereo(master)[:n].mean(axis=1)
    b = _stereo(total)[:n].mean(axis=1)
    corr = fftconvolve(b, a[::-1], mode="full")
    lags = np.arange(-n + 1, n)
    maxlag = int(ALIGN_MAX_LAG_S * sr)
    m = np.abs(lags) <= maxlag
    i = int(np.argmax(np.abs(corr[m])))
    return int(lags[m][i])


def _shift(x: np.ndarray, lag: int, n: int) -> np.ndarray:
    """x moved earlier by lag samples (lag > 0) or later (lag < 0), cut / padded to n frames."""
    a = _stereo(x)
    if lag > 0:
        a = a[lag:]
    elif lag < 0:
        a = np.concatenate([np.zeros((-lag, 2)), a])
    if a.shape[0] < n:
        a = np.concatenate([a, np.zeros((n - a.shape[0], 2))])
    return a[:n]


def band_residual_db(master: np.ndarray, total: np.ndarray, sr: int) -> dict:
    """Residual of the master after the best gain per band (P-22 bands): EQ-like differences are
    absorbed, what the stems cannot reproduce remains. dB relative to the master energy."""
    res, ref = 0.0, 0.0
    per = {}
    for b in BANDS:
        lo, hi = b["range_hz"]
        if lo >= sr / 2.0:
            continue
        m = MA.band_filter(master, sr, lo, hi)
        s = MA.band_filter(total, sr, lo, hi)
        ss = float(np.sum(s * s))
        g = float(np.sum(m * s)) / ss if ss > 0 else 0.0
        e = m - g * s
        em, ee = float(np.sum(m * m)), float(np.sum(e * e))
        res += ee
        ref += em
        per[b["id"]] = _r(10.0 * math.log10(max(ee, 1e-30) / em), 2) if em > 0 else None
    return {"total_db": _r(10.0 * math.log10(max(res, 1e-30) / ref), 2) if ref > 0 else None, "bands": per}


def sum_master_difference(master: np.ndarray, total: np.ndarray, sr: int,
                          m_meas: dict | None = None) -> dict:
    """§1.3: align the stem sum to the master in time and gain, then measure the difference."""
    from mankomix.core.reference import measure_reference
    lag = align_lag(master, total, sr)
    n = min(_stereo(master).shape[0], _stereo(total).shape[0] - max(lag, 0))
    n = max(n, 0)
    m = _stereo(master)[:n]
    s = _shift(total, lag, n)
    lm, ls = _lufs(m, sr), _lufs(s, sr)
    gain = (lm - ls) if lm is not None and ls is not None else 0.0
    s_g = s * 10.0 ** (gain / 20.0)
    mm = m_meas or {}
    m_ltas = mm.get("ltas_raw") or measure_reference(m, sr).get("ltas_erb") or {}
    s_vec = measure_reference(s_g, sr)
    s_ltas = s_vec.get("ltas_erb") or {}
    mb, sb = _ltas_band_means(m_ltas), _ltas_band_means(s_ltas)
    ltas_diff = {b: _r(mb[b] - sb[b], 2) if mb.get(b) is not None and sb.get(b) is not None else None
                 for b in BAND_IDS}
    tm, ts = _tilt(m_ltas), _tilt(s_ltas)
    # slope of the per-centre difference (ERB centres, both level matched to the same level)
    diff_slope = None
    c1 = m_ltas.get("centers_hz") or []
    c2 = s_ltas.get("centers_hz") or []
    if c1 and len(c1) == len(c2):
        d = {"centers_hz": c1, "level_db": [(_f(a) - _f(b)) if _f(a) is not None and _f(b) is not None else None
                                            for a, b in zip(m_ltas.get("level_db") or [], s_ltas.get("level_db") or [])]}
        cs = np.asarray(c1, float)
        lv = np.asarray([v if v is not None else np.nan for v in d["level_db"]], float)
        msk = np.isfinite(lv) & (cs >= TILT_FIT_HZ[0]) & (cs <= TILT_FIT_HZ[1])
        if msk.sum() >= 4:
            diff_slope = float(np.polyfit(np.log2(cs[msk]), lv[msk], 1)[0])
    cm, cs_ = _obs(m, sr, "crest"), _obs(s_g, sr, "crest")
    wm, ws = _obs(m, sr, "side_ratio"), _obs(s_g, sr, "side_ratio")
    s_p03 = (s_vec.get("measure") or {}).get("P-03") or {}
    m_plr = (mm.get("dynamics") or {}).get("plr_db")
    resid = band_residual_db(m, s_g, sr)
    den = math.sqrt(float(np.sum(m * m)) * float(np.sum(s_g * s_g)))
    corr = float(np.sum(m * s_g)) / den if den > 0 else None
    unreliable = resid["total_db"] is None or resid["total_db"] > RESIDUAL_UNRELIABLE_DB
    return {
        "lag_samples": int(lag), "lag_ms": _r(1000.0 * lag / sr, 2),
        "gain_db": _r(gain, 2),
        "lufs_diff_lu": _r(gain, 2),
        "ltas_diff_db": ltas_diff,
        "ltas_diff_slope_db_per_oct": _r(diff_slope, 3),
        "tilt_master": _r(tm, 3), "tilt_sum": _r(ts, 3),
        "crest_diff_db": _r(cm - cs_, 2) if cm is not None and cs_ is not None else None,
        "plr_diff_db": _r(_f(m_plr) - _f(s_p03.get("plr_db")), 2)
        if _f(m_plr) is not None and _f(s_p03.get("plr_db")) is not None else None,
        "width_diff_db": _r(wm - ws, 2) if wm is not None and ws is not None else None,
        "residual": resid,
        "correlation": _r(corr, 4),
        "reliable": not unreliable,
    }


# ---------------------------------------------------------------------------
# signs (rules)
# ---------------------------------------------------------------------------

def _sign(rule: str, title: str, raised: bool, finding: str, evidence: list[tuple[str, Any]], conf: str,
          scope: str) -> dict:
    return {"rule": rule, "title": title, "raised": bool(raised), "finding": finding,
            "evidence": [(k, v) for k, v in evidence], "confidence": conf if raised else None, "scope": scope}


def signs(meas: dict, summary: dict) -> list[dict]:
    """The five initial sign rules of §1.2. Facts from measurements; no intent is stated."""
    out = []
    d = meas["dynamics"]
    checks = [
        ("PLR dB", d.get("plr_db"), _f(d.get("plr_db")) is not None and d["plr_db"] <= LIMIT_RULE["plr_db_max"],
         f"≤ {LIMIT_RULE['plr_db_max']:g}"),
        ("広帯域クレスト dB", d.get("crest_db"),
         _f(d.get("crest_db")) is not None and d["crest_db"] <= LIMIT_RULE["crest_db_max"], f"≤ {LIMIT_RULE['crest_db_max']:g}"),
        ("短期ラウドネスの幅 p95−p10 LU", d.get("short_range_lu"),
         _f(d.get("short_range_lu")) is not None and d["short_range_lu"] <= LIMIT_RULE["short_range_lu_max"],
         f"≤ {LIMIT_RULE['short_range_lu_max']:g}"),
        (f"ピーク −{NEAR_PEAK_DB:g} dB 以内の割合（頭打ち率）", d.get("near_peak_fraction"),
         _f(d.get("near_peak_fraction")) is not None and d["near_peak_fraction"] >= LIMIT_RULE["near_peak_fraction_min"],
         f"≥ {LIMIT_RULE['near_peak_fraction_min']:g}"),
    ]
    k = sum(1 for c in checks if c[2])
    grade = "強い" if k >= 3 else ("中程度" if k == 2 else ("弱い" if k == 1 else "なし"))
    out.append(_sign("RS-LIMIT", "最終段の抑え込みの強さ", k >= 1,
                     f"抑え込みの兆候: {grade}（4 指標中 {k} が閾値の側）",
                     [(f"{c[0]}（{c[3]}{'、該当' if c[2] else ''}）", c[1]) for c in checks],
                     "medium" if k >= 2 else "low", "all"))
    mb = meas.get("mono_boundary_hz")
    first = (meas["spatial"]["low_side"] or [{}])[0].get("side_ratio_db")
    out.append(_sign("RS-MONO-LOW", "低域のモノ化の境界", mb is not None and mb >= 60.0,
                     (f"低域は {mb:g} Hz までモノ（S/M < {MONO_SIDE_DB_MAX:g} dB の帯域が下から連続）" if mb is not None
                      else f"最低帯域から S/M ≥ {MONO_SIDE_DB_MAX:g} dB（モノ化の境界は見えない）"),
                     [("境界 Hz", mb), ("20–40 Hz の S/M dB", first), ("閾値 S/M dB", MONO_SIDE_DB_MAX)],
                     "high", "all"))
    hf = meas["hf"]
    ro = hf.get("rolloff_hz")
    out.append(_sign("RS-HF", "高域の扱い", ro is not None,
                     (f"{ro / 1000:.1f} kHz より上が急に落ちる（ロールオフ）" if ro is not None
                      else "上端の急な落ち込みは検出されない（全帯域）"),
                     [("エア帯（6–20 kHz）の比", hf.get("air_fraction")), ("ロールオフ Hz", ro),
                      ("落ち込み dB", hf.get("rolloff_drop_db")), ("高域の平坦度（雑音性）", hf.get("flatness"))],
                     "high", "hf"))
    secs = {s["id"]: s for s in meas.get("sections") or []}
    mx, mn = secs.get(summary.get("max") or ""), secs.get(summary.get("min") or "")
    if mx and mn and mx is not mn:
        dl = _f(mx.get("lufs_i")) - _f(mn.get("lufs_i")) if _f(mx.get("lufs_i")) is not None and _f(mn.get("lufs_i")) is not None else None
        dw = _f(mx.get("side_ratio_db")) - _f(mn.get("side_ratio_db")) \
            if _f(mx.get("side_ratio_db")) is not None and _f(mn.get("side_ratio_db")) is not None else None
        db_, band_ = None, None
        for b in BAND_IDS:
            a, c = _f((mx.get("bands") or {}).get(b)), _f((mn.get("bands") or {}).get(b))
            if a and c and a > 0 and c > 0:
                v = 10.0 * math.log10(a / c)
                if db_ is None or abs(v) > abs(db_):
                    db_, band_ = v, b
        hits = [dl is not None and abs(dl) >= CONTRAST_RULE["lufs_lu_min"],
                dw is not None and abs(dw) >= CONTRAST_RULE["width_db_min"],
                db_ is not None and abs(db_) >= CONTRAST_RULE["band_db_min"]]
        k2 = sum(hits)
        out.append(_sign("RS-CONTRAST", "区間コントラスト", k2 >= 1,
                         f"最大区間 `{mx['id']}` と最小区間 `{mn['id']}` の差: 3 指標中 {k2} が閾値以上",
                         [("ラウドネス差 LU", _r(dl, 2)), ("幅の差（S/M）dB", _r(dw, 2)),
                          (f"帯域比の差 dB（最大の帯域 {band_ or '—'}）", _r(db_, 2))],
                         "medium" if k2 >= 2 else "low", "sections"))
    else:
        out.append(_sign("RS-CONTRAST", "区間コントラスト", False, "比べる区間が 2 つ未満", [], "low", "sections"))
    tp = d.get("true_peak_dbtp")
    li = d.get("lufs_i")
    out.append(_sign("RS-DELIVERY", "納品ラウドネスの帯", li is not None,
                     (f"LUFS-I {_num(li, 1)}（1 LU 刻みの帯 {round(li):d}）、TP {_num(tp, 2)} dBTP" if li is not None
                      else "測定不能"),
                     [("LUFS-I", li), ("トゥルーピーク dBTP", tp)], "high", "all"))
    return out


def apply_caps(sgns: list[dict], *, lossy: bool, separated: bool) -> list[dict]:
    """Mechanical confidence caps: lossy -> HF low; separated -> medium at most."""
    for s in sgns:
        cap = None
        reasons = []
        if separated:
            cap = "medium"
            reasons.append("分離由来")
        if lossy and s["scope"] == "hf":
            cap = "low"
            reasons.append("非可逆音源の高域")
        s["cap"] = cap
        s["cap_reason"] = "、".join(reasons) or None
        if s["confidence"] is not None:
            s["confidence"] = cap_confidence(s["confidence"], cap)
    return sgns


def caps_lines(*, lossy: bool, separated: bool, diff_reliable: bool | None) -> list[str]:
    out = []
    if lossy:
        out.append(f"- 非可逆音源: 高域（おおむね {LOSSY_HF_HZ / 1000:g} kHz 以上）に関する結論の確度は **low** が上限")
    if separated:
        out.append("- `origin: separated`（分離で得た擬似ステム）: すべての結論の確度は **medium** が上限")
    if diff_reliable is False:
        out.append("- 和とマスターの差分は**信頼できない**（合わせた後の残差が大きい）: 差分から引く結論は **low** が上限")
    if not out:
        out.append("- 機械的な上限なし（可逆音源・分離なし）。確度の規則（high／medium／low）はそのまま適用する")
    out.append("- 指揮者は分析メモでこの上限を超える確度を書けない（関門で見る）")
    return out


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _frac_db(v: Any) -> str:
    f = _f(v)
    return _num(10.0 * math.log10(f), 1) if f is not None and f > 0 else "—"


KV_LOUDNESS = (
    ("lufs_i", "積分ラウドネス LUFS-I", 2), ("short_p50", "短期ラウドネス p50 LUFS", 2),
    ("short_p95", "短期ラウドネス p95 LUFS", 2), ("short_max", "短期ラウドネス 最大 LUFS", 2),
    ("short_range_lu", "短期ラウドネスの幅 p95−p10 LU", 2), ("lra_lu", "LRA LU", 2),
    ("true_peak_dbtp", "トゥルーピーク dBTP", 2), ("plr_db", "PLR dB", 2), ("psr_db", "PSR dB", 2),
    ("crest_db", "広帯域クレスト dB", 2), ("near_peak_fraction", f"ピーク −{NEAR_PEAK_DB:g} dB 以内の割合", 5),
)


def render(study: dict) -> str:
    m = study.get("master")
    st = study.get("stems")
    lines = [f"# 測定資料（refstudy）: work_{study['work']}", "",
             "<!-- 機械生成（mankomix direction ref study）。手で編集しない。 -->", "",
             f"- 版: refstudy {REFSTUDY_VERSION} / engine mankomix {ENGINE_VERSION}",
             f"- origin: `{study['origin']}`",
             "- 道具が出すのは〔測定〕と〔兆候〕まで。作品の意図・傾向の読みは指揮者が分析メモに〔推定〕（確度つき）として書く",
             "- 粒度: 時間は区間単位、周波数は帯域集計まで。フレーム列・スペクトログラム・波形・LTAS の全ビンは載せない",
             ""]
    # 1. materials
    lines += ["## 1. 素材", ""]
    rows = []
    for mat in study["materials"]:
        rows.append([mat["type"], f"`{mat['sha256']}`" if mat.get("sha256") else f"`{mat.get('sha256_set')}`（集合）",
                     mat.get("format") or "—", "はい" if mat.get("lossy") else "いいえ",
                     mat.get("count") or 1, _num(mat.get("duration_s"), 3)])
    lines += _table(["種類", "SHA-256", "形式", "非可逆", "本数", "長さ s"], rows)
    lines += ["", "- 音声は読み込んで測っただけで、複製・変換物・ファイル名は残していない", ""]
    # 2. caps
    lines += ["## 2. 確度の上限（機械的付記）", ""]
    lines += caps_lines(lossy=study["lossy"], separated=study["origin"] == "separated",
                        diff_reliable=(study.get("difference") or {}).get("reliable") if study.get("difference") else None)
    lines += ["", "確度の規則: high = 直接の測定で比較条件が揃う／medium = 独立な測定 2 つ以上が同じ向き／"
              "low = 兆候 1 つだけ・分離由来・非可逆音源の高域・編成が大きく違う", ""]
    if m:
        lines += _render_master(m, study)
    else:
        lines += ["## 3. マスター", "", "- マスターの持ち込みなし（`--master` 未指定）", "",
                  "## 4. 区間", "", "- マスターがないため空欄", "", "## 5. 兆候", "", "- マスターがないため空欄", ""]
    if st:
        lines += _render_stems(st, study)
    else:
        lines += ["## 6. ステム", "", "- ステムの持ち込みなし（`--stems` 未指定）", ""]
    lines += ["## 7. 和とマスターの差分", ""]
    if study.get("difference"):
        lines += _render_difference(study["difference"])
    else:
        lines += ["- ステムとマスターの両方がないため空欄", ""]
    lines += ["## 付記: 載せていない項目", "",
              "- 個別トラックの処理、使用機材、編集の経緯（2mix・配布ステムからは分からない。分析メモでは〔不明〕と書く）",
              "- フレームごとの値、スペクトログラム、波形、LTAS の全ビン（粒度の規則）",
              "- ファイル名・パス（素材は SHA-256 で指す）", ""]
    return "\n".join(lines)


def _render_master(m: dict, study: dict) -> list[str]:
    d = m["dynamics"]
    out = ["## 3. マスター: 全体", "", "### 3.1 ラウドネスと動き", ""]
    out += _table(["量", "値"], [[f"`{k}` {label}", _num(d.get(k), dig)] for k, label, dig in KV_LOUDNESS])
    out += ["", "### 3.2 帯域の配分", ""]
    rows = []
    for b in BANDS:
        bid = b["id"]
        rows.append([f"`{bid}`", f"{b['range_hz'][0]:g}–{b['range_hz'][1]:g}", _num(m["bands"].get(bid), 4),
                     _frac_db(m["bands"].get(bid)), _num(m["ltas_band_db"].get(bid), 1),
                     _num(m["band_crest_db"].get(bid), 1)])
    out += _table(["帯域", "Hz", "エネルギー比", "比 dB", f"LTAS 平均 dB（{_num(m['level_match']['target_lufs'], 0)} LUFS 合わせ）",
                   "帯域クレスト dB"], rows)
    out += ["", f"- `tilt_db_per_oct` LTAS の傾き（{TILT_FIT_HZ[0]:g}–{TILT_FIT_HZ[1]:g} Hz の回帰）: "
            f"{_num(m.get('tilt_db_per_oct'), 2)} dB/oct",
            f"- レベル合わせ: {_num(m['level_match']['gain_db'], 2, sign=True)} dB（R-01）", ""]
    out += ["### 3.3 空間", ""]
    rows = [[f"`{bid}`", _sm(v.get("side_ratio_db")), _num(v.get("correlation"), 3), _num(v.get("mono_loss_db"), 2)]
            for bid, v in m["spatial"]["bands"].items()]
    out += _table(["帯域", "S/M dB", "相関", "モノ化損失 dB"], rows)
    out += ["", f"- 全帯域: S/M {_num(m['width']['side_ratio_db'], 2)} dB、相関 {_num(m['width']['correlation'], 3)}",
            f"- `mono_boundary_hz` 低域のモノ化の境界: {_num(m.get('mono_boundary_hz'), 0)} Hz"
            f"（S/M < {MONO_SIDE_DB_MAX:g} dB の帯域が最低帯域から連続する上限）",
            f"- 負相関の持続（{NEG_CORR_BAND_HZ[0]:g}–{NEG_CORR_BAND_HZ[1]:g} Hz、{NEG_CORR_WINDOW_S:g} s 窓）: 最長 "
            f"{_num(m['spatial']['negative']['longest_run_s'], 2)} s、割合 {_num(m['spatial']['negative']['negative_fraction'], 4)}",
            "", "低域の S/M（モノ化の境界の根拠。帯域集計）", ""]
    out += _table(["帯域 Hz", "S/M dB"], [[f"{r['band_hz'][0]:g}–{r['band_hz'][1]:g}", _sm(r.get("side_ratio_db"))]
                                         for r in m["spatial"]["low_side"]])
    hf = m["hf"]
    out += ["", "### 3.4 高域", ""]
    out += _table(["量", "値"], [
        ["`air_fraction` エア帯（6–20 kHz）のエネルギー比", _num(hf.get("air_fraction"), 4)],
        ["`rolloff_hz` ロールオフ周波数 Hz（— = 全帯域）", _num(hf.get("rolloff_hz"), 0)],
        ["`rolloff_drop_db` ロールオフの落ち込み dB", _num(hf.get("rolloff_drop_db"), 1)],
        ["`flatness` 高域（10–14 kHz）の平坦度（雑音性）", _num(hf.get("flatness"), 4)],
        ["`shimmer_index_db` 高域のちらつき指標 dB", _num(hf.get("shimmer_index_db"), 2)],
    ])
    if study["lossy"]:
        out += ["", f"- 非可逆音源: この節の値（特に {LOSSY_HF_HZ / 1000:g} kHz 以上）はコーデックの影響を含む。確度上限 low"]
    v = m["vector"]
    out += ["", "### 3.5 全体ベクトル（measure_reference）", ""]
    out += _table(["量", "値"], [
        ["`P-11` LTAS の突出 dB", _num(v.get("P-11"), 2)], ["`P-17` 突出の p99 dB", _num(v.get("P-17"), 2)],
        ["`P-19` RMS の偏差 dB", _num(v.get("P-19"), 2)], ["`P-20` コントラスト dB", _num(v.get("P-20"), 2)],
        ["`bpm` BPM（確度）", f"{_num(v.get('bpm'), 1)}（{_num(v.get('bpm_confidence'), 2)}）"],
        ["`key` キー（確度）", f"{v.get('key') or '—'}（{_num(v.get('key_confidence'), 2)}）"],
    ])
    out += [""]
    # 4. sections
    out += ["## 4. 区間", ""]
    src = study.get("sections_source")
    out.append("- 区分: " + ("利用者指定（`--sections`）" if src == "user" else
                            "自動（`master_analysis.section_times` の最大・最小 3 s 区間）"))
    summ = study.get("summary") or {}
    out.append(f"- 要約: 最大区間 `{summ.get('max') or '—'}`、最小区間 `{summ.get('min') or '—'}`（LUFS-I の大小）")
    out.append("")
    rows = []
    allrow = {"id": "（全体）", "start_s": 0.0, "end_s": m.get("duration_s"), "lufs_i": d.get("lufs_i"),
              "short_max": d.get("short_max"), "crest_db": d.get("crest_db"),
              "side_ratio_db": m["width"]["side_ratio_db"], "correlation": m["width"]["correlation"], "bands": m["bands"]}
    for s in [allrow] + list(m.get("sections") or []):
        mark = ""
        if s["id"] == summ.get("max"):
            mark = "最大"
        elif s["id"] == summ.get("min"):
            mark = "最小"
        rows.append([f"`{s['id']}`" if s is not allrow else s["id"], mark,
                     f"{_num(s['start_s'], 1)}–{_num(s['end_s'], 1)}", _num(s.get("lufs_i"), 1),
                     _num(s.get("short_max"), 1), _num(s.get("crest_db"), 1), _num(s.get("side_ratio_db"), 1),
                     _num(s.get("correlation"), 3)] + [_frac_db((s.get("bands") or {}).get(b)) for b in BAND_IDS])
    out += _table(["区間", "要約", "秒", "LUFS-I", "短期最大", "クレスト dB", "S/M dB", "相関"]
                  + [f"{b} dB" for b in BAND_IDS], rows)
    out += ["", "- 帯域の列はエネルギー比の dB（10·log10(比)）", ""]
    # 5. signs
    out += ["## 5. 兆候", "", "測定の組み合わせから規則で導いた事実寄りの所見。意図は言わない。", ""]
    rows = []
    for s in study["signs"]:
        ev = "; ".join(f"{k} = {_c(v)}" for k, v in s["evidence"]) or "—"
        rows.append([f"`{s['rule']}`", s["title"], "立つ" if s["raised"] else "立たず", s["finding"], ev,
                     s["confidence"] or "—", f"{s['cap']}（{s['cap_reason']}）" if s.get("cap") else "—"])
    out += _table(["規則", "兆候", "状態", "所見", "根拠の測定値", "確度（規則）", "確度上限"], rows)
    out += [""]
    return out


def _c(v: Any) -> str:
    if isinstance(v, bool) or v is None:
        return "—" if v is None else str(v)
    if isinstance(v, (int, float)):
        s = _num(v, 4)
        return s.rstrip("0").rstrip(".") if "." in s else s
    return str(v)


def _render_stems(st: dict, study: dict) -> list[str]:
    out = ["## 6. ステム", "", f"- 注記: {STEM_NOTE}"]
    if study["origin"] == "separated":
        out.append("- このステムは 2mix からの分離で得た擬似ステム（`origin: separated`）。にじみを含む。確度上限 medium")
    out += ["", "### 6.1 役割の割り当て", ""]
    rows = []
    for a in st["assignment"]:
        rows.append([f"`{a['role']}`", a["count"], ", ".join(a["sources"]), ", ".join(f"`{h}`" for h in a["sha16"])])
    out += _table(["役割", "本数", "割り当ての出どころ", "SHA-256（先頭 16 桁）"], rows)
    if st.get("excluded"):
        names = {"fullmix": "全体ミックス", "derived_sum": "派生の合算"}
        out += ["", "- 除外: " + "、".join(f"{names.get(e['reason'], e['reason'])} {e['count']} 本" for e in st["excluded"])
                + "（全体ミックス・派生の合算は同じ音を二重に数えるため測らない）"]
    out += ["", "- 同じ役割のファイルが複数あるときは合算して 1 役割として測る。役割は `knowledge/ingest_patterns.json` の"
            "語彙で名前から推定（`--roles` で上書き可）", ""]
    m = st["measure"]
    out += ["### 6.2 ステム単位の量", "", f"- ステム和の LUFS-I: {_num(m['sum_lufs'], 2)}", ""]
    rows = []
    for r, v in m["roles"].items():
        rows.append([f"`{r}`", _num(v["lufs_i"], 1), _num(v["rel_lu"], 1, sign=True), _num(v["lr_diff_db"], 1, sign=True),
                     _sm(v["side_ratio_db"]), _num(v["correlation"], 3), _num(v["crest_db"], 1),
                     _num(v["present_fraction"], 2)] + [_frac_db(v["bands"].get(b)) for b in BAND_IDS])
    out += _table(["役割", "LUFS-I", "和との差 LU", "L/R 差 dB", "S/M dB", "相関", "クレスト dB", "在区間の割合"]
                  + [f"{b} dB" for b in BAND_IDS], rows)
    out += ["", "- L/R 差 = 10·log10(E_L/E_R)（正 = 左寄り）。帯域の列はエネルギー比の dB。S/M の <-60 は中央定位（ほぼモノ）", "",
            "帯域別クレスト dB（P-04 の定義）", ""]
    out += _table(["役割"] + [f"{b} dB" for b in BAND_IDS],
                  [[f"`{r}`"] + [_num(v["band_crest_db"].get(b), 1) for b in BAND_IDS] for r, v in m["roles"].items()])
    out += [""]
    secs = study.get("section_list") or []
    if secs:
        out += ["### 6.3 区間別の相対レベルと在・不在", "",
                f"値 = 区間内の和に対する LU 差。· = 不在（区間の積分ラウドネス < {ABSENT_LUFS:.0f} LUFS。曲資料 §3 と同じ基準）", ""]
        rows = []
        for r, v in m["roles"].items():
            rows.append([f"`{r}`"] + [_num(p["rel_lu"], 1, sign=True) if p["present"] else "·" for p in v["sections"]])
        out += _table(["役割"] + [f"`{s['id']}`" for s in secs], rows)
        out += [""]
    rel = m["relations"]
    out += ["### 6.4 ステム間の関係（曲資料 §5 と同じ定義）", ""]
    lv = rel.get("lead_vs_rest_lu")
    if lv:
        vals = lv["values"]
        out.append(f"- `lead_vs_rest_lu` 主役（`{lv['lead']}`）対伴奏（他の役割の和）の LU 差: 全体 {_num(vals.get('all'), 2, sign=True)}"
                   + ("" if not secs else "、区間別 " + "、".join(f"`{s['id']}` {_num(vals.get(s['id']), 2, sign=True)}" for s in secs)))
    else:
        out.append("- `lead_vs_rest_lu` 主役対伴奏: 主役（vocals）がない、または役割が 1 つだけ")
    ls = rel.get("low_share")
    if ls:
        out += ["", "低域の分け合い（drums と bass。キック単独のステムがなければドラムに含まれる）", ""]
        out += _table(["帯域", "drums dB", "bass dB", "drums の取り分"],
                      [[f"`{k}`", _num(v["drums_db"], 1), _num(v["bass_db"], 1), _num(v["drums_share"], 3)] for k, v in ls.items()])
    else:
        out += ["", "- 低域の分け合い: drums と bass の両方がないため空欄"]
    out += ["", f"帯域の重なり（帯域担当。最大の役割から {_num(rel['band_owner_rule']['within_db'], 0)} dB 以内かつ帯域の "
            f"{_num(rel['band_owner_rule']['min_share'], 2)} 以上、`knowledge/masking_model.json` の P-22 規則）", ""]
    out += _table(["帯域", "担当数", "担当"], [[f"`{b}`", len(o), ", ".join(o) or "—"] for b, o in rel["band_owners"].items()])
    out += [""]
    return out


def _render_difference(df: dict) -> list[str]:
    out = ["ステム和（ゲイン 0、頭合わせ）をマスターに時間とゲインで合わせ、差を測る。"
           "バス／マスター段が全体として何をしたかの推定値（推定であって処理の記録ではない）。", ""]
    if not df["reliable"]:
        out += ["- **差分は信頼できない**: 合わせた後の残差が大きく、ステムが和でマスターを再現しない。"
                "この節の値から引く結論の確度は low が上限", ""]
    out += _table(["量", "値"], [
        ["`lag_ms` 時間合わせ（正 = 和が遅れていた）ms", _num(df["lag_ms"], 2)],
        ["`lufs_diff_lu` ラウドネス差（マスター − 和）LU", _num(df["lufs_diff_lu"], 2, sign=True)],
        ["`ltas_diff_slope_db_per_oct` LTAS 差の傾き dB/oct", _num(df["ltas_diff_slope_db_per_oct"], 2, sign=True)],
        ["`crest_diff_db` クレスト差（マスター − 和）dB", _num(df["crest_diff_db"], 2, sign=True)],
        ["`plr_diff_db` PLR 差（マスター − 和）dB", _num(df["plr_diff_db"], 2, sign=True)],
        ["`width_diff_db` 幅の差（S/M、マスター − 和）dB", _num(df["width_diff_db"], 2, sign=True)],
        ["`residual_db` 合わせた後の残差（帯域ごとの最適ゲイン後、対マスター）dB", _num(df["residual"]["total_db"], 2)],
        ["`correlation` 合わせた後の相関", _num(df["correlation"], 4)],
    ])
    out += ["", "帯域別（LTAS 差はレベル合わせ後のマスター − 和、残差は帯域内の最適ゲイン後）", ""]
    out += _table(["帯域", "LTAS 差 dB", "残差 dB"],
                  [[f"`{b}`", _num(df["ltas_diff_db"].get(b), 2, sign=True), _num(df["residual"]["bands"].get(b), 1)]
                   for b in BAND_IDS])
    out += ["", f"- 残差 > {RESIDUAL_UNRELIABLE_DB:g} dB を「信頼できない」とする。"
            f"判定: {'信頼できる' if df['reliable'] else '信頼できない'}", ""]
    return out


# ---------------------------------------------------------------------------
# separation (optional; existing path only)
# ---------------------------------------------------------------------------

def separate_in_memory(x: np.ndarray, sr: int) -> dict[str, np.ndarray]:
    """Pseudo stems from the registered default 'full' separation model.

    The worker protocol needs files: they go to a temporary folder outside the
    kb and the project and are deleted before returning; only arrays leave."""
    from mankomix.core import registry
    from mankomix.core.separation import pipeline as SP
    try:
        model_id = registry.default_model("full")
        if not model_id:
            raise SeparationUnavailable("no default separation model is configured")
        resolved = registry.resolve_for_run(model_id)
    except SeparationUnavailable:
        raise
    except Exception as e:  # missing weights, unknown model, bad hash
        raise SeparationUnavailable(f"the separation path is not usable here: {e}") from None
    entry = resolved["entry"]
    rt = entry.get("runtime") or {}
    if entry.get("task") != "separation" or not rt.get("backend"):
        raise SeparationUnavailable(f"model '{model_id}' cannot run separation")
    gain, _ = SP._normalise_gain(x, sr)
    rate = SP._model_rate(entry, sr)
    work = Path(tempfile.mkdtemp(prefix="mankomix_refsep_"))
    try:
        audio_io.write(work / "input.wav", SP._resample(x * gain, sr, rate).astype(np.float32), rate, subtype="FLOAT")
        request = {"protocol": 1, "backend": rt["backend"], "architecture": entry.get("architecture"),
                   "config": rt.get("config") or {},
                   "weights": {name: str(p) for name, p in resolved["paths"].items()},
                   "roles": resolved["roles"], "input": str(work / "input.wav"),
                   "output_dir": str(work / "out"), "device": "auto"}
        result = SP.run_worker(request, work)
        outs = {}
        for stem, fname in sorted((result.get("stems") or {}).items()):
            y, ysr = audio_io.read(work / "out" / fname)
            y = SP._resample(y, ysr, sr) / gain
            n = x.shape[0]
            if y.shape[0] < n:
                y = np.concatenate([y, np.zeros((n - y.shape[0], y.shape[1]))])
            role = SP.STEM_ROLE.get(stem, "other")
            outs.setdefault(role, []).append(_stereo(y[:n]))
        return {r: _sum(v) for r, v in outs.items()}
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# building the study
# ---------------------------------------------------------------------------

def _load_json_arg(v: Any, what: str) -> Any:
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return v
    s = str(v)
    p = Path(s[1:] if s.startswith("@") else s)
    try:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
        return json.loads(s)
    except ValueError:
        raise RefStudyError(f"{what}: invalid JSON") from None


def build_study(work: str, *, master: str | Path | None = None, stems: str | Path | None = None,
                sections: Any = None, roles: Any = None, separate: bool = False,
                _separator=None) -> dict:
    """Measure the material and return the study (dict) and its Markdown. Nothing is written."""
    check_slug(work)
    if master is None and stems is None:
        raise RefStudyError("give --master and/or --stems")
    if separate and master is None:
        raise RefStudyError("--separate needs --master")
    if separate and stems is not None:
        raise RefStudyError("--separate and --stems exclude each other (real stems are better than pseudo stems)")
    materials: list[dict] = []
    lossy = False
    x = sr = None
    if master is not None:
        mp = Path(master)
        if not mp.is_file():
            raise RefStudyError("--master: file not found")
        if not audio_io.is_audio_file(mp):
            raise RefStudyError("--master: not an audio file")
        mi = material_info(mp)
        lossy = lossy or mi["lossy"]
        materials.append({"type": "master", **{k: mi[k] for k in ("sha256", "format", "lossy", "duration_s")}})
        x, sr = read_audio(mp)
    by_role: dict[str, np.ndarray] | None = None
    assignment, excluded = [], []
    s_sr = None
    if stems is not None:
        sd = Path(stems)
        if not sd.is_dir():
            raise RefStudyError("--stems: folder not found")
        files = sorted((p for p in sd.iterdir() if p.is_file() and audio_io.is_audio_file(p)), key=lambda p: p.name)
        if not files:
            raise RefStudyError("--stems: no audio files in the folder")
        ov = _load_json_arg(roles, "--roles") or {}
        if not isinstance(ov, dict):
            raise RefStudyError("--roles must be a JSON object {file name: role}")
        assigned = assign_roles([p.name for p in files], ov)
        byname = {p.name: p for p in files}
        groups: dict[str, list[np.ndarray]] = {}
        shas: dict[str, list[str]] = {}
        srcs: dict[str, set] = {}
        all_sha = []
        st_lossy = False
        st_dur = None
        st_rate = st_depth = None
        for a in assigned:
            if a["excluded"]:
                continue
            p = byname[a["name"]]
            mi = material_info(p)
            st_lossy = st_lossy or mi["lossy"]
            y, ysr = read_audio(p)
            if s_sr is None:
                s_sr, st_rate, st_depth = ysr, mi["sample_rate"], mi["bit_depth"]
            elif ysr != s_sr:
                raise RefStudyError("--stems: the stems have different sample rates")
            groups.setdefault(a["role"], []).append(y)
            shas.setdefault(a["role"], []).append(mi["sha256"])
            srcs.setdefault(a["role"], set()).add(a["role_source"])
            all_sha.append(mi["sha256"])
            st_dur = max(st_dur or 0.0, float(mi["duration_s"] or 0.0))
        for a in assigned:
            if a["excluded"]:
                excluded.append(a["excluded"])
        if not groups:
            raise RefStudyError("--stems: every file was excluded (full mix or derived sums only)")
        by_role = {r: _sum(v) for r, v in sorted(groups.items())}
        assignment = [{"role": r, "count": len(shas[r]), "sources": sorted(srcs[r]),
                       "sha16": sorted(h[:16] for h in shas[r])} for r in sorted(groups)]
        lossy = lossy or st_lossy
        set_sha = _sha256_bytes("\n".join(sorted(all_sha)).encode("ascii"))
        materials.append({"type": "stems", "sha256_set": set_sha, "count": len(all_sha),
                          "format": f"{_rate_text(st_rate)}/{st_depth}", "lossy": st_lossy, "duration_s": _r(st_dur, 3)})
        if x is not None and s_sr != sr:
            raise RefStudyError("the master and the stems have different sample rates")
    origin = "measured"
    if separate:
        sep = _separator or separate_in_memory
        by_role = {r: _stereo(v) for r, v in sorted(sep(x, sr).items())}
        s_sr = sr
        origin = "separated"
        assignment = [{"role": r, "count": 1, "sources": ["separation"], "sha16": []} for r in sorted(by_role)]
    # sections
    ref_x = x if x is not None else (_sum(list(by_role.values())) if by_role else None)
    ref_sr = sr if x is not None else s_sr
    dur = ref_x.shape[0] / float(ref_sr)
    spec = _load_json_arg(sections, "--sections")
    if spec is not None:
        secs = load_sections(spec, dur)
        sec_src = "user"
    else:
        secs = auto_sections(ref_x, ref_sr)
        sec_src = "auto"
    study: dict = {"work": work, "origin": origin, "lossy": bool(lossy), "materials": materials,
                   "sections_source": sec_src, "section_list": secs}
    if x is not None:
        mm = master_measure(x, sr, secs)
        summ = section_summary(mm["sections"])
        study["summary"] = summ
        study["master"] = mm
        study["signs"] = apply_caps(signs(mm, summ), lossy=lossy, separated=origin == "separated")
    if by_role:
        study["stems"] = {"assignment": assignment,
                          "excluded": [{"reason": r, "count": excluded.count(r)} for r in sorted(set(excluded))],
                          "measure": stems_measure(by_role, s_sr, secs)}
        if x is not None and origin == "measured":
            study["difference"] = sum_master_difference(x, _sum(list(by_role.values())), sr, study.get("master"))
    md = render(study)
    study["markdown"] = md
    study["sha256"] = _sha256_bytes(md.encode("utf-8"))
    return study


# ---------------------------------------------------------------------------
# kb files
# ---------------------------------------------------------------------------

def work_dir(kb_root: Path, slug: str) -> Path:
    return Path(kb_root) / "references" / "works" / slug


def engineer_path(kb_root: Path, slug: str) -> Path:
    return Path(kb_root) / "references" / "engineers" / f"{slug}.md"


def _q(s: str) -> str:
    return '"' + str(s).replace('"', "'") + '"'


def work_card_template(slug: str, study: dict, created: str) -> str:
    mats = []
    for m in study["materials"]:
        if m["type"] == "master":
            mats.append(f"{{ type: master, lossy: {'true' if m['lossy'] else 'false'}, format: {_q(m['format'])}, "
                        f"sha256: {_q(m['sha256'])}, obtained: \"\" }}")
        else:
            mats.append(f"{{ type: stems, count: {m['count']}, lossy: {'true' if m['lossy'] else 'false'}, "
                        f"format: {_q(m['format'])}, sha256_set: {_q(m['sha256_set'])}, obtained: \"\" }}")
    fm = [
        "---",
        f"id: work_{slug}",
        "kind: work",
        f"title: {_q(slug)}",
        f"created: {created}",
        "status: draft",
        "visibility: private",
        "artist: \"\"",
        "release: { title: \"\", year: null }",
        "credits: []",
        "credits_source: \"\"",
        "genre: []",
        "rights: third_party",
        "materials: [" + ", ".join(mats) + "]",
        f"study: {{ sha256: {_q(study['sha256'])}, engine: {{ version: {_q(ENGINE_VERSION)}, refstudy: {REFSTUDY_VERSION} }} }}",
        "evidence: measured",
        "backing: [refstudy.md]",
        "---",
    ]
    body = [
        "", f"# work_{slug}", "",
        "<!-- 雛形（mankomix direction ref study が作成）。メタ情報（artist、release、credits、credits_source、"
        "genre、materials の obtained）は利用者か指揮者が埋める。自前作品は rights: own に直し、公開 kb に置く。 -->", "",
        "## 何の作品か", "", "（未記入。1〜2 行。批評・歌詞・解説文の転載は書かない）", "",
        "## 測定の要点", "", "（未記入。[refstudy.md](refstudy.md) からの書き写し）", "",
        "## 読み", "", "（未記入。指揮者の〔推定〕と確度。確度は refstudy §2 の上限を超えない）", "",
        "## 使った案件", "", "（未記入。リンク）", "",
    ]
    return "\n".join(fm + body)


def study_command(work: str, *, master=None, stems=None, sections=None, roles=None, separate: bool = False,
                  kb_root: str | Path = DEFAULT_KB, created: str | None = None, _separator=None) -> dict:
    """``direction ref study``: write refstudy.md (and the work card template when absent)."""
    root = Path(kb_root)
    study = build_study(work, master=master, stems=stems, sections=sections, roles=roles, separate=separate,
                        _separator=_separator)
    d = work_dir(root, work)
    d.mkdir(parents=True, exist_ok=True)
    rs = d / "refstudy.md"
    data = study["markdown"].encode("utf-8")
    old = rs.read_bytes() if rs.is_file() else None
    if old != data:
        rs.write_bytes(data)
    card = d / "work.md"
    created_card = False
    card_stale = None
    if not card.is_file():
        card.write_bytes(work_card_template(work, study, created or date.today().isoformat()).encode("utf-8"))
        created_card = True
    else:
        try:
            meta, _ = kbmod.parse_front_matter(card.read_text(encoding="utf-8"))
        except kbmod.FrontMatterError:
            meta = None
        cur = ((meta or {}).get("study") or {}).get("sha256") if isinstance((meta or {}).get("study"), dict) else None
        card_stale = cur != study["sha256"]
    out = {"kind": "refstudy", "work": f"work_{work}", "origin": study["origin"], "lossy": study["lossy"],
           "refstudy": f"references/works/{work}/refstudy.md", "refstudy_sha256": study["sha256"],
           "changed": old != data, "work_card": f"references/works/{work}/work.md",
           "work_card_created": created_card,
           "materials": study["materials"],
           "signs": [{"rule": s["rule"], "raised": s["raised"], "confidence": s["confidence"], "cap": s.get("cap")}
                     for s in study.get("signs") or []],
           "difference_reliable": (study.get("difference") or {}).get("reliable") if study.get("difference") else None,
           "sections": [s["id"] for s in study["section_list"]], "sections_source": study["sections_source"]}
    if card_stale:
        out["work_card_stale"] = True
        out["note"] = ("the work card's study.sha256 differs from this refstudy; update 'study' (and 'materials' "
                       "if the material changed) in work.md")
    return out


# ---------------------------------------------------------------------------
# reading a refstudy back (tables only; used by refsheet and credit)
# ---------------------------------------------------------------------------

_KEY_RE = re.compile(r"^`([^`]+)`")


def parse_tables(md: str) -> dict[str, list[dict]]:
    """Tables of a refstudy, keyed by the number of the heading above them ('3.1', '6.2', ...)."""
    out: dict[str, list[dict]] = {}
    cur = None
    head = None
    count: dict[str, int] = {}
    for ln in md.splitlines():
        h = re.match(r"^#{2,3}\s+(\d+(?:\.\d+)?)\.?\s", ln)
        if h:
            cur, head = h.group(1), None
            continue
        if not ln.startswith("|"):
            head = None
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip())[1:-1]]
        if head is None:
            head = cells
            n = count.get(cur or "", 0)
            count[cur or ""] = n + 1
            key = (cur or "") if n == 0 else f"{cur}#{n + 1}"
            out[key] = []
            continue
        if all(re.fullmatch(r"-+", c) for c in cells):
            continue
        k = (cur or "") if count[cur or ""] == 1 else f"{cur}#{count[cur or '']}"
        out[k].append(dict(zip(head, cells)))
    return out


def cell_num(s: Any) -> float | None:
    if s is None:
        return None
    t = str(s).strip().split("（")[0].strip()
    if t in ("", "—", "·"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def row_key(cell: str) -> str | None:
    m = _KEY_RE.match(str(cell).strip())
    return m.group(1) if m else None


def study_values(md: str) -> dict:
    """The key quantities of a refstudy as a flat dict {key: float} (master) plus stems and relations."""
    t = parse_tables(md)
    vals: dict[str, Any] = {}
    for sec in ("3.1", "3.4", "3.5", "7"):
        for r in t.get(sec, []):
            k = row_key(r.get("量", ""))
            if k:
                vals[k] = cell_num(r.get("値"))
    for r in t.get("3.2", []):
        k = row_key(r.get("帯域", ""))
        if k:
            vals[f"band_db:{k}"] = cell_num(r.get("比 dB"))
            vals[f"band_crest:{k}"] = cell_num(r.get("帯域クレスト dB"))
    for r in t.get("3.3", []):
        k = row_key(r.get("帯域", ""))
        if k:
            vals[f"side_db:{k}"] = cell_num(r.get("S/M dB"))
            vals[f"corr:{k}"] = cell_num(r.get("相関"))
    m = re.search(r"`tilt_db_per_oct`[^:]*:\s*(\S+) dB/oct", md)
    vals["tilt_db_per_oct"] = cell_num(m.group(1)) if m else None
    m = re.search(r"`mono_boundary_hz`[^:]*:\s*(\S+) Hz", md)
    vals["mono_boundary_hz"] = cell_num(m.group(1)) if m else None
    m = re.search(r"- 全帯域: S/M (\S+) dB、相関 (\S+)", md)
    if m:
        vals["side_ratio_db"], vals["correlation"] = cell_num(m.group(1)), cell_num(m.group(2))
    m = re.search(r"^- origin: `(\w+)`", md, re.MULTILINE)
    vals["origin"] = m.group(1) if m else None
    vals["lossy"] = "## 2. 確度の上限" in md and "- 非可逆音源: 高域" in md
    stems = {}
    for r in t.get("6.2", []):
        k = row_key(r.get("役割", ""))
        if k:
            stems[k] = {"lufs_i": cell_num(r.get("LUFS-I")), "rel_lu": cell_num(r.get("和との差 LU")),
                        "lr_diff_db": cell_num(r.get("L/R 差 dB")), "side_ratio_db": cell_num(r.get("S/M dB")),
                        "correlation": cell_num(r.get("相関")), "crest_db": cell_num(r.get("クレスト dB")),
                        "present_fraction": cell_num(r.get("在区間の割合")),
                        **{f"band_db:{b}": cell_num(r.get(f"{b} dB")) for b in BAND_IDS}}
    vals["stems"] = stems
    m = re.search(r"`lead_vs_rest_lu` 主役（`(\w+)`）対伴奏[^:]*: 全体 (\S+?)(?:、|$)", md, re.MULTILINE)
    vals["lead_vs_rest_lu"] = cell_num(m.group(2)) if m else None
    low = {}
    for key in ("6.4", "6.4#2"):
        for r in t.get(key, []):
            k = row_key(r.get("帯域", ""))
            if k and "drums の取り分" in r:
                low[k] = cell_num(r.get("drums の取り分"))
            if k and "担当数" in r:
                vals[f"owners:{k}"] = cell_num(r.get("担当数"))
    vals["low_share"] = low
    return vals


# ---------------------------------------------------------------------------
# ref list
# ---------------------------------------------------------------------------

def _card_meta(p: Path) -> dict | None:
    try:
        meta, _ = kbmod.parse_front_matter(p.read_text(encoding="utf-8"))
    except (OSError, kbmod.FrontMatterError):
        return None
    return meta


def list_command(kb_root: str | Path = DEFAULT_KB) -> dict:
    root = Path(kb_root)
    works, engs = [], []
    wd = root / "references" / "works"
    if wd.is_dir():
        for d in sorted((p for p in wd.iterdir() if p.is_dir()), key=lambda p: p.name):
            card, rs = d / "work.md", d / "refstudy.md"
            meta = _card_meta(card) if card.is_file() else None
            item: dict[str, Any] = {"work": f"work_{d.name}", "card": card.is_file(), "refstudy": rs.is_file(),
                                    "title": (meta or {}).get("title"), "rights": (meta or {}).get("rights"),
                                    "visibility": (meta or {}).get("visibility"), "status": (meta or {}).get("status")}
            if rs.is_file():
                text = rs.read_text(encoding="utf-8")
                sha = _sha256_bytes(rs.read_bytes())
                item["refstudy_sha256"] = sha
                m = re.search(r"- 版: refstudy (\d+)", text)
                ver = int(m.group(1)) if m else None
                card_sha = ((meta or {}).get("study") or {}).get("sha256") if isinstance((meta or {}).get("study"), dict) else None
                if ver != REFSTUDY_VERSION:
                    fresh = "outdated_format"
                elif card_sha is None:
                    fresh = "no_card_hash"
                elif card_sha == sha:
                    fresh = "fresh"
                else:
                    fresh = "stale"
                item["freshness"] = fresh
                ov = study_values(text)
                item["origin"] = ov.get("origin")
            else:
                item["freshness"] = "no_refstudy"
            works.append(item)
    ed = root / "references" / "engineers"
    if ed.is_dir():
        for p in sorted(ed.glob("*.md"), key=lambda p: p.name):
            meta = _card_meta(p) or {}
            engs.append({"engineer": f"eng_{p.stem}", "name": meta.get("name"), "title": meta.get("title"),
                         "credited_works": [w["work"] for w in _credited(root, p.stem)]})
    return {"kind": "ref_list", "works": works, "engineers": engs, "count": {"works": len(works), "engineers": len(engs)}}


# ---------------------------------------------------------------------------
# ref credit (T-8)
# ---------------------------------------------------------------------------

CREDIT_KEYS = (
    ("lufs_i", "積分ラウドネス LUFS-I", 2), ("true_peak_dbtp", "トゥルーピーク dBTP", 2), ("plr_db", "PLR dB", 2),
    ("lra_lu", "LRA LU", 2), ("short_range_lu", "短期ラウドネスの幅 LU", 2), ("crest_db", "広帯域クレスト dB", 2),
    ("tilt_db_per_oct", "LTAS の傾き dB/oct", 2), ("side_ratio_db", "全帯域 S/M dB", 2),
    ("mono_boundary_hz", "低域のモノ化の境界 Hz", 0), ("air_fraction", "エア帯の比", 4),
)
CREDIT_BEGIN = "<!-- ref credit: begin（mankomix direction ref credit が再生成。手で編集しない） -->"
CREDIT_END = "<!-- ref credit: end -->"
MIN_TREND_N = 3


def _credited(root: Path, person: str) -> list[dict]:
    out = []
    wd = root / "references" / "works"
    if not wd.is_dir():
        return out
    for d in sorted((p for p in wd.iterdir() if p.is_dir()), key=lambda p: p.name):
        card = d / "work.md"
        meta = _card_meta(card) if card.is_file() else None
        if not meta:
            continue
        roles = []
        for c in meta.get("credits") or []:
            if isinstance(c, dict) and str(c.get("person") or "") in (f"eng_{person}", person):
                roles.append(str(c.get("role") or "—"))
        if roles:
            out.append({"work": f"work_{d.name}", "slug": d.name, "roles": sorted(set(roles)),
                        "refstudy": (d / "refstudy.md").is_file()})
    return out


def credit_aggregate(root: Path, person: str) -> dict:
    works = _credited(root, person)
    per: dict[str, list[float]] = {k: [] for k, _, _ in CREDIT_KEYS}
    used = []
    for w in works:
        if not w["refstudy"]:
            continue
        v = study_values((work_dir(root, w["slug"]) / "refstudy.md").read_text(encoding="utf-8"))
        used.append(w["work"])
        for k, _, _ in CREDIT_KEYS:
            if v.get(k) is not None:
                per[k].append(float(v[k]))
    stats = {}
    for k, _, _ in CREDIT_KEYS:
        a = np.asarray(sorted(per[k]), float)
        if a.size == 0:
            stats[k] = {"n": 0, "median": None, "iqr": None}
        else:
            stats[k] = {"n": int(a.size), "median": float(np.median(a)),
                        "iqr": float(np.percentile(a, 75) - np.percentile(a, 25)) if a.size > 1 else 0.0}
    return {"works": works, "measured": used, "stats": stats}


def render_credit(person: str, agg: dict) -> str:
    out = [CREDIT_BEGIN, "", "## クレジットされた作品", ""]
    if agg["works"]:
        out += _table(["作品", "役割", "refstudy"],
                      [[f"[{w['work']}](../works/{w['slug']}/work.md)", ", ".join(w["roles"]), "あり" if w["refstudy"] else "なし"]
                       for w in agg["works"]])
    else:
        out.append("- なし（work カードの `credits` にこの人物がない）")
    out += ["", "## 測定の集計", "",
            f"refstudy のある作品 {len(agg['measured'])} 件の集計（中央値と四分位範囲）。"
            f"n < {MIN_TREND_N} は傾向とは言えない（事例）。内容は公表クレジットと測定の集計に限る。", ""]
    rows = []
    for k, label, dig in CREDIT_KEYS:
        s = agg["stats"][k]
        note = "—" if s["n"] == 0 else ("傾向とは言えない（事例）" if s["n"] < MIN_TREND_N else "集計")
        rows.append([f"`{k}` {label}", s["n"], _num(s["median"], dig), _num(s["iqr"], dig), note])
    out += _table(["量", "n", "中央値", "四分位範囲", "表示"], rows)
    out += ["", CREDIT_END]
    return "\n".join(out)


def engineer_template(person: str, created: str) -> str:
    return "\n".join([
        "---", f"id: eng_{person}", "kind: engineer", f"title: {_q(person)}", "name: \"\"", f"created: {created}",
        "status: draft", "visibility: private", "works: []", "credits_source: \"\"", "---", "",
        f"# eng_{person}", "",
        "<!-- 雛形（mankomix direction ref credit が作成）。公表クレジットと測定の集計だけを書く。人物評・私的情報は書かない。 -->",
        "", CREDIT_BEGIN, CREDIT_END, ""])


def credit_command(person: str, kb_root: str | Path = DEFAULT_KB, created: str | None = None) -> dict:
    check_slug(person, "person")
    root = Path(kb_root)
    agg = credit_aggregate(root, person)
    block = render_credit(person, agg)
    p = engineer_path(root, person)
    created_card = False
    if p.is_file():
        text = p.read_text(encoding="utf-8")
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        text = engineer_template(person, created or date.today().isoformat())
        created_card = True
    if CREDIT_BEGIN in text and CREDIT_END in text:
        a = text.index(CREDIT_BEGIN)
        b = text.index(CREDIT_END) + len(CREDIT_END)
        new = text[:a] + block + text[b:]
    else:
        new = text.rstrip("\n") + "\n\n" + block + "\n"
    changed = new != text or created_card
    if changed:
        p.write_bytes(new.encode("utf-8"))
    return {"kind": "ref_credit", "engineer": f"eng_{person}", "card": f"references/engineers/{person}.md",
            "card_created": created_card, "changed": changed, "works": [w["work"] for w in agg["works"]],
            "measured": agg["measured"],
            "stats": {k: {"n": s["n"], "median": _r(s["median"], 4), "iqr": _r(s["iqr"], 4),
                          "trend": s["n"] >= MIN_TREND_N} for k, s in agg["stats"].items()}}
