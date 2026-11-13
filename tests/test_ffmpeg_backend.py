"""ffmpeg backend: build detection, encoder discovery, codec round trip (SPEC 13.3, S-02)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mankomix.dsp import ffmpeg_backend as fb
from mankomix.dsp.reference import true_peak_dbtp

SR = 48000

FAKE_VERSION = """ffmpeg version 7.1-test Copyright (c) 2000-2024 the FFmpeg developers
built with gcc 14
configuration: --enable-shared --enable-libopus --enable-libvorbis --enable-libmp3lame
libavutil      59. 39.100 / 59. 39.100
"""

FAKE_ENCODERS = """Encoders:
 V..... = Video
 A..... = Audio
 ------
 V....D mpeg4                MPEG-4 part 2
 A....D aac                  AAC (Advanced Audio Coding)
 A....D libopus              libopus Opus (codec opus)
 A..X.D vorbis               Vorbis
"""


def test_build_classification_from_fake_configuration():
    assert fb.classify_build("--enable-shared --enable-libopus") == "lgpl"
    assert fb.classify_build("--enable-gpl --enable-version3 --enable-librubberband") == "gpl"
    assert fb.classify_build("--enable-gpl --enable-nonfree --enable-libfdk-aac") == "nonfree"
    vi = fb.parse_version_output(FAKE_VERSION)
    assert vi["version"] == "7.1-test" and vi["build"] == "lgpl" and not vi["version3"]
    vi = fb.parse_version_output(FAKE_VERSION.replace("--enable-shared", "--enable-gpl --enable-librubberband"))
    assert vi["build"] == "gpl" and "--enable-librubberband" in vi["gpl_only_components"]


def test_encoder_parsing_and_pick():
    enc = fb.parse_encoders_output(FAKE_ENCODERS)
    assert enc == {"mpeg4", "aac", "libopus", "vorbis"}
    assert fb.pick_encoder("aac", enc) == "aac"
    assert fb.pick_encoder("opus", enc) == "libopus"
    assert fb.pick_encoder("ogg_vorbis", enc) == "vorbis"          # native fallback
    assert fb.pick_encoder("mp3", enc) is None
    with pytest.raises(ValueError):
        fb.pick_encoder("wma", enc)


def test_missing_encoder_returns_none(monkeypatch):
    monkeypatch.setattr(fb, "encoders", lambda: set())
    x = np.zeros((SR // 10, 2))
    assert fb.encode_decode_roundtrip(x, SR, "aac", "256k") is None
    assert fb.encode_decode_roundtrip(x, SR, "mp3", 320000) is None


def test_estimate_delay_on_synthetic_shift():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((SR, 2)) * 0.1
    d = np.concatenate([np.zeros((1105, 2)), x])[: SR + 2000]
    assert fb.estimate_delay(x, d, SR) == 1105
    aligned = fb._align(d, 1105, SR)
    assert np.array_equal(aligned, x)


def _program(seconds=2.0):
    rng = np.random.default_rng(3)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    x = 0.2 * np.sin(2 * math.pi * 220 * t)[:, None] + 0.1 * np.sin(2 * math.pi * 3300 * t)[:, None]
    env = np.zeros(n)
    for s in range(2000, n - 4000, 9000):
        env[s:s + 3000] = np.exp(-np.arange(3000) / 500.0)
    x = x + 0.4 * env[:, None] * rng.standard_normal((n, 2))
    return x * 0.8


@pytest.mark.ffmpeg
def test_version_info_and_encoders_from_real_ffmpeg():
    vi = fb.version_info()
    assert vi is not None and vi["build"] in ("lgpl", "gpl", "nonfree") and vi["version"]
    assert "aac" in fb.encoders()


@pytest.mark.ffmpeg
@pytest.mark.parametrize("codec,bitrate", [("aac", "256k"), ("mp3", "320k"), ("opus", "160k"),
                                           ("ogg_vorbis", "320k")])
def test_roundtrip_returns_aligned_audio(codec, bitrate):
    x = _program()
    out = fb.encode_decode_roundtrip(x, SR, codec, bitrate, return_info=True)
    if out is None:
        pytest.skip(f"encoder for {codec} not available in this ffmpeg build")
    y, sr, info = out
    assert sr == SR and y.shape == x.shape and y.dtype == np.float64
    assert np.all(np.isfinite(y))
    # aligned: no residual lag, and the waveforms match closely
    assert fb.estimate_delay(x, y, SR) == 0
    r = np.corrcoef(x[:, 0], y[:, 0])[0, 1]
    assert r > 0.98, (codec, info)
    tp = true_peak_dbtp(y, SR)           # S-02: measured after the codec
    assert math.isfinite(tp) and abs(tp - true_peak_dbtp(x, SR)) < 3.0
    assert info["encoder"] in fb.CODECS[codec]["encoders"]


@pytest.mark.ffmpeg
def test_ffmpeg_resample_matches_reference():
    from mankomix.dsp.reference.export import resample_poly_hq

    t = np.arange(SR) / SR
    x = np.stack([0.5 * np.sin(2 * math.pi * 1000 * t)] * 2, axis=1)
    y = fb.resample(x, SR, 44100)
    ref = resample_poly_hq(x, SR, 44100)
    assert y.shape == ref.shape
    mid = slice(2000, -2000)
    assert np.max(np.abs(y[mid] - ref[mid])) < 1e-3
