"""W1b: BB-07, four EQ processors, and existing channel-targeted EQ."""
import json
import numpy as np
import pytest
from scipy import signal, fft

from mankomix.dsp import reference, engine as E, processors as P
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb import fir as F
from mankomix.dspx.procs import linear_eq as L, fir_eq as Q, tilt_eq as T, cut_filter as C
from tests import toolimpl_harness as H

TYPES = ("linear_eq", "fir_eq", "tilt_eq", "cut_filter")


@pytest.fixture(autouse=True)
def enable_under_test(monkeypatch):
    # Test the deliberately unavailable linear_eq without publishing it as
    # implemented; its two strict xfails retain the unmet specification.
    assert not L.SPECS[0]["implemented"]
    monkeypatch.setitem(P.PROCESSORS["linear_eq"], "implemented", True)


def run(ptype, x, sr=48000, **params):
    return E.render_chain(x, sr, [{"type": ptype, "params": params}], stage="track")


def db(x):
    return 20*np.log10(np.maximum(np.abs(x), 1e-15))


def response(h, sr=48000, nfft=262144):
    return fft.rfftfreq(nfft, 1/sr), fft.rfft(h, nfft, workers=1)


def test_bb07_design_symmetry_flat_and_cepstrum():
    h = F.design_linear_fir(lambda f: np.ones_like(f), 48000, 8193)
    assert np.array_equal(h, h[::-1])
    assert h[4096] == 1 and np.count_nonzero(h) == 1
    for sr in (44100, 48000, 96000):
        for name, taps in F.RESOLUTIONS.items():
            length = F.resolution_taps(sr, name)
            assert length % 2 and abs(length-1-(taps-1)*sr/48000) <= 1
    assert np.array_equal(F.minimum_phase(np.zeros(9)), np.zeros(9))


