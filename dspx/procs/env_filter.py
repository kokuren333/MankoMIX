"""dB envelope-to-cutoff mapping using the shared TPT SVF."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e, _b
from mankomix.dspx.bb.time_creative import definition


def validate(p):
    if p['ceiling_db'] < p['threshold_db']+6:
        raise ParamError('ceiling_db must exceed threshold_db by at least 6 dB')
    if p['key_lo_hz'] and p['key_hi_hz'] and p['key_lo_hz'] >= p['key_hi_hz']:
        raise ParamError('key_lo_hz must be below key_hi_hz')


def cutoff_control(x, sr, p):
    """Return (cutoff Hz, smoothed detector dBFS), linked or per-channel."""
    from scipy import signal
    from mankomix.dspx.bb import dynamics as D
    validate(p)
    key = x.copy()
    for name, mode in [('key_lo_hz', 'highpass'), ('key_hi_hz', 'lowpass')]:
        if p[name]:
            key = signal.sosfilt(signal.butter(2, min(p[name], .45*sr), mode, fs=sr, output='sos'), key, axis=0)
    target = D.level_db(D.detector(key, sr, 'peak', stereo_link=p['stereo_link']))+p['sensitivity_db']
    # Envelope state is expressed relative to the -240 dB detector floor.
    env = D.envelope(np.maximum(target+240, 0), sr, p['attack_ms'], p['release_ms'])-240
    e = np.clip((env-p['threshold_db'])/(p['ceiling_db']-p['threshold_db']), 0, 1)
    return np.minimum(.45*sr, p['base_hz']*2**(p['range_oct']*e)), env


def env_filter(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.svf import svf
    validate(p)
    if p['mix'] == 0:
        return x.copy(), sr, {}
    cutoff, env = cutoff_control(x, sr, p)
    wet = svf(x, sr, cutoff, p['resonance_db'], p['filter'], int(p['slope_db_oct']))
    y = wet if p['mix'] == 1 else x+p['mix']*(wet-x)
    return y, sr, {'cutoff_min_hz': float(cutoff.min()) if len(x) else None,
                   'cutoff_max_hz': float(cutoff.max()) if len(x) else None}


SPECS = [definition('env_filter', [
    _f('base_hz', 'Hz', 40, 8000, 300, 'Zero-envelope cutoff.'),
    _f('range_oct', 'oct', -6, 6, 3, 'Full envelope excursion.'),
    _f('sensitivity_db', 'dB', -40, 20, 0, 'Detector gain.'),
    _f('threshold_db', 'dBFS', -80, 0, -40, 'Envelope zero reference.'),
    _f('ceiling_db', 'dBFS', -40, 0, -6, 'Envelope one reference.'),
    _f('attack_ms', 'ms', .5, 200, 10, 'Rising dB envelope time constant.'),
    _f('release_ms', 'ms', 10, 2000, 150, 'Falling dB envelope time constant.'),
    _e('filter', ['lowpass', 'bandpass', 'highpass'], 'bandpass', 'SVF output.'),
    _f('resonance_db', 'dB', 0, 24, 12, 'Resonance peak gain.'),
    _e('slope_db_oct', [12, 24], 12, 'Filter slope.'),
    _f('key_lo_hz', 'Hz', 0, 2000, 0, 'Detector highpass; zero disables.'),
    _f('key_hi_hz', 'Hz', 0, 20000, 0, 'Detector lowpass; zero disables.'),
    _b('stereo_link', True, 'Maximum-linked envelope.'),
    _f('mix', None, 0, 1, 1, 'Wet proportion.')], implemented=True)]
IMPLS = {'env_filter': env_filter}
TIME_VARYING = {'env_filter'}
CROSS_VALIDATE = {'env_filter': validate}
