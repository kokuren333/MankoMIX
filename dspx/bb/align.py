"""BB-17: independent cross-correlation / GCC-PHAT delay and polarity.

estimate_delay(reference, target, sr, max_delay_ms=100, band_hz=None,
method='gcc_phat', oversample=16) returns JSON-safe measurements. A positive
delay means target arrives later. PHAT uses B*conj(A)/abs(B*conj(A)); a
parabola on an oversampled correlation refines the absolute peak. Polarity
is the sign of the ordinary correlation AFTER fractional alignment.
estimate_segments(..., segment_s=10, **controls) returns median/MAD and cells.
align_pair(reference, target, delay_samples, polarity=1) delays only the
earlier signal, preserving length, with the existing BB-09 sinc256 kernel.
solve_delays(count, pairs) reconciles (i,j,delay_samples[,weight]) by weighted
least squares with track zero anchored; returns nonnegative arrival times
and causal compensating delays (samples). No third-party source copied.
Formula source: Knapp & Carter, IEEE TASSP 24(4), 1976, 320-327.
"""
import numpy as np
from scipy import fft
from mankomix.dsp.errors import ParamError


def _mono(x):
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 2 and a.shape[1] == 1:
        a = a[:, 0]
    if a.ndim != 1 or not np.isfinite(a).all():
        raise ParamError('delay estimation requires finite mono arrays')
    return a


def align_pair(reference, target, delay_samples, polarity=1):
    from mankomix.dspx.bb.delayline import fractional_delay
    a, b = _mono(reference), _mono(target)
    if len(a) != len(b) or not np.isfinite(delay_samples) or polarity not in (-1, 1):
        raise ParamError('equal lengths, finite delay and +/-1 polarity required')
    a = fractional_delay(a[:, None], max(0., delay_samples), 'sinc256')[:, 0]
    b = fractional_delay(b[:, None], max(0., -delay_samples), 'sinc256')[:, 0]
    return a, b*polarity


def estimate_delay(reference, target, sr, *, max_delay_ms=100., band_hz=None,
                   method='gcc_phat', oversample=16):
    a, b = _mono(reference), _mono(target)
    if (sr <= 0 or not np.isfinite(max_delay_ms) or max_delay_ms < 0 or
            method not in ('gcc_phat', 'correlation') or
            isinstance(oversample, bool) or int(oversample) != oversample or not 1 <= oversample <= 32):
        raise ParamError('invalid delay estimation controls')
    lo, hi = (0., sr/2) if band_hz is None else band_hz
    if not np.isfinite([lo, hi]).all() or not 0 <= lo < hi <= sr/2:
        raise ParamError('delay estimation band must be inside Nyquist')
    n = min(len(a), len(b))
    empty = dict(delay_samples=0., delay_ms=0., polarity=1, correlation_before=0.,
                 correlation_after=0., peak_sharpness=0., confidence='low', reliable=False)
    if n < 8:
        return empty
    a, b = a[:n]-np.mean(a[:n]), b[:n]-np.mean(b[:n])
    size = fft.next_fast_len(2*n-1)
    aa, bb = fft.rfft(a, size, workers=1), fft.rfft(b, size, workers=1)
    f = fft.rfftfreq(size, 1/sr)
    band = (f >= lo) & (f <= hi) & (f > 0)
    cross = bb*np.conj(aa)
    mag = abs(cross)
    if not np.any(band) or not np.max(mag[band], initial=0):
        return empty
    good = band & (mag > np.max(mag[band])*1e-10)
    spectrum = np.where(good, cross/np.maximum(mag, 1e-300), 0) if method == 'gcc_phat' else np.where(band, cross, 0)
    os = int(oversample)
    cc = fft.irfft(spectrum, size*os, workers=1)
    radius = min(int(np.floor(max_delay_ms*sr*.001*os)), (n-2)*os)
    grid = np.arange(-radius, radius+1)
    values = abs(cc[grid % len(cc)])
    k = int(np.argmax(values))
    fraction = 0.
    if 0 < k < len(values)-1:
        left, center, right = values[k-1:k+2]
        den = left-2*center+right
        if den < 0:
            fraction = float(np.clip(.5*(left-right)/den, -.5, .5))
    delay = float(np.clip((grid[k]+fraction)/os, -radius/os, radius/os))
    af = fft.irfft(np.where(band, aa, 0), size, workers=1)[:n]
    bf = fft.irfft(np.where(band, bb, 0), size, workers=1)[:n]
    def corr(x, y):
        den = np.sqrt(np.sum(x*x)*np.sum(y*y))
        return float(np.clip(np.sum(x*y)/den, -1, 1)) if den else 0.
    before = corr(af, bf)
    aligned_a, aligned_b = align_pair(af, bf, delay)
    margin = int(np.ceil(abs(delay)))+128
    cut = slice(margin, -128) if n > margin+256 else slice(None)
    after = corr(aligned_a[cut], aligned_b[cut])
    sharpness = float((values[k]-np.median(values))/max(values[k], 1e-300))
    reliable = abs(after) >= .6
    return dict(delay_samples=delay, delay_ms=delay*1000/sr, polarity=-1 if after < 0 else 1,
                correlation_before=before, correlation_after=after,
                peak_sharpness=sharpness, confidence='high' if reliable else 'low', reliable=reliable)


def estimate_segments(reference, target, sr, *, segment_s=10., **controls):
    if not np.isfinite(segment_s) or segment_s <= 0:
        raise ParamError('segment_s must be positive')
    a, b = _mono(reference), _mono(target)
    size = max(8, round(segment_s*sr))
    cells = []
    for start in range(0, min(len(a), len(b)), size):
        cell = estimate_delay(a[start:start+size], b[start:start+size], sr, **controls)
        cells.append(dict(start_s=start/sr, **cell))
    usable = [c for c in cells if c['reliable']]
    delays = np.array([c['delay_samples'] for c in usable])
    median = float(np.median(delays)) if len(delays) else 0.
    return dict(delay_samples=median, delay_ms=median*1000/sr,
                mad_samples=float(np.median(abs(delays-median))) if len(delays) else 0.,
                polarity=-1 if sum(c['polarity'] for c in usable) < 0 else 1,
                confidence='high' if usable else 'low', segments=cells)


def solve_delays(count, pairs):
    if isinstance(count, bool) or int(count) != count or count < 2:
        raise ParamError('at least two tracks required')
    rows, rhs = [], []
    for pair in pairs:
        i, j, delay, *weights = pair
        weight = weights[0] if weights else 1.
        if (not isinstance(i, (int, np.integer)) or not isinstance(j, (int, np.integer)) or
                not 0 <= i < count or not 0 <= j < count or i == j or
                not np.isfinite([delay, weight]).all() or weight <= 0):
            raise ParamError('invalid delay graph edge')
        row = np.zeros(count)
        row[j], row[i] = np.sqrt(weight), -np.sqrt(weight)
        rows.append(row[1:])
        rhs.append(delay*np.sqrt(weight))
    matrix = np.asarray(rows).reshape(-1, count-1)
    if not len(rows) or np.linalg.matrix_rank(matrix) < count-1:
        raise ParamError('delay graph must be connected')
    anchored = np.linalg.lstsq(matrix, rhs, rcond=None)[0]
    residual = matrix @ anchored - np.asarray(rhs)
    fitted = np.r_[0., anchored]
    fitted -= np.min(fitted)
    return dict(arrival_samples=fitted.tolist(), delay_samples=(np.max(fitted)-fitted).tolist(),
                residual_rms_samples=float(np.sqrt(np.mean(residual**2))))
