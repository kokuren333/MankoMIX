"""Finite image-source early reflections, independent of scene declarations."""
from mankomix.dspx.params import _f, _i, _b


def early_reflections(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.image_source import image_ir
    from mankomix.dspx.bb.ir import convolve_ir, ir_stats
    if not p["mix"]:
        return x.copy(), sr, {"latency_samples": 0, "bypass": True}
    h, stats = image_ir(sr, p)
    wet = convolve_ir(x, h)
    if x.shape[1] == 1:
        # ER preserves input shape; conv_reverb supports stereo asset expansion.
        wet = wet.mean(axis=1, keepdims=True)
    stats.update(ir_stats(h, sr, p), latency_samples=0, execution="lti", tail_truncated_at_end=True)
    return (1-p["mix"])*x+p["mix"]*wet, sr, stats


def cross_validate(p):
    from mankomix.dspx.bb.image_source import geometry
    geometry(p)


def _spec():
    from mankomix.dspx.bb.reverb import definition
    return definition("early_reflections", [
        _f("room_w_m", "m", 2, 50, 8, "Room width."),
        _f("room_l_m", "m", 2, 80, 12, "Room length."),
        _f("room_h_m", "m", 2, 20, 4, "Room height."),
        _f("absorption", None, .05, .9, .3, "Uniform wall energy absorption."),
        _f("distance_m", "m", .5, 30, 3, "Source distance; source must fit inside room."),
        _f("azimuth", None, -1, 1, 0, "Source horizontal direction."),
        _i("max_order", None, 1, 6, 3, "Maximum total reflection order."),
        _f("max_ms", "ms", 20, 200, 80, "Strict IR support."),
        _f("damping_hz", "Hz", 1000, 20000, 10000, "Lowpass once per reflection."),
        _b("direct", False, "Include the zero-order path."),
        _f("width", None, 0, 1, 1, "Stereo width."),
        _f("mix", None, 0, 1, .2, "Dry/wet mix; zero bypasses exactly."),
        _f("lowcut_hz", "Hz", 20, 2000, 100, "Wet highpass."),
        _f("highcut_hz", "Hz", 1000, 20000, 12000, "Wet lowpass.")], implemented=True)


SPECS = [_spec()]
IMPLS = {"early_reflections": early_reflections}
CROSS_VALIDATE = {"early_reflections": cross_validate}
