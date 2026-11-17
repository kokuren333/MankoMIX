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
- Times are milliseconds; delay / reverb also take a note value at a BPM (R-11).
- ``aw.*`` types are the Airwindows ports of the native core (backend
  ``native`` only). Their parameter ids mirror the native processor JSON; a
  chain step may declare a ``fallback`` reference processor used when the
  native library is unavailable (the record shows what actually ran).
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

# Note values for time parameters (R-11): "1/4" quarter, "d" dotted (x1.5), "t" triplet (x2/3).
NOTE_VALUES = ["none"] + [f"1/{d}{m}" for d in (1, 2, 4, 8, 16, 32, 64) for m in ("", "d", "t")]

_AIRWINDOWS_ORIGIN = {"source": "airwindows", "license": "MIT",
                      "repository": "https://github.com/airwindows/airwindows",
                      "notice": "third_party/airwindows/LICENSE, third_party/airwindows/ORIGIN.md"}


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
        "implemented": True,
        "description": "Dynamic EQ band for intermittent problems (R-13). y = x + (G(t)-1) * B(x) with "
                       "B the band-pass (peak) or 2nd-order Butterworth low/high-pass (shelves): a "
                       "minimum-phase peaking/shelving filter at every instant. The band's own RMS "
                       "(linked) drives G: above threshold the band is pulled toward the threshold "
                       "until |range_db| is used up (range < 0 cuts, > 0 boosts). Below threshold "
                       "the output is the input, bit for bit.",
        "params": [
            _e("shape", ["peak", "low_shelf", "high_shelf"], "peak", "Band shape."),
            _f("freq_hz", "Hz", 10.0, 24000.0, 1000.0, "Center frequency (shelves: corner)."),
            _f("bw_oct", "oct", 0.02, 6.0, 1.0,
               "Bandwidth in octaves between the -3 dB points of the band-pass (peak only)."),
            _f("range_db", "dB", -24.0, 24.0, -3.0, "Maximum gain change (negative = cut)."),
            _f("threshold_db", "dBFS", -80.0, 0.0, -30.0, "Band detector threshold (band RMS)."),
            _f("attack_ms", "ms", 0.1, 200.0, 5.0, "Attack time."),
            _f("release_ms", "ms", 5.0, 2000.0, 120.0, "Release time."),
        ],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 2,
        "backends": ["reference", "native"],
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
        "backends": ["reference", "native"],
    },
    {
        "type": "deesser",
        "implemented": True,
        "description": "Split-band sibilance control: only the detector band (band-pass at freq_hz, "
                       "bw_oct) is reduced, minimum phase, by up to range_db while its RMS exceeds "
                       "the threshold. The default band covers about 4.6-9.2 kHz.",
        "params": [
            _f("freq_hz", "Hz", 2000.0, 16000.0, 6500.0, "Detector band center."),
            _f("bw_oct", "oct", 0.1, 4.0, 1.0, "Detector bandwidth in octaves."),
            _f("threshold_db", "dBFS", -80.0, 0.0, -30.0, "Threshold (band RMS)."),
            _f("range_db", "dB", 0.0, 24.0, 6.0, "Maximum reduction."),
            _f("attack_ms", "ms", 0.1, 50.0, 1.0, "Attack time."),
            _f("release_ms", "ms", 5.0, 500.0, 60.0, "Release time."),
        ],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 2,
        "backends": ["reference", "native"],
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
        "implemented": True,
        "description": "Deterministic true-stereo algorithmic reverb (early-reflection taps, all-pass "
                       "diffusers, 8-line Hadamard FDN with per-band absorption) rendered to an "
                       "impulse response and applied by FFT convolution. Described by measured "
                       "vectors (RT60 per band, ER/late, D/R, mono loss) recorded from its own "
                       "impulse response (R-10). mix = 1 is the 100 % wet mode for send buses.",
        "params": [
            _f("rt60_s", "s", 0.1, 10.0, 1.5, "Mid-band decay time (250 Hz - 4 kHz)."),
            _f("predelay_ms", "ms", 0.0, 250.0, 20.0, "Pre-delay."),
            _f("er_late_db", "dB", -24.0, 24.0, 0.0, "Early/late energy ratio."),
            _f("mix", "0..1", 0.0, 1.0, 0.2, "Wet mix: y = (1-mix)*dry + mix*wet (1 = send, 100 % wet)."),
            _f("lowcut_hz", "Hz", 20.0, 2000.0, 600.0, "Return low cut (12 dB/oct)."),
            _f("highcut_hz", "Hz", 1000.0, 20000.0, 6000.0,
               "Return high cut (12 dB/oct; not applied at or above 0.45 x sample rate)."),
            _f("rt60_low_mult", "x", 0.1, 4.0, 1.0, "RT60 multiplier below 250 Hz."),
            _f("rt60_high_mult", "x", 0.1, 4.0, 0.7, "RT60 multiplier above 4 kHz."),
            _f("bpm", "BPM", 0.0, 400.0, 0.0,
               "Tempo used only to record pre-delay / RT60 as note values (R-11); 0 = unknown."),
        ],
        "realtime": _rt(True, 0, True, "offline: FFT convolution with the rendered IR; the tail "
                                       "beyond the end of the input is not rendered"),
        "offline_only": False,
        "stages": ["track", "bus"],
        "master_slot": None,
        "backends": ["reference"],
    },
    {
        "type": "delay",
        "implemented": True,
        "description": "Feedback delay with an exact integer sample delay from time_ms or a note "
                       "value at bpm (R-11). Band-limit filters act on the wet input (every repeat "
                       "has the same band). route puts the wet signal on one channel for Haas "
                       "widening. The Haas region (localisation / fusion / echo) is reported with "
                       "the mono fold-down loss (R-10).",
        "params": [
            _f("time_ms", "ms", 0.1, 4000.0, 250.0, "Delay time (used when note = none)."),
            _f("feedback", "0..1", 0.0, 0.95, 0.2, "Feedback."),
            _f("mix", "0..1", 0.0, 1.0, 0.2, "Wet mix: y = (1-mix)*dry + mix*wet."),
            _e("note", NOTE_VALUES, "none",
               "Note value (quarter note = one beat; d = dotted, t = triplet). Overrides time_ms; "
               "needs bpm."),
            _f("bpm", "BPM", 0.0, 400.0, 0.0, "Tempo for note values (0 = unknown)."),
            _f("lowcut_hz", "Hz", 0.0, 2000.0, 0.0, "Wet low cut, 12 dB/oct (0 = off)."),
            _f("highcut_hz", "Hz", 0.0, 24000.0, 0.0, "Wet high cut, 12 dB/oct (0 = off)."),
            _e("route", ["both", "left", "right"], "both",
               "Channels that receive the wet signal (stereo input only)."),
        ],
        "realtime": _rt(True, 0, True),
        "offline_only": False,
        "stages": ["track", "bus"],
        "master_slot": None,
        "backends": ["reference"],
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

# Airwindows ports in the native core (dsp/native/). Parameter ids, units, ranges and defaults
# mirror the native processor JSON (checked by tests/test_dsp_native_wiring.py). "fallback" names
# the reference processor a chain step may fall back to (dsp/native_wiring.py maps the params).
_NATIVE_PROCESSORS: list[dict[str, Any]] = [
    {
        "type": "aw.purest_drive",
        "implemented": True,
        "description": "Airwindows PurestDrive: program-dependent sine saturation (saturates less on "
                       "low-level or polarity-reversing material). 0 = transparent.",
        "params": [_f("drive", "norm", 0.0, 1.0, 0.0, "Drive (original knob scale 0..1).")],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 3,
        "backends": ["native"],
        "abstract_type": "saturator",
        "native": {"id": "aw.purest_drive", "role": "channel_drive",
                   "origin": {**_AIRWINDOWS_ORIGIN, "plugin": "PurestDrive"}},
        "fallback": {"type": "saturator",
                     "mapping": "mode=tanh, drive_db=0, mix=drive (sine blend approximated by tanh)"},
    },
    {
        "type": "aw.clip_only2",
        "implemented": True,
        "description": "Airwindows ClipOnly2: safety clipper that rounds the corner just below the "
                       "ceiling; below the ceiling only a one-sample delay (compensated offline).",
        "params": [
            _f("input_gain_db", "dB", -24.0, 24.0, 0.0, "Gain before the clipper."),
            _f("ceiling_db", "dBFS", -24.0, 0.0, -0.4, "Clip ceiling."),
        ],
        "realtime": _rt(True, 1, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 5,
        "backends": ["native"],
        "abstract_type": "clipper",
        "native": {"id": "aw.clip_only2", "role": "safety_clipper",
                   "origin": {**_AIRWINDOWS_ORIGIN, "plugin": "ClipOnly2"}},
        "fallback": {"type": "clipper",
                     "mapping": "mode=soft, softness=0.1, ceiling_db=ceiling_db, "
                                "drive_db=max(input_gain_db, 0) (negative input gain is dropped)"},
    },
    {
        "type": "aw.console7_channel",
        "implemented": True,
        "description": "Airwindows Console7Channel: first half of the Console7 summing pair (per "
                       "channel, or on the 2mix before aw.console7_buss).",
        "params": [_f("fader", "norm", 0.0, 1.0, 0.772,
                      "Channel fader (original knob). 0.772 = unity for a full-scale sine through "
                      "the Console7 pair.")],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 3,
        "backends": ["native"],
        "abstract_type": "saturator",
        "native": {"id": "aw.console7_channel", "role": "console_channel",
                   "origin": {**_AIRWINDOWS_ORIGIN, "plugin": "Console7Channel"}},
        "fallback": {"type": "gain",
                     "mapping": "gain_db = 20*log10((fader*1.272019649514069)^2) (small-signal "
                                "gain; saturation dropped)"},
    },
    {
        "type": "aw.console7_buss",
        "implemented": True,
        "description": "Airwindows Console7Buss: second half of the Console7 pair (after summing). "
                       "channel -> buss at defaults is near unity gain.",
        "params": [_f("master", "norm", 0.0, 1.0, 1.0, "Buss master (original knob).")],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 3,
        "backends": ["native"],
        "abstract_type": "saturator",
        "native": {"id": "aw.console7_buss", "role": "console_buss",
                   "origin": {**_AIRWINDOWS_ORIGIN, "plugin": "Console7Buss"}},
        "fallback": {"type": "gain",
                     "mapping": "gain_db = 20*log10(master*1.03) (small-signal gain; saturation "
                                "dropped)"},
    },
    {
        "type": "aw.pressure4",
        "implemented": True,
        "description": "Airwindows Pressure4: linked vari-mu style bus compressor with a sine "
                       "output stage (output within +-1). At the default mewiness = +1 it RAISES "
                       "the crest factor; the measured crest change is recorded, never assumed.",
        "params": [
            _f("pressure", "norm", 0.0, 1.0, 0.0, "Amount of compression (0 = off)."),
            _f("speed", "norm", 0.0, 1.0, 0.2, "Release speed."),
            _f("mewiness", "bipolar", -1.0, 1.0, 1.0, "Character (+1 default raises crest factor)."),
            _f("output_gain", "linear", 0.0, 1.0, 1.0, "Output gain (linear)."),
        ],
        "realtime": _rt(True, 0, False),
        "offline_only": False,
        "stages": ["track", "bus", "master"],
        "master_slot": 2,
        "backends": ["native"],
        "abstract_type": "compressor",
        "native": {"id": "aw.pressure4", "role": "vari_mu_bus",
                   "origin": {**_AIRWINDOWS_ORIGIN, "plugin": "Pressure4"}},
        "fallback": {"type": "compressor",
                     "mapping": "threshold_db=-6-24*pressure, ratio=1+5*pressure, knee_db=12, "
                                "attack_ms=10, release_ms=40+460*(1-speed), detector=rms, "
                                "makeup_db=20*log10(output_gain) (mewiness ignored)"},
    },
]
_PROCESSORS += _NATIVE_PROCESSORS

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
    if type in ("delay", "reverb") and 0.0 < p["bpm"] < 20.0:
        raise ParamError(f"{type}: bpm must be 0 (unknown) or >= 20")
    if type == "delay" and p["note"] != "none":
        if p["bpm"] <= 0.0:
            raise ParamError("delay: a note value needs bpm > 0")
        ms = note_ms(p["note"], p["bpm"])
        if ms > 4000.0:
            raise ParamError(f"delay: note {p['note']} at {p['bpm']} BPM is {ms:.1f} ms (> 4000 ms)")
    if type == "stereo":
        xs = p["crossovers_hz"]
        if any(b <= a for a, b in zip(xs, xs[1:])):
            raise ParamError("stereo: crossovers_hz must be strictly ascending")
        if xs and p["mono_below_hz"] > 0 and xs[0] <= p["mono_below_hz"]:
            raise ParamError("stereo: crossovers_hz must lie above mono_below_hz")
        if p["widths"] and len(p["widths"]) != len(xs) + 1:
            raise ParamError("stereo: widths must have len(crossovers_hz) + 1 items")


def note_ms(note: str, bpm: float) -> float:
    """Duration in ms of a note value at ``bpm`` (quarter note = one beat), e.g. "1/8d"."""
    if note not in NOTE_VALUES or note == "none":
        raise ParamError(f"unknown note value {note!r}")
    body = note[2:]
    mod = 1.0
    if body.endswith("d"):
        mod, body = 1.5, body[:-1]
    elif body.endswith("t"):
        mod, body = 2.0 / 3.0, body[:-1]
    return 4.0 * 60000.0 / bpm / int(body) * mod


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
                "fallback": {"oneOf": [
                    {"type": "string"},
                    {"type": "object", "properties": {"type": {"type": "string"},
                                                      "params": {"type": "object"}},
                     "required": ["type"], "additionalProperties": False}]},
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


# Additive extension registration and BB-00 contracts; original definitions stay intact.
from mankomix.dspx import contracts as _xcontracts, registry as _xregistry

for _spec in _xregistry.specs():
    if _spec["type"] in PROCESSORS:
        raise ImportError(f"duplicate processor type: {_spec['type']}")
    _spec["schema_version"] = SCHEMA_VERSION
    PROCESSORS[_spec["type"]] = _spec

_validate_params_base = validate_params
_param_schema_base = _param_schema
_graph_schema_base = graph_schema


def validate_params(type: str, params: dict | None) -> dict:
    return _xcontracts.validate_params(type, params, _validate_params_base)


def _param_schema(spec: dict) -> dict:
    return _xcontracts.param_schema(spec, _param_schema_base)


def graph_schema() -> dict:
    return _xcontracts.graph_schema(_graph_schema_base)
