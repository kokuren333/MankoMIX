"""W2h grain acceptance and strict diagnostics for incompatible requirements."""
import numpy as np
import pytest

from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain, validate_chain
from mankomix.dsp.errors import ChainError, ParamError
from mankomix.dspx.bb.grains import event_random, grain_window, plan_grains, render_grains
from tests.toolimpl_harness import assert_common_tests, fundamental_frequency, null, peak_dbfs

KINDS = ("granular_delay", "granular")
CLEAN = dict(grain_ms=80, density_hz=25, spray_ms=0, jitter=0, pitch_semitones=0,
             pitch_spread=0, reverse=0, pan_spread=0, feedback=0, mix=1)


@pytest.fixture
def enabled(monkeypatch):
    # Exercise the reference through the real engine without publishing a type
    # whose specification is not met. monkeypatch restores the public flags.
    for kind in KINDS:
        monkeypatch.setitem(P.PROCESSORS[kind], "implemented", True)


def render(kind, x, sr=8000, *, project_seed=123, item_id="grain-a", stage="track", **params):
    return render_chain(x, sr, [{"type": kind, "id": item_id, "params": params}],
                        stage=stage, seed=project_seed)


def tone(sr=8000, seconds=2, frequency=200):
    return (.2 * np.sin(2 * np.pi * frequency * np.arange(round(sr * seconds)) / sr))[:, None]


@pytest.mark.parametrize("kind", KINDS)
def test_public_declaration_and_unavailable_status(kind):
    from mankomix.director.direction import TIME_VARYING
    spec = P.PROCESSORS[kind]
    assert spec["implemented"] is False
    assert spec["stages"] == ["track", "bus"]
    assert spec["master_slot"] is None
    assert spec["backends"] == ["reference"]
    assert spec["offline_only"] is (kind == "granular")
    assert spec["realtime"] == dict(block_ok=False, allocates=True, latency_samples=0)
    assert kind in TIME_VARYING
    with pytest.raises(ChainError) as error:
        render(kind, tone(seconds=.01))
    assert error.value.rule == "not_implemented"


def test_fixed_seven_draws_seek_and_parameter_independence():
    all_draws = event_random(923, 51, count=50)
    assert all_draws.tobytes() == np.concatenate([event_random(923, 51, k, 1) for k in range(50)]).tobytes()
    assert event_random(923, 52, count=50).tobytes() != all_draws.tobytes()
    p = P.validate_params("granular", CLEAN)
    first = plan_grains(16000, 8000, p, seed=66)
    varied = plan_grains(16000, 8000, {**p, "pitch_spread": 24, "reverse": 1, "level_spread_db": 24}, seed=66)
    assert [(g.center, g.pan) for g in first] == [(g.center, g.pan) for g in varied]
    assert all(g.rate < 0 for g in varied)
    with pytest.raises(ValueError):
        event_random(0, first=-1)


@pytest.mark.parametrize("window", ["hann", "tukey", "exp_decay", "exp_attack"])
def test_window_shapes(window):
    u = np.linspace(0, 1, 1001)
    w = grain_window(u, window)
    assert w.dtype == np.float64 and np.isfinite(w).all()
    assert w[0] == w[-1] == 0 and np.min(w) >= 0 and np.max(w) <= 1
    assert grain_window(np.array([-1, 2]), window).tolist() == [0, 0]
    if window == "exp_decay":
        assert w[100] > w[900]
    elif window == "exp_attack":
        assert w[100] < w[900]
    else:
        np.testing.assert_allclose(w, w[::-1], atol=2e-15)


@pytest.mark.parametrize("kind", KINDS)
def test_bypass_and_silence(enabled, kind):
    x = np.random.Generator(np.random.PCG64(17)).normal(size=(2048, 2)) * .1
    assert render(kind, x, mix=0).audio.tobytes() == x.tobytes()
    assert np.count_nonzero(render(kind, np.zeros_like(x)).audio) == 0


@pytest.mark.parametrize("kind", KINDS)
def test_engine_seed_project_item_parameter_and_context_excerpt(enabled, kind):
    x = tone(seconds=.6)
    base = render(kind, x).audio
    assert base.tobytes() == render(kind, x).audio.tobytes()
    for changes in ({"project_seed": 124}, {"item_id": "grain-b"}, {"seed": 1}):
        assert base.tobytes() != render(kind, x, **changes).audio.tobytes()
    # The engine's supported excerpt operation replays context from sample 0.
    again = render(kind, x).audio[803:]
    assert again.tobytes() == base[803:].tobytes()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("jitter", [0, 1])
