"""reverb and delay (SPEC 6.5.2, 6.5.4, R-10, R-11): measured vectors, exact delays, Haas regions."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import engine
from mankomix.dsp import processors as P
from mankomix.dsp.errors import ChainError
from mankomix.dsp.reference import space

SR = 48000


def _reverb(x, **params):
    return space.reverb(np.asarray(x, dtype=np.float64), SR, P.validate_params("reverb", params))


def _delay(x, **params):
    return space.delay(np.asarray(x, dtype=np.float64), SR, P.validate_params("delay", params))


def _impulse(n, at=0, ch=2):
    x = np.zeros((n, ch))
    x[at] = 1.0
    return x


def _band_energy_db(x, lo, hi):
    spec = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return 10 * math.log10(float(np.sum(spec[(f >= lo) & (f < hi)])) + 1e-30)


# --------------------------------------------------------------------------- reverb

def test_reverb_is_deterministic():
    x = np.random.default_rng(3).standard_normal((SR, 2)) * 0.1
    y1, _, s1 = _reverb(x, rt60_s=1.2, mix=0.3)
    y2, _, s2 = _reverb(x, rt60_s=1.2, mix=0.3)
    assert np.array_equal(y1, y2)
    assert s1 == s2


@pytest.mark.parametrize("rt60", [0.6, 1.5, 3.0])
def test_reverb_rt60_of_impulse_response_at_1khz(rt60):
    n = int(SR * (rt60 * 1.6 + 0.3))
    y, _, st = _reverb(_impulse(n), rt60_s=rt60, mix=1.0, predelay_ms=10.0)
    for ch in range(2):
        est = space.schroeder_rt60(y[:, ch], SR, 1000.0)
        assert est is not None and abs(est / rt60 - 1.0) <= 0.25, (ch, est)
    # the processor records the same measurement of its own impulse response
    assert abs(st["rt60_measured_s"]["1000"] / rt60 - 1.0) <= 0.25
    assert st["rt60_set_s"]["mid"] == rt60


def test_reverb_band_multipliers_shape_the_decay():
    st = _reverb(_impulse(SR), rt60_s=1.5, mix=1.0, lowcut_hz=20.0, highcut_hz=20000.0,
                 rt60_low_mult=2.0, rt60_high_mult=0.5)[2]
    rt = st["rt60_measured_s"]
    assert rt["250"] > 1.15 * rt["1000"]
    assert rt["4000"] < 0.85 * rt["1000"]


def test_reverb_wet_lowcut_highcut_are_effective():
    x = np.random.default_rng(1).standard_normal((2 * SR, 2)) * 0.1
    wide, _, _ = _reverb(x, rt60_s=1.0, mix=1.0, lowcut_hz=20.0, highcut_hz=20000.0)
    plate, _, st = _reverb(x, rt60_s=1.0, mix=1.0, lowcut_hz=600.0, highcut_hz=6000.0)
    assert st["wet_filters"]["lowcut_hz"] == 600.0 and st["wet_filters"]["highcut_hz"] == 6000.0
    mid = _band_energy_db(plate[:, 0], 1500, 3000) - _band_energy_db(wide[:, 0], 1500, 3000)
    low = _band_energy_db(plate[:, 0], 50, 150) - _band_energy_db(wide[:, 0], 50, 150)
    high = _band_energy_db(plate[:, 0], 14000, 20000) - _band_energy_db(wide[:, 0], 14000, 20000)
    assert abs(mid) < 1.0
    assert low < mid - 12.0      # 12 dB/oct, >= 2 octaves below 600 Hz
    assert high < mid - 12.0     # >= 1.2 octaves above 6 kHz


def test_reverb_mono_compatibility_stat_and_send_mode():
    n = SR
    x = _impulse(n, at=0)
    x[0, 1] = 1.0                                   # centred source
    y, _, st = _reverb(x, rt60_s=1.5, mix=1.0, predelay_ms=20.0)
    mono = st["mono"]
    assert abs(mono["correlation"]) < 0.3          # decorrelated return
    assert -4.0 < mono["mono_loss_db"] < -1.5      # ~ -3 dB for uncorrelated channels
    assert st["mono_compatible"] is True and st["send_mode"] is True and st["dr_db_white"] is None
    # 100 % wet: nothing before the pre-delay (plus the first reflection at ~4 ms)
    pre = int(0.020 * SR)
    assert np.max(np.abs(y[:pre])) < 1e-9
    # measured mono stat matches the rendered output
    ref = space.mono_fold(y[:, 0], y[:, 1])
    assert abs(ref["correlation"] - mono["correlation"]) < 0.05


def test_reverb_dry_mix_and_stage_rules():
    x = np.random.default_rng(2).standard_normal((SR // 4, 2)) * 0.1
    y, _, st = _reverb(x, mix=0.0)
    assert np.array_equal(y, x)
    res = engine.render_chain(x, SR, [{"type": "reverb", "params": {"mix": 1.0, "bpm": 120.0}}],
                              stage="bus")
    assert res.steps[0]["backend"] == "reference"
    assert res.steps[0]["stats"]["predelay_note"]["value"] in P.NOTE_VALUES
    with pytest.raises(ChainError):
        engine.validate_chain([{"type": "reverb"}], "master")


def test_reverb_mono_input_keeps_channel_count():
    y, _, _ = _reverb(_impulse(SR // 2, ch=1), mix=1.0)
    assert y.shape == (SR // 2, 1) and np.max(np.abs(y)) > 0


# --------------------------------------------------------------------------- delay

def test_delay_exact_samples_for_time_ms():
    n = 4000
    y, _, st = _delay(_impulse(n, at=100), time_ms=12.5, feedback=0.0, mix=1.0)
    assert st["delay_samples"] == 600
    expect = np.zeros(n)
    expect[700] = 1.0
    for ch in range(2):
        assert np.array_equal(y[:, ch], expect)


@pytest.mark.parametrize("note,bpm,ms", [("1/8", 120.0, 250.0), ("1/4d", 90.0, 1000.0),
                                         ("1/8t", 100.0, 200.0), ("1/16", 150.0, 100.0)])
def test_delay_note_values(note, bpm, ms):
    D = int(round(ms * SR / 1000))
    n = D + 1000
    y, _, st = _delay(_impulse(n, at=5, ch=1), note=note, bpm=bpm, feedback=0.0, mix=1.0)
    assert st["delay_samples"] == D and st["note"]["value"] == note
    assert abs(st["note"]["note_ms"] - ms) < 1e-9
    nz = np.nonzero(y[:, 0])[0]
    assert list(nz) == [5 + D] and y[5 + D, 0] == 1.0


def test_delay_feedback_repeats():
    D = 480
    y, _, st = _delay(_impulse(5 * D, ch=1), time_ms=10.0, feedback=0.5, mix=1.0)
    for k in range(1, 5):
        assert abs(y[k * D, 0] - 0.5 ** (k - 1)) < 1e-12
    assert st["echo_decay_60db_s"] == pytest.approx(D / SR * 60 / (20 * math.log10(2)), rel=1e-3)


@pytest.mark.parametrize("ms,region,comb", [(2.0, "localisation", True), (15.0, "fusion", False),
                                            (80.0, "echo", False)])
def test_delay_haas_region_with_mono_loss(ms, region, comb):
    x = np.random.default_rng(4).standard_normal((SR // 2, 1)) * 0.1
    x = np.repeat(x, 2, axis=1)                      # centred source
    y, _, st = _delay(x, time_ms=ms, feedback=0.0, mix=1.0, route="right")
    assert st["haas"]["region"] == region and st["haas"]["comb_risk"] is comb
    assert np.array_equal(y[:, 0], x[:, 0])          # left untouched
    mono = st["mono"]
    assert mono["in"]["mono_loss_db"] == pytest.approx(0.0, abs=1e-6)
    assert mono["loss_change_db"] < -1.0             # a delayed copy no longer sums coherently
    assert mono["comb_first_repeat"]["first_notch_hz"] == pytest.approx(1000.0 / (2 * ms), rel=1e-3)


def test_delay_filters_and_validation():
    x = np.random.default_rng(5).standard_normal((SR, 1)) * 0.1
    y, _, st = _delay(x, time_ms=50.0, mix=1.0, feedback=0.0, lowcut_hz=1000.0, highcut_hz=3000.0)
    assert st["wet_filters"]["lowcut_hz"] == 1000.0
    assert _band_energy_db(y[:, 0], 50, 200) < _band_energy_db(y[:, 0], 1500, 2500) - 20
    with pytest.raises(ValueError):
        P.validate_params("delay", {"note": "1/4"})               # note needs bpm
    with pytest.raises(ValueError):
        P.validate_params("delay", {"bpm": 10.0})
    with pytest.raises(ValueError):
        P.validate_params("delay", {"note": "1/1d", "bpm": 40.0})  # 9000 ms > 4000 ms
    assert P.note_ms("1/8d", 120.0) == pytest.approx(375.0)
    assert space.nearest_note(251.0, 120.0)["value"] == "1/8"
