"""Dense serial allpass diffusion and a short eight-line FDN."""
from mankomix.dspx.params import _f
from mankomix.dspx.bb.reverb import definition, rv_params, process_reverb, validate_decay_rv


def reverb_chamber(x, sr, params, *, seed=0):
    validate_decay_rv(params)
    return process_reverb(x, sr, params, chamber=True, seed=seed, absorption_order=4)


SPECS = [definition("reverb_chamber", rv_params(.3, 8, 1.8, 5) + [
    _f("size_m", "m", 2, 15, 6, "Chamber size."),
    _f("density", None, 0, 1, .9, "Allpass diffusion density."),
    _f("rt60_low_mult", None, .1, 4, 1, "Low RT60 multiplier."),
    _f("rt60_high_mult", None, .1, 4, .8, "High RT60 multiplier."),
    _f("distance", None, 0, 1, .5, "Late onset rise from zero to 40 ms."),
    _f("width", None, 0, 1, 1, "Stereo width."),
], implemented=True)]
IMPLS = {"reverb_chamber": reverb_chamber}
CROSS_VALIDATE = {"reverb_chamber": validate_decay_rv}
