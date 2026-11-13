"""Music-information analysis on synthetic signals (SPEC 6.3, R-11, R-16)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from mankomix.core.analysis.music import analyze_music, detect_sections, note_values_ms

SR = 48000


def _click_track(bpm: float, dur: float = 16.0, sr: int = SR) -> np.ndarray:
    rng = np.random.default_rng(1)
    x = rng.standard_normal(int(dur * sr)) * 1e-4  # faint noise floor, like a real render
    n = int(0.01 * sr)
    burst = rng.standard_normal(n) * np.exp(-np.arange(n) / (0.002 * sr)) * 0.5
    t = 0.5
    while t < dur - 0.1:
        i = int(round(t * sr))
        x[i:i + n] += burst
        t += 60.0 / bpm
    return x


def _arpeggio(notes, dur_note=0.25, reps=64, sr: int = SR) -> np.ndarray:
    t = np.arange(int(dur_note * sr)) / sr
    env = np.exp(-t * 3.0)
    segs = []
    for k in range(reps):
        f = notes[k % len(notes)]
        segs.append((np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)) * env)
    return np.concatenate(segs) * 0.3


def _json_clean(obj) -> None:
    json.dumps(obj, allow_nan=False)


@pytest.mark.parametrize("bpm", [90.0, 120.0, 140.0])
def test_click_track_tempo(bpm):
    r = analyze_music(_click_track(bpm), SR)
    _json_clean(r)
    assert abs(r["bpm"] - bpm) <= 1.0
    assert r["bpm_confidence"] >= 0.5
    assert "bpm" not in r["low_confidence"]
    beats = np.array(r["beats_s"])
    assert beats.size >= 10
    assert abs(np.median(np.diff(beats)) - 60.0 / bpm) < 0.02
    # Beats sit on the clicks (first click at 0.5 s).
    phase = (beats - 0.5) / (60.0 / bpm)
    assert np.all(np.abs(phase - np.round(phase)) * (60.0 / bpm) < 0.03)
    nv = r["note_values"]
    assert nv["1/4"] == pytest.approx(60000.0 / bpm, rel=0.01)
    assert nv["1/8"] == pytest.approx(nv["1/4"] / 2)
    assert nv["1/16"] == pytest.approx(nv["1/4"] / 4)
    assert nv["1/2"] == pytest.approx(nv["1/4"] * 2)
    assert nv["1bar"] == pytest.approx(nv["1/4"] * 4)


def test_a_minor_arpeggio_key_and_tonic():
    r = analyze_music(_arpeggio([220.0, 261.63, 329.63]), SR)
    _json_clean(r)
    assert r["key"] == "A minor"
    assert r["key_confidence"] >= 0.5
    assert r["tonic_hz"] == pytest.approx(27.5, rel=0.01)  # lowest A >= 20 Hz
    assert r["tonic_octave_above_hz"] == pytest.approx(55.0, rel=0.01)
    assert 20.0 <= r["tonic_bass_hz"] < 200.0
    assert isinstance(r["tonic_in_sub_band"], bool)
    assert isinstance(r["small_speaker_loss"], bool)
    assert abs(r["tuning_cents"]) < 10.0


def test_c_major_arpeggio():
    r = analyze_music(_arpeggio([261.63, 329.63, 392.0]), SR)
    assert r["key"] == "C major"
    assert r["tonic_hz"] == pytest.approx(32.70, rel=0.01)


def test_tonic_bass_octave_from_bass_note():
    # A minor with a sustained A1 (55 Hz) bass: tonic sits in the sub band.
    x = _arpeggio([220.0, 261.63, 329.63])
    t = np.arange(x.size) / SR
    x = x + 0.2 * np.sin(2 * np.pi * 55.0 * t)
    r = analyze_music(x, SR)
    assert r["key"] == "A minor"
    assert r["tonic_bass_hz"] == pytest.approx(55.0, rel=0.01)
    assert r["tonic_bass_source"] == "spectral_peak"
    assert r["tonic_in_sub_band"] is True
    assert r["small_speaker_loss"] is True


def test_sections_quiet_loud_quiet():
    rng = np.random.default_rng(0)
    env = np.concatenate([np.full(SR * 4, 0.1), np.full(SR * 4, 1.0), np.full(SR * 4, 0.1)])
    x = rng.standard_normal((SR * 12, 2)) * 0.1 * env[:, None]
    secs = detect_sections(x, SR)
    _json_clean(secs)
    assert [s["label"] for s in secs] == ["quiet", "loud", "quiet"]
    assert abs(secs[1]["start_s"] - 4.0) < 1.0
    assert abs(secs[1]["end_s"] - 8.0) < 1.0
    assert secs[0]["start_s"] == 0.0 and secs[-1]["end_s"] == pytest.approx(12.0)
    assert secs[1]["short_term_lufs_mean"] > secs[0]["short_term_lufs_mean"] + 6.0
    for s in secs:
        assert set(s) == {"start_s", "end_s", "label", "short_term_lufs_mean"}


def test_steady_signal_is_one_mid_section():
    rng = np.random.default_rng(2)
    secs = detect_sections(rng.standard_normal(SR * 12) * 0.1, SR)
    assert len(secs) == 1 and secs[0]["label"] == "mid"


def test_noise_reports_low_tempo_confidence():
    rng = np.random.default_rng(3)
    r = analyze_music(rng.standard_normal(SR * 12) * 0.1, SR)
    _json_clean(r)
    assert r["bpm_confidence"] < 0.5
    assert "bpm" in r["low_confidence"]


@pytest.mark.parametrize("x", [np.zeros(SR * 2), np.zeros((SR // 2, 2)), np.zeros(100)])
def test_silence_and_short_inputs_do_not_crash(x):
    r = analyze_music(x, SR)
    _json_clean(r)
    assert r["bpm_confidence"] == 0.0
    assert r["key_confidence"] == 0.0


def test_note_values_none_without_tempo():
    assert note_values_ms(None) is None
    assert note_values_ms(60.0)["1/4"] == pytest.approx(1000.0)


def test_other_sample_rate():
    sr = 44100
    t = np.arange(sr * 12) / sr
    x = np.zeros(t.size)
    n = int(0.01 * sr)
    burst = np.random.default_rng(4).standard_normal(n) * np.exp(-np.arange(n) / (0.002 * sr))
    for k in range(int(11.5 * 2)):
        i = int(round((0.25 + k * 0.5) * sr))
        x[i:i + n] += burst
    r = analyze_music(x + 1e-4 * np.random.default_rng(5).standard_normal(t.size), sr)
    assert abs(r["bpm"] - 120.0) <= 1.0
