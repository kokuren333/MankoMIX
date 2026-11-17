"""T01-06 a single detector and combined downward/upward gain curve."""
import numpy as np
from mankomix.dspx.params import _f, _b
from mankomix.dspx.bb import dynamics as D

SPECS = [{
    'type': 'leveler', 'name': 'Bilateral leveler',
    'description': 'Combined downward and floor-protected upward compression.',
    'stages': ['track', 'bus', 'master'], 'master_slot': 2, 'offline_only': False,
    'backends': ['reference'], 'implemented': True,
    'realtime': {'block_ok': False, 'latency_samples': 0, 'allocates': True},
    'params': [
        _f('high_threshold_db', 'dBFS', -60, 0, -14, 'Downward threshold.'),
        _f('down_ratio', ':1', 1, 30, 3, 'Downward ratio.'),
        _f('low_threshold_db', 'dBFS', -80, 0, -34, 'Upward threshold; at least 3 dB below high.'),
        _f('up_ratio', ':1', 1, 10, 2, 'Upward ratio.'),
        _f('max_gain_db', 'dB', 0, 24, 6, 'Maximum boost.'),
        _f('floor_db', 'dBFS', -120, -30, -60, 'Noise protection floor.'),
        _f('knee_db', 'dB', 0, 24, 6, 'Quadratic knee width.'),
        _f('attack_ms', 'ms', .05, 300, 15, 'Gain attack time constant.'),
        _f('release_ms', 'ms', 5, 3000, 250, 'Gain release time constant.'),
        _f('rms_window_ms', 'ms', 1, 300, 30, 'Causal RMS window.'),
        _b('stereo_link', True, 'Maximum-linked detector.'),
        _f('output_db', 'dB', -24, 12, 0, 'Output trim.'),
    ]}]
TIME_VARYING = {'leveler'}


def leveler(x, sr, p, *, seed=0):
    # Relationship validation is here because the W0 registry has no validator hook.
    if p['low_threshold_db'] > p['high_threshold_db']-3:
        from mankomix.dsp.errors import ParamError
        raise ParamError('low_threshold_db must be at least 3 dB below high_threshold_db')
    if p['up_ratio'] == 1 and p['down_ratio'] == 1:
        return D.apply_gain(x, 0, p['output_db']), sr, {'latency_samples': 0}
    det = D.detector(x, sr, 'rms', p['rms_window_ms'], p['stereo_link'])
    target = D.bilateral_gain_db(D.level_db(det), p['high_threshold_db'], p['down_ratio'],
                    p['low_threshold_db'], p['up_ratio'], p['max_gain_db'], p['floor_db'], p['knee_db'])
    gain = D.smooth_gain(target, sr, p['attack_ms'], p['release_ms'])
    gain = np.where(target == 0, 0, gain)
    return D.apply_gain(x, gain, p['output_db']), sr, {'latency_samples': 0,
            'gain_reduction': D.gr_stats(-gain)}


IMPLS = {'leveler': leveler}
