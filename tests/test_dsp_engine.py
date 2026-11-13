"""DSP engine: S-05, S-06, S-09, stage rules, export module, determinism (SPEC 5.3, 6.6.2, 9.6)."""

from __future__ import annotations

import math
import struct

import numpy as np
import pytest
import soundfile as sf
from scipy import signal

from mankomix.dsp import engine, reference
from mankomix.dsp.errors import ChainError, NumericError

SR = 48000


def _sig(seconds=0.5, sr=SR, seed=0, amp=0.3):
    rng = np.random.default_rng(seed)
    n = int(sr * seconds)
    t = np.arange(n) / sr
    x = amp * np.sin(2 * math.pi * 440 * t)[:, None] + 0.05 * rng.standard_normal((n, 2))
    return x


def _tag(path) -> int:
    with open(path, "rb") as f:
        data = f.read(4096)
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    i = 12
    while i < len(data):
        cid, size = data[i:i + 4], struct.unpack("<I", data[i + 4:i + 8])[0]
        if cid == b"fmt ":
            return struct.unpack("<H", data[i + 8:i + 10])[0]
        i += 8 + size + (size & 1)
    raise AssertionError("no fmt chunk")


# --------------------------------------------------------------------------- S-06

GOOD_MASTER = [
    {"id": "eq", "type": "eq", "params": {"freq_hz": 250.0, "gain_db": -1.0}},
    {"id": "hpf", "type": "filter", "params": {"kind": "hpf", "freq_hz": 25.0}},
    {"id": "comp", "type": "compressor", "params": {"threshold_db": -20.0, "ratio": 1.5}},
    {"id": "sat", "type": "saturator", "params": {"drive_db": 3.0, "mix": 0.3}},
    {"id": "st", "type": "stereo", "params": {"mono_below_hz": 120.0}},
    {"id": "trim", "type": "gain", "params": {"gain_db": -0.5}},
    {"id": "clip", "type": "clipper", "params": {"ceiling_db": -0.5}},
    {"id": "drive", "type": "loudness_gain", "params": {"gain_db": 3.0}},
    {"id": "lim", "type": "limiter", "params": {"ceiling_dbtp": -1.0}},
]


def test_master_chain_in_fixed_order_renders_and_records_backends():
    x = _sig()
    res = engine.render_chain(x, SR, GOOD_MASTER, stage="master")
    assert [s["id"] for s in res.steps] == [s["id"] for s in GOOD_MASTER]
    assert all(s["backend"] == "reference" for s in res.steps)
    assert all({"id", "type", "backend", "params", "stats", "in_peak", "out_peak"} <= set(s) for s in res.steps)
    assert "reference" in res.backends and res.audio.dtype == np.float64
    assert res.audio.shape == x.shape
    assert reference.true_peak_dbtp(res.audio, SR) <= -1.0 + 0.05
    assert res.to_dict()["steps"][0]["params"]["bw_oct"] == 1.0


@pytest.mark.parametrize("chain", [
    [{"type": "limiter"}, {"type": "eq"}],                              # limiter not last
    [{"type": "limiter"}, {"type": "gain"}],                            # nothing after the limiter
    [{"type": "compressor"}, {"type": "eq"}],                           # dynamics before EQ
    [{"type": "stereo"}, {"type": "saturator"}],                        # enhance after stereo
    [{"type": "clipper"}, {"type": "compressor"}, {"type": "limiter"}],
    [{"type": "limiter"}, {"type": "limiter"}],
])
def test_s06_order_violations_raise(chain):
    with pytest.raises(ValueError, match="S-06") as ei:
        engine.render_chain(_sig(0.05), SR, chain, stage="master")
    assert ei.value.rule == "S-06"


def test_stage_rules():
    x = _sig(0.05)
    with pytest.raises(ChainError, match="S-06"):
        engine.render_chain(x, SR, [{"type": "limiter"}], stage="track")
    for t in ("dither", "resample"):
        with pytest.raises(ChainError) as ei:
            engine.validate_chain([{"type": t}], "master")
        assert ei.value.rule == "stage"
    with pytest.raises(ChainError):
        engine.validate_chain([{"type": "eq"}], "export")
    with pytest.raises(ChainError):
        engine.validate_chain([{"type": "reverb"}], "track")             # declared only
    with pytest.raises(ValueError):
        engine.validate_chain([{"type": "eq", "params": {"q": 1}}], "track")
    with pytest.raises(ValueError):
        engine.validate_chain([{"type": "eq", "id": "a"}, {"type": "eq", "id": "a"}], "track")
    engine.validate_chain([{"type": "pan"}, {"type": "eq"}, {"type": "compressor"}], "track")


