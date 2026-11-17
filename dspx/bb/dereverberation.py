"""Offline late-power estimation and variance-weighted delayed prediction.

Independent equations from spec/10 T10-09. The delayed exponential PSD
model is also Eq. (9) of Lebart, Boucher & Denbigh, Acta Acustica 87
(2001), 359-366. No third-party implementation source is used.
"""
import numpy as np
from scipy import signal, optimize, fft
from mankomix.dsp.errors import ParamError


def estimate_rt60(x, sr):
    """Return (seconds or None, selected decay records), using Gaussian ML.

    Nonoverlapping 20 ms powers; candidates start at local maxima, stop at
    a >3 dB rise or 40 dB drop, and require >=120 ms / >=12 dB decay.
    Fit E(t)=A exp(-6 ln(10)t/T) by profiling A out of the likelihood.
    The median of valid candidates is returned; absence never invents an RT.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2 or sr <= 0 or not np.isfinite(x).all():
        raise ParamError('finite (samples, channels) audio and positive sr required')
    step = max(1, round(.02*sr))
    count = len(x)//step
    if count < 8 or not np.any(x):
        return None, []
    power = np.mean(x[:count*step].reshape(count, step, x.shape[1])**2, axis=(1, 2))
    level = 10*np.log10(np.maximum(power, 1e-30))
    # Three-block averaging limits periodogram fluctuations in diffuse tails.
    sm = np.convolve(power, np.ones(3)/3, mode='valid')
    db = 10*np.log10(np.maximum(sm, 1e-30))
    starts = signal.find_peaks(db, distance=3)[0]
    starts = np.unique(np.r_[0, starts])
    records = []
    occupied = -1
    for start in starts:
        if start < occupied or db[start] < level.max()-40:
            continue
        end = int(start)+1
        while end < len(db) and end-start < round(3*sr/step):
            if db[end] > np.min(db[start:end])+3 or db[end] < db[start]-40:
                break
            end += 1
        if end-start < max(6, round(.12*sr/step)) or db[start]-db[end-1] < 12:
            continue
        t = np.arange(end-start)*step/sr
        obs = sm[start:end]/max(float(sm[start]), 1e-30)
        def objective(rt):
            rate = 6*np.log(10)/rt
            terms = np.log(np.maximum(obs, 1e-30))+rate*t
            top = float(np.max(terms))
            log_a = top+np.log(np.mean(np.exp(terms-top)))
            return len(t)*log_a-rate*float(np.sum(t))
        fit = optimize.minimize_scalar(objective, bounds=(.1, 10), method='bounded',
                                       options={'xatol': 1e-7, 'maxiter': 80})
        rt = float(fit.x)
        trend = np.polyfit(t, db[start:end], 1)
        residual = db[start:end]-np.polyval(trend, t)
        r2 = 1-float(np.sum(residual**2))/max(float(np.sum((db[start:end]-np.mean(db[start:end]))**2)), 1e-30)
        if not .105 < rt < 9.95 or r2 < .9:
            continue
        # A nearly pure decaying tone is not evidence for a diffuse room tail.
        lo, hi = int(start*step), min(len(x), int(end*step))
        magnitude = abs(fft.rfft(x[lo:hi], axis=0, workers=1))
        flatness = float(np.exp(np.mean(np.log(magnitude+1e-30)))/max(float(np.mean(magnitude)), 1e-30))
        if flatness < .01:
            continue
        records.append(dict(start_s=float(start*step/sr), duration_s=float(len(t)*step/sr),
                            rt60_s=rt, r_squared=r2, spectral_flatness=flatness))
        occupied = end
    return (float(np.median([r['rt60_s'] for r in records])) if records else None), records


def late_power(analysis, rt60_s, early_ms=50, band_tilt=0):
    """Return delayed, 20 ms averaged PSD times exp(-6 ln(10) early/T(f)).

    T(f)=clip(T60 * 10**(-tilt*log2(max(f,125)/1000)/20), .05, 20).
    Positive tilt shortens high-frequency RT. Delay is ceil(early/hop).
    """
    if not np.isfinite(rt60_s) or rt60_s <= 0 or early_ms <= 0:
        raise ParamError('positive RT and early interval required')
    a = analysis
    power = abs(a.spectra)**2
    alpha = np.exp(-a.hop_samples/(a.sr*.02))
    smoothed = signal.lfilter([1-alpha], [1, -alpha], power, axis=0)
    delay = max(1, int(np.ceil(early_ms*.001*a.sr/a.hop_samples)))
    rt = np.clip(rt60_s*10**(-band_tilt*np.log2(np.maximum(a.frequencies_hz, 125)/1000)/20), .05, 20)
    decay = np.exp(-6*np.log(10)*delay*a.hop_samples/(a.sr*rt))
    out = np.zeros_like(power)
    if delay < len(out):
        out[delay:] = smoothed[:-delay]*decay[None, :, None]
    return out


def early_envelope(x, sr, early_ms):
    """Removal weight, zero through early_ms after a 6 dB power rise.

    A 2 ms block clock compares with the preceding 40 ms mean. Ignore blocks
    60 dB below the clip maximum. The following 10 ms cosine opens removal;
    the same envelope applies to all channels and both dereverb methods.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] < 1 or not np.isfinite(x).all() or sr <= 0 or early_ms <= 0:
        raise ParamError('finite audio, positive sr and early interval required')
    if not len(x):
        return np.ones(0)
    step = max(1, round(.002*sr))
    padded = np.pad(np.mean(x*x, axis=1), (0, (-len(x)) % step))
    power = padded.reshape(-1, step).mean(axis=1)
    history = max(1, round(.04*sr/step))
    previous = np.convolve(np.r_[np.zeros(history), power], np.ones(history)/history,
                           mode='valid')[:len(power)]
    rising = (power > 4*np.maximum(previous, 1e-30)) & (power > power.max(initial=0)*1e-6)
    attacks = np.flatnonzero(rising & ~np.r_[False, rising[:-1]])*step
    envelope = np.ones(len(x))
    # One clock block covers an onset anywhere inside its detection block.
    length, fade = round(early_ms*.001*sr)+step, max(1, round(.01*sr))
    for start in attacks:
        end = min(len(x), start+length)
        envelope[start:end] = 0
        stop = min(len(x), end+fade)
        envelope[end:stop] = np.minimum(envelope[end:stop], .5-.5*np.cos(np.pi*np.arange(stop-end)/fade))
    return envelope


