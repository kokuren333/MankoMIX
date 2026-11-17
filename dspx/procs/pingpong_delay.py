"""Two integer delay lines with crossed feedback and M/S width."""
import numpy as np

from mankomix.dspx.params import _e, _f
from mankomix.dspx.bb.delayline import (
    DelayLine, LoopFilter, definition, delay_ms, dl_params, spatial_stats,
    validate_feedback,
)


def cross_validate(p):
    ms = delay_ms(p)
    validate_feedback(p, ms * max(1, p["ratio"]))


def pingpong_delay(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.selfduck import duck_wet
    cross_validate(p)
    ms = delay_ms(p)
    delays = np.array([max(1, round(ms * sr / 1000)), max(1, round(ms * p["ratio"] * sr / 1000))])
    if p["mix"] == 0:
        return x.copy(), sr, spatial_stats(x, sr, ms)
    dry = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x
    injection = dry.copy()
    if p["input"] == "mono_sum" or x.shape[1] == 1:
        mono = np.mean(x, axis=1)
        injection[:] = 0
        injection[:, 0 if p["start"] == "left" else 1] = mono
    line = DelayLine(max(delays), 2, "integer")
    wet = line.process(injection, delays, p["feedback"],
                       LoopFilter(sr, 2, p["lowcut_hz"], p["highcut_hz"]),
                       matrix=np.array([[0., 1.], [1., 0.]]))
    if p["width"] != 1:
        mid = (wet[:, 0] + wet[:, 1]) / 2
        side = (wet[:, 0] - wet[:, 1]) / 2 * p["width"]
        wet = np.column_stack((mid + side, mid - side))
    wet = duck_wet(dry, wet, sr, p)
    y = (1 - p["mix"]) * dry + p["mix"] * wet
    stats = spatial_stats(y, sr, ms)
    stats.update(delay_samples=delays.tolist(), feedback=p["feedback"], seed=p["seed"])
    return y, sr, stats


SPECS = [definition("pingpong_delay", dl_params() + [
    _e("start", ["left", "right"], "left", "Initial repeat side for mono injection."),
    _f("width", None, 0, 1, 1, "One gives alternating sides, zero gives centre."),
    _e("input", ["mono_sum", "stereo"], "mono_sum", "Injection routing."),
    _f("ratio", None, 0.5, 2, 1, "Right / left delay ratio."),
])]
IMPLS = {"pingpong_delay": pingpong_delay}
TIME_VARYING = {"pingpong_delay"}
CROSS_VALIDATE = {"pingpong_delay": cross_validate}
