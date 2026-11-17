"""Explicit spectral inpainting on BB-06's centered grid.

repair_spectra(analysis, regions, mode=..., context_ms=..., attenuate_db=...,
feather_ms=..., feather_oct=...) returns spectra; regions are (t0,t1,lo,hi).
Unselected bins are copied exactly. Context frames must fit entirely outside
every selected time region. Instantaneous frequency is phase-unwrapped around
the bin center; both clean boundaries contribute a deterministic phase bridge.
repair_audio uses additive WOLA differences and preserves samples outside the
time feather support. spectral_gap is the same full-band replace_time kernel.
"""
import numpy as np
from mankomix.dsp.errors import ParamError


def _phase_step(z, a, b, omega):
    if a == b:
        return omega
    expected = omega*(b-a)
    error = np.angle(z[b]*np.conj(z[a])*np.exp(-1j*expected))
    return omega+error/(b-a)


def repair_spectra(analysis, regions, *, mode='replace_time', context_ms=200,
                   attenuate_db=12, feather_ms=10, feather_oct=.05, boundary_ms=0):
    """Modify only the explicit rectangles; ties in pattern search favor earlier frames."""
    a = analysis
    z = a.spectra
    out = z.copy()
    if mode not in ('attenuate', 'replace_time', 'replace_freq', 'pattern'):
        raise ParamError('unknown spectral repair mode')
    if not len(z):
        return out
    times = a.samples/a.sr
    half = len(a.window)/(2*a.sr)
    clean = np.ones(len(z), dtype=bool)
    for t0, t1, _, _ in regions:
        clean &= (times+half <= t0) | (times-half >= t1)
    omega = 2*np.pi*a.frequencies_hz[:, None]*a.hop_samples/a.sr
    for t0, t1, lo, hi in regions:
        tw = np.maximum(0, np.minimum((times-t0)/max(feather_ms/1000, 1e-30)+1,
                                     (t1-times)/max(feather_ms/1000, 1e-30)+1))
        tw = np.minimum(tw, 1)
        tw[(times < t0-feather_ms/1000) | (times > t1+feather_ms/1000)] = 0
        freq = a.frequencies_hz
        fw = ((freq >= lo) & (freq <= hi)).astype(float)
        if feather_oct:
            lower = lo/2**feather_oct
            upper = hi*2**feather_oct
            if lo:
                k = (freq > lower) & (freq < lo)
                fw[k] = .5-.5*np.cos(np.pi*np.log2(freq[k]/lower)/feather_oct)
            k = (freq > hi) & (freq < upper)
            fw[k] = .5+.5*np.cos(np.pi*np.log2(freq[k]/hi)/feather_oct)
        left = np.flatnonzero(clean & (times+half <= t0) & (times >= t0-context_ms/1000-half))
        right = np.flatnonzero(clean & (times-half >= t1) & (times <= t1+context_ms/1000+half))
        context = np.r_[left, right]
        if not len(context):
            continue
        li = int(left[-1]) if len(left) else int(right[0])
        ri = int(right[0]) if len(right) else li
        ls = _phase_step(z, int(left[-2]) if len(left) > 1 else li, li, omega)
        rs = _phase_step(z, ri, int(right[1]) if len(right) > 1 else ri, omega)
        median = np.median(abs(z[context]), axis=0)
        selected = np.flatnonzero(fw)
        targets = np.flatnonzero(tw)
        pattern_indices = None
        if mode == 'pattern' and len(targets):
            from mankomix.dspx.bb.restoration import runs
            available = np.zeros(len(z),dtype=bool)
            available[context] = True
            stretches = runs(available)
            span = min(len(targets),max(b-a for a,b in stretches))
            candidates = [i for a,b in stretches for i in range(a,b-span+1)]
            scores = []
            for i in candidates:
                first = np.log(np.maximum(abs(z[i,selected]),1e-30))
                last = np.log(np.maximum(abs(z[i+span-1,selected]),1e-30))
                scores.append(float(np.mean((first-np.log(np.maximum(abs(z[li,selected]),1e-30)))**2)
                                    +np.mean((last-np.log(np.maximum(abs(z[ri,selected]),1e-30)))**2)))
            best = candidates[int(np.argmin(scores))]
            pattern_indices = best+np.arange(len(targets))%span
        for position, i in enumerate(targets):
            u = np.clip((i-li)/max(1, ri-li), 0, 1)
            if boundary_ms:
                # Extend the one-sided phase predictions through the chosen
                # boundary fades before interpolating the central bridge.
                fade_frames = boundary_ms*a.sr/(1000*a.hop_samples)
                u = np.clip((i-li-fade_frames)/max(1,ri-li-2*fade_frames),0,1)
            if mode == 'attenuate':
                magnitude = np.maximum(abs(z[i])*10**(-attenuate_db/20), np.minimum(abs(z[i]), median))
                replacement = magnitude*np.exp(1j*np.angle(z[i]))
            elif mode == 'replace_time':
                l = abs(z[li])*np.exp(1j*(np.angle(z[li])+ls*(i-li)))
                r = abs(z[ri])*np.exp(1j*(np.angle(z[ri])+rs*(i-ri)))
                replacement = (1-u)*l+u*r
            elif mode == 'replace_freq':
                replacement = z[i].copy()
                outside = np.flatnonzero(fw == 0)
                if not len(outside):
                    continue
                for ch in range(z.shape[2]):
                    mag = np.interp(freq[selected], freq[outside], abs(z[i, outside, ch]))
                    phase = np.interp(freq[selected], freq[outside], np.unwrap(np.angle(z[i, outside, ch])))
                    replacement[selected, ch] = mag*np.exp(1j*phase)
            else:
                replacement = z[pattern_indices[position]]
            w = tw[i]*fw[:, None]
            ids = fw != 0
            out[i, ids] = out[i, ids]+w[ids]*(replacement[ids]-out[i, ids])
    return out


