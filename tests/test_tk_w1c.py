"""W1c acceptance tests, including explicit diagnostics for unmet specifications."""
import time

import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain, validate_chain
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb.delayline import (
    DelayLine, LoopFilter, feedback_limit, fractional_delay, integer_feedback, read_samples,
)
from mankomix.dspx.procs.haas import haas, latency_samples
from mankomix.dspx.procs.ms_gain import ms_gain
from mankomix.dspx.procs.time_align import time_align
from tests.toolimpl_harness import assert_common_tests

KINDS = ("pingpong_delay", "slapback", "multitap_delay", "haas", "ms_gain", "time_align")


def render(kind, x, sr=8000, **params):
    return render_chain(x, sr, [{"type": kind, "params": params}], stage="track", seed=123)


def endpoint_params(kind, pid, edge):
    p = {pid: edge}
    # The scalar feedback maximum remains legal with a sufficiently short line.
    if pid == "feedback" and edge == .95:
        if kind == "pingpong_delay":
            p["time_ms"] = 20
        elif kind == "multitap_delay":
            p.update(tap_ms=[20], tap_db=[0])
    return p


def pulse(n=8000, channels=1, at=0):
    x = np.zeros((n, channels))
    x[at] = 1
    return x


@pytest.mark.parametrize("method", ["integer", "lagrange3", "sinc8"])
def test_bb_integer_reads_and_zero_extension(method):
    x = np.random.Generator(np.random.PCG64(8)).normal(size=(97, 2))
    y = fractional_delay(x, 7, method)
    np.testing.assert_array_equal(y[:7], 0)
    assert y[7:].tobytes() == x[:-7].tobytes()
    np.testing.assert_array_equal(read_samples(x, np.array([-100., 1000.]), method), 0)


def test_lagrange_reproduces_cubic():
    t = np.arange(200.)
    x = (t ** 3 - 7 * t + 2)[:, None]
    pos = np.arange(5., 190.) + 0.37
    np.testing.assert_allclose(read_samples(x, pos, "lagrange3")[:, 0], pos ** 3 - 7 * pos + 2, atol=3e-9, rtol=1e-14)


@pytest.mark.parametrize("method,base", [("integer", 17), ("lagrange3", 7.3), ("sinc8", 9.4)])
def test_bb_streaming_modulation_and_loop_block_bits(method, base):
    rng = np.random.Generator(np.random.PCG64(20))
    x = rng.normal(size=(2117, 2)) * .1
    t = np.arange(len(x))
    d = np.full_like(x, base) if method == "integer" else np.column_stack((base + .3 * np.sin(t / 21), base + .2 * np.cos(t / 31)))
    outputs = []
    for block in (1, 64, 1024, len(x)):
        line = DelayLine(32, 2, method)
        filt = LoopFilter(8000, 2, 80, 2000)
        pieces = []
        for a in range(0, len(x), block):
            pieces.append(line.process(x[a:a+block], d[a:a+block], .6, filt,
                                       matrix=[[0, 1], [1, 0]], block_size=block))
        outputs.append(np.concatenate(pieces))
    assert all(y.tobytes() == outputs[0].tobytes() for y in outputs[1:])
    # Without feedback a second, offline read implementation gives the same result.
    line = DelayLine(32, 2, method)
    y = line.process(x, d)
    np.testing.assert_allclose(y, read_samples(x, t[:, None] - d, method), atol=0, rtol=0)


def test_bb_feedback_recurrence_and_filter_location():
    x = pulse(400)
    expected = np.zeros_like(x)
    for n in range(13, len(x)):
        expected[n] = x[n-13] + .7 * expected[n-13]
    np.testing.assert_array_equal(integer_feedback(x, 13, .7), expected)
    np.testing.assert_array_equal(DelayLine(13, 1, "integer").process(x, 13, .7), expected)
    filtered = DelayLine(13, 1, "integer").process(x, 13, .7, LoopFilter(8000, 1, 0, 1000))
    assert filtered[13, 0] == 1  # first repeat has not crossed the loop EQ
    assert not np.array_equal(filtered[26:39], expected[26:39])
    for kwargs in ({"delays": .5}, {"delays": 14}, {"delays": 2.5, "feedback": 2}):
        with pytest.raises(ValueError):
            DelayLine(13, 1).process(x, **kwargs)
    with pytest.raises(ValueError):
        DelayLine(13, 1).process(x, 2.5)


