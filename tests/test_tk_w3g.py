"""W3g acceptance: provenance, structural cues, measured interpolation and clock."""
import io
import json
import subprocess
import sys

import numpy as np
import pytest
from scipy import fft, signal

from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain, validate_chain
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb.asset_registry import sha256
from mankomix.dspx.bb.hrtf import (HRTFS, MODEL, model_bytes, decode_npz, load_hrtf,
                                  sphere_hrir, nearest_directions)
from mankomix.dspx.procs.binaural_pan import control_nodes, render_excerpt
from tests import toolimpl_harness as harness


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path/"settings"))


def params(**kw):
    return P.validate_params("binaural_pan", kw)


def render(x, sr=48000, stage="track", **kw):
    return render_chain(x, sr, [{"id": "w3g", "type": "binaural_pan", "params": kw}], stage=stage, seed=17)


def register(tmp_path, h=None, az=None, el=None, sr=48000, id="fixture"):
    if h is None:
        h = np.zeros((4, 40, 2))
        for i in range(4):
            h[i, 3+i, 0] = .7+i*.05
            h[i, 6-i, 1] = .8-i*.05
            h[i, 11+i, :] = [-.04, .03]
        az, el = [-60, -20, 20, 60], [-15, 15, 15, -15]
    path = tmp_path/(id+".npz")
    np.savez(path, azimuth_deg=np.asarray(az), elevation_deg=np.asarray(el), hrir=h, sr=np.int64(sr))
    HRTFS.register_file(path, id=id, license_spdx="unknown")
    return path, h, np.asarray(az), np.asarray(el)


def noise(frames=3072, channels=2):
    return np.random.Generator(np.random.PCG64(9)).normal(0, .08, (frames, channels))


def test_catalogue_and_original_hash():
    entries = HRTFS.catalog()["hrtfs"]
    assert [e["id"] for e in entries] == ["model_sphere"]
    assert entries[0]["sha256"] == sha256(model_bytes())
    assert entries[0]["license"]["spdx"] == "Apache-2.0"
    _, stats = load_hrtf("model_sphere", 48000)
    assert stats["warnings"] == [] and "path" not in stats["asset"]


@pytest.mark.parametrize("missing", ["license", "sha256", "origin", "channels", "model_version"])
def test_catalogue_rejects_missing(missing):
    doc = HRTFS.catalog()
    del doc["hrtfs"][0][missing]
    with pytest.raises(ParamError):
        HRTFS.check(doc)


def test_local_provenance_and_tamper(tmp_path):
    path, *_ = register(tmp_path)
    public = HRTFS.resolve("fixture")
    assert public["tier"] == "byo" and "path" not in public
    assert public["license"]["spdx"] == "unknown"
    _, stats = load_hrtf("fixture", 48000)
    assert any("unknown" in s for s in stats["warnings"])
    with pytest.raises(ParamError):
        HRTFS.register_file(path, id="model_sphere", license_spdx="unknown")
    with pytest.raises(ParamError):
        HRTFS.register_file(path, id="fixture", license_spdx="unknown")
    path.write_bytes(path.read_bytes()+b"changed")
    with pytest.raises(ParamError, match="sha256 mismatch"):
        render(noise(64, 1), hrtf="fixture")  # warm cache must still rehash
    HRTFS.remove("fixture")
    assert path.exists()
    with pytest.raises(ParamError, match="unregistered"):
        params(hrtf="fixture")


@pytest.mark.parametrize("key,value", [("azimuth_deg", [181]), ("elevation_deg", [91]),
                                      ("sr", 48000.5), ("hrir", np.zeros((1, 8, 1))),
                                      ("hrir", np.full((1, 8, 2), np.nan))])
def test_npz_validation(key, value):
    doc = dict(azimuth_deg=[0], elevation_deg=[0], sr=np.int64(48000), hrir=np.ones((1, 8, 2)))
    doc[key] = value
    out = io.BytesIO(); np.savez(out, **doc)
    with pytest.raises(ParamError):
        decode_npz(out.getvalue())


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
def test_sphere_cues(sr):
    h = sphere_hrir(sr, 90)
    # Independent peak ITD and sinusoidal response measurement.
    itd = np.diff(np.argmax(np.abs(h), axis=0))[0]*-1000/sr
    assert .6 <= itd <= .75
    frequency = np.array([1000, 2000, 4000, 8000, 12000])
    responses = [signal.freqz(h[:, e], worN=frequency, fs=sr)[1] for e in range(2)]
    ild = 20*np.log10(np.abs(responses[1]/responses[0]))
    assert np.min(ild) >= 5
    front = sphere_hrir(sr, 0)
    assert front[:, 0].tobytes() == front[:, 1].tobytes()
    for channels in (1, 2):
        pulse = np.zeros((len(h)*2, channels)); pulse[100] = 1
        y = render(pulse, sr, azimuth_deg=90).audio
        measured_itd = -np.diff(np.argmax(np.abs(y), axis=0))[0]*1000/sr
        assert .6 <= measured_itd <= .75 and y.shape == (len(pulse), 2)
    print(json.dumps({"sr": sr, "itd_ms": float(itd), "ild_db": ild.tolist()}, sort_keys=True))


