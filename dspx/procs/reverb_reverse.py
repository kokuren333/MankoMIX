"""Causal rising velvet IR or offline time-reversed finite FDN IR."""
import numpy as np

from mankomix.dspx.params import _e, _f
from mankomix.dspx.bb.curves import period_ms
from mankomix.dspx.bb.fir import fft_convolve
from mankomix.dspx.bb.reverb import (definition, rv_params, validate_rv, velvet_ir,
    render_ir, measure_ir, finish, _stereo, _wet_filter, NOTE_VALUES)


def cross_validate(p):
    validate_rv(p)
    period_ms(p["length_ms"], note=p["note"], bpm=p["bpm"])


def reverse_source_ir(sr, p, *, seed=0):
    """Finite forward source; filtering occurs before reversal and shifting."""
    duration = period_ms(p["length_ms"], note=p["note"], bpm=p["bpm"])
    n = max(1, round(duration*sr/1000))
    h = render_ir(sr, {**p, "predelay_ms": 0, "size_m": 6, "distance": 0}, chamber=True, seed=seed, frames=n)
    from mankomix.dspx.bb.delayline import LoopFilter
    return LoopFilter(sr, 4, 0, p["damping_hz"] if p["damping_hz"] < .45*sr else 0)(h.reshape(n, 4)).reshape(h.shape)


def reverb_reverse(x, sr, p, *, seed=0):
    cross_validate(p)
    if not p["mix"]:
        return x.copy(), sr, {"latency_samples": 0, "bypass": True}
    length = period_ms(p["length_ms"], note=p["note"], bpm=p["bpm"])
    if p["mode"] == "envelope":
        h = velvet_ir(sr, length, p, shape="ramp_up", seed=seed)
        h = _wet_filter(h.reshape(len(h), 4), sr, p).reshape(h.shape)
        fade = min(len(h), max(1, round(.005*sr)))
        h[-fade:] *= np.linspace(1, 0, fade)[:, None, None]
        wet = fft_convolve(_stereo(x), h, "same")
        lost_energy = 0.
    else:
        source = reverse_source_ir(sr, p, seed=seed)
        h = source[::-1].copy()
        advance = len(h)-1+round(p["gap_ms"]*sr/1000)
        full = fft_convolve(_stereo(x), h)
        lost_energy = float(np.sum(full[:min(advance, len(full))]**2))
        wet = np.zeros((len(x), 2))
        retained = full[advance:advance+len(x)]
        wet[:len(retained)] = retained
    if x.shape[1] == 1:
        wet = wet.mean(axis=1, keepdims=True)
    else:
        mid = wet.mean(axis=1, keepdims=True)
        wet = mid+p["width"]*(wet-mid)
    stats = measure_ir(h, sr, p)
    stats.update(execution="lti", noncausal=p["mode"] == "true", discarded_before_start_energy=lost_energy,
                 length_samples=len(h), gap_samples=round(p["gap_ms"]*sr/1000))
    return finish(x, wet, sr, p, stats)


SPECS = [definition("reverb_reverse", rv_params(pre=False) + [
    _e("mode", ["envelope", "true"], "envelope", "Causal rising IR or noncausal reverse."),
    _f("length_ms", "ms", 100, 4000, 800, "Reverse duration."),
    _e("note", NOTE_VALUES, "none", "Tempo-synchronised length."),
    _f("gap_ms", "ms", 0, 100, 0, "Gap before dry onset in true mode."),
    _f("density", None, 0, 1, .8, "Velvet pulse density."),
    _f("damping_hz", "Hz", 1000, 20000, 8000, "Source IR damping."),
    _f("width", None, 0, 1, 1, "Stereo width."),
], implemented=True, offline=True)]
IMPLS = {"reverb_reverse": reverb_reverse}
CROSS_VALIDATE = {"reverb_reverse": cross_validate}
