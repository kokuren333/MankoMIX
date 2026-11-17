"""Pinned IR convolution through BB-08, BB-07 and BB-10 finishing."""
import numpy as np
from mankomix.dspx.params import _f, _e


def asset_param(id, default, *, allow_empty=False):
    return {"id": id, "type": "asset", "registry": "irs", "unit": None,
            "default": default, "allow_empty": allow_empty, "description": "Registered impulse response ID."}


def conv_reverb(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.ir import load_ir, prepare_ir, convolve_ir, ir_stats, decay_time
    from mankomix.dspx.bb.reverb import finish, _wet_filter
    from mankomix.dspx.bb.delayline import fractional_delay
    # Verify provenance even in bypass: a bad/missing asset never silently passes.
    h, stats = load_ir(p["ir"], sr)
    if not p["mix"]:
        return x.copy(), sr, dict(stats, latency_samples=0, bypass=True)
    h = prepare_ir(h, sr, **{k: p[k] for k in ("start_ms", "length_s", "fade_ms", "decay", "gain_mode")})
    wet = convolve_ir(x, h)
    wet = _wet_filter(fractional_delay(wet, round(p["predelay_ms"]*sr/1000), "integer"), sr, p)
    measurement = _wet_filter(np.pad(h, ((0, round(.5*sr)), (0, 0))), sr, p)
    measurement = np.pad(measurement, ((round(p["predelay_ms"]*sr/1000), 0), (0, 0)))
    stats.update(ir_stats(measurement, sr, p), execution="lti")
    dry = x if wet.shape[1] == x.shape[1] else x.repeat(wet.shape[1], axis=1)
    return finish(dry, wet, sr, dict(p, rt60_s=decay_time(h, sr) or 0), stats)


def _spec():
    from mankomix.dspx.bb.reverb import definition, rv_params, validate_rv
    common = [p for p in rv_params() if p["id"] not in ("rt60_s", "seed")]
    return definition("conv_reverb", [asset_param("ir", "synth_room_a"),
        _f("start_ms", "ms", 0, 500, 0, "Trim IR beginning."),
        _f("length_s", "s", .05, 20, 20, "Maximum IR length."),
        _f("fade_ms", "ms", 1, 500, 50, "IR end fade."),
        _f("decay", None, .25, 1, 1, "Shorten measured T20 by an exponential window."),
        _e("gain_mode", ["energy", "peak", "none"], "energy", "IR normalization.")]+common, implemented=True)


def cross_validate(p):
    from mankomix.dspx.bb.reverb import validate_rv
    validate_rv(p)


SPECS = [_spec()]
IMPLS = {"conv_reverb": conv_reverb}
CROSS_VALIDATE = {"conv_reverb": cross_validate}
