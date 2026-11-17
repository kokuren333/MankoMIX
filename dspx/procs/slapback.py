"""Slapback is a BB-00 composite, expanded into the existing delay."""
from mankomix.dspx.params import _e, _f
from mankomix.dspx.bb.delayline import definition


def expand(p):
    return [{"type": "delay", "params": {
        "time_ms": p["time_ms"], "mix": p["mix"], "highcut_hz": p["tone_hz"],
        "lowcut_hz": p["lowcut_hz"], "route": p["route"], "feedback": 0, "note": "none",
    }}]


SPECS = [definition("slapback", [
    _f("time_ms", "ms", 40, 150, 90, "Single echo time."),
    _f("mix", None, 0, 1, 0.15, "Wet proportion."),
    _f("tone_hz", "Hz", 0, 24000, 5000, "Wet lowpass; zero bypasses."),
    _f("lowcut_hz", "Hz", 0, 2000, 150, "Wet highpass; zero bypasses."),
    _e("route", ["both", "left", "right"], "both", "Wet routing."),
])]
SPECS[0]["composite"] = True
IMPLS = {}
COMPOSITES = {"slapback": expand}
TIME_VARYING = {"slapback"}