def test_measured_grain_count(enabled, kind, jitter):
    r = render(kind, tone(seconds=1.37), density_hz=37, jitter=jitter)
    count = r.steps[0]["stats"]["grain_count"]
    print("grain_count", kind, jitter, count, "expected", 37 * 1.37)
    assert abs(count - 37 * 1.37) <= 1


@pytest.mark.parametrize("kind", KINDS)
def test_pitch_octave_measured(enabled, kind):
    p = {**CLEAN, "grain_ms": 200, "density_hz": 10, "pitch_semitones": 12}
    if kind == "granular_delay":
        p["time_ms"] = 400
    else:
        p.update(mode="scrub", position=[[0, .4], [2, 2.4]])
    y = render(kind, tone(frequency=200), **p).audio[8000:]
    f = fundamental_frequency(y, 8000, low_hz=390, high_hz=410)
    cents = 1200 * np.log2(f / 400)
    print("octave_cents", kind, cents)
    assert abs(cents) <= 10


@pytest.mark.parametrize("kind", KINDS)
def test_reverse_asymmetric_grain_envelope(enabled, kind):
    sr = 8000
    x = np.linspace(.05, .9, sr * 2)[:, None]
    p = {**CLEAN, "density_hz": 1, "reverse": 1}
    if kind == "granular_delay":
        p["time_ms"] = 300
    else:
        p.update(mode="scrub", position=[[0, .7]])
    y = render(kind, x, **p).audio
    samples = np.arange(sr - 250, sr + 250)
    w = .5 + .5 * np.cos(2 * np.pi * (samples - sr) / 640)
    recovered = y[samples, 0] / (w / np.sqrt(.08))
    source = 5600 - (samples - sr)
    np.testing.assert_allclose(recovered, x[source, 0], atol=5e-15)
    assert recovered[0] > recovered[-1]


@pytest.mark.parametrize("kind", KINDS)
def test_kernel_block_sizes_preserve_bits_with_feedback(kind):
    x = tone(seconds=.15)
    p = P.validate_params(kind, dict(grain_ms=20, density_hz=100, feedback=.4,
                                     spray_ms=0, jitter=0, pan_spread=0))
    delay = 80 if kind == "granular_delay" else None
    outputs = [render_grains(x, 8000, p, seed=25, delay_samples=delay, block_size=b)[0]
               for b in (1, 64, 1024, len(x))]
    assert all(y.tobytes() == outputs[0].tobytes() for y in outputs[1:])


def test_fractional_grains_filters_and_pan_block_bits():
    p = P.validate_params("granular_delay", dict(grain_ms=20, density_hz=100, feedback=.4,
                                                  spray_ms=2, jitter=.8, pitch_semitones=3,
                                                  reverse=.4, lowcut_hz=80, highcut_hz=2500))
    x = np.repeat(tone(seconds=.08), 2, axis=1)
    outputs = [render_grains(x, 8000, p, seed=25, delay_samples=500, block_size=b)[0]
               for b in (1, 64, 1024, len(x))]
    assert all(y.tobytes() == outputs[0].tobytes() for y in outputs[1:])


def test_delay_feedback_after_normalization_filter_and_duck(enabled):
    x = np.zeros((10000, 1))
    x[1600] = 1
    p = {**CLEAN, "time_ms": 250, "feedback": .6}
    plain = render("granular_delay", x, **p).audio
    g = 1 / np.sqrt(2)
    for repetition in range(1, 5):
        actual = plain[1600 + repetition * 2000, 0]
        assert actual == pytest.approx(g * (.6 * g) ** (repetition - 1), abs=1e-15)
    filtered = render("granular_delay", x, **{**p, "highcut_hz": 1000}).audio
    assert filtered[3600, 0] == plain[3600, 0]
    assert filtered[5600, 0] < plain[5600, 0]
    constant = np.full((16000, 1), .1)
    plain = render("granular_delay", constant, **CLEAN).audio
    ducked = render("granular_delay", constant, **{**CLEAN, "duck_db": 12, "duck_attack_ms": 5}).audio
    change = float(20 * np.log10(np.sqrt(np.mean(ducked[-4000:] ** 2)) / np.sqrt(np.mean(plain[-4000:] ** 2))))
    print("wet_duck_db", change)
    assert abs(change + 12) < .01


