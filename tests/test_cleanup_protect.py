"""Cleanup stage: sibilant/breath protection (SPEC 6.4.2 step 4)."""

from __future__ import annotations

import numpy as np

from mankomix.core.cleanup import run_cleanup
from tests.fixtures import synth
from tests.test_cleanup_policy import SR, music

BURSTS_S = (0.3, 1.3, 2.3, 3.3)
BURST_LEN_S = 0.15


def _with_sibilants(x, seed=21, level=0.08):
    """Add noise bursts band-limited to 4.5-9 kHz with 15 ms ramps."""
    rng = np.random.default_rng(seed)
    y = x.copy()
    n = int(BURST_LEN_S * SR)
    ramp = int(0.015 * SR)
    env = np.ones(n)
    env[:ramp] = np.linspace(0.0, 1.0, ramp)
    env[-ramp:] = np.linspace(1.0, 0.0, ramp)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    for t0 in BURSTS_S:
        spec = np.fft.rfft(rng.standard_normal(n))
        spec[(f < 4500.0) | (f > 9000.0)] = 0.0
        b = np.fft.irfft(spec, n)
        b *= level / np.sqrt(np.mean(b ** 2))
        a = int(t0 * SR)
        y[a:a + n] += (b * env)[:, None]
    return y


def _band_energy(x, lo, hi):
    spec = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(x.shape[0], 1.0 / SR)
    sel = (f >= lo) & (f < hi)
    return float(np.sum(np.abs(spec[sel]) ** 2))


def test_sibilant_bursts_keep_their_5_8k_energy():
    base = synth.add_shimmer(music(seconds=4.0, seed=5), SR, depth_db=-24.0, seed=13)
    x = _with_sibilants(base)
    res = run_cleanup(x, SR)
    rep = res.report
    assert rep["steps_planned"]["spectral_reduction"] == "run"
    assert rep["steps"]["protection"]["sibilant_frames"] > 0
    n = int(BURST_LEN_S * SR)
    for t0 in BURSTS_S:
        a = int(t0 * SR)
        e_in = _band_energy(x[a:a + n], 5000.0, 8000.0)
        e_out = _band_energy(res.audio[a:a + n], 5000.0, 8000.0)
        assert e_out >= 0.9 * e_in, (t0, e_out / e_in)
    # the shimmer was still reduced
    assert rep["p16_after"]["shimmer_index_db"] < rep["p16_before"]["shimmer_index_db"] - 3.0
    assert rep["oversuppression"]["flagged"] is False


def test_protection_caps_an_aggressive_policy():
    """Rough (flickering) sibilants under a deliberately aggressive sibilance
    band setting with the transient gates disabled: the protection stage
    alone keeps >= 90 % of their 5-8 kHz energy; without it they are eaten,
    and the over-suppression check notices (delta correlates with them)."""
    from mankomix.core.cleanup import plan_cleanup
    from mankomix.core.cleanup._util import load_policy

    base = synth.add_shimmer(music(seconds=4.0, seed=5), SR, depth_db=-24.0, seed=13)
    smooth = _with_sibilants(base)
    t = np.arange(base.shape[0]) / SR
    gate = 0.5 + 0.5 * np.sign(np.sin(2.0 * np.pi * 25.0 * t))
    x = base + (smooth - base) * gate[:, None]
    bands = load_policy()["bands"]
    for b in bands:
        if b["id"] == "sibilance":
            b.update(threshold_db=1.0, per_pass_max_db=6.0, total_max_db=12.0)
    pol = {"bands": bands, "detector": {"onset": {"comod_db": [100.0, 200.0], "jump_db": 100.0},
                                        "attack": {"rise_db": 100.0}}}
    n = int(BURST_LEN_S * SR)

    def ratios(res):
        return [_band_energy(res.audio[int(t0 * SR):int(t0 * SR) + n], 5000.0, 8000.0)
                / _band_energy(x[int(t0 * SR):int(t0 * SR) + n], 5000.0, 8000.0) for t0 in BURSTS_S]

    protected = run_cleanup(x, SR, plan_cleanup(x, SR, overrides={"policy": pol}))
    assert min(ratios(protected)) >= 0.9
    unprotected = run_cleanup(x, SR, plan_cleanup(x, SR, overrides={"policy": pol, "protection": "skip"}))
    assert max(ratios(unprotected)) < 0.9
    assert unprotected.report["oversuppression"]["rerun"] is True
