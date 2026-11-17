"""Intentional fractional delay, polarity and first-order phase rotation."""
import numpy as np
from scipy import signal

from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _b, _f, _i
from mankomix.dspx.bb.delayline import definition, fractional_delay


def cross_validate(p):
    if 0 < p["allpass_hz"] < 20:
        raise ParamError("allpass_hz must be zero or at least 20 Hz")


def time_align(x, sr, p, *, seed=0):
    cross_validate(p)
    f = p["allpass_hz"]
    if f and f >= sr / 2:
        raise ParamError("allpass_hz must be zero or at least 20 Hz and below Nyquist")
    d = p["delay_ms"] * sr / 1000
    # Alignment has a tighter bandwidth specification than the DT family.
    # A 256-point windowed sinc retains 0.9*Nyquist within 0.01 dB.
    y = fractional_delay(x, d, "sinc256")
    if f:
        tangent = np.tan(np.pi * f / sr)
        a = (tangent - 1) / (tangent + 1)
        for _ in range(p["allpass_stages"]):
            y = signal.lfilter([a, 1], [1, a], y, axis=0)
    if p["polarity_invert"]:
        y = -y
    return y, sr, {"delay_samples": d, "latency_samples": 0, "latency_compensated": False}


SPECS = [definition("time_align", [
    _f("delay_ms", "ms", 0, 100, 0, "Intentional delay; never latency compensated."),
    _b("polarity_invert", False, "Invert polarity."),
    _f("allpass_hz", "Hz", 0, 20000, 0, "Zero bypasses, otherwise 20 Hz or higher."),
    _i("allpass_stages", None, 1, 4, 1, "First-order allpass stages."),
], channel=True, latency_rule="Intentional delay is not compensated; centred sinc uses offline context.")]
IMPLS = {"time_align": time_align}
CROSS_VALIDATE = {"time_align": cross_validate}
SPECS[0]["realtime"]["block_ok"] = False