def repair_audio(x, sr, regions, *, window=2048, **kwargs):
    """Add the spectral correction; preserve bytes beyond selected time supports."""
    from mankomix.dspx.bb.stft import analyze, synthesize, window_samples
    a = analyze(x, sr, window=window_samples(window, sr))
    z = repair_spectra(a, regions, **kwargs)
    correction = synthesize(a, z-a.spectra)
    y = x.copy()
    feather = kwargs.get('feather_ms', 10)/1000
    for t0, t1, _, _ in regions:
        start, end = max(0, round((t0-feather)*sr)), min(len(x), round((t1+feather)*sr))
        y[start:end] = x[start:end]+correction[start:end]
    return y


def spectral_gap(x, sr, start, end, *, context_ms=300, fade_ms=2):
    """Full-band replace_time; copy only the missing sample interval."""
    from mankomix.dspx.bb.stft import window_samples
    from scipy import fft
    half = window_samples(2048,sr)/(2*sr)
    # Every analysis window touching a missing sample must be replaced, even
    # if its center lies outside the hole. Only unknown samples are returned.
    y = repair_audio(x, sr, [(start/sr-half, end/sr+half, 0, sr/2)],
                     context_ms=context_ms, feather_ms=0, feather_oct=0,boundary_ms=fade_ms)
    estimate = y[start:end].copy()
    n = round(context_ms*sr/1000)
    for ch in range(x.shape[1]):
        context = np.r_[x[max(0,start-n):start,ch],x[end:min(len(x),end+n),ch]]
        if len(context) < 8:
            continue
        power = abs(fft.rfft(context,workers=1))**2
        flatness = np.exp(np.mean(np.log(np.maximum(power,1e-30))))/max(np.mean(power),1e-30)
        if flatness > .3:
            # Noise phase is not predictable: preserve its observed RMS,
            # rather than claim sample recovery from the conditional mean.
            rms = np.sqrt(np.mean(estimate[:,ch]**2))
            if rms:
                estimate[:,ch] *= np.sqrt(np.mean(context**2))/rms
    return estimate
