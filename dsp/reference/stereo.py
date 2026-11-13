"""stereo: band-split M/S width (reference backend).

Mid is untouched. Side is split into bands with linear-phase lowpass FIRs of
equal length; band k = LP_{k+1}(S) - LP_k(S), with LP_0 = 0 and the top band
taking the delayed full Side, so the bands sum back to S exactly. Each band is
scaled by its width; the FIR delay is compensated (output time-aligned).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import signal


def _band_edges(p: dict) -> tuple[list[float], list[float]]:
    edges: list[float] = []
    widths: list[float] = []
    if p["mono_below_hz"] > 0:
        edges.append(p["mono_below_hz"])
        widths.append(0.0)
    xs = list(p["crossovers_hz"])
    above = list(p["widths"]) if p["widths"] else [p["width"]] * (len(xs) + 1)
    edges += xs
    widths += above
    return edges, widths


def _taps_for(f_lowest: float, sr: int) -> int:
    # transition width ~ half an octave below the lowest edge, Kaiser ~ 90 dB
    tw = max(f_lowest * 0.5, 10.0)
    n, _ = signal.kaiserord(90.0, tw / (sr / 2.0))
    return int(min(max(n, 255), 1 << 15)) | 1


def stereo(x: np.ndarray, sr: int, p: dict, **_):
    if x.shape[1] != 2:
        return x.copy(), sr, {"skipped": "stereo processor needs 2 channels", "latency_samples": 0}
    m = 0.5 * (x[:, 0] + x[:, 1])
    s = 0.5 * (x[:, 0] - x[:, 1])
    edges, widths = _band_edges(p)
    n = x.shape[0]
    taps = 0
    if not edges:
        s_out = s * widths[0]
    elif all(abs(w - widths[0]) < 1e-15 for w in widths) and widths[0] == 1.0:
        s_out = s.copy()
    else:
        taps = _taps_for(min(edges), sr)
        d = (taps - 1) // 2
        beta = signal.kaiser_beta(90.0)
        lps = []
        for f in edges:
            h = signal.firwin(taps, f, window=("kaiser", beta), fs=sr)
            lps.append(signal.oaconvolve(s, h, mode="full")[d:d + n])
        # perfect-reconstruction bands
        bands = [lps[0]]
        for k in range(1, len(lps)):
            bands.append(lps[k] - lps[k - 1])
        bands.append(s - lps[-1])
        s_out = np.zeros(n)
        for b, w in zip(bands, widths):
            if w != 0.0:
                s_out += w * b
    y = np.stack([m + s_out, m - s_out], axis=1)
    e_s_in = float(np.sum(s * s))
    e_m = float(np.sum(m * m))
    e_s_out = float(np.sum(s_out * s_out))
    return y, sr, {
        "bands": [{"lo_hz": (0.0 if i == 0 else edges[i - 1]),
                   "hi_hz": (edges[i] if i < len(edges) else sr / 2.0),
                   "width": w} for i, w in enumerate(widths)],
        "side_to_mid_db_in": _ratio_db(e_s_in, e_m),
        "side_to_mid_db_out": _ratio_db(e_s_out, e_m),
        "fir_taps": taps,
        "latency_samples": (taps - 1) // 2 if taps else 0,
        "latency_compensated": True,
    }


def _ratio_db(a: float, b: float) -> float | None:
    if a <= 0 or b <= 0:
        return None
    return round(10 * math.log10(a / b), 3)
