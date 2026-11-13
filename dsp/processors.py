"""Abstract processor definitions, kept as data (SPEC 6.5.2, 14.2).

Every processor declares stable parameter IDs with unit, range and default,
its realtime suitability (block processing, latency, allocation while
processing), whether it is offline-only, and the stages it may run in. The
definitions are the shared contract between the offline renderer, the project
file and a future plugin shell: parameter IDs never change across versions.

Representation rules that are enforced here:

- EQ bandwidth is held in octaves, never Q (R-12). Default phase is minimum.
- Times are milliseconds (R-11: callers may additionally record note values).
- Pan law is defined by the measured center attenuation (default -3 dB).
- ``limiter`` runs only as the final step of the mastering stage (S-06).
- ``loudness_gain`` / ``resample`` / ``dither`` belong to the export module.
  ``loudness_gain`` is additionally accepted in the mastering stage as the
  limiter drive (slot 5 of the fixed order, SPEC 6.6.2).
"""

from __future__ import annotations

import copy
import math
from typing import Any

from .errors import ParamError

SCHEMA_VERSION = 1

STAGES = ("track", "bus", "master", "export")

# Fixed mastering order (SPEC 6.6.2, S-06). Slot numbers follow the SPEC list.
MASTER_SLOTS = {
    1: "corrective_eq",
    2: "dynamics",
    3: "enhance",
    4: "stereo_image",
    5: "loudness_reach",
    6: "true_peak_limiter",
}

# Order inside the export module (SPEC 5.3, 6.6.2 step 7).
EXPORT_SLOTS = {1: "loudness_gain", 2: "resample", 3: "dither"}


def _f(pid, unit, lo, hi, default, desc):
    return {"id": pid, "type": "float", "unit": unit, "min": lo, "max": hi, "default": default,
            "description": desc}


def _i(pid, unit, lo, hi, default, desc):
    return {"id": pid, "type": "int", "unit": unit, "min": lo, "max": hi, "default": default,
            "description": desc}


def _e(pid, choices, default, desc, unit=None):
    return {"id": pid, "type": "enum", "unit": unit, "choices": list(choices), "default": default,
            "description": desc}


def _b(pid, default, desc):
    return {"id": pid, "type": "bool", "unit": None, "default": default, "description": desc}


def _a(pid, unit, lo, hi, max_len, default, desc):
    return {"id": pid, "type": "float_array", "unit": unit, "min": lo, "max": hi, "max_len": max_len,
            "default": list(default), "description": desc}


def _rt(block_ok, latency, allocates, rule=None):
    d = {"block_ok": block_ok, "latency_samples": latency, "allocates": allocates}
    if rule:
        d["latency_rule"] = rule
    return d