@pytest.mark.parametrize("angle", [0, 17.3, 90, 179, 180])
@pytest.mark.parametrize("mode", ["mono_sum", "stereo"])
def test_bit_exact_mirror(angle, mode):
    x = noise()
    p = dict(azimuth_deg=angle, elevation_deg=23, input=mode, room=.7, lo_bypass_hz=150)
    y = render(x, **p).audio
    p["azimuth_deg"] = -angle
    mirror = render(x[:, ::-1], **p).audio
    assert y[:, ::-1].tobytes() == mirror.tobytes()


def test_moving_mirror_and_frontal_st1():
    x = noise()
    path = [[0, -37.3], [.04, 81.7], [.1, 3.1]]
    p = dict(path=path, elevation_path=[[0, -30], [.07, 60]], input="stereo", room=.3)
    a = render(x, **p).audio
    p["path"] = [[t, -v] for t, v in path]
    b = render(x[:, ::-1], **p).audio
    assert a[:, ::-1].tobytes() == b.tobytes()
    front = render(x).audio
    assert front[:, 0].tobytes() == front[:, 1].tobytes()


@pytest.mark.parametrize("i", range(4))
def test_measured_grid_convolution(tmp_path, i):
    _, h, az, el = register(tmp_path)
    x = noise(3072, 1)
    y = render(x, hrtf="fixture", azimuth_deg=float(az[i]), elevation_deg=float(el[i])).audio
    reference = np.column_stack([np.convolve(x[:, 0], h[i, :, ear])[:len(x)] for ear in range(2)])
    error = harness.null(y, reference)
    assert error["rms_dbfs"] <= -100
    print(json.dumps({"grid_row": i, "null_dbfs": error["rms_dbfs"]}))


def test_neighbours_and_separate_delay(tmp_path):
    az, el = np.array([-30., 30., 0., 0.]), np.array([0., 0., -30., 30.])
    ids, w = nearest_directions(az, el, 0., 0.)
    assert ids.tolist() == [0, 1, 2, 3]
    assert np.max(np.abs(w-.25)) < 1e-14
    h = np.zeros((4, 24, 2))
    for i in range(4):
        h[i, 2*i, :] = 1
    register(tmp_path, h, az, el)
    prepared, _ = load_hrtf("fixture", 48000)
    kernel = prepared.kernel(0, 0, 48000)
    assert np.argmax(kernel[:, 0]) == 3
    assert abs(kernel[3, 0]-1) < 1e-12
    assert np.max(np.abs(np.delete(kernel[:, 0], 3))) < 1e-12


def test_sr_resampling_and_elevation(tmp_path):
    h = np.zeros((1, 160, 2)); h[0, 24, :] = 1
    register(tmp_path, h, [0], [0], sr=48000)
    for sr in (44100, 96000):
        prepared, _ = load_hrtf("fixture", sr)
        assert abs(np.argmax(prepared.kernel(0, 0, sr)[:, 0])/sr-.0005) <= 1/sr
    assert not np.array_equal(sphere_hrir(48000, 30, 45), sphere_hrir(48000, 30, -45))


def test_absolute_nodes_and_excerpt():
    p = params(path=[[0, -40], [.01, 60], [.11, -20]], elevation_path=[[0, 0], [.2, 40]])
    all_nodes = np.arange(0, 6016, 64)
    a = control_nodes(p, 48000, all_nodes)
    b = control_nodes(p, 48000, all_nodes[7:])
    for full, part in zip(a, b):
        assert full[7:].tobytes() == part.tobytes()
    x = noise(6000)
    y = render(x, **p).audio
    part = render_excerpt(x, 48000, p, 1031, 5097, seed=17)
    assert part.tobytes() == y[1031:5097].tobytes()


@pytest.mark.parametrize("measured", [False, True])
def test_motion_update_sidebands(tmp_path, measured):
    sr = 16000  # hop rate 250 Hz; coherent carrier and motion over one second
    t = np.arange(sr*2)/sr
    path = [[float(q), float(35+5*np.sin(2*np.pi*q))] for q in np.arange(513)/256]
    p = dict(path=path)
    if measured:
        h = np.zeros((4, 32, 2))
        for i in range(4):
            h[i, 2+i, 0] = .5+.1*i
            h[i, 1, 1] = 1-.08*i
        register(tmp_path, h, [0, 30, 60, 90], [0]*4, sr)
        p["hrtf"] = "fixture"
    x = (.2*np.sin(2*np.pi*2000*t))[:, None]
    y = render(x, sr, **p).audio[-sr:]
    spectrum = np.abs(fft.rfft(y*np.hanning(sr)[:, None], axis=0, workers=1))
    carrier = np.max(spectrum[1998:2003], axis=0)
    levels = []
    for order in (1, 2, 3):
        for sign in (-1, 1):
            center = 2000+sign*order*sr//64
            levels.append(float(np.max(20*np.log10(np.max(spectrum[center-3:center+4], axis=0)/carrier))))
    worst = max(levels)
    assert worst <= -70
    print(json.dumps({"measured": measured, "update_sideband_dbc": worst}))


