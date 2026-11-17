"""One head/tail fade on the absolute sample clock (not an edit operation)."""
import numpy as np
from mankomix.dspx.params import _e, _f
from mankomix.dspx.bb.curves import fade_shape

SHAPES = ['linear', 'equal_power', 's_curve', 'exp', 'log']
SPECS = [{
    'type': 'fade', 'implemented': True,
    'description': 'One absolute-time head and tail amplitude fade.',
    'params': [_f('in_end_s', 's', 0, 36000, 0, 'Fade-in end, zero disables.'),
               _f('out_start_s', 's', 0, 36000, 0, 'Fade-out start, zero disables.'),
               _f('out_ms', 'ms', 1, 120000, 5000, 'Fade-out duration.'),
               _e('shape_in', SHAPES, 's_curve', 'Fade-in shape.'),
               _e('shape_out', SHAPES, 'exp', 'Fade-out shape.'),
               _f('floor_db', 'dB', -144, -60, -120, 'Exponential floor before exact mute.')],
    'stages': ['track', 'bus', 'master'], 'master_slot': 5, 'offline_only': False,
    'realtime': {'block_ok': True, 'latency_samples': 0, 'allocates': True},
    'backends': ['reference'],
}]
TIME_VARYING = {'fade'}


def fade_envelope(frames, sr, p, *, start_sample=0):
    """Return amplitude by absolute integer index; later blocks need only offset."""
    n = np.arange(start_sample, start_sample+frames, dtype=np.int64)
    gain = np.ones(frames, dtype=np.float64)
    if p['in_end_s'] > 0:
        end = int(round(p['in_end_s']*sr))
        if end > 0:
            gain *= fade_shape(n/end, p['shape_in'], floor_db=p['floor_db'])
    if p['out_start_s'] > 0:
        start = int(round(p['out_start_s']*sr))
        end = int(round((p['out_start_s']+p['out_ms']/1000)*sr))
        gain *= fade_shape((end-n)/max(1, end-start), p['shape_out'], floor_db=p['floor_db'])
    return gain


def fade(x, sr, p, *, seed=0, start_sample=0):
    y = x.copy()
    if p['in_end_s'] or p['out_start_s']:
        gain = fade_envelope(len(x), sr, p, start_sample=start_sample)
        # Avoid any arithmetic outside the fades (including signed zeros).
        active = gain != 1
        y[active] *= gain[active, None]
        y[gain == 0] = 0.0
    return y, sr, {'in_end_sample': int(round(p['in_end_s']*sr)),
                   'out_start_sample': int(round(p['out_start_s']*sr)),
                   'note': 'In master slot 5, limiter gain reduction can decrease during the fade.'}


IMPLS = {'fade': fade}