_PROCESSORS: list[dict[str, Any]] = [
    {
        "type": "gain",
        "implemented": True,
        "description": "Static gain (trim).",
        "params": [_f("gain_db", "dB", -60.0, 24.0, 0.0, "Gain in decibels.")],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": None,   # neutral: allowed anywhere before the limiter
        "backends": ["reference"],
    },
    {
        "type": "pan",
        "implemented": True,
        "description": "Constant-power pan law defined by its center attenuation. Mono input is "
                       "panned to stereo; stereo input is balanced (the far side is attenuated).",
        "params": [
            _f("position", "-1..1", -1.0, 1.0, 0.0, "-1 = hard left, 0 = center, +1 = hard right."),
            _f("center_db", "dB", -6.0, 0.0, -3.0,
               "Per-channel attenuation at center for a mono source (-3 = constant power, "
               "-6 = linear-sum law, 0 = balance law)."),
        ],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus"],
        "master_slot": None,
        "backends": ["reference"],
    },
    {
        "type": "filter",
        "implemented": True,
        "description": "Butterworth high/low-pass filter, minimum phase. The phase cost is recorded.",
        "params": [
            _e("kind", ["hpf", "lpf"], "hpf", "Filter kind."),
            _f("freq_hz", "Hz", 10.0, 24000.0, 30.0, "Cutoff (-3 dB point). Must be below Nyquist."),
            _e("slope_db_oct", [6, 12, 18, 24, 48], 12, "Slope in dB per octave.", unit="dB/oct"),
        ],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 1,
        "backends": ["reference"],
    },
    {
        "type": "eq",
        "implemented": True,
        "description": "One parametric band (RBJ cookbook biquads). Bandwidth in octaves (R-12). "
                       "Minimum phase by default; linear phase is an FIR whose pre-ringing is "
                       "recorded and is meant only for small cuts (SPEC 6.6.3).",
        "params": [
            _e("shape", ["peak", "low_shelf", "high_shelf", "notch"], "peak", "Band shape."),
            _f("freq_hz", "Hz", 10.0, 24000.0, 1000.0, "Center / corner frequency."),
            _f("gain_db", "dB", -24.0, 24.0, 0.0, "Band gain (ignored by notch)."),
            _f("bw_oct", "oct", 0.02, 6.0, 1.0,
               "Bandwidth in octaves. peak: between the half-gain (dB) points; notch: between "
               "the -3 dB points; shelves: transition width (1.9 oct ~ Q 0.707, no overshoot)."),
            _e("phase", ["minimum", "linear"], "minimum", "Phase mode."),
        ],
        "realtime": _rt(True, 0, False, "phase=linear: (fir_taps-1)/2 samples"),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 1,
        "backends": ["reference"],
    },
    {
        "type": "dynamic_eq",
        "implemented": False,
        "description": "Dynamic EQ band for intermittent problems (R-13). Declared only (not in M2).",
        "params": [
            _e("shape", ["peak", "low_shelf", "high_shelf"], "peak", "Band shape."),
            _f("freq_hz", "Hz", 10.0, 24000.0, 1000.0, "Center frequency."),
            _f("bw_oct", "oct", 0.02, 6.0, 1.0, "Bandwidth in octaves."),
            _f("range_db", "dB", -24.0, 24.0, -3.0, "Maximum gain change."),
            _f("threshold_db", "dBFS", -80.0, 0.0, -30.0, "Band detector threshold."),
            _f("attack_ms", "ms", 0.1, 200.0, 5.0, "Attack time."),
            _f("release_ms", "ms", 5.0, 2000.0, 120.0, "Release time."),
        ],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 2,
        "backends": [],
    },
    {
        "type": "compressor",
        "implemented": True,
        "description": "Feed-forward single-band compressor, stereo linked, soft knee, gain "
                       "smoothing in the dB domain (decoupled attack/release).",
        "params": [
            _f("threshold_db", "dBFS", -60.0, 0.0, -18.0, "Threshold."),
            _f("ratio", ":1", 1.0, 30.0, 2.0, "Compression ratio."),
            _f("knee_db", "dB", 0.0, 24.0, 6.0, "Knee width (0 = hard knee)."),
            _f("attack_ms", "ms", 0.05, 300.0, 10.0, "Attack time constant."),
            _f("release_ms", "ms", 5.0, 3000.0, 150.0, "Release time constant."),
            _e("detector", ["peak", "rms"], "rms", "Level detector."),
            _f("rms_window_ms", "ms", 1.0, 300.0, 10.0, "RMS detector window."),
            _f("makeup_db", "dB", -12.0, 24.0, 0.0, "Makeup gain."),
            _b("stereo_link", True, "Link the detector across channels."),
        ],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 2,
        "backends": ["reference"],
    },
    {
        "type": "deesser",
        "implemented": False,
        "description": "Sibilance control. Declared only (not in M2).",
        "params": [
            _f("freq_hz", "Hz", 2000.0, 16000.0, 6500.0, "Detector band center."),
            _f("bw_oct", "oct", 0.1, 4.0, 1.0, "Detector bandwidth in octaves."),
            _f("threshold_db", "dBFS", -80.0, 0.0, -30.0, "Threshold."),
            _f("range_db", "dB", 0.0, 24.0, 6.0, "Maximum reduction."),
        ],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 2,
        "backends": [],
    },
    {
        "type": "saturator",
        "implemented": True,
        "description": "Waveshaping saturation (tanh or biased-tanh asymmetric), 4x oversampled. "
                       "The harmonic character (even/odd) is measured and recorded, never assumed.",
        "params": [
            _f("drive_db", "dB", 0.0, 36.0, 6.0, "Input drive into the curve (small-signal gain stays 1)."),
            _e("mode", ["tanh", "asymmetric"], "tanh", "Curve."),
            _f("asymmetry", "0..1", 0.0, 1.0, 0.3, "Bias for the asymmetric curve (even harmonics)."),
            _f("mix", "0..1", 0.0, 1.0, 1.0, "Wet/dry mix."),
            _f("output_db", "dB", -24.0, 12.0, 0.0, "Output gain."),
            _e("oversample", [1, 2, 4, 8], 4, "Oversampling factor.", unit="x"),
        ],
        "realtime": _rt(True, 0, False, "oversample>1: half the polyphase FIR length"),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 3,
        "backends": ["reference"],
    },
    {
        "type": "clipper",
        "implemented": True,
        "description": "Hard or soft clipper on an oversampled signal to limit aliasing.",
        "params": [
            _e("mode", ["hard", "soft"], "soft", "Clip curve."),
            _f("ceiling_db", "dBFS", -24.0, 0.0, -0.5, "Clip level (sample domain of the oversampled signal)."),
            _f("drive_db", "dB", 0.0, 24.0, 0.0, "Gain before clipping."),
            _f("softness", "0..1", 0.0, 1.0, 0.3, "Soft mode: fraction of the ceiling used as knee."),
            _e("oversample", [1, 2, 4, 8], 4, "Oversampling factor.", unit="x"),
        ],
        "realtime": _rt(True, 0, False, "oversample>1: half the polyphase FIR length"),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 5,
        "backends": ["reference"],
    },
    {
        "type": "stereo",
        "implemented": True,
        "description": "Band-split M/S width. Side is split with linear-phase complementary FIR "
                       "crossovers (perfect reconstruction); Mid is untouched. Below mono_below_hz "
                       "the side is removed; above it each band gets its own width (vector).",
        "params": [
            _f("mono_below_hz", "Hz", 0.0, 500.0, 0.0, "Side removed below this frequency (0 = off)."),
            _f("width", "x", 0.0, 2.0, 1.0, "Side multiplier above the mono split (when widths is empty)."),
            _a("crossovers_hz", "Hz", 20.0, 20000.0, 8, [], "Additional band edges above mono_below_hz."),
            _a("widths", "x", 0.0, 2.0, 9, [],
               "Per-band side multipliers above mono_below_hz (len = len(crossovers_hz) + 1)."),
        ],
        "suggested": {"mono_below_hz": 120.0, "crossovers_hz": [4000.0], "widths": [1.0, 1.1],
                      "note": "SPEC 6.6.3: low bands narrow, high bands wider. Initial values."},
        "realtime": _rt(True, 0, False, "(fir_taps-1)/2 samples of the crossover FIR"),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 4,
        "backends": ["reference"],
    },
    {
        "type": "reverb",
        "implemented": False,
        "description": "Reverb described by measured vectors (RT60 per band, ER/late, D/R) (R-10). Declared only.",
        "params": [
            _f("rt60_s", "s", 0.1, 10.0, 1.5, "Mid-band decay time."),
            _f("predelay_ms", "ms", 0.0, 250.0, 20.0, "Pre-delay."),
            _f("er_late_db", "dB", -24.0, 24.0, 0.0, "Early/late ratio."),
            _f("mix", "0..1", 0.0, 1.0, 0.2, "Wet mix."),
            _f("lowcut_hz", "Hz", 20.0, 2000.0, 600.0, "Return low cut."),
            _f("highcut_hz", "Hz", 1000.0, 20000.0, 6000.0, "Return high cut."),
        ],
        "realtime": _rt(True, 0, True),
        "offline_only": False,
        "stages": ["track", "bus"],
        "master_slot": None,
        "backends": [],
    },
    {
        "type": "delay",
        "implemented": False,
        "description": "Delay; Haas region (localisation / fusion / echo) is explicit (R-10). Declared only.",
        "params": [
            _f("time_ms", "ms", 0.1, 4000.0, 250.0, "Delay time."),
            _f("feedback", "0..1", 0.0, 0.95, 0.2, "Feedback."),
            _f("mix", "0..1", 0.0, 1.0, 0.2, "Wet mix."),
        ],
        "realtime": _rt(True, 0, True),
        "offline_only": False,
        "stages": ["track", "bus"],
        "master_slot": None,
        "backends": [],
    },
    {
        "type": "limiter",
        "implemented": True,
        "description": "True-peak limiter: oversampled peak detection, lookahead, smooth gain "
                       "envelope; the output true peak is verified by re-measurement. Mastering "
                       "final step only (S-06). Latency is compensated in offline rendering.",
        "params": [
            _f("ceiling_dbtp", "dBTP", -12.0, 0.0, -1.0, "True-peak ceiling."),
            _f("lookahead_ms", "ms", 1.0, 10.0, 3.0, "Lookahead (typ. 1.5-5 ms)."),
            _f("release_ms", "ms", 5.0, 2000.0, 100.0, "Release time constant."),
            _e("oversample", [4, 8, 16], 8,
               "Detector oversampling factor (>= 4, BS.1770; raised so the detector runs at "
               ">= 192 kHz). Detection and verification use the same detector; 8x reads at or "
               "above common 4x meters.", unit="x"),
        ],
        "realtime": _rt(True, 0, False, "round(lookahead_ms * sr / 1000) samples (+ detector FIR)"),
        "offline_only": False,
        "stages": ["master"],
        "master_slot": 6,
        "position": "final",
        "backends": ["reference"],
    },
    {
        "type": "loudness_gain",
        "implemented": True,
        "description": "Static gain by dB to reach loudness. Export module; in the mastering "
                       "stage only as limiter drive (slot 5).",
        "params": [_f("gain_db", "dB", -60.0, 40.0, 0.0, "Gain in decibels.")],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["master", "export"],
        "master_slot": 5,
        "export_slot": 1,
        "backends": ["reference"],
    },
    {
        "type": "resample",
        "implemented": True,
        "description": "Sample-rate conversion. Reference: scipy resample_poly with a Kaiser "
                       "window FIR (~120 dB stopband). ffmpeg: aresample (swr). Export module only.",
        "params": [_i("target_sr", "Hz", 8000, 768000, 44100, "Output sample rate.")],
        "realtime": _rt(False, 0, True, "rate change: not a block processor"),
        "offline_only": True,
        "stages": ["export"],
        "master_slot": None,
        "export_slot": 2,
        "backends": ["reference", "ffmpeg"],
    },
    {
        "type": "dither",
        "implemented": True,
        "description": "TPDF dither (+-1 LSB) and quantisation, applied once at the final export "
                       "when word length decreases. No noise shaping. Seeded RNG (PCG64) with a "
                       "seed derived from the project (SPEC 9.6). Nothing may follow (S-05).",
        "params": [
            _e("bit_depth", [16, 24], 16, "Target word length.", unit="bit"),
            _e("type", ["tpdf"], "tpdf", "Dither PDF."),
            _e("noise_shaping", ["none"], "none", "Noise shaping (SPEC 5.3: none by default)."),
        ],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["export"],
        "master_slot": None,
        "export_slot": 3,
        "position": "final",
        "backends": ["reference"],
    },
]

