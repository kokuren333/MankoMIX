"""Deterministic rectangular image-source early reflections (original code).

geometry(p) fixes the receiver at (0.50 W, 0.43 L, 0.47 H). The source is
receiver + distance*(sin(pi*azimuth/2), cos(pi*azimuth/2), 0). It must lie
inside the room. There is no scene.room mapping. Sound speed is 343 m/s.
image_taps(sr,p) returns path metadata; image_ir(sr,p) returns stereo IR
and metadata. Reflection order is the Manhattan norm of image indices;
image coordinate k*L+s for even k, (k+1)*L-s for odd k. All paths with
order<=max_order are counted before the strict max_ms support window.
Per-wall damping is a second-order Butterworth LP, applied once per bounce.
Fractional placement uses the existing BB-09 windowed-sinc reader.
"""
import itertools
import math
import numpy as np
from scipy import signal
from mankomix.dsp.errors import ParamError


def geometry(p):
    room = np.array([p["room_w_m"], p["room_l_m"], p["room_h_m"]])
    listener = room*np.array([.5, .43, .47])
    a = p["azimuth"]*math.pi/2
    source = listener + p["distance_m"]*np.array([math.sin(a), math.cos(a), 0.])
    if np.any(source <= 0) or np.any(source >= room):
        raise ParamError("source distance and azimuth must place the source inside the room")
    return room, listener, source


def image_taps(sr, p):
    room, receiver, source = geometry(p)
    order = p["max_order"]
    taps = []
    for indices in itertools.product(range(-order, order+1), repeat=3):
        count = sum(abs(k) for k in indices)
        if count > order or (not count and not p["direct"]):
            continue
        image = np.array([k*l+s if k % 2 == 0 else (k+1)*l-s
                          for k, l, s in zip(indices, room, source)])
        direction = image-receiver
        distance = float(np.linalg.norm(direction))
        delay = distance/343*sr
        pan = float(direction[0]/distance)
        angle = (pan+1)*math.pi/4
        gain = (1-p["absorption"])**(count/2)/distance
        taps.append({"image": list(indices), "order": count, "delay_samples": delay,
                     "distance_m": distance, "gain": gain,
                     "pan_gains": [math.cos(angle), math.sin(angle)],
                     "in_window": delay < p["max_ms"]*sr/1000})
    return taps


def image_ir(sr, p):
    from .delayline import read_samples
    taps = image_taps(sr, p)
    n = max(1, round(p["max_ms"]*sr/1000))
    h = np.zeros((n, 2))
    # Build each order independently so damping is applied exactly per bounce.
    for order in range(p["max_order"]+1):
        group = np.zeros((n, 2))
        for tap in taps:
            if tap["order"] != order or not tap["in_window"]:
                continue
            d = tap["delay_samples"]
            lo, hi = max(0, math.floor(d)-5), min(n, math.ceil(d)+6)
            if hi <= lo:
                continue
            unit = np.ones((1, 1))
            pulse = read_samples(unit, np.arange(lo, hi)-d, "sinc8")[:, 0]
            group[lo:hi] += pulse[:, None]*tap["gain"]*np.array(tap["pan_gains"])
        if 0 < p["damping_hz"] < .45*sr:
            sos = signal.butter(2, p["damping_hz"], fs=sr, output="sos")
            for _ in range(order):
                group = signal.sosfilt(sos, group, axis=0)
        h += group
    from .reverb import _wet_filter
    # Filtering stays inside the finite IR, including its IIR tail.
    h = _wet_filter(h, sr, p)
    mid = h.mean(axis=1, keepdims=True)
    h = mid+p["width"]*(h-mid)
    return h, {"tap_count": len(taps), "active_tap_count": sum(t["in_window"] for t in taps),
               "paths": taps, "receiver_ratio": [.5, .43, .47], "sound_speed_m_s": 343}
