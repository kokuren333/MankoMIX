"""reverb and delay (reference backend), described by measured vectors (SPEC 6.5.2, R-10, R-11).

Both processors are linear and time invariant and fully deterministic (fixed
tables, no random numbers).

reverb
    A true-stereo algorithmic reverb rendered as impulse responses and applied
    by FFT convolution (exactly the LTI system, up to truncation of the tail
    below -90 dB):

    - early reflections: a fixed table of 12 taps (4-61 ms) with constant-power
      panning, mirrored for the right input;
    - late field: a Schroeder all-pass diffuser chain (4 stages) feeding an
      8-line feedback delay network with an orthogonal (Hadamard) mixing
      matrix. Each line has an absorption filter (broadband gain plus RBJ low
      and high shelves at 250 Hz / 4 kHz) whose loop gain is
      ``-60 dB * m_i / (sr * RT60(band))`` per pass, which sets the decay time
      per band exactly for a lossless matrix;
    - ER and late parts are energy-normalised and mixed by ``er_late_db``;
      ``predelay_ms`` shifts the whole wet response;
    - the wet path is band-limited by 12 dB/oct Butterworth ``lowcut_hz`` /
      ``highcut_hz`` filters (SPEC 6.5.4: plate-like return 600 Hz - 6 kHz);
    - ``y = (1 - mix) * dry + mix * wet``; ``mix = 1`` is the 100 % wet mode for
      send buses.

    The statistics are measured on the rendered wet impulse response:
    RT60 per octave band (Schroeder backward integration, T20 fit), ER/late
    energy ratio, D/R for white input, inter-channel correlation and mono
    fold-down loss of the wet return.

delay
    ``w[n] = u[n - D] + feedback * w[n - D]`` with ``u`` the (optionally band-
    limited) input and ``D`` an integer number of samples from ``time_ms`` or
    a note value at ``bpm``. The feedback comb is evaluated exactly and
    vectorised by viewing the signal as rows of D samples (``z^-D`` becomes a
    unit delay along the rows). Filters act on the wet input, so every repeat
    has the same band limit. ``route`` puts the wet signal on both channels or
    on one channel only (Haas widening). The Haas region (R-10: < 5 ms
    localisation / comb risk, 5-30 ms fusion, > 30 ms echo) and the measured
    mono fold-down loss are always reported together.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

from ..processors import NOTE_VALUES, note_ms
from .filters import rbj_biquad

# ---------------------------------------------------------------------------
# note values (R-11)
# ---------------------------------------------------------------------------

__all__ = ["note_ms", "nearest_note", "reverb", "delay", "reverb_ir", "schroeder_rt60",
           "haas_region", "mono_fold"]


def nearest_note(ms: float, bpm: float) -> dict | None:
    """Nearest note value to ``ms`` at ``bpm`` with the relative deviation (R-11 recording)."""
    if not bpm or bpm <= 0 or ms <= 0:
        return None
    best = min(NOTE_VALUES[1:], key=lambda n: abs(math.log(note_ms(n, bpm) / ms)))
    ref = note_ms(best, bpm)
    return {"value": best, "bpm": bpm, "note_ms": round(ref, 4),
            "deviation_pct": round(100.0 * (ms - ref) / ref, 3)}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _strided_iir(u: np.ndarray, D: int, b, a) -> np.ndarray:
    """Apply H(z^-D) = B(z^-D) / A(z^-D) exactly: rows of D samples, filter along the rows."""
    n = u.shape[0]
    k = -(-n // D)
    pad = np.zeros((k * D,) + u.shape[1:])
    pad[:n] = u
    rows = pad.reshape((k, D) + u.shape[1:])
    out = signal.lfilter(b, a, rows, axis=0)
    return out.reshape((k * D,) + u.shape[1:])[:n]


def _band_limit(x: np.ndarray, sr: int, lowcut: float, highcut: float) -> tuple[np.ndarray, dict]:
    applied = {"lowcut_hz": None, "highcut_hz": None, "slope_db_oct": 12}
    y = x
    if lowcut and lowcut > 0:
        if lowcut < 0.45 * sr:
            y = signal.sosfilt(signal.butter(2, lowcut, "highpass", output="sos", fs=sr), y, axis=0)
            applied["lowcut_hz"] = lowcut
    if highcut and highcut > 0:
        if highcut < 0.45 * sr:
            y = signal.sosfilt(signal.butter(2, highcut, "lowpass", output="sos", fs=sr), y, axis=0)
            applied["highcut_hz"] = highcut
        else:
            applied["highcut_note"] = f"highcut {highcut} Hz at or above 0.45 x sr: not applied"
    return y, applied


def _energy(v: np.ndarray) -> float:
    return float(np.dot(v, v))


def mono_fold(left: np.ndarray, right: np.ndarray) -> dict:
    """Correlation and mono fold-down loss: 10 log10(E[((L+R)/2)^2] / ((E[L^2] + E[R^2]) / 2)).

    0 dB for identical channels, about -3 dB for uncorrelated ones, -inf for
    opposite polarity.
    """
    el, er = _energy(left), _energy(right)
    if el <= 0 or er <= 0:
        return {"correlation": None, "mono_loss_db": None}
    rho = float(np.dot(left, right) / math.sqrt(el * er))
    m = 0.5 * (left + right)
    em = _energy(m)
    loss = 10.0 * math.log10(em / (0.5 * (el + er))) if em > 0 else None
    return {"correlation": round(rho, 4), "mono_loss_db": round(loss, 3) if loss is not None else None}


# ---------------------------------------------------------------------------
# RT60 measurement
# ---------------------------------------------------------------------------

def schroeder_rt60(ir: np.ndarray, sr: int, band_hz: float | None = None,
                   fit_db: tuple[float, float] = (-5.0, -25.0)) -> float | None:
    """RT60 estimate of an impulse response (Schroeder backward integration, line fit).

    ``band_hz`` selects an octave band (4th-order Butterworth band-pass); the
    default fit range -5..-25 dB is T20 (x3).
    """
    h = np.asarray(ir, dtype=np.float64)
    if band_hz:
        lo, hi = band_hz / math.sqrt(2.0), min(band_hz * math.sqrt(2.0), 0.49 * sr)
        if lo >= hi:
            return None
        h = signal.sosfilt(signal.butter(4, [lo, hi], "bandpass", output="sos", fs=sr), h)
    e = np.cumsum((h * h)[::-1])[::-1]
    if e[0] <= 0:
        return None
    edc = 10.0 * np.log10(np.maximum(e / e[0], 1e-30))
    hi_db, lo_db = fit_db
    i0 = int(np.argmax(edc <= hi_db))
    i1 = int(np.argmax(edc <= lo_db))
    if edc[i1] > lo_db or i1 <= i0 + 2:
        return None
    t = np.arange(i0, i1) / sr
    slope, _ = np.polyfit(t, edc[i0:i1], 1)
    if slope >= 0:
        return None
    return float(-60.0 / slope)


# ---------------------------------------------------------------------------
# reverb
# ---------------------------------------------------------------------------

# early reflections: (time ms after the pre-delay, gain, pan -1..1); a fixed sparse pattern
_ER_TAPS = (
    (4.3, 0.84, -0.55), (7.9, 0.72, 0.50), (11.3, 0.66, -0.20), (14.9, 0.60, 0.80),
    (19.1, 0.52, -0.90), (23.7, 0.45, 0.30), (27.1, 0.40, -0.40), (31.9, 0.33, 0.70),
    (37.3, 0.27, -0.70), (43.1, 0.22, 0.10), (51.7, 0.16, 0.60), (61.3, 0.12, -0.30),
)
# Schroeder all-pass diffusers (ms, gain) and FDN line lengths (ms, mutually incommensurate)
_AP_STAGES = ((4.77, 0.70), (3.59, 0.70), (12.73, 0.62), (9.31, 0.62))
_FDN_MS = (29.71, 37.13, 41.11, 43.73, 47.93, 53.27, 59.93, 67.73)
_XOVER_LOW_HZ = 250.0
_XOVER_HIGH_HZ = 4000.0
_TAIL_DB = 90.0           # IR rendered until the slowest band decays by this much
_MAX_IR_S = 30.0


def _hadamard8() -> np.ndarray:
    h = np.array([[1.0]])
    for _ in range(3):
        h = np.block([[h, h], [h, -h]])
    return h


def _absorption_sos(m: int, sr: int, rt_low: float, rt_mid: float, rt_high: float) -> np.ndarray:
    """Loop filter of one FDN line: broadband mid gain and two shelves (gains in dB per pass)."""
    def db(rt):
        return -60.0 * m / (sr * rt)
    g_mid = db(rt_mid)
    hs_f = min(_XOVER_HIGH_HZ, 0.4 * sr)
    ls = rbj_biquad("low_shelf", _XOVER_LOW_HZ, db(rt_low) - g_mid, 1.9, sr)
    hs = rbj_biquad("high_shelf", hs_f, db(rt_high) - g_mid, 1.9, sr)
    sos = np.vstack([ls, hs])
    sos[0, :3] *= 10.0 ** (g_mid / 20.0)
    return sos


def _fdn_late(sr: int, n: int, rt: tuple[float, float, float]) -> np.ndarray:
    """Late impulse responses, shape (n, 2 inputs, 2 outputs)."""
    N = len(_FDN_MS)
    m = [max(2, int(round(ms * 1e-3 * sr))) for ms in _FDN_MS]
    H = _hadamard8() / math.sqrt(N)
    had = _hadamard8()
    # Walsh rows: injection 1, 2 and output 5, 7. Products of rows are rows (index XOR); since
    # 5^7 = 2 differs from 0 and from 1^2 = 3, the outputs are orthogonal for a left, right or
    # centred source even while only some lines carry energy (early part of the late field).
    b_in = np.stack([had[1], had[2]], axis=0) / math.sqrt(N)       # (2 inputs, N)
    c_out = np.stack([had[5], had[7]], axis=0) / math.sqrt(N)      # (2 outputs, N)
    # diffused impulse (same for both inputs; the injection vectors decorrelate them)
    u = np.zeros(n)
    u[0] = 1.0
    for ms, g in _AP_STAGES:
        D = max(1, int(round(ms * 1e-3 * sr)))
        u = _strided_iir(u, D, [-g, 1.0], [1.0, -g])
    sos = [_absorption_sos(mi, sr, *rt) for mi in m]
    zi = [np.zeros((s.shape[0], 2, 2)) for s in sos]                # (sections, inputs, 2)
    v = np.zeros((N, 2, n))                                         # line inputs per input channel
    out = np.zeros((n, 2, 2))
    B = min(m)
    for s in range(0, n, B):
        e = min(s + B, n)
        L = e - s
        o = np.zeros((N, 2, L))
        for i in range(N):
            lo, hi = s - m[i], e - m[i]
            if hi > 0:
                src = v[i, :, max(lo, 0):hi]
                o[i, :, L - src.shape[1]:] = src
            o[i], zi[i] = signal.sosfilt(sos[i], o[i], axis=-1, zi=zi[i])
        # o: (N, inputs, L); feedback through the orthogonal matrix plus injection
        v[:, :, s:e] = np.einsum("ij,jkl->ikl", H, o) + b_in.T[:, :, None] * u[s:e][None, None, :]
        out[s:e] = np.einsum("oj,jkl->lko", c_out, o)
    return out


def _er(sr: int, n: int) -> np.ndarray:
    """Early reflections, shape (n, 2 inputs, 2 outputs).

    The right output reads the tap table on a stretched time grid (+8.3 % + 0.7 ms) so the two
    outputs never share a tap time (a centred source gets decorrelated reflections). The right
    input mirrors the pan positions of the left input.
    """
    out = np.zeros((n, 2, 2))
    for ms, g, pan in _ER_TAPS:
        for o in (0, 1):
            k = int(round((ms * (1.0 + 0.083 * o) + 0.7 * o) * 1e-3 * sr))
            if k >= n:
                continue
            for inp, pp in ((0, pan), (1, -pan)):
                th = (pp + 1.0) * math.pi / 4.0
                out[k, inp, o] += g * (math.cos(th) if o == 0 else math.sin(th))
    return out


def reverb_ir(sr: int, p: dict) -> tuple[np.ndarray, dict]:
    """Wet impulse responses h[n, input, output] (true stereo) and their design record."""
    rt_mid = p["rt60_s"]
    rt = (rt_mid * p["rt60_low_mult"], rt_mid, rt_mid * p["rt60_high_mult"])
    pre = int(round(p["predelay_ms"] * 1e-3 * sr))
    tail_s = max(rt) * _TAIL_DB / 60.0
    n = int(min(_MAX_IR_S * sr, pre + math.ceil((0.1 + tail_s) * sr)))
    n_body = n - pre
    late = _fdn_late(sr, n_body, rt)
    er = _er(sr, n_body)
    # energy normalisation: each (input, output) path carries on average 1/2, so a centred
    # source (both inputs) gives about unit wet energy per output
    def norm(h):
        e = float(np.sum(h * h)) / 4.0
        return h * math.sqrt(0.5 / e) if e > 0 else h
    r = 10.0 ** (p["er_late_db"] / 10.0)
    body = math.sqrt(r / (1.0 + r)) * norm(er) + math.sqrt(1.0 / (1.0 + r)) * norm(late)
    h = np.zeros((n, 2, 2))
    h[pre:] = body
    h, filt = _band_limit(h.reshape(n, 4), sr, p["lowcut_hz"], p["highcut_hz"])
    h = h.reshape(n, 2, 2)
    # gentle fade over the last 5 % (the tail is already ~90 dB down there)
    nf = max(1, n // 20)
    h[-nf:] *= np.linspace(1.0, 0.0, nf)[:, None, None] ** 2
    design = {"rt60_set_s": {"low": round(rt[0], 4), "mid": round(rt[1], 4), "high": round(rt[2], 4)},
              "crossovers_hz": [_XOVER_LOW_HZ, min(_XOVER_HIGH_HZ, 0.4 * sr)],
              "predelay_samples": pre, "ir_samples": n, "wet_filters": filt,
              "design": "true-stereo ER taps + 4 all-pass diffusers + 8-line Hadamard FDN, "
                        "rendered to IR and applied by FFT convolution"}
    return h, design


def _measure_ir(h: np.ndarray, sr: int, pre: int) -> dict:
    left = h[:, 0, 0] + h[:, 1, 0]     # centred source: both inputs
    right = h[:, 0, 1] + h[:, 1, 1]
    mono = 0.5 * (left + right)
    rt = {}
    for f in (250.0, 1000.0, 4000.0):
        v = schroeder_rt60(left, sr, f) if f < 0.45 * sr else None
        rt[str(int(f))] = round(v, 4) if v else None
    split = pre + int(round(0.08 * sr))
    e_er = _energy(left[:split]) + _energy(right[:split])
    e_late = _energy(left[split:]) + _energy(right[split:])
    e_wet = 0.5 * (_energy(left) + _energy(right))
    return {
        "rt60_measured_s": rt,
        "er_late_measured_db": (round(10.0 * math.log10(e_er / e_late), 3)
                                if e_er > 0 and e_late > 0 else None),
        "wet_energy_db": round(10.0 * math.log10(e_wet), 3) if e_wet > 0 else None,
        "mono": mono_fold(left, right),
        "mono_ir_energy_db": round(10.0 * math.log10(_energy(mono)), 3) if _energy(mono) > 0 else None,
    }


def convolve_mimo(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """y[:, o] = sum_i (x[:, i] * h[:, i, o])[:n] by overlap-add FFT convolution.

    Every input block is transformed once and reused for all outputs (true stereo needs
    2 forward + 2 inverse transforms per block instead of 4 + 4).
    """
    from scipy import fft as sfft

    n, ci = x.shape
    co = h.shape[2]
    if n == 0:
        return np.zeros((0, co))
    h = h[: min(h.shape[0], n)]
    L = h.shape[0]
    nfft = 1 << max(13, int(math.ceil(math.log2(2 * L))))
    B = nfft - L + 1                     # block hop; B > L - 1, so a tail overlaps one block only
    nb = -(-n // B)
    H = sfft.rfft(h, nfft, axis=0)       # (F, ci, co)
    out = np.zeros(((nb + 1) * B, co))
    chunk = max(1, (1 << 21) // nfft)
    xp = np.zeros((nb * B, ci))
    xp[:n] = x
    xb = xp.reshape(nb, B, ci)
    for k0 in range(0, nb, chunk):
        k1 = min(nb, k0 + chunk)
        X = sfft.rfft(xb[k0:k1], nfft, axis=1)                    # (b, F, ci)
        Y = np.einsum("bfi,fio->bfo", X, H)
        yb = sfft.irfft(Y, nfft, axis=1)                            # (b, nfft, co)
        heads = out[k0 * B:k1 * B].reshape(k1 - k0, B, co)
        heads += yb[:, :B]
        if L > 1:
            tails = out[(k0 + 1) * B:(k1 + 1) * B].reshape(k1 - k0, B, co)
            tails[:, :L - 1] += yb[:, B:B + L - 1]
    return out[:n]


def reverb(x: np.ndarray, sr: int, p: dict, **_):
    h, design = reverb_ir(sr, p)
    n, ch = x.shape
    if ch == 2:
        wet = convolve_mimo(x, h)
    else:
        # mono (or > 2 channels): each channel through the summed left-output response
        hm = (h[:, 0, 0] + h[:, 1, 0])[:, None, None]
        wet = np.concatenate([convolve_mimo(x[:, c:c + 1], hm) for c in range(ch)], axis=1)
    mix = p["mix"]
    y = (1.0 - mix) * x + mix * wet
    meas = _measure_ir(h, sr, design["predelay_samples"])
    e_wet = 10.0 ** (meas["wet_energy_db"] / 10.0) if meas["wet_energy_db"] is not None else 0.0
    dr = (round(20.0 * math.log10((1.0 - mix) / mix) - 10.0 * math.log10(e_wet), 3)
          if 0 < mix < 1 and e_wet > 0 else None)
    stats = {**design, **meas,
             "mix": mix, "send_mode": mix >= 1.0,
             "dr_db_white": dr,
             "mono_compatible": (meas["mono"]["correlation"] is not None
                                 and meas["mono"]["correlation"] > -0.2),
             "latency_samples": 0,
             "tail_truncated_at_end": True}
    if p["bpm"] > 0:
        stats["predelay_note"] = nearest_note(p["predelay_ms"], p["bpm"])
        stats["rt60_note"] = nearest_note(p["rt60_s"] * 1000.0, p["bpm"])
    return y, sr, stats


# ---------------------------------------------------------------------------
# delay
# ---------------------------------------------------------------------------

def haas_region(ms: float) -> dict:
    """R-10 time-region of a delayed copy (precedence effect)."""
    if ms < 5.0:
        region, desc = "localisation", "< 5 ms: shifts localisation; comb filtering risk in mono"
    elif ms <= 30.0:
        region, desc = "fusion", "5-30 ms: fuses with the direct sound (precedence); widens"
    else:
        region, desc = "echo", "> 30 ms: heard as a separate echo"
    return {"region": region, "comb_risk": ms < 5.0, "description": desc}


def delay_ms(p: dict) -> float:
    if p["note"] != "none":
        return note_ms(p["note"], p["bpm"])
    return p["time_ms"]


def delay(x: np.ndarray, sr: int, p: dict, **_):
    t_ms = delay_ms(p)
    D = max(1, int(round(t_ms * 1e-3 * sr)))
    n, ch = x.shape
    route = p["route"] if ch == 2 else "both"
    cols = {"both": list(range(ch)), "left": [0], "right": [1]}[route]
    u, filt = _band_limit(x[:, cols], sr, p["lowcut_hz"], p["highcut_hz"])
    fb = p["feedback"]
    w = _strided_iir(u, D, [0.0, 1.0], [1.0, -fb])
    mix = p["mix"]
    y = x.copy()
    y[:, cols] = (1.0 - mix) * x[:, cols] + mix * w
    stats = {
        "delay_samples": D,
        "time_ms": round(D * 1000.0 / sr, 6),
        "time_ms_requested": round(t_ms, 6),
        "route": route,
        "feedback": fb,
        "mix": mix,
        "wet_filters": filt,
        "haas": haas_region(D * 1000.0 / sr),
        "echo_decay_60db_s": (round(D / sr * 60.0 / (-20.0 * math.log10(fb)), 4) if fb > 0 else None),
        "latency_samples": 0,
    }
    if p["note"] != "none":
        stats["note"] = {"value": p["note"], "bpm": p["bpm"], "note_ms": round(t_ms, 6)}
    elif p["bpm"] > 0:
        stats["note"] = nearest_note(D * 1000.0 / sr, p["bpm"])
    # R-10: the time region always comes with the mono fold-down loss
    if ch == 2:
        mo_in, mo_out = mono_fold(x[:, 0], x[:, 1]), mono_fold(y[:, 0], y[:, 1])
        delta = (round(mo_out["mono_loss_db"] - mo_in["mono_loss_db"], 3)
                 if mo_in["mono_loss_db"] is not None and mo_out["mono_loss_db"] is not None else None)
        # first-repeat comb of a centred source folded to mono
        if route == "both":
            a, b = 1.0 - mix, mix
        else:
            a, b = 1.0 - mix / 2.0, mix / 2.0
        depth = 20.0 * math.log10(abs(a - b) / (a + b)) if a != b else None
        stats["mono"] = {"in": mo_in, "out": mo_out, "loss_change_db": delta,
                         "comb_first_repeat": {"first_notch_hz": round(sr / (2.0 * D), 3),
                                               "notch_spacing_hz": round(sr / D, 3),
                                               "notch_depth_db": round(depth, 2) if depth is not None
                                               else "total"}}
    return y, sr, stats
