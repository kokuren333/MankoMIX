"""Geometry-scaled early reflections, allpass diffusion and 16-line FDN."""
from mankomix.dspx.params import _f
from mankomix.dspx.bb.reverb import definition, rv_params, process_reverb, validate_rv


def reverb_hall(x, sr, params, *, seed=0):
    return process_reverb(x, sr, params, seed=seed)


SPECS = [definition("reverb_hall", rv_params(.2, 20, 2.2) + [
    _f("size_m", "m", 3, 60, 25, "Room size."),
    _f("diffusion", None, 0, 1, .7, "Allpass diffusion."),
    _f("er_late_db", "dB", -24, 24, 0, "Early/late balance."),
    _f("rt60_low_mult", None, .1, 4, 1.2, "Low RT60 multiplier."),
    _f("rt60_high_mult", None, .1, 4, .6, "High RT60 multiplier."),
    _f("low_xover_hz", "Hz", 100, 1000, 250, "Low absorption crossover."),
    _f("high_xover_hz", "Hz", 1000, 12000, 4000, "High absorption crossover."),
    _f("width", None, 0, 1, 1, "Stereo width."),
    _f("mod_depth", None, 0, 1, 0, "Delay modulation depth."),
    _f("mod_rate_hz", "Hz", .05, 5, .5, "Delay modulation rate."),
])]
IMPLS = {"reverb_hall": reverb_hall}
TIME_VARYING = {"reverb_hall"}
CROSS_VALIDATE = {"reverb_hall": validate_rv}