@pytest.mark.parametrize("start", ["left", "right"])
def test_pingpong_alternation_decay_width_seed_and_fold(start):
    x = pulse()
    params = dict(time_ms=20, feedback=.7, mix=1, start=start)
    result = render("pingpong_delay", x, **params)
    y = result.audio
    assert y.shape == (len(x), 2)
    for n in range(1, 12):
        side = (n - 1 + (start == "right")) % 2
        assert y[n * 160, side] == pytest.approx(.7 ** (n - 1), abs=1e-15)
        assert y[n * 160, 1-side] == 0
    locations = np.flatnonzero(np.sum(y, axis=1))
    np.testing.assert_array_equal(np.diff(locations), 160)
    assert result.audio.tobytes() == render("pingpong_delay", x, **params).audio.tobytes()
    centre = render("pingpong_delay", x, **dict(params, width=0)).audio
    assert centre[:, 0].tobytes() == centre[:, 1].tobytes()
    assert "mono" in result.steps[0]["stats"]
    assert "haas" in result.steps[0]["stats"]


def test_pingpong_ratio_and_stereo_crossfeed():
    x = pulse()
    y = render("pingpong_delay", x, time_ms=10, ratio=1.5, feedback=.5, mix=1).audio
    np.testing.assert_array_equal(np.flatnonzero(y[:, 0])[:3], [80, 280, 480])
    np.testing.assert_array_equal(np.flatnonzero(y[:, 1])[:3], [200, 400, 600])
    stereo = pulse(channels=2)
    stereo[0, 1] = 0
    y = render("pingpong_delay", stereo, time_ms=10, input="stereo", mix=1, feedback=.5).audio
    assert y[80, 0] == 1 and y[160, 1] == .5


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
def test_tempo_and_delay_intervals(sr):
    x = pulse(sr)
    y = render("pingpong_delay", x, sr, note="1/16", bpm=120, mix=1, feedback=.5).audio
    expected = round(sr * .125)
    assert np.argmax(y[:, 0]) == expected
    assert abs(expected - sr * .125) <= .5
    assert y[2*expected, 1] == .5


@pytest.mark.parametrize("params", [{"note": "1/4"}, {"bpm": 10}, {"note": "1/1d", "bpm": 20}])
def test_delay_tempo_invalid(params):
    with pytest.raises(ParamError):
        P.validate_params("pingpong_delay", params)
    with pytest.raises(ParamError):
        render("pingpong_delay", pulse(64), **params)


def test_slapback_composite_bytes_record_and_single_repeat():
    x = pulse()
    p = dict(time_ms=90, mix=1, tone_hz=0, lowcut_hz=0, route="both")
    composite = render("slapback", x, **p)
    manual = render("delay", x, time_ms=90, mix=1, highcut_hz=0, lowcut_hz=0, route="both", feedback=0, note="none")
    assert composite.audio.tobytes() == manual.audio.tobytes()
    assert np.flatnonzero(composite.audio[:, 0]).tolist() == [720]
    assert composite.steps[0]["type"] == "delay"
    assert composite.steps[0]["composite_of"]["type"] == "slapback"
    assert composite.steps[0]["id"].endswith(".1")


def test_multitap_levels_pan_recurrence_beats():
    x = pulse()
    p = dict(tap_ms=[10, 20, 30], tap_db=[-3, -6, -9], tap_pan=[-1, 0, 1], mix=1, feedback=.5)
    y = render("multitap_delay", x, **p).audio
    for index, (db, pan) in enumerate(zip(p["tap_db"], p["tap_pan"]), 1):
        expected = 10 ** (db/20) * np.array([np.cos((pan+1)*np.pi/4), np.sin((pan+1)*np.pi/4)])
        np.testing.assert_allclose(y[80*index], expected, atol=1e-15)
        np.testing.assert_allclose(y[80*index + 240], expected * .5, atol=1e-15)
    ms = render("multitap_delay", x, tap_ms=[10, 20], tap_db=[0, 0], mix=1).audio
    beats = render("multitap_delay", x, tap_ms=[.02, .04], tap_db=[0, 0], tap_unit="beats", bpm=120, mix=1).audio
    assert ms.tobytes() == beats.tobytes()


