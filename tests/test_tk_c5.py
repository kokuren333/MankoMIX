"""C5 closure: calibrated grain windows and conservative feedback bounds."""
import numpy as np
import pytest

from mankomix.dsp import processors as P
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb.grains import (grain_feedback_bounds, plan_grains, grain_window, render_grains,
                                     render_calibrated_grains)
from tests.toolimpl_harness import null, peak_dbfs
from tests.test_tk_w2h import CLEAN, KINDS, enabled, render, tone


@pytest.mark.parametrize("kind", KINDS)
def test_legacy_renderer_keeps_original_normalization_and_feedback(kind):
    p = P.validate_params(kind, CLEAN)
    x = tone(seconds=.4)
    delay = 160 if kind == "granular_delay" else None
    old, stats = render_grains(x, 8000, p, delay_samples=delay)
    actual_delay = 160 if delay is not None else 5
    assert null(x[:-actual_delay] / np.sqrt(2), old[actual_delay:])["rms_dbfs"] < -120
    assert stats["normalization_gain"] == 1 / np.sqrt(2)
    calibrated, _ = render_calibrated_grains(x, 8000, p, delay_samples=delay)
    np.testing.assert_array_equal(calibrated, old * np.sqrt(2))


def test_sinc_peak_bound_over_entire_fraction_interval():
    # Certify the continuous interval, including the gaps between grid points.
    # |sinc'| <= pi/2 from its cosine integral, |Hann'| <= pi/8.
    # Eight raw coefficients therefore have total Lipschitz constant 5*pi.
    size = 32768
    frac = (np.arange(size) + .5) / size
    distance = frac[:, None] - np.arange(-3, 5)
    raw = np.sinc(distance) * (.5 + .5 * np.cos(np.pi * distance / 4))
    margin = 5 * np.pi / (2 * size) + 1e-10
    upper = np.sum(abs(raw), axis=1) + margin
    lower = np.sum(raw, axis=1) - margin
    assert np.min(lower) > 0
    certified = float(np.max(upper / lower))
    print("sinc8_continuous_peak_bound", certified)
    assert certified < 2


@pytest.mark.parametrize("kind", KINDS)
def test_feedback_boundary_rejection_and_time_pitch_level_relations(enabled, kind):
    base = {**CLEAN, "grain_ms": 500 if kind == "granular_delay" else 1000,
            "density_hz": 200 if kind == "granular_delay" else 400}
    if kind == "granular_delay":
        base["time_ms"] = 4000
    p = P.validate_params(kind, base)
    delay = 4000 if kind == "granular_delay" else None
    bound = grain_feedback_bounds(p, delay_ms=delay)
    limit = bound["feedback_max"]
    P.validate_params(kind, {**base, "feedback": limit})
    with pytest.raises(ParamError, match="CT-8"):
        P.validate_params(kind, {**base, "feedback": np.nextafter(limit, np.inf)})
    if kind == "granular_delay":
        note = {**base, "note": "1/1", "bpm": 60}
        assert P.validate_params(kind, {**note, "feedback": limit})["feedback"] == limit
        with pytest.raises(ParamError, match="CT-8"):
            P.validate_params(kind, {**note, "feedback": np.nextafter(limit, np.inf)})
    else:
        varied = P.validate_params(kind, {**base, "level_spread_db": 24, "pan_spread": 1})
        assert grain_feedback_bounds(varied)["feedback_max"] < limit / 10


@pytest.mark.parametrize("kind,settings,sr", [
    ("granular_delay", dict(time_ms=4000), 1000),
    ("granular_delay", dict(time_ms=4000, grain_ms=500, density_hz=200, jitter=1,
                            spray_ms=1000, pitch_semitones=24, pitch_spread=12,
                            reverse=1, pan_spread=1), 4),
    ("granular", dict(buffer_s=20, speed=0, grain_ms=1000, density_hz=4), 100),
    ("granular", dict(buffer_s=20, speed=-4, grain_ms=1000, density_hz=400, jitter=1,
                      spray_ms=2000, pitch_semitones=24, pitch_spread=24, reverse=1,
                      pan_spread=1, level_spread_db=24, window="exp_decay"), 4),
    ("granular_delay", dict(time_ms=4000, lowcut_hz=1, highcut_hz=100), 1000),
])
def test_ct8_extreme_combination_at_permitted_boundary(enabled, kind, settings, sr):
    base = {**CLEAN, **settings}
    p = P.validate_params(kind, base)
    delay = p["time_ms"] if kind == "granular_delay" else None
    bound = grain_feedback_bounds(p, delay_ms=delay, sr=sr)
    limit = min(bound["feedback_max"], grain_feedback_bounds(p, delay_ms=delay)["feedback_max"])
    assert limit > 0
    p["feedback"] = limit
    x = np.zeros((69 * sr, 2))
    x[:4 * sr] = np.where(np.random.Generator(np.random.PCG64(120)).random((4 * sr, 2)) < .5, -1., 1.)
    x[4 * sr:9 * sr] = 1
    y = render(kind, x, sr, **p).audio
    tail = peak_dbfs(y[-sr:])
    print("ct8_extreme", kind, settings, "sr", sr, "feedback", limit,
          "gain_bound", bound["loop_peak_gain_bound"], "age_s", bound["history_age_bound_s"],
          "tail_dbfs", tail, "peak_dbfs", peak_dbfs(y))
    assert np.isfinite(y).all() and tail < -120
    if settings == dict(time_ms=4000):
        assert np.any(y[-sr:])  # Exclude a silent gap between repetitions.
    if bound["feedback_max"] < grain_feedback_bounds(p, delay_ms=delay)["feedback_max"]:
        with pytest.raises(ParamError, match="CT-8"):
            render(kind, x[:sr], sr, **{**p, "feedback": np.nextafter(limit, np.inf)})


