"""T01-07 acoustic gate/expander; the offline edit gate is unchanged."""
import numpy as np
from mankomix.dspx.params import _f, _b
from mankomix.dspx.bb import dynamics as D

SPECS = [{
    'type': 'gate', 'name': 'Gate / expander', 'description': 'Hysteretic acoustic downward expander.',
    'stages': ['track', 'bus', 'master'], 'master_slot': 2, 'offline_only': False,
    'backends': ['reference'], 'implemented': True,
    'realtime': {'block_ok': False, 'latency_samples': 0, 'allocates': True,
                 'latency_rule': 'round(lookahead_ms * sr / 1000); compensated offline'},
    'params': [
        _f('threshold_db', 'dBFS', -80, 0, -45, 'Opening threshold.'),
        _f('ratio', ':1', 1, 100, 4, 'Expansion ratio.'),
        _f('range_db', 'dB', -90, 0, -40, 'Maximum attenuation.'),
        _f('hysteresis_db', 'dB', 0, 12, 3, 'Opening minus closing threshold.'),
        _f('knee_db', 'dB', 0, 24, 3, 'Quadratic knee width.'),
        _f('attack_ms', 'ms', .05, 100, 1, 'Opening gain time constant.'),
        _f('hold_ms', 'ms', 0, 2000, 50, 'Hold before closure.'),
        _f('release_ms', 'ms', 5, 3000, 150, 'Closing gain time constant.'),
        _f('lookahead_ms', 'ms', 0, 20, 0, 'Signal-side delay.'),
        _f('key_lo_hz', 'Hz', 0, 2000, 0, 'Key highpass; zero disables.'),
        _f('key_hi_hz', 'Hz', 0, 20000, 0, 'Key lowpass; zero disables.'),
        _b('stereo_link', True, 'Maximum-linked detector.'),
    ]}]
TIME_VARYING = {'gate'}


def raw_gate(x, sr, p):
    """Uncompensated signal-side delay, used for latency measurement."""
    gain, states = D.gate_gain(x, sr, p)
    delay = round(p['lookahead_ms'] * sr / 1000)
    y = D.apply_gain(D.delay_audio(x, delay), gain)
    return y, sr, {'latency_samples': delay, 'latency_compensated': False,
                   'gain_reduction': D.gr_stats(-gain),
                   'state_changes': int(np.count_nonzero(np.diff(states > 0, axis=0)))}


def gate(x, sr, p, *, seed=0):
    delay = round(p['lookahead_ms'] * sr / 1000)
    padded = np.pad(x, ((0, delay), (0, 0))) if delay else x
    y, _, stats = raw_gate(padded, sr, p)
    stats['latency_compensated'] = True
    return y[delay:delay+len(x)], sr, stats


IMPLS = {'gate': gate}