def test_causal_delay_under_reverse_pitch_spray_and_live_buffer_bounds():
    p = P.validate_params("granular_delay", dict(time_ms=.1, grain_ms=500, density_hz=200,
                                                   spray_ms=1000, reverse=1, pitch_semitones=24,
                                                   pitch_spread=12))
    grains = plan_grains(1600, 8000, p, seed=87, delay_samples=.8)
    for g in grains:
        for n in (g.start, g.stop - 1):
            pos = g.source_center - g.rate * g.center + g.rate * n
            assert np.floor(pos) + 4 < n
    p = P.validate_params("granular", dict(buffer_s=.1, speed=0, grain_ms=20,
                                           density_hz=100, spray_ms=0, jitter=0, pan_spread=0))
    x = np.zeros((2400, 1))
    x[100] = 1
    wet, _ = render_grains(x, 8000, p)
    assert np.max(abs(wet[:1200])) > 0
    assert np.count_nonzero(wet[1600:]) == 0


@pytest.mark.parametrize("scrub", [False, True])
def test_stationary_texture_centroid(enabled, scrub):
    p = {**CLEAN, "speed": 0}
    if scrub:
        p.update(mode="scrub", position=[[0, .5]])
    x = tone(seconds=2, frequency=125) + .5 * tone(seconds=2, frequency=400)
    y = render("granular", x, **p).audio[:, 0]
    centroids = []
    for start in (3200, 6400, 9600):
        segment = y[start:start + 3200]
        spectrum = np.abs(np.fft.rfft(segment * np.hanning(len(segment))))
        centroids.append(float(np.sum(np.fft.rfftfreq(len(segment), 1 / 8000) * spectrum) / np.sum(spectrum)))
    variation = np.ptp(centroids) / np.mean(centroids)
    print("centroid_variation", scrub, centroids, variation)
    assert variation <= .05


def test_quantized_pitches_and_three_spectral_lines(enabled):
    sr = 8000
    p = {**CLEAN, "mode": "scrub", "position": [[0, 2]], "grain_ms": 1000,
         "density_hz": 10, "pitch_quantize": [0, 7, 12]}
    resolved = P.validate_params("granular", p)
    plans = plan_grains(sr * 6, sr, resolved, seed=24)
    assert {g.pitch_semitones for g in plans} == {0, 7, 12}
    y = render("granular", tone(seconds=6), **p).audio[sr:, 0]
    mag = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freq = np.fft.rfftfreq(len(y), 1 / sr)
    peaks = []
    for target in 200 * 2.0 ** (np.array([0, 7, 12]) / 12):
        band = np.flatnonzero(abs(freq - target) < 3)
        measured = freq[band[np.argmax(mag[band])]]
        peaks.append(float(measured))
        assert abs(1200 * np.log2(measured / target)) < 10
        assert np.max(mag[band]) > np.max(mag) * .05
    print("quantized_frequency_hz", peaks)


def test_scrub_future_read_and_slope_geometry(enabled):
    p = {**CLEAN, "mode": "scrub", "position": [[0, .2], [2, 2.2]]}
    x = tone(seconds=2)
    y = render("granular", x, **p).audio
    expected = np.r_[x[1600:, 0], np.zeros(1600)][:, None] / np.sqrt(2)
    assert np.max(abs(y - expected)) < 1e-12
    assert np.max(abs(y[:1000])) > 0


@pytest.mark.parametrize("kind", KINDS)
def test_range_defaults_and_every_numeric_endpoint(enabled, kind):
    numeric = {
        "grain_ms": (5, 500 if kind == "granular_delay" else 1000, 80),
        "density_hz": (1, 200 if kind == "granular_delay" else 400, 25),
        "spray_ms": (0, 1000 if kind == "granular_delay" else 2000, 50),
        "jitter": (0, 1, .3), "pitch_semitones": (-24, 24, 0),
        "pitch_spread": (0, 12 if kind == "granular_delay" else 24, 0),
        "reverse": (0, 1, 0), "pan_spread": (0, 1, .5),
        "feedback": (0, .9, .2 if kind == "granular_delay" else 0),
        "mix": (0, 1, .2 if kind == "granular_delay" else .5), "seed": (0, 65535, 0),
    }
    if kind == "granular_delay":
        numeric.update(time_ms=(.1, 4000, 250), bpm=(0, 400, 0), lowcut_hz=(0, 2000, 0),
                       highcut_hz=(0, 24000, 0), duck_db=(0, 24, 0),
                       duck_threshold_db=(-80, 0, -40), duck_attack_ms=(.1, 200, 10),
                       duck_release_ms=(5, 3000, 250))
    else:
        numeric.update(buffer_s=(.1, 20, 4), speed=(-4, 4, 1), level_spread_db=(0, 24, 0))
    definitions = {s["id"]: s for s in P.PROCESSORS[kind]["params"]}
    defaults = P.validate_params(kind, {})
    x = tone(sr=48000, seconds=.003)
    for pid, (lo, hi, default) in numeric.items():
        spec = definitions[pid]
        assert (spec["min"], spec["max"], spec["default"]) == (lo, hi, default)
        assert defaults[pid] == default
        for edge in (lo, hi):
            assert np.isfinite(render(kind, x, 48000, **{pid: edge}).audio).all()
        for edge in (lo - 1, hi + 1):
            with pytest.raises(ParamError):
                P.validate_params(kind, {pid: edge})
    assert numeric.keys() == {s["id"] for s in definitions.values() if s["type"] in ("float", "int")}
    assert render(kind, x, 48000).audio.tobytes() == render(kind, x, 48000, **defaults).audio.tobytes()
    with pytest.raises(ParamError):
        P.validate_params(kind, {"unknown": 1})


