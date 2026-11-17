"""Absolute-time pitch bend with exact neutral-region restoration."""
from mankomix.dspx.params import _f, _e, _b


def pitch_curve(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.pitchtime import bend
    if not p['bend']:
        return x.copy(), sr, {'latency_samples': 0}
    wet = bend(x, sr, p['bend'], p['interp'], p['glide_ms'], p['quality'],
               p['formant'], p['grain_ms'])
    if p['harmony_db'] > -90:
        wet = wet+x*10.**(p['harmony_db']/20)
    return wet, sr, {'quality': p['quality'],
                     'latency_samples': round(.04*sr) if p['quality'] == 'standard' else 0,
                     'latency_compensated': True,
                     'clock': 'full-context absolute sample grid'}


SPECS = [dict(type='pitch_curve', description='Absolute-time pitch bend.',
    stages=['track', 'bus'], master_slot=None, offline_only=False,
    backends=['reference'], implemented=True,
    realtime=dict(block_ok=False, latency_samples=0, allocates=True,
        latency_rule='Fast: 0; standard: 40 ms lookahead, internally compensated; empty: 0.'),
    params=[
        dict(id='bend', type='curve', unit=None, x_unit='s', x_min=0, x_max=36000,
             y_min=-24, y_max=24, max_points=4096, default=[], description='Absolute semitone curve.'),
        _e('interp', ['linear', 'smooth', 'step'], 'linear', 'Semitone interpolation.'),
        _f('glide_ms', 'ms', 0, 500, 0, 'Finite raised-cosine step transition duration.'),
        _e('quality', ['fast', 'standard'], 'fast', 'Pitch algorithm.'),
        _b('formant', False, 'Preserve envelope in standard quality.'),
        _f('grain_ms', 'ms', 10, 200, 40, 'Crossfade grain duration.'),
        _f('harmony_db', 'dB', -90, 6, -90, 'Dry gain; -90 disables dry addition.')])]
TIME_VARYING = {'pitch_curve'}
IMPLS = {'pitch_curve': pitch_curve}
