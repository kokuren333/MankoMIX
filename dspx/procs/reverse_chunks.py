"""Play the preceding grid chunk backwards, without latency compensation."""
import numpy as np
from mankomix.dspx.params import _f, _i
from mankomix.dspx.bb.time_creative import definition, grid_params


def reverse_chunks(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.time_creative import grid, validate_grid, seam_gain, mix_active
    validate_grid(p)
    k, start, end = grid(len(x), sr, p)
    # Independent rounded predecessor boundary (works for fractional periods).
    from mankomix.dspx.bb.curves import period_ms
    dur = period_ms(p['step_ms'], note=p['step_note'], bpm=p['bpm'])*sr/1000
    prev = np.rint(p['origin_s']*sr+(k-1)*dur).astype(np.int64)
    pos = start-1-(np.arange(len(x))-start)
    valid = (k >= 1) & (pos >= prev) & (pos >= 0) & (pos < len(x))
    wet = np.zeros_like(x)
    wet[valid] = x[pos[valid]]
    wet *= seam_gain(np.arange(len(x))-start, end-start, p['fade_ms']*sr/1000)[:, None]
    selected = (k >= 0) & (k % p['every'] == 0)
    wet[~selected] = x[~selected]
    return mix_active(x, wet, p, sr), sr, {'musical_delay': 'previous chunk; deliberately uncompensated'}


SPECS = [definition('reverse_chunks', grid_params(False)+[
    _f('fade_ms', 'ms', .5, 50, 5, 'Chunk seam amplitude fade.'),
    _f('mix', None, 0, 1, 1, 'Wet proportion.'),
    _i('every', None, 1, 8, 1, 'Reverse chunks numbered 0, n, 2n, ...')], implemented=True)]
TIME_VARYING = {'reverse_chunks'}
IMPLS = {'reverse_chunks': reverse_chunks}


def validate(p):
    from mankomix.dspx.bb.time_creative import validate_grid
    validate_grid(p, resolve_tempo=False)


CROSS_VALIDATE = {'reverse_chunks': validate}
