"""Octave divider or BB-12 pitch-tracked sub synthesis, whole-context only.

The positive Schmitt transition toggles the divider once per source cycle.
Initial polarity is +1; hysteresis is 1e-6 full scale. Polyphonic divider
tracking is unreliable by construction. Tracked mode integrates sample-grid
frequency from absolute sample zero, keeping phase continuous across voicing.
Carrier filtering precedes the final envelope; silent tails hold the period.
"""
import numpy as np
from mankomix.dspx.params import _f, _e, _b


def validate(p):
    if p['lo_hz'] >= p['hi_hz']:
        from mankomix.dsp.errors import ParamError
        raise ParamError('lo_hz must be below hi_hz')


def divider_wave(x, hysteresis=1e-6):
    """Zero-state Schmitt-trigger octave divider; return +/-1 per channel."""
    result = np.ones_like(x)
    for c in range(x.shape[1]):
        armed, polarity = False, 1.
        for i, v in enumerate(x[:, c]):
            if v < -hysteresis:
                armed = True
            elif v > hysteresis and armed:
                polarity = -polarity
                armed = False
            result[i, c] = polarity
    return result


def tracked_wave(x, sr, lo, hi, threshold_db):
    """BB-12 YIN on a 2 kHz analysis grid, sample-held f0 and absolute integral."""
    from scipy import signal
    from mankomix.dspx.bb.pitch import detect_pitch, sample_pitch
    from math import gcd
    analysis_sr = min(sr, 2000)
    divisor = gcd(sr, analysis_sr)
    a = signal.resample_poly(x, analysis_sr//divisor, sr//divisor, axis=0)
    out = np.zeros_like(x)
    voiced_count = 0
    for c in range(x.shape[1]):
        track = detect_pitch(a[:, c:c+1], analysis_sr, method='yin', fmin=lo,
                             fmax=hi, silence_db=threshold_db, hop_ms=10)
        f0, voiced, _ = sample_pitch(track, np.arange(len(x))*analysis_sr/sr)
        frequency = np.nan_to_num(f0)/2
        known = np.flatnonzero(voiced)
        if len(known):
            indices = np.maximum.accumulate(np.where(voiced, np.arange(len(x)), known[0]))
            frequency = frequency[indices]
        else:
            frequency[:] = 0
        cycles = np.r_[0., np.cumsum(frequency[:-1])/sr]
        out[:, c] = np.sin(2*np.pi*np.remainder(cycles, 1))
        voiced_count += int(np.count_nonzero(voiced))
    return out, voiced_count


def source_cycles(band, sr, lo, hi, source=None):
    """Interpolate Schmitt cycle boundaries; continue phase across silence.

    Each transition of the existing flip-flop marks one input cycle. Linear
    crossing interpolation removes sample quantization; end periods are held.
    """
    toggles = divider_wave(band)
    cycles = np.zeros_like(band)
    valid = np.zeros_like(band, dtype=bool)
    t = np.arange(len(band))
    for c in range(band.shape[1]):
        ix = np.flatnonzero(np.diff(toggles[:, c]) != 0)+1
        if source is not None:
            from scipy.ndimage import maximum_filter1d
            support = maximum_filter1d(np.abs(source[:, c]), max(3, sr//1000), mode='constant') > 1e-12
            ix = ix[support[ix]]
        if len(ix) < 2:
            continue
        # Locate the actual zero between the samples bracketing a transition.
        z = ix-1-band[ix-1, c]/np.maximum(band[ix, c]-band[ix-1, c], 1e-30)
        periods = np.diff(z)
        f = sr/np.maximum(periods, 1)
        good = (f >= lo) & (f <= hi)
        if not np.any(good):
            continue
        k = np.arange(len(z), dtype=float)
        phase = np.interp(t, z, k)
        phase[t < z[0]] = (t[t < z[0]]-z[0])/periods[0]
        phase[t > z[-1]] = k[-1]+(t[t > z[-1]]-z[-1])/periods[-1]
        cycles[:, c] = phase
        valid[:, c] = good[np.clip(np.searchsorted(z, t)-1, 0, len(good)-1)]
    return cycles, valid


def projected_amplitude(source, cycles, sr, lo):
    """Local sinusoidal least-squares amplitude, excluding silent samples.

    A centered source-cycle window estimates both quadratures. Omitting zero
    support prevents a burst boundary from diluting the amplitude estimate.
    The full-context analysis is intentional and never used by other types.
    """
    from scipy.ndimage import uniform_filter1d, maximum_filter1d
    width = 2*int(np.ceil(sr/lo))+1
    u, v = np.sin(2*np.pi*cycles), np.cos(2*np.pi*cycles)
    present = np.abs(source) > 1e-12
    def avg(a):
        return uniform_filter1d(a, width, axis=0, mode='constant')
    aa, bb, ab = avg(u*u*present), avg(v*v*present), avg(u*v*present)
    ax, bx = avg(u*source), avg(v*source)
    det = aa*bb-ab*ab
    a = np.divide(bb*ax-ab*bx, det, out=np.zeros_like(source), where=det > 1e-12)
    b = np.divide(aa*bx-ab*ax, det, out=np.zeros_like(source), where=det > 1e-12)
    support = maximum_filter1d(present.astype(float), 3, axis=0, mode='constant') > 0
    return np.minimum(np.hypot(a, b), 2*np.max(np.abs(source), axis=0))*support, support


def source_band(source, sr, lo, hi):
    """BB-07 BPF with stable two-pole prediction at finite-record boundaries.

    Zero extension can turn an out-of-band sine into an in-band transient.
    Fit each edge locally, clamp predictor poles to the unit disk and extend
    by the FIR half length. Silent edges predict silence. Only the extension
    is predicted: all original samples pass to the existing FIR unchanged.
    """
    from scipy import signal
    from mankomix.dspx.bb.lowend import band_fir
    pad=int(np.ceil(20*sr/min(lo, hi)))
    width=min(len(source), max(3, int(np.ceil(4*sr/lo))))
    def predict(edge):
        out=np.zeros((pad, source.shape[1]))
        if len(edge)<3:
            return out
        for c in range(source.shape[1]):
            u=edge[:, c]
            a=np.linalg.lstsq(np.column_stack([u[1:-1],u[:-2]]),u[2:],rcond=None)[0]
            poles=np.roots([1.,-a[0],-a[1]])
            poles/=np.maximum(1.,abs(poles))
            den=np.real(np.poly(poles))
            zi=signal.lfiltic([1.],den,[u[-1],u[-2]])
            out[:, c]=signal.lfilter([1.],den,np.zeros(pad),zi=zi)[0]
            out[:, c]=np.clip(out[:, c],-2*np.max(abs(u)),2*np.max(abs(u)))
        return out
    before=predict(source[:width][::-1])[::-1]
    after=predict(source[-width:])
    padded=np.concatenate([before,source,after])
    band, info=band_fir(padded,sr,lo,hi)
    info=dict(info, boundary_rule='stable_two_pole_prediction')
    return band[pad:pad+len(source)],info


def sub_synth(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.lowend import amplitude_envelope
    from mankomix.dspx.bb.dynamics import envelope
    from scipy import signal
    validate(p)
    info = dict(latency_samples=0, mode=p['mode'], divider_polyphonic_unreliable=True)
    if p['amount_db'] == -60 or not len(x):
        return x.copy(), sr, info
    source = np.mean(x, axis=1, keepdims=True) if p['mono'] else x
    band, fir_info = source_band(source, sr, p['lo_hz'], p['hi_hz'])
    cycles, valid = source_cycles(band, sr, p['lo_hz'], p['hi_hz'], source)
    peak, support = projected_amplitude(source, cycles, sr, p['lo_hz'])
    band_peak = amplitude_envelope(band, sr, .1, .1)
    threshold = 10**(p['threshold_db']/20)
    target = np.where(valid & (peak >= threshold) & (band_peak >= threshold), peak, 0.)
    env = envelope(target, sr, p['attack_ms'], p['release_ms'])
    # The user highcut is an upper bound. A cycle-adaptive ceiling prevents
    # a high setting from admitting the divider's third harmonic.
    input_hz = np.diff(cycles, axis=0)*sr
    cutoffs=[]
    for c in range(source.shape[1]):
        selected=input_hz[:, c][valid[1:, c] & (input_hz[:, c] > 0)]
        ceiling=.75*float(np.median(selected)) if len(selected) else p['sub_highcut_hz']
        cutoffs.append(min(p['sub_highcut_hz'], ceiling, .45*sr))
    def filter_carrier(wave):
        out=np.empty_like(wave)
        for c, cutoff in enumerate(cutoffs):
            sos=signal.ellip(4, .1, 40, cutoff, fs=sr, output='sos')
            out[:, c]=signal.sosfilt(sos, wave[:, c])
        return out
    if p['mode'] == 'divider':
        # Period continuation sustains the carrier during the envelope release.
        # A fourth-order elliptic LPF meets the harmonic limit without adding poles.
        pad = sr//2
        step = cycles[1:2]-cycles[0:1] if len(x)>1 else np.zeros_like(cycles[0:1])
        pre = cycles[0:1]+np.arange(-pad, 0)[:, None]*step
        phase = np.concatenate([pre, cycles])
        wave = np.where(np.sin(np.pi*phase) >= 0, 1., -1.)
        carrier = filter_carrier(wave)[pad:]
    else:
        # Keep BB-12 YIN, but hold the last voiced frequency through the release.
        carrier, info['voiced_samples'] = tracked_wave(band, sr, p['lo_hz'], p['hi_hz'], p['threshold_db'])
        carrier = filter_carrier(carrier)
    sub = carrier*env
    # Reject an actively present out-of-band source, while permitting silence tails.
    sub *= valid | ~support
    # Remove only a carrier-weighted finite-record residual: inactive samples
    # remain exact zero rather than receiving a record-wide DC offset.
    weight = env*(valid | ~support)
    total = np.sum(weight, axis=0)
    correction = np.divide(np.sum(sub, axis=0), total, out=np.zeros_like(total), where=total > 0)
    sub -= weight*correction
    info['source_fir'] = fir_info
    info['carrier_highcut_hz'] = cutoffs
    return x+sub*10**(p['amount_db']/20), sr, info


def _spec():
    from mankomix.dspx.bb.lowend import definition
    return definition('sub_synth', [
        _e('mode', ['divider', 'tracked'], 'divider', 'Octave division or BB-12 tracking.'),
        _f('lo_hz', 'Hz', 30, 120, 50, 'Source band lower edge.'),
        _f('hi_hz', 'Hz', 60, 250, 110, 'Source band upper edge.'),
        _f('amount_db', 'dB', -60, 6, -60, 'Added sub; -60 bypasses.'),
        _f('sub_highcut_hz', 'Hz', 30, 120, 60, 'Fourth-order elliptic carrier lowpass.'),
        _f('attack_ms', 'ms', 10, 100, 10, 'Envelope attack.'),
        _f('release_ms', 'ms', 20, 1000, 150, 'Envelope release.'),
        _f('threshold_db', 'dBFS', -80, 0, -45, 'Below-band threshold disables synthesis.'),
        _b('mono', True, 'Add the same sub to both channels.')],
        'Octave sub synthesis; divider can mistrack chords and multiple notes.', offline=True)


SPECS = [_spec()]
SPECS[0]['implemented'] = True
IMPLS = {'sub_synth': sub_synth}
CROSS_VALIDATE = {'sub_synth': validate}
