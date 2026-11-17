"""T01-04 level-independent dual-envelope transient shaping."""
from mankomix.dspx.params import _f, _b
from mankomix.dspx.bb import dynamics as D

SPECS = [{
    'type': 'transient_shaper', 'name': 'Transient shaper',
    'description': 'Difference-envelope attack and sustain control.',
    'stages': ['track', 'bus', 'master'], 'master_slot': 2, 'offline_only': False,
    'backends': ['reference'], 'implemented': True,
    'realtime': {'block_ok': False, 'latency_samples': 0, 'allocates': True},
    'params': [
        _f('attack_db', 'dB', -12, 12, 0, 'Attack gain.'),
        _f('sustain_db', 'dB', -12, 12, 0, 'Sustain gain.'),
        _f('fast_ms', 'ms', .1, 10, 1, 'Fast envelope time constant.'),
        _f('slow_ms', 'ms', 5, 100, 20, 'Slow envelope time constant.'),
        _f('sustain_release_ms', 'ms', 50, 2000, 300, 'Sustain envelope release.'),
        _f('max_gain_db', 'dB', 0, 18, 12, 'Absolute dynamic gain limit.'),
        _b('stereo_link', True, 'Maximum-linked detector.'),
        _f('output_db', 'dB', -24, 12, 0, 'Output trim.'),
    ]}]
TIME_VARYING = {'transient_shaper'}


def transient_shaper(x, sr, p, *, seed=0):
    if p['attack_db'] == 0 and p['sustain_db'] == 0:
        return D.apply_gain(x, 0, p['output_db']), sr, {'latency_samples': 0}
    gain = D.transient_gain(x, sr, p)
    return D.apply_gain(x, gain, p['output_db']), sr, {'latency_samples': 0,
            'gain_reduction': D.gr_stats(-gain)}


IMPLS = {'transient_shaper': transient_shaper}
