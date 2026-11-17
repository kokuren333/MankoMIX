"""Deterministic bandwidth extension; estimated high frequencies are not recovery.

detect_cliff(analysis) -> (Hz or None, depth_dB). extend(x,sr,p,seed=0)
returns (additive_high_band, metadata), reusing BB-06 and BB-13. Bin power
is extrapolated from the observed octave; copy_up translates repeated bands,
harmonic uses oversampled squaring. A final one-worker Fourier projection
restricts the addition to [cutoff,top]. No third-party source is copied.
"""
import numpy as np
from scipy import fft, ndimage


def detect_cliff(analysis):
    """Find a >=20 dB third-octave drop with broadband support below it."""
    from mankomix.dspx.bb.stft import smooth_frequency
    f = analysis.frequencies_hz
    if not len(analysis.spectra) or f[-1] < 4000:
        return None, 0.
    power = np.mean(abs(analysis.spectra)**2, axis=(0,2))
    smoothed = smooth_frequency(power[None,:,None], f, 1/24)[0,:,0]
    candidates = []
    for k in np.flatnonzero((f >= 2000) & (f <= min(20000, f[-1]/1.15))):
        lo = (f >= f[k]/2**(1/3)) & (f < f[k])
        hi = (f > f[k]) & (f <= f[k]*2**(1/3))
        before, after = np.mean(power[lo]), np.mean(power[hi])
        # A sparse harmonic spectrum is not evidence of a bandwidth cliff.
        occupied = np.mean(power[lo] > before*.02)
        depth = 10*np.log10(max(before,1e-30)/max(after,1e-30))
        if before > np.max(power)*1e-7 and depth >= 20 and occupied >= .8:
            width = max(1, round(k/80))
            slope = np.log(max(smoothed[max(0,k-width)],1e-30))-np.log(max(smoothed[min(len(f)-1,k+width)],1e-30))
            candidates.append((slope, -k, depth))
    if not candidates:
        return None, 0.
    _, negative, depth = max(candidates)
    return float(f[-negative]), float(depth)


def extend(x, sr, p, *, seed=0):
    """Synthesize only the absent high band and return the additive signal."""
    from mankomix.dspx.bb.stft import analyze, synthesize, window_samples, smooth_frequency
    from mankomix.dspx.bb.nonlinear import oversampled
    a = analyze(x,sr,window=window_samples(2048,sr))
    automatic, depth = detect_cliff(a)
    cutoff = p['cutoff_hz'] or automatic
    info = dict(cutoff_hz=cutoff, cliff_depth_db=depth, detected=cutoff is not None,
                caveat='Generated high frequencies are an estimate, not restoration of original content.')
    added = np.zeros_like(x)
    if not cutoff or not len(x) or cutoff >= min(p['top_hz'],sr/2):
        return added, info
    f, z = a.frequencies_hz, a.spectra
    power = np.mean(abs(z)**2,axis=0)
    env = smooth_frequency(power[None],f,1/3)[0]
    # Keep the envelope fitting octave below the smoothing kernel's contact
    # with the cliff; including that shoulder biases the extrapolated slope.
    source = (f >= cutoff/2) & (f < cutoff/2**(1/6))
    if np.count_nonzero(source) < 2:
        return added, info
    reference = np.maximum(env[source],1e-30)
    slope = np.array([np.polyfit(np.log2(f[source]/cutoff),10*np.log10(reference[:,ch]),1)[0]
                      for ch in range(x.shape[1])])
    slope = np.clip(slope,-24,0) if not p['slope_db_oct'] else np.full(x.shape[1],p['slope_db_oct'])
    anchor = np.array([np.mean(10*np.log10(reference[:,ch])-slope[ch]*np.log2(f[source]/cutoff))
                       for ch in range(x.shape[1])])
    target = (f >= cutoff) & (f <= min(p['top_hz'],sr/2))
    dest = np.flatnonzero(target)
    width = min(p['top_hz']-cutoff,cutoff/2)
    origin = cutoff-width+np.mod(f[dest]-cutoff,width)
    src = np.clip(np.searchsorted(f,origin),1,len(f)-1)
    mapped = z[:,src].copy()
    # Translation phase advance preserves each source component's offset from its bin.
    shift = f[dest]-f[src]
    mapped *= np.exp(2j*np.pi*a.samples[:,None,None]*shift[None,:,None]/sr)
    if p['source'] == 'harmonic':
        band = np.zeros_like(z)
        band[:,source] = z[:,source]
        low = synthesize(a,band)
        nonlinear = oversampled(low,4,lambda v:v*v)
        mapped = analyze(nonlinear,sr,window=len(a.window)).spectra[:,dest]
    desired = 10**((anchor[None,:]+slope[None,:]*np.log2(f[dest,None]/cutoff)+p['level_db'])/10)
    actual = np.mean(abs(mapped)**2,axis=0)
    mapped *= np.sqrt(desired/np.maximum(actual,1e-30))[None]
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([int(seed),int(p['seed'])])))
    noise = (rng.standard_normal(mapped.shape)+1j*rng.standard_normal(mapped.shape))/np.sqrt(2)
    noise *= np.sqrt(desired)[None]
    source_envelope = np.sqrt(np.mean(abs(z[:,source])**2,axis=1))
    source_envelope /= np.maximum(np.sqrt(np.mean(source_envelope**2,axis=0)),1e-30)
    follow = (1-p['transient_follow'])+p['transient_follow']*source_envelope
    # Noise and mapped components share the observed temporal envelope.
    noise *= follow[:,None,:]
    generated = np.sqrt(1-p['noise_mix'])*mapped+np.sqrt(p['noise_mix'])*noise
    high = np.zeros_like(z)
    high[:,dest] = generated
    added = synthesize(a,high)
    spectrum = fft.rfft(added,axis=0,workers=1)
    freq = fft.rfftfreq(len(x),1/sr)
    spectrum[(freq < cutoff) | (freq > min(p['top_hz'],sr/2))] = 0
    # Calibrate the *power envelope* after WOLA, whose phase covariance
    # changes when bands are translated or independently randomized.
    desired_full = np.zeros_like(spectrum.real)
    keep = (freq >= cutoff) & (freq <= min(p['top_hz'],sr/2))
    desired_full[keep] = 10**((anchor[None,:]+slope[None,:]*np.log2(freq[keep,None]/cutoff)+p['level_db'])/10)
    measured = abs(spectrum)**2/len(x)*np.sum(a.window**2)
    desired_sm = smooth_frequency(desired_full[None],freq,1/3)[0]
    measured_sm = smooth_frequency(measured[None],freq,1/3)[0]
    spectrum *= np.sqrt(desired_sm/np.maximum(measured_sm,1e-30))
    added = fft.irfft(spectrum,n=len(x),axis=0,workers=1)
    info['slope_db_oct'] = slope.tolist()
    return added, info