PROCESSORS: dict[str, dict[str, Any]] = {p["type"]: p for p in _PROCESSORS}
for _p in _PROCESSORS:
    _p["schema_version"] = SCHEMA_VERSION


def processor_types(*, implemented_only: bool = False) -> list[str]:
    return [t for t, p in PROCESSORS.items() if p["implemented"] or not implemented_only]


def describe(type: str) -> dict:
    """Return a deep copy of the processor definition (raises ValueError if unknown)."""
    if type not in PROCESSORS:
        raise ParamError(f"unknown processor type: {type!r}")
    return copy.deepcopy(PROCESSORS[type])


def _num(v, pid, ptype):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ParamError(f"parameter {pid!r} must be a number, got {type(v).__name__}")
    if not math.isfinite(float(v)):
        raise ParamError(f"parameter {pid!r} must be finite")
    if ptype == "int":
        if float(v) != int(v):
            raise ParamError(f"parameter {pid!r} must be an integer")
        return int(v)
    return float(v)


def _check_range(v, spec, pid):
    if v < spec["min"] or v > spec["max"]:
        raise ParamError(f"parameter {pid!r}={v} out of range [{spec['min']}, {spec['max']}] "
                         f"({spec.get('unit') or 'no unit'})")


def validate_params(type: str, params: dict | None) -> dict:
    """Validate and normalise parameters; fill defaults.

    Raises ValueError (ParamError) on unknown processor, unknown parameter IDs,
    wrong types or out-of-range values.
    """
    if type not in PROCESSORS:
        raise ParamError(f"unknown processor type: {type!r}")
    params = dict(params or {})
    spec_by_id = {s["id"]: s for s in PROCESSORS[type]["params"]}
    unknown = sorted(set(params) - set(spec_by_id))
    if unknown:
        raise ParamError(f"{type}: unknown parameter(s) {unknown}; known: {sorted(spec_by_id)}")
    out: dict[str, Any] = {}
    for pid, spec in spec_by_id.items():
        v = params.get(pid, spec["default"])
        t = spec["type"]
        if t in ("float", "int"):
            v = _num(v, pid, t)
            _check_range(v, spec, pid)
        elif t == "enum":
            match = [c for c in spec["choices"]
                     if c == v and not (isinstance(v, bool) or isinstance(c, bool))]
            if not match:
                raise ParamError(f"{type}: parameter {pid!r}={v!r} not in {spec['choices']}")
            v = match[0]
        elif t == "bool":
            if not isinstance(v, bool):
                raise ParamError(f"{type}: parameter {pid!r} must be a boolean")
        elif t == "float_array":
            if not isinstance(v, (list, tuple)):
                raise ParamError(f"{type}: parameter {pid!r} must be a list of numbers")
            if len(v) > spec["max_len"]:
                raise ParamError(f"{type}: parameter {pid!r} has more than {spec['max_len']} items")
            vv = []
            for item in v:
                item = _num(item, pid, "float")
                _check_range(item, spec, pid)
                vv.append(item)
            v = vv
        out[pid] = v
    _cross_validate(type, out)
    return out


