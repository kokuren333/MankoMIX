"""M/S gain with the BB-00 encoding convention; default bypass is exact."""
import numpy as np

from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _b, _e, _f
from mankomix.dspx.bb.delayline import definition, spatial_stats


def ms_gain(x, sr, p, *, seed=0):
    if x.shape[1] != 2:
        raise ParamError("ms_gain requires stereo input")
    if p["mode"] == "process" and not any((p["mid_db"], p["side_db"], p["mid_mute"], p["side_mute"], p["swap"])):
        return x.copy(), sr, spatial_stats(x, sr)
    if p["mode"] == "decode":
        mid, side = x[:, 0].copy(), x[:, 1].copy()
    else:
        mid = (x[:, 0] + x[:, 1]) / 2
        side = (x[:, 0] - x[:, 1]) / 2
    mid = mid * (0 if p["mid_mute"] else 10 ** (p["mid_db"] / 20))
    side = side * (0 if p["side_mute"] else 10 ** (p["side_db"] / 20))
    if p["swap"]:
        side = -side
    y = np.column_stack((mid, side)) if p["mode"] == "encode" else np.column_stack((mid + side, mid - side))
    return y, sr, spatial_stats(y, sr)


SPECS = [definition("ms_gain", [
    _f("mid_db", "dB", -24, 12, 0, "Mid gain."),
    _f("side_db", "dB", -24, 12, 0, "Side gain."),
    _b("mid_mute", False, "Mute mid."), _b("side_mute", False, "Mute side."),
    _b("swap", False, "Swap decoded left and right."),
    _e("mode", ["process", "encode", "decode"], "process", "M/S processing or conversion."),
], implemented=False, master=True)]
IMPLS = {"ms_gain": ms_gain}
