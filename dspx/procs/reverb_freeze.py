"""Scheduled lossless FDN freeze, with absolute sample-time transitions."""
from mankomix.dspx.params import _a, _e, _f


def cross_validate(p):
    from mankomix.dspx.bb.reverb import validate_freeze
    validate_freeze(p)
    if p['rt60_s'] > 24:
        from mankomix.dsp.errors import ParamError
        raise ParamError('rt60_s must be <= 24 s for 60-second decay after freeze release')


def reverb_freeze(x, sr, params, *, seed=0):
    from mankomix.dspx.bb.reverb import process_freeze
    cross_validate(params)
    return process_freeze(x, sr, params, seed=seed)


def _specs():
    from mankomix.dspx.bb.reverb import definition, rv_params
    return [definition("reverb_freeze", rv_params(.3, 60, 4) + [
        _a("freeze_start_s", "s", 0, 36000, 16, [], "Strictly ordered freeze starts."),
        _a("freeze_end_s", "s", 0, 36000, 16, [], "Matching exclusive ends."),
        _f("freeze_fade_ms", "ms", 5, 2000, 50, "Absorption bypass transition."),
        _e("freeze_input", ["mute", "pass"], "mute", "Tank input during freeze."),
        _f("size_m", "m", 3, 60, 30, "FDN delay geometry."),
        _f("diffusion", None, 0, 1, .8, "Input allpass diffusion."),
        _f("damping_hz", "Hz", 1000, 20000, 8000, "Loop high frequency absorption corner."),
        _f("mod_depth", None, 0, 1, 0, "Delay modulation outside lossless holds."),
    ], implemented=True)]


SPECS = _specs()
IMPLS = {"reverb_freeze": reverb_freeze}
CROSS_VALIDATE = {"reverb_freeze": cross_validate}
TIME_VARYING = {"reverb_freeze"}
