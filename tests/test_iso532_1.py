"""ISO 532-1:2017 Zwicker loudness prototype (M10 study; docs/M10_STUDIES.md section c).

Reference values and where they come from
-----------------------------------------
- 1 kHz tone, 40 dB SPL, frontal free field = 1 sone (definition of the sone;
  ISO 532-1:2017 clause 3, Zwicker & Fastl, Psychoacoustics, ch. 8).
- LN = 40 phon at 1 sone, +10 phon per doubling of N (ISO 532-1 relation).
- ISO 532-1:2017 Annex B.2 "test signal 1" (stationary, given as 28
  one-third-octave levels): N = 83.296 sone (free field).
- ISO 532-1:2017 Annex B.3 stationary test signals 2-4 (sine tones, free field):
  250 Hz 80 dB -> 14.655 sone, 1 kHz 60 dB -> 4.019 sone, 4 kHz 40 dB -> 1.549 sone.
- ISO 532-1:2017 Annex B.4 time-varying test signals 10-12 (1 kHz tone pulses,
  70 dB, 100 ms silence before): Nmax = 4.2998 (10 ms), 5.9746 (50 ms),
  8.0772 sone (500 ms).
  The numbers above are the results distributed with the standard's electronic
  attachment, as quoted in MoSQITo (Apache-2.0):
  https://github.com/Eomys/MoSQITo/blob/master/tests/sq_metrics/loudness/test_loudness_zwst.py
  https://github.com/Eomys/MoSQITo/blob/master/validations/sq_metrics/loudness_zwst/validation_loudness_zwst.py
  https://github.com/Eomys/MoSQITo/blob/master/tests/input/  (time-varying results workbook)
  No ISO audio or data file is stored in this repository: the signals are
  synthesised here. The tone pulses use 5 ms raised-cosine ramps and the
  nominal duration between the half-amplitude points, which approximates (but
  does not reproduce bit for bit) the envelope of the ISO files.
- Tolerance: 5 % on N, the tolerance ISO 532-1 itself uses for conformity
  (clauses 5.1 / 6.1). Our one-third-octave filter bank is our own design (see
  the module docstring), which costs up to about 2 % against the reference.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from mankomix.core.analysis import iso532_1 as z

SR = 48000
CAL = 100.0   # dB SPL of a full-scale sine: the convention of the ISO 532-1 WAV files

# ISO 532-1:2017 Annex B.2, test signal 1 (one-third-octave levels, dB, 25 Hz .. 12.5 kHz).
TEST_SIGNAL_1 = [-60, -60, 78, 79, 89, 72, 80, 89, 75, 87, 85, 79, 86, 80, 71, 70, 72, 71, 72, 74,
                 69, 65, 67, 77, 68, 58, 45, 30]


def _tone(freq: float, db_spl: float, dur: float = 1.5, sr: int = SR, cal: float = CAL) -> np.ndarray:
    t = np.arange(int(round(dur * sr))) / sr
    return 10.0 ** ((db_spl - cal) / 20.0) * np.sin(2.0 * np.pi * freq * t)


def _pulse(dur: float, db_spl: float = 70.0, freq: float = 1000.0, pre: float = 0.1,
           post: float = 0.2, ramp: float = 0.005) -> np.ndarray:
    n = int(round((dur + ramp) * SR))
    y = np.sin(2.0 * np.pi * freq * np.arange(n) / SR)
    r = int(round(ramp * SR))
    w = np.sin(0.5 * np.pi * np.arange(r) / r) ** 2
    y[:r] *= w
    y[-r:] *= w[::-1]
    return np.concatenate([np.zeros(int(pre * SR)), 10.0 ** ((db_spl - CAL) / 20.0) * y,
                           np.zeros(int(post * SR))])


def _close(value: float, ref: float, rel: float = 0.05) -> bool:
    return abs(value - ref) <= rel * ref


# ---------------------------------------------------------------------------
# Stationary core from one-third-octave levels


def test_annex_b2_test_signal_1_from_levels():
    r = z.loudness_from_third_octave_levels(TEST_SIGNAL_1, field="free")
    assert abs(r["N_sone"] - 83.296) <= 0.1          # same algorithm and tables -> near exact
    assert len(r["specific_loudness"]) == 240 and len(r["bark_axis"]) == 240
    assert r["bark_axis"][0] == 0.1 and r["bark_axis"][-1] == 24.0
    # The specific loudness integrates to N (0.1-Bark grid, piecewise linear slopes).
    assert _close(sum(r["specific_loudness"]) * 0.1, r["N_sone"], 0.02)
    json.dumps(r, allow_nan=False)


def test_levels_input_validation():
    with pytest.raises(ValueError):
        z.loudness_from_third_octave_levels(TEST_SIGNAL_1[:-1])
    with pytest.raises(ValueError):
        z.loudness_from_third_octave_levels(TEST_SIGNAL_1, field="binaural")
    hot = list(TEST_SIGNAL_1)
    hot[3] = 125.0
    assert z.loudness_from_third_octave_levels(hot)["warnings"]


def test_silence_is_zero_loudness():
    r = z.loudness_from_third_octave_levels([-60.0] * 28)
    assert r["N_sone"] == 0.0
    assert max(r["specific_loudness"]) == 0.0


def test_loudness_level_relation():
    assert z.loudness_level_phon(1.0) == pytest.approx(40.0)
    assert z.loudness_level_phon(2.0) == pytest.approx(50.0)
    assert z.loudness_level_phon(4.0) == pytest.approx(60.0)
    assert z.loudness_level_phon(0.5) < 40.0


def test_diffuse_field_differs_from_free_field():
    free = z.loudness_from_third_octave_levels(TEST_SIGNAL_1, "free")["N_sone"]
    diffuse = z.loudness_from_third_octave_levels(TEST_SIGNAL_1, "diffuse")["N_sone"]
    assert diffuse != free and 0.8 * free < diffuse < 1.2 * free


# ---------------------------------------------------------------------------
# Stationary method from signals


def test_one_sone_definition():
    r = z.loudness_zwicker(_tone(1000.0, 40.0), SR, calibration_db_spl=CAL)
    assert _close(r["N_sone"], 1.0)
    assert abs(r["LN_phon"] - 40.0) < 1.0


@pytest.mark.parametrize("freq, db, ref", [(250.0, 80.0, 14.655), (1000.0, 60.0, 4.019),
                                           (4000.0, 40.0, 1.549)])
def test_annex_b3_tones(freq, db, ref):
    r = z.loudness_zwicker(_tone(freq, db), SR, calibration_db_spl=CAL)
    assert _close(r["N_sone"], ref), (r["N_sone"], ref)


def test_other_sample_rate_is_resampled():
    x = _tone(1000.0, 60.0, sr=44100)
    r = z.loudness_zwicker(x, 44100, calibration_db_spl=CAL)
    assert _close(r["N_sone"], 4.019)
    assert r["sample_rate_analysis"] == 48000 and r["sample_rate_in"] == 44100.0


def test_calibration_is_explicit_and_consistent():
    x = _tone(1000.0, 60.0)
    with pytest.raises(TypeError):
        z.loudness_zwicker(x, SR)                                  # no implicit level
    with pytest.raises(ValueError):
        z.loudness_zwicker(x, SR, calibration_db_spl=float("nan"))
    a = z.loudness_zwicker(x, SR, calibration_db_spl=CAL)
    # The same samples declared 20 dB louder equal a 20 dB louder tone at the old calibration.
    b = z.loudness_zwicker(x, SR, calibration_db_spl=CAL + 20.0)
    c = z.loudness_zwicker(_tone(1000.0, 80.0), SR, calibration_db_spl=CAL)
    assert b["N_sone"] == pytest.approx(c["N_sone"], rel=1e-6)
    assert b["N_sone"] > 3.0 * a["N_sone"]                         # about +20 phon -> about x4
    assert a["calibration"]["calibration_db_spl"] == CAL
    assert a["calibration"]["pa_per_unit"] == pytest.approx(2.0 * np.sqrt(2.0))


def test_stereo_reports_each_channel():
    x = np.stack([_tone(1000.0, 50.0), _tone(1000.0, 60.0)], axis=1)
    r = z.loudness_zwicker(x, SR, calibration_db_spl=CAL)
    assert r["channel"] == 1
    assert len(r["per_channel"]) == 2
    assert r["per_channel"][0]["N_sone"] < r["per_channel"][1]["N_sone"] == r["N_sone"]


def test_deterministic_and_json_safe():
    x = _tone(500.0, 65.0)
    a = z.loudness_zwicker(x, SR, calibration_db_spl=CAL)
    b = z.loudness_zwicker(x, SR, calibration_db_spl=CAL)
    assert a == b
    json.dumps(a, allow_nan=False)


def test_bad_arguments():
    x = _tone(1000.0, 60.0)
    with pytest.raises(ValueError):
        z.loudness_zwicker(x, SR, "binaural", calibration_db_spl=CAL)
    with pytest.raises(ValueError):
        z.loudness_zwicker(x, SR, calibration_db_spl=CAL, method="moore")
    with pytest.raises(ValueError):
        z.loudness_zwicker(x[:1000], SR, calibration_db_spl=CAL)  # shorter than skip + 50 ms
    with pytest.raises(ValueError):
        z.loudness_zwicker(x, 16000, calibration_db_spl=CAL)      # 12.5 kHz band unreachable


# ---------------------------------------------------------------------------
# Time-varying method


@pytest.mark.parametrize("dur, ref", [(0.01, 4.2998), (0.05, 5.9746), (0.5, 8.0772)])
def test_annex_b4_tone_pulses(dur, ref):
    r = z.loudness_zwicker(_pulse(dur), SR, calibration_db_spl=CAL, method="time_varying", skip_s=0.0)
    assert _close(r["N_max_sone"], ref), (r["N_max_sone"], ref)
    series = np.asarray(r["N_sone_series"])
    t = np.asarray(r["time_s"])
    assert np.allclose(np.diff(t), 0.002)
    peak_t = t[int(np.argmax(series))]
    assert 0.1 <= peak_t <= 0.1 + dur + 0.05                       # peak while the pulse sounds
    assert series[-1] < 0.1 * r["N_max_sone"]                       # decays after the pulse
    json.dumps({k: v for k, v in r.items()}, allow_nan=False)


def test_time_varying_steady_tone_matches_stationary():
    x = _tone(1000.0, 60.0, dur=1.0)
    tv = z.loudness_zwicker(x, SR, calibration_db_spl=CAL, method="time_varying", skip_s=0.3)
    st = z.loudness_zwicker(x, SR, calibration_db_spl=CAL, method="stationary", skip_s=0.3)
    assert _close(tv["N5_sone"], st["N_sone"], 0.03)
    assert tv["N5_sone"] >= tv["N10_sone"] - 1e-9
