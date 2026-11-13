"""User references (SPEC 4.6, D-039, R-01, R-17).

A reference is registered by extracting ONLY its measurement vector; the audio
is never copied into the project. The vector goes to
``analysis/ref_<id>.json`` and ``project.references`` gets
``{id, label, vector, sha256}`` (sha256 of the audio content, so the same file
is not registered twice).

Level matching (R-01): every spectral quantity of a reference is measured
after normalising its integrated loudness to the common comparison level of
knowledge/thresholds_m3.json (``level_match.target_lufs``, -23 LUFS), the same
level the project audio is normalised to. That level sits below virtually any
finished track, so references are lowered, never raised; if a reference is
quieter than that level the fact is recorded in the vector.

The distribution (``reference_distribution``) is used as the P-01 target and
for scalar targets (P-07, P-03, P-05, P-11): median and IQR across references.
With a single reference the IQR is a default width from
knowledge/objective_metrics.json.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import audio_io, config
from .errors import InputError
from .hashing import sha256_file

VECTOR_VERSION = 1


def _json_safe(obj):
    from .measure.vector import json_safe
    return json_safe(obj)


def _refs(project) -> list[dict]:
    return [r for r in project.data.get("references") or [] if isinstance(r, dict)]


def _vector_path(project, rid: str) -> Path:
    return project.root / "analysis" / f"ref_{rid}.json"


def measure_reference(x, sr: int) -> dict:
    """Measurement vector of a reference signal (no audio kept)."""
    from .analysis.perceptual import measure_mix_perceptual
    from .measure import measure_signal
    from .objectives import reference_scalars
    vec = measure_signal(x, sr)
    perc = measure_mix_perceptual(x, sr)
    lm = perc.get("level_match") or {}
    p01 = perc.get("P-01") or {}
    notes = []
    if lm.get("gain_db") is not None and lm["gain_db"] > 0:
        notes.append("reference is quieter than the comparison level and was raised to it (R-01 prefers lowering)")
    music = perc.get("music") or {}
    return _json_safe({
        "vector_version": VECTOR_VERSION,
        "sample_rate": int(sr),
        "duration_s": vec.get("duration_s"),
        "level_match": {**lm, "direction": "down" if (lm.get("gain_db") or 0) <= 0 else "up",
                        "rule": "R-01"},
        "ltas_erb": {"centers_hz": p01.get("centers_hz"), "level_db": p01.get("level_db"),
                     "level_matched_to_lufs": lm.get("target_lufs")},
        "measure": {k: vec.get(k) for k in ("P-03", "P-04", "P-05", "P-06", "P-07", "P-14", "LTAS")},
        "perceptual": {
            "P-11": {k: (perc.get("P-11") or {}).get(k) for k in ("ltas_prominence_db", "peaky_frame_pct")},
            "P-17": {k: (perc.get("P-17") or {}).get(k) for k in ("p99_prominence_db", "event_pct")},
            "P-19": {k: (perc.get("P-19") or {}).get(k) for k in ("rms_deviation_db", "max_peak_db")},
            "P-20": {k: (perc.get("P-20") or {}).get(k) for k in ("contrast_db", "opening_db")},
        },
        "music": {k: music.get(k) for k in ("bpm", "bpm_confidence", "key", "key_confidence")},
        "scalars": reference_scalars(vec, perc),
        "notes": notes,
    })


def reference_add(project, audio_path, *, label: str | None = None, actor: str = "human") -> dict:
    """Measure a reference file and register its vector (the audio is not copied, 4.6)."""
    p = Path(audio_path)
    if not p.is_file():
        raise InputError(f"reference file not found: '{p.name}'")
    sha = sha256_file(p)
    for r in _refs(project):
        if r.get("sha256") == sha:
            return {"added": False, "reference": r, "note": "already registered (same audio content)"}
    x, sr = audio_io.read(p)
    vec = measure_reference(x, sr)
    rid = sha[:12]
    vec.update({"id": rid, "label": label or p.stem, "source": {"file_name": p.name, "sha256": sha}})
    path = _vector_path(project, rid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(vec, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    entry = {"id": rid, "label": label or p.stem, "vector": f"analysis/ref_{rid}.json", "sha256": sha}
    project.data.setdefault("references", []).append(entry)
    project.save(actor=actor, op="reference_add", reason=f"reference '{entry['label']}' registered (vector only)")
    return {"added": True, "reference": entry,
            "summary": {"integrated_lufs": (vec["measure"].get("P-03") or {}).get("integrated_lufs"),
                        "level_match_gain_db": vec["level_match"].get("gain_db"),
                        "scalars": vec["scalars"]}}


def reference_list(project) -> dict:
    out = []
    for r in _refs(project):
        path = _vector_path(project, r["id"])
        item = {"id": r["id"], "label": r.get("label"), "vector": r.get("vector"), "vector_present": path.is_file()}
        if path.is_file():
            try:
                v = json.loads(path.read_text(encoding="utf-8"))
                item["duration_s"] = v.get("duration_s")
                item["integrated_lufs"] = ((v.get("measure") or {}).get("P-03") or {}).get("integrated_lufs")
            except (OSError, ValueError):
                item["vector_present"] = False
        out.append(item)
    return {"references": out, "count": len(out),
            "target_source": "references" if out else "generic_prior"}


def reference_remove(project, ref_id: str, *, actor: str = "human", delete_vector: bool = True) -> dict:
    refs = _refs(project)
    hit = next((r for r in refs if r.get("id") == ref_id), None)
    if hit is None:
        raise InputError(f"unknown reference '{ref_id}'", details={"valid": [r.get("id") for r in refs]})
    project.data["references"] = [r for r in refs if r.get("id") != ref_id]
    project.save(actor=actor, op="reference_remove", reason=f"reference '{ref_id}' removed")
    removed_file = False
    path = _vector_path(project, ref_id)
    if delete_vector and path.is_file():
        path.unlink()
        removed_file = True
    return {"removed": ref_id, "vector_deleted": removed_file}


def load_vectors(project) -> list[dict]:
    out = []
    for r in _refs(project):
        path = _vector_path(project, r["id"])
        if path.is_file():
            out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def _default_iqr(centers: np.ndarray) -> np.ndarray:
    """Single-reference IQR width: mid value inside the mid range, widening to the edges (ERB scale)."""
    from .analysis.erb import hz_to_erb_number
    rc = config.load_knowledge("objective_metrics")["reference"]
    mid_lo, mid_hi = config.load_knowledge("thresholds_m3")["p01_generic_prior"]["mid_range_hz"]
    e = hz_to_erb_number(centers)
    e_lo, e_hi = hz_to_erb_number(np.asarray([mid_lo, mid_hi], float))
    e_min, e_max = hz_to_erb_number(20.0), hz_to_erb_number(20000.0)
    t = np.where(e < e_lo, (e_lo - e) / max(e_lo - e_min, 1e-9),
                 np.where(e > e_hi, (e - e_hi) / max(e_max - e_hi, 1e-9), 0.0))
    return rc["single_reference_iqr_db_mid"] + np.clip(t, 0, 1) * (
        rc["single_reference_iqr_db_edge"] - rc["single_reference_iqr_db_mid"])


def distribution_from_vectors(vectors: list[dict]) -> dict | None:
    """{median_db[], iqr_db[], centers_hz, n, scalars{key: {median, iqr, n}}, p01} or None."""
    from .analysis.erb import hz_to_erb_number
    usable = [v for v in vectors if (v.get("ltas_erb") or {}).get("centers_hz")]
    if not usable:
        return None
    centers = np.asarray(usable[0]["ltas_erb"]["centers_hz"], dtype=np.float64)
    ec = hz_to_erb_number(centers)
    rows = []
    for v in usable:
        c = np.asarray(v["ltas_erb"]["centers_hz"], dtype=np.float64)
        lv = np.asarray([x if x is not None else -200.0 for x in v["ltas_erb"]["level_db"]], dtype=np.float64)
        rows.append(np.interp(ec, hz_to_erb_number(c), lv))
    m = np.vstack(rows)
    med = np.median(m, axis=0)
    rc = config.load_knowledge("objective_metrics")["reference"]
    if len(rows) == 1:
        iqr = _default_iqr(centers)
        iqr_src = "default_width_single_reference"
    else:
        iqr = np.maximum(np.percentile(m, 75, axis=0) - np.percentile(m, 25, axis=0), rc["min_iqr_db"])
        iqr_src = f"measured (floor {rc['min_iqr_db']} dB)"
    scalars = {}
    keys = sorted({k for v in usable for k in (v.get("scalars") or {})})
    for k in keys:
        vals = [float(v["scalars"][k]) for v in usable if (v.get("scalars") or {}).get(k) is not None
                and math.isfinite(float(v["scalars"][k]))]
        if not vals:
            continue
        a = np.asarray(vals)
        scalars[k] = {"median": float(np.median(a)),
                      "iqr": float(np.percentile(a, 75) - np.percentile(a, 25)) if a.size > 1 else 0.0,
                      "n": int(a.size)}
    out = {"centers_hz": centers, "median_db": med, "iqr_db": iqr, "iqr_source": iqr_src,
           "n": len(usable), "ids": [v.get("id") for v in usable], "scalars": scalars,
           "level_matched_to_lufs": usable[0]["ltas_erb"].get("level_matched_to_lufs")}
    out["p01"] = {"centers_hz": centers, "median_db": med, "iqr_db": iqr, "shape_only": False,
                  "source": f"references (n={len(usable)})"}
    return _json_safe(out)


def reference_distribution(project) -> dict | None:
    """P-01 target distribution (and scalar targets) from the project's references; None without any."""
    return distribution_from_vectors(load_vectors(project))


__all__ = ["measure_reference", "reference_add", "reference_list", "reference_remove",
           "load_vectors", "distribution_from_vectors", "reference_distribution"]