def test_enum_array_curve_and_relationship_validation(enabled):
    for note in P.NOTE_VALUES:
        p = dict(note=note, bpm=400)
        assert np.isfinite(render("granular_delay", tone(seconds=.003), **p).audio).all()
    for window in ("hann", "tukey", "exp_decay", "exp_attack"):
        assert np.isfinite(render("granular", tone(seconds=.01), window=window).audio).all()
    assert P.validate_params("granular_delay", {})["note"] == "none"
    assert P.validate_params("granular", {})["mode"] == "live"
    assert P.validate_params("granular", {})["window"] == "hann"
    for kind, bad in [
        ("granular_delay", {"note": "1/4"}), ("granular_delay", {"bpm": 19}),
        ("granular_delay", {"note": "1/1d", "bpm": 20}),
        ("granular_delay", {"note": "bad"}), ("granular", {"window": "bad"}),
        ("granular", {"mode": "bad"}), ("granular", {"mode": "scrub"}),
        ("granular", {"mode": "scrub", "position": [[0, 0]], "feedback": .1}),
        ("granular", {"pitch_quantize": list(range(9))}),
        ("granular", {"pitch_quantize": [float("nan")]}),
        ("granular", {"position": [[0, 0]] * 1025}),
        ("granular", {"position": [[1, 0], [0, 0]]}),
        ("granular", {"position": [[0, -1]]}),
    ]:
        with pytest.raises(ParamError):
            P.validate_params(kind, bad)
    assert len(P.validate_params("granular", {"pitch_quantize": list(range(8))})["pitch_quantize"]) == 8
    curve = [[i / 1023, i / 1023] for i in range(1024)]
    assert np.isfinite(render("granular", tone(seconds=.01), mode="scrub", position=curve).audio).all()
    # Finite coordinates well outside the file are zero-extended safely.
    assert not np.any(render("granular", tone(seconds=.01), mode="scrub", position=[[0, 1e300]], mix=1).audio)
    for kind in KINDS:
        with pytest.raises(ParamError):
            validate_chain([{"type": kind, "channel": "side"}], "track")
        with pytest.raises(ChainError):
            validate_chain([{"type": kind}], "master")


@pytest.mark.parametrize("kind", KINDS)
def test_common_active_sample_rates_and_neutral(enabled, kind):
    p = dict(grain_ms=20, density_hz=100, spray_ms=0, jitter=0, pan_spread=0, feedback=0, mix=.4)
    if kind == "granular_delay":
        p["time_ms"] = 20

    def probe(x, y, sr, validated):
        delay = round(.020 * sr) if kind == "granular_delay" else 5
        a = round(.05 * sr)
        expected = .6 * x[a:] + .4 / np.sqrt(2) * x[a-delay:len(x)-delay]
        error = float(np.max(abs(y[a:] - expected)))
        f = fundamental_frequency(y[a:], sr, low_hz=990, high_hz=1010)
        return {"passed": error < 1e-12 and abs(f - 1000) < 1,
                "max_error": error, "frequency_hz": f, "musical_delay_samples": delay}

    assert_common_tests(kind, params=p, neutral={"mix": 0}, latency_params={"mix": 0},
                        stages=("track", "bus"), seconds=.16, sr_probe=probe)