def test_bypassed_steps_are_recorded_but_not_run():
    x = _sig(0.05)
    res = engine.render_chain(x, SR, [{"type": "gain", "params": {"gain_db": -6.0}, "bypass": True}],
                              stage="master")
    assert np.array_equal(res.audio, x) and res.steps[0]["bypass"] is True


# --------------------------------------------------------------------------- S-05

def test_s05_nothing_after_dither_in_chain():
    with pytest.raises(ChainError, match="S-05"):
        engine.render_chain(_sig(0.05), SR, [{"type": "dither"}, {"type": "resample"}], stage="export")
    with pytest.raises(ChainError, match="S-05"):
        engine.render_chain(_sig(0.05), SR, [{"type": "dither"}, {"type": "loudness_gain"}], stage="export")


def test_s05_dithered_audio_refuses_further_processing(tmp_path):
    res = engine.render_chain(_sig(0.05), SR, [{"type": "dither", "params": {"bit_depth": 16}}],
                              stage="export", seed=1)
    assert res.dithered and isinstance(res.audio, engine.DitheredAudio)
    with pytest.raises(ChainError, match="S-05"):
        engine.render_chain(res.audio, SR, [{"type": "gain"}], stage="master")
    with pytest.raises(ChainError, match="S-05"):
        engine.export_audio(res.audio, SR, "distributor_44k16", tmp_path / "x.wav", seed=1)
    # quantised to the 16-bit grid
    k = np.asarray(res.audio) * 32768.0
    assert np.array_equal(k, np.rint(k))


def test_dither_applied_once_only_when_depth_decreases(tmp_path):
    x = _sig(0.3)
    rec = engine.export_audio(x, SR, "distributor_44k16", tmp_path / "d16.wav", seed=11)
    assert rec["dithered"] is True and rec["bit_depth"] == 16
    assert [s["type"] for s in rec["steps"]].count("dither") == 1
    assert rec["steps"][-1]["type"] == "dither"
    assert rec["dither"] == {"type": "tpdf", "seed": 11, "bit_depth": 16, "noise_shaping": "none",
                             "rng": "numpy.PCG64"}
    rec = engine.export_audio(x, SR, "archive_f32", tmp_path / "a.wav", seed=11)
    assert rec["dithered"] is False and rec["dither"] is None and rec["resampled_from"] is None
    assert not any(s["type"] == "dither" for s in rec["steps"])
    data, sr = sf.read(str(tmp_path / "a.wav"), dtype="float64")
    assert sr == SR and np.allclose(data, x.astype(np.float32))
    # an explicit dither="none" override is recorded, with a warning, no dither
    rec = engine.export_audio(x, SR, "hires_native", tmp_path / "h.flac", seed=11, dither="none")
    assert rec["dithered"] is False and rec["quantization"] == "round" and rec["warnings"]
    # hires_native declares TPDF: 32f -> 24 bit reduces word length (S-05)
    rec = engine.export_audio(x, SR, "hires_native", tmp_path / "h.wav", seed=11)
    assert rec["dithered"] is True and rec["bit_depth"] == 24


def test_dither_determinism_same_seed_same_bytes(tmp_path):
    x = _sig(0.3)
    a = engine.export_audio(x, SR, "cd_redbook", tmp_path / "a.wav", seed=123)
    b = engine.export_audio(x, SR, "cd_redbook", tmp_path / "b.wav", seed=123)
    c = engine.export_audio(x, SR, "cd_redbook", tmp_path / "c.wav", seed=124)
    ba, bb, bc = ((tmp_path / n).read_bytes() for n in ("a.wav", "b.wav", "c.wav"))
    assert ba == bb
    assert ba != bc
    ia, _ = sf.read(str(tmp_path / "a.wav"), dtype="int16")
    ic, _ = sf.read(str(tmp_path / "c.wav"), dtype="int16")
    diff = np.abs(ia.astype(int) - ic.astype(int))
    assert diff.max() <= 2 and np.count_nonzero(diff) > 0.1 * diff.size   # only the LSBs differ
    assert a["file"] == "a.wav" and "/" not in a["file"] and "\\" not in a["file"]
    assert engine.seed_from_hash("sha256:" + "ab" * 32) == engine.seed_from_hash("sha256:" + "ab" * 32)


def test_tpdf_dither_statistics():
    x = np.zeros((200000, 1)) + 0.25 / 32768      # quarter LSB DC
    res = engine.render_chain(x, SR, [{"type": "dither", "params": {"bit_depth": 16}}], stage="export", seed=3)
    k = np.asarray(res.audio)[:, 0] * 32768
    assert set(np.unique(k)) <= {-1.0, 0.0, 1.0, 2.0}
    assert abs(k.mean() - 0.25) < 0.01            # dither linearises: the mean survives
    assert res.steps[0]["stats"]["noise_shaping"] == "none"


