"""Verification of rendered variants (SPEC 6.7, 4.3).

Every verdict is measured on the rendered files. Status values:

- ``pass`` / ``fail``: evaluated hard check
- ``not_run``: the check applies but could not run (e.g. encoder missing).
  Never counted as a pass (SPEC 6.7, 13.3).
- ``not_applicable``: the profile does not ask for this check
- ``not_evaluated``: the check belongs to a later milestone (named)

The overall result is ``pass`` only if every evaluated hard check passes and
nothing applicable was left ``not_run`` (that case is ``incomplete``).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import audio_io, config
from . import master_analysis as ma
from .errors import InputError
from .mastering import (check_chain_order, codec_after_ceiling, effective_ceiling, find_variant,
                        loudness_window, thresholds, tv)
from .measure import loudness as ld
from .hashing import sha256_file
from .render import (ARCHIVE_DELIVERY, variant_route, codec_true_peaks, load_manifest, manifest_path_for,
                     output_ext, output_name, variant_dir)
from .routes import load_master_input
from .cleanstage import route_baseline, s07_check, s08_check

HARD_CHECKS = ("P-03", "S-01", "S-02", "S-03", "S-04", "S-05", "S-06", "S-07", "S-08", "S-09")


def _st(status: str, **kw) -> dict:
    d = {"status": status}
    d.update(kw)
    return d


def dither_facts(export: dict, delivery: dict) -> dict:
    """Facts for S-05 from the export record written by dsp.engine.export_audio."""
    exp = export or {}
    steps = exp.get("steps") or []
    types = [s.get("type") for s in steps]
    count = types.count("dither")
    if not steps and exp.get("dithered"):
        count = 1
    after = []
    if "dither" in types:
        after = [s.get("id") for s in steps[types.index("dither") + 1:]]
    depth = exp.get("bit_depth", delivery.get("bit_depth"))
    reduced = depth in (16, 24)  # the master is float; integer targets reduce word length
    policy = (delivery.get("dither") or "tpdf").lower()
    return {"dither_count": count, "depth_reduced": reduced, "target_bit_depth": depth,
            "delivery_dither_policy": policy, "steps_after_dither": after,
            "quantization": exp.get("quantization"), "seed": (exp.get("dither") or {}).get("seed")}


def _check_s05(export: dict, delivery: dict) -> dict:
    """S-05 rule itself: word length decreased <=> TPDF dither applied exactly once, last.

    The delivery's declared policy is recorded but does not excuse a violation.
    """
    f = dither_facts(export, delivery)
    if f["steps_after_dither"]:
        return _st("fail", rule="S-05", facts=f, problem="processing after dither")
    if f["depth_reduced"]:
        ok = f["dither_count"] == 1
        return _st("pass" if ok else "fail", rule="S-05", facts=f,
                   expected="TPDF dither exactly once at the final export (word length reduced)",
                   **({} if ok else {"problem": f"dither applied {f['dither_count']} times"}))
    ok = f["dither_count"] == 0
    return _st("pass" if ok else "fail", rule="S-05", facts=f,
               expected="no dither (word length not reduced)",
               **({} if ok else {"problem": "dither applied without a word-length reduction"}))


def _check_s09(y: np.ndarray, sr_out: int, in_frames: int, in_sr: int, th: dict, fixed_point: bool,
               input_dc: list[float] | None = None) -> dict:
    """S-09 health. DC fails only when above the limit and not inherited from the input
    (input DC scaled by the master gain; the master stage does not remove DC by design)."""
    from .measure.vector import health
    h = health(y)
    expected = int(round(in_frames * sr_out / float(in_sr)))
    tol = int(tv(th, "s09_health", "length_tolerance_samples", default=1))
    dc_max = float(tv(th, "s09_health", "dc_offset_max", default=0.001))
    clip_level = float(tv(th, "s09_health", "clip_sample_abs", default=1.0))
    finite = np.where(np.isfinite(y), y, 0.0)
    clipped = int(np.sum(np.abs(finite) >= clip_level - (1.0 / 32768.0 if fixed_point else 0.0)))
    dc = [abs(v) for v in h["dc_offset"]]
    problems = []
    if h["nan_count"] or h["inf_count"]:
        problems.append("non-finite samples")
    if clipped:
        problems.append("clipped samples")
    allowed = [max(dc_max, 1.5 * (input_dc[i] if input_dc and i < len(input_dc) else 0.0))
               for i in range(len(dc))]
    if any(v > a for v, a in zip(dc, allowed)):
        problems.append("DC offset")
    if abs(y.shape[0] - expected) > tol:
        problems.append("length mismatch")
    return _st("fail" if problems else "pass", rule="S-09", problems=problems,
               measured={"nan": h["nan_count"], "inf": h["inf_count"], "clipped_samples": clipped,
                         "dc_offset": [round(v, 6) for v in dc],
                         "input_dc_scaled": None if input_dc is None else [round(v, 6) for v in input_dc],
                         "frames": int(y.shape[0]),
                         "expected_frames": expected, "tolerance": tol, "channels": int(y.shape[1])})


def _check_s03(y, sr, th, boundary) -> dict:
    from .measure.stereo import low_band_negative_persistence
    max_run = float(tv(th, "s03_low_band_phase", "max_persistence_s", default=1.0))
    max_frac = float(tv(th, "s03_low_band_phase", "max_negative_fraction", default=0.1))
    r = low_band_negative_persistence(y, sr, cutoff_hz=boundary)
    if r is None:
        return _st("not_applicable", rule="S-03", reason="mono output")
    run, frac = float(r.get("longest_negative_run_s", 0.0)), float(r.get("negative_fraction", 0.0))
    ok = run <= max_run and frac <= max_frac
    return _st("pass" if ok else "fail", rule="S-03",
               measured={"boundary_hz": boundary, "longest_negative_run_s": round(run, 3),
                         "negative_fraction": round(frac, 4), "min_correlation": ma.finite_or_none(r.get("min_correlation"))},
               limits={"max_persistence_s": max_run, "max_negative_fraction": max_frac})


def _check_s04(y, sr, th, boundary) -> dict:
    low_max = float(tv(th, "s04_mono_loss", "low_band_max_db", default=1.5))
    band = tv(th, "s04_mono_loss", "lead_clarity_band_hz", default=[300, 5000])
    lead_max = float(tv(th, "s04_mono_loss", "lead_clarity_max_db", default=3.0))
    low = ma.mono_loss_db(y, sr, 20.0, boundary)
    lead = ma.mono_loss_db(y, sr, float(band[0]), float(band[1]))
    ok = (low is None or low <= low_max) and (lead is None or lead <= lead_max)
    return _st("pass" if ok else "fail", rule="S-04",
               measured={"low_band_mono_loss_db": None if low is None else round(low, 3),
                         "lead_clarity_mono_loss_db": None if lead is None else round(lead, 3)},
               limits={"low_band_max_db": low_max, "lead_clarity_band_hz": band, "lead_clarity_max_db": lead_max},
               note="full-mix proxy: the lead band is evaluated on the whole mix (stems arrive with M4)")


def _overall(checks: dict) -> str:
    hard = [checks[k] for k in HARD_CHECKS if k in checks]
    if any(c["status"] == "fail" for c in hard):
        return "fail"
    if any(c["status"] in ("not_run", "missing") for c in hard):
        return "incomplete"
    return "pass"


def _verify_output(project, variant_id, out, chain_res, th, inp: dict, recheck_codecs: bool) -> dict:
    in_frames, in_sr = inp["frames"], inp["sr"]
    profile = config.get_profile(out["profile"])
    delivery = config.get_delivery(out["delivery"])
    vdir = variant_dir(project, variant_id)
    path = vdir / output_name(profile["id"], delivery)
    rec = {"profile": profile["id"], "delivery": delivery["id"], "file": project.rel(path),
           "manifest": project.rel(manifest_path_for(path))}
    man = load_manifest(project, variant_id, profile["id"], delivery["id"])
    if not path.is_file() or man is None:
        rec["checks"] = {"render": _st("missing", reason="output not rendered; run render first")}
        rec["overall"] = "fail"
        return rec
    y, sr = audio_io.read(path)
    info = audio_io.info(path)
    fixed_point = "PCM" in (info.subtype or "").upper()
    lufs = float(ld.integrated(y, sr))
    tp = float(ld.true_peak_dbtp(y, sr))
    checks: dict = {}

    window = loudness_window(profile)
    if window is None:
        checks["P-03"] = _st("not_applicable", rule="P-03", measured={"lufs_i": round(lufs, 2)},
                             reason="profile has no loudness window (objective-driven)")
    else:
        ok = window[0] - 1e-6 <= lufs <= window[1] + 1e-6
        checks["P-03"] = _st("pass" if ok else "fail", rule="P-03", measured={"lufs_i": round(lufs, 2)},
                             window_lufs_i=window, target_lufs_i=out.get("target_lufs_i"))

    ceiling = effective_ceiling(profile, lufs, out.get("ceiling_dbtp"))
    checks["S-01"] = _st("pass" if tp <= ceiling + 1e-9 else "fail", rule="S-01",
                         measured={"true_peak_dbtp": round(tp, 3)}, ceiling_dbtp=ceiling,
                         oversample=ld.tp_oversample_factor(sr), conditional_applied=ceiling < float(
                             (profile.get("true_peak") or {}).get("ceiling_dbtp", -1.0)))

    codecs = list(profile.get("codec_checks") or [])
    if not codecs:
        checks["S-02"] = _st("not_applicable", rule="S-02", reason="profile declares no codec checks")
    else:
        cc = codec_after_ceiling(profile, th)
        s02m = man.get("s02") or {}
        stored = s02m.get("codecs") or {}
        same_file = man.get("file_sha256") == sha256_file(path)
        if (not recheck_codecs and same_file and set(stored) == set(codecs)
                and all(r.get("status") == "not_run" or r.get("true_peak_dbtp") is not None for r in stored.values())):
            # measured on these exact bytes during render (hash verified); re-judge against the ceiling
            res = {}
            for c, r in stored.items():
                r = dict(r)
                if r.get("status") != "not_run":
                    r["status"] = "pass" if r["true_peak_dbtp"] <= cc + 1e-9 else "fail"
                r["source"] = "render manifest (file sha256 verified)"
                res[c] = r
        else:
            res = codec_true_peaks(y, sr, codecs, cc, th)
        statuses = [r["status"] for r in res.values()]
        st = "fail" if "fail" in statuses else "not_run" if "not_run" in statuses else "pass"
        checks["S-02"] = _st(st, rule="S-02", codec_after_ceiling_dbtp=cc, codecs=res,
                             render_iterations=(man.get("s02") or {}).get("iteration_count"),
                             final_limiter_ceiling_dbtp=man.get("final_limiter_ceiling_dbtp"))

    checks["S-05"] = _check_s05(man.get("export") or {}, delivery)
    checks["S-06"] = chain_res
    gain = 10.0 ** ((lufs - inp["lufs"]) / 20.0) if np.isfinite(lufs) and np.isfinite(inp["lufs"]) else 1.0
    checks["S-09"] = _check_s09(y, sr, in_frames, in_sr, th, fixed_point, [v * gain for v in inp["dc"]])
    boundary = float((profile.get("playback_assumptions") or {}).get("mono_low_band_hz")
                     or tv(th, "s03_low_band_phase", "boundary_hz", default=120.0))
    checks["S-03"] = _check_s03(y, sr, th, boundary)
    checks["S-04"] = _check_s04(y, sr, th, boundary)
    checks["OF-5"] = _st("not_evaluated", milestone="M3", rule="OF-5",
                         reason="translation gate is implemented in M3")
    # S-07 (cleanup leaves the low band untouched): from the cleanup records of the input
    checks["S-07"] = dict(inp["s07"])
    # S-08 (noise-return guard): P-16 of this output vs the cleaned baseline, gain compensated
    checks["S-08"] = s08_check(inp["noise_baseline"], y, sr, lufs if np.isfinite(lufs) else None)
    rec["measured"] = {"lufs_i": round(lufs, 3), "true_peak_dbtp": round(tp, 3), "sample_rate": sr,
                       "frames": int(y.shape[0]), "subtype": info.subtype}
    rec["checks"] = checks
    rec["overall"] = _overall(checks)
    return rec


def verify_variant(project, variant_id: str, *, recheck_codecs: bool = False) -> dict:
    """Verify every output of a variant; writes reports/verify_<variant>.json.

    S-02 codec results measured during render are reused when the output file's
    sha256 still matches its manifest; ``recheck_codecs=True`` re-encodes.
    """
    data = project.data
    variant = find_variant(data, variant_id)
    if variant is None:
        raise InputError(f"unknown variant '{variant_id}'")
    th = thresholds()
    chain = (variant.get("master") or {}).get("chain") or []
    chain_res = check_chain_order(chain)
    outs = variant.get("outputs") or []

    a_man = load_manifest(project, variant_id, None, ARCHIVE_DELIVERY)
    route = variant_route(project, variant)
    x, in_sr = load_master_input(project, route)
    in_frames = int(x.shape[0])
    inp = {"frames": in_frames, "sr": int(in_sr), "lufs": float(ld.integrated(x, in_sr)),
           "dc": [float(abs(v)) for v in np.mean(x, axis=0)],
           "s07": s07_check(project, route),
           "noise_baseline": route_baseline(project, route, x, int(in_sr))}

    outputs = [_verify_output(project, variant_id, o, chain_res, th, inp, recheck_codecs) for o in outs]

    archive = None
    if a_man is not None:
        ad = config.get_delivery(ARCHIVE_DELIVERY)
        ap = variant_dir(project, variant_id) / f"master__{ARCHIVE_DELIVERY}.{output_ext(ad)}"
        if ap.is_file():
            y, sr = audio_io.read(ap)
            archive = {"file": project.rel(ap),
                       "checks": {"S-05": _check_s05(a_man.get("export") or {}, ad),
                                  "S-06": chain_res,
                                  "S-09": _check_s09(y, sr, in_frames, in_sr, th, False,
                                                     [v * (10.0 ** ((float(ld.integrated(y, sr)) - inp["lufs"]) / 20.0))
                                                      for v in inp["dc"]])}}
            archive["overall"] = _overall(archive["checks"])

    results = [o["overall"] for o in outputs] + ([archive["overall"]] if archive else [])
    overall = "fail" if "fail" in results or not outputs else "incomplete" if "incomplete" in results else "pass"
    report = {
        "schema_version": 1,
        "kind": "verify_report",
        "variant": variant_id,
        "project_hash": project.content_hash(),
        "overall": overall,
        "passed": overall == "pass",
        "outputs": outputs,
        "archive": archive,
        "statuses": {"pass": "evaluated and passed", "fail": "evaluated and failed",
                     "not_run": "applies but could not run; never counted as pass",
                     "not_applicable": "not required by the profile",
                     "not_evaluated": "belongs to a later milestone"},
    }
    rdir = Path(project.root) / "reports"
    rdir.mkdir(parents=True, exist_ok=True)
    with open(rdir / f"verify_{variant_id}.json", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    report["path"] = project.rel(rdir / f"verify_{variant_id}.json")
    return report
