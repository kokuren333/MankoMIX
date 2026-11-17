"""Parallel compression; the original compressor and saturator remain intact.

Defaults blend dry and wet at -6 dB each. Fast peak detection controls the
transient, and 17 dB makeup restores the roughly 16 dB peak compression while
lifting the decay. Parameter ranges and the legacy compressor are unchanged.
"""
import numpy as np
from scipy import signal
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e
from mankomix.dspx.bb import dynamics as D

SPECS = [{
    'type': 'parallel_comp', 'implemented': True,
    'description': 'Dry plus compressed, highpassed and optionally saturated wet return.',
    'stages': ['track', 'bus', 'master'], 'master_slot': 2,
    'offline_only': False, 'backends': ['reference'], 'channel_ok': True,
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0},
    'params': [_f(k, unit, lo, hi, default, desc) for k, unit, lo, hi, default, desc in [
        ('threshold_db', 'dBFS', -60, 0, -30, 'Wet threshold.'),
        ('ratio', ':1', 1, 30, 10, 'Wet ratio.'),
        ('knee_db', 'dB', 0, 24, 3, 'Wet knee.'),
        ('attack_ms', 'ms', .05, 300, .1, 'Wet attack tau.'),
        ('release_ms', 'ms', 5, 3000, 80, 'Wet release tau.'),
        ('rms_window_ms', 'ms', 1, 300, 5, 'Wet RMS window.'),
        ('wet_makeup_db', 'dB', -12, 36, 17, 'Wet compressor makeup.'),
        ('wet_hpf_hz', 'Hz', 0, 1000, 0, 'Wet highpass; zero disables.'),
        ('wet_drive_db', 'dB', 0, 24, 0, 'Fourfold tanh saturation; zero bypasses.'),
        ('dry_db', 'dB', -90, 12, -6, 'Dry level; -90 is exact mute.'),
        ('wet_db', 'dB', -90, 12, -6, 'Wet level; -90 is exact mute.')]]
        + [_e('detector', ['peak', 'rms'], 'peak', 'Wet detector.')]}]
TIME_VARYING = {'parallel_comp'}


def parallel_comp(x, sr, p, *, seed=0):
    if p['wet_hpf_hz'] >= .98*sr/2:
        raise ParamError('wet_hpf_hz must be below 0.98 * Nyquist')
    y = x.copy() if p['dry_db'] == 0 else (np.zeros_like(x) if p['dry_db'] <= -90 else x*10**(p['dry_db']/20))
    stats = {'latency_samples': 0, 'latency_compensated': True, 'saturation_oversample': 4 if p['wet_drive_db'] else 1}
    if p['wet_db'] > -90:
        cp = dict(p, stereo_link=True)
        gr = D.compressor_gain(x, sr, cp)
        wet = D.apply_gain(x, -gr, p['wet_makeup_db'])
        if p['wet_hpf_hz']:
            wet = signal.sosfilt(signal.butter(2, p['wet_hpf_hz'], 'highpass', fs=sr, output='sos'), wet, axis=0)
        if p['wet_drive_db']:
            from mankomix.dsp.reference.nonlinear import saturator
            wet, _, _ = saturator(wet, sr, dict(mode='tanh', drive_db=p['wet_drive_db'],
                                                oversample=4, mix=1, output_db=0))
        y += wet*10**(p['wet_db']/20)
        stats['gain_reduction'] = D.gr_stats(gr)
    return y, sr, stats


IMPLS = {'parallel_comp': parallel_comp}
