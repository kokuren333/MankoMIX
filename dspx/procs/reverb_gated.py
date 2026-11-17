"""Finite velvet-noise IRs or a dry-keyed gate on the FDN return."""
import numpy as np

from mankomix.dspx.params import _f, _e
from mankomix.dspx.bb.curves import period_ms
from mankomix.dspx.bb.dynamics import gate_gain
from mankomix.dspx.bb.fir import fft_convolve
from mankomix.dspx.bb.reverb import (definition, rv_params, validate_rv, velvet_ir,
    render_ir, measure_ir, finish, _stereo, _wet_filter, NOTE_VALUES)


def cross_validate(p):
    validate_rv(p)
    period_ms(p["gate_ms"], note=p["note"], bpm=p["bpm"])


def gated_ir(sr, p, *, seed=0):
    length = period_ms(p["gate_ms"], note=p["note"], bpm=p["bpm"])
    body = velvet_ir(sr, length, p, shape=p["shape"], seed=seed)
    # Filter before the strict support window so IIR tails cannot escape it.
    body = _wet_filter(body.reshape(len(body), 4), sr, p).reshape(body.shape)
    fade = min(len(body), max(1, round(.005*sr)))
    body[-fade:] *= np.linspace(1, 0, fade)[:, None, None]
    return np.pad(body, ((round(p["predelay_ms"]*sr/1000), 0), (0, 0), (0, 0)))


def reverb_gated(x, sr, p, *, seed=0):
    cross_validate(p)
    if not p["mix"]:
        return x.copy(), sr, {"latency_samples": 0, "bypass": True}
    h = gated_ir(sr, p, seed=seed) if p["mode"] == "nonlin" else render_ir(sr, {**p, "size_m": 25}, seed=seed)
    wet = fft_convolve(_stereo(x), h, "same")
    stats = measure_ir(h, sr, p)
    if p["mode"] == "keyed":
        gp = dict(threshold_db=p["threshold_db"], hold_ms=p["hold_ms"], release_ms=p["release_ms"],
                  attack_ms=.1, ratio=100., range_db=-120., knee_db=0., hysteresis_db=0., stereo_link=True)
        gain, states = gate_gain(x, sr, gp)
        wet *= 10**(gain/20)
        stats["gate_closed_samples"] = int(np.sum(states == 0))
    if x.shape[1] == 1:
        wet = wet.mean(axis=1, keepdims=True)
    else:
        mid = wet.mean(axis=1, keepdims=True)
        wet = mid+p["width"]*(wet-mid)
    stats["execution"] = "lti" if p["mode"] == "nonlin" else "tv_keyed"
    return finish(x, wet, sr, p, stats)


SPECS = [definition("reverb_gated", rv_params(sd=True) + [
    _e("mode", ["nonlin", "keyed"], "nonlin", "IR envelope or keyed return."),
    _f("gate_ms", "ms", 50, 1000, 250, "Nonlinear IR length."),
    _e("note", NOTE_VALUES, "none", "Tempo-synchronised gate duration."),
    _e("shape", ["flat", "decay", "ramp_up"], "flat", "IR envelope."),
    _f("density", None, 0, 1, .8, "Velvet pulse density."),
    _f("damping_hz", "Hz", 1000, 20000, 8000, "IR damping."),
    _f("width", None, 0, 1, 1, "Stereo width."),
    _f("threshold_db", "dBFS", -60, 0, -30, "Dry key gate threshold."),
    _f("hold_ms", "ms", 10, 1000, 150, "Gate hold."),
    _f("release_ms", "ms", 5, 500, 30, "Gate release time constant."),
])]
IMPLS = {"reverb_gated": reverb_gated}
TIME_VARYING = {"reverb_gated"}
CROSS_VALIDATE = {"reverb_gated": cross_validate}
