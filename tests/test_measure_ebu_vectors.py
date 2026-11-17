"""Additional synthetic conformance vectors from EBU Tech 3341/3342 (2023)."""
from __future__ import annotations

import numpy as np
import pytest

from mankomix.core.measure import loudness as L

SR = 48000


def _tones(*segments: tuple[float, float]) -> np.ndarray:
    x = np.empty((sum(round(seconds * SR) for _, seconds in segments), 2))
    start = 0
    for level, seconds in segments:
        count = round(seconds * SR)
        wave = 10.0 ** (level / 20.0) * np.sin(2 * np.pi * 1000 * np.arange(count) / SR)
        x[start:start + count] = wave[:, None]
        start += count
    return x


def test_tech3341_5(record_property):
    """EBU Tech 3341 test 5: expected I = -23.0 LUFS, tolerance +/-0.1 LU."""
    x = _tones((-26.0, 20.0), (-20.0, 20.1), (-26.0, 20.0))
    measured = L.integrated(x, SR)
    record_property("measured_lufs", measured)
    assert measured == pytest.approx(-23.0, abs=0.1)


def test_tech3341_6(record_property):
    """EBU Tech 3341 test 6: expected I = -23.0 LUFS, tolerance +/-0.1 LU."""
    wave = np.sin(2 * np.pi * 1000 * np.arange(20 * SR) / SR)
    levels = np.array([-28.0, -28.0, -24.0, -30.0, -30.0])
    x = wave[:, None] * 10.0 ** (levels / 20.0)
    measured = L.integrated(x, SR)
    record_property("measured_lufs", measured)
    assert measured == pytest.approx(-23.0, abs=0.1)


def test_tech3342_4(record_property):
    """EBU Tech 3342 test 4: expected LRA = 15.0 LU, tolerance +/-1.0 LU."""
    x = _tones(*((level, 20.0) for level in (-50.0, -35.0, -20.0, -35.0, -50.0)))
    measured = L.loudness_range(x, SR)
    record_property("measured_lu", measured)
    assert measured == pytest.approx(15.0, abs=1.0)


@pytest.mark.parametrize("divisor,phase", [
    pytest.param(4, 0.0, id="tech3341-15"),
    pytest.param(6, 60.0, id="tech3341-17"),
    pytest.param(8, 67.5, id="tech3341-18"),
])
def test_tech3341_true_peak(divisor, phase, record_property):
    """EBU Tech 3341 tests 15, 17, 18: expected -6.0 dBTP, tolerance +0.2/-0.4 dB."""
    n = np.arange(round(0.1 * SR))
    wave = 0.5 * np.sin(2 * np.pi * n / divisor + np.deg2rad(phase))
    fade = round(0.01 * SR)
    ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(fade) / fade)
    wave[:fade] *= ramp
    wave[-fade:] *= ramp[::-1]
    x = np.repeat(wave[:, None], 2, axis=1)
    measured = L.true_peak_dbtp(x, SR)
    record_property("measured_dbtp", measured)
    assert -6.0 - 0.4 <= measured <= -6.0 + 0.2
