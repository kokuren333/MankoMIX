"""Offline DC mean subtraction or first-order DC blocker.

Uses scipy.signal's public filter API (BSD-3-Clause; scipy 1.18.1),
without copying third-party source. Existing health/peak measurements are reused.
"""
import math
import numpy as np
from scipy import signal
from mankomix.dspx.params import _b, _e, _f

SPECS = [{
    'type': 'dc_remove', 'implemented': True,
    'description': 'Offline DC offset removal; off is bit-identical.',
    'params': [_e('mode', ['mean', 'highpass', 'off'], 'off', 'DC removal mode.'),
               _f('cutoff_hz', 'Hz', 1, 20, 5, 'First-order highpass cutoff.'),
               _e('phase', ['minimum', 'zero'], 'zero', 'Causal or forward/backward.'),
               _b('per_channel', True, 'Estimate each channel independently.'),
               _f('threshold_db', 'dBFS', -120, -20, -80, 'Mean subtraction threshold.')],
    'stages': ['track', 'bus'], 'master_slot': None, 'offline_only': True,
    'realtime': {'block_ok': False, 'latency_samples': 0, 'allocates': True},
    'backends': ['reference'],
}]


def dc_remove(x, sr, p, *, seed=0):
    from mankomix.core.measure.vector import health
    from mankomix.core.measure.loudness import sample_peak_dbfs
    before = health(x)['dc_offset_db']
    y = x.copy()
    if len(x) and p['mode'] == 'mean':
        mean = np.mean(x, axis=0) if p['per_channel'] else np.full(x.shape[1], np.mean(x))
        mean = np.where(np.abs(mean) >= 10**(p['threshold_db']/20), mean, 0.0)
        for ch in range(x.shape[1]):
            if mean[ch] != 0:
                y[:, ch] -= mean[ch]
    elif len(x) and p['mode'] == 'highpass':
        # cutoff_hz names the final -3 dB corner. Compensate the two passes
        # in the bilinear (prewarped) domain instead of changing the default.
        cutoff = min(p['cutoff_hz'], sr*0.49)
        if p['phase'] == 'zero':
            cutoff = sr/np.pi*np.arctan(np.tan(np.pi*cutoff/sr)*np.sqrt(np.sqrt(2)-1))
        sos = signal.butter(1, cutoff, btype='highpass', fs=sr, output='sos')
        if p['per_channel']:
            source = x
        else:
            source = np.mean(x, axis=1, keepdims=True)
        if p['phase'] == 'zero':
            # Long reflection prevents an impulse's distant tail from producing
            # measurable asymmetry. Constant extensions remove constant DC too.
            padlen = min(len(x)-1, int(np.ceil(12*sr/(2*np.pi*p['cutoff_hz']))))
            filtered = signal.sosfiltfilt(sos, source, axis=0, padlen=padlen)
            # A finite reflected record can retain a small boundary-induced
            # mean. Project that residual DC out of the zero-phase result.
            filtered -= np.mean(filtered, axis=0, keepdims=True)
        else:
            filtered = signal.sosfilt(sos, source, axis=0)
        y = filtered if p['per_channel'] else x + (filtered-source)
    peak = sample_peak_dbfs(y)
    return y, sr, {'mode': p['mode'], 'dc_before_dbfs': before,
                   'dc_after_dbfs': health(y)['dc_offset_db'],
                   'peak_after_dbfs': peak if math.isfinite(peak) else None,
                   'note': 'Subtracting DC can increase the sample peak.'}


IMPLS = {'dc_remove': dc_remove}
