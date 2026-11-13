"""Cleanup diagnosis (SPEC 6.4.2 step 1) and the P-16 noise/shimmer metrics.

P-16 as measured here:

* ``noise_floor_dbfs`` / ``noise_floor_hf_dbfs``: mean-square level (dBFS,
  full-scale square = 0 dB) of the quietest 400 ms passages (lowest
  percentile of frames, digital silence excluded), broadband and >= 5 kHz.
  On material without real pauses this is the quietest music, not noise.
* ``hf_ceiling_hz``: frequency where the long-term spectrum falls steeply and
  stays down up to Nyquist (None = full band).
* ``shimmer_index_db``: energy of the flickering, non-tonal, non-transient
  component in 10-14 kHz relative to the 1-8 kHz energy (dB). Companions:
  ``shimmer_flatness`` (band spectral flatness), ``shimmer_modulation``
  (fast envelope modulation depth) and ``shimmer_signal_corr`` (correlation
  of the band envelope with the 1-5 kHz envelope: signal-correlated noise).
* side artifacts: side-channel shimmer index and the side/mid HF anomaly.
* ``head_click``: click detected near the start.
* ``lowmid_density_db``: 250-500 Hz energy relative to the total.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from . import clicks as _clicks
from ._util import (EPS, as_2d, bin_range, db10, load_policy, mid_side, power_norm,
                    rnd, stft, stft_freqs, stft_params, v)
from .protect import _flatness, detect_events
from .spectral import attack_frames, flicker_excess_power, onset_gate

SHIMMER_BAND = (10000.0, 14000.0)
REF_BAND = (1000.0, 8000.0)
MID_BAND = (1000.0, 5000.0)
HF_NOISE_LO = 5000.0
SIDE_HF_BAND = (10000.0, 16000.0)


class Analysis:
    """STFT power of mid (and side) of one signal, shared by the metrics."""

    def __init__(self, x2d: np.ndarray, sr: float, policy: dict):
        self.sr = float(sr)
        self.n_fft, self.hop = stft_params(sr, policy)
        self.freqs = stft_freqs(sr, self.n_fft)
        self.frame_rate = sr / self.hop
        self.norm = power_norm(self.n_fft)
        mid, side = mid_side(x2d)
        sm = stft(mid, self.n_fft, self.hop)
        self.p_mid = (sm.real ** 2 + sm.imag ** 2).astype(np.float32)
        del sm
        if side is not None:
            ss = stft(side, self.n_fft, self.hop)
            self.p_side = (ss.real ** 2 + ss.imag ** 2).astype(np.float32)
            self.p_all = self.p_mid + self.p_side  # = mean channel power
        else:
            self.p_side = None
            self.p_all = self.p_mid
        att = attack_frames(mid, sr, self.n_fft, self.hop, self.p_mid.shape[0], policy)
        self.gate = onset_gate(self.p_mid, self.freqs, self.frame_rate, policy, attacks=att)

    def band_sum(self, p: np.ndarray, lo: float, hi: float) -> np.ndarray:
        sl = bin_range(self.freqs, lo, hi)
        return p[:, sl].sum(axis=1).astype(np.float64)


# --- individual metrics ---------------------------------------------------------

def hf_ceiling(ltas_power: np.ndarray, freqs: np.ndarray, sr: float, policy: dict) -> dict:
    """HF ceiling from a long-term power spectrum (linear, per bin)."""
    cp = policy["ceiling"]
    df = freqs[1] - freqs[0]
    sm = max(1, int(round(float(v(cp["smooth_hz"])) / df)))
    lt = ndimage.uniform_filter1d(ltas_power.astype(np.float64), sm, mode="nearest")
    ldb = 10.0 * np.log10(lt + EPS)
    nyq = sr / 2.0
    top = min(nyq * 0.995, 24000.0)
    b_far, b_near = v(cp["below_window_hz"])
    gap = float(v(cp["above_gap_hz"]))
    drop = float(v(cp["drop_db"]))
    fmin = float(v(cp["search_min_hz"]))
    peak_db = float(np.max(ldb[freqs >= 100.0])) if np.any(freqs >= 100.0) else float(np.max(ldb))
    min_content = float(v(cp["min_content_db"]))
    result = {"hf_ceiling_hz": None, "drop_db": None}
    cands = np.flatnonzero((freqs >= fmin) & (freqs <= top - gap - 4 * df))
    found = None
    # suffix 95th percentile is expensive; precompute on a coarse step
    step = max(1, int(round(50.0 / df)))
    for k in cands[::step]:
        f = freqs[k]
        bsl = bin_range(freqs, f - b_far, f - b_near)
        asl = bin_range(freqs, f + gap, top)
        if bsl.stop - bsl.start < 2 or asl.stop - asl.start < 2:
            continue
        below = float(np.median(ldb[bsl]))
        if below < peak_db + min_content:
            continue
        above = float(np.percentile(ldb[asl], 95.0))
        if below - above >= drop:
            found = (k, below, below - above)
            break
    if found is None:
        return result
    k, below, dd = found
    edge = below - float(v(cp["edge_db"]))
    k_start = int(np.searchsorted(freqs, freqs[k] - b_near))
    idx = np.flatnonzero(ldb[k_start:] < edge)
    fc = float(freqs[k_start + idx[0]]) if idx.size else float(freqs[k])
    if fc >= float(v(cp["full_band_min_hz"])):
        return result
    result["hf_ceiling_hz"] = round(fc, 1)
    result["drop_db"] = round(dd, 2)
    return result


def _noise_floor(an: Analysis, policy: dict) -> dict:
    dp = policy["diagnosis"]
    win = max(1, int(round(float(v(dp["noise_floor_window_s"])) * an.frame_rate)))
    tot = an.p_all.sum(axis=1).astype(np.float64) * an.norm
    hf = an.band_sum(an.p_all, HF_NOISE_LO, an.sr) * an.norm
    tot_s = ndimage.uniform_filter1d(tot, win, mode="nearest")
    hf_s = ndimage.uniform_filter1d(hf, win, mode="nearest")
    # drop the padded edges (the STFT pads one window of zeros on each side)
    edge = int(np.ceil(an.n_fft / an.hop))
    if tot_s.shape[0] > 2 * edge + 1:
        tot_s = tot_s[edge:-edge]
        hf_s = hf_s[edge:-edge]
    silence = 10.0 ** (float(v(dp["silence_dbfs"])) / 10.0)
    live = tot_s > silence
    if not np.any(live):
        return {"noise_floor_dbfs": None, "noise_floor_hf_dbfs": None, "quiet_fraction": 0.0}
    thr = np.percentile(tot_s[live], float(v(dp["noise_floor_percentile"])))
    q = live & (tot_s <= thr)
    return {
        "noise_floor_dbfs": rnd(db10(np.mean(tot_s[q]))),
        "noise_floor_hf_dbfs": rnd(db10(np.mean(hf_s[q]))),
        "quiet_fraction": rnd(float(np.mean(q)), 4),
    }


def _shimmer(an: Analysis, policy: dict, ceiling_hz: float | None) -> dict:
    ref = float(np.sum(an.band_sum(an.p_mid, *REF_BAND))) + EPS
    hi = SHIMMER_BAND[1] if ceiling_hz is None else min(SHIMMER_BAND[1], ceiling_hz)
    lo = SHIMMER_BAND[0]
    out: dict = {}
    if hi - lo < 500.0 or an.sr / 2.0 <= lo:
        out.update(shimmer_index_db=None, shimmer_flatness=None, shimmer_modulation=None,
                   shimmer_signal_corr=None)
    else:
        fx = flicker_excess_power(an.p_mid, an.freqs, an.frame_rate, policy, lo, hi, gate=an.gate)
        out["shimmer_index_db"] = rnd(db10(fx / ref) if fx > 0 else -120.0)
        sl = bin_range(an.freqs, lo, hi)
        e = an.p_mid[:, sl].sum(axis=1).astype(np.float64)
        em = an.band_sum(an.p_mid, *MID_BAND)
        live = e > (np.max(e) * 1e-8 if e.size else 0)
        if np.sum(live) >= 8:
            out["shimmer_flatness"] = rnd(float(np.median(_flatness(an.p_mid[live][:, sl]))), 4)
            slow = ndimage.uniform_filter1d(e, 15, mode="nearest")
            out["shimmer_modulation"] = rnd(float(np.std((e - slow)[live]) / (np.mean(e[live]) + EPS)), 4)
            a = np.log(e[live] + EPS)
            b = np.log(em[live] + EPS)
            if np.std(a) > 0 and np.std(b) > 0:
                out["shimmer_signal_corr"] = rnd(float(np.corrcoef(a, b)[0, 1]), 4)
            else:
                out["shimmer_signal_corr"] = None
        else:
            out.update(shimmer_flatness=None, shimmer_modulation=None, shimmer_signal_corr=None)
    # side artifacts
    if an.p_side is not None and an.sr / 2.0 > SIDE_HF_BAND[0]:
        fxs = flicker_excess_power(an.p_side, an.freqs, an.frame_rate, policy, lo, max(hi, lo + 500.0),
                                   gate=an.gate)
        out["side_shimmer_index_db"] = rnd(db10(fxs / ref) if fxs > 0 else -120.0)
        s_hf = float(np.sum(an.band_sum(an.p_side, *SIDE_HF_BAND))) + EPS
        m_hf = float(np.sum(an.band_sum(an.p_mid, *SIDE_HF_BAND))) + EPS
        s_ref = float(np.sum(an.band_sum(an.p_side, *REF_BAND))) + EPS
        out["side_hf_excess_db"] = rnd(db10(s_hf / m_hf) - db10(s_ref / ref))
        out["side_hf_level_db"] = rnd(db10(s_hf / ref))
    else:
        out["side_shimmer_index_db"] = None
        out["side_hf_excess_db"] = None
        out["side_hf_level_db"] = None
    return out


def _above_ceiling(an: Analysis, policy: dict, ceiling_hz: float | None) -> dict:
    if ceiling_hz is None:
        return {"above_ceiling_artifact_db": None, "above_ceiling_level_db": None}
    ref = float(np.sum(an.band_sum(an.p_mid, *REF_BAND))) + EPS
    fx = flicker_excess_power(an.p_all, an.freqs, an.frame_rate, policy, ceiling_hz + 200.0,
                              an.sr / 2.0, threshold_db=2.0, gate=an.gate)
    above = float(np.mean(an.p_all[:, bin_range(an.freqs, ceiling_hz + 300.0, an.sr / 2.0)])) + EPS
    below = float(np.mean(an.p_all[:, bin_range(an.freqs, ceiling_hz - 2000.0, ceiling_hz - 300.0)])) + EPS
    return {"above_ceiling_artifact_db": rnd(db10(fx / ref) if fx > 0 else -120.0),
            "above_ceiling_level_db": rnd(db10(above / below))}


# --- public API -------------------------------------------------------------------

def noise_shimmer_metrics(x, sr: float, *, policy: dict | None = None,
                          analysis: Analysis | None = None,
                          with_clicks: bool = True) -> dict:
    """P-16 metrics of a signal (see module docstring)."""
    policy = policy or load_policy()
    x2d, _ = as_2d(x)
    an = analysis or Analysis(x2d, sr, policy)
    ltas = an.p_all.mean(axis=0)
    ceil = hf_ceiling(ltas, an.freqs, sr, policy)
    fc = ceil["hf_ceiling_hz"]
    m: dict = {"sr": int(sr), "channels": int(x2d.shape[1]),
               "duration_s": rnd(x2d.shape[0] / sr, 4)}
    m.update(_noise_floor(an, policy))
    m["hf_ceiling_hz"] = fc
    m["hf_ceiling_drop_db"] = ceil["drop_db"]
    m.update(_shimmer(an, policy, fc))
    m.update(_above_ceiling(an, policy, fc))
    total = float(np.sum(ltas)) + EPS
    lm = float(np.sum(ltas[bin_range(an.freqs, 250.0, 500.0)]))
    m["lowmid_density_db"] = rnd(db10(lm / total) if lm > 0 else -120.0)
    ev = detect_events(an.p_mid, an.freqs, an.frame_rate, policy)
    m["sibilant_seconds"] = rnd(float(np.sum(ev["sibilant"])) / an.frame_rate)
    m["noise_event_seconds"] = rnd(float(np.sum(ev["noise_event"])) / an.frame_rate)
    if with_clicks:
        cl = _clicks.detect_clicks(x2d, sr, policy=policy)
        head = float(v(policy["clicks"]["head_s"]))
        m["clicks"] = cl
        m["click_count"] = len(cl)
        m["head_click"] = any(c["peak"] < head * sr for c in cl)
    return m


def decide(metrics: dict, policy: dict) -> tuple[dict, dict]:
    """Step decisions run/light/skip and reasons from P-16 metrics."""
    dp = policy["diagnosis"]
    steps: dict = {}
    reasons: dict = {k: [] for k in ("click_repair", "spectral_reduction", "protection", "completion")}

    nc = int(metrics.get("click_count") or 0)
    if nc:
        steps["click_repair"] = "run"
        heads = " (including the head)" if metrics.get("head_click") else ""
        reasons["click_repair"].append(f"{nc} click(s) detected{heads}")
    else:
        steps["click_repair"] = "skip"
        reasons["click_repair"].append("no click detected")

    sh = metrics.get("shimmer_index_db")
    ssh = metrics.get("side_shimmer_index_db")
    ac = metrics.get("above_ceiling_artifact_db")
    sx = metrics.get("side_hf_excess_db")
    slev = metrics.get("side_hf_level_db")
    run_db = float(v(dp["shimmer_run_db"]))
    light_db = float(v(dp["shimmer_light_db"]))
    action = "skip"
    r = reasons["spectral_reduction"]
    if sh is not None and sh >= run_db:
        action = "run"
        r.append(f"shimmer index {sh:.1f} dB >= run threshold {run_db:.1f} dB")
    elif sh is not None and sh >= light_db:
        action = "light"
        r.append(f"shimmer index {sh:.1f} dB between light {light_db:.1f} and run {run_db:.1f} dB")
    if ssh is not None and ssh >= float(v(dp["side_shimmer_run_db"])):
        action = "run"
        r.append(f"side shimmer index {ssh:.1f} dB >= {float(v(dp['side_shimmer_run_db'])):.1f} dB")
    if (sx is not None and slev is not None and sx >= float(v(dp["side_hf_excess_db"]))
            and slev >= float(v(dp["side_hf_min_level_db"]))):
        if action == "skip":
            action = "light"
        r.append(f"side HF anomaly: side/mid ratio in 10-16 kHz is {sx:.1f} dB above the 1-8 kHz ratio")
    alev = metrics.get("above_ceiling_level_db")
    if (ac is not None and ac >= float(v(dp["above_ceiling_run_db"]))
            and alev is not None and alev >= float(v(dp["above_ceiling_min_level_db"]))):
        action = "run"
        r.append(f"flickering content above the HF ceiling ({ac:.1f} dB)")
    if action == "skip":
        r.append("no shimmer, side or above-ceiling artifact detected"
                 + (f" (shimmer index {sh:.1f} dB < {light_db:.1f} dB)" if sh is not None else ""))
    steps["spectral_reduction"] = action

    if action != "skip":
        steps["protection"] = "run"
        reasons["protection"].append(
            f"guards sibilants/breaths/cymbals during reduction "
            f"(sibilant {metrics.get('sibilant_seconds', 0)} s, breath/cymbal {metrics.get('noise_event_seconds', 0)} s detected)")
    else:
        steps["protection"] = "skip"
        reasons["protection"].append("no spectral reduction to guard")

    fc = metrics.get("hf_ceiling_hz")
    if fc is not None:
        auto = bool(v(policy["completion"]["auto_enable_on_ceiling"]))
        steps["completion"] = "run" if auto else "skip"
        reasons["completion"].append(
            f"HF ceiling at {fc:.0f} Hz; deterministic DSP completion "
            + ("enabled by policy" if auto else "available but off by default (enable in the plan)"))
    else:
        steps["completion"] = "skip"
        reasons["completion"].append("no HF ceiling (full band)")
    return steps, reasons


def diagnose(x, sr: float, *, policy: dict | None = None) -> dict:
    """P-16 metrics plus per-step decisions (run / light / skip) and reasons."""
    policy = policy or load_policy()
    metrics = noise_shimmer_metrics(x, sr, policy=policy)
    steps, reasons = decide(metrics, policy)
    skip_all = all(a == "skip" for a in steps.values())
    if skip_all:
        reasons["overall"] = ["nothing detected: the whole cleanup stage is skipped (SPEC 6.4.2 step 1)"]
    return {"metrics": metrics, "steps": steps, "reasons": reasons, "skip_all": skip_all}
