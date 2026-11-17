"""Cabinet IR preparation and dual-microphone blending over BB-08/07."""
import numpy as np
from mankomix.dspx.params import _f, _e
from mankomix.dsp.errors import ParamError


def cab_ir(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.ir import load_ir, prepare_ir, kernel, ir_stats
    from mankomix.dspx.bb.delayline import fractional_delay, LoopFilter
    h, stats = load_ir(p["ir"], sr)
    b = None
    if p["ir_b"]:
        b, second = load_ir(p["ir_b"], sr)
        stats["asset_b"] = second
    if not p["mix"]:
        return x.copy(), sr, dict(stats, latency_samples=0, bypass=True)
    opts = dict(length_s=p["length_ms"]/1000, gain_mode=p["gain_mode"], phase=p["phase"])
    h = prepare_ir(h, sr, **opts)
    def matrix(coeff):
        k = kernel(coeff, x.shape[1])
        if k.ndim == 1:
            k = k[:, None, None]*np.eye(x.shape[1])[None]
        elif k.ndim == 2:
            k = k[:, :, None]*np.eye(x.shape[1])[None]
        return k
    effective = matrix(h)
    if b is not None:
        b = prepare_ir(b, sr, **opts)
        second = matrix(b)
        count = max(len(effective), len(second)+int(np.ceil(p["b_delay_ms"]*sr/1000))+4)
        effective = np.pad(effective, ((0, count-len(effective)), (0, 0), (0, 0)))
        second = np.pad(second, ((0, count-len(second)), (0, 0), (0, 0)))
        # A mono path expands symmetrically when the other asset is stereo.
        outputs = max(effective.shape[2], second.shape[2])
        if effective.shape[2] != outputs:
            effective = np.repeat(effective, outputs, axis=2)
        if second.shape[2] != outputs:
            second = np.repeat(second, outputs, axis=2)
        flat = second.reshape(count, -1)
        second = fractional_delay(flat, p["b_delay_ms"]*sr/1000, "sinc8").reshape(second.shape)
        effective = (1-p["blend"])*effective+p["blend"]*second
    if p["lowcut_hz"] or (0 < p["highcut_hz"] < .45*sr):
        # Retain the wet filter response even when the source IR is one sample.
        effective = np.pad(effective, ((0, round(.5*sr)), (0, 0), (0, 0)))
    shape = effective.shape
    effective = LoopFilter(sr, shape[1]*shape[2], p["lowcut_hz"],
                          p["highcut_hz"] if p["highcut_hz"] < .45*sr else 0)(effective.reshape(len(effective), -1)).reshape(shape)
    from mankomix.dspx.bb.fir import fft_convolve
    wet = fft_convolve(x, effective, "same")
    dry = x if wet.shape[1] == x.shape[1] else np.repeat(x, 2, axis=1)
    measurement = effective
    if effective.shape[2] == 1:
        measurement = np.repeat(effective, 2, axis=2)
    stats.update(ir_stats(measurement, sr, p), latency_samples=0, phase=p["phase"],
                 blend=p["blend"], b_delay_ms=p["b_delay_ms"], tail_truncated_at_end=True)
    return (1-p["mix"])*dry+p["mix"]*wet, sr, stats


def cross_validate(p):
    from mankomix.dspx.assets import resolve
    for key in ("ir", "ir_b"):
        if p[key] and resolve("irs", p[key]).get("kind", "room") != "cabinet":
            raise ParamError("cab_ir requires kind cabinet")


def _spec():
    from mankomix.dspx.bb.reverb import definition
    # Keep definition modules independent; do not import another processor.
    def asset(id, default, empty=False):
        return {"id": id, "type": "asset", "registry": "irs", "unit": None,
                "default": default, "allow_empty": empty, "description": "Registered cabinet IR ID."}
    spec = definition("cab_ir", [asset("ir", "synth_cab_a"),
        _f("length_ms", "ms", 5, 500, 200, "Maximum cabinet IR length."),
        _e("phase", ["as_is", "minimum"], "as_is", "Real-cepstrum minimum phase."),
        asset("ir_b", "", True), _f("blend", None, 0, 1, 0, "Second IR weight."),
        _f("b_delay_ms", "ms", 0, 5, 0, "Second microphone delay."),
        _f("lowcut_hz", "Hz", 0, 500, 0, "Wet highpass; zero bypasses."),
        _f("highcut_hz", "Hz", 0, 20000, 0, "Wet lowpass; zero bypasses."),
        _e("gain_mode", ["energy", "peak", "none"], "energy", "IR normalization."),
        _f("mix", None, 0, 1, 1, "Dry/wet mix.")], implemented=True)
    spec["channel_ok"] = True
    return spec


SPECS = [_spec()]
IMPLS = {"cab_ir": cab_ir}
CROSS_VALIDATE = {"cab_ir": cross_validate}
