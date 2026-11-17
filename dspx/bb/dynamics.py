"""BB-03 detectors, gain computers and dynamics control primitives.

All levels/gains are amplitude dB; negative gain attenuates. coef(ms, sr)
uses exp(-1/(tau*sr)), the existing ballistics 63.212% definition. detector
and compressor_gain preserve the existing compressor's RMS and arithmetic.
API: detector, level_db, envelope, dual_envelope, smooth_gain, static_curve_db,
downward_gain_db, upward_gain_db, expander_gain_db, bilateral_gain_db,
compressor_gain, gate_gain, transient_gain, delay_audio, apply_gain.
GainSmoother and GateState retain their state across process() calls.
Program release smoothly interpolates fast/slow tau according to a smoothed
absolute gain demand; it never changes the fixed-release default path.
Algorithms are independently expressed from one-pole recurrences and
piecewise quadratic knees; no external implementation is ported.
"""
from __future__ import annotations

import math
import numpy as np
from scipy import fft, signal

from mankomix.dsp.errors import ParamError

# Lazy imports keep declaration discovery independent of reference.__init__,
# which itself collects the extension implementation table.
def coef(ms, sr):
    """63.212% one-pole time constant; identical to reference ballistics."""
    return math.exp(-1.0 / (ms * 1e-3 * sr))


def smooth_python(values, a, r):
    from mankomix.dsp.reference.ballistics import smooth_python as original
    return original(values, a, r)


def rms_detector(x, sr, window_ms):
    from mankomix.dsp.reference.dynamics import rms_detector as original
    return original(x, sr, window_ms)


def static_curve_db(level, threshold, ratio, knee):
    """Original compressor output-level curve (dB)."""
    from mankomix.dsp.reference.dynamics import static_curve_db as original
    return original(level, threshold, ratio, knee)


def gr_stats(gr):
    from mankomix.dsp.reference.dynamics import gr_stats as original
    return original(gr)


def detector(x, sr, mode='rms', window_ms=10, stereo_link=True):
    """Per-channel peak or causal rectangular RMS, optionally maximum-linked."""
    x = np.asarray(x, dtype=np.float64)
    if mode not in ('peak', 'rms'):
        raise ParamError('detector must be peak or rms')
    det = np.abs(x) if mode == 'peak' else rms_detector(x, sr, window_ms)
    return np.max(det, axis=1, keepdims=True) if stereo_link else det


def level_db(det):
    return 20.0 * np.log10(np.maximum(det, 1e-12))


def envelope(values, sr, attack_ms, release_ms):
    """Linear-amplitude follower, zero initial state, separate rise/fall tau."""
    a, r = coef(attack_ms, sr), coef(release_ms, sr)
    v = np.asarray(values, dtype=np.float64)
    if v.ndim == 1:
        return smooth_python(v, a, r)
    return np.column_stack([smooth_python(c, a, r) for c in v.T])


def dual_envelope(values, sr, fast_ms=1, slow_ms=20, release_ms=300):
    """Return fast, slow and fast-attack/long-release amplitude envelopes."""
    return (envelope(values, sr, fast_ms, fast_ms),
            envelope(values, sr, slow_ms, slow_ms),
            envelope(values, sr, fast_ms, release_ms))


class GainSmoother:
    """Stateful signed-dB smoother; attack increases absolute gain demand.

    program_release=(fast_ms, slow_ms, reference_db) enables adaptive release.
    Fixed positive attenuation traces match reference smooth_python exactly.
    """
    def __init__(self, sr, attack_ms, release_ms, *, program_release=None):
        self.sr, self.attack_ms, self.release_ms = sr, attack_ms, release_ms
        self.program_release = program_release
        self.state = None
        self.program_state = None

    def process(self, target):
        target = np.asarray(target, dtype=np.float64)
        mono = target.ndim == 1
        t = target[:, None] if mono else target
        if self.state is None:
            self.state = np.zeros(t.shape[1])
            self.program_state = np.zeros(t.shape[1])
        out = np.empty_like(t)
        aa, ar = coef(self.attack_ms, self.sr), coef(self.release_ms, self.sr)
        ap = coef(50, self.sr)
        for i, row in enumerate(t):
            for c, value in enumerate(row):
                prev = self.state[c]
                attack = abs(value) > abs(prev) or value * prev < 0
                a = aa if attack else ar
                if self.program_release is not None:
                    fast, slow, ref = self.program_release
                    self.program_state[c] = ap * self.program_state[c] + (1-ap) * abs(value)
                    if not attack:
                        tau = fast + (slow-fast) * min(1, self.program_state[c] / max(ref, 1e-12))
                        a = coef(tau, self.sr)
                self.state[c] = a * prev + (1-a) * value
                out[i, c] = self.state[c]
        return out[:, 0] if mono else out


