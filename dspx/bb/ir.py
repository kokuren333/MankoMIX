"""BB-08 IR synthesis, verified loading and preparation over BB-07/10.

synthetic_ir(id, sr=44100, seed=208) returns original float64 coefficients.
synthetic_bytes(...) returns reproducible PCM32 WAV bytes (the catalogue hash).
load_ir(id, sr) returns coefficients (frames, 1/2/4), public provenance stats.
prepare_ir(h, sr, ...) trims/windows/normalizes without extending the decay.
convolve_ir(x, h) implements mono/diagonal/LL,LR,RL,RR routing via BB-07.
SciPy signal APIs (BSD-3-Clause), no external implementation copied.
"""
from __future__ import annotations
import io
import math
import wave
from collections import OrderedDict
from mankomix import repo_data_root
import numpy as np
from scipy import signal
import soundfile as sf
from mankomix.dsp.errors import ParamError
from .asset_registry import AssetRegistry, sha256


def synthetic_ir(id, sr=44100, seed=208):
    if id == "synth_room_a":
        n = round(2*sr)
        rng = np.random.Generator(np.random.PCG64(seed))
        h = rng.integers(-32768, 32768, (n, 2)).astype(np.float64)/32768
        h *= np.exp(-math.log(1000)*np.arange(n)[:, None]/(sr*.8))*.02
        h[:round(.006*sr)] = 0
        return h
    if id == "synth_cab_a":
        h = np.zeros(round(.2*sr)); h[0] = 1
        # Original 110 Hz second-order resonance, cone-breakup comb and HF rolloff.
        r = math.exp(-math.pi*110/(1.4*sr))
        h = signal.lfilter([1-r], [1, -2*r*math.cos(2*math.pi*110/sr), r*r], h)
        d = max(1, round(.00023*sr))
        h[d:] += .22*h[:-d].copy()
        h = signal.sosfilt(signal.butter(2, min(5500, .4*sr), fs=sr, output="sos"), h)
        h /= max(np.max(np.abs(h)), 1e-30)*2
        return h[:, None]
    raise ParamError("unknown original IR generator")


def synthetic_bytes(id, sr=44100, seed=208):
    h = synthetic_ir(id, sr, seed)
    pcm = np.rint(np.clip(h, -1, 1-2**-31)*2**31).astype("<i4")
    out = io.BytesIO()
    with wave.open(out, "wb") as f:
        f.setnchannels(h.shape[1]); f.setsampwidth(4); f.setframerate(sr)
        f.writeframes(pcm.tobytes())
    return out.getvalue()


def decode(data):
    try:
        h, sr = sf.read(io.BytesIO(data), dtype="float64", always_2d=True)
    except (RuntimeError, ValueError) as exc:
        raise ParamError("IR must be a readable audio file") from exc
    if not len(h) or h.shape[1] not in (1, 2, 4) or not np.isfinite(h).all():
        raise ParamError("IR requires finite nonempty 1, 2 or 4 channel audio")
    return h, sr


def metadata(data):
    h, sr = decode(data)
    return {"sr": sr, "channels": h.shape[1], "length_s": len(h)/sr}


def validate_record(e):
    if e.get("kind", "room") not in ("room", "cabinet"):
        raise ParamError("IR kind must be room or cabinet")
    if type(e.get("sr")) is not int or e["sr"] <= 0 or e.get("channels") not in (1, 2, 4):
        raise ParamError("invalid IR sample rate or channels")
    length = e.get("length_s")
    if isinstance(length, bool) or not isinstance(length, (int, float)) or not math.isfinite(length) or length <= 0:
        raise ParamError("invalid IR length")
    if e["tier"] == "official":
        o = e["origin"]
        if o.get("type") != "synthetic" or o.get("generator") != "tools/generate_synthetic_irs.py" or not isinstance(o.get("args"), dict):
            raise ParamError("official IR requires the original generator and arguments")


def generate(e):
    return synthetic_bytes(e["id"], **e["origin"]["args"])


