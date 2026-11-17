"""BB-24: original spherical model and pinned, local HRIR sets.

HRTFS is BB-08 AssetRegistry: catalog/resolve/register_file/remove/load.
model_bytes() is the canonical descriptor hashed by the official catalogue.
decode_npz(data) -> (azimuth, elevation, hrir[directions,taps,2], sr).
load_hrtf(id, sr) -> (HRTFSet, provenance); rehashes before every cache hit.
HRTFSet.kernel(azimuth_deg, elevation_deg, sr) -> causal float64 stereo HRIR.
sphere_hrir(sr, azimuth_deg, elevation_deg=0) -> original stereo HRIR.
sphere_itd(azimuth_deg, elevation_deg=0) -> signed seconds (left minus right).
nearest_directions(az, el, query_az, query_el) -> indices, spherical weights.

Independent structural construction, following the head shadow/ITD/reflection
decomposition in Brown & Duda, IEEE TSAP 6(5), 476-488 (1998), sections II-IV:
https://www.ece.ucdavis.edu/cipic/wp-content/uploads/sites/12/2015/04/cipic_Brown_Duda98.pdf
The radius, shelf and pinna constants below are original choices, not a fit
to a person or a measured dataset. No third-party implementation is copied.
"""
from __future__ import annotations

import io
import json
import math
from collections import OrderedDict

import numpy as np
from scipy import signal

from mankomix import repo_data_root
from mankomix.dsp.errors import ParamError
from .asset_registry import AssetRegistry


MODEL = {"model": "model_sphere", "version": 1, "radius_m": .09,
         "sound_speed_m_s": 343., "shadow_amount": .9,
         "pinna_delays_ms": [.09, .16, .25], "pinna_gains": [.12, -.08, .045],
         "support_s": .012}


def model_bytes():
    return (json.dumps(MODEL, sort_keys=True, separators=(",", ":"))+"\n").encode("utf-8")


def decode_npz(data):
    """NPZ keys: azimuth_deg/elevation_deg (D,), hrir (D,N,2), sr scalar.

    Degrees use front=0, right=positive, elevation=up. Row number is the
    direction ID used to break equal-distance ties. Pickles are never loaded.
    """
    try:
        with np.load(io.BytesIO(data), allow_pickle=False) as z:
            if any(z[key].dtype.kind not in "fiu" for key in ("azimuth_deg", "elevation_deg", "hrir")):
                raise ValueError("real numeric arrays required")
            az = np.asarray(z["azimuth_deg"], dtype=np.float64)
            el = np.asarray(z["elevation_deg"], dtype=np.float64)
            h = np.asarray(z["hrir"], dtype=np.float64)
            rate = np.asarray(z["sr"])
    except (ValueError, KeyError, OSError, TypeError, EOFError) as exc:
        raise ParamError("HRTF must be a readable numeric NPZ set") from exc
    if (rate.shape != () or rate.dtype.kind not in "iu" or not 8000 <= int(rate) <= 384000
            or az.ndim != 1 or not len(az) or el.shape != az.shape
            or h.ndim != 3 or h.shape[0] != len(az) or h.shape[2] != 2
            or not 1 <= h.shape[1] <= int(rate)//2
            or not all(np.isfinite(v).all() for v in (az, el, h))
            or np.any(np.abs(az) > 180) or np.any(np.abs(el) > 90)):
        raise ParamError("invalid HRTF coordinates, sample rate or HRIR shape")
    return az.copy(), el.copy(), h.copy(), int(rate)


def metadata(data):
    if data == model_bytes():
        return {"kind": "structural", "channels": 2, "model_version": 1}
    az, _, h, sr = decode_npz(data)
    return {"kind": "measured", "channels": 2, "sr": sr,
            "directions": len(az), "taps": h.shape[1]}


