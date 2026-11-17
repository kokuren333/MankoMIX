"""Window-aware lobe coordinates for spectral_fx and spectral_dynamics.

No existing BB-06 operation is changed. ``lobes`` returns a peak index and
coherent sinusoidal amplitude for every bin, in (time, bin, channel) order.
The sqrt-Hann response is evaluated at the instantaneous sub-bin offset;
valleys separate components, so a window's sidelobes are not new sounds.
"""
import numpy as np
from scipy import signal


def frequencies(a):
    """Instantaneous bin frequencies from wrapped inter-frame phase residuals."""
    phase = np.angle(a.spectra)
    f = a.frequencies_hz
    if len(phase) < 2:
        return np.broadcast_to(f[None, :, None], phase.shape).copy()
    expected = 2*np.pi*f*a.hop_samples/a.sr
    residual = np.angle(np.exp(1j*(np.diff(phase, axis=0)-expected[None, :, None])))
    hz = f[None, :, None]+residual*a.sr/(2*np.pi*a.hop_samples)
    return np.concatenate([hz[:1], hz], axis=0)


def window_response(offset, n):
    """Magnitude of sum sin(pi*j/n) exp(-2j*pi*offset*j/n)."""
    q = np.asarray(offset)
    def geometric(v):
        return n*np.sinc(v)/np.sinc(v/n)*np.exp(-1j*np.pi*v*(n-1)/n)
    return abs((geometric(q-.5)-geometric(q+.5))/(2j))


def lobes(a, *, linked=False):
    """Resolve all local maxima and repeat each calibrated level to its valley.

    Linked detection uses the channel maximum before finding regions. There
    is no peak count cap or deletion of weak bins. Edge bins remain valid.
    """
    mag = abs(a.spectra)
    hz = frequencies(a)
    if linked:
        channel = np.argmax(mag, axis=2, keepdims=True)
        hz = np.take_along_axis(hz, channel, axis=2)
        mag = np.max(mag, axis=2, keepdims=True)
    ids = np.zeros(mag.shape, dtype=np.int64)
    amplitude = np.zeros_like(mag)
    n = len(a.window)
    for ch in range(mag.shape[2]):
        for t in range(len(mag)):
            m = mag[t, :, ch]
            peaks = signal.find_peaks(m)[0]
            if m[0] > m[1]:
                peaks = np.r_[0, peaks]
            if m[-1] > m[-2]:
                peaks = np.r_[peaks, len(m)-1]
            if not len(peaks):
                peaks = np.array([int(np.argmax(m))])
            edges = [0]+[int(l+np.argmin(m[l:r+1]))
                         for l, r in zip(peaks[:-1], peaks[1:])]+[len(m)]
            offset = peaks-hz[t, peaks, ch]*n/a.sr
            response = window_response(np.clip(offset, -.5, .5), n)
            values = 2*m[peaks]/np.maximum(response, 1e-30)
            values[(peaks == 0) | (peaks == len(m)-1)] *= .5
            widths = np.diff(edges)
            ids[t, :, ch] = np.repeat(peaks, widths)
            amplitude[t, :, ch] = np.repeat(values, widths)
    return ids, amplitude