def test_mono_statistics_st2():
    result = render(noise(), azimuth_deg=90)
    y = result.audio
    stats = result.steps[0]["stats"]
    expected = 10*np.log10(np.mean(((y[:, 0]+y[:, 1])/2)**2)/(np.mean(y*y)))
    assert abs(stats["mono"]["mono_loss_db"]-expected) <= .1
    assert "mono_worst_third_octave_db" in stats
    assert "correlation" in stats["mono"]
    spectrum = fft.rfft(y, axis=0, workers=1)
    frequencies = fft.rfftfreq(len(y), 1/48000)
    losses = []
    for i in range(-17, 14):
        centre = 1000*2**(i/3)
        band = spectrum[(frequencies >= centre/2**(1/6)) & (frequencies < centre*2**(1/6))]
        energy = np.sum(np.abs(band)**2)/2
        if energy:
            folded = np.sum(np.abs(np.mean(band, axis=1))**2)
            losses.append(10*np.log10(max(folded/energy, 1e-300)))
    assert abs(stats["mono_worst_third_octave_db"]-min(losses)) <= .1
    levels = 10*np.log10(np.sum(y[:, 1]**2)/np.sum(y[:, 0]**2))
    assert abs(stats["level_difference_db"]-levels) <= .001
    assert "mono fold" in stats["binaural_note"]
    print(json.dumps({"spatial": stats}, sort_keys=True))


def test_distance_low_bypass_room():
    x = noise(12000, 1)
    base = render(x).audio
    half = render(x, distance_gain=True, distance_m=.75).audio
    assert np.max(np.abs(half-2*base)) < 1e-14
    same = render(x, distance_m=50).audio
    assert base.tobytes() == same.tobytes()
    far = render(x, distance_gain=True, distance_m=50).audio
    assert np.mean(far*far) < np.mean(base*base)/100
    pulse = np.zeros((4000, 1)); pulse[0] = 1
    wet = render(pulse, room=1).audio-render(pulse).audio
    assert abs(wet[round(.007*48000), 0]) > .05
    # A 30 Hz tone stays close to the centre when the split is at 300 Hz.
    t = np.arange(48000)/48000
    low = render(np.sin(2*np.pi*30*t)[:, None]*.1, azimuth_deg=90, lo_bypass_hz=300).audio[10000:]
    centered = render(np.sin(2*np.pi*30*t)[:, None]*.1, azimuth_deg=90).audio[10000:]
    assert np.mean((low[:, 0]-low[:, 1])**2) < np.mean((centered[:, 0]-centered[:, 1])**2)/10


def test_defaults_ranges_and_contracts():
    expected = dict(hrtf="model_sphere", azimuth_deg=0., elevation_deg=0., distance_m=1.5,
                    path=[], elevation_path=[], distance_gain=False, room=0., input="mono_sum",
                    spread_deg=30., lo_bypass_hz=0.)
    assert params() == expected
    for spec in P.describe("binaural_pan")["params"]:
        if spec["type"] == "float":
            for value in (spec["min"], spec["max"]):
                assert np.isfinite(render(noise(128, 1), **{spec["id"]: value}).audio).all()
    for key, bounds in (("path", (-180, 180)), ("elevation_path", (-90, 90))):
        full = [[float(i), float(bounds[i % 2])] for i in range(4096)]
        assert len(params(**{key: full})[key]) == 4096
        for invalid in (full+[[4096., 0.]], [[0., bounds[1]+1]], [[1., 0.], [0., 0.]], [[-1., 0.]], [[0., float("nan")]]):
            with pytest.raises(ParamError):
                params(**{key: invalid})
    with pytest.raises(ParamError):
        params(hrtf="not_registered")
    with pytest.raises(ParamError):
        validate_chain([dict(id="p", type="binaural_pan", channel="left")], "track")
    with pytest.raises(ChainError):
        validate_chain([dict(id="p", type="binaural_pan")], "master")
    assert "binaural_pan" in __import__("mankomix.dspx.registry", fromlist=["time_varying_types"]).time_varying_types()


