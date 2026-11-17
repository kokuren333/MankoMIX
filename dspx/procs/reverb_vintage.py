"""Four input diffusers and a crossed two-loop, multitap allpass tank."""
from mankomix.dspx.params import _e, _f


def cross_validate(p):
    from mankomix.dspx.bb.reverb import validate_rv
    validate_rv(p)
    if p['rt60_s']*max(1., p['bass_mult']) > 24:
        from mankomix.dsp.errors import ParamError
        raise ParamError('rt60_s * max(1, bass_mult) must be <= 24 s for 60-second decay')


def reverb_vintage(x, sr, params, *, seed=0):
    from mankomix.dspx.bb.vintage import process_vintage
    cross_validate(params)
    return process_vintage(x, sr, params, seed=seed)


def _specs():
    from mankomix.dspx.bb.reverb import definition, rv_params
    return [definition("reverb_vintage", rv_params(.3, 20, 2.5) + [
        _f("input_diffusion", None, 0, 1, .75, "Four-stage input diffusion."),
        _f("tank_diffusion", None, 0, 1, .6, "Tank allpass diffusion."),
        _f("damping_hz", "Hz", 1000, 20000, 6000, "Tank damping cutoff."),
        _f("bass_mult", None, .5, 2, 1.2, "Low-band decay multiplier."),
        _f("mod_depth", None, 0, 1, .3, "Tank allpass modulation depth."),
        _f("mod_rate_hz", "Hz", .1, 3, 1, "Tank modulation frequency."),
        _f("bandwidth_hz", "Hz", 4000, 20000, 10000, "Internal bandwidth cutoff."),
        _e("bits", ["0", "12", "14", "16"], "0", "Internal TPDF quantizer; zero disables.", unit="bit"),
    ], implemented=True)]


SPECS = _specs()
IMPLS = {"reverb_vintage": reverb_vintage}
CROSS_VALIDATE = {"reverb_vintage": cross_validate}
TIME_VARYING = {"reverb_vintage"}
