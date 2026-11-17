"""Offline live-buffer or curve-directed granular effect."""
from mankomix.dspx.params import _a, _e, _f, _i


def cross_validate(p):
    from mankomix.dsp.errors import ParamError
    from mankomix.dspx.bb.grains import validate_grain_feedback
    if p["mode"] == "scrub":
        if not p["position"]:
            raise ParamError("scrub mode requires a position curve")
        if p["feedback"] != 0:
            raise ParamError("feedback is available in live mode only")
    else:
        validate_grain_feedback(p)


def granular(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.grains import render_calibrated_grains
    cross_validate(p)
    if p["mix"] == 0:
        return x.copy(), sr, {"latency_samples": 0, "grain_count": 0}
    wet, stats = render_calibrated_grains(x, sr, p, seed=seed)
    return (1 - p["mix"]) * x + p["mix"] * wet, sr, stats


SPECS = [{"type": "granular", "description": "Offline granular live buffer and scrub effect.",
          "params": [
              _e("mode", ["live", "scrub"], "live", "Recent buffer or absolute source curve."),
              _f("buffer_s", "s", .1, 20, 4, "Live input history length."),
              {"id": "position", "type": "curve", "unit": "s", "x_unit": "s",
               "x_min": 0, "x_max": 1.7976931348623157e308,
               "y_min": 0, "y_max": 1.7976931348623157e308, "max_points": 1024, "default": [],
               "description": "Absolute input seconds by output seconds; required in scrub mode."},
              _f("speed", None, -4, 4, 1, "Live source head speed."),
              _f("grain_ms", "ms", 5, 1000, 80, "Grain duration."),
              _f("density_hz", "Hz", 1, 400, 25, "Grain centers per second."),
              _f("spray_ms", "ms", 0, 2000, 50, "Source position deviation."),
              _f("jitter", None, 0, 1, .3, "Grain interval variation."),
              _f("pitch_semitones", "semitones", -24, 24, 0, "Grain playback pitch."),
              _f("pitch_spread", "semitones", 0, 24, 0, "Uniform pitch deviation."),
              _a("pitch_quantize", "semitones", -24, 24, 8, [], "Absolute grain pitches in the base pitch range; empty selects continuous pitch."),
              _f("reverse", None, 0, 1, 0, "Fraction of reversed grains."),
              _e("window", ["hann", "tukey", "exp_decay", "exp_attack"], "hann", "Grain window."),
              _f("pan_spread", None, 0, 1, .5, "Stereo grain pan spread; mono retains one channel."),
              _f("level_spread_db", "dB", 0, 24, 0, "Symmetric grain level deviation."),
              _f("feedback", None, 0, .9, 0, "Post-normalization feedback, live only."),
              _f("mix", None, 0, 1, .5, "Wet proportion."),
              _i("seed", None, 0, 65535, 0, "Deterministic parameter seed."),
          ], "stages": ["track", "bus"], "master_slot": None,
          "realtime": {"block_ok": False, "allocates": True, "latency_samples": 0},
          "offline_only": True, "backends": ["reference"], "implemented": True,
          "channel_ok": False}]
IMPLS = {"granular": granular}
TIME_VARYING = {"granular"}
CROSS_VALIDATE = {"granular": cross_validate}
