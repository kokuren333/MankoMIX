"""SOS cut filters and linear-phase magnitude equivalents.

Uses public scipy.signal design functions (SciPy 1.18.1, BSD-3-Clause);
no implementation code copied. See third_party/W1b_APIS.md.
"""
import numpy as np
from scipy import signal, optimize
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _e, _f
from mankomix.dspx.bb.fir import resolution_taps, design_linear_fir, apply_fir


def check(p, sr):
    if p["family"] == "linkwitz_riley" and p["slope_db_oct"] % 12:
        raise ParamError("cut_filter: linkwitz_riley requires a multiple of 12 dB/oct")
    if p["resonance_db"] and (p["family"] != "butterworth" or p["slope_db_oct"] < 12):
        raise ParamError("cut_filter: resonance requires butterworth and at least 12 dB/oct")
    if p["freq_hz"] >= .49*sr:
        raise ParamError("cut_filter: freq_hz must be below 0.98 * Nyquist")


def _resonant_butter(order, cutoff, kind, sr, resonance):
    # Raise Q of only the pole pair with the smallest damping; all pole radii
    # stay unity in the normalized analog prototype. The passband stays unity.
    z, poles, gain = signal.butter(order, 1, analog=True, output="zpk")
    index = int(np.argmax(poles.imag))
    conjugate = int(np.argmin(np.abs(poles - poles[index].conjugate())))
    base_q = -1/(2*poles[index].real)

    def prototype(q):
        pp = poles.copy()
        pp[index] = -1/(2*q) + 1j*np.sqrt(1-1/(4*q*q))
        pp[conjugate] = pp[index].conjugate()
        return pp

    def peak(q):
        pp = prototype(q)
        # All other factors are smooth; the resonant maximum is below the
        # normalized cutoff. Bounded scalar search also resolves very high Q.
        result = optimize.minimize_scalar(
            lambda w: -abs(signal.freqs_zpk(z, pp, gain, worN=[w])[1][0]),
            bounds=(0, 1.01), method="bounded", options={"xatol": 1e-12})
        return 20*np.log10(max(1, -result.fun))

    q = optimize.brentq(lambda value: peak(value)-resonance, base_q, 1e5)
    prewarp = 2*sr*np.tan(np.pi*cutoff/sr)
    transform = signal.lp2hp_zpk if kind == "hpf" else signal.lp2lp_zpk
    z, poles, gain = transform(z, prototype(q), gain, wo=prewarp)
    return signal.zpk2sos(*signal.bilinear_zpk(z, poles, gain, fs=sr))


def design_sos(p, sr):
    check(p, sr)
    order = p["slope_db_oct"] // 6
    kind = "highpass" if p["kind"] == "hpf" else "lowpass"
    family, cutoff = p["family"], p["freq_hz"]
    if family == "butterworth":
        if p["resonance_db"]:
            return _resonant_butter(order, cutoff, p["kind"], sr, p["resonance_db"])
        return signal.butter(order, cutoff, kind, fs=sr, output="sos")
    if family == "linkwitz_riley":
        half = order // 2
        sos = signal.butter(half, cutoff, kind, fs=sr, output="sos")
        sos = np.concatenate((sos, sos))
        # LR2/LR6/... require reversed HP polarity for an all-pass sum.
        if p["kind"] == "hpf" and half % 2:
            sos[0, :3] *= -1
        return sos
    if family == "bessel":
        return signal.bessel(order, cutoff, kind, fs=sr, output="sos", norm="mag")
    return signal.ellip(order, p["ripple_db"], p["stopband_db"], cutoff,
                        kind, fs=sr, output="sos")


def design(p, sr):
    sos = design_sos(p, sr)
    return design_linear_fir(lambda f: np.abs(signal.sosfreqz(sos, worN=f, fs=sr)[1]),
                             sr, resolution_taps(sr, "mid"))


def cut_filter(x, sr, p, *, seed=0):
    sos = design_sos(p, sr)
    if p["phase"] == "linear":
        y, stats = apply_fir(x, design(p, sr), sr)
    else:
        y = signal.sosfilt(sos, x, axis=0)
        stats = {"latency_samples": 0, "phase_cost": {"phase_type": "minimum"}}
    stats.update(order=p["slope_db_oct"]//6, design=p["family"],
                 hpf_polarity=(-1 if p["phase"] == "minimum" and p["family"] == "linkwitz_riley"
                               and (p["slope_db_oct"]//12) % 2 and p["kind"] == "hpf" else 1))
    return y, sr, stats


SPECS = [{"type": "cut_filter", "description": "SOS cut filters with optional linear-phase FIR.",
          "params": [_e("kind", ["hpf", "lpf"], "hpf", "Cut direction."),
                     _f("freq_hz", "Hz", 10, 24000, 30, "Cutoff frequency."),
                     _e("family", ["butterworth", "linkwitz_riley", "bessel", "elliptic"], "butterworth", "Filter family."),
                     _e("slope_db_oct", [6, 12, 18, 24, 36, 48, 72, 96], 24, "Order times six.", "dB/oct"),
                     _f("resonance_db", "dB", 0, 12, 0, "Peak resonance; Butterworth order >= 2 only."),
                     _f("ripple_db", "dB", .01, 1, .1, "Elliptic passband ripple."),
                     _f("stopband_db", "dB", 40, 120, 80, "Elliptic stopband attenuation."),
                     _e("phase", ["minimum", "linear"], "minimum", "Filter phase.")],
          "stages": ["track", "bus", "master"], "master_slot": 1,
          "realtime": {"block_ok": True, "latency_samples": 0, "allocates": True,
                       "latency_rule": "linear: (resolution_taps(sr,'mid')-1)/2; minimum: 0; compensated offline"},
          "offline_only": False, "backends": ["reference"], "implemented": True}]
IMPLS = {"cut_filter": cut_filter}
