"""Zwicker loudness after ISO 532-1:2017 (method 1) -- M10 prototype, NOT wired in.

Status: prototype for the M10 study (docs/M10_STUDIES.md, section c). Nothing in
the measurement vector (SPEC 4.2), the objectives or the planner calls this
module. Wiring it in (as a new proxy or as a validator of P-01 / P-11) needs a
decision record first.

What is implemented
-------------------
- ``loudness_from_third_octave_levels``: the stationary core of the method from
  28 one-third-octave band levels (25 Hz .. 12.5 kHz, dB SPL): low-frequency
  correction by equal-loudness contours, critical-band levels, core loudness,
  correction of the lowest critical band, upper masking slopes, total loudness
  N (sone), loudness level LN (phon) and the specific loudness N'(z) on the
  0.1 .. 24 Bark grid (240 values).
- ``third_octave_levels``: one-third-octave band levels of a signal.
- ``loudness_zwicker``: stationary (``method="stationary"``) or time-varying
  (``method="time_varying"``) loudness of a signal. The time-varying path adds
  the 0.5 ms band-level tracking, the non-linear temporal decay of the core
  loudness and the temporal weighting of the total loudness (3.5 ms / 70 ms),
  and reports N(t) every 2 ms with Nmax, N5 and N10.

Calibration (explicit, never implied)
-------------------------------------
Digital audio has no absolute level. ``calibration_db_spl`` is REQUIRED and
states the sound pressure level, in dB re 20 uPa, of a full-scale digital sine
(peak 1.0, i.e. 0 dBFS in the AES17 sense, RMS 1/sqrt(2)). The conversion is
``p[Pa] = x * 20e-6 * 10**(calibration_db_spl / 20) * sqrt(2)``.
The WAV files distributed with ISO 532-1 use 100 dB (a sample value of 1.0 is
2*sqrt(2) Pa). For a mix the value is a listening-level assumption, not a
property of the file; record it next to every result.

Provenance (no copied code)
---------------------------
- Algorithm and constant tables (RAP, DLL, LTQ, A0, DDF, DCB, ZUP, RNS, USL)
  follow the BASIC program published by E. Zwicker, H. Fastl, U. Widmann,
  K. Kurakata, S. Kuwano and S. Namba, "Program for calculating loudness
  according to DIN 45631 (ISO 532 B)", J. Acoust. Soc. Jpn. (E) 12(1), 39-42
  (1991), which ISO 532-1:2017 adopts unchanged for the stationary core. The
  transcription of the tables was cross-checked against MoSQITo
  (Apache-2.0, https://github.com/Eomys/MoSQITo). The code here is written
  independently; the ISO 532-1 C program (ISO customer licence, not permissive)
  was not used.
- The time-varying steps (smoothing time constants, decay time constants
  5 ms / 15 ms / 75 ms with 24 interpolation steps, weighting 0.47 x 3.5 ms +
  0.53 x 70 ms) are the published parameters of the method; the state update
  of the non-linear decay is written from its description (cross-checked
  against MoSQITo, Apache-2.0).
- One-third-octave filters are OUR OWN design: 6th-order Butterworth band-pass
  (scipy, bilinear transform) on the IEC 61260-1 base-10 band edges
  fm * 10**(+-1/20) at 48 kHz. ISO 532-1 Annex A prescribes a specific
  coefficient table that we do not reproduce. Measured difference to that
  filter bank: identical gain at the band centre (< 0.01 dB), about 2 % wider
  -3 dB bandwidth (about +0.1 dB band level for broadband noise). Results for
  tones at band centres are unaffected; broadband results can differ by about
  1 %. This is inside the 5 % tolerance of ISO 532-1 clause 5.1 / 6.1 but it
  is a documented deviation.

Signals: float arrays, 1-D (mono) or [frames, channels]. Each channel is
evaluated on its own (the method is monaural); the top-level result is the
channel with the largest loudness and ``per_channel`` keeps all of them.
Signals at other rates are resampled to 48 kHz with scipy's polyphase filter
(D-057: numpy / scipy only).
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
from scipy import signal as _sig

ANALYZER = "mankomix.analysis.iso532_1/0.1-prototype"
STANDARD = "ISO 532-1:2017 method 1 (Zwicker); prototype, not wired into the measurement vector"

P_REF = 20e-6
I_REF = P_REF * P_REF
FS_STD = 48000
N_BANDS = 28
# Exact mid-band frequencies (IEC 61260-1, base 10): 1000 * 10**(k/10), k = -16 .. 11.
CENTRES_HZ = 1000.0 * 10.0 ** ((np.arange(N_BANDS) - 16) / 10.0)
NOMINAL_HZ = [25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630,
              800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500]
BARK_AXIS = np.round(np.arange(1, 241) * 0.1, 1)

# ---------------------------------------------------------------------------
# Constant tables (Zwicker et al. 1991; ISO 532-1:2017 Annex A, same values).

# Upper limits of the eight level ranges for the low-frequency correction (dB).
_RAP = np.array([45.0, 55.0, 65.0, 71.0, 80.0, 90.0, 100.0, 120.0])
# Level reduction of the 11 one-third-octave bands 25 .. 250 Hz in each range (dB).
_DLL = np.array([
    [-32, -24, -16, -10, -5, 0, -7, -3, 0, -2, 0],
    [-29, -22, -15, -10, -4, 0, -7, -2, 0, -2, 0],
    [-27, -19, -14, -9, -4, 0, -6, -2, 0, -2, 0],
    [-25, -17, -12, -9, -3, 0, -5, -2, 0, -2, 0],
    [-23, -16, -11, -7, -3, 0, -4, -1, 0, -1, 0],
    [-20, -14, -10, -6, -3, 0, -4, -1, 0, -1, 0],
    [-18, -12, -9, -6, -2, 0, -3, -1, 0, -1, 0],
    [-15, -10, -8, -4, -2, 0, -3, -1, 0, -1, 0],
], dtype=np.float64)
# Critical-band level at the threshold in quiet, without the ear transmission (dB).
_LTQ = np.array([30, 18, 12, 8, 7, 6, 5, 4, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3], dtype=np.float64)
# Transmission of the outer / middle ear (dB, subtracted).
_A0 = np.array([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -0.5, -1.6, -3.2, -5.4, -5.6, -4.0, -1.5, 2.0, 5.0, 12.0])
# Free-field to diffuse-field level difference (dB, added for field="diffuse").
_DDF = np.array([0, 0, 0.5, 0.9, 1.2, 1.6, 2.3, 2.8, 3.0, 2.0, 0, -1.4, -2.0, -1.9, -1.0, 0.5, 3.0, 4.0, 4.3, 4.0])
# One-third-octave band level to critical-band level adaptation (dB, subtracted).
_DCB = np.array([-0.25, -0.6, -0.8, -0.8, -0.5, 0, 0.5, 1.1, 1.5, 1.7, 1.8, 1.8, 1.7, 1.6, 1.4, 1.2, 0.8, 0.5, 0, -0.5])
# Upper limits (Bark) of the 20 approximated critical bands, plus 24 Bark.
_ZUP = np.array([0.9, 1.8, 2.8, 3.5, 4.4, 5.4, 6.6, 7.9, 9.2, 10.6, 12.3, 13.8, 15.2, 16.7, 18.1, 19.3,
                 20.6, 21.8, 22.7, 23.6, 24.0])
# Specific-loudness ranges selecting the steepness of the upper slope (sone/Bark).
_RNS = np.array([21.5, 18, 15.1, 11.5, 9, 6.1, 4.4, 3.1, 2.13, 1.36, 0.82, 0.42, 0.30, 0.22, 0.15, 0.10,
                 0.035, 0.0])
# Steepness of the upper slopes (sone/Bark per Bark): row = range in _RNS, column =
# critical band of the masker (columns beyond the 8th repeat the 8th).
_USL = np.array([
    [13.00, 8.20, 6.30, 5.50, 5.50, 5.50, 5.50, 5.50],
    [9.00, 7.50, 6.00, 5.10, 4.50, 4.50, 4.50, 4.50],
    [7.80, 6.70, 5.60, 4.90, 4.40, 3.90, 3.90, 3.90],
    [6.20, 5.40, 4.60, 4.00, 3.50, 3.20, 3.20, 3.20],
    [4.50, 3.80, 3.60, 3.20, 2.90, 2.70, 2.70, 2.70],
    [3.70, 3.00, 2.80, 2.35, 2.20, 2.20, 2.20, 2.20],
    [2.90, 2.30, 2.10, 1.90, 1.80, 1.70, 1.70, 1.70],
    [2.40, 1.70, 1.50, 1.35, 1.30, 1.30, 1.30, 1.30],
    [1.95, 1.45, 1.30, 1.15, 1.10, 1.10, 1.10, 1.10],
    [1.50, 1.20, 0.94, 0.86, 0.82, 0.82, 0.82, 0.82],
    [0.72, 0.67, 0.64, 0.63, 0.62, 0.62, 0.62, 0.62],
    [0.59, 0.53, 0.51, 0.50, 0.42, 0.42, 0.42, 0.42],
    [0.40, 0.33, 0.26, 0.24, 0.24, 0.22, 0.22, 0.22],
    [0.27, 0.21, 0.20, 0.18, 0.17, 0.17, 0.17, 0.17],
    [0.16, 0.15, 0.14, 0.12, 0.11, 0.11, 0.11, 0.11],
    [0.12, 0.11, 0.10, 0.08, 0.08, 0.08, 0.08, 0.08],
    [0.09, 0.08, 0.07, 0.06, 0.06, 0.06, 0.06, 0.05],
    [0.06, 0.05, 0.03, 0.02, 0.02, 0.02, 0.02, 0.02],
])

# Time-varying method parameters.
_LEVEL_RATE = 2000.0          # band levels / core loudness every 0.5 ms
_OUT_DECIMATION = 4           # N(t) reported every 2 ms
_NL_ITER = 24                 # interpolation steps of the decay and weighting filters
_T_SHORT, _T_LONG, _T_VAR = 0.005, 0.015, 0.075
_TW_SHORT, _TW_LONG, _TW_MIX = 0.0035, 0.070, 0.47
_LF_MAX_DB = 120.0            # validity limit of the low-frequency table
_LEVEL_FLOOR = 1e-12          # Pa^2 added before the log (silence -> about -26 dB SPL)


# ---------------------------------------------------------------------------
# Calibration


def pascal_per_unit(calibration_db_spl: float) -> float:
    """Pa per digital unit when a full-scale sine (peak 1.0) has ``calibration_db_spl`` dB SPL."""
    if calibration_db_spl is None or not math.isfinite(float(calibration_db_spl)):
        raise ValueError("calibration_db_spl must be a finite number (dB SPL of a full-scale sine)")
    return P_REF * 10.0 ** (float(calibration_db_spl) / 20.0) * math.sqrt(2.0)


# ---------------------------------------------------------------------------
# Stationary core: third-octave levels -> core loudness -> specific loudness


def _check_field(field: str) -> str:
    if field not in ("free", "diffuse"):
        raise ValueError("field must be 'free' or 'diffuse'")
    return field


def _core_loudness(levels: np.ndarray, field: str) -> np.ndarray:
    """Core loudness of the 20 critical bands plus a trailing 0 -> shape (21, T).

    ``levels``: one-third-octave levels in dB SPL, shape (28, T).
    """
    lt = np.asarray(levels, dtype=np.float64)
    t = lt.shape[1]
    # Low-frequency correction of the bands 25 .. 250 Hz: the first range j whose
    # limit RAP[j] - DLL[j, i] is not exceeded; the last range otherwise.
    low = lt[:11]
    thr = _RAP[:, None] - _DLL                                # (8, 11)
    exceeded = low[None, :, :] > thr[:, :, None]              # (8, 11, T)
    j = np.minimum(np.argmin(exceeded, axis=0), 7)            # first not exceeded
    j = np.where(exceeded.all(axis=0), 7, j)
    dll = _DLL[j, np.arange(11)[:, None]]                     # (11, T)
    ti = 10.0 ** ((low + dll) / 10.0)
    gi = np.stack([ti[0:6].sum(0), ti[6:9].sum(0), ti[9:11].sum(0)])
    with np.errstate(divide="ignore"):
        lcb = np.where(gi > 0, 10.0 * np.log10(np.maximum(gi, 1e-300)), -np.inf)
    le = np.concatenate([lcb, lt[11:]], axis=0)               # (20, T): 3 + 17 bands
    le = le - _A0[:, None]
    if field == "diffuse":
        le = le + _DDF[:, None]
    ltq = _LTQ[:, None]
    above = le > ltq
    le = np.where(above, le - _DCB[:, None], le)
    s = 0.25
    with np.errstate(over="ignore", invalid="ignore"):
        mp1 = 0.0635 * 10.0 ** (0.025 * ltq)
        mp2 = (1.0 - s + s * 10.0 ** ((le - ltq) / 10.0)) ** 0.25 - 1.0
        nm = np.where(above, mp1 * mp2, 0.0)
    nm = np.maximum(nm, 0.0)
    # Lowest critical band: dependence of the threshold within the band.
    korr = 0.4 + 0.32 * nm[0] ** 0.2
    nm[0] = nm[0] * np.minimum(korr, 1.0)
    return np.vstack([nm, np.zeros((1, t))])


def _slopes(nm: np.ndarray) -> tuple[float, np.ndarray]:
    """Total loudness and specific loudness (240 values) from 21 core-loudness values."""
    ns = np.zeros(240)
    total = 0.0
    z1 = 0.0
    n1 = 0.0
    j = 0          # index into _RNS
    k = 0          # next index of the 0.1-Bark grid (z = (k + 1) / 10)
    for i in range(21):
        zup = _ZUP[i] + 1e-4
        ig = min(max(i - 1, 0), 7)
        nmi = float(nm[i])
        while z1 < zup:
            if n1 > nmi:
                usl = _USL[j, ig]
                n2 = max(_RNS[j], nmi)
                dz = (n1 - n2) / usl
                z2 = z1 + dz
                if z2 > zup:
                    z2 = zup
                    dz = z2 - z1
                    n2 = n1 - dz * usl
                total += dz * (n1 + n2) / 2.0
                while k < 240 and (k + 1) / 10.0 <= z2:
                    ns[k] = n1 - ((k + 1) / 10.0 - z1) * usl
                    k += 1
            else:
                if n1 < nmi:
                    j = 0
                    while j < 17 and _RNS[j] >= nmi:
                        j += 1
                z2 = zup
                n2 = nmi
                total += n2 * (z2 - z1)
                while k < 240 and (k + 1) / 10.0 <= z2:
                    ns[k] = n2
                    k += 1
            if n2 <= _RNS[j]:
                j += 1
            if j > 17:
                j = 17
            n1, z1 = n2, z2
    return max(total, 0.0), np.maximum(ns, 0.0)


def _round_n(n: float) -> float:
    """Rounding of the total loudness prescribed by the method (3 decimals up to 16 sone)."""
    if n <= 16.0:
        return math.floor(n * 1000.0 + 0.5) / 1000.0
    return math.floor(n * 100.0 + 0.5) / 100.0


def loudness_level_phon(n_sone: float) -> float:
    """Loudness level LN (phon) from loudness N (sone), ISO 532-1 relation."""
    n = float(n_sone)
    if n < 1.0:
        return 40.0 * (n + 0.0005) ** 0.35
    return 10.0 * math.log2(n) + 40.0


def loudness_from_third_octave_levels(levels_db, field: str = "free") -> dict:
    """Stationary Zwicker loudness from 28 one-third-octave levels (dB SPL, 25 Hz .. 12.5 kHz)."""
    _check_field(field)
    lt = np.asarray(levels_db, dtype=np.float64).reshape(-1)
    if lt.shape != (N_BANDS,):
        raise ValueError(f"expected {N_BANDS} one-third-octave levels (25 Hz .. 12.5 kHz)")
    if not np.all(np.isfinite(lt)):
        raise ValueError("levels must be finite (use a low value such as -60 dB for empty bands)")
    warnings = []
    if float(lt[:11].max()) > _LF_MAX_DB:
        warnings.append("a band at or below 250 Hz exceeds 120 dB; the method is not specified there")
    nm = _core_loudness(lt[:, None], field)[:, 0]
    n_raw, ns = _slopes(nm)
    n = _round_n(n_raw)
    return {
        "analyzer": ANALYZER, "standard": STANDARD, "method": "stationary", "field": field,
        "N_sone": n, "N_sone_unrounded": n_raw, "LN_phon": loudness_level_phon(n),
        "specific_loudness": ns.tolist(), "bark_axis": BARK_AXIS.tolist(),
        "core_loudness": nm[:20].tolist(), "third_octave_levels_db": lt.tolist(),
        "third_octave_centres_hz": NOMINAL_HZ, "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Signal path


def _as_channels(x) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        return a[:, None]
    if a.ndim == 2:
        return a
    raise ValueError("signal must be 1-D or [frames, channels]")


def _to_48k(x: np.ndarray, sr: float) -> np.ndarray:
    if int(sr) == FS_STD and float(sr) == FS_STD:
        return x
    if sr < 2 * 14200:
        raise ValueError("sample rate too low for the 12.5 kHz band (needs >= 28.4 kHz)")
    fr = Fraction(FS_STD, int(round(sr))).limit_denominator(1000)
    return _sig.resample_poly(x, fr.numerator, fr.denominator, axis=0)


_SOS_CACHE: list | None = None


def _filter_bank() -> list:
    """Own design: 6th-order Butterworth band-pass on base-10 band edges, at 48 kHz."""
    global _SOS_CACHE
    if _SOS_CACHE is None:
        half = 10.0 ** (1.0 / 20.0)
        _SOS_CACHE = [_sig.butter(3, [fc / half, fc * half], btype="bandpass", fs=FS_STD, output="sos")
                      for fc in CENTRES_HZ]
    return _SOS_CACHE


def _band_signals(p: np.ndarray):
    """Yield (band index, band-filtered pressure) for a 1-D pressure signal at 48 kHz."""
    for b, sos in enumerate(_filter_bank()):
        yield b, _sig.sosfilt(sos, p)


def third_octave_levels(x, sr: float, *, calibration_db_spl: float, skip_s: float = 0.2) -> np.ndarray:
    """Long-term one-third-octave levels (dB SPL), shape (28,) or (28, channels).

    The band power is averaged from ``skip_s`` to the end (the start is skipped
    so that filter onsets do not count). ``calibration_db_spl`` as in
    ``loudness_zwicker``.
    """
    xc = _to_48k(_as_channels(x), sr) * pascal_per_unit(calibration_db_spl)
    start = int(round(max(skip_s, 0.0) * FS_STD))
    if xc.shape[0] - start < FS_STD // 20:
        raise ValueError("signal too short after skip_s (need at least 50 ms)")
    out = np.empty((N_BANDS, xc.shape[1]))
    for c in range(xc.shape[1]):
        for b, y in _band_signals(xc[:, c]):
            out[b, c] = 10.0 * np.log10(np.mean(y[start:] ** 2) / I_REF + _LEVEL_FLOOR / I_REF)
    return out[:, 0] if np.asarray(x).ndim == 1 else out


def _band_level_tracks(p: np.ndarray) -> np.ndarray:
    """Band levels every 0.5 ms: square, 3 x first-order smoothing, decimate (shape (28, T))."""
    dec = int(FS_STD / _LEVEL_RATE)
    n_out = (p.shape[0] + dec - 1) // dec
    out = np.empty((N_BANDS, n_out))
    for b, y in _band_signals(p):
        fc = CENTRES_HZ[b]
        tau = 2.0 / (3.0 * fc) if fc <= 1000.0 else 2.0 / 3000.0
        a1 = math.exp(-1.0 / (FS_STD * tau))
        e = y * y
        for _ in range(3):
            e = _sig.lfilter([1.0 - a1], [1.0, -a1], e)
        out[b] = 10.0 * np.log10((e[::dec] + _LEVEL_FLOOR) / I_REF)
    return out


def _decay_coefficients() -> tuple:
    dt = 1.0 / (_LEVEL_RATE * _NL_ITER)
    p = (_T_VAR + _T_LONG) / (_T_VAR * _T_SHORT)
    q = 1.0 / (_T_SHORT * _T_VAR)
    l1 = -p / 2.0 + math.sqrt(p * p / 4.0 - q)
    l2 = -p / 2.0 - math.sqrt(p * p / 4.0 - q)
    den = _T_VAR * (l1 - l2)
    e1, e2 = math.exp(l1 * dt), math.exp(l2 * dt)
    return ((e1 - e2) / den,
            ((_T_VAR * l2 + 1.0) * e1 - (_T_VAR * l1 + 1.0) * e2) / den,
            ((_T_VAR * l1 + 1.0) * e1 - (_T_VAR * l2 + 1.0) * e2) / den,
            (_T_VAR * l1 + 1.0) * (_T_VAR * l2 + 1.0) * (e1 - e2) / den,
            math.exp(-dt / _T_LONG),
            math.exp(-dt / _T_VAR))


def _decay_band(c: list, coeffs: tuple) -> list:
    """Non-linear temporal decay of one band's core loudness (0.5 ms steps).

    Between two input samples the input is interpolated linearly in _NL_ITER
    steps; the output is the filter state at each original sample instant.
    State: uo (output) and u2 (the slower, second state of the decay).
    Scalar Python on purpose: about 8x faster than numpy on 21-element arrays.
    """
    b0, b1, b2, b3, b4, b5 = coeffs
    t = len(c)
    res = [0.0] * t
    uo = u2 = 0.0
    for n in range(t):
        ui = c[n]
        step = ((c[n + 1] if n + 1 < t else 0.0) - ui) / _NL_ITER
        for it in range(_NL_ITER):
            if ui < uo:                       # falling input: decay
                if uo > u2:                   # two-time-constant phase
                    nu2 = uo * b0 - u2 * b1
                    nuo = uo * b2 - u2 * b3
                    if ui > nuo:
                        nuo = ui
                    if nu2 > nuo:
                        nu2 = nuo
                    uo, u2 = nuo, nu2
                else:                         # single long time constant
                    uo = uo * b4
                    if ui > uo:
                        uo = ui
                    u2 = uo
            else:                             # rising or equal: follow the input
                if abs(ui - uo) < 1e-5 and ui <= u2:
                    u2 = ui
                else:
                    u2 = (u2 - ui) * b5 + ui
                uo = ui
            if it == 0:
                res[n] = uo
            ui += step
    return res


def _nonlinear_decay(core: np.ndarray) -> np.ndarray:
    """Non-linear temporal decay of the core loudness, band by band (shape (21, T))."""
    coeffs = _decay_coefficients()
    out = np.zeros_like(core)
    for b in range(core.shape[0]):
        if core.shape[1] and float(core[b].max()) > 0.0:
            out[b] = _decay_band(core[b].tolist(), coeffs)
    return out


def _interp_lowpass(x: np.ndarray, tau: float) -> np.ndarray:
    """First-order low-pass on the 2 kHz series with 24-step linear interpolation."""
    a1 = math.exp(-1.0 / (_LEVEL_RATE * _NL_ITER * tau))
    nxt = np.concatenate([x[1:], [0.0]])
    fine = x[:, None] + (nxt - x)[:, None] * (np.arange(_NL_ITER)[None, :] / _NL_ITER)
    y = _sig.lfilter([1.0 - a1], [1.0, -a1], fine.reshape(-1))
    return y.reshape(-1, _NL_ITER)[:, 0]


def _percentile_exceeded(series: np.ndarray, pct: float) -> float:
    """Loudness exceeded during pct % of the time (N5 for pct = 5)."""
    if series.size == 0:
        return 0.0
    return float(np.percentile(series, 100.0 - pct))


def _stationary_channel(levels: np.ndarray, field: str) -> dict:
    return loudness_from_third_octave_levels(levels, field)


def _time_varying_channel(p: np.ndarray, field: str, skip_s: float, return_specific: bool) -> dict:
    tracks = _band_level_tracks(p)
    warnings = []
    if float(tracks[:11].max(initial=-np.inf)) > _LF_MAX_DB:
        warnings.append("a band at or below 250 Hz exceeds 120 dB; the method is not specified there")
    core = _nonlinear_decay(_core_loudness(tracks, field))
    t = core.shape[1]
    n_t = np.empty(t)
    keep = return_specific
    spec = np.empty((240, (t + _OUT_DECIMATION - 1) // _OUT_DECIMATION)) if keep else None
    for n in range(t):
        n_t[n], ns = _slopes(core[:, n])
        if keep and n % _OUT_DECIMATION == 0:
            spec[:, n // _OUT_DECIMATION] = ns
    weighted = (_TW_MIX * _interp_lowpass(n_t, _TW_SHORT)
                + (1.0 - _TW_MIX) * _interp_lowpass(n_t, _TW_LONG))
    n_out = weighted[::_OUT_DECIMATION]
    time_s = np.arange(n_out.size) * (_OUT_DECIMATION / _LEVEL_RATE)
    stats = n_out[time_s >= skip_s] if np.any(time_s >= skip_s) else n_out
    n5 = _percentile_exceeded(stats, 5.0)
    res = {
        "N_sone_series": n_out.tolist(), "time_s": time_s.tolist(),
        "N_max_sone": float(stats.max(initial=0.0)), "N5_sone": n5,
        "N10_sone": _percentile_exceeded(stats, 10.0), "LN_phon": loudness_level_phon(n5),
        "warnings": warnings,
    }
    if keep:
        res["specific_loudness"] = spec.T.tolist()
        res["bark_axis"] = BARK_AXIS.tolist()
    return res


def loudness_zwicker(x, sr: float, field: str = "free", *, calibration_db_spl: float,
                     method: str = "stationary", skip_s: float = 0.2,
                     return_specific: bool = False) -> dict:
    """Zwicker loudness (ISO 532-1:2017 method 1) of a signal. Prototype; not in the vector.

    Parameters
    ----------
    x, sr:        signal (1-D or [frames, channels]) and its sample rate.
    field:        "free" (frontal free field) or "diffuse".
    calibration_db_spl: REQUIRED. dB SPL of a full-scale digital sine (peak 1.0).
                  ISO 532-1's own WAV files use 100. For music this is the
                  assumed listening level and must be stored with the result.
    method:       "stationary" (long-term third-octave levels) or "time_varying".
    skip_s:       start of the analysed part (filter onsets are not counted);
                  for "time_varying" it also limits the statistics (Nmax, N5, N10).
    return_specific: time-varying only; include N'(z, t) every 2 ms (large).

    Returns a JSON-safe dict. Stationary: N_sone, LN_phon, specific_loudness
    (240 values, sone/Bark, z = 0.1 .. 24 Bark), core_loudness,
    third_octave_levels_db. Time-varying: N_sone_series and time_s (2 ms),
    N_max_sone, N5_sone, N10_sone, LN_phon (of N5). Both: calibration,
    per_channel (when there is more than one channel), warnings.
    """
    _check_field(field)
    if method not in ("stationary", "time_varying"):
        raise ValueError("method must be 'stationary' or 'time_varying'")
    xc = _to_48k(_as_channels(x), sr) * pascal_per_unit(calibration_db_spl)
    if not np.all(np.isfinite(xc)):
        raise ValueError("signal contains NaN or infinity")
    results = []
    for c in range(xc.shape[1]):
        p = xc[:, c]
        if method == "stationary":
            start = int(round(max(skip_s, 0.0) * FS_STD))
            if p.size - start < FS_STD // 20:
                raise ValueError("signal too short after skip_s (need at least 50 ms)")
            lv = np.array([10.0 * np.log10(np.mean(y[start:] ** 2) / I_REF + _LEVEL_FLOOR / I_REF)
                           for _, y in _band_signals(p)])
            r = _stationary_channel(lv, field)
        else:
            r = _time_varying_channel(p, field, skip_s, return_specific)
        results.append(r)
    key = "N_sone" if method == "stationary" else "N5_sone"
    best = max(range(len(results)), key=lambda i: results[i][key])
    out = dict(results[best])
    out.update({
        "analyzer": ANALYZER, "standard": STANDARD, "method": method, "field": field,
        "calibration": {"calibration_db_spl": float(calibration_db_spl),
                        "definition": "dB SPL of a full-scale digital sine (peak 1.0)",
                        "pa_per_unit": pascal_per_unit(calibration_db_spl)},
        "sample_rate_in": float(sr), "sample_rate_analysis": FS_STD, "skip_s": float(skip_s),
        "channel": best, "filter_bank": "own 6th-order Butterworth, IEC 61260-1 base-10 edges "
                                        "(not the ISO 532-1 Annex A coefficient table)",
    })
    if len(results) > 1:
        out["per_channel"] = [{k: r[k] for k in (key, "LN_phon")} for r in results]
    return out