def _cross_validate(type: str, p: dict) -> None:
    if type == "stereo":
        xs = p["crossovers_hz"]
        if any(b <= a for a, b in zip(xs, xs[1:])):
            raise ParamError("stereo: crossovers_hz must be strictly ascending")
        if xs and p["mono_below_hz"] > 0 and xs[0] <= p["mono_below_hz"]:
            raise ParamError("stereo: crossovers_hz must lie above mono_below_hz")
        if p["widths"] and len(p["widths"]) != len(xs) + 1:
            raise ParamError("stereo: widths must have len(crossovers_hz) + 1 items")


def check_runtime(type: str, params: dict, sr: int) -> None:
    """Checks that depend on the sample rate (frequencies below Nyquist)."""
    nyq = sr / 2.0
    freqs = []
    if type in ("filter", "eq", "dynamic_eq", "deesser"):
        freqs.append(params["freq_hz"])
    if type == "stereo":
        freqs += list(params["crossovers_hz"]) + [params["mono_below_hz"]]
    for f in freqs:
        if f >= nyq * 0.98:
            raise ParamError(f"{type}: frequency {f} Hz is too close to Nyquist ({nyq} Hz)")


# ---------------------------------------------------------------------------
# JSON Schema for a chain (shared contract, SPEC 14.2)
# ---------------------------------------------------------------------------

