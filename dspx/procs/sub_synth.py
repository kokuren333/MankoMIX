"""Octave divider or BB-12 pitch-tracked sub synthesis, whole-context only.

The positive Schmitt transition toggles the divider once per source cycle.
Initial polarity is +1; hysteresis is 1e-6 full scale. Polyphonic divider
tracking is unreliable by construction. Tracked mode integrates sample-grid
frequency from absolute sample zero, keeping phase continuous across voicing.
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
        frequency = np.where(voiced, np.nan_to_num(f0)/2, 0.)
        cycles = np.r_[0., np.cumsum(frequency[:-1])/sr]
        out[:, c] = np.sin(2*np.pi*np.remainder(cycles, 1))*voiced
        voiced_count += int(np.count_nonzero(voiced))
    return out, voiced_count


def sub_synth(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.lowend import band_fir, amplitude_envelope
    from mankomix.dspx.bb import nonlinear as N
    from scipy import signal
    validate(p)
    info = dict(latency_samples=0, mode=p['mode'], divider_polyphonic_unreliable=True)
    if p['amount_db'] == -60 or not len(x):
        return x.copy(), sr, info
    source = np.mean(x, axis=1, keepdims=True) if p['mono'] else x
    band, fir_info = band_fir(source, sr, p['lo_hz'], p['hi_hz'])
    # Threshold the unsmoothed source amplitude so below-floor inputs are
    # exactly silent. The follower alone controls attack/release.
    peak = amplitude_envelope(band, sr, .1, .1)
    from mankomix.dspx.bb.dynamics import envelope
    env = envelope(np.where(peak >= 10**(p['threshold_db']/20), peak, 0.),
                   sr, p['attack_ms'], p['release_ms'])
    if p['mode'] == 'divider':
        wave = divider_wave(band)
    else:
        wave, info['voiced_samples'] = tracked_wave(band, sr, p['lo_hz'], p['hi_hz'], p['threshold_db'])
    sub = signal.sosfilt(signal.butter(4, min(p['sub_highcut_hz'], .45*sr),
                         fs=sr, output='sos'), wave*env, axis=0)
    sub = N.dc_block(sub, sr)
    info['source_fir'] = fir_info
    return x+sub*10**(p['amount_db']/20), sr, info


def _spec():
    from mankomix.dspx.bb.lowend import definition
    return definition('sub_synth', [
        _e('mode', ['divider', 'tracked'], 'divider', 'Octave division or BB-12 tracking.'),
        _f('lo_hz', 'Hz', 30, 120, 50, 'Source band lower edge.'),
        _f('hi_hz', 'Hz', 60, 250, 110, 'Source band upper edge.'),
        _f('amount_db', 'dB', -60, 6, -60, 'Added sub; -60 bypasses.'),
        _f('sub_highcut_hz', 'Hz', 30, 120, 60, 'Fourth-order generated lowpass.'),
        _f('attack_ms', 'ms', 1, 100, 10, 'Envelope attack.'),
        _f('release_ms', 'ms', 20, 1000, 150, 'Envelope release.'),
        _f('threshold_db', 'dBFS', -80, 0, -45, 'Below-band threshold disables synthesis.'),
        _b('mono', True, 'Add the same sub to both channels.')],
        'Octave sub synthesis; divider can mistrack chords and multiple notes.', offline=True)


SPECS = [_spec()]
IMPLS = {'sub_synth': sub_synth}
CROSS_VALIDATE = {'sub_synth': validate}