@pytest.mark.parametrize("shape", ["mono", "diagonal", "mimo"])
@pytest.mark.parametrize("length", [1, 37, 2071])
def test_bb07_convolution_direct_full_partitioned_and_chunks(shape, length):
    rng = np.random.Generator(np.random.PCG64(829))
    x = rng.normal(size=(length, 2))
    h = rng.normal(size={"mono": (275,), "diagonal": (275, 2), "mimo": (275, 2, 3)}[shape])
    kernel = (h[:, None, None]*np.eye(2)[None] if shape == "mono" else
              h[:, :, None]*np.eye(2)[None] if shape == "diagonal" else h)
    expected = np.zeros((len(x)+len(h)-1, kernel.shape[2]))
    for i in range(2):
        for o in range(kernel.shape[2]):
            expected[:, o] += np.convolve(x[:, i], kernel[:, i, o])
    one = F.fft_convolve(x, h)
    part = F.partitioned_convolve(x, h, 128)
    np.testing.assert_allclose(one, expected, rtol=0, atol=1e-12)
    np.testing.assert_allclose(part, expected, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(F.fft_convolve(x, h, "same"), one[:len(x)])
    for size in (1, 64, 1024, len(x)):
        conv = F.PartitionedConvolver(h, 2, 128)
        blocks = [conv.process(x[k:k+size]) for k in range(0, len(x), size)]
        blocks.append(conv.flush())
        assert np.concatenate(blocks).tobytes() == part.tobytes()
        with pytest.raises(ValueError):
            conv.process(x)
    for size in (31, 256):
        np.testing.assert_allclose(F.partitioned_convolve(x, h, size), expected, rtol=0, atol=1e-12)


def test_bb07_empty_and_invalid():
    for conv in (F.fft_convolve, F.partitioned_convolve):
        assert conv(np.zeros((0, 2)), np.ones((3, 2, 4))).shape == (0, 4)
        with pytest.raises(ValueError):
            conv(np.ones(4), np.ones(3))
        with pytest.raises(ValueError):
            conv(np.ones((4, 2)), np.ones((3, 3)))
        with pytest.raises(ValueError):
            conv(np.ones((4, 2)), np.ones(3), mode="bad")
    with pytest.raises(ValueError):
        F.design_linear_fir(lambda f: -np.ones_like(f), 48000, 5)
    with pytest.raises(ValueError):
        F.design_linear_fir(lambda f: f, 48000, 4)


@pytest.mark.parametrize("resolution", ["mid", "high", "max"])
def test_linear_eq_analog_accuracy_and_exact_symmetry(resolution):
    p = P.validate_params("linear_eq", dict(freq_hz=[100, 1000, 12000], gain_db=[-6, 9, -4],
                                          bw_oct=[.3, 1, .5], resolution=resolution,
                                          low_shelf_hz=100, low_shelf_db=3,
                                          high_shelf_hz=6000, high_shelf_db=-3))
    h = L.design(p, 48000)
    assert np.array_equal(h, h[::-1])
    f, actual = response(h, nfft=1048576)
    target = L.magnitude(f, p)
    error = float(np.max(np.abs(db(actual[f >= 100])-db(target[f >= 100]))))
    print("linear_eq", resolution, "max_error_db", error)
    assert error <= .1


def test_linear_eq_single_band_matches_existing_and_error_record():
    p = P.validate_params("linear_eq", dict(freq_hz=[1000], gain_db=[-6], bw_oct=[1]))
    h = L.design(p, 48000)
    old = reference.filters._linear_phase_fir(reference.filters.rbj_biquad("peak", 1000, -6, 1, 48000),
                                             48000, 1000, 1)
    f, a = response(h)
    _, b = response(old)
    assert np.max(np.abs(db(a)-db(b))) <= .2
    x = H.impulse(sr=48000, seconds=.3)
    stats = run("linear_eq", x, freq_hz=[20], gain_db=[12], bw_oct=[.02]).steps[0]["stats"]
    assert stats["magnitude_error_db"]["narrow_band"]
    assert stats["magnitude_error_db"]["below_100_hz"] > 0
    assert stats["pre_ringing"]["energy_ratio_db"] is not None


@pytest.mark.xfail(strict=True, reason="Specified mid=8193 taps cannot meet 0.1 dB at 100 Hz / 0.3 oct / +/-24 dB")
@pytest.mark.parametrize("gain", [-24, 24])
def test_linear_eq_spec_low_frequency_range_limit(gain):
    p = P.validate_params("linear_eq", dict(freq_hz=[100], gain_db=[gain], bw_oct=[.3]))
    f, actual = response(L.design(p, 48000), nfft=1048576)
    error = float(np.max(np.abs(db(actual[f >= 100])-db(L.magnitude(f[f >= 100], p)))))
    print("linear_eq mid 100 Hz .3 oct", gain, "dB error", error)
    assert error <= .1


@pytest.mark.parametrize("kind,params", [("linear_eq", {}), ("fir_eq", {}),
                                       ("fir_eq", {"curve": [[100, 6], [10000, -6]], "amount": 0}),
                                       ("tilt_eq", {}), ("tilt_eq", {"phase": "linear"})])
def test_neutral_is_bit_identical_and_causal_delay(kind, params):
    x = np.random.Generator(np.random.PCG64(3)).normal(size=(4001, 2))
    result = run(kind, x, **params)
    assert result.audio.tobytes() == x.tobytes()
    if kind == "linear_eq":
        h = L.design(P.validate_params(kind, params), 48000)
    elif kind == "fir_eq":
        h = Q.design(P.validate_params(kind, params), 48000)
    elif params.get("phase") == "linear":
        h = T.design(P.validate_params(kind, params), 48000)
    else:
        return
    pulse = np.zeros((len(h)+16, 1))
    pulse[0] = 1
    raw = F.fft_convolve(pulse, h)
    assert np.argmax(np.abs(raw[:, 0])) == result.steps[0]["stats"]["latency_samples"]


def test_fir_eq_curve_accuracy_minimum_phase_energy_and_gain():
    curve = [[10, 5], [100, 5], [300, -3], [1000, -3], [5000, 4], [24000, 4]]
    p = P.validate_params("fir_eq", {"curve": curve})
    linear = Q.design(p, 48000)
    minimum = Q.design({**p, "phase": "minimum"}, 48000)
    f, a = response(linear)
    _, b = response(minimum)
    curve_error = np.max(np.abs(db(a[f >= 100])-db(F.curve_magnitude(f[f >= 100], curve))))
    phase_error = np.max(np.abs(db(a)-db(b)))
    fraction = float(np.sum(minimum[:len(minimum)//2]**2)/np.sum(minimum**2))
    n99 = int(np.searchsorted(np.cumsum(minimum**2), .99*np.sum(minimum**2)))
    print("fir_eq curve_error_db", curve_error, "minimum_vs_linear_db", phase_error,
          "front_energy_fraction", fraction, "energy_99_sample", n99)
    assert curve_error <= .2 and phase_error <= .2 and fraction >= .99
    assert np.argmax(np.abs(minimum)) == 0
    result = run("fir_eq", H.impulse(sr=48000, seconds=.3), curve=curve, phase="minimum")
    assert result.steps[0]["stats"]["latency_samples"] == 0
    # A constant +6 dB curve must retain full gain through cepstral conversion.
    flat = Q.design(P.validate_params("fir_eq", {"curve": [[10, 6]], "phase": "minimum"}), 48000)
    assert abs(np.sum(flat)-10**(.3)) < 1e-12


@pytest.mark.parametrize("phase", ["minimum", "linear"])
@pytest.mark.parametrize("tilt", [-6, -3, 3, 6])
def test_tilt_pivot_endpoints_monotonic_and_slope(phase, tilt):
    p = P.validate_params("tilt_eq", {"tilt_db": tilt, "phase": phase})
    f = np.geomspace(20, 20000, 3000)
    if phase == "minimum":
        probe = lambda f: signal.sosfreqz(T.design_sos(p, 48000), worN=f, fs=48000)[1]
    else:
        h = T.design(p, 48000)
        probe = lambda f: signal.freqz(h, worN=f, fs=48000)[1]
        assert np.array_equal(h, h[::-1])
    gain = db(probe(f))
    assert abs(db(probe([650]))[0]) <= .05
    assert abs(gain[0]+tilt) <= .5 and abs(gain[-1]-tilt) <= .5
    assert np.min(np.diff(gain)*np.sign(tilt)) >= -1e-6
    assert np.max(np.abs(np.diff(gain)/np.diff(np.log2(f)))) <= 6


@pytest.mark.parametrize("kind", ["hpf", "lpf"])
@pytest.mark.parametrize("slope", [6, 12, 18, 24, 36, 48, 72, 96])
def test_cut_butter_cutoff_slope(kind, slope):
    sr, cutoff = 96000, 1000
    p = P.validate_params("cut_filter", dict(kind=kind, freq_hz=cutoff, slope_db_oct=slope))
    sos = C.design_sos(p, sr)
    assert abs(db(signal.sosfreqz(sos, worN=[cutoff], fs=sr)[1])[0]+3.01029995664) < 1e-8
    # Stopband octave measurement far enough from cutoff and digital Nyquist.
    # Use prewarped analog octaves: digital Hz octaves near Nyquist are warped.
    r = np.array([.2, .4]) if kind == "hpf" else np.array([2.5, 5])
    pair = sr/np.pi*np.arctan(np.tan(np.pi*cutoff/sr)*r)
    values = 20*np.log10(np.abs(signal.sosfreqz(sos, worN=pair, fs=sr)[1]))
    assert abs(abs(values[1]-values[0])-slope) <= 1


@pytest.mark.parametrize("kind", ["hpf", "lpf"])
@pytest.mark.parametrize("stop,ripple", [(40, 1), (80, .1), (120, .01)])
def test_cut_elliptic_stopband_and_ripple(kind, stop, ripple):
    p = P.validate_params("cut_filter", dict(kind=kind, family="elliptic", freq_hz=2000,
                                            slope_db_oct=48, stopband_db=stop, ripple_db=ripple))
    sos = C.design_sos(p, 48000)
    f = np.linspace(.01, 23999, 100000)
    gain = db(signal.sosfreqz(sos, worN=f, fs=48000)[1])
    passed = f <= 2000 if kind == "lpf" else f >= 2000
    stopped = f >= 8000 if kind == "lpf" else f <= 500
    assert np.ptp(gain[passed]) <= ripple+1e-8
    assert np.max(gain[stopped]) <= -stop+1e-8


@pytest.mark.parametrize("kind", ["hpf", "lpf"])
@pytest.mark.parametrize("slope", [12, 24, 96])
@pytest.mark.parametrize("resonance", [1, 6, 12])
def test_cut_resonance(kind, slope, resonance):
    p = P.validate_params("cut_filter", dict(kind=kind, freq_hz=2000, slope_db_oct=slope,
                                            resonance_db=resonance))
    f = np.geomspace(200, 20000, 40000)
    peak = float(np.max(db(signal.sosfreqz(C.design_sos(p, 48000), worN=f, fs=48000)[1])))
    assert abs(peak-resonance) <= .5


@pytest.mark.parametrize("slope", [12, 24, 36, 48, 72, 96])
def test_cut_linkwitz_riley_allpass(slope):
    p = P.validate_params("cut_filter", dict(family="linkwitz_riley", freq_hz=1500, slope_db_oct=slope))
    f = np.geomspace(10, 23990, 12000)
    hp = signal.sosfreqz(C.design_sos(p, 48000), worN=f, fs=48000)[1]
    lp = signal.sosfreqz(C.design_sos({**p, "kind": "lpf"}, 48000), worN=f, fs=48000)[1]
    assert np.max(np.abs(db(hp+lp))) <= .01


def test_bb07_complementary_linear_reconstruction_acceptance():
    p = P.validate_params("cut_filter", dict(family="linkwitz_riley", freq_hz=1500,
                                            slope_db_oct=24, phase="linear"))
    hp = C.design(p, 48000)
    lp = C.design({**p, "kind": "lpf"}, 48000)
    x = H.white_noise(sr=48000, seconds=.3, channels=2, seed=77)
    low, _ = F.apply_fir(x, lp, 48000)
    high, _ = F.apply_fir(x, hp, 48000)
    measured = H.null(x, low+high)
    print("linear complementary reconstruction RMS dBFS", measured["rms_dbfs"])
    assert measured["rms_dbfs"] <= -120


@pytest.mark.parametrize("kind", ["hpf", "lpf"])
@pytest.mark.parametrize("slope", [6, 12, 18, 24, 48])
def test_cut_existing_filter_null(kind, slope):
    x = H.white_noise(sr=48000, seconds=.15, channels=2, seed=73)
    params = dict(kind=kind, freq_hz=3000, slope_db_oct=slope)
    old = run("filter", x, **params).audio
    new = run("cut_filter", x, **params).audio
    assert H.null(old, new)["rms_dbfs"] <= -120


@pytest.mark.parametrize("family", ["butterworth", "linkwitz_riley", "bessel", "elliptic"])
@pytest.mark.parametrize("kind", ["hpf", "lpf"])
def test_cut_extreme_stability_and_linear_uses_magnitude(family, kind):
    p = P.validate_params("cut_filter", dict(kind=kind, family=family, freq_hz=20, slope_db_oct=96))
    x = H.impulse(sr=96000, seconds=3, channels=1, at_s=0)
    y, _, _ = C.cut_filter(x, 96000, p)
    assert np.isfinite(y).all()
    sos = C.design_sos(p, 96000)
    assert max(abs(pole) for section in sos for pole in np.roots(section[3:])) < 1
    assert np.sum(y[-96000:]**2) < np.sum(y[96000:192000]**2)
    p = {**p, "freq_hz": 2000, "slope_db_oct": 24, "phase": "linear"}
    h = C.design(p, 48000)
    assert np.array_equal(h, h[::-1])
    probe = signal.freqz(h, worN=[2000], fs=48000)[1]
    target = signal.sosfreqz(C.design_sos(p, 48000), worN=[2000], fs=48000)[1]
    assert abs(db(probe)[0]-db(target)[0]) < .05


@pytest.mark.parametrize("kind", ["hpf", "lpf"])
def test_cut_slowest_extreme_60_second_tail(kind):
    p = P.validate_params("cut_filter", dict(kind=kind, family="elliptic", freq_hz=20,
                                            slope_db_oct=96))
    x = np.zeros((60*96000, 1))
    x[0] = 1
    y, _, _ = C.cut_filter(x, 96000, p)
    tail = H.peak_dbfs(y[-96000:])
    print("elliptic 96 kHz / 20 Hz / 96 dB/oct / 60 s tail", kind, tail)
    assert np.isfinite(y).all() and tail < -120


@pytest.mark.parametrize("kind,bad", [
    ("linear_eq", {"freq_hz": [100]}),
    ("linear_eq", {"freq_hz": [100], "gain_db": [2], "bw_oct": []}),
    ("cut_filter", {"family": "linkwitz_riley", "slope_db_oct": 18}),
    ("cut_filter", {"family": "elliptic", "resonance_db": 2}),
    ("cut_filter", {"slope_db_oct": 6, "resonance_db": 2}),
    ("cut_filter", {"freq_hz": 24000}),
    ("fir_eq", {"curve": [[100, 0], [50, 1]]}),
    ("fir_eq", {"curve": [[9, 0]]}),
    ("fir_eq", {"curve": [[100, 25]]}),
    ("fir_eq", {"curve": [[10+i, 0] for i in range(513)]})])
def test_cross_validation(kind, bad):
    with pytest.raises(ParamError):
        run(kind, np.zeros((32, 2)), **bad)


def test_registration_master_order_and_schema():
    for kind in TYPES:
        spec = P.describe(kind)
        assert spec["master_slot"] == 1 and spec["stages"] == ["track", "bus", "master"]
        assert spec["backends"] == ["reference"] and not spec["offline_only"]
        E.validate_chain([{"type": kind}, {"type": "compressor"}, {"type": "limiter"}], "master")
        with pytest.raises(ChainError):
            E.validate_chain([{"type": "compressor"}, {"type": kind}], "master")
    assert not {"ms_eq", "matcheq"} & P.PROCESSORS.keys()


@pytest.mark.parametrize("kind,params,neutral,latency_params", [
    ("linear_eq", {"freq_hz": [1000], "gain_db": [6], "bw_oct": [1]},
     {"freq_hz": [], "gain_db": [], "bw_oct": []}, {}),
    ("fir_eq", {"curve": [[10, 6], [24000, 6]]}, {"curve": []}, {}),
    ("fir_eq", {"curve": [[10, 6], [24000, 6]], "phase": "minimum"}, {"curve": []}, {}),
    ("tilt_eq", {"tilt_db": 3}, {"tilt_db": 0}, {"tilt_db": 0}),
    ("tilt_eq", {"tilt_db": 3, "phase": "linear"}, {"tilt_db": 0}, {}),
    ("cut_filter", {"kind": "lpf", "freq_hz": 3000}, None,
     {"kind": "hpf", "freq_hz": 30, "slope_db_oct": 6}),
    ("cut_filter", {"kind": "lpf", "freq_hz": 3000, "phase": "linear"}, None, {})])
def test_common_contract(kind, params, neutral, latency_params):
    def declared(sr, p):
        if kind == "linear_eq" or p.get("phase") == "linear":
            return F.resolution_taps(sr, p.get("resolution", "mid"))//2
        return 0

    def raw(x, sr, p, **kwargs):
        if declared(sr, p):
            module = {"linear_eq": L, "fir_eq": Q, "tilt_eq": T, "cut_filter": C}[kind]
            return F.fft_convolve(x, module.design(p, sr))
        return reference.IMPLEMENTATIONS[kind](x, sr, p)[0]

    def probe(x, y, sr, p):
        if kind == "linear_eq":
            expected = 6
        elif kind == "fir_eq":
            expected = 6
        elif kind == "tilt_eq":
            g = 10**(p["tilt_db"]/20)
            r = np.tan(np.pi*1000/sr)/np.tan(np.pi*p["pivot_hz"]/sr)
            expected = 10*np.log10((g*g*r*r+1)/(r*r+g*g))
        else:
            r = np.tan(np.pi*1000/sr)/np.tan(np.pi*p["freq_hz"]/sr)
            expected = -10*np.log10(1+r**(p["slope_db_oct"]//3))
        # Exclude leading/trailing FIR boundaries, measure coherent tone amplitude.
        a, b = x[len(x)//3:2*len(x)//3], y[len(y)//3:2*len(y)//3]
        t = np.arange(len(x))[len(x)//3:2*len(x)//3]/sr
        basis = np.column_stack((np.sin(2*np.pi*1000*t), np.cos(2*np.pi*1000*t)))
        amp_in = np.linalg.norm(np.linalg.lstsq(basis, a, rcond=None)[0], axis=0)
        amp_out = np.linalg.norm(np.linalg.lstsq(basis, b, rcond=None)[0], axis=0)
        gain = float(np.mean(db(amp_out/amp_in)))
        return {"gain_db": gain, "expected_db": expected, "passed": abs(gain-expected) < .05}

    H.assert_common_tests(kind, params=params, neutral=neutral, seconds=.3,
                          declared_latency=declared, latency_probe=raw,
                          latency_params=latency_params, sr_probe=probe,
                          invalid_params=([{"freq_hz": [100, 200]}] if kind == "linear_eq" else None))


@pytest.mark.parametrize("kind", TYPES)
def test_declared_defaults_and_parameter_edges_are_rendered(kind):
    spec = P.describe(kind)
    defaults = P.validate_params(kind, {})
    assert defaults == {s["id"]: s["default"] for s in spec["params"]}
    x = np.ones((256, 1))
    assert np.isfinite(run(kind, x, sr=96000).audio).all()
    for item in spec["params"]:
        pid = item["id"]
        if item["type"] in ("float", "float_array"):
            values = [item["min"], item["max"]]
        elif item["type"] == "enum":
            values = item["choices"]
        else:
            continue
        for value in values:
            p = {pid: value}
            if item["type"] == "float_array":
                p = {"freq_hz": [1000], "gain_db": [6], "bw_oct": [1]}
                p[pid] = [value]
            if kind == "cut_filter" and pid == "resonance_db" and value:
                p["slope_db_oct"] = 24
            y = run(kind, x, sr=96000, **p).audio
            assert np.isfinite(y).all(), (kind, pid, value)
    if kind == "fir_eq":
        points = [[float(f), float(g)] for f, g in zip(np.geomspace(10, 24000, 512), np.linspace(-24, 24, 512))]
        assert np.isfinite(run(kind, x, sr=96000, curve=points, amount=1.5).audio).all()
    if kind == "linear_eq":
        p = dict(freq_hz=np.geomspace(10, 24000, 16).tolist(), gain_db=[24]*16, bw_oct=[6]*16)
        assert np.isfinite(run(kind, x, sr=96000, **p).audio).all()


def test_t0202_side_eq_mid_null_and_gain():
    sr = 48000
    m = H.sine(500, -20, sr=sr, seconds=.4)[:, 0]
    s = H.sine(1000, -24, sr=sr, seconds=.4)[:, 0]
    x = np.column_stack((m+s, m-s))
    y = E.render_chain(x, sr, [{"type": "eq", "channel": "side",
                              "params": {"freq_hz": 1000, "gain_db": 6, "bw_oct": 1}}], stage="track").audio
    assert H.null((y[:, 0]+y[:, 1])/2, (x[:, 0]+x[:, 1])/2)["rms_dbfs"] <= -140
    gain = H.rms_dbfs((y[4800:, 0]-y[4800:, 1])/2)-H.rms_dbfs(s[4800:])
    assert abs(gain-6) < .01


@pytest.mark.parametrize("channel,index", [("left", 1), ("right", 0)])
def test_t0202_opposite_channel_exact(channel, index):
    x = H.white_noise(sr=48000, seconds=.2, channels=2, seed=86)
    y = E.render_chain(x, 48000, [{"type": "eq", "channel": channel,
                                 "params": {"freq_hz": 1000, "gain_db": 6}}], stage="track").audio
    assert x[:, index].tobytes() == y[:, index].tobytes()


def test_t0202_linear_time_alignment_and_mono_rejection():
    x = H.impulse(sr=48000, seconds=.3, channels=2, at_s=.15)
    x[:, 1] *= .5
    chain = [{"type": "eq", "channel": "side", "params": {"freq_hz": 1000, "gain_db": 6,
                                                              "phase": "linear"}}]
    result = E.render_chain(x, 48000, chain, stage="track")
    mid = (result.audio[:, 0]+result.audio[:, 1])/2
    side = (result.audio[:, 0]-result.audio[:, 1])/2
    assert np.argmax(np.abs(mid)) == np.argmax(np.abs(side)) == 7200
    assert result.steps[0]["stats"]["latency_compensated"]
    for target in ("mid", "side", "left", "right"):
        with pytest.raises(ParamError):
            E.render_chain(x[:, :1], 48000, [{"type": "eq", "channel": target}], stage="track")


def test_t0202_omitted_channel_all_existing_chains():
    x = H.white_noise(sr=48000, seconds=.01, channels=2, seed=44)
    for spec in P._PROCESSORS:
        kind = spec["type"]
        stage = spec["stages"][0]
        item = {"type": kind}
        if kind.startswith("aw."):
            item["fallback"] = {"type": "gain", "params": {}}
        # Original loop is retained as the W0 baseline entry point.
        plain = E.render_chain(x, 48000, [item], stage=stage)
        explicit = E.render_chain(x, 48000, [{**item, "channel": "stereo"}], stage=stage)
        assert plain.audio.tobytes() == explicit.audio.tobytes(), kind
        a, b = plain.steps[0].copy(), explicit.steps[0].copy()
        b.pop("channel")
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@pytest.mark.parametrize("kind", [
    "pan", "stereo", "limiter", "resample", "dither",
    "reverb", "delay", "aw.purest_drive"])
def test_t0202_denied_types(kind):
    stage = P.describe(kind)["stages"][0]
    with pytest.raises(ParamError, match="channel targeting"):
        E.validate_chain([{"type": kind, "channel": "side"}], stage)
