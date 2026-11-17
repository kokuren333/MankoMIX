"""W2c: registry provenance, IR convolution, image geometry and contracts."""
import json
import math
import subprocess
import sys
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf
from scipy import fft
from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb.ir import IRS, load_ir, synthetic_bytes, prepare_ir, convolve_ir, decay_time
from mankomix.dspx.bb.image_source import image_ir, image_taps
from tests.toolimpl_harness import assert_common_tests, rt60

KINDS = ("conv_reverb", "early_reflections", "cab_ir")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path/"settings"))


def params(kind, **kw):
    return P.validate_params(kind, kw)


def render(kind, x, sr=48000, **kw):
    return render_chain(x, sr, [{"id": "w2c", "type": kind, "params": kw}], stage="track", seed=13)


def register(tmp_path, h, sr=48000, id="test_ir", kind="room", license_spdx="unknown"):
    path = tmp_path/(id+".wav")
    sf.write(path, np.asarray(h), sr, subtype="DOUBLE")
    IRS.register_file(path, id=id, kind=kind, license_spdx=license_spdx)
    return path


def test_generator_and_catalogue():
    for e in IRS.catalog()["irs"]:
        h, s = load_ir(e["id"], e["sr"])
        assert s["source_sha256"] == e["sha256"]
        assert h.shape == (round(e["length_s"]*e["sr"]), e["channels"])
    result = subprocess.run([sys.executable, "-B", "tools/generate_synthetic_irs.py"], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {e["id"]:e["sha256"] for e in IRS.catalog()["irs"]}


@pytest.mark.parametrize("bad", ["license", "sha256", "sr", "channels", "origin"])
def test_catalogue_rejects_missing(bad):
    doc = IRS.catalog()
    del doc["irs"][0][bad]
    with pytest.raises(ParamError):
        IRS.check(doc)


def test_local_rules_and_rehash(tmp_path):
    path = register(tmp_path, np.array([1., 0, 0]))
    e = IRS.resolve("test_ir")
    assert "path" not in e and e["tier"] == "byo"
    _, s = load_ir("test_ir", 48000)
    assert any("unknown" in w for w in s["warnings"])
    assert s["asset"]["license"]["spdx"] == "unknown"
    with pytest.raises(ParamError):
        IRS.register_file(path, id="synth_room_a", license_spdx="unknown")
    with pytest.raises(ParamError):
        IRS.register_file(path, id="another", license_spdx="")
    with pytest.raises(ParamError):
        IRS.register_file(path, id="test_ir", license_spdx="unknown")
    sf.write(path, np.array([.5, 0, 0]), 48000, subtype="DOUBLE")
    with pytest.raises(ParamError, match="sha256 mismatch"):
        render("conv_reverb", np.ones((32, 1)), ir="test_ir", mix=0)
    IRS.remove("test_ir")
    assert path.exists()
    with pytest.raises(ParamError, match="unregistered"):
        load_ir("test_ir", 48000)


@pytest.mark.parametrize("kind", KINDS[:1]+KINDS[2:])
def test_unknown_and_kind(kind):
    with pytest.raises(ParamError):
        params(kind, ir="no_such_ir")
    if kind == "cab_ir":
        assert params(kind)["ir_b"] == ""
        with pytest.raises(ParamError, match="kind cabinet"):
            params(kind, ir="synth_room_a")
    else:
        with pytest.raises(ParamError):
            params(kind, ir="")


@pytest.mark.parametrize("channels", [1, 2])
def test_unit_delay_and_direct_convolution(channels):
    rng = np.random.Generator(np.random.PCG64(7))
    x = rng.normal(size=(128, channels))*.2
    assert np.max(np.abs(convolve_ir(x, np.ones((1, 1)))-x)) < 1e-12
    h = np.zeros((19, 1)); h[7] = .25
    want = np.zeros_like(x); want[7:] = .25*x[:-7]
    assert np.max(np.abs(convolve_ir(x, h)-want)) < 1e-12
    h = rng.normal(size=(21, channels))*.1
    want = np.column_stack([np.convolve(x[:, i], h[:, i])[:len(x)] for i in range(channels)])
    assert np.max(np.abs(convolve_ir(x, h)-want)) < 1e-12


def test_four_channel_and_mono_expansion(tmp_path):
    h = np.zeros((10, 4)); h[2] = [1, 2, 3, 4]
    x = np.zeros((64, 2)); x[0] = [5, 7]
    y = convolve_ir(x, h)
    assert np.allclose(y[2], [26, 38], atol=1e-12)
    assert np.allclose(convolve_ir(x[:, :1], h)[2], [20, 30], atol=1e-12)
    register(tmp_path, np.array([[1., .5], [0, 0]]))
    r = render("conv_reverb", x[:, :1], ir="test_ir", mix=1, lowcut_hz=20, highcut_hz=20000)
    assert r.audio.shape == (64, 2)


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
def test_resample_and_decay(sr):
    h, s = load_ir("synth_room_a", sr)
    rt = decay_time(h, sr)
    assert abs(rt/.8-1) < .02
    half = prepare_ir(h, sr, decay=.5)
    assert abs(decay_time(half, sr)/rt-.5) < .025
    assert len(s["cache_key"]["converted_sha256"]) == 64
    print("IR_RT", sr, rt, decay_time(half, sr))


def test_cab_unit_and_delay_engine(tmp_path):
    h = np.zeros(200); h[0] = 1
    register(tmp_path, h, id="unit", kind="cabinet")
    x = np.random.Generator(np.random.PCG64(3)).normal(size=(800, 2))*.1
    y = render("cab_ir", x, ir="unit", gain_mode="none").audio
    assert np.max(np.abs(y-x)) < 1e-12
    h[:] = 0; h[31] = .2
    register(tmp_path, h, id="delay", kind="cabinet")
    y = render("cab_ir", x, ir="delay", gain_mode="none").audio
    assert np.max(np.abs(y[31:]-.2*x[:-31])) < 1e-12
    for sr in (48000, 96000):
        yy = render("cab_ir", x, sr=sr, ir="unit").audio
        assert np.isfinite(yy).all()


def test_minimum_phase_and_comb(tmp_path):
    h, _ = load_ir("synth_cab_a", 48000)
    a = prepare_ir(h, 48000, gain_mode="none")
    b = prepare_ir(h, 48000, gain_mode="none", phase="minimum")
    A, B = abs(fft.rfft(a[:, 0], 65536, workers=1)), abs(fft.rfft(b[:, 0], 65536, workers=1))
    mask = A > A.max()*1e-5
    error = float(np.max(abs(20*np.log10(B[mask]/A[mask]))))
    assert error < .1
    assert np.sum(b[:len(b)//4]**2)/np.sum(b*b) >= .99
    h = np.zeros(1024); h[0] = 1
    register(tmp_path, h, id="unit", kind="cabinet")
    x = np.zeros((4800, 1)); x[0] = 1
    r = render("cab_ir", x, ir="unit", ir_b="unit", blend=.5, b_delay_ms=1, gain_mode="none", phase="minimum")
    mag = abs(fft.rfft(r.audio[:, 0], 48000, workers=1))
    assert mag[500] < 1e-12 and abs(mag[1000]-1) < 1e-12
    assert r.steps[0]["stats"]["latency_samples"] == 0
    print("CAB_MIN_MAG_DB", error)


def test_first_order_geometry_and_gains():
    p = params("early_reflections", max_order=1, max_ms=200, lowcut_hz=20, highcut_hz=20000, damping_hz=20000)
    taps = image_taps(48000, p)
    assert len(taps) == 6
    # Independently mirror the source across each of the six physical planes.
    room = np.array([8., 12., 4.]); receiver = room*np.array([.5, .43, .47])
    source = receiver+np.array([0, 3, 0])
    expected = []
    for axis in range(3):
        for side in (0, 1):
            image = source.copy(); image[axis] = -source[axis] if side == 0 else 2*room[axis]-source[axis]
            d = np.linalg.norm(image-receiver)
            expected.append((d/343*48000, math.sqrt(.7)/d))
    for t, (delay, gain) in zip(sorted(taps, key=lambda v:v["delay_samples"]), sorted(expected)):
        assert abs(t["delay_samples"]-delay) < 1e-10
        assert abs(20*math.log10(t["gain"]/gain)) < .1
    # Each isolated sinc tap peaks at the independently rounded arrival.
    for tap in taps:
        from mankomix.dspx.bb.delayline import read_samples
        d = tap["delay_samples"]
        pulse = read_samples(np.ones((1,1)), np.arange(math.ceil(d)+10)-d, "sinc8")[:,0]
        assert abs(np.argmax(abs(pulse))-d) <= 1
        assert abs(np.sum(pulse)-1) < 1e-12


@pytest.mark.parametrize("order", [1, 2, 3, 4, 5, 6])
def test_tap_counts_support_and_mirror(order):
    p = params("early_reflections", max_order=order, azimuth=.4)
    h, stats = image_ir(48000, p)
    assert stats["tap_count"] == (4*order**3+6*order**2+8*order)//3
    assert len(h) == round(.08*48000)
    other, _ = image_ir(48000, dict(p, azimuth=-.4))
    assert np.max(np.abs(h[:, ::-1]-other)) < 1e-12
    x = np.zeros((9600, 2)); x[0] = 1
    y = render("early_reflections", x, **dict(p, mix=1)).audio
    assert np.max(np.abs(y[3840:])) < 1e-12
    assert "mono" in render("early_reflections", x, **p).steps[0]["stats"]


@pytest.mark.parametrize("kind", KINDS)
def test_defaults_and_parameter_endpoints(kind):
    p = params(kind)
    x = np.zeros((64, 2)); x[0] = .1
    assert np.isfinite(render(kind, x).audio).all()
    assert p == {s["id"]:s["default"] for s in P.PROCESSORS[kind]["params"]}
    for s in P.PROCESSORS[kind]["params"]:
        values = [s["min"],s["max"]] if s["type"] in ("float", "int") else s.get("choices", [False, True] if s["type"] == "bool" else [])
        for v in values:
            kw = {s["id"]:v}
            if kind == "early_reflections":
                kw.update(distance_m=.5)
                if s["id"] == "distance_m":
                    kw.update(room_w_m=50, room_l_m=80, distance_m=v)
            r = render(kind, x, sr=8000, **kw)
            assert np.isfinite(r.audio).all(), (kind, s["id"], v)
    with pytest.raises(Exception):
        render_chain(x, 48000, [{"type":kind}], stage="master")


@pytest.mark.parametrize("kind", KINDS)
def test_common(kind):
    # Conv's stereo assets expand mono. CT-7's fixed-shape harness uses bypass,
    # then the probe measures active kernels separately at each rate.
    pp = {"mix":0} if kind == "conv_reverb" else {}
    def probe(x, y, sr, p):
        if kind in ("cab_ir", "conv_reverb"):
            h, _ = load_ir(p["ir"], sr)
            if kind == "conv_reverb":
                assert abs(decay_time(h, sr)/.8-1) < .02
            else:
                peak = int(np.argmax(np.abs(h[:, 0])))
                assert peak/sr < .02
        else:
            taps = image_taps(sr, p)
            assert abs(min(t["delay_samples"] for t in taps)/sr-min(t["distance_m"] for t in taps)/343) < 1e-12
        return {"passed": True, "sr":sr}
    result = assert_common_tests(kind, params=pp, neutral={"mix":0}, sr_probe=probe,
                               latency_params={"mix":0}, seconds=.04)
    assert all(v["passed"] for v in result.values())


def test_generic_additional_registry(tmp_path, monkeypatch):
    from mankomix.dspx.bb.asset_registry import AssetRegistry
    path = tmp_path/"other.json"
    path.write_text(json.dumps({"schema_version":1,"other":[]}), encoding="utf-8")
    reg = AssetRegistry("other", path, lambda data:{"size":len(data)})
    source = tmp_path/"source.bin"; source.write_bytes(b"sample")
    reg.register_file(source, id="local", license_spdx="unknown")
    assert reg.load("local")[0] == b"sample"
    from mankomix.dspx import assets
    monkeypatch.setitem(assets.RESOLVERS, "other", reg.resolve)
    assert assets.resolve("other", "local")["tier"] == "byo"
    reg.remove("local")
    assert source.read_bytes() == b"sample"


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
def test_active_conv_measurements_and_decay(sr):
    x = np.zeros((round(2.5*sr), 2)); x[0] = 1
    r = render("conv_reverb", x, sr=sr, mix=1, predelay_ms=0, lowcut_hz=20, highcut_hz=20000)
    half = render("conv_reverb", x, sr=sr, mix=1, predelay_ms=0, lowcut_hz=20, highcut_hz=20000, decay=.5)
    full_rt, half_rt = rt60(r.audio, sr, band_hz=1000), rt60(half.audio, sr, band_hz=1000)
    assert abs(full_rt/.8-1) < .1  # RT2: declared RT60 +/-10%.
    reference, _ = load_ir("synth_room_a", 44100)
    reference_rt = rt60(reference, 44100, band_hz=1000)
    assert abs(full_rt/reference_rt-1) < .02  # T03-01(5): resampling +/-2%.
    assert abs(half_rt/full_rt-.5) < .025
    stats = r.steps[0]["stats"]
    assert all(key in stats for key in ("rt60_measured_s", "er_late_measured_db", "dr_db_white", "mono"))
    assert abs(stats["rt60_measured_s"]["1000"]/full_rt-1) < .02
    print("CONV_ACTIVE_RT", sr, full_rt, half_rt)


@pytest.mark.parametrize("sr", [48000, 96000])
def test_cab_imported_44100_decay(tmp_path, sr):
    n = round(.5*44100)
    rng = np.random.Generator(np.random.PCG64(123))
    h = rng.normal(size=n)*np.exp(-math.log(1000)*np.arange(n)/(44100*.15))
    register(tmp_path, h, sr=44100, id="decay_cab", kind="cabinet")
    values = []
    for rate in (44100, sr):
        x = np.zeros((rate, 1)); x[0] = 1
        y = render("cab_ir", x, sr=rate, ir="decay_cab", length_ms=500).audio
        values.append(rt60(y, rate, band_hz=1000))
    assert abs(values[1]/values[0]-1) < .02


def test_conv_active_delta_matches_wet_filters(tmp_path):
    from mankomix.dspx.bb.delayline import LoopFilter
    register(tmp_path, np.array([1., 0, 0]))
    x = np.random.Generator(np.random.PCG64(112)).normal(size=(512, 2))*.1
    actual = render("conv_reverb", x, ir="test_ir", gain_mode="none", mix=1, predelay_ms=0,
                    lowcut_hz=20, highcut_hz=20000).audio
    expected = LoopFilter(48000, 2, 20, 20000)(x)
    assert np.max(abs(actual-expected)) < 1e-12


def test_bypass_bits_and_channel_target(tmp_path):
    x = np.random.Generator(np.random.PCG64(41)).normal(size=(128,2))*.1
    for kind in KINDS:
        assert render(kind, x, mix=0).audio.tobytes() == x.tobytes()
    r = render_chain(x, 48000, [{"id":"cab", "type":"cab_ir", "channel":"left"}], stage="track", seed=0)
    assert r.audio[:,1].tobytes() == x[:,1].tobytes()


def test_invalid_geometry_and_unsupported_audio(tmp_path):
    with pytest.raises(ParamError, match="inside"):
        params("early_reflections", distance_m=30)
    path = tmp_path/"bad.wav"; path.write_bytes(b"invalid")
    with pytest.raises(ParamError):
        IRS.register_file(path, id="bad", license_spdx="unknown")
    register(tmp_path, np.zeros(10), id="silent")
    h, _ = load_ir("silent", 48000)
    assert np.array_equal(prepare_ir(h,48000),h)
    with pytest.raises(ParamError, match="beyond"):
        prepare_ir(h,48000,start_ms=500)


def test_render_stats_preserve_byo_license_without_paths(tmp_path):
    register(tmp_path, np.array([1.,0,0]), id="unknown_cab", kind="cabinet")
    x = np.ones((64,1))*.1
    result = render("cab_ir", x, ir="unknown_cab")
    stats = result.steps[0]["stats"]
    assert stats["asset"]["license"]["spdx"] == "unknown"
    assert any("unknown" in w for w in stats["warnings"])
    assert str(tmp_path) not in json.dumps(result.steps)


@pytest.mark.parametrize("kind", KINDS)
def test_sixty_second_tail(kind):
    sr = 4000
    x = np.zeros((sr*61, 2))
    x[:80] = np.random.Generator(np.random.PCG64(9)).choice([-1.,1.], (80,2))
    r = render(kind, x, sr=sr, mix=1)
    peak = float(np.max(abs(r.audio[-sr:])))
    assert peak < 1e-6
    print("TAIL_60S", kind, peak)


def test_cache_returns_copies_and_optional_asset_stays_strict():
    h, meta = load_ir("synth_cab_a", 48000)
    expected = h.copy(); h[:] = 0
    again, other = load_ir("synth_cab_a", 48000)
    assert np.array_equal(again, expected)
    assert meta["cache_key"] == other["cache_key"]
    with pytest.raises(ParamError):
        params("cab_ir", ir_b="missing")
    with pytest.raises(ParamError):
        params("cab_ir", ir_b=123)



def test_true_stereo_energy_normalization():
    h = np.array([[1.,0,0,1]])
    assert np.array_equal(prepare_ir(h,48000),h)



def test_public_registration():
    for kind in KINDS:
        definition = P.PROCESSORS[kind]
        assert definition["implemented"] is True
        assert definition["stages"] == ["track", "bus"]
        assert definition["master_slot"] is None
        assert definition["backends"] == ["reference"]
        assert definition["realtime"] == {"block_ok":False, "latency_samples":0, "allocates":True}
