"""filter (Butterworth HPF/LPF) and eq (RBJ cookbook biquads) -- reference backend.

The biquad formulas follow Robert Bristow-Johnson's "Cookbook formulae for
audio EQ biquad filter coefficients" and are written out here; bandwidth is
specified in octaves (R-12) and converted with the cookbook's bilinear-warp
correction, so the digital band edges land where the octave width says.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

_SLOPE_TO_ORDER = {6: 1, 12: 2, 18: 3, 24: 4, 48: 8}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _sosfilt(sos: np.ndarray, x: np.ndarray) -> np.ndarray:
    return signal.sosfilt(sos, x, axis=0)


def _phase_cost(sos: np.ndarray, sr: int, probe_hz: list[float]) -> dict:
    """Phase shift and group delay at a few probe frequencies (SPEC 6.5.2: record phase cost)."""
    probes = [f for f in probe_hz if 0 < f < sr / 2]
    worN = np.array(probes, dtype=np.float64)
    _, h = signal.sosfreqz(sos, worN=worN, fs=sr)
    # group delay via a small symmetric finite difference of the unwrapped phase
    df = 0.5
    _, h_lo = signal.sosfreqz(sos, worN=np.maximum(worN - df, 0.01), fs=sr)
    _, h_hi = signal.sosfreqz(sos, worN=worN + df, fs=sr)
    dphi = np.unwrap(np.stack([np.angle(h_lo), np.angle(h_hi)]), axis=0)
    gd_s = -(dphi[1] - dphi[0]) / (2 * math.pi * 2 * df)
    out = []
    for f, hv, gd in zip(probes, h, gd_s):
        out.append({"freq_hz": round(f, 3), "mag_db": round(20 * math.log10(max(abs(hv), 1e-300)), 4),
                    "phase_deg": round(math.degrees(np.angle(hv)), 3),
                    "group_delay_ms": round(gd * 1000.0, 4)})
    return {"phase_type": "minimum", "probes": out}


# ---------------------------------------------------------------------------
# filter
# ---------------------------------------------------------------------------

def butter_sos(kind: str, freq_hz: float, slope: int, sr: int) -> np.ndarray:
    order = _SLOPE_TO_ORDER[int(slope)]
    btype = "highpass" if kind == "hpf" else "lowpass"
    return signal.butter(order, freq_hz, btype=btype, output="sos", fs=sr)


def filt(x: np.ndarray, sr: int, p: dict, **_):
    sos = butter_sos(p["kind"], p["freq_hz"], p["slope_db_oct"], sr)
    y = _sosfilt(sos, x)
    f = p["freq_hz"]
    cost = _phase_cost(sos, sr, [f / 2, f, f * 2, 1000.0, 100.0])
    return y, sr, {"order": _SLOPE_TO_ORDER[int(p["slope_db_oct"])], "design": "butterworth",
                   "phase_cost": cost}


# ---------------------------------------------------------------------------
# eq
# ---------------------------------------------------------------------------

def bw_to_q(bw_oct: float) -> float:
    """Analog relation between octave bandwidth and Q."""
    return 1.0 / (2.0 * math.sinh(math.log(2.0) / 2.0 * bw_oct))


def rbj_biquad(shape: str, freq_hz: float, gain_db: float, bw_oct: float, sr: int) -> np.ndarray:
    """Return a single second-order section [b0 b1 b2 1 a1 a2] (normalised)."""
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq_hz / sr
    cw, sw = math.cos(w0), math.sin(w0)
    if shape in ("peak", "notch"):
        # cookbook: alpha = sin(w0) * sinh(ln(2)/2 * BW * w0/sin(w0))  (bilinear-warp corrected)
        alpha = sw * math.sinh(math.log(2.0) / 2.0 * bw_oct * w0 / sw)
    else:
        alpha = sw / (2.0 * bw_to_q(bw_oct))
    if shape == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif shape == "notch":
        b = [1.0, -2 * cw, 1.0]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif shape == "low_shelf":
        sa = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sa), 2 * A * ((A - 1) - (A + 1) * cw),
             A * ((A + 1) - (A - 1) * cw - sa)]
        a = [(A + 1) + (A - 1) * cw + sa, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sa]
    elif shape == "high_shelf":
        sa = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + sa), -2 * A * ((A - 1) + (A + 1) * cw),
             A * ((A + 1) + (A - 1) * cw - sa)]
        a = [(A + 1) - (A - 1) * cw + sa, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sa]
    else:
        raise ValueError(f"unknown eq shape {shape!r}")
    a0 = a[0]
    return np.array([[b[0] / a0, b[1] / a0, b[2] / a0, 1.0, a[1] / a0, a[2] / a0]])


def _linear_phase_fir(sos: np.ndarray, sr: int, freq_hz: float, bw_oct: float) -> np.ndarray:
    """Zero-phase FIR with the magnitude of ``sos`` (frequency sampling + Kaiser window)."""
    # resolution: enough taps for the narrowest feature (bandwidth around freq) and low end
    f_lo = max(10.0, min(freq_hz * (2.0 ** (-max(bw_oct, 0.05) / 2.0)), freq_hz) * 0.5)
    taps = int(min(1 << 16, max(1023, 8.0 * sr / f_lo)))
    taps |= 1
    nfft = 1 << int(math.ceil(math.log2(taps * 4)))
    _, h = signal.sosfreqz(sos, worN=nfft // 2 + 1, whole=False, fs=sr)
    mag = np.abs(h)
    imp = np.fft.irfft(mag, n=nfft)
    imp = np.roll(imp, taps // 2)[:taps]
    return imp * signal.windows.kaiser(taps, 8.0)


def eq(x: np.ndarray, sr: int, p: dict, **_):
    sos = rbj_biquad(p["shape"], p["freq_hz"], p["gain_db"], p["bw_oct"], sr)
    f = p["freq_hz"]
    if p["phase"] == "minimum":
        y = _sosfilt(sos, x)
        stats = {"phase_cost": _phase_cost(sos, sr, [f / 2, f, f * 2]), "latency_samples": 0}
        return y, sr, stats
    fir = _linear_phase_fir(sos, sr, p["freq_hz"], p["bw_oct"])
    d = (len(fir) - 1) // 2
    y = signal.oaconvolve(x, fir[:, None], mode="full", axes=0)[d:d + x.shape[0]]
    # pre-ringing: energy before the main tap relative to the whole response
    peak = np.max(np.abs(fir))
    pre = fir[:d]
    pre_energy = float(np.sum(pre ** 2))
    tot = float(np.sum(fir ** 2))
    above = np.nonzero(np.abs(pre) > peak * 1e-3)[0]
    pre_ms = (d - above[0]) / sr * 1000.0 if above.size else 0.0
    stats = {
        "phase_cost": {"phase_type": "linear", "group_delay_ms_constant": round(d / sr * 1000, 4)},
        "latency_samples": d,
        "latency_compensated": True,
        "fir_taps": len(fir),
        "pre_ringing": {
            "energy_ratio_db": round(10 * math.log10(pre_energy / tot), 3) if pre_energy > 0 else None,
            "duration_ms_above_-60db": round(pre_ms, 3),
            "note": "linear-phase EQ rings before transients; keep to small cuts (SPEC 6.6.3, R-12)",
        },
    }
    return y, sr, stats
