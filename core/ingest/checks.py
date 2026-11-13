"""Import checks and the conform policy (docs/SPEC.md 6.1.4, 6.1.5; D-054).

Checks measure and report. They never modify, convert or rewrite any file
(A-7, A-12, D-030). Assets are read one at a time to keep memory bounded; the
only derived audio is a temporary in-memory stem sum (resampled with
resample_poly when rates differ) for the stem-sum consistency check, and it is
never written anywhere.
"""

from __future__ import annotations

import math
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .. import audio_io
from ..errors import InputError
from .naming import is_unknown_role, load_knowledge

EPS = 1e-30


# --------------------------------------------------------------------------
# Conform policy (D-054)
# --------------------------------------------------------------------------

def project_sample_rate(assets: Iterable[dict]) -> int:
    """Majority sample rate of the assets; a tie goes to the higher rate."""
    counts = Counter(int(a["sample_rate"]) for a in assets)
    if not counts:
        raise InputError("no assets to derive a project sample rate from")
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def length_at_rate(frames: int, from_rate: int, to_rate: int) -> int:
    """Length in samples after resampling (same rounding as resample_poly: ceil)."""
    if from_rate == to_rate:
        return int(frames)
    return int(-(-int(frames) * int(to_rate) // int(from_rate)))


def conform_policy(assets: list[dict]) -> dict:
    """Render-time conform policy for the given assets (nothing is converted here).

    Returns the dict stored at timebase.conform_policy:
    {sample_rate:"majority", alignment:"head", short_assets:"pad_silence_at_render",
     applied:[{asset, from_rate, to_rate, action}]}
    action is "resample_at_render" for a rate change, "pad_silence_at_render"
    for an asset shorter than the project length (both may apply to one asset).
    """
    assets = list(assets)
    policy = {"sample_rate": "majority", "alignment": "head",
              "short_assets": "pad_silence_at_render", "applied": []}
    if not assets:
        return policy
    pr = project_sample_rate(assets)
    longest = max(length_at_rate(a["length_samples"], a["sample_rate"], pr) for a in assets)
    for a in assets:
        sr = int(a["sample_rate"])
        if sr != pr:
            policy["applied"].append({"asset": a["id"], "from_rate": sr, "to_rate": pr,
                                      "action": "resample_at_render"})
        if length_at_rate(a["length_samples"], sr, pr) < longest:
            policy["applied"].append({"asset": a["id"], "from_rate": sr, "to_rate": pr,
                                      "action": "pad_silence_at_render"})
    return policy


def resolve_timebase(assets: list[dict]) -> dict:
    """{sample_rate, length_samples, conform_policy} for the project timebase."""
    assets = list(assets)
    pr = project_sample_rate(assets)
    length = max(length_at_rate(a["length_samples"], a["sample_rate"], pr) for a in assets)
    return {"sample_rate": pr, "length_samples": length, "conform_policy": conform_policy(assets)}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def load_thresholds() -> dict:
    return load_knowledge("ingest_thresholds")


def resolve_asset_file(project: Any, asset: dict) -> Path:
    """Real location of an asset: inside the project, or a linked file outside it."""
    if hasattr(project, "asset_path"):
        try:
            return Path(project.asset_path(asset["id"]))
        except InputError:
            raise
        except Exception:  # fall back to the plain rules below
            pass
    if asset.get("linked"):
        try:
            from ..config import get_linked_location  # type: ignore[import-not-found]
        except ImportError as exc:
            raise InputError("linked asset needs core.config.get_linked_location") from exc
        loc = get_linked_location(asset["sha256"])
        if not loc:
            raise InputError(f"linked asset location unknown: {asset.get('original_name')}",
                             details={"asset": asset.get("id"), "sha256": asset.get("sha256")})
        return Path(loc)
    return Path(project.root) / asset["path"]


def _db(x: float) -> float:
    return 20.0 * math.log10(max(float(x), EPS))


def _r(x: float | None, nd: int = 2) -> float | None:
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None if math.isnan(x) else (-999.0 if x < 0 else 999.0)
    return round(x, nd)


def _check(check: str, level: str, asset: str | None, message: str, values: dict | None = None) -> dict:
    return {"check": check, "level": level, "asset": asset, "message": message, "values": values or {}}


def _bit_depth(subtype: str) -> str:
    s = (subtype or "unknown").upper()
    return {"FLOAT": "32f", "DOUBLE": "64f", "PCM_16": "16", "PCM_24": "24", "PCM_32": "32",
            "PCM_S8": "8", "PCM_U8": "8"}.get(s, s.lower())


def _majority(values: list) -> Any:
    counts = Counter(values)
    return max(counts.items(), key=lambda kv: (kv[1], str(kv[0])))[0]


# --------------------------------------------------------------------------
# Per-signal checks
# --------------------------------------------------------------------------

def _run_lengths(mask: np.ndarray) -> np.ndarray:
    """Lengths of runs of True in a 1-D boolean array."""
    if not mask.any():
        return np.zeros(0, dtype=np.int64)
    padded = np.concatenate(([0], mask.astype(np.int8), [0]))
    d = np.diff(padded)
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return ends - starts


def _signal_checks(aid: str, x: np.ndarray, sr: int, th: dict) -> tuple[list[dict], bool]:
    """Health, silence and headroom checks on one asset. Returns (checks, is_silent)."""
    out: list[dict] = []
    finite = np.isfinite(x)
    n_bad = int(x.size - np.count_nonzero(finite))
    if n_bad:
        out.append(_check("health_non_finite", th.get("non_finite", {}).get("level", "warning"), aid,
                          f"{n_bad} NaN/Inf samples", {"non_finite_samples": n_bad}))
        x = np.where(finite, x, 0.0)

    peak = float(np.max(np.abs(x))) if x.size else 0.0
    sil = th["silence"]
    if x.size == 0 or (sil.get("all_exact_zero_is_silent", True) and peak == 0.0) \
            or _db(peak) < float(sil["peak_dbfs_below"]):
        out.append(_check("silence", sil.get("level", "reject"), aid,
                          "stem is silent (failed export?): drop it or re-export; import kept the file as is",
                          {"peak_dbfs": _r(_db(peak)), "threshold_dbfs": sil["peak_dbfs_below"]}))
        return out, True

    # Clipping: runs of consecutive samples at/above the clip level.
    cl = th["clipping"]
    level = float(cl["clip_level_abs"])
    min_run = int(cl["min_run_samples"])
    runs_total, longest, clipped = 0, 0, 0
    for ch in range(x.shape[1]):
        lengths = _run_lengths(np.abs(x[:, ch]) >= level)
        long_runs = lengths[lengths >= min_run]
        runs_total += int(long_runs.size)
        clipped += int(long_runs.sum())
        if lengths.size:
            longest = max(longest, int(lengths.max()))
    over_fs = int(np.count_nonzero(np.abs(x) > 1.0))
    if runs_total >= int(cl.get("warn_min_runs", 1)):
        out.append(_check("health_clipping", "warning", aid,
                          f"{runs_total} clipped runs (>= {min_run} samples at |x| >= {level})",
                          {"runs": runs_total, "longest_run": longest, "clipped_samples": clipped,
                           "sample_peak_dbfs": _r(_db(peak)), "over_full_scale_samples": over_fs}))
    elif over_fs and cl.get("report_over_full_scale", True):
        out.append(_check("health_over_full_scale", "warning", aid,
                          f"{over_fs} samples above 0 dBFS (float file; would clip in fixed point)",
                          {"over_full_scale_samples": over_fs, "sample_peak_dbfs": _r(_db(peak))}))

    # DC offset.
    dc = np.mean(x, axis=0)
    dc_db = _db(float(np.max(np.abs(dc))))
    if dc_db > float(th["dc_offset"]["warn_abs_mean_dbfs_above"]):
        out.append(_check("health_dc_offset", "warning", aid, f"DC offset {dc_db:.1f} dBFS",
                          {"dc_dbfs": _r(dc_db), "dc_per_channel": [_r(v, 6) for v in dc]}))

    # Head click: largest jump in the first window vs the following reference span.
    hc = th["head_click"]
    w = max(1, int(round(sr * float(hc["window_ms"]) / 1000.0)))
    r = max(1, int(round(sr * float(hc["reference_ms"]) / 1000.0)))
    seg = x[: w + r]
    jumps = np.abs(np.diff(np.vstack([np.zeros((1, x.shape[1])), seg]), axis=0)).max(axis=1)
    head = jumps[:w]
    ref = jumps[w:]
    if head.size:
        jmax = float(head.max())
        ref_level = float(np.percentile(ref, float(hc["reference_percentile"]))) if ref.size else 0.0
        ratio_db = _db(jmax) - _db(ref_level) if ref_level > 0 else 999.0
        if _db(jmax) >= float(hc["min_jump_dbfs"]) and ratio_db >= float(hc["jump_over_reference_db"]):
            pos = int(np.argmax(head))
            out.append(_check("health_head_click", "warning", aid,
                              f"possible click at {1000.0 * pos / sr:.1f} ms",
                              {"position_samples": pos, "position_ms": _r(1000.0 * pos / sr),
                               "jump_dbfs": _r(_db(jmax)), "over_reference_db": _r(ratio_db)}))

    out.append(_headroom_check(aid, x, sr, peak, th["headroom"]))
    return out, False


def _headroom_check(aid: str, x: np.ndarray, sr: int, peak: float, hr: dict) -> dict:
    lim = hr["over_limiting"]
    try:
        from ..measure.loudness import loudness_summary  # type: ignore[import-not-found]
        s = loudness_summary(x, sr)
        tp = float(s["true_peak_dbtp"])
        il = float(s["integrated_lufs"])
        plr = s.get("plr_db")
        plr = float(plr) if plr is not None else tp - il
        values = {"true_peak_dbtp": _r(tp), "integrated_lufs": _r(il), "plr_db": _r(plr),
                  "headroom_db": _r(-tp), "sample_peak_dbfs": _r(_db(peak))}
        if s.get("psr_db") is not None:
            values["psr_db"] = _r(s["psr_db"])
        suspicious = tp > float(lim["true_peak_dbtp_above"]) and plr < float(lim["plr_db_below"])
        basis = "true peak / PLR"
    except Exception as exc:  # measure module missing or failing: crude fallback
        fb = hr["fallback"]
        rms = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
        crest = _db(peak) - _db(rms)
        values = {"sample_peak_dbfs": _r(_db(peak)), "rms_dbfs": _r(_db(rms)), "crest_db": _r(crest),
                  "headroom_db": _r(-_db(peak)), "fallback": True,
                  "fallback_reason": type(exc).__name__}
        suspicious = _db(peak) > float(fb["sample_peak_dbfs_above"]) and crest < float(fb["crest_db_below"])
        basis = "fallback: sample peak / RMS crest factor (loudness module unavailable)"
    if suspicious:
        return _check("headroom", hr.get("level", "warning"), aid,
                      f"{hr.get('message', 'likely master-bus processed')} [{basis}]", values)
    return _check("headroom", "info", aid, f"peak and headroom recorded [{basis}]", values)


def _to_channels(x: np.ndarray, ch: int) -> np.ndarray:
    if x.shape[1] == ch:
        return x
    if x.shape[1] == 1:
        return np.repeat(x, ch, axis=1)
    if ch == 1:
        return x.mean(axis=1, keepdims=True)
    if x.shape[1] > ch:
        return x[:, :ch]
    return np.concatenate([x, np.repeat(x[:, -1:], ch - x.shape[1], axis=1)], axis=1)


def _to_rate(x: np.ndarray, sr: int, pr: int) -> np.ndarray:
    if sr == pr:
        return x
    from scipy.signal import resample_poly
    f = Fraction(pr, sr)
    return resample_poly(x, f.numerator, f.denominator, axis=0)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def run_checks(project: Any, *, thresholds: dict | None = None) -> list[dict]:
    """Run every import check over the project's assets. Never modifies files.

    Each result: {check, level: info|warning|reject, asset, message, values}.
    """
    th = thresholds or load_thresholds()
    data = project.data
    assets: list[dict] = list(data.get("assets") or [])
    out: list[dict] = []
    if not assets:
        return out
    tb = resolve_timebase(assets)
    pr, longest = tb["sample_rate"], tb["length_samples"]
    by_id = {a["id"]: a for a in assets}
    fullmix_id = data.get("fullmix_asset")
    if fullmix_id not in by_id:
        fullmix_id = None

    # ---- format ----------------------------------------------------------
    for a in assets:
        out.append(_check("format", "info", a["id"],
                          f"{a.get('format')} {a['sample_rate']} Hz {a['channels']} ch "
                          f"{a['length_samples']} samples",
                          {"sample_rate": a["sample_rate"], "channels": a["channels"],
                           "bit_depth": _bit_depth(a.get("subtype", "")), "container": a.get("container"),
                           "length_samples": a["length_samples"], "duration_s": a.get("duration_s")}))
    for a in assets:
        if int(a["sample_rate"]) != pr:
            out.append(_check("format_sample_rate", "warning", a["id"],
                              f"sample rate {a['sample_rate']} Hz differs from the project rate {pr} Hz; "
                              "not converted now, resampled only at render",
                              {"sample_rate": a["sample_rate"], "project_sample_rate": pr,
                               "action": "resample_at_render"}))
    major_ch = _majority([int(a["channels"]) for a in assets])
    major_depth = _majority([_bit_depth(a.get("subtype", "")) for a in assets])
    for a in assets:
        if int(a["channels"]) != major_ch:
            out.append(_check("format_channels", "warning", a["id"],
                              f"{a['channels']} channels while most assets have {major_ch}",
                              {"channels": a["channels"], "majority_channels": major_ch}))
        depth = _bit_depth(a.get("subtype", ""))
        if depth != major_depth:
            out.append(_check("format_bit_depth", "warning", a["id"],
                              f"bit depth {depth} while most assets have {major_depth}",
                              {"bit_depth": depth, "majority_bit_depth": major_depth}))
        if a.get("lossy"):
            out.append(_check("format_lossy", "warning", a["id"],
                              "lossy input: separation and cleanup quality will suffer",
                              {"container": a.get("container")}))

    # ---- length (D-054) ---------------------------------------------------
    lm = th["length_mismatch"]["reject_above"]
    longest_s = longest / pr
    boundary_s = max(float(lm["seconds"]), float(lm["fraction_of_length"]) * longest_s)
    for a in assets:
        n = length_at_rate(a["length_samples"], a["sample_rate"], pr)
        diff = longest - n
        if diff <= 0:
            continue
        diff_s = diff / pr
        values = {"length_samples_at_project_rate": n, "longest_samples": longest,
                  "diff_samples": diff, "diff_s": round(diff_s, 4), "boundary_s": round(boundary_s, 4)}
        if diff_s > boundary_s:
            out.append(_check("length_mismatch", "reject", a["id"],
                              f"{diff_s:.3f} s shorter than the longest asset (> {boundary_s:.3f} s): "
                              "mixed renders or takes suspected; choose an alignment (no automatic stretch)",
                              values))
        else:
            out.append(_check("length_mismatch", "warning", a["id"],
                              f"{diff_s:.3f} s shorter than the longest asset; tail padded with silence at render",
                              values))

    # ---- duplicates / unknown role ---------------------------------------
    seen: dict[str, str] = {}
    for a in assets:
        if a["sha256"] in seen:
            out.append(_check("duplicate", "warning", a["id"],
                              f"same content as {seen[a['sha256']]}", {"duplicate_of": seen[a["sha256"]],
                                                                       "sha256": a["sha256"]}))
        else:
            seen[a["sha256"]] = a["id"]
    for sk in (data.get("ingest") or {}).get("skipped", []) or []:
        if sk.get("reason") == "duplicate":
            out.append(_check("duplicate", "warning", sk.get("duplicate_of"),
                              f"'{sk.get('original_name')}' has the same content as {sk.get('duplicate_of')}; "
                              "not imported again", {"original_name": sk.get("original_name"),
                                                     "sha256": sk.get("sha256")}))
        elif sk.get("reason") == "derived_sum":
            out.append(_check("derived_sum", "warning", None,
                              f"'{sk.get('original_name')}' looks like a sum of other stems; not imported",
                              {"original_name": sk.get("original_name")}))
    for a in assets:
        if is_unknown_role(a):
            out.append(_check("unknown_role", "warning", a["id"],
                              f"role of '{a.get('original_name')}' could not be inferred; set to '{a.get('role')}'",
                              {"original_name": a.get("original_name"), "role": a.get("role")}))

    # ---- signal checks, one file at a time; build the stem sum -------------
    fm_channels = int(by_id[fullmix_id]["channels"]) if fullmix_id else None
    stem_sum: np.ndarray | None = None
    summed: list[str] = []
    order = [a for a in assets if a["id"] != fullmix_id] + ([by_id[fullmix_id]] if fullmix_id else [])
    fullmix_x: np.ndarray | None = None
    for a in order:
        try:
            path = resolve_asset_file(project, a)
            x, sr = audio_io.read(path)
        except InputError as exc:
            out.append(_check("readable", "reject", a["id"], f"cannot read asset: {exc.message}", {}))
            continue
        res, _silent = _signal_checks(a["id"], x, sr, th)
        out.extend(res)
        if not fullmix_id:
            del x
            continue
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        y = _to_channels(_to_rate(x, sr, pr), fm_channels)
        del x
        if a["id"] == fullmix_id:
            fullmix_x = y
        elif a.get("origin") != "reference_fullmix" and a.get("role") != "fullmix":
            if stem_sum is None:
                stem_sum = np.zeros((longest, fm_channels), dtype=np.float64)
            n = min(len(y), longest)
            stem_sum[:n] += y[:n]
            summed.append(a["id"])
        del y

    # ---- stem-sum consistency (record only) -------------------------------
    if fullmix_id and fullmix_x is not None and stem_sum is not None:
        out.append(_stem_sum_check(fullmix_id, fullmix_x, stem_sum, summed, pr, th["stem_sum"]))
    return out


def _stem_sum_check(fid: str, mix: np.ndarray, ssum: np.ndarray, summed: list[str], pr: int,
                    cfg: dict) -> dict:
    n = max(len(mix), len(ssum))
    if len(mix) < n:
        mix = np.vstack([mix, np.zeros((n - len(mix), mix.shape[1]))])
    if len(ssum) < n:
        ssum = np.vstack([ssum, np.zeros((n - len(ssum), ssum.shape[1]))])
    e_mix = float(np.sum(mix * mix))
    e_sum = float(np.sum(ssum * ssum))
    cross = float(np.sum(mix * ssum))
    e_res = float(np.sum((mix - ssum) ** 2))
    corr = cross / math.sqrt(e_mix * e_sum) if e_mix > 0 and e_sum > 0 else None
    residual_db = 10.0 * math.log10(max(e_res, EPS) / e_mix) if e_mix > 0 else None
    values: dict[str, Any] = {"residual_db": _r(residual_db), "correlation": _r(corr, 4),
                              "stems_summed": summed, "compared_samples": n, "sample_rate": pr,
                              "alignment": "head", "gain_db": 0.0}
    if e_sum > 0 and e_mix > 0:
        g = cross / e_sum
        res_fit = max(e_mix - cross * cross / e_sum, 0.0)
        values["best_fit_gain_db"] = _r(_db(abs(g))) if g != 0 else None
        values["residual_after_gain_fit_db"] = _r(10.0 * math.log10(max(res_fit, EPS) / e_mix))
    msg = (f"stem sum vs full mix: null residual {values['residual_db']} dB, "
           f"correlation {values['correlation']} (record only)")
    return _check("stem_sum_consistency", cfg.get("level", "info"), fid, msg, values)
