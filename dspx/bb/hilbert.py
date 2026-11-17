"""Reusable causal IIR quadrature pair for frequency shifting.

HilbertPair(channels).process(x) returns (in_phase, quadrature), preserving
state across blocks. hilbert_pair(x) is a zero-state whole-context wrapper.
pair_response(frequencies, sr) returns both complex responses for inspection.
frequency_shift(x, sr, cycles, feedback=0, lo_hz=20, max_up_hz=0) returns
upper/lower shifted arrays; cycles is an absolute integrated shift phase.

Parallel allpass principle: Wardle, DAFx-98, section 5.2,
https://dafx.de/paper-archive/1998/WAR19.PS.pdf . Independent first-order
design, no source code copied. The fixed pole locations were fitted to phase
quadrature on 20/96000..0.45 cycles/sample, using analytic allpass phases.
Each branch is exactly allpass; group delay is frequency-dependent and is
intentionally not compensated (declared latency zero). DC crossings fold.
"""
import numpy as np
from scipy import signal

_LOG_Q = np.array([
    8.776074002094283, 7.610622199639055, 6.971724922689762, 6.454823866777292,
    5.980293355963839, 5.522331395887712, 5.0711514419981345, 4.622798727140234,
    4.175628659315184, 3.7289418130587215, 3.282422490024384, 2.835893227656469,
    2.389189037262742, 1.942063293917675, 1.4940778044832994, 1.0444429225098573,
    .591767318733179, .13361723866984754, -.33445790363972433, -.8215901065186295,
    -1.3498800848150931, -1.9842528368921217, -2.9724007636789405, -4.9060434132923945])
_POLES = np.tanh(_LOG_Q/2)


def _sections(branch):
    return np.array([[p, -1, 0, 1, -p, 0] for p in _POLES[branch::2]])


class HilbertPair:
    """Zero initial state; float64 frames x fixed channels; no FFT or latency trim."""
    def __init__(self, channels=1):
        self.sections = [_sections(1), _sections(0)]
        self.states = [np.zeros((12, 2, channels)) for _ in range(2)]

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        if not len(x):
            return x.copy(), x.copy()
        result = []
        for j in range(2):
            out, self.states[j] = signal.sosfilt(self.sections[j], x, axis=0, zi=self.states[j])
            result.append(out)
        return tuple(result)


def hilbert_pair(x):
    return HilbertPair(x.shape[1]).process(x)


def pair_response(frequencies, sr):
    return tuple(signal.sosfreqz(_sections(j), worN=frequencies, fs=sr)[1] for j in (1, 0))


def frequency_shift(x, sr, cycles, *, feedback=0., lo_hz=20., max_up_hz=0.):
    """Two SSB directions; feedback returns the upper output after 10 ms.

    Upward antialias lowpass is applied before the pair. Feedback has a fixed
    sample delay, with a shared stateful pair rather than independent chunks.
    """
    source = np.asarray(x, dtype=np.float64)
    sections = []
    if lo_hz > 0:
        sections.extend(signal.butter(2, min(lo_hz, sr*.45), 'highpass', fs=sr, output='sos'))
    if max_up_hz > 0:
        # A steep safety band leaves the shifted stopband below Nyquist.
        stop = sr/2-max_up_hz
        if stop <= 0:
            return np.zeros_like(x), np.zeros_like(x)
        cutoff = stop*.94
        order, edge = signal.ellipord(cutoff, stop, .01, 100, fs=sr)
        sections.extend(signal.ellip(order, .01, 100, edge, fs=sr, output='sos'))
    sos = np.asarray(sections)
    filter_state = np.zeros((len(sos), 2, x.shape[1]))
    pair = HilbertPair(x.shape[1])
    upper, lower = np.zeros_like(x), np.zeros_like(x)
    d = max(1, round(.01*sr))
    size = d if feedback else max(1, len(x))
    angle = 2*np.pi*np.remainder(cycles, 1)
    for start in range(0, len(x), size):
        end = min(start+size, len(x))
        v = source[start:end].copy()
        if feedback and start >= d:
            v += feedback*upper[start-d:end-d]
        if len(sos):
            v, filter_state = signal.sosfilt(sos, v, axis=0, zi=filter_state)
        real, imag = pair.process(v)
        c, s = np.cos(angle[start:end, None]), np.sin(angle[start:end, None])
        upper[start:end] = real*c-imag*s
        lower[start:end] = real*c+imag*s
    return upper, lower