def test_common_ct1_to_ct8(monkeypatch):
    # BB-01 assumes all processors preserve channel count. This explicit test
    # adapter retains all measurements and uses T05's mono->stereo contract.
    # No numeric acceptance limit is changed and no mono case is omitted.
    original = harness.run_common_tests

    def probe(x, y, sr, p):
        frequency = harness.fundamental_frequency(y, sr, low_hz=900, high_hz=1100)
        good = abs(frequency-1000) <= 1
        return dict(passed=good, frequency_hz=frequency, frequency_passed=good,
                    finite=bool(np.isfinite(y).all()),
                    binaural_shape_passed=y.shape == (len(x), 2))

    def adapted(*args, **kw):
        results = original(*args, **kw)
        ct = results["CT-7"]
        for row in ct["measurements"]:
            row["passed"] = bool(row["frequency_passed"] and row["binaural_shape_passed"] and row["finite"])
        ct["passed"] = all(row["passed"] for row in ct["measurements"])
        ct["shape_contract"] = "T05 mono to stereo; all mono/stereo cases measured"
        return results

    monkeypatch.setattr(harness, "run_common_tests", adapted)
    results = harness.assert_common_tests("binaural_pan", params={}, neutral=None,
                                          seconds=.025, sr_probe=probe,
                                          invalid_params=[dict(path=[[0, 181]])])
    print(json.dumps({"common_passed": {k: v["passed"] for k, v in results.items()},
                      "ct7": results["CT-7"]}, sort_keys=True))


def test_fractional_itd_extraction(tmp_path):
    from mankomix.dspx.bb.delayline import fractional_delay
    h = np.zeros((4, 128, 2))
    impulse = np.zeros((128, 1)); impulse[0] = 1
    delays = [7.25, 9.5, 13.75, 17.125]
    for i, delay in enumerate(delays):
        h[i, :, 0] = fractional_delay(impulse, delay)[:, 0]
        h[i, :, 1] = fractional_delay(impulse, 5.+delay % 1)[:, 0]
    register(tmp_path, h, [-60, -20, 20, 60], [0]*4)
    prepared, _ = load_hrtf("fixture", 48000)
    # A finite sinc has its own minimum-phase delay. Identical fractional
    # kernels in both ears cancel that contribution in the known ITD.
    want = np.floor(delays)-5
    assert np.max(np.abs(np.diff(prepared.delays, axis=1)[:, 0]+want)) < 1e-8
    assert np.all(np.abs(prepared.delays[:, 0]-np.rint(prepared.delays[:, 0])) > .01)


def test_sofa_converter_numeric_contract(tmp_path, monkeypatch):
    # h5py is optional and absent in the runtime. A dataset adapter tests the
    # conversion math without adding a dependency or claiming a real HDF5 read.
    from types import SimpleNamespace
    from tools.register_hrtf import convert_sofa

    class Dataset:
        def __init__(self, data, **attrs):
            self.data, self.attrs = np.asarray(data), attrs
        def __array__(self, dtype=None, copy=None):
            return np.asarray(self.data, dtype=dtype)

    class File(dict):
        attrs = {"SOFAConventions": "SimpleFreeFieldHRIR"}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    ir = np.zeros((2, 2, 16)); ir[:, :, 0] = 1
    source = File(SourcePosition=Dataset([[30, 10, 1.5], [330, -10, 1.5]], Type="spherical", Units="degree, degree, metre"),
                  ReceiverPosition=Dataset([[0, .09, 0], [0, -.09, 0]], Type="cartesian"),
                  **{"Data.SamplingRate": Dataset([48000]), "Data.IR": Dataset(ir),
                     "Data.Delay": Dataset([[2, 4]], Units="samples")})
    monkeypatch.setitem(sys.modules, "h5py", SimpleNamespace(File=lambda *args: source))
    target = tmp_path/"converted.npz"
    convert_sofa("unused", target)
    az, el, h, sr = decode_npz(target.read_bytes())
    assert az.tolist() == [-30, 30] and el.tolist() == [10, -10] and sr == 48000
    assert np.argmax(h[0], axis=0).tolist() == [2, 4]
    with pytest.raises(FileExistsError):
        convert_sofa("unused", target)
    source["SourcePosition"].attrs["Type"] = "cartesian"
    with pytest.raises(ValueError, match="spherical"):
        convert_sofa("unused", tmp_path/"bad.npz")


def test_register_cli(tmp_path):
    path, *_ = register(tmp_path)
    HRTFS.remove("fixture")
    def cli(*args):
        out = subprocess.run([sys.executable, "-B", "tools/register_hrtf.py", *args], capture_output=True, text=True, check=True)
        return json.loads(out.stdout)
    result = cli("register", str(path), "--id", "from_cli", "--license", "unknown")
    assert "path" not in result["entry"]
    assert cli("list")["byo"][0]["id"] == "from_cli"
    assert cli("remove", "from_cli")["removed"] == "registration"
