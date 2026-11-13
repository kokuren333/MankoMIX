"""Sanity tests for the synthetic test-signal library (tests/fixtures/synth.py)."""

from __future__ import annotations

import math

import numpy as np
import pytest
import soundfile as sf
from scipy import signal

from tests.fixtures import synth

SR = 48000


def band_energy(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    """Energy of ``x`` (all channels) between ``lo`` and ``hi`` Hz.

    Hann-windowed FFT, so that abrupt segment edges do not leak energy.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    spec = np.abs(np.fft.rfft(x * np.hanning(x.shape[0])[:, None], axis=0)) ** 2
    f = np.fft.rfftfreq(x.shape[0], d=1.0 / sr)
    m = (f >= lo) & (f < hi)
    return float(spec[m].sum())


def band_fraction(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    return band_energy(x, sr, lo, hi) / band_energy(x, sr, 0.0, sr)


def db(ratio: float) -> float:
    return 10.0 * math.log10(max(ratio, 1e-300))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gen", [synth.white_noise, synth.pink_noise])
def test_noise_is_deterministic_by_seed(gen):
    a = gen(-20.0, sr=SR, seconds=0.5, seed=7, channels=2)
    b = gen(-20.0, sr=SR, seconds=0.5, seed=7, channels=2)
    c = gen(-20.0, sr=SR, seconds=0.5, seed=8, channels=2)
    assert a.tobytes() == b.tobytes()
    assert not np.array_equal(a, c)


def test_song_stems_are_bit_identical_across_calls(song_stems):
    again = synth.song_stems(sr=SR, seconds=synth.SONG_SECONDS, seed=0)
    assert list(again) == list(song_stems)
    for role in song_stems:
        assert again[role].tobytes() == song_stems[role].tobytes(), role
    other = synth.song_stems(sr=SR, seconds=2.0, seed=1)
    short = synth.song_stems(sr=SR, seconds=2.0, seed=0)
    assert not np.array_equal(other["drums"], short["drums"])


def test_defect_injectors_are_deterministic(song_mix):
    a = synth.add_shimmer(song_mix, SR, depth_db=-20.0, seed=3)
    b = synth.add_shimmer(song_mix, SR, depth_db=-20.0, seed=3)
    assert a.tobytes() == b.tobytes()


# ---------------------------------------------------------------------------
# Basic signals and levels
# ---------------------------------------------------------------------------


def test_level_helpers_round_trip():
    assert synth.db_to_amp(-6.0) == pytest.approx(0.501187, rel=1e-5)
    assert synth.amp_to_db(synth.db_to_amp(-37.5)) == pytest.approx(-37.5)
    assert synth.amp_to_db(0.0) == -400.0


def test_sine_levels_and_shape():
    x = synth.sine(1000.0, -12.0, sr=SR, seconds=1.0, channels=2)
    assert x.shape == (SR, 2) and x.dtype == np.float64
    assert synth.peak_dbfs(x) == pytest.approx(-12.0, abs=0.1)
    assert synth.rms_dbfs(x) == pytest.approx(-12.0 - 3.0103, abs=0.1)


def test_sine_phase():
    x = synth.sine(1000.0, 0.0, math.pi / 2.0, sr=SR, seconds=0.01)
    assert x[0, 0] == pytest.approx(1.0)


@pytest.mark.parametrize("gen", [synth.white_noise, synth.pink_noise])
def test_noise_rms_is_exact(gen):
    x = gen(-23.0, sr=SR, seconds=1.0, seed=0, channels=2)
    assert x.shape == (SR, 2)
    for c in range(2):
        assert synth.rms_dbfs(x[:, c]) == pytest.approx(-23.0, abs=0.1)
    assert abs(float(np.corrcoef(x[:, 0], x[:, 1])[0, 1])) < 0.05


def test_pink_noise_has_equal_energy_per_octave():
    x = synth.pink_noise(-20.0, sr=SR, seconds=4.0, seed=2)
    octaves = [db(band_energy(x, SR, f, 2 * f)) for f in (100.0, 400.0, 1600.0, 6400.0)]
    assert max(octaves) - min(octaves) < 1.5
    white = synth.white_noise(-20.0, sr=SR, seconds=4.0, seed=2)
    # White noise gains ~3 dB per octave; across 6 octaves that is ~18 dB.
    assert db(band_energy(white, SR, 6400.0, 12800.0) / band_energy(white, SR, 100.0, 200.0)) > 15.0


def test_impulse_and_silence():
    x = synth.impulse(0.25, -6.0, sr=SR, seconds=0.5, channels=2)
    idx = np.flatnonzero(x[:, 0])
    assert idx.tolist() == [SR // 4]
    assert synth.peak_dbfs(x) == pytest.approx(-6.0, abs=0.1)
    s = synth.silence(sr=SR, seconds=0.5, channels=2)
    assert s.shape == (SR // 2, 2) and not s.any()


def test_sweep_runs_from_f0_to_f1():
    x = synth.sweep(100.0, 10000.0, -6.0, sr=SR, seconds=2.0)[:, 0]
    assert synth.peak_dbfs(x) == pytest.approx(-6.0, abs=0.1)
    win = SR // 20
    for seg, expected in ((x[:win], 100.0), (x[-win:], 10000.0)):
        spec = np.abs(np.fft.rfft(seg * np.hanning(win), n=8 * win))
        f_peak = np.fft.rfftfreq(8 * win, 1.0 / SR)[int(np.argmax(spec))]
        # The frequency moves during the window; allow one window's worth of travel.
        assert expected / 1.4 < f_peak < expected * 1.4


def test_ebu_tone_sequence_levels():
    x = synth.ebu_tone_sequence([-20.0, -30.0, -20.0], [0.5, 1.0, 0.5], sr=SR)
    assert x.shape == (2 * SR, 2)
    segs = [x[: SR // 2], x[SR // 2: 3 * SR // 2], x[3 * SR // 2:]]
    for seg, level in zip(segs, (-20.0, -30.0, -20.0)):
        assert synth.peak_dbfs(seg) == pytest.approx(level, abs=0.1)
        assert synth.rms_dbfs(seg) == pytest.approx(level - 3.0103, abs=0.1)
    with pytest.raises(ValueError):
        synth.ebu_tone_sequence([-20.0], [1.0, 2.0])


def test_intersample_peak_signal_overshoots_by_3db():
    x = synth.intersample_peak_signal(-1.0, sr=SR, seconds=0.5)
    assert synth.peak_dbfs(x) == pytest.approx(-1.0, abs=0.1)
    up = signal.resample_poly(x, 8, 1, axis=0)
    core = up[len(up) // 4: 3 * len(up) // 4]  # avoid resampler edge effects
    true_peak = synth.peak_dbfs(core)
    assert true_peak == pytest.approx(-1.0 + synth.INTERSAMPLE_OVERSHOOT_DB, abs=0.1)
    assert true_peak > 1.9 + synth.peak_dbfs(x)


# ---------------------------------------------------------------------------
# AI-defect injectors
# ---------------------------------------------------------------------------


def test_hf_ceiling_removes_energy_above_cutoff():
    x = synth.white_noise(-20.0, sr=SR, seconds=2.0, seed=1, channels=2)
    y = synth.add_hf_ceiling(x, SR, cutoff_hz=16000.0)
    assert y.shape == x.shape
    above_before = band_energy(x, SR, 16000.0, SR / 2)
    above_after = band_energy(y, SR, 16000.0, SR / 2)
    assert db(above_after / above_before) < -40.0
    passband = db(band_energy(y, SR, 100.0, 14000.0) / band_energy(x, SR, 100.0, 14000.0))
    assert abs(passband) < 0.5


def test_shimmer_adds_energy_only_in_its_band():
    x = synth.pink_noise(-20.0, sr=SR, seconds=2.0, seed=4, channels=2)
    y = synth.add_shimmer(x, SR, band=(10000.0, 14000.0), depth_db=-20.0, seed=5)
    added = y - x
    in_band = band_energy(added, SR, 10000.0, 14000.0)
    out_band = band_energy(added, SR, 0.0, 9800.0) + band_energy(added, SR, 14200.0, SR / 2)
    assert db(out_band / in_band) < -40.0
    assert synth.rms_dbfs(added) - synth.rms_dbfs(x) == pytest.approx(-20.0, abs=0.1)
    # Pink noise has ~ -13.6 dB of its energy in 10-14 kHz, so -20 dB of shimmer
    # raises that band by roughly 20 % (independent noise: energies add).
    before, after = band_energy(x, SR, 10000.0, 14000.0), band_energy(y, SR, 10000.0, 14000.0)
    assert after == pytest.approx(before + in_band, rel=0.05)
    assert after > 1.1 * before


def test_shimmer_is_signal_correlated_and_modulated():
    tone = synth.pink_noise(-20.0, sr=SR, seconds=2.0, seed=6, channels=2)
    tone[SR:] = 0.0  # second half is silent
    added = synth.add_shimmer(tone, SR, depth_db=-20.0, seed=7) - tone
    first, second = added[: SR - 2000], added[SR + 2000:]
    assert synth.rms_dbfs(second) < synth.rms_dbfs(first) - 60.0
    # Short-term level of the shimmer moves by many dB (tremolo), not stationary.
    frames = first[: (len(first) // 480) * 480, 0].reshape(-1, 480)
    levels = 10.0 * np.log10(np.mean(frames ** 2, axis=1) + 1e-20)
    assert np.percentile(levels, 90) - np.percentile(levels, 10) > 6.0


def test_head_click():
    x = synth.silence(sr=SR, seconds=0.5, channels=2)
    y = synth.add_head_click(x, SR, dbfs=-6.0)
    assert synth.peak_dbfs(y[:10]) == pytest.approx(-6.0, abs=0.1)
    assert not y[SR // 100:].any()
    later = synth.add_head_click(x, SR, at_s=0.1, dbfs=-12.0)
    assert not later[: SR // 10].any()
    assert synth.peak_dbfs(later) == pytest.approx(-12.0, abs=0.1)


def test_noise_floor_level():
    x = synth.silence(sr=SR, seconds=1.0, channels=2)
    y = synth.add_noise_floor(x, SR, dbfs=-70.0, seed=1)
    assert synth.rms_dbfs(y) == pytest.approx(-70.0, abs=0.1)
    yp = synth.add_noise_floor(x, SR, dbfs=-70.0, seed=1, color="pink")
    assert synth.rms_dbfs(yp) == pytest.approx(-70.0, abs=0.1)


def test_lowmid_buildup_boosts_250_to_500_hz():
    lo = synth.sine(350.0, -20.0, sr=SR, seconds=1.0)
    hi = synth.sine(5000.0, -20.0, sr=SR, seconds=1.0)
    gain_lo = synth.rms_dbfs(synth.add_lowmid_buildup(lo, SR, gain_db=6.0)[SR // 2:]) - synth.rms_dbfs(lo)
    gain_hi = synth.rms_dbfs(synth.add_lowmid_buildup(hi, SR, gain_db=6.0)[SR // 2:]) - synth.rms_dbfs(hi)
    assert gain_lo == pytest.approx(6.0, abs=0.3)
    assert abs(gain_hi) < 0.3


def test_make_overlimited_crushes_crest_factor(song_mix):
    y = synth.make_overlimited(song_mix, SR)
    crest_before = synth.peak_dbfs(song_mix) - synth.rms_dbfs(song_mix)
    crest_after = synth.peak_dbfs(y) - synth.rms_dbfs(y)
    assert synth.peak_dbfs(y) <= -0.1 + 1e-9
    assert crest_after < 6.0 < crest_before
    assert np.mean(np.abs(y) >= synth.db_to_amp(-0.1) - 1e-12) > 0.01  # flat tops


def test_dc_and_nan_injection():
    x = synth.sine(1000.0, -20.0, sr=SR, seconds=1.0, channels=2)
    assert np.mean(synth.add_dc(x, 0.02), axis=0) == pytest.approx([0.02, 0.02], abs=1e-6)
    y = synth.inject_nan(x, positions=(5, 100), channel=1)
    assert np.isnan(y).sum() == 2 and np.isnan(y[5, 1]) and not np.isnan(x).any()
    z = synth.inject_nan(x, positions=(7,), value=float("inf"))
    assert np.isinf(z[7, 0])


def test_antiphase_low_inverts_only_the_low_band():
    mono = synth.pink_noise(-20.0, sr=SR, seconds=2.0, seed=9)
    y = synth.antiphase_low(mono, SR, below_hz=120.0)
    assert y.shape == (2 * SR, 2)
    np.testing.assert_array_equal(y[:, 0], mono[:, 0])
    lp = signal.butter(4, 60.0, "lowpass", fs=SR, output="sos")
    hp = signal.butter(4, 1000.0, "highpass", fs=SR, output="sos")
    low = signal.sosfiltfilt(lp, y, axis=0)
    high = signal.sosfiltfilt(hp, y, axis=0)
    assert np.corrcoef(low[:, 0], low[:, 1])[0, 1] < -0.9
    assert np.corrcoef(high[:, 0], high[:, 1])[0, 1] > 0.99


# ---------------------------------------------------------------------------
# The synthetic song
# ---------------------------------------------------------------------------


def test_song_stems_layout(song_stems, song_mix):
    assert tuple(song_stems) == synth.SONG_ROLES
    n = synth.frames_for(SR, synth.SONG_SECONDS)
    for role, x in song_stems.items():
        assert x.shape == (n, 2), role
        assert x.dtype == np.float64
        assert np.isfinite(x).all()
        assert synth.peak_dbfs(x) < -6.0, role
        assert synth.rms_dbfs(x) > -70.0, role
        assert not x.flags.writeable  # session fixture is frozen
    assert synth.peak_dbfs(song_mix) == pytest.approx(-6.0, abs=0.01)


def test_kick_and_bass_live_below_250_hz(song_stems):
    kick = synth.kick(sr=SR, seconds=4.0)
    assert band_fraction(kick, SR, 0.0, 250.0) > 0.9
    for x in (synth.bass_line(sr=SR, seconds=4.0), song_stems["bass"]):
        assert band_fraction(x, SR, 0.0, 250.0) > 0.9
        assert band_fraction(x, SR, 50.0, 110.0) > 0.5  # fundamentals 55-98 Hz
    assert band_fraction(song_stems["drums"], SR, 0.0, 250.0) > 0.8


def test_kick_fundamental_is_tonic():
    x = synth.kick(sr=SR, seconds=2.0, beats=(0.0,))[:, 0]
    tail = x[int(0.08 * SR): int(0.35 * SR)]
    spec = np.abs(np.fft.rfft(tail, n=SR))
    f_peak = np.fft.rfftfreq(SR, 1.0 / SR)[int(np.argmax(spec))]
    assert f_peak == pytest.approx(55.0, abs=3.0)


def test_vocals_live_in_200_hz_to_5_khz(song_stems):
    for x in (synth.vocal_line(sr=SR, seconds=4.0), song_stems["vocals"]):
        assert band_fraction(x, SR, 200.0, 5000.0) > 0.9
    # Sibilant bursts give the lead vocal a 5-8 kHz component (P-17 material).
    with_s = band_energy(synth.vocal_line(sr=SR, seconds=4.0), SR, 5000.0, 8000.0)
    without = band_energy(synth.vocal_line(sr=SR, seconds=4.0, sibilance=False), SR, 5000.0, 8000.0)
    assert db(with_s / without) > 10.0


def test_pad_is_wide_stereo(song_stems):
    x = song_stems["synth"]
    assert np.corrcoef(x[:, 0], x[:, 1])[0, 1] < 0.9
    bass = song_stems["bass"]
    assert np.corrcoef(bass[:, 0], bass[:, 1])[0, 1] > 0.999


def test_song_has_quiet_and_loud_sections(song_mix, song_sections):
    guard = 0.1
    (q0, q1), (l0, l1) = song_sections["quiet"], song_sections["loud"]
    quiet = song_mix[synth.frames_for(SR, q0): synth.frames_for(SR, q1 - guard)]
    loud = song_mix[synth.frames_for(SR, l0 + guard): synth.frames_for(SR, l1)]
    assert synth.rms_dbfs(loud) - synth.rms_dbfs(quiet) >= 4.0


# ---------------------------------------------------------------------------
# stem_sum and file helpers
# ---------------------------------------------------------------------------


def test_stem_sum_pads_and_broadcasts():
    a = np.ones((100, 2))
    b = np.full((60, 1), 0.5)
    c = np.full(80, 0.25)  # 1-D mono
    out = synth.stem_sum({"a": a, "b": b, "c": c})
    assert out.shape == (100, 2)
    np.testing.assert_allclose(out[0], [1.75, 1.75])
    np.testing.assert_allclose(out[70], [1.25, 1.25])
    np.testing.assert_allclose(out[90], [1.0, 1.0])
    assert synth.stem_sum([a, b]).shape == (100, 2)
    with pytest.raises(ValueError):
        synth.stem_sum([np.ones((10, 2)), np.ones((10, 3))])
    with pytest.raises(ValueError):
        synth.stem_sum({})


def test_stem_sum_of_song_matches_fixture(song_stems, song_mix):
    total = synth.stem_sum(song_stems)
    np.testing.assert_allclose(synth.normalize_peak(total, -6.0), song_mix, atol=1e-12)


def test_write_and_read_wav_round_trip(tmp_path):
    x = synth.sine(440.0, -3.0, sr=SR, seconds=0.25, channels=2)
    path = synth.write_wav(tmp_path / "sub" / "tone.wav", x, SR)
    info = sf.info(str(path))
    assert info.samplerate == SR and info.channels == 2 and info.subtype == "FLOAT"
    y, sr = synth.read_wav(path)
    assert sr == SR
    np.testing.assert_array_equal(y, x.astype(np.float32).astype(np.float64))
    pcm = synth.write_wav(tmp_path / "loud.wav", x * 4.0, SR, subtype="PCM_24")
    assert np.max(np.abs(synth.read_wav(pcm)[0])) <= 1.0


def test_file_fixtures(stems_dir, mix_wav, defective_mix_wav, song_stems):
    names = sorted(p.name for p in stems_dir.iterdir())
    assert names == sorted(f"{role}.wav" for role in song_stems)
    for p in [*stems_dir.iterdir(), mix_wav, defective_mix_wav]:
        info = sf.info(str(p))
        assert info.samplerate == SR and info.channels == 2
        assert info.frames == synth.frames_for(SR, synth.SONG_SECONDS)


def test_defective_mix_has_the_defects(song_mix, defective_mix):
    above = band_energy(defective_mix[SR // 10:], SR, 16000.0, SR / 2)
    original = band_energy(song_mix[SR // 10:], SR, 16000.0, SR / 2)
    shimmer_band = band_energy(defective_mix, SR, 10000.0, 14000.0)
    assert original > 0.0 and db(above / original) < -40.0
    assert shimmer_band > band_energy(song_mix, SR, 10000.0, 14000.0)
    assert synth.peak_dbfs(defective_mix[:5]) > synth.peak_dbfs(song_mix[:SR // 10]) + 3.0


def test_rng_fixture_is_seeded(rng):
    assert isinstance(rng, np.random.Generator)
    assert rng.integers(0, 1_000_000) == np.random.default_rng(20240613).integers(0, 1_000_000)
