"""Tests of the native DSP core through its ctypes binding (dsp/native_backend.py).

Everything except the import-safety test is skipped when the library has not
been built (python -I tools/build_native.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from mankomix.dsp import native_backend as nb

ROOT = Path(__file__).resolve().parent.parent
SR = 48000
EXPECTED_IDS = {
    "aw.purest_drive",
    "aw.clip_only2",
    "aw.console7_channel",
    "aw.console7_buss",
    "aw.pressure4",
}

needs_lib = pytest.mark.skipif(not nb.available(), reason=f"native library unavailable: {nb.load_error()}")


def _sine(freq: float = 997.0, amp: float = 0.5, seconds: float = 0.5, sr: int = SR, channels: int = 2) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    cols = [amp * np.sin(2 * np.pi * freq * (1 + 0.1 * c) * t) for c in range(channels)]
    return np.stack(cols, axis=1)


def _noise(amp: float = 0.3, seconds: float = 0.5, sr: int = SR, channels: int = 2, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return amp * rng.standard_normal((int(sr * seconds), channels))


def _processor_ids() -> list[str]:
    return sorted(EXPECTED_IDS)


# --------------------------------------------------------------------------- import safety


def test_import_without_library_does_not_crash(tmp_path):
    missing = tmp_path / "no_such_library.bin"
    env = dict(os.environ, **{nb.ENV_VAR: str(missing)})
    code = (
        "from mankomix.dsp import native_backend as nb;"
        "assert nb.available() is False;"
        "assert nb.load_error();"
        "print('ok')"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "ok"


# --------------------------------------------------------------------------- metadata


@needs_lib
def test_processor_list_json():
    procs = nb.processors()
    ids = [p["id"] for p in procs]
    assert len(ids) == len(set(ids))
    assert EXPECTED_IDS <= set(ids)
    for p in procs:
        assert p["type"] in {"saturator", "clipper", "compressor"}
        assert p["origin"]["license"] == "MIT"
        assert p["origin"]["source"] == "airwindows"
        assert len(p["origin"]["commit"]) == 40
        rt = p["realtime"]
        assert rt["block_ok"] is True
        assert rt["allocates_in_process"] is False
        assert isinstance(rt["latency_samples"], int) and rt["latency_samples"] >= 0
        param_ids = [q["id"] for q in p["params"]]
        assert len(param_ids) == len(set(param_ids))
        for q in p["params"]:
            assert set(q) >= {"id", "unit", "min", "max", "default"}
            assert q["min"] <= q["default"] <= q["max"]


@needs_lib
def test_version_info_has_no_paths():
    info = nb.version_info()
    assert info["backend"] == "native"
    assert info["abi"] == nb.EXPECTED_ABI
    assert info["version"].count(".") == 2
    assert len(info["library_sha256"]) == 64
    assert "/" not in info["library_file"] and "\\" not in info["library_file"]


@needs_lib
@pytest.mark.parametrize("pid", _processor_ids())
def test_defaults_roundtrip_and_latency(pid):
    info = nb.processor_info(pid)
    with nb.NativeProcessor(pid, SR, 2) as proc:
        for q in info["params"]:
            assert proc.get_param(q["id"]) == pytest.approx(q["default"])
        assert proc.latency == info["realtime"]["latency_samples"]


# --------------------------------------------------------------------------- signal sanity


@needs_lib
@pytest.mark.parametrize("pid", _processor_ids())
@pytest.mark.parametrize("signal", ["sine", "noise", "loud_noise", "silence"])
@pytest.mark.parametrize("channels", [1, 2])
def test_output_is_finite(pid, signal, channels):
    x = {
        "sine": _sine(channels=channels),
        "noise": _noise(channels=channels),
        "loud_noise": _noise(amp=4.0, channels=channels),
        "silence": np.zeros((SR // 4, channels)),
    }[signal]
    info = nb.processor_info(pid)
    settings = [{}]
    settings.append({q["id"]: q["min"] for q in info["params"]})
    settings.append({q["id"]: q["max"] for q in info["params"]})
    for params in settings:
        y = nb.process(pid, x, SR, params)
        assert y.shape == x.shape
        assert y.dtype == np.float64
        assert np.all(np.isfinite(y)), params
        assert np.max(np.abs(y)) <= max(4.0, 1.5 * np.max(np.abs(x)))


@needs_lib
def test_mono_1d_input_keeps_shape():
    x = _sine(channels=1)[:, 0]
    y = nb.process("aw.purest_drive", x, SR, {"drive": 0.5})
    assert y.shape == x.shape


@needs_lib
def test_input_array_is_not_modified():
    x = _noise()
    before = x.copy()
    nb.process("aw.pressure4", x, SR, {"pressure": 0.5})
    assert np.array_equal(x, before)


# --------------------------------------------------------------------------- documented behaviour


@needs_lib
@pytest.mark.parametrize("make", [_sine, _noise])
def test_purest_drive_zero_is_transparent(make):
    x = make()
    y = nb.process("aw.purest_drive", x, SR, {"drive": 0.0})
    # Only the original denormal guard may touch exact zeros (< 1e-7).
    assert np.max(np.abs(y - x)) < 1e-6


@needs_lib
def test_purest_drive_adds_odd_harmonics():
    sr = SR
    t = np.arange(sr) / sr
    x = 0.5 * np.sin(2 * np.pi * 1000 * t)
    y = nb.process("aw.purest_drive", x, sr, {"drive": 1.0})
    spec = np.abs(np.fft.rfft(y * np.hanning(sr)))
    third = spec[3000] / spec[1000]
    assert 1e-4 < third < 0.1


@needs_lib
@pytest.mark.parametrize("ceiling_db", [-0.4, -1.0, -6.0, -12.0])
@pytest.mark.parametrize("gain_db", [0.0, 12.0, 24.0])
def test_clipper_output_stays_below_ceiling(ceiling_db, gain_db):
    x = _noise(amp=2.0)
    y = nb.process("aw.clip_only2", x, SR, {"ceiling_db": ceiling_db, "input_gain_db": gain_db})
    ceiling = 10 ** (ceiling_db / 20)
    assert np.max(np.abs(y)) <= ceiling * (1 + 1e-6)


@needs_lib
@pytest.mark.parametrize("sr", [44100, 48000, 96000, 192000])
def test_clipper_below_ceiling_is_one_sample_delay(sr):
    x = _sine(amp=0.5, sr=sr)
    with nb.NativeProcessor("aw.clip_only2", sr, 2) as proc:
        assert proc.latency == 1
        y = proc.process(x)
    assert np.array_equal(y[1:], x[:-1])
    assert np.all(y[0] == 0.0)


@needs_lib
@pytest.mark.parametrize("amp", [0.25, 0.5, 1.0])
def test_console7_pair_is_near_unity(amp):
    x = _sine(freq=1000.0, amp=amp, seconds=1.0)
    y = nb.process("aw.console7_buss", nb.process("aw.console7_channel", x, SR), SR)
    half = len(x) // 2
    rms = lambda v: np.sqrt(np.mean(v[half:] ** 2))  # noqa: E731
    assert abs(20 * np.log10(rms(y) / rms(x))) < 0.25


@needs_lib
@pytest.mark.parametrize("pressure", [0.0, 0.5, 1.0])
def test_pressure4_output_is_bounded(pressure):
    y = nb.process("aw.pressure4", _noise(amp=3.0), SR, {"pressure": pressure})
    assert np.max(np.abs(y)) <= 1.0


@needs_lib
@pytest.mark.parametrize("mewiness", [0.0, -1.0])
def test_pressure4_reduces_crest_factor(mewiness):
    x = _noise(amp=0.3, seconds=1.0)
    half = len(x) // 2  # skip the initial attack from the start-up state
    crest = lambda v: np.max(np.abs(v[half:])) / np.sqrt(np.mean(v[half:] ** 2))  # noqa: E731
    light = nb.process("aw.pressure4", x, SR, {"pressure": 0.0, "mewiness": mewiness})
    heavy = nb.process("aw.pressure4", x, SR, {"pressure": 0.8, "mewiness": mewiness})
    assert crest(heavy) < 0.95 * crest(light)


# --------------------------------------------------------------------------- determinism / realtime claim


@needs_lib
@pytest.mark.parametrize("pid", _processor_ids())
def test_deterministic(pid):
    x = _noise(amp=0.8)
    a = nb.process(pid, x, SR)
    b = nb.process(pid, x, SR)
    assert np.array_equal(a, b)
    with nb.NativeProcessor(pid, SR, 2) as proc:
        first = proc.process(x)
        proc.reset()
        second = proc.process(x)
    assert np.array_equal(first, a)
    assert np.array_equal(second, a)


@needs_lib
@pytest.mark.parametrize("pid", _processor_ids())
@pytest.mark.parametrize("blocks", [1, 64, 511, 512, 4096, [1, 3, 17, 700, 513]])
def test_block_size_independent(pid, blocks):
    x = np.concatenate([_noise(amp=0.8, seconds=0.25), _sine(amp=1.2, seconds=0.25)])
    whole = nb.process(pid, x, SR)
    split = nb.process(pid, x, SR, block_size=blocks)
    assert np.array_equal(whole, split)


@needs_lib
@pytest.mark.parametrize("pid", _processor_ids())
def test_block_size_independent_with_parameter_change(pid):
    info = nb.processor_info(pid)
    change = {q["id"]: q["min"] + 0.37 * (q["max"] - q["min"]) for q in info["params"]}
    x = _noise(amp=0.8, seconds=0.5)
    at = 10007  # parameter change position, deliberately not on any block grid

    def render(block: int) -> np.ndarray:
        planar = np.ascontiguousarray(x.T).copy()
        with nb.NativeProcessor(pid, SR, 2) as proc:
            for lo, hi in ((0, at), (at, planar.shape[1])):
                if lo == at:
                    for k, v in change.items():
                        proc.set_param(k, v)
                for s in range(lo, hi, block):
                    proc.process_planar(planar[:, s:min(s + block, hi)])
        return planar.T

    reference = render(1 << 30)
    for block in (1, 100, 512, 1023):
        assert np.array_equal(render(block), reference), block


# --------------------------------------------------------------------------- API errors


@needs_lib
def test_errors_and_clamping():
    with pytest.raises(nb.NativeBackendError):
        nb.NativeProcessor("no.such_processor", SR, 2)
    with pytest.raises(nb.NativeBackendError):
        nb.NativeProcessor("aw.purest_drive", 1000.0, 2)
    with pytest.raises(ValueError):
        nb.NativeProcessor("aw.purest_drive", SR, 0)
    with nb.NativeProcessor("aw.purest_drive", SR, 2) as proc:
        with pytest.raises(KeyError):
            proc.set_param("no_such_param", 0.5)
        assert proc.set_param("drive", 5.0) is True
        assert proc.get_param("drive") == 1.0
        assert proc.set_param("drive", 0.25) is False
        with pytest.raises(nb.NativeBackendError):
            proc.set_param("drive", float("nan"))
        with pytest.raises(ValueError):
            proc.process(_sine(channels=3))
    with pytest.raises(KeyError):
        nb.process("aw.clip_only2", _sine(), SR, {"drive": 1.0})