def _param_schema(spec: dict) -> dict:
    t = spec["type"]
    if t == "float":
        s = {"type": "number", "minimum": spec["min"], "maximum": spec["max"]}
    elif t == "int":
        s = {"type": "integer", "minimum": spec["min"], "maximum": spec["max"]}
    elif t == "enum":
        s = {"enum": list(spec["choices"])}
    elif t == "bool":
        s = {"type": "boolean"}
    else:
        s = {"type": "array", "maxItems": spec["max_len"],
             "items": {"type": "number", "minimum": spec["min"], "maximum": spec["max"]}}
    s["default"] = copy.deepcopy(spec["default"])
    s["description"] = spec["description"] + (f" [{spec['unit']}]" if spec.get("unit") else "")
    return s


def graph_schema() -> dict:
    """JSON Schema (draft 2020-12) describing a processor chain."""
    variants = []
    for t, p in PROCESSORS.items():
        variants.append({
            "type": "object",
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "type": {"const": t},
                "params": {
                    "type": "object",
                    "properties": {s["id"]: _param_schema(s) for s in p["params"]},
                    "additionalProperties": False,
                },
                "backend": {"enum": ["reference", "ffmpeg", "native"]},
                "bypass": {"type": "boolean"},
                "note": {"type": "string"},
            },
            "required": ["type"],
            "additionalProperties": False,
        })
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "mankomix/chain.schema.json",
        "title": "MankoMIX processor chain",
        "description": "Ordered list of abstract processors (SPEC 6.5.2). Stage rules: limiter is the "
                       "final mastering step (S-06); resample/dither belong to export; nothing "
                       "follows dither (S-05).",
        "x-schema-version": SCHEMA_VERSION,
        "type": "array",
        "items": {"oneOf": variants},
    }
