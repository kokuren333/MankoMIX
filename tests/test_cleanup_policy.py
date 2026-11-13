"""Cleanup stage: policy data, S-07 low-band null test, skip-when-clean, D-041 hook.

Signals are synthesized here (nothing is written to disk). ``music`` is also
imported by the other test_cleanup_* files.
"""

from __future__ import annotations

import numpy as np
import pytest

from mankomix.core.cleanup import (diagnose, neural_completion, null_test_residual_dbfs,
                                   plan_cleanup, run_cleanup)
from mankomix.core.cleanup._util import load_policy, v
from mankomix.core.errors import ValidationError
from tests.fixtures import synth

SR = 48000


def music(seconds: float = 5.0, sr: int = SR, seed: int = 0, noise_dbfs: float = -70.0) -> np.ndarray:
    """Music-like stereo test signal: three panned harmonic voices (partials
    up to 18 kHz) changing every 0.5 s, a kick every 0.5 s, a high-passed
    noise hit every second, and a faint white noise floor. Full band, no
    flicker, no clicks."""
    rng = np.random.default_rng(seed)
    n = int(sr * seconds)
    out = np.zeros((n, 2))
    note = 0.5
    roots = [57, 60, 64, 62, 55, 59, 65, 67]
    seg_n = int(note * sr)
    seg = np.arange(seg_n) / sr
    env = (np.minimum(seg / 0.01, 1.0) * np.exp(-seg * 2.0)
           * np.clip((note - seg) / 0.02, 0.0, 1.0))
    for i in range(int(seconds / note)):
        s0 = i * seg_n
        e = min(seg_n, n - s0)
        for vi, off in enumerate((0, 4, 7)):
            f0 = 440.0 * 2.0 ** ((roots[i % len(roots)] + off + 12 * (vi == 2) - 69) / 12.0)
            k = np.arange(1, int(18000.0 // f0) + 1)
            ph = rng.uniform(0.0, 2.0 * np.pi, k.size)
            tone = (np.sin(2.0 * np.pi * f0 * np.outer(seg, k) + ph) / k ** 1.3).sum(axis=1)
            pan = (-0.5, 0.0, 0.5)[vi]
            gl, gr = np.cos((pan + 1.0) * np.pi / 4.0), np.sin((pan + 1.0) * np.pi / 4.0)
            out[s0:s0 + e, 0] += 0.15 * gl * (tone * env)[:e]
            out[s0:s0 + e, 1] += 0.15 * gr * (tone * env)[:e]
        hit_n = int(0.2 * sr)
        ht = np.arange(hit_n) / sr
        eh = min(hit_n, n - s0)
        kick = np.sin(2.0 * np.pi * (50.0 * ht + 70.0 / 30.0 * (1.0 - np.exp(-30.0 * ht)))) * np.exp(-18.0 * ht)
        out[s0:s0 + eh] += 0.4 * kick[:eh, None]
        if i % 2 == 1:
            spec = np.fft.rfft(rng.standard_normal((hit_n, 2)), axis=0)
            spec[np.fft.rfftfreq(hit_n, 1.0 / sr) < 2000.0] = 0.0
            hat = np.fft.irfft(spec, hit_n, axis=0) * np.exp(-30.0 * ht)[:, None]
            out[s0:s0 + eh] += 0.12 * hat[:eh]
    out *= 0.5 / np.max(np.abs(out))
    out += 10.0 ** (noise_dbfs / 20.0) * rng.standard_normal((n, 2))
    return out


@pytest.fixture(scope="module")
def clean():
    return music()


# --- policy data ------------------------------------------------------------------

def test_policy_band_layout_and_limits():
    pol = load_policy()
    assert v(pol["crossover"]["frequency_hz"]) == 1000.0
    bands = {b["id"]: b for b in pol["bands"]}
    assert bands["low"]["policy"] == "untouched" and bands["low"]["total_max_db"] == 0.0
    assert bands["presence"]["range_hz"] == [1000.0, 5000.0]
    assert bands["sibilance"]["range_hz"] == [5000.0, 8000.0]
    sh = bands["shimmer"]
    assert sh["range_hz"] == [10000.0, 14000.0]
    assert 3.0 <= sh["per_pass_max_db"] <= 6.0
    assert int(v(pol["passes"]["run"])) >= 2
    assert bands["air"]["min_reduction_db"] > 0.0
    assert bands["above_ceiling"]["range_hz"][0] == "ceiling"
    assert v(pol["s07"]["residual_limit_dbfs"]) == -80.0
    assert v(pol["s08"]["shimmer_index_tol_db"]) > 0 and v(pol["s08"]["noise_floor_tol_db"]) > 0
    assert v(pol["completion"]["auto_enable_on_ceiling"]) is False
    # every calibratable scalar carries a confidence label
    for section in ("s07", "s08", "p21", "diagnosis", "clicks", "ceiling", "oversuppression"):
        for key, node in pol[section].items():
            assert isinstance(node, dict) and "confidence" in node, (section, key)


# --- S-07 ---------------------------------------------------------------------------

def test_s07_low_band_untouched(clean):
    x = synth.add_head_click(synth.add_shimmer(clean, SR, depth_db=-24.0, seed=3), SR)
    plan = plan_cleanup(x, SR)
    assert plan["steps"]["spectral_reduction"]["action"] == "run"
    assert plan["steps"]["click_repair"]["action"] == "run"
    res = run_cleanup(x, SR, plan)
    resid = null_test_residual_dbfs(x, res.audio, SR, 1000.0)
    assert resid <= -80.0
    assert res.report["s07"]["pass"] is True
    assert res.report["s07"]["residual_dbfs"] <= -80.0
    # something above the crossover really changed
    assert np.max(np.abs(res.delta)) > 1e-3


def test_s07_fir_cross_check_interior(clean):
    # independent FIR low-pass measurement (no edge events in this signal)
    x = synth.add_shimmer(clean, SR, depth_db=-24.0, seed=4)
    res = run_cleanup(x, SR)
    assert null_test_residual_dbfs(x, res.audio, SR, 1000.0, method="fir") <= -80.0


# --- skip when clean ----------------------------------------------------------------

def test_clean_signal_skips_everything(clean):
    d = diagnose(clean, SR)
    assert d["skip_all"] is True
    assert all(a == "skip" for a in d["steps"].values())
    assert d["reasons"]["overall"]
    plan = plan_cleanup(clean, SR)
    assert plan["skip_all"] is True and plan["reasons"]
    res = run_cleanup(clean, SR, plan)
    assert np.array_equal(res.audio, clean)
    assert not np.any(res.delta)
    assert res.report["skipped"] is True
    assert res.report["noise_baseline"]["kind"] == "cleanup_noise_baseline"


def test_clean_mono_skips_and_keeps_shape(clean):
    mono = clean.mean(axis=1)
    res = run_cleanup(mono, SR)
    assert res.audio.shape == mono.shape
    assert np.array_equal(res.audio, mono)


# --- proposal shape and D-041 --------------------------------------------------------

def test_plan_is_a_proposal_with_alternatives(clean):
    x = synth.add_shimmer(clean, SR, depth_db=-24.0, seed=5)
    plan = plan_cleanup(x, SR, overrides={"spectral_reduction": "light"})
    st = plan["steps"]["spectral_reduction"]
    assert st["action"] == "light" and st["proposed"] == "run" and st["overridden"] is True
    assert st["params"]["strength"] < 1.0
    assert st["reasons"] and st["alternatives"]
    assert {a["action"] for a in st["alternatives"]} == {"run", "skip"}
    assert plan["ops"] == ["approve", "reject"]


def test_neural_completion_is_refused():
    x = np.zeros((1000, 2))
    with pytest.raises(ValidationError):
        neural_completion(x, SR)
    with pytest.raises(ValidationError):
        neural_completion(x, SR, enabled=True)
    with pytest.raises(Exception) as exc:
        neural_completion(x, SR, enabled=True, model="some-model")
    assert "not available" in str(exc.value)


def test_neural_method_in_plan_is_refused(clean):
    x = synth.add_hf_ceiling(clean, SR, 16000.0)
    plan = plan_cleanup(x, SR, overrides={"completion": {"action": "run", "method": "neural"}})
    with pytest.raises(ValidationError):
        run_cleanup(x, SR, plan)