# --------------------------------------------------------------------------- formats

@pytest.mark.parametrize("fmt,depth", [("distributor_44k16", 16), ("hires_native", 24)])
def test_pcm_wav_is_wave_format_pcm(tmp_path, fmt, depth):
    path = tmp_path / "out.wav"
    rec = engine.export_audio(_sig(0.2), SR, fmt, path, seed=5)
    assert _tag(path) == 1
    assert rec["wav_format_tag"] == "WAVE_FORMAT_PCM"
    info = sf.info(str(path))
    assert info.subtype == f"PCM_{depth}"


def test_resample_48k_to_44k1_length_and_frequency(tmp_path):
    n = SR  # 1 s
    t = np.arange(n) / SR
    x = np.stack([0.5 * np.sin(2 * math.pi * 1000 * t), 0.5 * np.sin(2 * math.pi * 23000 * t)], axis=1)
    res = engine.render_chain(x, SR, [{"type": "resample", "params": {"target_sr": 44100}}], stage="export")
    y = res.audio
    assert res.sr == 44100 and y.shape[0] == -(-n * 147 // 160)
    assert res.steps[0]["stats"]["ratio"] == "147/160"
    seg = y[4410:-4410, 0]
    spec = np.abs(np.fft.rfft(seg * signal.windows.blackmanharris(len(seg))))
    f_peak = np.argmax(spec) * 44100 / len(seg)
    assert abs(f_peak - 1000.0) < 2.0
    assert abs(20 * math.log10(np.sqrt(2) * np.std(seg) / 0.5)) < 0.01
    # 23 kHz is above the new Nyquist: must be removed, not aliased
    assert 20 * math.log10(np.max(np.abs(y[4410:-4410, 1])) / 0.5) < -100
    # via the export module
    rec = engine.export_audio(x, SR, "distributor_44k16", tmp_path / "r.wav", seed=1)
    assert rec["sample_rate"] == 44100 and rec["resampled_from"] == SR
    assert rec["resample_backend"] == "reference" and rec["frames"] == y.shape[0]


def test_export_container_and_rate_selection(tmp_path):
    x = _sig(0.1)
    with pytest.raises(ValueError):
        engine.export_audio(x, SR, "distributor_44k16", tmp_path / "x.flac", seed=0)
    rec = engine.export_audio(x, SR, "dj_wav", tmp_path / "x.aiff", seed=0)
    assert rec["sample_rate"] == SR and rec["container"] == "aiff"
    rec = engine.export_audio(x, 96000, "dj_wav", tmp_path / "y.wav", seed=0)
    assert rec["sample_rate"] == 44100
    mono = x[:, :1]
    rec = engine.export_audio(mono, SR, "distributor_44k16", tmp_path / "m.wav", seed=0)
    assert rec["channels"] == 2


# --------------------------------------------------------------------------- S-09

def test_nan_input_and_nan_step_raise(monkeypatch):
    x = _sig(0.05)
    x[10, 0] = np.nan
    with pytest.raises(NumericError, match="S-09"):
        engine.render_chain(x, SR, [{"type": "gain"}], stage="track")

    def bad(x, sr, p, **_):
        y = x.copy()
        y[5, 1] = np.inf
        return y, sr, {}
    monkeypatch.setitem(reference.IMPLEMENTATIONS, "gain", bad)
    with pytest.raises(NumericError, match="S-09") as ei:
        engine.render_chain(_sig(0.05), SR, [{"id": "g1", "type": "gain"}], stage="track")
    assert ei.value.step == "g1"


def test_length_change_is_rejected(monkeypatch):
    def short(x, sr, p, **_):
        return x[:-1], sr, {}
    monkeypatch.setitem(reference.IMPLEMENTATIONS, "gain", short)
    with pytest.raises(NumericError, match="S-09"):
        engine.render_chain(_sig(0.05), SR, [{"type": "gain"}], stage="track")


def test_render_is_deterministic():
    x = _sig(0.3, seed=9)
    a = engine.render_chain(x, SR, GOOD_MASTER, stage="master")
    b = engine.render_chain(x, SR, GOOD_MASTER, stage="master")
    assert np.array_equal(a.audio, b.audio)


@pytest.mark.ffmpeg
def test_ffmpeg_resample_backend_is_recorded():
    x = _sig(0.2)
    res = engine.render_chain(x, SR, [{"type": "resample", "params": {"target_sr": 44100}}], stage="export",
                              backend_preference=("ffmpeg", "reference"))
    assert res.steps[0]["backend"] == "ffmpeg"
    assert res.backends["ffmpeg"]["build"] in ("lgpl", "gpl", "nonfree")
    assert res.audio.shape[0] == -(-x.shape[0] * 147 // 160)