@pytest.mark.parametrize("kind", KINDS)
def test_feedback_point_nine_tail_and_full_scale(enabled, kind):
    # Actual sixty-second CT-8, at a small rate to keep the file under 3 min.
    p = dict(grain_ms=20, density_hz=100, spray_ms=0, jitter=0, pan_spread=0, feedback=.9, mix=.3)
    if kind == "granular_delay":
        p["time_ms"] = 20

    # CT-7 has its own required-rate measurement above. Here test the tail
    # directly so this stress rate is never mistaken for that measurement.
    sr = 1000
    x = np.zeros((sr * 61, 2))
    x[:1000] = np.where(np.random.Generator(np.random.PCG64(2)).random((1000, 2)) < .5, -1, 1)
    y = render(kind, x, sr, **p).audio
    tail = peak_dbfs(y[-sr:])
    print("feedback_0.9_tail_dbfs", kind, tail, "peak", peak_dbfs(y))
    assert np.isfinite(y).all() and tail < -120


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.xfail(strict=True, reason="Unit-peak Hann COLA=1, but specified normalization divides it by sqrt(2).")
def test_spec_coherent_overlap_null_unmet(enabled, kind):
    x = tone()
    p = dict(CLEAN)
    if kind == "granular_delay":
        p["time_ms"] = 250
        delay = 2000
    else:
        delay = 5
    y = render(kind, x, **p).audio
    measured = null(x[:-delay], y[delay:])
    assert null(x[:-delay], y[delay:] * np.sqrt(2))["rms_dbfs"] <= -120
    print("coherent_null_dbfs", kind, measured["rms_dbfs"], "gain_db", -10 * np.log10(2))
    assert measured["rms_dbfs"] <= -60


@pytest.mark.xfail(strict=True, reason="Scrub slope one inherits the incompatible Hann normalization.")
def test_spec_scrub_slope_null_unmet(enabled):
    x = tone()
    y = render("granular", x, **{**CLEAN, "mode": "scrub", "position": [[0, .25], [2, 2.25]]}).audio
    measured = null(x[2000:], y[:-2000])
    print("scrub_slope_null_dbfs", measured["rms_dbfs"])
    assert measured["rms_dbfs"] <= -60


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.xfail(strict=True, reason="Hann mean square is 3/8: 1/sqrt(overlap) does not preserve random-grain RMS.")
def test_spec_noise_rms_unmet(enabled, kind):
    x = np.random.Generator(np.random.PCG64(27)).normal(size=(8000 * 5, 1)) * .1
    y = render(kind, x, mix=1, feedback=0, pan_spread=0).audio
    gain = float(20 * np.log10(np.sqrt(np.mean(y[8000:] ** 2)) / np.sqrt(np.mean(x[8000:] ** 2))))
    print("random_noise_gain_db", kind, gain)
    assert abs(gain) <= 3


@pytest.mark.xfail(strict=True, reason="Four-second delay and feedback .9 cannot meet the universal 60 s / -120 dB tail.")
def test_spec_long_delay_tail_unmet(enabled):
    sr = 1000
    x = np.zeros((sr * 61, 1))
    x[:sr] = 1
    y = render("granular_delay", x, sr, **{**CLEAN, "time_ms": 4000, "feedback": .9}).audio
    tail = peak_dbfs(y[-sr:])
    print("long_delay_tail_dbfs", tail)
    assert tail < -120


@pytest.mark.parametrize("kind,overlap", [("granular_delay", 100), ("granular", 400)])
def test_unstable_legal_coherent_loop_is_not_certified(kind, overlap):
    # Independent lower-bound derivation for the centered Hann interior.
    # Grain gains add coherently to overlap/2; feedback is .9 after /sqrt(N).
    loop_gain = .9 * np.sqrt(overlap) / 2
    assert loop_gain > 1
    print("legal_coherent_loop_gain", kind, loop_gain)
    assert not P.PROCESSORS[kind]["implemented"]


@pytest.mark.parametrize("kind", KINDS)
def test_dense_feedback_measured_growth(enabled, kind):
    sr = 1000
    frames = 2000 if kind == "granular_delay" else 200
    x = np.zeros((frames, 1))
    x[:10] = 1
    p = {**CLEAN, "grain_ms": 500 if kind == "granular_delay" else 1000,
         "density_hz": 200 if kind == "granular_delay" else 400, "feedback": .9}
    if kind == "granular_delay":
        p["time_ms"] = 50
    y = render(kind, x, sr, **p).audio
    early = peak_dbfs(y[:frames // 4])
    late = peak_dbfs(y[-frames // 4:])
    print("dense_feedback_growth_db", kind, early, late, late - early)
    assert np.isfinite(y).all() and late - early > 120
