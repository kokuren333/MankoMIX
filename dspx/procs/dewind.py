"""T10-15 low-coherence steep-spectrum wind detector; no clothing model."""
import numpy as np
from scipy import ndimage
from mankomix.dspx.params import _f, _b
from mankomix.dspx.bb.restoration import definition, rp_params, validate_region


def wind_gains(a,p):
    """Return real gains, detected frame mask, slope and coherence diagnostics."""
    from mankomix.dspx.bb.noise import suppression_gains
    z, f = a.spectra, a.frequencies_hz
    power = abs(z)**2
    if not len(z):
        return np.ones_like(power),np.zeros(0,dtype=bool),np.empty(0),np.empty(0)
    low = f <= p['max_hz']
    higher = (f >= p['max_hz']) & (f <= p['max_hz']*2)
    # PSD/octave slope: use bin means, so pink noise reads -3 dB/oct.
    split = max(60,p['max_hz']/2)
    first = (f >= max(20,split/2)) & (f < split)
    second = (f >= split) & (f <= min(p['max_hz'],split*2))
    def energy(mask):
        return np.mean(power[:,mask],axis=(1,2)) if np.any(mask) else np.zeros(len(z))
    e1 = ndimage.uniform_filter1d(energy(first),size=19,mode='nearest')
    e2 = ndimage.uniform_filter1d(energy(second),size=19,mode='nearest')
    slope = 10*np.log10(np.maximum(e2,1e-30)/np.maximum(e1,1e-30))
    if z.shape[2] == 2 and p['use_coherence']:
        # Complex coherence must be averaged before taking its magnitude.
        cross = ndimage.uniform_filter1d(z[:,:,0]*z[:,:,1].conj(),size=9,axis=0,mode='nearest')
        auto = ndimage.uniform_filter1d(power,size=9,axis=0,mode='nearest')
        coherence = np.mean(abs(cross[:,low])**2/np.maximum(auto[:,low,0]*auto[:,low,1],1e-30),axis=1)
        incoherent = coherence < .35
    else:
        coherence = np.ones(len(z))
        e = energy(low)
        smooth = ndimage.uniform_filter1d(e,size=19,mode='nearest')
        modulation = abs(e-smooth)/np.maximum(smooth,1e-30)
        incoherent = modulation > .35
    ratio = 10*np.log10(np.maximum(energy(low),1e-30)/np.maximum(energy(higher),1e-30))
    active = (slope <= -10) & (ratio >= p['threshold_db']) & incoherent
    # Track the upper extent of each steep low-band PSD by its 99.5% energy
    # quantile. A per-frame highpass complement leaves higher bands open.
    low_power = np.mean(power[:,low],axis=2)
    cumulative = np.cumsum(low_power,axis=1)
    total = cumulative[:,-1]
    index = np.argmax(cumulative >= .995*total[:,None],axis=1)
    upper = np.clip(f[low][index],min(80,p['max_hz']),p['max_hz'])
    # Release is applied to the detected low-band gain; above max_hz is untouched.
    noise = np.where(active[:,None,None],power,0.)
    raw = suppression_gains(power,noise,a.sr,a.hop_samples,f,method='wiener',
        reduction_db=p['max_reduce_db'],time_smooth_ms=0,freq_smooth_oct=0,transient_protect=0)
    target = np.ones_like(power)
    # Wind estimate dominates the low-band PSD in detected frames.
    target[:,low] = np.where(active[:,None,None],10**(-p['max_reduce_db']/20),raw[:,low])
    target[:,~low] = 1
    target[f[None,:]>upper[:,None]] = 1
    gain = np.ones_like(target)
    alpha = np.exp(-a.hop_samples/(a.sr*p['release_ms']/1000))
    state = np.ones(target.shape[1:])
    for i in range(len(target)):
        state = np.where(target[i] < state,target[i],alpha*state+(1-alpha)*target[i])
        gain[i] = state
    return gain,active,slope,coherence


def dewind(x,sr,p,*,seed=0):
    from mankomix.dspx.bb.stft import analyze, synthesize, window_samples
    from mankomix.dspx.bb.restoration import region_mix, finish
    validate_region(p)
    confidence = 'normal' if x.shape[1] == 2 and p['use_coherence'] else 'low'
    if not len(x) or not p['amount'] or not np.any(x):
        return finish(x,x.copy(),sr,p,confidence=confidence,wind_frame_count=0)
    a = analyze(x,sr,window=window_samples(4096,sr))
    gains,active,slope,coherence = wind_gains(a,p)
    if np.any(active):
        from scipy import fft
        correction = synthesize(a,a.spectra*(gains-1))
        spectrum = fft.rfft(correction,axis=0,workers=1)
        spectrum[fft.rfftfreq(len(x),1/sr)>p['max_hz']] = 0
        wet = x+fft.irfft(spectrum,n=len(x),axis=0,workers=1)
        y = region_mix(x,wet,sr,p)
    else:
        y = x.copy()
    return finish(x,y,sr,p,confidence=confidence,wind_frame_count=int(np.sum(active)),
                  minimum_slope_db_oct=float(np.min(slope)),mean_coherence=float(np.mean(coherence)))


SPECS = [definition('dewind',rp_params(1)+[
    _f('max_hz','Hz',80,1000,300,'Maximum wind frequency.'),_f('threshold_db','dB',0,24,6,'Low/mid excess.'),
    _f('max_reduce_db','dB',3,40,24,'Maximum wind reduction.'),_f('release_ms','ms',20,1000,150,'Release time.'),
    _b('use_coherence',True,'Use stereo low-band coherence.')])]
SPECS[0]['description'] = 'Steep-spectrum incoherent low-band wind suppression.'
SPECS[0]['implemented'] = True
IMPLS = {'dewind':dewind}
CROSS_VALIDATE = {'dewind':validate_region}
