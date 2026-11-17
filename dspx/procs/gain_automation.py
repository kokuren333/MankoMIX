"""Full-band automation adapter for buses without a core automation reader.

This is the bus counterpart of a track fader's precomputed dB curve. It is
kept separate so band_automation's documented frequency ranges stay intact.
"""
SPECS = [{
    'type': 'gain_automation', 'implemented': True,
    'description': 'Absolute dB automation for bus gain.',
    'params': [{'id': 'gain', 'type': 'curve', 'unit': 's/dB', 'x_min': 0, 'x_max': 1e12,
                'y_min': -1e12, 'y_max': 12, 'max_points': 65536, 'default': [],
                'description': 'Absolute seconds and dB knots; empty is neutral.'}],
    'stages': ['bus'], 'master_slot': None, 'offline_only': False,
    'backends': ['reference'], 'channel_ok': True,
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0}}]
TIME_VARYING = {'gain_automation'}


def gain_automation(x, sr, p, *, seed=0, start_sample=0):
    from mankomix.dspx.bb.curves import sample_curve
    from mankomix.dspx.bb.keyed import band_gain
    y = x.copy() if not p['gain'] else band_gain(x, sr, sample_curve(p['gain'], len(x), sr, start_sample=start_sample))
    return y, sr, {'latency_samples': 0, 'points': len(p['gain'])}


IMPLS = {'gain_automation': gain_automation}