IRS = AssetRegistry("irs", repo_data_root()/"registry"/"irs.json",
                    metadata, generate=generate, validate=validate_record)


_RESAMPLED = OrderedDict()


def load_ir(id, sr):
    from mankomix.dsp.reference.export import resample_poly_hq
    data, record, warnings = IRS.load(id)
    h, source_sr = decode(data)
    # Verify source bytes before every cache lookup, including a warm cache.
    prefix = (record["sha256"], int(sr), "resample_poly_hq_v1")
    hit = next((key for key in _RESAMPLED if key[:3] == prefix), None)
    if hit is None:
        h = resample_poly_hq(h, source_sr, sr)
        digest = sha256(np.asarray(h, dtype="<f8").tobytes())
        hit = (*prefix, digest)
        h.setflags(write=False)
        _RESAMPLED[hit] = h
        while len(_RESAMPLED) > 8:
            _RESAMPLED.popitem(last=False)
    else:
        _RESAMPLED.move_to_end(hit)
        h, digest = _RESAMPLED[hit], hit[-1]
    return h.copy(), {"asset": record, "warnings": warnings, "source_sha256": record["sha256"],
               "converted_sha256": digest, "cache_key": {"source_sha256": record["sha256"],
               "converted_sha256": digest, "sr": sr, "method": "resample_poly_hq"}}


def decay_time(h, sr):
    energy = np.sum(h*h, axis=1)
    edc = np.cumsum(energy[::-1])[::-1]
    if not len(edc) or edc[0] == 0:
        return None
    db = 10*np.log10(np.maximum(edc/edc[0], 1e-300))
    indices = np.flatnonzero((db <= -5) & (db >= -25))
    if len(indices) < 3:
        return None
    slope = np.polyfit(indices/sr, db[indices], 1)[0]
    return float(-60/slope) if slope < 0 else None


def prepare_ir(h, sr, *, start_ms=0, length_s=20, fade_ms=0, decay=1, gain_mode="energy", phase="as_is"):
    from .fir import minimum_phase
    begin = round(start_ms*sr/1000)
    h = h[begin:begin+max(1, round(length_s*sr))].copy()
    if not len(h):
        raise ParamError("IR start is beyond the source length")
    rt = decay_time(h, sr)
    if decay < 1 and rt:
        h *= np.exp(-math.log(1000)*np.arange(len(h))[:, None]/sr*(1/decay-1)/rt)
    if fade_ms:
        count = min(len(h), max(1, round(fade_ms*sr/1000)))
        h[-count:] *= np.linspace(1, 0, count)[:, None]
    if phase == "minimum":
        h = np.column_stack([minimum_phase(h[:, i]) for i in range(h.shape[1])])
    if gain_mode == "energy":
        scale = math.sqrt(float(np.sum(h*h)/min(h.shape[1], 2)))
    elif gain_mode == "peak":
        scale = float(np.max(np.abs(h)))
    elif gain_mode == "none":
        scale = 1
    else:
        raise ParamError("unknown IR gain mode")
    if scale:
        h /= scale
    return h


def kernel(h, channels):
    if h.shape[1] == 1:
        return h[:, 0]
    if h.shape[1] == 2:
        return h[:, None, :] if channels == 1 else h
    matrix = h.reshape(len(h), 2, 2)  # LL, LR, RL, RR: input then output.
    return matrix.sum(axis=1, keepdims=True) if channels == 1 else matrix


def convolve_ir(x, h):
    from .fir import fft_convolve
    if x.shape[1] not in (1, 2):
        raise ParamError("IR processing requires mono or stereo input")
    return fft_convolve(x, kernel(h, x.shape[1]), "same")


def ir_stats(h, sr, p):
    from .reverb import measure_ir
    if h.ndim == 3:
        return measure_ir(h, sr, p)
    if h.shape[1] == 1:
        pair = np.repeat(h, 2, axis=1)
    elif h.shape[1] == 2:
        pair = h
    else:
        pair = h.reshape(len(h), 2, 2).sum(axis=1)
    return measure_ir(pair, sr, p)
