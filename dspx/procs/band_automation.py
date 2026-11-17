"""Absolute-time dB automation applied to a Butterworth band."""
from mankomix.dspx.params import _f, _e

SPECS = [{
    'type': 'band_automation', 'implemented': True,
    'description': 'Precomputed dB automation on a Butterworth band.',
    'params': [_f('lo_hz', 'Hz', 20, 8000, 60, 'Lower band edge.'),
               _f('hi_hz', 'Hz', 60, 20000, 250, 'Upper band edge.'),
               {'id': 'gain', 'type': 'curve', 'unit': 's/dB', 'x_min': 0, 'x_max': 1e12,
                'y_min': -24, 'y_max': 12, 'max_points': 65536, 'default': [],
                'description': 'Absolute seconds and dB knots; empty is neutral.'},
               _e('slope_db_oct', [12, 24], 12, 'Slope at each band edge.', 'dB/oct')],
    'stages': ['track', 'bus'], 'master_slot': None, 'offline_only': False,
    'backends': ['reference'], 'channel_ok': True,
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0}}]
TIME_VARYING = {'band_automation'}


def check(params):
    from mankomix.dspx.bb.keyed import validate_band
    validate_band(params['lo_hz'], params['hi_hz'])


def band_automation(x, sr, p, *, seed=0, start_sample=0):
    """Render from the absolute clock; filtered excerpts replay full context."""
    from mankomix.dspx.bb.curves import sample_curve
    from mankomix.dspx.bb.keyed import band_gain, validate_band
    validate_band(p['lo_hz'], p['hi_hz'], sr)
    gain = sample_curve(p['gain'], len(x), sr, start_sample=start_sample) if p['gain'] else None
    y = x.copy() if gain is None else band_gain(x, sr, gain, p['lo_hz'], p['hi_hz'], p['slope_db_oct'])
    return y, sr, {'latency_samples': 0, 'band_hz': [p['lo_hz'], p['hi_hz']], 'points': len(p['gain'])}


CROSS_VALIDATE = {'band_automation': check}
IMPLS = {'band_automation': band_automation}
