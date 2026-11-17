"""W0 acceptance and independent calibration of the BB-01 test harness."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import processors as P
from tests import toolimpl_harness as H


@pytest.fixture(scope="module")
def compressor_static():
    p = P.validate_params("compressor", {})
    # Include both knee boundaries and interior points, with steady RMS input.
    levels = p["threshold_db"] + np.array([-12, -6, -3, -2, -1, 0, 1, 2, 3, 6, 12])
    rows = H.static_characteristic("compressor", levels, params=p, sr=16000,
                                   settle_s=0.25, measure_s=0.05)
    return p, rows


def theoretical_compressor_output(level, p):
    """Independent scalar piecewise soft-knee equation, not a DSP helper call."""
    threshold, ratio, knee = p["threshold_db"], p["ratio"], p["knee_db"]
    over = level - threshold
    if over <= -knee / 2:
        return level + p["makeup_db"]
    if over >= knee / 2:
        return threshold + over / ratio + p["makeup_db"]
    return level + (1 / ratio - 1) * (over + knee / 2) ** 2 / (2 * knee) + p["makeup_db"]


def test_compressor_static_curve_including_knee(compressor_static):
    p, rows = compressor_static
    errors = [abs(row["output_dbfs"] - theoretical_compressor_output(row["input_dbfs"], p)) for row in rows]
    assert max(errors) <= 0.5, (rows, errors)
    inside = [row for row in rows if abs(row["input_dbfs"] - p["threshold_db"]) < p["knee_db"] / 2]
    assert len(inside) == 5


@pytest.mark.parametrize("method", ["63", "10-90"])
@pytest.mark.parametrize("sr", [8000, 16000])
def test_compressor_declared_db_ballistics(sr, method):
    # Peak detector isolates the declared dB one-pole from the RMS input window.
    p = P.validate_params("compressor", {"detector": "peak"})
    measured = H.dynamics_times(params=p, sr=sr, method=method)
    assert measured["attack"]["tau_s"] == pytest.approx(p["attack_ms"] / 1000, rel=0.10)
    assert measured["release"]["tau_s"] == pytest.approx(p["release_ms"] / 1000, rel=0.10)


@pytest.fixture(scope="module")
def reverb_ir():
    sr, declared = 16000, 0.6
    x = H.impulse(sr=sr, seconds=1.5, channels=2)
    result = H.render("reverb", x, sr, {"rt60_s": declared, "mix": 1.0, "predelay_ms": 10.0})
    return sr, declared, result


def test_existing_reverb_octave_rt60_accuracy(reverb_ir):
    sr, declared, result = reverb_ir
    for ch in range(2):
        for method in ("T20", "T30"):
            measured = H.rt60(result.audio[:, ch], sr, method=method, band_hz=1000)
            # Existing rt60_s is the FDN's middle-band design target, not a
            # guarantee for broadband decay shaped by shelves and wet filters.
            # Existing test_dsp_space uses +/-25% for the 1 kHz T20 estimate.
            assert measured == pytest.approx(declared, rel=0.25), (ch, method, measured)
    bands = H.octave_rt60(result.audio, sr, centers_hz=(250, 1000, 4000))
    assert bands[1000] == pytest.approx(declared, rel=0.25)
    assert H.edt(result.audio, sr, band_hz=1000) > 0
    assert H.decay_fit(result.audio, sr, band_hz=1000)["r_squared"] > 0.98
    assert abs(H.late_correlation(result.audio, sr, start_s=0.1)) < 0.3
    assert np.isfinite(H.ringing_spectrum(result.audio, sr, hi_hz=4000)["max_adjacent_db"])


def test_gain_passes_all_common_tests_and_exact_null():
    results = H.assert_common_tests("gain", neutral={"gain_db": 0}, params={"gain_db": -6})
    assert list(results) == [f"CT-{i}" for i in range(1, 9)]
    assert all(result["passed"] for result in results.values())
    assert results["CT-2"]["mode"] == "full_repeat_and_context_replay_excerpt"
    assert len(results["CT-7"]["measurements"]) == 3 * 2 * 3
    x = H.white_noise(sr=8000, seconds=0.1, seed=12)
    measured = H.null(x, x.copy())
    assert measured == {"rms": 0, "peak": 0, "rms_dbfs": -math.inf,
                        "peak_dbfs": -math.inf, "bit_identical": True}


def test_common_failures_include_measured_values():
    with pytest.raises(AssertionError, match=r"CT-4.*rms_dbfs"):
        H.assert_common_tests("gain", neutral={"gain_db": 1}, stages=("bus",), srs=(8000,))
    failed = H.run_common_tests("gain", stages=("bus",), srs=(8000,),
                                sr_probe=lambda *args: {"passed": False, "measured_ms": 99})
    assert not failed["CT-7"]["passed"]
    assert failed["CT-7"]["measurements"][0]["measured_ms"] == 99
    unsupported = H.run_common_tests("compressor", stages=("bus",), srs=(8000,))
    assert unsupported["CT-2"]["passed"]
    assert not unsupported["CT-7"]["passed"]
    assert "sr_probe required" in unsupported["CT-7"]["measurements"][0]["reason"]


def test_common_feedback_tail_and_array_length_validation():
    wet = H.run_common_tests("delay", params={"time_ms": 10, "feedback": 0.5, "mix": 1},
                            feedback=True, stages=("bus",), srs=(8000,))
    assert wet["CT-8"]["passed"]
    assert wet["CT-8"]["measurements"][0]["tail_peak_dbfs"] < -120
    slow = H.run_common_tests("delay", params={"time_ms": 1000, "feedback": 0.95, "mix": 1},
                             feedback=True, stages=("bus",), srs=(8000,), latency_params={"mix": 0})
    assert slow["CT-5"]["passed"]
    assert not slow["CT-8"]["passed"]
    assert slow["CT-8"]["measurements"][0]["tail_peak_dbfs"] > -120
    arrays = H.run_common_tests("stereo", stages=("bus",), srs=(44100,),
                                invalid_params=[{"widths": [1.0, 1.0]}])
    assert arrays["CT-6"]["passed"], arrays["CT-6"]
    assert arrays["CT-6"]["measurements"]["widths:band_count"]["exception"] == "ParamError"


def test_common_nonzero_latency_requires_raw_measurement():
    def raw_probe(x, sr, params, *, stage, seed):
        y = H.render("gain", x, sr, params, stage=stage, seed=seed).audio
        return np.pad(y, ((3, 0), (0, 0)))[:len(x)]

    kwargs = {"stages": ("bus",), "srs": (8000,), "declared_latency": 3}
    missing = H.run_common_tests("gain", **kwargs)
    assert not missing["CT-5"]["passed"]
    measured = H.run_common_tests("gain", latency_probe=raw_probe, **kwargs)
    assert measured["CT-5"]["passed"]
    row = measured["CT-5"]["measurements"][0]
    assert row["raw_measured_samples"] == 3 and row["offline_samples"] == 0
    wrong = H.run_common_tests("gain", latency_probe=raw_probe, offline_latency=1, **kwargs)
    assert not wrong["CT-5"]["passed"]


def test_common_block_adapter_runs_64_1024_and_full():
    calls = []

    def gain_blocks(x, sr, params, *, block_size, stage, seed):
        # Gain has no state to retain; this adapter can safely call the public
        # engine on successive chunks. Stateful effects require a state API.
        calls.append(block_size)
        return np.concatenate([H.render("gain", x[i:i + block_size], sr, params, stage=stage, seed=seed).audio
                               for i in range(0, len(x), block_size)])

    result = H.run_common_tests("gain", block_renderer=gain_blocks, stages="bus", srs=(8000,))
    assert result["CT-2"]["passed"] and result["CT-2"]["mode"] == "stateful_blocks"
    assert calls == [64, 1024, 2000]


@pytest.mark.parametrize("generator", [H.white_noise, H.pink_noise, H.drum, H.kick_train])
def test_seeded_synthesis_is_bit_deterministic(generator):
    kwargs = {"sr": 16000, "seconds": 0.15, "channels": 2}
    a, b, c = [generator(seed=s, **kwargs) for s in (11, 11, 12)]
    assert a.dtype == np.float64 and a.shape == (2400, 2)
    assert a.tobytes() == b.tobytes()
    assert a.tobytes() != c.tobytes()


@pytest.mark.parametrize("kind", ["kick", "snare", "hat"])
def test_drum_kinds_and_levels(kind):
    x = H.drum(kind, sr=16000, seconds=0.4, channels=2, seed=14)
    assert H.peak_dbfs(x) == pytest.approx(-6, abs=1e-12)
    drop = H.rms_dbfs(x[-1600:]) - H.rms_dbfs(x[:1600])
    if kind == "kick":
        # Equal 100 ms windows 300 ms apart on a 120 ms exponential envelope.
        assert drop == pytest.approx(-20 * 0.3 / (0.12 * math.log(10)), abs=1)
    else:
        assert drop < -25


def test_basic_signals_envelopes_steps_and_bpm():
    sr = 16000
    x = H.sine(1000, -12, sr=sr, seconds=0.1, channels=2)
    assert H.peak_dbfs(x) == pytest.approx(-12)
    assert H.rms_dbfs(x) == pytest.approx(-12 - 10 * math.log10(2))
    assert np.count_nonzero(H.impulse(sr=sr, seconds=0.1, channels=2)) == 2
    for make in (H.sine, H.impulse, H.tone_burst):
        assert np.array_equal(make(sr=sr, seconds=0.1, seed=3), make(sr=sr, seconds=0.1, seed=3))
    sweep = H.sweep(100, 3000, sr=sr, seconds=0.5)
    assert H.fundamental_frequency(sweep[:800], sr, low_hz=80, high_hz=300) < 160
    assert H.fundamental_frequency(sweep[-800:], sr, low_hz=2000, high_hz=3200) > 2400
    burst = H.tone_burst(sr=sr, seconds=0.4, rise_ms=10, decay_ms=100)
    env = H.rms_envelope(burst, sr, window_ms=2)
    assert env[160, 0] > env[40, 0]
    assert env[1600, 0] > env[4800, 0]
    steps = H.level_steps([-30, -10], [0.1, 0.2], sr=sr)
    assert H.rms_dbfs(steps[:1600]) == pytest.approx(-30)
    assert H.rms_dbfs(steps[1600:]) == pytest.approx(-10)
    train = H.kick_train(240, sr=sr, seconds=0.8, seed=4)
    assert all(H.peak_dbfs(train[start:start + 400]) > -10 for start in (0, 4000, 8000, 12000))


def _vowel_pitch(x, sr, expected):
    # Waveform autocorrelation, independent of the pulse-generation algorithm.
    part = x[sr // 4:3 * sr // 4, 0]
    corr = signal.correlate(part, part, mode="full", method="fft")[len(part) - 1:]
    a, b = round(sr / (expected * 1.1)), round(sr / (expected * 0.9))
    k = a + int(np.argmax(corr[a:b]))
    left, mid, right = corr[k - 1:k + 2]
    delta = 0.5 * (left - right) / (left - 2 * mid + right)
    return sr / (k + delta)


def test_vowel_f0_and_formants_within_one_percent():
    sr, f0 = 16000, 100.0
    formants = (700, 1200, 2500)
    v = H.vowel(f0, formants, sr=sr, seconds=1.0, channels=2)
    assert v.tobytes() == H.vowel(f0, formants, sr=sr, seconds=1.0, channels=2).tobytes()
    assert _vowel_pitch(v, sr, f0) == pytest.approx(f0, rel=0.01)
    # Observe peaks on the actual sustained vowel, not metadata or filter coeffs.
    tail = v[sr // 4:, 0]
    spectrum = np.abs(np.fft.rfft(tail * np.hanning(len(tail))))
    f = np.fft.rfftfreq(len(tail), 1 / sr)
    for target in formants:
        indices = np.flatnonzero((f > target - 150) & (f < target + 150))
        observed = f[indices[np.argmax(spectrum[indices])]]
        assert observed == pytest.approx(target, rel=0.01)
    # Broadband excitation checks off-harmonic formants without an F0 grid.
    targets = (643, 1271, 2467, 3403, 4201)
    response = signal.sosfilt(H.formant_sos(targets, 40, sr=sr), H.impulse(sr=sr)[:, 0])
    spectrum = np.abs(np.fft.rfft(response, n=4 * sr))
    frequencies = np.fft.rfftfreq(4 * sr, 1 / sr)
    for target in targets:
        indices = np.flatnonzero(abs(frequencies - target) < 30)
        assert frequencies[indices[np.argmax(spectrum[indices])]] == pytest.approx(target, rel=0.01)


def test_vowel_f0_curves_callable_samples_and_points():
    sr = 16000
    t = np.arange(sr) / sr
    curve = np.where(t < 0.5, 100.0, 160.0)
    a = H.vowel(curve, sr=sr)
    b = H.vowel(lambda times: np.where(times < 0.5, 100.0, 160.0), sr=sr)
    assert a.tobytes() == b.tobytes()
    for segment, expected in ((a[:sr // 2], 100), (a[sr // 2:], 160)):
        assert _vowel_pitch(np.tile(segment, (2, 1)), sr, expected) == pytest.approx(expected, rel=0.01)
    points = H.vowel([(0, 100), (0.4, 100), (0.6, 160), (1, 160)], sr=sr)
    assert points.shape == a.shape and np.isfinite(points).all()


def test_delay_compensated_null_and_polarity():
    sr = 8000
    x = H.white_noise(sr=sr, seconds=0.1, channels=2, seed=6)
    y = np.pad(x, ((37, 0), (0, 0)))
    result = H.compensated_null(x, y)
    assert result["latency_samples"] == 37 and result["overlap_frames"] == len(x)
    assert result["rms_dbfs"] == -math.inf
    assert H.compensated_null(y, x)["latency_samples"] == -37
    inverted = H.compensated_null(x, -y)
    assert inverted["latency_samples"] == 37 and inverted["rms"] == pytest.approx(2 * H.rms(x))
    pulse = H.impulse(at_s=0.01, sr=sr, seconds=0.1)
    assert H.latency(pulse) == 80
    with pytest.raises(ValueError, match="silence"):
        H.latency(np.zeros(100))


def test_harmonic_and_smpte_calibration():
    sr, seconds = 16000, 0.2
    t = np.arange(round(sr * seconds)) / sr
    x = np.sin(2 * np.pi * 1000 * t) + 0.01 * np.cos(2 * np.pi * 2000 * t) + 0.02 * np.sin(2 * np.pi * 3000 * t)
    measured = H.thd(x, sr, 1000, max_order=5)
    assert measured["thd_ratio"] == pytest.approx(math.sqrt(0.01 ** 2 + 0.02 ** 2), abs=1e-12)
    assert measured["thdn_ratio"] == pytest.approx(measured["thd_ratio"], abs=1e-12)
    noisy = x + H.white_noise(-40, sr=sr, seconds=seconds, seed=5)[:, 0]
    assert H.thd(noisy, sr, 1000, max_order=5)["thdn_ratio"] > measured["thdn_ratio"]
    clean = H.two_tone(sr=sr, seconds=seconds)
    assert H.imd_smpte(clean, sr)["imd_db"] < -200
    # AM modulation depth m generates sidebands m/2 each, IMD = m/sqrt(2).
    am = 0.4 * np.sin(2 * np.pi * 60 * t) + 0.1 * (1 + 0.1 * np.cos(2 * np.pi * 60 * t)) * np.sin(2 * np.pi * 7000 * t)
    assert H.imd_smpte(am, sr)["imd_ratio"] == pytest.approx(0.1 / math.sqrt(2), abs=1e-12)


def test_band_level_parseval_and_causal_rms():
    sr = 8000
    x = H.sine(1000, -12, sr=sr, seconds=0.1)
    assert H.band_level(x, sr, 900, 1100)["dbfs"] == pytest.approx(H.rms_dbfs(x), abs=1e-12)
    assert H.band_level(x, sr, 0, sr / 2)["rms"] == pytest.approx(H.rms(x), abs=1e-12)
    nyquist = H.level_steps([0], 0.1, sr=sr)
    assert H.band_level(nyquist, sr, 0, sr / 2)["rms"] == pytest.approx(1)
    constant = np.ones((800, 2))
    env = H.rms_envelope(constant, sr, window_ms=10)
    assert env[0, 0] == pytest.approx(1 / math.sqrt(80))
    assert np.all(env[79:] == pytest.approx(1))


def test_exponential_edc_t20_t30_edt_and_undefined_silence():
    sr, expected = 8000, 0.6
    t = np.arange(2 * sr) / sr
    ir = np.exp(-3 * math.log(10) * t / expected)
    for method in ("T20", "T30", "EDT"):
        assert H.rt60(ir, sr, method=method) == pytest.approx(expected, rel=1e-5)
    curve = H.edc(ir)
    assert curve[0] == 0 and np.all(np.diff(curve) <= 0)
    assert H.rt60(np.zeros(1000), sr) is None
    assert np.isneginf(H.edc(np.zeros(1000))).all()
    assert H.late_correlation(np.zeros((1000, 2)), sr) is None
    assert H.late_correlation(ir, sr) is None


def test_echo_density_correlation_and_ringing_calibration():
    sr = 16000
    gaussian = H.white_noise(sr=sr, seconds=1, seed=17, channels=2)
    dense = H.echo_density(gaussian, sr)
    assert np.mean(dense["density"]) == pytest.approx(1, abs=0.03)
    sparse = H.echo_density(H.impulse(sr=sr, seconds=1), sr)
    assert np.max(sparse["density"]) < 0.02
    assert not H.echo_density(np.zeros(16000), sr)["density"].any()
    assert H.late_correlation(np.repeat(gaussian[:, :1], 2, axis=1), sr) == pytest.approx(1)
    assert H.late_correlation(np.column_stack([gaussian[:, 0], -gaussian[:, 0]]), sr) == pytest.approx(-1)
    flat = H.ringing_spectrum(gaussian, sr, start_s=0, hi_hz=4000)
    assert flat["max_adjacent_db"] < 6
    ringing = gaussian + H.sine(1000, 0, sr=sr, seconds=1, channels=2)
    assert H.ringing_spectrum(ringing, sr, start_s=0, hi_hz=4000)["max_adjacent_db"] > 6