def wpe(spectra, taps=12, delay=3, iterations=3):
    """Return (residual, diagnostics) for fixed-iteration multichannel WPE.

    Layout (time, bin, channel). Past vectors use all channels and lags
    delay..delay+taps-1, with zero initial history. For each bin solve
    (Z^H W Z + load I) G = Z^H W X; Y=X-ZG. The variance is the channel
    mean |Y|^2, floored at 1e-6 of the original bin mean (absolute 1e-30).
    Load=1e-6*trace(R)/dimension+1e-12. Exactly iterations updates.
    """
    x = np.asarray(spectra, dtype=np.complex128)
    if (x.ndim != 3 or x.shape[-1] < 1 or not np.isfinite(x).all()
            or any(isinstance(v, bool) or not isinstance(v, (int, np.integer)) for v in (taps, delay, iterations))
            or not 4 <= taps <= 40
            or not 1 <= delay <= 6 or not 1 <= iterations <= 5):
        raise ParamError('invalid WPE data or fixed iteration settings')
    y = x.copy()
    frames, bins, channels = x.shape
    if not frames or not np.any(x):
        return y, dict(iterations=iterations, loaded_solves=0)
    dimension = taps*channels
    eye = np.eye(dimension)
    for k in range(bins):
        target = x[:, k]
        past = np.zeros((frames, dimension), dtype=np.complex128)
        for tap in range(taps):
            lag = delay+tap
            if lag < frames:
                past[lag:, tap*channels:(tap+1)*channels] = target[:-lag]
        floor = max(1e-30, 1e-6*float(np.mean(abs(target)**2)))
        for _ in range(iterations):
            weight = 1/np.maximum(np.mean(abs(y[:, k])**2, axis=1), floor)
            # Explicit reductions and Cholesky avoid a threaded BLAS dispatch.
            weighted = past.conj()*weight[:, None]
            normal = np.einsum('td,te->de', weighted, past, optimize=False)
            cross = np.einsum('td,tc->dc', weighted, target, optimize=False)
            load = 1e-6*float(np.trace(normal).real)/dimension+1e-12
            # Positive load handles silent, rank-deficient and identical channels.
            coef = _loaded_solve(normal+load*eye, cross)
            y[:, k] = target-np.einsum('td,dc->tc', past, coef, optimize=False)
    return y, dict(iterations=iterations, loaded_solves=bins*iterations)


def _loaded_solve(matrix, rhs):
    """Serial complex Cholesky for the already-loaded Hermitian normal system."""
    n = len(matrix)
    lower = np.zeros_like(matrix)
    for j in range(n):
        diag = matrix[j, j].real-float(np.sum(abs(lower[j, :j])**2))
        lower[j, j] = np.sqrt(max(diag, np.finfo(float).tiny))
        correction = np.einsum('ij,j->i', lower[j+1:, :j], lower[j, :j].conj(), optimize=False)
        lower[j+1:, j] = (matrix[j+1:, j]-correction)/lower[j, j]
    forward, answer = np.zeros_like(rhs), np.zeros_like(rhs)
    for j in range(n):
        forward[j] = (rhs[j]-np.einsum('i,ic->c', lower[j, :j], forward[:j], optimize=False))/lower[j, j]
    for j in range(n-1, -1, -1):
        answer[j] = (forward[j]-np.einsum('i,ic->c', lower[j+1:, j].conj(), answer[j+1:], optimize=False))/lower[j, j]
    return answer