@pytest.mark.parametrize("p", [
    {"tap_ms": []}, {"tap_db": [0]}, {"tap_pan": [0]}, {"tap_ms": [20, 10, 30]},
    {"tap_ms": [10, 10, 30]}, {"tap_unit": "beats"},
    {"tap_unit": "beats", "bpm": 120, "tap_ms": [1, 2, 16]},
    {"tap_ms": [.01, .02, .03]},
])
def test_multitap_invalid(p):
    with pytest.raises(ParamError):
        P.validate_params("multitap_delay", p)
    with pytest.raises(ParamError):
        render("multitap_delay", pulse(64), **p)


@pytest.mark.parametrize("kind", ["pingpong_delay", "multitap_delay"])
def test_delays_dry_bytes_duck_and_feedback_decay(kind):
    rng = np.random.Generator(np.random.PCG64(31))
    x = rng.normal(size=(1000, 1))
    assert render(kind, x, mix=0).audio.tobytes() == x.tobytes()
    # Sixty seconds after stopping a full-scale input, at maximal feedback.
    sr = 8000
    full = np.r_[np.where(x > 0, 1., -1.), np.zeros((60*sr, 1))]
    p = dict(time_ms=20) if kind == "pingpong_delay" else dict(tap_ms=[10, 20], tap_db=[0, 0])
    y = render(kind, full, mix=1, feedback=.95, **p).audio
    assert np.isfinite(y).all() and np.max(np.abs(y[-sr:])) < 1e-6
    tone = np.sin(2*np.pi*500*np.arange(sr*2)/sr)[:, None] * .5
    clear = render(kind, tone, mix=1, feedback=0, **p).audio
    duck = render(kind, tone, mix=1, feedback=0, duck_db=12, **p).audio
    ratio = 20*np.log10(np.linalg.norm(duck[-sr//2:])/np.linalg.norm(clear[-sr//2:]))
    assert ratio == pytest.approx(-12, abs=.01)
    assert render(kind, tone, mix=1, duck_db=0, **p).audio.tobytes() == render(kind, tone, mix=1, **p).audio.tobytes()


def test_haas_impulse_symmetry_stats_and_notch():
    x = pulse(16000, 2, at=1000)
    p = dict(delay_ms=12.5, lo_keep_hz=0, delayed_db=-6, input="stereo")
    result = render("haas", x, **p)
    assert np.argmax(result.audio[:, 1]) == 1100
    assert result.audio[1100, 1] == pytest.approx(10 ** (-6/20), abs=1e-15)
    mirrored = render("haas", x[:, ::-1], **dict(p, side="left")).audio
    assert mirrored[:, ::-1].tobytes() == result.audio.tobytes()
    y = render("haas", x, delay_ms=12.5, lo_keep_hz=0).audio
    frequencies, response = signal.freqz(np.mean(y[1000:1201], axis=1), worN=65536, fs=8000)
    first = frequencies[np.argmin(np.abs(response[(frequencies > 20) & (frequencies < 60)])) + np.flatnonzero(frequencies > 20)[0]]
    assert first == pytest.approx(40, rel=.02)
    stats = result.steps[0]["stats"]
    m = np.mean(result.audio, axis=1)
    measured = 10*np.log10(np.sum(m*m)/(np.sum(result.audio*result.audio)/2))
    assert stats["mono"]["mono_loss_db"] == pytest.approx(measured, abs=.001)
    assert stats["haas"]["within_1_35_ms"] and stats["first_notch_hz"] == 40


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
def test_haas_low_protection_and_compensated_latency(sr):
    t = np.arange(sr)/sr
    x = (.5*np.sin(2*np.pi*60*t))[:, None]
    p = P.validate_params("haas", {})
    y, _, stats = haas(x, sr, p)
    steady = y[sr//3:2*sr//3]
    phase = np.angle(np.sum(steady[:, 1]*np.exp(-2j*np.pi*60*t[sr//3:2*sr//3])) / np.sum(steady[:, 0]*np.exp(-2j*np.pi*60*t[sr//3:2*sr//3])))
    assert abs(np.degrees(phase)) <= 1
    loss = 10*np.log10(np.mean(np.mean(steady, axis=1)**2) / np.mean(steady**2))
    assert abs(loss) <= .1
    impulse = pulse(sr//2, 2, at=sr//10)
    raw = haas(impulse, sr, p, compensate=False)[0]
    compensated = haas(impulse, sr, p)[0]
    assert np.argmax(np.abs(raw[:, 0])) - sr//10 == latency_samples(sr, p)
    assert np.argmax(np.abs(compensated[:, 0])) == sr//10
    assert stats["latency_samples"] == latency_samples(sr, p)


def test_ms_gain_measured_behavior_and_unmet_exact_roundtrip():
    sr = 8000
    x = np.random.Generator(np.random.PCG64(50)).normal(size=(8000, 2)) * .1
    p = P.validate_params("ms_gain", {})
    assert ms_gain(x, sr, p)[0].tobytes() == x.tobytes()
    side_mute = ms_gain(x, sr, dict(p, side_mute=True))[0]
    assert side_mute[:, 0].tobytes() == side_mute[:, 1].tobytes()
    mid_mute = ms_gain(x, sr, dict(p, mid_mute=True))[0]
    np.testing.assert_array_equal(mid_mute[:, 0], -mid_mute[:, 1])
    from mankomix.dsp.reference.stereo import stereo
    expected = stereo(x, sr, P.validate_params("stereo", {"width": 10**(-6/20)}))[0]
    measured = ms_gain(x, sr, dict(p, side_db=-6))[0]
    assert np.max(np.abs(expected-measured)) < 1e-12
    encoded = ms_gain(x, sr, dict(p, mode="encode"))[0]
    decoded = ms_gain(encoded, sr, dict(p, mode="decode"))[0]
    assert np.max(np.abs(decoded-x)) < 1e-15
    assert decoded.tobytes() != x.tobytes()  # ordinary float64 encoding is lossy
    assert not P.describe("ms_gain")["implemented"]
    with pytest.raises(ParamError):
        ms_gain(x[:, :1], sr, p)
    assert P.describe("ms_gain")["master_slot"] == P.describe("stereo")["master_slot"] == 4


def test_time_align_measurements_and_sinc_bandwidth():
    sr = 48000
    x = pulse(4096, at=512)
    p = P.validate_params("time_align", {})
    assert time_align(x, sr, p)[0].tobytes() == x.tobytes()
    assert time_align(x, sr, dict(p, polarity_invert=True))[0].tobytes() == (-x).tobytes()
    delay = 100.5
    y = time_align(x, sr, dict(p, delay_ms=delay*1000/sr))[0][:, 0]
    centroid = np.dot(np.arange(len(y)), y) / np.sum(y) - 512
    assert centroid == pytest.approx(delay, abs=.01)
    freq, h = signal.freqz(y, worN=32768)
    error = np.max(np.abs(20*np.log10(np.abs(h[freq <= .9*np.pi]))))
    assert error < .01
    assert P.describe("time_align")["implemented"]
    for stages in (1, 2, 4):
        ap = time_align(pulse(8192), sr, dict(p, allpass_hz=1000, allpass_stages=stages))[0][:, 0]
        omega = 2*np.pi*np.array([100, 1000, 10000])/sr
        response = np.exp(-1j*omega[:, None]*np.arange(len(ap))) @ ap
        np.testing.assert_allclose(np.abs(response), 1, atol=1e-12)
        assert response[1] == pytest.approx(np.exp(-.5j*np.pi*stages), abs=1e-12)
    with pytest.raises(ParamError):
        time_align(x, sr, dict(p, allpass_hz=10))
    with pytest.raises(ParamError):
        P.validate_params("time_align", {"allpass_hz": 10})


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
@pytest.mark.parametrize("fraction", [.01, .25, .5, .9])
def test_time_align_precision_across_sample_rates(sr, fraction):
    x = pulse(2048, at=512)
    delay = 150 + fraction
    p = P.validate_params("time_align", {"delay_ms": delay * 1000 / sr})
    y = render("time_align", x, sr, **p).audio[:, 0]
    centroid = np.dot(y, np.arange(len(y))) / np.sum(y) - 512
    assert abs(centroid - delay) <= .01
    omega, h = signal.freqz(y, worN=8192)
    assert np.max(np.abs(20*np.log10(np.abs(h[omega <= .9*np.pi])))) <= .01


def test_time_align_channel_and_allpass_runtime_limits():
    x = pulse(4096, 2, at=512)
    result = render_chain(x, 48000, [{"type": "time_align", "channel": "left", "params": {"delay_ms": .5}}], stage="track")
    assert result.audio[:, 1].tobytes() == x[:, 1].tobytes()
    assert np.argmax(result.audio[:, 0]) == 512+24
    with pytest.raises(ParamError):
        render("time_align", x, 8000, allpass_hz=4000)


@pytest.mark.parametrize("kind", KINDS)
def test_defaults_and_all_numeric_endpoints_render(kind, monkeypatch):
    # Test pending M/S implementation directly through the same engine path,
    # restoring its public unavailable flag automatically after each case.
    if kind == "ms_gain":
        monkeypatch.setitem(P.PROCESSORS[kind], "implemented", True)
    x = pulse(256, 2, at=10)
    assert np.isfinite(render(kind, x, 48000).audio).all()
    for decl in P.describe(kind)["params"]:
        if decl["type"] in ("float", "int"):
            for edge in (decl["min"], decl["max"]):
                p = endpoint_params(kind, decl["id"], edge)
                assert np.isfinite(render(kind, x, 48000, **p).audio).all()
    if kind == "haas":
        assert np.isfinite(render(kind, x, 48000, lo_keep_hz=.1).audio).all()


def test_multitap_array_bounds_and_maximum_count():
    p = dict(tap_ms=np.linspace(.1, 4000, 16).tolist(), tap_db=[6]*16, tap_pan=[-1, 1]*8)
    assert np.isfinite(render("multitap_delay", pulse(64), 48000, **p).audio).all()
    assert np.isfinite(render("multitap_delay", pulse(64), 48000,
                              tap_ms=[.01, .02, .03], tap_unit="beats", bpm=400).audio).all()
    with pytest.raises(ParamError):
        render("multitap_delay", pulse(64), tap_ms=list(range(1, 18)), tap_db=[0]*17)


@pytest.mark.parametrize("kind", ["pingpong_delay", "slapback", "multitap_delay", "haas"])
def test_common_harness(kind, monkeypatch):
    # The harness requires shape preservation, so shape-changing types use their
    # specified exact bypass here; active stereo/mono conversion is tested above.
    params = {"delay_ms": 0} if kind == "haas" else {"mix": 0}

    def probe(x, y, sr, p):
        q = {"delay_ms": 10, "lo_keep_hz": 0} if kind == "haas" else {"mix": 1}
        if kind == "slapback":
            q.update(time_ms=40, tone_hz=0, lowcut_hz=0)
            ms = 40
        elif kind == "pingpong_delay":
            q.update(time_ms=10, feedback=0)
            ms = 10
        elif kind == "multitap_delay":
            q.update(tap_ms=[10], tap_db=[0], feedback=0)
            ms = 10
        else:
            ms = 10
        test = render(kind, pulse(sr//4), sr, **q).audio
        channel = 1 if kind == "haas" else 0
        actual = int(np.argmax(np.abs(test[:, channel])))
        return {"passed": abs(actual - ms*sr/1000) <= .5,
                "delay_samples": actual, "requested_ms": ms}

    assert_common_tests(kind, neutral=params, params=params, seconds=.03, sr_probe=probe)


@pytest.mark.parametrize("kind", ["ms_gain", "time_align"])
def test_unimplemented_diagnostics_common_harness(kind, monkeypatch):
    # Evaluate M/S DSP without declaring it available to users.
    # ms_gain's deliberate mono rejection conflicts with CT-7's fixed mono loop.
    monkeypatch.setitem(P.PROCESSORS[kind], "implemented", True)
    def probe(x, y, sr, p):
        return {"passed": np.max(np.abs(x-y)) < 1e-12, "max_error": float(np.max(np.abs(x-y)))}
    if kind == "time_align":
        assert_common_tests(kind, neutral={}, seconds=.03, sr_probe=probe)
    else:
        with pytest.raises(AssertionError, match="ms_gain requires stereo input"):
            assert_common_tests(kind, neutral={}, seconds=.03, sr_probe=probe)


@pytest.mark.parametrize("kind", KINDS)
def test_registration_and_numeric_bounds(kind):
    spec = P.describe(kind)
    p = P.validate_params(kind, {})
    assert spec["backends"] == ["reference"] and not spec["offline_only"]
    assert spec["master_slot"] != 6
    assert spec["channel_ok"] == (kind == "time_align")
    for decl in spec["params"]:
        assert p[decl["id"]] == decl["default"]
        if decl["type"] in ("float", "int"):
            for edge in (decl["min"], decl["max"]):
                endpoint = endpoint_params(kind, decl["id"], edge)
                assert P.validate_params(kind, endpoint)[decl["id"]] == edge
            for invalid in (decl["min"]-1, decl["max"]+1):
                with pytest.raises(ParamError):
                    P.validate_params(kind, {decl["id"]: invalid})


def test_bb_performance_smoke():
    sr = 48000
    x = np.zeros((sr*2, 2))
    x[0] = 1
    start = time.perf_counter()
    y = DelayLine(12000, 2, "integer").process(x, [12000, 12000], .95)
    assert np.isfinite(y).all()
    assert time.perf_counter() - start < 15


@pytest.mark.parametrize("kind", ["pingpong_delay", "multitap_delay"])
def test_longest_unsafe_feedback_rejected_before_render(kind):
    params = {"time_ms": 4000} if kind == "pingpong_delay" else {"tap_ms": [4000], "tap_db": [0]}
    params.update(mix=1, feedback=.95)
    for call in (lambda: P.validate_params(kind, params),
                 lambda: render(kind, pulse(64), **params)):
        with pytest.raises(ParamError, match="maximum allowed feedback is"):
            call()
    assert P.describe(kind)["implemented"]


@pytest.mark.parametrize("ms", [.1, 20, 125, 250, 500, 1000, 2000, 4000])
def test_feedback_boundary_and_note_conversion(ms):
    maximum = feedback_limit(ms)
    p = dict(time_ms=ms, feedback=maximum)
    assert P.validate_params("pingpong_delay", p)["feedback"] == maximum
    assert maximum ** (60000 / ms) < 1e-6
    if maximum < .95:
        with pytest.raises(ParamError, match="maximum allowed feedback is"):
            P.validate_params("pingpong_delay", dict(p, feedback=np.nextafter(maximum, 1)))
    # Both tempo-based front ends use the converted duration, not the raw value.
    if ms in (250, 500, 1000, 2000, 4000):
        bpm = 60000 / ms
        if bpm >= 20:
            q = dict(note="1/4", bpm=bpm, feedback=maximum)
        else:
            q = dict(note="1/2", bpm=2*bpm, feedback=maximum)
        assert P.validate_params("pingpong_delay", q)["feedback"] == maximum
        if maximum < .95:
            with pytest.raises(ParamError, match="maximum allowed feedback is"):
                P.validate_params("pingpong_delay", dict(q, feedback=np.nextafter(maximum, 1)))
        taps = dict(tap_ms=[1], tap_db=[0], tap_unit="beats", bpm=bpm, feedback=maximum)
        if bpm >= 20:
            P.validate_params("multitap_delay", taps)
            if maximum < .95:
                with pytest.raises(ParamError, match="maximum allowed feedback is"):
                    P.validate_params("multitap_delay", dict(taps, feedback=np.nextafter(maximum, 1)))


@pytest.mark.parametrize("kind", ["pingpong_delay", "multitap_delay"])
@pytest.mark.parametrize("channels", [1, 2])
def test_maximum_delay_and_allowed_feedback_ct8(kind, channels):
    sr = 8000
    # Excite for longer than the longest line to avoid an empty last-second
    # window between sparse impulse repeats; include both coherent and noise input.
    x = np.ones((9*sr, channels))
    x[:4*sr] = np.random.Generator(np.random.PCG64(120)).choice([-1., 1.], (4*sr, channels))
    x = np.concatenate((x, np.zeros((60*sr, channels))))
    if kind == "pingpong_delay":
        p = dict(time_ms=4000, ratio=2, input="stereo", start="right")
        maximum = feedback_limit(8000)
    else:
        p = dict(tap_ms=np.linspace(3800, 4000, 16).tolist(), tap_db=[6]*16,
                 tap_pan=[-1]*16)
        maximum = feedback_limit(4000, 16*10**(6/20))
    p.update(feedback=maximum, mix=1)
    y = render(kind, x, sr, **p).audio
    assert P.describe(kind)["implemented"]
    assert np.isfinite(y).all()
    peak = np.max(np.abs(y[-sr:]))
    assert 0 < peak < 1e-6  # Nonempty tail below -120 dBFS, with loop EQ bypassed.
    with pytest.raises(ParamError, match="maximum allowed feedback is"):
        P.validate_params(kind, dict(p, feedback=np.nextafter(maximum, 1)))
