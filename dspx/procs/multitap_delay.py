"""Integer multitap delay, with feedback from the final unpanned read."""
import numpy as np

from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _e, _f
from mankomix.dspx.bb.delayline import (
    DelayLine, LoopFilter, definition, dl_params, duck_wet, fractional_delay,
    integer_feedback, spatial_stats, validate_feedback,
)


def tap_times(p):
    times = p["tap_ms"]
    if not times or len(times) != len(p["tap_db"]) or (p["tap_pan"] and len(times) != len(p["tap_pan"])):
        raise ParamError("tap arrays must be nonempty and have matching lengths")
    if any(a >= b for a, b in zip(times, times[1:])):
        raise ParamError("tap_ms must be strictly ascending")
    if 0 < p["bpm"] < 20:
        raise ParamError("bpm must be zero or at least 20")
    if p["tap_unit"] == "beats":
        if not p["bpm"] or any(t < 0.01 or t > 16 for t in times):
            raise ParamError("beat taps require bpm and values in [0.01,16]")
        times = [t * 60000 / p["bpm"] for t in times]
        if times[-1] > 4000:
            raise ParamError("converted taps exceed 4000 ms")
    elif any(t < 0.1 for t in times):
        raise ParamError("millisecond taps must be at least 0.1 ms")
    return times


def cross_validate(p):
    times = tap_times(p)
    # Triangle bound covers all pans and simultaneous full-scale tap outputs.
    gain = sum(10 ** (db / 20) for db in p["tap_db"])
    validate_feedback(p, times[-1], gain)


def multitap_delay(x, sr, p, *, seed=0):
    cross_validate(p)
    times = tap_times(p)
    delays = [max(1, round(t * sr / 1000)) for t in times]
    if not p["mix"]:
        return x.copy(), sr, spatial_stats(x, sr, times[0])
    dry = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x
    if p["feedback"]:
        if not p["lowcut_hz"] and not p["highcut_hz"]:
            last = integer_feedback(x, delays[-1], p["feedback"])
        else:
            line = DelayLine(delays[-1], x.shape[1], "integer")
            last = line.process(x, delays[-1], p["feedback"], LoopFilter(sr, x.shape[1], p["lowcut_hz"], p["highcut_hz"]))
        source = x + p["feedback"] * LoopFilter(sr, x.shape[1], p["lowcut_hz"], p["highcut_hz"])(last)
    else:
        source = x
    wet = np.zeros_like(dry)
    for d, db, pan in zip(delays, p["tap_db"], p["tap_pan"] or [0.] * len(delays)):
        tap = fractional_delay(source, d, "integer") * 10 ** (db / 20)
        # Equal-power pan, exact silence at the endpoints.
        gains = np.array([np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)])
        if pan == 1:
            gains[0] = 0
        elif pan == -1:
            gains[1] = 0
        wet += tap * gains
    wet = duck_wet(dry, wet, sr, p)
    y = (1 - p["mix"]) * dry + p["mix"] * wet
    stats = spatial_stats(y, sr, times[0])
    stats.update(tap_samples=delays, tap_ms=times, feedback=p["feedback"])
    return y, sr, stats


SPECS = [definition("multitap_delay", [
    # The shared static array schema spans both units; cross-validation enforces ms>=.1.
    _a("tap_ms", "ms or beats", 0.01, 4000, 16, [125, 250, 375], "Ascending tap positions; beats must be in [0.01,16]."),
    _a("tap_db", "dB", -60, 6, 16, [-3, -6, -9], "Tap levels; one per time."),
    _a("tap_pan", None, -1, 1, 16, [], "Equal-power pan; empty means centre."),
    _e("tap_unit", ["ms", "beats"], "ms", "Tap time unit."),
] + [dict(s, default=0) if s["id"] == "feedback" else s for s in dl_params()
     if s["id"] not in {"time_ms", "note", "seed"}])]
IMPLS = {"multitap_delay": multitap_delay}
TIME_VARYING = {"multitap_delay"}
CROSS_VALIDATE = {"multitap_delay": cross_validate}
