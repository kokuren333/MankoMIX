"""T01-05 floor-protected upward compression."""
import numpy as np
from mankomix.dspx.params import _f, _b, _e
from mankomix.dspx.bb import dynamics as D

SPECS = [{
    'type': 'upward_compressor', 'name': 'Upward compressor',
    'description': 'Lift quiet material above a protected noise floor.',
    'stages': ['track', 'bus', 'master'], 'master_slot': 2, 'offline_only': False,
    'backends': ['reference'], 'implemented': True,
    'realtime': {'block_ok': False, 'latency_samples': 0, 'allocates': True},
    'params': [
        _f('threshold_db', 'dBFS', -80, 0, -30, 'Upper threshold.'),
        _f('ratio', ':1', 1, 10, 2, 'Upward compression ratio.'),
        _f('max_gain_db', 'dB', 0, 24, 6, 'Maximum boost.'),
        _f('floor_db', 'dBFS', -120, -30, -60, 'Noise protection floor.'),
        _f('knee_db', 'dB', 0, 24, 6, 'Quadratic knee width.'),
        _f('attack_ms', 'ms', .05, 300, 20, 'Gain attack time constant.'),
        _f('release_ms', 'ms', 5, 3000, 200, 'Gain release time constant.'),
        _e('detector', ['peak', 'rms'], 'rms', 'Detector mode.'),
        _f('rms_window_ms', 'ms', 1, 300, 20, 'Causal RMS window.'),
        _b('stereo_link', True, 'Maximum-linked detector.'),
        _f('mix', None, 0, 1, 1, 'Wet fraction.'),
    ]}]
TIME_VARYING = {'upward_compressor'}


def upward_compressor(x, sr, p, *, seed=0):
    if p['ratio'] == 1 or p['max_gain_db'] == 0 or p['mix'] == 0:
        return x.copy(), sr, {'latency_samples': 0}
    det = D.detector(x, sr, p['detector'], p['rms_window_ms'], p['stereo_link'])
    target = D.upward_gain_db(D.level_db(det), p['threshold_db'], p['ratio'],
                             p['max_gain_db'], p['floor_db'], p['knee_db'])
    gain = D.smooth_gain(target, sr, p['attack_ms'], p['release_ms'])
    # Exact pass-through outside the active static curve, including the floor.
    gain = np.where(target == 0, 0, gain)
    wet = D.apply_gain(x, gain)
    y = x + p['mix'] * (wet-x)
    return y, sr, {'latency_samples': 0, 'gain_reduction': D.gr_stats(-gain)}


IMPLS = {'upward_compressor': upward_compressor}