def smooth_gain(target, sr, attack_ms, release_ms, *, program_release=None):
    return GainSmoother(sr, attack_ms, release_ms, program_release=program_release).process(target)


def downward_gain_db(level, threshold, ratio, knee=0, range_db=None):
    """Negative dB gain for downward compression; optional positive GR limit."""
    g = static_curve_db(level, threshold, ratio, knee) - level
    return np.maximum(g, -range_db) if range_db is not None else g


def upward_gain_db(level, threshold, ratio, max_gain_db=6, floor_db=-60, knee=6):
    """Mirrored quadratic knee; floor..floor-12 dB uses cubic smoothstep."""
    below = threshold - np.asarray(level, dtype=np.float64)
    slope = 1 - 1 / ratio
    if knee > 0:
        demand = np.where(below >= knee/2, below,
                          np.where(below > -knee/2, (below+knee/2)**2/(2*knee), 0))
    else:
        demand = np.maximum(below, 0)
    g = np.minimum(demand * slope, max_gain_db)
    f = np.clip((np.asarray(level) - (floor_db-12)) / 12, 0, 1)
    return g * f*f*(3-2*f)


def expander_gain_db(level, threshold, ratio, range_db=-40, knee=3):
    """Downward expansion: negative range_db bounds the attenuation."""
    below = threshold - np.asarray(level, dtype=np.float64)
    if knee > 0:
        demand = np.where(below >= knee/2, below,
                          np.where(below > -knee/2, (below+knee/2)**2/(2*knee), 0))
    else:
        demand = np.maximum(below, 0)
    return np.maximum(-(ratio-1)*demand, range_db)


def bilateral_gain_db(level, high_threshold_db, down_ratio, low_threshold_db,
                      up_ratio, max_gain_db=6, floor_db=-60, knee_db=6):
    if low_threshold_db > high_threshold_db - 3:
        raise ParamError('low_threshold_db must be at least 3 dB below high_threshold_db')
    return (downward_gain_db(level, high_threshold_db, down_ratio, knee_db) +
            upward_gain_db(level, low_threshold_db, up_ratio, max_gain_db, floor_db, knee_db))


def compressor_gain(x, sr, params):
    """Return positive smoothed GR with original compressor operation order."""
    det = detector(x, sr, params['detector'], params['rms_window_ms'], params['stereo_link'])
    level = level_db(det)
    gr = level - static_curve_db(level, params['threshold_db'], params['ratio'], params['knee_db'])
    a, r = coef(params['attack_ms'], sr), coef(params['release_ms'], sr)
    out = np.column_stack([smooth_python(c, a, r) for c in gr.T])
    return np.minimum(out, params.get('range_db', np.inf))