def validate_record(e):
    if e.get("channels") != 2 or e.get("kind") not in ("structural", "measured"):
        raise ParamError("HRTF requires structural/measured kind and two ears")
    if e["tier"] == "official":
        if (e.get("id") != "model_sphere" or e.get("kind") != "structural"
                or e.get("model_version") != 1
                or e["origin"].get("generator") != "dspx/bb/hrtf.py"):
            raise ParamError("only the original model_sphere may be bundled")
    elif (e["kind"] != "measured" or type(e.get("sr")) is not int
          or not 8000 <= e["sr"] <= 384000
          or type(e.get("directions")) is not int or e["directions"] < 1
          or type(e.get("taps")) is not int or not 1 <= e["taps"] <= e["sr"]//2):
        raise ParamError("invalid measured HRTF metadata")


HRTFS = AssetRegistry("hrtfs", repo_data_root()/"registry"/"hrtfs.json", metadata,
                      generate=lambda e: model_bytes(), validate=validate_record)


def sphere_itd(azimuth_deg, elevation_deg=0):
    lateral = math.sin(math.radians(abs(azimuth_deg))) * math.cos(math.radians(elevation_deg))
    theta = math.asin(np.clip(lateral, -1., 1.))
    value = MODEL["radius_m"]/MODEL["sound_speed_m_s"] * (theta + math.sin(theta))
    return math.copysign(value, azimuth_deg) if azimuth_deg else 0.


def sphere_hrir(sr, azimuth_deg, elevation_deg=0):
    """Woodworth ITD, unity-DC one-pole/one-zero shelf, three pinna echoes.

    Always construct positive azimuth first, then swap ears exactly. The
    frontal gain is sqrt(1/2) per ear, matching the equal-power centre law.
    The musical ITD is not declared as processing latency.
    """
    from .delayline import fractional_delay
    n = max(8, int(math.ceil(MODEL["support_s"]*sr)))
    impulse = np.zeros((n, 1)); impulse[0] = 1
    az, el = math.radians(abs(azimuth_deg)), math.radians(elevation_deg)
    lateral = math.sin(az)*math.cos(el)
    omega = MODEL["sound_speed_m_s"]/MODEL["radius_m"]
    pole = (2*sr-omega)/(2*sr+omega)
    ears = []
    for sign in (-1, 1):
        alpha = 1 + sign*MODEL["shadow_amount"]*lateral
        b = [(2*sr*alpha+omega)/(2*sr+omega), (omega-2*sr*alpha)/(2*sr+omega)]
        head = signal.lfilter(b, [1, -pole], impulse, axis=0)
        pinna = head.copy()
        for j, (delay, gain) in enumerate(zip(MODEL["pinna_delays_ms"], MODEL["pinna_gains"])):
            d = delay*(1+.22*math.sin(el)+.12*(1-math.cos(az)))*sr/1000
            g = gain*(1+.3*math.sin(el)+sign*.15*lateral)/(j*.1+1)
            pinna += g*fractional_delay(head, d)
        delay = abs(sphere_itd(abs(azimuth_deg), elevation_deg))*sr if sign < 0 else 0.
        ears.append(fractional_delay(pinna, delay)[:, 0]*math.sqrt(.5))
    h = np.column_stack(ears)
    return h[:, ::-1].copy() if azimuth_deg < 0 else h


def _vectors(az, el):
    az, el = np.radians(az), np.radians(el)
    return np.stack((np.cos(el)*np.cos(az), np.cos(el)*np.sin(az), np.sin(el)), axis=-1)


def nearest_directions(az, el, query_az, query_el):
    """Four nearest great-circle neighbours, inverse-angle-squared weights."""
    v = _vectors(az, el)
    q = _vectors(query_az, query_el)
    # Chord distances avoid arccos losing precision around exact nodes.
    chord = np.linalg.norm(v-q, axis=1)
    ids = np.lexsort((np.arange(len(az)), chord))[:4]
    if chord[ids[0]] < 1e-12:
        return ids[:1], np.ones(1)
    angle = 2*np.arcsin(np.clip(chord[ids]/2, 0, 1))
    w = 1/angle**2
    return ids, w/np.sum(w)


class HRTFSet:
    """Prepared, immutable HRIR set. Exact nodes retain the original HRIR.

    Between nodes, interpolate minimum-phase filters and excess-phase delays
    separately; the delay uses BB-09 sinc8. Non-minimum-phase residuals at
    measured nodes are preserved by the exact-node path, not interpolated.
    """
    def __init__(self, az=None, el=None, hrir=None):
        self.az, self.el, self.hrir = az, el, hrir
        if hrir is not None:
            from .fir import minimum_phase
            from scipy import fft
            self.minimum = np.zeros_like(hrir)
            self.delays = np.zeros((len(hrir), 2))
            for i in range(len(hrir)):
                for ear in range(2):
                    h = hrir[i, :, ear]
                    nonzero = np.flatnonzero(np.abs(h) > np.max(np.abs(h))*1e-8)
                    onset = int(nonzero[0]) if len(nonzero) else 0
                    minimum = minimum_phase(h)
                    if len(nonzero) and h[onset] < 0:
                        minimum *= -1
                    self.minimum[i, :, ear] = minimum
                    # Weighted linear excess-phase fit: a pure delay has
                    # phase -omega*d. Unlike onset thresholding, this retains
                    # fractional ITD in bandlimited measured HRIRs.
                    nfft = 1 << (max(2048, 8*len(h))-1).bit_length()
                    H = fft.rfft(h, nfft, workers=1)
                    M = fft.rfft(minimum, nfft, workers=1)
                    omega = 2*np.pi*fft.rfftfreq(nfft)
                    phase = np.unwrap(np.angle(H*np.conj(M)))
                    weight = np.abs(H)**2
                    weight[(omega > .8*np.pi) | (omega < .02*np.pi)] = 0
                    total = np.sum(weight)
                    if total:
                        centre = np.sum(weight*omega)/total
                        slope = np.sum(weight*(omega-centre)*phase)/np.sum(weight*(omega-centre)**2)
                        self.delays[i, ear] = np.clip(-slope, 0, len(h)-1)
            for array in (az, el, hrir, self.minimum, self.delays):
                array.setflags(write=False)

    def kernel(self, azimuth_deg, elevation_deg, sr):
        if self.hrir is None:
            return sphere_hrir(sr, azimuth_deg, elevation_deg)
        from .delayline import fractional_delay
        ids, w = nearest_directions(self.az, self.el, azimuth_deg, elevation_deg)
        if len(ids) == 1:
            return self.hrir[ids[0]].copy()
        h = np.sum(self.minimum[ids]*w[:, None, None], axis=0)
        d = np.sum(self.delays[ids]*w[:, None], axis=0)
        h = np.pad(h, ((0, int(np.ceil(np.max(d)))+4), (0, 0)))
        return fractional_delay(h, d[None, :])


_CACHE = OrderedDict()


def load_hrtf(id, sr):
    data, record, warnings = HRTFS.load(id)
    key = (record["sha256"], sr)
    if key not in _CACHE:
        if record["kind"] == "structural":
            prepared = HRTFSet()
        else:
            from mankomix.dsp.reference.export import resample_poly_hq
            az, el, h, source_sr = decode_npz(data)
            h = np.stack([resample_poly_hq(row, source_sr, sr) for row in h])
            prepared = HRTFSet(az, el, h)
        _CACHE[key] = prepared
        while len(_CACHE) > 4:
            _CACHE.popitem(last=False)
    _CACHE.move_to_end(key)
    return _CACHE[key], {"asset": record, "source_sha256": record["sha256"],
                         "warnings": warnings, "sample_rate_hz": sr}