@pytest.mark.parametrize("kind,window", [("granular_delay", "hann")] +
                         [("granular", w) for w in ("hann", "tukey", "exp_decay", "exp_attack")])
def test_window_noise_rms_calibration(enabled, kind, window):
    x = np.random.Generator(np.random.PCG64(27)).normal(size=(40000, 2)) * .1
    p = dict(mix=1, feedback=0, pan_spread=0)
    if kind == "granular":
        p["window"] = window
    y = render(kind, x, **p).audio
    gain = float(10 * np.log10(np.mean(y[8000:] ** 2) / np.mean(x[8000:] ** 2)))
    print("window_noise_rms_db", kind, window, gain)
    assert abs(gain) <= 3


@pytest.mark.parametrize("kind", KINDS)
def test_default_full_scale_and_sixty_second_tail(enabled, kind):
    sr = 1000
    x = np.zeros((69 * sr, 2))
    x[:9 * sr] = 1
    y = render(kind, x, sr).audio
    tail = peak_dbfs(y[-sr:])
    print("default_ct8_tail_dbfs", kind, tail)
    assert np.isfinite(y).all() and tail < -120


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("jitter", [0, 1])
def test_continuous_bounds_cover_actual_fractional_grain_rows(kind, jitter):
    from mankomix.dspx.bb.delayline import _kernel
    from mankomix.dspx.bb.grains import grain_window_gain

    sr, frames = 1000, 1000
    p = P.validate_params(kind, dict(feedback=0, grain_ms=500, density_hz=200, jitter=jitter,
                                     pitch_semitones=24, pitch_spread=12, reverse=1,
                                     spray_ms=100, pan_spread=1))
    delay = 200 if kind == "granular_delay" else None
    bounds = grain_feedback_bounds(p, delay_ms=delay, sr=sr)
    plans = plan_grains(frames, sr, p, seed=932, delay_samples=delay)
    gain, _ = grain_window_gain(p)
    envelope = np.zeros((frames, 2))
    maximum_age = 0
    for g in plans:
        n = np.arange(g.start, g.stop)
        pos = g.source_center - g.rate * g.center + g.rate * n
        ix, weights = _kernel(pos, "sinc8")
        row = np.sum(abs(weights), axis=1)
        if kind == "granular":
            valid = pos >= n - p["buffer_s"] * sr
            row *= valid
        else:
            valid = np.ones(len(n), dtype=bool)
        if np.any(valid):
            maximum_age = max(maximum_age, np.max(n[valid] - np.min(ix[valid], axis=1)))
        window = grain_window((n - g.center) / (p["grain_ms"] * sr / 1000) + .5)
        angle = (g.pan + 1) * np.pi / 4
        pan = np.sqrt(2) * np.array([np.cos(angle), np.sin(angle)])
        envelope[n] += (window * row * gain / np.sqrt(100) * g.level)[:, None] * pan
    assert maximum_age / sr <= bounds["history_age_bound_s"]
    assert np.max(envelope) <= bounds["loop_peak_gain_bound"] * (1 + 1e-12)


def test_slow_filter_memory_is_included_in_runtime_rejection(enabled):
    # Very slow stable poles cannot satisfy a sixty-second decay merely by
    # treating the filter's frequency gain as unity.
    p = {**CLEAN, "time_ms": 20, "feedback": .01, "lowcut_hz": .0001}
    P.validate_params("granular_delay", p)
    with pytest.raises(ParamError, match="CT-8"):
        render("granular_delay", tone(seconds=.01), **p)


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
@pytest.mark.parametrize("channels", [1, 2])
def test_scrub_slope_null_at_required_rates(enabled, sr, channels):
    x = np.random.Generator(np.random.PCG64(45)).normal(size=(sr // 5, channels)) * .1
    delay = sr // 50
    p = {**CLEAN, "grain_ms": 20, "density_hz": 100, "mode": "scrub",
         "position": [[0, .02], [1, 1.02]]}
    y = render("granular", x, sr, **p).audio
    error = null(x[delay:], y[:-delay])["rms_dbfs"]
    print("scrub_required_sr_null_dbfs", sr, channels, error)
    assert error <= -60