class GateState:
    """Hysteretic open/hold/closed machine and release/attack gain recursion.

    Opening is level >= threshold; closure requires hold samples below
    threshold-hysteresis. The hysteresis region retains the previous state.
    State is initially closed and gain initially zero dB, like ballistics.
    """
    def __init__(self, sr, params):
        self.sr, self.p = sr, params
        self.open = self.remaining = self.gain = None

    def process(self, levels):
        p, sr = self.p, self.sr
        levels = np.asarray(levels, dtype=np.float64)
        if self.open is None:
            self.open = np.zeros(levels.shape[1], dtype=bool)
            self.remaining = np.zeros(levels.shape[1], dtype=int)
            self.gain = np.zeros(levels.shape[1])
        out, states = np.empty_like(levels), np.empty_like(levels, dtype=np.int8)
        hold = round(p['hold_ms'] * sr/1000)
        aa, ar = coef(p['attack_ms'], sr), coef(p['release_ms'], sr)
        static = expander_gain_db(levels, p['threshold_db'], p['ratio'], p['range_db'], p['knee_db'])
        for i, row in enumerate(levels):
            for c, value in enumerate(row):
                if value >= p['threshold_db']:
                    self.open[c], self.remaining[c] = True, hold
                elif self.open[c]:
                    if value >= p['threshold_db'] - p['hysteresis_db']:
                        self.remaining[c] = hold
                    elif self.remaining[c] > 0:
                        self.remaining[c] -= 1
                    else:
                        self.open[c] = False
                target = (static[i, c] if value >= p['threshold_db'] else 0.0) if self.open[c] else static[i, c]
                a = aa if target > self.gain[c] else ar
                self.gain[c] = a*self.gain[c] + (1-a)*target
                # Preserve exact unity for a newly opened constant signal.
                out[i, c] = self.gain[c]
                states[i, c] = (2 if self.remaining[c] < hold else 1) if self.open[c] else 0
        return out, states


def gate_gain(x, sr, params):
    """Return (negative gain dB, state trace), with optional key HP/LP."""
    key = x
    for pid, kind in (('key_lo_hz', 'highpass'), ('key_hi_hz', 'lowpass')):
        freq = params.get(pid, 0)
        if freq:
            if freq >= .98 * sr/2:
                raise ParamError(f'{pid} must be below 0.98 * Nyquist')
            key = signal.sosfilt(signal.butter(2, freq, kind, fs=sr, output='sos'), key, axis=0)
    if params.get('key_lo_hz', 0) and params.get('key_hi_hz', 0) and params['key_lo_hz'] >= params['key_hi_hz']:
        raise ParamError('key_lo_hz must be below key_hi_hz')
    det = detector(key, sr, 'peak', stereo_link=params['stereo_link'])
    return GateState(sr, params).process(level_db(det))


def transient_gain(x, sr, params):
    """Level-independent difference-envelope gain, normalized in dB.

    Attack difference saturates at 6 dB; sustain difference has a 0.2 dB
    carrier-ripple deadband and saturates at 1 dB. These normalizations are
    dimensionless and independent of the absolute input level.
    """
    # Analytic amplitude removes carrier ripple before the difference
    # followers. Rectification with a fixed short RMS window would interpret
    # a steady low-frequency sine as repeated transients. This full-context
    # envelope is why the processor declares block_ok=False.
    with fft.set_workers(1):
        det = np.abs(signal.hilbert(x, axis=0))
    if params['stereo_link']:
        det = np.max(det, axis=1, keepdims=True)
    ef, es, er = dual_envelope(det, sr, params['fast_ms'], params['slow_ms'], params['sustain_release_ms'])
    tiny = np.finfo(np.float64).tiny
    af = 20*np.log10(np.maximum(ef, tiny)/np.maximum(es, tiny))
    sf = 20*np.log10(np.maximum(er, tiny)/np.maximum(ef, tiny))
    attack = np.clip(af/6, 0, 1)
    sustain = np.clip((sf-.2)/.8, 0, 1)
    gain = np.clip(params['attack_db']*attack + params['sustain_db']*sustain,
                   -params['max_gain_db'], params['max_gain_db'])
    return envelope_signed(gain, sr, 1)


def envelope_signed(values, sr, ms):
    """Symmetric one-pole smoothing for signed dB, with zero initial state."""
    a = coef(ms, sr)
    return signal.lfilter([1-a], [1, -a], values, axis=0)


def delay_audio(x, samples):
    """Causal integer signal-side delay, same length, zero initial state."""
    if samples < 0:
        raise ParamError('delay must be nonnegative')
    return np.pad(x, ((samples, 0), (0, 0)))[:len(x)] if samples else x.copy()


def apply_gain(x, gain_db, output_db=0):
    """Exact unity at zero dB; signed gain may be linked or per-channel."""
    return x * np.exp((gain_db + output_db) * (math.log(10)/20))
