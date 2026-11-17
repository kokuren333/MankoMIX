"""Hann-window granular delay using a shared deterministic grain renderer."""
from mankomix.dspx.params import _f


def cross_validate(p):
    from mankomix.dspx.bb.delayline import delay_ms
    from mankomix.dspx.bb.grains import validate_grain_feedback
    validate_grain_feedback(p, delay_ms=delay_ms(p))


def granular_delay(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.delayline import delay_ms, duck_wet, spatial_stats
    from mankomix.dspx.bb.grains import render_calibrated_grains
    ms = delay_ms(p)
    cross_validate(p)
    if p["mix"] == 0:
        return x.copy(), sr, {"latency_samples": 0, "grain_count": 0}
    wet, stats = render_calibrated_grains(x, sr, p, seed=seed, delay_samples=ms * sr / 1000)
    wet = duck_wet(x, wet, sr, p)
    y = (1 - p["mix"]) * x + p["mix"] * wet
    stats.update(spatial_stats(y, sr, ms))
    stats["delay_ms"] = ms
    return y, sr, stats


def _delay_params():
    from mankomix.dspx.bb.delayline import dl_params
    declarations = dl_params()
    for spec in declarations:
        if spec["id"] == "feedback":
            spec.update(max=0.9, default=0.2)
    return declarations

SPECS = [{"type": "granular_delay", "description": "Seeded Hann-window granular delay.",
          "params": _delay_params() + [
              _f("grain_ms", "ms", 5, 500, 80, "Grain duration."),
              _f("density_hz", "Hz", 1, 200, 25, "Grain centers per second."),
              _f("spray_ms", "ms", 0, 1000, 50, "Source position deviation."),
              _f("jitter", None, 0, 1, .3, "Grain interval variation."),
              _f("pitch_semitones", "semitones", -24, 24, 0, "Grain playback pitch."),
              _f("pitch_spread", "semitones", 0, 12, 0, "Uniform pitch deviation."),
              _f("reverse", None, 0, 1, 0, "Fraction of reversed grains."),
              _f("pan_spread", None, 0, 1, .5, "Stereo grain pan spread; mono retains one channel."),
          ], "stages": ["track", "bus"], "master_slot": None,
          "realtime": {"block_ok": False, "allocates": True, "latency_samples": 0},
          "offline_only": False, "backends": ["reference"], "channel_ok": False,
          "implemented": True}]
IMPLS = {"granular_delay": granular_delay}
TIME_VARYING = {"granular_delay"}
CROSS_VALIDATE = {"granular_delay": cross_validate}
